# Current State

- Product baseline: `feature/mvp-product-layer` at
  `2b219671f8070185d6114a9f70e2a4313a3135c6`.
- Refactor branch: `refactor/cgnk-project-structure`.
- Baseline validation: compile and CLI smoke PASS; 201 pytest tests PASS; contract checks
  and `scripts/verify.ps1` PASS; product-layer coverage previously measured at 83%.
- Implemented: Creator/Source/Recording persistence, Moment lifecycle, persistent hybrid
  retrieval, evidence-grounded conversation, clip rendering/re-render, review, explicit
  feedback, GUI/CLI surfaces, and local persistence E2E.
- Product verdict: `MVP_NOT_READY`.
- Core Product branch adds segmented TS capture, segment-close events, incremental ASR,
  recording-relative chat, PROVISIONAL Moment/index updates, Live Search/Conversation,
  and idempotent stream-end reconciliation. Automated replay E2E is passing.
- Remaining product gates: one real 10–30 minute Twitch session, real-material validation
  across 10 recordings / 20+ hours, and the associated human Moment/Clip/latency gates.

The structural refactor does not change the product verdict or claim those gates.

## Creator-Adaptive Phase 3

- Active work is on `feature/real-avatar-model-integration` from the canonical Creator-Adaptive evidence HEAD `4f97d4f`.
- The user-directed audit found `G:/Cliper/acfv/model/best.pt`. Checkpoint metadata and the original training/inference code prove it is a one-class Ultralytics YOLO11l detector (`0: vtuber`), not a Saruei/anny identity classifier.
- Real GPU inference is validated on 500 Saruei and 500 anny frames across multiple time regions. Avatar presence recall against recording context was 98.4% and 100%; all Creator identity remains UNKNOWN because no evidence-backed identity mapping exists.
- The repository now has a configuration/entrypoint integration harness, explicit versioned label mapping, persisted unknown observations, multi-frame visual spans, visual-first fusion, strict trusted-speech/lexicon/acoustic bootstrap, and profile-isolated Adaptive ASR Shadow fallback.
- Generic ASR remains authoritative. Creator-specific v2 voice profiles, trusted speech, lexicon, acoustic exemplars, adaptive results, and WER/CER are blocked at the visual-identity gate; none were fabricated from recording ownership.

## New Twitch Validation (2026-10-14)

- Branch `validation/new-twitch-vod-creator-adaptive` freezes nine previously unused
  public Twitch VOD ranges in `NEW_TWITCH_VALIDATION_V1`: five Saruei sessions, the
  only currently public anny archive, and Shylily/Zentreya/Ironmouse open-set material.
- Raw media is local-only and excluded from Git/delivery. The split SHA-256 is
  `ee9ceda31e283627a4f9c23729a2a756e0ca4e5488b70db04f302f4651c2b5a3`;
  HOLDOUT and UNKNOWN are forbidden from all training memory.
- The new-corpus visual benchmark selects MobileNetV3 only for shadow use. Recording-
  level proxy metrics are 100% strong precision, 24% strong coverage, 100% unknown
  rejection, and zero false-strong predictions. Saruei generalizes; anny does not
  (15.2% closed-set top-1 and zero strong predictions), so no production replacement
  is authorized.
- ECAPA is the better support-only speaker encoder, but its new-VOD attack FAR remains
  4.61%. Strict Trusted Speech rejects all automatic candidates; Creator Lexicon and
  Acoustic Exemplars remain empty, Adaptive ASR remains shadow/unchanged, and human
  WER/CER remains pending. Generic fallback and cross-Creator memory isolation pass.

## Multi-Creator Twitch Adaptive Audit (2026-10-14)

- Branch `feature/multi-creator-twitch-adaptive` adds atelieranoko, snuffy, and laphipi
  beside Saruei and anny. The current 18-VOD frozen split SHA-256 is
  `90e272ca8798449faec258e890152906f7c15cad5f2753b60c5e7a078b99446f`.
- The actual Q volume is 256 GB, not 2 TB. The 2 TB E and F volumes cannot preserve the
  required `max(15%, 200 GiB)` reserve for the estimated 185.08 GiB corpus. Bulk status
  is therefore `BULK_STORAGE_NOT_AVAILABLE`; no full-corpus download, training, model
  benchmark, Trusted Speech promotion, lexical memory, or product generation is claimed.
- Three canonical ten-minute 720p probes were acquired for engineering inspection.
  They produced 300 holdout/probe-only visual crops and 287 real large-v3 transcript
  segments. Snuffy VOD `2900140146` was detected as active `RECORDING` and excluded from
  the frozen corpus before training.
- Creator-adaptive contracts now support unnamed voice sub-centres, distinguish voice
  mode shift from known-Creator identity conflict, keep speaker and lexical-acoustic
  representations separate, and expose optional voice-style-change human review.
- Human identity, ASR, trusted-speech, and voice-style ground truth remains pending.
