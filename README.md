# fin-buddy

FinBuddy is a responsive expense-tracking prototype with a dashboard for reviewing spending and transaction history.

## Features

- Add and view expenses
- Review spending by category
- See monthly totals and a spending chart
- Save transactions in a local SQLite database
- Use the interface on desktop and mobile screens

## Tech stack

- HTML, CSS and JavaScript
- Python
- SQLite

## Run locally

You need Python 3.9 or later.

### macOS

Double-click `Start FinBuddy.command` in the project folder and keep its Terminal window open.

### VS Code Live Server

1. Start the backend using `Start FinBuddy.command`.
2. Open `index.html` in VS Code and click **Go Live**.
3. The page should open at `http://127.0.0.1:5500/` or `http://127.0.0.1:5501/` and show **SQLite connected**.

You can also open `http://127.0.0.1:8000/` to use the page served directly by the backend.

## Data storage

Transactions are stored locally in `finbuddy/data/app.sqlite3`. The backend only listens on your own computer; this project does not currently provide cloud storage or multi-device sync.

## Current limitations

The web version requires expenses to be entered manually. Automatic transaction capture from UPI apps such as Google Pay, PhonePe, Paytm or BHIM is not currently available.
