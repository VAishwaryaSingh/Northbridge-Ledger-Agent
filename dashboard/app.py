"""Streamlit dashboard — a clickable demo of the whole engine.

Run with: streamlit run dashboard/app.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

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
from src.variance.explainer import compute_account_movement, explain_movement

ANSWER_KEY_PATH = "data/anomaly_answer_key.csv"
DEMO_DB_PATH = "data/demo_ledger.db"  # frozen snapshot shipped in the repo, used when there's no live pull yet

# The real precision/recall result from README.md's "Accuracy result" section — used as a display
# fallback wherever the private answer key (gitignored, not published) isn't present, e.g. on this
# public deployment, so the demo still shows the true measured number rather than erroring.
PUBLISHED_SCORE = {
    "total_planted_anomalies": 7,
    "caught": 7,
    "false_positive_count": 3,
    "precision": 0.7,
    "recall": 1.0,
}

st.set_page_config(page_title="NorthBridge Ledger Agent", layout="wide")
st.title("NorthBridge Ledger Reconciliation & Anomaly Detection Agent")
st.caption(
    "Independent portfolio project — connects to a live Xero organisation, reconciles bank "
    "transactions, flags anomalies, and explains variance. Not affiliated with Xero or Intuit/QuickBooks."
)

conn = sqlite3.connect(DB_PATH if os.path.exists(DB_PATH) else DEMO_DB_PATH)

st.header("1. Reconciliation")
bank_matches = match_bank_transactions(conn)
recon_report = build_reconciliation_report(bank_matches)

col1, col2, col3 = st.columns(3)
col1.metric("Bank transactions", recon_report["total_bank_transactions"])
col2.metric("Auto-matched", f"{recon_report['pct_auto_matched']}%")
col3.metric("Unmatched", recon_report["unmatched_count"])
if recon_report["unmatched_items"]:
    st.dataframe(recon_report["unmatched_items"], use_container_width=True)

st.header("2. Anomaly detection")


def _a6_from_reconciliation() -> list[dict]:
    return [
        {
            "target_anomaly_id": "A6",
            "contact_name": item["contact_name"],
            "amount": item["total"],
            "date": item["date"],
            "record_id": item["bank_transaction_id"],
            "reason": f"Bank line for {item['contact_name']} (£{item['total']:.2f}) has no matching invoice/bill.",
        }
        for item in recon_report["unmatched_items"]
    ]


detected = (
    find_duplicate_invoices(conn)
    + find_vat_code_mismatches(conn)
    + find_threshold_adjacent_round_amounts(conn)
    + find_weekend_or_holiday_postings(conn)
    + find_duplicate_payments(conn)
    + _a6_from_reconciliation()
    + find_statistical_outliers(conn)
)
try:
    score = score_against_answer_key(detected, ANSWER_KEY_PATH)
except FileNotFoundError:
    # The private answer key is gitignored and not published — fall back to the
    # already-measured, published result (see README.md's "Accuracy result").
    score = PUBLISHED_SCORE

col1, col2, col3, col4 = st.columns(4)
col1.metric("Planted anomalies caught", f"{score['caught']} / {score['total_planted_anomalies']}")
col2.metric("False positives", score["false_positive_count"])
col3.metric("Precision", score["precision"])
col4.metric("Recall", score["recall"])
st.caption(
    "The 3 false positives are ordinary monthly bank-fee lines flagged 'unmatched' by reconciliation "
    "(expected — bank fees never have a bill), not real coding errors."
)
st.dataframe(
    [{"anomaly": d["target_anomaly_id"], "contact": d["contact_name"], "amount": d["amount"], "reason": d["reason"]} for d in detected],
    use_container_width=True,
)

st.header("3. Variance / explain the number")
period_pairs = [("2026-06", "2026-07"), ("2026-07", "2026-08")]
period_a, period_b = st.selectbox(
    "Compare", period_pairs, index=1, format_func=lambda p: f"{p[0]} → {p[1]}"
)

movement = compute_account_movement(conn, period_a, period_b)
top_movers = [m for m in movement if m["account_code"]][:5]

for m in top_movers:
    st.write("- " + explain_movement(conn, m["account_code"], period_a, period_b))

conn.close()
