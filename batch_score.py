import csv
import logging
import os
import sys
import time
from datetime import date, timedelta

import pandas as pd

from app import app, Policy, policy_features, risk_level, renewal_model

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
REPORT_DIR = os.path.join(BASE_DIR, "reports")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)
LOCK_PATH = os.path.join(LOG_DIR, "batch_score.lock")
STALE_LOCK_SECONDS = 60 * 60   # a lock older than 1 hour is left over from a crash

# Write every message to a log file and to the screen
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "batch_score.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


def acquire_lock():
    """Only one batch run at a time. Returns True if this run got the lock."""
    if os.path.exists(LOCK_PATH):
        age = time.time() - os.path.getmtime(LOCK_PATH)
        if age < STALE_LOCK_SECONDS:
            return False
        logging.warning("Removing a stale lock file (%.0f minutes old)", age / 60)
        os.remove(LOCK_PATH)
    try:
        # O_EXCL makes the operating system refuse if the file already exists
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def release_lock():
    try:
        os.remove(LOCK_PATH)
    except FileNotFoundError:
        pass


def score_upcoming(days):
    """Score every policy that expires soon and has no outcome yet.
    This only reads data. It never creates campaigns."""
    if renewal_model is None:
        raise RuntimeError("Model not trained yet. Run train_model.py")

    today = date.today()
    policies = Policy.query.filter(
        Policy.renewed.is_(None),
        Policy.end_date >= today,
        Policy.end_date <= today + timedelta(days=days),
    ).all()

    rows = []
    if policies:
        feats = [policy_features(p) for p in policies]
        probs = renewal_model.predict_proba(pd.DataFrame(feats))[:, 1]
        for p, f, prob in zip(policies, feats, probs):
            rows.append({
                "policy_id": p.id,
                "customer": p.policyholder.name,
                "policy_type": p.policy_type,
                "end_date": p.end_date.isoformat(),
                "days_left": (p.end_date - today).days,
                "late_payments": f["late_payments"],
                "missed_payments": f["missed_payments"],
                "renewal_probability": round(float(prob), 3),
                "risk_level": risk_level(float(prob)),
                "already_contacted": "yes" if p.campaigns else "no",
            })
    rows.sort(key=lambda r: r["renewal_probability"])   # riskiest first
    return rows


def write_report(rows):
    path = os.path.join(REPORT_DIR, "risk_report_" + date.today().isoformat() + ".csv")
    columns = ["policy_id", "customer", "policy_type", "end_date", "days_left",
               "late_payments", "missed_payments", "renewal_probability",
               "risk_level", "already_contacted"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def main():
    days = 60
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            days = 0
        if not 1 <= days <= 365:
            logging.error("Usage: python batch_score.py [days]  (a whole number from 1 to 365)")
            return 1

    if not acquire_lock():
        logging.warning("Another batch run is already in progress. Skipping this run.")
        return 2

    started = time.time()
    try:
        logging.info("Batch scoring started (policies expiring within %d days)", days)
        with app.app_context():
            rows = score_upcoming(days)
        path = write_report(rows)
        counts = {level: sum(1 for r in rows if r["risk_level"] == level)
                  for level in ("high", "medium", "low")}
        logging.info(
            "Scored %d policies: %d high, %d medium, %d low risk (%.1f seconds)",
            len(rows), counts["high"], counts["medium"], counts["low"],
            time.time() - started,
        )
        logging.info("Report written to %s", path)
        logging.info("No campaigns were created. An admin runs the campaign manually.")
        return 0
    except Exception:
        logging.exception("Batch scoring failed")
        return 1
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())