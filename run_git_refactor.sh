# 在 Git Bash 里执行，确保当前目录是仓库根目录
# 1) 新建分支
git switch -c refactor/fold-to-src || git switch refactor/fold-to-src

# 2) 把还在根目录的目录/脚本移入 src/acfv/（存在才移动）
[ -d processing ] && git mv -k processing src/acfv/

for f in background_runtime.py clip_video.py clip_video_clean.py \
         console_disable.py error_handler.py launcher.py main_logging.py \
         rag_module.py rag_vector_database.py safe_callbacks.py silent_exit.py \
         sitecustomize.py subprocess_utils.py utils.py warning_manager.py; do
  [ -f "$f" ] && git mv -k "$f" src/acfv/ && echo "moved: $f"
done

# 可选：把构建脚本收纳到 tools/
mkdir -p tools
[ -f build_pyinstaller.bat ] && git mv -k build_pyinstaller.bat tools/
[ -f build_with_pyinstaller.py ] && git mv -k build_with_pyinstaller.py tools/

git commit -m "refactor: fold top-level scripts into src/acfv and move build tools" || true

# 3) 迁移并取消跟踪大文件（模型/可执行）
mkdir -p artifacts/large
git rm --cached -f best.pt TwitchDownloaderCLI.exe 2>/dev/null || true
[ -f best.pt ] && mv -f best.pt artifacts/large/
[ -f TwitchDownloaderCLI.exe ] && mv -f TwitchDownloaderCLI.exe artifacts/large/

# 忽略 artifacts/ 与常见大文件类型
printf '%s\n' 'artifacts/large/' '*.pt' '*.pth' '*.bin' '*.onnx' '*.exe' '*.mp4' '*.avi' '*.mkv' >> .gitignore

git add -A
git commit -m "chore: relocate large binaries to artifacts/large and update .gitignore" || true

# 4) （若还没配）补上 CLI 入口
grep -q '^\[project\.scripts\]' pyproject.toml || {
  printf '\n[project.scripts]\nacfv = "acfv.cli:main"\n' >> pyproject.toml
  git add pyproject.toml
  git commit -m "chore: add console script acfv" || true
}

# 5) 推送分支
git push -u origin refactor/fold-to-src
