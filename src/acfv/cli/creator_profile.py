from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from acfv.creator_adaptive.repository import CreatorAdaptiveRepository
from acfv.library.service import LibraryService
from acfv.providers.avatar_identity import ExistingAvatarModelAdapter
from acfv.providers.avatar_discovery import discover_avatar_models
from acfv.voice_profile import CreatorVoiceProfileService, VoiceProfileInsufficientData


creator_profile_app = typer.Typer(no_args_is_help=True)


def _visual_v3_available() -> bool:
    root = Path.cwd().resolve()
    config = root / "config/creator_visual_identity.json"
    if not config.is_file():
        return False
    payload = json.loads(config.read_text(encoding="utf-8"))
    artifact = Path(str(payload.get("classifier_path", "")))
    return (artifact if artifact.is_absolute() else root / artifact).is_file()


@creator_profile_app.command("discover-avatar")
def discover_avatar(
    output: Optional[Path] = typer.Option(None, "--output", help="Optional JSON report path"),
    mapping: Optional[Path] = typer.Option(None, "--mapping", help="Explicit external-label to Creator-ID JSON"),
) -> None:
    label_mapping: dict[str, str | None] | None = None
    if mapping:
        payload = json.loads(mapping.expanduser().read_text(encoding="utf-8"))
        label_mapping = dict(payload.get("labels", payload))
    project = Path.cwd().resolve()
    # User-authorized bounded root for this recovered model. Never expand this
    # command into a drive/home scan.
    roots = [Path("G:/Cliper")]
    report = discover_avatar_models(project, search_roots=roots, label_mapping=label_mapping)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        output = output.expanduser().resolve(); output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    typer.echo(encoded)


def _creator_id(value: str) -> str:
    service = LibraryService()
    direct = service.repository.get_creator(value)
    if direct:
        return direct.id
    for creator in service.list_creators():
        if creator.slug.casefold() == value.casefold() or creator.display_name.casefold() == value.casefold():
            return creator.id
    raise typer.BadParameter(f"Unknown Creator: {value}")


@creator_profile_app.command("status")
def status(creator: str = typer.Argument("", help="Creator ID, slug, or display name")) -> None:
    repository = CreatorAdaptiveRepository()
    avatar = ExistingAvatarModelAdapter()
    rows = [repository.profile_summary(_creator_id(creator))] if creator else [repository.profile_summary(item.id) for item in LibraryService().list_creators()]
    typer.echo(json.dumps({"avatar_provider": avatar.audit(), "creator_visual_identity_v1": {"available": _visual_v3_available(), "runtime_mode": "SHADOW_VISUAL_IDENTITY"}, "profiles": rows}, ensure_ascii=False, indent=2))


@creator_profile_app.command("build")
def build(creator: str) -> None:
    creator_id = _creator_id(creator)
    repository = CreatorAdaptiveRepository()
    current = repository.latest_profile(creator_id)
    version = str((current or {}).get("profile_version") or "creator_profile_v1")
    avatar = ExistingAvatarModelAdapter()
    if _visual_v3_available() and version != "creator_profile_v3":
        version = "creator_profile_v3"
    elif avatar.status == "READY" and version == "creator_profile_v1":
        version = "creator_profile_v2"
    repository.ensure_profile(
        creator_id, version,
        visual_status="READY" if _visual_v3_available() else ("CONFIGURED_NEEDS_BUILD" if avatar.status == "READY" else "REAL_MODEL_NOT_CONFIGURED"),
    )
    result: dict[str, object] = {"creator_id": creator_id, "profile_version": version, "mode": "incremental"}
    try:
        result["voice"] = CreatorVoiceProfileService(repository=repository).build(creator_id, profile_version=version)
    except VoiceProfileInsufficientData as exc:
        result["voice"] = str(exc)
    result["profile"] = repository.profile_summary(creator_id)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@creator_profile_app.command("rebuild")
def rebuild(creator: str) -> None:
    creator_id = _creator_id(creator)
    repository = CreatorAdaptiveRepository()
    existing = repository.rows("creator_identity_profiles", where="creator_id=?", params=(creator_id,))
    version = f"creator_profile_v{len(existing) + 1}"
    repository.ensure_profile(creator_id, version)
    typer.echo(json.dumps({"creator_id": creator_id, "profile_version": version, "old_profiles_preserved": True}, indent=2))


@creator_profile_app.command("inspect")
def inspect_profile(creator: str) -> None:
    creator_id = _creator_id(creator)
    typer.echo(json.dumps(CreatorAdaptiveRepository().profile_summary(creator_id), ensure_ascii=False, indent=2))


@creator_profile_app.command("shadow")
def shadow(recording_id: str = typer.Argument("", help="Optional recording filter")) -> None:
    repository = CreatorAdaptiveRepository()
    where, params = ("recording_id=?", (recording_id,)) if recording_id else ("", ())
    rows = repository.rows("adaptive_transcript_decisions", where=where, params=params)
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["action"])] = counts.get(str(row["action"]), 0) + 1
    typer.echo(json.dumps({"mode": "SHADOW_ONLY", "official_transcript_mutated": False, "spans": len(rows), "actions": counts}, indent=2))


@creator_profile_app.command("evaluate")
def evaluate() -> None:
    repository = CreatorAdaptiveRepository()
    rows = repository.rows("adaptive_transcript_decisions")
    typer.echo(json.dumps({
        "spans": len(rows), "human_ground_truth": "NOT_EVALUATED",
        "wer": "NOT_EVALUATED", "production_ready": False,
        "reason": "production gate requires independent human ground truth",
    }, indent=2))

