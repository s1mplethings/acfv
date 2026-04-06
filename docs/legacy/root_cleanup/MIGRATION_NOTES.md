# Migration Notes: Legacy InterestRating -> Unified ACFV Architecture

## 1. Overview
The project transitioned from a mixed legacy structure (interest_rating external folder + ad-hoc pipeline backend) to an internal, modular architecture under `src/acfv/arc/` providing:
- `arc/pipeline`: Declarative stage-based processing (Validate -> ChatExtract -> Analyze -> Clip)
- `arc/services`: Focused service modules (e.g. `scoring.py`)
- `arc/domain`: Domain models & settings (`settings.py`)
- `arc/ui`: (Placeholder for future UI-specific domain abstractions)

## 2. Key Changes
| Area | Legacy | New |
|------|--------|-----|
| Configuration | Multiple `ConfigManager` definitions + JSON `config.txt` | Single `Settings` model (bridges legacy keys) in `arc/domain/settings.py` |
| Pipeline orchestration | `features/modules/pipeline_backend.py` (monolithic, side effects) | `arc/pipeline/stages.py` composable stages, context dict |
| Scoring logic | Embedded in `processing/analyze_data.py` | Extracted to `arc/services/scoring.py` with clear helpers |
| GUI entry | External `interest_rating` fallback via sys.path hacks | Internal `interest_adapter.py` using only internal modules |
| Logging | Multiple handlers scattered | Central log consumption + GUI logging tab tailing `processing.log` |
| Secret handling | Raw files (.env, dify_key.txt) | Sanitized examples + pre-commit secret scanning |

## 3. Configuration Migration
Legacy keys are preserved where practical. Mapping:

| Legacy Key | Settings Attribute | Notes |
|------------|--------------------|-------|
| VIDEO_FILE | video_file | GUI sets through legacy config UI (if present) |
| CHAT_FILE | chat_file | Optional; empty treated as no chat |
| CHAT_OUTPUT | chat_output | Defaults to `processing/chat_with_emotes.json` |
| ANALYSIS_OUTPUT | analysis_output | High-interest segments JSON |
| OUTPUT_CLIPS_DIR | output_clips_dir | Clip export directory |
| MAX_CLIP_COUNT | max_clip_count | Not yet enforced; selection currently uses `top_segments` |
| CHAT_DENSITY_WEIGHT | chat_density_weight | Included in `weights` property |
| CHAT_SENTIMENT_WEIGHT | chat_sentiment_weight | Included in `weights` property |
| VIDEO_EMOTION_WEIGHT | video_emotion_weight | Placeholder (0.0 emotion score until integration) |
| SEGMENT_WINDOW (new) | segment_window | Defines analysis window size (seconds) |
| TOP_SEGMENTS (new) | top_segments | Maximum non-overlapping segments selected |

Unused or complex legacy keys (e.g. `WHISPER_MODEL`, `ENABLE_VIDEO_EMOTION`) remain accessible through old `ConfigManager` but are not yet wired into stages.

## 4. Stage Pipeline Contract
Each stage receives a shared `StageContext` (dict). Important context entries:
- Input: `video_path`, `chat_html`, optional `settings`
- Intermediate: `chat_json`, `segments`
- Output: `clips`, `clips_dir`, `segments_file`

Error handling is localized; failures produce empty artifacts rather than raising (except ValidateStage which enforces video existence).

## 5. Scoring Simplification
Original scoring combined multiple nuanced metrics; current implementation focuses on:
- Chat density (# messages per window)
- VADER sentiment heuristic (aggregated window text)
- Placeholder video emotion (0.0)
Normalization: raw score list -> relative z-score -> sigmoid -> ranking. Future enhancement points:
- Integrate real video emotion service
- Add transcription & semantic similarity contributions

## 6. Removed / Deprecated
- External `interest_rating` fallback logic (deleted from adapter)
- Duplicate `ConfigManager` in `features/modules/pipeline_backend.py` (kept temporarily; mark for deprecation)
- Indirect sys.path modifications for legacy imports

## 7. Logging Panel
GUI now includes a "日志" tab tailing `processing.log` last ~64KB (limited to 20K chars) with optional auto-refresh (2s interval).

## 8. Secret Hygiene
Pre-commit hook and `tools/scan_secrets.py` ensure example placeholders are used. Real secrets should be stored outside repo or in ignored paths.

## 9. Next Targets
1. Enforce `max_clip_count` and merge/extend policies from legacy logic.
2. Integrate audio/transcription stages (extend pipeline before Analyze).
3. Emotion model integration (`video_emotion_weight`).
4. Replace legacy modules under `features/modules` with lean service equivalents.
5. Expand tests (unit tests for scoring, pipeline flow, settings loading).

## 10. How to Use (Quick)
```python
from acfv.app.interest_adapter import create_interest_main_window
# In a PyQt5 application context:
win = create_interest_main_window()
win.show()
```
Pipeline run (GUI button) executes stages and populates results & logs tabs.

## 11. Rollback Strategy
If a regression is discovered:
- Re-enable legacy `interest_rating` by reinstating old adapter fallback (commit history contains removed code).
- Use `processing/high_interest_segments.json` diff to verify selection logic changes.

## 12. Validation Checklist
- [x] Video path required; error surfaced via QMessageBox.
- [x] Chat optional; empty file produced when absent.
- [x] Results tab shows produced clips.
- [x] Settings override tested (segment window, top segments).
- [x] Logging tab tails file without freezing UI.

---
For questions or incremental migration steps, consult this document first to avoid reintroducing deprecated patterns.

## Runtime storage refactor

- Introduced `var/` runtime directory (configurable via `ACFV_STORAGE_ROOT`).
- Processing outputs now write under `var/processing`.
- Mutable GUI config migrates to `var/settings/config.json`.
- Secrets such as HuggingFace token look for `var/secrets/config.json` or environment variables first.
- Legacy `config.txt` files are auto-migrated on first run.
