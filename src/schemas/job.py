"""
Pydantic Schemas for Job Creation & Status Responses
====================================================
Validates incoming API payloads and defines serialized responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field, ConfigDict
from src.models.job import JobStatus


class JobCreateRequest(BaseModel):
    brand_id: str = Field(default="skyon", description="Target brand identifier, e.g. skyon or r4realty")
    topic: str = Field(..., min_length=5, max_length=500, description="The video topic or subject headline")


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    brand_id: str
    topic: str
    status: JobStatus
    stage: str
    script_data: Optional[dict[str, Any]] = None
    video_path: Optional[str] = None
    qc_report: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    instagram_media_id: Optional[str] = None
    instagram_permalink: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
