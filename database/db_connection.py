import logging
import os
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

import config  # noqa: F401  (loads .env before DATABASE_URL is read)

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DEFAULT_URL = "postgresql://trend_user:trend_password@localhost:5432/trend_db"

Base = declarative_base()
_engine: Optional[Engine] = None
SessionLocal = None


def normalize_url(url: str) -> str:
    """Pin the psycopg2 driver (SQLAlchemy 2.1 defaults 'postgresql://' to psycopg 3)
    and accept Heroku-style 'postgres://' URLs."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


def get_engine() -> Optional[Engine]:
    """Create the engine lazily so tests/CLI can set DATABASE_URL first."""
    global _engine, SessionLocal
    if _engine is None:
        url = normalize_url(os.getenv("DATABASE_URL", DEFAULT_URL))
        try:
            # Hour buckets are computed in UTC everywhere, so pin the session time zone.
            _engine = create_engine(url, pool_size=10, max_overflow=20, pool_pre_ping=True,
                                    connect_args={"options": "-c timezone=utc"})
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
        except Exception as e:
            logger.error("Failed to initialize database engine: %s", e)
            _engine = None
    return _engine


def reset_engine(url: Optional[str] = None) -> Optional[Engine]:
    """Dispose the current engine and (optionally) point at a new URL."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None
    if url:
        os.environ["DATABASE_URL"] = url
    return get_engine()


def init_db() -> None:
    """Apply schema.sql. Idempotent: safe on new and existing databases."""
    engine = get_engine()
    if engine is None:
        raise RuntimeError("Database engine is not available")
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)
    logger.info("Database schema is up to date.")


def get_db():
    get_engine()
    if SessionLocal is None:
        logger.error("Database session factory is not initialized.")
        yield None
        return
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def __getattr__(name):
    # Backwards compatibility for `from database.db_connection import engine`.
    if name == "engine":
        return get_engine()
    raise AttributeError(name)
