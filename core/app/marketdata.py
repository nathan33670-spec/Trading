"""Prix de marché en temps réel (sans clé pour la crypto, Finnhub pour actions).

- crypto : API publique Kraken (paires EUR), ex. "BTC/EUR" → XBTEUR.
  Cotations ET historique de bougies, sans aucune clé — c'est ce qui permet à
  l'analyse technique de tourner même sans le moindre compte API.
- stock/etf : Finnhub /quote (symboles US et principaux tickers, clé gratuite)

Renvoie None si le prix est indisponible : dans ce cas le signal est rejeté,
on ne trade jamais à l'aveugle.
"""
import logging
import threading
import time

import httpx

from .analysis.indicators import Candle

log = logging.getLogger(__name__)
HTTP_TIMEOUT = 10.0

_KRAKEN_ALIASES = {"BTC": "XBT", "DOGE": "XDG"}

# Cache des bougies : {(symbole, intervalle): (expiration_monotonic, bougies)}
_ohlc_cache: dict[tuple[str, int], tuple[float, list[Candle]]] = {}
_ohlc_lock = threading.Lock()


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


# ── Historique de bougies (analyse technique) ────────────────────────────────

def crypto_ohlc(symbol: str, interval_min: int = 60, cache_ttl: int = 300) -> list[Candle]:
    """Bougies OHLCV d'une paire crypto via l'API publique Kraken (sans clé).

    Kraken renvoie au maximum 720 bougies, soit 30 jours en 1 h — largement
    de quoi calculer une EMA200. La dernière bougie est encore en formation :
    on la conserve (c'est le prix courant) mais les détecteurs s'appuient
    surtout sur les bougies closes.
    """
    key = (symbol.upper(), interval_min)
    now = time.monotonic()
    with _ohlc_lock:
        cached = _ohlc_cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

    try:
        resp = httpx.get(
            "https://api.kraken.com/0/public/OHLC",
            params={"pair": _kraken_pair(symbol), "interval": interval_min},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            log.warning("Kraken OHLC %s: %s", symbol, data["error"])
            return []
        rows = next(v for k, v in data["result"].items() if k != "last")
        candles = [
            Candle(
                ts=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[6]),
            )
            for row in rows
        ]
    except Exception as exc:
        log.warning("Bougies %s indisponibles: %s", symbol, exc)
        return []

    with _ohlc_lock:
        _ohlc_cache[key] = (now + cache_ttl, candles)
    return candles


def clear_ohlc_cache() -> None:
    with _ohlc_lock:
        _ohlc_cache.clear()
