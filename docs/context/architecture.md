# Current Architecture

The actual dependency direction is:

```text
GUI / CLI adapters
  -> canonical capability services
  -> repositories, domain objects, and existing backend
  -> pipeline, providers, steps, and infrastructure
```

Product capabilities live in `library`, `moments`, `retrieval`, `conversation`, `clips`,
and `feedback`. They consume canonical pipeline artifacts and backend services; they do
not duplicate the processing pipeline. The processing engine remains `backend`,
`pipeline`, `modular`, `steps`, and `providers`, with the ten-stage flow documented in
`docs/repo_map.md`.

The optional Creator-Adaptive Understanding layer precedes product consumers. It fuses
provider observations through `CreatorIdentityService`, builds WHO-only voice profiles,
stores provenance-gated speech/lexicon memory, and records adaptive ASR comparisons in
shadow mode. Generic ASR stays authoritative and is always the fallback. See
`docs/creator-adaptive-understanding-architecture.md`.

GUI and CLI are adapters, never capability owners. Transitional `interest`, `features`,
`processing`, and `arc` imports remain where current runtime or tests require them.
