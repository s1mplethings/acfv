#!/usr/bin/env python3
"""Lightweight secret pattern scan before commit."""
import re, sys, pathlib
PATTERNS = [
    re.compile(r'sk-[0-9A-Za-z]{16,}'),  # lengthened to reduce false positives
    re.compile(r'(?i)api[_-]?key\s*[:=]\s*[0-9A-Za-z-_]{16,}'),
    re.compile(r'(?i)secret[_-]?key\s*[:=]\s*[0-9A-Za-z]{16,}'),
]
IGNORE_DIRS = {'venv', '.venv', 'secrets', 'artifacts', '.git', 'dist', '__pycache__'}
IGNORE_SUFFIXES = {'.egg-info'}
def iter_files(root: pathlib.Path):
    for p in root.rglob('*'):
        if p.is_dir():
            if p.name in IGNORE_DIRS:
                # skip walking into this directory
                continue
            # allow recursion only if not ignored
            continue
        # skip any path containing ignored directory names
        if any(part in IGNORE_DIRS for part in p.parts):
            continue
        if any(str(p).endswith(suf) for suf in IGNORE_SUFFIXES):
            continue
        if p.suffix in {'.py', '.txt', '.json', '.env'} and not p.name.endswith('.example'):
            yield p
def main():
    root = pathlib.Path('.')
    flagged = []
    for f in iter_files(root):
        try:
            text = f.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        for pat in PATTERNS:
            for m in pat.finditer(text):
                flagged.append((f, m.group(0)))
    if flagged:
        print('[acfv][secrets] Potential secrets detected:')
        for f, val in flagged:
            print(f'  - {f}: {val[:50]}')
        print('\nBlock commit. Please remove or move to secrets/.')
        return 1
    print('[acfv][secrets] No obvious secrets found.')
    return 0
if __name__ == '__main__':
    sys.exit(main())