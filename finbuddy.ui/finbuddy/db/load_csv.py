"""Load a cleaned FinBuddy CSV into a new SQLite database."""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from pathlib import Path

from .database import Database, Transaction


EXPECTED_COLUMNS = [
    "raw_text",
    "amount",
    "date",
    "txn_type",
    "merchant",
    "category",
]


def load_csv(
    input_path: Path,
    output_path: Path,
    *,
    replace: bool = False,
    append: bool = False,
) -> int:
    """Load *input_path* into *output_path* and return the inserted row count."""
    if replace and append:
        raise ValueError("--replace and --append cannot be used together")
    if output_path.exists() and not replace:
        if not append:
            raise FileExistsError(
                f"Database already exists: {output_path}. "
                "Use --append to add rows or --replace to rebuild it."
            )

    with input_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPECTED_COLUMNS:
            raise ValueError(
                "CSV columns must be exactly: " + ", ".join(EXPECTED_COLUMNS)
            )

        transactions = []
        for row_number, row in enumerate(reader, start=2):
            try:
                transactions.append(
                    Transaction(
                        raw_text=row["raw_text"],
                        amount=Decimal(row["amount"]),
                        date=row["date"],
                        txn_type=row["txn_type"],
                        merchant=row["merchant"] or None,
                        category=row["category"],
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"Invalid CSV row {row_number}: {error}") from error

    if replace and output_path.exists():
        output_path.unlink()

    with Database(output_path) as database:
        return database.add_transactions(transactions, import_source=input_path.name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=Path("data/testing/sms_transactions_refined.csv"),
        help="cleaned CSV input path",
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=Path("data/testing.sqlite3"),
        help="SQLite output path",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing SQLite database",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="append rows to an existing SQLite database",
    )
    args = parser.parse_args()

    inserted = load_csv(
        args.input,
        args.output,
        replace=args.replace,
        append=args.append,
    )
    print(f"Loaded {inserted} transactions into {args.output}")


if __name__ == "__main__":
    main()
