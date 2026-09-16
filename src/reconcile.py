"""Phase 4 entrypoint: run reconciliation against the local database and print a report.

Run with: python -m src.reconcile [--db data/ledger_quickbooks.db]
"""

from __future__ import annotations

import argparse
import json
import sqlite3

from src.db.load import DB_PATH
from src.reconciliation.matcher import build_reconciliation_report, match_bank_transactions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DB_PATH, help="Path to the ledger database (default: %(default)s)")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    matches = match_bank_transactions(conn)
    report = build_reconciliation_report(matches)
    conn.close()

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
