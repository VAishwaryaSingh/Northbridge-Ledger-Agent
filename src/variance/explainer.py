"""Period-over-period variance explanation — Phase 6.

For accounts with material movement between two periods, identifies the
specific transactions driving the change and generates a plain-English
sentence, e.g. "Marketing expense up 340% vs. last month, driven by two
invoices from [Contact] totalling £X."
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict


def compute_account_movement(conn: sqlite3.Connection, period_a: str, period_b: str) -> list[dict]:
    """Account-level £ and % change between two periods ('YYYY-MM' strings)."""
    rows = conn.execute(
        """SELECT li.account_code, a.name, a.account_type,
                  COALESCE(SUM(CASE WHEN substr(i.invoice_date,1,7)=? THEN li.line_amount END), 0) AS amount_a,
                  COALESCE(SUM(CASE WHEN substr(i.invoice_date,1,7)=? THEN li.line_amount END), 0) AS amount_b
           FROM line_items li
           JOIN invoices i ON li.invoice_id = i.invoice_id
           LEFT JOIN accounts a ON a.code = li.account_code
           WHERE substr(i.invoice_date, 1, 7) IN (?, ?)
           GROUP BY li.account_code
           HAVING amount_a != 0 OR amount_b != 0""",
        (period_a, period_b, period_a, period_b),
    ).fetchall()

    movement = []
    for account_code, account_name, account_type, amount_a, amount_b in rows:
        delta = amount_b - amount_a
        pct_change = (delta / amount_a * 100) if amount_a else None
        movement.append(
            {
                "account_code": account_code,
                "account_name": account_name,
                "account_type": account_type,
                "amount_period_a": amount_a,
                "amount_period_b": amount_b,
                "delta": delta,
                "pct_change": round(pct_change, 1) if pct_change is not None else None,
            }
        )
    return sorted(movement, key=lambda m: abs(m["delta"]), reverse=True)


def explain_movement(conn: sqlite3.Connection, account_code: str, period_a: str, period_b: str) -> str:
    """Plain-English, transaction-backed explanation for one account's movement.

    Despite the historical stub's `account_id` naming, this takes the account's
    `code` (as stored on `line_items.account_code`), since that's what ties
    transactions to an account in this schema.
    """
    account = conn.execute("SELECT name FROM accounts WHERE code = ?", (account_code,)).fetchone()
    account_name = account[0] if account else account_code

    def _period_lines(period: str) -> list[tuple[str, float]]:
        return conn.execute(
            """SELECT c.name, li.line_amount
               FROM line_items li
               JOIN invoices i ON li.invoice_id = i.invoice_id
               JOIN contacts c ON c.contact_id = i.contact_id
               WHERE li.account_code = ? AND substr(i.invoice_date, 1, 7) = ?""",
            (account_code, period),
        ).fetchall()

    lines_a = _period_lines(period_a)
    lines_b = _period_lines(period_b)
    amount_a = sum(amount for _, amount in lines_a)
    amount_b = sum(amount for _, amount in lines_b)
    delta = amount_b - amount_a
    direction = "up" if delta >= 0 else "down"

    if amount_a:
        headline = f"{account_name} {direction} {abs(delta / amount_a * 100):.0f}% vs {period_a} (£{amount_a:,.0f} → £{amount_b:,.0f})"
    else:
        headline = f"{account_name}: new spend of £{amount_b:,.0f} in {period_b} (nothing in {period_a})"

    # What's new/bigger in period_b that wasn't in period_a, by contact
    by_contact_a: dict[str, float] = defaultdict(float)
    for name, amount in lines_a:
        by_contact_a[name] += amount
    by_contact_b: dict[str, float] = defaultdict(float)
    for name, amount in lines_b:
        by_contact_b[name] += amount

    driving = sorted(
        ((name, amount - by_contact_a.get(name, 0.0)) for name, amount in by_contact_b.items()),
        key=lambda x: abs(x[1]),
        reverse=True,
    )
    driving = [(name, amt) for name, amt in driving if abs(amt) > 0.01][:2]

    if not driving:
        return headline + "."

    parts = [f"{name} (+£{amt:,.0f})" if amt >= 0 else f"{name} (-£{abs(amt):,.0f})" for name, amt in driving]
    return f"{headline}, driven by {' and '.join(parts)}."
