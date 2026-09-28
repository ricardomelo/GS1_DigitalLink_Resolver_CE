"""
Record metadata kept by the portal: who created and who last changed each record, and when.

The resolver stores only the links, so this small JSON file (next to users.json, in the portal's
configuration volume) lets the record list show and filter by "last change". Records created or
changed outside the portal simply have no metadata.

Key: "<GTIN-14>" for the product level, "<GTIN-14>/10/<lot>" for a batch/lot.
Writes are atomic and serialised with an advisory lock, as in users.py. A failure here never
stops a save: the caller logs it and carries on.
"""
import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone

META_FILE = os.environ.get("PORTAL_META_FILE",
                           os.path.join(os.environ.get("PORTAL_CONFIG_DIR", "/app/config"), "records-meta.json"))


def key(gtin14: str, lot: str | None) -> str:
    return f"{gtin14}/10/{lot}" if lot else gtin14


def load() -> dict[str, dict]:
    try:
        with open(META_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


@contextmanager
def _locked():
    with open(META_FILE + ".lock", "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _write(data: dict) -> None:
    tmp = META_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, META_FILE)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def touch(gtin14: str, lot: str | None, user: str) -> None:
    """Records a creation or a change by `user` now."""
    with _locked():
        data = load()
        k = key(gtin14, lot)
        now = _now()
        entry = data.get(k) or {"createdAt": now, "createdBy": user}
        entry.update(updatedAt=now, updatedBy=user)
        data[k] = entry
        _write(data)


def remove(gtin14: str, lot: str | None) -> None:
    with _locked():
        data = load()
        if data.pop(key(gtin14, lot), None) is not None:
            _write(data)
