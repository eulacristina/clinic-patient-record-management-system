import sqlite3
import uuid
from contextlib import closing

from werkzeug.security import generate_password_hash

DATABASE = 'clinic.db'


def get_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_users(cursor):
    """One-time user cleanup, recorded in the 'migrations' table so it runs once.

    End result: usernames are unique (ignoring letter case) and exactly one
    account named 'AdminofClinic' exists with the starter password 'Admin@123'.
    CHANGE THAT PASSWORD after the first login (/change-password).
    """
    cursor.execute("CREATE TABLE IF NOT EXISTS migrations (name TEXT PRIMARY KEY)")
    if cursor.execute(
        "SELECT 1 FROM migrations WHERE name = 'adminofclinic_v1'"
    ).fetchone():
        return

    seen = set()
    for user_id, user_code, username in cursor.execute(
        "SELECT user_id, user_code, username FROM users ORDER BY user_id"
    ).fetchall():
        key = username.lower()
        if key in seen:
            cursor.execute(
                "UPDATE users SET username = ? WHERE user_id = ?",
                (f"{username}_{user_code}", user_id),
            )
        else:
            seen.add(key)

    pw_hash = generate_password_hash('Admin@123')
    target = cursor.execute(
        "SELECT user_id FROM users WHERE username = 'AdminofClinic' COLLATE NOCASE"
    ).fetchone()
    if target:
        cursor.execute(
            "UPDATE users SET username = 'AdminofClinic', password = ? WHERE user_id = ?",
            (pw_hash, target[0]),
        )
        action = "reset"
    else:
        spare = cursor.execute(
            "SELECT MAX(user_id) FROM users "
            "WHERE username LIKE 'admin%' COLLATE NOCASE AND email IS NULL"
        ).fetchone()[0]
        if spare:
            cursor.execute(
                "UPDATE users SET username = 'AdminofClinic', password = ? WHERE user_id = ?",
                (pw_hash, spare),
            )
            action = "renamed from an unused admin account"
        else:
            cursor.execute(
                "INSERT INTO users (user_code, username, password) VALUES (?, ?, ?)",
                ('USR-' + uuid.uuid4().hex[:6].upper(), 'AdminofClinic', pw_hash),
            )
            action = "created"

    cursor.execute("INSERT INTO migrations (name) VALUES ('adminofclinic_v1')")
    print(f"[models] AdminofClinic account {action}. Starter password: Admin@123")


def init_db():
    with closing(get_connection()) as conn:
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_code TEXT NOT NULL UNIQUE,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                email TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS patients (
                patient_id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_code TEXT NOT NULL UNIQUE,
                firstName TEXT NOT NULL,
                lastName TEXT NOT NULL,
                age INTEGER NOT NULL,
                gender TEXT NOT NULL,
                contact TEXT NOT NULL,
                attendingPhysician TEXT NOT NULL
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS appointments (
                appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                appointment_date TEXT NOT NULL,
                appointment_time TEXT NOT NULL,
                appointment_status TEXT NOT NULL,
                FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS consultation_records (
                consultation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                consultation_date TEXT NOT NULL,
                diagnosis TEXT,
                notes TEXT,
                FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS visits (
                visit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                appointment_id INTEGER NOT NULL UNIQUE,
                visit_date TEXT NOT NULL,
                notes TEXT NOT NULL,
                FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
                FOREIGN KEY (appointment_id) REFERENCES appointments(appointment_id)
            )
        ''')

        cursor.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]
        if "email" not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")

        cursor.execute("DROP INDEX IF EXISTS idx_users_email")
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_nocase "
            "ON users(email COLLATE NOCASE)"
        )

        _migrate_users(cursor)

        try:
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_nocase "
                "ON users(username COLLATE NOCASE)"
            )
        except sqlite3.IntegrityError:
            print("Could not enforce unique usernames: two users differ only by "
                  "letter case. Rename one of them, then run this again.")

        conn.commit()


def get_user_by_email(email):
    with closing(get_connection()) as conn:
        return conn.execute(
            "SELECT user_id, username FROM users WHERE email = ? COLLATE NOCASE",
            (email,),
        ).fetchone()


if __name__ == '__main__':
    init_db()
    print("Database initialized.")