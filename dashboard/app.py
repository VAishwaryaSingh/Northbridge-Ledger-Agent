"""Streamlit dashboard — a clickable demo of the whole engine, run against two
different ERPs (Xero and QuickBooks) to show the same code works on both.

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
DEMO_DB_PATH = "data/demo_ledger.db"  # frozen Xero snapshot, used when there's no live pull yet
QB_DB_PATH = "data/ledger_quickbooks.db"
QB_DEMO_DB_PATH = "data/demo_ledger_quickbooks.db"  # frozen QuickBooks snapshot

# The real precision/recall result from README.md's "Accuracy result" section — used as a display
# fallback wherever the private answer key (gitignored, not published) isn't present, e.g. on this
# public deployment, so the demo still shows the true measured number rather than erroring.
PUBLISHED_XERO_SCORE = {
    "total_planted_anomalies": 7,
    "caught": 7,
    "false_positive_count": 3,
    "precision": 0.7,
    "recall": 1.0,
}


def _connect(live_path: str, demo_path: str) -> sqlite3.Connection:
    return sqlite3.connect(live_path if os.path.exists(live_path) else demo_path)


def _a6_from_reconciliation(recon_report: dict) -> list[dict]:
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


def render_reconciliation(conn: sqlite3.Connection, heading: str) -> dict:
    st.header(heading)
    recon_report = build_reconciliation_report(match_bank_transactions(conn))

    col1, col2, col3 = st.columns(3)
    col1.metric("Bank transactions", recon_report["total_bank_transactions"])
    col2.metric("Auto-matched", f"{recon_report['pct_auto_matched']}%")
    col3.metric("Unmatched", recon_report["unmatched_count"])
    if recon_report["unmatched_items"]:
        st.dataframe(recon_report["unmatched_items"], use_container_width=True)
    return recon_report


def detect_all(conn: sqlite3.Connection, recon_report: dict) -> list[dict]:
    return (
        find_duplicate_invoices(conn)
        + find_vat_code_mismatches(conn)
        + find_threshold_adjacent_round_amounts(conn)
        + find_weekend_or_holiday_postings(conn)
        + find_duplicate_payments(conn)
        + _a6_from_reconciliation(recon_report)
        + find_statistical_outliers(conn)
    )


def render_anomaly_table(detected: list[dict]) -> None:
    st.dataframe(
        [{"anomaly": d["target_anomaly_id"], "contact": d["contact_name"], "amount": d["amount"], "reason": d["reason"]} for d in detected],
        use_container_width=True,
    )


def render_variance(conn: sqlite3.Connection, heading: str, period_pairs: list[tuple[str, str]], key: str) -> None:
    st.header(heading)
    period_a, period_b = st.selectbox(
        "Compare", period_pairs, index=len(period_pairs) - 1, format_func=lambda p: f"{p[0]} → {p[1]}", key=key
    )
    movement = compute_account_movement(conn, period_a, period_b)
    top_movers = [m for m in movement if m["account_code"]][:5]
    for m in top_movers:
        st.write("- " + explain_movement(conn, m["account_code"], period_a, period_b))


st.set_page_config(page_title="NorthBridge Ledger Agent", layout="wide")
st.title("NorthBridge Ledger Reconciliation & Anomaly Detection Agent")
st.caption(
    "Independent portfolio project — connects to live Xero and QuickBooks organisations, reconciles "
    "bank transactions, flags anomalies, and explains variance. Not affiliated with Xero or Intuit/QuickBooks."
)

st.markdown("## Xero")
xero_conn = _connect(DB_PATH, DEMO_DB_PATH)

xero_recon_report = render_reconciliation(xero_conn, "1. Reconciliation")

st.header("2. Anomaly detection")
xero_detected = detect_all(xero_conn, xero_recon_report)
try:
    score = score_against_answer_key(xero_detected, ANSWER_KEY_PATH)
except FileNotFoundError:
    # The private answer key is gitignored and not published — fall back to the
    # already-measured, published result (see README.md's "Accuracy result").
    score = PUBLISHED_XERO_SCORE

col1, col2, col3, col4 = st.columns(4)
col1.metric("Planted anomalies caught", f"{score['caught']} / {score['total_planted_anomalies']}")
col2.metric("False positives", score["false_positive_count"])
col3.metric("Precision", score["precision"])
col4.metric("Recall", score["recall"])
st.caption(
    "The 3 false positives are ordinary monthly bank-fee lines flagged 'unmatched' by reconciliation "
    "(expected — bank fees never have a bill), not real coding errors."
)
render_anomaly_table(xero_detected)

render_variance(xero_conn, "3. Variance / explain the number", [("2026-06", "2026-07"), ("2026-07", "2026-08")], key="xero_period")
xero_conn.close()

st.divider()
st.markdown("## QuickBooks — same engine, a second ERP")
st.caption(
    "No planted anomalies here (unlike the Xero side) — this is real, unmodified sandbox data. "
    "The point isn't a scored accuracy result, it's that the identical reconciliation/anomaly/variance "
    "code runs unchanged against a structurally different ERP's data."
)
qb_conn = _connect(QB_DB_PATH, QB_DEMO_DB_PATH)

qb_recon_report = render_reconciliation(qb_conn, "4. Reconciliation")

st.header("5. Anomaly detection")
qb_detected = detect_all(qb_conn, qb_recon_report)
st.metric("Items flagged", len(qb_detected))
render_anomaly_table(qb_detected)

render_variance(qb_conn, "6. Variance / explain the number", [("2026-06", "2026-07"), ("2026-07", "2026-08")], key="qb_period")
qb_conn.close()
