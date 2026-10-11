import os
from werkzeug.security import generate_password_hash
from app import app, db, User, Policyholder
import seed_data
import seed_upcoming


def main():
    with app.app_context():
        db.create_all()
        is_empty = Policyholder.query.count() == 0

    # Build the demo data only when the database is empty
    if is_empty:
        seed_data.seed()
        seed_upcoming.seed_upcoming()
        print("Demo data created.")

    # Create the admin account from settings, never from code
    name = os.environ.get("ADMIN_NAME")
    email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD")
    if name and email and password:
        with app.app_context():
            if not User.query.filter_by(email=email).first():
                db.session.add(User(name=name, email=email, role="admin",
                                    password=generate_password_hash(password)))
                db.session.commit()
                print("Admin account created.")


if __name__ == "__main__":
    main()