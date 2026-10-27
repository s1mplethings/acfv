from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable

from acfv.feedback import FeedbackService
from acfv.library import FeedbackDecision
from acfv.library.repository import LibraryRepository
from acfv.providers.download import validate_downloaded_media

from .duration import DurationProfile, DurationRequest, DurationVariant, VariantStatus
from .service import ClipService
from .subtitles import (
    ArgosTranslationProvider,
    BilingualDisplayMode,
    BilingualSubtitleService,
    BilingualSubtitleTrack,
    SubtitleCompleteness,
    SubtitlePosition,
)
from .variants import ClipEventPlan, ClipVariantService, RenderedVariant, load_event_plan


PROFILES = (
    DurationProfile.SHORT,
    DurationProfile.STANDARD,
    DurationProfile.LONG,
    DurationProfile.FULL_EVENT,
)
DISPLAY_PROFILES = (*PROFILES, DurationProfile.CUSTOM)
_ACTIVE_STATUSES = {
    "QUEUED", "BUILDING_BOUNDARY", "BUILDING_SUBTITLE", "TRANSLATING",
    "RENDERING_CLEAN", "RENDERING_BILINGUAL", "VALIDATING",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


class GuiVariantWorkflowService:
    """Durable GUI orchestration over the canonical variant/subtitle services."""

    def __init__(
        self,
        event_plan_path: Path,
        output_root: Path,
        *,
        variant_service: ClipVariantService | None = None,
        subtitle_service: BilingualSubtitleService | None = None,
        provider: Any | None = None,
        repository: LibraryRepository | None = None,
        media_validator: Callable[[Path], dict[str, Any]] = validate_downloaded_media,
    ) -> None:
        self.event_plan_path = Path(event_plan_path).resolve()
        self.output_root = Path(output_root).resolve()
        self.plan = load_event_plan(self.event_plan_path)
        if not Path(self.plan.source_path).is_file():
            raise ValueError(f"Recording media missing: {self.plan.source_path}")
        self.variant_service = variant_service or ClipVariantService()
        self.subtitle_service = subtitle_service or self.variant_service.subtitle_service
        self.provider = provider or ArgosTranslationProvider()
        self.repository = repository
        self.media_validator = media_validator
        self.state_path = self.output_root / "gui_workflow_state.json"
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()
        self.scan_outputs()
        self._write_human_review()

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.is_file():
            try:
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
                if state.get("event_id") == self.plan.event_id:
                    self._rebase_moved_state(state)
                    for row in (state.get("variants") or {}).values():
                        if row.get("status") in _ACTIVE_STATUSES:
                            row["status"] = "INTERRUPTED"
                    return state
            except (OSError, json.JSONDecodeError):
                pass
        return {
            "schema_version": "1.0",
            "recording_id": self.plan.recording_id,
            "event_id": self.plan.event_id,
            "event_plan_path": str(self.event_plan_path),
            "output_root": str(self.output_root),
            "selected_variant": "STANDARD",
            "settings": {
                "display_mode": "ZH_EN",
                "completeness": "COMPLETE",
                "position": "AUTO_SAFE_AREA",
                "custom_target_seconds": 60.0,
                "custom_min_seconds": 30.0,
                "custom_max_seconds": 90.0,
                "preview_volume": 50,
            },
            "variants": {},
            "decision": None,
            "updated_at": _now(),
        }

    def _rebase_moved_state(self, state: dict[str, Any]) -> None:
        """Keep durable workflow state portable when its output directory moves.

        Validation bundles and restored libraries may be copied to another
        machine or clean checkout.  Paths owned by the previous output root
        must follow that move even when the old directory still exists; using
        it would silently read or mutate the wrong Library.
        """
        old_value = str(state.get("output_root") or "").strip()
        old_root = Path(old_value).resolve() if old_value else self.output_root
        state["output_root"] = str(self.output_root)
        state["event_plan_path"] = str(self.event_plan_path)
        if old_root == self.output_root:
            return

        def relocated(value: Any) -> Any:
            if not isinstance(value, str) or not value.strip():
                return value
            path = Path(value)
            try:
                relative = path.resolve().relative_to(old_root)
            except (OSError, ValueError):
                return value
            return str((self.output_root / relative).resolve())

        for row in (state.get("variants") or {}).values():
            for key in ("manifest_path", "base_output_path", "latest_output_path"):
                if key in row:
                    row[key] = relocated(row[key])
            last_render = row.get("last_render")
            if isinstance(last_render, dict):
                for key in ("previous_output", "output_path"):
                    if key in last_render:
                        last_render[key] = relocated(last_render[key])
        decision = state.get("decision")
        if isinstance(decision, dict) and "output_path" in decision:
            decision["output_path"] = relocated(decision["output_path"])

    def _save(self) -> None:
        self.state["updated_at"] = _now()
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def scan_outputs(self) -> list[dict[str, Any]]:
        variants = self.state.setdefault("variants", {})
        for profile in DISPLAY_PROFILES:
            name = profile.value
            target = self.output_root / name.casefold()
            manifest_path = target / "manifest.json"
            row = dict(variants.get(name) or {})
            row.setdefault("profile", name)
            row.setdefault("status", "NOT_GENERATED")
            row.setdefault("dirty", False)
            row.setdefault("revision", 0)
            row.setdefault("cue_edit_count", 0)
            if manifest_path.is_file():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    packaged_media = target / "clip_bilingual.mp4"
                    declared_media = Path(str(manifest.get("bilingual_path") or packaged_media))
                    # A copied/restored workflow owns the media beside its
                    # current manifest, even if the embedded historical path
                    # still resolves on this machine.
                    media = packaged_media if packaged_media.is_file() else declared_media
                    discovered_status = "READY" if media.is_file() else "INTERRUPTED"
                    row.update({
                        "start_ms": int(manifest["start_ms"]),
                        "end_ms": int(manifest["end_ms"]),
                        "duration_ms": int(manifest["duration_ms"]),
                        "extension_reason": str(manifest.get("extension_reason") or ""),
                        "manifest_path": str(manifest_path),
                        "base_output_path": str(media),
                    })
                    if row.get("status") in {None, "NOT_GENERATED", "INTERRUPTED", "READY"}:
                        row["status"] = discovered_status
                    row.setdefault("latest_output_path", str(media))
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    row["status"] = "INTERRUPTED"
            variants[name] = row
        self._save()
        return self.variant_rows()

    def variant_rows(self) -> list[dict[str, Any]]:
        return [dict(self.state["variants"].get(profile.value) or {"profile": profile.value, "status": "NOT_GENERATED"})
                for profile in DISPLAY_PROFILES]

    def settings(self) -> dict[str, Any]:
        return dict(self.state["settings"])

    def update_settings(self, *, display_mode: str, completeness: str, position: str,
                        custom_target_seconds: float, custom_min_seconds: float,
                        custom_max_seconds: float, preview_volume: int,
                        apply_to_all: bool = False) -> None:
        if not 5 <= custom_target_seconds <= 600:
            raise ValueError("Custom target must be between 5 and 600 seconds")
        if not 5 <= custom_min_seconds <= custom_max_seconds <= 600:
            raise ValueError("Custom range must be ordered and between 5 and 600 seconds")
        previous = self.settings()
        current = {
            "display_mode": BilingualDisplayMode(display_mode).value,
            "completeness": SubtitleCompleteness(completeness).value,
            "position": SubtitlePosition(position).value,
            "custom_target_seconds": float(custom_target_seconds),
            "custom_min_seconds": float(custom_min_seconds),
            "custom_max_seconds": float(custom_max_seconds),
            "preview_volume": max(0, min(100, int(preview_volume))),
        }
        self.state["settings"] = current
        if any(previous.get(key) != current[key] for key in ("display_mode", "completeness", "position")):
            names = [item.value for item in PROFILES] if apply_to_all else [self.selected_profile]
            for name in names:
                self.state["variants"].setdefault(name, {})["dirty"] = True
        self._save()

    @property
    def selected_profile(self) -> str:
        return str(self.state.get("selected_variant") or "STANDARD")

    def select_variant(self, profile: str) -> dict[str, Any]:
        name = DurationProfile(profile).value
        row = self.state["variants"].get(name) or {}
        if row.get("status") != "READY":
            raise ValueError(f"Variant {name} is not ready")
        self.state["selected_variant"] = name
        self.state["selected_at"] = _now()
        row["selected"] = True
        for other_name, other in self.state["variants"].items():
            if other_name != name:
                other["selected"] = False
        self._persist_clip_selection(name, row)
        self._save()
        return dict(row)

    def _persist_clip_selection(self, name: str, row: dict[str, Any]) -> None:
        if self.repository is None:
            return
        clip = self.repository.get_clip(self.plan.clip_id)
        if clip is None:
            return
        ClipService(self.repository).select_rendered_variant(
            clip.id,
            start_ms=int(row["start_ms"]), end_ms=int(row["end_ms"]),
            profile=name,
            output_path=str(row.get("latest_output_path") or row.get("base_output_path")),
            display_mode=str(self.state["settings"]["display_mode"]),
            subtitle_completeness=str(self.state["settings"]["completeness"]),
            subtitle_position=str(self.state["settings"]["position"]),
            extension_reason=str(row.get("extension_reason") or ""),
        )

    def generate_selected(self, profile: str, *, preserve_edits: bool = True,
                          progress: Callable[[str, str], None] | None = None) -> RenderedVariant | DurationVariant:
        selected = DurationProfile(profile)
        settings = self.settings()
        request = DurationRequest(
            selected,
            settings["custom_target_seconds"] if selected is DurationProfile.CUSTOM else None,
            settings["custom_min_seconds"] if selected is DurationProfile.CUSTOM else None,
            settings["custom_max_seconds"] if selected is DurationProfile.CUSTOM else None,
        )
        old_edits = self._edit_map(selected.value) if preserve_edits else {}
        if not preserve_edits:
            self.edited_track_path(selected.value).unlink(missing_ok=True)
        callback = progress or (lambda _profile, _stage: None)
        row = self.state["variants"].setdefault(selected.value, {"profile": selected.value})
        row["status"] = "QUEUED"
        self._save()
        try:
            result = self.variant_service.generate_one(
                self.plan, request, output_root=self.output_root, provider=self.provider,
                display_mode=BilingualDisplayMode(settings["display_mode"]),
                completeness=SubtitleCompleteness(settings["completeness"]),
                position=SubtitlePosition(settings["position"]), glossary=self.plan.glossary or {},
                progress=lambda stage: self._set_stage(selected.value, stage, callback),
            )
            if isinstance(result, RenderedVariant):
                media_validation = self.media_validator(Path(result.bilingual_path))
                if old_edits:
                    track = self.subtitle_service.load_track(Path(result.output_dir) / "bilingual_track.json")
                    self._apply_edit_map(track, old_edits)
                    self.subtitle_service.save_edited_track(
                        track, self.edited_track_path(selected.value), clip_duration_ms=result.boundary.duration_ms,
                    )
                row.update({
                    "status": "READY", "start_ms": result.boundary.start_ms,
                    "end_ms": result.boundary.end_ms, "duration_ms": result.boundary.duration_ms,
                    "extension_reason": result.boundary.extension_reason,
                    "manifest_path": result.manifest_path, "base_output_path": result.bilingual_path,
                    "latest_output_path": result.bilingual_path, "dirty": bool(old_edits),
                    "media_validation": media_validation,
                })
            else:
                row.update({"status": result.status.value, "extension_reason": result.extension_reason})
            self._save()
            callback(selected.value, row["status"])
            return result
        except Exception as exc:
            row.update({"status": "FAILED", "error": str(exc)})
            self._save()
            callback(selected.value, "FAILED")
            raise

    def generate_all(self, *, preserve_edits: bool = True,
                     progress: Callable[[str, str], None] | None = None,
                     cancelled: Callable[[], bool] | None = None) -> list[RenderedVariant | DurationVariant]:
        results: list[RenderedVariant | DurationVariant] = []
        for profile in PROFILES:
            if cancelled and cancelled():
                row = self.state["variants"].setdefault(profile.value, {"profile": profile.value})
                if row.get("status") in {None, "NOT_GENERATED", "QUEUED"}:
                    row["status"] = "RETRY_AVAILABLE"
                continue
            try:
                results.append(self.generate_selected(profile.value, preserve_edits=preserve_edits, progress=progress))
            except Exception:
                continue
        if results:
            self.variant_service.write_summary(results, self.output_root)
        if (self.state["variants"].get("STANDARD") or {}).get("status") == "READY":
            self.select_variant("STANDARD")
        self._write_human_review()
        self._save()
        return results

    def _set_stage(self, profile: str, stage: str, callback: Callable[[str, str], None]) -> None:
        self.state["variants"].setdefault(profile, {"profile": profile})["status"] = stage
        self._save()
        callback(profile, stage)

    def base_track_path(self, profile: str) -> Path:
        return self.output_root / profile.casefold() / "bilingual_track.json"

    def edited_track_path(self, profile: str) -> Path:
        return self.output_root / profile.casefold() / "bilingual_track.edited.json"

    def load_track(self, profile: str) -> BilingualSubtitleTrack:
        edited = self.edited_track_path(profile)
        return self.subtitle_service.load_track(edited if edited.is_file() else self.base_track_path(profile))

    def save_cues(self, profile: str, edits: Iterable[dict[str, str]]) -> list[str]:
        name = DurationProfile(profile).value
        row = self.state["variants"].get(name) or {}
        if row.get("status") != "READY":
            raise ValueError(f"Variant {name} is not ready")
        track = self.load_track(name)
        by_id = {cue.cue_id: cue for cue in track.cues}
        changed = 0
        for edit in edits:
            cue = by_id.get(str(edit.get("cue_id") or ""))
            if cue is None:
                raise ValueError(f"Unknown subtitle cue: {edit.get('cue_id')}")
            zh_text = str(edit.get("zh_text") or "").strip()
            en_text = str(edit.get("en_text") or "").strip()
            if not zh_text or not en_text:
                raise ValueError(f"Cue {cue.cue_id} requires both Chinese and English text")
            if (cue.zh_text, cue.en_text) != (zh_text, en_text):
                cue.zh_text, cue.en_text = zh_text, en_text
                cue.translation_status = "USER_EDITED"
                changed += 1
        warnings = self.subtitle_service.save_edited_track(
            track, self.edited_track_path(name), clip_duration_ms=int(row["duration_ms"]),
        )
        row.update({"dirty": True, "cue_edit_count": int(row.get("cue_edit_count", 0)) + changed,
                    "cue_edited_at": _now(), "cue_edited_by": "user", "validation_warnings": warnings})
        self._save()
        return warnings

    def _edit_map(self, profile: str) -> dict[tuple[str, ...], tuple[str, str]]:
        path = self.edited_track_path(profile)
        if not path.is_file():
            return {}
        return {tuple(cue.word_ids): (cue.zh_text, cue.en_text) for cue in self.subtitle_service.load_track(path).cues}

    @staticmethod
    def _apply_edit_map(track: BilingualSubtitleTrack, edits: dict[tuple[str, ...], tuple[str, str]]) -> None:
        for cue in track.cues:
            replacement = edits.get(tuple(cue.word_ids))
            if replacement:
                cue.zh_text, cue.en_text = replacement
                cue.translation_status = "USER_EDITED"

    def rerender(self, profile: str, *, start_ms: int | None = None,
                 end_ms: int | None = None) -> dict[str, Any]:
        name = DurationProfile(profile).value
        row = self.state["variants"].get(name) or {}
        if row.get("status") != "READY":
            raise ValueError(f"Variant {name} is not ready")
        old_path = Path(str(row.get("latest_output_path") or row.get("base_output_path") or ""))
        if not old_path.is_file():
            raise ValueError(f"Output file missing: {old_path}")
        start = int(row["start_ms"] if start_ms is None else start_ms)
        end = int(row["end_ms"] if end_ms is None else end_ms)
        if start < 0 or end <= start or end > self.plan.source_duration_ms:
            raise ValueError("Custom duration conflicts with event boundary")
        settings = self.settings()
        old_edits = self._edit_map(name)
        boundaries_changed = (start, end) != (int(row["start_ms"]), int(row["end_ms"]))
        if boundaries_changed or row.get("dirty"):
            track = self.variant_service.subtitle_service.build_track(
                clip_id=f"{self.plan.clip_id}:{name}", words=self.plan.words,
                clip_start_ms=start, clip_end_ms=end, source_language=self.plan.source_language,
                provider=self.provider, display_mode=BilingualDisplayMode(settings["display_mode"]),
                completeness=SubtitleCompleteness(settings["completeness"]),
                cache_path=self.output_root / "translation_cache.json", glossary=self.plan.glossary or {},
            )
            self._apply_edit_map(track, old_edits)
        else:
            track = self.load_track(name)
            track.display_mode = BilingualDisplayMode(settings["display_mode"])
        revision = int(row.get("revision", 0)) + 1
        target = self.output_root / name.casefold() / "revisions" / f"revision_{revision:03d}"
        result = self.variant_service.rerender_bilingual(
            self.plan, start_ms=start, end_ms=end, track=track, output_dir=target,
            position=SubtitlePosition(settings["position"]),
        )
        output = Path(str(result["output_path"]))
        media = self.media_validator(output)
        old_hash, new_hash = _sha256(old_path), _sha256(output)
        revision_manifest = {
            "schema_version": "1.0", "profile": name, "revision": revision,
            "start_ms": start, "end_ms": end, "previous_output": str(old_path),
            "output_path": str(output), "old_hash": old_hash, "new_hash": new_hash,
            "changed_cues": int(row.get("cue_edit_count", 0)),
            "style": settings, "boundary_changed": boundaries_changed,
            "rendered_at": _now(), "media_validation": media,
        }
        (target / "revision_manifest.json").write_text(
            json.dumps(revision_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        row.update({"revision": revision, "latest_output_path": str(output), "start_ms": start,
                    "end_ms": end, "duration_ms": end - start, "dirty": False,
                    "last_render": revision_manifest})
        self._save()
        return revision_manifest

    def record_decision(self, decision: str, *, reason: str = "") -> dict[str, Any]:
        normalized = FeedbackDecision(decision)
        selected = self.state["variants"].get(self.selected_profile) or {}
        if selected.get("status") == "READY":
            row = self.select_variant(self.selected_profile)
        elif normalized is FeedbackDecision.REJECTED:
            # Rejecting an unsuitable proposal must not require spending time
            # rendering it first. FeedbackService is the canonical persistence
            # owner and already accepts a proposed Clip.
            row = selected
        else:
            raise ValueError(f"Variant {self.selected_profile} is not ready")
        payload = {
            "decision": normalized.value, "reason": reason.strip(), "profile": self.selected_profile,
            "output_path": row.get("latest_output_path"), "start_ms": row.get("start_ms"),
            "end_ms": row.get("end_ms"), "display_mode": self.state["settings"]["display_mode"],
            "cue_edit_count": row.get("cue_edit_count", 0), "render_revision": row.get("revision", 0),
            "decided_at": _now(),
        }
        self.state["decision"] = payload
        if self.repository is not None and self.repository.get_clip(self.plan.clip_id) is not None:
            FeedbackService(self.repository).decide(self.plan.clip_id, normalized, reason=reason)
        self._save()
        self._write_human_review()
        return payload

    def selected_output(self) -> Path:
        row = self.state["variants"].get(self.selected_profile) or {}
        path = Path(str(row.get("latest_output_path") or row.get("base_output_path") or ""))
        if not path.is_file():
            raise ValueError(f"Output file missing: {path}")
        return path

    def similarity_warning(self) -> str:
        ready = [row for row in self.variant_rows() if row.get("status") == "READY"]
        for index, left in enumerate(ready):
            for right in ready[index + 1:]:
                if abs(int(left.get("duration_ms", 0)) - int(right.get("duration_ms", 0))) < 5_000:
                    return "These variants are nearly identical for this event."
        return ""

    def _write_human_review(self) -> None:
        lines = [
            "# Final GUI Human Review", "", f"Recording: {self.plan.recording_id}",
            f"Event: {self.plan.event_id}", f"Selected Variant: {self.selected_profile}", "",
            "- [ ] Short preview plays", "- [ ] Standard preview plays", "- [ ] Long preview plays",
            "- [ ] Full Event preview plays", "", "- [ ] Chinese subtitle natural",
            "- [ ] English subtitle accurate", "- [ ] Timeline synchronized",
            "- [ ] Cue splitting natural", "- [ ] Subtitle size readable",
            "- [ ] Subtitle does not block content", "", "Best Variant:", "- [ ] Short",
            "- [ ] Standard", "- [ ] Long", "- [ ] Full Event", "", "Final decision:",
            "- [ ] Accept", "- [ ] Minor Edit", "- [ ] Major Edit", "- [ ] Reject", "", "Notes:", "",
        ]
        (self.output_root / "final-gui-human-review.md").write_text("\n".join(lines), encoding="utf-8")


__all__ = ["GuiVariantWorkflowService", "PROFILES", "DISPLAY_PROFILES"]
