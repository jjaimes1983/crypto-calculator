"""Best-effort current price lookup via CoinGecko's free public API (no key
needed). Used only to show today's unrealized P/L on the dashboard - it
has no effect on your stored average cost, and if a symbol can't be
resolved or the API is unreachable, the dashboard just shows the price
as unknown rather than failing the whole page.
"""
import requests

# Common symbol -> CoinGecko id. Add to this if you hold something not listed.
SYMBOL_TO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "ADA": "cardano",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "POL": "matic-network",
    "LTC": "litecoin",
    "LINK": "chainlink",
    "AVAX": "avalanche-2",
    "BNB": "binancecoin",
    "USDT": "tether",
    "USDC": "usd-coin",
    "TRX": "tron",
    "ATOM": "cosmos",
    "XLM": "stellar",
    "ETC": "ethereum-classic",
    "ALGO": "algorand",
}

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


def fetch_current_prices_eur(symbols: list[str], timeout: float = 5.0) -> dict:
    """Returns {symbol: eur_price or None}. Never raises - network/API
    problems just result in None values so the dashboard degrades gracefully."""
    ids = {}
    for s in symbols:
        cg_id = SYMBOL_TO_ID.get(s.upper())
        if cg_id:
            ids[cg_id] = s.upper()

    result = {s.upper(): None for s in symbols}
    if not ids:
        return result

    try:
        resp = requests.get(
            COINGECKO_URL,
            params={"ids": ",".join(ids.keys()), "vs_currencies": "eur"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        for cg_id, symbol in ids.items():
            price = data.get(cg_id, {}).get("eur")
            if price is not None:
                result[symbol] = float(price)
    except (requests.RequestException, ValueError):
        pass  # leave as None - caller/frontend handles missing prices

    return result
