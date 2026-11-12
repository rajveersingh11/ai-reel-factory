"""
Job Management API Routes
=========================
FastAPI endpoints for initiating and monitoring video production jobs.
"""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.job import Job, JobStatus
from src.schemas.job import JobCreateRequest, JobResponse
from src.workers.tasks import process_reel_job, execute_job_pipeline

log = logging.getLogger("reelfactory.api")
router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    request: JobCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Initiate a new Reel production job.
    Persists job record and dispatches an asynchronous worker task.
    """
    # 1. Create and persist Job record
    job = Job(
        brand_id=request.brand_id.lower().strip(),
        topic=request.topic.strip(),
        status=JobStatus.PENDING,
        stage="queued",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # 2. Dispatch worker task
    dispatched_via_celery = False
    if process_reel_job:
        try:
            process_reel_job.delay(job.id)
            dispatched_via_celery = True
            log.info(f"Dispatched job {job.id} via Celery queue")
        except Exception as e:
            log.warning(f"Celery dispatch failed ({e}), falling back to background thread")

    if not dispatched_via_celery:
        # Graceful fallback for lean dev environments without running Redis
        background_tasks.add_task(execute_job_pipeline, job.id)
        log.info(f"Dispatched job {job.id} via FastAPI background task")

    return job


@router.get("/{job_id}", response_model=JobResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """
    Retrieve real-time processing status and output metadata for a given job.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with ID '{job_id}' not found.",
        )
    return job


@router.get("", response_model=list[JobResponse])
def list_jobs(
    brand_id: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """
    List jobs, optionally filtered by brand_id (Requirement 4.B).
    """
    query = db.query(Job)
    if brand_id:
        query = query.filter(Job.brand_id == brand_id.lower().strip())
    return query.order_by(Job.created_at.desc()).limit(limit).all()
