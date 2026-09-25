"""
Manages portal users from the command line.

  docker compose run --rm portal-service python create_user.py maria            # create or reset
  docker compose run --rm portal-service python create_user.py maria --remove   # remove
"""
import getpass
import sys

import users


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: python create_user.py <username> [--remove]")
    username = sys.argv[1].strip()
    try:
        if "--remove" in sys.argv:
            users.remove(username)
            print(f"User {username} removed.")
            return
        password = getpass.getpass(f"Password (at least {users.MIN_PASSWORD_LENGTH} characters): ")
        if len(password) < users.MIN_PASSWORD_LENGTH or password != getpass.getpass("Repeat the password: "):
            sys.exit("Password too short, or the two entries do not match.")
        users.set_password(username, password)
        print(f"User {username} saved.")
    except users.StoreNotWritable as exc:
        sys.exit(f"Cannot write the users file ({exc}). /app/config must be writable by uid 10001.")


if __name__ == "__main__":
    main()
