"""Normalizes QuickBooks Online API data into the same shape Xero's raw API
JSON has — so `src/db/load.py`'s existing upsert_* functions (written against
Xero's field names) work unchanged against QuickBooks data too. This is the
practical form of "ledger-agnostic": one shared schema/engine, one adapter per
connector, rather than a heavier abstract-interface rewrite of code that
already works.

Known simplifications (documented rather than hidden — QBO's data model
genuinely doesn't map 1:1 to Xero's):
- QuickBooks splits contacts into Customer/Vendor with separate ID sequences
  that can collide, so IDs are prefixed ("CUST-"/"VEND-") to stay unique in
  the shared `contacts` table.
- Invoice (sales) lines reference an Item, not an Account directly — ItemRef
  is used as the line's "account code" stand-in, since QBO doesn't expose the
  Item's underlying income account without a separate Items API call.
- QuickBooks has no single "BankTransactions" entity: standalone spend
  (Purchase) and standalone receipts (Deposit) are mapped to Xero's
  SPEND/RECEIVE bank-transaction shape respectively.
"""

from __future__ import annotations


def to_accounts(qb_accounts: list[dict]) -> list[dict]:
    return [
        {
            "AccountID": a["Id"],
            "Code": a.get("AcctNum") or a["Id"],
            "Name": a.get("Name"),
            "Type": a.get("AccountType"),
            "TaxType": None,
        }
        for a in qb_accounts
    ]


def to_contacts(customers: list[dict], vendors: list[dict]) -> list[dict]:
    contacts = [
        {
            "ContactID": f"CUST-{c['Id']}",
            "Name": c.get("DisplayName") or c.get("CompanyName") or c["Id"],
            "IsCustomer": True,
            "IsSupplier": False,
        }
        for c in customers
    ]
    contacts += [
        {
            "ContactID": f"VEND-{v['Id']}",
            "Name": v.get("DisplayName") or v.get("CompanyName") or v["Id"],
            "IsCustomer": False,
            "IsSupplier": True,
        }
        for v in vendors
    ]
    return contacts


def _sales_line_items(qb_id: str, lines: list[dict]) -> list[dict]:
    # QBO line "Id" values (1, 2, 3...) are only unique within their own transaction,
    # not globally — always prefix with the parent transaction's ID to avoid collisions
    # across different invoices in the shared line_items table.
    items = []
    for i, line in enumerate(lines):
        detail = line.get("SalesItemLineDetail")
        if not detail:
            continue  # skip SubTotalLineDetail / DiscountLineDetail summary rows
        items.append(
            {
                "LineItemID": f"{qb_id}-{line.get('Id', i)}",
                "AccountCode": (detail.get("ItemRef") or {}).get("value"),
                "Description": line.get("Description"),
                "Quantity": detail.get("Qty"),
                "UnitAmount": detail.get("UnitPrice"),
                "LineAmount": line.get("Amount"),
                "TaxType": (detail.get("TaxCodeRef") or {}).get("value"),
                "TaxAmount": None,
            }
        )
    return items


def _expense_line_items(qb_id: str, lines: list[dict]) -> list[dict]:
    items = []
    for i, line in enumerate(lines):
        # Bills can code a line to an Account directly, or to an Item (whose
        # underlying account isn't exposed without a separate Items API call) —
        # handle both, using whichever ref is available as the "account code".
        detail = line.get("AccountBasedExpenseLineDetail")
        ref_key = "AccountRef"
        if not detail:
            detail = line.get("ItemBasedExpenseLineDetail")
            ref_key = "ItemRef"
        if not detail:
            continue
        items.append(
            {
                "LineItemID": f"{qb_id}-{line.get('Id', i)}",
                "AccountCode": (detail.get(ref_key) or {}).get("value"),
                "Description": line.get("Description"),
                "Quantity": detail.get("Qty", 1),
                "UnitAmount": detail.get("UnitPrice", line.get("Amount")),
                "LineAmount": line.get("Amount"),
                "TaxType": (detail.get("TaxCodeRef") or {}).get("value"),
                "TaxAmount": None,
            }
        )
    return items


def to_invoices(qb_invoices: list[dict]) -> list[dict]:
    """QBO Invoice -> Xero-shaped ACCREC invoice."""
    result = []
    for inv in qb_invoices:
        qb_id = inv["Id"]
        customer_ref = inv.get("CustomerRef") or {}
        result.append(
            {
                "InvoiceID": f"INV-{qb_id}",
                "Contact": {"ContactID": f"CUST-{customer_ref.get('value')}"},
                "Type": "ACCREC",
                "DateString": inv.get("TxnDate"),
                "DueDateString": inv.get("DueDate"),
                "Total": inv.get("TotalAmt"),
                "LineAmountTypes": None,
                "Status": "PAID" if float(inv.get("Balance", 0) or 0) == 0 else "AUTHORISED",
                "LineItems": _sales_line_items(qb_id, inv.get("Line", [])),
            }
        )
    return result


def to_bills(qb_bills: list[dict]) -> list[dict]:
    """QBO Bill -> Xero-shaped ACCPAY invoice (bill)."""
    result = []
    for bill in qb_bills:
        qb_id = bill["Id"]
        vendor_ref = bill.get("VendorRef") or {}
        result.append(
            {
                "InvoiceID": f"BILL-{qb_id}",
                "Contact": {"ContactID": f"VEND-{vendor_ref.get('value')}"},
                "Type": "ACCPAY",
                "DateString": bill.get("TxnDate"),
                "DueDateString": bill.get("DueDate"),
                "Total": bill.get("TotalAmt"),
                "LineAmountTypes": None,
                "Status": "PAID" if float(bill.get("Balance", 0) or 0) == 0 else "AUTHORISED",
                "LineItems": _expense_line_items(qb_id, bill.get("Line", [])),
            }
        )
    return result


def to_bank_transactions(purchases: list[dict], deposits: list[dict]) -> list[dict]:
    """QBO Purchase (standalone spend) + Deposit (standalone receipt) -> Xero-shaped bank transactions."""
    result = []
    for p in purchases:
        entity = p.get("EntityRef") or {}
        contact_id = f"VEND-{entity['value']}" if entity.get("type") == "Vendor" else None
        result.append(
            {
                "BankTransactionID": f"PUR-{p['Id']}",
                "Contact": {"ContactID": contact_id} if contact_id else {},
                "DateString": p.get("TxnDate"),
                "Total": p.get("TotalAmt"),
                "Type": "SPEND",
                "IsReconciled": False,
            }
        )
    for d in deposits:
        lines = d.get("Line", [])
        entity = (lines[0].get("DepositLineDetail", {}).get("Entity") if lines else None) or {}
        contact_id = f"CUST-{entity['value']}" if entity.get("type") == "Customer" else None
        result.append(
            {
                "BankTransactionID": f"DEP-{d['Id']}",
                "Contact": {"ContactID": contact_id} if contact_id else {},
                "DateString": d.get("TxnDate"),
                "Total": d.get("TotalAmt"),
                "Type": "RECEIVE",
                "IsReconciled": False,
            }
        )
    return result


def to_payments(payments: list[dict], bill_payments: list[dict]) -> list[dict]:
    """QBO Payment (AR) + BillPayment (AP) -> Xero-shaped payments, one row per linked invoice/bill."""
    result = []
    for pmt in payments:
        deposit_account = (pmt.get("DepositToAccountRef") or {}).get("value")
        for line in pmt.get("Line", []):
            for linked in line.get("LinkedTxn", []):
                if linked.get("TxnType") != "Invoice":
                    continue
                result.append(
                    {
                        "PaymentID": f"PMT-{pmt['Id']}-{linked['TxnId']}",
                        "Invoice": {"InvoiceID": f"INV-{linked['TxnId']}"},
                        "Account": {"AccountID": deposit_account},
                        "DateString": pmt.get("TxnDate"),
                        "Amount": line.get("Amount"),
                        "PaymentType": "ACCRECPAYMENT",
                        "Status": "PAID",
                    }
                )
    for bp in bill_payments:
        bank_account = (
            (bp.get("CheckPayment") or {}).get("BankAccountRef")
            or (bp.get("CreditCardPayment") or {}).get("BankAccountRef")
            or {}
        ).get("value")
        for line in bp.get("Line", []):
            for linked in line.get("LinkedTxn", []):
                if linked.get("TxnType") != "Bill":
                    continue
                result.append(
                    {
                        "PaymentID": f"BPMT-{bp['Id']}-{linked['TxnId']}",
                        "Invoice": {"InvoiceID": f"BILL-{linked['TxnId']}"},
                        "Account": {"AccountID": bank_account},
                        "DateString": bp.get("TxnDate"),
                        "Amount": line.get("Amount"),
                        "PaymentType": "ACCPAYPAYMENT",
                        "Status": "PAID",
                    }
                )
    return result
