"""Scanner : cooldown, positions ouvertes, et traçabilité dans l'onglet Marché."""
import pytest

from app.analysis import scanner
from app.db.models import (
    AssetClass,
    MarketState,
    RiskConfig,
    Signal,
    SignalStatus,
    Trade,
    TradeStatus,
)

from test_technical import candles_from, market, with_event


@pytest.fixture
def cfg(db):
    c = RiskConfig(id=1, tech_enabled=True, tech_min_conviction=50, crypto_watchlist=["BTC/EUR"])
    db.add(c)
    db.commit()
    return c


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    """Le scanner est testé seul : l'exécution a ses propres tests."""
    monkeypatch.setattr(scanner, "execute_signal", lambda db, signal: None)


def feed(monkeypatch, candles):
    monkeypatch.setattr(scanner.marketdata, "crypto_ohlc", lambda symbol, interval_min: candles)


def haussier():
    """Cassure sur la dernière bougie close (+ une bougie en formation)."""
    return with_event(market(), pct=3.0, volume=300.0)


def test_desactive_ne_fait_rien(db, cfg, monkeypatch):
    cfg.tech_enabled = False
    db.commit()
    assert scanner.scan(db) == []


def test_kill_switch_bloque_le_scan(db, cfg, monkeypatch):
    cfg.kill_switch = True
    db.commit()
    assert scanner.scan(db) == []


def test_signal_cree_et_etat_marche_renseigne(db, cfg, monkeypatch):
    feed(monkeypatch, haussier())
    created = scanner.scan(db)
    assert len(created) == 1
    assert created[0].source == "technical"
    assert created[0].markers  # les marqueurs sont tracés

    state = db.query(MarketState).filter_by(symbol="BTC/EUR").one()
    assert state.price > 0
    assert state.decision


def test_conviction_insuffisante_rejette_mais_trace(db, cfg, monkeypatch):
    """Une configuration faible est enregistrée puis rejetée, pas ignorée :
    elle doit rester visible dans l'onglet Signaux avec son motif."""
    candles = haussier()
    reading = scanner.technical.read("BTC/EUR", candles)
    reading.signal.conviction = 40           # configuration volontairement faible
    monkeypatch.setattr(scanner.technical, "read", lambda *a, **k: reading)
    feed(monkeypatch, candles)

    cfg.tech_min_conviction = 70
    db.commit()
    created = scanner.scan(db)

    assert created and created[0].status == SignalStatus.rejected
    assert "conviction" in created[0].status_reason
    state = db.query(MarketState).filter_by(symbol="BTC/EUR").one()
    assert "conviction" in state.decision


def test_position_ouverte_bloque_la_paire(db, cfg, monkeypatch):
    db.add(Trade(broker="paper", symbol="BTC/EUR", asset_class=AssetClass.crypto, side="buy",
                 qty=1, entry_price=100, stop_price=90, target_price=120,
                 status=TradeStatus.open))
    db.commit()
    feed(monkeypatch, haussier())
    assert scanner.scan(db) == []
    state = db.query(MarketState).filter_by(symbol="BTC/EUR").one()
    assert "déjà ouverte" in state.decision


def test_cooldown_empeche_le_sur_trading(db, cfg, monkeypatch):
    feed(monkeypatch, haussier())
    assert len(scanner.scan(db)) == 1
    # Deuxième passage immédiat : rien, la paire est en période de repos
    assert scanner.scan(db) == []
    state = db.query(MarketState).filter_by(symbol="BTC/EUR").one()
    assert "récent" in state.decision


def test_bougies_indisponibles_sont_tracees(db, cfg, monkeypatch):
    feed(monkeypatch, [])
    assert scanner.scan(db) == []
    state = db.query(MarketState).filter_by(symbol="BTC/EUR").one()
    assert "indisponibles" in state.decision


def test_absence_de_configuration_est_expliquee(db, cfg, monkeypatch):
    # marché plat : aucune configuration, mais la raison doit être visible
    feed(monkeypatch, candles_from([100.0] * 260, wick=0.0))
    assert scanner.scan(db) == []
    state = db.query(MarketState).filter_by(symbol="BTC/EUR").one()
    assert state.decision


def test_watchlist_par_defaut_si_vide(db, cfg):
    cfg.crypto_watchlist = []
    assert scanner.watchlist(cfg) == scanner.DEFAULT_WATCHLIST


def test_watchlist_normalisee(db, cfg):
    cfg.crypto_watchlist = [" btc/eur ", "eth/eur"]
    assert scanner.watchlist(cfg) == ["BTC/EUR", "ETH/EUR"]
