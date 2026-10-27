"""Portable bulk-media storage selection and locator helpers.

Large Twitch media may live outside the normal runtime root, but the configured
drive is never a durable recording identity.  Persisted records use the
``BULK_MEDIA_ROOT`` alias plus a relative path and resolve the alias locally.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path, PurePosixPath
from typing import Iterable

from .storage import settings_path


GIB = 1024 ** 3
TIB = 1024 ** 4
BULK_ROOT_ALIAS = "BULK_MEDIA_ROOT"
LOCAL_MAPPING_FILE = "bulk_media_root.json"


@dataclass(frozen=True)
class StorageVolume:
    drive_letter: str
    capacity_bytes: int
    free_bytes: int
    health_status: str = "Unknown"
    operational_status: str = "Unknown"
    drive_type: str = "Fixed"
    disk_number: int | None = None
    friendly_name: str = ""
    bus_type: str = ""
    media_type: str = "Unspecified"
    is_boot: bool = False
    is_system: bool = False
    file_system: str = ""
    file_system_label: str = ""

    @property
    def root(self) -> Path:
        return Path(f"{self.drive_letter.upper()}:\\")


@dataclass(frozen=True)
class StorageDecision:
    status: str
    selected_drive: str | None
    selected_root_alias: str
    reserve_bytes: int
    estimated_corpus_bytes: int
    projected_free_bytes: int | None
    probe_allowed: bool
    reasons: tuple[str, ...]
    candidates: tuple[dict[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def safe_reserve(capacity_bytes: int) -> int:
    """Return the mandatory free-space reserve for a candidate volume."""
    return max(200 * GIB, int(max(0, capacity_bytes) * 0.15))


def _normal(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def volume_rejection_reasons(
    volume: StorageVolume,
    *,
    estimated_corpus_bytes: int = 0,
    minimum_capacity_bytes: int = TIB,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if _normal(volume.drive_type) != "fixed":
        reasons.append("not a fixed local volume")
    if volume.is_boot or volume.is_system:
        reasons.append("system or boot volume")
    if _normal(volume.health_status) not in {"healthy", "ok"}:
        reasons.append(f"unhealthy: {volume.health_status}")
    operational = _normal(volume.operational_status)
    if operational not in {"ok", "online"}:
        reasons.append(f"not operational: {volume.operational_status}")
    if volume.capacity_bytes < minimum_capacity_bytes:
        reasons.append("capacity below 1 TiB")
    reserve = safe_reserve(volume.capacity_bytes)
    if volume.free_bytes - max(0, estimated_corpus_bytes) < reserve:
        reasons.append("free space would breach SAFE_RESERVE")
    return tuple(reasons)


def select_bulk_storage(
    volumes: Iterable[StorageVolume],
    *,
    estimated_corpus_bytes: int = 0,
    preferred_drive: str = "Q",
) -> StorageDecision:
    """Select a healthy large non-system volume, preferring a valid ``Q:``.

    A failure is explicit and still permits a deliberately bounded metadata or
    small-probe workflow.  It never silently redirects a bulk corpus to the
    system SSD.
    """
    rows = list(volumes)
    audits: list[dict[str, object]] = []
    eligible: list[StorageVolume] = []
    preferred = preferred_drive.rstrip(":").upper()
    for volume in rows:
        rejected = volume_rejection_reasons(
            volume, estimated_corpus_bytes=estimated_corpus_bytes
        )
        audits.append({
            **asdict(volume),
            "safe_reserve_bytes": safe_reserve(volume.capacity_bytes),
            "projected_free_bytes": volume.free_bytes - max(0, estimated_corpus_bytes),
            "eligible": not rejected,
            "rejection_reasons": list(rejected),
        })
        if not rejected:
            eligible.append(volume)
    selected = next(
        (item for item in eligible if item.drive_letter.upper() == preferred),
        None,
    )
    if selected is None and eligible:
        selected = max(
            eligible,
            key=lambda item: (
                _normal(item.media_type) == "hdd",
                item.free_bytes,
                item.capacity_bytes,
            ),
        )
    preferred_row = next(
        (item for item in rows if item.drive_letter.upper() == preferred), None
    )
    if selected is None:
        reserve_reference = max(
            (item for item in rows if not item.is_boot and not item.is_system),
            key=lambda item: (item.capacity_bytes, item.free_bytes),
            default=None,
        )
        reasons = ["no healthy non-system volume remains above SAFE_RESERVE"]
        if preferred_row is None:
            reasons.append(f"preferred drive {preferred}: is absent")
        else:
            reasons.extend(
                f"{preferred}: {reason}"
                for reason in volume_rejection_reasons(
                    preferred_row, estimated_corpus_bytes=estimated_corpus_bytes
                )
            )
        return StorageDecision(
            status="BULK_STORAGE_NOT_AVAILABLE",
            selected_drive=None,
            selected_root_alias=BULK_ROOT_ALIAS,
            reserve_bytes=safe_reserve(reserve_reference.capacity_bytes) if reserve_reference else 200 * GIB,
            estimated_corpus_bytes=max(0, estimated_corpus_bytes),
            projected_free_bytes=(reserve_reference.free_bytes - max(0, estimated_corpus_bytes)) if reserve_reference else None,
            probe_allowed=True,
            reasons=tuple(reasons),
            candidates=tuple(audits),
        )
    reserve = safe_reserve(selected.capacity_bytes)
    reasons = (
        (f"selected preferred drive {preferred}:",)
        if selected.drive_letter.upper() == preferred
        else (f"selected best eligible fallback because {preferred}: was not eligible",)
    )
    return StorageDecision(
        status="BULK_STORAGE_READY",
        selected_drive=selected.drive_letter.upper(),
        selected_root_alias=BULK_ROOT_ALIAS,
        reserve_bytes=reserve,
        estimated_corpus_bytes=max(0, estimated_corpus_bytes),
        projected_free_bytes=selected.free_bytes - max(0, estimated_corpus_bytes),
        probe_allowed=True,
        reasons=reasons,
        candidates=tuple(audits),
    )


def persist_local_bulk_root(root: Path, *, config_path: Path | None = None) -> Path:
    """Persist one machine-local absolute mapping beneath ignored runtime state."""
    resolved = Path(root).expanduser().resolve()
    if not resolved.is_absolute():
        raise ValueError("bulk media root must be absolute")
    target = Path(config_path or settings_path(LOCAL_MAPPING_FILE))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"root_alias": BULK_ROOT_ALIAS, "path": str(resolved)}, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def bulk_media_root(*, config_path: Path | None = None, required: bool = True) -> Path | None:
    """Resolve the local root mapping without leaking it into shared specs."""
    configured = os.environ.get("ACFV_BULK_MEDIA_ROOT")
    target = Path(config_path or settings_path(LOCAL_MAPPING_FILE))
    if not configured and target.is_file():
        payload = json.loads(target.read_text(encoding="utf-8"))
        if payload.get("root_alias") != BULK_ROOT_ALIAS:
            raise ValueError("invalid bulk-media root alias")
        configured = str(payload.get("path") or "")
    if configured:
        root = Path(configured).expanduser().resolve()
        if not root.is_absolute():
            raise ValueError("bulk media root must be absolute")
        return root
    if required:
        raise RuntimeError("BULK_STORAGE_NOT_AVAILABLE: configure ACFV_BULK_MEDIA_ROOT")
    return None


def relative_bulk_locator(*parts: str) -> str:
    """Return a portable alias locator and reject traversal/absolute input."""
    relative = PurePosixPath(*parts)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("bulk locator must be a safe relative path")
    return f"{BULK_ROOT_ALIAS}/{relative.as_posix()}"


def resolve_bulk_locator(locator: str, *, root: Path | None = None) -> Path:
    prefix = f"{BULK_ROOT_ALIAS}/"
    if not locator.startswith(prefix):
        raise ValueError("unsupported bulk-media locator")
    relative = PurePosixPath(locator[len(prefix):])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("unsafe bulk-media locator")
    base = Path(root).resolve() if root is not None else bulk_media_root()
    assert base is not None
    return base.joinpath(*relative.parts)
