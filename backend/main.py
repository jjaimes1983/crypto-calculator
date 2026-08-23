import shutil
import tempfile
from pathlib import Path
from typing import List

from fastapi import FastAPI, Depends, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .database import get_db, SessionLocal, engine, Base
from . import models
from .models import Asset, Transaction, TxType
from .parsers import binance, coinbase
from .calculations import compute_holding, solve_target_average
from .prices import fetch_current_prices_eur
from . import schemas

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Crypto Calculator")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


PARSERS = {
    "binance": binance.parse_file,
    "coinbase": coinbase.parse_file,
}


def _get_or_create_asset(db: Session, symbol: str) -> Asset:
    asset = db.query(Asset).filter(Asset.symbol == symbol).first()
    if not asset:
        asset = Asset(symbol=symbol)
        db.add(asset)
        db.flush()
    return asset


@app.post("/upload", response_model=schemas.UploadResult)
async def upload_file(exchange: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    exchange = exchange.lower().strip()
    if exchange not in PARSERS:
        raise HTTPException(400, f"Unknown exchange '{exchange}'. Supported: {list(PARSERS.keys())}")

    suffix = Path(file.filename).suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        normalized_txs = PARSERS[exchange](tmp_path)
    except Exception as e:
        raise HTTPException(400, f"Failed to parse file: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    imported = 0
    duplicates = 0
    for ntx in normalized_txs:
        asset = _get_or_create_asset(db, ntx.symbol)
        tx = Transaction(
            asset_id=asset.id,
            tx_type=TxType(ntx.tx_type),
            quantity=ntx.quantity,
            price_eur=ntx.price_eur,
            fee_eur=ntx.fee_eur,
            total_eur=ntx.total_eur,
            timestamp=ntx.timestamp,
            exchange=ntx.exchange,
            external_id=ntx.external_id,
            source_file=ntx.source_file,
            notes=ntx.notes,
        )
        db.add(tx)
        try:
            db.flush()
            imported += 1
        except IntegrityError:
            db.rollback()
            duplicates += 1

    db.commit()

    return schemas.UploadResult(
        exchange=exchange,
        filename=file.filename,
        parsed=len(normalized_txs),
        imported=imported,
        duplicates_skipped=duplicates,
    )


@app.get("/assets", response_model=List[schemas.HoldingOut])
def list_assets(db: Session = Depends(get_db)):
    assets = db.query(Asset).all()
    holdings = []
    symbols = []
    computed = []

    for asset in assets:
        h = compute_holding(asset.transactions)
        if h is None or h.quantity <= 0:
            continue
        computed.append(h)
        symbols.append(h.symbol)

    current_prices = fetch_current_prices_eur(symbols) if symbols else {}

    for h in computed:
        price = current_prices.get(h.symbol)
        unrealized = None
        unrealized_pct = None
        if price is not None:
            unrealized = (price - h.avg_cost_eur) * h.quantity
            if h.avg_cost_eur > 0:
                unrealized_pct = (price - h.avg_cost_eur) / h.avg_cost_eur * 100

        holdings.append(schemas.HoldingOut(
            symbol=h.symbol,
            quantity=h.quantity,
            avg_cost_eur=h.avg_cost_eur,
            total_cost_eur=h.total_cost_eur,
            realized_pl_eur=h.realized_pl_eur,
            current_price_eur=price,
            unrealized_pl_eur=unrealized,
            unrealized_pl_pct=unrealized_pct,
        ))

    holdings.sort(key=lambda h: h.total_cost_eur, reverse=True)
    return holdings


@app.get("/assets/{symbol}/transactions", response_model=List[schemas.TransactionOut])
def asset_transactions(symbol: str, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.symbol == symbol.upper()).first()
    if not asset:
        raise HTTPException(404, "Asset not found")
    txs = sorted(asset.transactions, key=lambda t: t.timestamp)
    return txs


@app.post("/assets/{symbol}/target-average", response_model=schemas.TargetAverageResponse)
def target_average(symbol: str, req: schemas.TargetAverageRequest, db: Session = Depends(get_db)):
    asset = db.query(Asset).filter(Asset.symbol == symbol.upper()).first()
    if not asset:
        raise HTTPException(404, "Asset not found")
    holding = compute_holding(asset.transactions)
    if holding is None:
        raise HTTPException(400, "No holdings for this asset")

    result = solve_target_average(
        current_qty=holding.quantity,
        current_avg_cost=holding.avg_cost_eur,
        buy_price=req.buy_price,
        target_avg=req.target_avg,
    )
    return schemas.TargetAverageResponse(
        reachable=result.reachable,
        message=result.message,
        required_quantity=result.required_quantity,
        required_eur=result.required_eur,
    )
