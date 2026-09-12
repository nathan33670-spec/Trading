"""Watchdog interne : alerte push si l'ingestion de news se tait trop longtemps.

Le crash du core est couvert par Docker (`restart: unless-stopped` + healthcheck) ;
ici on surveille la panne silencieuse — le process tourne mais plus rien n'entre
(flux RSS morts, DNS, coupure réseau du NAS…).
"""
import logging
from datetime import timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db.models import NewsItem, utcnow
from .notify.push import send_to_all

log = logging.getLogger(__name__)

# Une alerte par épisode de silence ; réarmé dès que le flux repart.
_alerted = False


def check_news_flow(db: Session) -> bool:
    """Renvoie True si une alerte a été envoyée."""
    global _alerted
    s = get_settings()
    last = db.scalar(select(NewsItem.created_at).order_by(NewsItem.created_at.desc()).limit(1))
    if last is not None and last.tzinfo is None:  # SQLite renvoie des datetimes naïfs
        last = last.replace(tzinfo=timezone.utc)

    now = utcnow()
    quiet = last is None or now - last > timedelta(minutes=s.watchdog_news_silence_min)
    if not quiet:
        if _alerted:
            log.info("Watchdog : le flux de news est reparti")
        _alerted = False
        return False
    if _alerted:
        return False

    _alerted = True
    age = "aucune depuis le démarrage" if last is None else f"il y a {int((now - last).total_seconds() // 60)} min"
    log.warning("Watchdog : ingestion muette (dernière news : %s)", age)
    send_to_all(
        db,
        "⚠️ NewsTrader : ingestion muette",
        f"Aucune news depuis plus de {s.watchdog_news_silence_min} min "
        f"(dernière : {age}). Vérifiez les flux RSS et la connexion du NAS.",
        tag="watchdog",
    )
    return True
