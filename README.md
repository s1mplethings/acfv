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



- **后台守护（StreamGet 录制）**  



  ```bash



  acfv stream-monitor



  # 指定配置文件

  acfv stream-monitor -c var/settings/stream_monitor.yaml



  ```  



首次运行会在 `var/settings/stream_monitor.yaml` 中复制模板；编辑 `targets` 列表后即可常驻后台轮询并通过 `streamget + ffmpeg` 自动落盘，可配合 systemd / pm2 / 计划任务运行。

如果更偏好图形化管理，可执行 `acfv stream-monitor-ui` 打开 PyQt 配置面板，或在主 GUI 新增的 “直播监控” 标签中直接操作。该标签页会实时显示各房间在线/录制状态，并将详细日志写入 `var/logs/stream_monitor.log`，还会在 Twitch 直播结束后自动调用 TwitchDownloaderCLI 抓取弹幕，生成与回放同目录的 `_chat.json`。







### 依赖与引用



- 需预装 `ffmpeg`、Python 3.9+，以及 `pip install -r requirements.txt`。



- 首次运行时会自动下载 [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader) 到 `var/tools/`，若失败可手动放入 PATH 或程序目录。



- Twitch Helix API：`https://api.twitch.tv/helix/users` 与 `https://api.twitch.tv/helix/videos` 用于获取用户与 VOD 列表。







### 获取 Token 及 VOD 数据



- **Hugging Face Token**：打开 <https://huggingface.co/settings/tokens>，点击 “New token”，选择 `Read` 权限，将令牌写入 `secrets/huggingface_token.txt`（或在 GUI 的 Secrets 页填写）。



- **Twitch Client ID & OAuth Token**：



  1. 访问 <https://dev.twitch.tv/console/apps> 创建应用，记录 Client ID 与 Client Secret。



  2. 使用 client_credentials 获取 App Access Token：



     ```bash



     curl -X POST "https://id.twitch.tv/oauth2/token" ^



       -H "Content-Type: application/x-www-form-urlencoded" ^



       -d "client_id=<CLIENT_ID>&client_secret=<CLIENT_SECRET>&grant_type=client_credentials"



     ```



     将返回 JSON 中的 `access_token` 填入 OAuth Token。



- **手动使用 TwitchDownloaderCLI**：若自动下载失败，可到 <https://github.com/lay295/TwitchDownloader/releases> 获取 Windows x64 CLI，将 `TwitchDownloaderCLI.exe` 放入 `var/tools/` 或 PATH 中，并执行：



  ```bash



  TwitchDownloaderCLI.exe videodownload --id <VOD_ID> -o video.mp4



  TwitchDownloaderCLI.exe chatdownload  --id <VOD_ID> -o chat.json --format json



  ```







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



- **Background Stream Monitor**  



  ```bash



  acfv stream-monitor



  # custom config path

  acfv stream-monitor -c var/settings/stream_monitor.yaml



  ```  



On first run the service copies a template to `var/settings/stream_monitor.yaml`; edit the `targets` list and keep the command alive (systemd/nohup/pm2) to poll and record via `streamget + ffmpeg`.

Prefer a GUI? Run `acfv stream-monitor-ui` or switch to the new “Stream Monitor” tab inside the main app. The tab mirrors the standalone UI, streams live status updates, writes detailed logs to `var/logs/stream_monitor.log`, and—when Twitch archives the stream—automatically calls TwitchDownloaderCLI to grab chat logs beside the recorded video.







### Dependencies & Attribution

- Install `ffmpeg`, Python 3.9+, and run `pip install -r requirements.txt`.

- On first launch ACFV will download [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader) into `var/tools/`; if that fails, place the binary manually on your PATH or beside the app.

- Twitch Helix endpoints (`https://api.twitch.tv/helix/users`, `https://api.twitch.tv/helix/videos`) power user and VOD discovery.



### Token & VOD Guide

- **Hugging Face Token**: Visit <https://huggingface.co/settings/tokens>, create a “New token” with `Read` scope, then store it in `secrets/huggingface_token.txt` or via the GUI Secrets tab.

- **Twitch Client ID & OAuth Token**:

  1. Go to <https://dev.twitch.tv/console/apps>, create an app, and note the Client ID/Secret.

  2. Request an App Access Token with the client credentials grant:

     ```bash

     curl -X POST "https://id.twitch.tv/oauth2/token" \

       -H "Content-Type: application/x-www-form-urlencoded" \

       -d "client_id=<CLIENT_ID>&client_secret=<CLIENT_SECRET>&grant_type=client_credentials"

     ```

     Copy the `access_token` field into the OAuth Token input.

- **Manual TwitchDownloaderCLI**: If auto-install fails, download the Windows x64 CLI from <https://github.com/lay295/TwitchDownloader/releases>, put `TwitchDownloaderCLI.exe` into `var/tools/` or your PATH, and run:

  ```bash

  TwitchDownloaderCLI.exe videodownload --id <VOD_ID> -o video.mp4

  TwitchDownloaderCLI.exe chatdownload  --id <VOD_ID> -o chat.json --format json

  ```



### Usage Principles



- ACFV is MIT-licensed; the author kindly asks that you keep usage to personal, internal, or other non-direct-commercial contexts.



- For commercial deployment, conduct your own compliance review and credit [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloader).



- Do not commit real credentials; rely on the `secrets/*.example` templates.



