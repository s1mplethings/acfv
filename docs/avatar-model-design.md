# Recovered Avatar Model Design

## Provenance

The canonical external checkpoint is `G:/Cliper/acfv/model/best.pt` (51,176,658 bytes; SHA-256 `48d0f7058739ec1f7baaa6ed58d9192130e9caa377be1dad238ba7288d4f1580`). `G:/Cliper/acfv/artifacts/secrets/best.pt` is byte-identical. ACFV references the canonical path and never copies or modifies either weight.

The original supporting code is in `G:/Cliper/yolo_funcs/`: `yolo_train.py`, `yolo_label_pyqt.py`, `frames_stract.py`, and `video_process.py`. `G:/Cliper/model_training/` is a later, unrelated optical-flow/MoE pipeline and is not provenance for this checkpoint.

## Architecture and contract

- Framework: PyTorch through Ultralytics 8.3.53.
- Task: object detection, not classification or segmentation.
- Architecture: pretrained YOLO11l backbone and three-scale Detect head (P3/P4/P5); input channels 3; `nc=1`.
- Input: OpenCV BGR frames. Ultralytics performs letterbox resize, channel conversion, scaling, batching, and device transfer. This matches the historical inference code, which passed raw OpenCV frames to `YOLO`.
- Training/inference size: 640 pixels.
- Output: zero or more `(xyxy bbox, class id, confidence)` detections.
- Only class: `0 -> vtuber`.
- Semantic limit: avatar/VTuber presence only. The output cannot distinguish Saruei from anny and cannot establish the active speaker.

## Training design recovered from the checkpoint

The embedded training arguments are the strongest record of the actual run: `model=yolo11l.pt`, `data=D:/Cliper/.yolo_tool/dataset/data.yaml`, 100 epochs, batch 16, image size 640, CUDA, 8 workers, pretrained weights, automatic optimizer, seed 0, deterministic mode, AMP enabled, and run name `train7`.

The label tool stores `images/`, YOLO-format `labels/`, `classes.txt`, train/validation splits, and a generated `data.yaml`. Frame extraction uses OpenCV and random video frames. Standard Ultralytics detection losses are implied by the framework/head: box, class, and DFL weights embedded as 7.5, 0.5, and 1.5.

Embedded augmentation parameters include HSV `(0.015, 0.7, 0.4)`, translation 0.1, scale 0.5, horizontal flip 0.5, mosaic 1.0 with close-mosaic at epoch 10, and no mixup/copy-paste. The historical root `config.json` contains an older one-epoch/100-pixel configuration; it is not the configuration embedded in `best.pt` and therefore is not treated as the completed training run.

Training metrics and dataset contents are not embedded in the checkpoint and the historical dataset path is absent from the authorized `G:/Cliper` search result. Accuracy, precision, recall, and class balance are therefore unknown.

## Production adapter

`acfv.providers.ultralytics_avatar.UltralyticsAvatarProvider` lazily loads the external checkpoint, verifies the exact `{0: "vtuber"}` class contract, supports CPU or CUDA, and normalizes detections without relabelling them. `config/avatar_identity.json` explicitly maps `vtuber` to `null`. Discovery reports `SELECTED_PRESENCE_ONLY`; downstream identity aggregation persists `VISUAL_UNKNOWN`.

The default confidence is 0.25, matching a normal Ultralytics detection threshold. It is configurable for diagnostics through `ACFV_AVATAR_CONFIDENCE`, but no confidence can convert a presence class into a Creator class.

## Real validation and limitations

On RTX 4050 Laptop GPU, the model loaded in 1.31 seconds, added about 224 MB process RAM, and peaked at about 1,015 MB allocated VRAM during batched inference. It detected `vtuber` on 492/500 Saruei frames and 500/500 anny frames. Median confidence was 0.881 and 0.957 respectively; batch throughput was 38.9–45.5 fps.

This validates avatar presence, preprocessing, batching, and output normalization. It does not validate Creator identity. Voice Profile v2, Trusted Speech, Creator Lexicon, Acoustic Exemplars, and Creator-Adaptive ASR remain blocked because their visual identity gate correctly requires an evidence-backed Creator mapping.
