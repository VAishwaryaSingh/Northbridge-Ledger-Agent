"""Rule-based anomaly checks — Phase 5.

Each rule is a separate, individually-testable, explainable function —
mirrors how an auditor would describe the check, not a black box.
One function per planted-anomaly type from the project plan (section 1).

Every flagged item is returned in a common shape so `score_against_answer_key`
(in statistical.py) can check detector output against the private answer key
generically:
    {
        "target_anomaly_id": "A1",   # which planted-anomaly type this rule targets
        "contact_name": str,
        "amount": float,
        "date": str,
        "record_id": str,            # invoice_id or bank_transaction_id
        "reason": str,                # human-readable, auditor-style explanation
    }
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime

from src.reconciliation.matcher import match_bank_transactions


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    return datetime.fromisoformat(date_str.split("T")[0])


def find_duplicate_invoices(conn: sqlite3.Connection, date_window_days: int = 10) -> list[dict]:
    """A1 — same contact+amount entered twice within a short date window.

    Recurring monthly invoices to the same contact/amount are ~28-31 days apart,
    so a window well under that (default 10 days) won't false-positive on them.
    """
    rows = conn.execute(
        """SELECT i.invoice_id, i.invoice_date, i.total, c.name
           FROM invoices i JOIN contacts c ON c.contact_id = i.contact_id
           WHERE i.invoice_type = 'ACCREC'
           ORDER BY c.name, i.total, i.invoice_date"""
    ).fetchall()

    flagged = []
    for i in range(len(rows) - 1):
        id1, date1, total1, name1 = rows[i]
        id2, date2, total2, name2 = rows[i + 1]
        if name1 != name2 or total1 != total2:
            continue
        d1, d2 = _parse_date(date1), _parse_date(date2)
        if d1 and d2 and abs((d2 - d1).days) <= date_window_days:
            flagged.append(
                {
                    "target_anomaly_id": "A1",
                    "contact_name": name1,
                    "amount": total1,
                    "date": date2,
                    "record_id": id2,
                    "reason": (
                        f"{name1} was invoiced £{total1:.2f} twice within "
                        f"{abs((d2 - d1).days)} days ({date1[:10]} and {date2[:10]}) — likely a duplicate invoice."
                    ),
                }
            )
    return flagged


def find_vat_code_mismatches(conn: sqlite3.Connection) -> list[dict]:
    """A2 — a line item's VAT/tax code differs from that contact's own established pattern.

    Each supplier has one true VAT treatment (standard-rated, zero-rated/reverse-charge,
    or no-VAT sole trader); a line item that breaks from the contact's own historical
    pattern is coded wrong, regardless of what other contacts on the same expense
    account normally use.
    """
    rows = conn.execute(
        """SELECT li.line_item_id, li.tax_type, li.line_amount, i.invoice_date, c.name
           FROM line_items li
           JOIN invoices i ON li.invoice_id = i.invoice_id
           JOIN contacts c ON c.contact_id = i.contact_id
           WHERE i.invoice_type = 'ACCPAY' AND li.tax_type IS NOT NULL
           ORDER BY c.name, i.invoice_date"""
    ).fetchall()

    by_contact: dict[str, list[tuple]] = {}
    for row in rows:
        by_contact.setdefault(row[4], []).append(row)

    flagged = []
    for name, items in by_contact.items():
        if len(items) < 3:
            continue  # not enough history to establish "normal" for this contact
        tax_types = [item[1] for item in items]
        mode_type, mode_count = Counter(tax_types).most_common(1)[0]
        if mode_count == len(items):
            continue  # fully consistent, nothing to flag
        for line_item_id, tax_type, amount, date, _ in items:
            if tax_type != mode_type:
                flagged.append(
                    {
                        "target_anomaly_id": "A2",
                        "contact_name": name,
                        "amount": amount,
                        "date": date,
                        "record_id": line_item_id,
                        "reason": (
                            f"{name}'s bill on {date[:10]} is coded {tax_type}, but their "
                            f"other bills are consistently coded {mode_type} — VAT code mismatch."
                        ),
                    }
                )
    return flagged


def find_threshold_adjacent_round_amounts(conn: sqlite3.Connection, threshold: float = 500.0) -> list[dict]:
    """A3 — an expense suspiciously just under a plausible approval threshold."""
    rows = conn.execute(
        """SELECT i.invoice_id, i.invoice_date, i.total, c.name
           FROM invoices i JOIN contacts c ON c.contact_id = i.contact_id
           WHERE i.invoice_type = 'ACCPAY'"""
    ).fetchall()

    flagged = []
    for invoice_id, date, total, name in rows:
        if threshold * 0.95 <= total < threshold:
            flagged.append(
                {
                    "target_anomaly_id": "A3",
                    "contact_name": name,
                    "amount": total,
                    "date": date,
                    "record_id": invoice_id,
                    "reason": (
                        f"{name}'s bill for £{total:.2f} on {date[:10]} sits suspiciously just "
                        f"under the £{threshold:.0f} approval threshold."
                    ),
                }
            )
    return flagged


def find_weekend_or_holiday_postings(conn: sqlite3.Connection) -> list[dict]:
    """A4 — a transaction dated on a weekend, for a business that only operates Mon-Fri.

    UK public holidays aren't checked (kept simple, per project scope) — weekends only.
    """
    rows = conn.execute(
        """SELECT i.invoice_id, i.invoice_date, i.total, c.name
           FROM invoices i JOIN contacts c ON c.contact_id = i.contact_id
           WHERE i.invoice_type = 'ACCPAY'"""
    ).fetchall()

    flagged = []
    for invoice_id, date, total, name in rows:
        dt = _parse_date(date)
        if dt and dt.weekday() >= 5:  # 5=Saturday, 6=Sunday
            flagged.append(
                {
                    "target_anomaly_id": "A4",
                    "contact_name": name,
                    "amount": total,
                    "date": date,
                    "record_id": invoice_id,
                    "reason": (
                        f"{name}'s bill for £{total:.2f} is dated {date[:10]}, a "
                        f"{dt.strftime('%A')} — Northbridge doesn't operate on weekends."
                    ),
                }
            )
    return flagged


def find_duplicate_payments(conn: sqlite3.Connection) -> list[dict]:
    """A5 — the same bill paid twice: once via a normal linked Payment, and again
    via a standalone bank transaction that also matches it by amount/date/contact.
    """
    bank_matches = [m for m in match_bank_transactions(conn) if m["match_status"] != "no_match"]

    flagged = []
    for match in bank_matches:
        invoice_id = match["matched_invoice_id"]
        existing_payments = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE invoice_id = ?", (invoice_id,)
        ).fetchone()[0]
        if existing_payments >= 1:
            flagged.append(
                {
                    "target_anomaly_id": "A5",
                    "contact_name": match["contact_name"],
                    "amount": match["total"],
                    "date": match["date"],
                    "record_id": match["bank_transaction_id"],
                    "reason": (
                        f"Bill for {match['contact_name']} (£{match['total']:.2f}) already has a "
                        f"recorded payment, but bank transaction on {match['date'][:10]} also matches it — "
                        f"looks like a duplicate payment."
                    ),
                }
            )
    return flagged
