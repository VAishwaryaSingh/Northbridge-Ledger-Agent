"""Shared detection pipeline used by the dashboard (and scripts), so the logic lives in one place."""

from __future__ import annotations

import sqlite3

from src.anomaly.rules import (
    find_duplicate_invoices,
    find_duplicate_payments,
    find_threshold_adjacent_round_amounts,
    find_vat_code_mismatches,
    find_weekend_or_holiday_postings,
)
from src.anomaly.statistical import find_statistical_outliers


def a6_from_reconciliation(recon_report: dict) -> list[dict]:
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


def detect_all(conn: sqlite3.Connection, recon_report: dict, progress=None) -> list[dict]:
    """Run every anomaly check. `progress`, if given, is called as progress(done, total, label) per rule."""
    steps = [
        ("duplicate invoices", find_duplicate_invoices),
        ("VAT code mismatches", find_vat_code_mismatches),
        ("threshold-adjacent amounts", find_threshold_adjacent_round_amounts),
        ("weekend postings", find_weekend_or_holiday_postings),
        ("duplicate payments", find_duplicate_payments),
        ("statistical outliers", find_statistical_outliers),
    ]
    detected = a6_from_reconciliation(recon_report)
    for n, (label, rule) in enumerate(steps, start=1):
        detected += rule(conn)
        if progress:
            progress(n, len(steps), label)
    return detected
