"""
Secrets the portal must use again, sealed before they are stored (Documentation/adr/0044-encrypted-backups-and-sealed-
secrets.md): the single sign-on client secrets, which the portal sends back to the provider and so cannot hash.

A sealed value is {"sealed": 1, "kid": <key id>, "nonce": <base64>, "data": <base64>}: AES-256-GCM under the data key,
with the value's place (for instance "sso:t-acme:clientSecret") as associated data, so that a sealed value copied to
another place does not open.

The data key is PORTAL_DATA_KEY (the installer writes one to .env; every replica must share it), stretched with
HKDF-SHA256; without it, a random key created once in the configuration volume (data.key, like the fallback session
key). Values sealed with another known key — PORTAL_DATA_KEY_PREVIOUS, or data.key once PORTAL_DATA_KEY is set — still
open; needs_resealing() tells the portal to seal them again with the current key.
"""
import base64
import hashlib
import os
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VARIABLE = "PORTAL_DATA_KEY"
PREVIOUS = "PORTAL_DATA_KEY_PREVIOUS"
FILE_NAME = "data.key"
INFO = b"gs1-resolver sealed values v1"


def config_dir() -> str:
    return os.environ.get("PORTAL_CONFIG_DIR", "/app/config")


def key_file(path: str, variable: str) -> str:
    """The text of a key file, created with a random key when it is not there yet.

    Several processes start at once (gunicorn's workers, replicas), so the file appears complete or not at all: the
    key is written to a file of this process's own and then linked to the final name, which fails for every process
    but the first. Reading a file another process had created but not yet written would give an empty key."""
    if not os.path.exists(path):
        draft = f"{path}.{os.getpid()}.{secrets.token_hex(4)}"
        try:
            fd = os.open(draft, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(secrets.token_hex(32))
            try:
                os.link(draft, path)
            except FileExistsError:
                pass                                   # another process was first: use its key
            finally:
                os.unlink(draft)
        except OSError as exc:
            raise RuntimeError(f"Cannot create {path} ({exc}). "
                               "/app/config must be writable by uid 10001 (the portal-config volume).") from exc
    with open(path, encoding="utf-8") as fh:
        key = fh.read().strip()
    if not key:
        raise RuntimeError(f"{path} is empty: delete it (a new key is made at the next start) "
                           f"or set {variable} in .env.")
    return key


def _derive(text: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=INFO).derive(text.encode())


def key_id(key: bytes) -> str:
    """A short name of a key, stored with each value it seals (never the key itself)."""
    return hashlib.sha256(b"kid:" + key).hexdigest()[:16]


def keys() -> list[bytes]:
    """The current key first, then the earlier ones that may still open a value."""
    path = os.path.join(config_dir(), FILE_NAME)
    current = os.environ.get(VARIABLE, "").strip()
    found = [_derive(current)] if current else [_derive(key_file(path, VARIABLE))]
    previous = os.environ.get(PREVIOUS, "").strip()
    if previous:
        found.append(_derive(previous))
    if current and os.path.exists(path):
        try:
            found.append(_derive(key_file(path, VARIABLE)))
        except RuntimeError:
            pass
    unique = []
    for key in found:
        if key not in unique:
            unique.append(key)
    return unique


def seal(text: str, place: str) -> dict:
    key = keys()[0]
    nonce = os.urandom(12)
    data = AESGCM(key).encrypt(nonce, text.encode(), place.encode())
    return {"sealed": 1, "kid": key_id(key), "nonce": base64.b64encode(nonce).decode(),
            "data": base64.b64encode(data).decode()}


def is_sealed(value) -> bool:
    return isinstance(value, dict) and value.get("sealed") == 1


def open_value(value, place: str) -> str | None:
    """The text of a sealed value (a text stored before sealing is returned as it is); None when no known key opens
    it, or it was sealed for another place, or it was changed."""
    if isinstance(value, str):
        return value
    if not is_sealed(value):
        return None
    try:
        nonce, data = base64.b64decode(value["nonce"]), base64.b64decode(value["data"])
    except (KeyError, TypeError, ValueError):
        return None
    candidates = sorted(keys(), key=lambda k: key_id(k) != value.get("kid"))   # the named key first
    for key in candidates:
        try:
            return AESGCM(key).decrypt(nonce, data, place.encode()).decode()
        except (InvalidTag, ValueError):
            continue
    return None


def needs_resealing(value) -> bool:
    """Whether a stored value should be sealed again with the current key: a text from before sealing, or a value
    sealed with an earlier key."""
    if isinstance(value, str):
        return bool(value)
    return is_sealed(value) and value.get("kid") != key_id(keys()[0])
