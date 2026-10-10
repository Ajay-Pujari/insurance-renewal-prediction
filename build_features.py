import pandas as pd
from app import app, Policy


def build_features():
    rows = []
    with app.app_context():
        for policy in Policy.query.all():
            # Only use policies where we already know the outcome
            if policy.renewed is None:
                continue

            holder = policy.policyholder
            payments = policy.payments

            late = sum(1 for p in payments if p.status == "late")
            missed = sum(1 for p in payments if p.status == "missed")
            days_late = [(p.paid_date - p.due_date).days
                         for p in payments if p.status == "late"]

            rows.append({
                "policy_id": policy.id,
                # clues about the person
                "age": holder.age,
                "gender": holder.gender,
                "city": holder.city,
                # clues about the policy
                "policy_type": policy.policy_type,
                "premium_amount": policy.premium_amount,
                "sum_assured": policy.sum_assured,
                # clues from payment history
                "total_payments": len(payments),
                "late_payments": late,
                "missed_payments": missed,
                "avg_days_late": round(sum(days_late) / len(days_late), 1) if days_late else 0,
                # the answer we want to predict (1 = renewed, 0 = lapsed)
                "renewed": int(policy.renewed),
            })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = build_features()
    df.to_csv("policy_features.csv", index=False)
    print(df.head())
    print("\nShape (rows, columns):", df.shape)
    print("\nRenewed counts:")
    print(df["renewed"].value_counts())