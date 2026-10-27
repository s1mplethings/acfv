---
id: acfv.product-layer-change
version: 1
scope: repository
tags: [product, service]
depends_on: [specs/capabilities/index.yaml]
risk: medium
---

# Product Layer Change

Purpose: modify Library, Moments, Retrieval, Conversation, Clips, or Feedback safely.

Inputs: capability ID, requested behavior, current spec and tests.

Outputs: canonical service change, focused tests, ChangeManifest and TestReceipt.

Dependencies: selected capability spec and `knowledge/decisions/canonical-owners.md`.

Workflow:
1. Resolve the capability through the registry and read its spec.
2. Confirm the service/repository owner and map all GUI/CLI callers.
3. Change the canonical owner; adapters must remain thin.
4. Reject duplicate repositories, search services, renderers, models, or runtime state.
5. Run unit tests, the relevant persistence/integration E2E, and the repo gate.

Verification: acceptance statements in the capability spec must map to named tests.
