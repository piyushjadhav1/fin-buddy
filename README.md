# FinBuddy

FinBuddy combines a browser spending dashboard, a FastAPI backend, the existing SQLite data layer, and an Android companion app.

## Project folders

- `beckend 3/` — FastAPI service and API documentation.
- `finbuddy.ui/` — browser interface, Android app, and SQLite schema/data-layer code.

## Run the API on Windows

From the project root in PowerShell:

```powershell
Set-Location '.\beckend 3'
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

The API listens at `http://127.0.0.1:8000`. Open `/docs` for interactive API documentation and `/api/health` to check the database connection.

The backend requires an existing FinBuddy SQLite database with a compatible schema. It does not create a replacement database or run migrations automatically. Set `FINBUDDY_DB` to the database file you intend to use. Use a disposable database for development; do not use production transaction data.

## Run the browser UI

Serve `finbuddy.ui/index.html` from a local HTTP server such as VS Code Live Server while the API is running. The UI connects to the API at `127.0.0.1:8000` when served from a local web origin. Opening the HTML file directly uses browser-local preview storage instead.

## Android app

Open `finbuddy.ui/android` in Android Studio. The debug build defaults to the Android emulator's host address, `http://10.0.2.2:8000`. Release builds require an explicitly configured HTTPS backend. Do not embed shared API tokens or real production URLs in the app.

The Android companion can read supported payment notifications and upload transactions. It does not provide student accounts or per-student data isolation, so this project is not ready for a production deployment with real student data.

## Data hygiene

SQLite files, database backups, Android build output, Python caches, and local machine configuration are excluded from new Git additions. Keep real transaction data and secrets out of source control.