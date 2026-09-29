"""
Portal user store: a JSON file mapping username → account.

    {"maria": {"hash": "<werkzeug hash>", "role": "editor", "prefixes": ["7891234"],
               "disabled": false, "mustChange": false, "created": "…", "lastLogin": "…"}}

Roles, from least to most: reader (consults and exports), editor (also changes records), admin (also
manages users and sees the audit trail). "prefixes" limits an account to identifiers of those GS1
Company Prefixes (empty: every identifier). "mustChange" asks for a new password at the next sign-in
(temporary passwords). Files written before roles existed ({"name": "<hash>"}) are read as admins and
converted on the next write.

Writes are atomic (temporary file + rename) and serialised with an advisory lock, so the portal and
create_user.py can safely touch the file at the same time. The file is re-read on every lookup, so
changes made from the command line take effect at once.
"""
import fcntl
import hashlib
import hmac
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

USERS_FILE = os.environ.get("PORTAL_USERS_FILE", "/app/config/users.json")
MIN_PASSWORD_LENGTH = 12
ROLES = ("reader", "editor", "admin")
USERNAME = re.compile(r"^[A-Za-z0-9._@\-]{3,64}$")
PREFIX = re.compile(r"^\d{4,12}$")
# Hash of a random password, checked when the username does not exist so that response
# times do not reveal which usernames are valid.
_DUMMY_HASH = generate_password_hash(os.urandom(16).hex())


class StoreNotWritable(Exception):
    """The users file (or its directory) cannot be written by the portal process."""


class UserError(Exception):
    """A request the store refuses; code is a message code for the browser."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = params


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _account(value) -> dict:
    if isinstance(value, str):                     # before roles: every user was an administrator
        value = {"hash": value, "role": "admin"}
    account = {"hash": "", "role": "admin", "prefixes": [], "disabled": False, "mustChange": False,
               "created": None, "lastLogin": None}
    account.update(value)
    if account["role"] not in ROLES:
        account["role"] = "reader"
    return account


def load() -> dict[str, dict]:
    try:
        with open(USERS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    return {name: _account(value) for name, value in data.items()}


def get(username: str) -> dict | None:
    return load().get(username or "")


def verify(username: str, password: str) -> bool:
    account = get(username)
    if not account or not account["hash"]:
        check_password_hash(_DUMMY_HASH, password or "")
        return False
    ok = check_password_hash(account["hash"], password or "")
    return ok and not account["disabled"]


def fingerprint(username: str) -> str | None:
    """Short digest of the user's hash and state, stored in the session: changing the password,
    disabling or removing the user signs out every other open session."""
    account = get(username)
    if not account or account["disabled"]:
        return None
    return hashlib.sha256(account["hash"].encode()).hexdigest()[:16]


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


def _write(accounts: dict[str, dict]) -> None:
    tmp = USERS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(accounts, fh, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, USERS_FILE)
    except OSError as exc:
        raise StoreNotWritable(str(exc)) from exc


def _active_admins(accounts: dict[str, dict]) -> set[str]:
    return {n for n, a in accounts.items() if a["role"] == "admin" and not a["disabled"]}


def clean_prefixes(values) -> list[str]:
    prefixes = sorted({str(v).strip() for v in values or [] if str(v).strip()})
    for prefix in prefixes:
        if not PREFIX.match(prefix):
            raise UserError("users.prefixInvalid", prefix=prefix)
    return prefixes


def set_password(username: str, password: str, must_change: bool = False, role: str | None = None,
                 prefixes=None) -> None:
    """Sets the password, creating the account when needed (role admin unless given)."""
    with _locked():
        accounts = load()
        account = accounts.get(username) or _account({"role": role or "admin", "created": _now()})
        account["hash"] = generate_password_hash(password)
        account["mustChange"] = must_change
        if role:
            account["role"] = role
        if prefixes is not None:
            account["prefixes"] = clean_prefixes(prefixes)
        accounts[username] = account
        _write(accounts)


def create(username: str, password: str, role: str, prefixes=(), must_change: bool = True) -> None:
    if not USERNAME.match(username or ""):
        raise UserError("users.nameInvalid")
    if role not in ROLES:
        raise UserError("users.roleInvalid")
    prefixes = clean_prefixes(prefixes)
    with _locked():
        accounts = load()
        if username in accounts:
            raise UserError("users.exists", user=username)
        account = _account({"role": role, "prefixes": prefixes, "created": _now()})
        account["hash"] = generate_password_hash(password)
        account["mustChange"] = must_change
        accounts[username] = account
        _write(accounts)


def update(username: str, role: str | None = None, prefixes=None, disabled: bool | None = None) -> dict:
    """Changes role, prefixes or state; the last active administrator cannot lose that status."""
    with _locked():
        accounts = load()
        account = accounts.get(username)
        if not account:
            raise UserError("users.unknown", user=username)
        if role is not None:
            if role not in ROLES:
                raise UserError("users.roleInvalid")
            account["role"] = role
        if prefixes is not None:
            account["prefixes"] = clean_prefixes(prefixes)
        if disabled is not None:
            account["disabled"] = bool(disabled)
        if not _active_admins(accounts):
            raise UserError("users.lastAdmin")
        _write(accounts)
        return account


def remove(username: str) -> None:
    with _locked():
        accounts = load()
        if username not in accounts:
            raise UserError("users.unknown", user=username)
        accounts.pop(username)
        if not _active_admins(accounts):
            raise UserError("users.lastAdmin")
        _write(accounts)


def touch_login(username: str) -> None:
    try:
        with _locked():
            accounts = load()
            if username in accounts:
                accounts[username]["lastLogin"] = _now()
                _write(accounts)
    except StoreNotWritable:
        pass


def public(username: str, account: dict) -> dict:
    """What the administration screen shows (never the hash)."""
    return {"username": username, **{k: account[k] for k in
                                     ("role", "prefixes", "disabled", "mustChange", "created", "lastLogin")}}


def is_writable() -> bool:
    directory = os.path.dirname(USERS_FILE) or "."
    if os.path.exists(USERS_FILE):
        return os.access(USERS_FILE, os.W_OK) and os.access(directory, os.W_OK)
    return os.access(directory, os.W_OK)
