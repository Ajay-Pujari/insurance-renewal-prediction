import joblib
import pandas as pd

model = joblib.load("renewal_model.joblib")

customers = pd.DataFrame([
    # risky: young, high premium, many late and missed payments
    {"age": 25, "premium_amount": 30000, "sum_assured": 900000,
     "late_payments": 5, "missed_payments": 3, "avg_days_late": 9,
     "gender": "M", "city": "Kurnool", "policy_type": "health"},
    # reliable: middle-aged, no late or missed payments
    {"age": 45, "premium_amount": 10000, "sum_assured": 400000,
     "late_payments": 0, "missed_payments": 0, "avg_days_late": 0,
     "gender": "F", "city": "Hyderabad", "policy_type": "motor"},
])

probs = model.predict_proba(customers)[:, 1]
for label, p in zip(["Risky customer", "Reliable customer"], probs):
    print(f"{label}: {p:.0%} chance of renewing")