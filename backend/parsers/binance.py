"""Parser for Binance's Spot "Order History" CSV export.

Where to get this file in Binance: Orders > Spot Order > Order History >
Export. Column layout confirmed against a real export (2026-08-23):

    Time, OrderNo, Pair, Type, Side, Order Price, Order Amount, Time
    (again - the fill/update time; pandas renames the duplicate header to
    "Time.1"), Executed, Average Price, Trading total, Status

Quirks this format has that the earlier (wrong) "Trade History" guess
didn't:
- This is ORDER history, not trade history - it includes orders that
  never filled. Only rows with Status == "FILLED" are real transactions;
  everything else (CANCELED, etc.) is skipped.
- Quantity/total columns have the asset glued directly onto the number
  with no separator (e.g. "13.21AVAX", "99.075EUR") - parsed by taking
  the leading numeric portion.
- The fill price is "Average Price" (a plain number) - not "Order Price",
  which is just the limit price the order was placed at and can differ
  from what it actually filled at.
- There's no fee column. "Trading total" is used as-is as the amount
  moved (in the quote currency, before EUR conversion) - whatever fee
  handling Binance already applied (fees are frequently deducted from
  the received asset rather than added to the quote total, in which case
  there's nothing to add here anyway). fee_eur is recorded as 0 rather
  than guessed.
- "OrderNo" is used directly as the de-dup key.

Currency handling: every trade's quote currency (EUR, a USD-family
stablecoin, or another crypto asset like BTC in a pair such as AVAXBTC)
goes through fx.rate_to_eur(), one shared conversion entry point used by
both parsers - see fx.py and crypto_prices.py for how each case is
resolved. A trade is skipped (and counted), never guessed, if the
relevant historical price lookup fails.
"""
import argparse
import re
from pathlib import Path
from typing import List

import pandas as pd

from .base import NormalizedTx
from .. import fx

EXCHANGE = "binance"

COLUMN_MAP = {
    "OrderNo": "order_no",
    "Pair": "pair",
    "Side": "side",
    "Time.1": "fill_time",
    "Executed²": "executed",
    "Average Price": "avg_price",
    "Trading total³": "total",
    "Status": "status",
}

QUOTES = ["EUR", "USDT", "USDC", "BUSD", "USD", "BTC", "ETH", "BNB"]

_NUM_PREFIX = re.compile(r"^-?[\d.]+")


def _parse_amount(s) -> float:
    """'13.21AVAX' -> 13.21, '99.075EUR' -> 99.075, '0EUR' -> 0.0"""
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    m = _NUM_PREFIX.match(s)
    if not m:
        raise ValueError(f"Could not parse a leading number out of '{s}'")
    return float(m.group())


def _split_pair(pair: str):
    """Split e.g. 'BTCEUR' -> ('BTC', 'EUR'), 'AVAXBTC' -> ('AVAX', 'BTC')."""
    pair = pair.upper().strip()
    for q in QUOTES:
        if pair.endswith(q) and len(pair) > len(q):
            return pair[: -len(q)], q
    return pair[:-3], pair[-3:]  # fallback guess: last 3 chars are the quote


def parse_file(path: str) -> List[NormalizedTx]:
    df = pd.read_csv(path) if str(path).lower().endswith(".csv") else pd.read_excel(path)

    missing = [c for c in COLUMN_MAP if c not in df.columns]
    if missing:
        raise ValueError(
            f"Binance parser: expected columns {missing} not found. "
            f"Columns present in file: {list(df.columns)}. "
            f"Update COLUMN_MAP in backend/parsers/binance.py to match your export."
        )

    df = df.rename(columns=COLUMN_MAP)

    results: List[NormalizedTx] = []
    skipped_not_filled = 0
    skipped_conversion_failed = 0

    for _, r in df.iterrows():
        if str(r["status"]).strip().upper() != "FILLED":
            skipped_not_filled += 1
            continue

        side = str(r["side"]).strip().lower()
        if side not in ("buy", "sell"):
            continue

        symbol, quote = _split_pair(str(r["pair"]))
        executed_qty = _parse_amount(r["executed"])
        if executed_qty == 0:
            continue

        avg_price_raw = float(r["avg_price"])
        total_raw = _parse_amount(r["total"])
        fill_time = pd.to_datetime(r["fill_time"]).to_pydatetime()

        rate = fx.rate_to_eur(quote, fill_time.date())
        if rate is None:
            skipped_conversion_failed += 1
            continue

        price_eur = avg_price_raw * rate
        total_eur = total_raw * rate

        order_no = r.get("order_no")
        external_id = f"{EXCHANGE}:{order_no}" if pd.notna(order_no) else None

        results.append(NormalizedTx(
            symbol=symbol,
            tx_type=side,
            quantity=executed_qty,
            price_eur=price_eur,
            fee_eur=0.0,  # not present in this export - see module docstring
            total_eur=total_eur,
            timestamp=fill_time,
            exchange=EXCHANGE,
            external_id=external_id,
            source_file=Path(path).name,
        ))

    if skipped_not_filled:
        print(f"[binance parser] skipped {skipped_not_filled} order(s) that weren't FILLED "
              f"(canceled, expired, etc.).")
    if skipped_conversion_failed:
        print(f"[binance parser] skipped {skipped_conversion_failed} trade(s) - couldn't convert "
              f"the quote currency to EUR for that date (see backend/fx.py and "
              f"backend/crypto_prices.py docstrings).")

    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path")
    ap.add_argument("--dry-run", action="store_true", help="Parse and print only, don't touch the DB")
    args = ap.parse_args()

    txs = parse_file(args.path)
    print(f"Parsed {len(txs)} transaction(s):")
    for t in txs[:30]:
        print(f"  {t.timestamp}  {t.tx_type.upper():4}  {t.quantity:>14.8f} {t.symbol:5} "
              f"@ EUR {t.price_eur:.4f}  total EUR {t.total_eur:.2f}")
    if len(txs) > 30:
        print(f"  ... and {len(txs) - 30} more")

    if not args.dry_run:
        print("Add --dry-run to only preview. Use the /upload API endpoint to actually import.")
