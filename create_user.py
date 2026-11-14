import sqlite3
import uuid
from getpass import getpass

from werkzeug.security import generate_password_hash

from password_rules import validate_password

DATABASE = 'clinic.db'


def create_user(username, password):
    """Returns (ok, message)."""
    username = username.strip()
    if not username:
        return False, "Username cannot be empty."

    errors = validate_password(password)
    if errors:
        return False, "Password rejected:\n" + "\n".join(f" - {e}" for e in errors)

    conn = sqlite3.connect(DATABASE)
    try:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        if exists:
            return False, (f"A user named '{username}' already exists. "
                           "Log in and use /change-password to change its password.")

        conn.execute(
            "INSERT INTO users (user_code, username, password) VALUES (?, ?, ?)",
            ('USR-' + uuid.uuid4().hex[:6].upper(), username,
             generate_password_hash(password))
        )
        conn.commit()
        return True, f"User '{username}' created."
    finally:
        conn.close()


if __name__ == '__main__':
    name = input("Username: ")
    pw = getpass("Password: ")
    if pw != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match.")
    ok, message = create_user(name, pw)
    print(message)
    raise SystemExit(0 if ok else 1)