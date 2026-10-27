# Twitch Capture

- Purpose: bind stream-monitor events to durable Source and Recording lifecycle state.
- Canonical Interface: `acfv.library.capture.StreamLibraryBridge`.
- Implementation: `src/acfv/library/capture.py` with `acfv.runtime.stream_monitor`.
- Inputs: bound Twitch Source, monitor target, presence/capture events.
- Outputs: Recording lifecycle updates and optional processing submission.
- Effects: records ordered closed media segments, emits `segment_closed`, and updates Library state.
- Errors: unrelated targets are ignored; capture failures become retryable state.
- Dependencies: Creator Library and existing stream monitor.
- Acceptance: detection drives Recording through RECORDING to COMPLETE/FAILED; five simulated segments close in continuous order and are forwarded once to Live Processing.
