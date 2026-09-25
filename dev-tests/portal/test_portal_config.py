#!/usr/bin/env python3
"""
Portal start-up configuration: public address and cookie flag derived from the environment, and the
first user created from PORTAL_ADMIN_USERNAME / PORTAL_ADMIN_PASSWORD only while the store is empty.

Each case imports portal/app.py in a fresh interpreter with its own environment.
  pip install -r portal/requirements.txt
  python dev-tests/portal/test_portal_config.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PORTAL = os.environ.get("PORTAL_DIR", os.path.join(HERE, "..", "..", "portal"))
PROBE = ("import json, app, users; print(json.dumps({'url': app.RESOLVER_PUBLIC_URL, 'origin': app.PORTAL_ORIGIN,"
         " 'secure': app.COOKIE_SECURE, 'users': sorted(users.load())}))")
failures = []


def check(name, condition, detail=""):
    print(("PASS " if condition else "FAIL ") + name + ("" if condition else f"  → {detail}"))
    if not condition:
        failures.append(name)


def run(env: dict, users: dict | None = None):
    config = tempfile.mkdtemp()
    if users is not None:
        with open(os.path.join(config, "users.json"), "w") as fh:
            json.dump(users, fh)
    base = {k: v for k, v in os.environ.items()
            if not k.startswith(("PORTAL_", "RESOLVER_")) and k not in ("FQDN", "SESSION_TOKEN")}
    base.update(SESSION_TOKEN="tok", PORTAL_CONFIG_DIR=config, PORTAL_USERS_FILE=os.path.join(config, "users.json"))
    base.update(env)
    proc = subprocess.run([sys.executable, "-c", PROBE], cwd=PORTAL, env=base, capture_output=True, text=True)
    if proc.returncode:
        return None, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1]), proc.stderr


out, _ = run({"FQDN": "id.example.org"})
check("FQDN only → https://FQDN", out and out["url"] == "https://id.example.org" and out["origin"] == out["url"], out)
check("https address → Secure cookie", out and out["secure"] is True, out)

out, _ = run({"FQDN": "id.example.org", "RESOLVER_PUBLIC_URL": "http://localhost:8080/"})
check("RESOLVER_PUBLIC_URL wins, trailing slash removed", out and out["url"] == "http://localhost:8080", out)
check("http address → cookie without Secure", out and out["secure"] is False, out)

out, _ = run({"RESOLVER_PUBLIC_URL": "http://localhost:8080", "PORTAL_COOKIE_SECURE": "true"})
check("PORTAL_COOKIE_SECURE overrides the default", out and out["secure"] is True, out)

out, err = run({})
check("no FQDN and no RESOLVER_PUBLIC_URL → refuses to start", out is None and "FQDN" in err, err[-200:])

admin = {"FQDN": "id.example.org", "PORTAL_ADMIN_USERNAME": "admin", "PORTAL_ADMIN_PASSWORD": "change-me-please"}
out, _ = run(admin)
check("empty store → first user created", out and out["users"] == ["admin"], out)

out, _ = run(admin, users={"maria": "pbkdf2:sha256:1$x$y"})
check("existing users → nothing created or changed", out and out["users"] == ["maria"], out)

out, err = run({**admin, "PORTAL_ADMIN_PASSWORD": "short"})
check("password under 12 characters → not created, warning", out and out["users"] == [] and "shorter" in err, err[-200:])

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
