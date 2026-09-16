-- SQLite schema — Phase 3. Xero's own IDs are kept as primary keys so every
-- row can be traced back to the source record.

CREATE TABLE IF NOT EXISTS accounts (
    account_id   TEXT PRIMARY KEY,   -- Xero AccountID
    code         TEXT,
    name         TEXT,
    account_type TEXT,
    tax_type     TEXT
);

CREATE TABLE IF NOT EXISTS contacts (
    contact_id TEXT PRIMARY KEY,     -- Xero ContactID
    name       TEXT,
    is_customer INTEGER,
    is_supplier INTEGER
);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id   TEXT PRIMARY KEY,   -- Xero InvoiceID
    contact_id   TEXT REFERENCES contacts(contact_id),
    invoice_type TEXT,               -- ACCREC (invoice) or ACCPAY (bill)
    invoice_date TEXT,
    due_date     TEXT,
    total        REAL,
    tax_type     TEXT,
    status       TEXT
);

CREATE TABLE IF NOT EXISTS bank_transactions (
    bank_transaction_id TEXT PRIMARY KEY,  -- Xero BankTransactionID
    contact_id           TEXT REFERENCES contacts(contact_id),
    date                 TEXT,
    total                REAL,
    type                 TEXT,             -- SPEND or RECEIVE
    is_reconciled        INTEGER
);

-- Payments recorded directly against an invoice/bill (e.g. via "Add Payment" in
-- Xero) live here, not in bank_transactions — BankTransactions only covers
-- standalone Spend/Receive Money lines. Both feed Phase 4 reconciliation.
CREATE TABLE IF NOT EXISTS payments (
    payment_id   TEXT PRIMARY KEY,   -- Xero PaymentID
    invoice_id   TEXT REFERENCES invoices(invoice_id),
    account_id   TEXT REFERENCES accounts(account_id),  -- bank account the payment moved through
    date         TEXT,
    amount       REAL,
    payment_type TEXT,               -- ACCRECPAYMENT / ACCPAYPAYMENT / etc.
    status       TEXT
);

-- Line-item detail per invoice/bill, needed for Phase 5's VAT-code-mismatch
-- rule (A2), which checks the tax type actually used against the account code
-- each line was coded to.
CREATE TABLE IF NOT EXISTS line_items (
    line_item_id TEXT PRIMARY KEY,   -- Xero LineItemID (falls back to "<invoice_id>-<index>" if absent)
    invoice_id   TEXT REFERENCES invoices(invoice_id),
    account_code TEXT,
    description  TEXT,
    quantity     REAL,
    unit_amount  REAL,
    line_amount  REAL,
    tax_type     TEXT,
    tax_amount   REAL
);
