"""Allocateur : du signal de régime aux positions réelles."""
import pytest

from app.analysis import allocator
from app.db.models import (
    AssetClass,
    MarketState,
    RiskConfig,
    Signal,
    SignalStatus,
    Trade,
    TradeStatus,
)

from test_regime import baisse, candles, hausse


@pytest.fixture
def cfg(db):
    c = RiskConfig(id=1, strategy="regime", regime_assets=["BTC/EUR"],
                   envelope_crypto_pct=30.0, max_invested_pct=60.0,
                   fee_crypto_pct=1.49, fee_crypto_min=0.99, regime_check_days=7)
    db.add(c)
    db.commit()
    return c


@pytest.fixture(autouse=True)
def marche(monkeypatch):
    """Marché simulé : prix courant fixe, historique paramétrable."""
    etat = {"closes": hausse()}
    monkeypatch.setattr(allocator.marketdata_history, "history",
                        lambda symbol, **kw: candles(etat["closes"]))
    monkeypatch.setattr(allocator.marketdata, "get_price",
                        lambda symbol, asset_class: etat["closes"][-1])
    import app.portfolio.service as service
    monkeypatch.setattr(service.marketdata, "get_price",
                        lambda symbol, asset_class: etat["closes"][-1])
    monkeypatch.setattr(service, "notify_trade_opened", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(service, "_broadcast", lambda *a, **k: None)
    return etat


def test_tendance_haussiere_ouvre_une_position(db, cfg, marche):
    actions = allocator.run(db, force=True)
    assert actions and "entrée" in actions[0]

    trade = db.query(Trade).one()
    assert trade.managed_by == "signal"        # sortie pilotée par le signal
    assert trade.symbol == "BTC/EUR"
    assert trade.entry_fee > 0
    # La taille vient de l'enveloppe crypto (30 % de 10 000 €), pas d'un stop
    assert 2_800 < trade.qty * trade.entry_price < 3_100


def test_objectif_inatteignable_et_stop_lointain(db, cfg, marche):
    allocator.run(db, force=True)
    t = db.query(Trade).one()
    assert t.target_price > t.entry_price * 100      # jamais déclenché
    assert t.stop_price < t.entry_price * 0.6        # garde-fou catastrophe


def test_tendance_baissiere_reste_en_cash(db, cfg, marche):
    marche["closes"] = baisse()
    assert allocator.run(db, force=True) == []
    assert db.query(Trade).count() == 0
    state = db.query(MarketState).filter_by(symbol="BTC/EUR").one()
    assert "baissière" in state.decision


def test_retournement_du_signal_ferme_la_position(db, cfg, marche):
    allocator.run(db, force=True)
    assert db.query(Trade).one().status == TradeStatus.open

    marche["closes"] = baisse()
    actions = allocator.run(db, force=True)
    assert actions and "sortie" in actions[0]
    t = db.query(Trade).one()
    assert t.status == TradeStatus.closed
    assert t.close_reason == "signal"


def test_position_conservee_tant_que_la_tendance_tient(db, cfg, marche):
    allocator.run(db, force=True)
    allocator.run(db, force=True)
    assert db.query(Trade).count() == 1        # pas de rachat par-dessus
    state = db.query(MarketState).filter_by(symbol="BTC/EUR").one()
    assert "conservée" in state.decision


def test_kill_switch_empeche_l_entree(db, cfg, marche):
    cfg.kill_switch = True
    db.commit()
    assert allocator.run(db, force=True) == []
    assert db.query(Trade).count() == 0
    state = db.query(MarketState).filter_by(symbol="BTC/EUR").one()
    assert "kill-switch" in state.decision


def test_enveloppe_crypto_nulle_refuse_l_entree(db, cfg, marche):
    cfg.envelope_crypto_pct = 0.0
    db.commit()
    assert allocator.run(db, force=True) == []
    signal = db.query(Signal).one()
    assert signal.status == SignalStatus.rejected


def test_frequence_de_verification_respectee(db, cfg, marche):
    allocator.run(db, force=True)
    # Sans force, la vérification hebdomadaire empêche un second passage
    marche["closes"] = baisse()
    assert allocator.run(db) == []
    assert db.query(Trade).one().status == TradeStatus.open


def test_strategie_inactive_ne_fait_rien(db, cfg, marche):
    cfg.strategy = "off"
    db.commit()
    assert allocator.run(db, force=True) == []
    assert db.query(Trade).count() == 0


def test_historique_insuffisant_est_trace(db, cfg, marche):
    marche["closes"] = hausse(100)
    assert allocator.run(db, force=True) == []
    state = db.query(MarketState).filter_by(symbol="BTC/EUR").one()
    assert "insuffisant" in state.decision


def test_actifs_par_defaut(db, cfg):
    cfg.regime_assets = []
    assert allocator.assets(cfg) == ["BTC/EUR"]


def test_positions_signal_ignorent_stop_suiveur(db, cfg, marche, monkeypatch):
    """Une position d'allocation ne doit pas être clôturée par un objectif :
    c'est ce qui plafonnait les gagnants dans la version précédente."""
    from app.portfolio.service import monitor_positions

    allocator.run(db, force=True)
    t = db.query(Trade).one()
    entry = t.entry_price

    import app.portfolio.service as service
    monkeypatch.setattr(service.marketdata, "get_price",
                        lambda symbol, asset_class: entry * 3)   # +200 %
    monitor_positions(db)

    t = db.query(Trade).one()
    assert t.status == TradeStatus.open        # on laisse courir
    assert t.stop_price == t.initial_stop      # aucun stop suiveur
