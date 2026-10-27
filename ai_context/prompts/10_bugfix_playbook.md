# Bugfix Playbook

1) Reproduce with `bash scripts/verify.sh`
2) Identify minimal failing error
3) Validate likely root cause
4) Implement smallest fix
5) Add/adjust tests if needed
6) Verify again
7) Report: `ai_context/runs/<timestamp>/result.md`
8) If FAIL: append to problem_registry
