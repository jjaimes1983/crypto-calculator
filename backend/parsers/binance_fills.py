"""Parser for Binance's fill-level "Trade History" export (Spot > Order
History has a separate "Trade History" tab - Export). Columns:

    Time, Pair, Side, Price, Executed, Amount, Fee

This is a different report than backend/parsers/binance.py handles (that
one is "Order History" - order-level, no fee column, quantities glued to
units like "13.21AVAX"). This one is fill-level, has a real Fee column,
and its Executed/Amount/Fee are plain numbers (Fee has the unit glued on,
e.g. "0.0155AVAX" or "0.78936EUR" - same glued-unit convention Order
History uses elsewhere).

Fee handling (reverse-engineered from a real account's fee pattern - see
the Crypto Calculator project notes for the numbers this was checked
against): on a BUY the fee is charged in the asset you're acquiring and
is deducted from the quantity actually credited to your wallet, so the
quantity/cost stored here is (Executed - Fee) units for (Amount) EUR -
you paid for the gross amount but only received the net. On a SELL the
fee is charged in the quote currency you receive and reduces net
proceeds, not the quantity sold, so the quantity stored is the full
Executed and the EUR amount stored is (Amount - Fee).

Currency handling: a EUR-quoted pair (e.g. AVAXEUR) needs no conversion.
A crypto-quoted pair (e.g. AVAXBTC) needs the quote asset's historical
EUR price. Two ways to supply that, in priority order:
  1. An optional "Rate EUR" column in the file - the quote currency's
     EUR value at that exact trade, if you already know it (e.g. from
     your exchange's own trade confirmation). Used as-is, no lookup.
  2. If that column is absent or blank for a row, falls back to
     fx.rate_to_eur() - the same historical-price lookup binance.py and
     coinbase.py use. A trade is skipped (and counted), never guessed,
     if that lookup fails.
"""
import argparse
import hashlib
import re
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from .base import NormalizedTx
from .. import fx

EXCHANGE = "binance"

COLUMN_MAP = {
    "Time": "time",
    "Pair": "pair",
    "Side": "side",
    "Price": "price",
    "Executed": "executed",
    "Amount": "amount",
    "Fee": "fee",
}
OPTIONAL_COLUMNS = {"Rate EUR": "rate_eur"}

QUOTES = ["EUR", "USDT", "USDC", "BUSD", "USD", "BTC", "ETH", "BNB"]

_NUM = re.compile(r"^-?[\d.,]+")


def _to_float(s) -> float:
    """Handles plain numbers and both '.' and ',' as the decimal separator
    (this data has shown up pasted in both conventions)."""
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace(",", ".")
    return float(s)


def _parse_glued(s) -> Tuple[float, str]:
    """'0.0155AVAX' -> (0.0155, 'AVAX'), '0,78936EUR' -> (0.78936, 'EUR')."""
    s = str(s).strip()
    m = _NUM.match(s)
    if not m:
        raise ValueError(f"Could not parse a leading number out of '{s}'")
    num = float(m.group().replace(",", "."))
    unit = s[m.end():].strip().upper()
    return num, unit


def _split_pair(pair: str):
    pair = pair.upper().strip()
    for q in QUOTES:
        if pair.endswith(q) and len(pair) > len(q):
            return pair[: -len(q)], q
    return pair[:-3], pair[-3:]


def parse_file(path: str) -> List[NormalizedTx]:
    df = pd.read_csv(path) if str(path).lower().endswith(".csv") else pd.read_excel(path)

    missing = [c for c in COLUMN_MAP if c not in df.columns]
    if missing:
        raise ValueError(
            f"Binance Trade History parser: expected columns {missing} not found. "
            f"Columns present in file: {list(df.columns)}. "
            f"Update COLUMN_MAP in backend/parsers/binance_fills.py to match your export."
        )

    rename = dict(COLUMN_MAP)
    for c, key in OPTIONAL_COLUMNS.items():
        if c in df.columns:
            rename[c] = key
    df = df.rename(columns=rename)
    has_rate_col = "rate_eur" in df.columns

    results: List[NormalizedTx] = []
    skipped_conversion_failed = 0
    seen_keys: dict = {}  # de-dup key -> how many times we've seen it so far in THIS file

    for _, r in df.iterrows():
        side = str(r["side"]).strip().lower()
        if side not in ("buy", "sell"):
            continue

        symbol, quote = _split_pair(str(r["pair"]))
        executed = _to_float(r["executed"])
        if executed == 0:
            continue
        amount_native = _to_float(r["amount"])
        fee_amount, fee_ccy = _parse_glued(r["fee"]) if pd.notna(r["fee"]) and str(r["fee"]).strip() else (0.0, "")
        trade_time = pd.to_datetime(r["time"], dayfirst=True).to_pydatetime()

        rate = 1.0
        if quote != "EUR":
            manual_rate = r.get("rate_eur") if has_rate_col else None
            if manual_rate is not None and pd.notna(manual_rate) and str(manual_rate).strip() != "":
                rate = _to_float(manual_rate)
            else:
                looked_up = fx.rate_to_eur(quote, trade_time.date())
                if looked_up is None:
                    skipped_conversion_failed += 1
                    continue
                rate = looked_up

        amount_eur = amount_native * rate

        if side == "buy":
            net_qty = executed - (fee_amount if fee_ccy == symbol else 0.0)
            if net_qty <= 0:
                continue
            total_eur = amount_eur
            price_eur = total_eur / net_qty
            fee_eur = fee_amount * price_eur if fee_ccy == symbol else (fee_amount * rate if fee_ccy == quote and quote != "EUR" else fee_amount if fee_ccy == "EUR" else 0.0)
            quantity = net_qty
        else:
            fee_eur = fee_amount * rate if (fee_ccy == quote and quote != "EUR") else (fee_amount if fee_ccy == "EUR" else 0.0)
            total_eur = amount_eur - fee_eur
            quantity = executed
            price_eur = total_eur / quantity if quantity else 0.0

        # Rows can be genuinely identical (an order that filled as several
        # same-sized pieces at the same timestamp) - a hash of the row's
        # own fields alone would collide for those and silently drop real
        # trades via the DB's de-dup constraint. Break the tie with an
        # occurrence counter, so distinct rows with identical content
        # still get distinct external_ids (and a re-upload of the *same*
        # file still de-dupes correctly, since the counter is deterministic).
        raw_key = f"{r['time']}|{r['pair']}|{side}|{r['price']}|{r['executed']}|{r['amount']}|{r['fee']}"
        occurrence = seen_keys.get(raw_key, 0)
        seen_keys[raw_key] = occurrence + 1
        external_id = "fill:" + hashlib.sha1(f"{raw_key}|{occurrence}".encode()).hexdigest()[:16]

        notes = None
        if quote != "EUR":
            notes = f"{symbol}{quote} swap - {quote}/EUR rate used: {rate:.2f}"

        results.append(NormalizedTx(
            symbol=symbol,
            tx_type=side,
            quantity=quantity,
            price_eur=price_eur,
            fee_eur=fee_eur,
            total_eur=total_eur,
            timestamp=trade_time,
            exchange=EXCHANGE,
            external_id=external_id,
            source_file=Path(path).name,
            notes=notes,
        ))

    if skipped_conversion_failed:
        print(f"[binance_fills parser] skipped {skipped_conversion_failed} trade(s) - couldn't convert "
              f"the quote currency to EUR for that date and no 'Rate EUR' override was given.")

    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path")
    ap.add_argument("--dry-run", action="store_true", help="Parse and print only, don't touch the DB")
    args = ap.parse_args()

    txs = parse_file(args.path)
    print(f"Parsed {len(txs)} transaction(s):")
    for t in txs:
        print(f"  {t.timestamp}  {t.tx_type.upper():4}  {t.quantity:>14.8f} {t.symbol:5} "
              f"@ EUR {t.price_eur:.4f}  total EUR {t.total_eur:.4f}  fee EUR {t.fee_eur:.4f}"
              + (f"  ({t.notes})" if t.notes else ""))

    if not args.dry_run:
        print("Add --dry-run to only preview. Use the /upload API endpoint to actually import.")
