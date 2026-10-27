# 1. Repository

branch: `fix/language-quality-calibration`  
base: requested `ae63f6f7f80e363f15f49fb78b871d9ea028455a`; unavailable in recovered object store, so the auditable available parent is `753add2`  
implementation: `291df397428afb06942d4080b049e63808a08337`  
evidence: evidence commit containing this report (final hash recorded in delivery)  
working tree: clean after evidence commit  
GUI changes: 0

# 2. Root Cause

Correction: empty or unsafe refiner output was conflated with a critical review decision. Local decode presence was not converted into validated independent evidence.  
Release Gate: issue-presence booleans and correction state acted as broad blockers instead of weighting semantic importance, position, and evidence.  
Entity Guard: capitalization heuristics made ordinary tokens Critical; no evidence-backed entity taxonomy existed.  
Broken Sentence: an abrupt prefix/suffix regex classified conversational fragments and complete short reactions as broken.  
Translation Guard: objective semantic failures, style warnings, terminology, and structural issues shared an underspecified `critical` boolean.

# 3. Fixed Sets

Low-confidence words: 22, unchanged sample identities  
Local re-decodes: 29, unchanged sample identities  
Entity findings: 25, unchanged pre-calibration findings  
Mutation cases: 30 (10 Critical / 10 Warning / 10 Harmless)

# 4. Correction Results

AUTO_CORRECTED: 0  
UNCHANGED_CONFIDENT: 8  
UNCHANGED_UNCERTAIN: 14  
NEEDS_REVIEW: 0 word-level decisions

There are no AUTO_CORRECTED rows to enumerate. Of 29 local decodes, 8 support the raw wording, 21 are inconclusive, 4 are empty, only 5 are exact full-window matches, 6 recur as the same phrase, and 0 have glossary agreement. Historical local-decode artifacts also omit probability/logprob deltas. Therefore no candidate has the two independently validated evidence classes required for a lexical replacement. Raw text is preserved.

# 5. Entity Calibration

Before findings: 25  
True entities: 1 evidence-backed game term  
Unknown capitalized: 22  
After critical: 1  
False positives removed: 24 Critical decisions (22 downgraded to Warning, 2 removed)

# 6. Broken Sentence Calibration

Before: 30  
True broken: 3  
Interrupted: 1  
Reaction: 0 among the frozen 30 suspects  
Valid fragment: 25  
After: 4 blocking-quality suspects (3 TRUE_BROKEN + 1 ASR_ERROR)

# 7. Translation Guards

Negation: 2, both remain Critical  
Numbers: 3, semantic-equivalence support added for English/Chinese number words  
Entities: 26 findings in the complete re-run; one evidence-backed game entity is Critical, capitalization-only findings are Warning  
Profanity: 10 Warning; adjacent and non-extreme strength changes do not become Critical  
Source-copy: 1 High structural issue; supported acronym/UI/proper-name copies are allowed

Critical: 6  
Warning: 36  
Style: 36

# 8. Release States

Before:

READY 0  
WARNING 0  
NEEDS_REVIEW 12

After:

READY: 0  
WARNING: 8 (`READY_WITH_WARNINGS`)  
NEEDS_REVIEW: 4

| Clip | Risk Score | Critical Issues | Warnings | State |
|---|---:|---:|---:|---|
| anny-01-5a9caed4 | 4.5000 | 0 | 8 | READY_WITH_WARNINGS |
| anny-02-0861efd7 | 10.3500 | 0 | 34 | NEEDS_REVIEW |
| anny-03-5f5dd861 | 8.6500 | 3 | 3 | NEEDS_REVIEW |
| anny-04-3ad97744 | 3.2000 | 0 | 6 | READY_WITH_WARNINGS |
| anny-05-877e635c | 0.4500 | 0 | 1 | READY_WITH_WARNINGS |
| Q8Pilot-01-e74cab24 | 4.9500 | 1 | 3 | NEEDS_REVIEW |
| Q8Pilot-02-7c47cf07 | 9.1000 | 2 | 6 | NEEDS_REVIEW |
| Saruei-01-8d310288 | 2.7908 | 0 | 5 | READY_WITH_WARNINGS |
| Saruei-02-0c6e3e2a | 7.2502 | 0 | 16 | READY_WITH_WARNINGS |
| Saruei-03-0e04994c | 7.8500 | 0 | 9 | READY_WITH_WARNINGS |
| twitchplayspokemon-01-e1aca6c6 | 0.4500 | 0 | 1 | READY_WITH_WARNINGS |
| twitchplayspokemon-02-63c106bf | 3.1500 | 0 | 7 | READY_WITH_WARNINGS |

`anny-02` is blocked by aggregate multi-type risk rather than a single Critical issue. Every issue, timestamp, evidence payload, contribution, and action is in `language-risk-report.json`.

# 9. Mutation Test

Critical: 10/10 blocked  
Recall: 100%  
Warning: 10/10 non-Critical  
Classification: 100%  
Harmless: 10  
False Critical: 0

# 10. Content Types

Reaction: 3 Clips; low confidence 4; corrections 0; warnings 14; critical 0; 3 Warning  
Chatting: 3 Clips; low confidence 8; corrections 0; warnings 25; critical 3; 2 Warning / 1 Needs Review  
Collab: 3 Clips; low confidence 10; corrections 0; warnings 49; critical 2; 1 Warning / 2 Needs Review  
Simulation: 3 Clips; low confidence 0; corrections 0; warnings 11; critical 1; 2 Warning / 1 Needs Review

# 11. Performance

ASR: historical median 13.007s; no ASR re-run and no model change  
Correction: historical median 16.606s; no added model call  
Guards: deterministic 12-Clip evidence pass approximately 0.05s excluding JSON/process startup  
Translation: historical median 36.418s; prompt/provider path unchanged  
Total: historical median 79.361s plus deterministic guards

Before / After: measured architecture adds no model, decode, translation, or audio stage; deterministic guard overhead is far below 20%.

# 12. Existing Regression

Duration: PASS; duration owner unchanged  
Retrieval: preserved prior Overall 27/30, Fixed 17/20, No-Evidence 12/12; architecture unchanged and full regression PASS  
Conversation: PASS  
Moment: PASS  
Download: PASS; CLI smoke PASS  
Live: PASS; CLI smoke PASS  
Artifact: PASS; contract checks PASS  
Feedback: PASS  
Final ASR: PASS; large-v3 path unchanged  
Translation: PASS; structured contextual provider path unchanged

# 13. Automated Verification

compileall: PASS twice  
CLI: root/gui/pipe clip/live/download PASS twice  
pytest #1: 475 passed  
pytest #2: 475 passed  
coverage: 84% focused changed-owner coverage (refinement 86%, subtitles 83%)  
verify: PASS twice; its internal pytest also 475 passed each time  
contracts: PASS twice  
skip/xfail: 0 / 0

# 14. Bugs Fixed

| ID | Severity | Observed | Root Cause | Fix | Regression | Commit |
|---|---|---|---|---|---|---|
| LQC-01 | High | no safe edit still blocked every Clip | correction states conflated | four-state decision and validated evidence | correction tests | 291df39 |
| LQC-02 | High | ordinary capitalization was Critical | capitalization-only entity heuristic | six entity types and evidence-aware severity | entity + mutation tests | 291df39 |
| LQC-03 | High | oral fragments marked broken | abrupt regex | five-class speech-form classifier | broken-sentence tests | 291df39 |
| LQC-04 | High | any finding could block a Clip | boolean gate | capped correlated risks + max/aggregate/hard blockers | release tests | 291df39 |
| LQC-05 | Critical | style and polarity shared weak categories | untyped guards | categorized issue records and hard blockers | 30 mutations | 291df39 |
| LQC-06 | High | `three → 三` mismatched; `no one` looked numeric | number token normalization | bilingual number equivalence and pronoun exclusion | number-equivalence test | 291df39 |

# 15. Review Pack

path: `C:\Users\sunom\.codex\deliverables\language-quality-calibration-review-pack.zip`  
size: 46,600,617 bytes (44.44 MiB)  
SHA256: `553DF580FD60CE404F69C8912098A15741F7E22BF725417612D7ACC827A06987`  
clips: 12  
issues: all calibrated per-Clip issues plus raw/final/corrected transcript, word confidence, original event audio, and 480p bilingual video proxy

# 16. Remaining Problems

- Human language review is still pending; automated guards intentionally do not judge humour, naturalness, or publishability.
- The 29 archived local re-decodes do not persist confidence deltas, so none can justify AUTO_CORRECTED under the new safety rule.
- `anny-02` has no single Critical issue but exceeds aggregate multi-type risk and remains in the manual queue.
- The requested base commit object is absent from the recovered repository; ancestry honestly starts from available snapshot `753add2`.
- G remains offline. The pack therefore contains the frozen original event audio plus the available final bilingual video proxy, not a separately recovered clean source-video file.

# 17. Engineering Status

EVIDENCE_BACKED_CORRECTION_READY: YES  
ENTITY_GUARD_CALIBRATED: YES  
BROKEN_SENTENCE_GUARD_CALIBRATED: YES  
TRANSLATION_GUARD_CALIBRATED: YES  
RISK_BASED_RELEASE_GATE_READY: YES  
LANGUAGE_GATE_FALSE_POSITIVE_REDUCED: YES  
CRITICAL_SEMANTIC_ERROR_GUARD_READY: YES  
FINAL_LANGUAGE_OUTPUT_ENGINEERING_READY: YES  
HUMAN_LANGUAGE_REVIEW_PENDING: YES
