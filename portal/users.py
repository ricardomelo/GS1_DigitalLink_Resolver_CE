"""
Portal user store: a JSON file mapping username → password hash (werkzeug format).

Writes are atomic (temporary file + rename) and serialised with an advisory lock, so the
portal (password changes) and create_user.py can safely touch the file at the same time.
The file is re-read on every lookup, so users added from the command line take effect at once.
"""
import fcntl
import hashlib
import hmac
import json
import os
from contextlib import contextmanager

from werkzeug.security import check_password_hash, generate_password_hash

USERS_FILE = os.environ.get("PORTAL_USERS_FILE", "/app/config/users.json")
MIN_PASSWORD_LENGTH = 12
# Hash of a random password, checked when the username does not exist so that response
# times do not reveal which usernames are valid.
_DUMMY_HASH = generate_password_hash(os.urandom(16).hex())


class StoreNotWritable(Exception):
    """The users file (or its directory) cannot be written by the portal process."""


def load() -> dict[str, str]:
    try:
        with open(USERS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def verify(username: str, password: str) -> bool:
    stored = load().get(username or "")
    if not stored:
        check_password_hash(_DUMMY_HASH, password or "")
        return False
    return check_password_hash(stored, password or "")


def fingerprint(username: str) -> str | None:
    """Short digest of the user's current hash. Stored in the session so that changing the
    password (or removing the user) invalidates every other open session."""
    stored = load().get(username or "")
    return hashlib.sha256(stored.encode()).hexdigest()[:16] if stored else None


def fingerprint_matches(username: str, value: str | None) -> bool:
    current = fingerprint(username)
    return bool(current and value) and hmac.compare_digest(current, value)


@contextmanager
def _locked():
    lock_path = USERS_FILE + ".lock"
    try:
        fh = open(lock_path, "a")
    except OSError as exc:
        raise StoreNotWritable(str(exc)) from exc
    with fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _write(users: dict[str, str]) -> None:
    tmp = USERS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(users, fh, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, USERS_FILE)
    except OSError as exc:
        raise StoreNotWritable(str(exc)) from exc


def set_password(username: str, password: str) -> None:
    with _locked():
        users = load()
        users[username] = generate_password_hash(password)
        _write(users)


def remove(username: str) -> None:
    with _locked():
        users = load()
        users.pop(username, None)
        _write(users)


def is_writable() -> bool:
    directory = os.path.dirname(USERS_FILE) or "."
    if os.path.exists(USERS_FILE):
        return os.access(USERS_FILE, os.W_OK) and os.access(directory, os.W_OK)
    return os.access(directory, os.W_OK)
