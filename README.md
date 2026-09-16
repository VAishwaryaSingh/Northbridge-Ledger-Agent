# NorthBridge Ledger Reconciliation & Anomaly Detection Agent

**Status: core engine + multi-ledger proof complete (Phases 1-8) — connects to live Xero and QuickBooks organisations, reconciles, detects anomalies, and explains variance on both.**

A small-scale version of the kind of AI-native ledger automation product accounting firms are increasingly adopting: connects to a live Xero (and QuickBooks Online) organisation via OAuth, reconciles bank transactions against invoices/bills, flags anomalies (duplicates, VAT miscodings, threshold-adjacent amounts, weekend postings, duplicate payments, statistical outliers), and explains period-over-period variance in plain English.

Built against a fictional company ("Northbridge Creative", a UK digital marketing consultancy) seeded with realistic Xero transactions and 7 deliberately planted anomalies, so the detector's accuracy could be honestly measured against a private answer key rather than just claimed. The same engine also runs, unmodified, against a real QuickBooks Online sandbox — proving it's ledger-agnostic, not a Xero-only script.

**Live demo:** https://northbridge-ledger-agent.streamlit.app/ (runs against a frozen snapshot of the seeded data, since the live Xero connection needs local credentials)

## Screenshot

![Dashboard screenshot](dashboard/screenshots/dashboard-full.png)

## Architecture

```mermaid
flowchart LR
    Xero[Xero API<br/>OAuth 2.0] --> Loader[db/load.py]
    QBO[QuickBooks API<br/>OAuth 2.0] --> Adapter[connectors/quickbooks_adapter.py] --> Loader
    Loader --> SQLite[(SQLite<br/>same schema either ledger)]
    SQLite --> Recon[reconciliation/matcher.py]
    SQLite --> Anomaly[anomaly/rules.py<br/>anomaly/statistical.py]
    SQLite --> Variance[variance/explainer.py]
    Recon --> Dashboard[dashboard/app.py<br/>Streamlit]
    Anomaly --> Dashboard
    Variance --> Dashboard
```

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your own Xero developer app credentials
```

## Running it

```bash
python -m src.pull_data          # Xero: OAuth + pull + load into data/ledger.db (idempotent)
python -m src.reconcile          # bank-transaction-to-invoice/bill reconciliation report
python -m src.detect_anomalies   # full anomaly detector, scored against the answer key
streamlit run dashboard/app.py   # interactive dashboard: reconciliation + anomalies + variance

# QuickBooks (Phase 8) — same engine, a second ERP
python -m src.pull_data_quickbooks                                    # OAuth + pull + load into data/ledger_quickbooks.db
python -m src.reconcile --db data/ledger_quickbooks.db
python -m src.detect_anomalies --db data/ledger_quickbooks.db --no-score   # no planted-anomaly answer key for this sandbox
```

See `northbridge-ledger-agent-plan.md` for the full phase-by-phase build plan and session log.

## Accuracy result

Running the full detector (5 rule-based checks + 1 statistical outlier check + reconciliation's unmatched-item detection) against the seeded dataset and scoring it against the private, deliberately-planted answer key (`data/anomaly_answer_key.csv`, not published in this repo):

**Caught 7 of 7 planted anomalies. 3 false positives. Precision 0.70, recall 1.00.**

The 3 false positives are all ordinary monthly bank-fee lines that reconciliation correctly flags as "unmatched" (bank fees never have a bill behind them) — not real coding errors, but they count against precision since the scoring is intentionally strict. This is the actual, unrounded result — not a claim.

## Multi-ledger proof (QuickBooks)

Phase 8 proves the engine isn't Xero-specific: `src/connectors/quickbooks_adapter.py` normalizes QuickBooks Online's API shapes (which genuinely differ from Xero's — separate Customer/Vendor entities instead of one Contact type, separate Purchase/Deposit entities instead of one BankTransaction type) into the same shape the shared database and engine already expect. The result is that `reconcile.py`, `detect_anomalies.py`, and the dashboard run **unmodified** against a real QuickBooks sandbox via a `--db` flag.

No anomalies were planted in the QuickBooks sandbox (the effort-to-payoff tradeoff of building a second full answer key wasn't worth it for a stretch goal) — instead, the detector found genuine, *unplanted* coincidences in Intuit's own canned demo data: a suspicious-looking duplicate invoice pattern and a bill dated on a Sunday, among others. See the dashboard's "QuickBooks" section for the live result.

## Disclaimer

This is an independent personal project built against a personal Xero trial organisation using only fictional/synthetic data. It is not affiliated with, endorsed by, or connected to Xero or Intuit/QuickBooks.
