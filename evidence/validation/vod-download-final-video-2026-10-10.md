# VOD Download Final Video Validation — 2026-10-10

## Identity

- Branch: `validation/vod-download-final-video`
- Base: `90ab5333fe906fd674e0b2749934d8d28946c9ba`
- Implementation SHA: `ff2b572aed3bc6cf9d7f5b5b1c30233d31382442`
- Validation level: `REAL_RANGE_DOWNLOAD`
- Recording: `452b2d8b-5db8-414f-aba7-26b3de70e3f0`
- Sanitized VOD ID: `2340856811`
- Authorization note: `ACFV_TEST_TWITCH_VOD_URL` was unset. A publicly accessible Highlight was used without OAuth for local-only validation; ownership/license was not independently verified.

## Download Implementation Audit

| Component | Current implementation | Canonical owner | Still used | Problem | Action |
|---|---|---|---|---|---|
| URL normalization / VOD ID | strict Twitch parser | `VodDownloadService` + `providers.download` adapter | yes | channel URLs previously shared legacy ingest paths | reject channel/non-Twitch inputs before persistence |
| Metadata | TwitchDownloaderCLI `info --format Raw` | `VodDownloadService.discover` | yes | no durable VOD model | persist metadata before transfer |
| Provider | TwitchDownloaderCLI 1.56.5 | `providers.download` adapter | yes | three independent 0–100 progress phases | map phases to monotonic overall progress |
| Resume / retry | bounded retry, exponential backoff | `VodDownloadService.download` | yes | provider has no trustworthy byte resume | declare `SAFE_RESTART_ONLY`; retain partial |
| Temporary / atomic completion | `source.part.mp4` then `os.replace` | `VodDownloadService` | yes | none after fix | validate before atomic promotion |
| Duplicate prevention | unique platform + external VOD ID | Library repository | yes | concurrent duplicate risk | serialized discovery plus unique key |
| Library registration | Creator/Source/Recording mapping | `LibraryService` | yes | none after fix | reuse creator/source and durable recording |
| Processing handoff | `LibraryService.process_recording` | canonical backend | yes | CLI could exit before daemon finalization | synchronous CLI completion path |
| GUI / CLI | Library `Download VOD`; `acfv download vod/status` | same service/state rows | yes | no second progress state | both read `VodDownload` |

## Real Runtime Results

- Provider: TwitchDownloaderCLI 1.56.5
- Requested range: 0–900,000 ms; local duration 900,008 ms; drift 8 ms.
- Download: 365,394,406 bytes in 104.433 seconds; 3,498,840 bytes/s average; retries 0.
- Media: H.264/AAC, 1280×720, ~60 fps, 44.1 kHz; decode errors 0; suspected muted intervals 0.
- ASR: faster-whisper medium, CUDA request, single GPU worker, 16 chunks, 131 transcript segments, failed chunks 0. Processing environment reported CUDA payload; GPU memory telemetry was unavailable.
- Transcript: monotonic timestamps, zero zero-length entries, last timestamp 900,000 ms, spoken coverage 95.84%.
- Moments: 11 FINAL; punctuation-only 0; invalid 0; duplicate stable keys 0.
- Index: 11 parents, 63 representations, schema v4, multilingual-e5-base, 768 dimensions, real transformer backend, multilingual cross-encoder reranker.
- VOD query set (`AUTO_DERIVED`): 10/10 target Top-1, including English, Chinese, and mixed-language queries.
- Fixed retrieval set: Top-1 11/20, Top-3 14/20, Top-5 15/20, Top-10 17/20, Top-30 18/20, MRR 0.6325.
- Conversation fixed set: No-Evidence 5/5; invalid citations 0; unsupported claims 0. Ollama-compatible endpoint returned HTTP 502, so supported answers honestly used `EVIDENCE_ONLY`.

## Final Clip and Review

- Query: `Which airway follows Auspitt in the flight plan?`
- Moment: `4d577273-352c-45ee-8191-a1412f9e3cb4`
- Original boundary: 840,000–900,000 ms.
- Reviewed boundary: 839,600–900,000 ms (400 ms lead-in).
- Subtitle review: long ASR cues reflowed; 10 timed events; clean 24 px style, 2 px outline, 1 px shadow, 28 px bottom margin.
- Final: H.264/AAC MP4, 1280×720, 60.418 seconds, 16,050,988 bytes.
- Final SHA-256: `2199d531f360e6baabbd93254c1fb60bad0e00d702ed307f1aca533f0700f47c`
- Clean/subtitled hashes differ and review-v1/final hashes differ. A subtitle-time preview frame was visually inspected.
- ACCEPT is durable for the route explanation. A greeting-heavy candidate is durably REJECTED with an explicit reason. Restart readback preserved both.

## Fault Matrix

| Fault | Detected | Logged/actionable | Recoverable | Data loss |
|---|---:|---:|---:|---:|
| Invalid/channel/non-Twitch URL | yes | yes | yes | no |
| Deleted VOD / 404 | yes | yes | yes | no |
| No network / DNS | yes (simulated) | yes | yes | no |
| 403 permission / 429 / 5xx | yes (provider failure class) | yes | yes | no |
| Downloader executable missing | yes | yes | yes | no |
| Downloader crash | yes | yes | yes, bounded retry | no |
| Interrupted download | yes | yes | yes, safe restart | no |
| Partial file | yes | yes | yes, retained | no |
| Duplicate / concurrent duplicate | yes | yes | existing job returned | no |
| Invalid output / ffprobe failure | yes | yes | yes | no |
| ASR failure | yes (existing suite) | yes | checkpoint retry | no |
| Index failure | yes (existing suite) | yes | rebuild | no |
| Render failure | yes (existing suite) | yes | explicit rerender | no |
| Missing source file | yes | yes | restore/relink source | no |

## Automated Verification

- Post-final-change Run #1: compileall PASS; five CLI help checks PASS; pytest `328 passed`; verify PASS; contracts PASS.
- Post-final-change Run #2: compileall PASS; five CLI help checks PASS; pytest `328 passed`; verify PASS; contracts PASS.
- Task-module coverage: 87% across VOD service/provider, grounded conversation, and subtitle generator (48 focused tests).
- CGNK registry/spec/guard tests: PASS. Formal CGNK server evaluation: `NOT_EVALUATED`; repository evidence is locally generated and SHA-bound.

## Bugs Fixed

| ID | Severity | Symptom | Root cause | Fix | Regression |
|---|---|---|---|---|---|
| VOD-01 | P1 | no canonical durable VOD lifecycle | legacy adapters owned fragments | new canonical service/model/CLI/GUI | VOD suite |
| VOD-02 | P1 | progress reset from 100 to 0 | provider emits video/audio/mux phases | monotonic phase mapping and persisted max | progress test |
| VOD-03 | P1 | successful CLI pipeline recovered as FAILED | daemon finalizer died with CLI process | synchronous CLI finalization | terminal-state test |
| VOD-04 | P1 | 24-second ASR cue covered most of frame | sentence-only splitting allowed huge cues | readable caption reflow | subtitle test + preview |
| VOD-05 | P1 | opposite yes/no streaming claim passed sufficiency gate | lexical overlap threshold too permissive | stronger yes/no reranker gate | fixed set 5/5 |

## Remaining Problems

- The configured local Ollama/OpenAI-compatible endpoint returned HTTP 502 during this run; grounded supported questions therefore ran in honest `EVIDENCE_ONLY` mode.
- Native end-to-end GUI clicking and “Open final video” remain `HUMAN_REQUIRED`; controller/service/error paths and GUI contract tests passed.
- TwitchDownloaderCLI does not provide verified byte-resume semantics; the product explicitly reports `SAFE_RESTART_ONLY`.

