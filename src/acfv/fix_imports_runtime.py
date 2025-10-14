import re
from pathlib import Path
RENAME = {
    r"\bfrom\s+utils\s+import\b": "from acfv.utils import",
    r"\bimport\s+utils\b": "from acfv import utils",
    r"\bfrom\s+subprocess_utils\s+import\b": "from acfv.subprocess_utils import",
    r"\bimport\s+subprocess_utils\b": "from acfv import subprocess_utils",
    r"\bfrom\s+error_handler\s+import\b": "from acfv.error_handler import",
    r"\bfrom\s+warning_manager\s+import\b": "from acfv.warning_manager import",
    r"\bfrom\s+main_logging\s+import\b": "from acfv.main_logging import",
    r"\bfrom\s+safe_callbacks\s+import\b": "from acfv.safe_callbacks import",
}

def rewrite_text(text: str) -> str:
    for pat, rep in RENAME.items():
        text = re.sub(pat, rep, text)
    return text

def run_fix(dry_run: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    changed = 0
    for p in root.rglob("*.py"):
        if "src/acfv/__pycache__" in str(p):
            continue
        old = p.read_text(encoding="utf-8", errors="ignore")
        new = rewrite_text(old)
        if new != old:
            if dry_run:
                print("[dry] would fix:", p)
            else:
                p.write_text(new, encoding="utf-8")
                print("fixed:", p)
            changed += 1
    print("done. files changed:", changed)
