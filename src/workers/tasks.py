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

        from src.services.video.production_pipeline import ProductionPipeline
        from src.schemas.script import ScriptData
        from src.core.config import settings

        pipeline = ProductionPipeline(brand_id=job.brand_id)
        script_obj = ScriptData(**job.script_data)
        job_output_dir = settings.STORAGE_ROOT / "jobs" / job_id

        final_video_path, qc_report = pipeline.produce(
            script=script_obj,
            output_dir=job_output_dir,
            job_id=job_id,
        )

        job.video_path = str(final_video_path.resolve())
        job.qc_report = qc_report.to_dict()

        if qc_report.overall_passed:
            # Gate 2 (Requirement 4.F): Stop and hold for Final Human Approval before publishing!
            job.status = JobStatus.FINAL_APPROVAL_PENDING
            job.stage = "final_approval_pending"
            log.info(f"Job {job_id} rendered and passed QC. Halted at Gate 2: FINAL_APPROVAL_PENDING")
        else:
            job.status = JobStatus.FAILED
            job.stage = "qc_failed"
            job.error_message = f"QC inspection failed with {qc_report.fatal_errors} fatal error(s)."
            log.error(f"Job {job_id} failed QC checks.")

        job.updated_at = datetime.now(timezone.utc)
        db.commit()

        return {
            "status": "completed" if qc_report.overall_passed else "failed",
            "job_id": job_id,
            "video_path": job.video_path,
            "qc_passed": qc_report.overall_passed,
        }

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

