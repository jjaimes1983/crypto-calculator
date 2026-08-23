from datetime import datetime
from typing import Optional
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
