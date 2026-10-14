"""
A small SMTP relay for the development tests (Documentation/adr/0004-e-mail.md, decision 9): enough of RFC 5321 to
receive what the portal sends, with the options a real relay has.

    relay = FakeRelay(starttls=True, credentials=("portal", "secret"))   # or implicit_tls=True, or neither
    relay.start()
    ... relay.port, relay.ca_file (the throwaway certificate to trust), relay.messages (email.message objects)
    relay.reply["RCPT"] = (450, "4.2.0 Mailbox busy")                     # refusals on demand
    relay.stop()

It offers STARTTLS only when asked, authentication (PLAIN and LOGIN) only when credentials are given — and then
only after STARTTLS, as real relays do — and keeps every accepted message. The certificate is made with the
openssl command for 127.0.0.1 and localhost, valid for a day.
"""
import base64
import os
import socket
import ssl
import subprocess
import tempfile
import threading
from email import message_from_bytes, policy


def make_certificate(folder: str) -> tuple[str, str]:
    """(certificate, key) for localhost and 127.0.0.1 in a folder."""
    cert, key = os.path.join(folder, "relay.crt"), os.path.join(folder, "relay.key")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
                    "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1", "-keyout", key, "-out", cert],
                   check=True, capture_output=True)
    return cert, key


class _Session:
    def __init__(self, relay, sock: socket.socket):
        self.relay, self.sock, self.buffer = relay, sock, b""
        self.tls = isinstance(sock, ssl.SSLSocket)
        self.authenticated = False
        self.sender, self.recipients = None, []

    def send(self, code: int, text: str, more: list[str] = ()) -> None:
        if more:                                       # a multi-line answer: "250-first", …, "250 last"
            lines = [f"{code}-{text}"] + [f"{code}-{line}" for line in more[:-1]] + [f"{code} {more[-1]}"]
        else:
            lines = [f"{code} {text}"]
        self.sock.sendall(("\r\n".join(lines) + "\r\n").encode())

    def line(self) -> bytes | None:
        while b"\r\n" not in self.buffer:
            chunk = self.sock.recv(65536)
            if not chunk:
                return None
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\r\n", 1)
        return line

    def data(self) -> bytes | None:
        while b"\r\n.\r\n" not in self.buffer:
            chunk = self.sock.recv(65536)
            if not chunk:
                return None
            self.buffer += chunk
        body, self.buffer = self.buffer.split(b"\r\n.\r\n", 1)
        return b"\n".join(line[1:] if line.startswith(b".") else line for line in body.split(b"\r\n"))

    def refusal(self, verb: str) -> bool:
        reply = self.relay.reply.get(verb)
        if reply:
            self.send(*reply)
            return True
        return False

    def run(self) -> None:
        self.relay.connections += 1
        self.send(220, "fake.relay ESMTP ready")
        while True:
            raw = self.line()
            if raw is None:
                return
            self.relay.commands.append(raw.decode(errors="replace").split(" ")[0].upper())
            verb, _, argument = raw.decode(errors="replace").partition(" ")
            verb = verb.upper()
            if verb in ("EHLO", "HELO"):
                offers = ["SIZE 10485760", "8BITMIME"]
                if self.relay.starttls and not self.tls:
                    offers.append("STARTTLS")
                if self.relay.credentials and (self.tls or not self.relay.starttls):
                    offers.append("AUTH PLAIN LOGIN")
                self.send(250, "fake.relay", offers)
            elif verb == "STARTTLS" and self.relay.starttls and not self.tls:
                self.send(220, "2.0.0 Ready to start TLS")
                self.sock = self.relay.context.wrap_socket(self.sock, server_side=True)
                self.tls, self.buffer = True, b""
            elif verb == "AUTH":
                self.auth(argument)
            elif verb == "MAIL":
                if self.relay.credentials and not self.authenticated:
                    self.send(530, "5.7.0 Authentication required")
                elif not self.refusal("MAIL"):
                    self.sender, self.recipients = argument, []
                    self.send(250, "2.1.0 OK")
            elif verb == "RCPT":
                if not self.refusal("RCPT"):
                    self.recipients.append(argument)
                    self.send(250, "2.1.5 OK")
            elif verb == "DATA":
                if not self.recipients:
                    self.send(503, "5.5.1 No recipients")
                    continue
                self.send(354, "End data with <CR><LF>.<CR><LF>")
                body = self.data()
                if body is None:
                    return
                if not self.refusal("DATA"):
                    message = message_from_bytes(body, policy=policy.default)
                    self.relay.messages.append(message)
                    self.relay.envelopes.append((self.sender, list(self.recipients), self.tls))
                    self.send(250, f"2.0.0 OK queued as {len(self.relay.messages)}")
            elif verb in ("RSET", "NOOP"):
                self.send(250, "2.0.0 OK")
            elif verb == "QUIT":
                self.send(221, "2.0.0 Bye")
                return
            else:
                self.send(502, "5.5.2 Command not implemented")

    def auth(self, argument: str) -> None:
        mechanism, _, initial = argument.partition(" ")
        if not self.relay.credentials or (self.relay.starttls and not self.tls):
            self.send(503, "5.5.1 AUTH not available")
            return
        if mechanism.upper() == "PLAIN":
            if not initial:
                self.send(334, "")
                initial = (self.line() or b"").decode()
            try:
                _, user, password = base64.b64decode(initial).decode().split("\0")
            except ValueError:
                self.send(501, "5.5.2 Bad PLAIN")
                return
        elif mechanism.upper() == "LOGIN":
            self.send(334, base64.b64encode(b"Username:").decode())
            user = base64.b64decode(self.line() or b"").decode()
            self.send(334, base64.b64encode(b"Password:").decode())
            password = base64.b64decode(self.line() or b"").decode()
        else:
            self.send(504, "5.5.4 Mechanism not supported")
            return
        if (user, password) == self.relay.credentials:
            self.authenticated = True
            self.send(235, "2.7.0 Authentication successful")
        else:
            self.send(535, "5.7.8 Authentication credentials invalid")


class FakeRelay:
    """An SMTP relay on 127.0.0.1 and a free port, in threads of the test program."""

    def __init__(self, starttls: bool = False, implicit_tls: bool = False, credentials: tuple | None = None):
        self.starttls, self.implicit_tls, self.credentials = starttls, implicit_tls, credentials
        self.messages, self.envelopes, self.commands = [], [], []
        self.reply: dict[str, tuple[int, str]] = {}
        self.connections = 0
        self.folder = tempfile.mkdtemp()
        self.ca_file, key = make_certificate(self.folder)
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(self.ca_file, key)
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self._stopped = False

    def start(self) -> "FakeRelay":
        self.server.listen(8)
        threading.Thread(target=self._accept, daemon=True).start()
        return self

    def _accept(self) -> None:
        while not self._stopped:
            try:
                sock, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(sock,), daemon=True).start()

    def _serve(self, sock: socket.socket) -> None:
        try:
            if self.implicit_tls:
                sock = self.context.wrap_socket(sock, server_side=True)
            _Session(self, sock).run()
        except (OSError, ssl.SSLError):
            pass
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def stop(self) -> None:
        self._stopped = True
        self.server.close()

    def clear(self) -> None:
        self.messages.clear(), self.envelopes.clear(), self.commands.clear(), self.reply.clear()
