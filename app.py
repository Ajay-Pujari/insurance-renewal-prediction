from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt, get_jwt_identity, verify_jwt_in_request,
)
from functools import wraps

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///renewal.db"
app.config["JWT_SECRET_KEY"] = "change-this-secret-later"
jwt = JWTManager(app)
db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="agent")


@app.route("/")


def home():
    return "Insurance Renewal System is running!"


@app.route("/register", methods=["POST"])


def register():
    data = request.get_json()  # read the JSON sent by the client

    # Reject if this email is already used
    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"error": "Email already registered"}), 400

    new_user = User(
        name=data["name"],
        email=data["email"],
        password=generate_password_hash(data["password"]),  # store the hash
        role=data.get("role", "agent"),  # default role is agent
    )
    db.session.add(new_user)   # stage the new row
    db.session.commit()        # save it to the database

    return jsonify({"message": "User registered successfully"}), 201


@app.route("/login", methods=["POST"])


def login():
    data = request.get_json()

    user = User.query.filter_by(email=data["email"]).first()

    # Wrong email OR wrong password -> same message (don't reveal which)
    if not user or not check_password_hash(user.password, data["password"]):
        return jsonify({"error": "Invalid email or password"}), 401

    # Create the token; store the user's id and role inside it
    token = create_access_token(
        identity=str(user.id),
        additional_claims={"role": user.role},
    )

    return jsonify({"access_token": token, "role": user.role}), 200


# A reusable "bouncer": checks the token AND the role inside it
def role_required(required_role):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()          # is there a valid token?
            claims = get_jwt()               # read what's inside the token
            if claims.get("role") != required_role:
                return jsonify({"error": "Access denied"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# Any logged-in user can see their own profile
@app.route("/profile")
@jwt_required()
def profile():
    user = db.session.get(User, int(get_jwt_identity()))
    return jsonify({"name": user.name, "email": user.email, "role": user.role})


# Only admins can see the list of all users
@app.route("/admin/users")
@role_required("admin")
def list_users():
    users = User.query.all()
    return jsonify([
        {"id": u.id, "name": u.name, "email": u.email, "role": u.role}
        for u in users
    ])


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)