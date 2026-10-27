# Creator Visual Identity Contract

The canonical service receives crops produced by the avatar presence detector and returns a versioned open-set decision. A decision contains candidate Creator ID (nullable), score, top-two margin, support score, state, model version, and provenance.

Required behavior:

- `vtuber` means presence only and cannot be converted directly to a Creator ID.
- UNKNOWN and AMBIGUOUS are valid results and always retain generic fallback.
- STRONG requires calibrated score, margin, support, and multi-frame temporal agreement before fusion.
- Training, validation, and holdout are split by recording/group; no recording may appear in more than one split.
- A classifier may read configured Creator IDs but cannot create, merge, or mutate Library Creator rows.
- Model/profile version changes isolate derived memory and require recalibration.
- Missing or integrity-mismatched model dependencies fail closed.

Trusted speech requires a temporally strong visual span or explicit human confirmation plus the remaining voice/content safety gates. Visual UNKNOWN can never bootstrap trusted memory.
