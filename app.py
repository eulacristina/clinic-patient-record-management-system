import sqlite3
import uuid
from functools import wraps
from flask import (Flask, render_template, request, redirect,
                   url_for, abort, session, flash)
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = 'change-this-to-a-long-random-string'  # needed for session and flash
DATABASE = 'clinic.db'


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'error')
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


# ---------- Auth ----------

@app.route('/')
def root():
    return redirect(url_for('index' if 'user_id' in session else 'login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        db.close()
        if user and check_password_hash(user['password'], password):
            session.clear()
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            return redirect(url_for('index'))
        flash('Invalid username or password.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


@app.route('/home')
@login_required
def index():
    return render_template('index.html')


# ---------- Patients ----------

@app.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    if request.method == 'POST':
        firstName = request.form['firstName'].strip()
        lastName = request.form['lastName'].strip()
        age = request.form['age']
        gender = request.form['gender']
        contact = request.form['contact'].strip()
        attendingPhysician = request.form['attendingPhysician'].strip()

        if not firstName or not lastName or not contact or not attendingPhysician:
            flash('All fields are required.', 'error')
            return render_template('register.html')
        if not age.isdigit() or not (0 < int(age) < 130):
            flash('Age must be a number between 1 and 129.', 'error')
            return render_template('register.html')

        patient_code = 'PT-' + uuid.uuid4().hex[:8].upper()
        db = get_db()
        try:
            db.execute(
                "INSERT INTO patients (patient_code, firstName, lastName, age, gender, contact, attendingPhysician) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (patient_code, firstName, lastName, int(age), gender, contact, attendingPhysician)
            )
            db.commit()
            flash(f'Patient registered. Code: {patient_code}', 'success')
        except sqlite3.IntegrityError:
            db.rollback()
            flash('Could not save: that patient code already exists. Try again.', 'error')
        finally:
            db.close()
        return redirect(url_for('register'))
    return render_template('register.html')

@app.route('/patients')
@login_required
def patients():
    q = request.args.get('q', '').strip()
    db = get_db()
    if q:
        like = f'%{q}%'
        rows = db.execute(
            "SELECT * FROM patients "
            "WHERE firstName LIKE ? OR lastName LIKE ? OR patient_code LIKE ? "
            "ORDER BY lastName, firstName",
            (like, like, like)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM patients ORDER BY lastName, firstName"
        ).fetchall()
    db.close()
    return render_template('patients.html', patients=rows, q=q)


@app.route('/patients/<int:patient_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_patient(patient_id):
    db = get_db()
    patient = db.execute(
        "SELECT * FROM patients WHERE patient_id = ?", (patient_id,)
    ).fetchone()
    if patient is None:
        db.close()
        flash('Patient not found.', 'error')
        return redirect(url_for('patients'))

    if request.method == 'POST':
        firstName = request.form['firstName'].strip()
        lastName = request.form['lastName'].strip()
        age = request.form['age']
        gender = request.form['gender']
        contact = request.form['contact'].strip()
        attendingPhysician = request.form['attendingPhysician'].strip()

        if not firstName or not lastName or not contact or not attendingPhysician:
            db.close()
            flash('All fields are required.', 'error')
            return redirect(url_for('edit_patient', patient_id=patient_id))
        if not age.isdigit() or not (0 < int(age) < 130):
            db.close()
            flash('Age must be a number between 1 and 129.', 'error')
            return redirect(url_for('edit_patient', patient_id=patient_id))

        try:
            db.execute(
                "UPDATE patients SET firstName = ?, lastName = ?, age = ?, gender = ?, "
                "contact = ?, attendingPhysician = ? WHERE patient_id = ?",
                (firstName, lastName, int(age), gender, contact,
                 attendingPhysician, patient_id)
            )
            db.commit()
            flash('Patient updated.', 'success')
        except sqlite3.Error:
            db.rollback()
            flash('Could not update the patient.', 'error')
        finally:
            db.close()
        return redirect(url_for('patients'))

    response = render_template('edit_patient.html', patient=patient)
    db.close()
    return response


@app.route('/patients/<int:patient_id>/delete', methods=['POST'])
@login_required
def delete_patient(patient_id):
    db = get_db()
    try:
        db.execute("DELETE FROM patients WHERE patient_id = ?", (patient_id,))
        db.commit()
        flash('Patient deleted.', 'success')
    except sqlite3.IntegrityError:
        db.rollback()
        flash('Cannot delete: this patient still has appointments or records.', 'error')
    finally:
        db.close()
    return redirect(url_for('patients'))

# ---------- Appointments ----------

@app.route('/appointments', methods=['GET', 'POST'])
@login_required
def appointments():
    db = get_db()

    if request.method == 'POST':
        patient_id = request.form['patient_id']
        appointment_date = request.form['appointment_date']
        appointment_time = request.form['appointment_time']
        try:
            db.execute(
                "INSERT INTO appointments (patient_id, appointment_date, appointment_time, appointment_status) "
                "VALUES (?, ?, ?, 'Scheduled')",
                (patient_id, appointment_date, appointment_time)
            )
            db.commit()
            flash('Appointment scheduled.', 'success')
        except sqlite3.Error:
            db.rollback()
            flash('Could not schedule the appointment.', 'error')
        return redirect(url_for('appointments'))

    patients = db.execute(
        "SELECT patient_id, patient_code, firstName, lastName FROM patients"
    ).fetchall()

    rows = db.execute("""
        SELECT a.appointment_id,
               a.patient_id,
               a.appointment_date,
               a.appointment_time,
               a.appointment_status,
               p.firstName,
               p.lastName,
               p.attendingPhysician AS attending_physician
        FROM appointments a
        JOIN patients p ON a.patient_id = p.patient_id
        ORDER BY a.appointment_date, a.appointment_time
    """).fetchall()

    return render_template('appointments.html', patients=patients, appointments=rows)


@app.route('/update_appointment/<int:appointment_id>', methods=['GET', 'POST'])
@login_required
def update_appointment(appointment_id):
    db = get_db()

    if request.method == 'POST':
        try:
            db.execute(
                "UPDATE appointments SET patient_id = ?, appointment_date = ?, "
                "appointment_time = ?, appointment_status = ? WHERE appointment_id = ?",
                (request.form['patient_id'],
                 request.form['appointment_date'],
                 request.form['appointment_time'],
                 request.form['appointment_status'],
                 appointment_id)
            )
            db.commit()
            flash('Appointment updated.', 'success')
        except sqlite3.Error:
            db.rollback()
            flash('Could not update the appointment.', 'error')
        return redirect(url_for('appointments'))

    appointment = db.execute(
        "SELECT * FROM appointments WHERE appointment_id = ?", (appointment_id,)
    ).fetchone()
    if appointment is None:
        flash('Appointment not found.', 'error')
        return redirect(url_for('appointments'))

    patients = db.execute(
        "SELECT patient_id, patient_code, firstName, lastName FROM patients"
    ).fetchall()
    return render_template('update_appointment.html', appointment=appointment, patients=patients)


@app.route('/delete_appointment/<int:appointment_id>', methods=['POST'])
@login_required
def delete_appointment(appointment_id):
    db = get_db()
    db.execute("DELETE FROM appointments WHERE appointment_id = ?", (appointment_id,))
    db.commit()
    flash('Appointment deleted.', 'success')
    return redirect(url_for('appointments'))


@app.route('/complete_appointment/<int:appointment_id>', methods=['GET', 'POST'])
@login_required
def complete_appointment(appointment_id):
    db = get_db()
    appointment = db.execute(
        "SELECT a.*, p.firstName, p.lastName "
        "FROM appointments a JOIN patients p ON a.patient_id = p.patient_id "
        "WHERE a.appointment_id = ?", (appointment_id,)
    ).fetchone()

    if appointment is None:
        db.close()
        flash('Appointment not found.', 'error')
        return redirect(url_for('appointments'))
    if appointment['appointment_status'] != 'Scheduled':
        db.close()
        flash('Only scheduled appointments can be completed.', 'error')
        return redirect(url_for('appointments'))

    if request.method == 'POST':
        notes = request.form['notes'].strip()
        if not notes:
            db.close()
            flash('Visit notes are required.', 'error')
            return redirect(url_for('complete_appointment', appointment_id=appointment_id))

        # TRANSACTION: both statements succeed together or neither is saved
        try:
            db.execute(
                "UPDATE appointments SET appointment_status = 'Completed' "
                "WHERE appointment_id = ?", (appointment_id,)
            )
            db.execute(
                "INSERT INTO visits (patient_id, appointment_id, visit_date, notes) "
                "VALUES (?, ?, ?, ?)",
                (appointment['patient_id'], appointment_id,
                 appointment['appointment_date'], notes)
            )
            db.commit()
            flash('Appointment completed and visit recorded.', 'success')
        except sqlite3.Error:
            db.rollback()
            flash('Could not complete the appointment. No changes were saved.', 'error')
        finally:
            db.close()
        return redirect(url_for('appointments'))

    response = render_template('complete_appointment.html', appointment=appointment)
    db.close()
    return response

# ---------- Consultation records ----------

@app.route('/consultation_records/')
@login_required
def consultation_records_index():
    db = get_db()
    patients = db.execute(
        "SELECT patient_id, patient_code, firstName, lastName FROM patients ORDER BY lastName"
    ).fetchall()
    return render_template('select_patient.html', patients=patients)


@app.route('/consultation_records/<int:patient_id>')
@login_required
def consultation_records(patient_id):
    db = get_db()
    patient = db.execute(
        "SELECT * FROM patients WHERE patient_id = ?", (patient_id,)
    ).fetchone()
    if patient is None:
        abort(404)

    records = db.execute(
        "SELECT * FROM consultation_records WHERE patient_id = ? "
        "ORDER BY consultation_date DESC",
        (patient_id,)
    ).fetchall()
    return render_template('consultation_records.html', patient=patient, records=records)


@app.route('/consultation_records/<int:patient_id>/add', methods=['POST'])
@login_required
def add_consultation_record(patient_id):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO consultation_records (patient_id, consultation_date, diagnosis, notes) "
            "VALUES (?, ?, ?, ?)",
            (patient_id,
             request.form['consultation_date'],
             request.form['diagnosis'],
             request.form['notes'])
        )
        db.commit()
        flash('Consultation record added.', 'success')
    except sqlite3.Error:
        db.rollback()
        flash('Could not save the record.', 'error')
    return redirect(url_for('consultation_records', patient_id=patient_id))


# ---------- Visit history ----------

@app.route('/visit_history/<int:patient_id>')
@login_required
def visit_history(patient_id):
    db = get_db()
    patient = db.execute(
        "SELECT * FROM patients WHERE patient_id = ?", (patient_id,)
    ).fetchone()
    if patient is None:
        db.close()
        abort(404)

    visits = db.execute(
        "SELECT a.appointment_id, a.appointment_date, a.appointment_time, "
        "a.appointment_status, v.notes "
        "FROM appointments a "
        "LEFT JOIN visits v ON v.appointment_id = a.appointment_id "
        "WHERE a.patient_id = ? "
        "ORDER BY a.appointment_date DESC, a.appointment_time DESC",
        (patient_id,)
    ).fetchall()
    db.close()

    stats = {
        'total': len(visits),
        'completed': sum(1 for v in visits if v['appointment_status'] == 'Completed'),
        'cancelled': sum(1 for v in visits if v['appointment_status'] == 'Cancelled'),
        'scheduled': sum(1 for v in visits if v['appointment_status'] == 'Scheduled'),
    }
    last_visit = next(
        (v['appointment_date'] for v in visits if v['appointment_status'] == 'Completed'),
        None
    )
    return render_template('visit_history.html', patient=patient, visits=visits,
                           stats=stats, last_visit=last_visit)

if __name__ == '__main__':
    app.run(debug=True, port=8080)