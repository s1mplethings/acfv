# Agent Entry (paste this at the start of any agent session)

## MUST READ
- docs/00_overview.md
- docs/10_workflow.md
- docs/20_conventions.md
- ai_context/README.md
- ai_context/problem_registry.md
- specs/templates/task_card.md

## HARD RULES
- Smallest change set.
- Do NOT delete/weaken tests.
- Do NOT change public API unless Task Card allows.
- If behavior changes, update specs + tests.

## REQUIRED END STATE
- `bash scripts/verify.sh` exits with code 0.
- Write a run report to: `ai_context/runs/<timestamp>/result.md`
