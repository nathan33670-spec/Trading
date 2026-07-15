"""Tâches périodiques : ingestion, analyse, monitoring, snapshots equity."""
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from .config import get_settings
from .db.session import session_factory

log = logging.getLogger(__name__)


def _with_session(fn):
    def runner():
        db = session_factory()()
        try:
            fn(db)
        except Exception:
            log.exception("Tâche %s en échec", fn.__name__)
        finally:
            db.close()

    runner.__name__ = fn.__name__
    return runner


def _ingest(db):
    from .news.ingest import ingest

    ingest(db)


def _analyze(db):
    from .analysis.pipeline import run_analysis
    from .portfolio.service import expire_stale_signals

    expire_stale_signals(db)
    run_analysis(db)


def _monitor(db):
    from .portfolio.service import monitor_positions

    monitor_positions(db)


def _snapshot(db):
    from .portfolio.service import snapshot_equity

    snapshot_equity(db)


def build_scheduler() -> BackgroundScheduler:
    s = get_settings()
    sched = BackgroundScheduler(timezone=s.tz)
    sched.add_job(_with_session(_ingest), "interval", minutes=s.ingest_interval_min, id="ingest")
    sched.add_job(_with_session(_analyze), "interval", minutes=s.analyze_interval_min, id="analyze",
                  jitter=30)
    sched.add_job(_with_session(_monitor), "interval", minutes=s.monitor_interval_min, id="monitor")
    sched.add_job(_with_session(_snapshot), "interval", hours=1, id="snapshot")
    return sched
