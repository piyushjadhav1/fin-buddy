# FinBuddy database layer

The database stores cleaned bank/UPI transactions in SQLite.

## Run the FinBuddy web app with SQLite

From the FinBuddy project folder, start the local backend with:

```bash
python3 server.py
```

Or double-click `Start FinBuddy.command` in the parent FinBuddy folder. This
starts a dependency-free Python server on `127.0.0.1:8000` and opens the web
app. The server reads and writes `data/app.sqlite3` and is only reachable from
this computer. The HTML page uses this API for transaction history, additions,
and deletions. Budget, theme, saving goal, and notification preferences remain
in this browser's local storage.

The web API provides `GET /api/health`, `GET /api/transactions` (debits by
default), `POST /api/transactions`, and `DELETE /api/transactions/{id}`. The
transaction API does not return `raw_text`, which can contain sensitive SMS or
UPI notification content.

Stop the server with `Control-C` in its Terminal window. If you open `index.html`
directly instead of using the server, the page stays in local-preview mode and
does not use SQLite.

Python 3.10 or newer is required. No third-party Python packages are needed.

The parser integration rules are documented in
[PARSER_CONTRACT.md](PARSER_CONTRACT.md).
The field definitions and current decisions are in
[DATA_DICTIONARY.md](DATA_DICTIONARY.md).
The schema review and implementation results are in
[SCHEMA_REVIEW.md](SCHEMA_REVIEW.md).

## Rebuild a testing database

From the project root, run:

```bash
python3 -m db.load_csv
```

This reads `data/testing/sms_transactions_refined.csv` and creates
`data/testing.sqlite3`. Existing databases are protected by default. To
append a new cleaned CSV to an existing app database, run:

```bash
python3 -m db.load_csv path/to/new_transactions.csv data/app.sqlite3 --append
```

Existing databases are protected by default. To intentionally rebuild one,
add `--replace`.

## Validate a database

Run the validation checks with:

```bash
python3 -m db.validate data/testing.sqlite3
```

## Migrate existing databases

Back up and migrate the local testing and app databases with:

```bash
python3 -m db.migrate
```

The migration writes a SQLite backup under `data/backups/` before changing an
existing database. It converts stored rupee values to integer paise, adds the
contract constraints, and adds optional CSV import-batch provenance. Only the
input filename is stored, not its full path. To migrate one database explicitly:

```bash
python3 -m db.migrate data/testing.sqlite3
```

The parser and Python API continue to accept `amount` in rupees. Reads expose
`amount` in rupees and `amount_paise` as the exact stored integer. Use
`Database.delete_transaction(id)` for permanent deletion. The data layer does
not provide an edit operation.

CSV loads record an import batch with the input filename and associate the
loaded transactions with it. Use `Database.list_import_batches()` to view batch
metadata and current associated row counts. Direct inserts without an
`import_source` remain unbatched; existing rows keep unknown provenance.

Repeated transactions must be detected and flagged as possible duplicates,
but each is stored as a separate row and counts separately in spending
totals. The database must not block, merge, or automatically delete them. The
database computes these flags on demand by matching date, amount, transaction
type, and trimmed case-insensitive merchant. If merchant is unavailable, it
matches normalized raw message text instead. Use
`Database.list_duplicate_candidates()` to retrieve every row in a matching
group; a match is only a review candidate, not proof of duplication.

## Normalize the SMS CSV

The attached SMS workbook has already been converted into the local refined
CSV. To apply the same merchant cleanup to a replacement refined CSV, run:

```bash
python3 -m db.normalize_sms_csv input.csv output.csv
python3 -m db.load_csv output.csv data/testing.sqlite3 --replace
python3 -m db.validate data/testing.sqlite3
```

Dataset-specific decisions and known data-quality issues are documented in
[DATASET_NOTES.md](DATASET_NOTES.md).

To create a shareable anonymized copy of the testing CSV, run:

```bash
python3 -m db.anonymize_sms_csv \
  data/testing/sms_transactions_refined.csv \
  data/testing/sms_transactions_anonymized.csv
```

The checks cover required fields, ISO dates, non-negative amounts, supported
transaction types, and supported categories. A missing merchant is allowed.

The anonymized CSV is intended for sharing after a human sample review. The
automatic redaction preserves parser patterns but does not guarantee that every
personal detail has been removed.

## Critical-thinking checkpoint

Before changing the database schema, import rules, or validation logic, pause
and question the assumptions behind the change:

- Is this message a real transaction, or an advertisement, balance alert, loan
  offer, refund, or other non-spending message?
- Is the extracted amount the transaction amount, rather than a balance, limit,
  reference number, or another amount appearing in the message?
- Are the currency, date, debit/credit direction, category mapping, and
  duplicate policy explicit and tested?
- Could this change silently discard data, change existing totals, break the
  parser contract, or make old databases unreadable?
- Are sensitive SMS contents being exposed unnecessarily?

When an assumption is uncertain, preserve the original data, record the issue,
add a focused test, and ask the team before inventing a value or changing the
shared contract. Future agents should use this checkpoint to look for likely
failure modes in later dataset updates and integrations.

## Schema

The agreed fields are:

`raw_text, amount, date, txn_type, merchant, category`

`id` and `created_at` are database-managed fields. `date` is stored as
`YYYY-MM-DD`; `txn_type` is either `debit` or `credit`; unknown categories
should be stored as `Others`.

## Example

```python
from db import Database, Transaction

with Database("data/finbuddy.sqlite3") as database:
    database.add_transaction(
        Transaction(
            raw_text="UPI debit of Rs 180 to CAFE COFFEE",
            amount=180.0,
            date="2026-10-08",
            txn_type="debit",
            merchant="CAFE COFFEE",
            category="Food",
        )
    )

    for row in database.spending_by_category():
        print(row["category"], row["total_amount"])
```
