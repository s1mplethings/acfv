# 1 Repository

Branch `feature/compact-human-review-gui`; verified implementation commit `6164bf72cef98fef1573d8a6fdacad368c653902`. The Lab is a new isolated capability under `src/acfv/human_review/`.

# 2 Human Review Lab

- entry: `python -m acfv.cli review-lab`
- single-window: yes; eight primary destinations only
- annotation DB: `human_review.sqlite`; automated runs use `human_review_test.sqlite`
- dataset: deterministic Fixed37 Human Review Large v1

# 3 Overview

- progress: six cards plus always-visible global progress
- continue: resumes the item on screen, otherwise selects the highest-priority unfinished task
- filters: Remaining, Completed, Skipped, Revisit, Creator, and Content Type

# 4 ASR

- samples: 200
- workflow: audio/context, four quick decisions, conditional human transcript
- shortcuts: 1–4, R, L, Space, Ctrl+Enter

# 5 Translation

- samples: 120
- blind: provider identity excluded before answer
- quick review: A, B, Same, Both Bad
- details: three optional ratings and nine optional issue flags

# 6 Boundary

- events: Fixed37 37/37
- video: media-first workspace with missing-media recovery
- start/end: three-way Start, End, and Length choices
- advanced: setup/core/payoff/aftermath, preferred profile, I/O manual timestamps

# 7 Watchability

- pairs: 74, including labelled consistency controls and profile comparisons
- blind: strategy identity excluded before answer
- quick review: A, B, Same, Both Bad with optional reasons

# 8 Subtitle

- cue: 100 cue review items with English/Chinese
- clip: 118 full-clip readability items
- readability: quick labels plus optional speed, break, sync, merge, split, and obstruction reasons

# 9 Publishability

- events: 37
- quick review: Keep, Maybe, Reject
- reject reasons: 13 multi-select reasons plus optional five-axis ratings

# 10 Analysis

- ASR: labels, WER, CER, confidence/accuracy buckets
- Translation: blinded choice distribution, provider wins, optional rating means
- Boundary: start/end/length and preferred profile distributions
- Watchability: choice distribution, strategy wins, content-type breakdown
- Subtitle: Cue/Clip distributions
- Publishability: Keep/Maybe/Reject and reject reasons

# 11 Persistence

- autosave: every Save/Skip/Revisit write is transactional
- resume: current task and item are persisted on display
- backup: every 50 revisions, manual menu action, and application close
- history: previous/new answer and status revisions with timestamp

# 12 Dataset Integrity

- counts: ASR 200; Translation 120; Boundary 37; Watchability 74; Subtitle 218; Publishability 37; total 686
- dedup: 0 duplicate sample IDs; 194/194 unique formal A/B pair IDs
- blind: 71 controls labelled; private provider/strategy withheld before answer
- Fixed37: boundary coverage 37/37; hash `acff329191e7b0aa7b4419a43b71beaa91a709a4c6ceb34f58fc034f34a3cda3`

# 13 Native Validation

- test annotations: 10 ASR, 10 Translation, 10 Boundary, 10 Watchability, 10 Subtitle, 5 Publishability
- restart: all six counts identical after close/reopen; SQLite integrity `ok`
- result: PASS; production database untouched

# 14 Visual Validation

- screenshots: 01–10 captured for each scale
- resolutions: 1920×1080 and 1280×720
- DPI: 100%, 125%, 150%
- issues: no geometry clipping or missing primary controls detected; offscreen font rasterization and native media decoding remain for human visual signoff

# 15 Performance

- startup: 131.84 ms
- media: 0.73–1.31 ms in the offscreen validation adapter
- save: included in the combined metric below
- next: Save & Next average 32.28 ms, p95 41.86 ms; task switching 26–38 ms
- analysis: 2.26 ms for 686-sample dataset state; refreshed lazily when Analysis is visible

# 16 Product Regression

- Backend: unchanged; full regression PASS
- Product GUI: unchanged; focused Product GUI tests and full regression PASS
- Fixed37: 37/37 dataset coverage and full regression PASS

# 17 Automated Verification

- pytest1: 524 passed, 0 skipped, 0 xfailed
- pytest2: 524 passed, 0 skipped, 0 xfailed
- verify1: PASS; 524 passed; contracts PASS
- verify2: PASS; 524 passed; contracts PASS
- contracts: PASS and manifests schema-valid
- skip: 0 added / 0 total
- xfail: 0

# 18 Deliverables

- launch command: `python -m acfv.cli review-lab`
- DB: configured Human Review root, separate production/test filenames
- backup: `<review-root>/backups/`
- exports: `<review-root>/exports/` as CSV, JSON, `analysis.json`, and `analysis.md`
- screenshots: `evidence/validation/human-review-lab/screenshots/`

# 19 Engineering Status

- HUMAN_REVIEW_SINGLE_WINDOW_READY: YES
- HUMAN_REVIEW_OVERVIEW_READY: YES
- ASR_GUI_READY: YES
- TRANSLATION_GUI_READY: YES
- BOUNDARY_GUI_READY: YES
- WATCHABILITY_GUI_READY: YES
- SUBTITLE_GUI_READY: YES
- PUBLISHABILITY_GUI_READY: YES
- ANALYSIS_GUI_READY: YES
- EXPORT_GUI_READY: YES
- ANNOTATION_AUTOSAVE_READY: YES
- ANNOTATION_RESUME_READY: YES
- ANNOTATION_BACKUP_READY: YES
- BLIND_REVIEW_READY: YES
- DATASET_LARGE_READY: YES
- HUMAN_REVIEW_LAB_READY: YES
- PRODUCT_GUI_UNCHANGED: YES
- BACKEND_UNCHANGED: YES
