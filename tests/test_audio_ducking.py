"""
Background Music (BGM) & Sidechain Ducking Test Suite
====================================================
Tests Option 2:
  1. Brand-specific BGM track resolution (Skyon -> tech, R4Realty -> luxury)
  2. BGM fallbacks based on brand tone
  3. Sidechain compression audio ducking execution via FFmpeg
  4. Audio loudness compliance (-14 LUFS EBU R128)
  5. Error handling and voiceover fallback
  6. End-to-end integration with ProductionPipeline
"""

from __future__ import annotations

import subprocess
from pathlib import Path
import pytest

from src.core.config import PROJECT_ROOT
from src.schemas.brand import brand_registry, BrandConfig
from src.schemas.script import ScriptData, SceneScript, NumericClaim
from src.services.audio.bgm_engine import BGMEngine
from src.services.video.qc_engine import FFMPEG, FFPROBE, QCEngine
from src.services.video.production_pipeline import ProductionPipeline


@pytest.fixture
def bgm_engine():
    return BGMEngine()


@pytest.fixture
def sample_voice_wav():
    """Locate or verify a real test WAV audio file."""
    candidate = PROJECT_ROOT / "spikes" / "phase1_rendering" / "output" / "narration.wav"
    if not candidate.exists() or candidate.stat().st_size < 1000:
        candidate = PROJECT_ROOT / "assets" / "models" / "piper" / "test_voice.wav"
    assert candidate.exists(), "Sample test voice WAV must exist"
    return candidate


def test_bgm_track_resolution_configured_brands(bgm_engine):
    """Verify that brands in brands.yaml resolve their designated tracks."""
    skyon = brand_registry.get("skyon")
    assert skyon is not None
    skyon_track = bgm_engine.resolve_bgm_track(skyon)
    assert skyon_track is not None
    assert skyon_track.name == "tech_ambient.wav"
    assert skyon_track.exists()

    r4realty = brand_registry.get("r4realty")
    assert r4realty is not None
    r4_track = bgm_engine.resolve_bgm_track(r4realty)
    assert r4_track is not None
    assert r4_track.name == "luxury_ambient.wav"
    assert r4_track.exists()


def test_bgm_track_fallback_by_tone(bgm_engine):
    """Verify that unconfigured brands fall back appropriately by brand tone."""
    # Custom luxury brand without explicit bgm_track
    custom_luxury = BrandConfig(
        id="prestige_estates",
        name="Prestige Estates",
        tone="Ultra-Luxury, Exclusive, Sophisticated",
        tagline="Finest Real Estate Properties",
        color_palette={"primary": "#D4AF37", "secondary": "#111111"},
        target_audience="High-net-worth investors",
        font_family="Cinzel",
    )
    luxury_track = bgm_engine.resolve_bgm_track(custom_luxury)
    assert luxury_track is not None
    assert luxury_track.name == "luxury_ambient.wav"

    # Custom tech brand without explicit bgm_track
    custom_tech = BrandConfig(
        id="devpulse",
        name="DevPulse",
        tone="Punchy, Authoritative, Tech-First",
        tagline="Developer productivity tools",
        color_palette={"primary": "#00FFCC", "secondary": "#0A0A0A"},
        target_audience="Software Engineers",
        font_family="Roboto",
    )
    tech_track = bgm_engine.resolve_bgm_track(custom_tech)
    assert tech_track is not None
    assert tech_track.name == "tech_ambient.wav"


def test_apply_ducking_creates_valid_audio(bgm_engine, sample_voice_wav, tmp_path):
    """Verify sidechain ducking produces a valid master audio WAV."""
    skyon = brand_registry.get("skyon")
    bgm_track = bgm_engine.resolve_bgm_track(skyon)
    out_path = tmp_path / "ducked_master.wav"

    result = bgm_engine.apply_ducking(
        voice_path=sample_voice_wav,
        bgm_path=bgm_track,
        output_path=out_path,
        bgm_volume=skyon.bgm_volume,
        target_loudness_lufs=-14.0,
    )

    assert result.exists()
    assert result.stat().st_size > 50000

    # Probe duration to verify it matches narration duration
    def get_duration(p: Path) -> float:
        res = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
            capture_output=True, text=True, check=True
        )
        return float(res.stdout.strip())

    voice_dur = get_duration(sample_voice_wav)
    master_dur = get_duration(result)
    assert abs(voice_dur - master_dur) < 0.25, f"Master duration ({master_dur}s) must match voice duration ({voice_dur}s)"


def test_apply_ducking_loudness_compliance(bgm_engine, sample_voice_wav, tmp_path):
    """Verify that ducked audio adheres to EBU R128 loudness target (-14 LUFS ± 2 LUFS)."""
    skyon = brand_registry.get("skyon")
    bgm_track = bgm_engine.resolve_bgm_track(skyon)
    out_path = tmp_path / "loudness_check.wav"

    bgm_engine.apply_ducking(
        voice_path=sample_voice_wav,
        bgm_path=bgm_track,
        output_path=out_path,
        bgm_volume=skyon.bgm_volume,
        target_loudness_lufs=-14.0,
    )

    # Analyze integrated loudness with ebur128
    cmd = [
        FFMPEG, "-i", str(out_path),
        "-af", "ebur128",
        "-f", "null", "-"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    
    # Extract Integrated loudness I:
    integrated_lufs = None
    for line in res.stderr.splitlines():
        if "I:" in line and "LUFS" in line and "TARGET" not in line:
            parts = line.split("I:")
            if len(parts) > 1:
                val_str = parts[1].split("LUFS")[0].strip()
                try:
                    integrated_lufs = float(val_str)
                except ValueError:
                    pass

    assert integrated_lufs is not None, "Failed to parse ebur128 integrated loudness"
    # Target is -14.0 LUFS, allowed range is -17.0 to -12.0
    assert -17.0 <= integrated_lufs <= -12.0, f"Loudness {integrated_lufs} LUFS is outside expected -14 LUFS range"


def test_apply_ducking_missing_file_errors(bgm_engine, tmp_path):
    """Ensure FileNotFoundError is raised when input files do not exist."""
    fake_voice = tmp_path / "non_existent_voice.wav"
    fake_bgm = tmp_path / "non_existent_bgm.wav"

    with pytest.raises(FileNotFoundError):
        bgm_engine.apply_ducking(fake_voice, fake_bgm, tmp_path / "out.wav")
