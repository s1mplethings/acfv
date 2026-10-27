---
id: acfv.pipeline-change
version: 1
scope: repository
tags: [pipeline, backend]
depends_on: [specs/capabilities/video_processing.md]
risk: high
---

# Pipeline Change

Purpose: change the existing processing engine without creating a second execution path.

Inputs: requested stage/contract change, capability spec, relevant module spec.

Outputs: minimal source/test changes, ChangeManifest, TestReceipt, optional promoted evidence.

Dependencies: backend service, pipeline orchestrator, modular plugins, steps, providers.

Workflow:
1. Read the processing capability and affected module contract.
2. Trace CLI/GUI through the backend service to the canonical stage owner.
3. Preserve stage vocabulary, output paths, and compatibility imports unless the contract changes explicitly.
4. Add focused unit/integration coverage and run a pipeline dry-run or artifact smoke.
5. Run the canonical repository verification gate.

Verification: targeted tests, contract checks, then `scripts/verify.ps1` or `.sh`.
