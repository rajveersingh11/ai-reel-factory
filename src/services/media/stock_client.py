"""
Free Stock Media API Client (Pexels & Pixabay)
==============================================
Provides automated retrieval of 9:16 vertical stock footage and high-res imagery.

Supports:
  1. Pexels Videos API (Free tier: 200 req/hr, portrait orientation)
  2. Pixabay Videos & Vertical Photos API (Free tier: 5,000 req/hr)
  3. Local caching in storage/cache/stock to prevent duplicate downloads
  4. Graceful offline/mock mode when API keys are not provided
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional, Any
import httpx

from src.core.config import settings

log = logging.getLogger("reelfactory.media.stock_client")


class StockAPIClient:
    """Queries free stock media APIs (Pexels & Pixabay) with local caching."""

    def __init__(
        self,
        pexels_key: Optional[str] = None,
        pixabay_key: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        mock_mode: bool = False,
    ):
        self.pexels_key = pexels_key or getattr(settings, "PEXELS_API_KEY", "")
        self.pixabay_key = pixabay_key or getattr(settings, "PIXABAY_API_KEY", "")
        self.cache_dir = cache_dir or getattr(
            settings, "STOCK_CACHE_DIR", settings.STORAGE_ROOT / "cache" / "stock"
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.mock_mode = mock_mode

    def _slugify(self, text: str) -> str:
        """Create clean filename safe slug."""
        return re.sub(r"[^a-zA-Z0-9_-]", "_", text.strip().lower())[:40]

    def search_pexels_video(self, query: str, min_duration: float = 3.0) -> Optional[Path]:
        """
        Search Pexels for a 9:16 portrait stock video clip.
        Returns cached Path to the downloaded MP4 file.
        """
        if not self.pexels_key or self.mock_mode:
            return None

        clean_q = query.strip()
        slug = self._slugify(clean_q)
        cached_files = list(self.cache_dir.glob(f"pexels_{slug}_*.mp4"))
        if cached_files and cached_files[0].stat().st_size > 50000:
            log.info(f"Using cached Pexels video: {cached_files[0].name}")
            return cached_files[0]

        url = "https://api.pexels.com/videos/search"
        headers = {"Authorization": self.pexels_key}
        params = {
            "query": clean_q,
            "orientation": "portrait",
            "size": "medium",
            "per_page": 5,
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get(url, headers=headers, params=params)
                if res.status_code != 200:
                    log.warning(f"Pexels API error ({res.status_code}): {res.text[:120]}")
                    return None

                data = res.json()
                videos = data.get("videos", [])
                if not videos:
                    return None

                # Pick the best portrait video file
                for video in videos:
                    if video.get("duration", 0) < min_duration:
                        continue
                    files = video.get("video_files", [])
                    # Look for portrait HD (width <= height)
                    portrait_files = [f for f in files if (f.get("width") or 0) <= (f.get("height") or 0)]
                    target_file = portrait_files[0] if portrait_files else (files[0] if files else None)

                    if target_file and target_file.get("link"):
                        download_url = target_file["link"]
                        video_id = video.get("id", "vid")
                        out_path = self.cache_dir / f"pexels_{slug}_{video_id}.mp4"

                        log.info(f"Downloading Pexels vertical video for '{clean_q}' -> {out_path.name}...")
                        dl_res = client.get(download_url, follow_redirects=True)
                        if dl_res.status_code == 200 and len(dl_res.content) > 50000:
                            out_path.write_bytes(dl_res.content)
                            return out_path
        except Exception as e:
            log.warning(f"Pexels fetch failed for query '{clean_q}': {e}")

        return None

    def search_pixabay_video(self, query: str) -> Optional[Path]:
        """
        Search Pixabay for a stock video clip.
        Returns cached Path to the downloaded MP4 file.
        """
        if not self.pixabay_key or self.mock_mode:
            return None

        clean_q = query.strip()
        slug = self._slugify(clean_q)
        cached_files = list(self.cache_dir.glob(f"pixabay_{slug}_*.mp4"))
        if cached_files and cached_files[0].stat().st_size > 50000:
            log.info(f"Using cached Pixabay video: {cached_files[0].name}")
            return cached_files[0]

        url = "https://pixabay.com/api/videos/"
        params = {
            "key": self.pixabay_key,
            "q": clean_q,
            "video_type": "film",
            "per_page": 5,
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get(url, params=params)
                if res.status_code != 200:
                    log.warning(f"Pixabay video API error ({res.status_code}): {res.text[:120]}")
                    return None

                data = res.json()
                hits = data.get("hits", [])
                if not hits:
                    return None

                hit = hits[0]
                videos = hit.get("videos", {})
                # Prefer medium or small MP4
                target_video = videos.get("medium") or videos.get("small") or videos.get("large")
                if target_video and target_video.get("url"):
                    download_url = target_video["url"]
                    vid_id = hit.get("id", "vid")
                    out_path = self.cache_dir / f"pixabay_{slug}_{vid_id}.mp4"

                    log.info(f"Downloading Pixabay video for '{clean_q}' -> {out_path.name}...")
                    dl_res = client.get(download_url, follow_redirects=True)
                    if dl_res.status_code == 200 and len(dl_res.content) > 50000:
                        out_path.write_bytes(dl_res.content)
                        return out_path
        except Exception as e:
            log.warning(f"Pixabay video fetch failed for '{clean_q}': {e}")

        return None

    def search_stock(self, keywords: list[str], min_duration: float = 3.0) -> Optional[Path]:
        """
        Orchestrates free stock search across Pexels and Pixabay.
        Iterates keywords in priority order.
        """
        for kw in keywords:
            clean = kw.strip()
            if len(clean) < 3:
                continue

            # 1. Try Pexels first (dedicated portrait orientation support)
            pexels_result = self.search_pexels_video(clean, min_duration=min_duration)
            if pexels_result:
                return pexels_result

            # 2. Try Pixabay video fallback
            pixabay_result = self.search_pixabay_video(clean)
            if pixabay_result:
                return pixabay_result

        return None

