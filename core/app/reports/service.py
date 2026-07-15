"""Synthèses hebdomadaires et mensuelles : stats + commentaire rédigé + push."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis.llm import write_commentary
from ..db.models import Report, Trade, TradeStatus, utcnow
from ..notify.push import send_to_all

log = logging.getLogger(__name__)


def _period(kind: str, now: datetime) -> tuple[datetime, datetime]:
    """Période écoulée : la semaine passée (lun→dim) ou le mois précédent."""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "weekly":
        end = today - timedelta(days=today.weekday())  # lundi de cette semaine
        start = end - timedelta(days=7)
    else:  # monthly
        end = today.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
    return start, end


def compute_stats(db: Session, start: datetime, end: datetime) -> dict:
    trades = db.scalars(
        select(Trade).where(
            Trade.status == TradeStatus.closed,
            Trade.closed_at >= start,
            Trade.closed_at < end,
        )
    ).all()

    wins = [t for t in trades if (t.pnl or 0) > 0]
    losses = [t for t in trades if (t.pnl or 0) <= 0]
    pnl = round(sum(t.pnl or 0 for t in trades), 2)
    best = max(trades, key=lambda t: t.pnl or 0, default=None)
    worst = min(trades, key=lambda t: t.pnl or 0, default=None)

    by_class: dict[str, float] = {}
    for t in trades:
        key = t.asset_class.value
        by_class[key] = round(by_class.get(key, 0.0) + (t.pnl or 0), 2)

    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        "pnl": pnl,
        "avg_pnl": round(pnl / len(trades), 2) if trades else 0.0,
        "best_trade": {"symbol": best.symbol, "pnl": best.pnl} if best else None,
        "worst_trade": {"symbol": worst.symbol, "pnl": worst.pnl} if worst else None,
        "pnl_by_class": by_class,
    }


def generate_report(db: Session, kind: str, notify: bool = True) -> Report:
    now = utcnow()
    start, end = _period(kind, now)
    stats = compute_stats(db, start, end)
    commentary = write_commentary(stats, kind)

    report = Report(kind=kind, period_start=start, period_end=end, stats=stats, commentary=commentary)
    db.add(report)
    db.commit()
    db.refresh(report)

    if notify:
        label = "hebdomadaire" if kind == "weekly" else "mensuelle"
        emoji = "📊" if stats["pnl"] >= 0 else "📉"
        send_to_all(
            db,
            f"{emoji} Synthèse {label}",
            f"{stats['trades']} trades, {stats['win_rate']:.0f} % gagnants — "
            f"P&L {stats['pnl']:+.2f} €\n{commentary[:180]}",
            tag=f"report-{report.id}",
        )
    return report
