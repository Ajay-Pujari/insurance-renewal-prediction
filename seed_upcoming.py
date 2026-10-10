import random
from datetime import date, timedelta
from app import app, db, Policyholder, Policy, Payment
from seed_data import FIRST, LAST, CITIES, POLICY_TYPES, HABITS

random.seed(7)


def make_payments_so_far(policy, start, premium, habit):
    """Payments due in the past get a result; future ones stay 'pending'."""
    late_rate, missed_rate = HABITS[habit]
    today = date.today()
    for month in range(12):
        due = start + timedelta(days=30 * month)
        paid, status = None, "pending"
        if due <= today:
            roll = random.random()
            if roll < missed_rate:
                paid, status = None, "missed"
            elif roll < missed_rate + late_rate:
                paid, status = due + timedelta(days=random.randint(3, 15)), "late"
            else:
                paid, status = due - timedelta(days=random.randint(0, 5)), "on_time"
            if paid and paid > today:      # can't have paid in the future
                paid, status = None, "pending"
        Payment(policy=policy, due_date=due, paid_date=paid,
                amount=round(premium / 12, 2), status=status)


def seed_upcoming(n=60):
    with app.app_context():
        if Policy.query.filter(Policy.renewed.is_(None)).count() > 0:
            print("Upcoming policies already exist. Nothing added.")
            return

        for i in range(1, n + 1):
            first, last = random.choice(FIRST), random.choice(LAST)
            holder = Policyholder(
                name=f"{first} {last}", age=random.randint(21, 70),
                gender=random.choice(["M", "F"]), city=random.choice(CITIES),
                email=f"upcoming{i}.{first}.{last}@example.com".lower(),
            )
            ptype = random.choice(list(POLICY_TYPES))
            low, high = POLICY_TYPES[ptype]
            premium = random.randint(low, high)
            end = date.today() + timedelta(days=random.randint(5, 60))
            start = end - timedelta(days=365)
            habit = random.choices(["good", "average", "poor"], weights=[60, 30, 10])[0]

            # renewed is left empty on purpose: the outcome is not known yet
            policy = Policy(
                policyholder=holder, policy_type=ptype, premium_amount=premium,
                sum_assured=premium * random.randint(20, 60),
                start_date=start, end_date=end,
            )
            make_payments_so_far(policy, start, premium, habit)
            db.session.add(holder)

        db.session.commit()
        print(f"Added {n} policies expiring in the next 60 days (outcome unknown).")


if __name__ == "__main__":
    seed_upcoming()