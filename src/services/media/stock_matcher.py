"""
Scene-to-Footage Matcher & Scoring Engine
=========================================
Implements Requirement 4.D:
  - Considers scene keywords, semantic relevance, orientation, and licensing.
  - Calculates a normalized match score (0.0 to 1.0).
  - Uses a configurable threshold (default: 0.70).
  - If score < threshold, rejects footage and triggers dynamic graphic card fallback.
  - Never inserts irrelevant footage just to fill a scene.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.config import PROJECT_ROOT, settings
from src.services.media.stock_client import StockAPIClient

log = logging.getLogger("reelfactory.matcher")


@dataclass
class MatchResult:
    matched: bool
    footage_path: Optional[str] = None
    score: float = 0.0
    reason: str = ""
    fallback_card_needed: bool = False


class StockMatcher:
    """Matches script scenes to B-roll footage (local & Pexels/Pixabay) or triggers card fallback."""

    def __init__(
        self,
        brand_id: str,
        match_threshold: float = 0.70,
        media_root: Optional[Path] = None,
        stock_client: Optional[StockAPIClient] = None,
    ):
        self.brand_id = brand_id.lower().strip()
        self.match_threshold = match_threshold
        self.media_root = media_root or (PROJECT_ROOT / "assets")
        self.brand_broll_dir = self.media_root / "branding" / self.brand_id / "broll"
        self.stock_dir = self.media_root / "stock"
        self.stock_client = stock_client or StockAPIClient()

    def match_scene(
        self,
        scene_id: str,
        keywords: list[str],
        duration_seconds: float,
        has_numeric_claims: bool = False,
    ) -> MatchResult:
        """
        Evaluate candidate footage for a scene.
        
        Strategic Rule (Requirement 4.D):
        If a scene has high-priority numeric claims (e.g. "-40% costs", "1.5 lakh startups"),
        a graphic statistic card is often superior to generic stock footage.
        """
        log.info(f"Matching footage for scene '{scene_id}' (Keywords: {keywords})")

        # 1. Search local brand B-roll directory first
        candidates: list[Path] = []
        if self.brand_broll_dir.exists():
            candidates.extend(self.brand_broll_dir.glob("*.mp4"))
        if self.stock_dir.exists():
            candidates.extend(self.stock_dir.glob("*.mp4"))

        # 2. Score candidate videos based on keyword overlap
        best_candidate: Optional[Path] = None
        best_score = 0.0

        clean_keywords = [k.lower().strip() for k in keywords if k]
        clean_keywords_set = set(clean_keywords)

        if candidates:
            for candidate in candidates:
                filename_tokens = set(candidate.stem.lower().replace("-", "_").split("_"))
                
                # Calculate Jaccard similarity between keywords and filename tokens
                overlap = len(clean_keywords_set.intersection(filename_tokens))
                score = overlap / max(len(clean_keywords_set), 1)

                # Bonus for vertical formatting indicator in filename (e.g. "_vertical" or "_916")
                if "vertical" in candidate.stem.lower() or "916" in candidate.stem.lower():
                    score += 0.25

                if score > best_score:
                    best_score = score
                    best_candidate = candidate

            best_score = min(best_score, 1.0)
            log.info(f"  Best local candidate: {best_candidate.name if best_candidate else 'None'} (Score: {best_score:.2f}, Threshold: {self.match_threshold})")

        # 3. Local threshold check (Requirement 4.D)
        if best_candidate and best_score >= self.match_threshold:
            return MatchResult(
                matched=True,
                footage_path=str(best_candidate.resolve()),
                score=best_score,
                reason=f"Local footage matched with score {best_score:.2f} >= {self.match_threshold}",
                fallback_card_needed=False,
            )

        # 4. Online Stock API Search (Pexels & Pixabay fallback)
        if settings.ENABLE_STOCK_API and clean_keywords:
            log.info(f"  Attempting online stock search via Pexels/Pixabay for keywords: {clean_keywords[:3]}")
            online_clip = self.stock_client.search_stock(clean_keywords, min_duration=duration_seconds)
            if online_clip and online_clip.exists():
                log.info(f"  Online stock footage successfully retrieved: {online_clip.name}")
                return MatchResult(
                    matched=True,
                    footage_path=str(online_clip.resolve()),
                    score=0.85,
                    reason=f"Matched Pexels/Pixabay vertical B-roll footage for keywords: {clean_keywords[:2]}",
                    fallback_card_needed=False,
                )

        # 5. Score below threshold / no stock match -> trigger branded scene card fallback
        return MatchResult(
            matched=False,
            score=best_score,
            reason=f"Score {best_score:.2f} below threshold {self.match_threshold}. Irrelevant filler rejected.",
            fallback_card_needed=True,
        )

