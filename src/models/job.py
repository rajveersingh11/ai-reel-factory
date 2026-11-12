"""
Job Data Model
==============
Represents a video production job.
Enforces multi-brand partitioning (brand_id) and lifecycle status tracking.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Enum, JSON, Text
from src.core.database import Base


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RESEARCHING = "RESEARCHING"
    SCRIPTING = "SCRIPTING"
    SCRIPT_APPROVAL_PENDING = "SCRIPT_APPROVAL_PENDING"  # Gate 1
    APPROVED = "APPROVED"
    RENDERING = "RENDERING"
    QC_PENDING = "QC_PENDING"
    FINAL_APPROVAL_PENDING = "FINAL_APPROVAL_PENDING"    # Gate 2
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    brand_id = Column(String(50), nullable=False, index=True)  # Requirement 4.B
    topic = Column(String(500), nullable=False)
    status = Column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False, index=True)
    stage = Column(String(50), default="initialization", nullable=False)

    # Content & artifacts
    script_data = Column(JSON, nullable=True)
    video_path = Column(String(1000), nullable=True)
    qc_report = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Job id={self.id} brand={self.brand_id} status={self.status}>"

