"""Print the APP_PASSWORD_HASH line for .env. The password is typed hidden and never saved.
Run from the project folder:  python -m scripts.hash_password"""
from __future__ import annotations

from getpass import getpass

from api.auth import hash_password

def main() -> int:
    first = getpass("New password (at least 12 characters): ")
    if len(first) < 12:
        print("✗ Use at least 12 characters.")
        return 1
    if getpass("Type it again: ") != first:
        print("✗ The two passwords are different.")
        return 1
    print("\nAdd this line to .env (keep the single quotes):\n")
    print(f"APP_PASSWORD_HASH='{hash_password(first)}'")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
