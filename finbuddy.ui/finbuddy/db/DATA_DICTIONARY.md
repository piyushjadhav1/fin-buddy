# FinBuddy transaction data dictionary

**Status:** Phase 1 decisions and Phases 3–4 database implementation are
recorded here, including current schema behavior.

## Transaction fields

| Field | Proposed type and format | Required | Empty/null rule | Maximum | Current database behavior |
|---|---|---:|---|---:|---|
| `raw_text` | UTF-8 text containing the original SMS/UPI message | Yes | Must not be blank. Preserve the original message. | 10,000 characters | SQLite and Python reject blank or over-limit text. |
| `amount` | INR amount in rupees at the parser/API boundary; stored as integer paise in `amount_paise` | Yes | Never null. Zero is allowed. Store the magnitude; use `txn_type` for direction. | ₹999,999,999.99 | `amount_paise` is an integer column; `amount` is a generated rupee-value column. Application and schema enforce precision and range. |
| `date` | Transaction date in exact `YYYY-MM-DD` form | Yes | Never null or blank. Do not substitute SMS receipt date for transaction date. | Exactly 10 characters | SQLite checks canonical shape and date validity; Python enforces exact shape and a valid calendar date. |
| `txn_type` | Lowercase enum: `debit` or `credit` | Yes | Never null or blank. | 6 characters | Enforced by SQLite and Python. |
| `merchant` | UTF-8 text for the merchant or recipient | No | Use SQL `NULL` when unknown. Importers may convert an empty CSV cell to `NULL`. | 256 characters | Nullable SQLite `TEXT`; blank and over-limit values are rejected. |
| `category` | Approved category enum | Yes | Use `Others` when the category is unknown. | 20 characters | SQLite permits the seven categories and defaults an omitted value to `Others`; Python checks the enum. |

Allowed categories:

```text
Food
Travel
Shopping
Bills/Recharge
Fees
Entertainment
Others
```

## Database-managed fields

| Field | Proposed meaning | Current behavior |
|---|---|---|
| `id` | Database-generated transaction identifier | SQLite integer primary key. |
| `created_at` | UTC timestamp when the row is inserted | SQLite `datetime('now')`; stored as text. |
| `import_batch_id` | Optional link to the bulk import that created the row | Nullable foreign key; unknown historical sources and ordinary inserts remain `NULL`. |

`import_batches` stores a generated batch ID, the source filename only, and
the UTC import timestamp. It deliberately does not store full local paths.

`created_at` records insertion time, not the SMS time or transaction date.

## Agreed handling rules

- Currency is INR. Parser/API input and exports express `amount` in rupees.
  Database storage uses integer paise to avoid floating-point rounding in
  monetary totals.
- Amounts are non-negative magnitudes, not signed cash flows. Zero is allowed.
  A debit of ₹25 and a credit of ₹25 are both stored as 2500 paise,
  distinguished by `txn_type`.
- Refunds should be represented as a positive `credit` unless the team defines
  a separate refund model.
- Keep the original SMS in `raw_text`. Corrections to extracted fields must
  leave that source text unchanged.
- Database rows use `NULL` for an unavailable merchant. CSV exports may encode
  it as an empty cell.
- Categories and transaction types are case-sensitive canonical values.
- Dates must use exact `YYYY-MM-DD` form and represent the transaction's local
  calendar date. The parser should account for the source timezone when
  resolving timestamps across midnight.
- Users cannot edit a stored transaction. Deleting a transaction permanently
  removes its row.
- Detect and flag possible duplicate transactions, but keep each as a separate
  row. Never block, merge, or automatically delete a flagged transaction.
- `raw_text` is capped at 10,000 characters, `merchant` at 256 characters, and
  `amount` at ₹999,999,999.99. Reject over-limit values for review; never
  silently truncate them.

## Current gap summary

The schema enforces transaction type, category, money precision and range,
field lengths, and strict dates. The application layer applies the same rules.
The data-access layer supports permanent deletion and has no edit operation.
Duplicate candidates are detected on demand using date, integer amount,
transaction type, and trimmed case-insensitive merchant. When merchant is
missing, normalized raw message text is used instead. This is a review flag,
not proof; rows are never blocked or merged. Bulk CSV provenance records only
the source filename and import time; historical transactions remain unassigned
because their source is unknown.
