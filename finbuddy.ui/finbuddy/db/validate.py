"""Validate a FinBuddy SQLite database without changing it."""

from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import date
from pathlib import Path


REQUIRED_COLUMNS = {
    "raw_text",
    "amount_paise",
    "date",
    "txn_type",
    "merchant",
    "category",
    "import_batch_id",
}
ALLOWED_TYPES = {"debit", "credit"}
ALLOWED_CATEGORIES = {
    "Food",
    "Travel",
    "Shopping",
    "Bills/Recharge",
    "Fees",
    "Entertainment",
    "Others",
}


def validate_database(path: str | Path) -> list[str]:
    """Return validation errors for *path*; return an empty list when valid."""
    database_path = Path(path)
    if not database_path.exists():
        return [f"database does not exist: {database_path}"]

    errors: list[str] = []
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "transactions" not in tables:
            return ["missing transactions table"]
        if "import_batches" not in tables:
            return ["missing import_batches table"]

        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(transactions)")
        }
        missing_columns = REQUIRED_COLUMNS - columns
        if missing_columns:
            errors.append("missing columns: " + ", ".join(sorted(missing_columns)))
            return errors

        rows = connection.execute(
            """
            SELECT id, raw_text, amount_paise, date, txn_type, merchant, category
            FROM transactions
            """
        ).fetchall()
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        for foreign_key_error in foreign_key_errors:
            errors.append(
                "foreign key violation in table "
                f"{foreign_key_error[0]} at row {foreign_key_error[1]}"
            )
        for row in rows:
            prefix = f"transaction id {row['id']}"
            if row["raw_text"] is None or not str(row["raw_text"]).strip():
                errors.append(f"{prefix}: raw_text is missing")
            elif len(row["raw_text"]) > 10_000:
                errors.append(f"{prefix}: raw_text exceeds 10000 characters")
            if row["amount_paise"] is None:
                errors.append(f"{prefix}: amount is missing")
            elif not isinstance(row["amount_paise"], int):
                errors.append(f"{prefix}: amount_paise is not an integer")
            elif row["amount_paise"] < 0:
                errors.append(f"{prefix}: amount is negative")
            elif row["amount_paise"] > 99_999_999_999:
                errors.append(f"{prefix}: amount exceeds ₹999,999,999.99")
            if row["date"] is None or not isinstance(row["date"], str):
                errors.append(f"{prefix}: date is missing or not text")
            else:
                try:
                    parsed_date = date.fromisoformat(row["date"])
                except ValueError:
                    errors.append(f"{prefix}: date is not ISO YYYY-MM-DD")
                else:
                    if (
                        len(row["date"]) != 10
                        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date"])
                        or parsed_date.isoformat() != row["date"]
                    ):
                        errors.append(f"{prefix}: date is not exact YYYY-MM-DD")
            if row["txn_type"] not in ALLOWED_TYPES:
                errors.append(f"{prefix}: unsupported txn_type {row['txn_type']!r}")
            if row["category"] not in ALLOWED_CATEGORIES:
                errors.append(f"{prefix}: unsupported category {row['category']!r}")
            merchant = row["merchant"]
            if merchant is not None:
                if not str(merchant).strip():
                    errors.append(f"{prefix}: blank merchant should be NULL")
                elif len(str(merchant)) > 256:
                    errors.append(f"{prefix}: merchant exceeds 256 characters")
    finally:
        connection.close()

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "database",
        nargs="?",
        type=Path,
        default=Path("data/testing.sqlite3"),
        help="SQLite database to validate",
    )
    args = parser.parse_args()
    errors = validate_database(args.database)
    if errors:
        print(f"FAIL: {len(errors)} database issue(s) found")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print(f"PASS: {args.database} has no database validation issues")


if __name__ == "__main__":
    main()
