from __future__ import annotations

import pytest

from acfv.clips import (
    ASRQualityFlag,
    BrokenSentenceClass,
    FinalTranscriptRequest,
    SourceCorrection,
    SourceCorrectionState,
    SourceTranscriptRefiner,
    SubtitleWord,
    classify_broken_sentence,
    cluster_language_issues,
    language_release_state,
    language_risk_issue,
    translation_semantic_guard,
)
from acfv.clips.refinement import _build_quality_report


class _Client:
    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, **_kwargs):
        return self.payload


def _correction(text, changes):
    return _Client({
        "corrected_text": text, "confidence": 0.99, "reason": "calibration",
        "changes": changes,
    })


def test_two_independent_evidence_classes_allow_correction() -> None:
    result = SourceTranscriptRefiner(_correction("pick Mercy", [
        {"before": "Murphy", "after": "Mercy", "evidence_type": "repeated_high_confidence"},
        {"before": "Murphy", "after": "Mercy", "evidence_type": "glossary"},
    ])).refine("pick Murphy", glossary={"Mercy": "Mercy"},
               repeated_high_confidence_terms=("Mercy",))
    assert result.state == SourceCorrectionState.AUTO_CORRECTED.value
    assert result.evidence and result.evidence.independent_evidence_count == 2


def test_acoustic_plus_exact_glossary_allows_correction() -> None:
    changes = [
        {"before": "Murphy", "after": "Mercy", "evidence_type": "acoustic_redecode"},
        {"before": "Murphy", "after": "Mercy", "evidence_type": "glossary"},
    ]
    result = SourceTranscriptRefiner(_correction("pick Mercy", changes)).refine(
        "pick Murphy", glossary={"Mercy": "Mercy"},
        acoustic_alternatives=({"status": "READY", "text": "pick Mercy"},),
    )
    assert result.state == SourceCorrectionState.AUTO_CORRECTED.value


def test_qwen_context_only_guess_is_kept_raw() -> None:
    result = SourceTranscriptRefiner(_correction("pick Mercy", [
        {"before": "Murphy", "after": "Mercy", "evidence_type": "qwen_context"},
    ])).refine("pick Murphy")
    assert result.state == SourceCorrectionState.UNCHANGED_UNCERTAIN.value
    assert result.corrected_text == "pick Murphy"


@pytest.mark.parametrize("raw,corrected,reason", [
    ("I didn't scream", "I screamed", "NEGATION_REMOVED"),
    ("Use 25 percent", "Use 20 percent", "NUMBER_CHANGED"),
])
def test_critical_semantic_correction_is_blocked(raw, corrected, reason) -> None:
    result = SourceTranscriptRefiner(_correction(corrected, [])).refine(raw)
    assert result.state == SourceCorrectionState.NEEDS_REVIEW.value
    assert reason in result.needs_review_reasons


def test_exact_adjacent_duplicate_removal_is_safe() -> None:
    result = SourceTranscriptRefiner(_correction("go now", [
        {"type": "duplicate_removal", "before": "go go", "after": "go"},
    ])).refine("go go now")
    assert result.state == SourceCorrectionState.AUTO_CORRECTED.value


@pytest.mark.parametrize("text,expected", [
    ("because", BrokenSentenceClass.TRUE_BROKEN),
    ("I was going to—", BrokenSentenceClass.INTERRUPTED_SPEECH),
    ("No!", BrokenSentenceClass.REACTION),
    ("I know you", BrokenSentenceClass.VALID_FRAGMENT),
    ("go now go now", BrokenSentenceClass.ASR_ERROR),
])
def test_broken_sentence_classes(text, expected) -> None:
    assert classify_broken_sentence(text) is expected


def test_low_importance_filler_is_warning_not_blocker() -> None:
    request = FinalTranscriptRequest("r", "e", "source", 10_000, 0, 10_000, "en")
    quality = _build_quality_report([
        SubtitleWord("1", "um", 500, 700, .40, "en", quality_flags=(
            ASRQualityFlag.LOW_WORD_CONFIDENCE.value,
        )),
    ], correction=SourceCorrection("um", "um"), request=request, local_redecode_count=1)
    assert quality.final_quality_state == "READY_WITH_WARNINGS"


def test_payoff_negation_and_number_are_hard_blockers() -> None:
    request = FinalTranscriptRequest("r", "e", "source", 10_000, 0, 10_000, "en", payoff_anchor_ms=5_000)
    for token in ("didn't", "50"):
        quality = _build_quality_report([
            SubtitleWord("1", token, 4_900, 5_100, .30, "en", quality_flags=(
                ASRQualityFlag.LOW_WORD_CONFIDENCE.value,
            )),
        ], correction=SourceCorrection(token, token), request=request, local_redecode_count=1)
        assert quality.final_quality_state == "NEEDS_REVIEW"


def test_release_states_cover_ready_warning_and_review() -> None:
    assert language_release_state([])[0] == "READY"
    warning = language_risk_issue(issue_id="w", issue_type="STYLE", severity="WARNING")
    assert language_release_state([warning])[0] == "READY_WITH_WARNINGS"
    critical = language_risk_issue(
        issue_id="c", issue_type="POLARITY", severity="CRITICAL",
        semantic_importance="CRITICAL", semantic_position="PAYOFF", hard_blocker=True,
    )
    assert language_release_state([critical])[0] == "NEEDS_REVIEW"
    assert language_release_state([], timeline_valid=False)[0] == "NEEDS_REVIEW"


def _cluster_issue(name: str, *, root: str, consequence: str = "STYLE",
                   start: int = 100, end: int = 200, risk: float = 1.0,
                   severity: str = "WARNING", source: str = "guard-a",
                   hard: bool = False) -> dict:
    issue = language_risk_issue(
        issue_id=name, issue_type=consequence, start_ms=start, end_ms=end,
        root_cause_key=root, semantic_consequence=consequence,
        severity=severity, evidence_source=source, hard_blocker=hard,
    )
    issue["risk_contribution"] = risk
    return issue


def test_cluster_mutation_same_root_duplicates_are_one_risk_unit() -> None:
    rows = [_cluster_issue("a", root="word:1"), _cluster_issue("b", root="word:1")]
    clusters = cluster_language_issues(rows, clip_id="generic")
    assert len(clusters) == 1
    assert clusters[0].cluster_risk == 1.0


def test_cluster_mutation_independent_roots_remain_independent() -> None:
    rows = [_cluster_issue("a", root="word:1"), _cluster_issue("b", root="word:2")]
    assert len(cluster_language_issues(rows)) == 2


def test_cluster_mutation_same_timestamp_unrelated_consequences_stay_separate() -> None:
    rows = [_cluster_issue("a", root="cue:1", consequence="NEGATION_MISMATCH"),
            _cluster_issue("b", root="cue:1", consequence="NUMBER_MISMATCH")]
    assert len(cluster_language_issues(rows)) == 2


def test_cluster_mutation_nonoverlapping_recurrence_stays_separate() -> None:
    rows = [_cluster_issue("a", root="token:thanks", start=0, end=100),
            _cluster_issue("b", root="token:thanks", start=200, end=300)]
    assert len(cluster_language_issues(rows)) == 2


def test_cluster_mutation_overlapping_spans_are_connected_transitively() -> None:
    rows = [_cluster_issue("a", root="cue:1", start=0, end=100),
            _cluster_issue("b", root="cue:1", start=50, end=150),
            _cluster_issue("c", root="cue:1", start=140, end=200)]
    assert len(cluster_language_issues(rows)) == 1


def test_cluster_mutation_mixed_severity_uses_maximum() -> None:
    rows = [_cluster_issue("a", root="cue:1", severity="WARNING"),
            _cluster_issue("b", root="cue:1", severity="HIGH")]
    assert cluster_language_issues(rows)[0].max_severity == "HIGH"


def test_cluster_mutation_independent_evidence_gets_limited_bonus() -> None:
    rows = [_cluster_issue("a", root="cue:1", source="asr"),
            _cluster_issue("b", root="cue:1", source="translation")]
    assert cluster_language_issues(rows)[0].cluster_risk == 1.1


def test_cluster_mutation_same_family_gets_no_bonus() -> None:
    rows = [_cluster_issue("a", root="cue:1", source="style-rule"),
            _cluster_issue("b", root="cue:1", source="style-rule")]
    assert cluster_language_issues(rows)[0].cluster_risk == 1.0


def test_cluster_mutation_hard_blocker_survives_deduplication() -> None:
    rows = [_cluster_issue("a", root="cue:1"),
            _cluster_issue("b", root="cue:1", consequence="STYLE", hard=True)]
    assert cluster_language_issues(rows)[0].hard_blocker
    assert language_release_state(rows)[0] == "NEEDS_REVIEW"


def test_cluster_mutation_legacy_findings_are_not_guessed_together() -> None:
    rows = [{"issue_id": "legacy-a", "type": "STYLE", "risk_contribution": 1.0},
            {"issue_id": "legacy-b", "type": "STYLE", "risk_contribution": 1.0}]
    assert len(cluster_language_issues(rows)) == 2


CRITICAL_MUTATIONS = [
    ("I didn't scream.", "我尖叫了。", {}),
    ("I never won.", "我赢了。", {}),
    ("No one left.", "所有人都离开了。", {}),
    ("I can't move.", "我能动。", {}),
    ("Use 25%.", "使用20%。", {}),
    ("Three players.", "有2个玩家。", {}),
    ("Wait 10 seconds.", "等5秒。", {}),
    ("Saruei arrived.", "安妮来了。", {"known_creator_entities": ["Saruei"]}),
    ("Choose Mercy.", "选择安娜。", {"game_terms": ["Mercy"]}),
    ("This is the payoff.", "", {}),
]

WARNING_MUTATIONS = [
    ("Are you ready?", "准备好了。", {}),
    ("This is fucking hard.", "这很难。", {}),
    ("Damn, okay.", "好吧。", {}),
    ("This is fine.", "笑死，这很好。", {}),
    ("Hello Bob.", "你好。", {}),
    ("Meet Alice.", "见面吧。", {}),
    ("Use Widget.", "使用组件。", {}),
    ("Okay Charlie.", "好的。", {}),
    ("Is Delta here?", "德尔塔在这里。", {}),
    ("Try Foobar.", "试试。", {}),
]

HARMLESS_MUTATIONS = [
    ("Guys, let's go.", "各位，我们走。", {}),
    ("Guys, let's go.", "兄弟们，我们走。", {}),
    ("Damn.", "靠。", {}),
    ("No!", "不！", {}),
    ("I didn't scream.", "我没有尖叫。", {}),
    ("Use 25%.", "使用25%。", {}),
    ("CS2", "CS2", {}),
    ("FMS", "FMS", {}),
    ("Twitch", "Twitch", {}),
    ("Saruei", "Saruei", {}),
]


@pytest.mark.parametrize("source,target,kwargs", CRITICAL_MUTATIONS)
def test_critical_mutation_recall_is_complete(source, target, kwargs) -> None:
    findings = translation_semantic_guard(source, target, semantic_position="PAYOFF", **kwargs)
    assert any(item["critical"] or item["hard_blocker"] for item in findings)


@pytest.mark.parametrize("source,target,kwargs", WARNING_MUTATIONS)
def test_warning_mutations_do_not_become_critical(source, target, kwargs) -> None:
    findings = translation_semantic_guard(source, target, **kwargs)
    assert findings
    assert not any(item["critical"] for item in findings)


@pytest.mark.parametrize("source,target,kwargs", HARMLESS_MUTATIONS)
def test_harmless_mutations_have_zero_false_critical(source, target, kwargs) -> None:
    findings = translation_semantic_guard(source, target, **kwargs)
    assert not any(item["critical"] for item in findings)


def test_entity_sources_are_typed_and_capitalization_alone_is_low_risk() -> None:
    cases = [
        ({"known_creator_entities": ["Saruei"]}, "KNOWN_CREATOR_ENTITY", True),
        ({"game_terms": ["Mercy"]}, "GAME_TERM", True),
        ({"ocr_entities": ["Widget"]}, "OCR_CONFIRMED_ENTITY", True),
        ({"glossary": {"Potion": "药水"}}, "GLOSSARY_ENTITY", True),
        ({"repeated_high_confidence_entities": ["Foobar"]}, "REPEATED_HIGH_CONFIDENCE_ENTITY", True),
        ({}, "UNKNOWN_CAPITALIZED_TOKEN", False),
    ]
    for kwargs, expected_type, critical in cases:
        token = next(iter(kwargs.get("known_creator_entities") or kwargs.get("game_terms")
                          or kwargs.get("ocr_entities") or kwargs.get("glossary", {})
                          or kwargs.get("repeated_high_confidence_entities") or ["Alice"]))
        findings = translation_semantic_guard(f"Meet {token}.", "见面吧。", **kwargs)
        entity = next(item for item in findings if item["code"] == "ENTITY_MISMATCH")
        assert entity["evidence"]["entity_type"] == expected_type
        assert entity["critical"] is critical


def test_sentence_initial_normal_word_is_not_an_entity() -> None:
    assert not any(
        item["code"] == "ENTITY_MISMATCH"
        for item in translation_semantic_guard("Something happened.", "发生了一些事。")
    )


def test_semantically_equivalent_chinese_number_passes_and_no_one_is_not_numeric() -> None:
    assert not any(
        item["code"] == "NUMBER_MISMATCH"
        for item in translation_semantic_guard("Three players.", "三名玩家。")
    )
    findings = translation_semantic_guard("No one left.", "所有人都离开了。")
    assert not any(item["code"] == "NUMBER_MISMATCH" for item in findings)
    assert any(item["code"] == "NEGATION_MISMATCH" for item in findings)
