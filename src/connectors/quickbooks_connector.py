"""QuickBooks Online OAuth 2.0 (Authorization Code flow) connector — Phase 8 (stretch).

Mirrors xero_connector.py's shape (local callback server, token exchange,
refresh-token handling) but against Intuit's OAuth/API endpoints. QBO's OAuth
callback returns a `realmId` (the sandbox company ID) alongside `code`, which
Xero doesn't have an equivalent of — that's the one structural difference.
"""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import set_key
from requests_oauthlib import OAuth2Session

AUTHORIZATION_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
API_BASE = "https://sandbox-quickbooks.api.intuit.com/v3/company"
MINOR_VERSION = 65

SCOPE = ["com.intuit.quickbooks.accounting"]

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")


def _client_id() -> str:
    return os.environ["QB_CLIENT_ID"]


def _client_secret() -> str:
    return os.environ["QB_CLIENT_SECRET"]


def _redirect_uri() -> str:
    return os.environ.get("QB_REDIRECT_URI", "http://localhost:8000/qb-callback")


def get_authorization_url() -> str:
    """Build the Intuit consent-screen URL to send the user to."""
    oauth = OAuth2Session(_client_id(), redirect_uri=_redirect_uri(), scope=SCOPE)
    url, _state = oauth.authorization_url(AUTHORIZATION_URL)
    return url


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        self.server.auth_code = params.get("code", [None])[0]
        self.server.realm_id = params.get("realmId", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body>QuickBooks authorized \xe2\x80\x94 you can close this tab.</body></html>")

    def log_message(self, format, *args):  # noqa: A002 - matches BaseHTTPRequestHandler signature
        pass


def run_local_callback_server(port: int = 8000) -> tuple[str, str]:
    """Start a local HTTP server to catch the OAuth redirect; returns (auth_code, realm_id)."""
    server = HTTPServer(("localhost", port), _CallbackHandler)
    server.auth_code = None
    server.realm_id = None
    server.handle_request()  # blocks until the single redirect request arrives
    return server.auth_code, server.realm_id


def exchange_code_for_tokens(auth_code: str) -> dict:
    """Exchange an authorization code for access/refresh tokens."""
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": _redirect_uri(),
        },
        auth=(_client_id(), _client_secret()),
        headers={"Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def refresh_access_token(refresh_token: str) -> dict:
    """Use a stored refresh token to get a new access token without re-authenticating."""
    response = requests.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        auth=(_client_id(), _client_secret()),
        headers={"Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


QBO_PAGE_SIZE = 1000  # QBO's maximum MAXRESULTS


def _query(entity: str, access_token: str, realm_id: str) -> list[dict]:
    """Run a `SELECT * FROM <entity>` query, following STARTPOSITION until a short page, and return
    the entity's own list under the response's QueryResponse key (QBO's query API shape)."""
    records: list[dict] = []
    start = 1
    while True:
        response = requests.get(
            f"{API_BASE}/{realm_id}/query",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            params={
                "query": f"SELECT * FROM {entity} STARTPOSITION {start} MAXRESULTS {QBO_PAGE_SIZE}",
                "minorversion": MINOR_VERSION,
            },
            timeout=30,
        )
        response.raise_for_status()
        batch = response.json().get("QueryResponse", {}).get(entity, [])
        records.extend(batch)
        if len(batch) < QBO_PAGE_SIZE:
            return records
        start += QBO_PAGE_SIZE


def get_company_info(access_token: str, realm_id: str) -> dict:
    """First-milestone call: GET the sandbox company's own CompanyInfo record."""
    response = requests.get(
        f"{API_BASE}/{realm_id}/companyinfo/{realm_id}",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        params={"minorversion": MINOR_VERSION},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_invoices(access_token: str, realm_id: str) -> list[dict]:
    return _query("Invoice", access_token, realm_id)


def get_bills(access_token: str, realm_id: str) -> list[dict]:
    return _query("Bill", access_token, realm_id)


def get_payments(access_token: str, realm_id: str) -> list[dict]:
    """Payments received against invoices (QBO's AR-side equivalent of a Xero Payment)."""
    return _query("Payment", access_token, realm_id)


def get_bill_payments(access_token: str, realm_id: str) -> list[dict]:
    """Payments made against bills (QBO's AP-side equivalent)."""
    return _query("BillPayment", access_token, realm_id)


def get_purchases(access_token: str, realm_id: str) -> list[dict]:
    """Standalone spend not tied to a bill — QBO's rough equivalent of a Xero
    'Spend Money' bank transaction."""
    return _query("Purchase", access_token, realm_id)


def get_deposits(access_token: str, realm_id: str) -> list[dict]:
    """Standalone receipts not tied to an invoice — QBO's rough equivalent of a
    Xero 'Receive Money' bank transaction."""
    return _query("Deposit", access_token, realm_id)


def get_accounts(access_token: str, realm_id: str) -> list[dict]:
    return _query("Account", access_token, realm_id)


def get_customers(access_token: str, realm_id: str) -> list[dict]:
    return _query("Customer", access_token, realm_id)


def get_vendors(access_token: str, realm_id: str) -> list[dict]:
    return _query("Vendor", access_token, realm_id)


def save_tokens(refresh_token: str, realm_id: str) -> None:
    """Persist the refresh token and realm (company) ID to .env so future runs skip the consent screen."""
    set_key(ENV_PATH, "QB_REFRESH_TOKEN", refresh_token)
    set_key(ENV_PATH, "QB_REALM_ID", realm_id)
