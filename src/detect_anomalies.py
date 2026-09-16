"""Phase 5 entrypoint: run every anomaly check against the local database and
score the combined output against the private answer key.

Run with: python -m src.detect_anomalies
"""

from __future__ import annotations

import json
import sqlite3

from src.anomaly.rules import (
    find_duplicate_invoices,
    find_duplicate_payments,
    find_threshold_adjacent_round_amounts,
    find_vat_code_mismatches,
    find_weekend_or_holiday_postings,
)
from src.anomaly.statistical import find_statistical_outliers, score_against_answer_key
from src.db.load import DB_PATH
from src.reconciliation.matcher import build_reconciliation_report, match_bank_transactions

ANSWER_KEY_PATH = "data/anomaly_answer_key.csv"


def _unmatched_bank_lines_as_a6(conn: sqlite3.Connection) -> list[dict]:
    """A6 is Phase 4's job (reconciliation), not a Phase 5 rule — reuse its
    unmatched-item output here so the full detector's score covers all 7 anomalies."""
    report = build_reconciliation_report(match_bank_transactions(conn))
    return [
        {
            "target_anomaly_id": "A6",
            "contact_name": item["contact_name"],
            "amount": item["total"],
            "date": item["date"],
            "record_id": item["bank_transaction_id"],
            "reason": f"Bank line for {item['contact_name']} (£{item['total']:.2f}) has no matching invoice/bill.",
        }
        for item in report["unmatched_items"]
    ]


def main() -> None:
    conn = sqlite3.connect(DB_PATH)

    detected = (
        find_duplicate_invoices(conn)
        + find_vat_code_mismatches(conn)
        + find_threshold_adjacent_round_amounts(conn)
        + find_weekend_or_holiday_postings(conn)
        + find_duplicate_payments(conn)
        + _unmatched_bank_lines_as_a6(conn)
        + find_statistical_outliers(conn)
    )
    conn.close()

    print(f"Detector flagged {len(detected)} item(s) total:\n")
    for item in detected:
        print(f"  [{item['target_anomaly_id']}] {item['reason']}")

    score = score_against_answer_key(detected, ANSWER_KEY_PATH)
    print(f"\n{'=' * 60}\nScore: caught {score['caught']} of {score['total_planted_anomalies']} "
          f"planted anomalies, {score['false_positive_count']} false positive(s)")
    print(f"Precision: {score['precision']}  Recall: {score['recall']}")
    if score["missed"]:
        print("\nMissed:")
        for m in score["missed"]:
            print(f"  [{m['id']}] {m['type']}: {m['description']}")
    if score["false_positives"]:
        print("\nFalse positives:")
        for fp in score["false_positives"]:
            print(f"  [{fp['target_anomaly_id']}] {fp['reason']}")

    print(f"\nFull JSON:\n{json.dumps(score, indent=2)}")


if __name__ == "__main__":
    main()
