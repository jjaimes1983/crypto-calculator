"""Parser for Coinbase's "Transaction History" CSV export.

Where to get this file: Coinbase > Taxes & Reports > Transaction history >
Generate/Download CSV. Column layout confirmed against a real export
(2026-08-23):

    ID, Timestamp, Transaction Type, Asset, Quantity Transacted,
    Price Currency, Price at Transaction, Subtotal,
    Total (inclusive of fees and/or spread), Fees and/or Spread, Notes,
    Sender Address, Recipient Address

How rows are interpreted:
- Every row with a nonzero "Quantity Transacted" is treated the same way,
  regardless of "Transaction Type": a positive quantity is an acquisition
  (Buy, Convert's incoming leg, Receive, Staking Income, Learning Reward,
  ...), a negative quantity is a disposal (Sell, Convert's outgoing leg,
  Send, ...). This matches how Jerson wants free/reward coins treated -
  counted toward the average at their recorded value when received, same
  as a purchase - and it means a paired "Convert" (two rows: one asset
  leaving, one arriving) and a "Retail Staking Transfer" (two rows, same
  asset, opposite sign, same instant - just moving into/out of staking)
  both fall out correctly with no special-case code.
- Rows whose "Asset" is itself a fiat currency (shouldn't normally appear
  in a crypto transaction history, but guarded against) are skipped.
- Amounts come in USD on this account. Per Jerson's choice, everything is
  converted to EUR using the *historical* rate on that transaction's date,
  via fx.rate_to_eur() - the same conversion entry point the Binance
  parser uses, so a "Price Currency" of EUR, a fiat/stablecoin, or (in
  principle, though not seen in a real Coinbase export) another crypto
  asset are all handled the same way. A row is skipped (and counted) if
  the relevant historical rate can't be fetched - see fx.py's and
  crypto_prices.py's docstrings for why that's a real risk right now
  (untested against either API from a network-restricted build
  environment).
- The "ID" column (Coinbase's own transaction id) is used directly as the
  de-dup key, prefixed with the exchange name.
"""
import argparse
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd

from .base import NormalizedTx
from .. import fx

EXCHANGE = "coinbase"

COLUMN_MAP = {
    "ID": "id",
    "Timestamp": "timestamp",
    "Transaction Type": "type",
    "Asset": "asset",
    "Quantity Transacted": "quantity",
    "Price Currency": "currency",
    "Price at Transaction": "spot_price",
    "Total (inclusive of fees and/or spread)": "total",
    "Fees and/or Spread": "fee",
}

FIAT_ASSETS = {"USD", "EUR", "GBP", "CHF", "CAD", "AUD"}


def _find_header_row(path: str) -> int:
    """Coinbase prepends a few summary lines (account name, user id, ...)
    before the real header. Scan the first 10 lines for the one that
    looks like headers."""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f.readlines()[:10]):
            if "Transaction Type" in line:
                return i
    return 0


def _parse_money(x) -> float:
    """Handles values like '$25.77926', '-$56.23448', '$0.00'."""
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", "").replace("$", "")
    if s in ("", "-", "nan"):
        return 0.0
    return float(s)


def _fallback_external_id(row: dict) -> str:
    raw = f"{EXCHANGE}|{row['timestamp']}|{row['asset']}|{row['quantity']}|{row['spot_price']}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def parse_file(path: str) -> List[NormalizedTx]:
    header_row = _find_header_row(path)
    df = pd.read_csv(path, skiprows=header_row)

    missing = [c for c in COLUMN_MAP if c not in df.columns]
    if missing:
        raise ValueError(
            f"Coinbase parser: expected columns {missing} not found. "
            f"Columns present in file: {list(df.columns)}. "
            f"Update COLUMN_MAP in backend/parsers/coinbase.py to match your export."
        )

    df = df.rename(columns=COLUMN_MAP)

    results: List[NormalizedTx] = []
    skipped_fiat = 0
    skipped_zero_qty = 0
    skipped_conversion_failed = 0

    for _, r in df.iterrows():
        asset = str(r["asset"]).strip().upper()
        if asset in FIAT_ASSETS:
            skipped_fiat += 1
            continue

        quantity = float(r["quantity"])
        if quantity == 0:
            skipped_zero_qty += 1
            continue

        currency = str(r["currency"]).strip().upper()
        total_raw = _parse_money(r["total"])
        price_raw = _parse_money(r["spot_price"])
        fee_raw = _parse_money(r["fee"])
        tx_timestamp = pd.to_datetime(r["timestamp"]).to_pydatetime()

        rate = fx.rate_to_eur(currency, tx_timestamp.date())
        if rate is None:
            skipped_conversion_failed += 1
            continue

        price_eur = price_raw * rate
        total_eur = abs(total_raw) * rate
        fee_eur = abs(fee_raw) * rate

        row_dict = {"timestamp": r["timestamp"], "asset": asset,
                    "quantity": quantity, "spot_price": r["spot_price"]}
        raw_id = r.get("id")
        external_id = f"{EXCHANGE}:{raw_id}" if pd.notna(raw_id) and str(raw_id).strip() \
            else _fallback_external_id(row_dict)

        results.append(NormalizedTx(
            symbol=asset,
            tx_type="buy" if quantity > 0 else "sell",
            quantity=abs(quantity),
            price_eur=price_eur,
            fee_eur=fee_eur,
            total_eur=total_eur,
            timestamp=tx_timestamp,
            exchange=EXCHANGE,
            external_id=external_id,
            source_file=Path(path).name,
            notes=f"{r['type']}: {r.get('notes', '')}".strip(": "),
        ))

    if skipped_fiat:
        print(f"[coinbase parser] skipped {skipped_fiat} row(s) whose asset was a fiat currency.")
    if skipped_zero_qty:
        print(f"[coinbase parser] skipped {skipped_zero_qty} row(s) with zero quantity.")
    if skipped_conversion_failed:
        print(f"[coinbase parser] skipped {skipped_conversion_failed} row(s) - couldn't convert "
              f"the price currency to EUR for that date (see backend/fx.py and "
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
        print(f"  {t.timestamp}  {t.tx_type.upper():4}  {t.quantity:>18.8f} {t.symbol:6} "
              f"@ EUR {t.price_eur:.6f}  fee EUR {t.fee_eur:.4f}  total EUR {t.total_eur:.2f}  [{t.notes}]")
    if len(txs) > 30:
        print(f"  ... and {len(txs) - 30} more")

    if not args.dry_run:
        print("Add --dry-run to only preview. Use the /upload API endpoint to actually import.")
