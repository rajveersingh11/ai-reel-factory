"""
Asynchronous Worker Tasks
=========================
Executes video production pipeline jobs asynchronously.
Updates job status in PostgreSQL.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from datetime import datetime, timezone

from src.core.database import SessionLocal
from src.models.job import Job, JobStatus
from src.workers.celery_app import celery_app

log = logging.getLogger("reelfactory.worker")


def execute_job_pipeline(job_id: str) -> dict:
    """
    Core pipeline worker logic.
    Transitions job through states and records intermediate artifacts.
    """
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            log.error(f"Job not found: {job_id}")
            return {"status": "error", "message": "Job not found"}

        log.info(f"Starting job execution: {job_id} (Brand: {job.brand_id})")
        
        # Step 1: Transition to PROCESSING / RENDERING
        job.status = JobStatus.RENDERING
        job.stage = "mock_video_rendering"
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

        # Step 2: Processing (Walking Skeleton mock execution or test render)
        # We simulate a 2-second pipeline step to verify async status polling
        time.sleep(2.0)

        # Check if the Phase 1 rendered video exists to link it as a real output artifact
        rendered_spike = Path("spikes/phase1_rendering/output/reel_spike_v1.mp4").resolve()
        if rendered_spike.exists():
            job.video_path = str(rendered_spike)
        else:
            job.video_path = f"storage/output/{job_id}.mp4"

        # Step 3: Transition to COMPLETED
        job.status = JobStatus.COMPLETED
        job.stage = "completed"
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

        log.info(f"Job successfully completed: {job_id}")
        return {"status": "completed", "job_id": job_id, "video_path": job.video_path}

    except Exception as exc:
        log.exception(f"Job execution failed: {job_id} — {exc}")
        db.rollback()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.FAILED
            job.stage = "failed"
            job.error_message = str(exc)
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
        return {"status": "failed", "job_id": job_id, "error": str(exc)}
    finally:
        db.close()


# Register Celery task if Celery is available
if celery_app:
    @celery_app.task(name="process_reel_job", bind=True)
    def process_reel_job(self, job_id: str):
        return execute_job_pipeline(job_id)
else:
    process_reel_job = None
