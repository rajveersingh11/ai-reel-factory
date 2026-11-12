"""
Automated Video Production & Gate 2 Tests
=========================================
Verifies Phase 4 Acceptance Criteria:
  1. Scene-to-footage matching & threshold rejection (Requirement 4.D)
  2. Fallback to dynamic branded statistic cards
  3. Deterministic Quality Control via ffprobe (Requirement 4.E)
  4. End-to-end production flow from approved script to rendered MP4
  5. Gate 2 Human Final Video Approval (Requirement 4.F)
"""

from __future__ import annotations

from pathlib import Path
from fastapi import BackgroundTasks

from src.core.database import SessionLocal, init_db
from src.models.job import Job, JobStatus
from src.schemas.job import JobCreateRequest
from src.schemas.script import ScriptApprovalDecision
from src.services.media.stock_matcher import StockMatcher
from src.services.video.qc_engine import QCEngine
from src.api.routes.jobs import create_job
from src.api.routes.scripts import submit_script_decision
from src.api.routes.production import submit_video_decision, get_job_qc_report, VideoApprovalDecision
from src.workers.tasks import execute_job_pipeline


def setup_module():
    """Ensure database schema is created."""
    init_db()


def test_footage_matcher_rejects_irrelevant_and_triggers_card_fallback():
    """Requirement 4.D: Irrelevant footage must be rejected and trigger card fallback."""
    matcher = StockMatcher(brand_id="skyon", match_threshold=0.75)

    # Search for an unrelated query with no local matching video
    result = matcher.match_scene(
        scene_id="s01",
        keywords=["astronomy", "deep galaxy telescope"],
        duration_seconds=10.0,
    )

    # Must reject and trigger fallback card
    assert result.matched is False
    assert result.fallback_card_needed is True
    assert result.score < 0.75
    assert "No candidate" in result.reason or "below threshold" in result.reason


def test_deterministic_qc_engine_on_valid_video():
    """Requirement 4.E: ffprobe validates measurable criteria."""
    sample_video = Path("spikes/phase1_rendering/output/reel_spike_v1.mp4").resolve()
    assert sample_video.exists(), "Phase 1 spike video must exist to run QC test"

    qc = QCEngine(target_width=1080, target_height=1920, min_duration=55.0, max_duration=65.0)
    report = qc.inspect(sample_video)

    assert report.overall_passed is True
    assert report.fatal_errors == 0

    # Verify specific deterministic checks
    checks_dict = {c.check_name: c for c in report.checks}
    assert checks_dict["Resolution"].passed is True
    assert checks_dict["Resolution"].actual_value == "1080x1920"
    assert checks_dict["Video Codec"].passed is True
    assert checks_dict["Audio Codec"].passed is True


def test_gate_2_final_video_approval_workflow():
    """Requirement 4.F: Gate 2 final approval before publishing."""
    db = SessionLocal()
    bg = BackgroundTasks()

    # 1. Create job and approve script (Gate 1)
    job = create_job(JobCreateRequest(brand_id="skyon", topic="AI Edge Computing 2025"), bg, db)
    execute_job_pipeline(job.id)  # Generates script, halts at SCRIPT_APPROVAL_PENDING
    db.expire_all()

    submit_script_decision(
        job_id=job.id,
        decision_payload=ScriptApprovalDecision(decision="approve"),
        db=db,
    )

    # 2. Worker executes production pipeline on approved script
    prod_res = execute_job_pipeline(job.id)
    assert prod_res["status"] == "completed"

    db.expire_all()
    rendered_job = db.query(Job).filter(Job.id == job.id).first()
    
    # Must halt at Gate 2: FINAL_APPROVAL_PENDING
    assert rendered_job.status == JobStatus.FINAL_APPROVAL_PENDING
    assert rendered_job.stage == "final_approval_pending"
    assert rendered_job.video_path is not None
    assert rendered_job.qc_report is not None
    assert rendered_job.qc_report["overall_passed"] is True

    # 3. Retrieve QC report via API
    qc_data = get_job_qc_report(job.id, db)
    assert qc_data["overall_passed"] is True

    # 4. Gate 2 Human Decision: APPROVE for publishing
    approval_res = submit_video_decision(
        job_id=job.id,
        decision_payload=VideoApprovalDecision(decision="approve", notes="Excellent pacing and typography."),
        db=db,
    )
    assert approval_res["decision"] == "approved"

    db.expire_all()
    final_job = db.query(Job).filter(Job.id == job.id).first()
    assert final_job.status == JobStatus.COMPLETED
    assert final_job.stage == "approved_for_publishing"

    db.close()
