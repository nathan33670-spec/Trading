"""Historique long de bougies (Bitstamp, public et sans clé).

Kraken plafonne à 720 bougies (≈2 ans en journalier), insuffisant pour
calibrer ou vérifier une stratégie de momentum 12 mois. Bitstamp remonte à
2016 pour BTC/EUR, ce qui permet de tester sur plusieurs cycles complets —
la leçon principale de ce projet : une stratégie jugée sur un seul marché
baissier paraît catastrophique, et sur un seul marché haussier, géniale.
"""
import logging
import threading
import time

import httpx

from .analysis.indicators import Candle

log = logging.getLogger(__name__)

HTTP_TIMEOUT = 20.0
DAY = 86400

# Correspondance symbole applicatif → paire Bitstamp
_BITSTAMP = {
    "BTC/EUR": "btceur", "ETH/EUR": "etheur", "XRP/EUR": "xrpeur",
    "LTC/EUR": "ltceur", "ADA/EUR": "adaeur", "SOL/EUR": "soleur",
    "LINK/EUR": "linkeur", "AVAX/EUR": "avaxeur", "UNI/EUR": "unieur",
    "DOT/EUR": "dotpeur", "ATOM/EUR": "atomeur",
}

_cache: dict[tuple[str, int], tuple[float, list[Candle]]] = {}
_lock = threading.Lock()
CACHE_TTL = 6 * 3600


def supported(symbol: str) -> bool:
    return symbol.upper() in _BITSTAMP


def history(symbol: str, step: int = DAY, start: int = 1_451_606_400) -> list[Candle]:
    """Bougies depuis `start` (défaut : 2016). Liste vide si indisponible."""
    pair = _BITSTAMP.get(symbol.upper())
    if not pair:
        return []

    key = (pair, step)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]

    candles: list[Candle] = []
    cursor, wall = start, int(time.time())
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            # Bitstamp exige start ET end, et renvoie 1000 bougies maximum :
            # on avance par fenêtres.
            while cursor < wall:
                end = min(cursor + 1000 * step, wall)
                resp = client.get(
                    f"https://www.bitstamp.net/api/v2/ohlc/{pair}/",
                    params={"step": step, "limit": 1000, "start": cursor, "end": end},
                )
                resp.raise_for_status()
                rows = resp.json().get("data", {}).get("ohlc", [])
                for r in rows:
                    close = float(r["close"])
                    if close > 0:
                        candles.append(Candle(
                            ts=int(r["timestamp"]), open=float(r["open"]),
                            high=float(r["high"]), low=float(r["low"]),
                            close=close, volume=float(r["volume"]),
                        ))
                cursor = end + step
    except Exception as exc:
        log.warning("Historique %s indisponible: %s", symbol, exc)
        return []

    seen: set[int] = set()
    unique = []
    for c in sorted(candles, key=lambda c: c.ts):
        if c.ts not in seen:
            seen.add(c.ts)
            unique.append(c)

    with _lock:
        _cache[key] = (now + CACHE_TTL, unique)
    return unique


def clear_cache() -> None:
    with _lock:
        _cache.clear()
