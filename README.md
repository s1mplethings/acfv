# ACFV

ACFV (Automated Clip Finder & Video Toolkit) helps creators turn long-form streams into highlights by combining Twitch VOD downloads, chat analysis, interest scoring, and automated clipping.  
ACFV（自动剪辑工具链）通过整合 Twitch 录像下载、聊天分析、兴趣评分与自动剪辑，让长直播快速生成精彩片段。

---

## 简体中文说明

### 项目亮点
- 图形界面一键完成 VOD 下载、弹幕抓取、自动剪辑与结果预览。
- 阶段化处理管线：校验 → 聊天提取 → 多模态兴趣分析 → 生成剪辑。
- 支持自定义权重、窗口长度、结果上限，兼容旧版 `config.txt` 配置。
- 下载模块集成 [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader) 与 Twitch Helix API，可同时获取视频与聊天。
- 输出统一存放在 `var/` 目录，便于迁移、备份或重置。

### 环境要求
- Windows 10 / Linux / macOS，建议 16 GB 内存及以上。
- Python 3.9+，具备 pip 或其他包管理器。
- [ffmpeg](https://ffmpeg.org/) 已加入系统 `PATH`。
- [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader/releases) 可在终端直接调用。
- 可用的 Twitch Helix API Client ID 与 OAuth Token。
- `requirements.txt` 中列出的 Python 依赖（PyTorch、Whisper、PyQt5 等）。

### 安装步骤
1. 取得项目代码：
   ```bash
   git clone https://example.com/your/acfv.git
   cd acfv
   ```
2. （可选）创建虚拟环境：
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate          # Windows
   source .venv/bin/activate         # Linux/macOS
   ```
3. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
4. 检查必备外部工具：
   ```bash
   ffmpeg -version
   TwitchDownloaderCLI.exe --help
   ```
5. 可选的开发模式安装：
   ```bash
   pip install -e .
   ```

### Twitch 凭证配置
1. 前往 <https://dev.twitch.tv/console/apps> 创建应用，记录 Client ID。
2. 通过 OAuth 流程生成访问令牌（可参考官方指引或第三方工具）。
3. 复制 `secrets/twitch_credentials.json.example` 为 `secrets/twitch_credentials.json` 并填写：
   ```json
   {
     "twitch_client_id": "your_client_id",
     "twitch_oauth_token": "your_token",
     "twitch_username": "channel_name"
   }
   ```
4. 也可在 GUI 的「Twitch 下载」页输入后保存设置。
5. 其他运行参数可在 `config.txt` 或 GUI 设置页调整，最终写入 `var/settings/config.json`。

### 使用方式
#### 启动图形界面
```bash
python -m acfv.cli gui
# 或在安装 console_scripts 后：
acfv gui
```
操作流程：
1. 在「Twitch 下载」页填写 Client ID、OAuth Token 和待抓取的主播用户名。
2. 点击"获取 VOD"并选择需要的录像，随后触发：
   - `TwitchDownloaderCLI.exe videodownload --id <VOD_ID> -o <video_path>`
   - `TwitchDownloaderCLI.exe chatdownload --id <VOD_ID> -o <chat_path> --format json`
3. 下载完成后会自动回填到主界面，点击"运行管线"启动自动剪辑。
4. 结果展示于「Results」页，剪辑文件保存在 `var/processing/output_clips/`（或自定义目录）。

#### 命令行管线
```bash
python -m acfv.cli.pipeline clip --url https://www.twitch.tv/videos/<VOD_ID> --out-dir runs/out
# 处理本地文件：
python -m acfv.cli.pipeline clip --url path/to/video.mp4 --out-dir runs/out
```
参数说明：
- `--url`：Twitch VOD 链接或本地文件路径。
- `--out-dir`：导出剪辑的目标目录。
- `--cfg`：可选 YAML 配置文件，用于覆盖默认设置。

管线会调用 `https://api.twitch.tv/helix/users` 与 `https://api.twitch.tv/helix/videos` 获取信息，并执行音频特征提取、兴趣评分、剪辑导出。日志记录在 `processing.log`。

### 运行目录
- `var/settings/`：图形界面保存的运行配置。
- `var/secrets/`：运行时产生的凭证（请勿提交版本库）。
- `var/processing/`：日志、缓存、字幕与输出剪辑。
- `thumbnails/`：自动生成的封面缩略图。
可通过删除 `var/` 重置环境，或设置 `ACFV_STORAGE_ROOT` 指向自定义路径。

### 外部调用与地址
- `TwitchDownloaderCLI.exe`：<https://github.com/lay295/TwitchDownloader>
- Twitch Helix API：
  - `https://api.twitch.tv/helix/users?login=<username>`
  - `https://api.twitch.tv/helix/videos?user_id=<id>&type=archive&first=20`
- `ffmpeg`：<https://ffmpeg.org/>

### 使用与合规
- 项目遵循 MIT License；作者请求仅在学习、研究或非直接商业化场景中使用。如需商业用途，请自行评估合规性并承担责任。
- 遵守 Twitch 服务条款，批量抓取时适当控制频率，避免触发限流。
- 使用 `.example` 模板管理凭证，不要在公开仓库提交真实密钥。

### 故障排查
- **GUI 无法启动**：确认 PyQt5 与 GUI 依赖已安装（`pip install -r requirements.txt`）。
- **下载失败**：检查 Client ID/OAuth Token、`TwitchDownloaderCLI.exe` 与 `ffmpeg` 是否可用。
- **剪辑结果为空**：调低兴趣阈值、检查视频长度，或查看 `processing.log` 获取错误详情。

### 贡献
欢迎通过 Issue 或 Pull Request 分享建议。提交前可运行：
```bash
python tools/scan_secrets.py
```
确保未误提交敏感信息。

---

## English Guide

### Highlights
- Desktop GUI orchestrates VOD download, chat capture, auto clipping, and result preview.
- Stage-based pipeline: validate → chat extraction → multimodal interest scoring → clip generation.
- Tunable weights, window length, and clip caps; backward-compatible with the legacy `config.txt`.
- Twitch ingestion uses [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader) and the Twitch Helix API, fetching both video and chat.
- Runtime data is centralized under `var/` for easy backup, migration, or cleanup.

### System Requirements
- Windows 10 / Linux / macOS with at least 16 GB RAM recommended.
- Python 3.9+ and pip (or an equivalent package manager).
- [ffmpeg](https://ffmpeg.org/) available on the `PATH`.
- [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader/releases) accessible from the terminal.
- Valid Twitch Helix API Client ID and OAuth token.
- Python dependencies listed in `requirements.txt` (PyTorch, Whisper, PyQt5, etc.).

### Installation
```bash
git clone https://example.com/your/acfv.git
cd acfv
python -m venv .venv            # optional virtualenv
.venv\Scripts\activate          # Windows
# or
source .venv/bin/activate       # Linux/macOS
pip install -r requirements.txt
ffmpeg -version                 # verify ffmpeg
TwitchDownloaderCLI.exe --help  # verify Twitch Downloader
pip install -e .                # optional editable install
```

### Twitch Credentials
1. Create an app at <https://dev.twitch.tv/console/apps> and note the Client ID.
2. Generate an OAuth token using the official flow or a trusted helper.
3. Copy `secrets/twitch_credentials.json.example` to `secrets/twitch_credentials.json`:
   ```json
   {
     "twitch_client_id": "your_client_id",
     "twitch_oauth_token": "your_token",
     "twitch_username": "channel_name"
   }
   ```
4. The GUI's "Twitch Download" tab can also store these values.
5. Additional runtime options can be adjusted in `config.txt` or via the GUI, ultimately persisted to `var/settings/config.json`.

### Usage
#### Launch the GUI
```bash
python -m acfv.cli gui
# or
acfv gui
```
Workflow:
1. Enter your Client ID, OAuth token, and broadcaster usernames on the "Twitch Download" tab.
2. Fetch and select desired VODs; the app triggers:
   - `TwitchDownloaderCLI.exe videodownload --id <VOD_ID> -o <video_path>`
   - `TwitchDownloaderCLI.exe chatdownload --id <VOD_ID> -o <chat_path> --format json`
3. Once downloads finish, launch "Run Pipeline" to analyze and clip.
4. Results appear on the "Results" tab and files land in `var/processing/output_clips/` (or your configured directory).

#### Command-Line Pipeline
```bash
python -m acfv.cli.pipeline clip --url https://www.twitch.tv/videos/<VOD_ID> --out-dir runs/out
# Local media:
python -m acfv.cli.pipeline clip --url path/to/video.mp4 --out-dir runs/out
```
Options:
- `--url`: Twitch VOD URL or local media path.
- `--out-dir`: Destination folder for exported clips.
- `--cfg`: Optional YAML config overriding defaults.

The CLI will hit `https://api.twitch.tv/helix/users` and `https://api.twitch.tv/helix/videos`, then extract audio features, score segments, and export clips. See `processing.log` for runtime diagnostics.

### Runtime Layout
- `var/settings/`: merged GUI settings and last-used parameters.
- `var/secrets/`: runtime credential snapshots (keep out of version control).
- `var/processing/`: logs, cached downloads, transcripts, exported clips.
- `thumbnails/`: generated cover images.
Delete `var/` to reset, or set `ACFV_STORAGE_ROOT` to relocate runtime data.

### External Services & Links
- `TwitchDownloaderCLI.exe`: <https://github.com/lay295/TwitchDownloader>
- Twitch Helix API endpoints:
  - `https://api.twitch.tv/helix/users?login=<username>`
  - `https://api.twitch.tv/helix/videos?user_id=<id>&type=archive&first=20`
- `ffmpeg`: <https://ffmpeg.org/>

### Usage & Compliance
- Code is released under MIT License. The author requests non-commercial, research, or hobby usage unless you've completed your own compliance review for commercial deployments.
- Follow Twitch Terms of Service and respect rate limits; insert delays when scraping in bulk.
- Never commit real credentials--use the provided `.example` templates.

### Troubleshooting
- **GUI fails to start**: ensure PyQt5 and dependencies are installed via `pip install -r requirements.txt`.
- **Downloads fail**: verify Client ID/OAuth token and confirm both `TwitchDownloaderCLI.exe` and `ffmpeg` are available on the `PATH`.
- **No clips exported**: adjust scoring thresholds, verify video length, and check `processing.log` for stack traces.

### Contributing
Issues and pull requests are welcome. Before submitting, you may run:
```bash
python tools/scan_secrets.py
```
to confirm no sensitive data is included.
