"""
SubStation Alpha (.ASS) Subtitle Generator
==========================================
Generates styled burned-in subtitles with strict mobile safe-zone boundaries.
Enforces:
  - Vertical safe zone: MarginV = 570 (text bottom at Y = 1350 on 1080x1920 canvas)
  - Clear high-contrast styling: white text, black border + drop shadow
  - Chunking: 4 to 6 words per subtitle line for mobile legibility
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("reelfactory.subtitles")


def format_ass_timestamp(seconds: float) -> str:
    """Convert seconds to ASS format H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


class SubtitleGenerator:
    """Generates ASS subtitles formatted for vertical short-form video."""

    def __init__(
        self,
        font_name: str = "Inter Bold",
        font_size: int = 68,
        margin_v: int = 570,  # 570px from bottom = 1350px from top
    ):
        self.font_name = font_name
        self.font_size = font_size
        self.margin_v = margin_v

    def generate_from_scenes(
        self,
        scenes: list[dict],
        total_audio_duration: float,
        output_ass: Path,
    ) -> Path:
        """
        Generate ASS subtitle file proportional to scene durations and total audio length.
        """
        output_ass.parent.mkdir(parents=True, exist_ok=True)
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
Style: Reel,{self.font_name},{self.font_size},{white},{white},{black},{transparent},-1,0,0,0,100,100,0,0,1,4,2,2,60,60,{self.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = [header]

        # Calculate time scale to fit total synthesized audio
        script_sec = sum(s.get("duration_seconds", 10.0) for s in scenes)
        time_scale = total_audio_duration / script_sec if script_sec > 0 else 1.0

        current_time = 0.0
        for scene in scenes:
            narration = scene.get("narration", "").strip()
            words = narration.split()
            scene_duration = scene.get("duration_seconds", 10.0) * time_scale

            chunk_size = 5  # 5 words per subtitle card
            chunks = [words[i:i + chunk_size] for i in range(0, len(words), chunk_size)]
            if not chunks:
                continue

            chunk_duration = scene_duration / len(chunks)

            for chunk in chunks:
                start_str = format_ass_timestamp(current_time)
                end_str = format_ass_timestamp(current_time + chunk_duration)
                text = " ".join(chunk).replace("{", "\\{").replace("}", "\\}")
                lines.append(f"Dialogue: 0,{start_str},{end_str},Reel,,0,0,0,,{text}")
                current_time += chunk_duration

        output_ass.write_text("\n".join(lines), encoding="utf-8")
        log.info(f"Generated ASS subtitle file: {output_ass.name}")
        return output_ass

