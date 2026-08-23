"""Shared shape that every exchange-specific parser normalizes into.

IMPORTANT / TODO for you (Jerson):
I built the Binance and Coinbase parsers from the *documented/standard*
export formats for each exchange. Binance in particular has changed its
export format more than once and has several different "Transaction
History" report types (Trade History, Convert History, Deposit/Withdrawal,
etc.) - I don't have one of your actual files to verify column names
against. Before trusting the numbers:

  1. Upload one real (or redacted-amounts) export file from each exchange.
  2. Run `python -m backend.parsers.binance path/to/file.csv --dry-run`
     (same for coinbase) - it will print the parsed rows without touching
     the database, so you can sanity-check them against the source file.
  3. Fix any column-name mismatches in binance.py / coinbase.py - they're
     intentionally kept simple and readable so this is a quick edit.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class NormalizedTx:
    symbol: str            # e.g. "BTC"
    tx_type: str            # "buy" | "sell"
    quantity: float          # positive units of the asset
    price_eur: float          # EUR per unit
    fee_eur: float
    total_eur: float          # what actually left/entered your account, in EUR
    timestamp: datetime
    exchange: str
    external_id: Optional[str] = None
    source_file: Optional[str] = None
    notes: Optional[str] = None
