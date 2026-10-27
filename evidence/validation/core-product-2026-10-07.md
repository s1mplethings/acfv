# Core Product Validation — 2026-10-07

## Source identity

- Implementation commit: `23416a98387fcfdabfaddffff628030e50e3ab35`.
- Base: `2aaf63f272b22b0ca458a9bd648453bfc31a156a`.
- Branch: `feature/acfv-core-product`.
- Environment: Windows 11, Python 3.12.3, PowerShell, local FFmpeg/ffprobe.

## Automated results

- Compileall: PASS.
- CLI help: root, GUI, pipeline, and live surfaces PASS.
- Pytest: 214 passed; no skips.
- Product + Live coverage: 85%.
- `scripts/verify.ps1`: PASS; contract checks PASS.
- Segmented capture: simulated FFmpeg process produced five ordered 60-second TS segments,
  five `segment_closed` events, and a concat invocation.
- Live lifecycle: local recorded-stream replay proved closed segment → once-only ASR →
  absolute transcript → aligned chat → PROVISIONAL Moment → live index/search/conversation
  before finish → FINAL reconciliation → restart → historical search → real FFmpeg clip
  render → Accept + explicit preference → second restart persistence.

## Validation classification

- Twitch status: REPLAYED STREAM plus mocked StreamGet/FFmpeg process boundaries; no real
  network Twitch live session was run.
- Recordings: one automated local replay fixture, not a human dogfooding dataset.
- Total duration: approximately 10 seconds of source media; not 20 hours.
- Retrieval gate: existing deterministic benchmark remains 10/10 Top-5; the required ten
  real-user questions over the dogfooding dataset were not evaluated.
- Moment gate: 20 randomly reviewed FINAL Moments were not evaluated.
- Clip gate: 10 human-reviewed real clips were not evaluated.
- Live latency: event order is tested, but real TTFT/TTFM/TTFS was not measured on Twitch;
  the ≤120 second real-session target is not evaluated.

## Verdict

The core implementation and automated replay E2E are complete, but the hard real-usage
gates remain open. Product verdict: `MVP_NOT_READY`.
