import re
from pathlib import Path
ROOT = Path(".")
files = [p for p in ROOT.rglob("*.py") if ".venv" not in p.parts and "site-packages" not in p.parts]
rules = [
    (re.compile(r"\bfrom\s+tools\b"), "from acfv.tools"),
    (re.compile(r"\bimport\s+tools\b"), "from acfv from acfv import tools"),
    (re.compile(r"\bfrom\s+config\b"), "from acfv.config"),
    (re.compile(r"\bimport\s+config\b"), "from acfv from acfv import config"),
]
changed = 0
for f in files:
    s = f.read_text(encoding="utf-8")
    s2 = s
    for pat, rep in rules:
        s2 = pat.sub(rep, s2)
    if s2 != s:
        f.write_text(s2, encoding="utf-8")
        changed += 1
print(f"[acfv] rewritten files: {changed}")
