"""Stratégie de régime : signal momentum 12 mois et son backtest."""
import pytest

from app.analysis.indicators import Candle
from app.analysis.regime import backtest, evaluate_regime
from app.brokers.fees import REVOLUT_STANDARD, FeeSchedule

GRATUIT = FeeSchedule("sans frais", 0.0, 0.0)
DAY = 86400


def candles(closes: list[float]) -> list[Candle]:
    return [
        Candle(ts=i * DAY, open=c, high=c * 1.01, low=c * 0.99, close=c, volume=100.0)
        for i, c in enumerate(closes)
    ]


def hausse(n=500, start=100.0, step=0.5):
    return [start + i * step for i in range(n)]


def baisse(n=500, start=400.0, step=0.5):
    return [max(start - i * step, 1.0) for i in range(n)]


# ── Signal ───────────────────────────────────────────────────────────────────

def test_historique_trop_court():
    assert evaluate_regime("BTC/EUR", candles(hausse(100))) is None


def test_hausse_sur_12_mois_investi():
    r = evaluate_regime("BTC/EUR", candles(hausse()))
    assert r.invested is True
    assert r.momentum_pct > 0
    assert "haussière" in r.reason


def test_baisse_sur_12_mois_hors_marche():
    r = evaluate_regime("BTC/EUR", candles(baisse()))
    assert r.invested is False
    assert r.momentum_pct < 0
    assert "baissière" in r.reason


def test_momentum_calcule_sur_la_bonne_reference():
    closes = hausse()
    r = evaluate_regime("BTC/EUR", candles(closes), momentum_days=365)
    assert r.reference_price == pytest.approx(closes[-366])
    attendu = (closes[-1] / closes[-366] - 1) * 100
    assert r.momentum_pct == pytest.approx(attendu, abs=0.01)


def test_confirmation_sma_peut_bloquer_une_entree():
    # Hausse longue puis décrochage récent : momentum encore positif,
    # mais le prix repasse sous sa moyenne mobile courte.
    closes = hausse(500) + [300.0] * 20   # décrochage sous la SMA50 (~345)
    sans = evaluate_regime("BTC/EUR", candles(closes), confirm_sma=0)
    avec = evaluate_regime("BTC/EUR", candles(closes), confirm_sma=50)
    assert sans.invested is True
    assert avec.invested is False
    assert avec.above_sma is False


def test_marqueurs_lisibles():
    r = evaluate_regime("BTC/EUR", candles(hausse()))
    assert r.markers and r.markers[0]["primary"] is True
    assert "12 mois" in r.markers[0]["label"]


# ── Backtest ─────────────────────────────────────────────────────────────────

def test_backtest_historique_insuffisant():
    assert backtest("BTC/EUR", candles(hausse(200)), GRATUIT) is None


def test_hausse_continue_suit_le_marche():
    r = backtest("BTC/EUR", candles(hausse(900)), GRATUIT, start_equity=10_000)
    assert r.equity > 10_000
    assert r.trades >= 1
    assert r.exposure > 0.9          # investi quasiment tout du long


def test_baisse_continue_protege_le_capital():
    r = backtest("BTC/EUR", candles(baisse(900, start=800.0)), GRATUIT, start_equity=10_000)
    # Jamais investi : le capital est intact, et bien meilleur que l'achat-conservation
    assert r.equity == pytest.approx(10_000, abs=1)
    assert r.equity > r.buy_hold_equity
    assert r.exposure == 0.0


def test_les_frais_reduisent_le_resultat():
    serie = candles(hausse(900))
    sans = backtest("BTC/EUR", serie, GRATUIT, start_equity=10_000)
    avec = backtest("BTC/EUR", serie, REVOLUT_STANDARD, start_equity=10_000)
    assert avec.fees > 0
    assert avec.equity < sans.equity


def test_controle_hebdomadaire_reduit_les_mouvements():
    """Le va-et-vient autour du seuil coûte cher : contrôler moins souvent
    doit produire moins d'allers-retours."""
    oscillant = []
    for cycle in range(40):
        base = 100.0 + (10 if cycle % 2 else -10)
        oscillant += [base + (1 if j % 2 else -1) for j in range(25)]
    serie = candles(oscillant)
    quotidien = backtest("BTC/EUR", serie, GRATUIT, momentum_days=200, check_every_days=1)
    hebdo = backtest("BTC/EUR", serie, GRATUIT, momentum_days=200, check_every_days=7)
    assert hebdo.trades <= quotidien.trades


def test_comparaison_achat_conservation_fournie():
    r = backtest("BTC/EUR", candles(hausse(900)), GRATUIT)
    assert r.buy_hold_equity > 0
    assert r.buy_hold_cagr != 0
    s = r.summary()
    assert {"cagr", "max_drawdown", "buy_hold_cagr", "exposure"} <= set(s)


def test_drawdown_jamais_negatif():
    r = backtest("BTC/EUR", candles(hausse(900)), GRATUIT)
    assert r.max_drawdown >= 0
    assert r.buy_hold_drawdown >= 0
