"""
Publishing API Endpoints
========================
Provides endpoints for initiating and monitoring distribution of approved Reels
to social platforms (Meta Instagram Graph API v21.0).
"""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.models.job import Job, JobStatus
from src.services.publishing.instagram import InstagramPublisher, InstagramPublishError

log = logging.getLogger("reelfactory.api.publishing")
router = APIRouter(prefix="/publish", tags=["Publishing"])


class InstagramPublishRequest(BaseModel):
    custom_caption: Optional[str] = Field(None, description="Optional override caption")
    public_video_url: Optional[str] = Field(None, description="Optional public video URL for Meta ingest")


class InstagramPublishResponse(BaseModel):
    job_id: str
    status: str
    instagram_media_id: Optional[str] = None
    instagram_permalink: Optional[str] = None
    published_at: Optional[str] = None
    message: Optional[str] = None


@router.post("/instagram/{job_id}", response_model=InstagramPublishResponse)
def publish_to_instagram(
    job_id: str,
    payload: Optional[InstagramPublishRequest] = None,
    db: Session = Depends(get_db),
):
    """
    Publish a Gate 2 approved video to Instagram Reels.
    Guarantees idempotency and enforces Gate 2 human approval.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )

    publisher = InstagramPublisher()
    custom_cap = payload.custom_caption if payload else None
    pub_url = payload.public_video_url if payload else None

    try:
        result = publisher.publish_reel(
            job=job,
            db=db,
            caption=custom_cap,
            public_video_url=pub_url,
        )
        return InstagramPublishResponse(
            job_id=job.id,
            status=result["status"],
            instagram_media_id=result.get("instagram_media_id"),
            instagram_permalink=result.get("instagram_permalink"),
            published_at=result.get("published_at"),
            message=result.get("message", "Video published successfully."),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except InstagramPublishError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

