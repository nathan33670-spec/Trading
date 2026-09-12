"""Frais : le paper trading doit payer exactement ce que paierait le réel."""
from app.brokers.fees import REVOLUT_STANDARD, FeeSchedule, schedule_for
from app.brokers.paper import PaperBroker


def test_revolut_standard_pourcentage():
    # 1,49 % de 1 000 € = 14,90 €
    assert REVOLUT_STANDARD.fee_for(1000) == 14.9


def test_revolut_plancher_sur_petits_montants():
    # 1,49 % de 20 € = 0,30 € → le plancher de 0,99 € s'applique
    assert REVOLUT_STANDARD.fee_for(20) == 0.99


def test_aller_retour_revolut_environ_3_pct():
    assert 2.9 < REVOLUT_STANDARD.round_trip_pct(1000) < 3.1


def test_aller_retour_ecrase_les_petites_positions():
    # Sur 30 €, le plancher rend l'aller-retour prohibitif (~6,6 %)
    assert REVOLUT_STANDARD.round_trip_pct(30) > 6


def test_montant_nul_sans_frais():
    assert REVOLUT_STANDARD.fee_for(0) == 0.0
    assert REVOLUT_STANDARD.round_trip_pct(0) == 0.0


def test_paper_broker_applique_les_frais():
    broker = PaperBroker(fees=REVOLUT_STANDARD)
    fill = broker.buy("BTC/EUR", qty=0.01, price_hint=100_000)
    assert fill.is_paper
    assert fill.price > 100_000            # slippage défavorable à l'achat
    assert fill.fee == REVOLUT_STANDARD.fee_for(fill.price * 0.01)


def test_paper_broker_slippage_defavorable_des_deux_cotes():
    broker = PaperBroker()
    assert broker.buy("X", 1, 100).price > 100
    assert broker.sell("X", 1, 100).price < 100


def test_paper_broker_sans_frais_par_defaut():
    assert PaperBroker().buy("X", 1, 100).fee == 0.0


class FakeCfg:
    fee_crypto_pct, fee_crypto_min = 1.49, 0.99
    fee_stock_pct, fee_stock_min = 0.15, 0.0


def test_schedule_choisit_le_bareme_selon_la_classe():
    assert schedule_for("crypto", FakeCfg()).pct == 1.49
    assert schedule_for("stock", FakeCfg()).pct == 0.15


def test_schedule_par_defaut_sans_config():
    assert schedule_for("crypto").name == "revolut_standard"


def test_bareme_personnalise():
    gratuit = FeeSchedule("test", pct=0.0, minimum=0.0)
    assert gratuit.fee_for(5000) == 0.0
