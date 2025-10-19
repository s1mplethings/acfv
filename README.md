# ACFV

![ACFV Logo](src/acfv/config/icon.png)

[简体中文](#简体中文) · [English](#english)

---

## 简体中文

### 使用方法
- **图形界面**  
  ```bash
  python -m acfv.cli gui
  # 或安装 console_scripts 后：acfv gui
  ```
  打开后在「Twitch 下载」页填写 Client ID、OAuth Token、主播用户名，获取目标 VOD 并点击“下载选择”；下载完成后点击“运行管线”生成剪辑。

- **命令行**  
  ```bash
  python -m acfv.cli.pipeline clip --url https://www.twitch.tv/videos/<VOD_ID> --out-dir runs/out
  # 处理本地文件：--url path/to/video.mp4
  ```
  参数说明：`--url` 为 Twitch VOD 链接或本地路径，`--out-dir` 为输出目录，可通过 `--cfg` 指定自定义 YAML 配置。

### 依赖与引用
- 外部下载工具：[`TwitchDownloaderCLI`](https://github.com/lay295/TwitchDownloader)（请自行下载并放入 PATH 或程序同目录）。
- 必备工具：`ffmpeg`、Python 3.9+、`pip install -r requirements.txt`。
- Twitch API：使用 Helix 接口（`https://api.twitch.tv/helix/users`、`https://api.twitch.tv/helix/videos`）获取视频与聊天数据。

### 商用与自用原则
- 本项目遵循 MIT License；作者请求仅将工具用于个人或团队内部流程验证、内容自用或非直接商业化目的。
- 如需对外商业化运营，请自行完成合规评估并明确标注使用了 [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader)。
- 请勿在公共仓库提交真实凭证，使用 `secrets/*.example` 模板即可。

---

## English

### Usage
- **GUI**  
  ```bash
  python -m acfv.cli gui
  # or, after installing console_scripts: acfv gui
  ```
  Fill in your Client ID, OAuth token, and target broadcaster on the “Twitch Download” tab, fetch the VOD list, choose one, then run “Download Selected”. After the assets are ready, click “Run Pipeline” to generate clips.

- **Command Line**  
  ```bash
  python -m acfv.cli.pipeline clip --url https://www.twitch.tv/videos/<VOD_ID> --out-dir runs/out
  # Local media: --url path/to/video.mp4
  ```
  Options: `--url` accepts a Twitch VOD URL or local path; `--out-dir` sets the export folder; use `--cfg` to supply a YAML override.

### Dependencies & Attribution
- External downloader: [`TwitchDownloaderCLI`](https://github.com/lay295/TwitchDownloader) (install it yourself and keep it on PATH or beside the app).
- Required tooling: `ffmpeg`, Python 3.9+, and `pip install -r requirements.txt`.
- Twitch Helix endpoints (`https://api.twitch.tv/helix/users`, `https://api.twitch.tv/helix/videos`) power user/channel lookups and VOD listings.

### Usage Principles
- Code is MIT licensed; the author kindly asks you to keep usage to personal or internal workflows, or non-direct-commercial scenarios.
- For public/commercial deployment, run your own compliance review and credit [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader).
- Never commit real credentials—rely on the `secrets/*.example` templates.
