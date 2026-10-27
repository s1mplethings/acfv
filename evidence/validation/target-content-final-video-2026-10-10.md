# 1. Repository

branch: `validation/target-content-final-video`

base: `4b9a709` (`validation/vod-download-final-video`)

implementation head: `8b0f1064334e0b66894ad64b6a171a1bf0edaf6c`

evidence head: recorded after evidence commit

working tree: clean after evidence commit

# 2. Target Material

source: existing user Creator Library; `ACFV_TARGET_TWITCH_VOD_URL` was not set, so a random public VOD was not downloaded

creator: Saruei

VOD / Recording: `121a99a3-affb-4e74-80de-c5fd13ed7c4b`

content type: `vtuber_game_reaction`

language: English

duration: 14,593.237 seconds

authorization: `USER_EXISTING_LIBRARY`

target suitability: `TARGET_PRODUCT_CONTENT`; the newly requested target download remains `TARGET_VOD_REQUIRED`

# 3. Why This Material Fits ACFV

reaction: strong fear, gasp/scream, denial, and post-event discussion

game event: the horror game detects a scream and shows `YOU SCREAMED`

chat: chat overlay is visible in source, but no historical chat artifact is available; `CHAT_UNAVAILABLE`

emotion: clear escalation from caution to panic, failure, denial, and adjustment discussion

setup/payoff: possible presence behind streamer -> flight response -> scare -> failure screen -> dispute and sensitivity question

expected clip opportunities: scare, failed no-scream challenge, denial, game result, microphone-sensitivity discussion

# 4. Download

validation level: target product used real existing Library media; download engineering reused the immutable real-VOD baseline

provider: existing local media for target; Twitch provider regression for engineering baseline

range: source 2601.000–2688.360 seconds; event context was selected from known Library evidence, not mechanical 0–900 seconds

bytes: source 11,214,628,272; selected clean clip 68,495,962; subtitled clip 93,791,469

wall time: `N/A_EXISTING_LIBRARY`; no new target URL was supplied

integrity: source readable; clean and subtitled ffprobe PASS; both full decode scans PASS

source-edge margin: 2601.000 seconds from source start and 11,904.877 seconds from source end; no override

# 5. Processing

ASR: real GPU faster-whisper medium word-timestamp pass on selected preview; 113 words

transcript: 26 ASR segments persisted in `word_transcript.json`

Moments: 443 FINAL moments exist for the target recording; selected event spans two related moments

Index: real multilingual E5 index, 5,226 parent moments / 24,351 representations, version 4

Retrieval: target fixed set Top1 7/16, Top3 10/16, Top5 12/16; immutable 20-query regression Top5 remains 15/20

Conversation: 9/16 gates correct, including No-Evidence 5/5; only 4/11 positive questions return evidence while LLM is unavailable, so target conversation is partial rather than PASS

# 6. Candidate Generation

candidate count: 3, generated from retrieval Top 10 and independently preview-rendered

Candidate 1:

type: `MOST_RELEVANT`

query: `There is something behind me, did Saruei scream?`

start/end: 2619.000 / 2672.360 seconds

scores: retrieval rank 1; watchability 0.6925; relevance 1.0; hook 0.2; reaction 1.0; source-edge penalty 0

preview: `candidate_01_preview.mp4`

Candidate 2:

type: `MOST_COMPLETE`

query: `There is something behind me, did Saruei scream?`

start/end: 2601.000 / 2688.360 seconds

scores: retrieval rank 1; watchability 0.8095; relevance 1.0; hook 1.0; reaction 1.0; context 1.0; source-edge penalty 0

preview: `candidate_02_preview.mp4`

Candidate 3:

type: `MOST_WATCHABLE`

query: `There is something behind me, did Saruei scream?`

start/end: 2660.360 / 2729.560 seconds

scores: retrieval rank 2; watchability 0.7620; relevance 0.8889; hook 1.0; reaction 1.0; source-edge penalty 0

preview: `candidate_03_preview.mp4`

# 7. Final Selection

selected candidate: `candidate_02` / `MOST_COMPLETE`

selection reason: highest watchability score, complete setup-to-result-to-reaction arc, complete sentences, sufficient context, and no source-edge risk

why not Top1-only: candidate boundaries are generated and ranked after retrieval; candidate 02 expands the rank-1 evidence from 53.36 seconds to 87.36 seconds and wins on narrative completeness rather than retrieval score alone

hook: streamer immediately describes fear and the urge to run

setup: establishes that something may be behind her during the no-scream challenge

payoff: the game declares `YOU SCREAMED`, followed by denial and a sensitivity question

reaction: strong panic/gasp followed by argumentative recovery

context: self-contained causal sequence

source-edge: PASS; margins exceed 10/20-second guard by hours

# 8. Subtitle

timing source: faster-whisper medium word timestamps

word-level: YES; 113 real word timestamps, no character-proportional timing fallback

cue count: 27

average duration: 1.602 seconds; maximum 3.160 seconds

max lines: 2

font: Arial

size: 40px at 1280×720 design resolution

position: top caption, 50px safe-area margin to avoid bottom HUD/avatar

visual previews: `subtitle_preview_start.jpg`, `subtitle_preview_middle.jpg`, `subtitle_preview_end.jpg`; all inspected and readable

# 9. Final Video

subtitled MP4: `outputs/target-content-validation/121a99a3-affb-4e74-80de-c5fd13ed7c4b/final_clip_subtitled.mp4`

clean MP4: `outputs/target-content-validation/121a99a3-affb-4e74-80de-c5fd13ed7c4b/final_clip_clean.mp4`

ASS: `final_clip.ass`

SRT: `final_clip.srt`

manifest: `final_clip_manifest.json`

review: `final_clip_review.json`

duration: subtitled 87.383333 seconds; clean 87.432 seconds

resolution: 1920×1080

codec: H.264 video / AAC stereo 48kHz audio / yuv420p

file size: 93,791,469 bytes subtitled; 68,495,962 bytes clean

SHA-256: subtitled `309B4FC3BE19D4529863F18D6D460D8EAE1DCE9FC2A009CD2DBC43802B8BFE8A`; clean `EAB12AEDFD8DEA15C088A689BD6D114D64B7F55555689850F0D23381C4AB97B3`

# 10. Product Quality

query match: PASS

self-contained: PASS

hook: GOOD

setup: GOOD

payoff: GOOD

reaction: GOOD

boundary: NO_EDIT by automatic structural checks; human confirmation pending

subtitle sync: GOOD in start/middle/end sampled review

subtitle visual: GOOD; 40px, two-line cap, safe top placement

watchability: PASS at clip level, score 0.8095

# 11. Automatic Verdict

`AUTO_PASS`

reasons: the selected real-media clip is query-matched, structurally complete, far from source edges, decodes cleanly, contains an observable game result and reaction, and has readable word-timed subtitles. This is a clip verdict, not a claim that all target retrieval/conversation queries pass.

# 12. Human Review

worksheet path: `outputs/target-content-validation/121a99a3-affb-4e74-80de-c5fd13ed7c4b/final-human-video-review.md`

status: `PENDING / HUMAN_REQUIRED`; native GUI visual interaction was not claimed as automated

# 13. Download Engineering Regression

URL: PASS in preserved Q8Pilot real-VOD baseline; no new target URL supplied (`TARGET_VOD_REQUIRED`)

resume: PASS

duplicate: PASS, including concurrent duplicate protection

media: PASS, including ffprobe and decode

Library: PASS, including registration and restart persistence

pipeline: PASS, canonical handoff retained; previous evidence was not overwritten

# 14. Full Regression

compileall: PASS twice after final implementation change

CLI: main, gui, pipe clip, live, and download help PASS twice

pytest #1: 337 passed, 11 warnings

pytest #2: 337 passed, 11 warnings

coverage: 86% across the changed product modules, with 337 passed

verify: PASS twice; each verify independently ran another 337 tests

contracts: PASS twice; CGNK repository guard targeted check 8 passed

# 15. Bugs Fixed

| ID | Severity | Observed Failure | Root Cause | General Fix | Regression | Commit |
|---|---|---|---|---|---|---|
| TC-01 | High | Retrieval Top-1 could become the final clip without editorial comparison | Retrieval relevance and edit quality were conflated | Added Top10 eligibility, three candidate intents, watchability features, preview selection | candidate diversity/ranking/source-edge unit tests | `cfe015a` |
| TC-02 | High | Clip could be deliverable too close to source boundaries | Render service lacked a formal source-edge gate | Added 10s start / 20s end guard and explicit override contract | source-edge rejection tests | `cfe015a` |
| TC-03 | High | Long ASR segments could produce mechanical or overlong captions | Subtitle path did not preserve/use word timings end-to-end | Preserved word timestamps and grouped by pause, punctuation, line, and 4s cap | word grouping and clip-offset tests | `cfe015a` |
| TC-04 | Medium | ASS fonts rendered disproportionately large because play resolution was missing | Renderer scaled style against implicit ASS resolution | Declared 1280×720 play resolution and tuned 34–44px presets/safe margins | subtitle contract/generator tests plus screenshots | `cfe015a` |
| TC-05 | High | Cross-encoder reranking could erase stronger multilingual fusion recall | Reranker score fully replaced fusion order | Blended fusion rank 70% and reranker rank 30% | retrieval representation tests and fixed-set rerun | `cfe015a` |
| TC-06 | Medium | New capability failed repository guard/spec completeness | Registry fixture and required spec headings were absent | Registered capability and completed implementation/effects contract | CGNK guard 8 passed | `f991889`, `8b0f106` |

# 16. Comparison to Previous Test

Previous material: Q8Pilot flight-simulation technical explanation, retained as `DOWNLOAD_ENGINEERING_BASELINE`

Previous clip: FMS / route-entry instructional passage

Problems: valid engineering sample but weak proxy for VTuber reaction watchability; relevance and information density dominated; product storytelling was not demonstrated

New material: Saruei VTuber horror-game reaction from the user's real Library

New clip: 87.36-second scare/failure/denial sequence with word-timed burned subtitles

Improvements: target-aligned source, three candidate previews, explicit watchability ranking, complete narrative boundary, large source-edge margin, visual subtitle review, and separate clip/product-system verdicts

# 17. Remaining Problems

- Target-content retrieval is 12/16 at Top5. Broad paraphrases about the game result, denial, and microphone sensitivity still miss or rank too low.
- Target-content conversation is only 9/16 by evidence gate; with the LLM unavailable, only 4/11 positive questions return evidence. No-Evidence behavior is correctly 5/5.
- Historical chat was visible in the source overlay but no aligned chat artifact exists, so chat-spike scoring could not be validated.
- Automated visual feature fields were empty; screenshots support the event, but triggered scene/OCR/VLM quality was not independently measured.
- Human playback/review and native GUI visual interaction remain `HUMAN_REQUIRED`.
- The target material came from the user's existing Library. A newly supplied `ACFV_TARGET_TWITCH_VOD_URL` is still required to repeat download and target-product evaluation on the exact same new source.

# 18. Engineering Status

DOWNLOAD_ENGINEERING_READY: YES

TARGET_CONTENT_PIPELINE_READY: NO — real target media completes the pipeline, but target retrieval/conversation recall is below a full readiness claim

WATCHABILITY_SELECTION_READY: YES

SUBTITLE_PRESENTATION_READY: YES

FINAL_TARGET_VIDEO_READY: NO — the produced clip itself is `AUTO_PASS`, but strict system readiness is withheld because Grounded Conversation and target fixed-set recall are not fully passing, and human review is pending
