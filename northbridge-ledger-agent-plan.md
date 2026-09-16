# Project Plan: NorthBridge Ledger Reconciliation & Anomaly Detection Agent

**Owner:** Aishwarya Singh, ACCA
**Purpose of this document:** This is a self-contained brief for an AI coding assistant (Claude Code, Cursor, or any other tool) to help build this project across multiple sessions. Read this whole file before doing anything. It contains all the context needed — you should not need anything else to get started, other than the owner's live Xero/QuickBooks credentials when a step requires them.

---

## 0. Read this first — instructions for whichever AI tool picks this up

- This is a **portfolio project**, not production software. Optimise for a clean, demonstrable, honestly-scoped result over engineering polish.
- Work through the phases **in order**. Each phase has a "Definition of Done" — don't move on until it's met.
- **Never commit credentials.** All API keys/secrets go in a local `.env` file that is git-ignored from the first commit.
- **Never touch real/production financial data.** Everything runs against a free Xero trial organisation or a free QuickBooks Online sandbox company that the owner controls and has seeded herself.
- If a step requires the owner to do something outside the coding tool (e.g. click through an OAuth consent screen, create a Xero trial org, note down a Client ID), **stop and ask her to do it**, then wait for confirmation before continuing.
- APIs and developer-portal steps can change over time — if anything in this doc looks outdated when you get there (endpoint names, sign-up flow, SDK availability), verify against the current official docs (developer.xero.com, developer.intuit.com) before proceeding, and update this file's notes accordingly.
- At the end of every working session, **update the "Session Log" section at the bottom of this file** (what got done, what's blocked, what's next) and make sure the "Master Checklist" checkboxes are current. This is how continuity is preserved across sessions and across different tools — the file is the memory, not the chat history.

---

## 1. Why this project exists (strategic context)

A growing category of AI-native fintech products sit on top of a client's existing ledger (Xero, QuickBooks, Business Central) and automate reconciliations, anomaly detection (miscodings, VAT issues, fraud), and variance reporting/insights for accounting firms and finance teams.

**The goal of this project — NorthBridge Ledger Reconciliation & Anomaly Detection Agent — is to build a real, working, honestly-tested artifact**: a small-scale version of what this category of product does, built on a live Xero (and optionally QuickBooks) instance, published as a public GitHub repo.

Every design choice below maps to a concrete capability of this category of product:
- Reconciliations prepared from source → Phase 4 (reconciliation layer)
- Anomalies flagged (miscodings, VAT issues, inconsistencies) → Phase 5 (anomaly detection)
- Variances explained → Phase 6 (variance/explain layer)
- Sits on top of the ledgers accounting firms already use (Xero, QuickBooks, Business Central) → Phase 8 (multi-ledger stretch goal)

---

## 2. Definition of "done" for the whole project

By the end, the owner should have:
1. A public GitHub repo containing working code that connects to a live Xero organisation, pulls real data via the API, reconciles bank transactions against invoices/bills, flags anomalies, and explains period-over-period variance.
2. A documented, honest accuracy result: a set of deliberately planted anomalies, and a report of how many the detector actually caught (precision/recall), not just a claim that it "works."
3. A clean README with an architecture diagram, screenshots, the accuracy result, and a clear disclaimer that this is an independent personal project (not affiliated with Xero or Intuit/QuickBooks).
4. (Stretch) The same engine also running against a QuickBooks Online sandbox, proving the multi-ledger claim.

---

## 3. Tech stack

- **Language:** Python 3.11+
- **API access:** Xero REST API via OAuth 2.0 (Authorization Code flow). Use the official `xero-python` SDK if it's current and well-maintained when you check; otherwise plain `requests` + `authlib` (or `requests-oauthlib`) works fine and is simpler to reason about.
- **Local data store:** SQLite (via Python's built-in `sqlite3`, or `sqlalchemy` if preferred) — no need for a server-based DB for this scale.
- **Data handling:** `pandas` for matching/aggregation logic.
- **Anomaly detection (stretch statistical layer):** `scikit-learn` (Isolation Forest or simple z-score — no need for anything heavier).
- **Visualisation:** Power BI (owner already has this skill and existing dashboards) **or** a lightweight `streamlit` app for an interactive, clickable demo. Pick one — don't build both unless there's spare time.
- **Environment/secrets:** `python-dotenv`, a `.env` file, and a `.gitignore` that excludes it from commit #1.
- **Version control:** Git + GitHub, public repo.

---

## 4. Environment setup checklist

- [x] Python 3.11+ installed, virtual environment created (`python -m venv venv`)
- [x] Git repo initialised, `.gitignore` created (must include `.env`, `__pycache__/`, `*.db`, `venv/`)
- [ ] Free Xero account created at xero.com
- [ ] A **30-day free trial organisation** started (do **not** rely on the Xero "Demo Company" for this project — as of the time this plan was written, the Demo Company resets periodically and does not support creating bank transactions via the API, which Phase 1 needs)
- [ ] Free developer account created at developer.xero.com
- [ ] A new app registered in the Xero Developer Portal (Web App integration type), producing a Client ID and Client Secret
- [ ] Redirect URI decided and registered (e.g. `http://localhost:8080/callback` for local dev)
- [ ] `.env` file created locally with `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `XERO_REDIRECT_URI` (tenant ID gets captured after first successful OAuth connection)

---

## 5. Phase-by-phase plan

### Phase 1 — Build a ledger you control
**Goal:** A Xero trial organisation with realistic data and a known set of planted errors.

Tasks:
- Pick a simple fictional SME (e.g. a boutique consultancy or online retailer). Give it a name unrelated to any real business.
- Build out: a chart of accounts (Xero's default is fine, lightly customised), 10–15 contacts (mix of customers and suppliers), 2–3 months of invoices and bills, and matching bank transactions.
- **Plant these anomalies deliberately** (this is the answer key — keep a private record, e.g. `anomaly_answer_key.csv`, of exactly what was planted and where, so it is not visible in the "clean" version of the data the detector will see):

| ID | Type | Description | How it should be caught |
|----|------|--------------|--------------------------|
| A1 | Duplicate invoice | Same invoice entered twice (same contact, amount, near-identical date) | Rule-based: exact/near-duplicate match on contact+amount+date window |
| A2 | Wrong VAT code | A transaction category that should be zero-rated/exempt has standard VAT applied (or vice versa) | Rule-based: VAT code vs. account-type mismatch check |
| A3 | Threshold-adjacent round amount | An expense just under a plausible approval threshold (e.g. £499 when the threshold is £500), suspiciously round | Rule-based: round-number + threshold-proximity flag |
| A4 | Weekend/holiday posting | A transaction dated on a weekend or public holiday for a business that doesn't operate then | Rule-based: date-vs-calendar check |
| A5 | Duplicate payment | The same supplier invoice paid twice | Rule-based: duplicate bank-transaction-to-bill match |
| A6 | Genuinely unmatched bank line | A bank transaction with no corresponding invoice/bill at all | Reconciliation layer: unmatched item |
| A7 | Statistical outlier | An expense far outside the normal range for its category, but not caught by any of the above rules (e.g. an unusually large "Office Supplies" entry with nothing else wrong about it) | Statistical layer only (z-score / Isolation Forest) — this is the one that proves the statistical layer adds value beyond the rules |

Add 2–3 more of your own if useful, but don't over-engineer this list — 7–10 planted items across a few hundred real transactions is enough to produce a meaningful precision/recall number.

**Definition of Done:** Trial org has realistic-looking data; the private answer key file lists every planted anomaly with its ID, type, and where to find it (contact/date/amount).

---

### Phase 2 — Connect via the API
**Goal:** A script that authenticates against the trial org and successfully pulls data.

Tasks:
- Register the Xero app, implement the OAuth 2.0 Authorization Code flow (a simple local callback server is the standard approach for a personal project like this).
- First milestone: a successful `GET` to the `Organisation` endpoint returning the org's own details.
- Then implement pulls for: `Invoices`, `Bills` (bills are Xero's `ACCPAY` invoice type — check current docs for the exact endpoint naming), `BankTransactions`, `Accounts` (chart of accounts), `Contacts`.
- Store the access/refresh token flow so the script can be re-run without re-authenticating every time (refresh token handling).

**Definition of Done:** Running one command re-pulls fresh data from the live trial org for all five entities above, authenticating automatically via the stored refresh token.

---

### Phase 3 — Land the data in a queryable store
**Goal:** A local SQLite database, rebuilt from the API pull.

Tasks:
- Design a simple schema: one table per entity (`invoices`, `bills`, `bank_transactions`, `accounts`, `contacts`), keeping Xero's own IDs as primary/foreign keys so records can be traced back to the source.
- Write a load script that takes the pulled JSON and writes it into the tables (upsert logic, not just append, so re-running doesn't duplicate rows).

**Definition of Done:** One script, run end-to-end, refreshes the local database from the live org and can be re-run safely (idempotent).

---

### Phase 4 — Reconciliation layer
**Goal:** Auto-match bank transactions to invoices/bills.

Tasks:
- For each bank transaction, attempt to match it to an invoice or bill by amount (exact or within a small tolerance), date (within a reasonable window), and contact.
- Classify each bank transaction as: exact match / probable match / no match.
- Produce a simple report: total transactions, % auto-matched, list of unmatched items needing review.

**Definition of Done:** Running the reconciliation script against the seeded data produces a report, and item A6 (the genuinely unmatched bank line) correctly shows up as unmatched.

---

### Phase 5 — Anomaly detection
**Goal:** Flag the planted anomalies, and measure how well the detector actually did.

Tasks:
- Implement rule-based checks for A1–A5 (see table in Phase 1) as separate, individually testable functions — each rule should be simple and explainable, the way an auditor would describe it, not a black box.
- Add one lightweight statistical layer (z-score by category, or `sklearn.ensemble.IsolationForest` on transaction amount grouped by account category) aimed at catching A7 and anything the rules missed.
- Run the full detector against the seeded dataset and compare its output to the private answer key from Phase 1.
- Calculate and record precision and recall (or simply: "caught X of Y planted anomalies, Z false positives"). **Do not skip this step or round it up — an honest, slightly imperfect number is more credible than a suspiciously perfect one.**

**Definition of Done:** A written accuracy result exists, based on an actual run against the answer key, e.g. "caught 8 of 10 planted anomalies (2 missed: describe why), with 1 false positive (describe why)."

---

### Phase 6 — Variance / "explain the number" layer
**Goal:** Plain-English, transaction-backed explanations of period-over-period movement.

Tasks:
- Pick two periods (e.g. month 2 vs. month 1 of the seeded data) and compute account-level movement (£ and % change).
- For accounts with material movement, identify the specific transactions driving the change and generate a plain-English sentence, e.g.: "Marketing expense up 340% vs. last month, driven by two invoices from [Contact] totalling £X."
- Visualise the results — either as a Power BI dashboard (reusing the existing skillset) or a simple `streamlit` app that can be clicked through live. Pick one.

**Definition of Done:** A dashboard or report exists showing at least 3–5 account-level variance explanations, each traceable back to specific transactions.

---

### Phase 7 — Package it as a portfolio piece
**Goal:** A public GitHub repo that reads well to a non-technical reader and holds up to a technical one.

Tasks:
- Write a README covering: the problem (bookkeepers/controllers lose real time to manual reconciliation, anomaly-spotting, and explaining variance every month-end — exactly what this category of AI-native ledger tooling targets), the architecture (Xero → OAuth pull → SQLite → reconciliation/anomaly/variance engine → dashboard), how to run it, screenshots, and the Phase 5 accuracy result stated plainly.
- Add a clear disclaimer: independent personal project, not affiliated with or endorsed by Xero or Intuit/QuickBooks; built against a personal trial/sandbox org using only fictional/synthetic data.
- Include a simple architecture diagram (even a basic one drawn in draw.io / Excalidraw / Mermaid embedded in the README is enough).

**Definition of Done:** Repo is public, README is complete with screenshots.

---

### Phase 8 — Stretch: add QuickBooks as a second connector
**Goal:** Prove the same engine works across more than one ledger — the "sits on top of the ledgers you already use" pattern this whole category of product is built around.

Tasks:
- Create a free QuickBooks Online sandbox company at developer.intuit.com (unlike Xero's Demo Company, this one is persistent and supports full read/write, so it's actually the easier environment to seed data in).
- Refactor Phases 2–6's logic behind a thin adapter/interface (e.g. a common `LedgerConnector` interface with a `XeroConnector` and `QuickBooksConnector` implementation) so the reconciliation/anomaly/variance engine is ledger-agnostic.
- Seed a comparable small dataset with its own planted anomalies in the QuickBooks sandbox, and re-run the same accuracy measurement.

**Definition of Done:** The same core engine, run with a different connector, produces a reconciliation/anomaly/variance result against QuickBooks data. Skip Business Central for this project — free API access is harder to obtain and the payoff for a portfolio piece is low relative to the effort.

---

## 6. Suggested repo structure

```
ledger-agent/
├── README.md
├── .env.example
├── .gitignore
├── requirements.txt
├── src/
│   ├── connectors/
│   │   ├── base.py            # LedgerConnector interface (Phase 8)
│   │   ├── xero_connector.py
│   │   └── quickbooks_connector.py   # Phase 8
│   ├── db/
│   │   ├── schema.sql
│   │   └── load.py
│   ├── reconciliation/
│   │   └── matcher.py
│   ├── anomaly/
│   │   ├── rules.py
│   │   └── statistical.py
│   └── variance/
│       └── explainer.py
├── data/
│   └── anomaly_answer_key.csv   # private — do not include planted-error details in the public repo if it would spoil the "test"; consider keeping this file local-only or in a private gist
├── notebooks/                   # optional exploration/scratch work
└── dashboard/                   # Power BI file or streamlit app
```

Note on `anomaly_answer_key.csv`: decide before publishing whether to include it in the public repo (transparent, shows your testing rigour) or keep it out and just report the resulting precision/recall numbers in the README (avoids "spoiling" the test if anyone wanted to try reproducing it blind). Either is defensible — pick one and be consistent.

---

## 7. Master checklist (update as you go)

- [x] Phase 1 — Ledger built with planted anomalies + private answer key
- [x] Phase 2 — API connection working, all 5 entities pulling
- [x] Phase 3 — Local SQLite store, idempotent load script
- [x] Phase 4 — Reconciliation layer working, unmatched items correctly identified
- [x] Phase 5 — Anomaly detection implemented + scored against answer key
- [x] Phase 6 — Variance/explain layer + dashboard
- [x] Phase 7 — GitHub repo public, README complete with screenshots
- [x] Phase 8 — (Stretch) QuickBooks connector added and tested

---

## 8. Session Log

_Update this section at the end of every working session, in every tool. This is what carries context forward — treat it as more reliable than any chat history._

**Template for each entry:**
```
### Session N — [date] — [tool used, e.g. Claude Code / Cursor]
Done:
-
Blocked on:
-
Next:
-
```

(Add entries below this line as you go.)

### Session 1 — 2026-09-14 — Claude Code
Done:
- Scaffolded the repo per section 6: `requirements.txt`, `.env.example`, `README.md` skeleton, `src/` packages (`connectors`, `db`, `reconciliation`, `anomaly`, `variance`) with stub functions/signatures matching the plan's phases, `dashboard/app.py` Streamlit placeholder.
- Decided: `requests` + `requests-oauthlib` for OAuth (not the `xero-python` SDK — recheck its currency when Phase 2 starts); Streamlit (not Power BI) for the dashboard.
- Added `data/anomaly_answer_key.csv` to `.gitignore` ahead of it existing, since it's the private answer key.
- No `base.py`/`LedgerConnector` interface yet — deferred to Phase 8 (stretch) to avoid speculative abstraction.
Blocked on:
- Owner needs to: create a Python venv, create a Xero trial organisation (not the Demo Company), register a developer app at developer.xero.com (Client ID/Secret), and decide/register a redirect URI — none of this can be done from the coding tool.
Next:
- Phase 1: design the fictional SME, chart of accounts, contacts, and seed 2-3 months of invoices/bills/bank transactions with the planted anomalies (A1-A7+), keeping the private answer key.
- Once credentials exist: fill in `.env`, implement `src/connectors/xero_connector.py` for real (Phase 2).

### Session 2 (in progress) — 2026-09-14 — Claude Code
Done:
- Designed the mock company: Northbridge Creative, fictional UK (Manchester) digital marketing consultancy. Full spec in `data/northbridge_creative_seed_plan.md`; the 7 planted anomalies (A1-A7) and exact placement in `data/anomaly_answer_key.csv` (gitignored, private).
- Created the real Xero trial org: business name "NorthBridge Creative", UK, VAT registered (standard 20%), no employees, industry ~marketing/advertising, financial year end 31 March (kept Xero's default rather than forcing calendar year — doesn't affect the 3-month seed window either way; **seed plan doc still says "calendar year" for FY — should be corrected to 31 March for consistency, not yet done**).
- Navigated away from a paid "Grow" plan checkout (90% off, ~£4.68/mo) that Xero's signup routed to by default, and found the true no-card 30-day free trial instead.
- Onboarding: selected "Track cashflow", "Send invoices & get paid", "Manage and pay bills" as focus areas; skipped Claim expenses / Payroll (not needed — no employees).
- Created revenue account **405 "Retainer Fees"** (code 200 was already taken by a Xero default account — seed plan doc updated to say 405).
- Created and approved the first invoice: **Harlow & Finch Estate Agents**, £1,800 + 20% VAT, dated 01 Jun 2026, due 15 Jun 2026, account 405, ref "June Retainer" — done (had to correct the VAT rate from an initial wrong pick of 5% to the correct 20%).
Blocked on:
- Nothing — paused for a break, resuming later.
- All 6 June retainer invoices created and approved: Harlow & Finch (£1,800), Bramwell Dental (£1,200), Kestrel Outdoor Gear (£2,400), The Copper Kettle Café (£900), Ardent Fitness Studios (£1,500), Voss Architecture Partners (£1,100) — all dated 01 Jun 2026, due 15 Jun 2026, account 405, 20% VAT.
- All 8 June supplier bills created and approved (CloudStack £120, Meridian SaaS £180 zero-rated, J. Okafor £350 no VAT, M. Andersson £300 no VAT, Sterling & Rowe £250, Regus £950, BT Business £75, Staples £70 — all dated 03 Jun 2026, due 17 Jun 2026). June baseline (Phase 1) data entry complete.
- Corrected actual account codes used (differ from original doc, since some default codes were taken/reused): Software Subscriptions=402, Contractor & Freelancer Fees=406, Professional Fees=430, Office Supplies=413, Rent=469 (reused existing), Telephone & Internet=489 (reused existing). Both `data/northbridge_creative_seed_plan.md` and `data/anomaly_answer_key.csv` updated to match.
- All 7 July sales invoices approved: 6 retainer invoices (incl. Bramwell Dental entered twice — 01 Jul + 04 Jul — planting anomaly **A1**, done) + the Kestrel one-off project invoice (£1,600, account 260 Project Fees).
Blocked on:
- Nothing — paused for a break before starting July supplier bills.
Next (exact resume point):
- July supplier bills (8, same pattern/accounts/VAT as June — Meridian SaaS stays Zero Rated this month, that's still the "correct" baseline for the August A2 anomaly).
- Then August: retainer invoices (6) + Kestrel project invoice (~£3,200) + supplier bills (8), weaving in anomalies A2 (Meridian SaaS wrongly standard-rated), A3 (M. Andersson £499 one-off), A4 (Staples bill on a weekend), A7 (Staples £1,850 outlier bill).
- Then: manual bank account setup, ~45 bank transactions matching invoices/bills across all 3 months + anomalies A5 (duplicate Regus rent payment) and A6 (unmatched £85.40 bank line).

### Session 3 — 2026-09-15 — Claude Code (guided manual entry; claude-in-chrome unavailable this session)
Done:
- July: 8 supplier bills entered/approved (same pattern as June — Meridian SaaS still Zero Rated this month).
- August: 6 retainer invoices + Kestrel's one-off Project Fees invoice (£3,200, account 260, dated 14 Aug) approved. 10 supplier bills entered: 8 normal (Meridian SaaS deliberately standard-rated 20% = anomaly **A2**; Staples' normal bill dated Sat 01 Aug = anomaly **A4**) + 2 extras (M. Andersson £499 = anomaly **A3**; Staples £1,850 "office furniture and equipment" = anomaly **A7**).
- Manual bank account "Northbridge Business Current Account" created (no live feed). All 51 bank transactions entered across June/July/August: 20 sales receipts, 26 supplier payments (incl. the normal July Regus payment), 3 monthly bank-fee SPEND lines, plus the 2 standalone anomaly lines — **A5** (duplicate Regus £1,140 SPEND, 17 Jul, contact Regus Manchester, account 469 Rent, 20% VAT, not linked to any bill) and **A6** (£85.40 SPEND, 8 Aug, contact "Amazon Business" one-off, account 413 Office Supplies, 20% VAT, not linked to any bill). The Bramwell Dental duplicate invoice (04 Jul, anomaly **A1**) was correctly left unpaid/dangling.
- Corrected `data/northbridge_creative_seed_plan.md`: Bank Fees account is **404**, not 449 (449 wasn't available/didn't match the account name in the live org — same pattern as the earlier account-code corrections).
- Corrected `data/anomaly_answer_key.csv` A6 row to match actual implementation: Xero's Spend Money form requires a non-blank contact, so A6 uses a one-off "Amazon Business" contact and is coded to 413 Office Supplies with 20% VAT (Tax Exclusive, £71.17 + VAT = £85.40) rather than being left fully uncoded as originally drafted — still correctly unmatched to any bill/invoice, which is what makes it A6.
- Learned and recorded a new Xero gotcha (see memory): Spend Money forces a contact, and the "Amounts are" Tax Exclusive/Inclusive toggle needs to be set deliberately or VAT inflates the total past the intended figure.
- **Phase 1 is now complete** — full 3-month dataset (June–August 2026) seeded with all 7 planted anomalies (A1–A7), private answer key up to date. Master Checklist Phase 1 box checked.
Blocked on:
- Nothing.
Next:
- Phase 2: register the Xero developer app (Client ID/Secret), implement the OAuth 2.0 Authorization Code flow in `src/connectors/xero_connector.py`, and pull the 5 entities (Organisation, Invoices, Bills, BankTransactions, Accounts, Contacts) from the now-complete trial org.

### Session 4 — 2026-09-15 — Claude Code
Done:
- Python venv created, `requirements.txt` installed. Environment setup checklist item now checked.
- Implemented `src/connectors/xero_connector.py` in full: OAuth 2.0 Authorization Code flow (local callback server on `localhost:8080`, token exchange, refresh-token handling), tenant discovery via `/connections`, and GET wrappers for Organisation/Invoices/Bills(ACCPAY)/BankTransactions/Accounts/Contacts. Added `src/pull_data.py` as the one-command Phase 2 entrypoint (`python -m src.pull_data`) — auto-refreshes if a stored refresh token exists in `.env`, otherwise runs the browser consent flow and saves the resulting refresh token + tenant ID back to `.env` (`.env.example` updated to document `XERO_REFRESH_TOKEN`).
- Registered a Xero developer app (Web app type, redirect URI `http://localhost:8080/callback`), captured Client ID/Secret into `.env`.
Blocked on:
- **Xero OAuth consistently fails with `unauthorized_client` / "Unknown client or client not enabled"` on the login/consent page itself (before the user even clicks Allow), for two separately created apps.** Ruled out: wrong Client ID (verified byte-for-byte in `.env`, no whitespace/quote corruption), wrong app type (confirmed "Web app"), propagation delay (waited, retried, same result), Xero platform outage (status.xero.com reports all systems operational), browser session/cookie confusion (reproduces in a fresh incognito window). The owner also reports no verification email has ever arrived from Xero for this account (checked, not just missed) — this looks like an account-level activation issue on Xero's side, not something fixable from the coding side.
- Owner is contacting Xero support directly about this; Phase 2 (OAuth connection) can't proceed until the account issue is resolved and a consent flow actually reaches the "Allow access" screen.
Next (exact resume point):
- Once the owner confirms Xero support has resolved the account/app-enablement issue: re-run `python -m src.pull_data` (venv + code are already in place and shouldn't need changes) and complete the browser consent flow. If it still errors after that, revisit the connector code itself rather than assuming an account issue again.

### Session 5 — 2026-09-16 — Claude Code
Done:
- **Root cause of the Session 4 OAuth blocker found — it was never an account-activation issue.** The owner's Chrome extension (Claude in Chrome) inspected the Xero Developer Portal and found the real cause: Xero rolled out new granular OAuth scopes for apps created after 2 March 2026 (ours was created 2026-09-15), and our code was requesting the old broad scope `accounting.transactions`, which no longer exists for new apps — producing `invalid_scope`. Fixed by updating `SCOPE` in `src/connectors/xero_connector.py` to the granular read-only equivalents (`accounting.invoices.read`, `accounting.banktransactions.read`, `accounting.settings.read`, `accounting.contacts.read`).
- **Phase 2 complete.** Re-ran `python -m src.pull_data`, completed the consent screen, confirmed connection to "NorthBridge Creative Ltd.". Refresh token + tenant ID saved to `.env`.
- Discovered the initial pull returned only 5 BankTransactions (not the ~51 expected) — traced to Xero's data model: payments recorded via "Add Payment" directly on an invoice/bill land in a separate `/Payments` endpoint, not `/BankTransactions` (which only covers Spend/Receive Money lines). Added `get_payments()` to the connector, added the `accounting.payments.read` scope, and re-ran (required one more quick re-consent for the new scope). Final counts all reconcile against Session 3's seed data: Invoices 21, Bills 26, Bank transactions 5, Payments 46, Accounts 94, Contacts 16.
- Working style established for this session (owner's request): one step at a time, ask permission before each step, plain-English summary after each.
- **Phase 3 complete.** Added `payments` and `line_items` tables to `src/db/schema.sql` (line_items needed for Phase 5's A2 VAT-mismatch rule; not in the original schema — gap discovered while starting this step). Implemented all `upsert_*` functions in `src/db/load.py` and wired them into `pull_data.py` (`load_all()`) so one command (`python -m src.pull_data`) refreshes `data/ledger.db` end-to-end. Hit and fixed two more Xero API quirks while getting line items to populate — see [[xero-api-gotchas]] (new memory): the `SummaryOnly` query param is case-sensitive, and only takes effect at all if a `page` param is also present. Verified idempotent (re-running twice produced identical row counts) and spot-checked the A1 duplicate Bramwell Dental invoice loaded correctly (both £1,440 rows present, the duplicate correctly `AUTHORISED`/unpaid vs. the original `PAID`).
- **Project genericized for the public repo** (owner's request): renamed the project "NorthBridge Ledger Reconciliation & Anomaly Detection Agent" throughout, dropped all firm-specific naming from README.md and this plan file (see [[northbridge-ledger-agent-context]] for the naming-decision note), and renamed this file itself from `sumary-ledger-agent-plan.md` → `northbridge-ledger-agent-plan.md`.
- **Phase 4 complete.** Implemented `src/reconciliation/matcher.py` (amount/date/contact fuzzy matching of `bank_transactions` against invoices/bills) and `src/reconcile.py` as the one-command entrypoint (`python -m src.reconcile`). Ran against the live-loaded data: of the 5 standalone bank transactions, 1 exact match (correctly the A5 duplicate Regus £1,140 SPEND, matched to the real July Regus bill) and 4 unmatched (the 3 normal monthly NatWest bank-fee lines, which have no bill by design, plus anomaly A6 — the £85.40 Amazon Business line — correctly flagged unmatched). Note: `payments` (46 rows, Xero's own "Add Payment" records) are already directly linked to their invoice via FK and weren't run through fuzzy matching — nothing to reconcile there.
- **Phase 5 complete.** Implemented all five rule-based checks in `src/anomaly/rules.py` (A1 duplicate invoice: same contact+amount within a 10-day window; A2 VAT mismatch: flags a line item whose tax code breaks from *that contact's own* established pattern, not a per-account rule, since two different contacts share account 402 with different legitimate VAT treatments; A3 threshold-adjacent: amount within 5% below a configurable threshold; A4 weekend posting: `invoice_date.weekday() >= 5`; A5 duplicate payment: reuses Phase 4's `match_bank_transactions` to find a bill with both a normal Payment *and* a matching standalone bank transaction). Implemented the statistical layer in `src/anomaly/statistical.py` using a median/MAD "modified z-score" (robust to the very outlier it's detecting, unlike a plain mean/std z-score which gets skewed by the outlier itself in a small sample) — an optional `IsolationForest` path also exists via `method="isolation_forest"`. Added `src/detect_anomalies.py` as the one-command entrypoint (`python -m src.detect_anomalies`), which also folds in Phase 4's reconciliation-unmatched output for A6 (not a Phase 5 rule) so the full detector covers all 7 planted anomalies. Added `score_against_answer_key` to `statistical.py`, matching each answer-key row to detector output by `target_anomaly_id` + contact name.
- **Result: caught 7 of 7 planted anomalies (A1-A7), 3 false positives, precision 0.7, recall 1.0.** The 3 false positives are all the normal monthly NatWest bank-fee lines — genuinely unmatched (bank fees never have a bill), correctly flagged by the reconciliation layer as "unmatched," but not real coding errors, so they inflate the A6 false-positive count without representing an actual detector mistake. This is the honest number to put in the README, with that caveat stated plainly.
- **Phase 6 complete.** Implemented `src/variance/explainer.py`: `compute_account_movement` (account-level £/% change between two 'YYYY-MM' periods) and `explain_movement` (plain-English sentence naming the specific contact(s) driving the change). Rewrote `dashboard/app.py` from the placeholder into a real 3-section Streamlit demo (reconciliation summary → anomaly detection summary/score → variance explanations), reusing the Phase 4/5/6 functions directly rather than duplicating logic.
- Result for July→August (the interesting month, where most anomalies land): top 5 movers were Office Supplies +2643% (driven by the Staples A7 outlier), Project Fees +100% (Kestrel's real seasonal campaign growth — not an anomaly), Retainer Fees -12% (the A1 Bramwell duplicate reverting), Contractor & Freelancer Fees +77% (the A3 Andersson threshold bill), Software Subscriptions flat. Nice side-effect: the variance layer independently surfaces the same anomalies from a different angle (a real "why did this move" narrative), without being told about them.
- Verified: dashboard's underlying data logic executes with no exceptions (ran it directly with Streamlit's UI calls mocked out); the Streamlit server itself starts and responds healthy. Not visually screenshotted (no browser in this environment) — worth a quick manual `streamlit run dashboard/app.py` check.
Blocked on:
- Nothing.
Next (exact resume point):
- **Core engine (Phases 2-6) is done.** Phase 8 (QuickBooks stretch) remains.

### Session 6 — 2026-09-16 — Claude Code
Done:
- Owner requested dropping the screen-recorded walkthrough video from scope — removed it from this plan file (Definition of Done items, Phase 7 tasks/DoD, Master Checklist, tech-stack notes). README already had no such framing.
- **Phase 7 complete.** Rewrote `README.md`: updated status, added a "Running it" section with the actual CLI commands (`pull_data` / `reconcile` / `detect_anomalies` / `streamlit run`), added the real Phase 5 accuracy result (7/7 caught, precision 0.70, recall 1.00, with the false-positive caveat explained), and embedded a dashboard screenshot.
- Captured the screenshot with Playwright (system-level install, headless Chromium) driving the actual running Streamlit app — **this caught a real bug**: `streamlit run dashboard/app.py` doesn't add the project root to `sys.path` the way a plain `python -c` exec test does, so `from src... import` failed with `ModuleNotFoundError` on first real run despite passing an earlier (misleading) mocked-logic test. Fixed by inserting the project root into `sys.path` at the top of `dashboard/app.py`. Re-verified with a fresh screenshot showing all 3 sections (reconciliation, anomalies, variance) rendering real data correctly. Saved to `dashboard/screenshots/dashboard-full.png`.
- Ran a secrets scan before committing (grepped for client_id/secret/password patterns across trackable files) — clean, nothing hardcoded outside `.env` (gitignored).
- **Created the public GitHub repo and pushed:** https://github.com/VAishwaryaSingh/northbridge-ledger-agent (first commit, all Phase 1-7 work included; `.env`, `data/ledger.db`, `data/anomaly_answer_key.csv`, and `venv/` correctly excluded via `.gitignore`).
- Owner asked to remove a non-project planning phase (Phase 9) from the plan doc entirely, since it's committed to the public repo — removed the Phase 9 section, its Definition-of-Done list item, and its Master Checklist line.
- **Deployed the dashboard live and linked it from the repo's GitHub "About" section.** Since `dashboard/app.py` only reads from a local SQLite file and the private answer key, and neither is committed (by design), added a fallback: a frozen demo snapshot (`data/demo_ledger.db`, added as a `.gitignore` exception) and a `PUBLISHED_SCORE` constant matching the real README result, used whenever the live-pulled DB / private answer key aren't present. Verified the fallback locally first (temporarily moved the real files aside, screenshotted, confirmed identical output, restored them) before the owner deployed to Streamlit Community Cloud themselves (I don't have browser/OAuth access to do that step). Live at **https://northbridge-ledger-agent.streamlit.app/** — verified working via a fresh screenshot of the actual deployed URL. Set as the GitHub repo's homepage/About link via `gh repo edit --homepage`, and added to the README.
Blocked on:
- Nothing.
Next (exact resume point):
- Phase 8 (stretch) — QuickBooks connector. Waiting on the owner to register a developer.intuit.com app + confirm a sandbox company exists (same pattern as Xero Phase 2) before writing `src/connectors/quickbooks_connector.py`.

### Session 7 — 2026-09-16 — Claude Code
Done:
- Owner registered the Intuit developer app and sandbox company. Hit two setup snags along the way: (1) the redirect URI kept failing "unique valid redirect URI" validation on `http://localhost:8080/qb-callback` for no obvious reason — switched to port 8000 (`http://localhost:8000/qb-callback`) and it was accepted; (2) the redirect URI field the error pointed to ("your app's keys tab") was actually a separate **Settings → Redirect URIs** page from the Keys & credentials page, and needed an explicit "Add URI" + "Save" click (not just typing into the box) to actually persist.
- **Phase 8 complete.** Built `src/connectors/quickbooks_connector.py` (OAuth 2.0 flow mirroring the Xero connector; QBO's callback returns a `realmId` alongside `code`, the one structural OAuth difference) and confirmed a live connection to the Intuit sandbox company ("Sandbox Company US f197").
- Rather than a full abstract `LedgerConnector` interface rewrite, built `src/connectors/quickbooks_adapter.py`: normalizes QBO's API shapes (Customer/Vendor, Purchase/Deposit, Payment/BillPayment, Item-vs-Account-coded lines) into the same Xero-shaped dicts `src/db/load.py` already expects, so the existing upsert/reconciliation/anomaly/variance code runs unchanged against QuickBooks data. Documented QBO's genuine structural differences from Xero in the adapter's docstring rather than hiding them.
- Loaded a second local database, `data/ledger_quickbooks.db`, via an extended `src/pull_data_quickbooks.py`. Caught and fixed a real bug while doing this: QBO line-item `Id` values (1, 2, 3...) are only unique *within* their own transaction, not globally, so using them directly as the shared `line_items` table's primary key caused massive collisions across different invoices (76 real line items collapsed to 5). Fixed by always prefixing with the parent transaction's ID.
- Added a `--db` flag to `src/reconcile.py` and `src/detect_anomalies.py` (plus `--no-score` on the latter, since there's no planted-anomaly answer key for the QuickBooks sandbox) so the *same* scripts run against either ledger.
- **Ran all three engine phases against real QuickBooks sandbox data:** reconciliation (40 standalone Purchase/Deposit transactions, 0% auto-matched — an honest, explainable result: this sandbox's data mostly uses direct Purchase entries rather than Bill+Payment pairs, unlike Northbridge's Xero data), anomaly detection (found 2 *real, unplanted* coincidences in Intuit's own canned data — a genuine duplicate-looking invoice pattern for "Sushi by Katsuyuki" and a bill dated on a Sunday for "Robertson & Associates" — plus the 40 unmatched-line flags), and variance explanation (July→August movement, e.g. "Miscellaneous up 1806%... driven by Brosnahan Insurance Agency and Cool Cars").
- Deliberately did not seed planted anomalies + a QuickBooks-specific answer key (the plan's own Phase 8 notes flag this as disproportionate effort for a stretch goal) — the QuickBooks result demonstrates the engine is ledger-agnostic using real sandbox data as-is, not a scored accuracy claim.
Blocked on:
- Nothing.
Next (exact resume point):
- All planned phases (1-8) are now complete. Optionally: extend the Streamlit dashboard with a ledger picker (Xero/QuickBooks) if the owner wants QuickBooks visible in the live demo too — not yet done, `data/ledger_quickbooks.db` isn't committed/shipped as a demo snapshot.

### Session 8 — 2026-09-16 — Claude Code
Done:
- Owner asked for QuickBooks to appear as its own section in the same live dashboard (not just CLI output), "so viewers can see it works on multiple ERPs." Refactored `dashboard/app.py` into reusable `render_reconciliation`/`detect_all`/`render_variance` helpers and called them twice — once against the Xero connection (sections 1-3, unchanged), once against a second QuickBooks connection (new sections 4-6) — separated by a divider and a caption explaining there's no planted-anomaly answer key on the QuickBooks side.
- Shipped `data/demo_ledger_quickbooks.db` (frozen snapshot, `.gitignore` exception added) so the QuickBooks section works on the public deployment the same way the Xero section already does.
- Updated README: architecture diagram now shows the QuickBooks connector/adapter path, "Running it" has the QuickBooks CLI commands, and a new "Multi-ledger proof (QuickBooks)" section explains the result. Replaced the dashboard screenshot with one showing both ERP sections.
- Streamlit Community Cloud's auto-redeploy-on-push was unusually slow this time (~10+ minutes polling showed no change) — owner manually triggered "Reboot app" from the Streamlit Cloud dashboard, which picked up the new code within a couple of minutes. Worth trying a manual reboot first if a future push doesn't show up promptly.
- Owner confirmed the live deployment now shows all 6 sections (Xero 1-3, QuickBooks 4-6) correctly.
Blocked on:
- Nothing.
Next (exact resume point):
- All planned phases (1-8) are complete and live. Nothing outstanding.
