import sqlite3, uuid
from werkzeug.security import generate_password_hash

conn = sqlite3.connect('clinic.db')
conn.execute(
    "INSERT INTO users (user_code, username, password) VALUES (?, ?, ?)",
    ('USR-' + uuid.uuid4().hex[:6].upper(), 'admin', generate_password_hash('admin123'))
)
conn.commit()
conn.close()
print("User created.")