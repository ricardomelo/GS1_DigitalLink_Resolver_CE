"""
Outgoing e-mail of the portal: SMTP submission to a relay the operator chooses
(Documentation/adr/0004-e-mail.md, section 3.1).

Settings, read from the environment at every call (the development tests change them):
  PORTAL_MAIL_HOST              the relay; empty: mail is off and the portal behaves as before item 3.1
  PORTAL_MAIL_PORT              default 587 (465 with "tls", 25 with "none")
  PORTAL_MAIL_SECURITY          starttls (default) | tls | none
  PORTAL_MAIL_USERNAME, _PASSWORD
                                the relay's credentials; never with "none" (they would travel in clear)
  PORTAL_MAIL_FROM              the sender, "Name <address>" or an address (required)
  PORTAL_MAIL_REPLY_TO          optional answer address
  PORTAL_MAIL_CA_FILE           an extra certificate authority (PEM) for a relay signed by a private one
  PORTAL_MAIL_TIMEOUT           seconds for each step of the conversation with the relay, default 20

Every message is sent over a connection of its own; the relay's certificate is always verified. Errors are
MailError, temporary (no connection, a timeout, a 4xx answer: try again later) or permanent (5xx, a refused
certificate, a relay without STARTTLS: trying again will not help).

The operator's check, in the portal-service container:
  python mail.py test someone@example.org
"""
import logging
import os
import smtplib
import socket
import ssl
import sys
from datetime import datetime, timezone
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid, parseaddr

log = logging.getLogger("portal.mail")

SECURITY_PORTS = {"starttls": 587, "tls": 465, "none": 25}
_warned: set[str] = set()


class MailError(Exception):
    """A message the relay did not take: temporary (try again later) or not."""

    def __init__(self, text: str, temporary: bool):
        super().__init__(text)
        self.temporary = temporary


def settings() -> dict:
    """The mail settings of the environment, tidied."""
    env = os.environ.get
    security = (env("PORTAL_MAIL_SECURITY", "") or "starttls").strip().lower()
    port_text = (env("PORTAL_MAIL_PORT", "") or "").strip()
    return {
        "host": (env("PORTAL_MAIL_HOST", "") or "").strip(),
        "security": security,
        "port": int(port_text) if port_text.isdigit() else SECURITY_PORTS.get(security, 587),
        "username": (env("PORTAL_MAIL_USERNAME", "") or "").strip(),
        "password": env("PORTAL_MAIL_PASSWORD", "") or "",
        "sender": (env("PORTAL_MAIL_FROM", "") or "").strip(),
        "reply_to": (env("PORTAL_MAIL_REPLY_TO", "") or "").strip(),
        "ca_file": (env("PORTAL_MAIL_CA_FILE", "") or "").strip(),
        "timeout": float((env("PORTAL_MAIL_TIMEOUT", "") or "20").strip() or 20),
    }


def problems(conf: dict | None = None) -> list[str]:
    """What is wrong with settings that name a relay (empty: they are usable)."""
    conf = conf or settings()
    found = []
    if conf["security"] not in SECURITY_PORTS:
        found.append(f"PORTAL_MAIL_SECURITY={conf['security']!r} is not starttls, tls or none")
    if not conf["sender"] or "@" not in parseaddr(conf["sender"])[1]:
        found.append("PORTAL_MAIL_FROM is not set to an address")
    if conf["username"] and not conf["password"]:
        found.append("PORTAL_MAIL_USERNAME is set without PORTAL_MAIL_PASSWORD")
    if conf["security"] == "none" and (conf["username"] or conf["password"]):
        found.append("PORTAL_MAIL_SECURITY=none cannot be used with credentials (they would travel in clear)")
    if conf["ca_file"] and not os.path.isfile(conf["ca_file"]):
        found.append(f"PORTAL_MAIL_CA_FILE={conf['ca_file']} does not exist")
    if not 0 < conf["port"] < 65536:
        found.append(f"PORTAL_MAIL_PORT={conf['port']} is not a port")
    return found


def enabled() -> bool:
    """Whether mail is on: a relay is named and its settings are usable (otherwise the error is logged once)."""
    conf = settings()
    if not conf["host"]:
        return False
    found = problems(conf)
    for text in found:
        if text not in _warned:
            _warned.add(text)
            log.error("E-mail is off: %s.", text)
    return not found


def _sender_domain(sender: str) -> str:
    address = parseaddr(sender)[1]
    return address.rsplit("@", 1)[-1] if "@" in address else "localhost"


def message(to: str, subject: str, text: str, html: str | None = None) -> EmailMessage:
    """A message from the configured sender: plain text with an optional HTML alternative, marked as
    automatic (RFC 3834) so that out-of-office replies are not sent back."""
    conf = settings()
    msg = EmailMessage()
    msg["From"] = conf["sender"]
    msg["To"] = to
    if conf["reply_to"]:
        msg["Reply-To"] = conf["reply_to"]
    msg["Subject"] = subject
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    msg["Message-ID"] = make_msgid(domain=_sender_domain(conf["sender"]))
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _context(conf: dict) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if conf["ca_file"]:
        context.load_verify_locations(cafile=conf["ca_file"])
    return context


def _local_name() -> str:
    """The name the portal gives itself in EHLO: the installation's domain when known."""
    return (os.environ.get("FQDN", "") or "").strip() or socket.getfqdn()


def send(msg: EmailMessage) -> str:
    """Sends one message through the relay; returns the relay's answer to the message (e.g. "250 2.0.0 OK
    queued as …"). Raises MailError."""
    conf = settings()
    found = problems(conf) if conf["host"] else ["PORTAL_MAIL_HOST is not set"]
    if found:
        raise MailError("; ".join(found), temporary=False)
    smtp = None
    try:
        if conf["security"] == "tls":
            smtp = smtplib.SMTP_SSL(conf["host"], conf["port"], local_hostname=_local_name(),
                                    timeout=conf["timeout"], context=_context(conf))
        else:
            smtp = smtplib.SMTP(conf["host"], conf["port"], local_hostname=_local_name(), timeout=conf["timeout"])
        smtp.ehlo()
        if conf["security"] == "starttls":
            if not smtp.has_extn("starttls"):
                raise MailError("the relay does not offer STARTTLS", temporary=False)
            smtp.starttls(context=_context(conf))
            smtp.ehlo()
        if conf["username"]:
            smtp.login(conf["username"], conf["password"])
        refused = smtp.send_message(msg)
        if refused:                                   # some recipients refused (we send to one)
            code, text = next(iter(refused.values()))
            raise MailError(f"{code} {text.decode(errors='replace') if isinstance(text, bytes) else text}",
                            temporary=400 <= code < 500)
        return "accepted"                              # the relay answered 250 to the end of the message
    except MailError:
        raise
    except smtplib.SMTPRecipientsRefused as exc:
        code, text = next(iter(exc.recipients.values()))
        raise MailError(f"recipient refused: {code} {_text(text)}", temporary=400 <= code < 500) from None
    except smtplib.SMTPResponseException as exc:
        raise MailError(f"{exc.smtp_code} {_text(exc.smtp_error)}", temporary=400 <= exc.smtp_code < 500) from None
    except ssl.SSLCertVerificationError as exc:
        raise MailError(f"the relay's certificate was refused: {exc.verify_message}", temporary=False) from None
    except (smtplib.SMTPException, OSError) as exc:     # no connection, a timeout, a dropped connection
        raise MailError(f"{type(exc).__name__}: {exc}", temporary=True) from None
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except (smtplib.SMTPException, OSError):
                pass


def _text(value) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else str(value)


def addressee(address: str, name: str = "") -> str:
    """An address for the To header (the user name as display name when given)."""
    if not name:
        return address
    local, _, domain = address.rpartition("@")
    return str(Address(display_name=name, username=local, domain=domain))


def main(argv: list[str]) -> int:
    """python mail.py test <address>: sends a test message at once and prints the outcome."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(argv) != 3 or argv[1] != "test" or "@" not in argv[2]:
        print("Usage: python mail.py test <address>", file=sys.stderr)
        return 2
    import mailtexts
    conf = settings()
    if not conf["host"]:
        print("E-mail is off: PORTAL_MAIL_HOST is not set (see .env.example).", file=sys.stderr)
        return 1
    for text in problems(conf):
        print(f"Setting problem: {text}.", file=sys.stderr)
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    lang = mailtexts.language(os.environ.get("LANG", "").split(".")[0].replace("_", "-"))
    subject, text, html = mailtexts.compose("test", lang, when=when,
                                            operator=os.environ.get("RESOLVER_ORG_NAME", ""),
                                            portal=_portal_address())
    print(f"Relay {conf['host']}:{conf['port']} ({conf['security']}), from {conf['sender']}, to {argv[2]} …")
    try:
        answer = send(message(argv[2], subject, text, html))
    except MailError as exc:
        print(f"Not sent ({'temporary' if exc.temporary else 'permanent'}): {exc}", file=sys.stderr)
        return 1
    print(f"Sent: the relay {answer} the message. Check the mailbox (and its spam folder).")
    return 0


def _portal_address() -> str:
    """The portal's public address (as app.py works it out), for the messages' signature."""
    base = (os.environ.get("PORTAL_ORIGIN", "") or os.environ.get("RESOLVER_PUBLIC_URL", "")).strip()
    if not base and (os.environ.get("FQDN", "") or "").strip():
        base = "https://" + os.environ["FQDN"].strip()
    return base.rstrip("/") + "/portal/"


if __name__ == "__main__":
    sys.exit(main(sys.argv))
