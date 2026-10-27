# CGNK Refactor Inventory

## Repository Artifact Inventory

- Source: `src/`, `tests/`, `scripts/`, and executable configuration.
- Spec: `specs/` contract and module documents.
- Knowledge: `knowledge/`, with existing issue memory retained and linked during safe migration.
- Evidence: reviewed records under `evidence/`; existing `docs/mvp_product_validation.md`
  is classified as prior validation input pending commit-bound promotion.
- Runtime: ignored `runs/`, `var/`, logs, recordings, indexes, databases, caches, and temporary transcripts.
- Legacy: `docs/legacy/`, `ai_context/`, and historical compatibility paths identified below.
- Unknown: historical root tooling and packaging helpers remain classified by their current
  tracked use; none were deleted without proof.

## Capability Inventory

Nine production capabilities are registered in `specs/capabilities/index.yaml`: Twitch
Capture, Processing Pipeline, Creator Library, Moment Lifecycle, Retrieval, Grounded
Conversation, Clip Rendering, Review, and Feedback.

## Legacy Import Graph

| Legacy path | Still imported | Canonical replacement | Type | Action |
|---|---|---|---|---|
| `acfv.interest` | GUI adapter | `acfv.main_window` | COMPATIBILITY | Preserve forwarding layer |
| `acfv.features` | GUI, logging, tests | split UI helpers / backend services | ACTIVE | Preserve; no bulk move |
| `acfv.processing` | backend, steps, UI, tests | step/provider modules where available | ACTIVE | Preserve |
| `acfv.arc` | GUI settings and legacy pipeline | canonical backend/pipeline | ACTIVE | Preserve pending migration |

No source path met the DEAD rule (no imports, entry point, tests, or registry dependency).

## Duplicate Truth Audit

| Area | Classification | Finding |
|---|---|---|
| Config | Needs Future Migration | ConfigManager, settings YAML, provider adapter, CLI YAML, and compatibility keys coexist; new code should use documented canonical adapters. |
| Models | Canonical | Creator/Source/Recording/Clip/Feedback models are owned by `acfv.library.models`; Moment by `acfv.moments.models`. |
| Pipeline | Canonical + Compatibility | backend service → pipeline orchestrator → modular pipeline; old backend retains forwarding or auxiliary GUI functions. |
| Search | Canonical | `HybridRetrievalService`; conversation and adapters consume it. |
| Render | Canonical | `backend.service.render_review_clip` adapts the existing renderer; `ClipService` consumes it. |
| Runtime | Canonical | backend job state plus `work/runtime` summaries; product state remains in LibraryRepository. |

## Config Source Audit

- Packaging dependency truth: `pyproject.toml`.
- Canonical application compatibility API: `acfv.config.config.ConfigManager`.
- Canonical pipeline/provider overrides: CLI YAML through `_YamlConfigAdapter` and
  `acfv.providers.config`.
- Defaults/examples: `src/acfv/config/default.yaml`, `config/audio_routing.yaml.example`,
  `src/acfv/config/stream_monitor.example.yaml`, and `*.example` files.
- Secrets: local `.env`, `config.txt`, token/key files; ignored and forbidden from Git.
- Legacy compatibility: `src/acfv/config/config/`, `src/acfv/configs/`, modular pipeline
  JSON, and old uppercase keys. Do not add new consumers to these paths.
