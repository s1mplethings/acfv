# Avatar Presence Detector Design

## Canonical role

`G:/Cliper/acfv/model/best.pt` is the external `AVATAR_PRESENCE_DETECTOR`. It finds VTuber-like avatar regions and returns bbox, confidence, and frame timestamp. Its raw class is exactly `vtuber`; it does not identify Saruei, anny, an active speaker, or a Library Creator.

## Recovered training design

- Architecture: Ultralytics YOLO11l detect model, P3/P4/P5 head, 640 input.
- Checkpoint SHA-256: `48d0f7058739ec1f7baaa6ed58d9192130e9caa377be1dad238ba7288d4f1580`.
- Training metadata: pretrained YOLO11l, 100 epochs, batch 16, CUDA, AMP, deterministic seed 0.
- Dataset tooling: historical PyQt labelling pipeline with YOLO image/label layout.
- Classes: `{0: "vtuber"}`.
- Runtime: Ultralytics 8.3.53; OpenCV BGR frames follow native Ultralytics letterbox/channel/scaling preprocessing.
- Original `best.pt` stays external and is never copied, overwritten, or shipped.

## Real validation

- Saruei: 492/500 detected frames (98.4%), median confidence 0.881.
- anny: 500/500 detected frames (100%), median confidence 0.957.
- Observed GPU throughput: 38.9–45.5 fps; peak VRAM approximately 1.0 GB.

## Two-stage boundary

Presence bbox is padded by 8% and passed to `CreatorVisualIdentityService`. Only that separate open-set model may emit a Creator candidate. Raw `vtuber` remains in observation metadata, and a missing/unsafe identity result remains UNKNOWN. Temporal aggregation—not a single frame—feeds Creator Identity Fusion.

## Lifecycle and safety

Any weight, class, preprocessing, or mapping change requires a new detector/model version, integrity hash, real validation, and profile rebuild. Presence output cannot mutate Creator, Recording, transcript, or trusted memory state.
