# 1. Repository

branch: `feature/bilingual-subtitle-duration-profiles`  
base: `4e76caede74e65b4a02b22a77b40c3ed5f35ecd9`  
implementation head: `20e3bbfecb76eedca8e3ef47d5a66329de1d9e30`  
evidence head: recorded by the evidence-only commit containing this file  
working tree: clean after evidence commit

# 2. Subtitle Architecture

timing source: faster-whisper word timestamps; segment/句级 fallback is explicit  
translation provider: existing optional Argos runtime, real en→zh package 1.9  
subtitle schema: typed `SubtitleWord`, synchronized `SubtitleCue`, `BilingualSubtitleTrack`  
display modes: ZH_EN, EN_ZH, ZH_ONLY, EN_ONLY, SOURCE_ONLY, SOURCE_ZH, SOURCE_EN  
cache: source text/language, target language, provider/model, glossary version, config version

# 3. Timeline Stability

word timestamps: recording-relative absolute milliseconds  
clip-relative conversion: `absolute_ms - final_clip_start_ms`  
non-zero start: covered by unit fixture  
range offset: covered by unit fixture  
monotonic: PASS  
overlap: 0 for every real variant  
out-of-range: 0 for every real variant  
coverage: 100% of recognized speech in all four variants

# 4. Segmentation

pause thresholds: weak 150 ms, medium 350 ms, strong 650 ms; configurable  
duration thresholds: minimum 600 ms, target 1–4 s, soft max 4.5 s, hard max 6 s  
semantic rules: punctuation, pauses, sentence/meaning boundaries and reaction units precede length  
reading speed: zh soft max 14 chars/s, en soft max 21 chars/s  
long cue handling: synchronized semantic split for both languages; no fixed-N-word or fixed-time slicing

# 5. Translation

source language: English for the Saruei validation event  
Chinese coverage: 100% of valid cues non-empty  
English coverage: 100% of valid cues non-empty  
untranslated: 0  
glossary: configurable and included in cache identity; no Creator hard-coding  
provider fallback: explicit TRANSLATION_UNAVAILABLE/DEGRADED; never copies source into the other language as fake success

# 6. Subtitle Visual

font: Arial Unicode MS-compatible ASS fallback chain  
Chinese size: 48 px design size  
English size: 36 px design size  
position: AUTO_SAFE_AREA resolved to top caption for this source  
max lines: two visual language rows  
safe area: 1280×720 ASS design resolution with outline/shadow  
preview images: start/middle/end JPEG for every variant (12 total)

# 7. Duration Profiles

SHORT:  
target: 20–45 s  
actual: 32.600 s  
start/end: 2625380 / 2657980 ms  
reason: extended_for_sentence_or_payoff

STANDARD:  
target: 45–90 s  
actual: 67.400 s  
start/end: 2620960 / 2688360 ms  
reason: semantic_boundaries_nearest_profile_target

LONG:  
target: 90–180 s  
actual: 84.420 s  
start/end: 2601000 / 2685420 ms  
reason: event_shorter_than_profile_target_preserved

FULL_EVENT:  
actual: 87.360 s  
start/end: 2601000 / 2688360 ms  
reason: natural_event_boundaries

# 8. Variant Structure

| Variant | Hook | Setup | Event | Payoff | Reaction | Aftermath |
|---|---|---|---|---|---|---|
| SHORT | retained | minimum necessary | retained | shared 2657460 ms | primary denial | omitted |
| STANDARD | retained | fear setup | retained | shared 2657460 ms | retained | short |
| LONG | retained | fuller setup | retained | shared 2657460 ms | retained | sensitivity discussion |
| FULL_EVENT | natural start | complete | retained | shared 2657460 ms | complete | natural close |

# 9. Output Files

short bilingual MP4: `outputs/bilingual-duration-validation/121a99a3-affb-4e74-80de-c5fd13ed7c4b/final_clip_short_bilingual.mp4`  
standard bilingual MP4: `outputs/bilingual-duration-validation/121a99a3-affb-4e74-80de-c5fd13ed7c4b/final_clip_standard_bilingual.mp4`  
long bilingual MP4: `outputs/bilingual-duration-validation/121a99a3-affb-4e74-80de-c5fd13ed7c4b/final_clip_long_bilingual.mp4`  
full event bilingual MP4: `outputs/bilingual-duration-validation/121a99a3-affb-4e74-80de-c5fd13ed7c4b/final_clip_full_event_bilingual.mp4`  
ASS: one `clip_zh_en.ass` per variant  
SRT: one `clip_zh_en.srt` per variant  
manifests: one `manifest.json` per variant plus `variant_comparison.json`  
timeline reports: one per variant plus consolidated evidence report  
review sheet: `variant_review.md` and `final-bilingual-duration-review.md`

# 10. Media Validation

ffprobe: PASS for 8 clean/bilingual MP4s  
decode: PASS for 8 MP4s  
audio: AAC present  
video: H.264 yuv420p present  
subtitle burn-in: PASS by distinct hashes and inspected frames  
hash: clean/bilingual SHA-256 differs for every profile

# 11. Product Quality

timeline: automated hard gates PASS; sampled frames align with the event region  
segmentation: 6/12/16/16 semantic cues; maximum 5.88 s  
translation: complete but local Argos phrasing remains literal in several sentences  
readability: top bilingual layout is readable and leaves the central game event visible  
short usefulness: fast payoff-preserving cut  
standard usefulness: strongest default balance  
long usefulness: preserves fuller setup/discussion without unrelated padding  
full-event usefulness: natural 87.36 s event record

# 12. GUI

duration selector: controls and persistence implemented  
custom duration: target/min/max controls implemented  
generate all: control present, but not wired to the real multi-variant service  
bilingual selector: implemented and persisted  
cue editor: separate zh/en controls present, but not wired to track-level edit persistence  
rerender: canonical single-clip re-render works; bilingual variant re-render from edited cues is pending  
open video: existing Preview opens the rendered clip; multi-variant compare/open flow is pending

# 13. CLI

commands: canonical `clip create` accepts duration/subtitle options; `clip variants <event-plan.json>` drives one/all variants  
results: help smoke PASS and four real variants generated through `ClipVariantService`

# 14. Tests

compileall: PASS ×2  
CLI: five requested help commands PASS ×2  
pytest #1: 352 passed, 11 warnings  
pytest #2: 352 passed, 11 warnings  
coverage: focused relevant suite 29 passed; 81% aggregate (duration 92%, subtitle 83%, ClipService 82%, variants 65%)  
verify: PASS ×2  
contracts: PASS ×2

# 15. Bugs Fixed

| ID | Severity | Observed Failure | Root Cause | General Fix | Regression | Commit |
|---|---|---|---|---|---|---|
| SUB-001 | High | potential 10s+ cue | a semantic unit could exceed hard max | split only at word/punctuation/pause candidates while keeping bilingual timing shared | long-cue test + real max 5.88s | 20e3bbf |
| SUB-002 | High | subtitle sizing could obscure 1080p video | ASS lacked design resolution | PlayResX/Y and safe-area style | ASS contract + 12 previews | 90751d3 |
| TR-001 | High | runtime existed without translation ability | Argos model is separately installed | explicit runtime state and real language-package smoke | provider failure + real untranslated=0 | 90751d3 |
| DUR-001 | High | exact-duration cuts could lose payoff | duration treated as hard trim | semantic units, shared anchor and explicit extension reason | all profile tests | 90751d3 |

# 16. Regression

Retrieval: full suite PASS  
Conversation: full suite PASS  
Moment: unchanged; full suite PASS  
Watchability: unchanged; full suite PASS  
Download: CLI smoke and full suite PASS  
Live: CLI smoke and full suite PASS  
Feedback: persistence regression PASS  
CGNK: repository guards and contract checks PASS; formal CGNK provider evidence remains NOT_EVALUATED

# 17. Human Review

review file: `outputs/bilingual-duration-validation/121a99a3-affb-4e74-80de-c5fd13ed7c4b/final-bilingual-duration-review.md`  
status: HUMAN_REQUIRED — scoring boxes intentionally remain unselected

# 18. Remaining Problems

- GUI does not yet provide the required end-to-end Generate All → compare → edit individual bilingual cues → re-render → select final workflow.
- Argos translation is complete but some Chinese lines are literal/awkward and still need human language review.
- A fresh machine must install the optional Argos en→zh package; absence is correctly reported as TRANSLATION_UNAVAILABLE.
- The host's full-suite coverage plugin path has a NumPy/transformers reload conflict; standard full regression is unaffected and focused coverage is 81%.

# 19. Engineering Status

BILINGUAL_SUBTITLE_READY: YES  
SUBTITLE_TIMELINE_READY: YES  
SEMANTIC_CUE_SEGMENTATION_READY: YES  
SHORT_VARIANT_READY: YES  
STANDARD_VARIANT_READY: YES  
LONG_VARIANT_READY: YES  
FULL_EVENT_VARIANT_READY: YES  
GUI_DURATION_SELECTION_READY: NO  
FINAL_MULTI_LENGTH_BILINGUAL_OUTPUT_READY: NO

The final aggregate status is deliberately NO because the required GUI end-to-end workflow and human translation review are not complete, despite the four validated command/service-generated bilingual outputs.
