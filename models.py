import sqlite3

def init_db():
    conn = sqlite3.connect('clinic.db')
    cursor = conn.cursor()

    cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_code TEXT NOT NULL UNIQUE,
                username TEXT NOT NULL,
                password TEXT NOT NULL
            )
        ''')

    # Create patients table
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

    # Create appointments table
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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visits (
            visit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            appointment_id INTEGER NOT NULL UNIQUE,
            visit_date TEXT NOT NULL,
            notes TEXT NOT NULL,
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
            FOREIGN KEY (appointment_id) REFERENCES appointments(appointment_id)
        )
    """)

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()