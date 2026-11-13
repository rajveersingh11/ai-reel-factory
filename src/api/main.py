"""
FastAPI Application Entry Point
===============================
Wires API routes, database initialization, and middleware.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import settings
from src.core.database import init_db
from src.api.routes.jobs import router as jobs_router
from src.api.routes.scripts import router as scripts_router
from src.api.routes.production import router as production_router
from src.api.routes.publishing import router as publishing_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("reelfactory")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: run database migrations/init on startup."""
    log.info("Initializing AI Reel Factory database schema...")
    init_db()
    log.info("AI Reel Factory Backend ready.")
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Local-first AI short-form video production platform.",
    lifespan=lifespan,
)

# CORS Middleware (allows local dev dashboards like Streamlit/Next.js)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(scripts_router, prefix="/api/v1")
app.include_router(production_router, prefix="/api/v1")
app.include_router(publishing_router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
def health_check():
    """Verify backend health status."""
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
    }


@app.get("/", tags=["Root"])
def root():
    return {
        "message": "Welcome to AI Reel Factory API",
        "docs": "/docs",
        "health": "/health",
    }

