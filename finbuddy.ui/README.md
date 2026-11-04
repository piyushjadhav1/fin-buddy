# FinBuddy local setup

## Use SQLite with VS Code Live Server

FinBuddy uses two local servers for this workflow: the Python server connects to SQLite on port `8000`, and VS Code Live Server serves `index.html` on port `5500` (or `5501`). Keep both running while using the app.

1. Start the backend by double-clicking `Start FinBuddy.command` in the project folder. Leave its Terminal window open.
2. In VS Code, open `index.html` and choose **Open with Live Server** (or click **Go Live**).
3. Use the page whose address begins with `http://127.0.0.1:5500/` or `http://127.0.0.1:5501/`. The dashboard should say **SQLite connected**.

Opening `index.html` directly as a `file:///...` page uses browser storage instead. The SQLite database file is `finbuddy/data/app.sqlite3`.
