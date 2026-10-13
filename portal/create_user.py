"""
Manages portal users from the command line (the portal's Users screen does the same for administrators).

  docker compose exec portal-service python create_user.py maria                      # create or reset (admin)
  docker compose exec portal-service python create_user.py maria --role editor --prefixes 7891234,7895678
  docker compose exec portal-service python create_user.py ana --role admin --tenant "Acme Foods" --email ana@acme.example
  docker compose exec portal-service python create_user.py maria --remove             # remove

A new user created here is an administrator unless --role says otherwise, and the operator's unless --tenant
names an organisation (by name or id): an administrator of the operator is a server administrator
(Documentation/adr/0002-tenants.md). Resetting keeps the role unless --role is given; an existing user's
organisation never changes.
"""
import argparse
import getpass
import sys

import tenants
import users


def main() -> None:
    """Command line: create a user or set a new password (asked twice), with role and prefixes, or remove a user."""
    parser = argparse.ArgumentParser(description="Create, reset or remove a portal user.")
    parser.add_argument("username")
    parser.add_argument("--role", choices=users.ROLES)
    parser.add_argument("--prefixes", help="GS1 Company Prefixes, comma-separated (empty: every identifier of the "
                                            "organisation, or everything the operator holds)")
    parser.add_argument("--tenant", help="organisation of a new user, by name or id (default: the operator)")
    parser.add_argument("--email", help="e-mail address (optional; empty removes it)")
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    username = args.username.strip()
    try:
        if args.remove:
            users.remove(username)
            print(f"User {username} removed.")
            return
        tenant = None
        if args.tenant:
            found = tenants.find(args.tenant)
            if not found:
                sys.exit(f"Refused: no organisation called {args.tenant!r}.")
            existing = users.get(username)
            if existing and existing.get("tenant") != found["id"]:
                sys.exit(f"Refused: {username} already exists in another organisation (or the operator's).")
            tenant = found["id"]
        password = getpass.getpass(f"Password (at least {users.MIN_PASSWORD_LENGTH} characters): ")
        if len(password) < users.MIN_PASSWORD_LENGTH or password != getpass.getpass("Repeat the password: "):
            sys.exit("Password too short, or the two entries do not match.")
        prefixes = None if args.prefixes is None else [p for p in args.prefixes.split(",") if p.strip()]
        users.set_password(username, password, role=args.role, prefixes=prefixes, tenant=tenant, email=args.email)
        print(f"User {username} saved.")
    except users.UserError as exc:
        sys.exit(f"Refused: {exc.code} {exc.params or ''}")
    except users.StoreNotWritable as exc:
        sys.exit(f"Cannot write to the portal's database ({exc}). Check PORTAL_DB_* in .env and that the "
                 "portal-db-init service completed (docker compose logs portal-db-init).")


if __name__ == "__main__":
    main()
