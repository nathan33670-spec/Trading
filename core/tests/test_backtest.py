"""Backtest : les hypothèses pessimistes doivent être respectées."""
from app.analysis.backtest import aggregate, run
from app.analysis.indicators import Candle
from app.brokers.fees import REVOLUT_STANDARD, FeeSchedule

from test_technical import candles_from, market

GRATUIT = FeeSchedule("sans frais", 0.0, 0.0)


def scenario(pct_after_entry: float) -> list[Candle]:
    """Marché haussier, cassure, puis mouvement dirigé pendant 60 bougies."""
    closes = market()
    closes = closes + [closes[-1] * 1.03]
    for _ in range(60):
        closes.append(closes[-1] * (1 + pct_after_entry / 100))
    return candles_from(closes, volume=300.0)


def test_historique_trop_court_aucun_trade():
    assert run("X/EUR", candles_from([100.0] * 50)).trades == []


def test_hausse_franche_declenche_et_gagne():
    result = run("BTC/EUR", scenario(+1.0), stake=1000, min_conviction=50, fees=GRATUIT)
    assert result.trades
    assert result.net > 0
    assert result.win_rate > 0


def test_baisse_franche_est_stoppee():
    result = run("BTC/EUR", scenario(-1.0), stake=1000, min_conviction=50, fees=GRATUIT)
    assert result.trades
    assert all(t.reason == "stop" for t in result.trades)
    assert result.net < 0


def volatile_scenario(pct_after_entry: float) -> list[Candle]:
    """Même chose, mais avec de larges mèches : l'ATR est élevé, donc les
    objectifs sont assez lointains pour franchir le garde-fou des frais."""
    closes = market()
    closes = closes + [closes[-1] * 1.03]
    for _ in range(60):
        closes.append(closes[-1] * (1 + pct_after_entry / 100))
    return candles_from(closes, volume=300.0, wick=0.04)


def test_frais_eliminent_les_objectifs_trop_courts():
    """Avec 1,49 % par transaction, une configuration à faible amplitude n'est
    tout simplement pas prise : c'est le garde-fou, pas un bug."""
    sans = run("BTC/EUR", scenario(+1.0), stake=1000, min_conviction=50, fees=GRATUIT)
    avec = run("BTC/EUR", scenario(+1.0), stake=1000, min_conviction=50, fees=REVOLUT_STANDARD)
    assert sans.trades          # sans frais, la configuration est jouable
    assert not avec.trades      # avec les frais Revolut, elle ne l'est plus


def test_les_frais_degradent_le_resultat():
    sans = run("BTC/EUR", volatile_scenario(+1.0), stake=1000, min_conviction=50, fees=GRATUIT)
    avec = run("BTC/EUR", volatile_scenario(+1.0), stake=1000, min_conviction=50, fees=REVOLUT_STANDARD)
    assert avec.trades, "le scénario volatil doit franchir le garde-fou des frais"
    assert avec.fees > 0
    assert avec.net < sans.net
    assert avec.gross == round(avec.net + avec.fees, 2)


def test_conviction_elevee_filtre_les_trades():
    peu = run("BTC/EUR", scenario(+1.0), min_conviction=50, fees=GRATUIT)
    beaucoup = run("BTC/EUR", scenario(+1.0), min_conviction=99, fees=GRATUIT)
    assert len(beaucoup.trades) <= len(peu.trades)


def test_resume_est_coherent():
    result = run("BTC/EUR", scenario(+1.0), stake=1000, min_conviction=50, fees=REVOLUT_STANDARD)
    s = result.summary()
    assert s["trades"] == len(result.trades)
    assert s["net"] == result.net
    assert s["gross"] == round(result.net + result.fees, 2)


def test_agregation_sur_plusieurs_paires():
    a = run("BTC/EUR", scenario(+1.0), min_conviction=50, fees=GRATUIT)
    b = run("ETH/EUR", scenario(-1.0), min_conviction=50, fees=GRATUIT)
    agg = aggregate([a, b])
    assert agg["symbols"] == 2
    assert agg["trades"] == len(a.trades) + len(b.trades)
    assert agg["net"] == round(a.net + b.net, 2)
    assert sum(agg["by_reason"].values()) == agg["trades"]


def test_agregation_vide_ne_plante_pas():
    agg = aggregate([])
    assert agg["trades"] == 0
    assert agg["win_rate"] == 0.0
