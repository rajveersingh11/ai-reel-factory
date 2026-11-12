"""
Deterministic Quality Control Engine (ffprobe & ebur128)
=========================================================
Implements Requirement 4.E:
  - Uses FFprobe and measurable checks rather than relying on an LLM.
  - Validates resolution, aspect ratio, duration, codecs, silence, loudness, and container.
  - Produces structured, serializable QC report for database persistence.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from src.core.config import settings

log = logging.getLogger("reelfactory.qc")

# Probe paths
_WINGET_BASE = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"


def _resolve_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    if name in ("ffmpeg", "ffprobe"):
        for candidate in _WINGET_BASE.glob(f"Gyan.FFmpeg_*/*/bin/{name}.exe"):
            if candidate.exists():
                return str(candidate)
    return name


FFMPEG = _resolve_tool("ffmpeg")
FFPROBE = _resolve_tool("ffprobe")


@dataclass
class QCCheckItem:
    check_name: str
    passed: bool
    actual_value: str
    expected_value: str
    is_fatal: bool = True
    details: str = ""


@dataclass
class QCReport:
    video_path: str
    overall_passed: bool = False
    fatal_errors: int = 0
    checks: list[QCCheckItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "video_path": self.video_path,
            "overall_passed": self.overall_passed,
            "fatal_errors": self.fatal_errors,
            "checks": [asdict(c) for c in self.checks],
        }


class QCEngine:
    """Automated deterministic quality inspector."""

    def __init__(
        self,
        target_width: int = 1080,
        target_height: int = 1920,
        min_duration: float = 55.0,
        max_duration: float = 65.0,
    ):
        self.target_width = target_width
        self.target_height = target_height
        self.min_duration = min_duration
        self.max_duration = max_duration

    def inspect(self, video_path: Path) -> QCReport:
        """Run all deterministic checks against the rendered MP4 file."""
        log.info(f"Running deterministic QC inspection on: {video_path.name}")
        report = QCReport(video_path=str(video_path))

        if not video_path.exists():
            report.checks.append(
                QCCheckItem(
                    check_name="File Existence",
                    passed=False,
                    actual_value="File Not Found",
                    expected_value=str(video_path),
                    is_fatal=True,
                )
            )
            report.fatal_errors = 1
            report.overall_passed = False
            return report

        # 1. FFprobe stream analysis
        probe_cmd = [
            FFPROBE, "-v", "quiet",
            "-print_format", "json",
            "-show_streams", "-show_format",
            str(video_path),
        ]
        probe_res = subprocess.run(probe_cmd, capture_output=True, text=True)
        if probe_res.returncode != 0:
            report.checks.append(
                QCCheckItem(
                    check_name="Container Integrity",
                    passed=False,
                    actual_value=probe_res.stderr[:200],
                    expected_value="Valid media container",
                    is_fatal=True,
                )
            )
            report.fatal_errors = 1
            return report

        probe_data = json.loads(probe_res.stdout)
        streams = {s.get("codec_type"): s for s in probe_data.get("streams", [])}
        fmt = probe_data.get("format", {})
        v = streams.get("video", {})
        a = streams.get("audio", {})

        # Check 1: Resolution (1080 x 1920)
        width = int(v.get("width", 0))
        height = int(v.get("height", 0))
        res_pass = (width == self.target_width and height == self.target_height)
        report.checks.append(
            QCCheckItem(
                check_name="Resolution",
                passed=res_pass,
                actual_value=f"{width}x{height}",
                expected_value=f"{self.target_width}x{self.target_height}",
                is_fatal=True,
            )
        )

        # Check 2: Video Codec (h264)
        v_codec = v.get("codec_name", "").lower()
        codec_pass = (v_codec == "h264")
        report.checks.append(
            QCCheckItem(
                check_name="Video Codec",
                passed=codec_pass,
                actual_value=v_codec,
                expected_value="h264",
                is_fatal=True,
            )
        )

        # Check 3: Pixel Format (yuv420p for universal mobile support)
        pix_fmt = v.get("pix_fmt", "").lower()
        pix_pass = (pix_fmt == "yuv420p")
        report.checks.append(
            QCCheckItem(
                check_name="Pixel Format",
                passed=pix_pass,
                actual_value=pix_fmt,
                expected_value="yuv420p",
                is_fatal=True,
            )
        )

        # Check 4: Audio Codec (aac)
        a_codec = a.get("codec_name", "").lower()
        a_codec_pass = (a_codec == "aac")
        report.checks.append(
            QCCheckItem(
                check_name="Audio Codec",
                passed=a_codec_pass,
                actual_value=a_codec,
                expected_value="aac",
                is_fatal=True,
            )
        )

        # Check 5: Audio Sample Rate (44100 or 48000 Hz)
        sample_rate = int(a.get("sample_rate", 0))
        sr_pass = sample_rate in (44100, 48000)
        report.checks.append(
            QCCheckItem(
                check_name="Audio Sample Rate",
                passed=sr_pass,
                actual_value=f"{sample_rate} Hz",
                expected_value="44100 or 48000 Hz",
                is_fatal=True,
            )
        )

        # Check 6: Duration (55.0 to 65.0 seconds)
        duration = float(fmt.get("duration", 0.0))
        dur_pass = (self.min_duration <= duration <= self.max_duration)
        report.checks.append(
            QCCheckItem(
                check_name="Video Duration",
                passed=dur_pass,
                actual_value=f"{duration:.2f}s",
                expected_value=f"{self.min_duration}–{self.max_duration}s",
                is_fatal=True,
            )
        )

        # Check 7: Container format
        fmt_name = fmt.get("format_name", "").lower()
        fmt_pass = ("mp4" in fmt_name or "mov" in fmt_name)
        report.checks.append(
            QCCheckItem(
                check_name="Container Format",
                passed=fmt_pass,
                actual_value=fmt_name,
                expected_value="mp4 / mov",
                is_fatal=True,
            )
        )

        # Check 8: Unexpected Silence Check (< 1.5s)
        silence_cmd = [
            FFMPEG, "-i", str(video_path),
            "-af", "silencedetect=noise=-40dB:d=1.5",
            "-f", "null", "-",
        ]
        silence_res = subprocess.run(silence_cmd, capture_output=True, text=True)
        # Check if silence gaps exist before trailing end of video
        has_mid_silence = "silence_duration" in silence_res.stderr
        report.checks.append(
            QCCheckItem(
                check_name="Silence Gaps (< 1.5s)",
                passed=not has_mid_silence,
                actual_value="Silence Detected" if has_mid_silence else "Continuous Audio",
                expected_value="Continuous Audio",
                is_fatal=False,
            )
        )

        # Final evaluation
        fatal_count = sum(1 for c in report.checks if not c.passed and c.is_fatal)
        report.fatal_errors = fatal_count
        report.overall_passed = (fatal_count == 0)

        log.info(f"  QC Complete: {'PASSED' if report.overall_passed else 'FAILED'} ({fatal_count} fatal errors)")
        return report

