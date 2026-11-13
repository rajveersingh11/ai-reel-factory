"""
Application Configuration & Settings
====================================
Uses Pydantic Settings to load and validate environment variables.
Enforces multi-brand configuration and hardware resource caps.
"""

from __future__ import annotations

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Project metadata ---
    PROJECT_NAME: str = "AI Reel Factory"
    VERSION: str = "0.1.0"
    DEBUG: bool = False

    # --- Multi-Brand defaults (Requirement 4.B) ---
    DEFAULT_BRAND_ID: str = "skyon"

    # --- Paths ---
    STORAGE_ROOT: Path = PROJECT_ROOT / "storage"
    ASSET_ROOT: Path = PROJECT_ROOT / "assets"
    FONTS_DIR: Path = PROJECT_ROOT / "assets" / "fonts"

    # --- Database ---
    # Default to local SQLite for lightweight local-first development.
    # Set to PostgreSQL in .env when running via Docker Compose.
    DATABASE_URL: str = f"sqlite:///{PROJECT_ROOT / 'storage' / 'reelfactory_dev.db'}"

    # --- Celery & Redis (Strict Concurrency = 1 for 8 GB RAM) ---
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_CONCURRENCY: int = 1

    # --- Piper TTS ---
    PIPER_MODELS_DIR: Path = PROJECT_ROOT / "assets" / "models" / "piper"
    DEFAULT_VOICE: str = "en_US-lessac-medium"

    # --- Video / Reel Constraints ---
    TARGET_WIDTH: int = 1080
    TARGET_HEIGHT: int = 1920
    TARGET_FPS: int = 30
    TARGET_DURATION_MIN: float = 55.0
    TARGET_DURATION_MAX: float = 65.0
    TARGET_LOUDNESS_LUFS: float = -14.0

    # --- Publishing & Meta Graph API (Phase 5) ---
    META_GRAPH_API_VERSION: str = "v21.0"
    INSTAGRAM_ACCESS_TOKEN: str = ""
    INSTAGRAM_BUSINESS_ACCOUNT_ID: str = ""
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # --- Free Stock Footage APIs (Pexels & Pixabay) ---
    PEXELS_API_KEY: str = ""
    PIXABAY_API_KEY: str = ""
    ENABLE_STOCK_API: bool = True
    STOCK_CACHE_DIR: Path = PROJECT_ROOT / "storage" / "cache" / "stock"


settings = Settings()
