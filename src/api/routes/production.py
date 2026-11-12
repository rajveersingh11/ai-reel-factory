"""
Video Production & Gate 2 Final Approval API Routes
===================================================
Enforces Requirement 4.F:
  - Gate 2: Final human video approval before publication.
  - Never publish automatically without explicit human approval.
  - Endpoints to inspect deterministic QC reports and submit sign-off decisions.
"""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.job import Job, JobStatus

log = logging.getLogger("reelfactory.api.production")
router = APIRouter(prefix="/jobs/{job_id}", tags=["Production & Gate 2 Approval"])


class VideoApprovalDecision(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$", description="approve or reject")
    notes: Optional[str] = Field(default=None, description="Human reviewer notes")


@router.get("/qc", status_code=status.HTTP_200_OK)
def get_job_qc_report(job_id: str, db: Session = Depends(get_db)):
    """Retrieve the automated ffprobe deterministic quality control report."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")
    if not job.qc_report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No QC report available. The job has not been rendered yet.",
        )
    return job.qc_report


@router.post("/video/decision", status_code=status.HTTP_200_OK)
def submit_video_decision(
    job_id: str,
    decision_payload: VideoApprovalDecision,
    db: Session = Depends(get_db),
):
    """
    Gate 2: Final human approval before publication (Requirement 4.F).
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")

    if job.status != JobStatus.FINAL_APPROVAL_PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot submit video decision: job status is '{job.status}'. "
                f"Must be in 'FINAL_APPROVAL_PENDING' status."
            ),
        )

    action = decision_payload.decision.lower().strip()

    if action == "approve":
        job.status = JobStatus.COMPLETED
        job.stage = "approved_for_publishing"
        db.commit()
        log.info(f"Job {job_id} FINAL VIDEO APPROVED. Ready for publishing (Phase 5).")
        return {
            "job_id": job.id,
            "decision": "approved",
            "status": job.status,
            "message": "Final video approved. Ready for social publishing.",
            "video_path": job.video_path,
        }

    elif action == "reject":
        job.status = JobStatus.REJECTED
        job.stage = "rejected_at_final_approval"
        db.commit()
        log.info(f"Job {job_id} FINAL VIDEO REJECTED.")
        return {
            "job_id": job.id,
            "decision": "rejected",
            "status": job.status,
            "message": "Video rejected by human reviewer. Publishing cancelled.",
        }

