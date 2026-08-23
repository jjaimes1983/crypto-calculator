"""SQLAlchemy models.

Design notes:
- Asset: one row per crypto asset (BTC, ETH, ...).
- Transaction: one row per buy/sell/fee event, normalized regardless of
  which exchange it came from. Parsers (backend/parsers/*) are responsible
  for turning raw exchange exports into rows in this shape.
- Everything monetary is stored in EUR (per user's choice) as the
  `price_eur` (price per unit at time of trade) and `fee_eur`. If a source
  file is in another currency, the parser should convert at parse time
  (or leave a TODO - see parsers/base.py) rather than storing mixed
  currencies silently.
- `external_id` + `exchange` give a de-duplication key so re-uploading the
  same export file twice doesn't double-count transactions.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint, Enum
)
from sqlalchemy.orm import relationship
import enum

from .database import Base


class TxType(str, enum.Enum):
    buy = "buy"
    sell = "sell"


class Asset(Base):
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True)
    symbol = Column(String, unique=True, nullable=False, index=True)  # e.g. "BTC"
    name = Column(String, nullable=True)  # e.g. "Bitcoin"

    transactions = relationship("Transaction", back_populates="asset", cascade="all, delete-orphan")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("exchange", "external_id", name="uq_exchange_external_id"),
    )

    id = Column(Integer, primary_key=True)
    asset_id = Column(Integer, ForeignKey("assets.id"), nullable=False)

    tx_type = Column(Enum(TxType), nullable=False)
    quantity = Column(Float, nullable=False)        # units of the asset
    price_eur = Column(Float, nullable=False)        # EUR per unit at execution
    fee_eur = Column(Float, nullable=False, default=0.0)
    total_eur = Column(Float, nullable=False)         # quantity*price_eur (+/- fee), what was actually paid/received

    timestamp = Column(DateTime, nullable=False)

    exchange = Column(String, nullable=False)         # "binance" | "coinbase" | "manual"
    external_id = Column(String, nullable=True)        # source row id/hash, for de-dup on re-upload
    source_file = Column(String, nullable=True)
    notes = Column(String, nullable=True)

    imported_at = Column(DateTime, default=datetime.utcnow)

    asset = relationship("Asset", back_populates="transactions")
