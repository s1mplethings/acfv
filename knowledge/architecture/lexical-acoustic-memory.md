# Lexical-Acoustic Memory Boundary

Creator lexical-acoustic memory stores TRAIN-only HuBERT/WavLM representations for
short trusted terms. It is scoped by Creator and profile version, may optionally use an
unnamed voice mode as a tie-break, and emits ranked candidate evidence only.

It must never accept speaker-identity embeddings, cross Creator/profile boundaries,
learn from VALIDATION/HOLDOUT/UNKNOWN, or mutate a transcript. The generic ASR result
remains authoritative unless the existing Adaptive ASR consensus gate independently
authorizes a shadow correction.
