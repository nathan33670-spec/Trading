from datetime import timedelta

import pytest

import app.watchdog as watchdog
from app.db.models import NewsItem, utcnow


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    watchdog._alerted = False
    sent = []
    monkeypatch.setattr(watchdog, "send_to_all", lambda db, title, body, tag: sent.append(title) or 1)
    yield sent


def news(minutes_ago: int) -> NewsItem:
    return NewsItem(
        source="test",
        title=f"news {minutes_ago}",
        hash=f"h{minutes_ago}",
        created_at=utcnow() - timedelta(minutes=minutes_ago),
    )


def test_flux_recent_pas_d_alerte(db, _reset_state):
    db.add(news(minutes_ago=10))
    db.commit()
    assert watchdog.check_news_flow(db) is False
    assert _reset_state == []


def test_silence_declenche_une_seule_alerte(db, _reset_state):
    db.add(news(minutes_ago=300))
    db.commit()
    assert watchdog.check_news_flow(db) is True
    assert watchdog.check_news_flow(db) is False  # pas de spam
    assert len(_reset_state) == 1


def test_rearme_apres_reprise_du_flux(db, _reset_state):
    db.add(news(minutes_ago=300))
    db.commit()
    assert watchdog.check_news_flow(db) is True

    db.add(news(minutes_ago=1))  # le flux repart
    db.commit()
    assert watchdog.check_news_flow(db) is False
    assert watchdog._alerted is False  # prêt pour le prochain incident


def test_base_vide_alerte(db, _reset_state):
    assert watchdog.check_news_flow(db) is True
