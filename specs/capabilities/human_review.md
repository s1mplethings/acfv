# Human Review Lab

- Purpose: build blinded review datasets, persist genuine human annotations, and expose compact analysis without requiring CSV/JSON/terminal workflows.
- Canonical Interface: `acfv.human_review.HumanReviewRepository`, `HumanReviewDatasetBuilder`, and `HumanReviewAnalysis`.
- Implementation: `src/acfv/human_review/`.
- CLI: `python -m acfv.cli review-lab`.
- Inputs: read-only canonical quality evidence and media artifacts; explicit human choices entered in the independent Qt Lab.
- Outputs: `human_review.sqlite`, revision history, SQLite backups, CSV/JSON exports, and human-data-only analysis. Interactive writes use WAL/NORMAL transactions; backup and close force a FULL WAL checkpoint before copying.
- Effects: writes only beneath the configured Human Review root. It does not mutate Product Library, clips, generation evidence, Product GUI, ASR, translation, or backend state.
- Errors: missing individual media is non-fatal and exposes Skip/Relink; missing canonical sources are reported in Dataset Info; failed database integrity enters read-only recovery instead of overwriting annotations.
- Dependencies: PyQt5, the existing Product GUI media/worker primitives, standard-library SQLite, and canonical quality evidence.
- Recovery: startup runs `PRAGMA integrity_check`; failure enters read-only recovery mode. The test database is always named `human_review_test.sqlite` and is separate from `human_review.sqlite`.
- Blindness: Translation and Watchability provider/strategy identity is private dataset state and is absent from presentation state until an answer is saved and reveal is enabled.
- Creator-adaptive review: Identity, ASR, Trusted Speech, and Adaptive-ASR tasks may also
  record the optional blinded answer `voice_style_changed = YES | NO | UNSURE`. Reviewers
  are explicitly told not to infer accent, nationality, or identity from style alone.
- Acceptance: all six review tasks and Analysis are available in one window; annotations autosave with revisions; skip/back/revisit/resume survive restart; automatic backup occurs every 50 revisions and on close; Save & Next averages under 100 ms and p95 stays under 150 ms in the canonical native validation; export and analysis require no scripts; Product GUI and backend contracts remain unchanged.
