# Bilingual Subtitle

- Purpose: produce complete Chinese and English captions on one stable, word-derived timeline.
- Canonical Interface: `acfv.clips.subtitles.BilingualSubtitleService`.
- Implementation: `src/acfv/clips/subtitles.py`, with contextual JSON-capable local Qwen as the final-quality primary, Argos only as an explicit provider fallback, and renderer adapters.
- Inputs: recording-relative word timestamps, clip boundaries, source language, display mode, translation provider, glossary, and segmentation configuration.
- Outputs: a typed `BilingualSubtitleTrack`, ASS/SRT files, and a timeline quality report.
- Effects: writes subtitle artifacts and a content-addressed translation cache beneath the selected output directory.
- Errors: invalid/overlapping timing, incomplete sentence boundaries, unavailable translation, empty target text, or out-of-range cues fail explicitly.
- Dependencies: canonical ASR word timestamps, `steps.subtitle_translate` provider implementations, and canonical Clip rendering.
- Acceptance: both languages share cue timing; all valid cues have required text; timing is monotonic and clip-relative; no character-derived timing is created; coverage and reading-speed metrics are reported.

Translation changes text only. GUI and renderer never assemble bilingual content independently.
The Qwen provider must return schema-validated, non-empty text and must preserve names, terminology,
profanity, uncertainty, and speaker intent without inventing facts. Classified background lyrics are
not promoted into creator-speech subtitles unless an explicit lyrics mode requests them.
English final-clip cues are translated in semantic groups of 5-9 cues while preserving exactly one
output for each cue ID. `LOCALIZED_CREATOR` is the final-clip default; `FAITHFUL` remains available.
Translation may use context but may not modify audio-derived timing. Glossary precedence is Recording
over Game over Creator over Global, and translation memory may only originate from explicit user edits.

Contextual localization v2 passes Creator, content type, game, event setup/payoff/reaction, tone,
speaker relations, current topic, callback, scoped glossary, previous cues, current cues, and next cues
as structured context. Output must contain each requested cue ID exactly once. A structured failure gets
one repair attempt, then an adaptive smaller batch; only the failed cue falls back to Argos.

Objective semantic guards cover cue omission/source copy, negation, numbers, typed named entities,
glossary, question force, profanity strength, and suspicious invented memes. Each finding records a
category (`CRITICAL_SEMANTIC`, `FACTUAL`, `TERMINOLOGY`, `STYLE`, `NATURALNESS`, or `STRUCTURAL`),
severity, evidence, and risk contribution. They are release signals, not naturalness or humour scores.
Entities are classified as known Creator entities, game terms, OCR-confirmed entities, glossary
entities, repeated high-confidence entities, or unknown capitalized tokens. Capitalization alone is
never critical. Acronyms, UI labels, and proper names may remain source text when supported by context.
Adjacent profanity-strength changes are warnings; only extreme tone insertion/removal is high risk.
Argos cues are labelled `ARGOS_FALLBACK`; mixed tracks are labelled `MIXED_PROVIDER`, and more than
20% fallback cues requires review. Clip readiness is `READY`, `READY_WITH_WARNINGS`, or
`NEEDS_REVIEW` based on maximum plus aggregate risk and explicit hard blockers. Automated readiness
never sets `PUBLISHABLE`; human language review remains pending.
