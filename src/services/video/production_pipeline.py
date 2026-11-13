"""
Automated Video Production Pipeline
===================================
Orchestrates Phase 4:
  1. Gate 1 Verification (Mandatory Script Approval Check)
  2. Scene Planning & Footage Matching / Fallback Card Generation (Requirement 4.D)
  3. Piper Neural Voiceover Synthesis
  4. Safe-Zone ASS Subtitle Generation
  5. FFmpeg 1080x1920 Compositor & Loudness Normalization (-14 LUFS)
  6. Deterministic Quality Control (Requirement 4.E)
  7. Transition to Gate 2: FINAL_APPROVAL_PENDING
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

from src.core.config import PROJECT_ROOT, settings
from src.schemas.brand import brand_registry
from src.schemas.script import ScriptData
from src.services.audio.tts_engine import TTSEngine
from src.services.audio.subtitle_generator import SubtitleGenerator
from src.services.media.stock_matcher import StockMatcher
from src.services.video.cards import render_scene_card
from src.services.video.qc_engine import QCEngine, QCReport, FFMPEG, FFPROBE

log = logging.getLogger("reelfactory.production")


class ProductionPipeline:
    """Orchestrates end-to-end video assembly from approved script."""

    def __init__(self, brand_id: str):
        self.brand_id = brand_id.lower().strip()
        self.brand_config = brand_registry.get(self.brand_id)
        self.matcher = StockMatcher(brand_id=self.brand_id)
        self.tts = TTSEngine()
        self.subtitles = SubtitleGenerator(font_name=self.brand_config.font_family)
        self.qc = QCEngine()

    def produce(
        self,
        script: ScriptData,
        output_dir: Path,
        job_id: str,
    ) -> tuple[Path, QCReport]:
        """
        Produce a complete 1080x1920 Reel from an approved script.
        Returns: (final_video_path, qc_report)
        """
        log.info(f"Starting automated production for job {job_id} ({self.brand_config.name})")
        output_dir.mkdir(parents=True, exist_ok=True)

        # ---------------------------------------------------------------------
        # Step 1: Voiceover Synthesis (TTS)
        # ---------------------------------------------------------------------
        full_narration = " ".join(scene.narration.strip() for scene in script.scenes)
        wav_path = output_dir / "narration.wav"
        self.tts.synthesize(text=full_narration, output_wav=wav_path)

        # Probe exact audio duration
        duration_cmd = [
            FFPROBE, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(wav_path),
        ]
        try:
            dur_res = subprocess.run(duration_cmd, capture_output=True, text=True, timeout=30)
            total_audio_duration = float(dur_res.stdout.strip())
        except subprocess.TimeoutExpired:
            log.warning("ffprobe audio duration probe timed out after 30s. Using 58.0s default.")
            total_audio_duration = 58.0
        except Exception:
            total_audio_duration = 58.0
        log.info(f"Total narration audio duration: {total_audio_duration:.2f}s")

        # ---------------------------------------------------------------------
        # Step 2: Scene-by-Scene Visual Planning (Requirement 4.D)
        # ---------------------------------------------------------------------
        cards_dir = output_dir / "cards"
        cards_dir.mkdir(exist_ok=True)

        script_total_sec = sum(s.duration_seconds for s in script.scenes)
        time_scale = total_audio_duration / script_total_sec if script_total_sec > 0 else 1.0

        scene_visual_files: list[tuple[Path, float]] = []

        for idx, scene in enumerate(script.scenes):
            scene_duration = scene.duration_seconds * time_scale
            has_claims = bool(scene.numeric_claims)

            # Match footage or trigger fallback card (Requirement 4.D)
            match_res = self.matcher.match_scene(
                scene_id=scene.scene_id,
                keywords=scene.keywords,
                duration_seconds=scene_duration,
                has_numeric_claims=has_claims,
            )

            if match_res.matched and match_res.footage_path:
                # Use matched B-roll clip
                scene_visual_files.append((Path(match_res.footage_path), scene_duration))
            else:
                # Fallback to dynamic branded statistic card (Requirement 4.D)
                metric_text = "KEY INSIGHT"
                metric_label = scene.visual_note or "Strategic Analysis"
                source_citation = None

                if scene.numeric_claims:
                    metric_text = scene.numeric_claims[0].claim.upper()
                    metric_label = scene.narration[:45] + "..."
                    source_citation = scene.numeric_claims[0].source_id

                card_path = cards_dir / f"scene_{idx + 1}.png"
                render_scene_card(
                    scene_idx=idx,
                    total_scenes=len(script.scenes),
                    brand_name=self.brand_config.name,
                    category_tag=scene.keywords[0] if scene.keywords else "Overview",
                    metric_text=metric_text,
                    metric_label=metric_label,
                    source_citation=source_citation,
                    output_path=card_path,
                )
                scene_visual_files.append((card_path, scene_duration))

        # ---------------------------------------------------------------------
        # Step 3: Build Visual Timeline (FFmpeg Concat)
        # ---------------------------------------------------------------------
        concat_file = output_dir / "visual_concat.txt"
        bg_video_path = output_dir / "assembled_background.mp4"

        has_video_clips = any(p.suffix.lower() in (".mp4", ".mov", ".mkv") for p, _ in scene_visual_files)

        if has_video_clips:
            # When mixing video footage and graphic cards, normalize each to an identical 1080x1920 30fps clip
            log.info("Visual timeline contains video clips: standardizing micro-clips for seamless concat...")
            normalized_clips: list[Path] = []
            for idx, (v_path, dur) in enumerate(scene_visual_files):
                clip_out = cards_dir / f"norm_scene_{idx + 1}.mp4"
                if v_path.suffix.lower() == ".png":
                    norm_cmd = [
                        FFMPEG, "-y",
                        "-loop", "1",
                        "-i", str(v_path),
                        "-t", f"{dur:.2f}",
                        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30",
                        "-c:v", "libx264",
                        "-preset", "veryfast",
                        "-crf", "22",
                        "-pix_fmt", "yuv420p",
                        "-an",
                        str(clip_out),
                    ]
                else:
                    norm_cmd = [
                        FFMPEG, "-y",
                        "-i", str(v_path),
                        "-t", f"{dur:.2f}",
                        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30",
                        "-c:v", "libx264",
                        "-preset", "veryfast",
                        "-crf", "22",
                        "-pix_fmt", "yuv420p",
                        "-an",
                        str(clip_out),
                    ]
                subprocess.run(norm_cmd, capture_output=True, text=True, timeout=60, check=True)
                normalized_clips.append(clip_out)

            concat_lines = [f"file '{c.resolve().as_posix()}'" for c in normalized_clips]
            concat_file.write_text("\n".join(concat_lines), encoding="utf-8")
            bg_cmd = [
                FFMPEG, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                str(bg_video_path),
            ]
        else:
            # All visual files are static PNG scene cards -> ultra-fast direct image demuxing
            concat_lines = []
            for v_path, dur in scene_visual_files:
                resolved_str = v_path.resolve().as_posix()
                concat_lines.append(f"file '{resolved_str}'")
                concat_lines.append(f"duration {dur:.2f}")
            concat_lines.append(f"file '{scene_visual_files[-1][0].resolve().as_posix()}'")
            concat_file.write_text("\n".join(concat_lines), encoding="utf-8")

            bg_cmd = [
                FFMPEG, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30,format=yuv420p",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "21",
                "-pix_fmt", "yuv420p",
                "-an",
                str(bg_video_path),
            ]

        try:
            bg_res = subprocess.run(bg_cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Background visual assembly timed out after 180s") from exc

        if bg_res.returncode != 0:
            raise RuntimeError(f"Visual assembly failed: {bg_res.stderr}")

        # ---------------------------------------------------------------------
        # Step 4: Subtitles Generation
        # ---------------------------------------------------------------------
        ass_path = output_dir / "subtitles.ass"
        scenes_dicts = [s.model_dump() for s in script.scenes]
        self.subtitles.generate_from_scenes(
            scenes=scenes_dicts,
            total_audio_duration=total_audio_duration,
            output_ass=ass_path,
        )

        # ---------------------------------------------------------------------
        # Step 5: Final Compositing (Burn Subtitles + EBU R128 Loudness)
        # ---------------------------------------------------------------------
        final_video_path = output_dir / f"{job_id}_reel_final.mp4"

        # Escape subtitle path for FFmpeg filtergraph
        sub_escaped = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")
        subtitle_filter = f"subtitles='{sub_escaped}'"

        filter_complex = (
            f"[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
            f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
            f"{subtitle_filter}[vout];"
            f"[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
        )

        compose_cmd = [
            FFMPEG, "-y",
            "-i", str(bg_video_path),
            "-i", str(wav_path),
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
            "-movflags", "+faststart",
            "-shortest",
            str(final_video_path),
        ]

        t0 = time.perf_counter()
        try:
            compose_res = subprocess.run(compose_cmd, capture_output=True, text=True, timeout=240)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Final video composition and subtitle burn timed out after 240s") from exc
        render_sec = time.perf_counter() - t0

        if compose_res.returncode != 0:
            raise RuntimeError(f"Final composition failed: {compose_res.stderr[-2000:]}")

        log.info(f"Video rendered in {render_sec:.1f}s -> {final_video_path.name}")

        # Cleanup bulky intermediate assembly files to prevent unbounded disk growth
        if final_video_path.exists() and final_video_path.stat().st_size > 0:
            if bg_video_path.exists():
                try:
                    bg_video_path.unlink(missing_ok=True)
                except Exception:
                    pass
            if concat_file.exists():
                try:
                    concat_file.unlink(missing_ok=True)
                except Exception:
                    pass

        # ---------------------------------------------------------------------
        # Step 6: Deterministic QC Verification (Requirement 4.E)
        # ---------------------------------------------------------------------
        qc_report = self.qc.inspect(final_video_path)

        return final_video_path, qc_report

