---
id: acfv.repository-audit
version: 1
scope: repository
tags: [audit, architecture]
depends_on: [.cgnk/project.yaml]
risk: low
---

# Repository Audit

Purpose: classify repository truth before proposing structural changes.

Inputs: requested scope, project manifest, capability registry, Git status/import graph.

Outputs: artifact inventory, legacy matrix, duplicate-truth findings, config-source audit,
and a bounded ChangeManifest draft.

Dependencies: `docs/context/`, `docs/repo_map.md`, `specs/capabilities/index.yaml`.

Workflow:
1. Confirm branch, base, HEAD, and a clean starting state.
2. Classify Source, Spec, Knowledge, Evidence, Runtime, Legacy, and Unknown artifacts.
3. Search imports, entry points, tests, and registries before calling anything dead.
4. Identify one canonical owner for each affected capability.
5. Record unresolved items as UNKNOWN or future migration; do not delete them.

Verification: run repository guard tests and ensure the audit names concrete paths.
