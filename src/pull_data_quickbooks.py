"""Phase 8 entrypoint: authenticate against the QuickBooks Online sandbox and
pull all entities — the QuickBooks equivalent of pull_data.py.

First run opens a browser for Intuit consent; later runs reuse the stored
refresh token (saved to .env by quickbooks_connector.save_tokens).

Run with: python -m src.pull_data_quickbooks
"""

from __future__ import annotations

import os
import webbrowser

from dotenv import load_dotenv

from src.connectors import quickbooks_adapter as adapter
from src.connectors import quickbooks_connector as qb
from src.db import load as db

load_dotenv()

QB_DB_PATH = "data/ledger_quickbooks.db"


def _authenticate() -> tuple[str, str]:
    """Return (access_token, realm_id), authenticating via browser consent if needed."""
    refresh_token = os.environ.get("QB_REFRESH_TOKEN")
    realm_id = os.environ.get("QB_REALM_ID")

    if refresh_token and realm_id:
        tokens = qb.refresh_access_token(refresh_token)
    else:
        auth_url = qb.get_authorization_url()
        print(f"Open this URL to authorize QuickBooks access:\n\n{auth_url}\n")
        webbrowser.open(auth_url)
        print("Waiting for you to complete the consent screen...")
        auth_code, realm_id = qb.run_local_callback_server()
        if not auth_code or not realm_id:
            raise RuntimeError("Did not receive an authorization code / realm ID from QuickBooks.")
        tokens = qb.exchange_code_for_tokens(auth_code)

    access_token = tokens["access_token"]
    qb.save_tokens(tokens["refresh_token"], realm_id)
    return access_token, realm_id


def main() -> None:
    access_token, realm_id = _authenticate()

    company = qb.get_company_info(access_token, realm_id)
    company_name = company["CompanyInfo"]["CompanyName"]
    print(f"Connected to: {company_name} (realm {realm_id})")

    invoices = qb.get_invoices(access_token, realm_id)
    bills = qb.get_bills(access_token, realm_id)
    payments = qb.get_payments(access_token, realm_id)
    bill_payments = qb.get_bill_payments(access_token, realm_id)
    purchases = qb.get_purchases(access_token, realm_id)
    deposits = qb.get_deposits(access_token, realm_id)
    accounts = qb.get_accounts(access_token, realm_id)
    customers = qb.get_customers(access_token, realm_id)
    vendors = qb.get_vendors(access_token, realm_id)

    print(f"Invoices: {len(invoices)}")
    print(f"Bills: {len(bills)}")
    print(f"Payments (AR): {len(payments)}")
    print(f"BillPayments (AP): {len(bill_payments)}")
    print(f"Purchases (standalone spend): {len(purchases)}")
    print(f"Deposits (standalone receipts): {len(deposits)}")
    print(f"Accounts: {len(accounts)}")
    print(f"Customers: {len(customers)}")
    print(f"Vendors: {len(vendors)}")

    conn = db.init_db(QB_DB_PATH)
    db.load_all(
        conn,
        accounts=adapter.to_accounts(accounts),
        contacts=adapter.to_contacts(customers, vendors),
        invoices=adapter.to_invoices(invoices),
        bills=adapter.to_bills(bills),
        bank_transactions=adapter.to_bank_transactions(purchases, deposits),
        payments=adapter.to_payments(payments, bill_payments),
    )
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("accounts", "contacts", "invoices", "line_items", "bank_transactions", "payments")
    }
    conn.close()
    print(f"\nLoaded into {QB_DB_PATH}: {counts}")


if __name__ == "__main__":
    main()
