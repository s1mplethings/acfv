# Conventions

- Keep changes small; prefer incremental PRs.
- Do not delete/weaken tests to "make things pass".
- If public API changes, update specs and tests.
- All automation must go through verify（Linux/macOS：`bash scripts/verify.sh`；Windows：`powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`）。
