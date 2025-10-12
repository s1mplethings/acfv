# 1) 新建工作分支
git switch -c refactor/finish-structure

# 2) 归并目录与脚本（存在才移动）
for d in processing modules services workers; do
  [ -d "$d" ] && git mv -k "$d" src/acfv/ && echo "moved dir: $d"
done

for f in utils.py subprocess_utils.py error_handler.py warning_manager.py \
         main_logging.py safe_callbacks.py downloader.py indexer.py \
         clip_video.py launcher.py main_window.py main.py app.py; do
  [ -f "$f" ] && git mv -k "$f" src/acfv/ && echo "moved file: $f"
done

git commit -m "refactor: move top-level code into src/acfv" || true

# 3) 迁移并取消跟踪已提交的大文件（模型/可执行/视频等）
mkdir -p artifacts/large
for pat in '*.pt' '*.pth' '*.bin' '*.onnx' '*.exe' '*.mp4' '*.avi' '*.mkv'; do
  while IFS= read -r -d '' f; do
    mkdir -p "artifacts/large/$(dirname "$f")"
    git rm --cached -f "$f" >/dev/null 2>&1 || true
    mv -f "$f" "artifacts/large/$f"
    echo "relocated: $f"
  done < <(git ls-files -z "$pat" 2>/dev/null || true)
done

# 4) 忽略 artifacts/ 与常见大文件
printf '%s\n' \
  'artifacts/large/' \
  '*.pt' '*.pth' '*.bin' '*.onnx' '*.exe' '*.mp4' '*.avi' '*.mkv' \
  >> .gitignore

git add -A
git commit -m "chore: relocate large artifacts and update .gitignore" || true

# 5) （如需）补上 CLI 脚本入口
if ! grep -q '^\[project\.scripts\]' pyproject.toml 2>/dev/null; then
  printf '\n[project.scripts]\nacfv = "acfv.cli:main"\n' >> pyproject.toml
  git add pyproject.toml
  git commit -m "chore: add console script acfv" || true
fi

# 6) 推送并准备开 PR
git push -u origin refactor/finish-structure
