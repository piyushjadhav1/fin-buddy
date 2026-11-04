"""Small, dependency-free data-access layer for FinBuddy's SQLite database."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Optional


CATEGORIES = (
    "Food",
    "Travel",
    "Shopping",
    "Bills/Recharge",
    "Fees",
    "Entertainment",
    "Others",
)
TXN_TYPES = ("debit", "credit")
MAX_AMOUNT_PAISE = 99_999_999_999
MAX_RAW_TEXT_LENGTH = 10_000
MAX_MERCHANT_LENGTH = 256


@dataclass(frozen=True)
class Transaction:
    """A cleaned bank/UPI transaction accepted by the database."""

    raw_text: str
    amount: Decimal | int | float | str
    date: str
    txn_type: str
    merchant: Optional[str] = None
    category: str = "Others"


class Database:
    """Create and query the FinBuddy transaction database."""

    def __init__(self, path: str | Path = "data/finbuddy.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    def _initialize(self) -> None:
        existing = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'transactions'"
        ).fetchone()
        if existing:
            columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(transactions)")
            }
            if "amount_paise" not in columns:
                raise RuntimeError(
                    f"Database at {self.path} needs migration. "
                    "Run: python3 -m db.migrate " + str(self.path)
                )
            migration_table = self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            version = (
                self._connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()[0]
                if migration_table
                else 0
            )
            if version < 3:
                raise RuntimeError(
                    f"Database at {self.path} needs migration. "
                    "Run: python3 -m db.migrate " + str(self.path)
                )
        schema_path = Path(__file__).with_name("schema.sql")
        self._connection.executescript(schema_path.read_text(encoding="utf-8"))
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def add_transaction(
        self, transaction: Transaction, *, import_source: Optional[str] = None
    ) -> int:
        """Insert one transaction, optionally recording its import source."""
        amount_paise = self._validate(transaction)
        batch_id = self._create_import_batch(import_source)
        cursor = self._connection.execute(
            """
            INSERT INTO transactions
                (raw_text, amount_paise, date, txn_type, merchant, category,
                 import_batch_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transaction.raw_text,
                amount_paise,
                transaction.date,
                transaction.txn_type,
                transaction.merchant,
                transaction.category,
                batch_id,
            ),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    def add_transactions(
        self,
        transactions: Iterable[Transaction],
        *,
        import_source: Optional[str] = None,
    ) -> int:
        """Insert multiple transactions and optionally record their source."""
        values = []
        for transaction in transactions:
            amount_paise = self._validate(transaction)
            values.append(
                (
                    transaction.raw_text,
                    amount_paise,
                    transaction.date,
                    transaction.txn_type,
                    transaction.merchant,
                    transaction.category,
                )
            )

        if not values:
            return 0

        batch_id = self._create_import_batch(import_source)

        self._connection.executemany(
            """
            INSERT INTO transactions
                (raw_text, amount_paise, date, txn_type, merchant, category,
                 import_batch_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [value + (batch_id,) for value in values],
        )
        self._connection.commit()
        return len(values)

    def list_import_batches(self) -> list[sqlite3.Row]:
        """Return import batches with their current associated transaction count."""
        return list(
            self._connection.execute(
                """
                SELECT import_batches.id, import_batches.source_name,
                       import_batches.imported_at, COUNT(transactions.id) AS transaction_count
                FROM import_batches
                LEFT JOIN transactions
                    ON transactions.import_batch_id = import_batches.id
                GROUP BY import_batches.id
                ORDER BY import_batches.imported_at DESC, import_batches.id DESC
                """
            ).fetchall()
        )

    def _create_import_batch(self, import_source: Optional[str]) -> Optional[int]:
        if import_source is None:
            return None
        if not isinstance(import_source, str) or not import_source.strip():
            raise ValueError("import_source must be nonblank text")
        source_name = import_source.strip()
        if len(source_name) > 256:
            raise ValueError("import_source cannot exceed 256 characters")
        cursor = self._connection.execute(
            "INSERT INTO import_batches (source_name) VALUES (?)", (source_name,)
        )
        return int(cursor.lastrowid)

    def delete_transaction(self, transaction_id: int) -> bool:
        """Permanently delete a transaction; return whether one row was removed."""
        if not isinstance(transaction_id, int) or transaction_id < 1:
            raise ValueError("transaction_id must be a positive integer")
        cursor = self._connection.execute(
            "DELETE FROM transactions WHERE id = ?", (transaction_id,)
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def list_transactions(
        self,
        *,
        category: Optional[str] = None,
        txn_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[sqlite3.Row]:
        """Return newest transactions, optionally filtered by category/type."""
        clauses = []
        parameters: list[object] = []

        if category is not None:
            if category not in CATEGORIES:
                raise ValueError(f"Unknown category: {category}")
            clauses.append("category = ?")
            parameters.append(category)

        if txn_type is not None:
            if txn_type not in TXN_TYPES:
                raise ValueError(f"Unknown transaction type: {txn_type}")
            clauses.append("txn_type = ?")
            parameters.append(txn_type)

        query = "SELECT * FROM transactions"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY date DESC, id DESC"

        if limit is not None:
            if limit < 1:
                raise ValueError("limit must be at least 1")
            query += " LIMIT ?"
            parameters.append(limit)

        return list(self._connection.execute(query, parameters).fetchall())

    def list_duplicate_candidates(self) -> list[sqlite3.Row]:
        """Return every row in a possible-duplicate group, without changing data.

        Candidate groups match on date, amount, and transaction type, plus a
        trimmed, case-insensitive merchant. When merchant is unavailable,
        normalized raw message text is used instead. These are review flags,
        not proof of duplication; every row remains stored and counted.
        """
        return list(
            self._connection.execute(
                """
                WITH grouped AS (
                    SELECT
                        id,
                        COUNT(*) OVER (
                            PARTITION BY
                                date,
                                amount_paise,
                                txn_type,
                                CASE
                                    WHEN merchant IS NULL THEN ''
                                    ELSE lower(trim(merchant))
                                END,
                                CASE
                                    WHEN merchant IS NULL THEN lower(trim(raw_text))
                                    ELSE ''
                                END
                        ) AS duplicate_group_size
                    FROM transactions
                )
                SELECT transactions.*,
                       grouped.duplicate_group_size,
                       1 AS is_duplicate_candidate
                FROM transactions
                JOIN grouped ON grouped.id = transactions.id
                WHERE grouped.duplicate_group_size > 1
                ORDER BY transactions.date DESC, transactions.id DESC
                """
            ).fetchall()
        )

    def spending_by_category(self) -> list[sqlite3.Row]:
        """Return total debits grouped by category for summaries/charts."""
        return list(
            self._connection.execute(
                """
                SELECT category, ROUND(SUM(amount_paise) / 100.0, 2) AS total_amount,
                       COUNT(*) AS transaction_count
                FROM transactions
                WHERE txn_type = 'debit'
                GROUP BY category
                ORDER BY total_amount DESC
                """
            ).fetchall()
        )

    @staticmethod
    def _validate(transaction: Transaction) -> int:
        if not isinstance(transaction.raw_text, str) or not transaction.raw_text.strip():
            raise ValueError("raw_text cannot be empty")
        if len(transaction.raw_text) > MAX_RAW_TEXT_LENGTH:
            raise ValueError(f"raw_text cannot exceed {MAX_RAW_TEXT_LENGTH} characters")
        try:
            amount = Decimal(str(transaction.amount))
        except (InvalidOperation, ValueError) as error:
            raise ValueError("amount must be a valid INR number") from error
        if not amount.is_finite() or amount < 0:
            raise ValueError("amount must be finite and non-negative")
        paise = amount * 100
        if paise != paise.to_integral_value():
            raise ValueError("amount cannot have more than two decimal places")
        amount_paise = int(paise)
        if amount_paise > MAX_AMOUNT_PAISE:
            raise ValueError("amount exceeds ₹999,999,999.99")
        if transaction.merchant is not None:
            if not isinstance(transaction.merchant, str):
                raise ValueError("merchant must be text or None")
            if not transaction.merchant.strip():
                raise ValueError("merchant must be None when unavailable")
            if len(transaction.merchant) > MAX_MERCHANT_LENGTH:
                raise ValueError(
                    f"merchant cannot exceed {MAX_MERCHANT_LENGTH} characters"
                )
        if transaction.txn_type not in TXN_TYPES:
            raise ValueError(f"txn_type must be one of {TXN_TYPES}")
        if transaction.category not in CATEGORIES:
            raise ValueError(f"category must be one of {CATEGORIES}")
        if not isinstance(transaction.date, str) or len(transaction.date) != 10:
            raise ValueError("date must use exact ISO format YYYY-MM-DD")
        try:
            parsed_date = date.fromisoformat(transaction.date)
        except ValueError as error:
            raise ValueError("date must be a valid date in YYYY-MM-DD format") from error
        if parsed_date.isoformat() != transaction.date:
            raise ValueError("date must use exact ISO format YYYY-MM-DD")
        return amount_paise
