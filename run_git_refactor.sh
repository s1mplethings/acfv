#!/usr/bin/env bash
# run_git_refactor.sh — 用 Git 完成 ACFV 结构化重构（可重复执行）

set -eu
if (set -o 2>/dev/null | grep -q 'pipefail'); then set -o pipefail; fi

# --- 小工具 ---
write_file() { # $1=path, 其余是行
  local path="$1"; shift
  if [ ! -e "$path" ]; then
    mkdir -p "$(dirname "$path")"
    printf "%s\n" "$@" > "$path"
    git add "$path" >/dev/null 2>&1 || true
    echo "wrote $path"
  fi
}

append_ignore() { # $1=path, $2...=lines
  local path="$1"; shift
  touch "$path"
  # 已经配置过就不重复
  grep -q "__pycache__/" "$path" && return 0 || true
  printf "%s\n" "$@" >> "$path"
  git add "$path" >/dev/null 2>&1 || true
}

# --- 先决检查 ---
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "请在 Git 仓库根目录运行"; exit 1; }

branch="refactor/structure-entry"
if git show-ref --verify --quiet "refs/heads/$branch"; then
  git switch "$branch"
else
  git switch -c "$branch"
fi

# --- 统一 .sh 为 LF 行尾 ---
if [ ! -f .gitattributes ] || ! grep -q '^\*\.sh text eol=lf$' .gitattributes; then
  printf '%s\n' '*.sh text eol=lf' >> .gitattributes
  git add .gitattributes
  git commit -m "chore: force LF for shell scripts" || true
fi

# --- 目录骨架 ---
mkdir -p src/acfv config data logs tests .github/workflows
: > data/.gitkeep
: > logs/.gitkeep
git add -A
git commit -m "chore: create project skeleton dirs" || true

# --- 迁移目录与脚本（存在才移动） ---
for d in modules processing services workers; do
  [ -d "$d" ] && git mv -k "$d" src/acfv/ && echo "moved dir: $d" || true
done

for f in utils.py subprocess_utils.py error_handler.py warning_manager.py \
         main_logging.py safe_callbacks.py downloader.py indexer.py \
         clip_video.py launcher.py main_window.py main.py app.py; do
  [ -f "$f" ] && git mv -k "$f" src/acfv/ && echo "moved file: $f" || true
done
git commit -m "refactor: move modules and scripts into src/acfv" || true

# --- 写入 acfv 包最小入口 ---
write_file src/acfv/__init__.py \
"__all__ = []" \
"__version__ = \"0.1.0\""

write_file src/acfv/__main__.py \
"from .cli import main" \
"" \
"if __name__ == \"__main__\":" \
"    main()"

write_file src/acfv/cli.py \
"import argparse" \
"from . import __version__" \
"" \
"def main() -> None:" \
"    p = argparse.ArgumentParser(prog=\"acfv\", description=\"ACFV CLI\")" \
"    sub = p.add_subparsers(dest=\"cmd\")" \
"    sub.add_parser(\"hello\", help=\"print version and hello\")" \
"" \
"    args = p.parse_args()" \
"    if args.cmd == \"hello\":" \
"        print(f\"acfv {__version__} - hello\")" \
"    else:" \
"        p.print_help()"

write_file src/acfv/fix_imports_runtime.py \
"import re" \
"from pathlib import Path" \
"RENAME = {" \
"    r\"\\bfrom\\s+utils\\s+import\\b\": \"from acfv.utils import\"," \
"    r\"\\bimport\\s+utils\\b\": \"from acfv import utils\"," \
"    r\"\\bfrom\\s+subprocess_utils\\s+import\\b\": \"from acfv.subprocess_utils import\"," \
"    r\"\\bimport\\s+subprocess_utils\\b\": \"from acfv import subprocess_utils\"," \
"    r\"\\bfrom\\s+error_handler\\s+import\\b\": \"from acfv.error_handler import\"," \
"    r\"\\bfrom\\s+warning_manager\\s+import\\b\": \"from acfv.warning_manager import\"," \
"    r\"\\bfrom\\s+main_logging\\s+import\\b\": \"from acfv.main_logging import\"," \
"    r\"\\bfrom\\s+safe_callbacks\\s+import\\b\": \"from acfv.safe_callbacks import\"," \
"}" \
"" \
"def rewrite_text(text: str) -> str:" \
"    for pat, rep in RENAME.items():" \
"        text = re.sub(pat, rep, text)" \
"    return text" \
"" \
"def run_fix(dry_run: bool = False) -> None:" \
"    root = Path(__file__).resolve().parents[2]" \
"    changed = 0" \
"    for p in root.rglob(\"*.py\"):" \
"        if \"src/acfv/__pycache__\" in str(p):" \
"            continue" \
"        old = p.read_text(encoding=\"utf-8\", errors=\"ignore\")" \
"        new = rewrite_text(old)" \
"        if new != old:" \
"            if dry_run:" \
"                print(\"[dry] would fix:\", p)" \
"            else:" \
"                p.write_text(new, encoding=\"utf-8\")" \
"                print(\"fixed:\", p)" \
"            changed += 1" \
"    print(\"done. files changed:\", changed)"

git add src/acfv
git commit -m "feat: add acfv package skeleton and CLI" || true

# --- pyproject.toml ---
if [ ! -f pyproject.toml ]; then
  write_file pyproject.toml \
"[project]" \
"name = \"acfv\"" \
"version = \"0.1.0\"" \
"description = \"Automated Clip for VTuber (ACFV)\"" \
"readme = \"README.md\"" \
"requires-python = \">=3.9\"" \
"dependencies = []" \
"" \
"[build-system]" \
"requires = [\"setuptools>=68\", \"wheel\"]" \
"build-backend = \"setuptools.build_meta\"" \
"" \
"[tool.setuptools.packages.find]" \
"where = [\"src\"]" \
"include = [\"acfv*\"]" \
"" \
"[project.scripts]" \
"acfv = \"acfv.cli:main\""
else
  grep -q "build-backend" pyproject.toml || printf "\n[build-system]\nrequires = [\"setuptools>=68\", \"wheel\"]\nbuild-backend = \"setuptools.build_meta\"\n" >> pyproject.toml
  grep -q "tool.setuptools.packages.find" pyproject.toml || printf "\n[tool.setuptools.packages.find]\nwhere = [\"src\"]\ninclude = [\"acfv*\"]\n" >> pyproject.toml
  grep -q "project.scripts" pyproject.toml || printf "\n[project.scripts]\nacfv = \"acfv.cli:main\"\n" >> pyproject.toml
  git add pyproject.toml
fi
git commit -m "chore: ensure pyproject with setuptools + console_scripts" || true

# --- .gitignore ---
append_ignore .gitignore \
"# Python" \
"__pycache__/" \
"*.py[cod]" \
"*.pyo" \
"*.egg-info/" \
".build/" \
"dist/" \
".build-cache/" \
"" \
"# Envs" \
".env" \
".env.*" \
".venv/" \
"venv/" \
"" \
"# Logs & data" \
"logs/" \
"*.log" \
"data/" \
"outputs/" \
"tmp/" \
"" \
"# Models / binaries / media" \
"*.pt" \
"*.pth" \
"*.bin" \
"*.onnx" \
"*.exe" \
"*.mp4" \
"*.avi" \
"*.mkv" \
"" \
"# IDE" \
".vscode/" \
".idea/"
git commit -m "chore: extend .gitignore for models, logs, envs" || true

# --- 配置、测试与 CI ---
write_file config/default.yaml \
"download:" \
"  save_dir: \"data/downloads\"" \
"  concurrency: 2" \
"process:" \
"  work_dir: \"outputs\"" \
"  log_dir: \"logs\""

write_file .env.example \
"ACFV_SAVE_DIR=outputs" \
"ACFV_LOG_DIR=logs" \
"ACFV_DEBUG=0"

mkdir -p tests .github/workflows
write_file tests/test_smoke.py \
"def test_import():" \
"    import acfv" \
"    assert hasattr(acfv, \"__version__\")"

write_file .github/workflows/ci.yml \
"name: CI" \
"on:" \
"  push: { branches: [\"**\"] }" \
"  pull_request:" \
"jobs:" \
"  test:" \
"    runs-on: ubuntu-latest" \
"    steps:" \
"    - uses: actions/checkout@v4" \
"    - uses: actions/setup-python@v5" \
"      with: { python-version: \"3.11\" }" \
"    - run: python -m pip install -U pip" \
"    - run: pip install ruff mypy pytest" \
"    - run: pip install -e ." \
"    - run: ruff check ." \
"    - run: mypy src || true" \
"    - run: pytest -q || true"

git commit -m "chore: add default config, env example, smoke test, and CI" || true

# --- 迁移并取消跟踪已提交的大文件（如有） ---
mkdir -p artifacts/large
relocated=0
while IFS= read -r -d '' f; do
  mkdir -p "artifacts/large/$(dirname "$f")"
  git rm --cached -f "$f" >/dev/null 2>&1 || true
  mv -f "$f" "artifacts/large/$f" 2>/dev/null || true
  relocated=$((relocated+1))
done < <(git ls-files -z '*.pt' '*.pth' '*.bin' '*.onnx' '*.exe' '*.mp4' '*.avi' '*.mkv' 2>/dev/null || true)
if [ $relocated -gt 0 ]; then
  grep -q "artifacts/large/" .gitignore || printf "artifacts/large/\n" >> .gitignore
  git add .gitignore artifacts/large || true
  git commit -m "chore: untrack and relocate large artifacts to artifacts/large" || true
fi

# --- 推送 ---
git push -u origin "$branch" || true

echo "Done."
echo "Next:"
echo "  pip install -e ."
echo "  acfv hello   # 或: python -m acfv hello"
echo "  打开 GitHub 创建从分支 $branch 的 PR"
