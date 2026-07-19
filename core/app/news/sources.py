"""Sources d'actualités financières.

Deux familles :
- Flux RSS (aucune clé requise) — liste modifiable ci-dessous.
- Finnhub (clé gratuite, secret `finnhub_api_key`) — news marchés générales.

Chaque fetcher renvoie une liste de dicts homogènes :
{source, title, url, summary, published_at (datetime|None)}
"""
import logging
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

RSS_FEEDS = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "yahoo-finance": "https://finance.yahoo.com/news/rssindex",
    "marketwatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "investing-news": "https://www.investing.com/rss/news.rss",
}

HTTP_TIMEOUT = 15.0


def _parse_rss(source: str, content: bytes) -> list[dict]:
    import feedparser

    parsed = feedparser.parse(content)
    items = []
    for entry in parsed.entries[:40]:
        published = None
        for attr in ("published_parsed", "updated_parsed"):
            t = getattr(entry, attr, None)
            if t:
                published = datetime(*t[:6], tzinfo=timezone.utc)
                break
        items.append(
            {
                "source": source,
                "title": getattr(entry, "title", "").strip(),
                "url": getattr(entry, "link", ""),
                "summary": getattr(entry, "summary", "")[:2000],
                "published_at": published,
            }
        )
    return items


def fetch_rss() -> list[dict]:
    items: list[dict] = []
    for source, url in RSS_FEEDS.items():
        try:
            resp = httpx.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True,
                             headers={"User-Agent": "NewsTrader/1.0"})
            resp.raise_for_status()
            items.extend(_parse_rss(source, resp.content))
        except Exception as exc:  # une source en panne ne bloque pas les autres
            log.warning("RSS %s indisponible: %s", source, exc)
    return items


def fetch_finnhub() -> list[dict]:
    from ..secrets import get_secret

    key = get_secret("finnhub_api_key")
    if not key:
        return []
    items = []
    try:
        resp = httpx.get(
            "https://finnhub.io/api/v1/news",
            params={"category": "general", "token": key},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        for n in resp.json()[:50]:
            items.append(
                {
                    "source": "finnhub",
                    "title": (n.get("headline") or "").strip(),
                    "url": n.get("url", ""),
                    "summary": (n.get("summary") or "")[:2000],
                    "published_at": datetime.fromtimestamp(n["datetime"], tz=timezone.utc)
                    if n.get("datetime")
                    else None,
                }
            )
    except Exception as exc:
        log.warning("Finnhub indisponible: %s", exc)
    return items


def fetch_all() -> list[dict]:
    return fetch_rss() + fetch_finnhub()
