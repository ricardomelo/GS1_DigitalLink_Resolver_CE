"""
Portal user store: the "users" collection of the portal's database (store.py), one document per account.

    {"_id": "maria", "hash": "<werkzeug hash>", "role": "editor", "prefixes": ["7891234"],
     "disabled": false, "mustChange": false, "created": "…", "lastLogin": "…"}

Roles, from least to most: reader (consults and exports), editor (also changes records), admin (also
manages users and sees the audit trail). "prefixes" limits an account to identifiers of those GS1
Company Prefixes (empty: every identifier). "mustChange" asks for a new password at the next sign-in
(temporary passwords). Accounts imported from a users.json written before roles existed ({"name": "<hash>"})
are read as admins (migrate.py).

Writes run under a lock shared by every replica (store.lock), so two administrators acting at the same
moment cannot both remove the last enabled administrator. Every lookup reads the database, so changes made
from the command line (create_user.py) take effect at once.
"""
import hashlib
import hmac
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError, PyMongoError
from werkzeug.security import check_password_hash, generate_password_hash

import store

MIN_PASSWORD_LENGTH = 12
ROLES = ("reader", "editor", "admin")
USERNAME = re.compile(r"^[A-Za-z0-9._@\-]{3,64}$")
PREFIX = re.compile(r"^\d{4,12}$", re.ASCII)   # ASCII digits only: \d alone would accept "７"
FIELDS = ("hash", "role", "prefixes", "disabled", "mustChange", "created", "lastLogin")
# Hash of a random password, checked when the username does not exist so that response
# times do not reveal which usernames are valid.
_DUMMY_HASH = generate_password_hash(os.urandom(16).hex())


class StoreNotWritable(Exception):
    """The user store cannot be written: the database is unreachable or refused the write."""


class UserError(Exception):
    """A request the store refuses; code is a message code for the browser."""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = params


def _now() -> str:
    """Current UTC time, ISO 8601 with a Z, to the second."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _account(value) -> dict:
    """An account with every field present; plain hashes from before roles become administrators."""
    if isinstance(value, str):                     # before roles: every user was an administrator
        value = {"hash": value, "role": "admin"}
    account = {"hash": "", "role": "admin", "prefixes": [], "disabled": False, "mustChange": False,
               "created": None, "lastLogin": None}
    account.update({k: v for k, v in value.items() if k in FIELDS})
    if account["role"] not in ROLES:
        account["role"] = "reader"
    return account


def _users():
    return store.col("users")


def load() -> dict[str, dict]:
    """Every account, keyed by user name."""
    return {doc["_id"]: _account(doc) for doc in _users().find().sort("_id", 1)}


def get(username: str) -> dict | None:
    """One account, or None."""
    doc = _users().find_one({"_id": username or ""})
    return _account(doc) if doc else None


def verify(username: str, password: str) -> bool:
    """Whether the password is right and the account enabled; spends the same time when the user does not exist."""
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
    """Whether a session's fingerprint still matches the account (constant-time comparison)."""
    current = fingerprint(username)
    return bool(current and value) and hmac.compare_digest(current, value)


@contextmanager
def _locked():
    """The users lock (store.lock); StoreNotWritable when the database cannot be reached or written."""
    try:
        with store.lock("users"):
            yield
    except (PyMongoError, store.LockTimeout) as exc:
        raise StoreNotWritable(str(exc)) from exc


def _save(username: str, account: dict) -> None:
    """Writes one account (whole document)."""
    _users().replace_one({"_id": username}, {k: account[k] for k in FIELDS}, upsert=True)


def _active_admins(accounts: dict[str, dict]) -> set[str]:
    """Names of the enabled administrators."""
    return {n for n, a in accounts.items() if a["role"] == "admin" and not a["disabled"]}


def clean_prefixes(values) -> list[str]:
    """GS1 Company Prefixes as stored: trimmed, unique, sorted, 4 to 12 digits each."""
    prefixes = sorted({str(v).strip() for v in values or [] if str(v).strip()})
    for prefix in prefixes:
        if not PREFIX.match(prefix):
            raise UserError("users.prefixInvalid", prefix=prefix)
    return prefixes


def set_password(username: str, password: str, must_change: bool = False, role: str | None = None,
                 prefixes=None) -> None:
    """Sets the password, creating the account when needed (role admin unless given)."""
    with _locked():
        account = get(username) or _account({"role": role or "admin", "created": _now()})
        account["hash"] = generate_password_hash(password)
        account["mustChange"] = must_change
        if role:
            account["role"] = role
        if prefixes is not None:
            account["prefixes"] = clean_prefixes(prefixes)
        _save(username, account)


def create(username: str, password: str, role: str, prefixes=(), must_change: bool = True) -> None:
    """Creates a user (name, role, prefixes); by default the password must be changed at the first sign-in."""
    if not USERNAME.match(username or ""):
        raise UserError("users.nameInvalid")
    if role not in ROLES:
        raise UserError("users.roleInvalid")
    prefixes = clean_prefixes(prefixes)
    account = _account({"role": role, "prefixes": prefixes, "created": _now()})
    account["hash"] = generate_password_hash(password)
    account["mustChange"] = must_change
    with _locked():
        try:
            _users().insert_one({"_id": username, **{k: account[k] for k in FIELDS}})
        except DuplicateKeyError:
            raise UserError("users.exists", user=username) from None


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
        _save(username, account)
        return account


def remove(username: str) -> None:
    """Removes a user, keeping at least one enabled administrator."""
    with _locked():
        accounts = load()
        if username not in accounts:
            raise UserError("users.unknown", user=username)
        accounts.pop(username)
        if not _active_admins(accounts):
            raise UserError("users.lastAdmin")
        _users().delete_one({"_id": username})


def touch_login(username: str) -> None:
    """Records the time of a successful sign-in (best effort)."""
    try:
        _users().update_one({"_id": username}, {"$set": {"lastLogin": _now()}})
    except PyMongoError:
        pass


def public(username: str, account: dict) -> dict:
    """What the administration screen shows (never the hash)."""
    return {"username": username, **{k: account[k] for k in
                                     ("role", "prefixes", "disabled", "mustChange", "created", "lastLogin")}}
