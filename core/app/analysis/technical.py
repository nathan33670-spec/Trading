"""Détection de marqueurs sur les courbes — 100 % déterministe, aucun LLM.

C'est le moteur qui fait vivre le bot entre deux actualités : il lit les
bougies, repère des configurations classiques et ne propose un signal que si
plusieurs marqueurs concordent.

Trois principes, appris à la dure (un premier jet produisait ~1 000 signaux par
mois, soit une fabrique à commissions) :

1. **Des événements, pas des états.** Un signal se déclenche sur une
   *transition* qui vient d'avoir lieu (cassure franchie, croisement, repli
   acheté), jamais sur une situation qui dure — sinon la même configuration
   redéclenche à chaque bougie.
2. **Uniquement des bougies closes.** La dernière bougie renvoyée par
   l'exchange est encore en formation : l'inclure ferait clignoter les
   détecteurs au gré des ticks.
3. **Un objectif qui paie les frais.** Avec 1,49 % par transaction (Revolut
   Standard), un aller-retour coûte ~3 % : viser 2 % est une perte certaine.
   C'est pourquoi l'unité de temps par défaut est 4 h et non 1 h.

Long uniquement, comme le reste de l'application. Rien n'est « garanti » : ces
règles sont des filtres de probabilité. Le moteur de risque reste seul maître
de la taille de position.
"""
import logging
from dataclasses import dataclass, field

from .indicators import Candle, atr, bollinger, ema, highest, lowest, macd, rsi, sma

log = logging.getLogger(__name__)

# Historique minimum pour que l'EMA200 soit définie, avec de la marge
MIN_CANDLES = 210


@dataclass
class Marker:
    """Un marqueur repéré sur la courbe."""

    code: str
    label: str
    score: int              # contribution à la conviction (positive ou négative)
    primary: bool = False   # un marqueur primaire peut à lui seul déclencher


@dataclass
class TechnicalSignal:
    symbol: str
    price: float
    conviction: int
    stop_pct: float
    target_pct: float
    markers: list[Marker] = field(default_factory=list)
    context: dict = field(default_factory=dict)

    @property
    def triggers(self) -> list[Marker]:
        return [m for m in self.markers if m.primary]

    @property
    def rationale(self) -> str:
        noms = ", ".join(m.label for m in self.markers if m.score > 0)
        c = self.context
        return (
            f"Analyse technique {c.get('timeframe', '?')} : {noms}. "
            f"RSI {c.get('rsi', 0):.0f}, tendance {c.get('trend', '?')}, "
            f"volatilité {c.get('atr_pct', 0):.1f} %/bougie. "
            f"Stop {self.stop_pct:.1f} % (1,5×ATR), objectif {self.target_pct:.1f} %."
        )


@dataclass
class Reading:
    """Lecture complète d'une courbe, signal ou non — sert aussi à l'affichage."""

    symbol: str
    price: float
    trend: str
    rsi: float
    atr_pct: float
    markers: list[Marker]
    signal: TechnicalSignal | None
    reason: str = ""          # pourquoi aucun signal, le cas échéant


def _crossed_above(fast: list[float | None], slow: list[float | None], within: int) -> bool:
    """Vrai si `fast` est passée au-dessus de `slow` dans les `within` dernières bougies."""
    n = len(fast)
    for i in range(n - 1, max(n - 1 - within, 0), -1):
        f0, s0, f1, s1 = fast[i - 1], slow[i - 1], fast[i], slow[i]
        if None in (f0, s0, f1, s1):
            continue
        if f0 <= s0 and f1 > s1:
            return True
    return False


def read(symbol: str, candles: list[Candle], timeframe: str = "4h", drop_forming: bool = True) -> Reading | None:
    """Analyse une courbe. `drop_forming` écarte la dernière bougie (en formation)."""
    if drop_forming and len(candles) > 1:
        candles = candles[:-1]
    if len(candles) < MIN_CANDLES:
        return None

    closes = [c.close for c in candles]
    volumes = [c.volume for c in candles]
    price = closes[-1]
    if price <= 0:
        return None

    ema20, ema50, ema200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    rsi14 = rsi(closes, 14)
    macd_line, macd_sig, macd_hist = macd(closes)
    bb_low, _, _ = bollinger(closes, 20, 2.0)
    atr14 = atr(candles, 14)
    vol_avg = sma(volumes, 20)

    e20, e50, e200 = ema20[-1], ema50[-1], ema200[-1]
    r, r_prev = rsi14[-1], rsi14[-2]
    a = atr14[-1]
    if None in (e20, e50, e200, r, r_prev, a) or a <= 0:
        return None

    atr_pct = a / price * 100
    trend_up = e50 > e200
    above_200 = price > e200
    trend_label = "haussière" if trend_up else "baissière"
    v_avg = vol_avg[-1] or 0.0

    def nothing(reason: str) -> Reading:
        return Reading(symbol, price, trend_label, r, atr_pct, [], None, reason)

    # ── Filtres d'exclusion ──────────────────────────────────────────────────
    if atr_pct < 0.35:
        return nothing(f"volatilité trop faible ({atr_pct:.2f} %/bougie) : le mouvement ne paierait pas les frais")
    if atr_pct > 8.0:
        return nothing(f"volatilité extrême ({atr_pct:.1f} %/bougie) : stops trop fragiles")
    # Anti-parabolique. Le seuil doit rester au-dessus de ce que produit une
    # cassure normale (~2-2,5 ATR au-dessus de l'EMA20), sinon il éliminerait
    # précisément les configurations qu'on cherche.
    if (price - e20) / a > 3.5:
        return nothing("prix déjà très étendu au-dessus de sa moyenne : on ne court pas après")
    if not above_200:
        return nothing("prix sous l'EMA200 : pas d'achat à contre-tendance de fond")

    markers: list[Marker] = []

    # ── Marqueurs primaires : des ÉVÉNEMENTS survenus sur la dernière bougie ──

    # 1. Cassure franche du plus haut des 20 bougies précédentes, volume à l'appui.
    #    La bougie d'avant doit être SOUS le seuil : c'est le franchissement qui
    #    compte, pas le fait d'être haut.
    prior_high = highest(closes, 20, len(closes) - 2)
    high_before = highest(closes, 20, len(closes) - 3)
    if prior_high and high_before and trend_up:
        if price > prior_high and closes[-2] <= high_before and v_avg and volumes[-1] > v_avg * 1.3:
            markers.append(Marker("breakout", "cassure du plus haut 20 bougies avec volume", 26, primary=True))

    # 2. Repli acheté en tendance : le RSI est descendu sous 40 dans les 5
    #    dernières bougies puis vient de repasser au-dessus de 45, près de l'EMA20.
    if trend_up:
        dipped = any((v is not None and v < 40) for v in rsi14[-6:-1])
        recovered = r_prev is not None and r_prev <= 45 < r
        near_ema = abs(price - e20) / a < 1.2
        if dipped and recovered and near_ema:
            markers.append(Marker("pullback", "repli acheté sur la moyenne mobile (tendance haussière)", 24, primary=True))

    # 3. Croisement MACD haussier tout frais, au-dessus de zéro (momentum réel)
    if _crossed_above(macd_line, macd_sig, within=1) and (macd_line[-1] or 0) > 0:
        markers.append(Marker("macd_cross", "croisement MACD haussier au-dessus de zéro", 20, primary=True))

    # 4. Croisement doré EMA20/EMA50 tout frais
    if _crossed_above(ema20, ema50, within=2):
        markers.append(Marker("golden_cross", "croisement EMA20 au-dessus d'EMA50", 20, primary=True))

    # 5. Rebond de survente franc : clôture sous la bande basse puis retour dedans
    low_band_prev = bb_low[-2]
    if (
        low_band_prev is not None and r_prev is not None
        and closes[-2] < low_band_prev and price > closes[-2] and r_prev < 30 and r > r_prev
    ):
        markers.append(Marker("oversold_bounce", "rebond après survente marquée (bande de Bollinger)", 22, primary=True))

    if not markers:
        return nothing("aucune configuration déclenchante")

    # ── Confirmations et pénalités ───────────────────────────────────────────
    confirmations = 0

    if trend_up:
        markers.append(Marker("trend_up", "tendance de fond haussière (EMA50 > EMA200)", 10))
        confirmations += 1
    else:
        markers.append(Marker("trend_down", "tendance de fond baissière", -16))

    if 45 <= r <= 68:
        markers.append(Marker("rsi_healthy", f"RSI sain ({r:.0f})", 8))
        confirmations += 1
    elif r > 75:
        markers.append(Marker("rsi_overbought", f"RSI en surachat ({r:.0f})", -14))

    hist_now, hist_prev = macd_hist[-1], macd_hist[-2]
    if hist_now is not None and hist_prev is not None and hist_now > hist_prev > 0:
        markers.append(Marker("momentum", "momentum MACD en expansion", 8))
        confirmations += 1

    if v_avg and volumes[-1] > v_avg * 1.5:
        markers.append(Marker("volume", "volume supérieur à 1,5× la moyenne", 8))
        confirmations += 1
    elif v_avg and volumes[-1] < v_avg * 0.6:
        markers.append(Marker("low_volume", "volume anémique", -10))

    slope = None
    if ema50[-6] not in (None, 0):
        slope = (e50 / ema50[-6] - 1) * 100
        if slope > 0.5:
            markers.append(Marker("ema_rising", "EMA50 orientée à la hausse", 6))
            confirmations += 1
        elif slope < -0.5:
            markers.append(Marker("ema_falling", "EMA50 orientée à la baisse", -8))

    ceiling = highest(closes, 50, len(closes) - 2)
    if ceiling and price < ceiling and (ceiling - price) / a < 1.0:
        markers.append(Marker("resistance", "résistance 50 bougies juste au-dessus", -12))

    floor = lowest(closes, 50, len(closes) - 2)
    if floor and (price - floor) / a < 2.0:
        markers.append(Marker("support", "support 50 bougies à portée sous le prix", 6))

    reading = Reading(symbol, price, trend_label, r, atr_pct, markers, None)

    # Un déclencheur seul ne suffit pas : il faut au moins deux confirmations.
    if confirmations < 2:
        reading.reason = "déclencheur isolé, pas assez de confirmations"
        return reading

    conviction = max(0, min(100, 35 + sum(m.score for m in markers)))

    # ── Stop et objectif dérivés de la volatilité réelle (ATR) ───────────────
    stop_pct = max(1.5, min(1.5 * atr_pct, 12.0))
    best_primary = max(m.score for m in markers if m.primary)
    r_multiple = 2.5 if best_primary >= 24 else 2.0
    target_pct = min(stop_pct * r_multiple, 30.0)

    reading.signal = TechnicalSignal(
        symbol=symbol,
        price=price,
        conviction=conviction,
        stop_pct=round(stop_pct, 2),
        target_pct=round(target_pct, 2),
        markers=markers,
        context={
            "timeframe": timeframe,
            "rsi": round(r, 1),
            "atr_pct": round(atr_pct, 2),
            "trend": trend_label,
            "confirmations": confirmations,
            "r_multiple": r_multiple,
        },
    )
    return reading


def analyze(symbol: str, candles: list[Candle], timeframe: str = "4h") -> TechnicalSignal | None:
    """Raccourci : renvoie directement le signal, ou None."""
    reading = read(symbol, candles, timeframe)
    return reading.signal if reading else None
