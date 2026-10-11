import os
from datetime import date, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template, redirect
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt, get_jwt_identity, verify_jwt_in_request,
)
import joblib
import pandas as pd

load_dotenv()  # reads the .env file

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///renewal.db"

secret = os.environ.get("JWT_SECRET_KEY")
if not secret:
    raise RuntimeError("JWT_SECRET_KEY is not set. Add it to your .env file.")
app.config["JWT_SECRET_KEY"] = secret
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)

db = SQLAlchemy(app)
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

class Campaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    policy_id = db.Column(db.Integer, db.ForeignKey("policy.id"), nullable=False)
    risk_level = db.Column(db.String(10), nullable=False)
    renewal_probability = db.Column(db.Float, nullable=False)  # score at the time
    offer_type = db.Column(db.String(30), nullable=False)
    offer_detail = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="sent")  # sent, accepted, declined
    outcome = db.Column(db.String(20))  # renewed or lapsed; empty until known
    created_at = db.Column(db.Date, nullable=False, default=date.today)
    policy = db.relationship("Policy", backref="campaigns")


@app.route("/")
def home():
    return redirect("/dashboard")


@app.route("/register", methods=["POST"])


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name or not email or not password:
        return jsonify({"error": "name, email and password are required"}), 400
    if "@" not in email or len(email) > 120:
        return jsonify({"error": "Enter a valid email address"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 400

    # The caller can never choose a role: everyone who registers is an agent
    new_user = User(
        name=name,
        email=email,
        password=generate_password_hash(password),
        role="agent",
    )
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message": "User registered successfully"}), 201


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()

    # Wrong email OR wrong password -> same message (don't reveal which)
    if not user or not check_password_hash(user.password, password):
        return jsonify({"error": "Invalid email or password"}), 401

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
    decided = Policy.query.filter(Policy.renewed.isnot(None)).count()

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

def choose_offer(features, level):
    """Pick an offer that matches the likely reason for leaving.
    Returns (offer_type, offer_detail), or None if no offer is needed."""
    if level == "high":
        if features["missed_payments"] >= 2 or features["late_payments"] >= 4:
            return ("flexible_payment",
                    "Flexible payment dates plus a 7-day grace period")
        if features["premium_amount"] > 25000:
            return ("premium_discount", "10% discount on the renewal premium")
        return ("personal_call",
                "Personal call from a retention agent plus a 5% loyalty discount")
    if level == "medium":
        if features["late_payments"] >= 2:
            return ("auto_pay", "Set up auto-pay and get a 3% discount")
        return ("reminder_offer",
                "Early renewal reminder with a 3% loyalty discount")
    return None  # low risk: no offer

def campaign_to_dict(c):
    return {
        "campaign_id": c.id,
        "policy_id": c.policy_id,
        "name": c.policy.policyholder.name,
        "policy_type": c.policy.policy_type,
        "end_date": c.policy.end_date.isoformat(),
        "risk_level": c.risk_level,
        "renewal_probability": c.renewal_probability,
        "offer_type": c.offer_type,
        "offer_detail": c.offer_detail,
        "status": c.status,
        "outcome": c.outcome,
        "created_at": c.created_at.isoformat(),
    }


@app.route("/campaigns/run", methods=["POST"])
@role_required("admin")
def run_campaigns():
    if renewal_model is None:
        return jsonify({"error": "Model not trained yet. Run train_model.py"}), 503

    data = request.get_json(silent=True) or {}
    days = data.get("days", 60)
    today = date.today()

    # Policies that expire soon and whose outcome is not known yet
    policies = Policy.query.filter(
        Policy.renewed.is_(None),
        Policy.end_date >= today,
        Policy.end_date <= today + timedelta(days=days),
    ).all()

    created, skipped_low, already = [], 0, 0
    if policies:
        feats = [policy_features(p) for p in policies]
        probs = renewal_model.predict_proba(pd.DataFrame(feats))[:, 1]

        for p, f, prob in zip(policies, feats, probs):
            level = risk_level(float(prob))
            offer = choose_offer(f, level)
            if offer is None:            # low risk: no offer needed
                skipped_low += 1
                continue
            if p.campaigns:              # already contacted: don't repeat
                already += 1
                continue
            campaign = Campaign(
                policy_id=p.id, risk_level=level,
                renewal_probability=round(float(prob), 3),
                offer_type=offer[0], offer_detail=offer[1],
            )
            db.session.add(campaign)
            created.append(campaign)
        db.session.commit()

    return jsonify({
        "created": len(created),
        "skipped_low_risk": skipped_low,
        "already_contacted": already,
        "campaigns": [campaign_to_dict(c) for c in created],
    }), 201


@app.route("/campaigns", methods=["GET"])
@jwt_required()
def list_campaigns():
    query = Campaign.query
    risk = request.args.get("risk")
    status = request.args.get("status")
    if risk:
        query = query.filter_by(risk_level=risk)
    if status:
        query = query.filter_by(status=status)

    campaigns = query.order_by(Campaign.renewal_probability).all()  # riskiest first
    return jsonify({"count": len(campaigns),
                    "items": [campaign_to_dict(c) for c in campaigns]})
@app.route("/campaigns/<int:campaign_id>/response", methods=["PATCH"])
@jwt_required()
def respond_to_campaign(campaign_id):
    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return jsonify({"error": "Campaign not found"}), 404

    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in ("accepted", "declined"):
        return jsonify({"error": "status must be 'accepted' or 'declined'"}), 400

    campaign.status = status
    db.session.commit()
    return jsonify(campaign_to_dict(campaign))


@app.route("/policies/<int:policy_id>/renewal", methods=["POST"])
@role_required("admin")
def record_outcome(policy_id):
    policy = db.session.get(Policy, policy_id)
    if not policy:
        return jsonify({"error": "Policy not found"}), 404
    if policy.renewed is not None:
        return jsonify({"error": "Outcome already recorded for this policy"}), 400

    data = request.get_json(silent=True) or {}
    renewed = data.get("renewed")
    if not isinstance(renewed, bool):
        return jsonify({"error": "renewed must be true or false"}), 400

    policy.renewed = renewed
    for c in policy.campaigns:          # copy the result onto every campaign
        c.outcome = "renewed" if renewed else "lapsed"
    db.session.commit()

    return jsonify({
        "policy_id": policy.id,
        "renewed": policy.renewed,
        "campaigns_updated": len(policy.campaigns),
    })

@app.route("/campaigns/stats", methods=["GET"])
@jwt_required()
def campaign_stats():
    campaigns = Campaign.query.all()
    accepted = [c for c in campaigns if c.status == "accepted"]
    declined = [c for c in campaigns if c.status == "declined"]
    waiting = [c for c in campaigns if c.status == "sent"]
    known = [c for c in campaigns if c.outcome is not None]  # final result known

    def rate(part, whole):
        return round(part / whole, 3) if whole else None

    def renewal_rate(group):
        done = [c for c in group if c.outcome is not None]
        return rate(sum(1 for c in done if c.outcome == "renewed"), len(done))

    # Results for each type of offer
    by_offer = {}
    for c in campaigns:
        row = by_offer.setdefault(c.offer_type, {
            "sent": 0, "accepted": 0, "outcomes_known": 0, "renewed": 0})
        row["sent"] += 1
        if c.status == "accepted":
            row["accepted"] += 1
        if c.outcome is not None:
            row["outcomes_known"] += 1
            if c.outcome == "renewed":
                row["renewed"] += 1
    for row in by_offer.values():
        row["renewal_rate"] = rate(row["renewed"], row["outcomes_known"])

    # The model's scores say how many would renew WITHOUT any offer
    expected = sum(c.renewal_probability for c in known)
    actual = sum(1 for c in known if c.outcome == "renewed")

    return jsonify({
        "campaigns_total": len(campaigns),
        "awaiting_response": len(waiting),
        "accepted": len(accepted),
        "declined": len(declined),
        "acceptance_rate": rate(len(accepted), len(accepted) + len(declined)),
        "outcomes_known": len(known),
        "renewal_rate_accepted": renewal_rate(accepted),
        "renewal_rate_declined": renewal_rate(declined),
        "expected_renewals_without_offer": round(expected, 1),
        "actual_renewals": actual,
        "extra_renewals": round(actual - expected, 1),
        "by_offer_type": by_offer,
    })

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

# ---- Details shown on the legal pages. Change these before publishing. ----
SITE_NAME = "Insurance Renewal Prediction System"
OPERATOR_NAME = "Ajay Pujari"
CONTACT_EMAIL = "ajaypujari170@gmail.com"
LEGAL_UPDATED = "11 October 2026"


@app.context_processor
def inject_site_info():
    # Makes these values available inside every template
    return {"site_name": SITE_NAME, "operator_name": OPERATOR_NAME,
            "contact_email": CONTACT_EMAIL, "updated": LEGAL_UPDATED}


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")