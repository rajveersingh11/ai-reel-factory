"""
SubStation Alpha (.ASS) Kinetic Subtitle Generator
=================================================
Generates high-retention, viral kinetic burned-in subtitles for 9:16 vertical short-form video.

Features (Option 3):
  1. Word-by-word active highlight (Karaoke / pop-in):
     - Active word scales up slightly (\\fscx112\\fscy112) in brand accent color.
     - Inactive words remain high-contrast crisp white.
  2. Mobile safe-zone compliance:
     - MarginV = 570 (text bottom baseline at Y = 1350 on 1080x1920 canvas).
     - Keeps subtitles clear of Instagram / Shorts UI overlays and top status bars.
  3. Chunking:
     - 3 to 5 words per subtitle card for optimal mobile reading velocity.
  4. Brand color theming:
     - Automatically adapts highlight color to brand identity (e.g. Cyan for Skyon, Gold for R4Realty).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger("reelfactory.subtitles")


def format_ass_timestamp(seconds: float) -> str:
    """Convert seconds to ASS format H:MM:SS.cc"""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def hex_to_ass_color(hex_str: str, alpha: str = "00") -> str:
    """
    Convert standard #RRGGBB hex color to ASS &HAABBGGRR& format.
    ASS uses BGR color ordering preceded by hexadecimal alpha (00 = fully opaque).
    """
    if not hex_str:
        return f"&H{alpha}00FFFF&"  # Default neon yellow

    hex_clean = hex_str.strip().lstrip("#")
    if len(hex_clean) == 6:
        r, g, b = hex_clean[0:2], hex_clean[2:4], hex_clean[4:6]
        return f"&H{alpha}{b.upper()}{g.upper()}{r.upper()}&"
    return f"&H{alpha}00FFFF&"


class SubtitleGenerator:
    """Generates ASS subtitles formatted for vertical short-form video."""

    def __init__(
        self,
        font_name: str = "Inter Bold",
        font_size: int = 70,
        margin_v: int = 570,  # 570px from bottom = 1350px from top
        primary_color: str = "&H00FFFFFF&",  # Base text (Crisp white)
        highlight_color: str = "&H0000FFFF&",  # Active word highlight (Neon Yellow / Brand accent)
        outline_color: str = "&H00000000&",  # Bold black border
        shadow_color: str = "&H90000000&",  # Deep drop shadow
        words_per_chunk: int = 4,  # Optimal mobile readability (3-5 words)
    ):
        self.font_name = font_name
        self.font_size = font_size
        self.margin_v = margin_v
        self.primary_color = primary_color
        self.highlight_color = highlight_color
        self.outline_color = outline_color
        self.shadow_color = shadow_color
        self.words_per_chunk = max(2, min(words_per_chunk, 6))

    def generate_from_scenes(
        self,
        scenes: list[dict],
        total_audio_duration: float,
        output_ass: Path,
        highlight_color: Optional[str] = None,
        kinetic: bool = True,
        uppercase: bool = True,
    ) -> Path:
        """
        Generate ASS subtitle file proportional to scene durations and total audio length.
        
        When kinetic=True:
          Emits word-level active highlight events where the currently spoken word pops
          in highlight_color with a subtle 112% scale up.
        When kinetic=False:
          Emits standard phrase-level cards.
        """
        output_ass.parent.mkdir(parents=True, exist_ok=True)
        active_highlight = highlight_color or self.highlight_color

        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Reel,{self.font_name},{self.font_size},{self.primary_color},{self.primary_color},{self.outline_color},{self.shadow_color},-1,0,0,0,100,100,1,0,1,5,3,2,60,60,{self.margin_v},1

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
            if not narration:
                continue

            raw_words = narration.split()
            scene_duration = scene.get("duration_seconds", 10.0) * time_scale

            # Clean and format words
            if uppercase:
                words = [w.upper().replace("{", "\\{").replace("}", "\\}") for w in raw_words]
            else:
                words = [w.replace("{", "\\{").replace("}", "\\}") for w in raw_words]

            # Partition into readable 3-5 word chunks
            chunks = [words[i:i + self.words_per_chunk] for i in range(0, len(words), self.words_per_chunk)]
            if not chunks:
                continue

            total_words_in_scene = len(words)

            for chunk in chunks:
                # Proportional duration based on word count in chunk
                chunk_fraction = len(chunk) / total_words_in_scene
                chunk_duration = scene_duration * chunk_fraction

                if kinetic and len(chunk) > 1:
                    # Word-by-word pop-in animation
                    word_duration = chunk_duration / len(chunk)
                    for w_idx, active_word in enumerate(chunk):
                        w_start = current_time + (w_idx * word_duration)
                        w_end = current_time + ((w_idx + 1) * word_duration)

                        # Assemble line with active word highlighted
                        line_parts = []
                        for idx, word in enumerate(chunk):
                            if idx == w_idx:
                                # Highlighted and subtly popped active word
                                line_parts.append(f"{{\\c{active_highlight}\\fscx112\\fscy112}}{word}{{\\rReel}}")
                            else:
                                line_parts.append(word)

                        start_str = format_ass_timestamp(w_start)
                        end_str = format_ass_timestamp(w_end)
                        line_text = " ".join(line_parts)
                        lines.append(f"Dialogue: 0,{start_str},{end_str},Reel,,0,0,0,,{line_text}")
                else:
                    # Static chunk card
                    start_str = format_ass_timestamp(current_time)
                    end_str = format_ass_timestamp(current_time + chunk_duration)
                    text = " ".join(chunk)
                    lines.append(f"Dialogue: 0,{start_str},{end_str},Reel,,0,0,0,,{text}")

                current_time += chunk_duration

        output_ass.write_text("\n".join(lines), encoding="utf-8")
        log.info(f"Generated kinetic ASS subtitle file: {output_ass.name} ({len(lines) - 1} dialogue events)")
        return output_ass
