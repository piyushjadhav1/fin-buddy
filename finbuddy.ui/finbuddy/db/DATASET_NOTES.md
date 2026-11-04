# SMS testing dataset notes

The local testing dataset was prepared from the attached
`SMS-Transactions-Extracted.xlsx` workbook.

## Current outputs

- `data/testing/sms_transactions_refined.csv` contains 13,756 cleaned records.
- `data/testing.sqlite3` contains the same 13,756 records.
- `data/app.sqlite3` is intentionally empty.
- `data/testing/sms_amount_review.csv` records all 208 source rows whose stored
  amount was capped at `10000`; the amount stated in the message was used for
  testing instead.

## Decisions

- Source `message` is stored as `raw_text`.
- `Debit` and `Credit` are normalized to lowercase `debit` and `credit`.
- Source categories are mapped to the seven agreed FinBuddy categories.
- Repeated SMS messages are retained. They may represent repeated real
  transactions, and the source does not provide a reliable transaction ID.
- Generic or warning-style merchant labels are stored as blank. The original
  message is always preserved in `raw_text`.
- The single record dated `2001-01-01` was excluded from the testing dataset
  because the source message contains only `01 JAN` and does not provide a
  reliable year. The original workbook remains unchanged.

## Privacy

The workbook contains account fragments, UPI identifiers, phone fragments, and
message text. Do not commit the raw workbook or local testing CSV to a public
GitHub repository without anonymizing it and obtaining the team's approval.

To create a shareable structure-preserving copy, run:

```bash
python3 -m db.anonymize_sms_csv \
  data/testing/sms_transactions_refined.csv \
  data/testing/sms_transactions_anonymized.csv
```

The anonymizer replaces URLs, phone numbers, account/reference numbers, and
UPI IDs. Merchant names are replaced with consistent pseudonyms. Keep the
amounts and dates unchanged only for private team testing. For public release,
also shift dates and perturb or bucket amounts so individual transactions
cannot be inferred. Automated redaction is not a guarantee of anonymity, so
review a sample before sharing outside the team.
