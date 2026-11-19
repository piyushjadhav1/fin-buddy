# Student Spending Backend

A FastAPI backend for parsing bank/UPI SMS, categorizing transactions, saving transaction history, and returning summaries and basic saving tips. It delegates transaction storage and validation to the existing FinBuddy database layer in `finbuddy.ui/finbuddy/db`.

## Transaction model

Each transaction contains these six agreed fields:

| Field | Current default |
| --- | --- |
| `raw_text` | Original SMS; read-only after creation |
| `amount` | Non-negative JSON number, in the configured currency's major units |
| `date` | ISO calendar date, `YYYY-MM-DD` |
| `txn_type` | `debit` or `credit` |
| `merchant` | Nullable string; use `null` when unavailable |
| `category` | `Food`, `Travel`, `Shopping`, `Bills/Recharge`, `Fees`, `Entertainment`, or `Others` |

The API wraps the six-field transaction in a resource object with a database-generated `id`. The agreed transaction model itself remains these six fields.

## Backend contract aligned to the existing database

The backend reads the existing database contract without changing its schema. The web UI may apply stricter input rules where its current form requires them:

- Currency: `INR`; amount precision: 2 decimal places. Amounts are stored internally as integer minor units to avoid floating-point accumulation in the database. There is no currency field in the agreed six-field transaction model.
- Date: `YYYY-MM-DD`; invalid dates are rejected. The SMS parser requires a date in the text and never substitutes today's date. Merchant extraction may return `null` when the SMS does not identify a merchant. The parse endpoint and stored `raw_text` both accept up to 10,000 characters.
- Validation: amount must be non-negative, finite, at most `999999999.99`, and within two decimal places; merchant may be `null` but cannot be blank; raw text cannot be blank; transaction type and category must exactly match the database lists; unknown input fields are rejected. The existing database layer applies its own matching validation before inserts. The web UI may continue requiring positive amounts and a merchant.
- Errors: all API errors use `{"error":"Readable message","code":"...","details":[{"field":"...","message":"Readable field guidance"}]}`. The web UI displays `error`; validation failures return HTTP 422.
- Editability: all stored transaction fields are read-only. The existing database contract supports permanent deletion but no update operation.
- Listing: page-number pagination, default 25 entries and maximum 100; filters are inclusive `start_date`/`end_date`, `category`, and `txn_type`.

The `GET /contract` endpoint reports required fields, nullability, limits, formats, categories, and editability. Database field rules remain defined by the existing database layer and its schema; change those only through the database team's process.

## Run locally

Requires Python 3.10 or newer.

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Run these commands from this directory. API documentation is available at `http://127.0.0.1:8000/docs`. Supported project layouts put `beckend 3/` beside `finbuddy.ui/`, or put `finbuddy.ui/` inside a sibling `fin-buddy-main/` directory. The data-layer package is `finbuddy.ui/finbuddy/`; the backend detects either layout and uses that package's `data/app.sqlite3` by default. Set `FINBUDDY_DATA_LAYER_DIR` to the existing directory that contains `db/` when the package is elsewhere. Set `FINBUDDY_DB` to another existing database file; it takes precedence over the legacy `SPENDING_DB_PATH` setting. The backend checks for the FinBuddy transaction table and supported schema version before opening the selected database through the existing database layer. A missing or incompatible database is reported to the UI with an actionable message; the backend does not create a replacement database or run migrations. If the data-layer directory cannot be found, set `FINBUDDY_DATA_LAYER_DIR` to its existing location. Any required migration must be handled through the database team.

## Web UI endpoints

- `GET /api/health` — database availability and transaction count
- `GET /api/transactions?type=debit&category=Food&search=swiggy` — flat transaction array; `type` accepts `debit`, `credit`, or `all` and defaults to `debit`; `category` accepts `All` or one of the seven categories; `search` matches merchant or category, case-insensitively
- `POST /api/transactions` — validate and save a transaction, returning the flat UI record
- `DELETE /api/transactions/{id}` — permanently delete a transaction through the existing database layer

The existing web UI expects transaction objects with `id`, `merchant`, `amount`, `category`, `date`, and `txn_type`; the API does not return `raw_text` in list/create responses. Errors use a readable string in the `error` property because that is what the UI reads. Missing files, invalid database files, and schema migrations return clear database-specific messages.

## Deployment settings and access protection

- `FINBUDDY_API_TOKEN` enables bearer-token protection for backend routes. When set, every non-preflight request must include `Authorization: Bearer <token>`. When unset, this protection is off for local development. Set the token through the hosting provider's secret settings; never commit it or place it in browser UI code. The current UI does not send an authorization token, so a deployment must use a trusted server-side gateway that adds the token, or the UI must later be updated to use a proper sign-in flow.
- A single shared token blocks callers who do not have the token, but it does not create student accounts or separate one student's transactions from another's. Do not treat it as multi-user data isolation.
- `FINBUDDY_CORS_ORIGINS` adds exact web UI origins allowed to call the API, as a comma-separated list, for example `https://finbuddy.example.com`. The backend already includes local development origins and the Android WebView origin by default. CORS controls which browser pages may call the API; it is not a substitute for authentication.
- The UI must also be configured to send requests to the deployed backend address, or both UI and API must be served through a same-origin gateway. CORS does not set the UI's API address.
When access-token protection is enabled, a rejected request returns HTTP `401` in the same readable error format as other API failures. CORS preflight (`OPTIONS`) requests do not require a token so browsers can complete their normal permission check.


Transaction list routes return newest dates first. Rows on the same date are ordered by descending database ID, so repeated requests and paginated results have a deterministic order.

Additional backend endpoints are available at `/health`, `/contract`, `/transactions/parse`, `/transactions`, `/summary`, and `/saving-tips`. These are not called by the current web UI.

Example parse request:

```json
{"raw_text":"UPI debit of Rs 250.00 to Swiggy on 2026-10-07"}
```

Example web UI response shape:

```json
{
  "id": 1,
  "merchant": "Swiggy",
  "amount": 250.0,
  "date": "2026-10-07",
  "txn_type": "debit",
  "category": "Food"
}
```

Example list requests: `GET /api/transactions?type=debit&category=All` or `GET /api/transactions?type=debit&category=Food&search=swiggy`.

The SMS parser uses starter keyword rules and should be calibrated on representative bank SMS before wider use. The companion Android app can now capture supported outgoing payment notifications and submit them as individual `POST /api/transactions` requests. This is notification-text parsing, not a bank feed. The Android client has no trusted login flow; uploads receive `401` when `FINBUDDY_API_TOKEN` is enabled, so do not embed the shared token in the APK. Batch upload and durable idempotency are not implemented, and a lost successful response can lead to a duplicate retry.
