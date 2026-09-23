"""Source-data coverage and data-quality stats for the dashboard.

Explains *why* row counts differ between ERPs: Xero and QuickBooks store cash
movements in different tables (standalone bank lines vs. payments against
invoices/bills), so "bank transactions" alone understates activity.
"""

from __future__ import annotations

import sqlite3

TABLE_NOTES = {
    "invoices": "Sales invoices and bills (ACCREC + ACCPAY)",
    "bank_transactions": "Standalone spend/receive lines only; payments against invoices are in `payments`",
    "payments": "Payments recorded directly against an invoice/bill",
    "contacts": "Customers and suppliers",
    "accounts": "Chart of accounts",
    "line_items": "Invoice/bill line detail",
}


def _count(conn: sqlite3.Connection, sql: str) -> int:
    return conn.execute(sql).fetchone()[0]


def compute_data_stats(conn: sqlite3.Connection) -> dict:
    coverage = [
        {"table": t, "rows_loaded": _count(conn, f"SELECT COUNT(*) FROM {t}"), "note": note}
        for t, note in TABLE_NOTES.items()
    ]
    counts = {c["table"]: c["rows_loaded"] for c in coverage}

    invoice_dates = conn.execute("SELECT MIN(invoice_date), MAX(invoice_date) FROM invoices").fetchone()
    quality = {
        "total_cash_movements": counts["bank_transactions"] + counts["payments"],
        "payments_unlinked": _count(
            conn,
            """SELECT COUNT(*) FROM payments p
               WHERE p.invoice_id IS NULL
                  OR p.invoice_id NOT IN (SELECT invoice_id FROM invoices)""",
        ),
        "bank_txns_no_contact": _count(
            conn, "SELECT COUNT(*) FROM bank_transactions WHERE contact_id IS NULL"
        ),
        "bank_txns_flagged_unreconciled": _count(
            conn, "SELECT COUNT(*) FROM bank_transactions WHERE COALESCE(is_reconciled, 0) = 0"
        ),
        "invoices_voided_or_deleted": _count(
            conn, "SELECT COUNT(*) FROM invoices WHERE status IN ('VOIDED', 'DELETED')"
        ),
        "invoice_date_from": (invoice_dates[0] or "")[:10],
        "invoice_date_to": (invoice_dates[1] or "")[:10],
    }
    return {"coverage": coverage, "quality": quality}
