# LICENSES.md — AI Reel Factory

This file tracks the licensing status of every dependency, model, font, and media asset used in this project.
**All assets must be verified before commercial publication.**

---

## 1. Python Packages

| Package | License | Commercial Use | Notes |
|---------|---------|----------------|-------|
| FastAPI | MIT | ✅ Yes | Web framework |
| Uvicorn | BSD-3-Clause | ✅ Yes | ASGI server |
| Pydantic / Pydantic-Settings | MIT | ✅ Yes | Data validation & config |
| SQLAlchemy | MIT | ✅ Yes | SQL toolkit & ORM |
| Alembic | MIT | ✅ Yes | DB migrations |
| Celery | BSD-3-Clause | ✅ Yes | Distributed task queue |
| Redis | MIT / BSD-3-Clause | ✅ Yes | Python Redis client |
| psycopg2-binary | LGPL-3.0 | ✅ Yes | PostgreSQL driver |
| asyncpg | Apache-2.0 | ✅ Yes | Async PostgreSQL driver |
| faster-whisper | MIT | ✅ Yes | Fast Whisper ASR |
| piper-tts | MIT | ✅ Yes | Speech synthesis |
| onnxruntime | MIT | ✅ Yes | ONNX model execution |
| Pillow | HPND / MIT-like | ✅ Yes | Image & scene card rendering |
| Streamlit | Apache-2.0 | ✅ Yes | Local review dashboard |
| httpx | BSD-3-Clause | ✅ Yes | Async HTTP client |
| duckduckgo-search | MIT | ✅ Yes | Topic research engine |
| beautifulsoup4 | MIT | ✅ Yes | HTML parsing for fact sources |
| rich | MIT | ✅ Yes | Console logging |
| python-dotenv | BSD-3-Clause | ✅ Yes | Environment loader |
| PyYAML | MIT | ✅ Yes | Brand YAML parser |
| pytest | MIT | ✅ Yes | Dev / Testing only |

---

## 2. AI Models

| Model | License | Commercial Use | Notes |
|-------|---------|----------------|-------|
| Qwen2.5-3B-Instruct (Q4_K_M) | Qwen License v1.0 | ⚠️ Verify | Free for research; commercial use requires Alibaba Cloud agreement for >100M MAU deployments. MVP scale is fine. |
| Qwen2.5-1.5B-Instruct (Q4_K_M) | Qwen License v1.0 | ⚠️ Verify | Same as above |
| Whisper (faster-whisper) | MIT | ✅ Yes | Model weights from OpenAI Whisper (MIT) |

---

## 3. TTS Voice Models (Piper)

> **CRITICAL:** Each Piper voice has its own separate license. The package license (MIT) does NOT cover the voice checkpoints.

| Voice | License | Commercial Use | Notes |
|-------|---------|----------------|-------|
| `en_US-lessac-medium` | CC BY 4.0 | ✅ Yes (with attribution) | Recommended default |
| `en_US-amy-medium` | CC BY 4.0 | ✅ Yes (with attribution) | Good fallback |
| `en_US-ryan-high` | CC BY 4.0 | ✅ Yes (with attribution) | High quality; larger model |
| `en_US-libritts-high` | CC BY 4.0 | ✅ Yes (with attribution) | Based on LibriTTS dataset |

**Attribution required:** "Voice synthesis powered by Piper TTS / [voice model name]"

---

## 4. Fonts

| Font | License | Commercial Use | Notes |
|------|---------|----------------|-------|
| Inter | SIL Open Font License 1.1 | ✅ Yes | Recommended for subtitles — download from rsms.me/inter |
| Montserrat | SIL Open Font License 1.1 | ✅ Yes | Alternative for stat cards |

---

## 5. Stock Footage & Media

| Source | License | Commercial Use | Notes |
|--------|---------|----------------|-------|
| Pixabay | Pixabay License | ✅ Yes | Free for commercial use; no attribution required; resale prohibited |
| Pexels | Pexels License | ✅ Yes | Free for commercial use; no attribution required |
| Local curated library | Per-asset | ⚠️ Verify each | Must document source URL for each asset |

---

## 6. Music & Sound Effects

> **STATUS: Deferred — no music in Phase 1 MVP.**
> When adding music, only use:
> - Royalty-free / CC0 sources (freepd.com, incompetech.com with CC BY license)
> - Or explicitly licensed tracks for Instagram/YouTube

---

## 7. Generated Content

| Asset Type | AI-Labeling Required (Instagram) | Notes |
|-----------|----------------------------------|-------|
| AI-generated scripts | ✅ Yes | Instagram requires disclosure of AI-generated material |
| AI-generated voiceovers | ✅ Yes | Must label as AI-generated voice |
| AI-generated visuals | ✅ Yes | Required from March 2024 Meta policy |
| Stock footage with AI narration | ✅ Yes | The AI component triggers disclosure |

**Reference:** Meta AI Content Disclosure Policy (Updated 2024) — verify current requirements before Phase 5 publishing.

---

## 8. Project License Recommendation

Two candidates for the project's own open-source license:

| Attribute | AGPL-3.0 | Apache-2.0 |
|-----------|----------|------------|
| Copyleft / viral | Strong (SaaS loophole closed) | None |
| Commercial use | Allowed, but derivatives must share source | Allowed freely |
| Patent grant | Yes | Yes (explicit) |
| Best for | Preventing proprietary forks; ensuring community gets improvements | Maximum adoption; commercial integrations welcome |
| SaaS compatibility | ⚠️ Requires source disclosure if SaaS | ✅ No restrictions |

**Recommendation:** Start with **Apache-2.0** for the MVP to allow maximum flexibility during early development and potential SaaS phase. If competitors begin exploiting the codebase without contributing, migrate to AGPL-3.0.

> **ACTION REQUIRED:** Choose project license before Phase 5 (publishing). `LICENSE` file is intentionally not created yet.

---

*Last updated: Phase 0 / Phase 1 initialization.*
*All entries must be re-verified before commercial deployment.*

