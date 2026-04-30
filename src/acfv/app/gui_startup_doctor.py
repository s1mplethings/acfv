from __future__ import annotations

import importlib
import importlib.util
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from acfv.background_runtime import create_background_runtime

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class StartupIssue:
    key: str
    title: str
    detail: str
    can_auto_fix: bool = False
    packages: tuple[str, ...] = ()


@dataclass
class StartupCheckReport:
    issues: list[StartupIssue] = field(default_factory=list)
    installed_packages: list[str] = field(default_factory=list)
    install_error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not self.issues and not self.install_error


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _ffmpeg_available() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def _safe_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def collect_startup_issues(config_manager: Any) -> list[StartupIssue]:
    issues: list[StartupIssue] = []

    try:
        create_background_runtime(log_level=str(config_manager.get("LOG_LEVEL", "INFO")))
    except Exception as exc:  # noqa: BLE001
        issues.append(
            StartupIssue(
                key="background_runtime",
                title="后台运行环境初始化失败",
                detail=str(exc),
            )
        )

    if not _ffmpeg_available():
        issues.append(
            StartupIssue(
                key="ffmpeg",
                title="未检测到 ffmpeg",
                detail="转录、抽音频和裁剪都依赖 ffmpeg；请把 ffmpeg 加到 PATH 或放到项目工具目录。",
            )
        )

    engine = str(config_manager.get("WHISPER_ENGINE", "auto") or "auto").strip().lower()
    has_openai_whisper = _module_available("whisper")
    has_faster_whisper = _module_available("faster_whisper")
    has_transformers = _module_available("transformers")

    if engine == "auto":
        if not has_openai_whisper and not has_faster_whisper:
            issues.append(
                StartupIssue(
                    key="asr_auto",
                    title="缺少可用转录引擎",
                    detail="当前配置为 auto，但没有检测到 openai-whisper 或 faster-whisper。",
                    can_auto_fix=True,
                    packages=("openai-whisper",),
                )
            )
    elif engine == "openai-whisper" and not has_openai_whisper:
        issues.append(
            StartupIssue(
                key="openai_whisper",
                title="缺少 openai-whisper",
                detail="当前转录引擎配置为 openai-whisper。",
                can_auto_fix=True,
                packages=("openai-whisper",),
            )
        )
    elif engine == "faster-whisper" and not has_faster_whisper:
        issues.append(
            StartupIssue(
                key="faster_whisper",
                title="缺少 faster-whisper",
                detail="当前转录引擎配置为 faster-whisper。",
                can_auto_fix=True,
                packages=("faster-whisper",),
            )
        )
    elif engine == "hf-whisper" and not has_transformers:
        issues.append(
            StartupIssue(
                key="hf_whisper",
                title="缺少 transformers",
                detail="当前转录引擎配置为 hf-whisper。",
                can_auto_fix=True,
                packages=("transformers",),
            )
        )

    return issues


def collect_auto_fix_packages(issues: Iterable[StartupIssue]) -> list[str]:
    packages: list[str] = []
    seen: set[str] = set()
    for issue in issues:
        if not issue.can_auto_fix:
            continue
        for package in issue.packages:
            normalized = package.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            packages.append(normalized)
    return packages


def install_missing_python_packages(
    packages: Sequence[str],
    *,
    python_executable: Optional[str] = None,
    timeout_sec: int = 1800,
) -> tuple[bool, str]:
    if not packages:
        return True, ""

    cmd = [
        python_executable or sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        *packages,
    ]
    LOGGER.info("[gui-startup] installing missing packages: %s", ", ".join(packages))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout_sec,
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)

    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if result.returncode != 0:
        return False, output or f"pip exited with code {result.returncode}"
    importlib.invalidate_caches()
    return True, output


def run_startup_self_check(config_manager: Any, *, attempt_auto_fix: Optional[bool] = None) -> StartupCheckReport:
    report = StartupCheckReport()
    if not _safe_bool(config_manager.get("GUI_STARTUP_SELF_CHECK", True), True):
        return report

    report.issues = collect_startup_issues(config_manager)
    auto_fix_enabled = (
        _safe_bool(config_manager.get("GUI_AUTO_INSTALL_MISSING_DEPS", True), True)
        if attempt_auto_fix is None
        else attempt_auto_fix
    )
    if report.issues and auto_fix_enabled:
        packages = collect_auto_fix_packages(report.issues)
        if packages:
            ok, output = install_missing_python_packages(packages)
            report.installed_packages = packages
            if not ok:
                report.install_error = output
            report.issues = collect_startup_issues(config_manager)
    return report


def format_startup_report(report: StartupCheckReport) -> str:
    lines: list[str] = []
    if report.installed_packages:
        lines.append("已尝试自动安装: " + ", ".join(report.installed_packages))
    if report.install_error:
        lines.append("自动安装失败: " + report.install_error.strip())
    if report.issues:
        lines.append("启动自检仍发现以下问题：")
        for issue in report.issues:
            suffix = "（可自动安装）" if issue.can_auto_fix else ""
            lines.append(f"- {issue.title}{suffix}: {issue.detail}")
    elif not lines:
        lines.append("启动自检通过。")
    return "\n".join(lines)
