"""Statistical anomaly layer — Phase 5.

Catches outliers the rule-based checks miss (targets planted anomaly A7):
an expense far outside the normal range for its account category.
"""

from __future__ import annotations

import csv
import sqlite3
from collections import defaultdict

MODIFIED_Z_THRESHOLD = 3.5  # standard cutoff for the median/MAD "modified z-score" method


def find_statistical_outliers(conn: sqlite3.Connection, method: str = "zscore") -> list[dict]:
    """method: 'zscore' (median/MAD-based "modified z-score" — robust to the very
    outlier it's trying to detect) or 'isolation_forest'."""
    rows = conn.execute(
        """SELECT li.line_item_id, li.account_code, li.line_amount, i.invoice_date, c.name
           FROM line_items li
           JOIN invoices i ON li.invoice_id = i.invoice_id
           JOIN contacts c ON c.contact_id = i.contact_id
           WHERE i.invoice_type = 'ACCPAY' AND li.line_amount IS NOT NULL"""
    ).fetchall()

    by_account: dict[str, list[tuple]] = defaultdict(list)
    for row in rows:
        by_account[row[1]].append(row)

    if method == "isolation_forest":
        return _find_outliers_isolation_forest(by_account)
    return _find_outliers_modified_zscore(by_account)


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _find_outliers_modified_zscore(by_account: dict[str, list[tuple]]) -> list[dict]:
    flagged = []
    for account_code, items in by_account.items():
        if len(items) < 3:
            continue  # not enough history to establish "normal" for this account
        amounts = [item[2] for item in items]
        median = _median(amounts)
        mad = _median([abs(a - median) for a in amounts])

        for line_item_id, _, amount, date, name in items:
            if mad == 0:
                # Every other value in this account is identical — any deviation stands out,
                # since there's no natural spread to divide by.
                is_outlier = amount != median
                modified_z = float("inf") if is_outlier else 0.0
            else:
                modified_z = 0.6745 * (amount - median) / mad
                is_outlier = abs(modified_z) > MODIFIED_Z_THRESHOLD

            if is_outlier:
                flagged.append(
                    {
                        "target_anomaly_id": "A7",
                        "contact_name": name,
                        "amount": amount,
                        "date": date,
                        "record_id": line_item_id,
                        "reason": (
                            f"{name}'s £{amount:.2f} line on account {account_code} is far outside "
                            f"the normal range for that account (median £{median:.2f}); "
                            f"modified z-score {modified_z:.1f}."
                        ),
                    }
                )
    return flagged


def _find_outliers_isolation_forest(by_account: dict[str, list[tuple]]) -> list[dict]:
    from sklearn.ensemble import IsolationForest

    flagged = []
    for account_code, items in by_account.items():
        if len(items) < 4:
            continue
        amounts = [[item[2]] for item in items]
        model = IsolationForest(contamination="auto", random_state=0)
        predictions = model.fit_predict(amounts)

        for (line_item_id, _, amount, date, name), prediction in zip(items, predictions):
            if prediction == -1:
                flagged.append(
                    {
                        "target_anomaly_id": "A7",
                        "contact_name": name,
                        "amount": amount,
                        "date": date,
                        "record_id": line_item_id,
                        "reason": (
                            f"{name}'s £{amount:.2f} line on account {account_code} was flagged as an "
                            f"outlier by IsolationForest relative to other spend on that account."
                        ),
                    }
                )
    return flagged


def _clean_contact(raw: str) -> str:
    """Strip parenthetical asides from the answer key's contact column,
    e.g. 'Amazon Business (one-off contact; ...)' -> 'Amazon Business'."""
    return raw.split(" (")[0].strip()


def score_against_answer_key(detected: list[dict], answer_key_path: str) -> dict:
    """Compare detector output to the private planted-anomaly answer key.

    Returns precision/recall counts — never round this up, per the plan.
    """
    with open(answer_key_path, newline="") as f:
        answer_key = list(csv.DictReader(f))

    caught_ids: list[str] = []
    missed: list[dict] = []
    false_positives: list[dict] = []

    for entry in answer_key:
        anomaly_id = entry["id"]
        expected_contact = _clean_contact(entry["contact"]).lower()

        candidates = [d for d in detected if d["target_anomaly_id"] == anomaly_id]
        matches = [d for d in candidates if expected_contact in d["contact_name"].lower()]
        non_matches = [d for d in candidates if expected_contact not in d["contact_name"].lower()]

        if matches:
            caught_ids.append(anomaly_id)
        else:
            missed.append({"id": anomaly_id, "type": entry["type"], "description": entry["description"]})

        false_positives.extend(
            {"target_anomaly_id": anomaly_id, **d} for d in non_matches
        )

    total = len(answer_key)
    caught = len(caught_ids)
    fp_count = len(false_positives)

    return {
        "total_planted_anomalies": total,
        "caught": caught,
        "caught_ids": caught_ids,
        "missed": missed,
        "false_positive_count": fp_count,
        "false_positives": false_positives,
        "precision": round(caught / (caught + fp_count), 3) if (caught + fp_count) else None,
        "recall": round(caught / total, 3) if total else None,
    }


def score_against_planted_records(detected: list[dict], planted_path: str) -> dict:
    """Score detector output against a planted-record list (synthetic dataset).

    Unlike `score_against_answer_key` (which matches on contact name), this matches on the exact
    record ID, because the synthetic set plants many anomalies per contact. A detection counts as
    caught only if its rule ID *and* record ID both match a planted anomaly; every other flag is
    a false positive.
    """
    with open(planted_path, newline="") as f:
        planted = list(csv.DictReader(f))

    planted_keys = {(p["id"], p["record_id"]) for p in planted}
    detected_keys = {(d["target_anomaly_id"], d["record_id"]) for d in detected}

    caught_keys = planted_keys & detected_keys
    false_positive_keys = detected_keys - planted_keys

    by_type = {}
    for anomaly_id in sorted({p["id"] for p in planted}):
        total = sum(1 for k in planted_keys if k[0] == anomaly_id)
        caught = sum(1 for k in caught_keys if k[0] == anomaly_id)
        fps = sum(1 for k in false_positive_keys if k[0] == anomaly_id)
        by_type[anomaly_id] = {"planted": total, "caught": caught, "false_positives": fps}

    total, caught, fp_count = len(planted_keys), len(caught_keys), len(false_positive_keys)
    return {
        "total_planted_anomalies": total,
        "caught": caught,
        "false_positive_count": fp_count,
        "precision": round(caught / (caught + fp_count), 3) if (caught + fp_count) else None,
        "recall": round(caught / total, 3) if total else None,
        "by_type": by_type,
    }
