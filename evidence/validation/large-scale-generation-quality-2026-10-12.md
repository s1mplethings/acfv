# 1. Repository

branch: `validation/large-scale-generation-quality`  
base: `73ea9170896c796ebd33bcdebe5f95c44c7c0a3c`  
implementation: `2f773ee`  
evidence: `F:\ACFV-Derived\acfv-large-scale-generation-quality` and the review-bundle receipt  
working tree: clean after the evidence commit; nothing pushed or merged

# 2. Corpus

Creators: 2 (`anny`, `Saruei`), below the requested 4 because no other authorized raw recordings were available.  
Recordings: 8 distinct real derived validation ranges.  
Hours sampled: 1.337 hours (eight approximately ten-minute ranges).  
Content types: celebration, chatting, collab, gaming, horror, reaction, simulation.  
Audio conditions: real VAD variation and examples of dense speech, sparse speech, reactions, game overlap and multi-person content were exercised. The Library does not contain trustworthy per-event labels for every requested acoustic condition, so whisper/music/scream/quiet cross-condition rates are not claimed.

# 3. Events

Unique: 37 (the frozen 32 plus five additive events; no failed frozen event was removed).  
By creator: anny 20; Saruei 17.  
By content: celebration 4; chatting 10; collab 6; gaming 3; horror 4; reaction 5; simulation 5.  
Discovery source: retrieval 7; conversation evidence 7; Moment 8; watchability top 5; random stratified 5; additive random stratified 5.

# 4. Candidates

Relevant: 37.  
Complete: 37.  
Watchable: 37.  
Duplicates: 0 duplicated candidate identities; 111 attempts total, 69 eligible and 42 `NOT_AVAILABLE`.

# 5. Final Outputs

STANDARD: 28.  
SHORT: 16.  
LONG: 11.  
FULL: 13.  
Total MP4: 68; all 68 passed ffprobe and full decode.

# 6. Duration

min: 17.58 s.  
median: 67.65 s.  
P90: 68.247 s.  
max: 70.65 s.  
stddev: 15.786 s.  
distribution: `<20` 2; `20–30` 1; `30–45` 1; `45–60` 3; `60–75` 21; `75–90` 0; `90+` 0.  
concentration: 71.43% in a ±5 s window, therefore `AUTO_SUSPECT_DURATION_CONCENTRATION`.

# 7. Boundary Quality

Start suspects: 2 discourse-connector auto-suspects; objective word cutoffs 0.  
End suspects: 50 punctuation-only auto-suspects; these are not promoted to critical findings.  
Incomplete: 0 objective word-timestamp cutoffs.  
Overextended: 2 cross-event near-duplicate pairs require human review.  
Mid-sentence: 0 objective word-timestamp cutoffs.  
By content type: every rendered content category had zero objective word crossings; human setup/payoff/aftermath judgment remains pending.

# 8. Watchability Structural Quality

Reaction: 4 warning / 5 review.  
Chatting: 0 warning / 30 review.  
Collab: 1 warning / 7 review.  
Simulation: 2 warning / 7 review.  
Bias findings: no automatic “interesting/funny” conclusion is made. Chatting is clearly the weakest gate distribution, and two additive events almost exactly overlap existing event windows. `MULTI_CONTENT_GENERATION_READY` is therefore not granted.

# 9. ASR

Words: 3,251 unique-event final-ASR words.  
Low confidence: 431 (13.26%).  
Corrections: 0 invented and 0 accepted auto-corrections.  
Uncertain: 493 words need review; 30 unique final transcripts had unresolved correction decisions.  
By audio condition: unavailable because acoustic-condition labels were not reliably persisted; no fabricated grouping is reported.  
Worst cases: 186 uncertain-identity findings, 19 broken-sentence findings, 19 low-confidence payoff events, 10 unresolved negations and 3 unresolved key numbers. Local re-decodes: 105.

# 10. Translation

Groups: 80 packaged contextual groups.  
Critical: 21 semantic-guard occurrences across rendered variants; 0 were allowed into `READY` or `READY_WITH_WARNINGS`.  
Warnings: runtime logs contained Qwen malformed/missing-field retries; persisted final timelines contain 0 structured failures and 0 untranslated cues.  
Tone suspects: not promoted to a human conclusion.  
Literal suspects: not promoted to a human conclusion.  
Entities: 230 automatic mismatch occurrences across profile variants.  
Negation: 8 automatic mismatch occurrences.  
Profanity: 55 automatic strength-mismatch occurrences.  
Terms: 13 number, 11 unexpected-source-copy and 1 question-force mismatch occurrence; consistency review remains human-required.

# 11. Subtitle

Cues: 931.  
Timeline invalid: 0.  
Overlap: 0.  
Out-of-range: 0.  
CPS: maximum English 30.769 and Chinese 107.143; these outliers require human readability review.  
Width: 0 visually clipped cues in automated reports; 68 five-frame contact sheets are packaged.  
Cue-boundary suspects: 50 punctuation-only end suspects; 100 cues are packaged for semantic review.  
Final-cue incomplete: 0 objective word cutoff, but punctuation/readability auto-suspects remain.

# 12. Selection Accuracy

Search-driven: 10/10 target hits, 9/10 Top-1, each linked to a real final STANDARD.  
Conversation-driven: 8/8 grounded and 8/8 cited the target Moment, each linked to a final STANDARD.  
Moment-driven: 8/8 proposals linked to a final STANDARD.  
Query mismatch: 0/28 STANDARD; 1/68 across all profiles (1.47%).

# 13. Duplication

Exact: 0 unexpected cross-event file hashes.  
Near: 2 cross-event temporal-IoU pairs (`0.9999` and `0.9988`) require review.  
Same-event variants: 2 exact SHORT/STANDARD pairs, explicitly classified as expected same-event variants.

# 14. Risk Gate

READY: 0.  
WARNING: 9 (`READY_WITH_WARNINGS`, 13.24%).  
NEEDS_REVIEW: 59 (86.76%).  
By content: celebration 2/2; chatting 0/30; collab 1/7; gaming 0/3; horror 0/5; reaction 4/5; simulation 2/7 (warning/review).  
By creator: anny 3/39; Saruei 6/20 (warning/review). Critical mutation recall was 10/10; warning and harmless false-critical counts were both 0/10; cluster mutations were 10/10.

# 15. Failure Taxonomy

| category | count | severity | root cause |
|---|---:|---|---|
| EVENT_SELECTION | 0 critical | — | real routes matched their selected target |
| UNDER_EXTENDED | 9 baseline STANDARD removals | P1 fixed | sub-15-second semantic fragments were incorrectly promoted |
| OVER_EXTENDED / DUPLICATE | 2 near pairs | P2 | different Moments reconstructed almost identical temporal windows |
| ASR | 493 review words | P2 | low acoustic confidence, identities, negation and numbers |
| TRANSLATION | 21 critical guard occurrences | P2 gated | model output preserved structurally but semantic guards require review |
| SUBTITLE_LAYOUT | 2 extreme CPS maxima | P2 | very short cues produce unreadable instantaneous CPS |
| QUERY_MISMATCH | 0 STANDARD / 1 all-profile | P2 | one non-standard boundary omitted query tokens |
| RISK_GATE | 0 leaked critical into warning/ready | — | gate behaved conservatively |
| RENDER | 0 | — | all 68 decoded |

# 16. Baseline vs Final

| Metric | V1 | Final | Delta |
|---|---:|---:|---:|
| Actual MP4 | 60 | 68 | +8 |
| STANDARD | 32 | 28 | -4, because nine invalid short standards were removed and five long events added |
| STANDARD under 20 s | 11 | 2 | -9 |
| Objective start cutoff | 0 | 0 | 0 |
| Objective end cutoff | 0 | 0 | 0 |
| STANDARD query mismatch | 6.25% | 0% | -6.25 pp |
| Unexpected exact duplicate | 0 | 0 | 0 |
| Timeline invalid | 0 | 0 | 0 |
| Full-decode failure | 0/20 | 0/68 | improved coverage |

# 17. Performance

Generation: candidate-generation baseline wall time was not instrumented; cached repeat is not presented as generation performance.  
ASR: median 9.801 s; P90 70.014 s.  
Translation: median 26.907 s; P90 54.806 s, with one severe malformed-response tail.  
Render: clean median/P90 2.517/4.777 s; bilingual median/P90 22.926/44.720 s.  
Memory: observed Python working set 2.46 GB and private bytes 11.13 GB during batch 1; Ollama working set 5.30 GB during the slow tail.  
VRAM: Windows WDDM returned N/A per process, so no numeric VRAM claim is made.

# 18. Long Batch

clips: events 1–20 ran in one continuous process; 21–36 ran after a deliberate restart; event 37 was additive to meet the STANDARD floor.  
duration: approximately 47 minutes for the first process; the second included a severe local-model tail.  
memory growth: no crash or observed runaway growth; only point snapshots were available, so a precise slope is not claimed.  
failures: 0 render/process failures; Qwen retries were recovered and retained as warnings.  
restart: PASS; events 1–20 were not regenerated and revision checkpoints remained intact.

# 19. Backend Regression

Fresh DB/library isolation, GPU final ASR, Moment, Retrieval, grounded Conversation, semantic Clip, duration profiles, contextual translation, bilingual subtitle, risk, mutation, Review, feedback and restart/recovery all passed automated or real-route checks. The original raw Library and media were not deleted or modified.

# 20. GUI Regression

Library: PASS, real library and recording workspace opened.  
Search: PASS, 20 results and event view opened.  
Conversation: PASS, evidence-only grounded UI displayed 5 evidence cards.  
Review: PASS, 10 clips opened, READY bilingual output edited/accepted in an isolated fixture, and restart persistence passed.  
No GUI redesign was performed.

# 21. Automated Verification

pytest #1: 496 passed, 0 failed.  
pytest #2: 496 passed, 0 failed.  
verify #1: PASS, 496 passed, contract checks PASS.  
verify #2: PASS, 496 passed, contract checks PASS.  
contracts: PASS twice.  
skip: 0 added.  
xfail: 0 added.

# 22. Review Bundle

path: `C:\Users\sunom\.codex\deliverables\acfv-generation-quality-review-bundle.zip`  
size: 215,723,053 bytes (205.73 MiB), under 500 MiB.  
SHA256: `1511276916cc332183d4172d4415bfedbd2e8318d3f24d1fa77e91894b3130b4`  
videos: 68 720p review proxies.  
contact sheets: 68.  
review index: `generation-quality-review-index.md`, plus 100 ASR audio samples, 80 translation groups, reports and mutation receipts.

# 23. Bugs Fixed

| ID | Severity | Observed | Root Cause | Generic Fix | Regression | Commit |
|---|---|---|---|---|---|---|
| GQ-001 | P1 | unrelated 180 s fallback outranked real highlights | fallback score used duration seconds against normalized semantic scores | neutral fallback score `0.0` | semantic merge regression | `2f773ee` |
| GQ-002 | P1 | 2–14 s fragments became STANDARD finals | no semantic viability floor | sub-15-second final profiles return `NOT_AVAILABLE` | duration profile regression | `2f773ee` |
| GQ-003 | P1 regression | final-profile floor blocked review proposals | proposal and publishable-final semantics were conflated | keep short items as `REVIEW_PROPOSAL`, never READY final | ClipService + full suite | `2f773ee` |

# 24. Remaining Quality Problems

- Only 2 creators were available, so 4-creator generalization is unproven.
- STANDARD duration remains concentrated: 71.43% within ±5 seconds.
- Two different-event outputs have temporal IoU above 0.99.
- ASR has a 13.26% low-confidence word rate and 493 words requiring review.
- Chatting is 30/30 `NEEDS_REVIEW`; no content category achieved an unqualified `READY` output.
- Qwen produced malformed/missing-field responses on several long events before retry recovery.
- CPS outliers (English 30.769, Chinese 107.143) require human subtitle readability review.
- Acoustic-condition, humor, natural-Chinese and publishability judgments remain human work.

# 25. Engineering Status

LARGE_SCALE_GENERATION_VALIDATED: NO — structural stress data is complete, but 4-creator coverage was not available.  
MULTI_CONTENT_GENERATION_READY: NO — chatting and several other content gates are materially weaker.  
SEMANTIC_BOUNDARY_QUALITY_READY: YES_FOR_OBJECTIVE_WORD_CUTOFFS; HUMAN_SETUP_PAYOFF_REVIEW_PENDING.  
DURATION_ADAPTIVITY_READY: NO — 71.43% concentration is an auto-suspect.  
FINAL_ASR_GENERATION_READY: YES_WITH_WARNINGS.  
CONTEXTUAL_TRANSLATION_ENGINEERING_READY: YES_WITH_WARNINGS; all critical guard hits were gated.  
BILINGUAL_SUBTITLE_GENERATION_READY: NO_FOR_READABILITY; structural timeline integrity passed.  
WATCHABILITY_STRUCTURAL_READY: NO.  
QUALITY_GATE_READY: YES.  
LONG_BATCH_STABILITY_READY: YES.

HUMAN_WATCHABILITY_REVIEW_PENDING: YES.  
HUMAN_TRANSLATION_REVIEW_PENDING: YES.  
HUMAN_PUBLISHABILITY_REVIEW_PENDING: YES.
