# Parser-to-database contract

The parser must produce one cleaned record for each accepted SMS transaction.
The final output must contain these columns in this exact order:

```text
raw_text,amount,date,txn_type,merchant,category
```

## Field rules

| Field | Rule |
|---|---|
| `raw_text` | Original SMS text. Required and non-empty. |
| `amount` | Non-negative INR amount in rupees, with at most two decimal places. Zero is allowed. Do not use account balances, credit limits, loan limits, or reference numbers. |
| `date` | Transaction date in exact `YYYY-MM-DD` format. |
| `txn_type` | Lowercase `debit` or `credit`. |
| `merchant` | Extracted merchant or recipient when available. May be empty. |
| `category` | One of the seven FinBuddy categories below. |

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

Use `Others` when the category is unknown or does not fit the available
categories. Do not create new category names without agreement from the team.
Do not invent `Fees` records when the source message does not support them.

## Validation before database import

```bash
python3 -m db.validate data/testing.sqlite3
```

To append a validated CSV to the app database:

```bash
python3 -m db.load_csv path/to/cleaned.csv data/app.sqlite3 --append
```

The database loader rejects unsupported categories, invalid transaction types,
negative amounts, amounts with more than two decimal places, empty or
over-limit text, over-limit merchants, over-limit amounts, and invalid or
non-canonical dates. `raw_text` is limited to 10,000 characters, `merchant` to
256 characters, and `amount` to ₹999,999,999.99. Parser/API amounts are
expressed in rupees. The database stores integer paise in `amount_paise`.
