"""Generate a large SYNTHETIC ledger (~5,000 bank transactions) for the dashboard's "Large" view.

This is fake, seeded data — not pulled from Xero or QuickBooks. It uses the same schema as the
live pulls (src/db/schema.sql), so the reconciliation / anomaly / variance code runs on it unchanged.
Anomalies A1-A7 are planted at known rates and their record IDs written to
data/synthetic_planted.csv, so precision and recall can be measured at scale.

Run with: python -m src.seed_synthetic
"""

from __future__ import annotations

import csv
import os
import random
import uuid
from datetime import date, timedelta

from src.db.load import init_db

DB_PATH = "data/demo_ledger_large.db"
PLANTED_PATH = "data/synthetic_planted.csv"
SEED = 42
TARGET_BANK_TRANSACTIONS = 5000
START, END = date(2026, 1, 1), date(2026, 8, 31)
VAT = 0.20

# code -> (name, type, typical net amount)
ACCOUNTS = {
    "400": ("Consulting Fees", "REVENUE", 900),
    "405": ("Retainer Fees", "REVENUE", 1200),
    "402": ("Software Subscriptions", "EXPENSE", 150),
    "406": ("Contractor & Freelancer Fees", "EXPENSE", 380),
    "413": ("Office Supplies", "EXPENSE", 90),
    "420": ("Travel", "EXPENSE", 210),
    "425": ("Marketing", "EXPENSE", 260),
    "430": ("Professional Fees", "EXPENSE", 320),
    "440": ("Utilities", "EXPENSE", 140),
    "450": ("Equipment", "EXPENSE", 300),
}
EXPENSE_CODES = [c for c, (_, t, _) in ACCOUNTS.items() if t == "EXPENSE"]
BANK_ACCOUNT_ID = "acct-bank-current"

PLANTED_COUNTS = {"A1": 12, "A2": 12, "A3": 10, "A4": 15, "A5": 10, "A6": 15, "A7": 10}


def _iso(d: date) -> str:
    return f"{d.isoformat()}T00:00:00"


def _weekday_in_window(rng: random.Random, start: date = START, end: date = END) -> date:
    while True:
        d = start + timedelta(days=rng.randrange((end - start).days + 1))
        if d.weekday() < 5:
            return d


def _weekend_in_window(rng: random.Random) -> date:
    while True:
        d = START + timedelta(days=rng.randrange((END - START).days + 1))
        if d.weekday() >= 5:
            return d


def generate(db_path: str = DB_PATH, planted_path: str = PLANTED_PATH) -> dict:
    rng = random.Random(SEED)

    def new_id() -> str:
        return str(uuid.UUID(int=rng.getrandbits(128)))

    if os.path.exists(db_path):
        os.remove(db_path)
    conn = init_db(db_path)

    contacts: dict[str, dict] = {}  # id -> {name, customer, supplier, account, tax, mult}
    invoices: list[tuple] = []
    line_items: list[tuple] = []
    bank_txns: list[tuple] = []
    payments: list[tuple] = []
    planted: list[tuple] = []  # (anomaly_id, record_id, contact_name, description)

    def add_contact(name: str, *, customer: bool, supplier: bool, account: str | None = None, tax: str = "INPUT2") -> str:
        cid = new_id()
        contacts[cid] = {
            "name": name, "customer": customer, "supplier": supplier,
            "account": account, "tax": tax, "mult": rng.uniform(0.85, 1.15),
        }
        return cid

    def add_invoice(cid: str, inv_type: str, d: date, net: float, *, tax: str | None = None, status: str = "PAID",
                    exact_total: float | None = None) -> tuple[str, str, float]:
        c = contacts[cid]
        tax = tax or c["tax"]
        if exact_total is not None:
            total = round(exact_total, 2)
            net = round(total / (1 + VAT), 2)
            tax_amt = round(total - net, 2)
        else:
            net = round(net, 2)
            tax_amt = round(net * VAT, 2) if tax == "INPUT2" or inv_type == "ACCREC" else 0.0
            total = round(net + tax_amt, 2)
        inv_id, li_id = new_id(), new_id()
        invoices.append((inv_id, cid, inv_type, _iso(d), _iso(d + timedelta(days=30)), total, "Exclusive", status))
        line_items.append((li_id, inv_id, c["account"], f"{c['name']} — {d.strftime('%b %Y')}", 1, net, net, tax, tax_amt))
        return inv_id, li_id, total

    def clean_amount(cid: str) -> float:
        """Net amount for an ordinary bill; never lands in the A3 threshold band (total £475-£500)."""
        c = contacts[cid]
        base = ACCOUNTS[c["account"]][2]
        while True:
            net = base * c["mult"] * rng.uniform(0.92, 1.08)
            total = net * (1 + VAT) if c["tax"] == "INPUT2" else net
            if not 475 <= total < 500:
                return net

    # --- Contacts -------------------------------------------------------------
    bank_suppliers = [
        add_contact(f"Supplier {i:02d}", customer=False, supplier=True, account=EXPENSE_CODES[i % len(EXPENSE_CODES)],
                    tax="ZERORATEDINPUT" if i % 7 == 0 else "INPUT2")
        for i in range(1, 21)
    ]
    bank_customers = [
        add_contact(f"Customer {i:02d}", customer=True, supplier=False, account="400") for i in range(1, 16)
    ]
    pay_suppliers = [
        add_contact(f"Recurring Supplier {i:02d}", customer=False, supplier=True,
                    account=EXPENSE_CODES[i % len(EXPENSE_CODES)]) for i in range(1, 11)
    ]
    retainer_customers = [
        add_contact(f"Retainer Client {i:02d}", customer=True, supplier=False, account="405") for i in range(1, 9)
    ]
    fees_contact = add_contact("Northbridge Bank Fees", customer=False, supplier=True, account="440", tax="NONE")

    months = [date(2026, m, 1) for m in range(1, 9)]

    # --- Bank-paid invoices (each gets one standalone bank transaction) -------
    planted_bank_budget = PLANTED_COUNTS["A5"] + PLANTED_COUNTS["A6"] + len(months)  # + monthly bank fees
    n_clean = TARGET_BANK_TRANSACTIONS - planted_bank_budget
    for _ in range(n_clean):
        is_supplier = rng.random() < 0.6
        cid = rng.choice(bank_suppliers if is_supplier else bank_customers)
        d = _weekday_in_window(rng, START, END - timedelta(days=30))
        if is_supplier:
            net = clean_amount(cid)
        else:
            net = ACCOUNTS["400"][2] * contacts[cid]["mult"] * rng.uniform(0.9, 1.1)
        inv_type = "ACCPAY" if is_supplier else "ACCREC"
        _, _, total = add_invoice(cid, inv_type, d, net)
        bank_txns.append(
            (new_id(), cid, _iso(d + timedelta(days=rng.randint(0, 25))), total,
             "SPEND" if is_supplier else "RECEIVE", int(rng.random() < 0.9))
        )

    # --- Payment-paid invoices (linked Payment rows, no standalone bank line) --
    pay_invoice_ids: dict[str, list[tuple[str, float, date]]] = {}
    for cid in pay_suppliers:
        for m in months:
            d = _weekday_in_window(rng, m, m + timedelta(days=27))
            inv_id, _, total = add_invoice(cid, "ACCPAY", d, clean_amount(cid))
            payments.append((new_id(), inv_id, BANK_ACCOUNT_ID, _iso(d + timedelta(days=rng.randint(3, 20))), total,
                             "ACCPAYPAYMENT", "AUTHORISED"))
            pay_invoice_ids.setdefault(cid, []).append((inv_id, total, d))
    retainer_amounts = {cid: round(rng.uniform(900, 2400), 2) for cid in retainer_customers}
    retainer_invoices: dict[str, list[tuple[str, date]]] = {cid: [] for cid in retainer_customers}
    for cid in retainer_customers:
        for m in months:
            d = m if m.weekday() < 5 else m + timedelta(days=2)
            inv_id, _, total = add_invoice(cid, "ACCREC", d, retainer_amounts[cid])
            payments.append((new_id(), inv_id, BANK_ACCOUNT_ID, _iso(d + timedelta(days=rng.randint(5, 25))), total,
                             "ACCRECPAYMENT", "AUTHORISED"))
            retainer_invoices[cid].append((inv_id, d))

    # --- Legitimate unmatched lines: monthly bank fees (expected false positives) --
    for m in months:
        d = _weekday_in_window(rng, m, m + timedelta(days=27))
        bank_txns.append((new_id(), fees_contact, _iso(d), round(rng.uniform(10, 18), 2), "SPEND", 1))

    # --- Planted anomalies ------------------------------------------------------
    # A1: duplicate retainer invoice, dated 3 days after the original, no payment.
    slots = [(cid, i) for cid in retainer_customers for i in range(len(months))]
    for cid, i in rng.sample(slots, PLANTED_COUNTS["A1"]):
        _, orig_date = retainer_invoices[cid][i]
        dup_id, _, total = add_invoice(cid, "ACCREC", orig_date + timedelta(days=3), retainer_amounts[cid], status="AUTHORISED")
        planted.append(("A1", dup_id, contacts[cid]["name"], f"Duplicate retainer invoice £{total:.2f}"))

    # A2: a bill coded with the other VAT treatment from the supplier's normal one.
    for cid in rng.sample(bank_suppliers, PLANTED_COUNTS["A2"]):
        normal = contacts[cid]["tax"]
        wrong = "ZERORATEDINPUT" if normal == "INPUT2" else "INPUT2"
        _, li_id, _ = add_invoice(cid, "ACCPAY", _weekday_in_window(rng), clean_amount(cid), tax=wrong, status="AUTHORISED")
        planted.append(("A2", li_id, contacts[cid]["name"], f"Coded {wrong}, normally {normal}"))

    # A3: bill of exactly £499 total, just under an assumed £500 approval threshold.
    a3_suppliers = [c for c in bank_suppliers if contacts[c]["tax"] == "INPUT2"]
    for cid in rng.sample(a3_suppliers, PLANTED_COUNTS["A3"]):
        inv_id, _, _ = add_invoice(cid, "ACCPAY", _weekday_in_window(rng), 0, exact_total=499.0, status="AUTHORISED")
        planted.append(("A3", inv_id, contacts[cid]["name"], "Bill of exactly £499"))

    # A4: bill dated on a weekend.
    for cid in rng.sample(bank_suppliers, PLANTED_COUNTS["A4"]):
        d = _weekend_in_window(rng)
        while True:
            net = clean_amount(cid)
            if not 475 <= net * (1 + VAT) < 500:
                break
        inv_id, _, _ = add_invoice(cid, "ACCPAY", d, net, status="AUTHORISED")
        planted.append(("A4", inv_id, contacts[cid]["name"], f"Bill dated {d.strftime('%A')} {d.isoformat()}"))

    # A5: a bill already paid via a linked Payment is paid again as a standalone bank line.
    pay_pool = [(cid, inv) for cid, invs in pay_invoice_ids.items() for inv in invs]
    for cid, (inv_id, total, d) in rng.sample(pay_pool, PLANTED_COUNTS["A5"]):
        bt_id = new_id()
        bank_txns.append((bt_id, cid, _iso(d + timedelta(days=rng.randint(5, 25))), total, "SPEND", 0))
        planted.append(("A5", bt_id, contacts[cid]["name"], f"Second payment of £{total:.2f} against an already-paid bill"))

    # A6: bank lines with no invoice or bill behind them.
    for i in range(PLANTED_COUNTS["A6"]):
        is_spend = rng.random() < 0.7
        cid = add_contact(f"One-off Payee {i + 1:02d}", customer=not is_spend, supplier=is_spend)
        bt_id = new_id()
        amount = round(rng.uniform(200, 1500), 2)
        bank_txns.append((bt_id, cid, _iso(_weekday_in_window(rng)), amount, "SPEND" if is_spend else "RECEIVE", 0))
        planted.append(("A6", bt_id, contacts[cid]["name"], f"Bank line £{amount:.2f} with no matching invoice/bill"))

    # A7: a line amount far outside the normal range for its account.
    for cid in rng.sample(bank_suppliers, PLANTED_COUNTS["A7"]):
        base = ACCOUNTS[contacts[cid]["account"]][2]
        _, li_id, total = add_invoice(cid, "ACCPAY", _weekday_in_window(rng), base * rng.uniform(7, 10), status="AUTHORISED")
        planted.append(("A7", li_id, contacts[cid]["name"], f"Line of £{total:.2f} vs typical £{base}"))

    # --- Write -------------------------------------------------------------------
    conn.executemany(
        "INSERT INTO accounts (account_id, code, name, account_type, tax_type) VALUES (?, ?, ?, ?, ?)",
        [(f"acct-{code}", code, name, typ, None) for code, (name, typ, _) in ACCOUNTS.items()]
        + [(BANK_ACCOUNT_ID, "090", "Business Current Account", "BANK", None)],
    )
    conn.executemany(
        "INSERT INTO contacts (contact_id, name, is_customer, is_supplier) VALUES (?, ?, ?, ?)",
        [(cid, c["name"], int(c["customer"]), int(c["supplier"])) for cid, c in contacts.items()],
    )
    conn.executemany("INSERT INTO invoices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", invoices)
    conn.executemany("INSERT INTO line_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", line_items)
    conn.executemany("INSERT INTO bank_transactions VALUES (?, ?, ?, ?, ?, ?)", bank_txns)
    conn.executemany("INSERT INTO payments VALUES (?, ?, ?, ?, ?, ?, ?)", payments)
    conn.commit()
    conn.close()

    with open(planted_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "record_id", "contact", "description"])
        w.writerows(planted)

    return {
        "bank_transactions": len(bank_txns), "payments": len(payments), "invoices": len(invoices),
        "contacts": len(contacts), "planted": len(planted),
    }


if __name__ == "__main__":
    print(generate())
