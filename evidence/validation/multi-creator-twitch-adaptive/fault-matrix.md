# Fault Matrix

| Fault | Observed / injected | Expected result | Result |
| --- | --- | --- | --- |
| Q exists but is only 256 GB | Real host | Reject Q | PASS |
| Healthy 2 TB HDD below reserve | Real E volume | Reject bulk | PASS |
| 2 TB fallback below reserve | Real F volume | Reject bulk | PASS |
| Unhealthy / repair-needed volume | Real G volume | Reject | PASS |
| Q absent | Unit test | Select eligible fallback | PASS |
| System volume has space | Unit test | Never select | PASS |
| Local root restart | Unit test | Resolve ignored mapping | PASS |
| Unsafe locator traversal | Unit test | Reject | PASS |
| Duplicate VOD in two roles | Unit test | Reject split | PASS |
| VALIDATION enters training memory | Unit test | Reject | PASS |
| VALIDATION threshold tuning | Unit test | Allow | PASS |
| HOLDOUT/UNKNOWN threshold tuning | Unit test | Reject | PASS |
| Active Twitch VOD | Real Snuffy probe | Exclude from frozen split | PASS |
| Visual A + changed unmatched voice | Unit test | VOICE_MODE_SHIFT_CANDIDATE | PASS |
| Visual A + strong known Voice B | Unit test | IDENTITY_CONFLICT | PASS |
| Speaker embedding used as lexical memory | Unit test | Reject | PASS |
| Cross-Creator lexical candidate | Unit test | Isolate | PASS |
| Formal bulk acquisition without safe disk | Real host | Do not start | PASS |

Canonical VOD download duplicate/partial/restart/bad-URL/deleted-VOD behavior remains
covered by the existing `test_vod_download.py` regression suite.
