"""Bank-transaction-to-invoice/bill reconciliation — Phase 4.

Classifies each bank transaction as exact match / probable match / duplicate claim /
no match, based on amount (tolerance), date (window), and contact.

- exact_match: amount within a penny and date within EXACT_DATE_WINDOW_DAYS. The only tier
  that is safe to auto-clear.
- probable_match: amount within AMOUNT_TOLERANCE_ABS / AMOUNT_TOLERANCE_PCT. Needs a reviewer.
- duplicate_claim: would match, but every candidate invoice is already taken by another bank
  line. A second payment against one invoice must not clear against it.
- no_match: nothing plausible.

Matching is one-to-one: each invoice is claimed by at most one bank line. Exact matches are
assigned for the whole ledger before any probable match, so a loose match never takes the
invoice an exact match needed.

Only `bank_transactions` (standalone Spend/Receive Money lines) go through
fuzzy matching here — `payments` recorded via Xero's "Add Payment" already
carry a direct invoice_id link, so there's nothing to reconcile for those.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime

EXACT_TOLERANCE_ABS = 0.01    # an "exact" match is within a penny, with no percentage allowance
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


def _amounts_close(a: float, b: float, tolerance_abs: float, tolerance_pct: float = 0.0) -> bool:
    return abs(a - b) <= max(tolerance_abs, abs(b) * tolerance_pct)


def _is_exact(amount: float, inv_total: float, day_diff: int) -> bool:
    return _amounts_close(amount, inv_total, EXACT_TOLERANCE_ABS) and day_diff <= EXACT_DATE_WINDOW_DAYS


def _is_probable(amount: float, inv_total: float, day_diff: int) -> bool:
    return (
        _amounts_close(amount, inv_total, AMOUNT_TOLERANCE_ABS, AMOUNT_TOLERANCE_PCT)
        and day_diff <= PROBABLE_DATE_WINDOW_DAYS
    )


def match_bank_transactions(conn: sqlite3.Connection, progress=None) -> list[dict]:
    """Return one classification record per bank transaction.

    Invoices are loaded once and grouped by (contact, type), so cost scales with the
    number of transactions rather than issuing one query per transaction.
    `progress`, if given, is called as progress(done, total) every 250 transactions.
    """
    transactions = conn.execute(
        """SELECT bt.bank_transaction_id, bt.contact_id, bt.date, bt.total, bt.type,
                  c.name AS contact_name
           FROM bank_transactions bt
           LEFT JOIN contacts c ON c.contact_id = bt.contact_id"""
    ).fetchall()

    candidates_by_key: dict[tuple, list[tuple]] = defaultdict(list)
    for inv_id, contact_id, inv_type, inv_date, due_date, inv_total in conn.execute(
        "SELECT invoice_id, contact_id, invoice_type, invoice_date, due_date, total FROM invoices"
    ):
        candidates_by_key[(contact_id, inv_type)].append(
            (inv_id, _parse_date(inv_date), _parse_date(due_date), inv_total)
        )

    # Per transaction: [(inv_id, inv_total, day_diff), ...] for same-contact, right-direction invoices.
    candidates: dict[str, list[tuple]] = {}
    for bt_id, contact_id, bt_date, total, bt_type, _ in transactions:
        bt_dt = _parse_date(bt_date)
        expected_invoice_type = "ACCPAY" if bt_type == "SPEND" else "ACCREC"
        found = []
        for inv_id, inv_dt, due_dt, inv_total in (
            candidates_by_key.get((contact_id, expected_invoice_type), []) if contact_id else []
        ):
            day_diff = _closest_day_diff(bt_dt, inv_dt, due_dt)
            if day_diff is not None:
                found.append((inv_id, inv_total, day_diff))
        candidates[bt_id] = found

    # Deterministic order so the same ledger always produces the same assignment.
    order = sorted(transactions, key=lambda t: (t[2] or "", t[0]))
    claimed: set[str] = set()
    assigned: dict[str, tuple[str, str]] = {}  # bt_id -> (status, invoice_id)

    for status, qualifies, rank in (
        ("exact_match", _is_exact, lambda amt, c: (c[2], abs(amt - c[1]))),
        ("probable_match", _is_probable, lambda amt, c: (abs(amt - c[1]), c[2])),
    ):
        for bt_id, _, _, total, _, _ in order:
            if bt_id in assigned:
                continue
            options = [c for c in candidates[bt_id] if c[0] not in claimed and qualifies(total, c[1], c[2])]
            if options:
                best = min(options, key=lambda c: rank(total, c))
                claimed.add(best[0])
                assigned[bt_id] = (status, best[0])

    for bt_id, _, _, total, _, _ in order:
        if bt_id in assigned:
            continue
        taken = [c for c in candidates[bt_id] if c[0] in claimed and _is_probable(total, c[1], c[2])]
        if taken:
            best = min(taken, key=lambda c: (abs(total - c[1]), c[2]))
            assigned[bt_id] = ("duplicate_claim", best[0])

    invoice_totals = {inv_id: t for cands in candidates.values() for inv_id, t, _ in cands}
    results = []
    total_rows = len(transactions)
    for n, (bt_id, contact_id, bt_date, total, bt_type, contact_name) in enumerate(transactions, start=1):
        best_status, best_match_id = assigned.get(bt_id, ("no_match", None))
        results.append(
            {
                "bank_transaction_id": bt_id,
                "date": bt_date,
                "total": total,
                "type": bt_type,
                "contact_name": contact_name,
                "match_status": best_status,
                "matched_invoice_id": best_match_id,
                "amount_gap": round(total - invoice_totals[best_match_id], 2) if best_match_id else None,
            }
        )
        if progress and (n % 250 == 0 or n == total_rows):
            progress(n, total_rows)

    return results


def build_reconciliation_report(matches: list[dict]) -> dict:
    """Summarise: total transactions, % auto-cleared (exact only), review queue, unmatched items."""
    total = len(matches)
    exact = [m for m in matches if m["match_status"] == "exact_match"]
    review = [m for m in matches if m["match_status"] in ("probable_match", "duplicate_claim")]
    unmatched = [m for m in matches if m["match_status"] == "no_match"]

    def _item(m: dict) -> dict:
        return {
            "bank_transaction_id": m["bank_transaction_id"],
            "date": m["date"],
            "total": m["total"],
            "contact_name": m["contact_name"],
        }

    return {
        "total_bank_transactions": total,
        "exact_matches": len(exact),
        "probable_matches": sum(1 for m in review if m["match_status"] == "probable_match"),
        "duplicate_claims": sum(1 for m in review if m["match_status"] == "duplicate_claim"),
        "unmatched_count": len(unmatched),
        "pct_auto_matched": round(100 * len(exact) / total, 1) if total else 0.0,
        "pct_needs_review": round(100 * len(review) / total, 1) if total else 0.0,
        "review_items": [
            {**_item(m), "match_status": m["match_status"], "matched_invoice_id": m["matched_invoice_id"], "amount_gap": m["amount_gap"]}
            for m in review
        ],
        "unmatched_items": [_item(m) for m in unmatched],
    }
