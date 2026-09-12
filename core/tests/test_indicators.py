"""Les indicateurs sont le socle : une erreur ici fausse toutes les décisions."""
import math

from app.analysis.indicators import (
    Candle,
    atr,
    bollinger,
    ema,
    highest,
    lowest,
    macd,
    rsi,
    sma,
    true_range,
)


def test_sma_valeurs_connues():
    out = sma([1, 2, 3, 4, 5], 3)
    assert out[:2] == [None, None]
    assert out[2:] == [2.0, 3.0, 4.0]


def test_sma_historique_insuffisant():
    assert sma([1, 2], 5) == [None, None]


def test_ema_amorcee_par_sma_et_converge():
    values = [10.0] * 30
    out = ema(values, 10)
    assert out[9] == 10.0
    assert out[-1] == 10.0  # série plate → EMA plate


def test_ema_egale_sma_sur_une_droite():
    # Propriété connue : sur une progression parfaitement linéaire, EMA et SMA
    # coïncident. C'est un bon contrôle de l'amorçage de l'EMA.
    values = [float(i) for i in range(1, 41)]
    assert math.isclose(ema(values, 10)[-1], sma(values, 10)[-1], rel_tol=1e-9)


def test_ema_plus_reactive_quand_la_hausse_accelere():
    values = [float(i * i) for i in range(1, 41)]
    assert ema(values, 10)[-1] > sma(values, 10)[-1]


def test_rsi_100_si_que_des_hausses():
    values = [float(i) for i in range(1, 30)]
    assert rsi(values, 14)[-1] == 100.0


def test_rsi_proche_de_zero_si_que_des_baisses():
    values = [float(i) for i in range(40, 10, -1)]
    assert rsi(values, 14)[-1] < 1.0


def test_rsi_autour_de_50_en_dents_de_scie():
    values = [10.0, 11.0] * 20
    r = rsi(values, 14)[-1]
    assert 40 < r < 60


def test_macd_croise_a_la_hausse_sur_retournement():
    values = [float(50 - i) for i in range(40)] + [float(10 + i * 2) for i in range(30)]
    line, signal, hist = macd(values)
    assert line[-1] > signal[-1]   # après un fort retournement haussier
    assert hist[-1] > 0


def test_true_range_prend_le_gap_en_compte():
    candles = [
        Candle(0, 10, 11, 9, 10, 1),
        Candle(1, 20, 21, 19, 20, 1),   # gap haussier : TR = 21 - 10 = 11
    ]
    assert true_range(candles)[1] == 11


def test_atr_serie_reguliere():
    candles = [Candle(i, 10, 12, 8, 10, 1) for i in range(20)]
    assert math.isclose(atr(candles, 14)[-1], 4.0, rel_tol=1e-6)


def test_bollinger_bandes_encadrent_la_moyenne():
    values = [10.0, 12.0, 11.0, 13.0, 9.0] * 6
    low, mid, up = bollinger(values, 20, 2.0)
    assert low[-1] < mid[-1] < up[-1]


def test_bollinger_bandes_collees_si_serie_plate():
    low, mid, up = bollinger([5.0] * 25, 20, 2.0)
    assert low[-1] == mid[-1] == up[-1] == 5.0


def test_highest_lowest_fenetre():
    values = [1.0, 5.0, 3.0, 9.0, 2.0]
    assert highest(values, 3, 3) == 9.0
    assert lowest(values, 3, 3) == 3.0
    assert highest(values, 10, 3) is None  # fenêtre plus longue que l'historique
