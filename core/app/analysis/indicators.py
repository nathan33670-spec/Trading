"""Indicateurs techniques — Python pur, sans dépendance (pas de numpy/pandas).

Toutes les fonctions prennent une liste de flottants ordonnée du plus ancien au
plus récent et renvoient soit une valeur, soit une série de même longueur dont
les premières valeurs sont None tant que l'indicateur n'a pas assez d'historique.

Aucun appel réseau ici : ce module est pur et testable à 100 %.
"""
from dataclasses import dataclass


@dataclass
class Candle:
    """Une bougie OHLCV. `ts` est un timestamp UNIX en secondes."""

    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    total = sum(values[:period])
    out[period - 1] = total / period
    for i in range(period, len(values)):
        total += values[i] - values[i - period]
        out[i] = total / period
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    """Moyenne mobile exponentielle, amorcée par une SMA sur la 1re fenêtre."""
    out: list[float | None] = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    """RSI de Wilder (lissage exponentiel des gains/pertes)."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out

    gains = losses = 0.0
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)

    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(delta, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-delta, 0.0)) / period
        out[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


def macd(
    values: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Renvoie (ligne MACD, ligne de signal, histogramme)."""
    fast_ema, slow_ema = ema(values, fast), ema(values, slow)
    line: list[float | None] = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(fast_ema, slow_ema)
    ]

    defined = [(i, v) for i, v in enumerate(line) if v is not None]
    sig: list[float | None] = [None] * len(values)
    if len(defined) >= signal:
        sig_vals = ema([v for _, v in defined], signal)
        for (idx, _), s in zip(defined, sig_vals):
            sig[idx] = s

    hist: list[float | None] = [
        (m - s) if (m is not None and s is not None) else None for m, s in zip(line, sig)
    ]
    return line, sig, hist


def true_range(candles: list[Candle]) -> list[float]:
    out = [candles[0].high - candles[0].low] if candles else []
    for i in range(1, len(candles)):
        c, prev = candles[i], candles[i - 1]
        out.append(max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close)))
    return out


def atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    """Average True Range (Wilder) — mesure de volatilité, base des stops."""
    tr = true_range(candles)
    out: list[float | None] = [None] * len(candles)
    if len(tr) < period:
        return out
    prev = sum(tr[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(tr)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def bollinger(
    values: list[float], period: int = 20, mult: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Renvoie (bande basse, moyenne, bande haute)."""
    mid = sma(values, period)
    lower: list[float | None] = [None] * len(values)
    upper: list[float | None] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        mean = mid[i]
        if mean is None:
            continue
        var = sum((v - mean) ** 2 for v in window) / period
        sd = var ** 0.5
        lower[i], upper[i] = mean - mult * sd, mean + mult * sd
    return lower, mid, upper


def highest(values: list[float], period: int, end: int) -> float | None:
    """Plus haut des `period` valeurs se terminant à l'indice `end` (inclus)."""
    start = end - period + 1
    if start < 0 or end >= len(values):
        return None
    return max(values[start : end + 1])


def lowest(values: list[float], period: int, end: int) -> float | None:
    start = end - period + 1
    if start < 0 or end >= len(values):
        return None
    return min(values[start : end + 1])


def slope_pct(values: list[float | None], period: int) -> float | None:
    """Pente d'une série sur `period` bougies, en % de la valeur de départ."""
    if len(values) < period + 1:
        return None
    last, first = values[-1], values[-1 - period]
    if last is None or first is None or first == 0:
        return None
    return (last / first - 1) * 100
