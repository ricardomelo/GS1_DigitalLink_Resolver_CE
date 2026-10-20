"""
Portal user store: the "users" collection of the portal's database (store.py), one document per account.

    {"_id": "maria", "hash": "<werkzeug hash>", "role": "editor", "prefixes": ["7891234"],
     "tenant": "t-3f9a1c0b2e7d", "email": "maria@example.org",
     "disabled": false, "mustChange": false, "created": "…", "lastLogin": "…",
     "invited": "…", "language": "pt-BR", "languageChosen": true, "notify": {"jobs": true}}

Roles, from least to most: reader (consults and exports), editor (also changes records), admin (also
manages users and sees the audit trail). "tenant" is the organisation the user belongs to (tenants.py,
Documentation/adr/0002-tenants.md); without it the user is the operator's, and an operator administrator is a
server administrator. "prefixes" limits an account to identifiers of those GS1 Company Prefixes (empty: every
identifier of its tenant, or everything the operator holds); a tenant user's prefixes lie inside the tenant's.
"email" is optional and unique in the installation. "mustChange" asks for a new password at the next sign-in
(temporary passwords). Accounts imported from a users.json written before roles existed ({"name": "<hash>"})
are read as admins (migrate.py).

E-mail (Documentation/adr/0004-e-mail.md, section 3.4): "invited" is the date of an invitation while the account
has no password of its own (an empty hash: no password signs in); "language" is the language of the user's
messages (taken from the page at each sign-in until "languageChosen"); "notify" holds the optional categories of
messages the user switched on (notify.py).

Writes run under a lock shared by every replica (store.lock), so two administrators acting at the same
moment cannot both remove the last enabled server administrator. Every lookup reads the database, so changes
made from the command line (create_user.py) take effect at once.
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
EMAIL = re.compile(r"^[^@\s\x00-\x1f\x7f]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                   r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
EMAIL_MAX = 254
FIELDS = ("hash", "role", "prefixes", "tenant", "email", "disabled", "mustChange", "created", "lastLogin",
          "invited", "language", "languageChosen", "notify")
OPTIONAL_FIELDS = ("tenant", "email", "invited", "language", "languageChosen", "notify")   # absent when empty
# The languages of the interface and the e-mails (Documentation/adr/0014-interface-languages.md)
LANGUAGES = ("en-GB", "pt-BR", "es", "fr", "de", "it", "tr", "zh-Hans", "ja", "ko", "hi", "ar")
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
    account = {"hash": "", "role": "admin", "prefixes": [], "tenant": None, "email": None, "disabled": False,
               "mustChange": False, "created": None, "lastLogin": None, "invited": None, "language": None,
               "languageChosen": False, "notify": {}}
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
def locked():
    """The users lock (store.lock); StoreNotWritable when the database cannot be reached or written."""
    try:
        with store.lock("users"):
            yield
    except (PyMongoError, store.LockTimeout) as exc:
        raise StoreNotWritable(str(exc)) from exc


def _stored(account: dict) -> dict:
    """The fields of an account as stored: no "tenant" for the operator's users, no "email" when there is none
    (so that queries for {"tenant": None} find both the users written before tenants existed and new ones), and
    the other optional fields only when they hold something."""
    return {k: account[k] for k in FIELDS if not (k in OPTIONAL_FIELDS and not account[k])}


def _save(username: str, account: dict) -> None:
    """Writes one account (whole document)."""
    _users().replace_one({"_id": username}, _stored(account), upsert=True)


def is_server_admin(account: dict | None) -> bool:
    """Whether the account is a server administrator: an administrator of the operator (enabled or not)."""
    return bool(account) and account["role"] == "admin" and not account.get("tenant")


def _active_admins(accounts: dict[str, dict]) -> set[str]:
    """Names of the enabled server administrators (administrators of the operator)."""
    return {n for n, a in accounts.items() if is_server_admin(a) and not a["disabled"]}


def clean_email(value) -> str | None:
    """An e-mail address as stored (trimmed, lower case), None when empty; UserError when it is not one."""
    email = str(value or "").strip().lower()
    if not email:
        return None
    if len(email) > EMAIL_MAX or not EMAIL.match(email):
        raise UserError("users.emailInvalid")
    return email


def _check_email(username: str, email: str | None) -> None:
    """Refuses an address another user already has (call under the lock)."""
    if email and _users().find_one({"email": email, "_id": {"$ne": username}}, {"_id": 1}):
        raise UserError("users.emailExists")


def _tenant_prefixes(tenant_id: str) -> list[str] | None:
    """The prefixes of a tenant, or None when it does not exist (read directly: tenants.py imports this module)."""
    doc = store.col("tenants").find_one({"_id": tenant_id}, {"prefixes": 1})
    return None if doc is None else list(doc.get("prefixes") or [])


def _check_scope(tenant_id: str | None, prefixes: list[str]) -> None:
    """A tenant user's prefixes lie inside the tenant's; an operator user's may not lie inside a tenant's (he
    would reach no record). Call under the lock."""
    if tenant_id:
        held = _tenant_prefixes(tenant_id)
        if held is None:
            raise UserError("users.tenantUnknown")
        for prefix in prefixes:
            if not any(prefix.startswith(t) for t in held):
                raise UserError("users.prefixOutsideTenant", prefix=prefix)
        return
    for doc in store.col("tenants").find({}, {"name": 1, "prefixes": 1}):
        for prefix in prefixes:
            if any(prefix.startswith(t) for t in doc.get("prefixes") or []):
                raise UserError("users.prefixOfTenant", prefix=prefix, tenant=doc.get("name", ""))


def clean_prefixes(values) -> list[str]:
    """GS1 Company Prefixes as stored: trimmed, unique, sorted, 4 to 12 digits each."""
    prefixes = sorted({str(v).strip() for v in values or [] if str(v).strip()})
    for prefix in prefixes:
        if not PREFIX.match(prefix):
            raise UserError("users.prefixInvalid", prefix=prefix)
    return prefixes


def set_password(username: str, password: str, must_change: bool = False, role: str | None = None,
                 prefixes=None, tenant: str | None = None, email=None) -> None:
    """Sets the password, creating the account when needed (role admin unless given; the tenant only when
    the account is created: an existing user keeps his). An invitation ends: the account has a password."""
    with locked():
        account = get(username)
        if account is None:
            account = _account({"role": role or "admin", "created": _now(), "tenant": tenant})
        account["hash"] = generate_password_hash(password)
        account["mustChange"] = must_change
        account["invited"] = None
        if role:
            account["role"] = role
        if prefixes is not None:
            account["prefixes"] = clean_prefixes(prefixes)
        if email is not None:
            account["email"] = clean_email(email)
            _check_email(username, account["email"])
        _check_scope(account["tenant"], account["prefixes"])
        _save(username, account)


def create(username: str, password: str | None, role: str, prefixes=(), must_change: bool = True,
           tenant: str | None = None, email=None, language: str | None = None) -> None:
    """Creates a user (name, role, prefixes, tenant, e-mail); by default the password must be changed at the
    first sign-in. Without a tenant the user is the operator's. Without a password (None) the user is invited:
    he chooses one through the link of his invitation (an address is then required)."""
    if not USERNAME.match(username or ""):
        raise UserError("users.nameInvalid")
    if role not in ROLES:
        raise UserError("users.roleInvalid")
    prefixes = clean_prefixes(prefixes)
    account = _account({"role": role, "prefixes": prefixes, "created": _now(), "tenant": tenant or None,
                        "email": clean_email(email), "language": clean_language(language)})
    if password is None:
        if not account["email"]:
            raise UserError("users.emailRequired")
        account["invited"] = _now()
    else:
        account["hash"] = generate_password_hash(password)
        account["mustChange"] = must_change
    with locked():
        _check_scope(account["tenant"], prefixes)
        _check_email(username, account["email"])
        try:
            _users().insert_one({"_id": username, **_stored(account)})
        except DuplicateKeyError:
            raise UserError("users.exists", user=username) from None


def update(username: str, role: str | None = None, prefixes=None, disabled: bool | None = None,
           email=None) -> dict:
    """Changes role, prefixes, e-mail ("" removes it) or state; the last active server administrator cannot
    lose that status. The tenant never changes."""
    with locked():
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
        if email is not None:
            account["email"] = clean_email(email)
            _check_email(username, account["email"])
        _check_scope(account["tenant"], account["prefixes"])
        if not _active_admins(accounts):
            raise UserError("users.lastAdmin")
        _save(username, account)
        return account


def clear_password(username: str) -> None:
    """Removes the password (an administrator's reset by link): no password signs in and every session of the
    account ends, until the user chooses a new one through the link."""
    with locked():
        account = get(username)
        if not account:
            raise UserError("users.unknown", user=username)
        account["hash"] = ""
        account["mustChange"] = False
        _save(username, account)


def find_login(login: str) -> str | None:
    """The user name an entry of the password recovery form means: a user name, or an e-mail address (case is
    ignored for both)."""
    text = str(login or "").strip()
    if not text or len(text) > EMAIL_MAX:
        return None
    if "@" in text:
        doc = _users().find_one({"email": text.lower()}, {"_id": 1})
        if doc:
            return doc["_id"]
    if get(text):
        return text
    if USERNAME.match(text):                       # user names are case-sensitive; recovery forgives case
        for doc in _users().find({}, {"_id": 1}):
            if doc["_id"].lower() == text.lower():
                return doc["_id"]
    return None


def clean_language(value) -> str | None:
    """A language of the messages (one of LANGUAGES), or None when it is not one."""
    text = str(value or "").strip()
    return text if text in LANGUAGES else None


def note_language(username: str, value) -> None:
    """Keeps the page's language as the language of the user's messages, until he chooses one (best effort)."""
    language = clean_language(value)
    if not language:
        return
    try:
        _users().update_one({"_id": username, "languageChosen": {"$ne": True}, "language": {"$ne": language}},
                            {"$set": {"language": language}})
    except PyMongoError:
        pass


def set_preferences(username: str, language=None, notify: dict | None = None) -> dict:
    """The user's own choices: the language of his messages and the optional categories (notify.py checks the
    names). Returns the account."""
    with locked():
        account = get(username)
        if not account:
            raise UserError("users.unknown", user=username)
        if language is not None:
            account["language"] = clean_language(language)
            if not account["language"]:
                raise UserError("preferences.languageInvalid")
            account["languageChosen"] = True
        if notify is not None:
            # both values are kept: a category on by default (alerts) is switched off by an explicit false
            account["notify"] = {**(account.get("notify") or {}), **{k: bool(v) for k, v in notify.items()}}
        _save(username, account)
        return account


def remove(username: str) -> None:
    """Removes a user, keeping at least one enabled administrator."""
    with locked():
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
                                     ("role", "prefixes", "tenant", "email", "disabled", "mustChange", "created",
                                      "lastLogin", "invited")}}
