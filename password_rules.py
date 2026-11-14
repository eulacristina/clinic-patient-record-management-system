import re

def validate_password(password):
    """Returns a list of problems. An empty list means the password is valid."""
    errors = []

    if len(password) < 8:
        errors.append("Must be at least 8 characters long.")
    if len(password) > 64:
        errors.append("Must be at most 64 characters long.")
    if not re.search(r"[A-Z]", password):
        errors.append("Must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        errors.append("Must contain at least one lowercase letter.")
    if not re.search(r"\d", password):
        errors.append("Must contain at least one number.")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-]", password):
        errors.append("Must contain at least one special character.")
    if " " in password:
        errors.append("Must not contain spaces.")

    return errors