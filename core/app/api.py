"""API REST consommée par la PWA et par n8n."""
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import marketdata
from .config import get_settings
from .db.models import (
    EquitySnapshot,
    NewsItem,
    Report,
    RiskConfig,
    Signal,
    Trade,
    TradeStatus,
    utcnow,
)
from .db.session import get_db
from .news.ingest import ingest, title_hash
from .portfolio import service as portfolio
from .ws import manager

router = APIRouter(prefix="/api")


# ── Authentification (jeton partagé) ─────────────────────────────────────────

def require_token(
    authorization: str = Header(default=""),
    x_api_token: str = Header(default=""),
) -> None:
    expected = get_settings().api_token
    provided = x_api_token or authorization.removeprefix("Bearer ").strip()
    if not expected or provided != expected:
        raise HTTPException(status_code=401, detail="jeton API invalide")


# ── Santé (public, pour le watchdog n8n) ─────────────────────────────────────

@router.get("/health")
def health(db: Session = Depends(get_db)):
    last_news = db.scalar(select(NewsItem).order_by(NewsItem.created_at.desc()).limit(1))
    return {
        "status": "ok",
        "last_news_at": last_news.created_at if last_news else None,
    }


class LoginBody(BaseModel):
    token: str


@router.post("/auth/login")
def login(body: LoginBody):
    if body.token != get_settings().api_token:
        raise HTTPException(status_code=401, detail="jeton invalide")
    return {"ok": True}


# ── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/dashboard", dependencies=[Depends(require_token)])
def dashboard(db: Session = Depends(get_db)):
    settings = get_settings()
    state = portfolio.get_state(db)
    cfg = portfolio.get_risk_config(db)

    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    open_trades = db.scalars(select(Trade).where(Trade.status == TradeStatus.open)).all()
    positions = []
    open_value = 0.0
    for t in open_trades:
        price = marketdata.get_price(t.symbol, t.asset_class.value) or t.entry_price
        value = t.qty * price
        open_value += value
        positions.append(
            {
                "id": t.id,
                "symbol": t.symbol,
                "asset_class": t.asset_class.value,
                "broker": t.broker,
                "is_paper": t.is_paper,
                "qty": t.qty,
                "entry_price": t.entry_price,
                "current_price": price,
                "stop_price": t.stop_price,
                "target_price": t.target_price,
                "unrealized_pnl": round((price - t.entry_price) * t.qty, 2),
                "unrealized_pnl_pct": round((price / t.entry_price - 1) * 100, 2),
                "opened_at": t.opened_at,
            }
        )

    curve = db.scalars(
        select(EquitySnapshot)
        .where(EquitySnapshot.ts >= now - timedelta(days=30))
        .order_by(EquitySnapshot.ts)
    ).all()

    equity = round(state.cash + open_value, 2)
    return {
        "equity": equity,
        "cash": state.cash,
        "start_capital": settings.start_capital,
        "total_pnl": round(equity - settings.start_capital, 2),
        "daily_pnl": state.daily_pnl,
        "weekly_pnl": state.weekly_pnl,
        "monthly_pnl": portfolio.realized_pnl_since(db, month_start),
        "positions": positions,
        "equity_curve": [{"ts": s.ts, "equity": s.equity} for s in curve],
        "mode": {
            "kill_switch": cfg.kill_switch,
            "live_trading212": cfg.live_trading212,
            "live_kraken": cfg.live_kraken,
        },
        "currency": settings.base_currency,
    }


# ── Signaux & trades ─────────────────────────────────────────────────────────

@router.get("/signals", dependencies=[Depends(require_token)])
def list_signals(limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    signals = db.scalars(select(Signal).order_by(Signal.created_at.desc()).limit(limit)).all()
    news_ids = {i for s in signals for i in (s.news_ids or [])}
    news = {
        n.id: {"title": n.title, "source": n.source, "url": n.url}
        for n in db.scalars(select(NewsItem).where(NewsItem.id.in_(news_ids))).all()
    } if news_ids else {}
    return [
        {
            "id": s.id,
            "asset": s.asset,
            "asset_class": s.asset_class.value,
            "direction": s.direction,
            "conviction": s.conviction,
            "gemini_agrees": s.gemini_agrees,
            "gemini_conviction": s.gemini_conviction,
            "horizon": s.horizon,
            "rationale": s.rationale,
            "status": s.status.value,
            "status_reason": s.status_reason,
            "created_at": s.created_at,
            "news": [news[i] for i in (s.news_ids or []) if i in news],
        }
        for s in signals
    ]


@router.get("/trades", dependencies=[Depends(require_token)])
def list_trades(
    status: str | None = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    q = select(Trade).order_by(Trade.opened_at.desc()).limit(limit)
    if status in ("open", "closed"):
        q = q.where(Trade.status == TradeStatus(status))
    return [
        {
            "id": t.id,
            "symbol": t.symbol,
            "asset_class": t.asset_class.value,
            "broker": t.broker,
            "is_paper": t.is_paper,
            "side": t.side,
            "qty": t.qty,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "stop_price": t.stop_price,
            "target_price": t.target_price,
            "status": t.status.value,
            "pnl": t.pnl,
            "pnl_pct": t.pnl_pct,
            "close_reason": t.close_reason,
            "opened_at": t.opened_at,
            "closed_at": t.closed_at,
            "rationale": t.rationale,
        }
        for t in db.scalars(q).all()
    ]


@router.post("/trades/{trade_id}/close", dependencies=[Depends(require_token)])
def close_trade_manual(trade_id: int, db: Session = Depends(get_db)):
    trade = db.get(Trade, trade_id)
    if not trade or trade.status != TradeStatus.open:
        raise HTTPException(status_code=404, detail="trade introuvable ou déjà clôturé")
    price = marketdata.get_price(trade.symbol, trade.asset_class.value)
    if not price:
        raise HTTPException(status_code=503, detail="prix indisponible, réessayer")
    portfolio.close_trade(db, trade, price, reason="manual")
    return {"ok": True, "pnl": trade.pnl}


# ── Réglages de risque ───────────────────────────────────────────────────────

class RiskBody(BaseModel):
    risk_per_trade_pct: float = Field(ge=0.1, le=5)
    max_daily_loss_pct: float = Field(ge=0.5, le=20)
    max_weekly_loss_pct: float = Field(ge=1, le=40)
    max_positions: int = Field(ge=1, le=20)
    max_exposure_per_asset_pct: float = Field(ge=1, le=100)
    min_conviction: int = Field(ge=0, le=100)
    kill_switch: bool
    live_trading212: bool
    live_kraken: bool


def _risk_dict(cfg: RiskConfig) -> dict:
    return {
        "risk_per_trade_pct": cfg.risk_per_trade_pct,
        "max_daily_loss_pct": cfg.max_daily_loss_pct,
        "max_weekly_loss_pct": cfg.max_weekly_loss_pct,
        "max_positions": cfg.max_positions,
        "max_exposure_per_asset_pct": cfg.max_exposure_per_asset_pct,
        "min_conviction": cfg.min_conviction,
        "kill_switch": cfg.kill_switch,
        "live_trading212": cfg.live_trading212,
        "live_kraken": cfg.live_kraken,
    }


@router.get("/settings/risk", dependencies=[Depends(require_token)])
def get_risk(db: Session = Depends(get_db)):
    return _risk_dict(portfolio.get_risk_config(db))


@router.put("/settings/risk", dependencies=[Depends(require_token)])
def put_risk(body: RiskBody, db: Session = Depends(get_db)):
    cfg = portfolio.get_risk_config(db)
    for key, value in body.model_dump().items():
        setattr(cfg, key, value)
    db.commit()
    return _risk_dict(cfg)


# ── Rapports ─────────────────────────────────────────────────────────────────

@router.get("/reports", dependencies=[Depends(require_token)])
def list_reports(db: Session = Depends(get_db)):
    reports = db.scalars(select(Report).order_by(Report.created_at.desc()).limit(50)).all()
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "period_start": r.period_start,
            "period_end": r.period_end,
            "stats": r.stats,
            "commentary": r.commentary,
            "created_at": r.created_at,
        }
        for r in reports
    ]


@router.post("/reports/generate", dependencies=[Depends(require_token)])
def generate_report_endpoint(kind: str = Query(pattern="^(weekly|monthly)$"), db: Session = Depends(get_db)):
    from .reports.service import generate_report

    report = generate_report(db, kind)
    return {"id": report.id, "stats": report.stats, "commentary": report.commentary}


# ── Web Push ─────────────────────────────────────────────────────────────────

class SubscriptionBody(BaseModel):
    endpoint: str
    keys: dict


@router.get("/push/vapid-public-key", dependencies=[Depends(require_token)])
def vapid_public_key():
    from .secrets import get_secret

    key = get_secret("vapid_public_key")
    if not key:
        raise HTTPException(status_code=503, detail="clés VAPID non générées (python -m app.secrets gen-vapid)")
    return {"key": key}


@router.post("/push/subscribe", dependencies=[Depends(require_token)])
def push_subscribe(body: SubscriptionBody, db: Session = Depends(get_db)):
    from .db.models import PushSubscription

    existing = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if existing:
        existing.keys = body.keys
    else:
        db.add(PushSubscription(endpoint=body.endpoint, keys=body.keys))
    db.commit()
    return {"ok": True}


@router.post("/push/test", dependencies=[Depends(require_token)])
def push_test(db: Session = Depends(get_db)):
    from .notify.push import send_to_all

    sent = send_to_all(db, "🔔 NewsTrader", "Les notifications fonctionnent !", tag="test")
    return {"sent": sent}


# ── Injection de test (vérification bout-en-bout) ────────────────────────────

class FakeNewsBody(BaseModel):
    title: str
    summary: str = ""
    source: str = "test"


@router.post("/test/inject-news", dependencies=[Depends(require_token)])
def inject_news(body: FakeNewsBody, db: Session = Depends(get_db)):
    """Injecte une fausse news puis lance l'analyse — pour tester la chaîne complète."""
    from .analysis.pipeline import run_analysis

    ingest(db, [{
        "source": body.source,
        "title": body.title,
        "summary": body.summary,
        "url": "",
        "published_at": utcnow(),
    }])
    signals = run_analysis(db)
    return {
        "ingested_hash": title_hash(body.title),
        "signals": [{"id": s.id, "asset": s.asset, "status": s.status.value, "reason": s.status_reason} for s in signals],
    }


# ── WebSocket temps réel ─────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query(default="")):
    if token != get_settings().api_token:
        await ws.close(code=4401)
        return
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive côté client
    except WebSocketDisconnect:
        manager.disconnect(ws)
