"""Parser for Binance's Spot "Trade History" CSV export.

Where to get this file in Binance: Orders > Spot Order > Trade History >
Export Trade History. Expected columns (as of Binance's current export):

    Date(UTC), Pair, Side, Price, Executed, Amount, Fee, Fee Coin

Only EUR-quoted pairs (e.g. "BTCEUR") are imported automatically, because
that's the currency this tool tracks cost basis in (see README). Trades in
other quote currencies (BTCUSDT, ETHBUSD, ...) are reported but *skipped*
rather than guessed-converted - crypto and FX both move fast enough that a
guessed rate would quietly corrupt your average cost. If most of your
trading is in USDT, tell me and I'll add a proper historical-FX conversion
step instead of skipping those rows.

Binance has changed its export format before. If your file's columns don't
match COLUMN_MAP below, this parser will raise a clear error naming the
columns it actually found - update COLUMN_MAP or the row-parsing logic to
match.
"""
import argparse
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd

from .base import NormalizedTx

EXCHANGE = "binance"

# Expected source column -> internal name. Edit here first if Binance's
# export headers differ from this.
COLUMN_MAP = {
    "Date(UTC)": "date",
    "Pair": "pair",
    "Side": "side",
    "Price": "price",
    "Executed": "executed",
    "Amount": "amount",
    "Fee": "fee",
}


def _row_external_id(row: dict) -> str:
    raw = f"{EXCHANGE}|{row['date']}|{row['pair']}|{row['side']}|{row['executed']}|{row['price']}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _split_pair(pair: str):
    """Split e.g. 'BTCEUR' -> ('BTC', 'EUR'). Handles the common quote
    currencies Binance uses; extend QUOTES if you trade others."""
    QUOTES = ["EUR", "USDT", "USDC", "BUSD", "USD", "BTC", "ETH", "BNB"]
    pair = pair.upper().strip()
    for q in QUOTES:
        if pair.endswith(q) and len(pair) > len(q):
            return pair[: -len(q)], q
    # Fall back: assume last 3 chars are the quote currency
    return pair[:-3], pair[-3:]


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
    skipped_non_eur = 0

    for _, r in df.iterrows():
        symbol, quote = _split_pair(str(r["pair"]))
        if quote != "EUR":
            skipped_non_eur += 1
            continue

        side = str(r["side"]).strip().lower()  # "buy" / "sell"
        if side not in ("buy", "sell"):
            continue

        quantity = float(r["executed"])
        price_eur = float(r["price"])
        fee_eur = float(r["fee"]) if not pd.isna(r["fee"]) else 0.0
        amount = float(r["amount"])  # quantity * price, before fee
        total_eur = amount + fee_eur if side == "buy" else amount - fee_eur

        row_dict = {"date": r["date"], "pair": r["pair"], "side": side,
                    "executed": quantity, "price": price_eur}

        results.append(NormalizedTx(
            symbol=symbol,
            tx_type=side,
            quantity=quantity,
            price_eur=price_eur,
            fee_eur=fee_eur,
            total_eur=total_eur,
            timestamp=pd.to_datetime(r["date"]).to_pydatetime(),
            exchange=EXCHANGE,
            external_id=_row_external_id(row_dict),
            source_file=Path(path).name,
        ))

    if skipped_non_eur:
        print(f"[binance parser] skipped {skipped_non_eur} non-EUR-quoted trade(s) - "
              f"see module docstring for why.")

    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path")
    ap.add_argument("--dry-run", action="store_true", help="Parse and print only, don't touch the DB")
    args = ap.parse_args()

    txs = parse_file(args.path)
    print(f"Parsed {len(txs)} EUR-quoted transaction(s):")
    for t in txs[:20]:
        print(f"  {t.timestamp}  {t.tx_type.upper():4}  {t.quantity:>14.8f} {t.symbol:5} "
              f"@ EUR {t.price_eur:.4f}  fee EUR {t.fee_eur:.4f}  total EUR {t.total_eur:.2f}")
    if len(txs) > 20:
        print(f"  ... and {len(txs) - 20} more")

    if not args.dry_run:
        print("Add --dry-run to only preview. Use the /upload API endpoint to actually import.")
