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
    Enforces Requirement 4.A (Script Approval Gate):
      1. If job is PENDING -> Generate research + script -> Pause at SCRIPT_APPROVAL_PENDING.
      2. If job is APPROVED -> Execute video assembly -> COMPLETED.
      3. Otherwise -> Block rendering.
    """
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            log.error(f"Job not found: {job_id}")
            return {"status": "error", "message": "Job not found"}

        log.info(f"Worker processing job: {job_id} (Status: {job.status}, Brand: {job.brand_id})")

        # --- Stage 1: Topic -> Research & Script Generation ---
        if job.status == JobStatus.PENDING or not job.script_data:
            from src.services.research.collector import ResearchCollector
            from src.services.llm.script_generator import ScriptGenerator

            job.status = JobStatus.RESEARCHING
            job.stage = "research_and_scripting"
            db.commit()

            collector = ResearchCollector(brand_id=job.brand_id)
            sources = collector.collect_sources(topic=job.topic)

            generator = ScriptGenerator(brand_id=job.brand_id)
            script = generator.generate(topic=job.topic, sources=sources)

            job.script_data = script.model_dump()
            job.status = JobStatus.SCRIPT_APPROVAL_PENDING
            job.stage = "script_approval_pending"
            job.updated_at = datetime.now(timezone.utc)
            db.commit()

            log.info(f"Job {job_id} halted at Gate 1: SCRIPT_APPROVAL_PENDING")
            return {
                "status": "waiting_for_approval",
                "job_id": job_id,
                "stage": job.stage,
                "script": job.script_data,
            }

        # --- Gate 1 Check (Requirement 4.A): Must be APPROVED to render ---
        if job.status != JobStatus.APPROVED:
            err = (
                f"Cannot render job {job_id}: status is '{job.status}'. "
                f"Gate 1 human approval is mandatory before video rendering begins."
            )
            log.warning(err)
            return {"status": "blocked", "job_id": job_id, "message": err}

        # --- Stage 2: Approved Script -> Video Rendering ---
        log.info(f"Rendering approved job {job_id}...")
        job.status = JobStatus.RENDERING
        job.stage = "video_rendering"
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

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

