"""Parser for Coinbase's "Transaction History" CSV export.

Where to get this file: Coinbase > Taxes & Reports (or Account Statements)
> Transaction history > Generate/Download CSV. Expected columns (as of
Coinbase's current export):

    Timestamp, Transaction Type, Asset, Quantity Transacted,
    Spot Price Currency, Spot Price at Transaction, Subtotal,
    Total (inclusive of fees and/or spread), Fees and/or Spread, Notes

Only rows where "Spot Price Currency" is EUR are imported automatically,
for the same reason noted in binance.py: no guessed FX conversion. Only
"Buy" and "Sell" transaction types are imported; Send/Receive/Convert/
Reward rows are reported but skipped (they're not purchases and don't
have a straightforward EUR cost-basis interpretation without more rules).

Coinbase's export has a few metadata lines above the real header row in
some report styles - this parser auto-detects the header row by looking
for "Transaction Type" in the first column.
"""
import argparse
import hashlib
from pathlib import Path
from typing import List

import pandas as pd

from .base import NormalizedTx

EXCHANGE = "coinbase"

COLUMN_MAP = {
    "Timestamp": "timestamp",
    "Transaction Type": "type",
    "Asset": "asset",
    "Quantity Transacted": "quantity",
    "Spot Price Currency": "currency",
    "Spot Price at Transaction": "spot_price",
    "Total (inclusive of fees and/or spread)": "total",
    "Fees and/or Spread": "fee",
}


def _find_header_row(path: str) -> int:
    """Coinbase sometimes prepends a few summary lines before the real
    header. Scan the first 10 lines for the row that looks like headers."""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f.readlines()[:10]):
            if "Transaction Type" in line:
                return i
    return 0


def _row_external_id(row: dict) -> str:
    raw = f"{EXCHANGE}|{row['timestamp']}|{row['asset']}|{row['type']}|{row['quantity']}|{row['spot_price']}"
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
    skipped_non_eur = 0
    skipped_other_type = 0

    for _, r in df.iterrows():
        tx_type_raw = str(r["type"]).strip().lower()
        if tx_type_raw not in ("buy", "sell"):
            skipped_other_type += 1
            continue

        if str(r["currency"]).strip().upper() != "EUR":
            skipped_non_eur += 1
            continue

        quantity = float(r["quantity"])
        price_eur = float(r["spot_price"])
        fee_eur = float(r["fee"]) if not pd.isna(r["fee"]) else 0.0
        total_eur = float(r["total"])

        row_dict = {"timestamp": r["timestamp"], "asset": r["asset"], "type": tx_type_raw,
                    "quantity": quantity, "spot_price": price_eur}

        results.append(NormalizedTx(
            symbol=str(r["asset"]).strip().upper(),
            tx_type=tx_type_raw,
            quantity=quantity,
            price_eur=price_eur,
            fee_eur=fee_eur,
            total_eur=total_eur,
            timestamp=pd.to_datetime(r["timestamp"]).to_pydatetime(),
            exchange=EXCHANGE,
            external_id=_row_external_id(row_dict),
            source_file=Path(path).name,
        ))

    if skipped_non_eur:
        print(f"[coinbase parser] skipped {skipped_non_eur} non-EUR-quoted row(s).")
    if skipped_other_type:
        print(f"[coinbase parser] skipped {skipped_other_type} non buy/sell row(s) "
              f"(sends, receives, converts, rewards, etc.).")

    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path")
    ap.add_argument("--dry-run", action="store_true", help="Parse and print only, don't touch the DB")
    args = ap.parse_args()

    txs = parse_file(args.path)
    print(f"Parsed {len(txs)} EUR buy/sell transaction(s):")
    for t in txs[:20]:
        print(f"  {t.timestamp}  {t.tx_type.upper():4}  {t.quantity:>14.8f} {t.symbol:5} "
              f"@ EUR {t.price_eur:.4f}  fee EUR {t.fee_eur:.4f}  total EUR {t.total_eur:.2f}")
    if len(txs) > 20:
        print(f"  ... and {len(txs) - 20} more")

    if not args.dry_run:
        print("Add --dry-run to only preview. Use the /upload API endpoint to actually import.")
