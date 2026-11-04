"""Local-only HTTP API and static page server for FinBuddy."""

from __future__ import annotations

import json
import os
import re
import threading
import webbrowser
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from db import Database, Transaction
from db.database import CATEGORIES, TXN_TYPES


PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("FINBUDDY_DB", PROJECT_DIR / "finbuddy" / "data" / "app.sqlite3"))
HOST = "127.0.0.1"
PORT = int(os.environ.get("FINBUDDY_PORT", "8000"))
MAX_BODY = 32_768
LIVE_SERVER_PORTS = {5500, 5501}
LIVE_SERVER_HOSTS = ("127.0.0.1", "localhost", "[::1]")
ALLOWED_ORIGINS = {
    f"http://{HOST}:{PORT}",
    f"http://localhost:{PORT}",
    *(
        f"http://{host}:{port}"
        for host in LIVE_SERVER_HOSTS
        for port in LIVE_SERVER_PORTS
    ),
}


def transaction_json(row: dict) -> dict:
    """Return only fields the UI needs; never expose raw bank/UPI message text."""
    return {
        "id": int(row["id"]),
        "merchant": row["merchant"] or "Unknown merchant",
        "amount": float(row["amount"]),
        "category": row["category"],
        "date": row["date"],
        "txn_type": row["txn_type"],
    }


class FinBuddyHandler(BaseHTTPRequestHandler):
    server_version = "FinBuddyLocal/1.0"

    def log_message(self, format: str, *args: object) -> None:
        # Do not log request bodies or financial data.
        print(f"{self.address_string()} - {format % args}")

    def _send_json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self) -> None:
        path = PROJECT_DIR / "index.html"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _check_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None or origin in ALLOWED_ORIGINS:
            return True
        self._send_json(403, {"error": "Request origin is not allowed."})
        return False

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Invalid Content-Length."})
            return None
        if length < 1 or length > MAX_BODY:
            self._send_json(413, {"error": "Request body is empty or too large."})
            return None
        if "application/json" not in self.headers.get("Content-Type", "").lower():
            self._send_json(415, {"error": "Send JSON using Content-Type: application/json."})
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "Invalid JSON."})
            return None
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "Expected a JSON object."})
            return None
        return payload

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send_html()
            return
        if parsed.path.startswith("/api/") and not self._check_origin():
            return
        if parsed.path == "/api/health":
            try:
                with Database(DB_PATH) as database:
                    count = database._connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
                self._send_json(200, {"ok": True, "storage": "sqlite", "transaction_count": count})
            except Exception:
                self._send_json(503, {"ok": False, "error": "The FinBuddy database is unavailable."})
            return
        if parsed.path == "/api/transactions":
            query = parse_qs(parsed.query)
            txn_type = query.get("type", ["debit"])[0]
            category = query.get("category", [None])[0]
            if txn_type not in TXN_TYPES and txn_type != "all":
                self._send_json(400, {"error": "type must be debit, credit, or all."})
                return
            if category is not None:
                category = "Others" if category == "Other" else category
                if category not in CATEGORIES:
                    self._send_json(400, {"error": "Unknown category."})
                    return
            try:
                with Database(DB_PATH) as database:
                    rows = database.list_transactions(
                        category=category,
                        txn_type=None if txn_type == "all" else txn_type,
                    )
                    records = [transaction_json(dict(row)) for row in rows]
                self._send_json(200, records)
            except Exception:
                self._send_json(503, {"error": "Could not read FinBuddy transactions."})
            return
        self._send_json(404, {"error": "Not found."})

    def do_OPTIONS(self) -> None:
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            self._send_json(404, {"error": "Not found."})
            return
        if not self._check_origin():
            return

        self.send_response(204)
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        if not self._check_origin():
            return
        if urlparse(self.path).path != "/api/transactions":
            self._send_json(404, {"error": "Not found."})
            return
        payload = self._read_json()
        if payload is None:
            return

        merchant_value = payload.get("merchant")
        merchant = merchant_value.strip() if isinstance(merchant_value, str) else None
        if merchant == "":
            merchant = None
        raw_text = payload.get("raw_text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            raw_text = f"Manual expense: {merchant or 'Unknown merchant'}"
        category = payload.get("category", "Others")
        category = "Others" if category == "Other" else category
        txn_type = payload.get("txn_type", "debit")
        try:
            transaction = Transaction(
                raw_text=raw_text,
                amount=Decimal(str(payload.get("amount"))),
                date=payload.get("date"),
                txn_type=txn_type,
                merchant=merchant,
                category=category,
            )
            with Database(DB_PATH) as database:
                transaction_id = database.add_transaction(transaction)
            response = {
                "id": transaction_id,
                "merchant": merchant or "Unknown merchant",
                "amount": float(transaction.amount),
                "category": category,
                "date": transaction.date,
                "txn_type": txn_type,
            }
            self._send_json(201, response)
        except (ValueError, TypeError, ArithmeticError) as error:
            self._send_json(400, {"error": str(error)})
        except Exception:
            self._send_json(503, {"error": "Could not save the transaction to SQLite."})

    def do_DELETE(self) -> None:
        if not self._check_origin():
            return
        match = re.fullmatch(r"/api/transactions/(\d+)", urlparse(self.path).path)
        if not match:
            self._send_json(404, {"error": "Not found."})
            return
        try:
            with Database(DB_PATH) as database:
                deleted = database.delete_transaction(int(match.group(1)))
            if deleted:
                self._send_json(200, {"ok": True})
            else:
                self._send_json(404, {"error": "Transaction not found."})
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
        except Exception:
            self._send_json(503, {"error": "Could not delete the transaction."})


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with Database(DB_PATH):
        pass
    server = ThreadingHTTPServer((HOST, PORT), FinBuddyHandler)
    print(f"FinBuddy is running at http://{HOST}:{PORT}")
    print(f"SQLite database: {DB_PATH}")
    if not os.environ.get("FINBUDDY_NO_BROWSER"):
        threading.Timer(0.6, webbrowser.open, args=(f"http://{HOST}:{PORT}/",)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nFinBuddy stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
