# AI Reel Factory

A local-first, open-source AI-powered short-form video production platform.

## Overview

Converts a topic or script into a complete, professional Instagram Reel (1080×1920, 60 seconds) using a fully deterministic, human-gated pipeline.

**Pipeline:**
```
Topic → Research → Script → [GATE 1: Human Approval] → Scene Planning →
Footage Matching → TTS → Subtitles → FFmpeg Render → QC →
[GATE 2: Human Approval] → Instagram Publish
```

## Development Environment Requirements

- Windows 11 / WSL2 Ubuntu
- Python 3.12+ (via `uv`)
- FFmpeg 6.0+ with libass
- 8 GB RAM (WSL2 capped at 3.5 GB)
- No GPU required

## Quick Start (Phase 1 Spike)

```powershell
# 1. Create virtual environment with Python 3.12
uv venv --python 3.12 .venv

# 2. Activate
.venv\Scripts\Activate.ps1

# 3. Install spike dependencies
uv pip install -e ".[spike]"

# 4. Run the rendering spike
python spikes/phase1_rendering/test_render.py
```

## Project Phases

| Phase | Focus | Status |
|-------|-------|--------|
| 0 | Environment & Feasibility | ✅ Complete |
| 1 | Video Rendering Spike | 🔄 In Progress |
| 2 | Walking Skeleton (FastAPI + Celery) | ⏳ Pending |
| 3 | Content Intelligence (LLM + Script) | ⏳ Pending |
| 4 | Automated Video Production | ⏳ Pending |
| 5 | Dashboard & Instagram Publishing | ⏳ Pending |
| 6 | AI Media Generation | ⏳ Deferred |
| 7 | SaaS Expansion | ⏳ Deferred |

## Architecture Principles

1. **Human-gated:** No rendering without script approval; no publishing without video approval.
2. **Deterministic QC:** ffprobe validates every output — never an LLM guess.
3. **Multi-brand:** Every asset references a `brand_id`. No hardcoded brand logic.
4. **Resource-disciplined:** Celery concurrency = 1. One heavy process at a time.
5. **Fact-checked:** Every numeric claim maps to a stored source ID.

## See Also

- [LICENSES.md](LICENSES.md) — Dependency and asset license tracking
- [spikes/phase1_rendering/](spikes/phase1_rendering/) — Rendering feasibility spike
