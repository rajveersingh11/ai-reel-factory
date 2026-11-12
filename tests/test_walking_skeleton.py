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
from src.models.job import Job, JobStatus
from src.api.routes.jobs import create_job, get_job_status, list_jobs
from src.api.routes.production import submit_video_decision, VideoApprovalDecision
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

    # 2. Worker executes research + script generation, pausing at Gate 1
    result1 = execute_job_pipeline(job.id)
    assert result1["status"] == "waiting_for_approval"

    db.expire_all()
    job = db.query(Job).filter(Job.id == job.id).first()
    assert job is not None
    assert job.status == JobStatus.SCRIPT_APPROVAL_PENDING

    # 3. Gate 1: Human approves script
    job.status = JobStatus.APPROVED
    db.commit()

    # 4. Worker executes rendering on approved script -> pauses at Gate 2
    result2 = execute_job_pipeline(job.id)
    assert result2["status"] == "completed"

    # 5. Verify database persistence at Gate 2 (FINAL_APPROVAL_PENDING)
    db.expire_all()
    rendered_job = get_job_status(job.id, db)
    assert rendered_job is not None
    assert rendered_job.status == JobStatus.FINAL_APPROVAL_PENDING
    assert rendered_job.stage == "final_approval_pending"
    assert rendered_job.video_path is not None
    assert rendered_job.updated_at >= rendered_job.created_at

    # Gate 2: Final human video approval transitions to COMPLETED
    approval_res = submit_video_decision(
        job_id=job.id,
        decision_payload=VideoApprovalDecision(decision="approve"),
        db=db,
    )
    assert approval_res["decision"] == "approved"

    db.expire_all()
    completed_job = get_job_status(job.id, db)
    assert completed_job is not None
    assert completed_job.status == JobStatus.COMPLETED
    assert completed_job.stage == "approved_for_publishing"

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
