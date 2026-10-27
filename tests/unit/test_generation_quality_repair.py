from __future__ import annotations

from acfv.clips import (
    BilingualDisplayMode, BilingualSubtitleService, BilingualSubtitleTrack,
    EventDuplicateCandidate, IssueScope, SubtitleCue, SubtitleWord,
    cluster_cross_event_duplicates,
    content_specific_watchability, deduplicate_event_profile_issues,
    event_issue_identity,
)


def test_event_shared_profile_risk_is_counted_once() -> None:
    issue = {"issue_id": "low-word", "type": "IDENTITY", "root_cause_key": "word:42",
             "semantic_consequence": "IDENTITY", "start_ms": 100, "end_ms": 200,
             "severity": "WARNING", "issue_scope": IssueScope.EVENT_SHARED.value}
    rows = [event_issue_identity(issue, event_id="event", profile=profile)
            for profile in ("SHORT", "STANDARD", "LONG")]
    assert len(deduplicate_event_profile_issues(rows)) == 1


def test_profile_specific_risk_remains_per_profile() -> None:
    issue = {"issue_id": "cut", "type": "BOUNDARY", "root_cause_key": "boundary:start",
             "semantic_consequence": "BOUNDARY", "start_ms": 100, "end_ms": 100,
             "severity": "HIGH", "issue_scope": IssueScope.PROFILE_SPECIFIC.value}
    rows = [event_issue_identity(issue, event_id="event", profile=profile)
            for profile in ("SHORT", "STANDARD")]
    assert len(deduplicate_event_profile_issues(rows)) == 2


def test_independent_negation_and_number_blockers_do_not_deduplicate() -> None:
    rows = []
    for consequence in ("NEGATION_MISMATCH", "NUMBER_MISMATCH"):
        rows.append(event_issue_identity({
            "issue_id": consequence, "type": consequence, "root_cause_key": "cue:1",
            "semantic_consequence": consequence, "start_ms": 100, "end_ms": 200,
            "severity": "CRITICAL", "hard_blocker": True,
        }, event_id="event", profile="STANDARD"))
    assert len(deduplicate_event_profile_issues(rows)) == 2


def test_near_identical_cross_event_region_is_clustered_and_weaker_event_suppressed() -> None:
    rows = [
        EventDuplicateCandidate("a", "r", 1000, 11000, "same complete story", .9, .9, .1, .8, .9),
        EventDuplicateCandidate("b", "r", 1005, 11005, "same complete story", .7, .8, .5, .7, .7),
    ]
    clusters = cluster_cross_event_duplicates(rows)
    assert len(clusters) == 1
    assert clusters[0].winner_event_id == "a"
    assert clusters[0].suppressed_event_ids == ("b",)


def test_same_event_variants_are_never_cross_event_deduplicated() -> None:
    rows = [
        EventDuplicateCandidate("same", "r", 1000, 11000, "same"),
        EventDuplicateCandidate("same", "r", 1000, 11000, "same"),
    ]
    assert cluster_cross_event_duplicates(rows) == []


def test_chatting_score_uses_topic_argument_conclusion_not_reaction_volume() -> None:
    calm = content_specific_watchability("chatting", {
        "topic": 1, "argument": 1, "conclusion": 1, "evidence_coverage": 1,
        "self_contained": 1, "boundary_quality": 1, "language_quality": 1,
        "reaction": 0, "volume": 0, "scene_change": 0,
    })
    noisy = content_specific_watchability("chatting", {
        "topic": 0, "argument": 0, "conclusion": 0, "reaction": 1,
        "volume": 1, "scene_change": 1,
    })
    assert calm["total"] > noisy["total"]
    assert "PUBLISHABLE" in calm["human_only"]


def test_short_semantic_compatible_cue_is_merged_without_changing_words() -> None:
    service = BilingualSubtitleService()
    words = [
        SubtitleWord("1", "Well,", 0, 300, .9, "en"),
        SubtitleWord("2", "this", 350, 800, .9, "en"),
        SubtitleWord("3", "works.", 810, 1_300, .9, "en"),
    ]
    groups = service._segment(words)
    assert len(groups) == 1
    assert [word.word_id for word in groups[0][0]] == ["1", "2", "3"]


def test_extreme_cps_is_explicit_readability_warning_not_silent_pass() -> None:
    cue = SubtitleCue(
        "1", 0, 200, "word", "这是非常长的中文字幕", "A very long English caption",
        "en", ["1"], "short_reaction_or_pause", .9, "TRANSLATION_READY",
    )
    track = BilingualSubtitleTrack(
        "clip", "en", BilingualDisplayMode.ZH_EN, [cue], "test", "word-timestamps",
    )
    report = BilingualSubtitleService().quality_report(track, 200)
    assert report["timeline_validity"] is True
    assert report["readability_suspects"][0]["action"] == "READABILITY_WARNING"
    assert report["readability_suspects"][0]["effective_display_duration"] == .2
