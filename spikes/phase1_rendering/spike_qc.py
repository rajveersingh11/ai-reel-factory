"""
Phase 1 QC Spike — spike_qc.py
===============================
Standalone quality-control inspector using ffprobe.
Can be run independently on any MP4 file to validate it meets
Reel production standards.

Usage:
    python spikes/phase1_rendering/spike_qc.py path/to/video.mp4
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# QC thresholds (mirror .env.example values)
# ---------------------------------------------------------------------------
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
MIN_DURATION = 55.0
MAX_DURATION = 65.0
TARGET_LUFS = -14.0
LUFS_TOLERANCE = 3.0
MAX_SILENCE_GAP_SECONDS = 1.5
CAPTION_SAFE_TOP = 700      # pixels from top
CAPTION_SAFE_BOTTOM = 1350  # pixels from top (1920 - 570)


@dataclass
class QCResult:
    check: str
    passed: bool
    actual: str
    expected: str
    note: str = ""
    fatal: bool = True


@dataclass
class QCReport:
    video_path: str
    results: list[QCResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed or not r.fatal for r in self.results)

    @property
    def fatal_failures(self) -> list[QCResult]:
        return [r for r in self.results if not r.passed and r.fatal]

    def print_report(self) -> None:
        print(f"\n{'=' * 60}")
        print(f"QC REPORT: {Path(self.video_path).name}")
        print(f"{'=' * 60}")
        for r in self.results:
            icon = "✅" if r.passed else ("⚠️ " if not r.fatal else "❌")
            severity = "" if r.passed else (" [WARNING]" if not r.fatal else " [FATAL]")
            print(f"  {icon} {r.check}{severity}")
            if not r.passed:
                print(f"       Actual:   {r.actual}")
                print(f"       Expected: {r.expected}")
                if r.note:
                    print(f"       Note:     {r.note}")

        print(f"\n{'=' * 60}")
        if self.all_passed:
            print("RESULT: ✅ PASSED — ready for review")
        else:
            fatal = len(self.fatal_failures)
            print(f"RESULT: ❌ FAILED — {fatal} fatal issue(s)")
        print(f"{'=' * 60}\n")


def probe_video(video_path: Path) -> dict:
    """Run ffprobe and return parsed JSON output."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return json.loads(result.stdout)


def measure_loudness(video_path: Path) -> dict | None:
    """
    Use FFmpeg's ebur128 filter to measure integrated loudness (LUFS).
    Returns dict with 'I' (integrated LUFS), 'TP' (true peak dBFS), 'LRA'.
    """
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-af", "ebur128=peak=true",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # ebur128 output goes to stderr
    output = result.stderr

    loudness: dict[str, float] = {}
    for line in output.splitlines():
        line = line.strip()
        if "I:" in line and "LUFS" in line:
            try:
                loudness["I"] = float(line.split("I:")[1].split("LUFS")[0].strip())
            except (IndexError, ValueError):
                pass
        if "True Peak:" in line and "dBFS" in line:
            try:
                loudness["TP"] = float(line.split("True Peak:")[1].split("dBFS")[0].strip())
            except (IndexError, ValueError):
                pass
        if "LRA:" in line and "LU" in line:
            try:
                loudness["LRA"] = float(line.split("LRA:")[1].split("LU")[0].strip())
            except (IndexError, ValueError):
                pass

    return loudness if loudness else None


def detect_silence(video_path: Path, max_gap: float = MAX_SILENCE_GAP_SECONDS) -> list[dict]:
    """
    Use FFmpeg's silencedetect filter to find silence gaps.
    Returns list of silence periods that exceed the threshold.
    """
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-af", f"silencedetect=noise=-40dB:d={max_gap}",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stderr

    silences: list[dict] = []
    current: dict = {}
    for line in output.splitlines():
        if "silence_start" in line:
            try:
                current = {"start": float(line.split("silence_start:")[1].strip())}
            except (IndexError, ValueError):
                pass
        elif "silence_end" in line and current:
            try:
                parts = line.split("|")
                current["end"] = float(parts[0].split("silence_end:")[1].strip())
                current["duration"] = float(parts[1].split("silence_duration:")[1].strip())
                silences.append(current)
                current = {}
            except (IndexError, ValueError):
                pass

    return silences


def run_full_qc(video_path: Path) -> QCReport:
    """Run all QC checks and return a QCReport."""
    report = QCReport(video_path=str(video_path))

    if not video_path.exists():
        report.results.append(QCResult(
            check="File exists",
            passed=False,
            actual="File not found",
            expected=str(video_path),
            fatal=True,
        ))
        return report

    # --- Probe ---
    probe = probe_video(video_path)
    streams = {s["codec_type"]: s for s in probe.get("streams", [])}
    fmt = probe.get("format", {})
    v = streams.get("video", {})
    a = streams.get("audio", {})

    # --- Check 1: Resolution ---
    width = int(v.get("width", 0))
    height = int(v.get("height", 0))
    report.results.append(QCResult(
        check="Resolution",
        passed=(width == TARGET_WIDTH and height == TARGET_HEIGHT),
        actual=f"{width}x{height}",
        expected=f"{TARGET_WIDTH}x{TARGET_HEIGHT}",
        fatal=True,
    ))

    # --- Check 2: Aspect ratio ---
    dar = v.get("display_aspect_ratio", "unknown")
    report.results.append(QCResult(
        check="Display aspect ratio (DAR)",
        passed=(dar == "9:16"),
        actual=dar,
        expected="9:16",
        fatal=False,  # Non-fatal if pixel dimensions are correct
        note="Calculated from width/height; may show as unknown",
    ))

    # --- Check 3: Video codec ---
    v_codec = v.get("codec_name", "MISSING")
    report.results.append(QCResult(
        check="Video codec",
        passed=(v_codec == "h264"),
        actual=v_codec,
        expected="h264",
        fatal=True,
    ))

    # --- Check 4: Pixel format ---
    pix_fmt = v.get("pix_fmt", "MISSING")
    report.results.append(QCResult(
        check="Pixel format",
        passed=(pix_fmt == "yuv420p"),
        actual=pix_fmt,
        expected="yuv420p",
        fatal=True,
        note="Required for maximum device compatibility",
    ))

    # --- Check 5: Frame rate ---
    r_frame_rate = v.get("r_frame_rate", "0/1")
    try:
        num, den = map(int, r_frame_rate.split("/"))
        fps = num / den
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    report.results.append(QCResult(
        check="Frame rate",
        passed=(abs(fps - 30.0) < 0.5),
        actual=f"{fps:.2f} fps",
        expected="30 fps",
        fatal=False,
    ))

    # --- Check 6: Audio codec ---
    a_codec = a.get("codec_name", "MISSING")
    report.results.append(QCResult(
        check="Audio codec",
        passed=(a_codec == "aac"),
        actual=a_codec,
        expected="aac",
        fatal=True,
    ))

    # --- Check 7: Audio sample rate ---
    sample_rate = int(a.get("sample_rate", 0))
    report.results.append(QCResult(
        check="Audio sample rate",
        passed=(sample_rate in (44100, 48000)),
        actual=f"{sample_rate} Hz",
        expected="44100 or 48000 Hz",
        fatal=True,
    ))

    # --- Check 8: Audio channels ---
    channels = int(a.get("channels", 0))
    report.results.append(QCResult(
        check="Audio channels",
        passed=(channels in (1, 2)),
        actual=f"{channels} channel(s)",
        expected="1 (mono) or 2 (stereo)",
        fatal=False,
    ))

    # --- Check 9: Duration ---
    duration = float(fmt.get("duration", 0))
    report.results.append(QCResult(
        check="Duration",
        passed=(MIN_DURATION <= duration <= MAX_DURATION),
        actual=f"{duration:.2f}s",
        expected=f"{MIN_DURATION}–{MAX_DURATION}s",
        fatal=True,
    ))

    # --- Check 10: Container format ---
    fmt_name = fmt.get("format_name", "")
    report.results.append(QCResult(
        check="Container format",
        passed=("mp4" in fmt_name or "mov" in fmt_name),
        actual=fmt_name,
        expected="mp4 / mov_mp4_m4a_3gp_3g2_mj2",
        fatal=True,
    ))

    # --- Check 11: Silence detection ---
    print("  Checking for unexpected silence (this takes a moment)...")
    silences = detect_silence(video_path, MAX_SILENCE_GAP_SECONDS)
    # Exclude trailing silence (last 1 second of video)
    significant_silences = [s for s in silences if s.get("start", 0) < duration - 1.0]
    report.results.append(QCResult(
        check=f"Unexpected silence gaps > {MAX_SILENCE_GAP_SECONDS}s",
        passed=(len(significant_silences) == 0),
        actual=f"{len(significant_silences)} gap(s): {significant_silences[:3]}",
        expected="0 significant gaps",
        fatal=False,
        note="Trailing silence (last 1s) is excluded",
    ))

    return report


def main() -> int:
    if len(sys.argv) < 2:
        # Default: check the spike output
        video_path = Path(__file__).parent / "output" / "reel_spike_v1.mp4"
        print(f"No path provided, checking default: {video_path}")
    else:
        video_path = Path(sys.argv[1])

    report = run_full_qc(video_path)
    report.print_report()
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
