"""
Manages portal users from the command line (the portal's Users screen does the same for administrators).

  docker compose exec portal-service python create_user.py maria                      # create or reset (admin)
  docker compose exec portal-service python create_user.py maria --role editor --prefixes 7891234,7895678
  docker compose exec portal-service python create_user.py maria --remove             # remove

A new user created here is an administrator unless --role says otherwise; resetting keeps the role
unless --role is given.
"""
import argparse
import getpass
import sys

import users


def main() -> None:
    """Command line: create a user or set a new password (asked twice), with role and prefixes, or remove a user."""
    parser = argparse.ArgumentParser(description="Create, reset or remove a portal user.")
    parser.add_argument("username")
    parser.add_argument("--role", choices=users.ROLES)
    parser.add_argument("--prefixes", help="GS1 Company Prefixes, comma-separated (empty: every identifier)")
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    username = args.username.strip()
    try:
        if args.remove:
            users.remove(username)
            print(f"User {username} removed.")
            return
        password = getpass.getpass(f"Password (at least {users.MIN_PASSWORD_LENGTH} characters): ")
        if len(password) < users.MIN_PASSWORD_LENGTH or password != getpass.getpass("Repeat the password: "):
            sys.exit("Password too short, or the two entries do not match.")
        prefixes = None if args.prefixes is None else [p for p in args.prefixes.split(",") if p.strip()]
        users.set_password(username, password, role=args.role, prefixes=prefixes)
        print(f"User {username} saved.")
    except users.UserError as exc:
        sys.exit(f"Refused: {exc.code} {exc.params or ''}")
    except users.StoreNotWritable as exc:
        sys.exit(f"Cannot write the users file ({exc}). /app/config must be writable by uid 10001.")


if __name__ == "__main__":
    main()
