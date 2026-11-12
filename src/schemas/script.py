"""
Structured Script & Fact-Checking Schemas
=========================================
Implements Requirement 4.C:
  - Every numeric claim must map to a stored source ID.
  - If a numeric claim has no supporting source, flag the scene and require human verification.
  - 140–160 narration words target for 60-second Reels.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field, model_validator


class ResearchSource(BaseModel):
    source_id: str = Field(..., description="Unique alphanumeric identifier (e.g. DPIIT-2024-Q3)")
    title: str = Field(..., description="Publication, agency, or document title")
    url: str = Field(..., description="Public reference or retrieval URL")
    retrieval_date: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        description="Date the source was retrieved",
    )
    key_facts: list[str] = Field(default_factory=list)


class NumericClaim(BaseModel):
    claim: str = Field(..., description="Specific numeric claim, e.g. 'over 1.5 lakh startups'")
    source_id: str = Field(..., description="Must match a valid ResearchSource.source_id")
    source_url: Optional[str] = None
    verified: bool = Field(default=False, description="True if mapped to a stored source ID")


class SceneScript(BaseModel):
    scene_id: str
    order: int
    duration_seconds: float = Field(default=12.0, ge=3.0, le=25.0)
    narration: str = Field(..., min_length=10, description="Voiceover text for this scene")
    keywords: list[str] = Field(default_factory=list, description="Keywords for visual matching")
    visual_note: str = Field(default="", description="Editorial visual direction")
    numeric_claims: list[NumericClaim] = Field(default_factory=list)
    is_flagged: bool = Field(default=False, description="Flagged if unverified numeric claim exists")
    flag_reason: Optional[str] = None

    @property
    def word_count(self) -> int:
        return len(self.narration.split())


class ScriptMetadata(BaseModel):
    topic: str
    brand_id: str
    target_duration_seconds: int = 60
    word_count_target: int = 150
    format: str = "instagram_reel"


class ScriptData(BaseModel):
    meta: ScriptMetadata
    scenes: list[SceneScript] = Field(..., min_length=3, max_length=8)
    sources: list[ResearchSource] = Field(default_factory=list)
    version: int = Field(default=1, description="Script revision version")
    total_narration_words: int = Field(default=0)
    fact_check_passed: bool = Field(default=True)

    @model_validator(mode="after")
    def validate_and_fact_check(self) -> "ScriptData":
        """
        1. Calculates total word count.
        2. Validates numeric claims against stored source IDs (Requirement 4.C).
        """
        total_words = sum(scene.word_count for scene in self.scenes)
        self.total_narration_words = total_words

        # Build set of registered source IDs
        registered_source_ids = {s.source_id.strip() for s in self.sources}

        # Regex to detect numbers/percentages/multipliers in narration
        # E.g. "40 percent", "1.5 lakh", "2x", "500", "5 times"
        numeric_pattern = re.compile(
            r"\b(\d+([,\.]\d+)?\s*(%|percent|x|times|lakh|crore|million|billion)?)\b",
            re.IGNORECASE,
        )

        all_claims_verified = True

        for scene in self.scenes:
            # Check explicit claims registered in scene
            for claim in scene.numeric_claims:
                if claim.source_id.strip() in registered_source_ids:
                    claim.verified = True
                else:
                    claim.verified = False
                    scene.is_flagged = True
                    scene.flag_reason = (
                        f"Claim '{claim.claim}' references unknown source ID '{claim.source_id}'."
                    )
                    all_claims_verified = False

            # Check if narration contains numbers not accounted for in numeric_claims
            found_numbers = numeric_pattern.findall(scene.narration)
            if found_numbers and not scene.numeric_claims:
                # Scene has numeric claims in prose but zero source mappings
                scene.is_flagged = True
                scene.flag_reason = (
                    f"Narration contains numbers ({[n[0] for n in found_numbers]}) without mapped source IDs."
                )
                all_claims_verified = False

        self.fact_check_passed = all_claims_verified
        return self


# Human decision model for Gate 1 (Requirement 4.A)
class ScriptApprovalDecision(BaseModel):
    decision: str = Field(
        ...,
        pattern="^(approve|edit|regenerate|reject)$",
        description="One of: approve, edit, regenerate, reject",
    )
    feedback: Optional[str] = Field(default=None, description="Editorial notes for regeneration")
    edited_script: Optional[ScriptData] = Field(
        default=None,
        description="Required if decision is 'edit'",
    )
