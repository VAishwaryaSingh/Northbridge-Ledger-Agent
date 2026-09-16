# Northbridge Creative — mock company seed plan

Fictional digital marketing & brand consultancy, used as the Xero trial org
for this project. Nothing here refers to a real business.

## Company profile

- **Legal name:** Northbridge Creative Ltd
- **Industry:** Digital marketing & brand consultancy
- **Location:** Manchester, UK
- **Currency:** GBP
- **VAT:** Registered, UK standard rate 20%, quarterly returns
- **Financial year:** ends 31 March (Xero default for UK orgs; doesn't affect the seed window below either way)
- **Bank account:** one business current account (e.g. name it "Northbridge Business Current Account" in Xero)
- **Seed data window:** June, July, August 2026 (3 full months, ending just before today)

## Chart of accounts

Use Xero's default COA, lightly customised with these accounts (create if missing, rename Xero defaults where close enough):

**Revenue**
| Code | Name |
|---|---|
| 405 | Retainer Fees |
| 260 | Project Fees |

**Operating expenses**
| Code | Name |
|---|---|
| 400 | Advertising & Marketing |
| 402 | Software Subscriptions |
| 406 | Contractor & Freelancer Fees |
| 413 | Office Supplies |
| 420 | Travel & Entertainment |
| 469 | Rent (reused existing Xero account, not a new one) |
| 430 | Professional Fees |
| 489 | Telephone & Internet (reused existing Xero account, not a new one) |
| 404 | Bank Fees |

Balance sheet accounts (Business Bank Account, Accounts Receivable, Accounts Payable, VAT) — use Xero's defaults.

## Contacts

**Customers (6)** — pay Northbridge a monthly retainer, standard-rated VAT on all sales:

| Contact | Sector | Monthly retainer (ex VAT) |
|---|---|---|
| Harlow & Finch Estate Agents | Property | £1,800 |
| Bramwell Dental Practice | Healthcare | £1,200 |
| Kestrel Outdoor Gear | E-commerce retail | £2,400 |
| The Copper Kettle Café | Hospitality (3 sites) | £900 |
| Ardent Fitness Studios | Fitness chain | £1,500 |
| Voss Architecture Partners | Professional services | £1,100 |

**Suppliers (8)** — Northbridge's own costs:

| Contact | What they supply | VAT treatment | Typical monthly cost (ex VAT) |
|---|---|---|---|
| CloudStack Hosting Ltd | Website hosting (UK-based) | Standard 20% | £120 |
| Meridian SaaS (Ireland) | Marketing analytics software (EU B2B digital service) | Reverse charge / zero-rated for UK VAT purposes | £180 |
| J. Okafor Design | Freelance graphic designer (sole trader, below VAT threshold) | No VAT | £350 |
| M. Andersson Copywriting | Freelance copywriter (sole trader, below VAT threshold) | No VAT | £300 |
| Sterling & Rowe Accountants | Bookkeeping/accounting fees | Standard 20% | £250 |
| Regus Manchester | Serviced office rent | Standard 20% | £950 |
| BT Business | Telephone & internet | Standard 20% | £75 |
| Staples Business Supplies | Office supplies | Standard 20% | £70 (varies) |

## Recurring monthly pattern (repeat for June, July, August 2026)

For each customer: one retainer invoice (ACCREC) on/around the 1st of the month, coded to 200 Retainer Fees, standard VAT, paid in full by bank transfer ~7–14 days later (create the matching bank RECEIVE transaction).

For each supplier: one bill (ACCPAY) on/around the 1st–5th of the month, coded to the relevant expense account above, paid by bank transfer ~7–14 days later (matching bank SPEND transaction).

This gives a baseline of 6×3 = 18 invoices, 8×3 = 24 bills, and ~42 matching bank transactions before any one-offs or planted anomalies are added.

## One-off / non-recurring items (real business texture, not anomalies)

- **Kestrel Outdoor Gear** — add 2 extra Project Fees invoices (260), one in July (~£1,600, a seasonal campaign) and one in August (~£3,200, a bigger autumn campaign). This is what should drive a visible revenue variance for Kestrel between July and August in Phase 6.
- A small **bank fee** transaction (449 Bank Fees, ~£15–25) in each of the 3 months, no invoice/bill behind it — normal, not a reconciliation gap.

## What goes where next

- Type all of the above directly into the Xero trial org UI (Phase 1).
- The specific planted anomalies (which line becomes A1–A7, exact contact/date/amount) are recorded separately in `data/anomaly_answer_key.csv` — gitignored, private, not meant to be guessable just from this file.
- Keep this file as the "clean" reference for what the business is supposed to look like; it can be shared/reused later (e.g. in the README) without spoiling the anomaly-detection test.
