"""Scanner technique : la boucle qui fait vivre le bot sans dépendre de l'actualité.

Toutes les N minutes, chaque paire de la watchlist est passée au crible des
détecteurs de `technical.py`. Une configuration suffisamment confirmée devient
un signal, soumis — comme tout signal — au moteur de risque avant exécution.

Ne nécessite **aucune clé API** : les bougies viennent de l'API publique Kraken.
"""
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import marketdata
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
from ..portfolio.service import execute_signal, get_risk_config
from . import technical

log = logging.getLogger(__name__)

# Paires EUR les plus liquides de Kraken — liquidité = stops qui tiennent.
DEFAULT_WATCHLIST = [
    "BTC/EUR", "ETH/EUR", "SOL/EUR", "XRP/EUR", "ADA/EUR",
    "DOT/EUR", "LINK/EUR", "AVAX/EUR", "LTC/EUR", "ATOM/EUR",
]

# Délai minimum entre deux signaux sur la même paire (évite le sur-trading)
COOLDOWN_MIN = 12 * 60


def watchlist(cfg: RiskConfig) -> list[str]:
    return [s.strip().upper() for s in (cfg.crypto_watchlist or DEFAULT_WATCHLIST) if s.strip()]


def _recently_signalled(db: Session, symbol: str) -> bool:
    cutoff = utcnow() - timedelta(minutes=COOLDOWN_MIN)
    return db.scalar(
        select(Signal.id)
        .where(Signal.asset == symbol, Signal.source == "technical", Signal.created_at >= cutoff)
        .limit(1)
    ) is not None


def _has_open_position(db: Session, symbol: str) -> bool:
    return db.scalar(
        select(Trade.id).where(Trade.symbol == symbol, Trade.status == TradeStatus.open).limit(1)
    ) is not None


def _record(db: Session, symbol: str, reading, decision: str) -> None:
    """Mémorise la dernière lecture d'une paire pour l'onglet Marché."""
    state = db.scalar(select(MarketState).where(MarketState.symbol == symbol))
    if state is None:
        state = MarketState(symbol=symbol)
        db.add(state)
    if reading is not None:
        state.price = round(reading.price, 8)
        state.trend = reading.trend
        state.rsi = round(reading.rsi, 1)
        state.atr_pct = round(reading.atr_pct, 2)
        state.conviction = reading.signal.conviction if reading.signal else 0
        state.markers = [
            {"code": m.code, "label": m.label, "score": m.score, "primary": m.primary}
            for m in reading.markers
        ]
    state.decision = decision
    state.updated_at = utcnow()
    db.commit()


def scan(db: Session) -> list[Signal]:
    """Un passage complet sur la watchlist. Renvoie les signaux créés."""
    cfg = get_risk_config(db)
    if not cfg.tech_enabled:
        return []
    if cfg.kill_switch:
        log.info("Scanner technique : kill-switch actif, passage ignoré")
        return []

    created: list[Signal] = []
    examined = 0
    tf = f"{cfg.tech_timeframe_min}min"

    for symbol in watchlist(cfg):
        if _has_open_position(db, symbol):
            _record(db, symbol, None, "position déjà ouverte")
            continue
        if _recently_signalled(db, symbol):
            _record(db, symbol, None, f"signal récent (attente de {COOLDOWN_MIN // 60} h)")
            continue

        candles = marketdata.crypto_ohlc(symbol, interval_min=cfg.tech_timeframe_min)
        if not candles:
            _record(db, symbol, None, "bougies indisponibles")
            continue
        examined += 1

        reading = technical.read(symbol, candles, timeframe=tf)
        if reading is None:
            _record(db, symbol, None, "historique insuffisant")
            continue
        if reading.signal is None:
            _record(db, symbol, reading, reading.reason or "aucune configuration")
            continue

        tech = reading.signal
        markers = [
            {"code": m.code, "label": m.label, "score": m.score, "primary": m.primary}
            for m in tech.markers
        ]
        signal = Signal(
            source="technical",
            markers=markers,
            asset=symbol,
            asset_class=AssetClass.crypto,
            direction="buy",
            conviction=tech.conviction,
            horizon="days",
            stop_pct=tech.stop_pct,
            target_pct=tech.target_pct,
            rationale=tech.rationale,
            llm_model="analyse technique",
        )
        db.add(signal)
        db.commit()
        db.refresh(signal)
        created.append(signal)

        if tech.conviction < cfg.tech_min_conviction:
            signal.status = SignalStatus.rejected
            signal.status_reason = (
                f"conviction technique {tech.conviction} < seuil {cfg.tech_min_conviction}"
            )
            db.commit()
            _record(db, symbol, reading, signal.status_reason)
            continue

        # Contre-expertise LLM optionnelle (désactivée par défaut : le moteur
        # technique est déterministe et n'a pas besoin d'un modèle pour agir).
        if cfg.tech_llm_review and not _llm_approves(signal, tech):
            signal.status = SignalStatus.rejected
            signal.status_reason = "second avis LLM défavorable"
            db.commit()
            _record(db, symbol, reading, signal.status_reason)
            continue

        trade = execute_signal(db, signal)
        _record(
            db, symbol, reading,
            f"position ouverte ({trade.qty:g} @ {trade.entry_price:g})" if trade
            else f"signal rejeté — {signal.status_reason}",
        )

    log.info(
        "Scanner technique : %d paires analysées, %d signaux (%d exécutés)",
        examined, len(created), sum(1 for s in created if s.status == SignalStatus.executed),
    )
    return created


def _llm_approves(signal: Signal, tech: technical.TechnicalSignal) -> bool:
    """Avis LLM facultatif sur une configuration technique. Indisponible = accord."""
    from . import llm

    try:
        agrees, _ = llm.second_opinion(
            {
                "asset": signal.asset,
                "direction": "buy",
                "conviction": signal.conviction,
                "rationale": signal.rationale,
            },
            [{"source": "analyse technique", "title": signal.rationale, "summary": ""}],
        )
    except Exception as exc:
        log.warning("Second avis LLM indisponible (%s) : signal conservé", exc)
        return True
    return agrees is not False
