# 1. Repository

branch: `validation/cross-library-generalization`  
base: `3cb0a9d98e2cc91cebed48507f49a8acd101377f`  
implementation head: `d404d18f45b1be6f3970b84d9dc82c9535bb15d6`  
evidence head: HEAD containing this evidence  
working tree: clean after evidence commit and bundle generation

CGNK repository specs, guards, contracts, and all five requested workflows were followed. The
CGNK Provider tool was unavailable in this runtime, so this document does not claim Provider
authority or a formal CGNK PASS beyond repository contract tests.

# 2. Library Inventory

Creators: 4 with recordings (two additional empty Creator rows excluded)  
Recordings: 12  
Hours: 52.929524  
Languages: English; mixed/mislabeled Japanese metadata; no authorized genuine Japanese Library  
Content Types: horror/story game, chatting/collab, flight simulation, automatic game commentary  
Source Types: LOCAL_IMPORT, VOD_DOWNLOAD, LIVE_CAPTURE

Result: `INSUFFICIENT_AUTHORIZED_LIBRARY_DIVERSITY`. The audit found 4 Creator rows with real
recordings, but only Saruei and anny satisfy the per-Library duration/recording target. No random
third-party VOD was downloaded to fill the matrix.

# 3. Test Matrix

| Library | Language | Content | Hours | Recordings | Role |
|---|---|---|---:|---:|---|
| Saruei | en | horror reaction/story | 19.759 | 4 | TRAIN |
| anny | en/mixed, mislabeled ja | chatting/collab/story | 32.671 | 6 | VALIDATION |
| Q8Pilot | en | simulation/chatting | 0.250 | 1 | VALIDATION (limited) |
| twitchplayspokemon | unknown/mostly en | game commentary | 0.249 | 1 | HOLDOUT (ENGINEERING_ONLY) |

# 4. Media Integrity

All 12 source paths exist and passed current ffprobe video/audio/readability checks. Eight selected
clip files (two rows per Creator) passed ffprobe and complete ffmpeg decode. Full decode of all
52.93 hours was not repeated; prior source validation was reused. Q8's two clip rows have the same
hash and therefore represent one unique render. No original media was modified.

# 5. Transcript Quality

| Library | Entries / coverage | AUTO_SUSPECT | Languages | Issues |
|---|---|---:|---|---|
| Saruei | artifacts present; tail bounded by media | 0/4 | en | minor short/duplicate Moments downstream |
| anny | artifacts present; tail bounded by media | 5/6 | en/mixed | `ja` metadata mismatch, music lyrics, mixed-script noise |
| Q8Pilot | complete limited artifact | 0/1 | en | only 15 minutes |
| twitchplayspokemon | complete limited artifact | 0/1 structural | unknown/en | automated commentary, not representative human speech |

The pass did not rewrite transcripts or change word timestamps. Japanese readiness is not inferred
from metadata. English post-correction was not applied because no timestamp-preserving, high-
confidence correction set was available across Libraries.

# 6. Translation

English source: Argos `en -> zh` installed; existing Saruei bilingual output reused. Literal text
is lowest-risk; slang/profanity and game terminology remain `AUTO_SUSPECT`. Japanese, Chinese,
and mixed source: `NOT_EVALUATED`. Canonical Qwen/local LLM was not configured; provider package
presence was not treated as runtime readiness. See `translation-provider-comparison.md`.

# 7. Subtitle Timeline

Saruei: existing word-timestamp bilingual timeline regression PASS.  
anny, Q8Pilot, holdout: overlap/out-of-range/coverage/CPS/segmentation bilingual checks
`NOT_EVALUATED`; no complete per-Library bilingual artifacts were found. This blocks the
multi-language subtitle gate.

# 8. Moments

| Library | Count | Invalid | Low-info | Exact duplicate rows | AUTO_SUSPECT | Median duration |
|---|---:|---:|---:|---:|---|---:|
| Saruei | 2,015 | 0 | 54 | 5 | yes | 19.480 s |
| anny | 3,211 | 0 | 120 | 37 | yes | 20.380 s |
| Q8Pilot | 11 | 0 | 0 | 0 | limited | 85.000 s |
| twitchplayspokemon | 22 | 0 | 3 | 0 | limited | 23.000 s |

The audit covers every persisted Moment structurally, exceeding the requested 20-per-Library
sample for the two full Libraries. Human topic-boundary and summary-grounding review was not
repeated for 80 items, so content readiness remains NO.

# 9. Retrieval

| Library | Top1 | Top3 | Top5 | Top10 | MRR | No-Evidence | Median / P90 |
|---|---:|---:|---:|---:|---:|---:|---|
| Saruei | 6/8 | 7/8 | 8/8 | 8/8 | 0.8229 | 3/3 | 3988.473 / 4230.631 ms |
| anny | 5/12 | 7/12 | 8/12 | 9/12 | 0.5111 | 3/3 | 3687.677 / 4029.059 ms |
| Q8Pilot | 5/5 | 5/5 | 5/5 | 5/5 | 1.0000 | 3/3 | 269.741 / not stable (cold 2208.993) ms |
| twitchplayspokemon | 4/5 | 5/5 | 5/5 | 5/5 | 0.9000 | 3/3 | 521.340 / sample too small |

Overall: Top1 20/30, Top3 24/30, Top5 26/30 (86.7%), Top10 27/30; no-evidence 12/12. The overall
gate passes numerically, but anny is 66.7% Top5, below the per-Library recommendation, so
cross-Library readiness still fails. The formal 20-query run used the required
`multilingual-e5-base` index; Creator and Recording scope/crowding regressions pass.

# 10. Conversation

Saruei saved real top-eight + diagnostic gate sample: 3/3 expected evidence in evidence-only mode.
anny: 0/3 sampled expected evidence due underlying retrieval misses. Q8Pilot: 2/3; holdout: 2/3.
No-evidence probes: 12/12 rejected with no citations. Invalid citations and unsupported claims:
0 in automated regressions. A grounded LLM provider was unavailable, so generated-answer quality,
multi-evidence synthesis, and production latency are `NOT_EVALUATED`.

# 11. Watchability

Horror reaction remains covered by prior real artifacts. Generic regression coverage now includes
Japanese CJK reaction, Chinese CJK reaction, and a long complete talking argument, each producing
three eligible candidates. FPS, real Japanese, collab speaker overlap, and comedy/failure were not
available as a sufficient real-event matrix. No Creator/game string or Creator-specific threshold
was introduced. Status: `NOT_EVALUATED` for cross-content product readiness.

# 12. Duration Profiles

Saruei reaction: existing SHORT/STANDARD/LONG/FULL_EVENT regression PASS; short can be preferred.
Chatting, story, FPS, and holdout: four-profile cross-Library output not available, so best-profile
claims are not made. STANDARD was not designated universally best.

# 13. Clips

Renders: 8 persisted clip rows inspected, 7 unique hashes. ffprobe: 8/8 PASS. Full decode: 8/8
PASS. Video/audio: 8/8. Subtitle burn-in: only existing Saruei bilingual artifacts proven.
Boundary/query mismatch/low-value: not manually adjudicated across 12-20 new events. Existing clip
files were reused; no formal output was overwritten.

# 14. Feedback / Preference

Creator and Recording scope regressions verify that a Recording inherits only its owning Creator's
explicit preference. Opposing Creator preferences do not leak. Strong evidence ordering remains
ahead of preference shaping. Persistence remains covered by the full suite.

# 15. Performance

Large-Library search median is about 3.7-4.0 s with P90 about 4.03-4.23 s; Q8 warm median 0.270 s;
holdout median 0.521 s. Clip decode checks took 0.279-2.349 s each. Startup/listing was exercised
through Library access and native GUI launch. Translation/render production latency, index memory,
and GPU memory were not reliably instrumented and are `NOT_EVALUATED`.

# 16. Holdout

Library: twitchplayspokemon (`ENGINEERING_ONLY`).  
Results: Top5 5/5, no-evidence 3/3, two distinct decoded clips.  
Regressions: none observed after generic fixes.  
Generalization: useful engineering holdout only; 15 minutes of automatic game commentary cannot
prove a human Creator/content/language product claim.

# 17. Bugs Fixed

| ID | Severity | Library | Observed Failure | Root Cause | General Fix | Regression | Commit |
|---|---|---|---|---|---|---|---|
| CLG-001 | high | multi-Creator | scoped lexical target crowded out | FTS limit applied before scope | filter allowed parent IDs before satisfying scoped limit | 140-noise-parent test | `7099ad8` |
| CLG-002 | high | multi-Creator | Recording preference absent/wrongly scoped | preference used only explicit creator argument | resolve Recording owner before preference shaping | opposing preference test | `7099ad8` |
| CLG-003 | high | cross-language | Chinese query + English evidence rejected by Conversation | lexical-only support gate | conservative cross-script semantic/reranker gate | positive + weak-negative tests | `7099ad8` |
| CLG-004 | medium | content/language | CJK reaction and talking candidates under-scored | English word/reaction assumptions | CJK bigrams/signals/punctuation and long-talk coverage | ja/zh/talking tests | `7099ad8` |
| CLG-005 | low | full suite | internal monkeypatch callers rejected keyword-only scoped IDs | helper call compatibility | keep optional scope set positional-compatible | legacy representation tests | `d404d18` |

# 18. GUI Redesign Backlog

5 items recorded; 0 implemented. Path: `evidence/validation/gui-redesign-backlog.md`. GUI source
files were untouched. Native launch reached the main window; the validation process was then closed.

# 19. Automated Verification

compileall: PASS in both runs  
CLI: PASS in both runs (`--help`, `gui --help`, `pipe clip --help`, `live --help`, `download --help`)  
pytest #1: 367 passed, 11 warnings (129.06 s); verify pytest 367 passed (146.90 s)  
pytest #2: 367 passed, 11 warnings (142.21 s); verify pytest 367 passed (150.73 s)  
coverage: focused changed modules 92% (retrieval 88%, candidates 92%, conversation 98%)  
verify: PASS twice  
contracts: PASS twice

# 20. Regression

Fixed Retrieval: current immutable 20-query Top5 16/20, above retained 15/20 gate.  
Grounded Conversation: no-evidence 12/12; cross-language support regression added.  
Saruei: Top5 8/8; existing Moment/clip artifacts retained.  
Download / Live / Subtitle / Duration / Feedback / CGNK repository guards: full suite PASS twice.

# 21. Evaluation Bundle

path: `var/deliverables/cross-library-evaluation-bundle.zip`  
size: 135,872,246 bytes (129.58 MiB)  
SHA-256: `2C23E605889C6040CBBBE9FE12FB0EDCDD7272FB88C8FFC008E2FAD7ED59697A`  
contents: 26 files: evidence, raw receipts, fixed-set references, per-Library reports, and eight decoded clip rows.

# 22. Remaining Problems

- Authorized diversity is below target: 12 vs 20 recordings, 52.93 vs 80 hours, only two full Libraries.
- No authorized genuine Japanese Creator Library; five `ja` labels are unreliable.
- anny Top5 is 8/12 (66.7%), below the per-Library 70% recommendation.
- Complete bilingual subtitle and all duration profiles were not present across all four Libraries.
- Conversation had no configured grounded LLM and insufficient supported/multi-evidence cases.
- Six dogfood DB artifact roots are stale `E:` paths; stable artifacts exist under `F:` fallback.
- Q8 provides two clip rows but only one unique output hash.
- Full-source decode, 60 real candidates, 40 bilingual cues, and required performance telemetry were not completed.

# 23. Engineering Status

MULTI_LIBRARY_INGEST_READY: YES  
MULTI_LANGUAGE_ASR_READY: NO  
CROSS_LANGUAGE_RETRIEVAL_READY: NO  
MULTI_CONTENT_MOMENT_READY: NO  
MULTI_CONTENT_WATCHABILITY_READY: NOT_EVALUATED  
MULTI_LANGUAGE_SUBTITLE_READY: NO  
MULTI_LIBRARY_CONVERSATION_READY: NO  
CROSS_LIBRARY_GENERALIZATION_READY: NO  
GUI_REDESIGN_REQUIRED: YES (backlog only; not a blocker for this pass)

