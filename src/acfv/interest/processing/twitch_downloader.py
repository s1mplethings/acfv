"""Migrated twitch_downloader core (simplified) from interest_rating.

Notes:
 - Retains TwitchDownloader, TwitchTab essential functionality for downloading VODs.
 - Thumbnail loading and legacy page classes omitted for initial integration to reduce complexity.
 - Can be expanded later if full feature parity required.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from typing import List

import requests
from PyQt5.QtCore import QThread, pyqtSignal, QSize
from PyQt5.QtWidgets import (
    QListWidget, QListWidgetItem, QVBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QHBoxLayout, QLabel, QAbstractItemView, QProgressBar,
    QMessageBox, QFileDialog
)

__all__ = ["TwitchDownloader", "TwitchDownloadWorker", "TwitchTab"]


def _sanitize(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = re.sub(r'\s+', '_', name)
    return name


class TwitchDownloader:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self._current_process = None
        self._cancel_requested = False

    def fetch_vods(self, client_id: str, oauth_token: str, usernames: str):
        headers = {"Client-ID": client_id, "Authorization": f"Bearer {oauth_token}"}
        names = [u.strip() for u in usernames.split(",") if u.strip()]
        vods = []
        for username in names:
            logging.info(f"获取用户 {username} 信息...")
            r1 = requests.get(f"https://api.twitch.tv/helix/users?login={username}", headers=headers, timeout=10)
            r1.raise_for_status()
            user_data = r1.json().get("data", [])
            if not user_data:
                logging.warning(f"用户不存在: {username}")
                continue
            user_id = user_data[0]["id"]
            r2 = requests.get(
                f"https://api.twitch.tv/helix/videos?user_id={user_id}&type=archive&first=20",
                headers=headers,
                timeout=15,
            )
            r2.raise_for_status()
            user_vods = r2.json().get("data", [])
            for vod in user_vods:
                vod["channel"] = username
                vods.append(vod)
            time.sleep(0.1)
        logging.info(f"共找到 {len(vods)} 个回放")
        return vods

    def download_vods(self, vods: List[dict], download_folder: str, progress_callback=None, stop_flag_callable=None):
        results = []
        total = len(vods)
        for idx, vod in enumerate(vods, start=1):
            if (stop_flag_callable and stop_flag_callable()) or self._cancel_requested:
                logging.info("取消下载")
                if progress_callback:
                    progress_callback(idx, total, "", "canceled")
                break
            try:
                safe_title = re.sub(r'[\\/:*?"<>|]', '_', vod.get("title", "vod"))
                timestamp = vod.get("created_at", "").replace(":", "-").replace("T", "_").rstrip("Z")
                safe_filename = f"{safe_title}_{timestamp}_{vod.get('id','')[:8]}"
                video_path = os.path.join(download_folder, safe_filename + ".mp4")
                if os.path.exists(video_path):
                    logging.info(f"已存在，跳过: {safe_filename}")
                    results.append(video_path)
                    continue
                if progress_callback:
                    progress_callback(idx, total, safe_filename, 'start')
                ok = self._download_video(vod["id"], video_path)
                if ok and progress_callback:
                    progress_callback(idx, total, safe_filename, 'item_done')
                if ok:
                    results.append(video_path)
            except Exception as e:  # noqa: BLE001
                logging.error(f"下载失败: {e}")
        return results

    def _download_video(self, vod_id: str, output_path: str) -> bool:
        cmd = ["TwitchDownloaderCLI.exe", "videodownload", "--id", vod_id, "-o", output_path]
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )
            self._current_process = process
            while True:
                if self._cancel_requested:
                    try:
                        process.kill()
                    except Exception:  # noqa: BLE001
                        pass
                    return False
                line = process.stdout.readline()
                if line == '' and process.poll() is not None:
                    break
                if line:
                    if "[O] Overwrite" in line and process.stdin:
                        process.stdin.write("o\n"); process.stdin.flush()
            rc = process.wait(); self._current_process = None
            return rc == 0
        except Exception as e:  # noqa: BLE001
            logging.error(f"调用下载工具失败: {e}")
            return False

    def cancel_current(self):
        self._cancel_requested = True
        proc = self._current_process
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        self._current_process = None


class TwitchDownloadWorker(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int, str, str)

    def __init__(self, downloader, method, *args, parent=None, **kwargs):
        super().__init__(parent)
        self.downloader = downloader
        self.method = method
        self.args = args
        self.kwargs = kwargs
        self._should_stop = False

    def _stop_flag(self):
        return self._should_stop

    def run(self):  # noqa: D401
        try:
            if self._should_stop:
                return
            method = getattr(self.downloader, self.method)
            if self.method == 'download_vods':
                def _progress(current, total, filename, stage):
                    if not self._should_stop:
                        self.progress.emit(current, total, filename, stage)
                self.kwargs.setdefault('progress_callback', _progress)
                self.kwargs.setdefault('stop_flag_callable', self._stop_flag)
                result = method(*self.args, **self.kwargs)
            else:
                result = method(*self.args, **self.kwargs)
            if not self._should_stop:
                self.finished.emit(result)
        except Exception as e:  # noqa: BLE001
            if not self._should_stop:
                self.error.emit(str(e))

    def stop(self):  # noqa: D401
        self._should_stop = True
        self.downloader.cancel_current()


class TwitchTab:
    def __init__(self, main_window, config_manager):
        self.main_window = main_window
        self.config_manager = config_manager
        self.downloader = TwitchDownloader(config_manager)
        self.fetch_worker: TwitchDownloadWorker | None = None
        self.download_worker: TwitchDownloadWorker | None = None
        self.vods: List[dict] = []

    def init_ui(self, tab_widget):
        layout = QVBoxLayout(tab_widget)
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
        self.list_vods = QListWidget(); self.list_vods.setSelectionMode(QAbstractItemView.MultiSelection)
        self.list_vods.setIconSize(QSize(160, 90))
        layout.addWidget(self.list_vods)
        dlr = QHBoxLayout(); dlr.addWidget(QLabel("下载目录:"))
        self.e_folder = QLineEdit(self.config_manager.get("replay_download_folder") or self.config_manager.get("twitch_download_folder", "./data/twitch"))
        btn_choose = QPushButton("选择"); btn_choose.clicked.connect(self.choose_folder)
        dlr.addWidget(self.e_folder); dlr.addWidget(btn_choose); layout.addLayout(dlr)
        self.btn_download = QPushButton("下载选中回放"); self.btn_download.clicked.connect(self.download_vod); layout.addWidget(self.btn_download)
        self.download_progress_bar = QProgressBar(); self.download_progress_bar.setVisible(False); layout.addWidget(self.download_progress_bar)
        self.download_status_label = QLabel(""); self.download_status_label.setVisible(False); layout.addWidget(self.download_status_label)
        self.cancel_button = QPushButton("取消下载"); self.cancel_button.setVisible(False); self.cancel_button.clicked.connect(self.cancel_download); layout.addWidget(self.cancel_button)
        self._current_total = 0; self._completed_items = 0; self._is_downloading = False

    # -------------- Actions --------------
    def fetch_vods(self):  # noqa: D401
        self.list_vods.clear()
        cid, tok, users = self.e_cid.text().strip(), self.e_tok.text().strip(), self.e_user.text().strip()
        if not cid or not tok or not users:
            QMessageBox.warning(self.main_window, "错误", "请填写完整 Twitch 配置"); return
        self.config_manager.set("twitch_client_id", cid)
        self.config_manager.set("twitch_oauth_token", tok)
        self.config_manager.set("twitch_username", users)
        self.config_manager.save()
        self.fetch_worker = TwitchDownloadWorker(self.downloader, "fetch_vods", cid, tok, users, parent=self.main_window)
        self.fetch_worker.finished.connect(self.on_fetch_done)
        self.fetch_worker.error.connect(self.on_fetch_error)
        self.fetch_worker.start()

    def on_fetch_done(self, vods):  # noqa: D401
        self.vods = vods or []
        for vod in self.vods:
            try:
                item = QListWidgetItem(f"[{vod.get('channel')}] {vod.get('title')} ({vod.get('created_at')})")
                self.list_vods.addItem(item)
            except Exception:  # noqa: BLE001
                continue
        self.main_window.update_status("回放列表获取完成")

    def on_fetch_error(self, msg):  # noqa: D401
        self.main_window.update_status("获取回放列表失败")
        QMessageBox.warning(self.main_window, "错误", msg)

    def choose_folder(self):  # noqa: D401
        d = QFileDialog.getExistingDirectory(self.main_window, "选择下载目录", self.config_manager.get("replay_download_folder") or self.config_manager.get("twitch_download_folder", "./data/twitch"))
        if d:
            self.e_folder.setText(d)
            self.config_manager.set("replay_download_folder", d)
            self.config_manager.set("twitch_download_folder", d)
            self.config_manager.save()

    def download_vod(self):  # noqa: D401
        items = self.list_vods.selectedItems()
        if not items:
            QMessageBox.warning(self.main_window, "错误", "请选择回放"); return
        folder = self.e_folder.text().strip()
        if not os.path.isdir(folder):
            QMessageBox.warning(self.main_window, "错误", "下载目录无效"); return
        selected = [self.vods[self.list_vods.row(it)] for it in items]
        count = len(selected)
        reply = QMessageBox.question(self.main_window, "确认下载", f"确定要下载 {count} 个回放吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._current_total = count; self._completed_items = 0
        self.download_progress_bar.setRange(0, count); self.download_progress_bar.setValue(0); self.download_progress_bar.setVisible(True)
        self.download_status_label.setText("准备开始下载..."); self.download_status_label.setVisible(True)
        self.cancel_button.setVisible(True); self.btn_download.setEnabled(False); self.list_vods.setEnabled(False); self._is_downloading = True
        self.download_worker = TwitchDownloadWorker(self.downloader, "download_vods", selected, folder, parent=self.main_window)
        self.download_worker.progress.connect(self.update_download_progress)
        self.download_worker.finished.connect(self.on_download_done)
        self.download_worker.error.connect(self.on_download_error)
        self.download_worker.start()

    def update_download_progress(self, current, total, filename, stage):  # noqa: D401
        if stage == 'item_done':
            self._completed_items = current; self.download_progress_bar.setValue(self._completed_items)
        elif stage == 'start':
            self.download_progress_bar.setValue(current - 1)
        stage_map = {'start': '开始', 'item_done': '完成', 'canceled': '已取消'}
        stage_cn = stage_map.get(stage, stage)
        self.download_status_label.setText(f"{stage_cn}: {filename} ({min(self._completed_items, total)}/{total})")
        if stage == 'canceled':
            self.download_progress_bar.setFormat("已取消"); self.finish_download_ui(canceled=True)

    def finish_download_ui(self, canceled=False):  # noqa: D401
        self.btn_download.setEnabled(True); self.list_vods.setEnabled(True); self.cancel_button.setVisible(False); self._is_downloading = False
        if canceled:
            self.download_status_label.setText("下载已取消")

    def on_download_done(self, results):  # noqa: D401
        if self._is_downloading:
            self.finish_download_ui()
            self.download_status_label.setText("全部下载完成")
        if results:
            last_video = results[-1]
            self.config_manager.set("VIDEO_FILE", last_video)
            self.config_manager.save()
            QMessageBox.information(self.main_window, "完成", f"下载完成\n视频: {last_video}")
        else:
            QMessageBox.information(self.main_window, "完成", "下载完成")
        self.main_window.update_status("下载完成")

    def on_download_error(self, msg):  # noqa: D401
        if self._is_downloading:
            self.finish_download_ui()
        self.main_window.update_status("下载失败")
        QMessageBox.warning(self.main_window, "错误", str(msg) if msg else "下载过程中发生未知错误")

    def cancel_download(self):  # noqa: D401
        if not self._is_downloading: return
        logging.info("取消下载请求")
        try: self.downloader.cancel_current()
        except Exception: pass  # noqa: BLE001
        if self.download_worker and self.download_worker.isRunning():
            try: self.download_worker.stop()
            except Exception: pass  # noqa: BLE001
        self.finish_download_ui(canceled=True); self.main_window.update_status("下载已取消")

