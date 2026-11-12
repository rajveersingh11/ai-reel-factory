"""
Celery Application Configuration
================================
Configures Celery with Redis broker.
Enforces worker concurrency = 1 (Requirement 2: 8 GB RAM discipline).
"""

from __future__ import annotations

import os
import sys
from src.core.config import settings

try:
    from celery import Celery

    celery_app = Celery(
        "reelfactory",
        broker=settings.REDIS_URL,
        backend=settings.REDIS_URL,
        include=["src.workers.tasks"],
    )

    # Windows requires 'solo' pool to prevent prefork process lockups
    is_windows = sys.platform.startswith("win")
    
    celery_app.conf.update(
        worker_concurrency=settings.CELERY_CONCURRENCY,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        worker_pool="solo" if is_windows else "prefork",
        broker_connection_retry=False,
        broker_connection_retry_on_startup=False,
        broker_connection_max_retries=1,
        redis_max_connections=5,
        result_backend_transport_options={"max_retries": 0},
    )
except ImportError:
    celery_app = None

