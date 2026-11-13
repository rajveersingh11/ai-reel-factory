"""
Background Music (BGM) & Automatic Audio Ducking Engine
======================================================
Implements intelligent audio ducking using FFmpeg sidechain compression.

Features:
  1. Resolves BGM track per brand identity (Tech Minimalist, Luxury Ambient, Lo-Fi).
  2. Sidechain ducking: BGM volume automatically compresses by 6:1 whenever voiceover speaks.
  3. Smooth release: BGM smoothly swells back during speech pauses and transitions.
  4. Deterministic loudness: Normalizes mixed master audio to -14.0 LUFS (EBU R128).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

from src.core.config import PROJECT_ROOT, settings
from src.schemas.brand import BrandConfig
from src.services.video.qc_engine import FFMPEG

log = logging.getLogger("reelfactory.audio.bgm")


class BGMEngine:
    """Manages brand soundtrack resolution and real-time audio ducking."""

    def __init__(self, bgm_root: Optional[Path] = None):
        self.bgm_root = bgm_root or (PROJECT_ROOT / "assets" / "audio" / "bgm")
        self.bgm_root.mkdir(parents=True, exist_ok=True)

    def resolve_bgm_track(self, brand: BrandConfig) -> Optional[Path]:
        """
        Locate the configured BGM track for a brand, checking:
          1. Exact track name in assets/audio/bgm/
          2. Brand-specific audio folder assets/branding/<brand_id>/audio/
          3. Default brand fallback track
        """
        track_name = brand.bgm_track
        if track_name:
            # Check assets/audio/bgm/<track_name>
            candidate = self.bgm_root / track_name
            if candidate.exists() and candidate.stat().st_size > 1000:
                return candidate

            # Check brand asset directory
            brand_audio = PROJECT_ROOT / "assets" / "branding" / brand.id / "audio" / track_name
            if brand_audio.exists() and brand_audio.stat().st_size > 1000:
                return brand_audio

        # Default fallbacks based on brand tone
        if "luxury" in brand.tone.lower() or "real estate" in brand.tagline.lower():
            fallback = self.bgm_root / "luxury_ambient.wav"
        else:
            fallback = self.bgm_root / "tech_ambient.wav"

        if fallback.exists() and fallback.stat().st_size > 1000:
            return fallback

        return None

    def apply_ducking(
        self,
        voice_path: Path,
        bgm_path: Path,
        output_path: Path,
        bgm_volume: float = 0.18,
        target_loudness_lufs: float = -14.0,
        timeout_seconds: int = 60,
    ) -> Path:
        """
        Mix voiceover and background music with automatic sidechain compression.
        
        Filtergraph:
          - [1:a] Base volume scaling + infinite seamless loop.
          - [bgm][voice] sidechaincompress: Compresses BGM whenever voiceover signal is active.
          - [voice][ducked] amix: Mixes the two audio streams to the exact length of voiceover.
          - loudnorm: Normalizes master mix to target LUFS (-14.0).
        """
        if not voice_path.exists():
            raise FileNotFoundError(f"Voice narration audio not found at: {voice_path}")
        if not bgm_path.exists():
            raise FileNotFoundError(f"BGM audio file not found at: {bgm_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        log.info(f"Applying sidechain audio ducking with BGM '{bgm_path.name}' (Base Vol: {bgm_volume:.2f})...")

        # FFmpeg filtergraph for sidechain compression
        filter_complex = (
            f"[1:a]volume={bgm_volume:.2f},aloop=loop=-1:size=2e+09[bgm_loop];"
            f"[bgm_loop][0:a]sidechaincompress=threshold=0.025:ratio=6:attack=120:release=650[ducked_bgm];"
            f"[0:a][ducked_bgm]amix=inputs=2:duration=first:dropout_transition=2,"
            f"loudnorm=I={target_loudness_lufs:.1f}:LRA=11:TP=-1.5[aout]"
        )

        cmd = [
            FFMPEG, "-y",
            "-i", str(voice_path),
            "-i", str(bgm_path),
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-c:a", "pcm_s16le",
            str(output_path),
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
            if res.returncode != 0:
                log.warning(f"Audio ducking filter failed ({res.returncode}): {res.stderr[-300:]}. Falling back to clean voiceover.")
                # Fallback to copy voiceover if filter fails
                import shutil
                shutil.copyfile(voice_path, output_path)
        except subprocess.TimeoutExpired as exc:
            log.warning("Audio ducking timed out. Falling back to clean voiceover.")
            import shutil
            shutil.copyfile(voice_path, output_path)

        return output_path

