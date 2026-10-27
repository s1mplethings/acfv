from acfv.conversation import ConversationRuntimeMode, GroundedConversationService, NO_EVIDENCE_ANSWER
from acfv.retrieval import SearchResult


def _result(text: str, moment_id: str = "moment-1", reranker_score: float | None = None) -> SearchResult:
    return SearchResult(
        moment_id=moment_id,
        creator_id="creator",
        recording_id="recording",
        start_ms=1000,
        end_ms=5000,
        score=1.0,
        summary=text,
        transcript_excerpt=text,
        recording_title="Stream",
        recorded_at=None,
        moment_status="FINAL",
        evidence=[{"type": "transcript", "text": text}],
        debug={"reranker_score": reranker_score} if reranker_score is not None else {},
    )


class FakeRetrieval:
    def __init__(self, results):
        self.results = results
        self.last_kwargs = {}

    def search(self, *args, **kwargs):
        self.last_kwargs = kwargs
        return self.results


class FakeLLM:
    available = True

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete_json(self, **kwargs):
        self.calls += 1
        return self.payload


def test_positive_query_returns_grounded_answer_and_reference() -> None:
    evidence = _result("她被吓到以后否认自己害怕")
    llm = FakeLLM({"answer": "她被吓到后确实否认了。[E1]", "citations": ["E1"]})
    service = GroundedConversationService(FakeRetrieval([evidence]), llm_client=llm)

    answer = service.ask("找到她被吓到以后又否认自己害怕的地方")

    assert answer.grounded is True
    assert answer.citations == ["E1"]
    assert answer.citation_details[0]["moment_id"] == "moment-1"
    assert answer.evidence_cards == [evidence]


def test_no_evidence_never_calls_llm_or_makes_claim() -> None:
    llm = FakeLLM({"answer": "invented", "citations": ["moment-1"]})
    service = GroundedConversationService(FakeRetrieval([_result("今天在画蓝色的龙")]), llm_client=llm)

    unsupported = [
        "她是不是说过永远不会再玩这个游戏？",
        "Did she announce a trip to Mars?",
        "Was a chocolate cake baked?",
        "Did a dog win the tournament?",
        "Was there a database outage?",
        "Did the stream show a wedding?",
        "Was a new car purchased?",
        "Did anyone play the violin?",
        "Was a medical diagnosis discussed?",
        "Did the creator publish a phone number?",
        "Was a purple submarine launched?",
        "Did the host announce a lottery winner?",
        "Was a contract signed on camera?",
        "Did someone repair a motorcycle?",
        "Was a secret password revealed?",
        "Did the stream confirm tomorrow's weather?",
        "Was a piano delivered to the studio?",
        "Did anyone adopt three cats?",
        "Was an election result announced?",
        "Did the creator promise a new album?",
    ]
    for query in unsupported:
        answer = service.ask(query)
        assert answer.answer == NO_EVIDENCE_ANSWER
        assert answer.grounded is False
        assert answer.evidence_cards == []
    assert llm.calls == 0


def test_invalid_llm_citations_are_rejected() -> None:
    llm = FakeLLM({"answer": "A claim", "citations": ["not-retrieved"]})
    service = GroundedConversationService(FakeRetrieval([_result("Overwatch match")]), llm_client=llm)

    answer = service.ask("Overwatch")

    assert answer.answer == NO_EVIDENCE_ANSWER
    assert answer.grounded is False


def test_llm_unavailable_is_truthful_evidence_only_mode() -> None:
    service = GroundedConversationService(FakeRetrieval([_result("Overwatch match tonight")]))
    answer = service.ask("Find the Overwatch match tonight")
    assert answer.runtime_mode == ConversationRuntimeMode.EVIDENCE_ONLY
    assert answer.grounded is False
    assert answer.confidence == "evidence_only"
    assert answer.citations == []
    assert answer.evidence_cards


def test_citation_presence_does_not_make_irrelevant_evidence_grounded() -> None:
    llm = FakeLLM({"answer": "A claim", "citations": ["E1"]})
    service = GroundedConversationService(FakeRetrieval([_result("drawing a blue dragon")]), llm_client=llm)
    answer = service.ask("Did they sign a Logitech sponsorship agreement?")
    assert answer.answer == NO_EVIDENCE_ANSWER
    assert answer.grounded is False
    assert llm.calls == 0


class FailingLLM:
    available = True

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = 0

    def complete_json(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload


def test_malformed_llm_output_gets_one_bounded_repair_then_evidence_only() -> None:
    llm = FailingLLM(payload={"answer": "claim without citations field"})
    answer = GroundedConversationService(FakeRetrieval([_result("Overwatch match tonight")]), llm_client=llm).ask("Find the Overwatch match tonight")
    assert llm.calls == 2
    assert answer.runtime_mode == ConversationRuntimeMode.EVIDENCE_ONLY
    assert answer.grounded is False


def test_llm_timeout_gets_one_bounded_retry_then_evidence_only() -> None:
    llm = FailingLLM(error=TimeoutError("provider timed out"))
    answer = GroundedConversationService(FakeRetrieval([_result("Overwatch match tonight")]), llm_client=llm).ask("Find the Overwatch match tonight")
    assert llm.calls == 2
    assert answer.runtime_mode == ConversationRuntimeMode.EVIDENCE_ONLY


def test_only_valid_stable_evidence_ids_are_exposed() -> None:
    second = _result("Overwatch match after dinner", moment_id="moment-2")
    llm = FakeLLM({"answer": "Two excerpts support this.", "citations": ["E2", "invented", "E2"]})
    answer = GroundedConversationService(FakeRetrieval([_result("Overwatch match tonight"), second]), llm_client=llm).ask("Find the Overwatch match")
    assert answer.citations == ["E2"]
    assert answer.evidence_cards == [second]
    assert answer.citation_details == [{"evidence_id": "E2", "moment_id": "moment-2", "recording_id": "recording", "start_ms": 1000, "end_ms": 5000}]


def test_calibrated_negative_reranker_score_can_still_support_specific_terms() -> None:
    service = GroundedConversationService(FakeRetrieval([_result("Repeat the words often to memorize them.", reranker_score=-2.9)]))
    answer = service.ask("What helps memorize words?")
    assert answer.runtime_mode == ConversationRuntimeMode.EVIDENCE_ONLY
    assert answer.evidence_cards


def test_cross_language_semantic_evidence_can_pass_without_lexical_overlap() -> None:
    evidence = _result(
        "The realistic horror game uses your mind to communicate with entities.",
        reranker_score=-2.2,
    )
    evidence.debug.update({"dense_score": 0.83, "final_rank": 3})
    answer = GroundedConversationService(FakeRetrieval([evidence])).ask(
        "哪个恐怖游戏会用人的思想和实体沟通？"
    )
    assert answer.runtime_mode == ConversationRuntimeMode.EVIDENCE_ONLY
    assert answer.evidence_cards == [evidence]


def test_cross_language_weak_semantic_evidence_is_rejected() -> None:
    evidence = _result("A routine cooking stream.", reranker_score=-8.0)
    evidence.debug.update({"dense_score": 0.74, "final_rank": 1})
    answer = GroundedConversationService(FakeRetrieval([evidence])).ask(
        "哪个恐怖游戏会用人的思想和实体沟通？"
    )
    assert answer.runtime_mode == ConversationRuntimeMode.DEGRADED
    assert answer.evidence_cards == []


def test_parent_child_semantic_support_recovers_specific_single_term_question() -> None:
    evidence = _result("Those paddles made her realize this was BDSM.", reranker_score=-7.2)
    evidence.debug.update({"dense_score": 0.82, "final_rank": 3, "winning_representation_type": "FULL_TRANSCRIPT"})

    answer = GroundedConversationService(FakeRetrieval([evidence])).ask(
        "What items made her realize the list was about BDSM?"
    )

    assert answer.runtime_mode == ConversationRuntimeMode.EVIDENCE_ONLY
    assert answer.evidence_cards == [evidence]


def test_semantic_support_does_not_relax_low_score_or_yes_no_safety() -> None:
    weak = _result("Those paddles were on a list about BDSM.", reranker_score=-8.0)
    weak.debug.update({"dense_score": 0.83, "final_rank": 2})
    yes_no = _result("The convention is scheduled and her passport is valid.", reranker_score=-2.0)
    yes_no.debug.update({"dense_score": 0.9, "final_rank": 1})

    assert GroundedConversationService(FakeRetrieval([weak])).ask(
        "What items made her realize the list was about BDSM?"
    ).evidence_cards == []
    assert GroundedConversationService(FakeRetrieval([yes_no])).ask(
        "Did she cancel a convention because of a passport problem?"
    ).evidence_cards == []


def test_yes_no_claim_needs_more_than_one_partial_term() -> None:
    service = GroundedConversationService(FakeRetrieval([_result("She said not to cancel a subscription.", reranker_score=-2.0)]))
    answer = service.ask("Did she cancel a convention because of a passport problem?")
    assert answer.runtime_mode == ConversationRuntimeMode.DEGRADED
    assert answer.evidence_cards == []


def test_yes_no_claim_rejects_semantically_opposite_streaming_plan() -> None:
    evidence = _result(
        "I have not streamed in two months, but I am planning to come back fully on March 18th.",
        reranker_score=-3.5,
    )
    service = GroundedConversationService(FakeRetrieval([evidence]))

    answer = service.ask("Did she say she was planning to stop streaming next month?")

    assert answer.runtime_mode == ConversationRuntimeMode.DEGRADED
    assert answer.evidence_cards == []


def test_default_conversation_window_includes_late_top_eight_evidence() -> None:
    retrieval = FakeRetrieval([_result("right trigger control")])
    GroundedConversationService(retrieval).ask("Which control was the right trigger?")
    assert retrieval.last_kwargs["top_k"] == 8


def test_winning_retrieval_excerpt_is_used_for_support_and_prompt() -> None:
    evidence = _result("Crow Country gameplay", reranker_score=-4.4)
    evidence.debug["winning_representation_excerpt"] = "She confused RB and RT, then identified RT as the right trigger."
    llm = FakeLLM({"answer": "She identified RT as the right trigger.", "citations": ["E1"]})
    answer = GroundedConversationService(FakeRetrieval([evidence]), llm_client=llm).ask(
        "What control did she identify as the right trigger in Crow Country?"
    )
    assert answer.grounded is True
    assert "retrieval_excerpt" in GroundedConversationService._prompt("question", {"E1": evidence})
