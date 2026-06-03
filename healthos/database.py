"""SQLAlchemy engine + session factory.

Use ``get_session()`` as a context manager for scripts/sync jobs, or the
``db_session`` FastAPI dependency for request handlers.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


engine = create_engine(
    settings.sync_db_url(),
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def get_session() -> Iterator[Session]:
    """Context-managed session that commits on success and rolls back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def db_session() -> Iterator[Session]:
    """FastAPI dependency. Read-mostly; handlers commit explicitly when needed."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
