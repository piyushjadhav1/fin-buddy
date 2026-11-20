# FinBuddy UI and database layer

- `index.html` — browser spending dashboard.
- `android/` — Android companion app.
- `finbuddy/db/` — SQLite schema, data access, validation, and migration tools.

The FastAPI backend is in the sibling `beckend 3/` folder at the project root. Start the API before serving the browser UI through a local HTTP server. The UI uses the API when available and falls back to browser-local preview storage when opened directly as a file or when the API is unavailable.

The backend expects an existing compatible SQLite database. Use only a disposable database for development and keep real transaction data out of Git.