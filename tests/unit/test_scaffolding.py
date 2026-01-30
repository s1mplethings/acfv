from pathlib import Path
import yaml


def test_docs_and_specs_exist():
    required = [
        "docs/00_overview.md",
        "docs/01_architecture.md",
        "docs/02_workflow.md",
        "docs/03_quality_gates.md",
        "specs/index.md",
        "specs/modules/transcribe_audio/spec.md",
    ]
    for item in required:
        assert Path(item).exists(), f"missing required doc/spec: {item}"


def test_keywords_yaml_has_core_keys():
    data = yaml.safe_load(Path("ai_context/keywords.yaml").read_text(encoding="utf-8"))
    for key in ["entrypoints", "invariants", "error_signatures", "hotspots", "tags"]:
        assert key in data, f"keywords.yaml missing {key}"
    assert "verify" in data["entrypoints"], "verify entrypoint must be defined"
