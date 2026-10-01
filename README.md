# Crypto Calculator

Personal web tool to import your Binance/Coinbase purchase history, track
your weighted-average cost basis per asset (in EUR), and figure out how
much you'd need to buy at a given price to move your average to a target
value.

## Quick start (easiest way to run it)

Double-click `run.command` in this folder. First time, it'll take a minute
to set itself up (installing dependencies); after that it opens your
browser straight to the app. To stop it, close the Terminal window it
opened (or press Ctrl+C in it). If double-clicking warns that it's from
an "unidentified developer", right-click the file instead and choose
"Open" — that only needs to happen once.

If you'd rather use the terminal directly, see "Setup" and "Run" below.

## Status / what to verify before trusting the numbers

This was built without access to a real export file from your accounts, so
the Binance and Coinbase parsers are written against the *documented*
column layout for each exchange's standard export, not a verified sample.
**Before relying on this for real decisions:**

1. Export one transaction history file from each exchange you use.
2. Dry-run the parser directly (no server needed) to see what it extracts:
   ```
   source venv/bin/activate
   python -m backend.parsers.binance /path/to/your/binance-export.csv --dry-run
   python -m backend.parsers.coinbase /path/to/your/coinbase-export.csv --dry-run
   ```
3. Compare the printed rows against the source file. If columns don't
   match, each parser module's docstring explains where to fix the column
   mapping (`COLUMN_MAP` near the top of `backend/parsers/binance.py` /
   `coinbase.py`).

Also note: **only EUR-quoted trades are imported automatically.** If you
traded pairs like BTC/USDT rather than BTC/EUR, those rows are reported as
skipped rather than silently converted at a guessed exchange rate. Tell me
if that's most of your history and I'll add a proper historical-FX
conversion step.

The average-cost calculation removes sold quantity at the pool's average
cost (standard "average cost basis" method) — this is not the same as
FIFO, which is what Spain's Hacienda uses for crypto capital gains tax. If
you ever need FIFO-based realized gains for a tax filing, that's a
different calculation from what's here.

## Setup

```bash
cd crypto-calculator
python3 -m venv venv          # already done if you received this pre-built
source venv/bin/activate
pip install -r requirements.txt
python -m backend.init_db      # creates data/crypto.db with empty tables
```

## Run

```bash
source venv/bin/activate
uvicorn backend.main:app --reload --port 8000
```

Open http://localhost:8000 in your browser.

## Using it

1. **Import transactions**: pick the exchange, choose your exported CSV,
   click "Upload & import". Re-uploading the same file is safe — duplicate
   rows are detected and skipped, so you can re-export "everything" each
   time rather than tracking what's new.
2. **Holdings**: each card shows quantity held, average cost, current
   market price (fetched live from CoinGecko, best-effort — shows
   "unknown" if the symbol isn't recognized or the API is unreachable),
   total invested, and unrealized P/L.
3. **Target-average calculator**: expand "Target-average calculator" on
   any holding, enter a target average and a hypothetical buy price — it
   tells you the quantity and EUR amount needed, live as you type. If the
   combination is mathematically unreachable (e.g. target average isn't
   between the buy price and your current average) it tells you why.

## Project layout

```
backend/
  main.py          FastAPI app + routes
  models.py        SQLAlchemy models (Asset, Transaction)
  database.py      SQLite engine/session setup
  calculations.py  average-cost + target-average math
  prices.py        CoinGecko current-price lookup
  parsers/
    binance.py     Binance Spot Trade History CSV parser
    coinbase.py    Coinbase Transaction History CSV parser
frontend/
  index.html, static/app.js, static/style.css   plain HTML/JS dashboard
data/
  crypto.db        SQLite database file (created on first run, gitignored)
```

## Adding another exchange later

Add a new module under `backend/parsers/` that exposes a `parse_file(path)
-> List[NormalizedTx]` function (see `backend/parsers/base.py` for the
shape), then register it in the `PARSERS` dict in `backend/main.py`.
