PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL CHECK (
        length(trim(source_name)) BETWEEN 1 AND 256
    ),
    imported_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
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
        category IN (
            'Food',
            'Travel',
            'Shopping',
            'Bills/Recharge',
            'Fees',
            'Entertainment',
            'Others'
        )
    ),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    import_batch_id INTEGER REFERENCES import_batches(id)
);

CREATE INDEX IF NOT EXISTS idx_transactions_date
    ON transactions(date);

CREATE INDEX IF NOT EXISTS idx_transactions_category
    ON transactions(category);

CREATE INDEX IF NOT EXISTS idx_transactions_type
    ON transactions(txn_type);

CREATE INDEX IF NOT EXISTS idx_transactions_import_batch
    ON transactions(import_batch_id);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO schema_migrations(version) VALUES (2);
INSERT OR IGNORE INTO schema_migrations(version) VALUES (3);
