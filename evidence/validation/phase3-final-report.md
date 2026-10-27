# ACFV Real Avatar Model Integration — Final Report

## 1 Repository

- Branch: `feature/real-avatar-model-integration`
- Base: `4f97d4fc05fd8f001331accf9345a2bfd4ab543c`
- Implementation: `5368adce048e7c971dbd906f3fd8aa58c45b48aa`
- Evidence: this report's commit
- Working tree: clean after evidence commit

## 2 model/ Audit

`G:/Cliper/acfv/model` contains one file, `best.pt` (51,176,658 bytes, SHA-256 `48d0f7058739ec1f7baaa6ed58d9192130e9caa377be1dad238ba7288d4f1580`). A byte-identical duplicate exists under `G:/Cliper/acfv/artifacts/secrets`. Training, annotation, frame extraction, and historical inference code were recovered from `G:/Cliper/yolo_funcs`. The checkpoint's embedded training arguments are authoritative over the older root `config.json`.

## 3 Avatar Model Design

- Framework/architecture: Ultralytics 8.3.53, PyTorch, YOLO11l detection, P3/P4/P5 head.
- Input/preprocess: 3-channel OpenCV BGR frame; native Ultralytics letterbox/scale at 640.
- Output/classes: boxes, confidence, class id; exactly `0 -> vtuber`.
- Training: pretrained YOLO11l, 100 epochs, batch 16, CUDA, AMP, automatic optimizer, deterministic seed 0.
- Dataset: YOLO images/labels and generated train/validation `data.yaml`.
- Augmentation/loss: embedded standard HSV, translation, scale, flip, mosaic; box/class/DFL weights 7.5/0.5/1.5.
- Metrics: unavailable; no values were invented.
- Checkpoint: normal Ultralytics `.pt` detection checkpoint.

## 4 Real Model Load

- Path/hash: canonical path and SHA-256 above.
- Entrypoint: `acfv.providers.ultralytics_avatar.create_provider`.
- GPU: RTX 4050 Laptop GPU; load 1.31 s; process RAM delta 223.6 MB; peak allocated VRAM 1,014.7 MB.
- CPU: real one-frame load/inference passed in 6.33 s.
- Result: `SELECTED_PRESENCE_ONLY`.

## 5 Real Avatar Inference

| Context proxy | Frames/regions | Detected | Median confidence | Range | Throughput |
|---|---:|---:|---:|---:|---:|
| Saruei | 500 / 10 | 492 (98.4%) | 0.881 | 0.268–0.943 | 38.9 fps |
| anny | 500 / 5 | 500 (100%) | 0.957 | 0.833–0.969 | 45.5 fps |

Every raw prediction remained `vtuber`. Recording ownership was used only as a sampling/validation context and never rewrote a prediction.

## 6 Visual Identity Spans

Twelve presence spans were produced: 11 Saruei-context regions and 1 continuous anny region. All 12 are `VISUAL_UNKNOWN`; strong/probable/ambiguous/conflict Creator spans are zero. This is correct because the model has no Creator class. Presence quality is measured separately by detection consistency and confidence.

## 7 Identity Fusion

Visual Creator observations: 0. Voice: not bootstrapped. Recording prior: not allowed to manufacture the missing visual label. Human: unchanged/highest authority. Fusion result: UNKNOWN 12; CONFIRMED/PROBABLE/CONFLICT 0.

## 8 Voice Profile v2

Saruei and anny candidates/retained/duration are all zero. Holdout, FAR, and FRR are `NOT_EVALUATED`. The strict `VISUAL_STRONG + compatible recording prior` gate blocked profile creation; thresholds were not lowered.

## 9 Trusted Speech

Candidates, pseudo-trusted, human-confirmed, and duration are zero for both Creators. The first blocking layer is lack of Creator-specific visual identity, followed by absence of Voice Profile v2. Music/overlap/ASR gates were therefore not reached.

## 10 Lexicon

Candidates/promoted/names/game terms/catchphrases/other are all zero. Reason: no Trusted Speech exists. Raw ASR was not promoted as authority.

## 11 Acoustic Exemplars

Count and terms are zero; provenance gate requires trusted Creator speech.

## 12 Adaptive ASR

Eligible/same/changed/conflict/high-risk changed are zero. Generic fallback remains authoritative and both Creator recommendations are `KEEP_SHADOW`.

## 13 Human Ground Truth

Samples and Generic/Adaptive WER/CER: `NOT_EVALUATED`; no independent human transcript was created or inferred.

## 14 Adaptive A/B Review

Items/completed/A wins/B wins/same/both wrong: all zero because there are no safe changed spans.

## 15 Creator Recommendation

- Saruei: `KEEP_SHADOW`
- anny: `KEEP_SHADOW`

## 16 Human Review v3

The v3 schema/artifact preserves the forward-only merge model and does not touch the existing Review DB. New Identity/Trusted/Adaptive items are zero rather than unsafe fabricated samples. Existing task UI, blind A/B behavior, persistence, restart, and analysis regressions pass.

## 17 Main GUI

Existing profile/update/status surfaces remain intact. The provider audit now resolves READY when the external model exists, while profile data remains unavailable until identity evidence exists. Product GUI regressions pass.

## 18 Performance

Avatar measurements are in sections 4–5. Voice, memory, and adaptive latency are not applicable because their gates did not open. GPU lifecycle is isolated to validation; the model is not co-resident with large-v3/Qwen during the run.

## 19 Fault Matrix

| Fault | Behavior |
|---|---|
| model missing/load failure | explicit provider error; generic pipeline remains available |
| bad label map | no identity selection; null mapping remains UNKNOWN |
| wrong input | explicit inference error |
| no detection | no observation; no memory write |
| identity conflict | generic fallback |
| voice/profile/memory/adaptive failure | stage blocked; generic transcript unchanged |
| review DB failure | existing recovery/read-only behavior; no annotation overwrite |

## 20 Safety

Raw media and official transcripts had zero mutations. No gate was lowered. Unknown `vtuber` observations cannot poison Creator memory. Cross-Creator isolation, fail-closed fallback, and profile versioning remain enforced. Weights were neither modified nor copied.

## 21 CGKN

Capability registry, current truth, Knowledge, contracts, guards, and evidence now distinguish validated presence from unavailable identity. The CGKN brief is sealed `ready`, advisory only; formal evidence status remains `NOT_EVALUATED` as required by CGKN authority boundaries.

## 22 Regression

Fixed37, Generation Quality, Backend, Product GUI, Human Review, creator-adaptive, contract, and CGKN guard paths are covered by the 560-test full suite and passed twice.

## 23 Automated Verification

Two final post-change runs: `560 passed` each; skip=0; xfail=0; compileall PASS; verify PASS twice; contracts PASS twice. Root/gui/review-lab/creator-profile/clip/live/download CLI smoke PASS. `git diff --check` PASS.

## 24 Bugs Fixed

| ID | Severity | Root cause | Fix | Regression |
|---|---|---|---|---|
| AVATAR-01 | High | real checkpoint not configured | external config + Ultralytics adapter | real CPU/GPU inference |
| AVATAR-02 | Critical | a selected model could be conflated with identity capability | split `SELECTED_IDENTITY` / `SELECTED_PRESENCE_ONLY`; explicit null map | unit + real span validation |
| AVATAR-03 | Medium | discovery roots exceeded the user's bounded scope | default root restricted to `G:/Cliper` | CLI/discovery tests |
| AVATAR-04 | Medium | model design/training provenance undocumented | checkpoint/code audit + Knowledge/evidence | CGKN guards |

## 25 Remaining Problems

The only recovered class is `vtuber`; a Creator-specific classifier/detector or human-labelled mapping dataset is still needed. Historical training metrics/dataset are unavailable. Voice v2, Trusted Speech, Lexicon, Acoustic Exemplars, real Adaptive results, and WER/CER cannot safely proceed until that identity gap is closed.

## 26 Engineering Status

```text
REAL_AVATAR_MODEL_DISCOVERED: YES
AVATAR_MODEL_DESIGN_UNDERSTOOD: YES
AVATAR_MODEL_TRAINING_PIPELINE_UNDERSTOOD: YES_WITH_MISSING_DATASET_AND_METRICS
REAL_AVATAR_INFERENCE_VALIDATED: YES_PRESENCE_ONLY
VISUAL_IDENTITY_SPANS_READY: UNKNOWN_ONLY
CREATOR_IDENTITY_REAL_VALIDATED: NO
VOICE_PROFILE_V2_READY: NO
TRUSTED_SPEECH_BOOTSTRAP_READY: BLOCKED
REAL_TRUSTED_SPEECH_AVAILABLE: NO
CREATOR_LEXICON_BOOTSTRAP_READY: BLOCKED
REAL_CREATOR_LEXICON_AVAILABLE: NO
ACOUSTIC_EXEMPLAR_MEMORY_READY: IMPLEMENTED_NO_REAL_DATA
REAL_ADAPTIVE_SHADOW_RESULTS_AVAILABLE: NO
CREATOR_ADAPTIVE_ASR_SHADOW_READY: IMPLEMENTED_BLOCKED_NO_CONTEXT
CREATOR_ADAPTIVE_ASR_PRODUCTION_READY: NO
IDENTITY_REVIEW_GUI_READY: YES_NO_SAFE_V3_ITEMS
TRUSTED_SPEECH_REVIEW_GUI_READY: YES_NO_SAFE_V3_ITEMS
ADAPTIVE_ASR_REVIEW_GUI_READY: YES_NO_SAFE_V3_ITEMS
GENERIC_ASR_FALLBACK_READY: YES
POISONING_PROTECTION_READY: YES
CROSS_CREATOR_ISOLATION_READY: YES
PROFILE_VERSIONING_READY: YES
CGNK_CREATOR_ADAPTIVE_ARCHITECTURE_READY: YES
CREATOR_ADAPTER_TRAINING_READY: NO
CREATOR_ADAPTER_TRAINING_IMPLEMENTED: NO
```
