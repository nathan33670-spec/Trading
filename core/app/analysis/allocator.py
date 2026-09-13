"""Exécution de la stratégie de régime : passer du signal aux positions.

Contrairement au swing trading, il n'y a ni objectif ni stop serré : on est
investi tant que la tendance de fond est haussière, en cash sinon. La taille
de position n'est donc pas calculée sur une distance au stop mais sur
l'**enveloppe crypto** définie par l'utilisateur.
"""
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    AssetClass,
    MarketState,
    RiskConfig,
    Signal,
    SignalStatus,
    Trade,
    TradeStatus,
    utcnow,
)
from ..portfolio.service import close_trade, get_risk_config, open_allocation
from . import regime
from .. import marketdata, marketdata_history

log = logging.getLogger(__name__)


def assets(cfg: RiskConfig) -> list[str]:
    return [s.strip().upper() for s in (cfg.regime_assets or regime.DEFAULT_ASSETS) if s.strip()]


def _record(db: Session, symbol: str, reading, decision: str) -> None:
    state = db.scalar(select(MarketState).where(MarketState.symbol == symbol))
    if state is None:
        state = MarketState(symbol=symbol)
        db.add(state)
    if reading is not None:
        state.price = round(reading.price, 8)
        state.trend = "haussière" if reading.invested else "baissière"
        state.conviction = 100 if reading.invested else 0
        state.markers = reading.markers
    state.decision = decision
    state.updated_at = utcnow()
    db.commit()


def _checked_recently(db: Session, symbol: str, days: int) -> bool:
    """Le signal n'est consulté qu'une fois par période : le contrôler chaque
    jour double le nombre d'allers-retours sans améliorer le rendement."""
    if days <= 1:
        return False
    state = db.scalar(select(MarketState).where(MarketState.symbol == symbol))
    if state is None or state.updated_at is None:
        return False
    last = state.updated_at
    if last.tzinfo is None:
        from datetime import timezone

        last = last.replace(tzinfo=timezone.utc)
    return (utcnow() - last) < timedelta(days=days)


def _open_position(db: Session, symbol: str) -> Trade | None:
    return db.scalar(
        select(Trade).where(
            Trade.symbol == symbol,
            Trade.status == TradeStatus.open,
            Trade.managed_by == "signal",
        )
    )


def run(db: Session, force: bool = False) -> list[str]:
    """Applique la stratégie de régime. Renvoie la liste des actions effectuées."""
    cfg = get_risk_config(db)
    actions: list[str] = []
    if cfg.strategy != "regime":
        return actions

    symbols = assets(cfg)
    for symbol in symbols:
        held = _open_position(db, symbol)

        if not force and _checked_recently(db, symbol, cfg.regime_check_days):
            continue

        candles = marketdata_history.history(symbol)
        reading = regime.evaluate_regime(
            symbol, candles,
            momentum_days=cfg.momentum_days,
            confirm_sma=cfg.regime_confirm_sma,
        )
        if reading is None:
            _record(db, symbol, None, "historique insuffisant pour le signal 12 mois")
            continue

        # ── Sortie : la tendance de fond s'est retournée ─────────────────────
        if held and not reading.invested:
            price = marketdata.get_price(symbol, "crypto") or reading.price
            close_trade(db, held, price, reason="signal")
            _record(db, symbol, reading, f"sortie — {reading.reason}")
            actions.append(f"{symbol} : sortie ({reading.momentum_pct:+.1f} % sur 12 mois)")
            continue

        if held:
            _record(db, symbol, reading, f"position conservée — {reading.reason}")
            continue

        if not reading.invested:
            _record(db, symbol, reading, reading.reason)
            continue

        # ── Entrée : on engage la part d'enveloppe prévue pour cet actif ─────
        if cfg.kill_switch:
            _record(db, symbol, reading, "signal haussier mais kill-switch actif")
            continue

        signal = Signal(
            source="regime",
            markers=reading.markers,
            asset=symbol,
            asset_class=AssetClass.crypto,
            direction="buy",
            conviction=100,
            horizon="weeks",
            stop_pct=regime.CATASTROPHE_STOP_PCT,
            target_pct=0.0,
            rationale=(
                f"Stratégie de régime : {reading.reason}. Exposition maintenue tant que "
                f"la tendance de fond reste haussière ; sortie sur retournement du signal, "
                f"pas sur objectif de prix."
            ),
            llm_model="momentum 12 mois",
        )
        db.add(signal)
        db.commit()
        db.refresh(signal)

        trade = open_allocation(db, signal, share=1 / max(len(symbols), 1))
        if trade:
            signal.status = SignalStatus.executed
            db.commit()
            _record(db, symbol, reading, f"position ouverte ({trade.qty:g} @ {trade.entry_price:g})")
            actions.append(f"{symbol} : entrée à {trade.entry_price:g} €")
        else:
            _record(db, symbol, reading, f"entrée refusée — {signal.status_reason}")

    if actions:
        log.info("Stratégie de régime : %s", " ; ".join(actions))
    return actions
