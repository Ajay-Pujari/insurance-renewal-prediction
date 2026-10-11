import getpass
from werkzeug.security import generate_password_hash
from app import app, db, User


def main():
    name = input("Admin name: ").strip()
    email = input("Admin email: ").strip().lower()
    password = getpass.getpass("Password (at least 12 characters): ")

    if not name or "@" not in email:
        print("A name and a valid email are required.")
        return
    if len(password) < 12:
        print("Password is too short. Nothing was created.")
        return

    with app.app_context():
        if User.query.filter_by(email=email).first():
            print("That email already has an account. Nothing was changed.")
            return
        db.session.add(User(name=name, email=email, role="admin",
                            password=generate_password_hash(password)))
        db.session.commit()
        print("Admin created:", email)


if __name__ == "__main__":
    main()