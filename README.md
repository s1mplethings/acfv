<h1 align="center">
  <img src="assets/acfv-logo.svg" alt="ACFV logo" width="140"><br>
  ACFV
</h1>

<p align="center">
  Twitch Clip & Chat Toolkit<br>
  <a href="#zh">简体中文</a> · <a href="#en">English</a>
</p>

---

## <a id="zh"></a>简体中文

### 使用方式
- **图形界面**  
  ```bash
  python -m acfv.cli gui
  # 或安装 console_scripts 后：acfv gui
  ```  
  在「Twitch 下载」页填写 Client ID、OAuth Token、主播用户名，点击“获取 VOD”并选择目标后执行“下载选择”，完成后按“运行管线”生成剪辑。

- **命令行**  
  ```bash
  python -m acfv.cli.pipeline clip --url https://www.twitch.tv/videos/<VOD_ID> --out-dir runs/out
  # 处理本地文件：--url path/to/video.mp4
  ```  
  `--url` 支持 Twitch VOD 链接或本地路径，`--out-dir` 为导出目录，可用 `--cfg` 指向自定义 YAML。

### 依赖与引用
- 需要预装 `ffmpeg`、Python 3.9+，以及 `pip install -r requirements.txt`。
- 录像与弹幕下载依赖 [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader)（自行下载并放入 PATH 或程序同目录）。
- Twitch Helix API（`https://api.twitch.tv/helix/users`、`https://api.twitch.tv/helix/videos`）用于获取用户与 VOD 列表。

### 商用/自用原则
- 项目以 MIT License 开源，但作者请求仅用于个人或团队内部流程、学习研究等非直接商业化场景。
- 若计划对外商用，请自行完成合规审查，并在产品中标注使用了 [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader)。
- 请勿提交真实凭证；使用 `secrets/*.example` 模板管理配置。

---

## <a id="en"></a>English

### Usage
- **GUI**  
  ```bash
  python -m acfv.cli gui
  # or, after installing console_scripts: acfv gui
  ```  
  On the “Twitch Download” tab, enter your Client ID, OAuth token, and broadcaster handles. Fetch the VOD list, pick one, run “Download Selected”, then press “Run Pipeline” to create clips.

- **CLI**  
  ```bash
  python -m acfv.cli.pipeline clip --url https://www.twitch.tv/videos/<VOD_ID> --out-dir runs/out
  # Local media: --url path/to/video.mp4
  ```  
  `--url` accepts a Twitch VOD link or local path; `--out-dir` chooses the export folder; `--cfg` can point to a custom YAML overrides file.

### Dependencies & Attribution
- Install `ffmpeg`, Python 3.9+, and run `pip install -r requirements.txt`.
- VOD/chat downloads rely on [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader) (install it yourself and keep it on PATH or beside ACFV).
- Twitch Helix endpoints (`https://api.twitch.tv/helix/users`, `https://api.twitch.tv/helix/videos`) provide account and VOD metadata.

### Usage Principles
- ACFV is MIT-licensed; the author kindly asks that you keep usage to personal, internal, or other non-direct-commercial contexts.
- For commercial deployment, conduct your own compliance review and credit [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader).
- Do not commit real credentials; rely on the `secrets/*.example` templates.
