"""
Record metadata kept by the portal: who created and who last changed each record, and when.

The resolver stores only the links, so this small JSON file (next to users.json, in the portal's
configuration volume) lets the record list show and filter by "last change". Records created or
changed outside the portal simply have no metadata.

Key: see key(): "<GTIN-14>" and "<GTIN-14>/10/<lot>" for GTINs, "<AI>/<value>" for the other keys.
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


def key(anchor: str, lot: str | None) -> str:
    """"09506000134352" for /01/… (the format used before other keys existed), "414/9506000134376"
    for the other primary keys; "/10/<lot>" appended for a batch."""
    base = anchor[4:] if anchor.startswith("/01/") else anchor.lstrip("/")
    return f"{base}/10/{lot}" if lot else base


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


def touch(anchor: str, lot: str | None, user: str) -> None:
    """Records a creation or a change by `user` now."""
    with _locked():
        data = load()
        k = key(anchor, lot)
        now = _now()
        entry = data.get(k) or {"createdAt": now, "createdBy": user}
        entry.update(updatedAt=now, updatedBy=user)
        data[k] = entry
        _write(data)


def remove(anchor: str, lot: str | None) -> None:
    with _locked():
        data = load()
        if data.pop(key(anchor, lot), None) is not None:
            _write(data)
