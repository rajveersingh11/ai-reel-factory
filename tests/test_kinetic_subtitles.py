"""
Kinetic Word-by-Word Subtitles Test Suite
========================================
Validates Option 3:
  1. Hex to ASS BGR color conversion.
  2. Kinetic word-by-word highlight tag emission (Karaoke pop-in).
  3. MarginV = 570 vertical safe-zone compliance (Instagram Reels standard).
  4. Brand accent color resolution and theming.
  5. FFmpeg libass compatibility (burn verification).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
import pytest

from src.core.config import PROJECT_ROOT
from src.schemas.brand import brand_registry
from src.services.audio.subtitle_generator import (
    SubtitleGenerator,
    hex_to_ass_color,
    format_ass_timestamp,
)
from src.services.video.qc_engine import FFMPEG


def test_hex_to_ass_color_conversion():
    """Verify standard hex colors convert to ASS &HAABBGGRR& format."""
    # Skyon Cyan: #00D4FF -> R=00, G=D4, B=FF -> &H00FFD400&
    assert hex_to_ass_color("#00D4FF") == "&H00FFD400&"
    # Pure Red: #FF0000 -> R=FF, G=00, B=00 -> &H000000FF&
    assert hex_to_ass_color("#FF0000") == "&H000000FF&"
    # Gold: #D4AF37 -> R=D4, G=AF, B=37 -> &H0037AFD4&
    assert hex_to_ass_color("#D4AF37") == "&H0037AFD4&"
    # Fallback on empty or invalid hex
    assert hex_to_ass_color("") == "&H0000FFFF&"
    assert hex_to_ass_color("invalid") == "&H0000FFFF&"


def test_format_ass_timestamp():
    """Ensure accurate centisecond timestamps for ASS subtitle format."""
    assert format_ass_timestamp(0.0) == "0:00:00.00"
    assert format_ass_timestamp(1.25) == "0:00:01.25"
    assert format_ass_timestamp(65.5) == "0:01:05.50"
    assert format_ass_timestamp(-5.0) == "0:00:00.00"  # Clamped to 0


def test_kinetic_subtitles_generation(tmp_path):
    """Verify that kinetic mode generates active word highlight tags."""
    gen = SubtitleGenerator(
        font_name="Inter Bold",
        font_size=70,
        margin_v=570,
        highlight_color="&H0000FFFF&",
        words_per_chunk=4,
    )

    scenes = [
        {
            "scene_id": "s01",
            "duration_seconds": 4.0,
            "narration": "The edge computing revolution begins right now.",
        }
    ]

    out_ass = tmp_path / "kinetic_test.ass"
    gen.generate_from_scenes(
        scenes=scenes,
        total_audio_duration=4.0,
        output_ass=out_ass,
        kinetic=True,
    )

    assert out_ass.exists()
    content = out_ass.read_text(encoding="utf-8")

    # Check ASS script headers and mobile safe zone
    assert "[Script Info]" in content
    assert "[V4+ Styles]" in content
    assert "[Events]" in content
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert "570,1" in content  # MarginV = 570

    # Check kinetic active tags
    dialogue_lines = [l for l in content.splitlines() if l.startswith("Dialogue:")]
    assert len(dialogue_lines) > 1, "Kinetic mode must emit multiple word-level dialogue events"

    # Each line should highlight a word with scale and color tags
    assert any(r"\fscx112\fscy112" in l for l in dialogue_lines)
    assert any(r"\rReel" in l for l in dialogue_lines)
    assert any("&H0000FFFF&" in l for l in dialogue_lines)


def test_static_subtitles_fallback(tmp_path):
    """Verify that kinetic=False falls back to static phrase cards."""
    gen = SubtitleGenerator(words_per_chunk=4)
    scenes = [
        {
            "scene_id": "s01",
            "duration_seconds": 4.0,
            "narration": "One two three four five six seven eight.",
        }
    ]

    out_ass = tmp_path / "static_test.ass"
    gen.generate_from_scenes(
        scenes=scenes,
        total_audio_duration=4.0,
        output_ass=out_ass,
        kinetic=False,
    )

    content = out_ass.read_text(encoding="utf-8")
    dialogue_lines = [l for l in content.splitlines() if l.startswith("Dialogue:")]
    
    # 8 words with words_per_chunk=4 -> exactly 2 static dialogue events
    assert len(dialogue_lines) == 2
    # Static mode should not contain active word highlight tags
    assert not any(r"\fscx112" in l for l in dialogue_lines)


def test_brand_specific_theming(tmp_path):
    """Verify brand highlight colors are correctly mapped into the ASS output."""
    skyon = brand_registry.get("skyon")
    skyon_highlight = hex_to_ass_color(skyon.accent_color or skyon.primary_color)

    gen = SubtitleGenerator(highlight_color=skyon_highlight)
    scenes = [{"scene_id": "s1", "duration_seconds": 2.0, "narration": "Cloud architecture speed"}]

    out_ass = tmp_path / "skyon_sub.ass"
    gen.generate_from_scenes(scenes, 2.0, out_ass, kinetic=True)

    content = out_ass.read_text(encoding="utf-8")
    assert skyon_highlight in content


def test_ffmpeg_libass_renders_kinetic_subtitles(tmp_path):
    """Ensure FFmpeg libass renders the kinetic ASS file without errors."""
    gen = SubtitleGenerator(
        font_name="Arial",
        highlight_color="&H0000FFFF&",
        margin_v=570,
    )
    scenes = [{"scene_id": "s1", "duration_seconds": 1.5, "narration": "Testing kinetic subtitle render"}]
    ass_path = tmp_path / "test_render.ass"
    gen.generate_from_scenes(scenes, 1.5, ass_path, kinetic=True)

    video_out = tmp_path / "sub_test.mp4"
    sub_arg = ass_path.as_posix().replace(":", "\\:")

    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=1.5:r=30",
        "-vf", f"subtitles='{sub_arg}'",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        str(video_out),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, f"FFmpeg failed to burn kinetic subtitles: {res.stderr[-500:]}"
    assert video_out.exists()
    assert video_out.stat().st_size > 10000

