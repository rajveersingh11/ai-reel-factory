"""
Phase 5 Test Suite: Instagram Reels Publishing & Gate 2 Prerequisite Verification
================================================================================
Validates:
  1. Gate 2 prerequisite: Non-approved jobs are strictly blocked from publishing.
  2. Idempotency: Duplicate publishing attempts are blocked.
  3. AI transparency disclosure compliance (#AIgenerated).
  4. Publishing REST API endpoints and video serving endpoint.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

from src.core.database import SessionLocal, init_db
from src.models.job import Job, JobStatus
from src.services.publishing.instagram import InstagramPublisher
from src.api.routes.publishing import publish_to_instagram, InstagramPublishRequest
from src.api.routes.jobs import get_job_video


@pytest.fixture(autouse=True)
def setup_db():
    init_db()


def test_publishing_strictly_requires_gate_2_approval():
    """Ensure videos CANNOT be published if Gate 2 approval was not granted."""
    db = SessionLocal()
    publisher = InstagramPublisher(mock_mode=True)

    # 1. Job in PENDING status
    job_pending = Job(
        brand_id="skyon",
        topic="Cloud Security Posture",
        status=JobStatus.PENDING,
        stage="queued",
    )
    db.add(job_pending)
    db.commit()

    with pytest.raises(ValueError, match="Gate 2 final human video approval is mandatory"):
        publisher.publish_reel(job_pending, db)

    # 2. Job in FINAL_APPROVAL_PENDING (rendered and QC passed, but human hasn't clicked Approve yet)
    job_unapproved_video = Job(
        brand_id="skyon",
        topic="Cloud Security Posture 2",
        status=JobStatus.FINAL_APPROVAL_PENDING,
        stage="final_approval_pending",
    )
    db.add(job_unapproved_video)
    db.commit()

    with pytest.raises(ValueError, match="Gate 2 final human video approval is mandatory"):
        publisher.publish_reel(job_unapproved_video, db)

    db.close()


def test_idempotent_publishing_prevents_duplicate_posts():
    """Verify published jobs cannot be published twice to avoid spamming social feeds."""
    db = SessionLocal()
    publisher = InstagramPublisher(mock_mode=True)

    # Create and approve job at Gate 2
    job = Job(
        brand_id="skyon",
        topic="Automated AI Workflows",
        status=JobStatus.COMPLETED,
        stage="approved_for_publishing",
        script_data={"topic": "Automated AI Workflows", "call_to_action": "Follow Skyon"},
    )
    db.add(job)
    db.commit()

    # First publish attempt -> SUCCESS
    res1 = publisher.publish_reel(job, db)
    assert res1["status"] == "published"
    assert res1["instagram_media_id"] is not None
    assert "https://www.instagram.com/reel/" in res1["instagram_permalink"]

    db.expire_all()
    job_refreshed = db.query(Job).filter(Job.id == job.id).first()
    assert job_refreshed.status == JobStatus.PUBLISHED
    assert job_refreshed.instagram_media_id == res1["instagram_media_id"]

    # Second publish attempt -> IDEMPOTENT ABORT (No duplicates)
    res2 = publisher.publish_reel(job_refreshed, db)
    assert res2["status"] == "already_published"
    assert res2["instagram_media_id"] == res1["instagram_media_id"]
    assert "duplicate" in res2["message"].lower()

    db.close()


def test_ai_transparency_disclosure_in_caption():
    """Verify Meta 2024 AI content transparency requirements (#AIgenerated)."""
    publisher = InstagramPublisher(mock_mode=True)
    job = Job(
        brand_id="r4realty",
        topic="Dubai Waterfront Penthouse Yields",
        status=JobStatus.COMPLETED,
        stage="approved_for_publishing",
        script_data={"call_to_action": "Book your private consultation today."},
    )

    caption = publisher._format_caption(job)
    assert "#AIgenerated" in caption
    assert "#AIVideoCreated" in caption
    assert "#r4realty" in caption
    assert "R4Realty" in caption
    assert "Dubai Waterfront Penthouse Yields" in caption


def test_publishing_api_endpoint_workflow():
    """Test the FastAPI route handlers for publishing."""
    db = SessionLocal()

    # 1. Test unapproved job rejection via API route
    unapproved = Job(
        brand_id="skyon",
        topic="API Test Topic",
        status=JobStatus.SCRIPT_APPROVAL_PENDING,
        stage="script_approval_pending",
    )
    db.add(unapproved)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        publish_to_instagram(unapproved.id, None, db)
    assert exc_info.value.status_code == 400
    assert "Gate 2" in exc_info.value.detail

    # 2. Test approved job success via API route
    approved = Job(
        brand_id="skyon",
        topic="API Test Approved Topic",
        status=JobStatus.COMPLETED,
        stage="approved_for_publishing",
        script_data={"call_to_action": "Visit skyon.io"},
    )
    db.add(approved)
    db.commit()

    api_res = publish_to_instagram(
        approved.id,
        InstagramPublishRequest(custom_caption="Custom VIP Reel Caption #AIgenerated"),
        db,
    )
    assert api_res.status == "published"
    assert api_res.instagram_media_id is not None
    assert api_res.instagram_permalink is not None

    db.close()


def test_video_download_route(tmp_path):
    """Test video file serving endpoint."""
    db = SessionLocal()

    # Non-existent job -> 404
    with pytest.raises(HTTPException) as exc_info:
        get_job_video("fake-job-id-9999", db)
    assert exc_info.value.status_code == 404

    # Existing job with real video file -> 200 FileResponse
    dummy_video = tmp_path / "test_serve.mp4"
    dummy_video.write_bytes(b"dummy mp4 video bytes")

    job = Job(
        brand_id="skyon",
        topic="Video Serve Test",
        status=JobStatus.COMPLETED,
        stage="approved_for_publishing",
        video_path=str(dummy_video),
    )
    db.add(job)
    db.commit()

    resp = get_job_video(job.id, db)
    assert isinstance(resp, FileResponse)
    assert resp.path == str(dummy_video)
    assert resp.media_type == "video/mp4"

    db.close()

