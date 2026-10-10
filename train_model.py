import json
import joblib
import pandas as pd
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.metrics import (accuracy_score, roc_auc_score,
                             classification_report, confusion_matrix)

NUMERIC = ["age", "premium_amount", "sum_assured",
           "late_payments", "missed_payments", "avg_days_late"]
CATEGORICAL = ["gender", "city", "policy_type"]
TARGET = "renewed"
# Left out on purpose: policy_id (just a label) and total_payments (always 12)

df = pd.read_csv("policy_features.csv")
X = df[NUMERIC + CATEGORICAL]
y = df[TARGET]

# 80% to learn from, 20% kept secret for the final exam
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

# Models only understand numbers, so turn words (city, gender...) into 0/1 columns
preprocess = ColumnTransformer(
    [("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL)],
    remainder="passthrough",  # numeric columns pass through unchanged
)

# A pipeline = preprocessing + model packed together as one object
model = Pipeline([
    ("prep", preprocess),
    ("rf", RandomForestClassifier(n_estimators=200, max_depth=6, random_state=42)),
])

model.fit(X_train, y_train)

# ---- The final exam ----
pred = model.predict(X_test)
proba = model.predict_proba(X_test)[:, 1]  # probability of renewing

baseline = max(y_test.mean(), 1 - y_test.mean())
print(f"Baseline (always guess the majority): {baseline:.1%}")
print(f"Model accuracy:                       {accuracy_score(y_test, pred):.1%}")
print(f"ROC-AUC:                              {roc_auc_score(y_test, proba):.3f}")

cv = cross_val_score(model, X, y, cv=5, scoring="roc_auc")
print(f"5-fold ROC-AUC (steadier estimate):   {cv.mean():.3f} +/- {cv.std():.3f}")

print("\nConfusion matrix (rows = real, columns = predicted):")
print("          lapsed  renewed")
print(confusion_matrix(y_test, pred))

print("\n", classification_report(y_test, pred, target_names=["lapsed", "renewed"]))

# ---- Which clues mattered most? ----
names = model.named_steps["prep"].get_feature_names_out()
importance = model.named_steps["rf"].feature_importances_
top = sorted(zip(names, importance), key=lambda t: t[1], reverse=True)[:8]
print("Top clues:")
for name, score in top:
    print(f"  {name.split('__')[-1]:<18} {score:.3f}")

# ---- Save the final model ----
# The exam is over, so retrain on ALL 500 policies before saving.
model.fit(X, y)
joblib.dump(model, "renewal_model.joblib")

# Save the scores too; the dashboard in Module 5 can show them
with open("model_metrics.json", "w") as f:
    json.dump({
        "test_accuracy": round(accuracy_score(y_test, pred), 3),
        "test_roc_auc": round(roc_auc_score(y_test, proba), 3),
        "cv_roc_auc": round(cv.mean(), 3),
        "trained_on_rows": len(df),
        "features": NUMERIC + CATEGORICAL,
    }, f, indent=2)

print("\nSaved renewal_model.joblib and model_metrics.json")