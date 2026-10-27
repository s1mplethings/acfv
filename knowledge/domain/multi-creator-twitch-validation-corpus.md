# Multi-Creator Twitch Validation Corpus

`MULTI_CREATOR_TWITCH_V1` is a VOD-level, creator-adaptive evaluation corpus for
Saruei, anny, atelieranoko, snuffy, and laphipi. Public Twitch discovery is metadata
only; formal media acquisition must pass through `VodDownloadService` and its canonical
TwitchDownloaderCLI adapter.

Frozen VOD inventory (UTC date; channel handle equals the lower-case Creator name):

| Creator | TRAIN VODs | VALIDATION VOD | HOLDOUT VOD |
| --- | --- | --- | --- |
| Saruei (`saruei`) | `2894283807` (2026-10-07), `2895222160` (2026-10-08), `2895982534` (2026-10-09) | `2896930589` (2026-10-10) | `2897884895` (2026-10-11) |
| anny (`anny`) | — | — | `2853235966` (2026-08-22) |
| atelieranoko (`atelieranoko`) | `2894403908` (2026-10-07), `2896165071` (2026-10-09) | `2898100328` (2026-10-11) | `2898984086` (2026-10-12) |
| snuffy (`snuffy`) | `2872738058` (2026-09-13), `2876880400` (2026-09-17) | `2882220435` (2026-09-23) | `2884984247` (2026-09-26) |
| laphipi (`laphipi`) | `2893473795` (2026-10-06), `2894425039` (2026-10-07) | `2896095029` (2026-10-09) | `2897831198` (2026-10-11) |

The split contains 18 VODs / 73.51 hours and has SHA-256
`90e272ca8798449faec258e890152906f7c15cad5f2753b60c5e7a078b99446f`.
anny is explicitly `LIMITED_VOD_DIVERSITY`. Snuffy VOD `2900140146` was discovered
and probed while still `RECORDING`; it is not a member of any frozen role.

The split is frozen and hashed before any training. A Twitch VOD ID can appear exactly
once. TRAIN can create visual/voice profiles, Trusted Speech, lexicon, and lexical-
acoustic exemplars. VALIDATION can tune thresholds only. HOLDOUT and UNKNOWN are
evaluation-only and can never feed known-Creator memory.

Large media is local-only and addressed as `BULK_MEDIA_ROOT/twitch/...`. Before bulk
download, the storage selector requires a healthy non-system volume of at least 1 TiB
and preserves `max(15% capacity, 200 GiB)` after the estimated corpus download. Q is a
preference, not an assumption. `BULK_STORAGE_NOT_AVAILABLE` blocks bulk acquisition but
does not block small bounded probes or metadata audit.

Voice-profile sub-centres are unnamed acoustic modes. Without human labels they are not
accent, nationality, language, or identity classes. Speaker embeddings answer WHO;
HuBERT/WavLM lexical-acoustic representations may support WHAT as candidate evidence,
but the two memories remain physically and logically separate.

All measured claims must name their truth source. Engineering ASR confidence is not
WER/CER, recording ownership is not identity truth, and review fields remain pending
until a human supplies ground truth.
