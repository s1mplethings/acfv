# Translation provider comparison

Date: 2026-10-10

## Available providers

| Provider | Runtime availability | Installed directions | Result |
|---|---:|---|---|
| Argos Translate | yes | `en -> zh` only | Reused existing validated Saruei bilingual artifacts. |
| Canonical local LLM / Qwen | not configured for this run | none proven | Not executed; no claim of quality. |
| OpenAI Python package | package present, provider not configured as canonical translation runtime | none proven | Not executed. |

## Three-sample comparison

The existing Argos `en -> zh` route was inspected against three classes already present in the
validated Saruei subtitle artifacts: literal statement, reaction/profanity/slang, and game
terminology/proper nouns. Timing and coverage remain machine-valid. Literal statements are the
least risky. Slang/profanity and game terms remain `AUTO_SUSPECT` because there was no second
configured provider or human adjudication in this run. Provider quality was therefore not ranked.

Japanese and mixed-source comparisons are `NOT_EVALUATED`: no authorized genuine Japanese
Creator Library was available, and the five recordings labelled `ja` are predominantly
English/mixed speech with music-lyric contamination. Machine-translated fixtures were not used as
a substitute. Argos must not be treated as a universal language solution.

