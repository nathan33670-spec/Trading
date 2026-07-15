"""Prix de marché en temps réel (sans clé pour la crypto, Finnhub pour actions).

- crypto : API publique Kraken (paires EUR), ex. "BTC/EUR" → XBTEUR
- stock/etf : Finnhub /quote (symboles US et principaux tickers, clé gratuite)

Renvoie None si le prix est indisponible : dans ce cas le signal est rejeté,
on ne trade jamais à l'aveugle.
"""
import logging

import httpx

log = logging.getLogger(__name__)
HTTP_TIMEOUT = 10.0

_KRAKEN_ALIASES = {"BTC": "XBT", "DOGE": "XDG"}


def _kraken_pair(symbol: str) -> str:
    base, _, quote = symbol.partition("/")
    base = _KRAKEN_ALIASES.get(base.upper(), base.upper())
    return f"{base}{(quote or 'EUR').upper()}"


def crypto_price(symbol: str) -> float | None:
    try:
        pair = _kraken_pair(symbol)
        resp = httpx.get(
            "https://api.kraken.com/0/public/Ticker",
            params={"pair": pair},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            log.warning("Kraken ticker %s: %s", pair, data["error"])
            return None
        result = data["result"]
        return float(next(iter(result.values()))["c"][0])
    except Exception as exc:
        log.warning("Prix crypto %s indisponible: %s", symbol, exc)
        return None


def stock_price(symbol: str) -> float | None:
    from .secrets import get_secret

    key = get_secret("finnhub_api_key")
    if not key:
        log.warning("finnhub_api_key manquante : prix actions indisponibles")
        return None
    try:
        resp = httpx.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": symbol, "token": key},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        price = resp.json().get("c")
        return float(price) if price else None
    except Exception as exc:
        log.warning("Prix action %s indisponible: %s", symbol, exc)
        return None


def get_price(symbol: str, asset_class: str) -> float | None:
    if asset_class == "crypto":
        return crypto_price(symbol)
    return stock_price(symbol)
