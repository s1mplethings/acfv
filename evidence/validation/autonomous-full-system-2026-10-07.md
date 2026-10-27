# ACFV Autonomous Full-System Validation — 2026-10-07

# 1. Repository

branch: `validation/autonomous-full-system`  
base: `cdec23794f4978289b826b963b05c7e5862bcd70`  
tested implementation: `b753fec4572297f0ca8c0fefb34b6dbbdc138ffe`  
evidence commit: recorded separately in the final handoff because a commit cannot contain its own hash  
commits: 5 focused implementation/test commits plus the evidence commit  
working tree at implementation gate: evidence files only

# 2. Capability Coverage

Labels are literal: prior same-day Twitch/GPU artifacts are `REAL`; deterministic media and transport runs are `REPLAY`; mocks are never called real.

| Capability | Unit | Integration | Replay | Real | Fault Injection | Persistence | GUI | Result |
|---|---|---|---|---|---|---|---|---|
| Creator | PASS | PASS | N/A | 52h library metadata | invalid/duplicate | restart PASS | contract + prior visible create | PASS |
| Source | PASS | PASS | N/A | Twitch source record | duplicate/invalid | enable/disable PASS | surface contract | PASS |
| Twitch Capture | PASS | PASS | PASS | 895.962s / 15 segments | crash/stop/invalid | PASS | launch/surface | PASS |
| Live Processing | PASS | PASS | PASS | during-live evidence | ASR/segment failure | PASS | surface contract | PASS |
| Video Processing | PASS | PASS | PASS | real source/render | provider/render failure | runtime PASS | controller contract | PASS |
| ASR | PASS | PASS | 10+ segment artifacts | RTX 4050 CUDA | CUDA/ASR/corrupt | checkpoints PASS | error contract | PASS |
| Chat | PASS | PASS | transport/extract | BLOCKED_EXTERNAL credentials | disconnect/absence | flush PASS | error contract | REAL BLOCKED |
| Analysis Profile | PASS | PASS | fixtures | artifact-backed | invalid profile | restart PASS | selection contract | PASS |
| Creator Library | PASS | PASS | N/A | 10 files / 52.4306435h | missing/invalid | restart PASS | library surface | PASS |
| Recording | PASS | PASS | capture replay | Twitch + local | stale/retry | PASS | surface contract | PASS |
| Moment Lifecycle | PASS | PASS | PASS | 22 FINAL | finalize/retry | 3x stable | surface contract | PASS |
| Semantic Index | PASS | PASS | rebuild | 22 FINAL = 22 FTS | write/rebuild | restart PASS | surfaced | PASS |
| Retrieval | PASS | PASS | multilingual/scoped | real live queries | fallbacks | PASS | search surface | PASS automated |
| Grounded Conversation | 20 negatives | PASS | PASS | live evidence | invalid citation/LLM | N/A | No-Evidence | PASS |
| Clip Proposal | PASS | PASS | PASS | 20 proposals | invalid boundary | PASS | create contract | PASS |
| Clip Rendering | PASS | PASS | PASS | 10 renders | missing/render error | rerender PASS | review contract | PASS |
| Subtitle | PASS | PASS | multilingual | 10 clips | font/special/empty | style PASS | editor contract | PASS |
| Review | PASS | PASS | N/A | 10 clips | invalid edits | PASS | control contract | PASS automated |
| Feedback | PASS | PASS | N/A | DB-backed | missing target | index-independent | controls | PASS |
| Explicit Preference | PASS | PASS | ranking fixture | DB-backed | missing creator | PASS | controls | PASS |
| Recovery | PASS | PASS | crash matrix | abandoned capture | capture/ASR/index/render | PASS | error contract | PASS |
| GUI | 27 tests | adapter contracts | N/A | window launched | env/config/deps | settings PASS | native API unavailable | PARTIAL |
| CLI | PASS | PASS | N/A | executable | invalid args | config-backed | N/A | PASS |
| Configuration | PASS | PASS | N/A | CUDA discovery | missing/partial/invalid | PASS | startup doctor | PASS |
| Persistence | PASS | PASS | restart/rebuild | real DB | concurrent R/W x5 | PASS | adapters | PASS |
| CGNK Guards | PASS | PASS | N/A | N/A | malformed inputs | N/A | N/A | PASS |

# 3. Bugs Discovered

| ID | Severity | Capability | Observed Failure | Root Cause | Fix | Regression Test | Commit | Status |
|---|---|---|---|---|---|---|---|---|
| AFS-01 | P3 | Runtime | Python 3.12 UTC deprecations | `datetime.utcnow()` | Explicit UTC timestamps | progress UTC + stream warnings-as-errors | `88da335` | FIXED |
| AFS-02 | P2 | Creator/Source | Invalid rename could reach persistence; no service enable toggle | Incomplete update validation/service path | Validate edits; add `set_source_enabled` | invalid/Unicode/duplicate/restart tests | `7ce8fb7` | FIXED |
| AFS-03 | P1 | Live Processing | Real transcript exceeded segment by 2s and overlapped next segment | Offset conversion did not enforce closed interval | Clamp to interval; drop zero-length overshoot | boundary timeline + live E2E | `b86d3ac` | FIXED |

P0: 0 discovered / 0 open  
P1: 1 discovered / 0 open  
P2: 1 discovered / 0 open  
P3: 1 discovered / 0 open

# 4. Fixes

- `src/acfv/live/service.py`: bounds ASR evidence to closed segment timelines; unit replay and live E2E pass (`b86d3ac`).
- `src/acfv/library/service.py`: validates Creator edits and persists Source enable/disable; Library restart suite passes (`7ce8fb7`).
- `src/acfv/runtime/stream_monitor.py`, `src/acfv/modular/progress.py`: timezone-aware UTC; deprecations-as-errors target passes (`88da335`).
- Concurrency, 20-query grounding, and Windows Unicode/space/case-alias coverage were added in `d9ce797` and `b753fec`.

# 5. Creator / Source

Create, update, duplicate, blank input, Unicode, Twitch attachment, future-compatible platform, cross-creator duplicate rejection, Source enable/disable, and restart persistence pass. Creator remains distinct from Twitch channel.

# 6. Capture

Prior same-base REAL Twitch: 895.962s, 15 segments, controlled stop COMPLETE. Replay/fault suites pass crash, controlled stop, shutdown classification, invalid input, stable publish, survivor segments, and retry. Actual FFmpeg stress: 30s = 15 full segments, 60s = 7, 90s = 5; all parseable and ordered.

# 7. ASR

RTX 4050, faster-whisper medium CUDA float16; one worker/model-reuse path. Prior REAL RTF: cold/prewarmed ~0.194, warm ~0.121. Queue, retry, checkpoint, CPU fallback, and discovery pass. From 121 real transcript entries, one cross-boundary overlap was found and code-fixed; regression proves bounded monotonic merge.

# 8. Chat

REAL: `BLOCKED_EXTERNAL` because Twitch Client ID/OAuth are absent. Replay/unit extract, timestamps, flush, absence, and failure isolation pass. Chat remains optional; capture, ASR, Moments, live retrieval, and finalization pass without it.

# 9. Moments

PROVISIONAL, chat-alone no-claim, incremental idempotence, FINALIZING/FINAL, failure/retry, and restart pass. REAL: 22 FINAL, 0 provisional. Finalization 3x stable. Objective machine screen: 20/20 `AUTO_PASS`, 0 empty/duplicate/invalid timestamp/summary-term mismatch. Human quality is pending.

# 10. Retrieval

Exact, semantic, Chinese, English, mixed, Creator, Recording, Entire Library, and LIVE_SESSION paths pass. Dense + FTS pass; CrossEncoder absence falls back. Determinism/persistence pass. No-Evidence hard suite: 20/20, 0 unsupported claims. The 52h import has no transcript/Moment artifacts, so search/reindex honestly returns zero.

# 11. Conversation

Supported, unsupported, ambiguous/multiple evidence, invalid citation, and LLM failure paths pass. Evidence cards resolve to persisted Moment/Recording/timestamps; invalid or absent citations return No Evidence.

# 12. Clip

20 real proposals and 10 real renders were reused and re-probed. 10/10 have audio + video and correct duration tolerance. Boundaries pass. Multilingual/special/empty subtitle, missing font, and rerender invalidation pass. Objective screen: 10/10 `AUTO_PASS`; no human edit rating was filled.

# 13. Review / Feedback

Preview/render adapter, Accept, Reject, boundary/subtitle/style edits, rerender, feedback deltas/query/Moment/Creator linkage, explicit preference, bounded ranking effect, restart, and index-independent persistence pass.

# 14. GUI

The full Qt window launched successfully. Programmatic GUI suites: 27 passed, covering environment selection, startup doctor, controller, tabs, and errors. Native Computer Use was attempted, but this session exposed browser-only APIs and could not bind the Windows window. No fresh Library → Creator → Recording → Conversation → Evidence → Clip → Review → Accept click-through is claimed. Prior visible evidence remains; visual judgment is `HUMAN_REQUIRED`.

# 15. Persistence / Recovery

Restart, stale state recovery, segment retry, finalization idempotence, reindex without retranscription, render retry, and DB reopen pass. Concurrent readers/writers: five runs, 8 workers, 120 operations/run; no lock/deadlock/loss. Orphans: Source 0, Recording 0, Moment 0, Clip 0, Feedback 0. Runtime artifacts: 83/83 JSON/JSONL files and 179 JSONL records parse.

# 16. Library Audit

recordings: 10  
hours: 52.4306435 stored and ffprobe actual  
raw: 167,135,233,040 bytes (155.657 GiB; 2.969 GiB/hour)  
missing media: 0; corrupt media: 0; max duration drift: 0 ms  
incomplete: 10 unprocessed (`NEW` / `NOT_INDEXED`)  
index consistency: raw 52h library = 0 Moments/0 index rows; processed REAL library = 22 FINAL/22 FTS/0 provisional. Startup 0.056s, list 10, empty reindex 0.039s, empty search 0.008s, restart 0.031s. No user media was rewritten or deleted.

# 17. Performance

TTFT: prior REAL median 47.7s  
TTFM: prior REAL median 47.7s  
TTFS: prior REAL median ~37.0s, max ~61.0s  
ASR: ~0.194 cold/prewarmed; ~0.121 warm  
search: prior live batch ~1.3s; empty-index query 0.008s  
render: ten clips ~28s  
storage: REAL tree 197,177,556 bytes; capture 180,571,699; clips 16,058,379; index 174,710. No unbounded duplicate growth observed.

# 18. Automated Validation

compileall: PASS  
CLI: all root commands help plus safe creators/recordings/search/live-status queries PASS  
pytest: 232 passed, 0 skipped  
coverage: 85% Product + Live  
verify: PASS; contracts PASS

Run #1: 232 passed, 11 warnings, 86.16s  
Run #2: 232 passed, 11 warnings, 80.57s  
Coverage: 232 passed, 85%, 116.97s  
Verify: 232 passed, contracts PASS, 87.78s

Warnings: 8 dependency/package namespace + 3 third-party pysubs2. ACFV-owned UTC deprecations were removed.

# 19. CGNK

manifest: PASS; registry: 10/10 production capabilities mapped; guards: PASS  
doctor: PASS; Provider mainline and Codex automation available  
formal generation evidence: `NOT_EVALUATED` (generation was not requested)  
ChangeManifest: `autonomous-full-system-change-manifest.json`  
TestReceipt: `autonomous-full-system-test-receipt.json`  
Evidence: this report; raw output remains under ignored `var/`

# 20. Remaining External / Human Blockers

- REAL Twitch Chat is blocked by absent credentials; code cannot synthesize them.
- Human retrieval Top-5, 20 Moment, and 10 Clip ratings remain subjective. Machine results are only `AUTO_PASS`/`AUTO_SUSPECT`.
- Fresh GUI-native click-through is blocked because this session has no native Windows Computer Use API. App launch and 27 GUI contract tests pass.
- The 52.431h library is raw/imported, not processed. Per instruction it was not retranscribed, so long-recording Moment/search/clip quality is unavailable until artifacts exist.

# 21. Readiness

MVP_CODE_READY: YES — all automatically verifiable code paths pass; known P0 = 0, known P1 = 0.  
PRODUCT_VALIDATION_PENDING: YES — credential-bound and subjective/visual gates remain.

# 22. Final Verdict

`MVP_CODE_READY`  
`PRODUCT_VALIDATION_PENDING`  
`MVP_NOT_READY`

No push, PR, or merge was performed.
