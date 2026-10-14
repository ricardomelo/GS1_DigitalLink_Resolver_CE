"""
A stand-in OpenID Connect provider for the tests of single sign-on (Documentation/adr/0012-single-sign-on.md): the
discovery document, the keys (RS256), an authorization endpoint that answers at once for the person the test chose
(no login form), and a token endpoint that checks the client's secret and the PKCE verifier. What the next ID token
says, and how the provider misbehaves, is set by the test in NEXT.

    provider = FakeProvider(port)               # serves http://127.0.0.1:<port>
    provider.NEXT.update(email="ana@acme.example")
"""
import base64
import hashlib
import threading
import time
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import Flask, jsonify, redirect, request
from werkzeug.serving import make_server


def _new_key(kid: str):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    public.update(kid=kid, use="sig", alg="RS256")
    return private, public


class FakeProvider:
    def __init__(self, port: int, client_id: str = "portal-client", client_secret: str = "s3cret-value"):
        self.issuer = f"http://127.0.0.1:{port}"
        self.client_id, self.client_secret = client_id, client_secret
        self.keys = [_new_key("key-1")]
        self.codes: dict[str, dict] = {}
        self.requests: list[dict] = []
        self.NEXT: dict = {}
        self.reset()
        app = Flask("fake-oidc")
        app.add_url_rule("/.well-known/openid-configuration", "discovery", self.discovery)
        app.add_url_rule("/jwks", "jwks", self.jwks)
        app.add_url_rule("/authorize", "authorize", self.authorize)
        app.add_url_rule("/token", "token", self.token, methods=["POST"])
        threading.Thread(target=make_server("127.0.0.1", port, app, threaded=True).serve_forever, daemon=True).start()

    def reset(self):
        """The next answer: a good ID token for NEXT["email"]."""
        self.NEXT.clear()
        self.NEXT.update(email=None, email_verified=True, aud=None, iss=None, nonce=None, exp=600, alg="RS256",
                         key=None, error=None, token_status=200, no_id_token=False, extra={})

    def rotate(self) -> None:
        """A new signing key (the provider's keys now list both); the next token is signed with it."""
        self.keys.append(_new_key(f"key-{len(self.keys) + 1}"))

    # -------------------------------------------------------------------------------------------- endpoints
    def discovery(self):
        return jsonify(issuer=self.NEXT.get("discovery_issuer") or self.issuer,
                       authorization_endpoint=self.issuer + "/authorize", token_endpoint=self.issuer + "/token",
                       jwks_uri=self.issuer + "/jwks", response_types_supported=["code"],
                       id_token_signing_alg_values_supported=["RS256"])

    def jwks(self):
        return jsonify(keys=[public for _, public in self.keys])

    def authorize(self):
        args = request.args.to_dict()
        self.requests.append({"endpoint": "authorize", **args})
        target = args["redirect_uri"]
        if self.NEXT["error"]:
            return redirect(target + "?" + urlencode({"error": self.NEXT["error"], "state": args.get("state", "")}))
        code = base64.urlsafe_b64encode(hashlib.sha256(str(time.time_ns()).encode()).digest()).decode()[:30]
        self.codes[code] = {"args": args, "next": dict(self.NEXT)}
        return redirect(target + "?" + urlencode({"code": code, "state": args.get("state", "")}))

    def token(self):
        form = request.form.to_dict()
        self.requests.append({"endpoint": "token", **form})
        grant = self.codes.pop(form.get("code", ""), None)
        if not grant or form.get("client_id") != self.client_id or form.get("client_secret") != self.client_secret \
                or form.get("redirect_uri") != grant["args"]["redirect_uri"]:
            return jsonify(error="invalid_grant"), 400
        verifier = form.get("code_verifier", "")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if challenge != grant["args"].get("code_challenge"):
            return jsonify(error="invalid_grant", error_description="PKCE"), 400
        wanted = grant["next"]
        if wanted["token_status"] != 200:
            return jsonify(error="server_error"), wanted["token_status"]
        if wanted["no_id_token"]:
            return jsonify(access_token="x", token_type="Bearer")
        now = int(time.time())
        claims = {"iss": wanted["iss"] or self.issuer, "aud": wanted["aud"] or self.client_id, "sub": "user-1",
                  "iat": now, "exp": now + wanted["exp"], "nonce": wanted["nonce"] or grant["args"].get("nonce"),
                  "email": wanted["email"], "email_verified": wanted["email_verified"], **wanted["extra"]}
        claims = {k: v for k, v in claims.items() if v is not None}
        private, public = wanted["key"] or self.keys[-1]
        if wanted["alg"] == "HS256":
            token = jwt.encode(claims, "shared", algorithm="HS256", headers={"kid": public["kid"]})
        else:
            token = jwt.encode(claims, private, algorithm=wanted["alg"], headers={"kid": public["kid"]})
        return jsonify(access_token="x", token_type="Bearer", id_token=token)
