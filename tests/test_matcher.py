import sqlite3
import unittest
from pathlib import Path

from src.reconciliation.matcher import build_reconciliation_report, match_bank_transactions

SCHEMA = (Path(__file__).resolve().parent.parent / "src" / "db" / "schema.sql").read_text()


def ledger(invoices, bank_txns):
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO contacts VALUES ('c1', 'Acme', 0, 1)")
    for inv_id, date, total in invoices:
        conn.execute(
            "INSERT INTO invoices VALUES (?, 'c1', 'ACCPAY', ?, ?, ?, 'Exclusive', 'AUTHORISED')", (inv_id, date, date, total)
        )
    for bt_id, date, total in bank_txns:
        conn.execute("INSERT INTO bank_transactions VALUES (?, 'c1', ?, ?, 'SPEND', 0)", (bt_id, date, total))
    return conn


def status(conn):
    return {m["bank_transaction_id"]: m["match_status"] for m in match_bank_transactions(conn)}


class MatcherTiers(unittest.TestCase):
    def test_exact_means_within_a_penny_not_two_percent(self):
        # 2% off a £1,000 invoice must not be an auto-clear.
        conn = ledger([("i1", "2026-08-01", 1000.00)], [("b1", "2026-08-05", 1015.00)])
        self.assertEqual(status(conn)["b1"], "probable_match")

    def test_same_amount_is_exact(self):
        conn = ledger([("i1", "2026-08-01", 1000.00)], [("b1", "2026-08-05", 1000.00)])
        self.assertEqual(status(conn)["b1"], "exact_match")

    def test_far_amount_is_no_match(self):
        conn = ledger([("i1", "2026-08-01", 250.00)], [("b1", "2026-08-05", 42.40)])
        self.assertEqual(status(conn)["b1"], "no_match")

    def test_probable_never_counts_as_auto_cleared(self):
        conn = ledger([("i1", "2026-08-01", 1000.00)], [("b1", "2026-08-05", 1015.00)])
        report = build_reconciliation_report(match_bank_transactions(conn))
        self.assertEqual(report["pct_auto_matched"], 0.0)
        self.assertEqual(report["pct_needs_review"], 100.0)
        self.assertEqual(len(report["review_items"]), 1)
        self.assertEqual(report["review_items"][0]["amount_gap"], 15.0)


class MatcherOneToOne(unittest.TestCase):
    def test_second_payment_against_same_invoice_is_duplicate_claim(self):
        conn = ledger([("i1", "2026-08-01", 500.00)], [("b1", "2026-08-02", 500.00), ("b2", "2026-08-20", 500.00)])
        s = status(conn)
        self.assertEqual(s["b1"], "exact_match")
        self.assertEqual(s["b2"], "duplicate_claim")

    def test_exact_match_is_not_stolen_by_an_earlier_loose_one(self):
        # b1 (earlier) is within 2% of both invoices; b2 is exact for i2. b2 must get i2.
        conn = ledger(
            [("i1", "2026-08-01", 1000.00), ("i2", "2026-08-01", 1010.00)],
            [("b1", "2026-08-02", 1005.00), ("b2", "2026-08-03", 1010.00)],
        )
        matches = {m["bank_transaction_id"]: m for m in match_bank_transactions(conn)}
        self.assertEqual((matches["b2"]["match_status"], matches["b2"]["matched_invoice_id"]), ("exact_match", "i2"))
        self.assertEqual((matches["b1"]["match_status"], matches["b1"]["matched_invoice_id"]), ("probable_match", "i1"))

    def test_each_invoice_is_claimed_once(self):
        conn = ledger(
            [("i1", "2026-08-01", 100.00)],
            [("b1", "2026-08-02", 100.00), ("b2", "2026-08-03", 100.00), ("b3", "2026-08-04", 100.00)],
        )
        claims = [m["matched_invoice_id"] for m in match_bank_transactions(conn) if m["match_status"] in ("exact_match", "probable_match")]
        self.assertEqual(len(claims), len(set(claims)))

    def test_result_is_deterministic(self):
        invoices = [("i1", "2026-08-01", 100.00), ("i2", "2026-08-01", 100.00)]
        bank = [("b1", "2026-08-02", 100.00), ("b2", "2026-08-02", 100.00)]
        self.assertEqual(match_bank_transactions(ledger(invoices, bank)), match_bank_transactions(ledger(invoices, bank)))


if __name__ == "__main__":
    unittest.main()
