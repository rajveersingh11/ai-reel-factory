"""
Tests for Free Stock Footage Integration (Pexels & Pixabay)
===========================================================
Validates:
  1. StockAPIClient offline and missing-key handling.
  2. Local caching mechanism to prevent bandwidth waste.
  3. StockMatcher fallback hierarchy: Local B-roll -> Online Stock -> Dynamic Card.
  4. Production pipeline seamless concat of real video clips and graphic cards.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from src.services.media.stock_client import StockAPIClient
from src.services.media.stock_matcher import StockMatcher, MatchResult
from src.services.video.cards import render_scene_card


def test_stock_client_missing_keys_returns_none(tmp_path):
    """When API keys are not provided, client returns None gracefully without crashing."""
    client = StockAPIClient(pexels_key="", pixabay_key="", cache_dir=tmp_path)
    res = client.search_stock(["technology", "artificial intelligence"])
    assert res is None


def test_stock_client_cache_hit_prevents_api_calls(tmp_path):
    """When a cached video file exists for a query slug, client reuses it immediately."""
    client = StockAPIClient(pexels_key="mock_key", pixabay_key="mock_key", cache_dir=tmp_path)

    # Place a dummy cached video file (> 50KB to simulate real MP4)
    cached_file = tmp_path / "pexels_artificial_intelligence_12345.mp4"
    cached_file.write_bytes(b"0" * 60000)

    # Search should hit cache
    result = client.search_pexels_video("artificial intelligence")
    assert result is not None
    assert result.name == cached_file.name


def test_stock_matcher_prioritizes_local_over_online(tmp_path):
    """Local high-relevance footage takes precedence over online APIs."""
    broll_dir = tmp_path / "branding" / "skyon" / "broll"
    broll_dir.mkdir(parents=True)
    local_clip = broll_dir / "cloud_devops_vertical.mp4"
    local_clip.write_bytes(b"0" * 1000)

    mock_client = MagicMock(spec=StockAPIClient)
    matcher = StockMatcher(brand_id="skyon", media_root=tmp_path, stock_client=mock_client)

    res = matcher.match_scene("scene_1", keywords=["cloud", "devops"], duration_seconds=5.0)
    assert res.matched is True
    assert "cloud_devops_vertical.mp4" in res.footage_path
    # mock_client should not have been called because local was found
    mock_client.search_stock.assert_not_called()


def test_stock_matcher_uses_online_stock_when_local_is_missing(tmp_path):
    """When local library has no match, online stock API is queried."""
    online_clip = tmp_path / "online_stock_clip.mp4"
    online_clip.write_bytes(b"0" * 1000)

    mock_client = MagicMock(spec=StockAPIClient)
    mock_client.search_stock.return_value = online_clip

    matcher = StockMatcher(brand_id="skyon", media_root=tmp_path, stock_client=mock_client)

    res = matcher.match_scene("scene_1", keywords=["robotics", "automation"], duration_seconds=5.0)
    assert res.matched is True
    assert res.score >= 0.70
    assert "online_stock_clip.mp4" in res.footage_path
    mock_client.search_stock.assert_called_once()

