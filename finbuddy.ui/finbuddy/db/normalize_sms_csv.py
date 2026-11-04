"""Normalize a refined SMS CSV without changing its raw message text."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


EXPECTED_COLUMNS = [
    "raw_text",
    "amount",
    "date",
    "txn_type",
    "merchant",
    "category",
]

GENERIC_MERCHANTS = {
    "",
    "Not specified",
    "A/c",
    "a/c no",
    "ATM",
    "Rs",
    "UPI recipient",
    "Paytm QR recipient",
    "UPI: VPA",
    "UPI: a/c",
}


def clean_merchant(value: str) -> str:
    """Return a useful merchant label, or an empty value when unreliable."""
    merchant = value.strip()
    if merchant in GENERIC_MERCHANTS:
        return ""
    lowered = merchant.lower()
    noisy_markers = (
        "block account",
        "report fraud",
        "call 1800",
        "call 0120",
        "call 0944",
    )
    if any(marker in lowered for marker in noisy_markers):
        return ""
    if re.search(r"\b(?:a/c|account)\b", lowered) and not re.search(
        r"[a-z]{3,}", lowered.replace("account", "")
    ):
        return ""
    return merchant


def normalize(input_path: Path, output_path: Path) -> int:
    with input_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != EXPECTED_COLUMNS:
            raise ValueError(
                "CSV columns must be exactly: " + ", ".join(EXPECTED_COLUMNS)
            )
        rows = []
        for row_number, row in enumerate(reader, start=2):
            if row["txn_type"] not in {"debit", "credit"}:
                raise ValueError(f"row {row_number}: invalid txn_type")
            if row["category"] not in {
                "Food",
                "Travel",
                "Shopping",
                "Bills/Recharge",
                "Fees",
                "Entertainment",
                "Others",
            }:
                raise ValueError(f"row {row_number}: invalid category")
            row["merchant"] = clean_merchant(row["merchant"])
            rows.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=EXPECTED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(f"Normalized {normalize(args.input, args.output)} transactions")


if __name__ == "__main__":
    main()
