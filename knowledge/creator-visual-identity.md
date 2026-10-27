# Creator Visual Identity Knowledge

- Stage 1 is external YOLO11l `best.pt` (`48d0f705...f1580`), used only for avatar presence/bbox crops.
- The dataset contains Saruei and anny plus locally authorized unknown/challenge material. Splits are recording-isolated and preserve source hashes, timestamps, bbox, detector confidence, quality, and detector hash.
- Frozen DINOv2-small, OpenCLIP ViT-B/32, and frozen ResNet18 plus a linear probe were compared on the same recording holdout.
- ResNet18 linear probe won on the production ordering: strong precision, unknown rejection, coverage, holdout accuracy, then cost. The selected safety threshold uses score `0.45`, margin `0.20`, and support `0.7738778293`.
- Holdout proxy results: Top1 `0.9753`, STRONG precision `1.0`, STRONG coverage `0.7464`, unknown rejection `1.0`, false-strong rate `0.0`.
- Independent raw-recording proxy validation produced 0 false STRONG identities in 246 Saruei and 500 anny STRONG frames. This is recording-prior proxy truth, not per-frame human ground truth.
- Runtime remains `SHADOW_VISUAL_IDENTITY` until the 100 STRONG / 50 uncertain review pack is human-labelled.
- Never reinterpret the raw presence class `vtuber` as Saruei or anny. Preserve UNKNOWN and generic fallback.
