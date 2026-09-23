"""Xero OAuth 2.0 (Authorization Code flow) connector — Phase 2."""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import set_key
from requests_oauthlib import OAuth2Session

AUTHORIZATION_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"
CONNECTIONS_URL = "https://api.xero.com/connections"
API_BASE = "https://api.xero.com/api.xro/2.0"

SCOPE = [
    "offline_access",
    "openid",
    "profile",
    "email",
    "accounting.invoices.read",
    "accounting.banktransactions.read",
    "accounting.payments.read",
    "accounting.settings.read",
    "accounting.contacts.read",
]

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")


def _client_id() -> str:
    return os.environ["XERO_CLIENT_ID"]


def _client_secret() -> str:
    return os.environ["XERO_CLIENT_SECRET"]


def _redirect_uri() -> str:
    return os.environ.get("XERO_REDIRECT_URI", "http://localhost:8080/callback")


def get_authorization_url() -> str:
    """Build the Xero consent-screen URL to send the user to."""
    oauth = OAuth2Session(_client_id(), redirect_uri=_redirect_uri(), scope=SCOPE)
    url, _state = oauth.authorization_url(AUTHORIZATION_URL)
    return url


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        self.server.auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body>Xero authorized \xe2\x80\x94 you can close this tab.</body></html>")

    def log_message(self, format, *args):  # noqa: A002 - matches BaseHTTPRequestHandler signature
        pass


def run_local_callback_server(port: int = 8080) -> str:
    """Start a local HTTP server to catch the OAuth redirect and return the auth code."""
    server = HTTPServer(("localhost", port), _CallbackHandler)
    server.auth_code = None
    server.handle_request()  # blocks until the single redirect request arrives
    return server.auth_code


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
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_tenant_id(access_token: str) -> str:
    """Discover the tenant (organisation) connected to this app."""
    response = requests.get(
        CONNECTIONS_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    response.raise_for_status()
    connections = response.json()
    if not connections:
        raise RuntimeError("No Xero organisation is connected to this app yet.")
    return connections[0]["tenantId"]


def _get(endpoint: str, access_token: str, tenant_id: str, params: dict | None = None) -> dict:
    response = requests.get(
        f"{API_BASE}/{endpoint}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Xero-tenant-id": tenant_id,
            "Accept": "application/json",
        },
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_organisation(access_token: str, tenant_id: str) -> dict:
    """First-milestone call: GET /Organisation."""
    return _get("Organisation", access_token, tenant_id)


MAX_PAGES = 500  # safety stop; at 100 rows per page that's 50,000 records


def _get_all_pages(endpoint: str, key: str, access_token: str, tenant_id: str, params: dict | None = None) -> list[dict]:
    """Fetch every page of a list endpoint (page=1, 2, ...) until a page comes back empty.

    Xero returns up to 100 records per page, so a single call silently truncates larger orgs.
    Stopping on an empty page (rather than "fewer than 100") is correct whatever page size Xero uses.
    """
    records: list[dict] = []
    for page in range(1, MAX_PAGES + 1):
        data = _get(endpoint, access_token, tenant_id, params={**(params or {}), "page": page})
        batch = data.get(key, [])
        if not batch:
            break
        records.extend(batch)
    return records


def get_invoices(access_token: str, tenant_id: str) -> list[dict]:
    # SummaryOnly=false (case-sensitive) only takes effect when a "page" param is present —
    # without it, Xero silently ignores SummaryOnly and still omits LineItems.
    return _get_all_pages(
        "Invoices", "Invoices", access_token, tenant_id,
        params={"where": 'Type=="ACCREC"', "SummaryOnly": "false"},
    )


def get_bills(access_token: str, tenant_id: str) -> list[dict]:
    """Bills are Xero's ACCPAY invoice type — same endpoint as invoices, filtered by type."""
    return _get_all_pages(
        "Invoices", "Invoices", access_token, tenant_id,
        params={"where": 'Type=="ACCPAY"', "SummaryOnly": "false"},
    )


def get_bank_transactions(access_token: str, tenant_id: str) -> list[dict]:
    return _get_all_pages("BankTransactions", "BankTransactions", access_token, tenant_id)


def get_accounts(access_token: str, tenant_id: str) -> list[dict]:
    data = _get("Accounts", access_token, tenant_id)
    return data.get("Accounts", [])


def get_contacts(access_token: str, tenant_id: str) -> list[dict]:
    return _get_all_pages("Contacts", "Contacts", access_token, tenant_id)


def get_payments(access_token: str, tenant_id: str) -> list[dict]:
    """Payments recorded directly against invoices/bills (e.g. via 'Add Payment') —
    separate from BankTransactions, which only covers Spend/Receive Money lines."""
    return _get_all_pages("Payments", "Payments", access_token, tenant_id)


def save_tokens(refresh_token: str, tenant_id: str) -> None:
    """Persist the refresh token and tenant ID to .env so future runs skip the consent screen."""
    set_key(ENV_PATH, "XERO_REFRESH_TOKEN", refresh_token)
    set_key(ENV_PATH, "XERO_TENANT_ID", tenant_id)
