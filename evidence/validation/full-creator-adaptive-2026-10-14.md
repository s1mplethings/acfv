# 1 Repository

branch: `feature/creator-visual-identity-full`  
base: `959369cdac26c7853df583c36a7cfc9d0754c668`  
implementation: `e880467`, `0f11fc5`  
evidence: `c262b8b`  
working tree: clean after final report commit

# 2 Presence Detector

model: external YOLO11l `G:/Cliper/acfv/model/best.pt`  
hash: `48d0f7058739ec1f7baaa6ed58d9192130e9caa377be1dad238ba7288d4f1580`  
task: single-class object detection  
classes: `{0: vtuber}`  
performance: Saruei 492/500, anny 500/500, 38.9–45.5 fps historical validation  
role: `AVATAR_PRESENCE_DETECTOR`, never Creator identity

# 3 Visual Dataset

Creators: Saruei, anny  
Recordings: 12 total (8 known, 4 local authorized unknown/challenge)  
Train crops: 600 (Saruei 97, anny 503)  
Validation crops: 309 (Saruei 187, anny 122)  
Holdout crops: 485 (Saruei 214, anny 271)  
Unknown crops: 51  
Dedup: time spacing plus dHash; 2,891 near-duplicates rejected  
Contamination suspects: 551 non-single-dominant and 8 invalid-quality samples rejected; no recording leakage  
Dataset hash: `524738ad39c9625d533fb80974e457ab1eed3aa1257dd05ff2a697f4762f4cf8`

# 4 Candidate A — DINO

model: frozen DINOv2-small  
embedding dim: 384  
prototypes: multi-prototype/medoid  
Top1: 0.7402  
Strong precision: 0.7372  
Strong coverage: 0.7402  
Unknown rejection: 0.92  
Latency: 14.47 ms/crop (69.12 fps)  
VRAM: 670.57 MB peak

# 5 Candidate B — OpenCLIP

model: frozen OpenCLIP ViT-B/32 image encoder  
embedding dim: 512  
prototypes: multi-prototype/medoid  
Top1: 0.7031  
Strong precision: 0.6875  
Strong coverage: 0.7031  
Unknown rejection: 0.56  
Latency: 12.42 ms/crop (80.50 fps)  
VRAM: 569.63 MB peak

# 6 Candidate C — Classifier

architecture: frozen torchvision ResNet18 ImageNet-v1 + linear head + support-centroid open-set rejection  
train: 600 known crops, recording isolated  
validation: 309 known plus 26 unknown calibration items  
holdout: Top1 0.9753; production STRONG precision 1.0; coverage 0.7464  
open-set: 25/25 unknown rejected; minimum support 0.7738778  
latency: 8.17 ms/crop (122.47 fps benchmark)  
VRAM: 685.88 MB peak

# 7 Selection

winner: ResNet18 linear probe  
reason: highest safety-ordered STRONG precision, unknown rejection, holdout generalization, and fastest measured encoder  
rejected: DINOv2 and OpenCLIP as production winners  
tradeoffs: conservative margin lowers Saruei strong coverage to protect memory precision; no ensemble cost

# 8 Production Visual Identity

model version: `creator_visual_identity_v1` / `torchvision:resnet18:f37072fd47e8-linear-probe-v1`  
Creator prototypes/classes: Saruei and anny  
Strong threshold: score 0.45, margin 0.20, support 0.7738778  
Unknown: first-class reject state  
Ambiguous: no Creator selection and generic fallback  
temporal aggregation: weighted multi-frame spans with support, duration, coverage, conflicts, and provenance

# 9 Real Holdout

Saruei: 500 independent raw frames; 246 STRONG, 246 proxy-correct, 0 false, coverage 0.492  
anny: 500 independent raw frames; 500 STRONG, 500 proxy-correct, 0 false, coverage 1.0  
Unknown: benchmark challenge rejection 1.0 (25/25 production holdout)  
Confusion: production holdout STRONG Saruei 91 correct/0 false, anny 271 correct/0 false, unknown 25 reject  
Strong false identity: 0 in production holdout and independent raw proxy validation. Human per-frame truth remains NOT_EVALUATED.

# 10 Visual Identity Spans

Creator: Saruei — 14 spans, 575,600 ms, 10 strong, 0 probable, 0 ambiguous, 4 unknown, 0 conflict  
Creator: anny — 1 span, 180,640 ms, 1 strong, 0 probable, 0 ambiguous, 0 unknown, 0 conflict

# 11 Creator Identity Fusion

Confirmed: 33  
Probable: 101  
Unknown: 0 persisted decisions in the strict candidate run  
Conflict: 0 persisted decisions; conflict path is regression-covered  
Voice support: secondary only  
Human: highest authority; no human labels injected

# 12 Voice Profile v3

Saruei: 20 candidates, 13 retained, 61,131 ms, FAR proxy 0, FRR proxy 0, production strong threshold 0.7227  
anny: 46 candidates, 29 retained, 136,260 ms, FAR proxy 0, FRR proxy 0.6296, production strong threshold 0.7898

# 13 Trusted Speech

Saruei: 13 candidates, 1 pseudo trusted, 0 human confirmed, 1,120 ms, 9 rejected, 3 auto-high  
anny: 54 candidates, 4 pseudo trusted, 0 human confirmed, 12,440 ms, 18 rejected, 32 auto-high  
reasons: identity/profile/content/ASR/independent-evidence gates are retained in v3 run evidence

# 14 Lexicon

Saruei: 3 candidates, 0 promoted  
anny: 6 candidates, 0 promoted  
names/games/characters/catchphrases/technical terms: none promoted because no term repeated across independently trusted units; ordinary stopwords/short words are filtered

# 15 Acoustic Exemplars

count: 0  
terms: none  
duration: 0  
provenance: gate is implemented, scoped, immutable, and intentionally produced no unsafe exemplar

# 16 Adaptive ASR Shadow

Creator: Saruei 13 items; anny 20 items  
eligible: 33  
same/unchanged uncertain: 23  
changed: 0 official changes  
generic preferred: 1 KEEP  
adaptive candidate: 9 REVIEW  
conflict: generic fallback regression-covered  
fallback: generic transcript remains authoritative

# 17 Human Ground Truth

samples: NOT_EVALUATED  
Generic WER: NOT_EVALUATED  
Adaptive WER: NOT_EVALUATED  
high-risk categories: identity STRONG/uncertain, trusted speech, and adaptive A/B items are queued in Human Review v4

# 18 Adaptive Human Review

A/B items: 33  
completed: 0  
Generic wins: NOT_EVALUATED  
Adaptive wins: NOT_EVALUATED  
Same: NOT_EVALUATED  
Both wrong: NOT_EVALUATED

# 19 Creator Recommendation

Saruei: KEEP_SHADOW  
anny: KEEP_SHADOW

# 20 Human Review v4

old retained: yes, merge migration preserves prior samples/annotations  
Visual Identity: 150 items  
Trusted: 63 items  
Adaptive: 33 blind A/B items  
persistence: SQLite autosave/revision/restart preserved  
analysis: existing analysis plus task progress; production metrics await human completion

# 21 Product GUI

Profile: `creator_profile_v3` surfaced through canonical backend  
status: visual READY when versioned classifier is present; adaptive SHADOW  
jobs: existing job ownership unchanged  
regression: Product GUI suites included in 572-test passes; no redesign

# 22 Performance

YOLO: 49.20 fps Saruei / 59.65 fps anny in independent run  
Identity: 322.98 fps Saruei / 116.30 fps anny in independent run; 122.47 fps benchmark  
Combined: 42.70 fps Saruei / 39.43 fps anny serial estimate  
Voice: 66 candidate segments processed across 8 recordings  
Memory: 9,556-byte linear head; 1.57 MB manifest; encoder weights external  
Adaptive: 33 shadow items  
RAM: 2,985.59 MB process reading during combined real validation  
VRAM: 1,942.48 MB peak combined real validation; stages are sequenced for 6 GB devices

# 23 Safety

Raw media mutation: 0  
Transcript mutation: 0  
Poisoning: strict independent-evidence and trusted-only gates  
Cross creator: scoped repository/profile versions and regression guards  
Unknown: allowed and preferred over false STRONG  
Conflict fallback: generic ASR  
Profile version: v3 isolated; v1/v2 preserved

# 24 CGNK

Capabilities: `creator_visual_identity` added with one canonical owner  
Contracts: creator-visual-identity contract added  
Knowledge: detector role, benchmark, winner, rejection policy recorded  
Registry: synchronized  
Guards: raw `vtuber` mapping, split leakage, hash integrity, unknown/trust boundaries covered  
Evidence: complete promoted JSON set  
Status: doctor PASS; advisory brief valid; formal evidence NOT_EVALUATED

# 25 Existing Regression

Fixed37: PASS  
Generation Quality: PASS  
Creator Adaptive: PASS  
Backend: PASS  
Product GUI: PASS  
Human Review: PASS

# 26 Automated Verification

pytest1: 572 passed  
pytest2: 572 passed  
verify1: PASS (572 passed + contracts PASS)  
verify2: PASS (572 passed + contracts PASS)  
contracts: PASS twice  
CGNK: doctor PASS / formal evidence NOT_EVALUATED  
clean checkout: PASS at detached `c262b8b`  
skip: 0  
xfail: 0

# 27 Bugs Fixed

| ID | Severity | Observed | Root Cause | Fix | Regression | Commit |
|---|---|---|---|---|---|---|
| CVI-01 | Critical | raw `vtuber` could not identify Creator | presence and identity were conflated | separate open-set crop classifier/provider | raw-label guard | `e880467` |
| CVI-02 | High | softmax was overconfident on unknowns | no support-distance rejection | add support centroid and fail-closed thresholds | unknown challenge tests | `e880467` |
| CVI-03 | High | early raw Saruei region had low-margin false STRONG | margin 0.12 too permissive | calibrate production margin to 0.20 | 1,000-frame real proxy validation | `e880467` |
| CAD-01 | High | borderline ASR could self-confirm | insufficient independent evidence | require two agreeing independent decodes | trusted speech test | `e880467` |
| CAD-02 | Medium | ordinary short words entered lexicon candidates | bootstrap lacked generic-word filter | stopword and minimum-length gate | full v3 run | `e880467` |
| HR-01 | Medium | Review Lab only auto-found v2 | dataset discovery was version-specific | v4-first discovery with v2 fallback and merge | v4 persistence test | `e880467` |
| ART-01 | High | model config depended on ignored runtime path | classifier lived under `var/` | track 9.3 KB versioned head with SHA-256 verification | clean load test | `e880467` |

# 28 Remaining Problems

- The 150-frame visual review set has not been human-labelled, so reported real-frame precision is proxy evidence, not human GT.
- Adaptive Generic/Adaptive WER and per-Creator production gates remain NOT_EVALUATED.
- Saruei visual STRONG coverage is deliberately conservative (0.492 independent raw run).
- anny voice FRR proxy is high (0.6296); voice remains support-only.
- No lexicon or acoustic exemplar passed the strict repeat/trust gate in this bounded run.
- Dataset volume is below suggested targets for Saruei; no duplicate data was manufactured.

# 29 Engineering Status

AVATAR_PRESENCE_DETECTOR_READY: YES  
CREATOR_VISUAL_DATASET_READY: YES  
CREATOR_VISUAL_IDENTITY_MODEL_READY: YES  
VISUAL_OPEN_SET_REJECTION_READY: YES  
VISUAL_IDENTITY_REAL_VALIDATED: YES (proxy), HUMAN_REQUIRED for production precision  
CREATOR_IDENTITY_FUSION_READY: YES  
VOICE_PROFILE_V3_READY: YES  
TRUSTED_SPEECH_BOOTSTRAP_READY: YES  
REAL_TRUSTED_SPEECH_AVAILABLE: YES  
CREATOR_LEXICON_READY: YES  
REAL_CREATOR_LEXICON_AVAILABLE: NO (strict gate produced zero promotions)  
ACOUSTIC_EXEMPLAR_MEMORY_READY: YES  
CREATOR_ADAPTIVE_ASR_SHADOW_READY: YES  
REAL_ADAPTIVE_SHADOW_RESULTS_AVAILABLE: YES  
CREATOR_ADAPTIVE_ASR_PRODUCTION_READY: NO  
VISUAL_IDENTITY_REVIEW_GUI_READY: YES  
TRUSTED_SPEECH_REVIEW_GUI_READY: YES  
ADAPTIVE_ASR_REVIEW_GUI_READY: YES  
GENERIC_ASR_FALLBACK_READY: YES  
CROSS_CREATOR_ISOLATION_READY: YES  
POISONING_PROTECTION_READY: YES  
PROFILE_VERSIONING_READY: YES  
CGNK_CREATOR_VISUAL_IDENTITY_READY: YES  
CGNK_CREATOR_ADAPTIVE_ARCHITECTURE_READY: YES  
CREATOR_ADAPTER_TRAINING_READY: NO  
CREATOR_ADAPTER_TRAINING_IMPLEMENTED: NO
