# ACFV Real Library Build — Final Validation Report

Generated: `2026-10-08`  
Branch: `validation/real-library-build`

## 1. Repository

- Base: `80826f1345a235236cc1e614fcf7714fba9d7286`
- Implementation HEAD: `397135d297400e2e3ebe2cb8f7fd95620957082c`
- Scope: real-library build, recovery, validation, and narrowly required fixes only.
- Delivery policy: committed locally; no push and no merge.

## 2. Original Library

- Source: `F:\.work` (read-only throughout the pass).
- Recordings: **10**.
- Duration: **52.4306436111 hours**.
- Raw bytes: **167,135,233,040** (`155.657 GiB`).
- Canonical database: `var/final_validation_20261007/dogfood_import.db`.
- Relocated derived build: `F:\ACFV-Derived\real_library_build_20261007`.

## 3. Reuse Audit

Final audit classified all 10 recordings as `REUSE`: **10 REUSE / 0 RESUME / 0 REBUILD / 0 TRANSCRIBE / 0 BLOCKED**. Reuse required valid media, transcript, FINAL Moments, and matching index rows; it did not rely only on file presence. See `real-library-reuse-matrix.md`.

## 4. Processing Results

- READY recordings: **10/10**; failed recordings: **0**.
- Transcript entries: **36,366**.
- FINAL Moments: **3,999**.
- Indexed Moments: **3,999**.
- Clip proposals/renders: **10/10**, all `AUTO_PASS`.
- Final validator: **PASS** (`91.202 s`).

## 5. Per Recording

| Recording | Hours | Transcript | FINAL Moments | Index | ASR evidence | Status |
|---|---:|---:|---:|---:|---|---|
| `c86dc576` | 3.956 | 3,366 | 291 | 291 | historical WIP; runtime unavailable | READY |
| `121a99a3` | 4.054 | 2,824 | 293 | 293 | historical WIP; runtime unavailable | READY |
| `0a01c6ab` | 4.072 | 2,242 | 306 | 306 | historical WIP; runtime unavailable | READY |
| `90f26a14` | 4.390 | 2,092 | 372 | 372 | historical WIP; runtime unavailable | READY |
| `4493aff0` | 4.739 | 3,750 | 361 | 361 | historical WIP; runtime unavailable | READY |
| `5d31e9cc` | 5.068 | 3,850 | 389 | 389 | historical WIP; runtime unavailable | READY |
| `4863f974` | 6.431 | 5,082 | 473 | 473 | 2,386 s; RTF 0.103059; 193 chunks; 0 failed | READY |
| `5e6db3d3` | 7.243 | 3,968 | 566 | 566 | 3,115 s; RTF 0.119461; 218 chunks; 0 failed | READY |
| `2c6ed1ce` | 9.120 | 6,239 | 711 | 711 | 3,587 s; RTF 0.109254; 274 chunks; 0 failed | READY |
| `19dc8461` | 3.357 | 2,953 | 237 | 237 | 7 s cache-repair replay; not a representative ASR RTF | READY |

## 6. Bugs Found

| Severity | Problem | Resolution | Commit(s) |
|---|---|---|---|
| P1 | Long ASR runs could lose checkpoints or stall/restart without bounded recovery. | Preserved checkpoint events, validated recovery, recycled CUDA workers, and bounded retries. | `c7a50ad`, `9df0f20`, `dde5362`, `4e74142`, `9996e7e` |
| P1 | Disk exhaustion required relocation, while cached absolute audio/run paths could still target the old drive. | Relocated derived artifacts, rebased cached audio, and made the explicit stable build root authoritative. | `da26a68`, `19d2914`, `2fd7088` |
| P1 | Transcript/Moment tail evidence could exceed media duration. | Clamped ASR tails and final Moment evidence to recording bounds; added strict validation. | `9705533`, `a31c783`, `14b2971` |
| P1 | Windows validation cleanup could retain SQLAlchemy/SQLite handles and prevent recovery index deletion. | Disposed isolated engines and explicitly closed FTS connections. | `fc1d2dc`, `397135d` |
| P2 | Audit-only runs overwrote progress with `PENDING`. | Preserved existing build progress. | `0f135bc` |
| P2 | No-evidence probes could collide with real corpus terms; validator missed a legacy transcript filename. | Added deterministic nonce probes and both transcript layouts. | `397135d` |
| P2 | Unicode media paths and absent stderr could break ffmpeg/ffprobe diagnostics. | Added UTF-8 replacement decoding and safe stderr handling. | `397135d` |

Known P0: **0**. Known P1 remaining: **0**.

## 7. Transcript

- Entries: **36,366**; invalid: **0**; non-monotonic: **0**; zero-length: **0**.
- Overlapping adjacent entries: **207**, retained as informational ASR segmentation rather than corruption.
- Detected recording languages: **5 Japanese / 5 English**.
- Validator accepts canonical `transcript_merged.json` and legacy `transcription.json`.

## 8. Moments

- FINAL: **3,999**; invalid bounds: **0**.
- Near duplicates: **0**; pathological overlap: **0**.
- Shorter than 5 seconds: **541**, reported but not treated as invalid.
- Automatic classification: **3,999 AUTO_PASS / 0 AUTO_SUSPECT**.

## 9. Index

- Database FINAL rows: **3,999**; index rows: **3,999**.
- Missing: **0**; stale: **0**; duplicate IDs: **0**.
- A destructive index rebuild in an isolated recovery path restored all **3,999** rows and search remained functional.

## 10. Retrieval

- Full-library evidence benchmark: **36/50** expected recordings in top 5.
- Result-integrity sample: **50**, failures: **0**.
- No-evidence behavior: **20/20** correctly ungrounded; unsupported claims: **0**.
- Keyword, semantic, English, Chinese, mixed-language, creator scope, recording scope, and entire-library smokes: **PASS**.
- Cross-recording retrieval returned evidence from **8 recordings**.
- Deterministic legacy benchmark remains **3/3 tests passed** and its fixed query fixture resolved **10/10 expected top-5 results**; it is distinct from the 50-query real-library sample above.

## 11. Clips

- Proposals: **10**; rendered files: **10**; `AUTO_PASS`: **10**.
- All clips passed ffprobe video/audio/duration checks and source-interval bounds.
- Mostly-silent clips: **0**.
- Human clip review remains deliberately pending.

## 12. Library Integrity

- SQLite integrity: `ok`; foreign-key violations: **0**.
- Orphans: source-without-creator **0**, recording-without-creator **0**, Moment-without-recording **0**, Moment-without-creator **0**.
- Raw source library was not modified.

## 13. Recovery

The recovery E2E passed: index `3,999 -> rebuilt 3,999 -> reopened 3,999`, retrieval returned 5 hits, a real clip rendered successfully, feedback was persisted, and the clip/feedback state survived process restart.

## 14. Performance

- Retrieval latency: median **127.047 ms**, p90 **135.251 ms**, max **7,587.614 ms** (one cold-start outlier).
- Startup: database **59.915 ms**; index manifest **56.413 ms**.
- Memory: index-loaded process **101.023 MiB**; observed GPU allocation **400 MiB**.
- Measured continuation window was approximately **3 h 03 min**, including resumes, recovery, and validation. It excludes already-completed historical WIP, whose original wall time cannot be reconstructed reliably.
- Representative newly measured long-recording ASR RTF range: **0.103059–0.119461**.

## 15. Storage

| Category | Size |
|---|---:|
| Raw | 155.657 GiB |
| Analysis and other | 2.668 GiB |
| Transcripts | 10.962 MiB |
| Audio | 5.625 GiB |
| Chunks | 5.637 GiB |
| Index | 23.155 MiB |
| Clips | 205.877 MiB |
| Database | 19.352 MiB |
| Derived total | 14.183 GiB |
| Raw + derived total | 169.840 GiB |

## 16. Automated Verification

- Regression run 1: compileall PASS; four CLI smokes PASS; pytest **262 passed, 11 warnings in 81.26 s**; `verify.ps1` **262 passed, 11 warnings in 64.22 s**, contract checks PASS.
- Regression run 2: compileall PASS; four CLI smokes PASS; pytest **262 passed, 11 warnings in 61.73 s**; `verify.ps1` **262 passed, 11 warnings in 62.97 s**, contract checks PASS.
- Product-layer coverage: **87%**, **262 passed in 85.33 s** (target at least 80%; prior prompt baseline 85%).
- CLI smokes: `acfv --help`, `acfv gui --help`, `acfv pipe clip --help`, and `acfv live --help`, executed against `src` via `PYTHONPATH`.
- The 11 warnings are existing `pkg_resources`/`pysubs2` deprecations.

## 17. Human Validation Pack

Prepared and intentionally unscored:

- `final-human-retrieval-review.md`: 10 required, 0 rated.
- `final-human-moment-review.md`: 20 required, 0 rated.
- `final-human-clip-review.md`: 10 required, 0 rated.
- `final-gui-checklist.md`: pending.
- `human-review-results.json`: machine-readable human-result placeholder.

## 18. CGNK Evidence

The current real-library work preserves the CGNK-compatible project boundary and uses the reviewed provider route established by the earlier refactor. Supporting evidence remains in `cgnk-refactor-2026-10-07.md`, `cgnk-refactor-test-receipt.json`, and `cgnk-refactor-change-manifest.json`; this pass did not reintroduce removed non-MVP product surfaces.

## 19. Remaining Blockers

- Human retrieval, Moment, clip, and GUI review are incomplete; this is the sole MVP readiness blocker.
- Twitch Chat enrichment is `BLOCKED_EXTERNAL` where source chat is unavailable. It is optional enrichment and is **not** a code or real-library readiness blocker.
- No known P0/P1 code defect remains.

## 20. Readiness

- `MVP_CODE_READY`: **true**.
- `REAL_LIBRARY_READY`: **true**.
- `PRODUCT_VALIDATION_PENDING`: **true**.
- `MVP_READY_FOR_REAL_USAGE`: **false** until the human pack meets its thresholds.

## 21. Final Verdict

```text
MVP_CODE_READY
REAL_LIBRARY_READY
PRODUCT_VALIDATION_PENDING
MVP_NOT_READY
```

