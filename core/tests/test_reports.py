from datetime import timedelta

from app.db.models import AssetClass, Trade, TradeStatus, utcnow
from app.reports.service import compute_stats


def closed_trade(symbol: str, pnl: float, days_ago: int):
    ts = utcnow() - timedelta(days=days_ago)
    return Trade(
        broker="paper",
        symbol=symbol,
        asset_class=AssetClass.crypto if "/" in symbol else AssetClass.stock,
        side="buy",
        qty=1,
        entry_price=100,
        stop_price=97,
        target_price=106,
        status=TradeStatus.closed,
        opened_at=ts,
        closed_at=ts,
        exit_price=100 + pnl,
        pnl=pnl,
        pnl_pct=pnl,
    )


def test_compute_stats(db):
    db.add_all([
        closed_trade("AAPL", +50, days_ago=2),
        closed_trade("BTC/EUR", -20, days_ago=3),
        closed_trade("MSFT", +10, days_ago=4),
        closed_trade("OLD", +999, days_ago=40),  # hors période
    ])
    db.commit()

    end = utcnow()
    start = end - timedelta(days=7)
    stats = compute_stats(db, start, end)

    assert stats["trades"] == 3
    assert stats["wins"] == 2
    assert stats["losses"] == 1
    assert stats["pnl"] == 40.0
    assert stats["best_trade"]["symbol"] == "AAPL"
    assert stats["worst_trade"]["symbol"] == "BTC/EUR"
    assert stats["pnl_by_class"] == {"stock": 60.0, "crypto": -20.0}


def test_compute_stats_empty(db):
    end = utcnow()
    stats = compute_stats(db, end - timedelta(days=7), end)
    assert stats["trades"] == 0
    assert stats["win_rate"] == 0.0
