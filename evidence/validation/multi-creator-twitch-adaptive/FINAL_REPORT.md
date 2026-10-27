# 1 Repository

branch: `feature/multi-creator-twitch-adaptive`  
base: `2efa626fb2b106a0a4229aa2f9ea132a12d847ee`  
implementation: `bc4fb81287b25ce8fd616d6f467e8773a2a8efa8`  
evidence: this evidence directory; final evidence commit is recorded by Git  
working tree: clean after evidence commit and deliverable verification

# 2 Storage

Q exists: YES, but it is not the stated 2 TB HDD  
Q capacity: 256,059,109,376 bytes (238.47 GiB)  
Q free: 49,457,393,664 bytes (46.06 GiB)  
media type: USB SSD  
health: Healthy / OK  
selected BULK_MEDIA_ROOT: NONE — `BULK_STORAGE_NOT_AVAILABLE`  
reserve: 300,057,152,102 bytes on the largest 2 TB candidate  
estimated used: 198,481,500,000 bytes (184.85 GiB)  
final free: F had 241,972,154,368 bytes after probes; projected after corpus 43,490,654,368 bytes, below reserve

E is the real 2 TB USB HDD (Healthy/OK) but has only 96,490,627,072 bytes free. F is
also 2 TB but has only 241,972,154,368 bytes free. G reports Warning / Full Repair Needed.
Formal bulk download was correctly blocked.

# 3 Twitch Creators

| Creator | Channel resolved | VODs discovered | VODs usable in frozen corpus |
| --- | ---: | ---: | ---: |
| Saruei | YES | 20 | 5 |
| anny | YES | 1 | 1 (`LIMITED_VOD_DIVERSITY`) |
| atelieranoko | YES | 20 | 4 |
| snuffy | YES | 18 | 4; active probe VOD excluded |
| laphipi | YES | 20 | 4 |

# 4 Downloads

Only safety-bounded probes were permitted. Saruei and anny had no new eligible probe
after dedup/availability checks.

| Creator | VOD ID | Date UTC | Type | Range / quality | Bytes | Corpus role | Local locator | SHA-256 |
| --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| atelieranoko | 2898984086 | 2026-10-12 | archive | 10 min / 720p | 245,735,185 | HOLDOUT probe | local ignored validation root | `e0f4bca8ccca8488bd27bb362ee1e85a7a7c423257af42f6be4a4d04dc69afd0` |
| snuffy | 2900140146 | 2026-10-14 | archive, still RECORDING | 10 min / 720p | 245,282,547 | PROBE_UNFINALIZED; excluded | local ignored validation root | `f52baf855f3bfeb4f20afea90980a19ca934ac61cbd6c82378d57b6e2b07e0b6` |
| laphipi | 2897831198 | 2026-10-11 | archive | 10 min / 720p | 171,016,479 | HOLDOUT probe | local ignored validation root | `9f1617823ffdb9bb5f258c2ee26a9a4e7b1f7a71b686859d0df8dbe9a59b3f65` |

All three contain H.264 video + AAC audio at 1280×720, decode cleanly, and have no
detected long muted interval. Total downloaded: 662,034,211 bytes.

# 5 Corpus

TRAIN: 9 VODs  
VALIDATION: 4 VODs  
HOLDOUT: 5 VODs  
UNKNOWN: 0 new VODs; prior open-set corpus remains separate  
total hours: 73.51 metadata hours; full media not present  
split SHA: `90e272ca8798449faec258e890152906f7c15cad5f2753b60c5e7a078b99446f`

# 6 Visual Identity

five creators: corpus plan YES; five-Creator training NO  
model candidates: existing YOLO11l presence detector plus metric-identity candidates  
winner: NOT SELECTED — frozen TRAIN media unavailable

Per-Creator Strong precision proxy, Strong coverage, unknown, holdout, and temporal
metrics are `NOT_RUN_STORAGE_BLOCKED`. Engineering-only probe sampling produced 100
crops each for atelieranoko, snuffy, and laphipi (300 total), with no recording leakage.
Manual contact-sheet inspection found stable dominant avatars in all three probes; this
is not identity ground truth or a five-Creator metric.

# 7 Voice Models

ECAPA: existing baseline, not rerun on this split  
ERes2NetV2: NOT RUN; exact checkpoint license and fixed audio unavailable  
CAM++: NOT RUN  
ReDimNet: NOT RUN  
winner: NONE  
reason: comparing models without identical TRAIN/VALIDATION/HOLDOUT audio would be invalid

# 8 Voice Modes

| Creator | Segments | Clusters | Unnamed modes | Shift candidates | Conflicts | Unknown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Saruei | 0 | 0 | 0 | 0 | 0 | 0 |
| anny | 0 | 0 | 0 | 0 | 0 | 0 |
| atelieranoko | 0 | 0 | 0 | 0 | 0 | 0 |
| snuffy | 0 | 0 | 0 | 0 | 0 | 0 |
| laphipi | 0 | 0 | 0 | 0 | 0 | 0 |

Real profile build is blocked. The implementation and deterministic synthetic tests now
support unnamed `MODE_n` sub-centres and distinguish mode shift from known-other conflict.

# 9 Trusted Speech Funnel

For every Creator: candidates 0; visual reject 0; voice reject 0; music 0; overlap 0;
ASR reject 0; critical reject 0; re-decode reject 0; other 0; accepted 0; duration 0.
Reason: no legal TRAIN media/profile. HOLDOUT probes were never promoted.

# 10 Lexicon Funnel

For every Creator: trusted 0; raw terms 0; filtered 0; repeated 0; scope 0; promoted 0;
used 0. The TRAIN-only guard is active.

# 11 Lexical Acoustic Memory

HuBERT: research interface implemented; real benchmark NOT RUN  
WavLM if run: NOT RUN; license review required  
terms: 0  
exemplars: 0  
holdout queries: 0  
Top1 / Top3 / Top5 / MRR: NOT EVALUATED  
per creator / voice mode effect: NOT EVALUATED

Tests prove TRAIN-only, Creator/profile isolation, speaker-embedding rejection, and
candidate-only output. That is not a successful POC, so no production capability was added.

# 12 Adaptive Holdout

For each Creator: spans 0; generic 0; adaptive 0; same 0; changed 0; high-risk 0;
fallback 0. No TRAIN memory exists for this corpus. Generic ASR remains authoritative.

# 13 Human Ground Truth

For Saruei, anny, atelieranoko, snuffy, and laphipi: samples not yet annotated;
Generic WER `PENDING`; Adaptive WER `PENDING`; CER `PENDING`.

# 14 TS-ASR

collab samples: 0 frozen, speaker-enrolled samples  
provider: BUTSpeechFIT/TS-ASR-Whisper NOT INSTALLED / NOT RUN  
generic: NOT RUN  
adaptive: NOT RUN  
TS-ASR: NOT RUN  
human truth: PENDING  
decision: `NOT_APPLICABLE_UNTIL_FROZEN_COLLAB_MEDIA_AND_ENROLLMENT_EXIST`

# 15 Open-set Safety

Unknown creators: prior Shylily/Zentreya/Ironmouse evidence retained; no new unknown media  
visual false strong: NOT RUN on this five-Creator model  
voice false strong: NOT RUN  
trusted leakage: 0 by invariant/test  
adaptive leakage: 0 by invariant/test

# 16 New Creator Product Smoke

For atelieranoko, snuffy, and laphipi: ASR probe PASS; Moment, Search, Conversation,
Clip, Subtitle, and Render are `NOT_RUN_STORAGE_BLOCKED`. Saruei/anny existing product
regressions remain covered by the suite. No new-Creator product-readiness claim is made.

# 17 Human Review

dataset: `MULTI_CREATOR_TWITCH_V1`, separate `human_review_multi_creator_v1.sqlite`  
old annotations retained: YES; `MERGE_ONLY_NEVER_REPLACE`  
visual: 300  
ASR: 150  
trusted: 150  
adaptive: 0 (no TRAIN memory)  
voice-mode: optional Yes/No/Unsure field available; annotated candidates 0  
total: 600 pending human samples

# 18 Performance

disk: no candidate satisfies reserve; no HDD throughput benchmark is meaningful  
download: 662,034,211 bytes total; duration was not captured, so throughput is not claimed  
visual: 300 accepted crops; training/inference NOT RUN  
voice: NOT RUN  
lexical: NOT RUN  
adaptive: NOT RUN  
ASR: 10-minute probes processed in 63.47s / 48.83s / 57.87s on RTX 4050  
RAM: not instrumented  
VRAM: not instrumented

# 19 Fault Matrix

Storage, locator restart/traversal, VOD leakage, memory-role contamination, active-VOD,
voice-shift/conflict, representation separation, and cross-Creator isolation checks PASS.
See `fault-matrix.md`.

# 20 Existing Regression

Fixed37: PASS through full suite  
Generation: PASS through full suite  
Backend: PASS through full suite  
Product GUI: PASS through full suite and CLI smoke  
Human Review: PASS; old annotations untouched

# 21 Automated Verification

pytest1: 589 passed, 9 warnings  
pytest2: 589 passed, 9 warnings  
verify1: PASS; 589 tests; contracts PASS  
verify2: PASS; 589 tests; contracts PASS  
contracts: PASS ×2  
CGKN: doctor PASS; sealed brief valid (`7cc5897887b14f310e9a002c24486d123a5712ccb4c8d64269565966f566de11`)  
clean checkout: PASS after evidence commit; runtime roots resolve through local config  
skip: 0  
xfail: 0

# 22 CGNK

Corpus: UPDATED with creators, VOD roles, dates, alias, and split hash  
Voice Modes: UPDATED  
Trusted: UPDATED with TRAIN-only / Validation-threshold-only rules  
Lexical Acoustic: research knowledge UPDATED; no capability promoted  
Adaptive: UPDATED with voice-mode and lexical candidate evidence  
TS-ASR: NOT ADDED as production capability; POC not run  
Guards: VOD-level HOLDOUT/UNKNOWN/VALIDATION rules implemented and tested  
Evidence: doctor PASS; CGKN correctly reports formal evidence `NOT_EVALUATED`

# 23 Licenses

3D-Speaker and WeSpeaker code are Apache-2.0. Official WeSpeaker ReDimNet/CAM++ cards
declare Apache-2.0. HuBERT base declares Apache-2.0. WavLM links to a CC BY-SA 3.0
license and remains research-only pending review. 3D-Speaker checkpoint-specific weight
licenses were not independently confirmed, so no weights were downloaded. See
`speaker-model-license-audit.md`.

# 24 Bugs Fixed

- Stopped treating Q as a presumed 2 TB disk and added fail-closed reserve-aware selection.
- Added portable ignored bulk-root mapping and traversal-safe locators.
- Added live owner/type-scoped Twitch public metadata discovery without a second downloader.
- Prevented same-VOD split duplication and TRAIN-memory contamination.
- Corrected VALIDATION semantics: threshold tuning allowed, memory/training forbidden.
- Excluded an active Snuffy recording from every frozen role.
- Replaced single-centroid-only voice matching with optional unnamed sub-centres.
- Prevented a changed unmatched voice from becoming an automatic known-Creator conflict.
- Prevented speaker embeddings and cross-Creator rows from lexical-acoustic retrieval.
- Added optional non-nationality voice-style review input.

# 25 Remaining Problems

- Free at least about 500 GiB on a healthy 2 TB volume, or attach another healthy large
  persistent disk, then rerun corpus acquisition. Current F would need roughly 257 GiB
  more free just to satisfy the current estimate and reserve, with more headroom preferred.
- Full VOD media, chat, five-Creator visual training, speaker A/B, real voice modes,
  Trusted Speech, lexicon, HuBERT POC, adaptive holdout, TS-ASR, and new-Creator product
  smoke remain blocked downstream of storage.
- anny exposes only one public archive and cannot support a valid 3-way split.
- Human identity, voice-style, WER/CER, and blind Generic-vs-Adaptive truth remain pending.

# 26 Engineering Status

BULK_MEDIA_STORAGE_READY: NO — `BULK_STORAGE_NOT_AVAILABLE`  
NEW_MULTI_CREATOR_TWITCH_CORPUS_READY: NO — metadata/split ready, media absent  
ATELIERANOKO_CORPUS_READY: NO  
SNUFFY_CORPUS_READY: NO  
LAPHIPI_CORPUS_READY: NO  
FIVE_CREATOR_VISUAL_IDENTITY_READY: NO  
VOICE_MODEL_BENCHMARK_READY: NO  
MULTI_MODE_VOICE_PROFILE_READY: IMPLEMENTED / SYNTHETICALLY VALIDATED; REAL CORPUS NO  
TRUSTED_SPEECH_FUNNEL_READY: CONTRACT READY; REAL FUNNEL NO  
REAL_TRUSTED_SPEECH_MULTI_CREATOR_READY: NO  
CREATOR_LEXICON_MULTI_CREATOR_READY: NO  
LEXICAL_ACOUSTIC_MEMORY_POC_READY: NO  
LEXICAL_ACOUSTIC_MEMORY_PRODUCTION_READY: NO  
ADAPTIVE_ASR_MULTI_CREATOR_SHADOW_READY: NO — no TRAIN memory  
ADAPTIVE_ASR_HUMAN_VALIDATED: NO / PENDING  
ADAPTIVE_ASR_PRODUCTION_READY: NO  
TARGET_SPEAKER_ASR_POC_READY: NO  
OPEN_SET_SAFETY_READY: GUARDS YES; NEW FIVE-CREATOR METRICS NO  
VOICE_SHIFT_SAFETY_READY: YES at contract/unit level; REAL METRICS PENDING  
CGNK_MULTI_CREATOR_ADAPTIVE_READY: YES for implemented contracts/evidence; blocked stages recorded honestly

Overall: `AUTOMATED_SAFE_PREPARATION_COMPLETE_BULK_CORPUS_BLOCKED`. The system cannot yet
answer the final product question for a completely unseen VOD with changed voice style;
that requires the currently unavailable full corpus plus human truth.
