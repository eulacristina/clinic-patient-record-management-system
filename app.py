import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime
from functools import wraps

from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import (Flask, render_template, request, redirect,
                   url_for, abort, session, flash)
from werkzeug.security import check_password_hash, generate_password_hash

from models import get_user_by_email, init_db
from password_rules import validate_password

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]  # needed for session and flash
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

DATABASE = 'clinic.db'

init_db()  # creates missing tables/indexes and runs the one-time user cleanup

oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


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
        with closing(get_db()) as db:
            user = db.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
        if user and user['password'] and check_password_hash(user['password'], password):
            session.clear()
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            return redirect(url_for('index'))
        flash('Invalid username or password.', 'error')
    return render_template('login.html')


@app.route("/login/google")
def login_google():
    return google.authorize_redirect(url_for("google_callback", _external=True))


@app.route("/auth/google/callback")
def google_callback():
    try:
        token = google.authorize_access_token()
    except Exception:
        flash("Google sign-in failed. Please try again.", "error")
        return redirect(url_for("login"))

    info = token.get("userinfo") or {}
    if not info.get("email") or not info.get("email_verified"):
        flash("Your Google email could not be verified.", "error")
        return redirect(url_for("login"))

    user = get_user_by_email(info["email"])
    if not user:
        flash("This Google account is not authorized to use Clinic Care.", "error")
        return redirect(url_for("login"))

    session.clear()
    session["user_id"] = user["user_id"]
    session["username"] = user["username"]
    return redirect(url_for("index"))


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current = request.form['current_password']
        new = request.form['new_password']
        confirm = request.form['confirm_password']

        with closing(get_db()) as db:
            user = db.execute(
                "SELECT * FROM users WHERE user_id = ?", (session['user_id'],)
            ).fetchone()

            if (not user or not user['password']
                    or not check_password_hash(user['password'], current)):
                flash('Current password is incorrect.', 'error')
                return redirect(url_for('change_password'))

            if new != confirm:
                flash('New passwords do not match.', 'error')
                return redirect(url_for('change_password'))

            if new == current:
                flash('New password must be different from the current one.', 'error')
                return redirect(url_for('change_password'))

            errors = validate_password(new)
            if errors:
                for e in errors:
                    flash(e, 'error')
                return redirect(url_for('change_password'))

            try:
                db.execute(
                    "UPDATE users SET password = ? WHERE user_id = ?",
                    (generate_password_hash(new), session['user_id'])
                )
                db.commit()
                flash('Password changed.', 'success')
            except sqlite3.Error:
                db.rollback()
                flash('Could not change the password.', 'error')
                return redirect(url_for('change_password'))
        return redirect(url_for('index'))

    return render_template('change_password.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


@app.route('/home')
@login_required
def index():
    with closing(get_db()) as db:
        stats = db.execute("""
            SELECT
              (SELECT COUNT(*) FROM patients) AS patients,
              (SELECT COUNT(*) FROM appointments) AS total,
              (SELECT COUNT(*) FROM appointments WHERE appointment_status = 'Scheduled') AS scheduled,
              (SELECT COUNT(*) FROM appointments WHERE appointment_status = 'Completed') AS completed,
              (SELECT COUNT(*) FROM appointments WHERE appointment_status = 'Cancelled') AS cancelled
        """).fetchone()

        try:
            consultations_count = db.execute(
                "SELECT COUNT(*) FROM consultation_records"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            consultations_count = 0

        today_appts = db.execute("""
            SELECT a.appointment_id, a.appointment_time, a.appointment_status,
                   p.firstName, p.lastName, p.attendingPhysician
            FROM appointments a
            JOIN patients p ON a.patient_id = p.patient_id
            WHERE a.appointment_date = date('now', 'localtime')
            ORDER BY a.appointment_time
        """).fetchall()

        upcoming = db.execute("""
            SELECT a.appointment_id, a.appointment_date, a.appointment_time,
                   p.firstName, p.lastName
            FROM appointments a
            JOIN patients p ON a.patient_id = p.patient_id
            WHERE a.appointment_status = 'Scheduled'
              AND a.appointment_date > date('now', 'localtime')
            ORDER BY a.appointment_date, a.appointment_time
            LIMIT 5
        """).fetchall()

        recent_patients = db.execute(
            "SELECT patient_id, patient_code, firstName, lastName "
            "FROM patients ORDER BY patient_id DESC LIMIT 5"
        ).fetchall()

    return render_template(
        'index.html',
        # New dashboard data
        stats=stats,
        consultations_count=consultations_count,
        today_appts=today_appts,
        upcoming=upcoming,
        recent_patients=recent_patients,
        today=datetime.now().strftime('%A, %B %d, %Y'),
    )


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
        if not age.isdigit() or not (0 < int(age) < 100):
            flash('Age must be a number between 1 and 99.', 'error')
            return render_template('register.html')

        patient_code = 'PT-' + uuid.uuid4().hex[:8].upper()
        new_id = None
        with closing(get_db()) as db:
            try:
                cur = db.execute(
                    "INSERT INTO patients (patient_code, firstName, lastName, age, "
                    "gender, contact, attendingPhysician) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (patient_code, firstName, lastName, int(age), gender,
                     contact, attendingPhysician)
                )
                db.commit()
                new_id = cur.lastrowid
            except sqlite3.IntegrityError:
                db.rollback()
                flash('Could not save: that patient code already exists. Try again.', 'error')

        if new_id:
            # Show the "patient registered" card with a Schedule Appointment button
            return redirect(url_for('register', registered=new_id))
        return redirect(url_for('register'))

    registered = None
    reg_id = request.args.get('registered', type=int)
    if reg_id:
        with closing(get_db()) as db:
            registered = db.execute(
                "SELECT patient_id, patient_code, firstName, lastName "
                "FROM patients WHERE patient_id = ?", (reg_id,)
            ).fetchone()
    return render_template('register.html', registered=registered)


@app.route('/patients')
@login_required
def patients():
    q = request.args.get('q', '').strip()
    with closing(get_db()) as db:
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
    return render_template('patients.html', patients=rows, q=q)


@app.route('/patients/<int:patient_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_patient(patient_id):
    with closing(get_db()) as db:
        patient = db.execute(
            "SELECT * FROM patients WHERE patient_id = ?", (patient_id,)
        ).fetchone()
        if patient is None:
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
                flash('All fields are required.', 'error')
                return redirect(url_for('edit_patient', patient_id=patient_id))
            if not age.isdigit() or not (0 < int(age) < 100):
                flash('Age must be a number between 1 and 99.', 'error')
                return redirect(url_for('edit_patient', patient_id=patient_id))

            try:
                db.execute(
                    "UPDATE patients SET firstName = ?, lastName = ?, age = ?, "
                    "gender = ?, contact = ?, attendingPhysician = ? "
                    "WHERE patient_id = ?",
                    (firstName, lastName, int(age), gender, contact,
                     attendingPhysician, patient_id)
                )
                db.commit()
                flash('Patient updated.', 'success')
            except sqlite3.Error:
                db.rollback()
                flash('Could not update the patient.', 'error')
            return redirect(url_for('patients'))

        return render_template('edit_patient.html', patient=patient)


@app.route('/patients/<int:patient_id>/delete', methods=['POST'])
@login_required
def delete_patient(patient_id):
    with closing(get_db()) as db:
        try:
            db.execute("DELETE FROM patients WHERE patient_id = ?", (patient_id,))
            db.commit()
            flash('Patient deleted.', 'success')
        except sqlite3.IntegrityError:
            db.rollback()
            flash('Cannot delete: this patient still has appointments or records.', 'error')
    return redirect(url_for('patients'))


# ---------- Appointments ----------

@app.route('/appointments', methods=['GET', 'POST'])
@login_required
def appointments():
    with closing(get_db()) as db:
        if request.method == 'POST':
            patient_id = request.form['patient_id']
            appointment_date = request.form['appointment_date']
            appointment_time = request.form['appointment_time']
            try:
                db.execute(
                    "INSERT INTO appointments (patient_id, appointment_date, "
                    "appointment_time, appointment_status) VALUES (?, ?, ?, 'Scheduled')",
                    (patient_id, appointment_date, appointment_time)
                )
                db.commit()
                flash('Appointment scheduled.', 'success')
            except sqlite3.Error:
                db.rollback()
                flash('Could not schedule the appointment.', 'error')
            return redirect(url_for('appointments'))

        patients_list = db.execute(
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

    # Pre-select a patient when arriving from the "Schedule Appointment" button
    selected_patient_id = request.args.get('patient_id', type=int)

    return render_template('appointments.html', patients=patients_list,
                           appointments=rows,
                           selected_patient_id=selected_patient_id)


@app.route('/update_appointment/<int:appointment_id>', methods=['GET', 'POST'])
@login_required
def update_appointment(appointment_id):
    with closing(get_db()) as db:
        appointment = db.execute(
            "SELECT * FROM appointments WHERE appointment_id = ?", (appointment_id,)
        ).fetchone()
        if appointment is None:
            flash('Appointment not found.', 'error')
            return redirect(url_for('appointments'))

        if request.method == 'POST':
            # Completed appointments are locked, and "Completed" can only be set
            # through the complete_appointment route (which records visit notes).
            if (appointment['appointment_status'] == 'Completed'
                    or request.form['appointment_status'] == 'Completed'):
                flash('Cannot update. Appointment is already completed, or must be '
                      'completed using the Complete button.', 'error')
                return redirect(url_for('appointments'))
            try:
                db.execute(
                    "UPDATE appointments SET patient_id = ?, appointment_date = ?, "
                    "appointment_time = ?, appointment_status = ? "
                    "WHERE appointment_id = ?",
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

        patients_list = db.execute(
            "SELECT patient_id, patient_code, firstName, lastName FROM patients"
        ).fetchall()
        return render_template('update_appointment.html',
                               appointment=appointment, patients=patients_list)


@app.route('/delete_appointment/<int:appointment_id>', methods=['POST'])
@login_required
def delete_appointment(appointment_id):
    with closing(get_db()) as db:
        try:
            db.execute("DELETE FROM appointments WHERE appointment_id = ?",
                       (appointment_id,))
            db.commit()
            flash('Appointment deleted.', 'success')
        except sqlite3.IntegrityError:
            db.rollback()
            flash('Cannot delete: this appointment has a recorded visit.', 'error')
    return redirect(url_for('appointments'))


@app.route('/complete_appointment/<int:appointment_id>', methods=['GET', 'POST'])
@login_required
def complete_appointment(appointment_id):
    with closing(get_db()) as db:
        appointment = db.execute(
            "SELECT a.*, p.firstName, p.lastName "
            "FROM appointments a JOIN patients p ON a.patient_id = p.patient_id "
            "WHERE a.appointment_id = ?", (appointment_id,)
        ).fetchone()

        if appointment is None:
            flash('Appointment not found.', 'error')
            return redirect(url_for('appointments'))
        if appointment['appointment_status'] != 'Scheduled':
            flash('Only scheduled appointments can be completed.', 'error')
            return redirect(url_for('appointments'))

        if request.method == 'POST':
            notes = request.form['notes'].strip()
            if not notes:
                flash('Visit notes are required.', 'error')
                return redirect(url_for('complete_appointment',
                                        appointment_id=appointment_id))

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
            return redirect(url_for('appointments'))

        return render_template('complete_appointment.html', appointment=appointment)


# ---------- Consultation records ----------

@app.route('/consultation_records/')
@login_required
def consultation_records_index():
    with closing(get_db()) as db:
        patients_list = db.execute(
            "SELECT patient_id, patient_code, firstName, lastName "
            "FROM patients ORDER BY lastName"
        ).fetchall()
    return render_template('select_patient.html', patients=patients_list)


@app.route('/consultation_records/<int:patient_id>')
@login_required
def consultation_records(patient_id):
    with closing(get_db()) as db:
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
    with closing(get_db()) as db:
        try:
            db.execute(
                "INSERT INTO consultation_records "
                "(patient_id, consultation_date, diagnosis, notes) VALUES (?, ?, ?, ?)",
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
    with closing(get_db()) as db:
        patient = db.execute(
            "SELECT * FROM patients WHERE patient_id = ?", (patient_id,)
        ).fetchone()
        if patient is None:
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
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", port=8080)