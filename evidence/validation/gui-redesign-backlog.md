# GUI_REDESIGN_BACKLOG

This pass intentionally made no GUI code changes. Native launch reached the main window and the
existing automated GUI/service contracts remain in the release suite.

| Category | Problem | User impact | Evidence | Suggested future direction |
|---|---|---|---|---|
| Library Browsing | Library eligibility and transcript quality are not summarized per Creator. | Users may assume a short engineering sample is a fully validated Library. | Q8Pilot and holdout are each only about 15 minutes. | Add non-blocking quality badges in a future GUI pass. |
| Search Experience | Evidence-only versus grounded-LLM state is easy to miss. | Users may read a retrieved excerpt as a generated factual answer. | Conversation validation used evidence-only mode. | Make runtime mode visually explicit. |
| Review Workflow | Duplicate renders are not visually grouped. | Duplicate accepted outputs can look like independent evidence. | The two Q8 clip rows have the same SHA-256. | Group by media hash/event anchor. |
| Subtitle Editing | Translation-provider coverage is not visible before render. | Users may expect Japanese translation although only Argos `en -> zh` is installed. | Provider audit. | Show source/direction/provider readiness. |
| Error Messaging | Stale artifact roots rely on a stable fallback outside the recorded DB path. | Recovery may fail after a drive move without a clear explanation. | Six dogfood rows contain stale `E:` artifact roots; stable artifacts exist on `F:`. | Surface path remap guidance. |


## 2026-10-11 Generalization Quality Repair

- GUI visual redesign changes = 0.
- Smoke contracts passed for startup composition, Creator/Library switching, Conversation scope, clip review, and subtitle variant loading.
- Future redesign should expose portable artifact-locator health, transcript classification, and translation-provider readiness without changing the current workflow in this pass.
