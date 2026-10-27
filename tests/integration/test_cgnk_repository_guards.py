from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _yaml(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_cgnk_manifest_paths_exist() -> None:
    manifest = _yaml(".cgnk/project.yaml")
    assert manifest["schema_version"] == "1.0"
    paths = [
        *manifest["truth"].values(),
        manifest["specs"]["root"],
        manifest["specs"]["contracts"],
        manifest["knowledge"]["root"],
        manifest["skills"]["root"],
        manifest["evidence"]["root"],
        *manifest["runtime"]["roots"],
        *manifest["source"]["roots"],
        manifest["tests"]["root"],
        *manifest["verification"].values(),
        manifest["capabilities"]["registry"],
    ]
    assert all((ROOT / path).exists() for path in paths)


def test_capability_registry_has_unique_complete_owners() -> None:
    registry = _yaml("specs/capabilities/index.yaml")
    capabilities = registry["capabilities"]
    expected = {
        "live_processing", "twitch_capture", "vod_download", "video_processing", "creator_library", "moment_lifecycle",
        "retrieval", "grounded_conversation", "clip_rendering", "clip_candidate_selection", "clip_review", "feedback",
        "bilingual_subtitle", "clip_duration_profile", "final_clip_transcript_refinement",
            "human_review",
            "creator_identity", "voice_profile", "trusted_speech_memory", "creator_lexicon",
            "creator_adaptive_asr", "avatar_identity_provider", "creator_visual_identity",
    }
    ids = [item["id"] for item in capabilities]
    assert set(ids) == expected
    assert len(ids) == len(set(ids))
    for item in capabilities:
        assert item["interface"] and item["owner_layer"]
        assert (ROOT / item["spec"]).is_file()
        assert all((ROOT / path).exists() for path in item["implementation"])
        assert all((ROOT / path).is_file() for path in item["tests"])
        text = (ROOT / item["spec"]).read_text(encoding="utf-8")
        for heading in ("Purpose", "Canonical Interface", "Implementation", "Inputs", "Outputs", "Effects", "Errors", "Dependencies", "Acceptance"):
            assert heading in text


def test_agent_navigation_tasks_resolve_without_repo_scan() -> None:
    registered = {item["id"] for item in _yaml("specs/capabilities/index.yaml")["capabilities"]}
    tasks = _yaml("specs/capabilities/navigation_tests.yaml")["tasks"]
    assert len(tasks) == 5
    for task in tasks:
        assert task["capability"] in registered
        for key in ("spec", "skill", "source"):
            assert (ROOT / task[key]).is_file()
        assert all((ROOT / path).is_file() for path in task["tests"])


def test_developer_skills_have_workflow_metadata() -> None:
    expected = {
        "repository-audit", "pipeline-change", "product-layer-change",
        "capability-validation", "release-verification",
    }
    root = ROOT / ".agents" / "skills"
    assert {path.name for path in root.iterdir() if path.is_dir()} == expected
    for skill_dir in root.iterdir():
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        for field in ("id:", "version:", "scope:", "depends_on:", "risk:"):
            assert field in text
        for section in ("Purpose:", "Inputs:", "Outputs:", "Dependencies:", "Workflow:", "Verification:"):
            assert section in text


def test_source_and_project_truth_are_not_gitignored() -> None:
    candidates = [
        "src/acfv/_cgnk_guard.py", "tests/_cgnk_guard.py", "specs/_cgnk_guard.md",
        "knowledge/_cgnk_guard.md", ".agents/skills/_cgnk_guard/SKILL.md",
        ".cgnk/project.yaml", "evidence/_cgnk_guard.md",
    ]
    ignored = []
    for candidate in candidates:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", candidate],
            cwd=ROOT,
            check=False,
        )
        if result.returncode == 0:
            ignored.append(candidate)
    assert not ignored, f"project source/truth unexpectedly ignored: {ignored}"


def test_architecture_dependency_boundaries() -> None:
    rules = {
        "src/acfv/ui": ("sqlalchemy", "sqlmodel", "acfv.library.repository"),
        "src/acfv/conversation": ("subprocess", "acfv.processing", "acfv.steps.render_clips"),
        "src/acfv/retrieval": ("acfv.clips", "acfv.processing", "acfv.steps.render_clips"),
        "src/acfv/feedback": ("acfv.ui", "acfv.gui", "acfv.main_window"),
        "src/acfv/library": ("acfv.ui", "acfv.gui", "acfv.main_window"),
    }
    violations = []
    for directory, forbidden in rules.items():
        for path in (ROOT / directory).rglob("*.py"):
            for imported in _imports(path):
                if any(imported == item or imported.startswith(item + ".") for item in forbidden):
                    violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert not violations, "forbidden dependency direction:\n" + "\n".join(violations)


def test_tracked_files_contain_no_secret_values() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout.decode("utf-8").split("\0")
    patterns = {
        "OpenAI": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        "HuggingFace": re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
        "OAuth": re.compile(r"\boauth:[A-Za-z0-9]{20,}\b", re.IGNORECASE),
        "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    }
    findings = []
    for relative in filter(None, tracked):
        path = ROOT / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in patterns.items():
            if pattern.search(text):
                findings.append(f"{relative}: {name}")
    assert not findings, "tracked secret-like values found: " + ", ".join(findings)


def test_change_manifest_and_test_receipt_schemas_are_stable() -> None:
    for relative, required in (
        ("specs/contracts/change_manifest.schema.json", {"change_id", "capabilities", "files_changed", "behavior_change"}),
        ("specs/contracts/test_receipt.schema.json", {"change_id", "commit", "commands", "results", "passed", "environment"}),
    ):
        schema = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        assert schema["type"] == "object"
        assert required <= set(schema["required"])
        assert set(schema["required"]) <= set(schema["properties"])

    manifest = json.loads((ROOT / "evidence/validation/cgnk-refactor-change-manifest.json").read_text(encoding="utf-8"))
    receipt = json.loads((ROOT / "evidence/validation/cgnk-refactor-test-receipt.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "1" and manifest["behavior_change"] is False
    assert re.fullmatch(r"[0-9a-f]{40}", receipt["commit"])
    assert receipt["passed"] is True and receipt["commands"] and receipt["results"]
    assert {"os", "python"} <= set(receipt["environment"])
