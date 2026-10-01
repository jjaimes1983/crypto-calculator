from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel


class TransactionOut(BaseModel):
    id: int
    tx_type: str
    quantity: float
    price_eur: float
    fee_eur: float
    total_eur: float
    timestamp: datetime
    exchange: str
    source_file: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class HoldingOut(BaseModel):
    symbol: str
    quantity: float
    avg_cost_eur: float
    total_cost_eur: float
    realized_pl_eur: float
    current_price_eur: Optional[float] = None
    unrealized_pl_eur: Optional[float] = None
    unrealized_pl_pct: Optional[float] = None


class TargetAverageRequest(BaseModel):
    buy_price: float
    target_avg: float


class TargetAverageResponse(BaseModel):
    reachable: bool
    message: str
    required_quantity: Optional[float] = None
    required_eur: Optional[float] = None


class UploadResult(BaseModel):
    exchange: str
    filename: str
    parsed: int
    imported: int
    duplicates_skipped: int


class ConfigOut(BaseModel):
    tracked_symbols: List[str]


class ConfigUpdate(BaseModel):
    tracked_symbols: List[str]


class ManualTransactionRequest(BaseModel):
    tx_type: str  # "buy" or "sell"
    quantity: float
    price_eur: float = 0.0  # leave 0 for "unknown cost" (e.g. an unexplained wallet discrepancy)
    timestamp: Optional[datetime] = None  # defaults to now if not given
    notes: Optional[str] = None
