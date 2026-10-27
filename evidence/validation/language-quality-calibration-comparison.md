# Language Quality Calibration Comparison

| Metric | Before | After | Delta |
|---|---:|---:|---:|
| Low-confidence words | 22 | 22 | 0 |
| AUTO_CORRECTED | 0 | 0 | 0 |
| Entity findings | 25 | 23 | -2 |
| Critical entity findings | 25 | 1 | -24 |
| Broken-sentence findings | 30 | 4 | -26 |
| Critical translation findings | 29 | 6 | -23 |
| READY | 0 | 0 | 0 |
| READY_WITH_WARNINGS | 0 | 8 | 8 |
| NEEDS_REVIEW | 12 | 4 | -8 |
| Correction median runtime | 16.606s | 16.606s (no new model call) | 0% |
| Total language median runtime | 79.361s | 79.361s + deterministic guards | <1% estimated |

The after pass reuses the same 12 archived artifacts. It does not claim new acoustic decoding.
