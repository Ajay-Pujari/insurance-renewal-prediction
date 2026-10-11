import os
from werkzeug.security import generate_password_hash
from app import app, db, User, Policyholder
import seed_data
import seed_upcoming


def ensure_account(prefix, role):
    """Create an account from <PREFIX>_NAME, <PREFIX>_EMAIL and <PREFIX>_PASSWORD,
    but only if all three are set and the email is not taken yet."""
    name = os.environ.get(prefix + "_NAME")
    email = (os.environ.get(prefix + "_EMAIL") or "").strip().lower()
    password = os.environ.get(prefix + "_PASSWORD")
    if not (name and email and password):
        return
    with app.app_context():
        if not User.query.filter_by(email=email).first():
            db.session.add(User(name=name, email=email, role=role,
                                password=generate_password_hash(password)))
            db.session.commit()
            print(role.capitalize() + " account created.")


def main():
    with app.app_context():
        db.create_all()
        is_empty = Policyholder.query.count() == 0

    # Build the demo data only when the database is empty
    if is_empty:
        seed_data.seed()
        seed_upcoming.seed_upcoming()
        print("Demo data created.")

    ensure_account("ADMIN", "admin")
    ensure_account("AGENT", "agent")


if __name__ == "__main__":
    main()