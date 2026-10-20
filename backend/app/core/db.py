"""Database engine, session factory and declarative base."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_factory: sessionmaker | None = None


def get_engine() -> Engine:
    global _engine, _factory
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)
        _factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _factory = None


def session_factory() -> sessionmaker:
    get_engine()
    assert _factory is not None
    return _factory


@contextmanager
def db_session() -> Iterator[Session]:
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one transaction per request. Always declare it as `Depends(get_db, scope="function")`, so
    the commit happens before the response is sent: with the default "request" scope FastAPI commits only after the
    client has the response, so a client could act on a 200 before the change is visible (or a failed commit would
    already have been reported as success). Every use must share the same scope to share one session."""
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def notify(db: Session, channel: str, payload: str) -> None:
    """Queue a Postgres NOTIFY; delivered when the transaction commits."""
    db.execute(text("SELECT pg_notify(:c, :p)"), {"c": channel, "p": payload})
