"""PyQt editor for the StreamGet background monitor config."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from PyQt5 import QtWidgets
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices

from acfv.runtime.stream_monitor import (
    StreamMonitorConfig,
    StreamTarget,
    STREAM_CLIENTS,
    MonitorEvent,
    slugify,
    load_stream_monitor_config,
    processing_path,
    resolve_platform,
    save_stream_monitor_config,
)
from acfv.runtime.storage import logs_path
from acfv.ui.stream_monitor_worker import StreamMonitorWorker


QUALITY_OPTIONS = ["OD", "UHD", "HD", "SD", "LD"]
FORMAT_OPTIONS = ["mp4", "flv", "ts", "mkv"]


class StreamMonitorEditorWidget(QtWidgets.QWidget):
    """Core widget that can be used standalone or embedded inside the main GUI."""

    def __init__(self, config_path: Optional[Path] = None, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.config_path = config_path
        self.config, self.cfg_path, _ = load_stream_monitor_config(config_path)
        self.targets = list(self.config.targets)
        self.current_index: int | None = None
        self.log_path = logs_path("stream_monitor.log")
        self.monitor_worker: StreamMonitorWorker | None = None
        self.status_rows: Dict[str, int] = {}
        self._target_lookup: Dict[str, StreamTarget] = {}

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(self._build_info_banner())
        layout.addWidget(self._build_target_area(), stretch=1)
        layout.addLayout(self._build_bottom_actions())
        layout.addWidget(self._build_monitor_panel(), stretch=1)

        self._populate_general_settings()
        self._refresh_target_list()
        self._update_target_lookup()
        self.destroyed.connect(lambda *_: self._shutdown_monitor())

        if self.targets:
            self.target_list.setCurrentRow(0)
        else:
            self._clear_target_form()

    def _build_info_banner(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("全局说明")
        layout = QtWidgets.QVBoxLayout(box)
        label = QtWidgets.QLabel(
            "全局参数（ffmpeg 路径、默认清晰度、轮询间隔等）已移动到“设置 → 监控”中统一管理。"
            "此处专注于具体直播间的列表与实时状态。"
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        return box

    def _build_target_area(self) -> QtWidgets.QWidget:
        wrapper = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(wrapper)
        layout.setSpacing(12)

        self.target_list = QtWidgets.QListWidget()
        self.target_list.currentRowChanged.connect(self._on_target_selected)
        layout.addWidget(self.target_list, 1)

        self.target_form = self._build_target_form()
        layout.addWidget(self.target_form, 2)

        return wrapper

    def _build_target_form(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("流配置")
        form = QtWidgets.QFormLayout(box)

        self.enabled_checkbox = QtWidgets.QCheckBox("启用该流")
        form.addRow(self.enabled_checkbox)

        self.name_edit = QtWidgets.QLineEdit()
        self.url_edit = QtWidgets.QLineEdit()

        self.platform_combo = QtWidgets.QComboBox()
        self.platform_combo.addItems(["auto"] + sorted(STREAM_CLIENTS.keys()))
        self.platform_combo.setEditable(True)

        self.quality_combo = QtWidgets.QComboBox()
        self.quality_combo.addItems(QUALITY_OPTIONS)

        self.poll_override_spin = QtWidgets.QSpinBox()
        self.poll_override_spin.setRange(5, 3600)

        self.format_combo = QtWidgets.QComboBox()
        self.format_combo.addItems(FORMAT_OPTIONS)

        self.output_dir_edit = QtWidgets.QLineEdit()
        out_btn = QtWidgets.QPushButton("选择…")
        out_btn.clicked.connect(self._browse_output_dir)
        output_layout = QtWidgets.QHBoxLayout()
        output_layout.addWidget(self.output_dir_edit)
        output_layout.addWidget(out_btn)

        self.cookies_edit = QtWidgets.QLineEdit()
        cookie_btn = QtWidgets.QPushButton("文件…")
        cookie_btn.clicked.connect(self._browse_cookies)
        cookie_layout = QtWidgets.QHBoxLayout()
        cookie_layout.addWidget(self.cookies_edit)
        cookie_layout.addWidget(cookie_btn)

        self.proxy_edit = QtWidgets.QLineEdit()

        form.addRow("名称", self.name_edit)
        form.addRow("直播 URL", self.url_edit)
        form.addRow("平台", self.platform_combo)
        form.addRow("清晰度", self.quality_combo)
        form.addRow("轮询 (秒)", self.poll_override_spin)
        form.addRow("保存格式", self.format_combo)
        form.addRow("输出目录", output_layout)
        form.addRow("Cookies 文件", cookie_layout)
        form.addRow("代理", self.proxy_edit)

        button_row = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("新增")
        add_btn.clicked.connect(self._add_target)
        dup_btn = QtWidgets.QPushButton("复制")
        dup_btn.clicked.connect(self._duplicate_target)
        del_btn = QtWidgets.QPushButton("删除")
        del_btn.clicked.connect(self._delete_target)
        apply_btn = QtWidgets.QPushButton("应用更改")
        apply_btn.clicked.connect(self._apply_current_changes)

        button_row.addWidget(add_btn)
        button_row.addWidget(dup_btn)
        button_row.addWidget(del_btn)
        button_row.addStretch()
        button_row.addWidget(apply_btn)
        form.addRow(button_row)

        return box

    def _build_bottom_actions(self) -> QtWidgets.QHBoxLayout:
        layout = QtWidgets.QHBoxLayout()
        layout.addStretch()
        reload_btn = QtWidgets.QPushButton("重新载入")
        reload_btn.clicked.connect(self._reload_from_disk)
        save_btn = QtWidgets.QPushButton("保存配置")
        save_btn.clicked.connect(self._save_config)
        layout.addWidget(reload_btn)
        layout.addWidget(save_btn)
        return layout

    def _build_monitor_panel(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("实时状态")
        layout = QtWidgets.QVBoxLayout(box)

        controls = QtWidgets.QHBoxLayout()
        self.btn_start_monitor = QtWidgets.QPushButton("启动监控")
        self.btn_start_monitor.clicked.connect(self.start_monitor)
        self.btn_stop_monitor = QtWidgets.QPushButton("停止监控")
        self.btn_stop_monitor.clicked.connect(self.stop_monitor)
        self.btn_stop_monitor.setEnabled(False)
        controls.addWidget(self.btn_start_monitor)
        controls.addWidget(self.btn_stop_monitor)
        controls.addStretch()
        self.monitor_status_label = QtWidgets.QLabel("未运行")
        controls.addWidget(self.monitor_status_label)
        layout.addLayout(controls)

        path_row = QtWidgets.QHBoxLayout()
        self.log_path_label = QtWidgets.QLabel(f"日志：{self.log_path}")
        open_log_btn = QtWidgets.QPushButton("打开日志目录")
        open_log_btn.clicked.connect(self._open_log_dir)
        path_row.addWidget(self.log_path_label, 1)
        path_row.addWidget(open_log_btn)
        layout.addLayout(path_row)

        self.status_table = QtWidgets.QTableWidget(0, 6)
        self.status_table.setHorizontalHeaderLabels(["名称", "平台", "状态", "说明", "输出/其它", "时间"])
        self.status_table.horizontalHeader().setStretchLastSection(True)
        self.status_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.status_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.status_table, 1)

        return box

    # -- Helpers --------------------------------------------------------

    def _populate_general_settings(self) -> None:
        if hasattr(self, "log_path_label"):
            self.log_path_label.setText(f"日志：{self.log_path}")

    def _refresh_target_list(self) -> None:
        self.target_list.blockSignals(True)
        self.target_list.clear()
        for target in self.targets:
            icon = "✅ " if target.enabled else "⏸ "
            self.target_list.addItem(f"{icon}{target.name} ({target.platform})")
        self.target_list.blockSignals(False)
        self._update_target_lookup()

    def _on_target_selected(self, row: int) -> None:
        if row < 0 or row >= len(self.targets):
            self.current_index = None
            self._clear_target_form()
            return
        self.current_index = row
        target = self.targets[row]
        self.enabled_checkbox.setChecked(target.enabled)
        self.name_edit.setText(target.name)
        self.url_edit.setText(target.url)
        if self.platform_combo.findText(target.platform) == -1:
            self.platform_combo.addItem(target.platform)
        self.platform_combo.setCurrentText(target.platform)
        self.quality_combo.setCurrentText(target.quality)
        self.poll_override_spin.setValue(target.poll_interval)
        self.format_combo.setCurrentText(target.fmt)
        self.output_dir_edit.setText(str(target.output_dir))
        self.cookies_edit.setText(str(target.cookies_file) if target.cookies_file else "")
        self.proxy_edit.setText(target.proxy or "")

    def _clear_target_form(self) -> None:
        self.enabled_checkbox.setChecked(False)
        self.name_edit.clear()
        self.url_edit.clear()
        self.platform_combo.setCurrentIndex(0)
        self.quality_combo.setCurrentIndex(0)
        self.poll_override_spin.setValue(self.config.default_poll_interval)
        self.format_combo.setCurrentText(self.config.default_format)
        self.output_dir_edit.clear()
        self.cookies_edit.clear()
        self.proxy_edit.clear()

    def _collect_target_data(self) -> dict:
        return {
            "name": self.name_edit.text().strip() or "未命名",
            "url": self.url_edit.text().strip(),
            "platform": self.platform_combo.currentText().strip(),
            "quality": self.quality_combo.currentText(),
            "poll_interval": self.poll_override_spin.value(),
            "format": self.format_combo.currentText(),
            "output_dir": self.output_dir_edit.text().strip(),
            "cookies_file": self.cookies_edit.text().strip() or None,
            "proxy": self.proxy_edit.text().strip() or None,
            "enabled": self.enabled_checkbox.isChecked(),
        }

    def _update_target_lookup(self) -> None:
        self._target_lookup = {target.name: target for target in self.targets}

    def has_enabled_targets(self) -> bool:
        return any(target.enabled for target in self.targets)

    def _reset_status_table(self) -> None:
        self.status_table.setRowCount(0)
        self.status_rows.clear()

    def _get_platform_for_name(self, name: str) -> str:
        target = self._target_lookup.get(name)
        return target.platform if target else "-"

    def _apply_current_changes(self) -> None:
        if self.current_index is None:
            QtWidgets.QMessageBox.warning(self, "提示", "请选择一个流再修改。")
            return
        data = self._collect_target_data()
        if not data["url"]:
            QtWidgets.QMessageBox.warning(self, "提示", "URL 不能为空。")
            return
        target = self._build_target_from_data(data)
        self.targets[self.current_index] = target
        self._refresh_target_list()
        self.target_list.setCurrentRow(self.current_index)

    def _add_target(self) -> None:
        new_target = self._build_target_from_data(
            {
                "name": f"stream-{len(self.targets)+1}",
                "url": "",
                "platform": "auto",
                "quality": self.config.default_quality,
                "poll_interval": self.config.default_poll_interval,
                "format": self.config.default_format,
                "output_dir": "",
                "cookies_file": None,
                "proxy": None,
                "enabled": False,
            }
        )
        self.targets.append(new_target)
        self._refresh_target_list()
        self.target_list.setCurrentRow(len(self.targets) - 1)
        self._update_target_lookup()

    def _duplicate_target(self) -> None:
        if self.current_index is None:
            return
        original = self.targets[self.current_index]
        dup = StreamTarget(
            name=f"{original.name}-copy",
            url=original.url,
            platform=original.platform,
            quality=original.quality,
            poll_interval=original.poll_interval,
            fmt=original.fmt,
            output_dir=original.output_dir,
            cookies_file=original.cookies_file,
            proxy=original.proxy,
            enabled=original.enabled,
        )
        self.targets.insert(self.current_index + 1, dup)
        self._refresh_target_list()
        self.target_list.setCurrentRow(self.current_index + 1)
        self._update_target_lookup()

    def _delete_target(self) -> None:
        if self.current_index is None:
            return
        if QtWidgets.QMessageBox.question(self, "确认", "确定要删除该条流配置吗？") != QtWidgets.QMessageBox.Yes:
            return
        self.targets.pop(self.current_index)
        self._refresh_target_list()
        if self.targets:
            self.target_list.setCurrentRow(min(len(self.targets) - 1, self.current_index))
        else:
            self._clear_target_form()
        self._update_target_lookup()

    def _build_target_from_data(self, data: dict) -> StreamTarget:
        output_raw = data.get("output_dir") or ""
        if output_raw:
            output_dir = Path(output_raw).expanduser()
        else:
            output_dir = processing_path("stream_monitor") / data["name"]
        cookies = Path(data["cookies_file"]).expanduser() if data.get("cookies_file") else None
        platform = data["platform"].strip()
        try:
            platform = resolve_platform(platform or "auto", data["url"])
        except ValueError:
            platform = platform or "douyin"
        return StreamTarget(
            name=data["name"],
            url=data["url"],
            platform=platform,
            quality=data["quality"],
            poll_interval=data["poll_interval"],
            fmt=data["format"],
            output_dir=output_dir,
            cookies_file=cookies,
            proxy=data.get("proxy"),
            enabled=data.get("enabled", True),
        )

    def _reload_from_disk(self) -> None:
        self.config, self.cfg_path, _ = load_stream_monitor_config(self.config_path)
        self.targets = list(self.config.targets)
        self._populate_general_settings()
        self._refresh_target_list()
        self._update_target_lookup()
        if self.targets:
            self.target_list.setCurrentRow(0)
        self._reset_status_table()

    def refresh_from_disk(self) -> None:
        self._reload_from_disk()

    def _save_config(self, show_message: bool = True) -> None:
        if self.current_index is not None:
            self._apply_current_changes()
        self.config.targets = self.targets
        save_stream_monitor_config(self.config, self.cfg_path)
        if show_message:
            QtWidgets.QMessageBox.information(self, "完成", f"配置已保存：{self.cfg_path}")
        self._refresh_target_list()

    # -- Monitor control ------------------------------------------------

    def start_monitor(self) -> None:
        if self.monitor_worker and self.monitor_worker.isRunning():
            QtWidgets.QMessageBox.information(self, "提示", "监控已在运行。")
            return
        self._save_config(show_message=False)
        self._reload_from_disk()
        if not self.has_enabled_targets():
            QtWidgets.QMessageBox.warning(self, "提示", "暂无启用的监控目标，请先在列表中勾选。")
            return
        self._reset_status_table()
        self.monitor_worker = StreamMonitorWorker(config_path=self.cfg_path, log_path=self.log_path)
        self.monitor_worker.event_emitted.connect(self._handle_monitor_event)
        self.monitor_worker.status_changed.connect(self._on_monitor_status_change)
        self.monitor_worker.error_occurred.connect(self._on_monitor_error)
        self.monitor_worker.finished.connect(self._on_monitor_finished)
        self.monitor_worker.start()
        self.btn_start_monitor.setEnabled(False)
        self.btn_stop_monitor.setEnabled(True)
        self.monitor_status_label.setText("启动中…")

    def stop_monitor(self) -> None:
        if self.monitor_worker and self.monitor_worker.isRunning():
            self.monitor_worker.request_stop()
            self.monitor_status_label.setText("停止中…")
            self.btn_stop_monitor.setEnabled(False)

    def _shutdown_monitor(self) -> None:
        if self.monitor_worker:
            if self.monitor_worker.isRunning():
                self.monitor_worker.request_stop()
                self.monitor_worker.wait(3000)
            self.monitor_worker = None

    def _handle_monitor_event(self, event: MonitorEvent) -> None:
        slug = slugify(event.target)
        row = self.status_rows.get(slug)
        if row is None:
            row = self.status_table.rowCount()
            self.status_table.insertRow(row)
            self.status_rows[slug] = row
            for col in range(6):
                self.status_table.setItem(row, col, QtWidgets.QTableWidgetItem(""))
        if event.target != "monitor":
            self.status_table.item(row, 0).setText(event.target)
            self.status_table.item(row, 1).setText(self._get_platform_for_name(event.target))
        self.status_table.item(row, 2).setText(event.event)
        self.status_table.item(row, 3).setText(event.message or "")
        extra = event.details.get("output") or event.details.get("url") or ""
        self.status_table.item(row, 4).setText(str(extra))
        self.status_table.item(row, 5).setText(event.timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        self.status_table.scrollToBottom()

    def _on_monitor_status_change(self, status: str) -> None:
        if status == "running":
            self.monitor_status_label.setText("运行中")
        else:
            self.monitor_status_label.setText("已停止")
            self.btn_start_monitor.setEnabled(True)
            self.btn_stop_monitor.setEnabled(False)

    def _on_monitor_error(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "监控异常", message)

    def _on_monitor_finished(self) -> None:
        self.monitor_worker = None

    def _open_log_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_path.parent)))

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._shutdown_monitor()
        super().closeEvent(event)

    # -- Browsers -------------------------------------------------------

    def _browse_output_dir(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_dir_edit.text())
        if directory:
            self.output_dir_edit.setText(directory)

    def _browse_cookies(self) -> None:
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择 cookies 文本", "", "Text Files (*.txt);;All Files (*)")
        if filename:
            self.cookies_edit.setText(filename)


def launch_editor(config_path: Optional[str] = None) -> None:
    import sys

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window = StreamMonitorEditor(Path(config_path) if config_path else None)
    window.show()
    app.exec_()


class StreamMonitorEditor(QtWidgets.QMainWindow):
    """Standalone wrapper window for the editor widget."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        super().__init__()
        self.setWindowTitle("ACFV Stream Monitor Config")
        self.resize(1024, 720)
        self.editor_widget = StreamMonitorEditorWidget(config_path=config_path, parent=self)
        self.setCentralWidget(self.editor_widget)
