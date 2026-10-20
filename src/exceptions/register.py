"""Exceptions register — what happens after something is flagged.

Detection (reconciliation + rules A1-A7) produces candidate exceptions. This module keeps
them across runs in a small SQLite register, separate from the ledger DB so re-pulling the
ledger never wipes review state:

- each exception has a severity: `blocks_close` or `warn`
- clearing one needs a named reviewer, a reason code and a written evidence note
- the register is idempotent: re-syncing a period never duplicates an item or resets its
  review status
- unresolved items carry forward: an item stays open in later periods and shows its age

Severity defaults below are starting points to agree with whoever owns the close, not
accounting policy.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

REGISTER_PATH = "data/exceptions.db"

# Unmatched bank lines / VAT mismatches below this amount warn instead of blocking.
BLOCKING_AMOUNT_THRESHOLD = 100.0

# rule -> (default severity, amount-gated?, evidence a reviewer must attach to clear it)
RULES: dict[str, dict] = {
    "A1": {"severity": "blocks_close", "gated": False, "evidence": "Confirmation the second invoice is valid, or the credit note / void reference."},
    "A2": {"severity": "blocks_close", "gated": True, "evidence": "Supplier invoice showing the correct VAT treatment, or the journal correcting the code."},
    "A3": {"severity": "warn", "gated": False, "evidence": "Approval record for the amount, or confirmation it is not split to avoid a limit."},
    "A4": {"severity": "warn", "gated": False, "evidence": "Reason the posting date is a weekend or holiday (e.g. the supplier's document date)."},
    "A5": {"severity": "blocks_close", "gated": False, "evidence": "Bank statement lines for both payments and the refund or reversal of the duplicate."},
    "A6": {"severity": "blocks_close", "gated": True, "evidence": "Bank statement line plus the invoice, receipt or approval that supports it."},
    "A7": {"severity": "warn", "gated": False, "evidence": "Supporting invoice or contract explaining the unusual amount."},
    "R1": {"severity": "blocks_close", "gated": False, "evidence": "Reviewer confirmation that the bank line belongs to the proposed invoice, with the amount gap explained."},
    "R2": {"severity": "blocks_close", "gated": False, "evidence": "Bank statement evidence of whether this is a second payment, and the refund or the invoice it should match."},
}

RULE_NAMES = {
    "A1": "Duplicate invoice", "A2": "VAT code mismatch", "A3": "Threshold-adjacent amount",
    "A4": "Weekend/holiday posting", "A5": "Duplicate payment", "A6": "Unmatched bank line",
    "A7": "Statistical outlier", "R1": "Probable match needs review", "R2": "Bank line claims an already-matched invoice",
}

REASON_CODES = [
    "valid_no_invoice_expected",
    "invoice_to_follow",
    "timing_difference",
    "corrected_in_ledger",
    "duplicate_reversed",
    "false_positive_confirmed",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS exceptions (
    exception_key      TEXT PRIMARY KEY,   -- dataset:rule:record_id, so re-syncs update in place
    dataset            TEXT NOT NULL,
    rule               TEXT NOT NULL,
    record_id          TEXT NOT NULL,
    period             TEXT NOT NULL,      -- YYYY-MM of the record's date
    contact_name       TEXT,
    amount             REAL,
    reason             TEXT,
    severity           TEXT NOT NULL,      -- blocks_close | warn
    required_evidence  TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'open',   -- open | cleared
    reason_code        TEXT,
    evidence_note      TEXT,
    reviewer           TEXT,
    cleared_at         TEXT,
    first_seen_period  TEXT NOT NULL,
    last_seen_period   TEXT NOT NULL,
    still_detected     INTEGER NOT NULL DEFAULT 1
);
"""


def connect(path: str = REGISTER_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def severity_for(rule: str, amount: float | None) -> str:
    cfg = RULES[rule]
    if cfg["gated"] and abs(amount or 0.0) < BLOCKING_AMOUNT_THRESHOLD:
        return "warn"
    return cfg["severity"]


def _period_of(date_str: str | None) -> str:
    return (date_str or "")[:7] or "unknown"


def recon_review_exceptions(recon_report: dict) -> list[dict]:
    """Probable matches and duplicate claims, shaped like detector output so they can be synced."""
    rule_for = {"probable_match": "R1", "duplicate_claim": "R2"}
    out = []
    for item in recon_report.get("review_items", []):
        rule = rule_for[item["match_status"]]
        gap = item["amount_gap"]
        if rule == "R1":
            reason = f"Probable match for {item['contact_name']} (£{item['total']:.2f}); amount differs from the invoice by £{gap:.2f}. Not auto-cleared."
        else:
            reason = f"Bank line for {item['contact_name']} (£{item['total']:.2f}) matches an invoice already claimed by another bank line."
        out.append(
            {
                "target_anomaly_id": rule,
                "contact_name": item["contact_name"],
                "amount": item["total"],
                "date": item["date"],
                "record_id": item["bank_transaction_id"],
                "reason": reason,
            }
        )
    return out


def sync(conn: sqlite3.Connection, dataset: str, as_of_period: str, detected: list[dict]) -> dict:
    """Upsert detected exceptions into the register. Never touches review fields of existing rows."""
    seen_keys = set()
    new = 0
    for d in detected:
        rule = d["target_anomaly_id"]
        key = f"{dataset}:{rule}:{d['record_id']}"
        seen_keys.add(key)
        existing = conn.execute("SELECT 1 FROM exceptions WHERE exception_key = ?", (key,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE exceptions SET last_seen_period = ?, still_detected = 1 WHERE exception_key = ?",
                (as_of_period, key),
            )
        else:
            new += 1
            conn.execute(
                """INSERT INTO exceptions (exception_key, dataset, rule, record_id, period, contact_name, amount,
                       reason, severity, required_evidence, first_seen_period, last_seen_period)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (key, dataset, rule, d["record_id"], _period_of(d.get("date")), d.get("contact_name"), d.get("amount"),
                 d.get("reason"), severity_for(rule, d.get("amount")), RULES[rule]["evidence"], as_of_period, as_of_period),
            )
    # Items the engine no longer reports (e.g. fixed in the ERP) are kept but marked, never silently dropped.
    stale = 0
    for row in conn.execute("SELECT exception_key FROM exceptions WHERE dataset = ? AND still_detected = 1", (dataset,)).fetchall():
        if row["exception_key"] not in seen_keys:
            conn.execute("UPDATE exceptions SET still_detected = 0 WHERE exception_key = ?", (row["exception_key"],))
            stale += 1
    conn.commit()
    return {"new": new, "seen": len(seen_keys), "no_longer_detected": stale}


def clear(conn: sqlite3.Connection, exception_key: str, reviewer: str, reason_code: str, evidence_note: str) -> None:
    """Clear an exception. Requires a named reviewer, a known reason code and a non-empty evidence note."""
    if not reviewer.strip():
        raise ValueError("A named reviewer is required to clear an exception.")
    if reason_code not in REASON_CODES:
        raise ValueError(f"Unknown reason code {reason_code!r}; use one of {REASON_CODES}.")
    if not evidence_note.strip():
        raise ValueError("An evidence note is required to clear an exception.")
    cur = conn.execute(
        """UPDATE exceptions SET status = 'cleared', reviewer = ?, reason_code = ?, evidence_note = ?, cleared_at = ?
           WHERE exception_key = ?""",
        (reviewer.strip(), reason_code, evidence_note.strip(), datetime.now(timezone.utc).isoformat(timespec="seconds"), exception_key),
    )
    if cur.rowcount == 0:
        raise KeyError(exception_key)
    conn.commit()


def reopen(conn: sqlite3.Connection, exception_key: str) -> None:
    conn.execute(
        "UPDATE exceptions SET status = 'open', reviewer = NULL, reason_code = NULL, evidence_note = NULL, cleared_at = NULL WHERE exception_key = ?",
        (exception_key,),
    )
    conn.commit()


def _months_between(earlier: str, later: str) -> int:
    (y1, m1), (y2, m2) = (int(earlier[:4]), int(earlier[5:7])), (int(later[:4]), int(later[5:7]))
    return (y2 - y1) * 12 + (m2 - m1)


def open_items(conn: sqlite3.Connection, dataset: str, close_period: str) -> list[dict]:
    """Uncleared exceptions dated in or before `close_period`, each with its age in months.

    age_months > 0 means the item is carried forward from an earlier period.
    """
    rows = conn.execute(
        "SELECT * FROM exceptions WHERE dataset = ? AND status = 'open' AND period <= ? ORDER BY period, rule, record_id",
        (dataset, close_period),
    ).fetchall()
    return [{**dict(r), "age_months": _months_between(r["period"], close_period), "rule_name": RULE_NAMES[r["rule"]]} for r in rows]


def close_status(conn: sqlite3.Connection, dataset: str, close_period: str) -> dict:
    items = open_items(conn, dataset, close_period)
    blocking = [i for i in items if i["severity"] == "blocks_close"]
    return {
        "close_period": close_period,
        "can_close": not blocking,
        "blocking_open": len(blocking),
        "warnings_open": len(items) - len(blocking),
        "carried_forward": sum(1 for i in items if i["age_months"] > 0),
        "oldest_age_months": max((i["age_months"] for i in items), default=0),
    }
