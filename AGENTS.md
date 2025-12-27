# Agent Scope

These instructions limit what an AI coding agent should read/modify in this repo.

## Default scope
- Allowed read/write: src/acfv/, tools/, README.md, requirements.txt, pyproject.toml, config.txt, .env.example
- Allowed read-only: docs or markdown files in the repo root

## Out of scope (do not read unless explicitly asked)
- dist/, build/, clips/, var/, processing/, logs/, thumbnails/, artifacts/, assets/
- src/acfv/data/nltk_data/
- secrets/ or any *.key/*.pem/*.secret.json/*.local.json

## Expansion rule
If a change requires files outside the default scope, ask the user to confirm the extra paths first.
