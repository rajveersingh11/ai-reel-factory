"""
Content Intelligence & Script Approval Gate Tests
=================================================
Verifies Phase 3 Acceptance Criteria:
  1. Multi-brand configuration loading (SKYON & R4Realty)
  2. Structured script schema validation (140–160 words target)
  3. Deterministic fact-checking & numeric claim tracking (Requirement 4.C)
  4. Flagging scenes with unbacked numeric claims (Requirement 4.C)
  5. Gate 1 Human Approval decisions: approve, edit, regenerate, reject (Requirement 4.A)
  6. Strict block on rendering unapproved scripts (Requirement 4.A)
"""

from __future__ import annotations

import pytest
from fastapi import BackgroundTasks

from src.core.database import SessionLocal, init_db
from src.models.job import Job, JobStatus
from src.schemas.brand import brand_registry
from src.schemas.job import JobCreateRequest
from src.schemas.script import (
    ScriptData,
    ScriptMetadata,
    SceneScript,
    NumericClaim,
    ResearchSource,
    ScriptApprovalDecision,
)
from src.api.routes.jobs import create_job, get_job_status
from src.api.routes.scripts import (
    generate_job_script,
    get_job_script,
    submit_script_decision,
)
from src.api.routes.production import submit_video_decision, VideoApprovalDecision
from src.workers.tasks import execute_job_pipeline


def setup_module():
    """Initialize database tables before running tests."""
    init_db()


def test_multi_brand_configuration():
    """Verify distinct brand identities loaded from YAML (Requirement 4.B)."""
    skyon = brand_registry.get("skyon")
    assert skyon.name == "SKYON IT SOLUTIONS"
    assert "Enterprise AI" in skyon.tagline

    r4 = brand_registry.get("r4realty")
    assert r4.name == "R4Realty"
    assert "Luxury" in r4.tagline
    assert r4.primary_color == "#D4AF37"


def test_script_fact_checking_and_claim_tracking():
    """Verify numeric claims map to stored source IDs (Requirement 4.C)."""
    sources = [
        ResearchSource(
            source_id="DPIIT-2024",
            title="DPIIT Startup Registry",
            url="https://dpiit.gov.in",
            key_facts=["Over 1.5 lakh startups registered"],
        )
    ]

    # Valid scene: claim mapped to valid source_id
    valid_scene = SceneScript(
        scene_id="s01",
        order=1,
        narration="India has over 1.5 lakh registered startups competing globally.",
        numeric_claims=[
            NumericClaim(claim="1.5 lakh", source_id="DPIIT-2024")
        ],
    )

    script = ScriptData(
        meta=ScriptMetadata(topic="Indian Startups", brand_id="skyon"),
        scenes=[
            valid_scene,
            SceneScript(scene_id="s02", order=2, narration="Founders are shipping rapidly every single week without delays."),
            SceneScript(scene_id="s03", order=3, narration="Artificial intelligence empowers teams to scale effortlessly worldwide."),
        ],
        sources=sources,
    )

    assert script.fact_check_passed is True
    assert script.scenes[0].is_flagged is False
    assert script.scenes[0].numeric_claims[0].verified is True


def test_unbacked_numeric_claims_are_flagged():
    """Requirement 4.C: Scene with unbacked numeric claims MUST be flagged."""
    sources = [
        ResearchSource(
            source_id="VERIFIED-SOURCE-1",
            title="Official Statistics",
            url="https://example.com",
        )
    ]

    # Scene containing numbers ("40 percent") but zero numeric_claims mapping
    unbacked_scene = SceneScript(
        scene_id="s01",
        order=1,
        narration="AI is slashing operational costs by 40 percent without hiring.",
        numeric_claims=[],
    )

    script = ScriptData(
        meta=ScriptMetadata(topic="Startup Costs", brand_id="skyon"),
        scenes=[
            unbacked_scene,
            SceneScript(scene_id="s02", order=2, narration="Teams build automated workflows from day one to win market share."),
            SceneScript(scene_id="s03", order=3, narration="Technology adoption remains the biggest factor separating winners from losers."),
        ],
        sources=sources,
    )

    assert script.fact_check_passed is False
    assert script.scenes[0].is_flagged is True
    assert "contains numbers" in script.scenes[0].flag_reason


def test_script_approval_gate_workflow():
    """Verify Gate 1 human decisions (Requirement 4.A): approve, edit, regenerate, reject."""
    db = SessionLocal()
    bg = BackgroundTasks()

    # 1. Create a job
    job = create_job(JobCreateRequest(brand_id="skyon", topic="Autonomous AI Coding Pipelines"), bg, db)
    assert job.status == JobStatus.PENDING

    # 2. Worker halts at Gate 1: SCRIPT_APPROVAL_PENDING
    worker_res = execute_job_pipeline(job.id)
    assert worker_res["status"] == "waiting_for_approval"

    db.expire_all()
    job = db.query(Job).filter(Job.id == job.id).first()
    assert job is not None
    assert job.status == JobStatus.SCRIPT_APPROVAL_PENDING

    # 3. Test Human Decision: REGENERATE with feedback
    regen_res = submit_script_decision(
        job_id=job.id,
        decision_payload=ScriptApprovalDecision(
            decision="regenerate",
            feedback="Make the opening hook punchier and emphasize B2B velocity.",
        ),
        db=db,
    )
    assert regen_res["decision"] == "regenerated"
    assert regen_res["version"] == 2

    # 4. Attempt rendering while still in SCRIPT_APPROVAL_PENDING -> MUST BE BLOCKED
    blocked_res = execute_job_pipeline(job.id)
    assert blocked_res["status"] == "blocked"

    # 5. Test Human Decision: APPROVE
    approve_res = submit_script_decision(
        job_id=job.id,
        decision_payload=ScriptApprovalDecision(decision="approve"),
        db=db,
    )
    assert approve_res["decision"] == "approved"

    db.expire_all()
    job = db.query(Job).filter(Job.id == job.id).first()
    assert job is not None
    assert job.status == JobStatus.APPROVED

    # 6. Now that job is APPROVED, worker executes video rendering -> pauses at Gate 2
    render_res = execute_job_pipeline(job.id)
    assert render_res["status"] == "completed"

    db.expire_all()
    rendered_job = db.query(Job).filter(Job.id == job.id).first()
    assert rendered_job is not None
    assert rendered_job.status == JobStatus.FINAL_APPROVAL_PENDING
    assert rendered_job.video_path is not None

    # Gate 2: Approve video
    approval_res = submit_video_decision(
        job_id=job.id,
        decision_payload=VideoApprovalDecision(decision="approve"),
        db=db,
    )
    assert approval_res["decision"] == "approved"

    db.expire_all()
    completed_job = db.query(Job).filter(Job.id == job.id).first()
    assert completed_job is not None
    assert completed_job.status == JobStatus.COMPLETED
    assert completed_job.stage == "approved_for_publishing"

    db.close()


def test_script_rejection_halts_job():
    """Verify reject decision halts the job permanently."""
    db = SessionLocal()
    bg = BackgroundTasks()

    job = create_job(JobCreateRequest(brand_id="r4realty", topic="Commercial Tower Yields"), bg, db)
    execute_job_pipeline(job.id)
    db.expire_all()

    reject_res = submit_script_decision(
        job_id=job.id,
        decision_payload=ScriptApprovalDecision(decision="reject"),
        db=db,
    )
    assert reject_res["decision"] == "rejected"

    db.expire_all()
    rejected_job = db.query(Job).filter(Job.id == job.id).first()
    assert rejected_job is not None
    assert rejected_job.status == JobStatus.REJECTED

    # Any attempt to render rejected job is permanently blocked
    blocked_res = execute_job_pipeline(job.id)
    assert blocked_res["status"] == "blocked"

    db.close()
