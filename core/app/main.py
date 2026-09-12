"""Point d'entrée FastAPI du core NewsTrader."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import router
from .db.session import init_db, session_factory
from .ws import manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Autonomie : clé maître et clés Web Push générées si absentes
    from .secrets import bootstrap_master_key, ensure_vapid_keys

    bootstrap_master_key()
    try:
        ensure_vapid_keys()
    except Exception:
        logging.getLogger(__name__).exception("Génération des clés VAPID impossible")

    init_db()

    # Seed de la config de risque (ligne unique)
    from .portfolio.service import get_risk_config

    db = session_factory()()
    try:
        get_risk_config(db)
    finally:
        db.close()

    manager.loop = asyncio.get_running_loop()

    scheduler = None
    if os.environ.get("RUN_SCHEDULER", "1") == "1":
        from .scheduler import build_scheduler

        scheduler = build_scheduler()
        scheduler.start()

    yield

    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="NewsTrader Core", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router)


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp
