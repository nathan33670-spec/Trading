"""Chaîne signal → risque → paper trade → monitoring → clôture, sans réseau."""
import pytest

from app.db.models import AssetClass, Signal, SignalStatus, Trade, TradeStatus
from app.portfolio import service


@pytest.fixture
def fixed_price(monkeypatch):
    prices = {"price": 100.0}
    monkeypatch.setattr(service.marketdata, "get_price", lambda s, c: prices["price"])
    return prices


def make_signal(db, **kw):
    defaults = dict(
        asset="AAPL",
        asset_class=AssetClass.stock,
        direction="buy",
        conviction=80,
        stop_pct=3.0,
        target_pct=6.0,
        rationale="test",
    )
    defaults.update(kw)
    s = Signal(**defaults)
    db.add(s)
    db.commit()
    return s


def test_buy_signal_opens_paper_trade(db, fixed_price):
    signal = make_signal(db)
    trade = service.execute_signal(db, signal)

    assert trade is not None
    assert trade.status == TradeStatus.open
    assert trade.broker == "paper"
    assert signal.status == SignalStatus.executed
    # sizing: 1% de risque donnerait ~33 unités, mais le plafond d'exposition
    # par actif (20% de 10 000 € = 2 000 €) limite à 20 unités
    assert 18 < trade.qty <= 20
    assert trade.stop_price < trade.entry_price < trade.target_price


def test_sell_without_position_rejected(db, fixed_price):
    signal = make_signal(db, direction="sell")
    trade = service.execute_signal(db, signal)
    assert trade is None
    assert signal.status == SignalStatus.rejected


def test_monitor_closes_on_target(db, fixed_price):
    service.execute_signal(db, make_signal(db))

    fixed_price["price"] = 100.0 * 1.07  # au-dessus de l'objectif (+6%)
    closed = service.monitor_positions(db)

    assert closed == 1
    trade = db.query(Trade).one()
    assert trade.status == TradeStatus.closed
    assert trade.close_reason == "target"
    assert trade.pnl > 0


def test_monitor_closes_on_stop_with_loss(db, fixed_price):
    service.execute_signal(db, make_signal(db))

    fixed_price["price"] = 100.0 * 0.95  # sous le stop (-3%)
    service.monitor_positions(db)

    trade = db.query(Trade).one()
    assert trade.status == TradeStatus.closed
    assert trade.close_reason == "stop"
    assert trade.pnl < 0
    # la perte reste de l'ordre du risque défini (1% de 10 000 € + slippage/gap)
    assert trade.pnl > -250


def test_sell_signal_closes_open_position(db, fixed_price):
    service.execute_signal(db, make_signal(db))
    fixed_price["price"] = 104.0

    sell = make_signal(db, direction="sell")
    trade = service.execute_signal(db, sell)

    assert trade is not None
    assert trade.status == TradeStatus.closed
    assert trade.close_reason == "signal"
    assert sell.status == SignalStatus.executed


def test_kill_switch_blocks_execution(db, fixed_price):
    cfg = service.get_risk_config(db)
    cfg.kill_switch = True
    db.commit()

    signal = make_signal(db)
    assert service.execute_signal(db, signal) is None
    assert signal.status == SignalStatus.rejected
    assert "kill-switch" in signal.status_reason


def test_cash_never_goes_negative(db, fixed_price):
    cfg = service.get_risk_config(db)
    cfg.max_positions = 20
    cfg.max_exposure_per_asset_pct = 100.0
    cfg.risk_per_trade_pct = 5.0
    db.commit()

    for i in range(10):
        make_signal(db, asset=f"SYM{i}", stop_pct=1.0)
    for s in db.query(Signal).all():
        service.execute_signal(db, s)

    state = service.get_state(db)
    assert state.cash >= -0.01
