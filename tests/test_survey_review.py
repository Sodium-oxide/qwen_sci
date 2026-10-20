import copy
import json
from types import SimpleNamespace

import pytest
import requests
from tenacity import retry, stop_after_attempt

from test_survey_evidence_bounded_writing import _quality_draft, _quality_generator, _sentence_patch
from modules.survey_review import ReviewStopped, confirmed_packet_evidence, freeze_paper_evidence, review_runtime


def with_sources(responses, sources=None):
    generator = _quality_generator(responses)
    generator.config.ModuleInfo.SurveyGenerator.claim_support_audit_enabled = True
    generator.work_analyzer = SimpleNamespace(work_collector=SimpleNamespace(
        _survey_resume_abstracts={paper_id: ["Study", text] for paper_id, text in
                                 (sources or {"W1": "A cautious observation is reported."}).items()},
    ))
    return generator


def assessment(verdict="supported", claim_id=1, paper_id="W1", quote="A cautious observation is reported"):
    return {"claim_id": claim_id, "paper_id": paper_id, "verdict": verdict,
            "evidence_quote": quote, "reason": "Source comparison."}


def audit_response(*items):
    return json.dumps({"assessments": list(items)})


def repair(generator, original, target=None, validate=True, stage="section_revision"):
    return generator._revise_evidence_bounded_section_quality(
        section_text=original, section_outline={}, suggestions=["Clarify the observation."],
        section_word_cap=200, settings=generator._evidence_bounded_section_quality_settings(),
        target_excerpts=[target or original.split("\n\n")[1]], stage=stage, section_index=1,
        validate_candidate=(lambda candidate: generator._revision_claim_support_errors(
            candidate, section_index=1, stage=stage, original_section=original
        )) if validate else None,
    )


def test_changed_sentence_is_not_blocked_by_unchanged_uncertain_claim():
    first = "The exposition is vague <Paper ID: W1>."
    replacement = "A cautious observation is reported <Paper ID: W1>."
    unchanged = "An unresolved claim <Paper ID: W2>."
    original = "## Evidence\n\n" + first + "\n\n" + unchanged
    generator = with_sources([_sentence_patch(replacement), audit_response(assessment())])
    generator._record_integrity("issues", {"claim": unchanged, "resolution": "manual_review"})

    revised = repair(generator, original, first)

    assert revised == original.replace(first, replacement)
    assert unchanged not in generator.chat_agent.calls[1]["prompt"]
    assert generator.survey_integrity_artifact["issues"][0]["resolution"] == "manual_review"


def test_changed_unsupported_claim_is_rejected():
    original = "## Evidence\n\nAn observation <Paper ID: W1>."
    generator = with_sources([_sentence_patch("A major effect is proven <Paper ID: W1>."),
                              audit_response(assessment("unsupported", quote=""))])
    assert repair(generator, original) is None
    assert len(generator.chat_agent.calls) == 2


def test_final_repair_is_not_blocked_by_an_unrelated_uncertain_claim():
    first = "A major effect is proven <Paper ID: W1>."
    replacement = "A cautious observation is reported <Paper ID: W1>."
    second = "An unresolved observation <Paper ID: W2>."
    original = "## Evidence\n\n" + first + "\n\n" + second
    generator = with_sources([
        audit_response(assessment("unsupported", quote=""), assessment("uncertain", 2, "W2", "")),
        _sentence_patch(replacement), audit_response(assessment()),
    ], {"W1": "A cautious observation is reported.", "W2": "An abstract with limited evidence."})

    result = generator._repair_final_claim_support(_quality_draft(original))

    assert result["section_drafts"] == [original.replace(first, replacement)]
    assert len(generator.chat_agent.calls) == 3
    assert any(item.get("claim") == second and item["resolution"] == "manual_review"
               for item in generator.survey_integrity_artifact["issues"])


@pytest.mark.parametrize("response", [json.dumps({"replacements": []}), _sentence_patch("An observation <Paper ID: W1>.")])
def test_empty_or_unchanged_patch_stops_before_audit(response):
    original = "## Evidence\n\nAn observation <Paper ID: W1>."
    generator = with_sources([response])
    generator.config.ModuleInfo.SurveyGenerator.evidence_bounded_section_quality_revise_retry = 2
    assert repair(generator, original) is None
    assert len(generator.chat_agent.calls) == 1
    assert not generator.survey_integrity_artifact.get("claim_support")


@pytest.mark.parametrize("sentence_id", [2, True])
def test_permission_conflict_stops_without_retry(sentence_id):
    original = "## Evidence\n\nAn observation <Paper ID: W1>. Unchanged sentence."
    generator = with_sources([_sentence_patch("Unpermitted modification.", sentence_id)])
    generator.config.ModuleInfo.SurveyGenerator.evidence_bounded_section_quality_revise_retry = 2
    assert repair(generator, original, "An observation") is None
    assert len(generator.chat_agent.calls) == 1
    assert any(item["status"] == "permission_conflict" for item in generator.survey_review_state["issues"].values())


def test_invalid_citation_is_rejected_before_audit():
    original = "## Evidence\n\nAn observation <Paper ID: W1>."
    generator = with_sources([_sentence_patch("A new claim <Paper ID: W2>.")])
    assert repair(generator, original) is None
    assert len(generator.chat_agent.calls) == 1
    assert not generator.survey_integrity_artifact.get("claim_support")


def test_repeated_rejected_candidate_does_not_repeat_audit():
    original = "## Evidence\n\nAn observation <Paper ID: W1>."
    patch = _sentence_patch("A major effect is proven <Paper ID: W1>.")
    generator = with_sources([patch, audit_response(assessment("unsupported", quote="")), patch])
    generator.config.ModuleInfo.SurveyGenerator.evidence_bounded_section_quality_revise_retry = 2
    assert repair(generator, original) is None
    assert len(generator.chat_agent.calls) == 3
    assert "Repeated rejected candidate" in generator._last_quality_revision_errors[0]
    assert repair(generator, original, stage="consolidation") is None
    assert len(generator.chat_agent.calls) == 3


def test_uncertain_changed_claim_stops_instead_of_rewriting_again():
    original = "## Evidence\n\nAn observation <Paper ID: W1>."
    generator = with_sources([_sentence_patch("A qualified effect is reported <Paper ID: W1>."),
                              audit_response(assessment("uncertain", quote=""))])
    generator.config.ModuleInfo.SurveyGenerator.evidence_bounded_section_quality_revise_retry = 2
    assert repair(generator, original) is None
    assert len(generator.chat_agent.calls) == 2
    assert any(item["status"] == "needs_evidence" for item in generator.survey_review_state["issues"].values())


def test_missing_local_evidence_never_fetches_or_calls_the_model():
    generator = with_sources([])
    def forbidden(*args, **kwargs):
        pytest.fail("Review attempted external evidence retrieval")
    generator.work_analyzer.work_collector._survey_resume_abstracts = {}
    generator.work_analyzer.work_collector.get_paper_title_abstract = forbidden
    generator.work_analyzer.get_paper_keynote = forbidden
    results = generator._audit_section_claim_support("An observation <Paper ID: W1>.", section_index=1, stage="final")
    assert results[0]["verdict"] == "uncertain"
    assert results[0]["source_status"] == {"W1": "unavailable"}
    assert not generator.chat_agent.calls


def test_frozen_fulltext_keeps_complete_passages_and_locations(tmp_path):
    generator = with_sources([])
    generator.work_analyzer.work_collector.data_manager = SimpleNamespace(cache_path=str(tmp_path))
    path = tmp_path / "parsed_papers" / "W1" / "auto" / "W1.md"
    path.parent.mkdir(parents=True)
    passage = "An intact source passage " + "x" * 3000
    path.write_text("# Results\n\n" + passage, encoding="utf-8")
    first = freeze_paper_evidence(generator, "W1")
    path.write_text("Changed after snapshot.", encoding="utf-8")
    assert freeze_paper_evidence(generator, "W1") == first
    assert any(item["text"] == passage and item["location"].endswith(":3") for item in first["fragments"])
    assert first["status"] == "fulltext"


def test_review_call_budget_is_shared_across_all_stages():
    original = "## Evidence\n\nAn observation <Paper ID: W1>."
    generator = with_sources([json.dumps({
        "scores": {"readability": 6, "scientific": 8, "framework": 8},
        "suggestions": ["Clarify."], "target_excerpts": ["An observation"],
    })])
    settings = generator.config.ModuleInfo.SurveyGenerator
    settings.review_max_calls = 1
    settings.survey_consolidation_enabled = True
    draft = generator._improve_evidence_bounded_sections(_quality_draft(original))
    draft = generator._consolidate_evidence_bounded_draft(draft)
    draft = generator._repair_final_claim_support(draft)
    assert draft["section_drafts"] == [original]
    assert len(generator.chat_agent.calls) == 1
    assert generator.survey_review_state["calls"] == 1
    assert any(item["status"] == "budget_exhausted" for item in generator.survey_review_state["issues"].values())


def test_token_budget_is_checked_before_dispatch():
    generator = with_sources([])
    generator.config.ModuleInfo.SurveyGenerator.review_max_tokens = 10
    with pytest.raises(ReviewStopped, match="token budget"):
        review_runtime(generator).call("A long review prompt", response_format="json_object")
    assert not generator.chat_agent.calls


@pytest.mark.parametrize("requested_output_tokens", [None, 24000])
def test_review_uses_normal_client_output_allowance_and_shared_deadline(monkeypatch, requested_output_tokens):
    from utils.api_call import DEFAULT_CHAT_MAX_OUTPUT_TOKENS

    generator = with_sources(["Reviewed"])
    runtime = review_runtime(generator)
    monkeypatch.setattr(runtime, "remaining_seconds", lambda: 275)
    options = {} if requested_output_tokens is None else {"max_output_tokens": requested_output_tokens}

    assert runtime.call("Review", **options) == "Reviewed"

    call = generator.chat_agent.calls[0]
    assert call["request_timeout"] == 275
    assert call["max_output_tokens"] == (requested_output_tokens or DEFAULT_CHAT_MAX_OUTPUT_TOKENS)
    assert call["max_output_tokens"] > 4096


def test_normal_output_allowance_is_clipped_by_remaining_shared_token_budget():
    generator = with_sources(["Reviewed"])
    runtime = review_runtime(generator)
    runtime.state["tokens_reserved"] = runtime.max_tokens - len("Review".encode("utf-8")) - 128 - 1024

    assert runtime.call("Review") == "Reviewed"
    assert generator.chat_agent.calls[0]["max_output_tokens"] == 1024
    assert runtime.state["tokens_reserved"] == runtime.max_tokens
    with pytest.raises(ReviewStopped, match="token budget"):
        runtime.call("Review again")
    assert len(generator.chat_agent.calls) == 1


def test_elapsed_budget_survives_resume():
    generator = with_sources([])
    state = review_runtime(generator).state
    state["elapsed_seconds"] = 600
    resumed = with_sources([])
    resumed.survey_review_state = copy.deepcopy(state)
    with pytest.raises(ReviewStopped, match="time budget"):
        review_runtime(resumed).call("Review")
    assert not resumed.chat_agent.calls


def test_network_retries_are_limited_and_charged_despite_transport_decorator():
    class Chat:
        def __init__(self):
            self.attempts = 0

        @retry(stop=stop_after_attempt(10))
        def remote_chat(self, prompt, **kwargs):
            self.attempts += 1
            raise requests.Timeout("Temporary timeout")

    generator = with_sources([])
    generator.chat_agent = Chat()
    with pytest.raises(ReviewStopped, match="network attempts exhausted"):
        review_runtime(generator).call("Review")
    assert generator.chat_agent.attempts == 2
    assert generator.survey_review_state["calls"] == 2


def test_audit_cache_and_terminal_state_survive_new_generator():
    claim = "An unresolved observation <Paper ID: W1>."
    generator = with_sources([audit_response(assessment("uncertain", quote=""))])
    generator._audit_section_claim_support(claim, section_index=1, stage="final")
    resumed = with_sources([])
    resumed.survey_review_state = copy.deepcopy(generator.survey_review_state)
    findings = resumed._audit_section_claim_support(claim, section_index=1, stage="final")
    assert findings[0]["cached"] is True
    assert repair(resumed, "## Evidence\n\n" + claim) is None
    assert not resumed.chat_agent.calls


def test_evidence_change_invalidates_audit_and_terminal_state():
    claim = "A cautious observation is reported <Paper ID: W1>."
    generator = with_sources([audit_response(assessment("uncertain", quote=""))])
    generator._audit_section_claim_support(claim, section_index=1, stage="final")
    resumed = with_sources([audit_response(assessment())], {"W1": "A cautious observation is reported. New evidence."})
    resumed.survey_review_state = copy.deepcopy(generator.survey_review_state)
    findings = resumed._audit_section_claim_support(claim, section_index=1, stage="final")
    assert findings[0]["verdict"] == "supported"
    assert len(resumed.chat_agent.calls) == 1
    assert not review_runtime(resumed).terminal(claim)


def test_multiple_papers_can_support_different_atomic_subclaims():
    claim = "Alpha is observed <Paper ID: W1>, and Beta is observed <Paper ID: W2>."
    response = {"claim_id": 1, "subclaims": [
        {"text": "Alpha is observed, ", "claim_type": "fact", "verdict": "supported",
         "evidence": [{"paper_id": "W1", "quote": "Alpha is observed"}]},
        {"text": "and Beta is observed.", "claim_type": "fact", "verdict": "supported",
         "evidence": [{"paper_id": "W2", "quote": "Beta is observed"}]},
    ]}
    generator = with_sources([audit_response(response)], {"W1": "Alpha is observed.", "W2": "Beta is observed."})
    result = generator._audit_section_claim_support(claim, section_index=1, stage="final")
    assert result[0]["verdict"] == "supported"


def test_omitted_unsupported_clause_cannot_be_hidden_by_atomic_subclaims():
    claim = "Alpha is observed and cures all disease <Paper ID: W1>."
    response = {"claim_id": 1, "subclaims": [
        {"text": "Alpha is observed", "claim_type": "fact", "verdict": "supported",
         "evidence": [{"paper_id": "W1", "quote": "Alpha is observed"}]},
    ]}
    generator = with_sources([audit_response(response)], {"W1": "Alpha is observed."})
    result = generator._audit_section_claim_support(claim, section_index=1, stage="final")
    assert result[0]["verdict"] == "uncertain"


def test_coverage_claim_uses_the_evidence_plan():
    claim = "SH1 has direct-observation evidence <Paper ID: W1>."
    response = {"claim_id": 1, "subclaims": [
        {"text": claim, "claim_type": "evidence_coverage", "verdict": "supported",
         "sub_hypothesis_id": "SH1", "ledger_quote": "direct_observation", "evidence": []},
    ]}
    generator = with_sources([audit_response(response)])
    findings = generator._audit_section_claim_support(claim, section_index=1, stage="final")
    assert findings[0]["verdict"] == "supported"


def test_uncited_new_fact_inside_a_changed_sentence_is_included_in_audit():
    original = "## Evidence\n\nAn observation <Paper ID: W1>."
    replacement = "This cures all disease. A cautious observation is reported <Paper ID: W1>."
    generator = with_sources([_sentence_patch(replacement), audit_response(assessment("unsupported", quote=""))])
    assert repair(generator, original) is None
    assert "This cures all disease." in generator.chat_agent.calls[1]["prompt"]


def test_audit_only_mode_keeps_unsupported_claim_without_repair():
    claim = "A major effect is proven <Paper ID: W1>."
    generator = with_sources([audit_response(assessment("unsupported", quote=""))])
    generator.config.ModuleInfo.SurveyGenerator.review_mode = "audit_only"
    result = generator._repair_final_claim_support(_quality_draft("## Evidence\n\n" + claim))
    assert claim in result["full_draft"]
    assert len(generator.chat_agent.calls) == 1
    assert generator.survey_integrity_artifact["issues"][0]["resolution"] == "manual_review"


def test_confirmed_packet_quotes_are_verified_against_the_original():
    packet = SimpleNamespace(markdown="## Results\n\nA cautious observation is reported.")
    notes = {0: {"claims": [
        {"evidence": "A cautious observation is reported.", "source_section": "Results"},
        {"evidence": "An invented result.", "source_section": "Results"},
    ]}}
    fragments = confirmed_packet_evidence(notes, [packet])
    assert len(fragments) == 1
    assert fragments[0]["source"] == "confirmed_fulltext"
    assert "Results" in fragments[0]["location"]
    assert fragments[0]["source_version"]


def test_resume_keeps_frozen_sources_when_original_files_are_unavailable():
    claim = "A cautious observation is reported <Paper ID: W1>."
    generator = with_sources([audit_response(assessment())])
    generator._audit_section_claim_support(claim, section_index=1, stage="final")
    resumed = with_sources([])
    resumed.work_analyzer.work_collector._survey_resume_abstracts = {}
    resumed.survey_review_state = copy.deepcopy(generator.survey_review_state)
    findings = resumed._audit_section_claim_support(claim, section_index=1, stage="final")
    assert findings[0]["cached"] is True
    assert findings[0]["verdict"] == "supported"
    assert not resumed.chat_agent.calls


def test_a_malformed_audit_is_not_requested_again_in_another_stage():
    claim = "A cautious observation is reported <Paper ID: W1>."
    generator = with_sources(["not JSON"])
    generator._audit_section_claim_support(claim, section_index=1, stage="section_revision")
    generator._audit_section_claim_support(claim, section_index=1, stage="final")
    assert len(generator.chat_agent.calls) == 1


def test_quality_scores_stalling_stops_additional_improvements():
    original = "## Evidence\n\nAn observation <Paper ID: W1>."
    review = {"scores": {"readability": 6, "scientific": 8, "framework": 8},
              "suggestions": ["Clarify."], "target_excerpts": ["An observation"]}
    revised_review = {**review, "target_excerpts": ["A cautious observation"]}
    generator = _quality_generator([
        json.dumps(review), _sentence_patch("A cautious observation <Paper ID: W1>."), json.dumps(revised_review),
    ])
    generator._improve_evidence_bounded_sections(_quality_draft(original))
    assert len(generator.chat_agent.calls) == 3
    assert any(item["reason"] == "quality_scores_stalled" for item in generator.survey_review_state["issues"].values())


def test_checkpoint_restores_review_limits_cache_and_terminal_issues(tmp_path):
    from modules.survey_delivery import get_survey_checkpoint

    original = "## Evidence\n\nAn unresolved observation <Paper ID: W1>."
    generator = with_sources([audit_response(assessment("uncertain", quote=""))])
    generator.config.BasicInfo.base_dir = str(tmp_path)
    checkpoint = get_survey_checkpoint(generator)
    checkpoint.begin([], "", _quality_draft(original)["outline"])
    generator._audit_section_claim_support(original, section_index=1, stage="final")
    checkpoint.save_draft(_quality_draft(original))
    resumed = with_sources([])
    resumed.config.BasicInfo.base_dir = str(tmp_path)
    get_survey_checkpoint(resumed).restore()
    results = resumed._audit_section_claim_support(original, section_index=1, stage="final")
    assert results[0]["cached"]
    assert resumed.survey_review_state["calls"] == 1
    assert review_runtime(resumed).terminal(original.split("\n\n")[1])
    assert not resumed.chat_agent.calls


def test_partial_final_repair_does_not_resolve_an_unchanged_unsupported_claim():
    first = "A major effect is proven <Paper ID: W1>."
    second = "A second unsupported assertion <Paper ID: W1>."
    original = "## Evidence\n\n" + first + "\n\n" + second
    generator = with_sources([
        audit_response(assessment("unsupported", quote=""), assessment("unsupported", 2, quote="")),
        _sentence_patch("A cautious observation is reported <Paper ID: W1>."), audit_response(assessment()),
    ])
    generator._repair_final_claim_support(_quality_draft(original))
    pending = [item for item in generator.survey_integrity_artifact["issues"]
               if item.get("claim") == second and item["stage"] == "final"]
    assert pending[0]["resolution"] == "manual_review"


def test_transport_rejects_an_expired_review_deadline_before_http(monkeypatch):
    import test_llm_provider_migration as fixtures
    from utils import api_call

    monkeypatch.setattr(api_call, "load_config", fixtures._project_config)
    monkeypatch.setattr(api_call.tiktoken, "encoding_for_model", lambda _model: fixtures._CharacterEncoding())
    monkeypatch.setattr(api_call.requests, "post", lambda *args, **kwargs: pytest.fail("HTTP request after deadline"))
    agent = api_call.ChatAgent(fixtures._survey_config())
    with pytest.raises(requests.Timeout, match="deadline exceeded"):
        api_call.ChatAgent.remote_chat.__wrapped__(agent, "question", max_output_tokens=12, request_deadline=0)


def test_streaming_transport_closes_response_at_review_deadline(monkeypatch):
    import test_llm_provider_migration as fixtures
    from utils import api_call

    current = [0.0]

    class Response(fixtures._FakeResponse):
        closed = False

        def iter_lines(self):
            current[0] = 2.0
            yield b'data: {"choices":[{"delta":{"content":"late answer"}}]}'

        def close(self):
            self.closed = True

    response = Response()
    monkeypatch.setattr(api_call, "load_config", fixtures._project_config)
    monkeypatch.setattr(api_call.tiktoken, "encoding_for_model", lambda _model: fixtures._CharacterEncoding())
    monkeypatch.setattr(api_call.time, "monotonic", lambda: current[0])
    monkeypatch.setattr(api_call.requests, "post", lambda *args, **kwargs: response)
    agent = api_call.ChatAgent(fixtures._survey_config(stream=True))
    with pytest.raises(requests.Timeout, match="while streaming"):
        api_call.ChatAgent.remote_chat.__wrapped__(agent, "question", max_output_tokens=12, request_deadline=1)
    assert response.closed


def test_audit_only_delivery_runs_all_audits_and_resumes_without_new_calls(tmp_path):
    from modules.survey_delivery import resume_survey_delivery, run_survey_delivery

    claim = "A major effect is proven <Paper ID: W1>."
    draft = _quality_draft("## Evidence\n\n" + claim)

    def generator_for(responses):
        generator = with_sources(responses)
        generator.config.BasicInfo.base_dir = str(tmp_path)
        generator.config.ModuleInfo.SurveyGenerator.review_mode = "audit_only"
        generator.config.ModuleInfo.SurveyGenerator.survey_consolidation_enabled = True
        generator.draft_survey = lambda *args: draft
        generator._finalize_evidence_bounded_draft = lambda *args: pytest.fail("Unresolved audit was finalized")
        return generator

    first = generator_for([
        json.dumps({"scores": {"readability": 6, "scientific": 6, "framework": 8},
                    "suggestions": ["Narrow the claim."], "target_excerpts": [claim]}),
        json.dumps({"contradictions": [], "repetitions": []}),
        audit_response(assessment("unsupported", quote="")),
    ])
    result = run_survey_delivery(first, None, [], "", draft["outline"])
    assert result[0] == {"survey_status": "requires_review"}
    assert len(first.chat_agent.calls) == 3
    assert {"section_quality", "consistency", "claim_support"}.issubset(first._survey_checkpoint.state["completed"])
    resumed = generator_for([])
    assert resume_survey_delivery(resumed, None)[0] == {"survey_status": "requires_review"}
    assert not resumed.chat_agent.calls


def test_new_local_evidence_invalidates_completed_review_stages_on_resume(tmp_path):
    from modules.survey_delivery import get_survey_checkpoint

    original = "## Evidence\n\nAn observation <Paper ID: W1>."
    generator = with_sources([])
    generator.config.BasicInfo.base_dir = str(tmp_path)
    checkpoint = get_survey_checkpoint(generator)
    checkpoint.begin([], "", _quality_draft(original)["outline"])
    generator._begin_review_stage(_quality_draft(original), "section_quality")
    checkpoint.state["completed"] = ["draft", "review", "section_quality", "consistency", "claim_support"]
    checkpoint.save_draft(_quality_draft(original))
    resumed = with_sources([])
    resumed.config.BasicInfo.base_dir = str(tmp_path)
    resumed.work_analyzer.work_collector.data_manager = SimpleNamespace(cache_path=str(tmp_path))
    path = tmp_path / "parsed_papers" / "W1" / "auto" / "W1.md"
    path.parent.mkdir(parents=True)
    path.write_text("New full-text evidence.", encoding="utf-8")
    restored = get_survey_checkpoint(resumed)
    restored.restore()
    assert restored.state["completed"] == ["draft", "review"]
    assert resumed.survey_review_state["evidence"]["W1"]["status"] == "fulltext"


def test_long_audit_batches_keep_successful_results_when_budget_ends():
    claims = [f"Observation {index} <Paper ID: W1>." for index in range(10)]
    generator = with_sources([audit_response(*(assessment(claim_id=index + 1) for index in range(8)))])
    generator.config.ModuleInfo.SurveyGenerator.review_max_calls = 1
    findings = generator._audit_section_claim_support("\n\n".join(claims), section_index=1, stage="final")
    assert len(findings) == 10
    assert [item["verdict"] for item in findings[:8]] == ["supported"] * 8
    assert [item["status"] for item in findings[8:]] == ["budget_exhausted"] * 2
    assert len(generator.chat_agent.calls) == 1


def test_stream_deadline_is_checked_even_without_a_complete_event_line(monkeypatch):
    from utils import api_call

    current = [0.0]

    class Response:
        closed = False

        def iter_content(self, chunk_size):
            assert chunk_size == 1
            yield b"d"
            current[0] = 2.0
            yield b"a"

        def close(self):
            self.closed = True

    response = Response()
    monkeypatch.setattr(api_call.time, "monotonic", lambda: current[0])
    with pytest.raises(requests.Timeout, match="while streaming"):
        list(api_call.ChatAgent._review_deadline_lines(response, 1))
    assert response.closed
