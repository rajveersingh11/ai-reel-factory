"""
Meta Instagram Reels Publishing Service
=======================================
Implements official Meta Graph API v21.0 for Instagram Reels publishing.

Enforces:
  1. Gate 2 Prerequisite: Only videos explicitly approved at Gate 2 can be published.
  2. Idempotency: Duplicate prevention tracking `instagram_media_id`.
  3. AI Disclosure: Transparent Meta 2024 compliance tagging (#AIgenerated).
  4. Multi-brand awareness: Resolves account IDs and captions per brand profile.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import httpx
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models.job import Job, JobStatus
from src.schemas.brand import BrandRegistry

log = logging.getLogger("reelfactory.publishing.instagram")


class InstagramPublishError(Exception):
    """Raised when Meta Graph API returns an unrecoverable publishing error."""
    pass


class InstagramPublisher:
    """Handles automated, idempotent publishing of 9:16 Reels to Instagram."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        api_version: Optional[str] = None,
        mock_mode: Optional[bool] = None,
    ):
        self.access_token = access_token or settings.INSTAGRAM_ACCESS_TOKEN
        self.api_version = api_version or settings.META_GRAPH_API_VERSION
        self.base_url = f"https://graph.facebook.com/{self.api_version}"
        self.brand_registry = BrandRegistry()

        # If mock_mode is explicitly set, use it. Otherwise, if token is empty, enable mock mode.
        if mock_mode is not None:
            self.mock_mode = mock_mode
        else:
            self.mock_mode = not bool(self.access_token)

    def format_caption(self, job: Job) -> str:
        """Construct compliant Instagram caption with brand tags & AI disclosure."""
        return self._format_caption(job)

    def _format_caption(self, job: Job) -> str:
        """Construct compliant Instagram caption with brand tags & AI disclosure."""
        brand = self.brand_registry.get(job.brand_id)
        topic = job.topic
        script = job.script_data or {}
        scenes = script.get("scenes", [])
        cta = script.get("call_to_action") or (scenes[-1].get("narration") if scenes else "")

        tags = [
            f"#{job.brand_id.lower()}",
            "#reels",
            "#shorts",
            "#AIgenerated",  # Meta 2024 mandatory AI content transparency tag
            "#AIVideoCreated",
        ]

        caption_lines = [
            f"🚀 {topic}",
            "",
            cta if cta else f"Follow @{brand.name.replace(' ', '')} for daily industry insights.",
            "",
            f"— {brand.name} | {brand.tagline}",
            "🤖 Produced with AI Reel Factory (Deterministic QC Passed)",
            "",
            " ".join(tags),
        ]
        return "\n".join(caption_lines).strip()

    def publish_reel(
        self,
        job: Job,
        db: Session,
        caption: Optional[str] = None,
        public_video_url: Optional[str] = None,
        account_id: Optional[str] = None,
        max_poll_seconds: int = 120,
    ) -> dict[str, Any]:
        """
        Publish a rendered Reel to Instagram.

        Prerequisites:
          - Job must have passed Gate 2 human approval.
          - Job must not have been previously published (idempotent).
        """
        # 1. Idempotency Check (Duplicate Post Prevention)
        if job.instagram_media_id or job.status == JobStatus.PUBLISHED:
            log.warning(
                f"Job {job.id} was already published to Instagram with ID '{job.instagram_media_id}'. "
                f"Duplicate publication skipped."
            )
            return {
                "job_id": job.id,
                "status": "already_published",
                "instagram_media_id": job.instagram_media_id,
                "instagram_permalink": job.instagram_permalink,
                "published_at": job.published_at.isoformat() if job.published_at else None,
                "message": "Job has already been published. Duplicate publishing prevented.",
            }

        # 2. Gate 2 Prerequisite Check
        is_approved = (
            job.status == JobStatus.COMPLETED
            or job.stage in ("approved_for_publishing", "completed")
        )
        if not is_approved:
            raise ValueError(
                f"Cannot publish Job '{job.id}': Status is '{job.status}' (stage: '{job.stage}'). "
                f"Gate 2 final human video approval is mandatory before publishing."
            )

        # 3. Resolve Media & Captions
        final_caption = caption or self._format_caption(job)
        video_url = public_video_url or f"{settings.PUBLIC_BASE_URL}/api/v1/jobs/{job.id}/video"
        target_account = account_id or settings.INSTAGRAM_BUSINESS_ACCOUNT_ID or "17841400000000000"

        # 4. Mock / Sandbox Execution Mode
        if self.mock_mode:
            log.info(f"Simulating Instagram Reels publication for Job {job.id} in mock mode...")
            mock_container_id = f"179_{abs(hash(job.id)) % 1000000000}"
            mock_media_id = f"180_{abs(hash(job.id)) % 1000000000}"
            mock_permalink = f"https://www.instagram.com/reel/C{job.id[:8].upper()}/"

            # Update DB state
            now = datetime.now(timezone.utc)
            job.instagram_media_id = mock_media_id
            job.instagram_permalink = mock_permalink
            job.published_at = now
            job.status = JobStatus.PUBLISHED
            job.stage = "published_to_instagram"
            db.commit()

            return {
                "job_id": job.id,
                "status": "published",
                "mode": "mock",
                "container_id": mock_container_id,
                "instagram_media_id": mock_media_id,
                "instagram_permalink": mock_permalink,
                "published_at": now.isoformat(),
                "caption": final_caption,
            }

        # 5. Live Meta Graph API Execution
        with httpx.Client(timeout=30.0) as client:
            # Step A: Create Media Container
            create_url = f"{self.base_url}/{target_account}/media"
            create_payload = {
                "media_type": "REELS",
                "video_url": video_url,
                "caption": final_caption,
                "share_to_feed": True,
                "access_token": self.access_token,
            }
            log.info(f"Submitting Reels container request to Meta Graph API for job {job.id}...")
            res = client.post(create_url, data=create_payload)
            if res.status_code != 200:
                raise InstagramPublishError(f"Container creation failed ({res.status_code}): {res.text}")

            container_id = res.json().get("id")
            if not container_id:
                raise InstagramPublishError(f"No container ID returned: {res.text}")

            # Step B: Poll Container Status until FINISHED
            status_url = f"{self.base_url}/{container_id}"
            poll_start = time.time()
            ready_to_publish = False

            while time.time() - poll_start < max_poll_seconds:
                status_res = client.get(
                    status_url,
                    params={"fields": "status_code,status", "access_token": self.access_token},
                )
                if status_res.status_code == 200:
                    status_data = status_res.json()
                    status_code = status_data.get("status_code", "").upper()
                    if status_code == "FINISHED":
                        ready_to_publish = True
                        break
                    elif status_code in ("ERROR", "EXPIRED"):
                        raise InstagramPublishError(f"Container failed with status '{status_code}': {status_data}")

                time.sleep(3.0)

            if not ready_to_publish:
                raise InstagramPublishError(
                    f"Container '{container_id}' processing timed out after {max_poll_seconds}s."
                )

            # Step C: Publish Container
            publish_url = f"{self.base_url}/{target_account}/media_publish"
            publish_res = client.post(
                publish_url,
                data={"creation_id": container_id, "access_token": self.access_token},
            )
            if publish_res.status_code != 200:
                raise InstagramPublishError(f"Media publish failed ({publish_res.status_code}): {publish_res.text}")

            media_id = publish_res.json().get("id")

            # Step D: Retrieve Media Permalink
            permalink_url = f"{self.base_url}/{media_id}"
            perm_res = client.get(
                permalink_url,
                params={"fields": "permalink", "access_token": self.access_token},
            )
            permalink = (
                perm_res.json().get("permalink")
                if perm_res.status_code == 200
                else f"https://www.instagram.com/reel/{media_id}/"
            )

            # Update DB state
            now = datetime.now(timezone.utc)
            job.instagram_media_id = media_id
            job.instagram_permalink = permalink
            job.published_at = now
            job.status = JobStatus.PUBLISHED
            job.stage = "published_to_instagram"
            db.commit()

            log.info(f"Job {job.id} successfully published to Instagram! Media ID: {media_id}")
            return {
                "job_id": job.id,
                "status": "published",
                "mode": "live",
                "container_id": container_id,
                "instagram_media_id": media_id,
                "instagram_permalink": permalink,
                "published_at": now.isoformat(),
                "caption": final_caption,
            }
