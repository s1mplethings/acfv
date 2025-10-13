# fix.sh —— 无 rsync 版本（Git Bash / WSL / Linux）
# 用法：在仓库根执行：bash fix.sh
set -euo pipefail

mkdir -p src/acfv

copy_dir () {
  local SRC="$1"
  local DST="$2"
  if [ -d "$SRC" ]; then
    mkdir -p "$DST"
    # 复制包含隐藏文件在内的全部内容
    ( shopt -s dotglob nullglob; cp -a "$SRC"/* "$DST"/ || true )
  fi
}

# 1) 把顶层 tools / config 收编到包里
copy_dir tools  src/acfv/tools
copy_dir config src/acfv/config

# 2) 补 __init__.py
: > src/acfv/__init__.py
[ -d src/acfv/tools ]  && : > src/acfv/tools/__init__.py
[ -d src/acfv/config ] && : > src/acfv/config/__init__.py

# 3) 入口：__main__.py + 动态 CLI
cat > src/acfv/__main__.py <<'PY'
from .cli import main
if __name__ == "__main__":
    main()
PY

cat > src/acfv/cli.py <<'PY'
import importlib, sys
CANDIDATES = [
    ("acfv.app", "main"),
    ("acfv.main", "main"),
    ("acfv.entry", "main"),
    ("acfv.run", "main"),
    ("acfv.tools.cli", "main"),
]
def main(argv=None):
    last_err = None
    for mod, func in CANDIDATES:
        try:
            m = importlib.import_module(mod)
            f = getattr(m, func, None)
            if callable(f):
                return f()  # 让被调用方自己处理 sys.argv
        except ModuleNotFoundError:
            continue
        except Exception as e:
            last_err = e
            break
    msg = "[acfv] 未找到真实入口。请在以下任一位置提供 main():\n" + \
          "\n".join(f"  - {m}.{f}" for m, f in CANDIDATES)
    if last_err:
        msg += f"\n最近一次错误：{type(last_err).__name__}: {last_err}"
    print(msg, file=sys.stderr)
    return 1
PY

# 4) 批量重写导入：tools/config -> acfv.tools / acfv.config
cat > rewrite_imports.py <<'PY'
import re
from pathlib import Path
ROOT = Path(".")
files = [p for p in ROOT.rglob("*.py") if ".venv" not in p.parts and "site-packages" not in p.parts]
rules = [
    (re.compile(r"\bfrom\s+tools\b"), "from acfv.tools"),
    (re.compile(r"\bimport\s+tools\b"), "from acfv import tools"),
    (re.compile(r"\bfrom\s+config\b"), "from acfv.config"),
    (re.compile(r"\bimport\s+config\b"), "from acfv import config"),
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
PY
python rewrite_imports.py

# 5) 写 pyproject.toml（src 布局 + CLI 入口）
cat > pyproject.toml <<'PY'
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "acfv"
version = "0.1.0"
requires-python = ">=3.9"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]

[project.scripts]
acfv = "acfv.__main__:main"
PY

echo "==> 修改完成。下一步："
echo "   1) python -m pip install -U pip"
echo "   2) pip install -e ."
echo "   3) python -m acfv   （或 acfv）"
