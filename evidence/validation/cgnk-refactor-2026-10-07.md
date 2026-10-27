# CGNK Refactor Validation — 2026-10-07

## Source identity

- Tested commit: `83dfd7db536be342f096af0aab3759201c873271`.
- Base: `2b219671f8070185d6114a9f70e2a4313a3135c6`.
- Branch: `refactor/cgnk-project-structure`.
- Environment: Windows 11, Python 3.12.3, PowerShell.

## Commands and results

| Command | Result |
|---|---|
| `python -m compileall -q src` | PASS |
| `python -m acfv.cli --help` | PASS |
| `python -m acfv.cli gui --help` | PASS |
| `python -m acfv.cli pipe clip --help` | PASS |
| `python -m pytest -q` | PASS — 209 tests, 244 warnings |
| full pytest with coverage for six Product Layer packages | PASS — 209 tests, 83% total |
| `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1` | PASS — 209 tests, contract checks PASS |
| `bash scripts/verify.sh` through WSL Ubuntu | NOT EVALUATED — WSL virtual disk mount failed before script start |

The 209 total contains the original 201 tests plus eight CGNK repository guard tests.
Warnings are existing dependency and deprecation warnings. No tests were skipped.

## Guard evidence

- Architecture dependency direction: PASS.
- Gitignore source/project-truth protection: PASS.
- Tracked secret scan: PASS after sanitizing one secret-shaped legacy example.
- Capability registry integrity and unique owners: PASS.
- CGNK manifest path integrity: PASS.
- Five agent navigation tasks: PASS.
- Developer Skill metadata/workflow integrity: PASS.
- ChangeManifest/TestReceipt schema integrity: PASS.

## Behavior and limitations

No file under `src/acfv/` was modified. Creator Library, Moments, Retrieval,
Conversation, rendering/re-render, Review, Feedback, GUI/CLI contracts, real FFmpeg
integration tests, and persistence E2E remain covered by the passing suite.

This evidence does not claim MVP readiness. The 10-recording / 20+ hour human dogfood
gate and live-before-stream-end segmented/incremental ASR plus Live Search remain open.
The WSL failure is recorded in `docs/issue_memory/problem_registry.md`; Windows remains
the canonical first-class environment.
