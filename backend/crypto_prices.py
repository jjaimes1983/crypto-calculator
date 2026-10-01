"""Historical EUR prices for crypto assets themselves, via CoinGecko's free
history endpoint. This is what makes a crypto-quoted trade (e.g. a
Binance AVAXBTC trade) convertible to EUR: multiply the BTC amount by
BTC's own historical EUR price on that date.

Same caveats as fx.py, which this mirrors:
- Could not be tested from the build sandbox - its network is
  allowlist-restricted and blocks external APIs entirely (confirmed via
  direct curl against api.coingecko.com - see fx.py's docstring for the
  same finding against Frankfurter). The live HTTP call needs verifying
  on your machine.
- Cached to data/crypto_price_cache.json so repeated imports don't
  re-fetch the same (asset, date) pair.
- Circuit breaker: after the first outright network failure or
  unexpected error status, stops calling the API for the rest of the
  process and returns None - never guesses a price.
- A short pause after each live (non-cached) call, to stay well under
  CoinGecko's free-tier rate limit if a file has many crypto-quoted
  trades across many different dates.
"""
import json
import time
from datetime import date
from pathlib import Path
from typing import Optional

import requests

from .prices import SYMBOL_TO_ID

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "crypto_price_cache.json"
_cache: Optional[dict] = None
_api_unreachable = False


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        if CACHE_PATH.exists():
            try:
                _cache = json.loads(CACHE_PATH.read_text())
            except (json.JSONDecodeError, OSError):
                _cache = {}
        else:
            _cache = {}
    return _cache


def _save_cache():
    CACHE_PATH.parent.mkdir(exist_ok=True)
    try:
        CACHE_PATH.write_text(json.dumps(_cache))
    except OSError:
        pass


def historical_eur_price(symbol: str, on_date: date) -> Optional[float]:
    """EUR value of 1 unit of `symbol` (a crypto asset, e.g. 'BTC') on
    `on_date`. Returns None - never a guess - if the symbol isn't
    recognized, the API has no data for that date, or the API/network is
    unreachable.
    """
    global _api_unreachable

    symbol = symbol.upper()
    coingecko_id = SYMBOL_TO_ID.get(symbol)
    if not coingecko_id:
        return None  # unrecognized asset - add it to SYMBOL_TO_ID in prices.py if needed

    cache = _load_cache()
    key = f"{coingecko_id}:{on_date.isoformat()}"
    if key in cache:
        return cache[key]

    if _api_unreachable:
        return None

    try:
        resp = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coingecko_id}/history",
            params={"date": on_date.strftime("%d-%m-%Y"), "localization": "false"},
            timeout=6,
        )
    except requests.RequestException:
        _api_unreachable = True
        return None

    if resp.status_code == 429:
        return None  # rate-limited - just this lookup fails, don't trip the permanent breaker
    if resp.status_code != 200:
        _api_unreachable = True
        return None

    time.sleep(1.3)  # be polite to the free tier before the next live call

    price = resp.json().get("market_data", {}).get("current_price", {}).get("eur")
    if price is None:
        return None  # no data for this asset/date - skip, don't guess

    price = float(price)
    cache[key] = price
    _save_cache()
    return price


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Look up a historical crypto EUR price (sanity check).")
    ap.add_argument("symbol", help="e.g. BTC")
    ap.add_argument("date", help="YYYY-MM-DD")
    args = ap.parse_args()
    d = date.fromisoformat(args.date)
    price = historical_eur_price(args.symbol, d)
    if price is None:
        print(f"Could not fetch a price for {args.symbol} on {d}. "
              f"Check your internet connection and that the symbol is in SYMBOL_TO_ID (backend/prices.py).")
    else:
        print(f"1 {args.symbol.upper()} = {price:.6f} EUR on {d}")
