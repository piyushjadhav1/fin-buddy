"""Back up and migrate FinBuddy SQLite databases to the current schema."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


MAX_AMOUNT_PAISE = 99_999_999_999
MAX_RAW_TEXT_LENGTH = 10_000
MAX_MERCHANT_LENGTH = 256
CATEGORIES = {
    "Food",
    "Travel",
    "Shopping",
    "Bills/Recharge",
    "Fees",
    "Entertainment",
    "Others",
}
TXN_TYPES = {"debit", "credit"}


def _backup_database(database_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"{database_path.stem}_before_migration_{timestamp}.sqlite3"
    with sqlite3.connect(database_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
    return backup_path


def _amount_to_paise(value: object, row_id: int) -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"row {row_id}: amount is not numeric") from error
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"row {row_id}: amount must be finite and non-negative")
    paise = amount * 100
    if paise != paise.to_integral_value():
        raise ValueError(f"row {row_id}: amount has more than two decimal places")
    amount_paise = int(paise)
    if amount_paise > MAX_AMOUNT_PAISE:
        raise ValueError(f"row {row_id}: amount exceeds ₹999,999,999.99")
    return amount_paise


def _preflight(
    connection: sqlite3.Connection,
    amount_column: str = "amount",
) -> list[tuple[object, ...]]:
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(transactions)")
    }
    required = {
        "id",
        "raw_text",
        amount_column,
        "date",
        "txn_type",
        "merchant",
        "category",
        "created_at",
    }
    missing = required - columns
    if missing:
        raise ValueError("legacy schema is missing columns: " + ", ".join(sorted(missing)))

    migrated_rows = []
    for row in connection.execute(
        f"""SELECT id, raw_text, {amount_column}, date, txn_type, merchant, category, created_at
           FROM transactions ORDER BY id"""
    ):
        row_id, raw_text, amount_value, date_text, txn_type, merchant, category, created_at = row
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise ValueError(f"row {row_id}: raw_text is missing or blank")
        if len(raw_text) > MAX_RAW_TEXT_LENGTH:
            raise ValueError(f"row {row_id}: raw_text exceeds 10000 characters")
        if amount_column == "amount_paise":
            if not isinstance(amount_value, int):
                raise ValueError(f"row {row_id}: stored amount_paise is not an integer")
            amount_paise = amount_value
            if amount_paise < 0 or amount_paise > MAX_AMOUNT_PAISE:
                raise ValueError(f"row {row_id}: amount_paise is outside the allowed range")
        else:
            amount_paise = _amount_to_paise(amount_value, row_id)
        try:
            parsed_date = date.fromisoformat(date_text)
        except (TypeError, ValueError) as error:
            raise ValueError(f"row {row_id}: date is invalid") from error
        if len(date_text) != 10 or parsed_date.isoformat() != date_text:
            raise ValueError(f"row {row_id}: date is not exact YYYY-MM-DD")
        if txn_type not in TXN_TYPES:
            raise ValueError(f"row {row_id}: invalid txn_type {txn_type!r}")
        if category not in CATEGORIES:
            raise ValueError(f"row {row_id}: invalid category {category!r}")
        if merchant is not None:
            if not str(merchant).strip():
                merchant = None
            elif len(str(merchant)) > MAX_MERCHANT_LENGTH:
                raise ValueError(f"row {row_id}: merchant exceeds 256 characters")
        migrated_rows.append(
            (row_id, raw_text, amount_paise, date_text, txn_type, merchant, category, created_at)
        )
    return migrated_rows


def migrate_database(database_path: Path, backup_dir: Path | None = None) -> Path | None:
    if not database_path.exists():
        raise FileNotFoundError(f"database does not exist: {database_path}")

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "transactions" not in tables:
            schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            connection.executescript(schema)
            connection.commit()
            return None

        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(transactions)")
        }
        current_version = 0
        if "schema_migrations" in tables:
            current_version = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
        if current_version > 3:
            raise ValueError(
                f"database schema version {current_version} is newer than this migration tool"
            )
        if "amount_paise" in columns and current_version >= 3:
            schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            connection.executescript(schema)
            connection.commit()
            return None

        if "amount_paise" in columns and current_version >= 2:
            backup_path = _backup_database(
                database_path,
                backup_dir or database_path.parent / "backups",
            )
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS import_batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL CHECK (
                        length(trim(source_name)) BETWEEN 1 AND 256
                    ),
                    imported_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            if "import_batch_id" not in columns:
                connection.execute(
                    """ALTER TABLE transactions ADD COLUMN import_batch_id INTEGER
                       REFERENCES import_batches(id)"""
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_transactions_import_batch "
                "ON transactions(import_batch_id)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (3)"
            )
            connection.commit()
            return backup_path

        amount_column = "amount_paise" if "amount_paise" in columns else "amount"
        migrated_rows = _preflight(connection, amount_column)
        backup_path = _backup_database(
            database_path,
            backup_dir or database_path.parent / "backups",
        )

        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS import_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL CHECK (
                    length(trim(source_name)) BETWEEN 1 AND 256
                ),
                imported_at TEXT NOT NULL DEFAULT (datetime('now'))
            )"""
        )
        connection.execute(
            """CREATE TABLE transactions_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT NOT NULL CHECK (length(trim(raw_text)) BETWEEN 1 AND 10000),
                amount_paise INTEGER NOT NULL CHECK (
                    typeof(amount_paise) = 'integer' AND amount_paise BETWEEN 0 AND 99999999999
                ),
                amount REAL GENERATED ALWAYS AS (CAST(amount_paise AS REAL) / 100.0) VIRTUAL,
                date TEXT NOT NULL CHECK (
                    length(date) = 10
                    AND date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
                    AND date(date, '+0 days') = date
                ),
                txn_type TEXT NOT NULL CHECK (txn_type IN ('debit', 'credit')),
                merchant TEXT CHECK (
                    merchant IS NULL OR length(merchant) <= 256 AND length(trim(merchant)) > 0
                ),
                category TEXT NOT NULL DEFAULT 'Others' CHECK (
                    category IN ('Food','Travel','Shopping','Bills/Recharge','Fees','Entertainment','Others')
                ),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                import_batch_id INTEGER REFERENCES import_batches(id)
            )"""
        )
        connection.executemany(
            """INSERT INTO transactions_new
               (id, raw_text, amount_paise, date, txn_type, merchant, category, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            migrated_rows,
        )
        connection.execute("DROP TABLE transactions")
        connection.execute("ALTER TABLE transactions_new RENAME TO transactions")
        connection.execute("CREATE INDEX idx_transactions_date ON transactions(date)")
        connection.execute("CREATE INDEX idx_transactions_category ON transactions(category)")
        connection.execute("CREATE INDEX idx_transactions_type ON transactions(txn_type)")
        connection.execute(
            "CREATE INDEX idx_transactions_import_batch ON transactions(import_batch_id)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')) )"
        )
        connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (1)")
        connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (2)")
        connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (3)")
        connection.commit()
        return backup_path
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "databases",
        nargs="*",
        type=Path,
        default=[Path("data/testing.sqlite3"), Path("data/app.sqlite3")],
        help="database paths to migrate (defaults to testing and app databases)",
    )
    parser.add_argument("--backup-dir", type=Path, default=Path("data/backups"))
    args = parser.parse_args()
    for database_path in args.databases:
        backup = migrate_database(database_path, args.backup_dir)
        if backup:
            print(f"Migrated {database_path}; backup saved at {backup}")
        else:
            print(f"{database_path} is already current or was initialized")


if __name__ == "__main__":
    main()
