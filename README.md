# Stock Ledger

### Stock performance tracker for taxation — with DKK reporting

A local web app for recording stock purchases and sales, tracking average purchase costs, and reviewing realized profits and losses by ticker and calendar year. Enter the final DKK amount from your Danish broker, or convert foreign-currency transactions using historical rates from Danmarks Nationalbank.

**Python standard library · SQLite persistence · No package installation · Runs on your computer**

> This is a record-keeping and realized-return calculation tool, not a complete Danish tax reporting system. It does not determine the tax treatment of your accounts or investments, or submit anything to Skattestyrelsen.

## Features

- **Current holdings:** remaining shares, average DKK purchase cost, and remaining DKK cost basis.
- **Realized returns:** profit and loss per ticker and calendar year, with a year filter and DKK CSV export.
- **Two entry methods:** broker-reported final DKK amounts or automatic historical currency conversion.
- **Transaction history:** purchases, sales, commissions, broker names, notes, and saved conversion details.
- **Automatic recalculation:** backdated entries, edits, and deletions replay the entire ledger in chronological order.
- **Overselling protection:** changes that would sell more shares than held are rejected without altering the ledger.
- **Persistent storage:** SQLite stores transactions and cached exchange rates across restarts.
- **Audit export:** download original amounts, final DKK totals, and exchange-rate provenance as CSV.

## Mac app

The desktop launcher bundles Python and opens the existing browser interface. On Apple Silicon, double-click **Stock Ledger.app**. A **◈ Ledger** menu appears in the menu bar with **Open Stock Ledger**, **Show Data Folder**, and **Quit Stock Ledger**. Closing the browser does not stop the app; use the menu to quit.

Your database is stored outside the app at:

```text
~/Library/Application Support/Stock Ledger/ledger.sqlite3
```

This location is shared by the Mac app and the Python version. It stays the same across restarts, app moves, and app replacements, for the same macOS user. Replacing the `.app` does not replace your records. Deleting this data folder or moving to a different Mac/user requires restoring or copying a backup.

The launcher opens the existing instance on repeated launches. If port 8765 is busy, it chooses a free local port and opens the correct URL automatically.

### Build the Mac app

Build on an Apple Silicon Mac with Python 3.10+:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-mac.txt
python -m PyInstaller --noconfirm StockLedger.spec
```

The result is `dist/Stock Ledger.app`. The current spec targets `arm64`; an Intel release needs an Intel-compatible Python/dependency environment and an appropriate target architecture. The bundle includes trusted certificate roots for HTTPS exchange-rate requests. Local builds are ad-hoc signed, not Developer ID signed or notarized; distributing a release to other Macs requires the appropriate signing/notarization workflow for a smooth first launch.

### Moving an existing ledger

Python launches automatically copy a legacy `ledger.sqlite3` beside `app.py` into the durable folder **only if the destination does not already exist**. For a first packaged launch, place a legacy `ledger.sqlite3` alongside `Stock Ledger.app` to migrate it. Migration uses SQLite's backup API, validates the copy, and leaves the original untouched. Existing destination databases are never overwritten or merged automatically.

## Quick start (Python)

Requires **Python 3.10 or newer** and a modern browser. There are no third-party Python packages, API keys, or frontend build steps.

```sh
git clone https://github.com/balazsban/stock-performance-tracker-for-taxation.git
cd stock-performance-tracker-for-taxation
python3 app.py
```

Open **[http://127.0.0.1:8765](http://127.0.0.1:8765)** and select **Add transaction**. On Windows, use `py -3 app.py` if `python3` is unavailable. Stop the server with `Ctrl+C`.

The database is created automatically on first launch. No sample transactions are loaded.

## Entering transactions

### Option 1: You know the final DKK amount

Choose **I have the final DKK amount** and enter the date, ticker / ledger ID, number of shares, and final amount:

| Transaction | Amount to enter |
| --- | --- |
| Purchase | Total DKK paid, including commissions and fees |
| Sale | Net DKK received, after commissions and fees |

No price-per-share or commission breakdown is required. The final amount is used directly; fees are **not added again**. If you only know the DKK value, leave the currency as DKK. Broker and note fields are optional.

### Option 2: You have original-currency amounts, such as an IBKR statement

Choose **Convert original currency automatically** and enter the original currency, quantity, price per share, and total fees. Use **Preview DKK conversion** to see the rate, its date, and the converted amount before saving.

The price and fees must be in the **same currency**. If fees are charged in another currency, calculate the final DKK amount separately and use option 1.

### Grouping holdings across brokers

Transactions with the **same ticker / ledger ID** share one DKK cost basis across brokers and currencies. Broker names are descriptive and do not split holdings.

Use the same ID consistently for the same security. Use different IDs for different securities or accounts that require separate accounting, for example `AAPL:ACCOUNT1` and `AAPL:ACCOUNT2`. The app does not automatically identify securities by ISIN or resolve ticker changes.

## How the calculations work

The ledger uses **moving weighted average cost** and Python `Decimal` arithmetic with 40 significant digits.

```text
Automatic purchase cost = (shares × original price + fees) × DKK exchange rate
Automatic sale proceeds = (shares × original price − fees) × DKK exchange rate

Average purchase cost = remaining DKK cost basis / remaining shares
Cost of shares sold   = shares sold × average cost immediately before the sale
Realized profit/loss  = net DKK sale proceeds − cost of shares sold
```

An entered final DKK amount replaces the first or second formula. A purchase updates the average. A sale removes cost at the existing average and leaves the remaining average unchanged. Selling the entire position resets its cost basis to zero.

### Example: exchange rates affect the DKK result

| Transaction | Original value | DKK per USD | DKK value |
| --- | ---: | ---: | ---: |
| Buy 10 shares at USD 100 | USD 1,000 | 7.00 | DKK 7,000 |
| Sell 10 shares at USD 120 | USD 1,200 | 6.00 | DKK 7,200 |

Ignoring fees, the realized profit is **DKK 200**. The app converts each transaction using its own historical rate; it does not convert the USD profit using a single rate at the end.

### Dates, precision, and edits

- Entries are processed by transaction date, then saved trade order for transactions on the same day.
- Use **Order day** in transaction history to arrange all trades for one ticker and date, earliest first. Save applies the entire proposed sequence atomically and recalculates every later trade; negative holdings reject the change without saving any part of it. Existing trades retain their entry order until reordered. New trades append to the day; ordinary edits preserve order. The transaction CSV includes `sort_order`.
- A sale's transaction year determines the calendar year of its realized result.
- Every change recalculates the history. Any resulting oversell causes the change to roll back.
- Inputs support up to 12 decimal places. The interface displays money to 2 decimal places, averages to 4, and share quantities to 6; underlying calculations retain greater precision.
- Short positions are not supported.

## Historical exchange rates

Automatic conversion uses **Danmarks Nationalbank's DNVALD table, exchange-rate type KBH**, through the official StatBank API. Published rates are DKK per **100** units of foreign currency; the app divides by 100 to obtain DKK per unit.

- On non-banking days, the app uses the preceding available banking-day observation and displays that rate's date.
- StatBank normally makes daily rates available the next banking morning. An unpublished banking-day rate is rejected rather than silently replaced with yesterday's rate.
- Future dates, unsupported currencies, and unavailable observations require retrying later or entering the final DKK amount.
- Rates are cached locally and saved with each transaction, including the source and effective date.
- Editing a transaction preserves its saved rate when the date and currency are unchanged.
- Existing foreign-currency entries without DKK values must be completed via **Edit**. Final DKK reports are withheld until all entries are complete.

Manual DKK entry and existing reports work offline. Uncached automatic conversions need internet access. The rate service receives the requested currency and date, not your ticker, broker, quantities, or transaction amounts.

Sources: [Nationalbank historical rates](https://nationalbanken.statbank.dk/DNVALD) · [Publication schedule and banking-day information](https://www.nationalbanken.dk/en/frequently-asked-questions/questions-regarding-exchange-rates)

## Exports and backups

| Output | Contents |
| --- | --- |
| **Export transactions** | Original transaction fields, broker, final DKK amount, saved rate, rate date, and conversion source |
| **Export DKK report** | Realized net proceeds, cost of shares sold, and profit/loss per ticker and year; respects the selected year |
| **SQLite backup** | Complete ledger and cached rates |

On macOS, data is stored in `~/Library/Application Support/Stock Ledger/ledger.sqlite3`. On Windows the default is `%LOCALAPPDATA%\Stock Ledger\ledger.sqlite3`; on Linux it is `$XDG_DATA_HOME/stock-ledger/ledger.sqlite3` (or `~/.local/share/stock-ledger/ledger.sqlite3`). To back up or move the complete ledger, stop the app and copy that file. To restore, stop the app and replace the database with the backup. CSV export is available, but **CSV import is not implemented**.

Database files, CSV exports, and common local artifacts are excluded by `.gitignore`. If using a custom database filename, ensure it is also ignored before committing.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8765` | Local HTTP port |
| `LEDGER_DB` | Per-user application data folder | Absolute database path; the parent directory is created automatically |

macOS / Linux:

```sh
PORT=8766 LEDGER_DB=/path/to/private/ledger.sqlite3 python3 app.py
```

PowerShell:

```powershell
$env:PORT = "8766"
$env:LEDGER_DB = "C:\path\to\private\ledger.sqlite3"
py -3 app.py
```

The server binds to **127.0.0.1** and is intended for personal local use. It has no user accounts or authentication and is not designed for public hosting.

## Development and tests

```sh
python3 -m unittest discover -v
```

The tests use temporary databases. Coverage includes weighted averages, fees, fractional shares, backdated changes, persistence and rollback, mixed-currency DKK accounting, saved-rate reuse, rate scaling, weekend fallback, missing rates, and database migration. Exchange-rate unit tests mock the external service, so the suite runs offline.

```text
app.py          HTTP server, SQLite storage, validation, and accounting
fx.py           Nationalbank rate lookup and cache
static/         HTML, CSS, and browser JavaScript
test_app.py     Core accounting and persistence tests
test_dkk.py     DKK conversion and migration tests
storage.py      Durable data paths and legacy database migration
desktop.py      Mac menu-bar app, instance lock, and browser launcher
test_storage.py Storage migration, restart persistence, and launcher tests
StockLedger.spec  PyInstaller Mac bundle configuration
```

## Scope and limitations

The app calculates transaction-based realized returns using the method described above. It does **not** implement:

- Account-specific or instrument-specific Danish tax rules, including mark-to-market taxation.
- Tax filing, tax rates, loss-offset rules, or automatic instrument classification.
- Dividends, withholding tax, stock splits, mergers, transfers, or other corporate actions.
- Live market prices, unrealized returns, or year-end market valuations.
- Broker synchronization, CSV import, or separate currency treatment for commissions.

Review the calculations against your broker records and the rules applicable to your investments before using them for a tax return.

## License

[MIT](LICENSE). The repository's existing MIT license is preserved; it permits commercial as well as personal use, subject to its terms.

### Full amounts in foreign currencies

Choose **Convert full amount in original currency**, then enter the shares, currency and full amount paid including fees. For sales, enter the net amount received after fees. The saved Nationalbank exchange rate converts that total to DKK; fees are not added again. Each purchase contributes its own historical DKK cost to the weighted average, and sales use their own converted net proceeds. Original totals and rates remain available in the history and CSV export. Existing price-per-share entries remain supported.
