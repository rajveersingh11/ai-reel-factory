"""
Database Engine & Session Management
====================================
Configures SQLAlchemy with PostgreSQL (or SQLite local fallback).
Provides session dependencies for FastAPI route handlers and Celery tasks.
"""

from __future__ import annotations

import logging
import socket
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from src.core.config import settings

log = logging.getLogger("reelfactory.db")

Base = declarative_base()


def _get_engine():
    import os
    db_url = os.environ.get("DATABASE_URL") or settings.DATABASE_URL

    # Support SQLite connect args
    if db_url.startswith("sqlite"):
        return create_engine(db_url, connect_args={"check_same_thread": False})

    # Connect to PostgreSQL with connection pooling
    return create_engine(
        db_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


engine = _get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all registered database tables."""
    # Ensure models are imported so their metadata is attached to Base
    import src.models.job  # noqa: F401
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for yielding database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
