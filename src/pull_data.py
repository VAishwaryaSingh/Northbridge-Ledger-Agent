"""Phase 2 entrypoint: authenticate against the Xero trial org and pull all five entities.

First run opens a browser for Xero consent; later runs reuse the stored refresh token
(saved to .env by xero_connector.save_tokens), so the script can be re-run without
re-authenticating every time.

Run with: python -m src.pull_data
"""

from __future__ import annotations

import os
import webbrowser

from dotenv import load_dotenv

from src.connectors import xero_connector as xero
from src.db import load as db

load_dotenv()


def _authenticate() -> tuple[str, str]:
    """Return (access_token, tenant_id), authenticating via browser consent if needed."""
    refresh_token = os.environ.get("XERO_REFRESH_TOKEN")
    if refresh_token:
        tokens = xero.refresh_access_token(refresh_token)
    else:
        auth_url = xero.get_authorization_url()
        print(f"Open this URL to authorize Xero access:\n\n{auth_url}\n")
        webbrowser.open(auth_url)
        print("Waiting for you to complete the consent screen...")
        auth_code = xero.run_local_callback_server()
        if not auth_code:
            raise RuntimeError("Did not receive an authorization code from Xero.")
        tokens = xero.exchange_code_for_tokens(auth_code)

    access_token = tokens["access_token"]
    tenant_id = xero.get_tenant_id(access_token)
    xero.save_tokens(tokens["refresh_token"], tenant_id)
    return access_token, tenant_id


def main() -> None:
    access_token, tenant_id = _authenticate()

    org = xero.get_organisation(access_token, tenant_id)
    org_name = org["Organisations"][0]["Name"]
    print(f"Connected to: {org_name}")

    invoices = xero.get_invoices(access_token, tenant_id)
    bills = xero.get_bills(access_token, tenant_id)
    bank_transactions = xero.get_bank_transactions(access_token, tenant_id)
    accounts = xero.get_accounts(access_token, tenant_id)
    contacts = xero.get_contacts(access_token, tenant_id)
    payments = xero.get_payments(access_token, tenant_id)

    print(f"Invoices: {len(invoices)}")
    print(f"Bills: {len(bills)}")
    print(f"Bank transactions: {len(bank_transactions)}")
    print(f"Accounts: {len(accounts)}")
    print(f"Contacts: {len(contacts)}")
    print(f"Payments: {len(payments)}")

    conn = db.init_db()
    db.load_all(
        conn,
        accounts=accounts,
        contacts=contacts,
        invoices=invoices,
        bills=bills,
        bank_transactions=bank_transactions,
        payments=payments,
    )
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("accounts", "contacts", "invoices", "line_items", "bank_transactions", "payments")
    }
    conn.close()
    print(f"\nLoaded into {db.DB_PATH}: {counts}")


if __name__ == "__main__":
    main()
