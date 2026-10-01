"""Historical USD -> EUR conversion, via the Frankfurter API (European
Central Bank reference rates - free, no API key, and ECB has published
daily rates back to 1999). Also the shared entry point (`rate_to_eur`)
for converting a transaction quoted in *any* currency to EUR - fiat, a
USD-pegged stablecoin, or a crypto asset (delegated to crypto_prices.py)
- so both parsers call one function regardless of what a trade was
quoted in.

USDT/USDC/BUSD/etc. ("stablecoins") are treated as 1:1 with USD - not
perfectly true minute to minute, but the drift is a basis point or two,
immaterial next to the price of a whole coin.

Results are cached to data/fx_cache.json so repeated imports (or a
--dry-run followed by a real upload) don't re-fetch the same date twice,
and so a flaky connection only has to succeed once per date.

IMPORTANT - this could not be tested from the environment I built it in
(its outbound network is restricted to an allowlist that blocks external
APIs, confirmed with a direct curl - see build notes). It's written
defensively - any failure returns None rather than guessing a rate, and
the parsers that call this skip + report affected transactions rather
than importing a fabricated number - but the actual HTTP call to
Frankfurter needs to be verified on your machine. Run a parser
--dry-run and check for "FX lookup failed" in the output; if you see
that a lot, tell me and I'll swap in a different rate source.
"""
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests

from . import crypto_prices

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "fx_cache.json"
STABLE_TO_USD = {"USD", "USDT", "USDC", "BUSD", "TUSD", "USDP", "DAI"}

_cache: Optional[dict] = None

# Circuit breaker: a file with hundreds of USD transactions can span
# hundreds of distinct dates. If the API/network is unreachable, retrying
# every date up to max_lookback_days times each turns one bad connection
# into a multi-minute hang. After ONE outright failure (network error or
# non-200 response), stop trying for the rest of this process and return
# None immediately - the caller's "skipped, FX lookup failed" reporting
# still applies, it just happens fast instead of after retrying hundreds
# of times for a service that's already known to be unreachable right now.
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
        pass  # cache is a pure optimization - fine to skip if disk write fails


def usd_to_eur_rate(on_date: date, max_lookback_days: int = 5) -> Optional[float]:
    """EUR per 1 USD, on `on_date` or the nearest earlier day the API has
    data for (FX markets are closed weekends/holidays). Returns None if
    no rate could be found within max_lookback_days, or the API/network
    is unreachable - callers must treat None as "skip this transaction",
    never substitute a guess.
    """
    global _api_unreachable

    cache = _load_cache()
    key = on_date.isoformat()
    if key in cache:
        return cache[key]

    if _api_unreachable:
        return None

    d = on_date
    for _ in range(max_lookback_days + 1):
        d_key = d.isoformat()
        if d_key in cache:
            rate = cache[d_key]
            cache[key] = rate
            _save_cache()
            return rate
        try:
            resp = requests.get(
                f"https://api.frankfurter.dev/v1/{d_key}",
                params={"from": "USD", "to": "EUR"},
                timeout=4,
            )
        except requests.RequestException:
            _api_unreachable = True  # stop hammering a service that's down for the rest of this run
            return None

        if resp.status_code == 200:
            rate = resp.json().get("rates", {}).get("EUR")
            if rate:
                rate = float(rate)
                cache[d_key] = rate
                cache[key] = rate
                _save_cache()
                return rate
            # 200 but no EUR rate for this date - try an earlier day
        elif resp.status_code != 404:
            # Anything other than "no data for this date" (404) suggests
            # the service itself is unhappy (blocked, rate-limited, down) -
            # trip the breaker rather than retrying that N more times.
            _api_unreachable = True
            return None

        d -= timedelta(days=1)

    return None


def convert_usd_to_eur(usd_amount: float, on_date: date) -> Optional[float]:
    rate = usd_to_eur_rate(on_date)
    if rate is None:
        return None
    return usd_amount * rate


def rate_to_eur(currency: str, on_date: date) -> Optional[float]:
    """EUR value of 1 unit of `currency` on `on_date` - the single
    conversion entry point both parsers use, regardless of whether
    `currency` is EUR itself, a fiat/stablecoin (this module, via
    Frankfurter), or a crypto asset like BTC (crypto_prices.py, via
    CoinGecko's historical price endpoint - e.g. for a Binance AVAXBTC
    trade, this is "how many EUR was 1 BTC worth that day"). Returns
    None - never a guess - if the currency is unrecognized or the
    relevant lookup failed.
    """
    currency = currency.upper()
    if currency == "EUR":
        return 1.0
    if currency in STABLE_TO_USD:
        return usd_to_eur_rate(on_date)
    return crypto_prices.historical_eur_price(currency, on_date)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Look up a historical USD->EUR rate (sanity check).")
    ap.add_argument("date", help="YYYY-MM-DD")
    args = ap.parse_args()
    d = date.fromisoformat(args.date)
    rate = usd_to_eur_rate(d)
    if rate is None:
        print(f"Could not fetch a rate for {d} (or the {7} days before it). "
              f"Check your internet connection - see the module docstring.")
    else:
        print(f"1 USD = {rate:.6f} EUR on/near {d}")
