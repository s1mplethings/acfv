# GUI Verification Receipt — 2026-10-12

Implementation: `20b9b0534f9d92ac8bdafa3b27fae887ca30a3b1`

After the final code modification, both required runs executed:

1. `python -m compileall -q src`
2. `python -m acfv.cli --help`
3. `python -m acfv.cli gui --help`
4. `python -m acfv.cli pipe clip --help`
5. `python -m acfv.cli live --help`
6. `python -m acfv.cli download --help`
7. `pytest -q`
8. `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`

| Check | Run 1 | Run 2 |
|---|---:|---:|
| compileall | PASS | PASS |
| five CLI help commands | PASS | PASS |
| direct pytest | 494 passed | 494 passed |
| verify nested pytest | 494 passed | 494 passed |
| contract checks | PASS | PASS |
| verify result | PASS | PASS |
| skipped | 0 | 0 |
| xfailed | 0 | 0 |

Focused GUI/Controller/Worker/Race/Persistence group: **51 passed**.

Native evidence:

- full workflow/result: `native-100/native-validation.json`
- real import + processing + post-processing search: `native-import-fixed/native-validation.json`
- clean checkout: `clean-worktree-final/native-validation.json`
- scaling: `visual-125/native-validation.json`, `visual-150/native-validation.json`
