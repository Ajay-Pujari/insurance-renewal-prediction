# Insurance Policy Renewal Prediction System

Insurers lose customers at renewal time without early warning. This system predicts
which policyholders are likely to lapse, so the insurer can run retention outreach early.

Live demo: https://insurance-renewal-2ppi.onrender.com

![Dashboard](docs/dashboard.png)

All data in the system is synthetic. Demo logins are not published here; ask the author.

## Modules
1. Authentication and Role Management
2. Policyholder Data Management
3. Renewal Prediction Engine
4. Retention Campaign Service
5. Analytics Dashboard

## Tech stack
Python, Flask, SQLAlchemy, SQLite, JWT (Flask-JWT-Extended), pandas, scikit-learn,
gunicorn, HTML and JavaScript, Chart.js

## Run it locally
    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt

Copy `.env.example` to `.env` and set `JWT_SECRET_KEY` to a random value:

    python -c "import secrets; print(secrets.token_hex(32))"

Create the demo data and train the model:

    python seed_data.py          # 500 policyholders, 500 policies, 6000 payments
    python build_features.py     # builds policy_features.csv
    python train_model.py        # trains and saves renewal_model.joblib
    python seed_upcoming.py      # 60 policies expiring soon, outcome unknown

Create the first admin account and start the server:

    python create_admin.py
    python app.py

Open http://127.0.0.1:5000/dashboard and log in.

`python bootstrap.py` does the data setup and creates accounts from environment variables
in one step. It is what the deployed site runs on every start.

## Accounts and roles
- Public sign-up is closed. `POST /register` returns 403 unless `ALLOW_REGISTRATION=1`.
- Admins create and remove agent accounts from the Team accounts panel on the dashboard.
- Admin accounts can only be created with `create_admin.py` or the `ADMIN_*` environment variables.

| Role | Can do |
|---|---|
| Agent | View everything, record whether a customer accepted or declined an offer |
| Admin | Everything an agent can, plus run campaigns, record final renewal outcomes and manage agents |

Permissions are enforced by the API, not just by hiding buttons. An agent who calls an
admin route directly still gets "Access denied". Removing an account also invalidates
that account's login token immediately.

## Dashboard
A web page that calls the API with the user's login token. It shows summary cards, four
charts (risk of upcoming renewals, policies by type, payments by status, renewal rate by
offer type) and a work list of upcoming renewals, riskiest first. The Privacy Policy and
Terms and Conditions pages are at `/privacy` and `/terms`.

## API endpoints
| Method | Route | Access |
|---|---|---|
| POST | /register | closed unless ALLOW_REGISTRATION=1 (creates agents only) |
| POST | /login | public (returns JWT) |
| GET | /profile | any logged-in user |
| GET | /admin/users | admin only |
| POST | /admin/agents | admin only |
| DELETE | /admin/users/<id> | admin only (agent accounts only) |
| POST | /policyholders | admin only |
| GET | /policyholders?page=1&per_page=20&city=... | logged-in |
| GET | /policyholders/summary | logged-in |
| GET | /policyholders/<id> | logged-in |
| POST, GET | /policyholders/<id>/policies | POST admin only, GET logged-in |
| POST, GET | /policies/<id>/payments | POST admin only, GET logged-in |
| GET | /policies/<id>/predict | logged-in |
| GET | /renewals/upcoming?days=60&risk=high | logged-in |
| POST | /campaigns/run | admin only |
| GET | /campaigns?risk=...&status=... | logged-in |
| PATCH | /campaigns/<id>/response | logged-in |
| POST | /policies/<id>/renewal | admin only |
| GET | /campaigns/stats | logged-in |
| GET | /dashboard, /privacy, /terms | public pages (data needs login) |

## Prediction model
Random Forest classifier (scikit-learn pipeline with one-hot encoding). Features: age,
gender, city, policy type, premium, sum assured, late payments, missed payments and
average days late. The target is whether the policy was renewed.

| Measure | Result |
|---|---|
| Baseline (always guess "renewed") | 63% |
| Test accuracy (100 unseen policies) | 78% |
| ROC-AUC, 5-fold cross-validation | 0.75 |

Predictions return a renewal probability and a risk level: high below 50%,
medium 50-70%, low above 70%.

## Retention campaigns
Policies that are about to expire and rated high or medium risk get an offer matched to the
likely reason for leaving. Low-risk policies get no offer, and a policy is never contacted twice.

| Risk | Situation | Offer |
|---|---|---|
| High | 4+ late or 2+ missed payments | Flexible payment dates + 7-day grace period |
| High | Premium over 25,000 | 10% renewal discount |
| High | Anything else | Personal call + 5% loyalty discount |
| Medium | 2+ late payments | Auto-pay setup + 3% discount |
| Medium | Anything else | Early reminder + 3% loyalty discount |

Customer responses (accepted or declined) and final outcomes (renewed or lapsed) are recorded,
and `/campaigns/stats` reports acceptance rate, renewal rates, and actual renewals against the
number the model expected without any offer.

## Dataset
Synthetic data generated by `seed_data.py`. Late and missed payments, young age and high
premiums lower the chance of renewal. Because the data is synthetic, the scores above show
that the model can find these built-in patterns, not how it would perform on real customers.

`simulate_responses.py` invents customer responses and makes accepted offers raise the chance
of renewal. It only demonstrates the tracking pipeline; it is not evidence that real offers work.

## Deployment (Render)
| Setting | Value |
|---|---|
| Build command | `pip install -r requirements.txt` |
| Start command | `python bootstrap.py && gunicorn app:app --workers 1 --timeout 120` |
| Python version | set in `.python-version` |

Environment variables: `JWT_SECRET_KEY` (required), `ADMIN_NAME`, `ADMIN_EMAIL`,
`ADMIN_PASSWORD`, and optionally `AGENT_NAME`, `AGENT_EMAIL`, `AGENT_PASSWORD` for a demo
agent. Real values are set on the host and never committed. Debug mode is off unless
`FLASK_DEBUG=1`.

## Security notes
- Passwords are stored as salted hashes.
- Login tokens are signed with a secret from the environment and expire after one hour.
- Roles are checked on the server for every protected route.
- The `.env` file is ignored by git.

## Known limitations
- There is no limit on login attempts yet.
- On the free hosting tier the service sleeps after a quiet period, so the first request can
  be slow, and the database is rebuilt on every start. Accounts created on the live site are
  removed when it restarts. A real deployment would need a persistent database.
- The model is trained once on synthetic data and is not retrained automatically.
- Campaign sending is simulated: offers are recorded but no email or SMS is sent.
- The dashboard loads Chart.js from a CDN, so it needs an internet connection.

## Author
Developed by Ajay Pujari.