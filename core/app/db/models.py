import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AssetClass(str, enum.Enum):
    stock = "stock"
    etf = "etf"
    crypto = "crypto"


class SignalStatus(str, enum.Enum):
    proposed = "proposed"    # émis par le LLM, en attente du moteur de risque
    executed = "executed"    # transformé en trade
    rejected = "rejected"    # refusé (risque, prix indisponible, divergence LLM…)
    expired = "expired"      # non exécuté avant sa date d'expiration


class TradeStatus(str, enum.Enum):
    open = "open"
    closed = "closed"


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    analyzed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(12), default="news", index=True)  # news / technical
    markers: Mapped[list] = mapped_column(JSON, default=list)   # marqueurs techniques repérés
    news_ids: Mapped[list] = mapped_column(JSON, default=list)
    asset: Mapped[str] = mapped_column(String(40))          # ex: "AAPL", "BTC/EUR"
    asset_class: Mapped[AssetClass] = mapped_column(Enum(AssetClass))
    direction: Mapped[str] = mapped_column(String(4))       # buy / sell
    conviction: Mapped[int] = mapped_column(Integer)        # 0-100 (Claude)
    gemini_agrees: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gemini_conviction: Mapped[int | None] = mapped_column(Integer, nullable=True)
    horizon: Mapped[str] = mapped_column(String(20), default="days")  # hours/days/weeks
    stop_pct: Mapped[float] = mapped_column(Float, default=3.0)    # distance stop en %
    target_pct: Mapped[float] = mapped_column(Float, default=6.0)  # distance target en %
    rationale: Mapped[str] = mapped_column(Text, default="")
    llm_model: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[SignalStatus] = mapped_column(Enum(SignalStatus), default=SignalStatus.proposed, index=True)
    status_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True)
    broker: Mapped[str] = mapped_column(String(20))          # paper / trading212 / kraken
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    asset_class: Mapped[AssetClass] = mapped_column(Enum(AssetClass))
    side: Mapped[str] = mapped_column(String(4))             # buy / sell
    qty: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    target_price: Mapped[float] = mapped_column(Float)
    status: Mapped[TradeStatus] = mapped_column(Enum(TradeStatus), default=TradeStatus.open, index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)      # en devise de base
    pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_reason: Mapped[str] = mapped_column(String(40), default="")    # stop/target/trailing/manual
    rationale: Mapped[str] = mapped_column(Text, default="")
    initial_stop: Mapped[float] = mapped_column(Float, default=0.0)  # stop d'origine (calcul du R)
    entry_fee: Mapped[float] = mapped_column(Float, default=0.0)
    exit_fee: Mapped[float] = mapped_column(Float, default=0.0)
    highest_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # suivi du stop suiveur
    trail_active: Mapped[bool] = mapped_column(Boolean, default=False)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)


class RiskConfig(Base):
    """Configuration de risque — une seule ligne (id=1), éditable depuis l'UI."""

    __tablename__ = "risk_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    risk_per_trade_pct: Mapped[float] = mapped_column(Float, default=1.0)
    max_daily_loss_pct: Mapped[float] = mapped_column(Float, default=3.0)
    max_weekly_loss_pct: Mapped[float] = mapped_column(Float, default=6.0)
    max_positions: Mapped[int] = mapped_column(Integer, default=5)
    max_exposure_per_asset_pct: Mapped[float] = mapped_column(Float, default=20.0)
    min_conviction: Mapped[int] = mapped_column(Integer, default=65)
    kill_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    live_trading212: Mapped[bool] = mapped_column(Boolean, default=False)
    live_kraken: Mapped[bool] = mapped_column(Boolean, default=False)

    # Enveloppes : part maximale du portefeuille engageable, au total et par
    # classe d'actif. Le reste du capital n'est jamais touché.
    max_invested_pct: Mapped[float] = mapped_column(Float, default=60.0)
    envelope_crypto_pct: Mapped[float] = mapped_column(Float, default=30.0)
    envelope_stock_pct: Mapped[float] = mapped_column(Float, default=40.0)

    # Frais par classe d'actif (crypto : Revolut Standard par défaut)
    fee_crypto_pct: Mapped[float] = mapped_column(Float, default=1.49)
    fee_crypto_min: Mapped[float] = mapped_column(Float, default=0.99)
    fee_stock_pct: Mapped[float] = mapped_column(Float, default=0.15)
    fee_stock_min: Mapped[float] = mapped_column(Float, default=0.0)
    # Un trade n'est pris que si l'objectif vaut au moins N fois l'aller-retour
    min_target_fee_ratio: Mapped[float] = mapped_column(Float, default=3.0)

    # Analyse technique (fonctionne sans aucune clé API)
    tech_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tech_min_conviction: Mapped[int] = mapped_column(Integer, default=70)
    tech_timeframe_min: Mapped[int] = mapped_column(Integer, default=1440)
    tech_llm_review: Mapped[bool] = mapped_column(Boolean, default=False)
    crypto_watchlist: Mapped[list] = mapped_column(JSON, default=list)

    # Stop suiveur : verrouille les gains quand la position part dans le bon sens.
    # Valeurs retenues d'après le backtest (voir README) : +2R puis suivi à 1,5R.
    trailing_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    trail_activate_r: Mapped[float] = mapped_column(Float, default=2.0)
    trail_distance_r: Mapped[float] = mapped_column(Float, default=1.5)


class MarketState(Base):
    """Dernière lecture technique d'une paire — alimente l'onglet Marché.

    Répond à « pourquoi le bot ne fait rien ? » : chaque paire scannée y laisse
    son état, ses marqueurs et la raison de l'inaction.
    """

    __tablename__ = "market_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    trend: Mapped[str] = mapped_column(String(20), default="")
    rsi: Mapped[float] = mapped_column(Float, default=0.0)
    atr_pct: Mapped[float] = mapped_column(Float, default=0.0)
    conviction: Mapped[int] = mapped_column(Integer, default=0)
    markers: Mapped[list] = mapped_column(JSON, default=list)
    decision: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    keys: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))  # weekly / monthly
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    commentary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
