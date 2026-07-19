"""Portefeuille : état, exécution des signaux, suivi des positions, P&L.

Stratégie volontairement simple et robuste : positions longues uniquement.
Un signal "sell" clôture la position ouverte correspondante s'il y en a une,
sinon il est rejeté (pas de vente à découvert).
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import marketdata
from ..brokers.base import BrokerAdapter, BrokerError
from ..brokers.paper import PaperBroker
from ..config import get_settings
from ..db.models import (
    EquitySnapshot,
    RiskConfig,
    Signal,
    SignalStatus,
    Trade,
    TradeStatus,
    utcnow,
)
from ..risk.engine import PortfolioState, RiskDecision, RiskLimits, evaluate

log = logging.getLogger(__name__)


# ── Configuration de risque ──────────────────────────────────────────────────

def get_risk_config(db: Session) -> RiskConfig:
    cfg = db.get(RiskConfig, 1)
    if cfg is None:
        cfg = RiskConfig(id=1)
        db.add(cfg)
        db.commit()
    return cfg


def risk_limits(cfg: RiskConfig) -> RiskLimits:
    return RiskLimits(
        risk_per_trade_pct=cfg.risk_per_trade_pct,
        max_daily_loss_pct=cfg.max_daily_loss_pct,
        max_weekly_loss_pct=cfg.max_weekly_loss_pct,
        max_positions=cfg.max_positions,
        max_exposure_per_asset_pct=cfg.max_exposure_per_asset_pct,
        min_conviction=cfg.min_conviction,
        kill_switch=cfg.kill_switch,
    )


# ── État du portefeuille ─────────────────────────────────────────────────────

def realized_pnl_since(db: Session, since: datetime) -> float:
    return float(
        db.scalar(
            select(func.coalesce(func.sum(Trade.pnl), 0.0)).where(
                Trade.status == TradeStatus.closed, Trade.closed_at >= since
            )
        )
        or 0.0
    )


def get_state(db: Session, with_market_prices: bool = False) -> PortfolioState:
    start_capital = get_settings().start_capital
    realized = float(
        db.scalar(select(func.coalesce(func.sum(Trade.pnl), 0.0)).where(Trade.status == TradeStatus.closed))
        or 0.0
    )
    open_trades = db.scalars(select(Trade).where(Trade.status == TradeStatus.open)).all()

    invested = sum(t.qty * t.entry_price for t in open_trades)
    cash = start_capital + realized - invested

    open_value = 0.0
    exposure: dict[str, float] = {}
    for t in open_trades:
        price = None
        if with_market_prices:
            price = marketdata.get_price(t.symbol, t.asset_class.value)
        value = t.qty * (price or t.entry_price)
        open_value += value
        exposure[t.symbol] = exposure.get(t.symbol, 0.0) + value

    now = utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())

    return PortfolioState(
        equity=round(cash + open_value, 2),
        cash=round(cash, 2),
        open_positions=len(open_trades),
        exposure_by_asset=exposure,
        daily_pnl=realized_pnl_since(db, day_start),
        weekly_pnl=realized_pnl_since(db, week_start),
    )


def snapshot_equity(db: Session) -> None:
    state = get_state(db, with_market_prices=True)
    db.add(EquitySnapshot(equity=state.equity, cash=state.cash))
    db.commit()


# ── Choix du courtier ────────────────────────────────────────────────────────

def broker_for(asset_class: str, cfg: RiskConfig) -> BrokerAdapter:
    """Paper par défaut ; réel seulement si le flag live du broker est activé."""
    if asset_class == "crypto" and cfg.live_kraken:
        from ..brokers.kraken import KrakenBroker

        return KrakenBroker()
    if asset_class in ("stock", "etf") and cfg.live_trading212:
        from ..brokers.trading212 import Trading212Broker

        return Trading212Broker()
    return PaperBroker()


# ── Exécution d'un signal ────────────────────────────────────────────────────

def execute_signal(db: Session, signal: Signal) -> Trade | None:
    """Chaîne complète : prix → moteur de risque → ordre → trade → notification."""
    from ..notify.push import notify_trade_opened

    cfg = get_risk_config(db)

    def reject(reason: str) -> None:
        signal.status = SignalStatus.rejected
        signal.status_reason = reason
        db.commit()
        log.info("Signal %s %s rejeté: %s", signal.direction, signal.asset, reason)

    price = marketdata.get_price(signal.asset, signal.asset_class.value)
    if not price:
        reject("prix de marché indisponible")
        return None

    # Un signal "sell" clôture une position existante, sinon rien (long only)
    if signal.direction == "sell":
        open_trade = db.scalar(
            select(Trade).where(Trade.symbol == signal.asset, Trade.status == TradeStatus.open)
        )
        if open_trade is None:
            reject("pas de position à vendre (vente à découvert non supportée)")
            return None
        trade = close_trade(db, open_trade, price, reason="signal")
        signal.status = SignalStatus.executed
        db.commit()
        return trade

    stop = price * (1 - signal.stop_pct / 100)
    target = price * (1 + signal.target_pct / 100)

    state = get_state(db)
    decision: RiskDecision = evaluate(
        asset=signal.asset,
        conviction=signal.conviction,
        entry=price,
        stop=stop,
        state=state,
        limits=risk_limits(cfg),
    )
    if not decision.approved:
        reject(f"risque: {decision.reason}")
        return None

    broker = broker_for(signal.asset_class.value, cfg)
    try:
        fill = broker.buy(signal.asset, decision.qty, price)
    except BrokerError as exc:
        reject(f"courtier: {exc}")
        return None

    trade = Trade(
        signal_id=signal.id,
        broker=fill.broker,
        is_paper=fill.is_paper,
        symbol=signal.asset,
        asset_class=signal.asset_class,
        side="buy",
        qty=fill.qty,
        entry_price=fill.price,
        stop_price=round(stop, 8),
        target_price=round(target, 8),
        rationale=signal.rationale,
    )
    db.add(trade)
    signal.status = SignalStatus.executed
    db.commit()
    db.refresh(trade)

    log.info("Trade ouvert: %s %s x%.6f @ %.4f (%s)", trade.side, trade.symbol, trade.qty, trade.entry_price, fill.broker)
    notify_trade_opened(db, trade)
    _broadcast("trade_opened", trade)
    return trade


def _broadcast(event: str, trade: Trade) -> None:
    from ..ws import manager

    manager.broadcast_sync(
        {
            "type": event,
            "trade": {
                "id": trade.id,
                "symbol": trade.symbol,
                "side": trade.side,
                "qty": trade.qty,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "pnl": trade.pnl,
                "pnl_pct": trade.pnl_pct,
                "status": trade.status.value,
                "is_paper": trade.is_paper,
            },
        }
    )


# ── Clôture & monitoring ─────────────────────────────────────────────────────

def close_trade(db: Session, trade: Trade, price: float, reason: str) -> Trade:
    from ..notify.push import notify_trade_closed

    cfg = get_risk_config(db)
    broker = broker_for(trade.asset_class.value, cfg)
    # Un trade réel doit être clôturé par un courtier réel, un paper par le paper
    if broker.is_paper != trade.is_paper:
        broker = PaperBroker() if trade.is_paper else broker

    try:
        fill = broker.sell(trade.symbol, trade.qty, price)
    except BrokerError as exc:
        log.error("Échec clôture %s: %s", trade.symbol, exc)
        return trade

    trade.exit_price = fill.price
    trade.closed_at = utcnow()
    trade.status = TradeStatus.closed
    trade.close_reason = reason
    trade.pnl = round((fill.price - trade.entry_price) * trade.qty, 2)
    trade.pnl_pct = round((fill.price / trade.entry_price - 1) * 100, 2)
    db.commit()

    log.info("Trade clôturé: %s @ %.4f → P&L %.2f (%s)", trade.symbol, fill.price, trade.pnl, reason)
    notify_trade_closed(db, trade)
    _broadcast("trade_closed", trade)
    return trade


def monitor_positions(db: Session) -> int:
    """Vérifie stops et objectifs des positions ouvertes. Renvoie le nb de clôtures."""
    open_trades = db.scalars(select(Trade).where(Trade.status == TradeStatus.open)).all()
    closed = 0
    for trade in open_trades:
        price = marketdata.get_price(trade.symbol, trade.asset_class.value)
        if not price:
            continue
        if price <= trade.stop_price:
            close_trade(db, trade, price, reason="stop")
            closed += 1
        elif price >= trade.target_price:
            close_trade(db, trade, price, reason="target")
            closed += 1
    return closed


def expire_stale_signals(db: Session) -> int:
    """Marque expirés les signaux proposés jamais exécutés (TTL)."""
    ttl = get_settings().signal_ttl_min
    cutoff = utcnow() - timedelta(minutes=ttl)
    stale = db.scalars(
        select(Signal).where(Signal.status == SignalStatus.proposed, Signal.created_at < cutoff)
    ).all()
    for s in stale:
        s.status = SignalStatus.expired
        s.status_reason = f"non exécuté sous {ttl} min"
    if stale:
        db.commit()
    return len(stale)
