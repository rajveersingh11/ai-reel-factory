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
    """Create all registered database tables and apply lightweight dev migrations."""
    # Ensure models are imported so their metadata is attached to Base
    import src.models.job  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Lightweight dev column migration for existing SQLite databases
    try:
        with engine.connect() as conn:
            from sqlalchemy import text
            res = conn.execute(text("PRAGMA table_info(jobs)"))
            cols = [r[1] for r in res.fetchall()]
            if cols:
                if "instagram_media_id" not in cols:
                    conn.execute(text("ALTER TABLE jobs ADD COLUMN instagram_media_id VARCHAR(100)"))
                if "instagram_permalink" not in cols:
                    conn.execute(text("ALTER TABLE jobs ADD COLUMN instagram_permalink VARCHAR(500)"))
                if "published_at" not in cols:
                    conn.execute(text("ALTER TABLE jobs ADD COLUMN published_at DATETIME"))
                conn.commit()
    except Exception as e:
        log.warning(f"Dev database schema sync note: {e}")


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for yielding database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
