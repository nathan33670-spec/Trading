"""Détecteurs de configurations : ce qui doit déclencher, et surtout ce qui ne doit pas."""
import math

from app.analysis.indicators import Candle
from app.analysis.technical import MIN_CANDLES, read


def candles_from(closes: list[float], volume: float = 100.0, wick: float = 0.005) -> list[Candle]:
    return [
        Candle(ts=i * 3600, open=c, high=c * (1 + wick), low=c * (1 - wick), close=c, volume=volume)
        for i, c in enumerate(closes)
    ]


def market(trend_bars: int = MIN_CANDLES, plateau_bars: int = 25) -> list[float]:
    """Longue tendance haussière bruitée, puis un plateau (base de cassure)."""
    closes = [100.0 + i * 0.4 + (1.5 if i % 2 else -1.5) for i in range(trend_bars)]
    top = closes[-1]
    closes += [top + (0.3 if i % 2 else -0.3) for i in range(plateau_bars)]
    return closes


def with_event(closes: list[float], pct: float, volume: float = 300.0) -> list[Candle]:
    """Ajoute une bougie d'événement close, puis une bougie en formation (ignorée)."""
    cs = candles_from(closes)
    price = closes[-1] * (1 + pct / 100)
    cs.append(Candle(ts=900_000, open=closes[-1], high=price * 1.002,
                     low=closes[-1] * 0.999, close=price, volume=volume))
    cs.append(Candle(ts=900_100, open=price, high=price, low=price, close=price, volume=volume))
    return cs


def test_historique_insuffisant_renvoie_none():
    assert read("X/EUR", candles_from([100.0] * 50)) is None


def test_volatilite_nulle_aucun_signal():
    reading = read("X/EUR", candles_from([100.0] * (MIN_CANDLES + 10), wick=0.0))
    assert reading is None or reading.signal is None


def test_tendance_baissiere_jamais_d_achat():
    closes = [300.0 - i * 0.5 + (2 if i % 2 else -2) for i in range(MIN_CANDLES + 10)]
    reading = read("X/EUR", candles_from(closes))
    assert reading.signal is None
    assert "EMA200" in reading.reason


def test_prix_parabolique_est_ecarte():
    reading = read("X/EUR", with_event(market(), pct=30))
    assert reading.signal is None
    assert "étendu" in reading.reason


def test_derniere_bougie_en_formation_est_ignoree():
    closes = market()
    # Référence : toutes les bougies closes, aucune écartée
    reference = read("X/EUR", candles_from(closes), drop_forming=False)
    # Même série + une bougie en formation aberrante : elle doit être écartée
    avec_formation = read("X/EUR", candles_from(closes + [closes[-1] * 3]))
    assert avec_formation.price == reference.price
    assert avec_formation.rsi == reference.rsi


def test_cassure_avec_volume_declenche_un_signal():
    reading = read("BTC/EUR", with_event(market(), pct=3.0, volume=300.0))
    assert reading.signal is not None, reading.reason
    assert "breakout" in {m.code for m in reading.markers}
    assert reading.signal.conviction > 0
    assert 1.5 <= reading.signal.stop_pct <= 12.0


def test_cassure_sans_volume_ne_declenche_pas():
    reading = read("BTC/EUR", with_event(market(), pct=3.0, volume=50.0))
    codes = {m.code for m in reading.markers} if reading else set()
    assert "breakout" not in codes


def test_objectif_est_un_multiple_du_stop():
    sig = read("BTC/EUR", with_event(market(), pct=3.0)).signal
    assert sig is not None
    assert math.isclose(sig.target_pct / sig.stop_pct, sig.context["r_multiple"], rel_tol=0.01)


def test_cassure_ancienne_ne_redeclenche_pas():
    """Une cassure vieille de 10 bougies ne doit plus déclencher : on veut un
    événement, pas un état — sinon le même signal repart à chaque passage."""
    closes = market()
    price = closes[-1] * 1.03
    closes = closes + [price] + [price * (1 + 0.001 * (1 if i % 2 else -1)) for i in range(10)]
    reading = read("BTC/EUR", candles_from(closes))
    codes = {m.code for m in reading.markers} if reading else set()
    assert "breakout" not in codes


def test_marqueurs_exposent_leur_contribution():
    reading = read("BTC/EUR", with_event(market(), pct=3.0))
    assert reading.markers
    for m in reading.markers:
        assert m.label and isinstance(m.score, int)
    assert any(m.primary for m in reading.markers)


def test_deux_confirmations_minimum():
    reading = read("BTC/EUR", with_event(market(), pct=3.0))
    if reading.signal is not None:
        assert reading.signal.context["confirmations"] >= 2
