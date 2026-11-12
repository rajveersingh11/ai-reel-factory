"""
Walking Skeleton Integration Tests
==================================
Tests Phase 2 Milestone:
  1. Job creation & validation (Pydantic + SQLAlchemy)
  2. Multi-brand partitioning (Requirement 4.B)
  3. Asynchronous worker pipeline execution (PENDING -> RENDERING -> COMPLETED)
  4. Querying job status and output artifacts
"""

from __future__ import annotations

from fastapi import BackgroundTasks
from src.core.database import SessionLocal, init_db
from src.schemas.job import JobCreateRequest
from src.models.job import JobStatus
from src.api.routes.jobs import create_job, get_job_status, list_jobs
from src.workers.tasks import execute_job_pipeline


def setup_module():
    """Ensure database schema is created before tests."""
    init_db()


def test_job_creation_and_lifecycle():
    db = SessionLocal()
    bg = BackgroundTasks()

    # 1. Submit a new Reel job for SKYON IT SOLUTIONS
    req = JobCreateRequest(
        brand_id="skyon",
        topic="Automating B2B Lead Generation with Open Source LLMs",
    )
    job = create_job(req, bg, db)

    assert job.id is not None
    assert job.brand_id == "skyon"
    assert job.status == JobStatus.PENDING
    assert job.stage == "queued"

    # 2. Worker executes the job pipeline
    result = execute_job_pipeline(job.id)
    assert result["status"] == "completed"

    # 3. Verify database persistence and final status
    db.expire_all()
    completed_job = get_job_status(job.id, db)
    assert completed_job.status == JobStatus.COMPLETED
    assert completed_job.stage == "completed"
    assert completed_job.video_path is not None
    assert completed_job.updated_at >= completed_job.created_at

    db.close()


def test_multi_brand_partitioning():
    db = SessionLocal()
    bg = BackgroundTasks()

    # Create job for Brand 1 (SKYON)
    job_skyon = create_job(
        JobCreateRequest(brand_id="skyon", topic="Cloud DevOps Pipeline Architecture"),
        bg,
        db,
    )

    # Create job for Brand 2 (R4Realty)
    job_r4 = create_job(
        JobCreateRequest(brand_id="r4realty", topic="Modern Architectural Villas 2025"),
        bg,
        db,
    )

    assert job_skyon.brand_id == "skyon"
    assert job_r4.brand_id == "r4realty"

    # Query Skyon jobs
    skyon_list = list_jobs("skyon", 50, db)
    assert all(j.brand_id == "skyon" for j in skyon_list)
    assert any(j.id == job_skyon.id for j in skyon_list)

    # Query R4Realty jobs
    r4_list = list_jobs("r4realty", 50, db)
    assert all(j.brand_id == "r4realty" for j in r4_list)
    assert any(j.id == job_r4.id for j in r4_list)

    db.close()
