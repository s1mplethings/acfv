# New Twitch Validation Corpus

`NEW_TWITCH_VALIDATION_V1` is a local, versioned validation corpus attached to the
existing `vod_download` and Creator-Adaptive capabilities. It is not a new product
capability.

## Provenance

The reviewed corpus record binds Creator, Twitch VOD ID, public URL, publication date,
requested range, actual quality, byte count, SHA-256, Library Recording ID, download
receipt, role, and media-integrity result. Raw VOD media, databases, credentials, and
large model weights remain under ignored runtime storage and are never placed in Git or
the delivery archive.

Discovery prefers Twitch Helix. When configured credentials are expired or unavailable,
public Twitch metadata may identify candidates, but every selected VOD must still pass
canonical `TwitchDownloaderCLI info` and `VodDownloadService` download/integrity gates.
Deleted, private, subscriber-only, or inaccessible content is not bypassed.

## Frozen roles

The split manifest is SHA-256 bound before training. One VOD ID belongs to exactly one
top-level role:

- `TRAIN`: may build visual models, voice profiles, trusted speech, lexicon, and acoustic exemplars.
- `VALIDATION`: may select visual/voice thresholds, but cannot build memory.
- `HOLDOUT`: final unseen evaluation only; it cannot tune or train any component.
- `UNKNOWN`: open-set and cross-Creator attack evidence only; it cannot create known-Creator memory.

An UNKNOWN calibration partition may tune open-set rejection only. Separate UNKNOWN
Creators/VODs remain untouched holdout evidence. A failed holdout cannot be moved into
TRAIN. A pre-training range revision is allowed only when the old and new split hashes,
reason, failed receipt, and replacement integrity evidence are retained.

## Ground truth and claims

Broadcaster ownership is a weak recording-level proxy only for verified single-Creator
spans. It is not frame truth, active-speaker truth, or transcript ground truth. Human
visual precision and Generic-versus-Adaptive WER/CER remain `PENDING` until review items
from the same frozen HOLDOUT VODs are labelled.

Corpus insufficiency is an outcome, not a reason to reuse older VODs. If a Creator has
too few current public archives for independent TRAIN/VALIDATION/HOLDOUT roles, report
that limitation and keep production gates closed.

## Observed v1 outcome

- Saruei: TRAIN `2895982534`, `2895222160`, `2894283807`; VALIDATION
  `2896930589`; HOLDOUT `2897884895`.
- anny: HOLDOUT `2853235966`; status `INSUFFICIENT_CURRENT_PUBLIC_VODS`, with no
  new-data TRAIN or VALIDATION role.
- UNKNOWN: Shylily `2898966148` (calibration), Zentreya `2899063581` and
  Ironmouse `2899332592` (holdout).
- All nine selected ranges passed audio/video probe, duration, full decode, and silence
  inspection. The 7,211-crop v2 manifest reports no Recording/VOD split leakage.
- MobileNetV3 is the safest visual shadow candidate, not a production replacement:
  proxy strong precision 1.0, coverage 0.24, unknown rejection 1.0. anny temporal
  generalization failed, and wide/masked context exposed crop-scale sensitivity.
- ECAPA beats Resemblyzer as support evidence but still has 4.61% attack FAR. Strict
  Trusted Speech admits no automatic units, so Lexicon/Acoustic memory remains empty,
  Adaptive ASR stays shadow, and Generic ASR remains authoritative.
