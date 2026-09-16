"""Load Xero API pulls into the local SQLite store — Phase 3.

Upserts on the Xero-native ID so re-running is idempotent.
"""

from __future__ import annotations

import sqlite3

DB_PATH = "data/ledger.db"
SCHEMA_PATH = "src/db/schema.sql"


def init_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    return conn


def _date(record: dict) -> str | None:
    """Xero returns both a .NET-style 'Date' and an ISO 'DateString' — prefer the latter."""
    return record.get("DateString") or record.get("Date")


def upsert_accounts(conn: sqlite3.Connection, accounts: list[dict]) -> None:
    rows = [
        (a["AccountID"], a.get("Code"), a.get("Name"), a.get("Type"), a.get("TaxType"))
        for a in accounts
    ]
    conn.executemany(
        """INSERT INTO accounts (account_id, code, name, account_type, tax_type)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(account_id) DO UPDATE SET
               code=excluded.code, name=excluded.name,
               account_type=excluded.account_type, tax_type=excluded.tax_type""",
        rows,
    )
    conn.commit()


def upsert_contacts(conn: sqlite3.Connection, contacts: list[dict]) -> None:
    rows = [
        (c["ContactID"], c.get("Name"), int(bool(c.get("IsCustomer"))), int(bool(c.get("IsSupplier"))))
        for c in contacts
    ]
    conn.executemany(
        """INSERT INTO contacts (contact_id, name, is_customer, is_supplier)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(contact_id) DO UPDATE SET
               name=excluded.name, is_customer=excluded.is_customer, is_supplier=excluded.is_supplier""",
        rows,
    )
    conn.commit()


def upsert_invoices(conn: sqlite3.Connection, invoices: list[dict]) -> None:
    invoice_rows = []
    line_item_rows = []
    for inv in invoices:
        invoice_id = inv["InvoiceID"]
        contact = inv.get("Contact") or {}
        invoice_rows.append(
            (
                invoice_id,
                contact.get("ContactID"),
                inv.get("Type"),
                _date(inv),
                inv.get("DueDateString") or inv.get("DueDate"),
                inv.get("Total"),
                inv.get("LineAmountTypes"),
                inv.get("Status"),
            )
        )
        for idx, li in enumerate(inv.get("LineItems", [])):
            line_item_rows.append(
                (
                    li.get("LineItemID") or f"{invoice_id}-{idx}",
                    invoice_id,
                    li.get("AccountCode"),
                    li.get("Description"),
                    li.get("Quantity"),
                    li.get("UnitAmount"),
                    li.get("LineAmount"),
                    li.get("TaxType"),
                    li.get("TaxAmount"),
                )
            )

    conn.executemany(
        """INSERT INTO invoices
               (invoice_id, contact_id, invoice_type, invoice_date, due_date, total, tax_type, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(invoice_id) DO UPDATE SET
               contact_id=excluded.contact_id, invoice_type=excluded.invoice_type,
               invoice_date=excluded.invoice_date, due_date=excluded.due_date,
               total=excluded.total, tax_type=excluded.tax_type, status=excluded.status""",
        invoice_rows,
    )
    conn.executemany(
        """INSERT INTO line_items
               (line_item_id, invoice_id, account_code, description, quantity, unit_amount, line_amount, tax_type, tax_amount)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(line_item_id) DO UPDATE SET
               invoice_id=excluded.invoice_id, account_code=excluded.account_code,
               description=excluded.description, quantity=excluded.quantity,
               unit_amount=excluded.unit_amount, line_amount=excluded.line_amount,
               tax_type=excluded.tax_type, tax_amount=excluded.tax_amount""",
        line_item_rows,
    )
    conn.commit()


def upsert_bank_transactions(conn: sqlite3.Connection, transactions: list[dict]) -> None:
    rows = [
        (
            t["BankTransactionID"],
            (t.get("Contact") or {}).get("ContactID"),
            _date(t),
            t.get("Total"),
            t.get("Type"),
            int(bool(t.get("IsReconciled"))),
        )
        for t in transactions
    ]
    conn.executemany(
        """INSERT INTO bank_transactions
               (bank_transaction_id, contact_id, date, total, type, is_reconciled)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(bank_transaction_id) DO UPDATE SET
               contact_id=excluded.contact_id, date=excluded.date, total=excluded.total,
               type=excluded.type, is_reconciled=excluded.is_reconciled""",
        rows,
    )
    conn.commit()


def upsert_payments(conn: sqlite3.Connection, payments: list[dict]) -> None:
    rows = [
        (
            p["PaymentID"],
            (p.get("Invoice") or {}).get("InvoiceID"),
            (p.get("Account") or {}).get("AccountID"),
            _date(p),
            p.get("Amount"),
            p.get("PaymentType"),
            p.get("Status"),
        )
        for p in payments
    ]
    conn.executemany(
        """INSERT INTO payments (payment_id, invoice_id, account_id, date, amount, payment_type, status)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(payment_id) DO UPDATE SET
               invoice_id=excluded.invoice_id, account_id=excluded.account_id, date=excluded.date,
               amount=excluded.amount, payment_type=excluded.payment_type, status=excluded.status""",
        rows,
    )
    conn.commit()


def load_all(
    conn: sqlite3.Connection,
    *,
    accounts: list[dict],
    contacts: list[dict],
    invoices: list[dict],
    bills: list[dict],
    bank_transactions: list[dict],
    payments: list[dict],
) -> None:
    """Load a full pull in FK-safe order: accounts/contacts before invoices,
    invoices before bank_transactions/payments (which reference them)."""
    upsert_accounts(conn, accounts)
    upsert_contacts(conn, contacts)
    upsert_invoices(conn, invoices + bills)
    upsert_bank_transactions(conn, bank_transactions)
    upsert_payments(conn, payments)
