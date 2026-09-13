"""API REST consommée par la PWA."""
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
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
from .security import check_not_locked, client_ip, record_failure, record_success, tokens_match
from .ws import manager

router = APIRouter(prefix="/api")


# ── Authentification (jeton partagé) ─────────────────────────────────────────

def require_token(
    request: Request,
    authorization: str = Header(default=""),
    x_api_token: str = Header(default=""),
) -> None:
    ip = client_ip(request)
    check_not_locked(ip)
    expected = get_settings().api_token
    provided = x_api_token or authorization.removeprefix("Bearer ").strip()
    if not tokens_match(provided, expected):
        record_failure(ip)
        raise HTTPException(status_code=401, detail="jeton API invalide")
    record_success(ip)


# ── Santé (public : healthcheck Docker / supervision externe) ────────────────

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
def login(body: LoginBody, request: Request):
    ip = client_ip(request)
    check_not_locked(ip)
    if not tokens_match(body.token, get_settings().api_token):
        record_failure(ip)
        raise HTTPException(status_code=401, detail="jeton invalide")
    record_success(ip)
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
        "envelopes": {
            "invested": round(open_value, 2),
            "invested_pct": round(open_value / equity * 100, 1) if equity > 0 else 0.0,
            "max_invested_pct": cfg.max_invested_pct,
            "by_class": [
                {
                    "name": name,
                    "used": round(state.exposure_by_class.get(key, 0.0), 2),
                    "used_pct": round(state.exposure_by_class.get(key, 0.0) / equity * 100, 1)
                    if equity > 0 else 0.0,
                    "max_pct": max_pct,
                }
                for name, key, max_pct in (
                    ("crypto", "crypto", cfg.envelope_crypto_pct),
                    ("actions / ETF", "stock", cfg.envelope_stock_pct),
                )
            ],
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
            "source": s.source,
            "markers": s.markers or [],
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
            "fees": round((t.entry_fee or 0) + (t.exit_fee or 0), 2),
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
    # Enveloppes
    max_invested_pct: float = Field(default=60.0, ge=1, le=100)
    envelope_crypto_pct: float = Field(default=30.0, ge=0, le=100)
    envelope_stock_pct: float = Field(default=40.0, ge=0, le=100)
    # Frais
    fee_crypto_pct: float = Field(default=1.49, ge=0, le=5)
    fee_crypto_min: float = Field(default=0.99, ge=0, le=50)
    fee_stock_pct: float = Field(default=0.15, ge=0, le=5)
    fee_stock_min: float = Field(default=0.0, ge=0, le=50)
    min_target_fee_ratio: float = Field(default=3.0, ge=0, le=10)
    # Stratégie
    strategy: str = Field(default="regime", pattern="^(regime|swing|off)$")
    regime_assets: list[str] = Field(default_factory=list, max_length=20)
    momentum_days: int = Field(default=365, ge=30, le=1000)
    regime_check_days: int = Field(default=7, ge=1, le=60)
    regime_confirm_sma: int = Field(default=0, ge=0, le=400)
    # Analyse technique court terme
    tech_enabled: bool = False
    tech_min_conviction: int = Field(default=70, ge=0, le=100)
    tech_timeframe_min: int = Field(default=1440)
    tech_llm_review: bool = False
    crypto_watchlist: list[str] = Field(default_factory=list, max_length=40)
    # Stop suiveur
    trailing_enabled: bool = True
    trail_activate_r: float = Field(default=2.0, ge=0.5, le=10)
    trail_distance_r: float = Field(default=1.5, ge=0.3, le=10)


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
        "max_invested_pct": cfg.max_invested_pct,
        "envelope_crypto_pct": cfg.envelope_crypto_pct,
        "envelope_stock_pct": cfg.envelope_stock_pct,
        "fee_crypto_pct": cfg.fee_crypto_pct,
        "fee_crypto_min": cfg.fee_crypto_min,
        "fee_stock_pct": cfg.fee_stock_pct,
        "fee_stock_min": cfg.fee_stock_min,
        "min_target_fee_ratio": cfg.min_target_fee_ratio,
        "strategy": cfg.strategy,
        "regime_assets": cfg.regime_assets or [],
        "momentum_days": cfg.momentum_days,
        "regime_check_days": cfg.regime_check_days,
        "regime_confirm_sma": cfg.regime_confirm_sma,
        "tech_enabled": cfg.tech_enabled,
        "tech_min_conviction": cfg.tech_min_conviction,
        "tech_timeframe_min": cfg.tech_timeframe_min,
        "tech_llm_review": cfg.tech_llm_review,
        "crypto_watchlist": cfg.crypto_watchlist or [],
        "trailing_enabled": cfg.trailing_enabled,
        "trail_activate_r": cfg.trail_activate_r,
        "trail_distance_r": cfg.trail_distance_r,
    }


@router.get("/settings/risk", dependencies=[Depends(require_token)])
def get_risk(db: Session = Depends(get_db)):
    return _risk_dict(portfolio.get_risk_config(db))


@router.put("/settings/risk", dependencies=[Depends(require_token)])
def put_risk(body: RiskBody, db: Session = Depends(get_db)):
    cfg = portfolio.get_risk_config(db)
    data = body.model_dump()
    watchlist = [s.strip().upper() for s in data.pop("crypto_watchlist", []) if s.strip()]
    regime_assets = [s.strip().upper() for s in data.pop("regime_assets", []) if s.strip()]
    for key, value in data.items():
        setattr(cfg, key, value)
    cfg.crypto_watchlist = watchlist
    cfg.regime_assets = regime_assets
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


# ── Marché : ce que le moteur technique voit, paire par paire ────────────────

@router.get("/market", dependencies=[Depends(require_token)])
def market(db: Session = Depends(get_db)):
    from .analysis.allocator import assets as regime_assets
    from .analysis.scanner import watchlist
    from .db.models import MarketState

    cfg = portfolio.get_risk_config(db)
    states = {s.symbol: s for s in db.scalars(select(MarketState)).all()}
    symbols = regime_assets(cfg) if cfg.strategy == "regime" else watchlist(cfg)
    rows = []
    for symbol in symbols:
        st = states.get(symbol)
        rows.append({
            "symbol": symbol,
            "price": st.price if st else None,
            "trend": st.trend if st else "",
            "rsi": st.rsi if st else None,
            "atr_pct": st.atr_pct if st else None,
            "conviction": st.conviction if st else 0,
            "markers": (st.markers or []) if st else [],
            "decision": st.decision if st else "pas encore analysée",
            "updated_at": st.updated_at if st else None,
        })
    return {
        "strategy": cfg.strategy,
        "enabled": cfg.strategy != "off",
        "momentum_days": cfg.momentum_days,
        "check_days": cfg.regime_check_days,
        "timeframe_min": cfg.tech_timeframe_min,
        "min_conviction": cfg.tech_min_conviction,
        "rows": rows,
    }


@router.post("/market/scan", dependencies=[Depends(require_token)])
def market_scan(db: Session = Depends(get_db)):
    """Force une évaluation immédiate de la stratégie active."""
    cfg = portfolio.get_risk_config(db)
    if cfg.strategy == "regime":
        from .analysis.allocator import run as run_regime

        return {"actions": run_regime(db, force=True)}
    if cfg.strategy == "swing":
        from .analysis.scanner import scan

        signals = scan(db)
        return {
            "signals": [
                {"asset": s.asset, "conviction": s.conviction, "status": s.status.value,
                 "reason": s.status_reason}
                for s in signals
            ]
        }
    return {"actions": [], "detail": "aucune stratégie active"}


@router.post("/market/backtest", dependencies=[Depends(require_token)])
def market_backtest(
    stake: float = Query(10_000.0, gt=0, le=1_000_000),
    db: Session = Depends(get_db),
):
    """Rejoue la stratégie active sur tout l'historique disponible, frais compris.

    C'est la réponse honnête à « est-ce que ça marche ? » : des chiffres mesurés
    sur les bougies réelles depuis 2016, comparés à l'achat-conservation.
    """
    from . import marketdata_history
    from .analysis import regime
    from .analysis.allocator import assets as regime_assets
    from .brokers.fees import FeeSchedule

    cfg = portfolio.get_risk_config(db)
    fees = FeeSchedule("crypto", pct=cfg.fee_crypto_pct, minimum=cfg.fee_crypto_min)

    if cfg.strategy != "regime":
        return _swing_backtest(cfg, fees, stake)

    def run_on(symbol, candles):
        return regime.backtest(
            symbol, candles, fees,
            start_equity=stake,
            momentum_days=cfg.momentum_days,
            confirm_sma=cfg.regime_confirm_sma,
            check_every_days=cfg.regime_check_days,
        )

    day = 86400
    results = []
    for symbol in regime_assets(cfg):
        candles = marketdata_history.history(symbol)
        full = run_on(symbol, candles)
        if not full:
            continue
        entry = full.summary()

        # Découpage par sous-périodes : une stratégie jugée sur une seule
        # fenêtre trompe — c'est l'erreur qui a coulé la version précédente.
        periods = []
        for years, label in ((5, "5 dernières années"), (3, "3 dernières années")):
            need = int(years * 365.25) + cfg.momentum_days + 32
            if len(candles) <= need:
                continue
            sub = run_on(symbol, candles[-need:])
            if sub:
                periods.append({"label": label, **sub.summary()})
        entry["periods"] = periods
        results.append(entry)

    if not results:
        raise HTTPException(status_code=503, detail="historique indisponible, réessayer")

    return {"strategy": "regime", "stake": stake, "per_symbol": results}


def _swing_backtest(cfg, fees, stake: float) -> dict:
    """Backtest de l'ancienne stratégie court terme (conservée en option)."""
    from .analysis import backtest
    from .analysis.scanner import watchlist

    tf = cfg.tech_timeframe_min
    results = []
    for symbol in watchlist(cfg):
        candles = marketdata.crypto_ohlc(symbol, interval_min=tf)
        if len(candles) < backtest.MIN_CANDLES + 2:
            continue
        results.append(backtest.run(
            symbol, candles, stake=stake / 10,
            min_conviction=cfg.tech_min_conviction, fees=fees,
            trailing=cfg.trailing_enabled,
            trail_activate_r=cfg.trail_activate_r,
            trail_distance_r=cfg.trail_distance_r,
            timeframe=f"{tf}min",
        ))
    if not results:
        raise HTTPException(status_code=503, detail="historique indisponible, réessayer")
    summary = backtest.aggregate(results)
    summary["strategy"] = "swing"
    summary["stake"] = stake / 10
    return summary


# ── Admin : clés API (write-only) & état des fournisseurs ────────────────────

class SecretValue(BaseModel):
    value: str = Field(min_length=1, max_length=4096)


def _known_secret_or_404(name: str) -> None:
    from .secrets import KNOWN_SECRETS

    if not any(item["name"] == name for item in KNOWN_SECRETS):
        raise HTTPException(status_code=404, detail="clé inconnue")


@router.get("/admin/secrets", dependencies=[Depends(require_token)])
def admin_list_secrets():
    """Les valeurs ne sortent jamais : uniquement le statut et les 4 derniers caractères."""
    from .secrets import KNOWN_SECRETS, get_secret, secret_hint

    return [
        {**item, "configured": bool(get_secret(item["name"])), "hint": secret_hint(item["name"])}
        for item in KNOWN_SECRETS
    ]


@router.put("/admin/secrets/{name}", dependencies=[Depends(require_token)])
def admin_set_secret(name: str, body: SecretValue):
    _known_secret_or_404(name)
    from .secrets import set_secret

    set_secret(name, body.value.strip())
    return {"ok": True}


@router.delete("/admin/secrets/{name}", dependencies=[Depends(require_token)])
def admin_delete_secret(name: str):
    _known_secret_or_404(name)
    from .secrets import delete_secret

    delete_secret(name)
    return {"ok": True}


@router.post("/admin/secrets/{name}/test", dependencies=[Depends(require_token)])
def admin_test_secret(name: str):
    """Vérifie qu'une clé fonctionne réellement, par un appel minimal au service.

    Une clé mal collée (espace, caractère manquant) ne se voit pas autrement
    qu'au premier signal manqué — d'où ce test immédiat.
    """
    _known_secret_or_404(name)
    from .secrets import get_secret

    value = get_secret(name)
    if not value:
        return {"ok": False, "detail": "aucune clé enregistrée"}

    tester = _SECRET_TESTS.get(name)
    if tester is None:
        return {"ok": True, "detail": "clé enregistrée (pas de test automatique pour ce service)"}
    try:
        return tester(value)
    except Exception as exc:                     # pragma: no cover - dépend du réseau
        return {"ok": False, "detail": f"échec du test : {exc}"}


def _test_gemini(key: str) -> dict:
    import httpx

    resp = httpx.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        params={"key": key}, timeout=15.0,
    )
    if resp.status_code == 200:
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        flash = [m for m in models if "flash" in m]
        return {"ok": True, "detail": f"clé valide — {len(models)} modèles accessibles"
                                      + (f", dont {flash[0].split('/')[-1]}" if flash else "")}
    if resp.status_code in (400, 403):
        return {"ok": False, "detail": "clé refusée par Google (invalide ou API non activée)"}
    return {"ok": False, "detail": f"réponse inattendue de Google ({resp.status_code})"}


def _test_anthropic(key: str) -> dict:
    import httpx

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": get_settings().claude_model, "max_tokens": 1,
              "messages": [{"role": "user", "content": "ping"}]},
        timeout=20.0,
    )
    if resp.status_code == 200:
        return {"ok": True, "detail": "clé valide, réponse reçue de l'API Anthropic"}
    if resp.status_code == 401:
        return {"ok": False, "detail": "clé refusée par Anthropic"}
    if resp.status_code == 400:
        # requête minimale rejetée mais authentification acceptée
        return {"ok": True, "detail": "clé acceptée (authentification réussie)"}
    return {"ok": False, "detail": f"réponse inattendue ({resp.status_code})"}


def _test_claude_cli(token: str) -> dict:
    import shutil
    import subprocess

    if not shutil.which("claude"):
        return {"ok": False, "detail": "CLI Claude Code absente de l'image"}
    proc = subprocess.run(
        ["claude", "-p", "réponds exactement: ok"],
        capture_output=True, text=True, timeout=90,
        env={"CLAUDE_CODE_OAUTH_TOKEN": token, "PATH": "/usr/local/bin:/usr/bin:/bin",
             "HOME": "/home/app"},
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return {"ok": True, "detail": f"jeton valide — réponse : {proc.stdout.strip()[:60]}"}
    return {"ok": False, "detail": (proc.stderr or proc.stdout or "pas de réponse").strip()[:200]}


def _test_finnhub(key: str) -> dict:
    import httpx

    resp = httpx.get("https://finnhub.io/api/v1/quote",
                     params={"symbol": "AAPL", "token": key}, timeout=15.0)
    if resp.status_code == 200 and resp.json().get("c"):
        return {"ok": True, "detail": f"clé valide — AAPL cotée à {resp.json()['c']} $"}
    if resp.status_code in (401, 403):
        return {"ok": False, "detail": "clé refusée par Finnhub"}
    return {"ok": False, "detail": f"réponse inattendue ({resp.status_code})"}


def _test_kraken(key: str) -> dict:
    from .secrets import get_secret

    secret = get_secret("kraken_api_secret")
    if not secret:
        return {"ok": False, "detail": "kraken_api_secret manquant"}
    import ccxt

    client = ccxt.kraken({"apiKey": key, "secret": secret})
    balance = client.fetch_balance()
    total = balance.get("total", {})
    actifs = [k for k, v in total.items() if v]
    return {"ok": True, "detail": f"clé valide — {len(actifs)} actif(s) sur le compte"}


def _test_trading212(key: str) -> dict:
    import httpx

    import os

    base = ("https://demo.trading212.com" if os.environ.get("T212_ENV", "demo") == "demo"
            else "https://live.trading212.com")
    resp = httpx.get(f"{base}/api/v0/equity/account/cash",
                     headers={"Authorization": key}, timeout=20.0)
    if resp.status_code == 200:
        return {"ok": True, "detail": f"clé valide — liquidités : {resp.json().get('free', '?')}"}
    if resp.status_code in (401, 403):
        return {"ok": False, "detail": "clé refusée par Trading212"}
    return {"ok": False, "detail": f"réponse inattendue ({resp.status_code})"}


_SECRET_TESTS = {
    "google_api_key": _test_gemini,
    "anthropic_api_key": _test_anthropic,
    "claude_code_oauth_token": _test_claude_cli,
    "finnhub_api_key": _test_finnhub,
    "kraken_api_key": _test_kraken,
    "trading212_api_key": _test_trading212,
}


@router.get("/admin/status", dependencies=[Depends(require_token)])
def admin_status():
    from .analysis.llm import _AVAILABILITY, PROVIDERS
    from .secrets import get_secret

    providers = {name: check() for name, check in _AVAILABILITY.items()}
    analyst = next((p for p in PROVIDERS if providers[p]), None)
    second = next((p for p in PROVIDERS if providers[p] and p != analyst), None)
    return {
        "providers": providers,
        "analyst": analyst,
        "second_opinion": second,
        "push_ready": bool(get_secret("vapid_private_key")),
        "market_data": bool(get_secret("finnhub_api_key")),
    }


# ── WebSocket temps réel ─────────────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = Query(default="")):
    if not tokens_match(token, get_settings().api_token):
        await ws.close(code=4401)
        return
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive côté client
    except WebSocketDisconnect:
        manager.disconnect(ws)
