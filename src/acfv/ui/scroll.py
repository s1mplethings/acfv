"""Scrolling behaviour helpers for Qt widgets."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Iterable, Optional, Set, Tuple, cast

from PyQt5.QtCore import QObject, QEvent, QPropertyAnimation, QAbstractAnimation, QEasingCurve, QPoint
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtWidgets import QAbstractItemView, QAbstractScrollArea, QWidget

_LOGGER = logging.getLogger(__name__)

DEFAULT_SINGLE_STEP = 2
DEFAULT_PAGE_STEP = 40

# 新增：滚轮平滑参数（像素步长与动画时长）
DEFAULT_WHEEL_PIXELS_PER_STEP = 24  # 一档滚轮对应的像素位移
DEFAULT_WHEEL_ANIM_MS = 140         # 动画时长（毫秒）


def _resolve_steps(single_step: Optional[int], page_step: Optional[int]) -> Tuple[int, int]:
    """Return scroll step sizes, falling back to config defaults when unset."""
    cfg_single, cfg_page = _load_configured_steps()
    resolved_single = cfg_single if single_step is None else single_step
    resolved_page = cfg_page if page_step is None else page_step

    # Clamp to sensible minimums to avoid zero/negative steps breaking scrolling queues.
    resolved_single = max(1, resolved_single)
    resolved_page = max(resolved_single, resolved_page)
    return resolved_single, resolved_page


@lru_cache(maxsize=1)
def _load_configured_steps() -> Tuple[int, int]:
    """Read smooth-scroll settings from the shared config (cached)."""
    try:
        from acfv.config.config import ConfigManager

        manager = ConfigManager()
        single = manager.get("UI_SCROLL_SINGLE_STEP", DEFAULT_SINGLE_STEP)
        page = manager.get("UI_SCROLL_PAGE_STEP", DEFAULT_PAGE_STEP)
        single_int = int(single)
        page_int = int(page)
        return single_int, page_int
    except Exception as exc:  # pragma: no cover - defensive guard
        _LOGGER.debug("Falling back to hardcoded scroll defaults: %s", exc)
        return DEFAULT_SINGLE_STEP, DEFAULT_PAGE_STEP


@lru_cache(maxsize=1)
def _load_wheel_smoothing_cfg() -> Tuple[int, int]:
    """Read wheel smoothing config (pixels per step, anim ms)."""
    try:
        from acfv.config.config import ConfigManager

        manager = ConfigManager()
        px = int(manager.get("UI_WHEEL_PIXELS_PER_STEP", DEFAULT_WHEEL_PIXELS_PER_STEP))
        ms = int(manager.get("UI_WHEEL_ANIM_MS", DEFAULT_WHEEL_ANIM_MS))
        return max(1, px), max(0, ms)
    except Exception as exc:  # pragma: no cover
        _LOGGER.debug("Falling back to wheel smoothing defaults: %s", exc)
        return DEFAULT_WHEEL_PIXELS_PER_STEP, DEFAULT_WHEEL_ANIM_MS


def _configure_scrollbar(widget: QAbstractScrollArea, *, single_step: int, page_step: int) -> None:
    """Apply sane scrolling increments to a single scroll area."""
    try:
        vertical = widget.verticalScrollBar()
        if vertical is not None:
            vertical.setSingleStep(single_step)
            vertical.setPageStep(page_step)
        horizontal = widget.horizontalScrollBar()
        if horizontal is not None:
            horizontal.setSingleStep(single_step)
            horizontal.setPageStep(page_step)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("Skip scrollbar tuning for %s: %s", widget, exc)

    if isinstance(widget, QAbstractItemView):
        try:
            widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            widget.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("Skip per-pixel scroll for %s: %s", widget, exc)

    # 新增：为所有 QAbstractScrollArea 装配滚轮平滑过滤器
    try:
        _ensure_wheel_smoother(widget)
    except Exception as exc:
        _LOGGER.debug("Skip installing wheel smoother for %s: %s", widget, exc)


class _WheelSmoother(QObject):
    """
    捕获 QEvent.Wheel 并将滚动转换为“像素级平滑+动画”的事件过滤器。
    适用：所有继承 QAbstractScrollArea 的组件（包含 QScrollArea、QTextEdit、QPlainTextEdit、QTableView 等）。
    """

    def __init__(self, area: QAbstractScrollArea, pixels_per_step: int, anim_ms: int) -> None:
        super().__init__(area)
        self._area = area
        self._px = max(1, pixels_per_step)
        self._anim_ms = max(0, anim_ms)

    def _animate_to(self, sb, target: int) -> None:
        target = max(sb.minimum(), min(sb.maximum(), target))
        if self._anim_ms <= 0:
            sb.setValue(target)
            return

        # 将动画对象挂到滚动条上，避免被 GC
        anim = getattr(sb, "_smooth_anim", None)
        if isinstance(anim, QPropertyAnimation) and anim.state() == QAbstractAnimation.State.Running:
            anim.stop()

        anim = QPropertyAnimation(sb, b"value", sb)
        setattr(sb, "_smooth_anim", anim)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setDuration(self._anim_ms)
        anim.setStartValue(sb.value())
        anim.setEndValue(target)
        anim.start()

    def _handle_single_scrollbar(self, sb, delta_pixels: int) -> None:
        if sb is None:
            return
        self._animate_to(sb, sb.value() - int(delta_pixels))

    def eventFilter(self, a0, a1) -> bool:  # noqa: D401
        if a1 is None or a1.type() != QEvent.Type.Wheel:  # type: ignore[union-attr]
            return super().eventFilter(a0, a1)

        wheel_event = cast(QWheelEvent, a1)

        # 优先使用 pixelDelta（触控板），否则用 angleDelta（传统滚轮，一档=120）
        pd: QPoint = wheel_event.pixelDelta()
        ad: QPoint = wheel_event.angleDelta()

        dx = pd.x() if not pd.isNull() else (ad.x() / 120.0) * self._px
        dy = pd.y() if not pd.isNull() else (ad.y() / 120.0) * self._px

        # 选择滚动条
        vbar = self._area.verticalScrollBar()
        hbar = self._area.horizontalScrollBar()

        # 若同时有水平/垂直增量，分别处理
        if abs(dy) >= 1 and vbar is not None and vbar.isVisible():
            self._handle_single_scrollbar(vbar, int(dy))
            wheel_event.accept()
        if abs(dx) >= 1 and hbar is not None and hbar.isVisible():
            self._handle_single_scrollbar(hbar, int(dx))
            wheel_event.accept()

        # 阻止默认的“大步进/整页”滚动
        return True


def _ensure_wheel_smoother(area: QAbstractScrollArea) -> None:
    if area is None:
        return
    # 避免重复安装
    if getattr(area, "_wheel_smoother_attached", False):
        return

    px, ms = _load_wheel_smoothing_cfg()
    vf = getattr(area, "viewport", None)
    target = vf() if callable(vf) else None
    if target is None:
        # 某些情况下 viewport 尚未构造，退化到对自身安装
        target = area

    if isinstance(target, QObject):
        filt = _WheelSmoother(area, pixels_per_step=px, anim_ms=ms)
        target.installEventFilter(filt)
        # 挂靠到实例，避免被 GC
        setattr(area, "_wheel_smoother_filter", filt)
        setattr(area, "_wheel_smoother_attached", True)


def enable_smooth_scrolling(
    widget: QAbstractScrollArea,
    *,
    single_step: Optional[int] = None,
    page_step: Optional[int] = None,
) -> None:
    """Tune a scrollable widget so the mouse wheel does not jump by pages."""
    if widget is None:
        return
    resolved_single, resolved_page = _resolve_steps(single_step, page_step)
    _configure_scrollbar(widget, single_step=resolved_single, page_step=resolved_page)


def apply_smooth_scrolling(
    root: QWidget,
    *,
    include_children: bool = True,
    single_step: Optional[int] = None,
    page_step: Optional[int] = None,
) -> None:
    """Apply smooth scrolling to ``root`` and optionally every scrollable descendant."""
    if root is None:
        return

    seen: Set[int] = set()

    def _yield_targets() -> Iterable[QAbstractScrollArea]:
        if isinstance(root, QAbstractScrollArea):
            yield root
        if include_children:
            for child in root.findChildren(QAbstractScrollArea):
                yield child

    for widget in _yield_targets():
        ident = id(widget)
        if ident in seen:
            continue
        seen.add(ident)
        resolved_single, resolved_page = _resolve_steps(single_step, page_step)
        _configure_scrollbar(widget, single_step=resolved_single, page_step=resolved_page)
