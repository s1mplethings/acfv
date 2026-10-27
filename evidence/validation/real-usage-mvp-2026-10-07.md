# Real-Usage MVP Validation — 2026-10-07

## Source identity

- Branch: `validation/real-usage-mvp`.
- Base: `9c227f6cf77cc871f6a5757ae7cb32f98738443d`.
- Analysis Profile commit: `a53a2f62fa5e089313cad94a8ad65cf32351a7ff`.
- Real-runtime fixes commit: `3be8996dde8b3ab6a9dce2f3c04571231ed112c6`.
- Environment: Windows 11, Python 3.12.3, FFmpeg N-116931, NVIDIA GeForce RTX 4050 Laptop GPU (6141 MiB), driver 581.29.

## Validation classification

| Area | Level | Evidence |
|---|---|---|
| Twitch detection | REAL | StreamGet detected public channel `twitchplayspokemon` live. |
| Twitch capture | REAL | Public Twitch HLS was captured by actual FFmpeg for 600.07 seconds of monitor runtime. |
| Segment processing | REAL capture / REPLAY processing | Captured TS files were processed after the timezone bug was fixed. |
| GPU ASR | REAL hardware + REAL media / REPLAY scheduling | faster-whisper medium ran on RTX 4050; NVIDIA process and memory were observed. |
| Twitch chat | NOT EVALUATED | No Twitch client ID/OAuth token was available; current transport is post-stream VOD chat, not live IRC/EventSub. |
| Live search | REPLAY ONLY | Search was executed against provisional Moments after capture, not while the Twitch stream was being captured. |
| Automated product E2E | REPLAY | Existing replay suite passed. |

## Real Twitch capture

- Monitor runtime: 600.07 seconds.
- Closed segments: 9; duplicates: 0; failed media segments: 0.
- Captured media duration: 515.464 seconds (8.591 minutes).
- Segment duration average/min/max: 57.274 / 35.466 / 60.000 seconds.
- Ordered names: `segment_000000.ts` through `segment_000008.ts`.
- Timeline gaps among the first eight full segments: 0; the ninth was correctly closed as a short final segment after forced FFmpeg termination.
- Failure injection: FFmpeg was terminated; `recording_failed` with return code 1 and a shutdown event were emitted. All nine CLOSED media files remained readable.
- The run is shorter than the requested 10–30 minutes of captured media and therefore does not close that gate.

## Bugs found and fixed

1. Recording creation silently failed. Monitor events used naive UTC datetimes, while persisted datetime fields require timezone information. Events now use timezone-aware UTC, and hook exceptions are logged at ERROR with traceback. A regression assertion verifies UTC offsets.
2. CUDA environment probing timed out before the installed `clip` environment finished importing Torch. The probe timeout is now configurable and defaults to 30 seconds.
3. CUDA DLL paths were derived from the parent of the environment root (`.../envs`) instead of the selected environment (`.../envs/clip`). The root calculation and Windows DLL-directory registration were fixed, allowing the live process to reuse its GPU model with one ASR worker.

## Incremental ASR and latency

- Model: faster-whisper medium, CUDA float16, one worker.
- Observed GPU memory: approximately 1859 MiB during the direct GPU validation sample.
- Segment 0: 60.0 seconds media, 34.256 seconds processing, RTF 0.571.
- Segment 1: 60.0 seconds media, 7.789 seconds processing with model reuse, RTF 0.130.
- Mean RTF: 0.350; no sustained backlog is expected from this two-segment sample because both processing times are below the 60-second arrival interval.
- Three provisional Moments were persisted from two processed segments.
- Derived upper-bound TTFT/TTFM/TTFS, measured as segment end (60 seconds after its first content) plus processing completion: samples 94.256 and 67.789 seconds; median 81.023, p90 91.609, max 94.256 seconds, n=2.
- These latency figures are REPLAY-derived upper bounds, not a successful live-session search measurement. They do not close the live TTFS gate.

## Retrieval and no-evidence checks

Using provisional Moments built from the real capture, after capture:

- `Spiritomb` retrieved the 0–34 second Moment: correct.
- `Who won the game?` retrieved the 0–34 second Moment containing “The Red Corner has won”: correct.
- `Did they mention Minecraft?` returned the live no-evidence answer: correct.
- `Was there a cooking recipe?` returned the live no-evidence answer: correct.
- Query latency without CrossEncoder: 10.5–49.6 ms after a 12.66-second index rebuild.
- This is not the required five during-live queries or the ten user-authored retrieval questions.

## Finalization, restart, and recovery

- Forced capture exit: PASS; failure was visible and segments were preserved.
- Stale Recording recovery after process exit: PASS; restart changed the abandoned `RECORDING` state to `FAILED`.
- Replay finalization: 3 provisional Moments became FINAL.
- Finalization idempotence: two calls retained the same 3 Moment IDs and the same 3 index rows.
- Restart persistence: Recording `COMPLETE`, index `READY`, and all 3 FINAL Moments restored.

## Automated verification

- Compileall: PASS.
- CLI help: root, GUI, pipe clip, live — 4/4 PASS.
- Pytest: 217 passed, 0 skipped.
- Selected product coverage: 85%.
- `scripts/verify.ps1`: PASS.
- Contract checks: PASS.

## Open gates and limitations

- No real Twitch chat transport/alignment/reconnect/flush validation.
- No live query was issued before the capture ended.
- No natural stream-end reconciliation; finalization used replay after injected failure.
- Dataset: 1 real recording, 0.143 captured hours, 1 creator; required 10 recordings / 20 hours not met.
- No ten human-authored retrieval questions, twenty human-reviewed FINAL Moments, ten human-reviewed Clips, subtitle review, preference ranking comparison, or full GUI-only dogfood flow.
- Analysis Profile persistence is covered by automated Creator/Recording restart tests, but GUI interaction was not manually dogfooded.

## Verdict

`MVP_NOT_READY`

The pass found and fixed real capture/library and CUDA-runtime defects, and it proves real Twitch capture plus real GPU ASR on the target machine. The mandatory live-search, chat, dataset, and human-review gates remain open.
