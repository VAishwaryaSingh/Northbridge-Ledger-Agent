"""Bank-transaction-to-invoice/bill reconciliation — Phase 4.

Classifies each bank transaction as exact match / probable match / no match,
based on amount (tolerance), date (window), and contact.

Only `bank_transactions` (standalone Spend/Receive Money lines) go through
fuzzy matching here — `payments` recorded via Xero's "Add Payment" already
carry a direct invoice_id link, so there's nothing to reconcile for those.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

AMOUNT_TOLERANCE_ABS = 5.0    # flat tolerance in GBP for a "probable" match
AMOUNT_TOLERANCE_PCT = 0.02   # relative tolerance for a "probable" match
EXACT_DATE_WINDOW_DAYS = 30   # invoice/due date within this many days = exact
PROBABLE_DATE_WINDOW_DAYS = 45


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    return datetime.fromisoformat(date_str.split("T")[0])


def _days_between(a: datetime, b: datetime) -> int:
    return abs((a - b).days)


def _closest_day_diff(bt_dt: datetime | None, inv_dt: datetime | None, due_dt: datetime | None) -> int | None:
    diffs = []
    if bt_dt and inv_dt:
        diffs.append(_days_between(bt_dt, inv_dt))
    if bt_dt and due_dt:
        diffs.append(_days_between(bt_dt, due_dt))
    return min(diffs) if diffs else None


def _amounts_close(a: float, b: float, tolerance_abs: float) -> bool:
    return abs(a - b) <= max(tolerance_abs, abs(b) * AMOUNT_TOLERANCE_PCT)


def match_bank_transactions(conn: sqlite3.Connection) -> list[dict]:
    """Return one classification record per bank transaction."""
    transactions = conn.execute(
        """SELECT bt.bank_transaction_id, bt.contact_id, bt.date, bt.total, bt.type,
                  c.name AS contact_name
           FROM bank_transactions bt
           LEFT JOIN contacts c ON c.contact_id = bt.contact_id"""
    ).fetchall()

    results = []
    for bt_id, contact_id, bt_date, total, bt_type, contact_name in transactions:
        bt_dt = _parse_date(bt_date)
        expected_invoice_type = "ACCPAY" if bt_type == "SPEND" else "ACCREC"

        candidates = (
            conn.execute(
                """SELECT invoice_id, invoice_date, due_date, total
                   FROM invoices
                   WHERE contact_id = ? AND invoice_type = ?""",
                (contact_id, expected_invoice_type),
            ).fetchall()
            if contact_id
            else []
        )

        best_match_id = None
        best_status = "no_match"

        for inv_id, inv_date, due_date, inv_total in candidates:
            day_diff = _closest_day_diff(bt_dt, _parse_date(inv_date), _parse_date(due_date))
            if day_diff is None:
                continue

            if _amounts_close(total, inv_total, tolerance_abs=0.01) and day_diff <= EXACT_DATE_WINDOW_DAYS:
                best_match_id, best_status = inv_id, "exact_match"
                break
            if (
                best_status == "no_match"
                and _amounts_close(total, inv_total, tolerance_abs=AMOUNT_TOLERANCE_ABS)
                and day_diff <= PROBABLE_DATE_WINDOW_DAYS
            ):
                best_match_id, best_status = inv_id, "probable_match"

        results.append(
            {
                "bank_transaction_id": bt_id,
                "date": bt_date,
                "total": total,
                "type": bt_type,
                "contact_name": contact_name,
                "match_status": best_status,
                "matched_invoice_id": best_match_id,
            }
        )

    return results


def build_reconciliation_report(matches: list[dict]) -> dict:
    """Summarise: total transactions, % auto-matched, list of unmatched items."""
    total = len(matches)
    matched = [m for m in matches if m["match_status"] != "no_match"]
    unmatched = [m for m in matches if m["match_status"] == "no_match"]

    return {
        "total_bank_transactions": total,
        "exact_matches": sum(1 for m in matches if m["match_status"] == "exact_match"),
        "probable_matches": sum(1 for m in matches if m["match_status"] == "probable_match"),
        "unmatched_count": len(unmatched),
        "pct_auto_matched": round(100 * len(matched) / total, 1) if total else 0.0,
        "unmatched_items": [
            {
                "bank_transaction_id": m["bank_transaction_id"],
                "date": m["date"],
                "total": m["total"],
                "contact_name": m["contact_name"],
            }
            for m in unmatched
        ],
    }
