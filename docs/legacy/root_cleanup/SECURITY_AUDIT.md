# Legacy Security Audit (Sanitized)

> NOT CURRENT PROJECT TRUTH.

The original historical report contained a secret-shaped example and was sanitized on
2026-10-07 so tracked history does not teach agents to preserve credential-like values.
Current policy is enforced by `tests/integration/test_cgnk_repository_guards.py`:

- secrets and local credentials remain ignored;
- tracked files are scanned for common OpenAI, Hugging Face, OAuth, and private-key forms;
- examples must use unmistakable placeholders rather than realistic token strings.

Use `docs/context/`, `knowledge/`, and the canonical verification gate for current guidance.
