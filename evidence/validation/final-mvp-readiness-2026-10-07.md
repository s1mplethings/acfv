# ACFV Final MVP Readiness — 2026-10-07

# 1. Repository

branch: `validation/final-mvp-readiness`  
base: `b8c6a6602ddedc884bdbc13d150af7e70da38b89`  
tested implementation: `d999cecbea6fff923b0db0ca96c2124dc0e265ec`  
commits: 7 focused commits  
working tree at implementation gate: clean

# 2. Bugs Found

| ID | Severity | Symptom | Root Cause | Fix | Regression Test | Commit |
|---|---|---|---|---|---|---|
| FMR-01 | P1 | Segment ASR failure polluted next stream session | Future raised before bridge cleanup | Drain futures, clean state, then raise aggregate error | `test_segment_failure_cleans_active_session_before_next_capture` | `c785f7c` |
| FMR-02 | P2 | Imported media duration remained empty | Scanner never probed duration | ffprobe on import and capture completion | `test_recording_import_and_capture_completion_probe_media_metadata` | `df0e8b1` |
| FMR-03 | P1 | Controlled stop could orphan FFmpeg or become FAILED | Shutdown order and exit classification were wrong | Terminate active capture first; distinguish controlled stop | `test_controlled_stop_finishes_recording_instead_of_reporting_failure` | `068d7f1` |
| FMR-04 | P1 | 15-minute run ended with Recording stuck in RECORDING | Watcher cancelled after fixed five-second grace | Await complete watcher/finalization before shutdown | `test_run_waits_for_slow_controlled_finalization_before_shutdown` | `c185ab9` |
| FMR-05 | P0 | ASR silently read only 40s of a final 60s TS | Next file creation preceded previous-file flush | Require stable size/mtime across two polls | `test_segment_is_not_published_until_previous_file_is_stable` | `7ef1c78` |
| FMR-06 | P1 | Cold TTFS was about 139s | ASR imports/runtime probe started after first close | Warm runtime in the single worker during first capture window | warmup/order tests | `de998b4` |
| FMR-07 | P1 | GUI opened only Fallback page | CUDA environment lacked `sqlmodel` but won environment scoring | Require PyQt5 + sqlmodel before candidate selection | `test_pick_better_python_rejects_cuda_env_missing_gui_dependencies` | `d999cec` |

# 3. Automated Validation

compileall: PASS  
CLI: 4/4 PASS  
pytest: 226 passed, 0 skipped  
coverage: 85% Product + Live  
contracts: PASS  
verify: PASS  
warnings: 247 known dependency/deprecation warnings; no new functional warning class.

# 4. Real Capture

Twitch: `twitchplayspokemon` REAL  
duration: 895.962 seconds  
segments: 15  
failures: 0 media failures; one validation shutdown race found and fixed  
natural end: no; controlled stop explicitly classified

# 5. ASR

hardware: NVIDIA RTX 4050 Laptop GPU  
model: faster-whisper medium / CUDA float16  
cold RTF after prewarm: 0.194  
warm RTF: 0.121 typical  
mean: about 0.157 for fixed cold/warm sample  
GPU memory: about 1859 MiB  
queue stability: one worker; 15 segments completed, transient normalization stall recovered without unbounded growth.

# 6. Live Search

REAL  
queries: 5 during-live factual + 2 no-evidence  
correct: 5/5 factual top result grounded  
No-Evidence: 2/2, zero claims; automated hard set 10/10  
TTFT: n=2 unique first-segment evidence, median 47.7s, p90 57.3s, max 59.7s  
TTFM: n=2, median 47.7s, p90 57.3s, max 59.7s  
TTFS: n=5 queries, median 37.0s, p90 61.0s, max 61.0s

# 7. Twitch Chat

BLOCKED_BY_CREDENTIAL  
messages: REAL not evaluated  
alignment: replay/unit paths only  
reconnect: not evaluated  
flush: artifact path validated  
failure isolation: chat remains optional and capture/ASR/Moments run without it.

# 8. Finalization

provisional: 22 real provisional Moments  
final: 22 FINAL Moments  
idempotence: 3/3 runs retained identical Moment IDs/count  
index consistency: 22 FINAL DB rows and 22 indexed rows after replacement

# 9. Persistence / Recovery

restart: PASS  
capture crash: stale RECORDING became retryable FAILED; 15 segments survived  
processing crash: failed-segment retry and no DONE replay covered  
index rebuild: PASS; no retranscription  
DB consistency: PASS across reopen/bootstrap

# 10. Retrieval

synthetic/deterministic: 10/10 Top5 gate PASS  
human: NOT EVALUATED; worksheet generated  
Top1: NOT EVALUATED  
Top3: NOT EVALUATED  
Top5: NOT EVALUATED

# 11. Moment Quality

sample: 20 FINAL real Moments prepared  
GOOD: blank for user  
ACCEPTABLE: blank for user  
BAD: blank for user

# 12. Clip Quality

sample: 10 real playable audio+video clips prepared  
NO_EDIT: blank for user  
MINOR_EDIT: blank for user  
MAJOR_EDIT: blank for user  
WRONG: blank for user

# 13. GUI E2E

Creator: PASS through real GUI  
Recording: surface present; isolated smoke had no recording  
Conversation: PASS No-Evidence behavior  
Evidence: surface present; no seeded GUI evidence  
Clip: Create Clip column/control present  
Review: boundary/subtitle/render/Accept/Reject controls present  
Feedback: preference and Accept/Reject controls present; full GUI chain NOT EVALUATED

# 14. Performance

TTFT: median 47.7s  
TTFM: median 47.7s  
TTFS: median 37.0s, max 61.0s  
search: during-live query batch completed in about 1.3s after index publication  
rerank: deterministic fallback validated; separate latency not isolated  
render: ten 8–12s clips rendered in about 28s total wall time  
disk/hour: raw capture about 0.289 GiB/hour; keeping raw segments plus concatenated media roughly doubles media storage.

# 15. Fault Injection

| Fault | Detected | Logged | Recoverable | Data Loss |
|---|---|---|---|---|
| Twitch unavailable | Yes | Yes | Yes | No |
| FFmpeg crash | Yes | Yes | Yes | Closed segments retained |
| Segment corrupt/failure | Yes | Yes | Retry failed only | No DONE replay |
| ASR error | Yes | Yes | Yes | Source retained |
| CUDA unavailable | Yes | Clear fallback/error | Yes | No |
| Chat disconnect | N/A without credential | N/A | Chat optional | Capture unaffected |
| Index write/rebuild | Yes | Yes | Rebuildable | Business data retained |
| DB reopen | Yes | Yes | Yes | No |
| Render failure | Yes | Yes | Re-renderable | No source loss |
| Missing media | Yes | Clear error | Relink/retry | DB state retained |

# 16. CGNK Evidence

Capability Registry: PASS  
Specs: PASS  
Skills: repository-audit, pipeline-change, product-layer-change, capability-validation, release-verification followed  
CGKN doctor: PASS; Provider mainline and Codex automation available  
CGKN formal generation evidence: NOT_EVALUATED (no generation run was required for this repository validation)  
ChangeManifest: `final-mvp-readiness-2026-10-07-change-manifest.json`  
TestReceipt: `final-mvp-readiness-2026-10-07-test-receipt.json`  
Evidence: this file plus three human-review worksheets

# 17. Remaining External Blockers

- Twitch OAuth/chat credentials were not available, so REAL chat message/alignment/reconnect validation is blocked.
- Human retrieval scoring (10 questions) is pending.
- Human review of 20 FINAL Moments is pending.
- Human review of 10 real Clips, including the 60% NO_EDIT+MINOR_EDIT gate, is pending.
- Full GUI-only Recording→Evidence→Clip→Render→Accept dogfood requires a user-reviewed Recording in the GUI Library.

# 18. Readiness Matrix

| Capability | Level | Result |
|---|---|---|
| Creator | UNIT / GUI | PASS |
| Capture | REAL | PASS |
| ASR | REAL | PASS |
| Chat | REPLAY / BLOCKED | NOT EVALUATED REAL |
| Moments | REAL / HUMAN | AUTOMATED PASS, HUMAN PENDING |
| Live Search | REAL | PASS |
| Finalization | REAL | PASS |
| Library | INTEGRATION / REAL LOCAL | PASS (10 recordings, 52.431h) |
| Retrieval | INTEGRATION / HUMAN | AUTOMATED PASS, HUMAN PENDING |
| Conversation | INTEGRATION / REAL | PASS |
| Clip | REAL | PASS |
| Review | REAL / HUMAN | TOOLING PASS, HUMAN PENDING |
| Feedback | INTEGRATION | PASS |
| Recovery | REAL / INTEGRATION | PASS |

# 19. Final Verdict

`MVP_CODE_READY`  
`PRODUCT_VALIDATION_PENDING`  
`MVP_NOT_READY`

The code and required REAL Twitch/GPU/during-live path are ready, with no known P0/P1 code defect remaining. The strict MVP verdict stays NOT READY because the credential-bound chat validation and mandatory human quality gates are not complete.
