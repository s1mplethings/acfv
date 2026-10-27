# Creator-Adaptive Understanding

ACFV improves repeated-Creator understanding through identity, trustworthy memory, scoped lexical context, and local ASR re-decode. It does not replace the processing engine. The safe order is identity → trusted memory → lexicon → shadow re-decode → human ground truth; model fine-tuning is a later, independently evaluated option.

All derived state is versioned and reversible. `creator_adaptation_enabled` defaults to false. Missing or uncertain adaptive evidence falls back to the existing generic pipeline.

Phase 2 adds an avatar-driven bootstrap lifecycle without weakening those rules: bounded model discovery → explicit label mapping → multi-frame visual spans → Recording-prior and Voice conflict checks → strict trusted corpus → scoped lexicon/acoustic exemplars → local shadow re-decode → Human Review. A configured provider creates a new compatible profile version; old memory remains available for audit but is not silently mixed into the new profile. Production stays a per-Creator recommendation until sufficient human transcripts exist and the user explicitly enables it.

