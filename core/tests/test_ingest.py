from app.db.models import NewsItem
from app.news.ingest import ingest


def items(*titles):
    return [{"source": "test", "title": t, "url": "", "summary": "", "published_at": None} for t in titles]


def test_ingest_and_dedup(db):
    assert ingest(db, items("Fed raises rates", "Apple beats earnings")) == 2
    # doublon exact + doublon insensible à la casse → ignorés
    assert ingest(db, items("Fed raises rates", "FED RAISES RATES", "New story")) == 1
    assert db.query(NewsItem).count() == 3


def test_ingest_skips_empty_titles(db):
    assert ingest(db, items("", "Valid title")) == 1
