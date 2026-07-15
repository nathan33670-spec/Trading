"""Notifications Web Push (VAPID) vers la PWA installée sur le téléphone."""
import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import PushSubscription, Trade

log = logging.getLogger(__name__)


def send_to_all(db: Session, title: str, body: str, tag: str = "newstrader") -> int:
    """Envoie une notification à tous les appareils abonnés. Renvoie le nb d'envois."""
    from ..secrets import get_secret

    private_key = get_secret("vapid_private_key")
    if not private_key:
        log.warning("vapid_private_key manquante : notification '%s' non envoyée", title)
        return 0

    from pywebpush import WebPushException, webpush  # import paresseux

    subs = db.scalars(select(PushSubscription)).all()
    payload = json.dumps({"title": title, "body": body, "tag": tag})
    sent = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": sub.keys},
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={"sub": "mailto:admin@newstrader.local"},
            )
            sent += 1
        except WebPushException as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None)
            if code in (404, 410):  # abonnement mort → nettoyage
                db.delete(sub)
                db.commit()
                log.info("Abonnement push expiré supprimé")
            else:
                log.warning("Échec push: %s", exc)
        except Exception as exc:
            log.warning("Échec push: %s", exc)
    return sent


def _fmt_money(v: float) -> str:
    return f"{v:+,.2f} €".replace(",", " ")


def notify_trade_opened(db: Session, trade: Trade) -> None:
    mode = "PAPER" if trade.is_paper else "RÉEL"
    title = f"📈 Position ouverte [{mode}]"
    body = (
        f"{trade.symbol} — achat {trade.qty:g} @ {trade.entry_price:g} "
        f"(stop {trade.stop_price:g} / objectif {trade.target_price:g})\n"
        f"{trade.rationale[:140]}"
    )
    send_to_all(db, title, body, tag=f"trade-{trade.id}")


def notify_trade_closed(db: Session, trade: Trade) -> None:
    mode = "PAPER" if trade.is_paper else "RÉEL"
    emoji = "✅" if (trade.pnl or 0) >= 0 else "🔻"
    reasons = {"stop": "stop touché", "target": "objectif atteint", "signal": "signal de vente", "manual": "clôture manuelle"}
    title = f"{emoji} Position clôturée [{mode}]"
    body = (
        f"{trade.symbol} — {reasons.get(trade.close_reason, trade.close_reason)}\n"
        f"Résultat : {_fmt_money(trade.pnl or 0)} ({trade.pnl_pct:+.2f} %)"
    )
    send_to_all(db, title, body, tag=f"trade-{trade.id}")
