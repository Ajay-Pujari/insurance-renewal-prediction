from datetime import date, timedelta
from sqlalchemy import func
import os
import joblib
import pandas as pd
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
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=2)
jwt = JWTManager(app)
# Load the trained model once, when the server starts
MODEL_PATH = os.path.join(os.path.dirname(__file__), "renewal_model.joblib")
try:
    renewal_model = joblib.load(MODEL_PATH)
except FileNotFoundError:
    renewal_model = None  # run train_model.py first

# Risk bands based on the chance of renewing
HIGH_RISK_BELOW = 0.50    # under 50% -> high risk of lapsing
MEDIUM_RISK_BELOW = 0.70  # 50-70%    -> medium risk
db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="agent")

class Policyholder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    gender = db.Column(db.String(10))
    city = db.Column(db.String(50))
    email = db.Column(db.String(120), unique=True)
    # one policyholder -> many policies
    policies = db.relationship("Policy", backref="policyholder")


class Policy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # foreign key = "this policy belongs to that policyholder"
    policyholder_id = db.Column(
        db.Integer, db.ForeignKey("policyholder.id"), nullable=False
    )
    policy_type = db.Column(db.String(30), nullable=False)  # health, motor, life, home
    premium_amount = db.Column(db.Float, nullable=False)
    sum_assured = db.Column(db.Float, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    renewed = db.Column(db.Boolean)  # True = renewed, False = lapsed, empty = not decided yet
    # one policy -> many payments
    payments = db.relationship("Payment", backref="policy")


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    policy_id = db.Column(db.Integer, db.ForeignKey("policy.id"), nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    paid_date = db.Column(db.Date)  # empty = not paid
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), nullable=False)  # on_time, late, missed


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

@app.route("/policyholders", methods=["POST"])
@role_required("admin")
def add_policyholder():
    data = request.get_json()

    holder = Policyholder(
        name=data["name"],
        age=data["age"],
        gender=data.get("gender"),
        city=data.get("city"),
        email=data.get("email"),
    )
    db.session.add(holder)
    db.session.commit()

    return jsonify({"message": "Policyholder added", "id": holder.id}), 201


@app.route("/policyholders", methods=["GET"])
@jwt_required()


def list_policyholders():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)  # max 100
    city = request.args.get("city")

    query = Policyholder.query
    if city:
        query = query.filter_by(city=city)

    result = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "page": result.page,
        "total_pages": result.pages,
        "total": result.total,
        "items": [
            {"id": h.id, "name": h.name, "age": h.age, "gender": h.gender,
             "city": h.city, "email": h.email}
            for h in result.items
        ],
    })




@app.route("/policyholders/<int:holder_id>", methods=["GET"])
@jwt_required()
def get_policyholder(holder_id):
    holder = db.session.get(Policyholder, holder_id)
    if not holder:
        return jsonify({"error": "Policyholder not found"}), 404

    return jsonify({
        "id": holder.id, "name": holder.name, "age": holder.age,
        "gender": holder.gender, "city": holder.city, "email": holder.email,
        "policy_count": len(holder.policies),  # follows the relationship
    })

@app.route("/policyholders/<int:holder_id>/policies", methods=["POST"])
@role_required("admin")
def add_policy(holder_id):
    holder = db.session.get(Policyholder, holder_id)
    if not holder:
        return jsonify({"error": "Policyholder not found"}), 404

    data = request.get_json()
    policy = Policy(
        policyholder_id=holder.id,
        policy_type=data["policy_type"],
        premium_amount=data["premium_amount"],
        sum_assured=data["sum_assured"],
        start_date=date.fromisoformat(data["start_date"]),  # "2025-01-01"
        end_date=date.fromisoformat(data["end_date"]),
        renewed=data.get("renewed"),  # true / false / leave out if undecided
    )
    db.session.add(policy)
    db.session.commit()

    return jsonify({"message": "Policy added", "id": policy.id}), 201


@app.route("/policyholders/<int:holder_id>/policies", methods=["GET"])
@jwt_required()
def list_policies(holder_id):
    holder = db.session.get(Policyholder, holder_id)
    if not holder:
        return jsonify({"error": "Policyholder not found"}), 404

    return jsonify([
        {"id": p.id, "policy_type": p.policy_type,
         "premium_amount": p.premium_amount, "sum_assured": p.sum_assured,
         "start_date": p.start_date.isoformat(),
         "end_date": p.end_date.isoformat(), "renewed": p.renewed}
        for p in holder.policies
    ])


@app.route("/policies/<int:policy_id>/payments", methods=["POST"])
@role_required("admin")
def add_payment(policy_id):
    policy = db.session.get(Policy, policy_id)
    if not policy:
        return jsonify({"error": "Policy not found"}), 404

    data = request.get_json()
    due = date.fromisoformat(data["due_date"])
    paid = date.fromisoformat(data["paid_date"]) if data.get("paid_date") else None

    # The server works out the status, not the person typing
    if paid is None:
        status = "missed" if due < date.today() else "pending"
    elif paid <= due:
        status = "on_time"
    else:
        status = "late"

    payment = Payment(
        policy_id=policy.id, due_date=due, paid_date=paid,
        amount=data["amount"], status=status,
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({"message": "Payment added", "status": status}), 201


@app.route("/policies/<int:policy_id>/payments", methods=["GET"])
@jwt_required()
def list_payments(policy_id):
    policy = db.session.get(Policy, policy_id)
    if not policy:
        return jsonify({"error": "Policy not found"}), 404

    return jsonify([
        {"id": pay.id, "due_date": pay.due_date.isoformat(),
         "paid_date": pay.paid_date.isoformat() if pay.paid_date else None,
         "amount": pay.amount, "status": pay.status}
        for pay in policy.payments
    ])

@app.route("/policyholders/summary", methods=["GET"])
@jwt_required()
def dataset_summary():
    total_policies = Policy.query.count()
    renewed = Policy.query.filter_by(renewed=True).count()

    by_type = (db.session.query(Policy.policy_type, func.count(Policy.id))
               .group_by(Policy.policy_type).all())
    by_status = (db.session.query(Payment.status, func.count(Payment.id))
                 .group_by(Payment.status).all())
    avg_premium = db.session.query(func.avg(Policy.premium_amount)).scalar()

    return jsonify({
        "policyholders": Policyholder.query.count(),
        "policies": total_policies,
        "renewal_rate": round(renewed / decided, 3) if decided else None,
        "policies_by_type": {t: c for t, c in by_type},
        "payments_by_status": {s: c for s, c in by_status},
        "average_premium": round(avg_premium, 2) if avg_premium else None,
    })

def policy_features(policy):
    """Turn one policy and its history into the clues the model was trained on."""
    holder = policy.policyholder
    payments = policy.payments
    late = sum(1 for p in payments if p.status == "late")
    missed = sum(1 for p in payments if p.status == "missed")
    days_late = [(p.paid_date - p.due_date).days
                 for p in payments if p.status == "late"]
    return {
        "age": holder.age,
        "premium_amount": policy.premium_amount,
        "sum_assured": policy.sum_assured,
        "late_payments": late,
        "missed_payments": missed,
        "avg_days_late": round(sum(days_late) / len(days_late), 1) if days_late else 0,
        "gender": holder.gender,
        "city": holder.city,
        "policy_type": policy.policy_type,
    }


def risk_level(renewal_probability):
    if renewal_probability < HIGH_RISK_BELOW:
        return "high"
    if renewal_probability < MEDIUM_RISK_BELOW:
        return "medium"
    return "low"


@app.route("/policies/<int:policy_id>/predict", methods=["GET"])
@jwt_required()
def predict_policy(policy_id):
    if renewal_model is None:
        return jsonify({"error": "Model not trained yet. Run train_model.py"}), 503

    policy = db.session.get(Policy, policy_id)
    if not policy:
        return jsonify({"error": "Policy not found"}), 404

    features = policy_features(policy)
    prob = float(renewal_model.predict_proba(pd.DataFrame([features]))[0][1])

    return jsonify({
        "policy_id": policy.id,
        "renewal_probability": round(prob, 3),
        "lapse_probability": round(1 - prob, 3),
        "risk_level": risk_level(prob),
        "features_used": features,
        "actual_outcome": policy.renewed,  # empty/null if not decided yet
    })

@app.route("/renewals/upcoming", methods=["GET"])
@jwt_required()
def upcoming_renewals():
    if renewal_model is None:
        return jsonify({"error": "Model not trained yet. Run train_model.py"}), 503

    days = request.args.get("days", 60, type=int)
    risk_filter = request.args.get("risk")      # high / medium / low
    today = date.today()

    policies = Policy.query.filter(
        Policy.renewed.is_(None),               # outcome not known yet
        Policy.end_date >= today,
        Policy.end_date <= today + timedelta(days=days),
    ).all()
    if not policies:
        return jsonify({"count": 0, "items": []})

    # Score everyone in ONE call to the model (much faster than one by one)
    feats = [policy_features(p) for p in policies]
    probs = renewal_model.predict_proba(pd.DataFrame(feats))[:, 1]

    items = []
    for p, f, prob in zip(policies, feats, probs):
        level = risk_level(float(prob))
        if risk_filter and level != risk_filter:
            continue
        items.append({
            "policy_id": p.id,
            "name": p.policyholder.name,
            "city": p.policyholder.city,
            "policy_type": p.policy_type,
            "end_date": p.end_date.isoformat(),
            "days_left": (p.end_date - today).days,
            "late_payments": f["late_payments"],
            "missed_payments": f["missed_payments"],
            "renewal_probability": round(float(prob), 3),
            "risk_level": level,
        })

    items.sort(key=lambda x: x["renewal_probability"])   # riskiest first
    return jsonify({"count": len(items), "items": items})


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)