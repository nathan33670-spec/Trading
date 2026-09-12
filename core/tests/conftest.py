import os
import sys
import tempfile
from pathlib import Path

# Environnement de test AVANT tout import de l'app
_tmp = tempfile.mkdtemp(prefix="newstrader-test-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("API_TOKEN", "test-token")
os.environ.setdefault("RUN_SCHEDULER", "0")
os.environ.setdefault("SECRETS_FILE", f"{_tmp}/credentials.enc.json")
os.environ.setdefault("START_CAPITAL", "10000")

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("MASTER_KEY", Fernet.generate_key().decode())

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base


@pytest.fixture
def db():
    """Session SQLite isolée par test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=__import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
