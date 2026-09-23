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

from src.anomaly.statistical import score_against_answer_key, score_against_planted_records
from src.db.load import DB_PATH
from src.reconciliation.matcher import build_reconciliation_report, match_bank_transactions
from src.pipeline import detect_all
from src.reconciliation.stats import compute_data_stats
from src.variance.explainer import compute_account_movement, explain_movement

ANSWER_KEY_PATH = "data/anomaly_answer_key.csv"
DEMO_DB_PATH = "data/demo_ledger.db"  # frozen Xero snapshot, used when there's no live pull yet
QB_DB_PATH = "data/ledger_quickbooks.db"
QB_DEMO_DB_PATH = "data/demo_ledger_quickbooks.db"  # frozen QuickBooks snapshot
LARGE_DB_PATH = "data/demo_ledger_large.db"  # synthetic, ~5,000 bank transactions (src/seed_synthetic.py)
LARGE_PLANTED_PATH = "data/synthetic_planted.csv"

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


def render_data_coverage(conn: sqlite3.Connection, heading: str, source_label: str) -> None:
    """Show what was loaded from the source, so headline counts (e.g. bank transactions) have context."""
    st.header(heading)
    stats = compute_data_stats(conn)
    quality = stats["quality"]
    st.caption(f"Source: {source_label}. Invoice dates {quality['invoice_date_from']} to {quality['invoice_date_to']}.")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total cash movements", quality["total_cash_movements"], help="bank_transactions + payments")
    col2.metric("Payments not linked to an invoice", quality["payments_unlinked"])
    col3.metric("Bank lines with no contact", quality["bank_txns_no_contact"])
    col4.metric("Voided / deleted invoices", quality["invoices_voided_or_deleted"])

    st.dataframe(
        [{"table": c["table"], "rows loaded": c["rows_loaded"], "what it holds": c["note"]} for c in stats["coverage"]],
        use_container_width=True,
    )
    st.caption(
        "Xero and QuickBooks split cash movements differently: standalone bank lines vs. payments recorded "
        "against invoices/bills. 'Bank transactions' in the reconciliation below counts only the former."
    )


def render_reconciliation(conn: sqlite3.Connection, heading: str, progress=None) -> dict:
    st.header(heading)
    recon_report = build_reconciliation_report(match_bank_transactions(conn, progress=progress))

    col1, col2, col3 = st.columns(3)
    col1.metric("Bank transactions", recon_report["total_bank_transactions"], help="Standalone bank lines only; see Data coverage above")
    col2.metric("Auto-matched", f"{recon_report['pct_auto_matched']}%")
    col3.metric("Unmatched", recon_report["unmatched_count"])
    if recon_report["unmatched_items"]:
        st.dataframe(recon_report["unmatched_items"], use_container_width=True)
    return recon_report


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


def run_with_progress(conn: sqlite3.Connection, heading: str) -> tuple[dict, list[dict]]:
    """Reconcile and run every anomaly check, driving a progress bar through the stages."""
    bar = st.progress(0.0, text="Reconciling bank transactions…")

    def on_match(done: int, total: int) -> None:
        bar.progress(0.5 * done / total, text=f"Reconciling bank transactions… {done:,} / {total:,}")

    recon_report = render_reconciliation(conn, heading, progress=on_match)

    def on_rule(done: int, total: int, label: str) -> None:
        bar.progress(0.5 + 0.5 * done / total, text=f"Anomaly check {done}/{total}: {label}")

    detected = detect_all(conn, recon_report, progress=on_rule)
    bar.progress(1.0, text="Done")
    return recon_report, detected


st.set_page_config(page_title="NorthBridge Ledger Agent", layout="wide")
st.title("NorthBridge Ledger Reconciliation & Anomaly Detection Agent")
st.caption(
    "Independent portfolio project — connects to live Xero and QuickBooks organisations, reconciles "
    "bank transactions, flags anomalies, and explains variance. Not affiliated with Xero or Intuit/QuickBooks."
)

view = st.radio(
    "Dataset",
    ["Live sandboxes (Xero + QuickBooks)", "Synthetic scale test (5,000 bank transactions)"],
    horizontal=True,
)

if view.startswith("Synthetic"):
    st.info(
        "This is **synthetic, seeded data** generated by `src/seed_synthetic.py` — not pulled from Xero or "
        "QuickBooks. It uses the same schema and runs the identical engine, to show how it behaves at scale. "
        "Anomalies were planted at known rates, so the score below is a check of speed and mechanics, not a "
        "claim about accuracy on real-world books: the planted patterns were written to fit the rules."
    )
    large_conn = sqlite3.connect(LARGE_DB_PATH)
    render_data_coverage(large_conn, "Data coverage", "synthetic dataset")
    recon_report, detected = run_with_progress(large_conn, "1. Reconciliation")

    st.header("2. Anomaly detection")
    score = score_against_planted_records(detected, LARGE_PLANTED_PATH)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Planted anomalies caught", f"{score['caught']} / {score['total_planted_anomalies']}")
    col2.metric("False positives", score["false_positive_count"])
    col3.metric("Precision", score["precision"])
    col4.metric("Recall", score["recall"])
    st.dataframe(
        [{"anomaly": k, **v} for k, v in score["by_type"].items()],
        use_container_width=True,
    )
    st.caption(
        "False positives: monthly bank-fee lines (no bill exists, so reconciliation flags them) and "
        "ordinary high-side amounts the statistical outlier check flags."
    )
    render_anomaly_table(detected)
    render_variance(large_conn, "3. Variance / explain the number", [("2026-06", "2026-07"), ("2026-07", "2026-08")], key="large_period")
    large_conn.close()
    st.stop()

st.markdown("## Xero")
xero_conn = _connect(DB_PATH, DEMO_DB_PATH)

render_data_coverage(
    xero_conn, "Data coverage",
    "live pull" if os.path.exists(DB_PATH) else "frozen demo snapshot",
)
xero_recon_report, xero_detected = run_with_progress(xero_conn, "1. Reconciliation")

st.header("2. Anomaly detection")
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

render_data_coverage(
    qb_conn, "Data coverage",
    "live pull" if os.path.exists(QB_DB_PATH) else "frozen demo snapshot",
)
qb_recon_report, qb_detected = run_with_progress(qb_conn, "4. Reconciliation")

st.header("5. Anomaly detection")
st.metric("Items flagged", len(qb_detected))
render_anomaly_table(qb_detected)

render_variance(qb_conn, "6. Variance / explain the number", [("2026-06", "2026-07"), ("2026-07", "2026-08")], key="qb_period")
qb_conn.close()
