"""Pipeline d'analyse : news fraîches → filtre mots-clés → Claude → Gemini → exécution.

Le pré-filtre par mots-clés évite d'envoyer chaque dépêche au LLM (maîtrise du coût) :
seules les news contenant un terme à fort impact partent en analyse.
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.models import AssetClass, NewsItem, Signal, SignalStatus
from ..portfolio.service import execute_signal
from . import llm

log = logging.getLogger(__name__)

# Termes (fr/en) qui justifient une analyse LLM — modifiable librement.
IMPACT_KEYWORDS = [
    # entreprises
    "earnings", "résultats", "profit warning", "guidance", "acquisition", "merger",
    "fusion", "buyback", "rachat", "dividend", "dividende", "bankruptcy", "faillite",
    "lawsuit", "recall", "upgrade", "downgrade", "ipo", "layoffs", "restructuring",
    # macro / banques centrales
    "fed", "bce", "ecb", "rate", "taux", "inflation", "cpi", "gdp", "pib",
    "unemployment", "chômage", "tariff", "sanction",
    # crypto
    "bitcoin", "btc", "ethereum", "etf approval", "halving", "sec", "hack",
    "exploit", "stablecoin", "regulation", "régulation", "listing", "delisting",
]


def _has_impact(title: str, summary: str) -> bool:
    text = f"{title} {summary}".lower()
    return any(kw in text for kw in IMPACT_KEYWORDS)


def run_analysis(db: Session) -> list[Signal]:
    """Analyse les news non traitées et crée/exécute les signaux. Renvoie les signaux créés."""
    settings = get_settings()

    pending = db.scalars(
        select(NewsItem).where(NewsItem.analyzed.is_(False)).order_by(NewsItem.id).limit(200)
    ).all()
    if not pending:
        return []

    # Pré-filtre : tout est marqué analysé, seules les news à impact partent au LLM
    candidates = [n for n in pending if _has_impact(n.title, n.summary)]
    for n in pending:
        n.analyzed = True
    db.commit()

    if not candidates:
        log.info("Analyse: %d news, aucune à fort impact", len(pending))
        return []

    batch = candidates[: settings.llm_batch_size]
    news_dicts = [
        {"source": n.source, "title": n.title, "summary": n.summary} for n in batch
    ]
    raw_signals, analyst = llm.analyze_news(news_dicts)

    created: list[Signal] = []
    for raw in raw_signals:
        try:
            asset_class = AssetClass(raw.get("asset_class", "stock"))
        except ValueError:
            asset_class = AssetClass.stock

        signal = Signal(
            news_ids=[batch[i].id for i in raw.get("news_indexes", []) if 0 <= i < len(batch)],
            asset=str(raw["asset"]).upper().strip(),
            asset_class=asset_class,
            direction=raw.get("direction", "buy"),
            conviction=int(raw.get("conviction", 0)),
            horizon=raw.get("horizon", "days"),
            stop_pct=max(0.5, min(float(raw.get("stop_pct", 3.0)), 15.0)),
            target_pct=max(1.0, min(float(raw.get("target_pct", 6.0)), 30.0)),
            rationale=raw.get("rationale", ""),
            llm_model=analyst,
        )
        db.add(signal)
        db.commit()
        db.refresh(signal)
        created.append(signal)

        # Contre-expertise par un fournisseur différent : exécutable si accord,
        # ou si l'analyste seul est très confiant quand aucun second avis n'existe
        agrees, g_conv = llm.second_opinion(raw, news_dicts, exclude=(analyst,))
        signal.gemini_agrees = agrees
        signal.gemini_conviction = g_conv
        db.commit()

        executable = (
            (agrees is True and signal.conviction >= settings.min_conviction)
            or (agrees is None and signal.conviction >= settings.solo_conviction)
        )
        if not executable:
            signal.status = SignalStatus.rejected
            signal.status_reason = (
                "désaccord du second avis" if agrees is False
                else f"conviction insuffisante sans second avis (<{settings.solo_conviction})"
            )
            db.commit()
            continue

        execute_signal(db, signal)

    return created
