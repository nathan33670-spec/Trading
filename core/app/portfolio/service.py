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
from ..brokers.fees import schedule_for
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
        max_invested_pct=cfg.max_invested_pct,
        envelope_pct={
            "crypto": cfg.envelope_crypto_pct,
            "stock": cfg.envelope_stock_pct,
            "etf": cfg.envelope_stock_pct,
        },
        min_target_fee_ratio=cfg.min_target_fee_ratio,
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

    # Le coût d'entrée inclut la commission : elle a bien quitté le cash.
    cost = sum(t.qty * t.entry_price + (t.entry_fee or 0.0) for t in open_trades)
    cash = start_capital + realized - cost

    open_value = 0.0
    exposure: dict[str, float] = {}
    by_class: dict[str, float] = {}
    for t in open_trades:
        price = None
        if with_market_prices:
            price = marketdata.get_price(t.symbol, t.asset_class.value)
        value = t.qty * (price or t.entry_price)
        open_value += value
        exposure[t.symbol] = exposure.get(t.symbol, 0.0) + value
        key = t.asset_class.value
        by_class[key] = by_class.get(key, 0.0) + value

    now = utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())

    return PortfolioState(
        equity=round(cash + open_value, 2),
        cash=round(cash, 2),
        open_positions=len(open_trades),
        exposure_by_asset=exposure,
        exposure_by_class=by_class,
        invested=round(open_value, 2),
        daily_pnl=realized_pnl_since(db, day_start),
        weekly_pnl=realized_pnl_since(db, week_start),
    )


def snapshot_equity(db: Session) -> None:
    state = get_state(db, with_market_prices=True)
    db.add(EquitySnapshot(equity=state.equity, cash=state.cash))
    db.commit()


# ── Choix du courtier ────────────────────────────────────────────────────────

def broker_for(asset_class: str, cfg: RiskConfig) -> BrokerAdapter:
    """Paper par défaut ; réel seulement si le flag live du broker est activé.

    Le courtier simulé applique le même barème de frais que le réel, sinon le
    paper trading donne une image trompeuse des performances.
    """
    if asset_class == "crypto" and cfg.live_kraken:
        from ..brokers.kraken import KrakenBroker

        return KrakenBroker()
    if asset_class in ("stock", "etf") and cfg.live_trading212:
        from ..brokers.trading212 import Trading212Broker

        return Trading212Broker()
    return PaperBroker(fees=schedule_for(asset_class, cfg))


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
        asset_class=signal.asset_class.value,
        target=target,
        fees=schedule_for(signal.asset_class.value, cfg),
    )
    if not decision.approved:
        reject(f"risque: {decision.reason}")
        return None
    if decision.capped_by:
        log.info("Position %s réduite : %s", signal.asset, decision.capped_by)

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
        initial_stop=round(stop, 8),
        target_price=round(target, 8),
        entry_fee=fill.fee,
        highest_price=fill.price,
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


def open_allocation(db: Session, signal: Signal, share: float = 1.0) -> Trade | None:
    """Ouvre une position d'**allocation** (stratégie de régime).

    Différence essentielle avec `execute_signal` : la taille ne vient pas d'une
    distance au stop mais de l'enveloppe de la classe d'actif. Il n'y a pas
    d'objectif de prix — la sortie est décidée par le signal — et le stop est un
    simple garde-fou catastrophe.
    """
    from ..notify.push import notify_trade_opened

    cfg = get_risk_config(db)
    asset_class = signal.asset_class.value

    def reject(reason: str) -> None:
        signal.status = SignalStatus.rejected
        signal.status_reason = reason
        db.commit()
        log.info("Allocation %s refusée: %s", signal.asset, reason)

    if cfg.kill_switch:
        reject("kill-switch actif")
        return None

    price = marketdata.get_price(signal.asset, asset_class)
    if not price:
        reject("prix de marché indisponible")
        return None

    state = get_state(db)
    if state.equity <= 0:
        reject("capital épuisé")
        return None

    # Budget : la plus contraignante des deux enveloppes, moins ce qui est déjà engagé
    envelope_pct = cfg.envelope_crypto_pct if asset_class == "crypto" else cfg.envelope_stock_pct
    class_room = state.equity * envelope_pct / 100.0 - state.exposure_by_class.get(asset_class, 0.0)
    global_room = state.equity * cfg.max_invested_pct / 100.0 - state.invested
    budget = min(class_room * share, global_room, state.cash * 0.998)

    if budget <= 0:
        reject(f"enveloppe {asset_class} ou cash épuisés")
        return None
    if budget < state.equity * 0.01:
        reject("budget résiduel trop faible pour une allocation")
        return None

    fees = schedule_for(asset_class, cfg)
    qty = (budget - fees.fee_for(budget)) / price
    if qty <= 0:
        reject("taille de position invalide")
        return None

    broker = broker_for(asset_class, cfg)
    try:
        fill = broker.buy(signal.asset, qty, price)
    except BrokerError as exc:
        reject(f"courtier: {exc}")
        return None

    stop = fill.price * (1 - signal.stop_pct / 100)
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
        initial_stop=round(stop, 8),
        # Pas d'objectif : la sortie vient du signal. On place une valeur
        # inatteignable pour que le suivi par niveaux ne s'en mêle pas.
        target_price=round(fill.price * 1_000, 8),
        entry_fee=fill.fee,
        highest_price=fill.price,
        managed_by="signal",
        rationale=signal.rationale,
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)

    log.info(
        "Allocation ouverte: %s x%.8f @ %.4f (budget %.2f €, frais %.2f €)",
        trade.symbol, trade.qty, trade.entry_price, budget, fill.fee,
    )
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
    trade.exit_fee = fill.fee
    trade.closed_at = utcnow()
    trade.status = TradeStatus.closed
    trade.close_reason = reason

    # P&L NET : frais d'entrée et de sortie déduits (c'est ce qui reste en poche)
    gross = (fill.price - trade.entry_price) * trade.qty
    fees_total = (trade.entry_fee or 0.0) + (trade.exit_fee or 0.0)
    cost = trade.entry_price * trade.qty + (trade.entry_fee or 0.0)
    trade.pnl = round(gross - fees_total, 2)
    trade.pnl_pct = round(trade.pnl / cost * 100, 2) if cost > 0 else 0.0
    db.commit()

    log.info(
        "Trade clôturé: %s @ %.4f → P&L net %.2f (brut %.2f, frais %.2f, %s)",
        trade.symbol, fill.price, trade.pnl, gross, fees_total, reason,
    )
    notify_trade_closed(db, trade)
    _broadcast("trade_closed", trade)
    return trade


def update_trailing_stop(trade: Trade, price: float, cfg: RiskConfig) -> bool:
    """Remonte le stop quand la position gagne. Renvoie True si le stop a bougé.

    Deux temps :
      1. dès que le gain atteint `trail_activate_r` fois le risque initial, le
         stop passe au point mort **frais compris** — le trade ne peut plus perdre ;
      2. ensuite il suit le plus haut atteint, à `trail_distance_r` × R.
    """
    if not cfg.trailing_enabled or not trade.initial_stop:
        return False
    r = trade.entry_price - trade.initial_stop
    if r <= 0:
        return False

    moved = False
    if not trade.trail_active and price >= trade.entry_price + r * cfg.trail_activate_r:
        fees = schedule_for(trade.asset_class.value, cfg)
        cushion = fees.round_trip_pct(trade.entry_price * trade.qty) / 100.0
        breakeven = trade.entry_price * (1 + cushion)
        if breakeven > trade.stop_price:
            trade.stop_price = round(breakeven, 8)
            moved = True
        trade.trail_active = True
        log.info(
            "%s : +%.1fR atteint, stop remonté au point mort (%.4f)",
            trade.symbol, cfg.trail_activate_r, trade.stop_price,
        )

    if trade.trail_active:
        candidate = (trade.highest_price or price) - r * cfg.trail_distance_r
        if candidate > trade.stop_price:
            trade.stop_price = round(candidate, 8)
            moved = True
    return moved


def monitor_positions(db: Session) -> int:
    """Stops, objectifs et stops suiveurs des positions ouvertes.

    Tourne toutes les minutes : c'est la partie la plus « vivante » du bot,
    elle gère les positions même quand aucune nouvelle opportunité n'apparaît.
    Renvoie le nombre de clôtures.
    """
    cfg = get_risk_config(db)
    open_trades = db.scalars(select(Trade).where(Trade.status == TradeStatus.open)).all()
    closed = 0
    dirty = False

    for trade in open_trades:
        price = marketdata.get_price(trade.symbol, trade.asset_class.value)
        if not price:
            continue

        if trade.highest_price is None or price > trade.highest_price:
            trade.highest_price = price
            dirty = True

        # Les positions d'allocation (stratégie de régime) ne sont pas pilotées
        # par des niveaux : leur sortie vient du signal. Seul le stop
        # catastrophe s'applique, pour couvrir un effondrement brutal.
        if trade.managed_by == "signal":
            if price <= trade.stop_price:
                db.commit()
                dirty = False
                close_trade(db, trade, price, reason="stop")
                closed += 1
            continue

        if update_trailing_stop(trade, price, cfg):
            dirty = True

        if price >= trade.target_price:
            db.commit()
            dirty = False
            close_trade(db, trade, price, reason="target")
            closed += 1
        elif price <= trade.stop_price:
            db.commit()
            dirty = False
            close_trade(db, trade, price, reason="trailing" if trade.trail_active else "stop")
            closed += 1

    if dirty:
        db.commit()
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
