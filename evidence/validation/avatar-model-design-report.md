# Avatar Model Design Report

The recovered model is an Ultralytics 8.3.53 YOLO11l **object detector**, not a classifier or segmenter. It accepts raw OpenCV BGR frames, uses native Ultralytics letterbox/scaling at 640 pixels, and returns `xyxy` boxes, confidence, and a class id. Its only class is `0: vtuber`; it has no Saruei or anny identity output.

The completed training run embedded in the checkpoint used pretrained `yolo11l.pt`, 100 epochs, batch 16, CUDA, AMP, automatic optimizer, deterministic seed 0, standard box/class/DFL losses, HSV/translation/scale/flip/mosaic augmentation, and a YOLO image/label dataset. Training metrics and the historical dataset are unavailable.

The full provenance, architecture, training, preprocessing, inference, dependency, checkpoint, and limitation audit is in [`docs/avatar-model-design.md`](../../docs/avatar-model-design.md).
