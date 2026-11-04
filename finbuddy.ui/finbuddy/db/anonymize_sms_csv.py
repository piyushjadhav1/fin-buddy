"""Create a shareable, structure-preserving copy of a cleaned SMS CSV."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from pathlib import Path


COLUMNS = ["raw_text", "amount", "date", "txn_type", "merchant", "category"]


def token(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"<{prefix}_{digest}>"


def anonymize_text(text: str) -> str:
    # Remove URLs first so numbers inside links are not mistaken for account data.
    text = re.sub(r"https?://\S+", "<URL>", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\+?91[-\s]?\d{10}\b", "<PHONE>", text)
    text = re.sub(r"\b\d{10}\b", "<PHONE>", text)
    text = re.sub(r"(?<!\d)\d{10}(?=[_@])", "<PHONE>", text)
    text = re.sub(r"\b\d{10}[A-Za-z_][A-Za-z0-9_]*\b", "<REFERENCE>", text)
    text = re.sub(r"\b(?:\d[ -]?){12,16}\b", "<REFERENCE>", text)
    text = re.sub(r"(?i)(a/c|account|acct|card)(\s*(?:no\.?|number)?)?\s*[:#-]?\s*[xX*\d-]{4,}", r"\1 <ACCOUNT>", text)
    text = re.sub(r"(?i)\b(?:vpa|upi\s*id)\s+[\w.-]+@[\w.-]+", "VPA <UPI_ID>", text)
    text = re.sub(r"\b[\w.-]+@[\w.-]+\b", "<UPI_ID>", text)
    # Redact receipt, loan, and reference tokens that mix letters and digits.
    text = re.sub(
        r"\b(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{8,}\b",
        "<REFERENCE>",
        text,
    )
    return text


def anonymize(input_path: Path, output_path: Path) -> int:
    with input_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != COLUMNS:
            raise ValueError("input must contain the cleaned six-column schema")
        rows = []
        for row in reader:
            row["raw_text"] = anonymize_text(row["raw_text"])
            if row["merchant"]:
                row["merchant"] = token("MERCHANT", row["merchant"])
            rows.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(f"Anonymized {anonymize(args.input, args.output)} transactions")


if __name__ == "__main__":
    main()
