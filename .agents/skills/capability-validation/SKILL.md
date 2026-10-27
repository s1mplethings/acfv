---
id: acfv.capability-validation
version: 1
scope: repository
tags: [validation, evidence]
depends_on: [specs/capabilities/index.yaml, specs/contracts/test_receipt.schema.json]
risk: medium
---

# Capability Validation

Purpose: prove a capability's declared acceptance without confusing runtime output with evidence.

Inputs: capability ID, commit SHA, dataset/fixtures, acceptance criteria.

Outputs: raw receipt under `var/`; optionally reviewed evidence under `evidence/`.

Dependencies: capability spec, targeted tests, TestReceipt schema.

Workflow:
1. Bind the run to the exact commit and record environment/tool versions.
2. Execute the smallest targeted unit/integration/E2E set that proves each acceptance item.
3. Store raw reports in `var/` and record failures honestly.
4. Promote only reviewed, stable results with dataset, commands, results, and limitations.
5. Never turn artifact presence or a prior report into a new PASS claim.

Verification: validate receipt shape and cross-link evidence to capability acceptance.
