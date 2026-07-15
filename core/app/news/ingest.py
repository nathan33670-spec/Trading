"""Ingestion : récupère les news, déduplique, stocke en base."""
import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import NewsItem
from . import sources

log = logging.getLogger(__name__)


def title_hash(title: str) -> str:
    return hashlib.sha256(title.lower().strip().encode()).hexdigest()


def ingest(db: Session, items: list[dict] | None = None) -> int:
    """Insère les news inédites. Renvoie le nombre de nouvelles entrées."""
    if items is None:
        items = sources.fetch_all()
    if not items:
        return 0

    hashes = {title_hash(i["title"]) for i in items if i["title"]}
    existing = set(
        db.scalars(select(NewsItem.hash).where(NewsItem.hash.in_(hashes))).all()
    )

    added = 0
    seen: set[str] = set()
    for item in items:
        if not item["title"]:
            continue
        h = title_hash(item["title"])
        if h in existing or h in seen:
            continue
        seen.add(h)
        db.add(
            NewsItem(
                source=item["source"],
                title=item["title"],
                url=item.get("url", ""),
                summary=item.get("summary", ""),
                published_at=item.get("published_at"),
                hash=h,
            )
        )
        added += 1
    db.commit()
    if added:
        log.info("Ingestion: %d nouvelles news", added)
    return added
