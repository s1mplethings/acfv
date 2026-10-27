# Creator-Adaptive Phase 2 Validation

Implementation commit: `5d391a1ba0886f107738534182077c46286759ac`.

## Outcome

The safe Phase 2 architecture is implemented and fully regression-tested. Bounded discovery inspected the repository and seven relevant local roots. Five weight files were found; runtime metadata proved that three unique hashes represent Japanese-character detectors or generic COCO detectors. None has Saruei, anny, or annytf labels, so no model was selected and real inference is `BLOCKED_MODEL_PATH`.

No downstream count was manufactured. `creator_profile_v1` remains preserved. The proposed `creator_profile_v2` has zero visual spans, v2 voice candidates, trusted units, lexicon candidates, acoustic exemplars, or adaptive shadow samples. Generic ASR remains authoritative, both Creators remain `KEEP_SHADOW`, and WER/CER are `NOT_EVALUATED`.

## Implemented safety boundaries

- Avatar selection requires explicit model path, executable Python entrypoint, and explicit versioned label mapping.
- Unknown labels are persisted without creating a Creator.
- Multi-frame visual spans do not imply active speech.
- Visual identity is primary, Recording Creator is contextual prior, voice is support/conflict, and human truth has highest priority.
- Any identity conflict or profile mismatch falls back to Generic ASR.
- Pseudo-trusted speech requires compatible profile, clean overlap/music state, no critical flags, high identity/ASR/redecode evidence, and independent support.
- Human promotion requires both speaker and transcript checks.
- Lexicon and acoustic exemplars use trusted provenance only; adaptive output cannot self-promote.
- Hotwords are Creator-scoped, history-ranked, and capped at 30.
- Raw media and official transcripts were not mutated.

## Validation

Two identical full rounds passed. Each round ran compileall, seven CLI help surfaces, 557 pytest tests with zero skips/xfails, the Windows verification script, and contract checks. The clean detached worktree at `F:\ACFV-Derived\acfv-avatar-phase2-clean-5d391a1` passed 57 focused tests plus Product GUI, Review Lab, provider configuration, and Generic fallback smoke checks and remained clean.

Human Review v2 validated 686 existing items with zero missing media, database integrity `ok`, no duplicate IDs, and no production DB mutation. The prior 100-item Phase 1 identity artifact remains preserved separately; it was not falsely reported as merged into the blocked Phase 2 dataset.

CGKN configuration, registry, capabilities, contracts, knowledge, guards, and the sealed ready brief are synchronized. CGKN correctly reports `formal_evidence_status: NOT_EVALUATED`; workflow readiness is not treated as formal product evidence.
