"""
Piper Neural TTS Audio Synthesis Engine
=======================================
Synthesizes voiceover narration using local Piper TTS (ONNX CPU).
Runs in ~1-2 seconds for a 60-second script on CPU with < 100 MB RAM.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from src.core.config import PROJECT_ROOT, settings

log = logging.getLogger("reelfactory.tts")


class TTSEngine:
    """Wraps Piper neural TTS synthesis."""

    def __init__(self, voice_model: Optional[str] = None):
        self.voice_name = voice_model or settings.DEFAULT_VOICE
        self.model_path = (
            PROJECT_ROOT / "assets" / "models" / "piper" / f"{self.voice_name}.onnx"
        )
        self._piper_cmd = self._resolve_piper_cmd()

    def _resolve_piper_cmd(self) -> list[str]:
        # 1. Try PATH
        found = shutil.which("piper")
        if found:
            return [found]
        # 2. Python module invocation
        return [sys.executable, "-m", "piper"]

    def synthesize(self, text: str, output_wav: Path) -> Path:
        """
        Synthesize text into a 22.05 kHz WAV file.
        """
        log.info(f"Synthesizing {len(text.split())} words with voice '{self.voice_name}'...")
        output_wav.parent.mkdir(parents=True, exist_ok=True)

        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Piper voice model not found at: {self.model_path}\n"
                f"Ensure en_US-lessac-medium.onnx is downloaded in assets/models/piper/"
            )

        cmd = self._piper_cmd + [
            "--model", str(self.model_path),
            "--output_file", str(output_wav),
        ]

        t0 = time.perf_counter()
        result = subprocess.run(
            cmd,
            input=text,
            text=True,
            capture_output=True,
        )
        elapsed = time.perf_counter() - t0

        if result.returncode != 0:
            raise RuntimeError(f"Piper TTS synthesis failed:\n{result.stderr}")

        size_kb = output_wav.stat().st_size // 1024
        log.info(f"  TTS complete in {elapsed:.1f}s — {output_wav.name} ({size_kb} KB)")
        return output_wav

