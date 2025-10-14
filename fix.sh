#!/usr/bin/env bash
set -euo pipefail

# === 0) 进入你的仓库目录：按你的环境二选一 ===
# Git Bash 通常是 /d/cliper/acfv
cd /d/cliper/acfv 2>/dev/null || cd /mnt/d/cliper/acfv

# === 1) 新建修复分支 ===
git checkout -b fix/entrypoint || git checkout fix/entrypoint

# === 2) 新增入口文件 acfv.cli._entry:main 和 __main__.py ===
mkdir -p src/acfv/cli

cat > src/acfv/cli/_entry.py <<'PY'
import sys

def main(argv=None):
    """
    Console entrypoint for `acfv`.
    Usage:
        acfv [gui]
    """
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in {"-h", "--help"}:
        print("Usage: acfv [gui]")
        return 0

    cmd, *rest = argv

    if cmd == "gui":
        # Try common GUI entry locations:
        for modpath, attr in (
            ("acfv.gui", "main"),
            ("acfv.app", "main"),
            ("acfv.frontend.gui", "main"),
        ):
            try:
                module = __import__(modpath, fromlist=[attr])
                gui_main = getattr(module, attr)
                return gui_main(*rest)
            except Exception:
                continue
        print("No GUI entry found. Expected one of: acfv.gui:main / acfv.app:main / acfv.frontend.gui:main")
        return 1

    print(f"Unknown command: {cmd}")
    return 1
PY

cat > src/acfv/__main__.py <<'PY'
from acfv.cli._entry import main

if __name__ == "__main__":
    raise SystemExit(main())
PY

# 如果你还没有 GUI 入口，先放一个占位，确保能跑通
[ -f src/acfv/gui.py ] || cat > src/acfv/gui.py <<'PY'
def main(*args):
    print("GUI OK", args)
PY

# === 3) 修改 pyproject.toml 的 console script 指向 ===
# 3.1 若已有 acfv=... 就替换为 acfv.cli._entry:main
sed -i.bak -E 's|^([[:space:]]*acfv[[:space:]]*=[[:space:]]*").*(")$|\1acfv.cli._entry:main\2|I' pyproject.toml || true

# 3.2 若文件里还没有 acfv.cli._entry:main，则插入到 [project.scripts] 段（若没有该段就追加）
if ! grep -qi 'acfv\.cli\._entry:main' pyproject.toml; then
  if grep -qi '^\[project\.scripts\]' pyproject.toml; then
    awk 'BEGIN{done=0}
         {print}
         /^\[project\.scripts\]/{ if(!done){ print "acfv = \"acfv.cli._entry:main\""; done=1 } }
         END{ if(!done){ print "\n[project.scripts]\nacfv = \"acfv.cli._entry:main\"" } }' pyproject.toml > pyproject.toml.tmp
    mv pyproject.toml.tmp pyproject.toml
  else
    printf '\n[project.scripts]\nacfv = "acfv.cli._entry:main"\n' >> pyproject.toml
  fi
fi

# === 4) 提交变更 ===
git add -A
git commit -m "feat(cli): add acfv.cli._entry entrypoint and __main__; set console script" || echo "Nothing to commit."

# === 5) 开发安装并自检 ===
python -m pip install -e .
echo "---- acfv gui ----"
acfv gui || true
echo "---- python -m acfv ----"
python -m acfv || true

echo "Done. If you saw 'GUI OK', the entry works."
