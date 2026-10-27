from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QTextEdit,
    QSpinBox,
    QMessageBox,
    QTabWidget,
    QSplitter,
)

from .scan import scan_project, FoundSpec
from .vscode import open_in_vscode, find_line_of_token


class CodeGui(QMainWindow):
    def __init__(self, project_root: Optional[str] = None) -> None:
        super().__init__()
        self.setWindowTitle("code-gui (ACFV DevTool)")
        self.resize(1200, 720)

        self.project_root = project_root or ""
        self.results: List[FoundSpec] = []
        self.modules: List[FoundSpec] = []
        self.adapters: List[FoundSpec] = []

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self._build_modules_tab()
        self._build_adapters_tab()

        if self.project_root:
            self.root_edit.setText(self.project_root)
            self.scan_now(show_message=False)

    def _msg(self, title: str, text: str) -> None:
        QMessageBox.information(self, title, text)

    def _err(self, title: str, text: str) -> None:
        QMessageBox.critical(self, title, text)

    def _build_modules_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)

        top = QHBoxLayout()
        self.root_edit = QLineEdit()
        self.root_edit.setPlaceholderText("Project root (repo folder)")
        btn_pick = QPushButton("Pick Root")
        btn_scan = QPushButton("Scan")
        btn_pick.clicked.connect(self.pick_root)
        btn_scan.clicked.connect(self.scan_now)
        top.addWidget(QLabel("Root"))
        top.addWidget(self.root_edit, 1)
        top.addWidget(btn_pick)
        top.addWidget(btn_scan)
        layout.addLayout(top)

        split = QSplitter()
        left = QWidget()
        left_l = QVBoxLayout(left)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter modules...")
        self.search_edit.textChanged.connect(self.refresh_module_list)
        left_l.addWidget(self.search_edit)

        self.module_list = QListWidget()
        self.module_list.currentItemChanged.connect(self.on_module_selected)
        left_l.addWidget(self.module_list, 1)

        right = QWidget()
        right_l = QVBoxLayout(right)

        self.module_info = QTextEdit()
        self.module_info.setReadOnly(True)
        right_l.addWidget(self.module_info, 1)

        openbar = QHBoxLayout()
        self.goto_line = QSpinBox()
        self.goto_line.setRange(0, 10_000_000)
        self.goto_line.setValue(0)
        self.goto_token = QLineEdit()
        self.goto_token.setPlaceholderText("Token search (e.g. def run)")
        btn_open = QPushButton("Open Implementation Folder")
        btn_open.clicked.connect(self.open_selected_module)

        openbar.addWidget(QLabel("Line"))
        openbar.addWidget(self.goto_line)
        openbar.addWidget(QLabel("Token"))
        openbar.addWidget(self.goto_token, 1)
        openbar.addWidget(btn_open)
        right_l.addLayout(openbar)

        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([420, 780])
        layout.addWidget(split, 1)

        self.tabs.addTab(page, "Modules")

    def _build_adapters_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)

        split = QSplitter()
        self.adapter_list = QListWidget()
        self.adapter_list.currentItemChanged.connect(self.on_adapter_selected)

        right = QWidget()
        right_l = QVBoxLayout(right)
        self.adapter_info = QTextEdit()
        self.adapter_info.setReadOnly(True)
        right_l.addWidget(self.adapter_info, 1)

        btn_open = QPushButton("Open Adapter Folder")
        btn_open.clicked.connect(self.open_selected_adapter)
        right_l.addWidget(btn_open)

        split.addWidget(self.adapter_list)
        split.addWidget(right)
        split.setSizes([520, 680])
        layout.addWidget(split, 1)

        self.tabs.addTab(page, "Adapters")

    def pick_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select project root", str(Path.cwd()))
        if d:
            self.root_edit.setText(d)

    def scan_now(self, show_message: bool = True) -> None:
        root = self.root_edit.text().strip()
        if not root:
            self._err("Missing root", "Select a project root folder")
            return
        self.project_root = root

        self.results = scan_project(root)
        self.modules = [x for x in self.results if x.kind == "module"]
        self.adapters = [x for x in self.results if x.kind == "adapter"]

        self.refresh_module_list()
        self.refresh_adapter_list()

        if show_message:
            self._msg("Scan complete", f"modules: {len(self.modules)} | adapters: {len(self.adapters)}")

    def refresh_module_list(self) -> None:
        q = self.search_edit.text().strip().lower()
        self.module_list.clear()
        for m in self.modules:
            if q and q not in m.name.lower():
                continue
            item = QListWidgetItem(f"{m.name} ({m.version})")
            item.setData(Qt.UserRole, m.name)
            tooltip = self._module_tooltip(m)
            if tooltip:
                item.setToolTip(tooltip)
            self.module_list.addItem(item)
        if self.module_list.count() > 0 and self.module_list.currentRow() < 0:
            self.module_list.setCurrentRow(0)

    def refresh_adapter_list(self) -> None:
        self.adapter_list.clear()
        for a in self.adapters:
            item = QListWidgetItem(f"{a.name} [{a.src} -> {a.dst}]")
            item.setData(Qt.UserRole, a.name)
            tooltip = self._adapter_tooltip(a)
            if tooltip:
                item.setToolTip(tooltip)
            self.adapter_list.addItem(item)
        if self.adapter_list.count() > 0 and self.adapter_list.currentRow() < 0:
            self.adapter_list.setCurrentRow(0)

    def on_module_selected(self, cur, prev) -> None:
        if not cur:
            return
        name = cur.data(Qt.UserRole)
        m = next((x for x in self.modules if x.name == name), None)
        if not m:
            return
        requires = "\n".join(m.requires) if m.requires else "-"
        provides = "\n".join(m.provides) if m.provides else "-"
        description = m.description or "-"
        impl_path = self._display_impl_path(m) or "-"
        self.module_info.setPlainText(
            f"Name: {m.name}\n"
            f"Version: {m.version}\n"
            f"File: {m.file_path}\n"
            f"Line: {m.line}\n\n"
            f"Description:\n{description}\n\n"
            f"Implementation:\n{impl_path}\n\n"
            f"Requires:\n{requires}\n\n"
            f"Provides:\n{provides}"
        )

    def on_adapter_selected(self, cur, prev) -> None:
        if not cur:
            return
        name = cur.data(Qt.UserRole)
        a = next((x for x in self.adapters if x.name == name), None)
        if not a:
            return
        description = a.description or "-"
        self.adapter_info.setPlainText(
            f"Name: {a.name}\n"
            f"Version: {a.version}\n"
            f"Src: {a.src}\n"
            f"Dst: {a.dst}\n"
            f"Description:\n{description}\n"
            f"File: {a.file_path}\n"
            f"Line: {a.line}\n"
        )

    def open_selected_module(self) -> None:
        cur = self.module_list.currentItem()
        if not cur:
            return
        name = cur.data(Qt.UserRole)
        m = next((x for x in self.modules if x.name == name), None)
        if not m:
            return

        line = self.goto_line.value()
        token = self.goto_token.text().strip()

        impl_file = self._resolve_impl_file(m)
        target_file = impl_file or Path(m.file_path)
        default_line = 1 if impl_file else m.line
        goto = None
        if line > 0:
            goto = line
        else:
            if token:
                tline = find_line_of_token(str(target_file), token)
                if tline:
                    goto = tline
            if goto is None:
                goto = default_line

        try:
            module_dir = str(target_file.parent)
            open_in_vscode(str(target_file), goto, workspace_dir=module_dir, new_window=True)
        except Exception as exc:
            self._err("Open failed", str(exc))

    def open_selected_adapter(self) -> None:
        cur = self.adapter_list.currentItem()
        if not cur:
            return
        name = cur.data(Qt.UserRole)
        a = next((x for x in self.adapters if x.name == name), None)
        if not a:
            return
        try:
            adapter_dir = str(Path(a.file_path).parent)
            open_in_vscode(a.file_path, a.line, workspace_dir=adapter_dir, new_window=True)
        except Exception as exc:
            self._err("Open failed", str(exc))

    def _module_tooltip(self, spec: FoundSpec) -> str:
        parts: List[str] = []
        if spec.description:
            parts.append(spec.description)
        if spec.requires:
            parts.append("Inputs: " + ", ".join(spec.requires))
        if spec.provides:
            parts.append("Outputs: " + ", ".join(spec.provides))
        return "\n".join(parts)

    def _adapter_tooltip(self, spec: FoundSpec) -> str:
        parts: List[str] = []
        if spec.description:
            parts.append(spec.description)
        if spec.src and spec.dst:
            parts.append(f"Converts: {spec.src} -> {spec.dst}")
        return "\n".join(parts)

    def _resolve_impl_file(self, spec: FoundSpec) -> Optional[Path]:
        if not spec.impl_path:
            return None
        impl = Path(spec.impl_path)
        if impl.is_absolute():
            return impl if impl.exists() else None
        root = Path(self.project_root) if self.project_root else Path.cwd()
        candidate = (root / impl).resolve()
        if candidate.exists():
            return candidate
        candidate = (Path(spec.file_path).parent / impl).resolve()
        if candidate.exists():
            return candidate
        return None

    def _display_impl_path(self, spec: FoundSpec) -> Optional[str]:
        impl_file = self._resolve_impl_file(spec)
        if impl_file:
            return str(impl_file)
        return spec.impl_path


def run_gui(project_root: Optional[str] = None) -> None:
    app = QApplication(sys.argv)
    window = CodeGui(project_root=project_root)
    window.show()
    sys.exit(app.exec_())


__all__ = ["run_gui", "CodeGui"]
