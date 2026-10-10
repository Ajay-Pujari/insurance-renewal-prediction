import random
from datetime import date, timedelta
from app import app, db, Policyholder, Policy, Payment

random.seed(42)  # same data every time you run it

FIRST = ["Anita", "Ravi", "Priya", "Suresh", "Kavya", "Arjun", "Meena",
         "Rahul", "Divya", "Kiran", "Sneha", "Vikram", "Lakshmi", "Manoj"]
LAST = ["Rao", "Reddy", "Sharma", "Naidu", "Kumar", "Patel", "Iyer", "Singh"]
CITIES = ["Hyderabad", "Bengaluru", "Chennai", "Kurnool",
          "Vijayawada", "Mumbai", "Delhi", "Pune"]

# policy type -> (min premium, max premium) per year
POLICY_TYPES = {"health": (8000, 30000), "motor": (5000, 20000),
                "life": (15000, 60000), "home": (6000, 25000)}

# payment habit -> (chance of paying late, chance of missing)
HABITS = {"good": (0.05, 0.01), "average": (0.20, 0.05), "poor": (0.40, 0.20)}


def make_payments(policy, start, premium, habit):
    """Create 12 monthly payments. Returns (late_count, missed_count)."""
    late_rate, missed_rate = HABITS[habit]
    late = missed = 0
    for month in range(12):
        due = start + timedelta(days=30 * month)
        roll = random.random()
        if roll < missed_rate:
            paid = None                                    # never paid
        elif roll < missed_rate + late_rate:
            paid = due + timedelta(days=random.randint(3, 15))   # paid late
        else:
            paid = due - timedelta(days=random.randint(0, 5))    # paid on time

        # same rule as the add_payment route
        if paid is None:
            status = "missed"
            missed += 1
        elif paid <= due:
            status = "on_time"
        else:
            status = "late"
            late += 1

        Payment(policy=policy, due_date=due, paid_date=paid,
                amount=round(premium / 12, 2), status=status)
    return late, missed


def seed(n=500):
    with app.app_context():
        # Wipe old policyholder data (your hand-typed tests). Users are NOT touched.
        Payment.query.delete()
        Policy.query.delete()
        Policyholder.query.delete()
        db.session.commit()

        for i in range(1, n + 1):
            age = random.randint(21, 70)
            first, last = random.choice(FIRST), random.choice(LAST)
            holder = Policyholder(
                name=f"{first} {last}", age=age,
                gender=random.choice(["M", "F"]),
                city=random.choice(CITIES),
                email=f"{first}.{last}{i}@example.com".lower(),
            )

            ptype = random.choice(list(POLICY_TYPES))
            low, high = POLICY_TYPES[ptype]
            premium = random.randint(low, high)
            start = date(2023, 1, 1) + timedelta(days=random.randint(0, 900))
            habit = random.choices(["good", "average", "poor"],
                                   weights=[60, 30, 10])[0]

            policy = Policy(
                policyholder=holder, policy_type=ptype,
                premium_amount=premium,
                sum_assured=premium * random.randint(20, 60),
                start_date=start, end_date=start + timedelta(days=365),
            )
            late, missed = make_payments(policy, start, premium, habit)

            # The hidden pattern the ML model will learn later
            chance = 0.85 - 0.07 * late - 0.15 * missed
            if age < 30:
                chance -= 0.05
            if premium > 25000:
                chance -= 0.08
            chance = max(0.05, min(0.95, chance))
            policy.renewed = random.random() < chance

            db.session.add(holder)

        db.session.commit()

        total = Policy.query.count()
        renewed = Policy.query.filter_by(renewed=True).count()
        print(f"Policyholders: {Policyholder.query.count()}")
        print(f"Policies:      {total}")
        print(f"Payments:      {Payment.query.count()}")
        print(f"Renewed:       {renewed} of {total} ({renewed / total:.0%})")


if __name__ == "__main__":
    seed()