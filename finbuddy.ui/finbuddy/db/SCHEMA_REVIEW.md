# FinBuddy schema review

**Phases:** 2 — Review current schema; 3 — Implement storage rules; 4 — Add import provenance  
**Status:** Phases 2–4 implemented locally; schema version 3.

## Findings

The `transactions` table has the six agreed transaction fields, generated
`id` and `created_at`, plus a nullable import-batch foreign key. CSV imports
record the filename (not the full path) and import time in `import_batches`.
SQLite constraints limit transaction type and category values and reject
negative amounts. Both local databases pass validation and SQLite integrity
checks after migration.

| Area | Current state | Finding |
|---|---|---|
| Money | `amount_paise INTEGER`; generated `amount` rupees value | Integer storage and 2-decimal rupee conversion avoid floating point in stored totals. |
| Required text | `raw_text TEXT NOT NULL` with nonblank and length checks | SQLite and Python enforce nonblank text up to 10,000 characters. |
| Date | `date TEXT NOT NULL` | SQLite and Python enforce exact `YYYY-MM-DD` and valid calendar dates. |
| Merchant | Nullable `TEXT` with length/nonblank checks | SQL `NULL` means unavailable; nonempty values are limited to 256 characters. |
| Amount range | Integer paise, zero through 99,999,999,999 | Zero is allowed; application and database enforce integer value and the ₹999,999,999.99 ceiling. |
| User changes | No update method; permanent delete method added | Matches the decision that users cannot edit and deletion permanently removes the row. |
| Import provenance | Optional `import_batch_id` and `import_batches` table | Bulk CSV imports store filename and time; direct inserts may remain unbatched. Existing rows with unknown source remain `NULL`. |
| Duplicate handling | Query-time candidate detection; no deduplication or blocking | Match date, integer amount, transaction type, and normalized merchant; if merchant is missing, use normalized raw text. Flags are review candidates, and every row is retained. |
| Indexes | Date, category, and type | Appropriate for current filters. Consider a compound date/type index only if real query performance requires it. |

## Existing testing-data measurements

Measured from `data/testing.sqlite3` (13,756 rows):

- SQLite integrity check: `ok`.
- Existing application validator: passed.
- Longest raw message: 518 characters; none exceeds the 10,000-character cap.
- Longest merchant: 100 characters; none exceeds the 256-character cap.
- Largest amount: ₹8,820,236; none exceeds the agreed ceiling.
- No zero amounts are currently present.
- No dates violate the exact 10-character `YYYY-MM-DD` shape.
- 12,509 rows (about 91.0%) are in `Others`.
- 7,548 rows (about 54.9%) have no merchant.
- 1,437 groups share the transaction matching fields; those groups contain
  5,219 rows, or 3,782 repeated rows beyond one row per group. All are retained
  and count separately in totals. Current candidate counts are produced by
  `Database.list_duplicate_candidates()` and are review flags, not proof that
  a transaction was imported twice.

The app database remains empty and has the same schema and indexes.

## Phase 3 implementation record

- Added `db.migrate`, which creates a SQLite backup before migrating an
  existing database and records schema version 2.
- Migrated all 13,756 testing rows and the empty app database.
- Compared each migrated row with its pre-migration backup. All transaction
  fields and amounts converted exactly; there were zero row mismatches.
- Both databases pass the application validator and SQLite integrity check.
- Backups are stored in `data/backups/` and ignored by Git.
- `Database.delete_transaction(id)` permanently deletes one row and reports
  whether a row was found. There is no transaction edit method.

## Improvement plan

1. Investigate `Others` using source messages and controlled, auditable
   corrections. Do not infer categories from merchant names alone when the
   message is ambiguous.

## Phase 4 implementation record

- Added optional import batch metadata: source filename and import timestamp.
- The loader associates every CSV-loaded row with its batch; direct database
  inserts remain unbatched unless an import source is supplied.
- Full local paths are not stored. Existing rows retain `NULL` provenance
  because their original source cannot be reliably reconstructed.
- Schema version 3 migration creates a backup before modifying each existing
  database and does not change transaction contents.

## Phase 4 readiness

The agreed base schema implementation is complete. Query-time duplicate
candidate detection is available through `Database.list_duplicate_candidates()`.
Flags are not persisted, and matching rows are never blocked, merged, or
deleted. All rows remain in totals. CSV import provenance is available through
`Database.list_import_batches()`.
