import sqlite3
import unittest

from src.exceptions import register


def mem():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(register.SCHEMA)
    return conn


def det(rule, record_id, date="2026-07-10T00:00:00", amount=500.0):
    return {"target_anomaly_id": rule, "contact_name": "Acme", "amount": amount, "date": date, "record_id": record_id, "reason": "test"}


class Severity(unittest.TestCase):
    def test_large_unmatched_blocks_small_warns(self):
        self.assertEqual(register.severity_for("A6", 500.0), "blocks_close")
        self.assertEqual(register.severity_for("A6", 15.0), "warn")

    def test_duplicate_payment_always_blocks(self):
        self.assertEqual(register.severity_for("A5", 1.0), "blocks_close")

    def test_weekend_posting_warns(self):
        self.assertEqual(register.severity_for("A4", 5000.0), "warn")


class Lifecycle(unittest.TestCase):
    def test_sync_is_idempotent(self):
        conn = mem()
        first = register.sync(conn, "xero", "2026-07", [det("A6", "b1")])
        second = register.sync(conn, "xero", "2026-07", [det("A6", "b1")])
        self.assertEqual((first["new"], second["new"]), (1, 0))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM exceptions").fetchone()[0], 1)

    def test_resync_does_not_reset_a_cleared_item(self):
        conn = mem()
        register.sync(conn, "xero", "2026-07", [det("A6", "b1")])
        register.clear(conn, "xero:A6:b1", "A. Reviewer", "invoice_to_follow", "Supplier confirmed invoice due 3 Aug.")
        register.sync(conn, "xero", "2026-07", [det("A6", "b1")])
        row = conn.execute("SELECT status, reviewer FROM exceptions").fetchone()
        self.assertEqual((row["status"], row["reviewer"]), ("cleared", "A. Reviewer"))

    def test_clearing_needs_reviewer_reason_and_evidence(self):
        conn = mem()
        register.sync(conn, "xero", "2026-07", [det("A6", "b1")])
        key = "xero:A6:b1"
        with self.assertRaises(ValueError):
            register.clear(conn, key, "", "invoice_to_follow", "note")
        with self.assertRaises(ValueError):
            register.clear(conn, key, "A", "because", "note")
        with self.assertRaises(ValueError):
            register.clear(conn, key, "A", "invoice_to_follow", "   ")
        self.assertEqual(conn.execute("SELECT status FROM exceptions").fetchone()[0], "open")

    def test_item_no_longer_detected_is_kept_and_marked(self):
        conn = mem()
        register.sync(conn, "xero", "2026-07", [det("A6", "b1")])
        result = register.sync(conn, "xero", "2026-07", [])
        self.assertEqual(result["no_longer_detected"], 1)
        row = conn.execute("SELECT status, still_detected FROM exceptions").fetchone()
        self.assertEqual((row["status"], row["still_detected"]), ("open", 0))


class CloseAndCarryForward(unittest.TestCase):
    def test_blocking_item_blocks_close_until_cleared(self):
        conn = mem()
        register.sync(conn, "xero", "2026-07", [det("A5", "b1")])
        self.assertFalse(register.close_status(conn, "xero", "2026-07")["can_close"])
        register.clear(conn, "xero:A5:b1", "A", "duplicate_reversed", "Refund line on statement 14 Jul.")
        self.assertTrue(register.close_status(conn, "xero", "2026-07")["can_close"])

    def test_warnings_do_not_block_close(self):
        conn = mem()
        register.sync(conn, "xero", "2026-07", [det("A4", "i1")])
        status = register.close_status(conn, "xero", "2026-07")
        self.assertTrue(status["can_close"])
        self.assertEqual(status["warnings_open"], 1)

    def test_unresolved_item_carries_into_next_month_with_age(self):
        conn = mem()
        register.sync(conn, "xero", "2026-07", [det("A5", "b1", date="2026-07-10T00:00:00")])
        self.assertEqual(register.close_status(conn, "xero", "2026-07")["carried_forward"], 0)
        august = register.close_status(conn, "xero", "2026-08")
        self.assertEqual((august["can_close"], august["carried_forward"], august["oldest_age_months"]), (False, 1, 1))
        self.assertEqual(register.open_items(conn, "xero", "2026-09")[0]["age_months"], 2)

    def test_later_period_items_do_not_block_an_earlier_close(self):
        conn = mem()
        register.sync(conn, "xero", "2026-08", [det("A5", "b1", date="2026-08-10T00:00:00")])
        self.assertTrue(register.close_status(conn, "xero", "2026-07")["can_close"])

    def test_datasets_are_separate(self):
        conn = mem()
        register.sync(conn, "xero", "2026-07", [det("A5", "b1")])
        self.assertTrue(register.close_status(conn, "quickbooks", "2026-07")["can_close"])


class ReviewItems(unittest.TestCase):
    def test_probable_and_duplicate_claim_become_blocking_exceptions(self):
        report = {"review_items": [
            {"bank_transaction_id": "b1", "date": "2026-07-05", "total": 1015.0, "contact_name": "Acme", "match_status": "probable_match", "matched_invoice_id": "i1", "amount_gap": 15.0},
            {"bank_transaction_id": "b2", "date": "2026-07-20", "total": 500.0, "contact_name": "Acme", "match_status": "duplicate_claim", "matched_invoice_id": "i2", "amount_gap": 0.0},
        ]}
        items = register.recon_review_exceptions(report)
        self.assertEqual([i["target_anomaly_id"] for i in items], ["R1", "R2"])
        conn = mem()
        register.sync(conn, "xero", "2026-07", items)
        self.assertEqual(register.close_status(conn, "xero", "2026-07")["blocking_open"], 2)


if __name__ == "__main__":
    unittest.main()
