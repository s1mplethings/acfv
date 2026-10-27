# ACFV New Twitch Creator-Adaptive Validation

## 1 Repository

branch: `validation/new-twitch-vod-creator-adaptive`  
base: `02ccae775c2e4c4567c8ffcee112f49517d8aae4`  
implementation: `aa1486c998b91fb455bfb25ae31d79ed4b08b5ec`  
evidence: `evidence/validation/new-twitch-creator-adaptive`  
working tree: clean after evidence commit

## 2 Twitch Discovery

Targets: Saruei, anny. UNKNOWN: Shylily, Zentreya, Ironmouse. Nine VODs selected; older Saruei VODs were budget-rejected. anny has `INSUFFICIENT_CURRENT_PUBLIC_VODS` (one archive, no public highlights). Existing Helix credentials returned unauthorized, so public Twitch metadata discovery plus canonical TwitchDownloaderCLI validation was used.

## 3 New Downloads

Nine canonical range downloads succeeded: five Saruei (three TRAIN, one VALIDATION, one HOLDOUT), one anny HOLDOUT, and three UNKNOWN. Total `10.01` GiB. IDs, dates, titles, ranges, quality, bytes, hashes and roles are in `download-receipts.json`.

## 4 Existing-VOD Dedup

Existing registry: Q8Pilot `2340856811` plus one legacy Saruei capture without a VOD ID. All nine selected IDs and media hashes are unique; duplicate rejects: 0.

## 5 Corpus Split

TRAIN: `2895982534`, `2895222160`, `2894283807`; VALIDATION: `2896930589`; HOLDOUT: `2897884895`, `2853235966`; UNKNOWN calibration: `2898966148`; UNKNOWN holdout: `2899063581`, `2899332592`. Split SHA-256: `ee9ceda31e283627a4f9c23729a2a756e0ca4e5488b70db04f302f4651c2b5a3`.

## 6 Media Integrity

ffprobe/video/audio/duration/full decode: 9/9 PASS. Silence scan: 9/9 executed; one Saruei TRAIN range has a suspected muted interval flag. Final download failures: 0. Raw media remains local-only.

## 7 Avatar Dataset

7,211 accepted crops: Saruei TRAIN 3000 / VALIDATION 1000 / HOLDOUT 1000; anny HOLDOUT 1000; UNKNOWN 1211. Recording leakage: false. Rejected: 1,672 no-single-avatar, 1,749 near-duplicate, 13 invalid quality/bbox.

## 8 Visual Models

DINOv2 P/C/U: 0.654/0.497/0.625; OpenCLIP: 0.581/0.772/0.000; ResNet18: 0.410/0.515/0.053; MobileNetV3: 1.000/0.240/1.000; ConvNeXt-Tiny: 0.854/0.415/0.998. P/C/U = strong precision / known coverage / unknown rejection.

## 9 New-VOD Visual Holdout

MobileNetV3 proxy: strong precision `1.000`, coverage `0.240`, UNKNOWN rejection `1.000`, false-strong `0.000`. Saruei top-1 1.000 / strong recall 0.480; anny top-1 0.152 / strong recall 0.000. Labels are `RECORDING_LEVEL_PROXY`, not human frame truth.

## 10 Visual Winner

Winner: MobileNetV3 linear probe, version `creator_visual_identity_v2_new_twitch`, selected for zero proxy false-strong and fastest throughput. Status: `SHADOW_VISUAL_IDENTITY`; no production replacement. Masked/wide context preserves precision but collapses coverage, so crop-scale sensitivity is open.

## 11 Voice A/B

Resemblyzer holdout FAR `0.1244`, FRR `0.5685`, support precision `0.7000`. ECAPA FAR `0.0461`, FRR `0.0342`, support precision `0.9338`. Winner: ECAPA, support-only. Canonical Saruei profile: 55 segments / 660 s / three TRAIN VODs; 30 retained.

## 12 Trusted Speech

TRAIN only. Saruei: 55 candidates, 0 pseudo-trusted, 55 rejected by the strict gate, 0 s trusted. anny: insufficient new TRAIN VOD. No validation/holdout speech entered memory.

## 13 Lexicon

Funnel: 0 trusted units → 0 term candidates → 0 repeated → 0 promoted → 0 used → 0 ASR changes. Acoustic exemplars: 0.

## 14 Holdout Adaptive ASR

Saruei: 100 spans (50 low-confidence/high-risk, 50 random); 100 `UNCHANGED_UNCERTAIN`, 0 changed because no trusted hotwords existed. anny: Generic fallback only. Generic transcript mutations: 0.

## 15 Human Ground Truth

Samples are ready in Human Review. Generic WER, Adaptive WER, CER and critical semantic accuracy: `PENDING`.

## 16 Unknown Safety

UNKNOWN Creators: Shylily, Zentreya, Ironmouse. Visual proxy false-strong: 0 for the selected model. Voice attack FAR is non-zero, therefore voice cannot authorize identity. 217 anny/UNKNOWN memory attacks: 217 Generic fallback, 0 memory leakage.

## 17 Target-Speaker POC

`NOT_APPLICABLE`: no verified collab speaker ground truth exists in the frozen Saruei ranges. Zentreya multi-avatar frames remain UNKNOWN challenge material and are not speaker truth.

## 18 Training / LoRA Readiness

Visual/voice derived data exists; transcript ground truth does not. Whisper LoRA training: not ready. Target-speaker POC: not accuracy-valid. Decision: do not train/enable.

## 19 Human Review Dataset

`NEW_TWITCH_VALIDATION_V1`: 500 local-ready items — Visual 250 (Saruei strong 100, anny strong 0, UNKNOWN 100, ambiguous 50), Trusted Speech candidates 50, Adaptive ASR 200. anny strong is zero because the model produced none; no samples were fabricated.

## 20 Performance

Download: 10.01 GiB / 9 ranges. Visual encoding FPS: DINOv2 186.32, OpenCLIP 245.69, ResNet18 293.47, MobileNetV3 571.67, ConvNeXt 276.41. Voice/ASR used RTX 4050 Laptop GPU (6 GiB); detailed per-model GPU/RAM data is in benchmark evidence.

## 21 Fault Matrix

Deleted/403/network interruption/partial/duplicate/disk-full/restart/ffprobe failure all have passing automated coverage. Real faults fixed: wrong-volume temp caching, exact-trim drift, Windows CLI version-on-stderr, failed-range revision, ECAPA Windows symlink privilege failure, and quadratic threshold-grid explosion.

## 22 Licenses

OpenCLIP 2.32 MIT; timm 1.0.13 Apache-2.0; SpeechBrain 1.0.3 Apache-2.0; Transformers 4.51.3 Apache-2.0; Resemblyzer package baseline Apache-2.0. Raw Twitch media redistribution is prohibited and excluded.

## 23 CGNK

Doctor PASS; Provider mainline available; repository guards PASS. New corpus knowledge and HOLDOUT/UNKNOWN leakage invariants are recorded. Sealed brief `7b178df2dd682db6f939c85d14e8a1c5a2f126c16e8e2cbc562e31fda3aec20b`. No project generation was required.

## 24 Existing Regression

Fixed37, Generation, Backend, GUI and Human Review regression paths are covered by the full 577-test suite and both canonical verify passes. No existing artifacts were deleted or rewritten.

## 25 Verification

pytest1: 577 PASS; pytest2: 577 PASS; verify1: PASS; verify2: PASS; contracts: PASS ×2; CGKN guards/doctor: PASS; compile/8 CLI helps: PASS ×2. Implementation commit was clean before evidence promotion.

## 26 Bugs Fixed

Same-drive downloader temp path; Windows version parsing/timeout/env precedence; retry range revision without duplicate rows; audio-only silence scan; batched visual presence inference; real OpenCLIP and timm encoders; bounded threshold calibration; ECAPA copy strategy on Windows; Human Review new-dataset discovery/metadata.

## 27 Remaining Problems

anny has no independent new TRAIN/VALIDATION VOD and fails temporal visual generalization. Visual human precision is pending. ECAPA FAR is 4.61%. Trusted Speech/Lexicon/Acoustic memory are empty. Adaptive WER/CER is pending. Crop-scale sensitivity remains. Twitch Helix credentials require renewal. Production gates remain closed.

## 28 Engineering Status

```text
NEW_TWITCH_CORPUS_READY: YES
TARGET_CREATOR_NEW_VODS_READY: PARTIAL_SARUEI_YES_ANNY_INSUFFICIENT
UNKNOWN_CREATOR_VODS_READY: YES
NEW_VOD_SPLIT_LEAKAGE_SAFE: YES
VISUAL_IDENTITY_NEW_VOD_VALIDATED: PARTIAL_SHADOW
OPEN_SET_NEW_VOD_VALIDATED: YES_RECORDING_PROXY
VOICE_MODEL_NEW_VOD_VALIDATED: YES_SUPPORT_ONLY
TRUSTED_SPEECH_NEW_VOD_READY: NO_STRICT_GATE_REJECTED_ALL
CREATOR_LEXICON_NEW_VOD_READY: NO
ADAPTIVE_ASR_NEW_VOD_SHADOW_READY: YES
ADAPTIVE_ASR_NEW_VOD_HUMAN_VALIDATED: NO_PENDING
ADAPTIVE_ASR_PRODUCTION_READY: NO
TARGET_SPEAKER_ASR_POC_READY: NOT_APPLICABLE_NO_GT
WHISPER_LORA_TRAINING_READY: NO
GENERIC_ASR_FALLBACK_READY: YES
CROSS_CREATOR_ISOLATION_READY: YES
POISONING_PROTECTION_READY: YES
CGNK_NEW_TWITCH_VALIDATION_READY: YES
```
