"""
Script Management & Approval Gate API Routes
============================================
Enforces Requirement 4.A:
  - The workflow must stop after script validation.
  - A human must approve the script before rendering begins.
  - Decisions: approve, edit, regenerate, reject.
  - Never spend rendering resources on an unapproved script.
"""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.job import Job, JobStatus
from src.schemas.script import (
    ScriptData,
    ScriptApprovalDecision,
)
from src.services.research.collector import ResearchCollector
from src.services.llm.script_generator import ScriptGenerator

log = logging.getLogger("reelfactory.api.scripts")
router = APIRouter(prefix="/jobs/{job_id}/script", tags=["Script Approval Gate"])


@router.post("/generate", response_model=ScriptData, status_code=status.HTTP_200_OK)
def generate_job_script(job_id: str, db: Session = Depends(get_db)):
    """
    Research topic, generate structured script, and hold for human approval.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )

    log.info(f"Initiating research & script generation for job {job_id}")

    # 1. Collect verified research sources
    collector = ResearchCollector(brand_id=job.brand_id)
    sources = collector.collect_sources(topic=job.topic)

    # 2. Generate structured script
    generator = ScriptGenerator(brand_id=job.brand_id)
    script = generator.generate(topic=job.topic, sources=sources)

    # 3. Persist and stop at Gate 1 (Requirement 4.A)
    job.script_data = script.model_dump()
    job.status = JobStatus.SCRIPT_APPROVAL_PENDING
    job.stage = "script_approval_pending"
    db.commit()

    log.info(f"Job {job_id} is now gated at SCRIPT_APPROVAL_PENDING")
    return script


@router.get("", response_model=ScriptData)
def get_job_script(job_id: str, db: Session = Depends(get_db)):
    """Retrieve the current script and fact-check validation status."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")
    if not job.script_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No script generated for this job yet. Call /generate first.",
        )
    return ScriptData(**job.script_data)


@router.post("/decision", status_code=status.HTTP_200_OK)
def submit_script_decision(
    job_id: str,
    decision_payload: ScriptApprovalDecision,
    db: Session = Depends(get_db),
):
    """
    Submit human approval decision (Requirement 4.A):
      - approve: Unlock job for video rendering
      - edit: Apply human edits and bump version
      - regenerate: Re-prompt LLM with feedback
      - reject: Cancel job
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")

    action = decision_payload.decision.lower().strip()

    # Rejection can happen at any point in the workflow
    if action == "reject":
        job.status = JobStatus.REJECTED
        job.stage = "rejected_by_human"
        db.commit()
        log.info(f"Job {job_id} REJECTED by human operator.")
        return {
            "job_id": job.id,
            "decision": "rejected",
            "status": job.status,
            "message": "Script rejected. Job cancelled.",
        }

    if not job.script_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot approve or edit a job without a generated script.",
        )

    current_script = ScriptData(**job.script_data)

    if action == "approve":
        # Gate 1 passed!
        job.status = JobStatus.APPROVED
        job.stage = "script_approved"
        db.commit()
        log.info(f"Job {job_id} script APPROVED by human. Ready for video rendering.")
        return {
            "job_id": job.id,
            "decision": "approved",
            "status": job.status,
            "message": "Script approved. Ready for video rendering.",
        }

    elif action == "edit":
        if not decision_payload.edited_script:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="edited_script field is required when decision is 'edit'.",
            )
        edited = decision_payload.edited_script
        edited.version = current_script.version + 1
        job.script_data = edited.model_dump()
        job.status = JobStatus.APPROVED  # Explicit human edit counts as approval
        job.stage = "script_edited_and_approved"
        db.commit()
        log.info(f"Job {job_id} script EDITED and approved (v{edited.version}).")
        return {
            "job_id": job.id,
            "decision": "edited",
            "version": edited.version,
            "status": job.status,
            "message": f"Script updated to v{edited.version} and approved.",
        }

    elif action == "regenerate":
        collector = ResearchCollector(brand_id=job.brand_id)
        sources = collector.collect_sources(topic=job.topic)
        generator = ScriptGenerator(brand_id=job.brand_id)

        new_script = generator.generate(
            topic=job.topic,
            sources=sources,
            feedback=decision_payload.feedback,
        )
        new_script.version = current_script.version + 1

        job.script_data = new_script.model_dump()
        job.status = JobStatus.SCRIPT_APPROVAL_PENDING
        job.stage = "script_regenerated_pending_approval"
        db.commit()
        log.info(f"Job {job_id} script REGENERATED (v{new_script.version}). Pending approval.")
        return {
            "job_id": job.id,
            "decision": "regenerated",
            "version": new_script.version,
            "status": job.status,
            "message": "Script regenerated. Pending human approval.",
            "script": new_script,
        }

    elif action == "reject":
        job.status = JobStatus.REJECTED
        job.stage = "rejected_by_human"
        db.commit()
        log.info(f"Job {job_id} REJECTED by human operator.")
        return {
            "job_id": job.id,
            "decision": "rejected",
            "status": job.status,
            "message": "Script rejected. Job cancelled.",
        }

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown decision '{action}'. Use approve, edit, regenerate, or reject.",
        )
