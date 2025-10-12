# tests/gui_dify_test.py
# -*- coding: utf-8 -*-
"""
极简 Dify 测试 GUI（增强版：自动自保活 8099）
- 启动时自动自检：确保 8099 工具服务存活；未启动则自动拉起 uvicorn（必要时自动写入缺省服务文件）
- “Preflight”/运行前再次兜底
"""
from __future__ import annotations

import os
import sys
import json
import time
import subprocess
from typing import Optional

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QLabel, QMessageBox, QCheckBox,
    QInputDialog, QLineEdit, QSplitter
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt

# ------------------ 路径设置 ------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

SERVICES_DIR = os.path.join(BASE_DIR, "services")
TOOL_FILE = os.path.join(SERVICES_DIR, "tool_server.py")
TOOL_MODULE = "services.tool_server:app"   # uvicorn 入口
TOOL_PORT = 8099
TOOL_HEALTH = f"http://127.0.0.1:{TOOL_PORT}/health"

# ------------------ 依赖：requests(可选) ------------------
try:
    import requests  # type: ignore
except Exception:
    requests = None

def http_get(url: str, timeout: float = 2.0) -> Optional[int]:
    """尽量用 requests；没有就用 urllib"""
    try:
        if requests:
            r = requests.get(url, timeout=timeout)
            return r.status_code
        else:
            import urllib.request  # type: ignore
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.getcode()
    except Exception:
        return None

# ------------------ Dify Backend ------------------
from services.dify_backend_service import get_backend

# ---- 启动时确保环境变量 ----
def ensure_env(default_base="http://localhost:5001/v1", cfg_name="dify_local.json", interactive=True):
    if not os.getenv("DIFY_BASE_URL"):
        os.environ["DIFY_BASE_URL"] = default_base
    if not os.getenv("DIFY_API_KEY"):
        cfg_path = os.path.join(BASE_DIR, cfg_name)
        key = None
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    obj = json.load(f) or {}
                    key = (obj.get("api_key") or "").strip()
                    base = (obj.get("base_url") or "").strip()
                    if base:
                        os.environ["DIFY_BASE_URL"] = base
            except Exception:
                pass
        if not key and interactive:
            key, ok = QInputDialog.getText(None, "Dify API Key", "请输入 Dify 应用的 API Key：", QLineEdit.Normal)
            if not ok or not key.strip():
                raise RuntimeError("未提供 DIFY_API_KEY")
            key = key.strip()
        if key:
            os.environ["DIFY_API_KEY"] = key
            try:
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump({"api_key": key, "base_url": os.environ["DIFY_BASE_URL"]}, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

# ------------------ 8099 工具服务：自动保活 ------------------
DEFAULT_TOOL_SERVER_CODE = """# -*- coding: utf-8 -*-
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, Dict, Any

app = FastAPI(title="Local Tool for Dify", version="0.1.0")

@app.get("/health")
def health():
    return {"ok": True}

class ToolIn(BaseModel):
    user_query: Optional[str] = None
    context: Optional[Dict[str, Any]] = None

@app.post("/tool/echo")
def tool_echo(x: ToolIn):
    return {
        "received": {
            "user_query": x.user_query,
            "context": x.context or {}
        },
        "reply": f"收到：{x.user_query or ''}"
    }
"""

def ensure_tool_file_exists(log_widget: Optional[QTextEdit] = None):
    try:
        os.makedirs(SERVICES_DIR, exist_ok=True)
        if not os.path.exists(TOOL_FILE):
            with open(TOOL_FILE, "w", encoding="utf-8") as f:
                f.write(DEFAULT_TOOL_SERVER_CODE)
            if log_widget:
                log_widget.append(f"[自保活] 已写入缺省工具服务文件：{TOOL_FILE}")
    except Exception as e:
        if log_widget:
            log_widget.append(f"[自保活] 写入工具服务文件失败：{e}")

def ensure_python_deps(log_widget: Optional[QTextEdit] = None):
    """确保 fastapi/uvicorn 可用；若缺失则尝试安装（失败忽略，避免阻塞）"""
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        return
    except Exception:
        pass
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "fastapi", "uvicorn"],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False
        )
        if log_widget:
            log_widget.append("[自保活] 已尝试安装 fastapi/uvicorn 依赖")
    except Exception as e:
        if log_widget:
            log_widget.append(f"[自保活] 安装依赖失败：{e}")

def ensure_firewall_rule_windows(port: int):
    """尽力放行防火墙（需要管理员权限；失败忽略）"""
    if os.name != "nt":
        return
    try:
        out = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name=Tool{port}"],
            capture_output=True, text=True
        )
        combined = (out.stdout or "") + (out.stderr or "")
        if "No rules match" in combined or "没有与指定条件匹配的规则" in combined:
            subprocess.run(
                ["netsh", "advfirewall", "firewall", "add", "rule",
                 f"name=Tool{port}", "dir=in", "action=allow", "protocol=TCP", f"localport={port}"],
                check=False
            )
    except Exception:
        pass  # 非管理员或命令不可用时忽略

def is_tool_alive() -> bool:
    code = http_get(TOOL_HEALTH, timeout=1.5)
    return code == 200

def start_tool_subprocess(log_widget: Optional[QTextEdit] = None) -> Optional[subprocess.Popen]:
    """
    在后台拉起 uvicorn services.tool_server:app
    返回 Popen 对象，失败则返回 None
    """
    ensure_tool_file_exists(log_widget)
    ensure_python_deps(log_widget)
    ensure_firewall_rule_windows(TOOL_PORT)

    python_exec = sys.executable or "python"
    argv = [
        python_exec, "-m", "uvicorn", TOOL_MODULE,
        "--host", "0.0.0.0",
        "--port", str(TOOL_PORT),
        "--reload"
    ]
    try:
        proc = subprocess.Popen(
            argv,
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            creationflags=(0x08000000 if os.name == "nt" else 0)  # CREATE_NO_WINDOW
        )
        if log_widget:
            log_widget.append(f"[自保活] 已尝试启动 8099 工具服务（PID={proc.pid}）")
        return proc
    except Exception as e:
        if log_widget:
            log_widget.append(f"[自保活] 启动失败：{e}")
        return None

def wait_tool_ready(timeout: float = 12.0, log_widget: Optional[QTextEdit] = None) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if is_tool_alive():
            if log_widget:
                log_widget.append("[自保活] 8099 /health OK")
            return True
        time.sleep(0.4)
    if log_widget:
        log_widget.append("[自保活] 等待 8099 就绪超时")
    return False

def ensure_tool_running(log_widget: Optional[QTextEdit] = None) -> Optional[subprocess.Popen]:
    """
    确保 8099 服务存活；否则自动启动并等待健康。
    返回：子进程对象（如果是我们启动的），或者 None（本就存活）
    """
    if is_tool_alive():
        if log_widget:
            log_widget.append("[自保活] 检测到 8099 已在运行")
        return None
    proc = start_tool_subprocess(log_widget)
    if proc and wait_tool_ready(log_widget=log_widget):
        return proc
    return proc

# ------------------ 调用线程 ------------------
class RunnerWorker(QThread):
    token = pyqtSignal(str)           # 流式 token
    finished_data = pyqtSignal(dict)  # 阻塞模式结果
    error = pyqtSignal(str)
    done = pyqtSignal()

    def __init__(self, task: str, context: str, streaming: bool):
        super().__init__()
        self.task = task
        self.context = context
        self.streaming = streaming
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        backend = get_backend()
        try:
            if not self.streaming:
                data = backend.run_blocking(self.task, self.context)
                if self._stop:
                    return
                self.finished_data.emit(data)
            else:
                for piece in backend.run_streaming(self.task, self.context):
                    if self._stop:
                        break
                    self.token.emit(piece)
                self.done.emit()
        except Exception as e:
            self.error.emit(str(e))

def classify_error(msg: str) -> str:
    m = msg.lower()
    if "host.docker.internal" in m and ("8099" in m or ":8099" in m):
        return "可能的外部工具端点不可达: 请确认工具服务已启动或修改为本机IP。"
    if "invalid_param" in m and "user_query" in m:
        return "工作流可能需要 user_query / context 等字段，请核对 inputs 键名。"
    if "401" in m or "unauthorized" in m:
        return "鉴权失败: 请检查 API Key。"
    if "403" in m:
        return "权限不足或 Key 类型不匹配。"
    if "429" in m:
        return "触发限流: 稍后重试或降低频率。"
    if "timeout" in m:
        return "请求超时: 可增大 DIFY_TIMEOUT 或缩短输入。"
    return ""

# ------------------ GUI ------------------
class DifyTestGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dify 测试 - 单功能简化版（自保活 8099）")
        self.resize(820, 600)
        layout = QVBoxLayout(self)

        self.task_edit = QTextEdit()
        self.task_edit.setPlaceholderText("输入你的测试指令 ...")
        layout.addWidget(QLabel("指令 (必填)"))
        layout.addWidget(self.task_edit, 2)

        self.context_edit = QTextEdit()
        self.context_edit.setPlaceholderText("可选上下文 ...")
        layout.addWidget(QLabel("上下文 (可选)"))
        layout.addWidget(self.context_edit, 1)

        row = QHBoxLayout()
        self.chk_stream = QCheckBox("Streaming")
        self.btn_run = QPushButton("运行")
        self.btn_stop = QPushButton("停止");
        self.btn_stop.setEnabled(False)
        self.btn_clear = QPushButton("清空")
        row.addWidget(self.chk_stream)
        row.addWidget(self.btn_run)
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_clear)
        row.addStretch(1)
        layout.addLayout(row)

        # ===== 输出区域改造：左（纯回答） + 右（详细JSON/日志） =====
        splitter = QSplitter()
        splitter.setOrientation(Qt.Horizontal)

        self.pure_output_edit = QTextEdit()
        self.pure_output_edit.setReadOnly(True)
        self.pure_output_edit.setPlaceholderText("纯回答区：只显示最终回答或流式内容")

        self.detail_output_edit = QTextEdit()
        self.detail_output_edit.setReadOnly(True)
        self.detail_output_edit.setPlaceholderText("详细区：显示JSON、日志、自检信息")

        splitter.addWidget(self.pure_output_edit)
        splitter.addWidget(self.detail_output_edit)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        layout.addWidget(QLabel("输出 (左=回答 右=详细)"))
        layout.addWidget(splitter, 3)

        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

        env_row = QHBoxLayout()
        self.env_label = QLabel("")
        self.btn_env = QPushButton("Preflight")
        env_row.addWidget(self.env_label)
        env_row.addStretch(1)
        env_row.addWidget(self.btn_env)
        layout.addLayout(env_row)

        self.worker: Optional[RunnerWorker] = None
        self.tool_proc: Optional[subprocess.Popen] = None

        # 启动时准备环境
        ensure_env(default_base="http://localhost:5001/v1", interactive=True)
        try:
            backend = get_backend()
            self.env_label.setText(f"Base: {backend.client.base_url}  (mode? {getattr(backend, 'mode', 'n/a')})")
        except Exception as e:
            self.env_label.setText(f"[后端初始化失败] {e}")

        # —— 关键：启动即自保活 8099 ——
        self.detail_output_edit.append("[自保活] 开始检测 8099 工具服务 ...")
        self.tool_proc = ensure_tool_running(self.detail_output_edit)
        if is_tool_alive():
            self.detail_output_edit.append("[自保活] 8099 节点已就绪。")
        else:
            self.detail_output_edit.append("[自保活] 仍未就绪，请检查端口占用/权限（可点 Preflight 再试）。")

        # 事件绑定
        self.btn_run.clicked.connect(self.on_run)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_clear.clicked.connect(self.clear_outputs)
        self.btn_env.clicked.connect(self.on_preflight)

    def closeEvent(self, event):
        # 尝试优雅关闭我们拉起的子进程
        try:
            if self.tool_proc and self.tool_proc.poll() is None:
                self.tool_proc.terminate()
                try:
                    self.tool_proc.wait(timeout=3)
                except Exception:
                    self.tool_proc.kill()
        except Exception:
            pass
        return super().closeEvent(event)

    def on_run(self):
        task = self.task_edit.toPlainText().strip()
        if not task:
            QMessageBox.warning(self, "提示", "请输入指令")
            return
        if not is_tool_alive():
            # 运行前再次兜底
            self.detail_output_edit.append("[自保活] 运行前检测到 8099 未就绪，尝试重新拉起 ...")
            self.tool_proc = ensure_tool_running(self.detail_output_edit)
            if not is_tool_alive():
                QMessageBox.critical(self, "错误", "8099 工具服务未就绪，请检查。")
                return

        context = self.context_edit.toPlainText().strip()
        streaming = self.chk_stream.isChecked()
        self.detail_output_edit.append(f"\n=== 开始 {'Streaming' if streaming else 'Blocking'} 调用 ===")
        # 清空纯回答区开始新的内容
        self.pure_output_edit.clear()
        self.pure_output_edit.append("[开始] 接收回答…\n")
        self.set_running(True)
        self.worker = RunnerWorker(task, context, streaming)
        self.worker.error.connect(self.on_error)
        self.worker.finished_data.connect(self.on_block_result)
        self.worker.token.connect(self.on_stream_token)
        self.worker.done.connect(self.on_stream_done)
        self.worker.finished.connect(lambda: self.set_running(False))
        self.worker.start()

    def on_stop(self):
        if self.worker:
            self.worker.stop()
            self.detail_output_edit.append("\n[已请求停止]")

    def set_running(self, running: bool):
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running and self.chk_stream.isChecked())
        self.chk_stream.setEnabled(not running)
        self.status_label.setText("Running" if running else "Ready")

    def on_block_result(self, data: dict):
        # 输出结果
        answer = data.get("raw_answer") or data.get("json", {}).get("answer", "")
        if not answer:
            answer = "(无回答)"
        self.pure_output_edit.append(answer)

        try:
            pretty = json.dumps(data.get("json", {}), ensure_ascii=False, indent=2)
        except Exception:
            pretty = "{}"
        self.detail_output_edit.append("[结果 JSON]\n" + pretty)
        self.detail_output_edit.append("[原始回答]\n" + answer)
        self.detail_output_edit.append(f"[Meta] {data.get('meta')}")

    def on_stream_token(self, piece: str):
        cursor = self.pure_output_edit.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(piece)
        self.pure_output_edit.setTextCursor(cursor)
        self.pure_output_edit.ensureCursorVisible()

    def on_stream_done(self):
        self.detail_output_edit.append("\n[Streaming 结束]")

    def on_error(self, msg: str):
        hint = classify_error(msg)
        if hint:
            self.detail_output_edit.append(f"\n[错误] {msg}\n[提示] {hint}")
        else:
            self.detail_output_edit.append(f"\n[错误] {msg}")
        self.set_running(False)

    def on_preflight(self):
        # 重跑一遍工具自检，并尝试拉起
        self.detail_output_edit.append("\n[Preflight] 自检 8099 ...")
        self.tool_proc = ensure_tool_running(self.detail_output_edit)
        # 再测 Dify 连接
        try:
            backend = get_backend()
            info = backend.preflight()
            self.detail_output_edit.append("[Preflight] Dify OK: " + json.dumps(info, ensure_ascii=False, indent=2))
        except Exception as e:
            self.detail_output_edit.append(f"[Preflight] Dify 连接失败: {e}")

    # 新增：清空两个输出
    def clear_outputs(self):
        self.pure_output_edit.clear()
        self.detail_output_edit.clear()
        self.detail_output_edit.append("[已清空]")

def main():
    app = QApplication(sys.argv)
    gui = DifyTestGUI()
    gui.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
