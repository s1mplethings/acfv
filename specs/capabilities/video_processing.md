# Processing Pipeline

- Purpose: execute the existing ten-stage media workflow and publish canonical artifacts.
- Canonical Interface: `acfv.backend.service.create_job` (or `render_review_clip` for reviewed render adaptation).
- Implementation: `backend`, `pipeline`, `modular`, `steps`, and `providers`.
- Inputs: local/Twitch video, configuration, output directory.
- Outputs: transcript, selections, clip manifests, rendered clips, export results, runtime summaries.
- Effects: writes only beneath the selected run directory.
- Errors: canonical job state and logs report failure/cancellation.
- Dependencies: configured local providers and FFmpeg.
- Acceptance: fixed stage vocabulary and artifact contracts pass `contract_checks.py`; no second pipeline is introduced.

Closed live segments reuse the existing transcribe implementation through the Live
Processing service. This is an incremental adapter, not a second full-video pipeline.
