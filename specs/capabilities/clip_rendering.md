# Clip Rendering

- Purpose: turn one reviewed Moment-derived proposal into an MP4 through the existing renderer.
- Canonical Interface: `acfv.clips.service.ClipService.render`.
- Implementation: `src/acfv/clips/service.py`, adapting `acfv.backend.service.render_review_clip`.
- Inputs: Clip ID, source path, editable boundaries, subtitle text/style.
- Outputs: persisted render status and MP4 path.
- Effects: invokes the existing FFmpeg render path; no second renderer.
- Errors: missing Clip/source or invalid render failure is persisted and raised.
- Dependencies: LibraryRepository and backend render adapter.
- Acceptance: file exists, ffprobe is valid, and duration is close to requested interval.

Clip event identity is independent from output variants. Candidates from the same Recording with temporal IoU >= 0.8, the same payoff/parent anchor, or identical media hashes count as one event; multiple duration/subtitle renders may be retained as `same_event_variant` but do not inflate unique-event validation counts.
