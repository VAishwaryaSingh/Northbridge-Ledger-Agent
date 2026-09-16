"""Phase 4 entrypoint: run reconciliation against the local database and print a report.

Run with: python -m src.reconcile
"""

from __future__ import annotations

import json
import sqlite3

from src.db.load import DB_PATH
from src.reconciliation.matcher import build_reconciliation_report, match_bank_transactions


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    matches = match_bank_transactions(conn)
    report = build_reconciliation_report(matches)
    conn.close()

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
