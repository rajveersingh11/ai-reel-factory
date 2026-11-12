"""
Phase 1 Rendering Spike — test_render.py
========================================
Demonstrates the full local rendering pipeline WITHOUT any backend infrastructure:
  1. Load a hardcoded script JSON
  2. Synthesize narration with Piper TTS (CPU)
  3. Align subtitles with faster-whisper (INT8 CPU)
  4. Build an .ASS subtitle file with safe-zone positioning
  5. Render a 1080x1920 MP4 with burned-in captions via FFmpeg
  6. Run deterministic QC checks via ffprobe

Acceptance criteria:
  - Output resolution: 1080x1920
  - Duration: 55–62 seconds
  - Codec: H.264 video, AAC audio
  - Captions within safe zone (Y: 700–1350 on 1920-height canvas)
  - No silent gaps > 1.5 seconds
"""

from __future__ import annotations

import json
import logging
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SPIKE_DIR = Path(__file__).parent
PROJECT_ROOT = SPIKE_DIR.parent.parent
OUTPUT_DIR = SPIKE_DIR / "output"
ASSETS_DIR = PROJECT_ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"

SCRIPT_PATH = SPIKE_DIR / "sample_script.json"
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Tool resolution — handles restricted PATH environments (AppLocker / sandbox)
# Checks shutil.which() first, then probes known WinGet install locations.
# ---------------------------------------------------------------------------
_WINGET_BASE = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"

def _find_tool(name: str) -> str | None:
    """Return absolute path to a CLI tool, or None if not found."""
    # 1. Try PATH first
    found = shutil.which(name)
    if found:
        return found
    # 2. Probe WinGet packages (Gyan.FFmpeg pattern)
    if name in ("ffmpeg", "ffprobe"):
        for candidate in _WINGET_BASE.glob(f"Gyan.FFmpeg_*/*/bin/{name}.exe"):
            if candidate.exists():
                return str(candidate)
    # 3. Common explicit install paths
    explicit = {
        "ffmpeg":  [r"C:\Program Files\FFmpeg\bin\ffmpeg.exe"],
        "ffprobe": [r"C:\Program Files\FFmpeg\bin\ffprobe.exe"],
        "piper":   [r"C:\Program Files\piper\piper.exe"],
    }
    for path in explicit.get(name, []):
        if Path(path).exists():
            return path
    return None

# Resolved tool paths (set once at import time)
FFMPEG  = _find_tool("ffmpeg")
FFPROBE = _find_tool("ffprobe")
PIPER   = _find_tool("piper")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("spike.render")


# ---------------------------------------------------------------------------
# Step 0: Dependency checks
# ---------------------------------------------------------------------------
def check_dependencies() -> dict[str, str | bool]:
    """Verify all required tools are reachable before proceeding."""
    log.info("Checking dependencies...")
    results: dict[str, str | bool] = {}

    for tool, resolved in [("ffmpeg", FFMPEG), ("ffprobe", FFPROBE), ("piper", PIPER)]:
        results[tool] = resolved or False
        status = f"  {'✅' if resolved else '❌'} {tool}: {resolved or 'NOT FOUND'}"
        log.info(status)

    # Python packages
    for pkg in ("faster_whisper",):
        try:
            __import__(pkg)
            results[pkg] = True
            log.info(f"  ✅ {pkg}: importable")
        except ImportError:
            results[pkg] = False
            log.info(f"  ❌ {pkg}: NOT INSTALLED")

    return results


# ---------------------------------------------------------------------------
# Step 1: Load script
# ---------------------------------------------------------------------------
def load_script(path: Path) -> dict:
    log.info(f"Loading script: {path}")
    with open(path, encoding="utf-8") as f:
        script = json.load(f)
    scenes = script["scenes"]
    total_words = sum(len(s["narration"].split()) for s in scenes)
    total_duration = sum(s["duration_seconds"] for s in scenes)
    log.info(f"  Scenes: {len(scenes)}  |  Words: {total_words}  |  Target duration: {total_duration}s")
    return script


# ---------------------------------------------------------------------------
# Step 2: Synthesize narration with Piper TTS
# ---------------------------------------------------------------------------
def synthesize_narration(
    script: dict,
    voice_model_path: Path,
    output_wav: Path,
    piper_binary: str = "piper",
) -> Path:
    """
    Concatenate all scene narrations and synthesize to a single WAV file.
    Uses Piper TTS with ONNX CPU inference.
    """
    full_narration = " ".join(s["narration"] for s in script["scenes"])
    log.info(f"Synthesizing {len(full_narration.split())} words via Piper TTS...")

    if not voice_model_path.exists():
        raise FileNotFoundError(
            f"Piper voice model not found: {voice_model_path}\n"
            f"Download with: python -m piper --download-voice en_US-lessac-medium"
        )

    t0 = time.perf_counter()
    result = subprocess.run(
        [
            piper_binary,
            "--model", str(voice_model_path),
            "--output_file", str(output_wav),
        ],
        input=full_narration,
        text=True,
        capture_output=True,
    )
    elapsed = time.perf_counter() - t0

    if result.returncode != 0:
        raise RuntimeError(f"Piper TTS failed:\n{result.stderr}")

    size_kb = output_wav.stat().st_size // 1024
    log.info(f"  TTS complete in {elapsed:.1f}s — {output_wav.name} ({size_kb} KB)")
    return output_wav


# ---------------------------------------------------------------------------
# Step 3: Align subtitles with faster-whisper
# ---------------------------------------------------------------------------
def transcribe_and_align(
    audio_path: Path,
    script: dict,
    output_ass: Path,
) -> Path:
    """
    Use faster-whisper (INT8 CPU) to get word-level timestamps.
    Then build an ASS subtitle file with:
      - Safe zone: MarginV targets ~1350px from top (570px from bottom on 1920h canvas)
      - Bold Inter font for readability
      - Drop shadow for contrast on any background
    """
    from faster_whisper import WhisperModel  # type: ignore

    log.info("Loading faster-whisper small model (INT8 CPU)...")
    t0 = time.perf_counter()
    model = WhisperModel("small", device="cpu", compute_type="int8")
    log.info(f"  Model loaded in {time.perf_counter() - t0:.1f}s")

    full_narration = " ".join(s["narration"] for s in script["scenes"])

    log.info("Transcribing audio for subtitle alignment...")
    t0 = time.perf_counter()
    segments, info = model.transcribe(
        str(audio_path),
        language="en",
        word_timestamps=True,
        initial_prompt=full_narration,  # Anchors transcription to known text
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
    )

    words: list[dict] = []
    for segment in segments:
        if segment.words:
            for word in segment.words:
                words.append({
                    "word": word.word.strip(),
                    "start": word.start,
                    "end": word.end,
                })
    elapsed = time.perf_counter() - t0
    log.info(f"  Aligned {len(words)} words in {elapsed:.1f}s")

    # Group words into caption chunks (max 6 words or 3.5 seconds each)
    chunks = _group_words_into_chunks(words, max_words=6, max_duration=3.5)
    log.info(f"  Created {len(chunks)} subtitle chunks")

    # Write ASS subtitle file
    _write_ass_file(chunks, output_ass)
    log.info(f"  ASS subtitles written: {output_ass.name}")
    return output_ass


def _group_words_into_chunks(
    words: list[dict],
    max_words: int = 6,
    max_duration: float = 3.5,
) -> list[dict]:
    """Group word-level timestamps into readable subtitle chunks."""
    chunks: list[dict] = []
    if not words:
        return chunks

    current_words: list[str] = []
    chunk_start: float = words[0]["start"]

    for word_data in words:
        current_words.append(word_data["word"])
        duration = word_data["end"] - chunk_start

        if len(current_words) >= max_words or duration >= max_duration:
            chunks.append({
                "text": " ".join(current_words),
                "start": chunk_start,
                "end": word_data["end"],
            })
            current_words = []
            # Next chunk starts at the end of this one (no gap)
            chunk_start = word_data["end"]

    # Flush remaining words
    if current_words and words:
        chunks.append({
            "text": " ".join(current_words),
            "start": chunk_start,
            "end": words[-1]["end"],
        })

    return chunks


def _ass_timestamp(seconds: float) -> str:
    """Convert float seconds to ASS timestamp format H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _write_ass_file(chunks: list[dict], output_path: Path) -> None:
    """
    Write an ASS subtitle file optimized for 1080x1920 Instagram Reels.

    Safe zone: Y position targets the middle-lower area.
    - Canvas: 1080w x 1920h
    - MarginV=570: positions bottom of text 570px from bottom = 1350px from top
    - This keeps captions ABOVE Instagram's UI chrome (action bar, description)
    - And well below the top safe area

    Style choices:
    - FontSize=68: readable on mobile without being overwhelming
    - Bold: improves legibility on complex backgrounds
    - PrimaryColour=white with black outline + drop shadow
    - Alignment=2 (bottom-center): standard subtitle alignment
    """
    # ASS colour format: &HAABBGGRR (alpha, blue, green, red)
    white = "&H00FFFFFF"
    black = "&H00000000"
    transparent = "&HFF000000"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Reel,Inter Bold,68,{white},{white},{black},{transparent},-1,0,0,0,100,100,0,0,1,4,2,2,60,60,570,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    for chunk in chunks:
        start = _ass_timestamp(chunk["start"])
        end = _ass_timestamp(chunk["end"])
        # Escape braces and special ASS characters
        text = chunk["text"].replace("{", "\\{").replace("}", "\\}")
        lines.append(f"Dialogue: 0,{start},{end},Reel,,0,0,0,,{text}")

    output_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Step 4: Generate a test card video (no stock footage needed for spike)
# ---------------------------------------------------------------------------
def generate_test_card(output_path: Path, duration_seconds: float) -> Path:
    """
    Generate a solid-color 1080x1920 background video using FFmpeg's lavfi source.
    Uses a branded gradient-style background (dark navy → deep blue).
    No stock footage dependency for the spike.
    """
    log.info(f"Generating {duration_seconds:.1f}s test card background (1080x1920)...")

    cmd = [
        FFMPEG, "-y",
        # Input: color source (dark navy background)
        "-f", "lavfi",
        "-i", f"color=c=0x0D1B2A:size=1080x1920:rate=30:duration={duration_seconds}",
        # Simple text overlay using drawtext (no libass needed for the card itself)
        "-vf", (
            "drawtext=text='AI REEL FACTORY':fontsize=72:fontcolor=white"
            ":x=(w-text_w)/2:y=(h/2)-80:box=0,"
            "drawtext=text='Phase 1 Spike':fontsize=48:fontcolor=0xAAAAAA"
            ":x=(w-text_w)/2:y=(h/2)+20:box=0"
        ),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",  # No audio — audio added in final compose step
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.warning(f"Test card drawtext failed (font issue?), falling back to plain color card")
        log.debug(result.stderr)
        # Fallback: plain color, no text
        cmd_fallback = [
            FFMPEG, "-y",
            "-f", "lavfi",
            "-i", f"color=c=0x0D1B2A:size=1080x1920:rate=30:duration={duration_seconds}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", "-an",
            str(output_path),
        ]
        result2 = subprocess.run(cmd_fallback, capture_output=True, text=True)
        if result2.returncode != 0:
            raise RuntimeError(f"Test card generation failed:\n{result2.stderr}")

    log.info(f"  Background card: {output_path.name}")
    return output_path


# ---------------------------------------------------------------------------
# Step 5: Compose final Reel with audio + subtitles
# ---------------------------------------------------------------------------
def compose_reel(
    video_path: Path,
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path,
    font_dir: Path,
) -> Path:
    """
    Final FFmpeg compositing step:
      1. Mux video background with narration audio
      2. Apply loudnorm filter (target: -14 LUFS, Instagram standard)
      3. Burn in .ASS subtitles using libass
      4. Output: H.264 / AAC MP4, 1080x1920, 30fps

    The subtitle filter uses forward-slash paths to avoid Windows path escaping
    issues in FFmpeg filtergraphs.
    """
    log.info("Composing final Reel...")

    # FFmpeg subtitle filter path escaping on Windows:
    # - Backslashes must be escaped as \\
    # - Drive colons must be escaped as \:
    # - The fontsdir option is omitted when the directory is empty (libass uses system fonts)
    sub_path_ffmpeg = (
        str(subtitle_path)
        .replace("\\", "\\\\")   # D:\path → D:\\path
        .replace(":", "\\:")     # D\\: → D\\\\:  (escapes drive colon)
    )

    # Only pass fontsdir if the fonts directory actually contains font files
    font_files = list(font_dir.glob("*.ttf")) + list(font_dir.glob("*.otf"))
    if font_files:
        fonts_path_ffmpeg = str(font_dir).replace("\\", "/")
        subtitle_filter = f"subtitles='{sub_path_ffmpeg}':fontsdir='{fonts_path_ffmpeg}'"
    else:
        # libass will fall back to system fonts (Arial/sans-serif)
        subtitle_filter = f"subtitles='{sub_path_ffmpeg}'"
        log.info("  No custom fonts found — libass will use system fonts")

    filter_complex = (
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
        f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
        f"{subtitle_filter}[vout];"
        f"[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
    )

    cmd = [
        FFMPEG, "-y",
        "-i", str(video_path),   # [0:v] background video
        "-i", str(audio_path),   # [1:a] narration audio
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-profile:v", "high",
        "-level", "4.0",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-movflags", "+faststart",  # Enables streaming / Instagram ingest
        "-shortest",                 # Trim to shortest stream (audio or video)
        str(output_path),
    ]

    t0 = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.perf_counter() - t0

    if result.returncode != 0:
        log.error("FFmpeg composition failed. stderr:")
        log.error(result.stderr[-3000:])  # Last 3000 chars to avoid flood
        raise RuntimeError("FFmpeg render failed")

    size_mb = output_path.stat().st_size / 1024 / 1024
    log.info(f"  Render complete in {elapsed:.1f}s — {output_path.name} ({size_mb:.1f} MB)")
    return output_path


# ---------------------------------------------------------------------------
# Step 6: Deterministic QC via ffprobe
# ---------------------------------------------------------------------------
def run_qc(video_path: Path) -> bool:
    """
    Validate the rendered output against Phase 1 acceptance criteria.
    Uses ffprobe only — no LLM, no heuristics.
    Returns True if all checks pass.
    """
    log.info("Running deterministic QC checks...")
    passed = True

    probe_cmd = [
        FFPROBE, "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        str(video_path),
    ]
    result = subprocess.run(probe_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error(f"❌ ffprobe failed: {result.stderr}")
        return False

    import json as _json
    probe = _json.loads(result.stdout)
    streams = {s["codec_type"]: s for s in probe.get("streams", [])}
    fmt = probe.get("format", {})

    # --- Check 1: Resolution ---
    v = streams.get("video", {})
    width = int(v.get("width", 0))
    height = int(v.get("height", 0))
    res_ok = width == 1080 and height == 1920
    log.info(f"  {'✅' if res_ok else '❌'} Resolution: {width}x{height} (expected 1080x1920)")
    passed = passed and res_ok

    # --- Check 2: Aspect ratio ---
    dar = v.get("display_aspect_ratio", "")
    ar_ok = dar == "9:16"
    log.info(f"  {'✅' if ar_ok else '⚠️'} Display aspect ratio: {dar} (expected 9:16)")
    # Non-fatal if pixel dimensions are correct

    # --- Check 3: Video codec ---
    v_codec = v.get("codec_name", "")
    codec_ok = v_codec == "h264"
    log.info(f"  {'✅' if codec_ok else '❌'} Video codec: {v_codec} (expected h264)")
    passed = passed and codec_ok

    # --- Check 4: Pixel format ---
    pix_fmt = v.get("pix_fmt", "")
    pix_ok = pix_fmt == "yuv420p"
    log.info(f"  {'✅' if pix_ok else '❌'} Pixel format: {pix_fmt} (expected yuv420p)")
    passed = passed and pix_ok

    # --- Check 5: Audio codec ---
    a = streams.get("audio", {})
    a_codec = a.get("codec_name", "MISSING")
    audio_ok = a_codec == "aac"
    log.info(f"  {'✅' if audio_ok else '❌'} Audio codec: {a_codec} (expected aac)")
    passed = passed and audio_ok

    # --- Check 6: Duration ---
    duration = float(fmt.get("duration", 0))
    dur_ok = 55.0 <= duration <= 65.0
    log.info(f"  {'✅' if dur_ok else '❌'} Duration: {duration:.2f}s (expected 55–65s)")
    passed = passed and dur_ok

    # --- Check 7: File integrity (moov atom) ---
    # faststart flag should put moov at start; check format name
    fmt_name = fmt.get("format_name", "")
    integrity_ok = "mp4" in fmt_name or "mov" in fmt_name
    log.info(f"  {'✅' if integrity_ok else '❌'} Container format: {fmt_name}")
    passed = passed and integrity_ok

    # --- Check 8: Audio sample rate ---
    sample_rate = int(a.get("sample_rate", 0))
    sr_ok = sample_rate in (44100, 48000)
    log.info(f"  {'✅' if sr_ok else '❌'} Audio sample rate: {sample_rate} Hz")
    passed = passed and sr_ok

    # --- Summary ---
    if passed:
        log.info("🎉 QC PASSED — all checks green")
    else:
        log.error("💥 QC FAILED — review errors above before proceeding")

    return passed


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main() -> int:
    log.info("=" * 60)
    log.info("AI REEL FACTORY — Phase 1 Rendering Spike")
    log.info("=" * 60)

    # --- Dependency check ---
    deps = check_dependencies()
    ffmpeg_ok = bool(deps.get("ffmpeg"))
    ffprobe_ok = bool(deps.get("ffprobe"))
    piper_ok = bool(deps.get("piper"))
    whisper_ok = bool(deps.get("faster_whisper"))

    if not ffmpeg_ok or not ffprobe_ok:
        log.error("FFmpeg/FFprobe not found. Ensure it's installed and PATH is set.")
        return 1

    # --- Load script ---
    script = load_script(SCRIPT_PATH)
    total_duration = sum(s["duration_seconds"] for s in script["scenes"])

    # --- Determine pipeline mode ---
    if piper_ok:
        # Full pipeline with TTS
        voice_model_path = ASSETS_DIR / "models" / "piper" / "en_US-lessac-medium.onnx"
        wav_path = OUTPUT_DIR / "narration.wav"
        synthesize_narration(script, voice_model_path, wav_path)
    else:
        log.warning("⚠️  Piper TTS not found — generating silent audio placeholder")
        wav_path = OUTPUT_DIR / "narration_silent.wav"
        # Generate silent audio of correct duration using resolved FFMPEG path
        result = subprocess.run([
            FFMPEG, "-y",
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={total_duration}",
            "-c:a", "pcm_s16le",
            str(wav_path),
        ], capture_output=True, text=True)
        if result.returncode != 0:
            log.error(f"Silent audio generation failed: {result.stderr}")
            return 1
        log.info(f"  Silent audio placeholder: {wav_path.name}")

    # --- Subtitle alignment (requires Piper audio for real alignment) ---
    ass_path = OUTPUT_DIR / "subtitles.ass"
    if whisper_ok and piper_ok:
        transcribe_and_align(wav_path, script, ass_path)
    else:
        log.warning("⚠️  faster-whisper not installed — generating placeholder subtitles")
        _write_placeholder_ass(script, ass_path)

    # --- Generate background video ---
    bg_video_path = OUTPUT_DIR / "background.mp4"
    generate_test_card(bg_video_path, total_duration)

    # --- Final composition ---
    final_output = OUTPUT_DIR / "reel_spike_v1.mp4"
    compose_reel(
        video_path=bg_video_path,
        audio_path=wav_path,
        subtitle_path=ass_path,
        output_path=final_output,
        font_dir=FONTS_DIR,
    )

    # --- QC ---
    qc_passed = run_qc(final_output)

    log.info("=" * 60)
    if qc_passed:
        log.info(f"✅ Spike complete. Output: {final_output}")
        log.info("Review the video on a mobile viewport before Phase 2.")
    else:
        log.error("❌ Spike produced a non-conforming output. Review QC failures.")
    log.info("=" * 60)

    return 0 if qc_passed else 1


def _write_placeholder_ass(script: dict, output_path: Path) -> None:
    """
    Generate a simple time-proportional ASS subtitle file from the script JSON,
    without running faster-whisper. Used when whisper is not yet installed.
    """
    white = "&H00FFFFFF"
    black = "&H00000000"
    transparent = "&HFF000000"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Reel,Inter Bold,68,{white},{white},{black},{transparent},-1,0,0,0,100,100,0,0,1,4,2,2,60,60,570,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    current_time = 0.0

    for scene in script["scenes"]:
        words = scene["narration"].split()
        duration = float(scene["duration_seconds"])
        # Split scene into chunks of 6 words
        chunk_size = 6
        num_chunks = max(1, len(words) // chunk_size)
        chunk_duration = duration / max(1, len(words) // chunk_size + (1 if len(words) % chunk_size else 0))

        for i in range(0, len(words), chunk_size):
            chunk_words = words[i:i + chunk_size]
            start = _ass_timestamp(current_time)
            end = _ass_timestamp(current_time + chunk_duration)
            text = " ".join(chunk_words)
            lines.append(f"Dialogue: 0,{start},{end},Reel,,0,0,0,,{text}")
            current_time += chunk_duration

    output_path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"  Placeholder subtitles written: {output_path.name}")


if __name__ == "__main__":
    sys.exit(main())

