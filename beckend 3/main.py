"""Extensible student spending API with a stable, designer-reviewable contract."""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from data_layer_path import resolve_data_layer_dir

DATA_LAYER_DIR = resolve_data_layer_dir(__file__)
if str(DATA_LAYER_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_LAYER_DIR))

from db import Database, Transaction as DatabaseTransaction
from db.database import (
    CATEGORIES,
    MAX_AMOUNT_PAISE,
    MAX_MERCHANT_LENGTH,
    MAX_RAW_TEXT_LENGTH,
    TXN_TYPES as TRANSACTION_TYPES,
)

TransactionType = Literal["debit", "credit"]
Category = Literal[
    "Food", "Travel", "Shopping", "Bills/Recharge", "Fees", "Entertainment", "Others"
]
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = DATA_LAYER_DIR / "data" / "app.sqlite3"
DB_PATH = Path(os.environ.get("FINBUDDY_DB", os.environ.get("SPENDING_DB_PATH", DEFAULT_DB_PATH)))
CURRENCY_CODE = "INR"
CURRENCY_MINOR_UNITS = 2
DATE_FORMAT = "YYYY-MM-DD"
EDITABLE_FIELDS: tuple[str, ...] = ()
READ_ONLY_FIELDS = ("raw_text", "amount", "date", "txn_type", "merchant", "category")
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
AMOUNT_QUANTUM = Decimal("0.01")
MAX_AMOUNT_RUPEES = float(Decimal(MAX_AMOUNT_PAISE) / 100)


class TransactionFields(BaseModel):
    """The six agreed transaction fields used to create and return transactions. Existing transactions are read-only."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    raw_text: str = Field(min_length=1, max_length=MAX_RAW_TEXT_LENGTH)
    amount: float = Field(ge=0, le=MAX_AMOUNT_RUPEES, allow_inf_nan=False)
    date: date
    txn_type: TransactionType
    merchant: str | None = Field(default=None, max_length=MAX_MERCHANT_LENGTH)
    category: Category

    @field_validator("amount")
    @classmethod
    def amount_has_configured_precision(cls, value: float) -> float:
        try:
            amount = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("amount must be a valid decimal number") from exc
        if amount.quantize(AMOUNT_QUANTUM) != amount:
            raise ValueError(
                f"amount may have at most {CURRENCY_MINOR_UNITS} decimal places"
            )
        return float(amount)

    @field_validator("merchant")
    @classmethod
    def merchant_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("merchant cannot be blank; use null when unavailable")
        return value.strip()


class TransactionResource(BaseModel):
    """Database identity is transport metadata; transaction fields stay grouped."""

    id: int
    transaction: TransactionFields


class ParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_text: str = Field(min_length=1, max_length=MAX_RAW_TEXT_LENGTH)


app = FastAPI(title="Student Spending API", version="2.0.0")
DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:5500",
    "http://127.0.0.1:5501",
    "http://localhost:5500",
    "http://localhost:5501",
    # Android WebViewAssetLoader serves the UI from this HTTPS origin.
    "https://appassets.androidplatform.net",
)
configured_cors_origins = tuple(
    origin.strip().rstrip("/")
    for origin in os.environ.get("FINBUDDY_CORS_ORIGINS", "").split(",")
    if origin.strip()
)
cors_origins = list(dict.fromkeys((*DEFAULT_CORS_ORIGINS, *configured_cors_origins)))
API_ACCESS_TOKEN = os.environ.get("FINBUDDY_API_TOKEN", "").strip()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


def _has_valid_api_token(authorization: str | None) -> bool:
    """Check the optional deployment bearer token without timing leaks."""
    if not API_ACCESS_TOKEN or not authorization:
        return False
    scheme, separator, supplied_token = authorization.partition(" ")
    return bool(
        separator
        and scheme.casefold() == "bearer"
        and supplied_token
        and secrets.compare_digest(supplied_token, API_ACCESS_TOKEN)
    )


@app.middleware("http")
async def api_access_guard(request: Request, call_next):
    """Require a bearer token on app routes whenever deployment auth is enabled."""
    if request.method == "OPTIONS":
        return await call_next(request)
    if API_ACCESS_TOKEN and not _has_valid_api_token(request.headers.get("authorization")):
        return JSONResponse(
            status_code=401,
            content={
                "error": "Authentication required. Sign in through the configured app gateway.",
                "code": "unauthorized",
                "details": [],
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


class DatabaseAccessError(RuntimeError):
    """A safe, user-facing problem opening the configured FinBuddy database."""


def _open_database() -> Database:
    if not DB_PATH.is_file():
        raise DatabaseAccessError(
            "The configured FinBuddy database file was not found. Set FINBUDDY_DB to an existing database."
        )

    connection = None
    try:
        read_only_uri = DB_PATH.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(read_only_uri, uri=True)
        transaction_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='transactions'"
        ).fetchone()
        if transaction_table is None:
            raise DatabaseAccessError(
                "The selected file is not a FinBuddy database. Check FINBUDDY_DB."
            )

        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_xinfo(transactions)")
        }
        if "amount_paise" not in columns:
            raise DatabaseAccessError(
                "This FinBuddy database needs an approved database-team migration before the backend can use it."
            )
        required_columns = {
            "id", "raw_text", "amount_paise", "amount", "date", "txn_type",
            "merchant", "category", "created_at", "import_batch_id",
        }
        if not required_columns.issubset(columns):
            raise DatabaseAccessError(
                "The selected database has an incomplete FinBuddy schema. Check its schema version."
            )

        migration_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        version = (
            connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0]
            if migration_table
            else 0
        )
        if version < 3:
            raise DatabaseAccessError(
                "This FinBuddy database needs an approved database-team migration before the backend can use it."
            )
    except sqlite3.Error as exc:
        raise DatabaseAccessError(
            "The configured FinBuddy database could not be read. Check its path and access permissions."
        ) from exc
    finally:
        if connection is not None:
            connection.close()

    try:
        return Database(DB_PATH)
    except RuntimeError as exc:
        if "needs migration" in str(exc).lower():
            message = "This FinBuddy database needs an approved database-team migration before the backend can use it."
        else:
            message = "The selected database does not match the FinBuddy schema. Check its schema version."
        raise DatabaseAccessError(message) from exc
    except (sqlite3.Error, OSError) as exc:
        raise DatabaseAccessError(
            "The configured FinBuddy database could not be opened. Check its path and access permissions."
        ) from exc


def _error(code: str, message: str, details: list[dict] | None = None, status: int = 400):
    return JSONResponse(
        status_code=status,
        content={"error": message, "code": code, "details": details or []},
    )


def _validation_error_message(item: dict) -> tuple[str, str]:
    location = [str(part) for part in item.get("loc", ()) if part != "body"]
    field = ".".join(location) or "request"
    name = location[-1] if location else "request"
    error_type = item.get("type", "")
    messages = {
        "amount": {
            "missing": "Enter the transaction amount.",
            "float_parsing": "Enter a valid amount.",
            "greater_than_equal": "Amount cannot be negative.",
            "less_than_equal": "Amount is too large.",
            "value_error": "Amount can have at most two decimal places.",
        },
        "date": {
            "missing": "Enter the transaction date as YYYY-MM-DD.",
            "date_parsing": "Enter the transaction date as YYYY-MM-DD.",
            "date_from_datetime_parsing": "Enter the transaction date as YYYY-MM-DD.",
            "date_type": "Enter the transaction date as YYYY-MM-DD.",
        },
        "txn_type": {
            "missing": "Choose debit or credit.",
            "literal_error": "Choose debit or credit.",
        },
        "type": {
            "literal_error": "Choose debit, credit, or all.",
        },
        "category": {
            "missing": "Choose an expense category.",
            "literal_error": "Choose one of the available expense categories.",
        },
        "merchant": {
            "missing": "Enter a merchant name.",
            "string_too_short": "Enter a merchant name.",
            "string_too_long": "Merchant name is too long.",
            "value_error": "Enter a merchant name.",
        },
        "raw_text": {
            "missing": "Enter the transaction text.",
            "string_too_short": "Enter the transaction text.",
            "string_too_long": "Transaction text is too long.",
        },
        "transaction_id": {
            "int_parsing": "Enter a valid transaction number.",
        },
        "search": {
            "string_too_long": "Search text is too long.",
        },
    }
    message = messages.get(name, {}).get(error_type)
    if message is None:
        message = "Check the transaction details and try again." if name == "request" else f"Check {name} and try again."
    return field, message


@app.exception_handler(RequestValidationError)
async def request_validation_error(_: Request, exc: RequestValidationError):
    details = [
        {"field": field, "message": message}
        for field, message in (_validation_error_message(item) for item in exc.errors())
    ]
    message = details[0]["message"] if details else "Check the transaction details and try again."
    return _error("validation_error", message, details, 422)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    message = exc.detail if isinstance(exc.detail, str) else "Request could not be completed. Please try again."
    return _error("request_error", message, [], exc.status_code)


@app.exception_handler(DatabaseAccessError)
async def database_access_error(_: Request, exc: DatabaseAccessError):
    return _error("database_unavailable", str(exc), [], 503)


@app.exception_handler(sqlite3.Error)
async def sqlite_database_error(_: Request, __: sqlite3.Error):
    return _error(
        "database_unavailable",
        "The FinBuddy database could not complete the request. Check that the existing database is available.",
        [],
        503,
    )


@app.exception_handler(Exception)
async def unexpected_error(_: Request, __: Exception):
    return _error("internal_error", "Something went wrong. Please try again.", [], 500)


def _ui_transaction(resource: TransactionResource) -> dict:
    """Return the flat transaction shape consumed by the existing web UI."""
    transaction = resource.transaction
    return {
        "id": resource.id,
        "merchant": transaction.merchant or "Unknown merchant",
        "amount": transaction.amount,
        "category": transaction.category,
        "date": transaction.date.isoformat(),
        "txn_type": transaction.txn_type,
    }


def _ui_transaction_from_row(row) -> dict:
    return {
        "id": int(row["id"]),
        "merchant": row["merchant"] or "Unknown merchant",
        "amount": float(row["amount"]),
        "category": row["category"],
        "date": row["date"],
        "txn_type": row["txn_type"],
    }


def _newest_first(rows) -> list:
    """Keep list and page results newest-first with a deterministic ID tie-breaker."""
    return sorted(rows, key=lambda row: (row["date"], int(row["id"])), reverse=True)


def _from_row(row) -> TransactionResource:
    transaction = TransactionFields(
        raw_text=row["raw_text"],
        amount=float(row["amount"]),
        date=row["date"],
        txn_type=row["txn_type"],
        merchant=row["merchant"],
        category=row["category"],
    )
    return TransactionResource(id=row["id"], transaction=transaction)


def _save(transaction: TransactionFields) -> TransactionResource:
    database_transaction = DatabaseTransaction(
        raw_text=transaction.raw_text,
        amount=Decimal(str(transaction.amount)),
        date=transaction.date.isoformat(),
        txn_type=transaction.txn_type,
        merchant=transaction.merchant,
        category=transaction.category,
    )
    with _open_database() as database:
        transaction_id = database.add_transaction(database_transaction)
    return TransactionResource(id=transaction_id, transaction=transaction)


def _parse_date(text: str) -> date:
    patterns = (
        r"\b(\d{4}-\d{2}-\d{2})\b",
        r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = match.group(1)
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                pass
    match = re.search(r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b", text)
    if match:
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(match.group(1), fmt).date()
            except ValueError:
                pass
    raise ValueError("Could not find a transaction date. Include a date such as 2026-10-07.")


def _parse_amount(text: str) -> float:
    matches = re.findall(
        r"(?:₹|\bRs\.?\s*|\bINR\s*)\s*([0-9][0-9,]*(?:\.\d{1,4})?)",
        text,
        re.I,
    )
    if not matches:
        matches = re.findall(
            r"\b(?:debited|credited|spent|received|paid)\s+(?:by\s+|of\s+)?([0-9][0-9,]*(?:\.\d{1,4})?)\b",
            text,
            re.I,
        )
    if not matches:
        raise ValueError("Could not find an amount. Include an amount such as Rs 250.00.")
    amount = Decimal(matches[0].replace(",", ""))
    if amount < 0:
        raise ValueError("Transaction amount cannot be negative.")
    if amount.quantize(AMOUNT_QUANTUM) != amount:
        raise ValueError(
            f"The configured currency allows {CURRENCY_MINOR_UNITS} decimal places."
        )
    return float(amount)


def _parse_type(text: str) -> TransactionType:
    lower = text.lower()
    debit = re.search(r"\b(debit(?:ed)?|spent|purchase|paid|sent|withdrawn)\b", lower)
    credit = re.search(r"\b(credit(?:ed)?|received|refund(?:ed)?|deposited)\b", lower)
    if bool(debit) == bool(credit):
        raise ValueError("Could not determine transaction type. Include a clear debit or credit keyword.")
    return "debit" if debit else "credit"


def _parse_merchant(text: str) -> str | None:
    patterns = (
        r"\b(?:to|at|towards|for)\s+([A-Za-z][A-Za-z0-9 .&'_-]{1,49}?)(?=\s+(?:on|dated|ref|upi|vpa|from|using|\btxn\b)|[.,;|]|$)",
        r"\bVPA\s+([A-Za-z][A-Za-z0-9._-]{1,39})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            merchant = re.sub(r"\s+", " ", match.group(1)).strip(" .-_")
            if merchant:
                return merchant[:160]
    return None


KEYWORDS: dict[str, tuple[str, ...]] = {
    "Food": ("food", "restaurant", "cafe", "coffee", "swiggy", "zomato", "canteen", "mess", "pizza", "grocery", "groceries"),
    "Travel": ("travel", "uber", "ola", "rapido", "metro", "bus", "train", "rail", "irctc", "flight", "taxi", "fuel", "petrol"),
    "Shopping": ("shopping", "amazon", "flipkart", "myntra", "store", "retail", "mall"),
    "Bills/Recharge": ("bill", "bills", "recharge", "electricity", "mobile", "broadband", "wifi", "airtel", "jio", "vodafone", "postpaid", "prepaid"),
    "Fees": ("fee", "fees", "tuition", "college", "university", "school", "exam", "hostel"),
    "Entertainment": ("movie", "cinema", "netflix", "spotify", "hotstar", "concert", "game", "gaming", "entertainment"),
}


def _categorize(text: str, merchant: str | None) -> Category:
    haystack = f"{text} {merchant or ''}".lower()
    for category, words in KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(word)}\b", haystack) for word in words):
            return category  # type: ignore[return-value]
    return "Others"


def _parse_sms(raw_text: str) -> TransactionFields:
    merchant = _parse_merchant(raw_text)
    return TransactionFields(
        raw_text=raw_text,
        amount=_parse_amount(raw_text),
        date=_parse_date(raw_text),
        txn_type=_parse_type(raw_text),
        merchant=merchant,
        category=_categorize(raw_text, merchant),
    )


def _date_filters(start_date: date | None, end_date: date | None) -> tuple[list[str], list[str]]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    clauses, params = [], []
    if start_date:
        clauses.append("date >= ?")
        params.append(start_date.isoformat())
    if end_date:
        clauses.append("date <= ?")
        params.append(end_date.isoformat())
    return clauses, params


@app.get("/health")
@app.get("/api/health")
def health() -> dict:
    with _open_database() as database:
        count = len(database.list_transactions())
    return {"ok": True, "storage": "sqlite", "transaction_count": count}


@app.get("/contract")
def get_contract() -> dict:
    """Machine-readable current defaults, to help UI and DB clients stay aligned."""
    return {
        "transaction_fields": {
            "raw_text": {
                "type": "string", "required": True, "nullable": False,
                "min_length": 1, "max_length": MAX_RAW_TEXT_LENGTH,
                "editable": "raw_text" in EDITABLE_FIELDS,
            },
            "amount": {
                "type": "number", "required": True, "minimum": 0,
                "maximum": MAX_AMOUNT_RUPEES, "currency": CURRENCY_CODE,
                "decimal_places": CURRENCY_MINOR_UNITS,
                "editable": "amount" in EDITABLE_FIELDS,
            },
            "date": {
                "type": "date", "required": True, "format": DATE_FORMAT,
                "editable": "date" in EDITABLE_FIELDS,
            },
            "txn_type": {
                "type": "string", "required": True,
                "allowed": list(TRANSACTION_TYPES),
                "editable": "txn_type" in EDITABLE_FIELDS,
            },
            "merchant": {
                "type": "string", "required": False, "nullable": True,
                "max_length": MAX_MERCHANT_LENGTH,
                "editable": "merchant" in EDITABLE_FIELDS,
            },
            "category": {
                "type": "string", "required": True,
                "allowed": list(CATEGORIES),
                "editable": "category" in EDITABLE_FIELDS,
            },
        },
        "read_only_fields": list(READ_ONLY_FIELDS),
        "pagination": {"default_page_size": DEFAULT_PAGE_SIZE, "max_page_size": MAX_PAGE_SIZE, "style": "page_number"},
        "errors": {"format": {"error": "string", "code": "string", "details": []}},
    }


@app.post("/transactions/parse", response_model=TransactionResource, status_code=201)
def parse_and_save(request: ParseRequest) -> TransactionResource:
    try:
        transaction = _parse_sms(request.raw_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _save(transaction)


@app.post("/transactions", response_model=TransactionResource, status_code=201)
def create_transaction(transaction: TransactionFields) -> TransactionResource:
    return _save(transaction)


@app.get("/transactions")
def list_transactions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    category: Category | None = Query(default=None),
    txn_type: TransactionType | None = Query(default=None),
) -> dict:
    _date_filters(start_date, end_date)  # Validate range before reading.
    with _open_database() as database:
        rows = database.list_transactions(category=category, txn_type=txn_type)
    if start_date:
        rows = [row for row in rows if row["date"] >= start_date.isoformat()]
    if end_date:
        rows = [row for row in rows if row["date"] <= end_date.isoformat()]
    rows = _newest_first(rows)
    total = len(rows)
    start = (page - 1) * page_size
    page_rows = rows[start : start + page_size]
    return {
        "items": [_from_row(row) for row in page_rows],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": (total + page_size - 1) // page_size,
        },
    }


@app.get("/api/transactions")
def list_ui_transactions(
    txn_type: Literal["debit", "credit", "all"] = Query(default="debit", alias="type"),
    category: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=256),
) -> list[dict]:
    """List flat records with the UI's category chips and merchant/category search."""
    if category == "All":
        category = None
    elif category is not None and category not in CATEGORIES:
        raise HTTPException(status_code=422, detail="Unknown category")
    with _open_database() as database:
        rows = database.list_transactions(
            category=category,
            txn_type=None if txn_type == "all" else txn_type,
        )
    if search and search.strip():
        query = search.strip().casefold()
        rows = [
            row
            for row in rows
            if query in (row["merchant"] or "Unknown merchant").casefold()
            or query in row["category"].casefold()
        ]
    rows = _newest_first(rows)
    return [_ui_transaction_from_row(row) for row in rows]


@app.post("/api/transactions", status_code=201)
def create_ui_transaction(transaction: TransactionFields) -> dict:
    """Create a transaction and return the flat response expected by the UI."""
    try:
        return _ui_transaction(_save(transaction))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/transactions/{transaction_id}")
def delete_ui_transaction(transaction_id: int) -> dict:
    try:
        with _open_database() as database:
            deleted = database.delete_transaction(transaction_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"ok": True}


@app.get("/summary")
def summary(start_date: date | None = None, end_date: date | None = None) -> dict:
    _date_filters(start_date, end_date)
    totals = {"debit": 0, "credit": 0}
    by_category_minor = {category: 0 for category in CATEGORIES}
    with _open_database() as database:
        rows = database.list_transactions()
    for row in rows:
        if start_date and row["date"] < start_date.isoformat():
            continue
        if end_date and row["date"] > end_date.isoformat():
            continue
        amount_paise = row["amount_paise"]
        totals[row["txn_type"]] += amount_paise
        if row["txn_type"] == "debit":
            by_category_minor[row["category"]] += amount_paise
    debit, credit = totals["debit"], totals["credit"]
    return {
        "currency": CURRENCY_CODE,
        "total_debits": float(Decimal(debit) / 100),
        "total_credits": float(Decimal(credit) / 100),
        "net": float(Decimal(credit - debit) / 100),
        "spending_by_category": {
            category: float(Decimal(value) / 100) for category, value in by_category_minor.items()
        },
    }


@app.get("/saving-tips")
def saving_tips(start_date: date | None = None, end_date: date | None = None) -> dict:
    data = summary(start_date, end_date)
    spending = data["spending_by_category"]
    ranked = sorted(((value, category) for category, value in spending.items() if value > 0), reverse=True)
    tips = []
    if not ranked:
        tips.append("Add a few transactions to get saving tips based on your spending.")
    else:
        top_amount, top_category = ranked[0]
        tips.append(f"Your highest recorded expense is {top_category} at {CURRENCY_CODE} {top_amount:.2f}. Try setting a weekly limit for it.")
        discretionary = spending["Food"] + spending["Shopping"] + spending["Entertainment"]
        if discretionary > 0:
            tips.append(f"Food, shopping, and entertainment add up to {CURRENCY_CODE} {discretionary:.2f}. Review small repeat purchases in these categories.")
        if data["total_credits"] and data["total_debits"] >= data["total_credits"]:
            tips.append("Recorded spending matches or exceeds recorded income. Consider saving a small amount as soon as money arrives.")
        elif data["total_credits"] > data["total_debits"]:
            tips.append("Your recorded credits exceed debits. Consider moving a fixed portion of the difference into savings.")
    return {"tips": tips}

