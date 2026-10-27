---
id: acfv.release-verification
version: 1
scope: repository
tags: [release, verification]
depends_on: [scripts/verify.ps1, scripts/verify.sh]
risk: high
---

# Release Verification

Purpose: execute the canonical repository gate and promote a commit-bound result.

Inputs: clean candidate commit, ChangeManifest, supported environment.

Outputs: TestReceipt and reviewed validation/release evidence.

Dependencies: repository guards, capability tests, canonical verify scripts.

Workflow:
1. Confirm exact SHA and working-tree state.
2. Run compileall and all three CLI help commands.
3. Run full pytest and coverage when required.
4. Run `scripts/verify.ps1` on Windows; run `.sh` when a POSIX environment is available.
5. Commit structural/evidence inputs, rerun against that commit, then record exact results.
6. Do not claim product readiness when known product gates remain open.

Verification: receipt must name SHA, commands, environment, pass/fail, skips, and limitations.
