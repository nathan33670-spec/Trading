import logging
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings

log = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = get_settings().database_url
        kwargs = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def session_factory() -> sessionmaker:
    get_engine()
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()


def _literal_default(col, dialect_name: str) -> str | None:
    """Valeur SQL à donner aux lignes existantes pour une colonne ajoutée."""
    default = getattr(col, "default", None)
    arg = getattr(default, "arg", None) if default is not None else None
    if callable(arg):
        # default=list / dict sur une colonne JSON
        try:
            value = arg({})
        except Exception:
            return None
        if value == []:
            return "'[]'"
        if value == {}:
            return "'{}'"
        return None
    if arg is None:
        return None
    if isinstance(arg, bool):
        return ("1" if arg else "0") if dialect_name == "sqlite" else ("true" if arg else "false")
    if isinstance(arg, (int, float)):
        return repr(arg)
    if isinstance(arg, str):
        escaped = arg.replace("'", "''")
        return f"'{escaped}'"
    return None


def migrate_schema() -> None:
    """Ajoute les colonnes manquantes aux tables existantes.

    Les montées de version ajoutent des réglages (enveloppes, frais, analyse
    technique…) : sans cela, une base déjà déployée planterait au démarrage.
    Volontairement minimal — on ajoute, on ne supprime ni ne renomme jamais.
    """
    from sqlalchemy import inspect, text

    from . import models

    engine = get_engine()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    dialect = engine.dialect.name

    with engine.begin() as conn:
        for table in models.Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all vient de la créer, elle est à jour
            present = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in present:
                    continue
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}"
                literal = _literal_default(col, dialect)
                if literal is not None:
                    ddl += f" DEFAULT {literal}"
                    if not col.nullable:
                        ddl += " NOT NULL"
                conn.execute(text(ddl))
                log.info("Migration : colonne %s.%s ajoutée", table.name, col.name)


def init_db() -> None:
    from . import models  # noqa: F401

    models.Base.metadata.create_all(get_engine())
    migrate_schema()
