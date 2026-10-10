import random
from app import app, db, Campaign

random.seed(11)

# Chance that a customer accepts each type of offer (invented numbers)
ACCEPT_CHANCE = {"flexible_payment": 0.60, "premium_discount": 0.65,
                 "personal_call": 0.55, "auto_pay": 0.50, "reminder_offer": 0.40}
ACCEPT_BOOST = 0.25   # accepting raises the chance of renewing by 25 points
FRACTION = 0.7        # only 70% have answered; the rest stay "waiting"


def simulate():
    with app.app_context():
        done = 0
        for c in Campaign.query.filter_by(status="sent").all():
            policy = c.policy
            if policy.renewed is not None:      # outcome already recorded by hand
                continue
            if random.random() > FRACTION:      # this customer hasn't answered yet
                continue

            accepted = random.random() < ACCEPT_CHANCE[c.offer_type]
            c.status = "accepted" if accepted else "declined"

            chance = c.renewal_probability + (ACCEPT_BOOST if accepted else 0)
            renewed = random.random() < min(chance, 0.97)
            policy.renewed = renewed
            for other in policy.campaigns:
                other.outcome = "renewed" if renewed else "lapsed"
            done += 1

        db.session.commit()
        print(f"Simulated responses and outcomes for {done} campaigns.")


if __name__ == "__main__":
    simulate()