"""Tests for the FinBuddy SQLite data-access layer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sqlite3

from db import Database, Transaction
from db.load_csv import load_csv
from db.migrate import migrate_database


class DuplicateCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.sqlite3")

    def tearDown(self) -> None:
        self.database.close()
        self.temp_dir.cleanup()

    @staticmethod
    def transaction(
        *,
        raw_text: str = "UPI debit",
        amount: int = 75,
        merchant: str | None = "Campus Cafe",
    ) -> Transaction:
        return Transaction(
            raw_text=raw_text,
            amount=amount,
            date="2026-10-14",
            txn_type="debit",
            merchant=merchant,
            category="Food",
        )

    def test_flags_all_matching_rows_without_dropping_or_merging(self) -> None:
        first_id = self.database.add_transaction(self.transaction())
        second_id = self.database.add_transaction(
            self.transaction(raw_text="UPI debit ref 123", merchant=" campus cafe ")
        )

        candidates = self.database.list_duplicate_candidates()

        self.assertEqual({row["id"] for row in candidates}, {first_id, second_id})
        self.assertTrue(all(row["is_duplicate_candidate"] for row in candidates))
        self.assertTrue(all(row["duplicate_group_size"] == 2 for row in candidates))
        totals = self.database.spending_by_category()
        self.assertEqual(totals[0]["transaction_count"], 2)
        self.assertEqual(totals[0]["total_amount"], 150)

    def test_missing_merchant_uses_normalized_raw_text(self) -> None:
        self.database.add_transaction(
            self.transaction(raw_text="UPI debit reference 1", merchant=None)
        )
        self.database.add_transaction(
            self.transaction(raw_text=" upi debit reference 1 ", merchant=None)
        )
        self.database.add_transaction(
            self.transaction(raw_text="UPI debit reference 2", merchant=None)
        )

        candidates = self.database.list_duplicate_candidates()

        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(row["duplicate_group_size"] == 2 for row in candidates))

    def test_candidate_flag_is_recomputed_after_permanent_deletion(self) -> None:
        first_id = self.database.add_transaction(self.transaction())
        self.database.add_transaction(self.transaction(raw_text="UPI debit ref 2"))
        self.assertEqual(len(self.database.list_duplicate_candidates()), 2)

        self.assertTrue(self.database.delete_transaction(first_id))
        self.assertEqual(self.database.list_duplicate_candidates(), [])

    def test_bulk_import_source_is_recorded_without_storing_full_path(self) -> None:
        inserted = self.database.add_transactions(
            [self.transaction(), self.transaction(raw_text="UPI debit ref 2")],
            import_source="student_dataset.csv",
        )

        batches = self.database.list_import_batches()

        self.assertEqual(inserted, 2)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["source_name"], "student_dataset.csv")
        self.assertEqual(batches[0]["transaction_count"], 2)

    def test_csv_loader_records_the_input_filename_as_provenance(self) -> None:
        input_path = Path(self.temp_dir.name) / "cleaned_sample.csv"
        output_path = Path(self.temp_dir.name) / "loaded.sqlite3"
        input_path.write_text(
            "raw_text,amount,date,txn_type,merchant,category\n"
            'UPI debit,75.00,2026-10-14,debit,Campus Cafe,Food\n',
            encoding="utf-8",
        )

        self.assertEqual(load_csv(input_path, output_path), 1)
        with Database(output_path) as loaded_database:
            batches = loaded_database.list_import_batches()
            self.assertEqual(batches[0]["source_name"], "cleaned_sample.csv")
            self.assertEqual(batches[0]["transaction_count"], 1)

    def test_version_two_database_migrates_without_inventing_provenance(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as connection:
            connection.executescript(
                """
                CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY,
                    raw_text TEXT NOT NULL,
                    amount_paise INTEGER NOT NULL,
                    amount REAL GENERATED ALWAYS AS (amount_paise / 100.0) VIRTUAL,
                    date TEXT NOT NULL,
                    txn_type TEXT NOT NULL,
                    merchant TEXT,
                    category TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                INSERT INTO schema_migrations(version) VALUES (2);
                INSERT INTO transactions
                    (id, raw_text, amount_paise, date, txn_type, merchant, category, created_at)
                VALUES (41, 'UPI debit', 7500, '2026-10-14', 'debit',
                        'Campus Cafe', 'Food', '2026-10-14 10:00:00');
                """
            )

        backup_path = migrate_database(
            legacy_path, Path(self.temp_dir.name) / "backups"
        )

        self.assertIsNotNone(backup_path)
        self.assertTrue(backup_path.exists())
        with Database(legacy_path) as migrated:
            row = migrated.list_transactions()[0]
            self.assertEqual(row["id"], 41)
            self.assertIsNone(row["import_batch_id"])
            self.assertEqual(migrated.list_import_batches(), [])


if __name__ == "__main__":
    unittest.main()
