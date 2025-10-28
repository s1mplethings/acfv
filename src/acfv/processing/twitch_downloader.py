# twitch_downloader.py - Twitch下载功能模块

import os
import re
import requests
import subprocess
import logging
import time
from PyQt5.QtCore import QThread, pyqtSignal, QSize
from PyQt5.QtGui import QImage, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QPushButton,
    QListWidget, QHBoxLayout, QLabel, QAbstractItemView, QGroupBox,
    QProgressBar, QMessageBox, QFileDialog, QListWidgetItem
)

from acfv.utils import safe_slug
from acfv.utils.twitch_downloader_setup import ensure_cli_on_path

ensure_cli_on_path(auto_install=True)


def sanitize_filename(name: str) -> str:
    """Return a filesystem-safe, length-limited slug for downloads."""
    return safe_slug(name, max_length=80)



def createFolderSelector(default_path="./"):
    """创建文件夹选择器组件"""
    container = QWidget()
    layout = QHBoxLayout(container)

    folder_edit = QLineEdit(default_path)
    btn_select = QPushButton("选择文件夹")

    def selectFolder():
        folder = QFileDialog.getExistingDirectory(container, "选择文件夹", default_path)
        if folder:
            folder_edit.setText(folder)

    btn_select.clicked.connect(selectFolder)
    layout.addWidget(folder_edit)
    layout.addWidget(btn_select)

    return container, folder_edit, btn_select


class TwitchDownloader:
    """Twitch视频下载器

    新增：支持进度回调(progress_callback) 和 停止标志(stop_flag_callable)
    """
    
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self._current_process = None  # 跟踪当前运行的 CLI 进程
        self._cancel_requested = False
        self._detail_progress_cb = None  # 细粒度进度回调
        self._current_vod_context = None  # (idx, total, safe_filename)
    
    def fetch_vods(self, client_id, oauth_token, usernames):
        """获取指定用户的VOD列表"""
        import time
        
        headers = {"Client-ID": client_id, "Authorization": f"Bearer {oauth_token}"}
        names = [u.strip() for u in usernames.split(",") if u.strip()]
        
        vods = []
        
        for username in names:
            logging.info(f"正在获取 {username} 的用户信息...")
            
            # 获取用户ID
            r1 = requests.get(f"https://api.twitch.tv/helix/users?login={username}", headers=headers, timeout=10)
            r1.raise_for_status()
            user_data = r1.json().get("data", [])
            
            if not user_data:
                raise Exception(f"用户不存在: {username}")
            
            user_id = user_data[0]["id"]
            
            logging.info(f"正在获取 {username} 的回放列表...")
            
            # 获取VOD列表
            r2 = requests.get(
                f"https://api.twitch.tv/helix/videos?user_id={user_id}&type=archive&first=20",
                headers=headers,
                timeout=15
            )
            r2.raise_for_status()
            
            user_vods = r2.json().get("data", [])
            for vod in user_vods:
                vod["channel"] = username
                vods.append(vod)
                
            # 小延迟避免API限制
            time.sleep(0.1)
        
        logging.info(f"获取完成，共找到 {len(vods)} 个回放")
        return vods
    
    def download_vods(self, vods, download_folder, progress_callback=None, stop_flag_callable=None, detail_progress_callback=None):
        """下载指定的VOD列表（顺序执行，支持进度回调与停止）

        progress_callback: callable(current_index:int, total:int, safe_filename:str, stage:str)
            stage 取值示例: 'start', 'video_done', 'chat_done', 'item_done'
        stop_flag_callable: 返回 True 时提前停止
        """
        results = []
        total = len(vods)
        self._cancel_requested = False
        self._detail_progress_cb = detail_progress_callback
        for idx, vod in enumerate(vods, start=1):
            # 外部请求停止
            if (stop_flag_callable and stop_flag_callable()) or self._cancel_requested:
                logging.info("检测到停止/取消请求，终止后续下载")
                if progress_callback:
                    try:
                        progress_callback(idx, total, "", 'canceled')
                    except Exception:
                        pass
                break
            try:
                # 清理文件名，避免重复
                safe_title = re.sub(r'[\\/:\*\?"<>|]', '_', vod["title"])
                timestamp = vod.get("created_at", "").replace(":", "-").replace("T", "_").rstrip("Z")
                safe_filename = f"{safe_title}_{timestamp}_{vod['id'][:8]}"
                
                video_path = os.path.join(download_folder, safe_filename + ".mp4")
                chat_path = os.path.join(download_folder, safe_filename + "_chat.html")
                
                # 检查文件是否已存在
                if os.path.exists(video_path) and os.path.exists(chat_path):
                    logging.info(f"文件已存在，跳过下载: {safe_filename}")
                    results.append((video_path, chat_path))
                    continue
                
                # 进度：开始该VOD
                if progress_callback:
                    try:
                        progress_callback(idx, total, safe_filename, 'start')
                    except Exception:
                        pass

                # 保存当前VOD上下文供子函数使用
                self._current_vod_context = (idx, total, safe_filename)

                # 下载视频（带重试机制）
                video_success = self._download_with_retry(
                    "videodownload", vod["id"], video_path, 
                    f"视频 {safe_filename}",
                    stop_flag_callable=lambda: (stop_flag_callable and stop_flag_callable()) or self._cancel_requested
                )
                
                if not video_success:
                    logging.error(f"视频下载失败: {vod['id']}")
                    if progress_callback:
                        try:
                            progress_callback(idx, total, safe_filename, 'video_failed')
                        except Exception:
                            pass
                    continue
                
                if progress_callback:
                    try:
                        progress_callback(idx, total, safe_filename, 'video_done')
                    except Exception:
                        pass

                # 下载聊天记录（带重试机制）
                chat_success = self._download_with_retry(
                    "chatdownload", vod["id"], chat_path, 
                    f"聊天记录 {safe_filename}",
                    extra_args=["--embed-images", "--bttv=true", "--ffz=true", "--stv=true"],
                    stop_flag_callable=lambda: (stop_flag_callable and stop_flag_callable()) or self._cancel_requested
                )
                
                if not chat_success:
                    logging.error(f"聊天记录下载失败: {vod['id']}")
                    # 即使聊天记录失败，视频下载成功也算部分成功
                    results.append((video_path, None))
                else:
                    results.append((video_path, chat_path))

                if progress_callback:
                    try:
                        if chat_success:
                            progress_callback(idx, total, safe_filename, 'chat_done')
                        progress_callback(idx, total, safe_filename, 'item_done')
                    except Exception:
                        pass
                
                # 下载间隔，避免API限制
                import time
                time.sleep(1)
                
            except Exception as e:
                logging.error(f"下载VOD {vod.get('id', 'Unknown')} 时出错: {e}")
                # 继续下载下一个，不中断整个流程
                continue
        
        return results
    
    def _download_with_retry(self, command_type, vod_id, output_path, description, max_retries=3, extra_args=None, stop_flag_callable=None):
        """带重试机制的下载"""
        if extra_args is None:
            extra_args = []
            
        for attempt in range(max_retries):
            try:
                logging.info(f"{description} (尝试 {attempt + 1}/{max_retries})")
                
                # 构建命令
                command = ["TwitchDownloaderCLI.exe", command_type, "--id", vod_id, "-o", output_path] + extra_args
                
                # 使用Popen来实时处理输出，自动响应覆盖提示
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                self._current_process = process
                
                # 实时读取输出并自动响应
                while True:
                    # 取消检查
                    if self._cancel_requested or (stop_flag_callable and stop_flag_callable()):
                        logging.info("收到取消信号，终止当前下载进程...")
                        try:
                            process.kill()
                        except Exception:
                            pass
                        self._current_process = None
                        return False
                    output = process.stdout.readline()
                    if output == '' and process.poll() is not None:
                        break
                    if output:
                        print(output.strip())  # 显示进度
                        # 检测到覆盖提示时自动输入o
                        if "[O] Overwrite / [R] Rename / [E] Exit:" in output:
                            process.stdin.write("o\n")
                            process.stdin.flush()
                            logging.info("自动选择覆盖文件")
                        # 解析细粒度进度
                        self._parse_and_emit_subprogress(output.strip(), command_type)
                
                # 等待进程完成
                return_code = process.wait()
                self._current_process = None
                
                if return_code == 0:
                    logging.info(f"{description} 完成")
                    return True
                else:
                    raise subprocess.CalledProcessError(return_code, command)
                
            except subprocess.TimeoutExpired:
                logging.warning(f"{description} 超时 (尝试 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(5)  # 等待5秒后重试
                continue
                
            except subprocess.CalledProcessError as e:
                logging.warning(f"{description} 失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)  # 等待5秒后重试
                continue
                
            except Exception as e:
                logging.error(f"{description} 未知错误: {e}")
                return False
        
        return False

    def cancel_current(self):
        """请求取消当前下载"""
        self._cancel_requested = True
        proc = self._current_process
        if proc and proc.poll() is None:
            try:
                logging.info("正在终止当前下载进程...")
                proc.kill()
            except Exception as e:
                logging.debug(f"终止进程时忽略错误: {e}")
        self._current_process = None
        # 通知UI取消当前细粒度阶段
        if self._detail_progress_cb and self._current_vod_context:
            idx, total, safe_filename = self._current_vod_context
            try:
                self._detail_progress_cb(idx, total, safe_filename, '已取消', 0)
            except Exception:
                pass

    # ---------------- 细粒度进度解析 -----------------
    def _parse_and_emit_subprogress(self, line: str, command_type: str):
        """解析 TwitchDownloaderCLI 输出中的进度并回调 UI。

        解析示例：
        [STATUS] - Downloading 42%
        [STATUS] - Downloading Embed Images 50%
        [STATUS] - Embedding Images 12%
        [STATUS] - Writing Output File
        """
        if not self._detail_progress_cb or not self._current_vod_context:
            return
        if not line.startswith('[STATUS] -'):
            return
        try:
            content = line[len('[STATUS] -'):].strip()
            percent = None
            stage_name = content
            # 提取百分比
            if content.endswith('%'):
                # 从后往前找第一个空格再取数字
                parts = content.rsplit(' ', 1)
                if len(parts) == 2 and parts[1].endswith('%'):
                    num = parts[1][:-1]
                    if num.isdigit():
                        percent = int(num)
                        stage_name = parts[0]
            # 规范化阶段名称
            mapping = {
                'Downloading': '下载中',
                'Downloading Embed Images': '下载嵌入图片',
                'Embedding Images': '嵌入图片',
                'Writing Output File': '写入文件'
            }
            stage_cn = mapping.get(stage_name, stage_name)
            idx, total, safe_filename = self._current_vod_context
            # 根据命令类型前置标签
            if command_type == 'videodownload' and stage_cn == '下载中':
                stage_cn = '视频下载'
            elif command_type == 'chatdownload' and stage_cn == '下载中':
                stage_cn = '聊天下载'
            # 默认百分比
            if percent is None:
                # 写入文件等无百分比阶段，用 100 表示已完成或 0 表示开始
                percent = 100 if '写入' in stage_cn else 0
            try:
                self._detail_progress_cb(idx, total, safe_filename, stage_cn, percent)
            except Exception:
                pass
        except Exception:
            pass

    def download_single_vod(self, vod_id, download_folder, base_name):
        """下载单个VOD（用于兼容原有接口）"""
        video_output_path = os.path.join(download_folder, f"{base_name}.mp4")
        chat_output_path = os.path.join(download_folder, f"{base_name}_chat.html")

        command_video = [
            "TwitchDownloaderCLI.exe", "videodownload",
            "--id", vod_id, "-o", video_output_path
        ]
        command_chat = [
            "TwitchDownloaderCLI.exe", "chatdownload",
            "--id", vod_id, "-o", chat_output_path,
            "--embed-images", "--bttv=true", "--ffz=false", "--stv=false"
        ]

        # 下载视频，自动响应覆盖提示
        self._run_with_auto_overwrite(command_video, "视频下载")
        # 下载聊天记录，自动响应覆盖提示
        self._run_with_auto_overwrite(command_chat, "聊天记录下载")
        
        return video_output_path, chat_output_path

    def _run_with_auto_overwrite(self, command, description):
        """运行命令并自动响应覆盖提示"""
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # 实时读取输出并自动响应
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                print(output.strip())  # 显示进度
                # 检测到覆盖提示时自动输入o
                if "[O] Overwrite / [R] Rename / [E] Exit:" in output:
                    process.stdin.write("o\n")
                    process.stdin.flush()
                    logging.info(f"{description} - 自动选择覆盖文件")
        
        # 等待进程完成
        return_code = process.wait()
        
        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, command)


class Worker(QThread):
    """通用工作线程"""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self._should_stop = False

    def run(self):
        try:
            # 检查线程是否应该停止
            if self._should_stop:
                return
                
            result = self.func(*self.args, **self.kwargs)
            
            # 再次检查是否应该停止
            if not self._should_stop:
                self.finished.emit(result)
        except Exception as e:
            if not self._should_stop:
                self.error.emit(str(e))
    
    def stop(self):
        """停止线程"""
        self._should_stop = True
        self.quit()
        if not self.wait(2000):  # 等待2秒
            self.terminate()
            self.wait(1000)


class ThumbnailDownloader(QThread):
    """缩略图下载线程"""
    loaded = pyqtSignal(int, object)  # QImage
    failed = pyqtSignal(int, str)     # index, error

    def __init__(self, index, template_url, parent=None):
        super().__init__(parent)
        self.index = index
        self.template_url = template_url
        self._should_stop = False

    def run(self):
        try:
            # 检查线程是否应该停止
            if self._should_stop:
                return
                
            logging.info(f"正在下载缩略图 {self.index}: {self.template_url}")
            
            # 使用你提供的库的简单方法
            response = requests.get(self.template_url, timeout=10)
            if self._should_stop:
                return
                
            logging.info(f"缩略图 {self.index} HTTP状态码: {response.status_code}")
            
            if response.status_code == 200:
                image = QImage()
                if image.loadFromData(response.content):
                    logging.info(f"缩略图 {self.index} 下载成功，图片尺寸: {image.width()}x{image.height()}")
                    # 再次检查是否应该停止
                    if not self._should_stop:
                        self.loaded.emit(self.index, image)
                else:
                    msg = f"数据加载失败"
                    logging.error(f"缩略图 {self.index} {msg}")
                    if not self._should_stop:
                        self.failed.emit(self.index, msg)
            else:
                msg = f"HTTP错误: {response.status_code}"
                logging.error(f"缩略图 {self.index} {msg}")
                if not self._should_stop:
                    self.failed.emit(self.index, msg)
        except Exception as e:
            if not self._should_stop:
                logging.error(f"缩略图下载失败: {e}")
                try:
                    self.failed.emit(self.index, str(e))
                except Exception:
                    pass
    

    
    def stop(self):
        """停止线程"""
        self._should_stop = True
        self.quit()
        if not self.wait(1000):  # 缩略图线程等待时间短一些
            self.terminate()
            self.wait(500)


class TwitchDownloadWorker(QThread):
    """Twitch下载工作线程（支持进度）"""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int, str, str)  # current, total, filename, stage
    detail_progress = pyqtSignal(int, int, str, str, int)  # current, total, filename, sub_stage, percent

    def __init__(self, downloader, method, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.downloader = downloader
        self.method = method
        self.args = args
        self.kwargs = kwargs
        self._should_stop = False

    def _stop_flag(self):
        return self._should_stop

    def run(self):
        try:
            if self._should_stop:
                return
            method = getattr(self.downloader, self.method)

            # 若是下载方法，注入 progress_callback 与 stop_flag_callable
            if self.method == 'download_vods':
                def _progress_callback(current, total, filename, stage):
                    if not self._should_stop:
                        self.progress.emit(current, total, filename, stage)
                def _detail_progress(current, total, filename, sub_stage, percent):
                    if not self._should_stop:
                        self.detail_progress.emit(current, total, filename, sub_stage, percent)
                self.kwargs.setdefault('progress_callback', _progress_callback)
                self.kwargs.setdefault('stop_flag_callable', self._stop_flag)
                self.kwargs.setdefault('detail_progress_callback', _detail_progress)
                result = method(*self.args, **self.kwargs)
            else:
                result = method(*self.args, **self.kwargs)

            if not self._should_stop:
                self.finished.emit(result)
        except Exception as e:
            if not self._should_stop:
                self.error.emit(str(e))

    def stop(self):
        self._should_stop = True
        self.quit()
        if not self.wait(2000):
            self.terminate()
            self.wait(1000)





class TwitchTab:
    """Twitch下载标签页管理器"""
    
    def __init__(self, main_window, config_manager):
        self.main_window = main_window
        self.config_manager = config_manager
        self.downloader = TwitchDownloader(config_manager)
        self.fetch_worker = None
        self.download_worker = None
        self.thumbnail_threads = []

        self.vods = []
    
    def init_ui(self, tab_widget):
        """初始化Twitch标签页UI"""
        layout = QVBoxLayout(tab_widget)

        # 配置表单
        form = QFormLayout()
        self.e_cid = QLineEdit(self.config_manager.get("twitch_client_id"))
        form.addRow("Client ID:", self.e_cid)
        
        self.e_tok = QLineEdit(self.config_manager.get("twitch_oauth_token"))
        form.addRow("OAuth Token:", self.e_tok)
        
        self.e_user = QLineEdit(self.config_manager.get("twitch_username"))
        form.addRow("频道名(逗号分隔):", self.e_user)
        
        btn_fetch = QPushButton("获取回放列表")
        btn_fetch.clicked.connect(self.fetch_vods)
        form.addRow(btn_fetch)
        layout.addLayout(form)

        # VOD列表
        self.list_vods = QListWidget()
        self.list_vods.setSelectionMode(QAbstractItemView.MultiSelection)
        self.list_vods.setIconSize(QSize(160, 90))  # 设置缩略图尺寸

        layout.addWidget(self.list_vods)

        # 下载目录选择
        dlr = QHBoxLayout()
        dlr.addWidget(QLabel("下载目录:"))
        self.e_folder = QLineEdit(self.config_manager.get("replay_download_folder") or self.config_manager.get("twitch_download_folder", "./data/twitch"))
        btn_choose = QPushButton("选择")
        btn_choose.clicked.connect(self.choose_folder)
        dlr.addWidget(self.e_folder)
        dlr.addWidget(btn_choose)
        layout.addLayout(dlr)

        # 下载按钮与进度区域
        btn_dl = QPushButton("下载选中回放")
        btn_dl.clicked.connect(self.download_vod)
        layout.addWidget(btn_dl)
        self.btn_download = btn_dl  # 保存引用，下载过程中禁用

        # 进度条与状态标签（默认隐藏）
        self.download_progress_bar = QProgressBar()
        self.download_progress_bar.setVisible(False)
        layout.addWidget(self.download_progress_bar)
        # 当前单个VOD细粒度进度条
        self.item_progress_bar = QProgressBar()
        self.item_progress_bar.setVisible(False)
        self.item_progress_bar.setRange(0, 100)
        layout.addWidget(self.item_progress_bar)
        self.download_status_label = QLabel("")
        self.download_status_label.setVisible(False)
        layout.addWidget(self.download_status_label)
        # 取消按钮（默认隐藏，仅下载中可见）
        self.cancel_button = QPushButton("取消下载")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_download)
        layout.addWidget(self.cancel_button)

        # 状态变量
        self._current_total = 0
        self._completed_items = 0
        self._last_filename = ""
        self._is_downloading = False
    
    def fetch_vods(self):
        """获取VOD列表"""
        self.list_vods.clear()
        cid, tok, users = self.e_cid.text().strip(), self.e_tok.text().strip(), self.e_user.text().strip()
        
        if not cid or not tok or not users:
            QMessageBox.warning(self.main_window, "错误", "请填写完整 Twitch 配置")
            return

        # 保存配置
        self.config_manager.set("twitch_client_id", cid)
        self.config_manager.set("twitch_oauth_token", tok)
        self.config_manager.set("twitch_username", users)
        self.config_manager.save()

        # 启动获取线程
        self.fetch_worker = TwitchDownloadWorker(self.downloader, "fetch_vods", cid, tok, users, parent=self.main_window)
        self.fetch_worker.finished.connect(self.on_fetch_done)
        self.fetch_worker.error.connect(self.on_fetch_error)

        self.fetch_worker.start()



    def on_fetch_done(self, vods):
        """VOD获取完成 - 线程安全版本"""
        try:
            # 检查主窗口和组件是否仍然有效
            if not self.main_window or getattr(self.main_window, 'is_shutting_down', False):
                logging.info("主窗口已关闭，跳过VOD列表处理")
                return
                
            if not hasattr(self, 'list_vods') or self.list_vods is None:
                logging.warning("VOD列表组件无效")
                return
                
            self.main_window.update_status("回放列表获取完成")
            
            # 安全地处理VOD数据
            if vods and isinstance(vods, list):
                self.vods = vods
                
                # 清空现有列表
                try:
                    self.list_vods.clear()
                except Exception as e:
                    logging.warning(f"清空VOD列表失败: {e}")
                    return
                
                # 先添加所有VOD到列表
                for vod in vods:
                    try:
                        if isinstance(vod, dict) and all(key in vod for key in ['channel', 'title', 'created_at']):
                            item = QListWidgetItem(f"[{vod['channel']}] {vod['title']} ({vod['created_at']})")
                            self.list_vods.addItem(item)
                    except Exception as e:
                        logging.warning(f"添加VOD项失败: {e}")
                        continue
            else:
                self.vods = []
                logging.warning("收到无效的VOD数据")
                
        except Exception as e:
            logging.error(f"VOD列表处理异常: {e}")
            # 确保不会因为异常导致程序崩溃
            try:
                if self.main_window and not getattr(self.main_window, 'is_shutting_down', False):
                    self.main_window.stop_detailed_progress_display()
                    self.main_window.update_status("获取回放列表时出现问题")
            except Exception:
                pass
        
        # 启动缩略图加载（支持禁用与并发限制）
        self.thumbnail_threads = []
        try:
            disable_thumbs = bool(self.config_manager.get("DISABLE_TWITCH_THUMBNAILS", False))
        except Exception:
            disable_thumbs = False
            
        # 重新启用Twitch缩略图加载
        disable_thumbs = False
        if disable_thumbs:
            logging.info("⚠️ Twitch缩略图加载已临时禁用以避免崩溃")
            return
        try:
            max_conc = int(self.config_manager.get("TWITCH_THUMBNAIL_CONCURRENCY", 6))
        except Exception:
            max_conc = 6

        if not disable_thumbs:
            active = 0
            pending = []
            # 准备任务队列
            for idx, vod in enumerate(vods):
                thumbnail_url = vod.get("thumbnail_url", "")
                url = None
                if thumbnail_url:
                    if "{width}x{height}" in thumbnail_url:
                        url = thumbnail_url.replace("{width}x{height}", "320x180")
                    elif "%{width}x%{height}" in thumbnail_url:
                        url = thumbnail_url.replace("%{width}x%{height}", "320x180")
                    else:
                        url = thumbnail_url
                else:
                    vod_id = vod.get("id", "")
                    if vod_id:
                        url = f"https://static-cdn.jtvnw.net/cf_vods/d2n2mtpsfdzgw0/{vod_id}/thumb/custom-{vod_id}-320x180.jpg"
                if url:
                    pending.append((idx, url))

            # 启动受限并发
            def _start_one(idx, url):
                # 给缩略图下载线程设置正确的父对象，避免过早销毁
                td = ThumbnailDownloader(idx, url, parent=self.main_window)
                td.loaded.connect(self.on_thumb_loaded)
                if hasattr(td, 'failed'):
                    td.failed.connect(self.on_thumb_failed)
                # 避免闭包捕获同名变量被覆盖，使用默认参数绑定当前 td
                td.finished.connect(lambda td_ref=td: self._on_thumb_finished(td_ref))
                self.thumbnail_threads.append(td)
                td.start()

            self._thumb_pending = pending  # 保存到实例，便于回调取用
            self._thumb_active = 0
            self._thumb_max = max(1, max_conc)

            # 启动前 max_conc 个
            while self._thumb_active < self._thumb_max and self._thumb_pending:
                idx, url = self._thumb_pending.pop(0)
                logging.info(f"开始下载缩略图 {idx}: {url}")
                _start_one(idx, url)
                self._thumb_active += 1
        else:
            logging.info("已禁用Twitch缩略图加载")
    def on_fetch_error(self, msg):
        """VOD获取错误"""
        self.main_window.update_status("获取回放列表失败")
        QMessageBox.warning(self.main_window, "错误", msg)

    def on_thumb_loaded(self, idx, img):
        """缩略图加载完成"""
        from PyQt5.QtCore import Qt
        
        logging.info(f"缩略图 {idx} 加载完成，原始图片尺寸: {img.width()}x{img.height()}")
        pix = QPixmap.fromImage(img).scaled(160, 90, Qt.KeepAspectRatio | Qt.SmoothTransformation)
        logging.info(f"缩略图 {idx} 缩放后尺寸: {pix.width()}x{pix.height()}")
        
        item = self.list_vods.item(idx)
        if item:
            item.setIcon(QIcon(pix))
            logging.info(f"缩略图 {idx} 已设置到列表项")
            # 强制刷新列表项显示
            self.list_vods.update()
        else:
            logging.warning(f"找不到列表项 {idx} 来设置缩略图")
            logging.warning(f"当前列表项数量: {self.list_vods.count()}")

    def _on_thumb_finished(self, worker):
        """单个缩略图线程完成后的调度（限制并发）"""
        try:
            if hasattr(worker, 'deleteLater'):
                worker.deleteLater()
        except Exception:
            pass
        try:
            self._thumb_active = max(0, getattr(self, '_thumb_active', 1) - 1)
            # 继续启动队列中的下一个
            if getattr(self, '_thumb_pending', None) and self._thumb_active < getattr(self, '_thumb_max', 1):
                idx, url = self._thumb_pending.pop(0)
                logging.info(f"开始下载缩略图 {idx}: {url}")
                td = ThumbnailDownloader(idx, url, parent=self.main_window)
                td.loaded.connect(self.on_thumb_loaded)
                if hasattr(td, 'failed'):
                    td.failed.connect(self.on_thumb_failed)
                td.finished.connect(lambda td_ref=td: self._on_thumb_finished(td_ref))
                self.thumbnail_threads.append(td)
                td.start()
                self._thumb_active += 1
        except Exception as e:
            logging.debug(f"缩略图并发调度异常: {e}")

    def on_thumb_failed(self, idx, err):
        """缩略图失败时也推进并发队列，并用占位图避免卡住UI"""
        try:
            from PyQt5.QtGui import QImage
            img = QImage(160, 90, QImage.Format_RGB32)
            img.fill(0xFF222222)
            self.on_thumb_loaded(idx, img)
        except Exception:
            pass





    def choose_folder(self):
        """选择下载文件夹"""
        d = QFileDialog.getExistingDirectory(
            self.main_window, "选择下载目录", 
            self.config_manager.get("replay_download_folder") or self.config_manager.get("twitch_download_folder", "./data/twitch")
        )
        if d:
            self.e_folder.setText(d)
            # 同时保存到新旧两个配置项，保持兼容性
            self.config_manager.set("replay_download_folder", d)
            self.config_manager.set("twitch_download_folder", d)
            self.config_manager.save()

    def download_vod(self):
        """下载选中的VOD - 简化版本"""
        items = self.list_vods.selectedItems()
        if not items:
            QMessageBox.warning(self.main_window, "错误", "请先选择一个或多个回放")
            return
            
        folder = self.e_folder.text().strip()
        if not os.path.isdir(folder):
            QMessageBox.warning(self.main_window, "错误", "下载目录无效")
            return

        # 获取选中的VOD
        selected_vods = []
        for item in items:
            idx = self.list_vods.row(item)
            selected_vods.append(self.vods[idx])
        
        # 显示下载确认对话框
        count = len(selected_vods)
        reply = QMessageBox.question(
            self.main_window, 
            "确认下载", 
            f"确定要下载 {count} 个回放吗？\n\n这将需要较长时间，建议分批下载。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return

        # 配置进度条
        self._current_total = len(selected_vods)
        self._completed_items = 0
        self.download_progress_bar.setRange(0, self._current_total)
        self.download_progress_bar.setValue(0)
        self.download_progress_bar.setVisible(True)
        self.download_status_label.setText("准备开始下载...")
        self.download_status_label.setVisible(True)
        self.item_progress_bar.setVisible(True)
        self.item_progress_bar.setValue(0)
        self.item_progress_bar.setFormat("-")
        self.cancel_button.setVisible(True)
        self.btn_download.setEnabled(False)
        self.list_vods.setEnabled(False)
        self._is_downloading = True

        # 启动下载线程（顺序执行 + 进度信号）
        self.download_worker = TwitchDownloadWorker(
            self.downloader, "download_vods", selected_vods, folder,
            parent=self.main_window
        )
        self.download_worker.progress.connect(self.update_download_progress)
        # 细粒度进度
        if hasattr(self.download_worker, 'detail_progress'):
            self.download_worker.detail_progress.connect(self.update_item_detail_progress)
        self.download_worker.finished.connect(self.on_download_done)
        self.download_worker.error.connect(self.on_download_error)
        self.download_worker.start()

    def update_download_progress(self, current, total, filename, stage):
        """更新下载进度（主线程槽函数）"""
        # current: 1-based
        if total != self._current_total:
            # 初次或数量变化（极少）
            self._current_total = total
            self.download_progress_bar.setRange(0, total)

        # 只有在 item_done 时递增完成数，其他阶段显示状态
        if stage == 'item_done':
            self._completed_items = current
            self.download_progress_bar.setValue(self._completed_items)
        elif stage == 'start':
            # 还没完成，显示当前值
            self.download_progress_bar.setValue(current - 1)

        # 构造状态文本
        stage_map = {
            'start': '开始',
            'video_done': '视频完成',
            'chat_done': '聊天完成',
            'video_failed': '视频失败',
            'item_done': '完成',
            'canceled': '已取消'
        }
        stage_cn = stage_map.get(stage, stage)
        self.download_status_label.setText(
            f"{stage_cn}: {filename}  ({min(self._completed_items, total)}/{total})"
        )

        if stage == 'canceled':
            self.download_progress_bar.setFormat("已取消")
            self.finish_download_ui(canceled=True)

    def finish_download_ui(self, canceled=False):
        """统一恢复UI"""
        self.btn_download.setEnabled(True)
        self.list_vods.setEnabled(True)
        self.cancel_button.setVisible(False)
        self.item_progress_bar.setVisible(False)
        self._is_downloading = False
        if canceled:
            self.download_status_label.setText("下载已取消")

    def on_download_done(self, results):
        """下载完成 - 线程安全版本"""
        try:
            # 恢复UI
            if self._is_downloading:
                self.finish_download_ui()
                self.download_status_label.setText("全部下载完成")
            # 检查主窗口是否仍然有效
            if not self.main_window or getattr(self.main_window, 'is_shutting_down', False):
                logging.info("主窗口已关闭，跳过下载完成处理")
                return
                
            self.main_window.update_status("下载完成")
            
            if results and len(results) > 0:
                try:
                    last_video, last_chat = results[-1]
                    
                    # 安全地更新配置
                    if self.config_manager:
                        self.config_manager.set("VIDEO_FILE", last_video)
                        self.config_manager.set("CHAT_FILE", last_chat)
                        self.config_manager.save()
                    
                    # 安全地刷新本地视频列表
                    if (hasattr(self.main_window, 'local_tab') and 
                        self.main_window.local_tab and 
                        hasattr(self.main_window.local_tab, 'refresh_local_videos')):
                        try:
                            self.main_window.local_tab.refresh_local_videos()
                        except Exception as e:
                            logging.warning(f"刷新本地视频列表失败: {e}")
                    
                    # 安全地显示完成消息
                    try:
                        QMessageBox.information(
                            self.main_window, "完成", 
                            f"下载完成\n视频: {last_video}\n聊天: {last_chat}"
                        )
                    except Exception as e:
                        logging.warning(f"显示完成消息失败: {e}")
                        
                except (ValueError, IndexError, TypeError) as e:
                    logging.error(f"处理下载结果时出错: {e}")
                    QMessageBox.information(self.main_window, "完成", "下载完成，但处理结果时出现问题")
            else:
                QMessageBox.information(self.main_window, "完成", "下载完成")
                
        except Exception as e:
            logging.error(f"下载完成处理异常: {e}")
            # 确保不会因为异常导致程序崩溃
            try:
                if self.main_window and not getattr(self.main_window, 'is_shutting_down', False):
                    self.main_window.update_status("下载完成（处理时出现问题）")
            except Exception:
                pass



    def on_download_error(self, msg):
        """下载错误 - 线程安全版本"""
        try:
            if self._is_downloading:
                self.finish_download_ui()
            # 检查主窗口是否仍然有效
            if not self.main_window or getattr(self.main_window, 'is_shutting_down', False):
                logging.info("主窗口已关闭，跳过下载错误处理")
                return
                
            self.main_window.update_status("下载失败")
            
            # 安全地显示错误消息
            try:
                QMessageBox.warning(self.main_window, "错误", str(msg) if msg else "下载过程中发生未知错误")
            except Exception as e:
                logging.error(f"显示错误消息失败: {e}")
                
        except Exception as e:
            logging.error(f"下载错误处理异常: {e}")
            # 确保不会因为异常导致程序崩溃



    def cleanup(self):
        """清理资源"""
        workers_to_cleanup = [
            ('fetch_worker', self.fetch_worker),
            ('download_worker', self.download_worker)
        ]
        
        # 清理主要的工作线程
        for name, worker in workers_to_cleanup:
            try:
                if (worker and 
                    hasattr(worker, 'isRunning') and 
                    worker.isRunning()):
                    logging.info(f"正在停止{name}...")
                    if hasattr(worker, 'stop'):
                        worker.stop()
                    else:
                        worker.quit()
                        if not worker.wait(2000):  # 等待2秒
                            worker.terminate()
                            worker.wait(1000)
            except (RuntimeError, AttributeError) as e:
                # 对象可能已经被删除，忽略错误
                logging.debug(f"清理{name}时忽略错误: {e}")
        
        # 清理缩略图下载线程
        try:
            if hasattr(self, 'thumbnail_threads'):
                for i, worker in enumerate(self.thumbnail_threads):
                    try:
                        if (worker and 
                            hasattr(worker, 'isRunning') and 
                            worker.isRunning()):
                            logging.info(f"正在停止缩略图线程 {i+1}...")
                            if hasattr(worker, 'stop'):
                                worker.stop()
                            else:
                                worker.quit()
                                if not worker.wait(1000):  # 缩略图线程等待时间短一些
                                    worker.terminate()
                                    worker.wait(500)
                    except (RuntimeError, AttributeError) as e:
                        logging.debug(f"清理缩略图线程 {i+1} 时忽略错误: {e}")
        except (RuntimeError, AttributeError) as e:
            logging.debug(f"清理缩略图线程列表时忽略错误: {e}")

    def cancel_download(self):
        """用户点击取消下载"""
        if not self._is_downloading:
            return
        logging.info("用户请求取消当前下载队列")
        try:
            self.downloader.cancel_current()
        except Exception as e:
            logging.debug(f"调用取消时忽略错误: {e}")
        if self.download_worker and self.download_worker.isRunning():
            try:
                self.download_worker.stop()
            except Exception:
                pass
        self.finish_download_ui(canceled=True)
        self.main_window.update_status("下载已取消")

    def update_item_detail_progress(self, current, total, filename, sub_stage, percent):
        """更新单个文件的细粒度进度"""
        # 只有在下载中才更新
        if not self._is_downloading:
            return
        # 若切换到新的文件且 percent 很小，重置条
        try:
            self.item_progress_bar.setVisible(True)
            self.item_progress_bar.setValue(int(percent))
            # 设置显示文本：阶段 + 百分比
            self.item_progress_bar.setFormat(f"{sub_stage} {percent}%")
        except Exception:
            pass
        

        



class TwitchDownloadPage(QWidget):
    """Twitch下载页面（兼容原有接口）"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # 兼容原有的 config 导入方式
        try:
            from acfv import config
            self.config = config
        except ImportError:
            self.config = None
        
        self.vods = []
        self.worker = None
        self.video_output_path = ""
        self.chat_output_path = ""
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        gb_settings = QGroupBox("Twitch 设置")
        form = QFormLayout(gb_settings)
        
        # 兼容性处理
        default_client_id = ""
        default_oauth_token = ""
        default_username = ""
        default_download_folder = "./data/twitch"
        
        if self.config:
            default_client_id = getattr(self.config, "twitch_client_id", "")
            default_oauth_token = getattr(self.config, "twitch_oauth_token", "")
            default_username = getattr(self.config, "twitch_username", "")
            default_download_folder = getattr(self.config, "replay_download_folder") or getattr(self.config, "twitch_download_folder", "./data/twitch")
        
        self.edit_client_id = QLineEdit(default_client_id)
        self.edit_oauth_token = QLineEdit(default_oauth_token)
        self.edit_username = QLineEdit(default_username)
        
        form.addRow("Client ID:", self.edit_client_id)
        form.addRow("OAuth Token:", self.edit_oauth_token)
        form.addRow("Twitch 频道名 (多个用逗号分隔):", self.edit_username)
        layout.addWidget(gb_settings)

        self.btn_fetch = QPushButton("获取回放列表")
        self.btn_fetch.clicked.connect(self.fetch_vods)
        layout.addWidget(self.btn_fetch)

        self.list_vods = QListWidget()
        layout.addWidget(self.list_vods)

        folder_widget, self.edit_download_folder, _ = createFolderSelector(default_download_folder)
        layout.addWidget(QLabel("下载保存目录:"))
        layout.addWidget(folder_widget)

        self.btn_download = QPushButton("下载选中的回放")
        self.btn_download.clicked.connect(self.download_selected_vod)
        layout.addWidget(self.btn_download)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.setLayout(layout)

    def fetch_vods(self):
        """获取VOD列表（兼容原有接口）"""
        self.list_vods.clear()
        self.vods = []
        client_id = self.edit_client_id.text().strip()
        oauth_token = self.edit_oauth_token.text().strip()
        usernames = [n.strip() for n in self.edit_username.text().split(",") if n.strip()]
        
        if not (client_id and oauth_token and usernames):
            QMessageBox.warning(self, "错误", "请填写完整的 Twitch 设置")
            return

        headers = {"Client-ID": client_id, "Authorization": f"Bearer {oauth_token}"}
        for username in usernames:
            try:
                resp = requests.get(f"https://api.twitch.tv/helix/users?login={username}", headers=headers)
                resp.raise_for_status()
                data = resp.json().get("data", [])
                if not data:
                    QMessageBox.warning(self, "错误", f"无法获取用户信息: {username}")
                    continue
                user_id = data[0]["id"]
            except Exception as e:
                QMessageBox.warning(self, "错误", f"获取用户信息失败 ({username}): {e}")
                continue

            try:
                vod_resp = requests.get(
                    f"https://api.twitch.tv/helix/videos?user_id={user_id}&type=archive&first=20",
                    headers=headers
                )
                vod_resp.raise_for_status()
                vods_channel = vod_resp.json().get("data", [])
                for vod in vods_channel:
                    vod["channel"] = username
                    self.vods.append(vod)
                    item_text = f"[{username}] {vod['title']} ({vod['created_at']})"
                    self.list_vods.addItem(item_text)
            except Exception as e:
                QMessageBox.warning(self, "错误", f"获取回放列表失败 ({username}): {e}")

    def download_selected_vod(self):
        """下载选中的VOD（兼容原有接口）"""
        idx = self.list_vods.currentRow()
        if idx < 0 or idx >= len(self.vods):
            QMessageBox.warning(self, "错误", "请选择一个回放")
            return
        
        vod = self.vods[idx]
        vod_id = vod["id"]
        download_folder = self.edit_download_folder.text().strip()
        
        if not os.path.isdir(download_folder):
            QMessageBox.warning(self, "错误", "下载文件夹无效")
            return

        # 用 频道 + 标题 + 时间 来命名，并做安全字符替换
        raw_channel = vod.get("channel", vod_id)
        raw_title = vod.get("title", vod_id)
        raw_time = vod.get("created_at", "")
        safe_channel = sanitize_filename(raw_channel)
        safe_title = sanitize_filename(raw_title)
        safe_time = sanitize_filename(raw_time.replace("T", "_").replace(":", "-").rstrip("Z"))
        base_name = f"{safe_channel}_{safe_title}_{safe_time}"

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        def run_download():
            # 创建临时的 TwitchDownloader 实例
            downloader = TwitchDownloader(None)
            return downloader.download_single_vod(vod_id, download_folder, base_name)

        self.worker = Worker(run_download)
        self.worker.finished.connect(self.on_download_finished)
        self.worker.error.connect(self.on_download_error)
        self.worker.start()

    def on_download_finished(self, result):
        """下载完成回调（兼容原有接口）"""
        self.progress_bar.setVisible(False)
        self.video_output_path, self.chat_output_path = result
        
        result_msg = (
            f"视频和聊天记录下载完成。\n"
            f"视频保存为:\n{self.video_output_path}\n"
            f"聊天记录保存为:\n{self.chat_output_path}"
        )
        QMessageBox.information(self, "完成", result_msg)

        # 更新配置
        if self.config:
            self.config.VIDEO_FILE = self.video_output_path
            self.config.CHAT_FILE = self.chat_output_path
            download_folder = os.path.dirname(self.video_output_path)
            self.config.CHAT_OUTPUT = os.path.join(download_folder, "chat_with_emotes.json")
            self.config.TRANSCRIPTION_OUTPUT = os.path.join(download_folder, "transcription.json")
            self.config.ANALYSIS_OUTPUT = os.path.join(download_folder, "high_interest_segments.json")
            self.config.OUTPUT_CLIPS_DIR = os.path.join(download_folder, "output_clips")

        # 尝试调用主窗口的流水线
        main_window = self.parent()
        if hasattr(main_window, "runPipeline"):
            main_window.runPipeline()

    def on_download_error(self, error):
        """下载错误回调（兼容原有接口）"""
        self.progress_bar.setVisible(False)
        QMessageBox.warning(self, "错误", str(error))
