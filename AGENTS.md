# ACFV Agent Entry

This file is the repository entry point, not the project knowledge base.

1. Read `.cgnk/project.yaml`.
2. Locate the capability in `specs/capabilities/index.yaml`.
3. Read that capability's normative spec.
4. Read the relevant workflow in `.agents/skills/`.
5. Audit the canonical owner and its tests before editing.
6. Modify the canonical owner only; preserve documented compatibility shims.
7. Run targeted tests, then the canonical `scripts/verify.ps1` or `scripts/verify.sh` gate.
8. Produce a ChangeManifest and TestReceipt conforming to `specs/contracts/`.
9. Promote stable, reviewed results to `evidence/`; keep raw output in `var/` or `runs/`.

Current truth is in `docs/context/`. Reusable guidance is in `knowledge/`. Historical
documents under `docs/legacy/` are not current project truth.
