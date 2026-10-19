import json
from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf

from src.agents.idea_agent.agent.artifacts import artifact_init
from src.agents.idea_agent.utils.core.chat_transport import normalize_responses_kwargs
from src.agents.idea_agent.utils.workflow.keynote_compression import compress_keynotes
from src.agents.idea_agent.utils.workflow.ligagent_utils import LigRuntime, LigSession
from src.agents.idea_agent.utils.workflow.stage_contract import StageContext


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, message, *args):
        self.warnings.append(message % args if args else message)


def _context(tmp_path, responses, *, model="qwen3.8-flash", repairs=2):
    calls = []

    def chat(prompt, **kwargs):
        calls.append((prompt, kwargs))
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    artifact = artifact_init()
    agent = SimpleNamespace(
        model=model,
        project_config={"llm": {"provider": "qwen"}},
        config=OmegaConf.create({"agent": {"keynote_json_repair_attempts": repairs, "paper_keynote_keep_top_k": 3}}),
        run_dir=tmp_path,
        logger=_Logger(),
        chat=chat,
        session=LigSession(artifact),
    )
    agent.runtime = LigRuntime(agent)
    ctx = StageContext(
        agent=agent,
        artifact=artifact,
        workflow_name="ligagent.knowledge_acquisition",
        runtime=agent.runtime,
        session=agent.session,
        logger=agent.logger,
    )
    return agent, ctx, calls


def _reference(paper_id="W1"):
    return {
        "paper_id": paper_id,
        "title": f"Paper {paper_id}",
        "keynote": f"Original evidence for {paper_id}, including its limitations.\nSecond line.",
        "score": 95,
    }


def _compress(agent, ctx, reference=None, **kwargs):
    reference = reference or _reference()
    return compress_keynotes(
        agent,
        ctx,
        prompt=f"Compress {reference['title']} as JSON: {reference['keynote']}",
        references=[reference],
        **kwargs,
    )


def _checkpoint(tmp_path):
    paths = list((tmp_path / "keynote_compression").glob("*.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8"))


def test_keynote_requests_json_mode_and_reuses_completed_checkpoint(tmp_path):
    raw = '{"summary":"  Evidence.  ","insight":"A limitation."}'
    agent, ctx, calls = _context(tmp_path, [raw])

    result = _compress(agent, ctx)
    cached = _compress(agent, ctx)

    assert result["summary"] == "Evidence."
    assert result["insight"] == "A limitation."
    assert result["compression_status"] == "completed"
    assert calls[0][1]["response_format"] == {"type": "json_object"}
    assert cached == result
    assert len(calls) == 1
    assert _checkpoint(tmp_path)["attempts"][0]["raw_response"] == raw


def test_keynote_uses_resolved_stage_model_capabilities_and_responses_format(tmp_path):
    agent, ctx, calls = _context(tmp_path, ['{"summary":"Evidence.","insight":"A limitation."}'])
    agent.resolve_stage_model = lambda **_kwargs: "qwen3-max-2026-01-23"

    _compress(agent, ctx)

    kwargs = calls[0][1]
    assert kwargs["model"] == "qwen3-max-2026-01-23"
    response_format = kwargs["response_format"]
    assert response_format["type"] == "json_schema"
    schema = response_format["json_schema"]["schema"]
    assert schema["required"] == ["summary", "insight"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["summary"]["type"] == "string"
    converted = normalize_responses_kwargs(kwargs)
    assert converted["text"]["format"]["schema"] == schema
    assert converted["text"]["format"]["strict"] is True
    assert "response_format" not in converted


@pytest.mark.parametrize(
    ("raw", "expected_error"),
    [
        ("**Compressed keynote for LigAgent**\nEvidence.", "Expecting value"),
        ('{"summary":"Evidence."}', "insight"),
        ('{"summary":["Evidence."],"insight":"A limitation."}', "summary must be a string"),
        ('{"summary":"Evidence.","insight":{"claim":"A limitation."}}', "insight must be a string"),
        ('{"summary":"  ","insight":"A limitation."}', "summary must be a non-empty string"),
        ('{"summary":"Evidence.","insight":""}', "insight must be a non-empty string"),
        ('[{"summary":"Evidence.","insight":"A limitation."}]', "must be an object"),
        ('{"summary":"Evidence.","insight":"A limitation.","extra":true}', "unsupported fields"),
    ],
)
def test_keynote_repairs_only_invalid_capsule_and_preserves_raw_response(tmp_path, raw, expected_error):
    repaired = '{"summary":"Repaired evidence.","insight":"A supported limitation."}'
    agent, ctx, calls = _context(tmp_path, [raw, repaired])

    result = _compress(agent, ctx)

    assert result["compression_status"] == "repaired"
    assert result["summary"] == "Repaired evidence."
    assert len(calls) == 2
    assert expected_error in calls[1][0]
    assert raw in calls[1][0]
    assert _reference()["keynote"] in calls[1][0]
    assert calls[1][1]["temperature"] == 0.0
    assert [record["raw_response"] for record in _checkpoint(tmp_path)["attempts"]] == [raw, repaired]
    assert any("repair 1/2" in message for message in agent.logger.warnings)


def test_keynote_persists_raw_before_requesting_repair(tmp_path):
    agent, ctx, calls = _context(tmp_path, ["Markdown response"])

    def repair(prompt, **kwargs):
        saved = _checkpoint(tmp_path)
        assert saved["attempts"][0]["raw_response"] == "Markdown response"
        assert saved["attempts"][0]["error"]
        return '{"summary":"Evidence.","insight":"A limitation."}'

    original_chat = agent.chat

    def chat(prompt, **kwargs):
        if calls:
            return repair(prompt, **kwargs)
        return original_chat(prompt, **kwargs)

    agent.chat = chat
    assert _compress(agent, ctx)["compression_status"] == "repaired"


def test_keynote_falls_back_after_two_repairs_without_losing_original(tmp_path):
    raw = "**Compressed keynote**\nA response that is not JSON."
    agent, ctx, calls = _context(tmp_path, [raw, raw, raw])
    reference = _reference()

    result = _compress(agent, ctx, reference)

    assert len(calls) == 3
    assert result["compression_status"] == "fallback"
    assert result["summary"] == reference["keynote"]
    assert result["insight"] == ""
    assert result["original_keynotes"][0]["paper_id"] == "W1"
    assert len(result["compression_issues"]) == 3
    saved = _checkpoint(tmp_path)
    assert saved["status"] == "fallback"
    assert saved["references"][0]["keynote"] == reference["keynote"]
    assert [record["raw_response"] for record in saved["attempts"]] == [raw, raw, raw]
    assert any("continuing" in message and "W1" in message for message in agent.logger.warnings)


def test_keynote_does_not_repeat_exhausted_transport_failures(tmp_path):
    agent, ctx, calls = _context(tmp_path, [TimeoutError("Request retries exhausted")])

    result = _compress(agent, ctx)

    assert result["compression_status"] == "fallback"
    assert len(calls) == 1
    assert "Request retries exhausted" in _checkpoint(tmp_path)["attempts"][0]["error"]


def test_keynote_preserves_invalid_response_when_repair_request_fails(tmp_path):
    raw = "**Compressed keynote**\nThe original malformed answer."
    agent, ctx, calls = _context(tmp_path, [raw, TimeoutError("Repair request failed")])

    result = _compress(agent, ctx)

    assert result["compression_status"] == "fallback"
    assert len(calls) == 2
    attempts = _checkpoint(tmp_path)["attempts"]
    assert attempts[0]["raw_response"] == raw
    assert "Repair request failed" in attempts[1]["error"]


def test_keynote_retains_previous_failed_responses_when_retried(tmp_path):
    agent, ctx, calls = _context(
        tmp_path, ["Original malformed answer", '{"summary":"Evidence.","insight":"A limitation."}'], repairs=0
    )

    assert _compress(agent, ctx)["compression_status"] == "fallback"
    assert _compress(agent, ctx)["compression_status"] == "completed"
    assert len(calls) == 2
    attempts = _checkpoint(tmp_path)["attempts"]
    assert len(attempts) == 2
    assert attempts[0]["raw_response"] == "Original malformed answer"


def test_keynote_does_not_reuse_checkpoint_for_changed_source(tmp_path):
    agent, ctx, calls = _context(
        tmp_path,
        [
            '{"summary":"First evidence.","insight":"First limitation."}',
            '{"summary":"Updated evidence.","insight":"Updated limitation."}',
        ],
    )
    reference = _reference()

    _compress(agent, ctx, reference)
    reference["keynote"] = "Updated source evidence."
    result = _compress(agent, ctx, reference)

    assert result["summary"] == "Updated evidence."
    assert len(calls) == 2
    assert len(list((tmp_path / "keynote_compression").glob("*.json"))) == 2


def test_keynote_downgrades_explicitly_rejected_formats_with_bounded_requests(tmp_path):
    errors = [
        ValueError("response_format json_schema is not supported"),
        ValueError("response_format json_object is not supported"),
    ]
    agent, ctx, calls = _context(
        tmp_path,
        [*errors, '{"summary":"Evidence.","insight":"A limitation."}'],
        model="qwen3-max-2026-01-23",
    )

    result = _compress(agent, ctx)

    assert result["compression_status"] == "completed"
    assert len(calls) == 3
    assert calls[0][1]["response_format"]["type"] == "json_schema"
    assert calls[1][1]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[2][1]
    assert len(result["compression_issues"]) == 2


def test_keynote_omits_unsupported_format_for_unknown_model(tmp_path):
    agent, ctx, calls = _context(
        tmp_path, ['{"summary":"Evidence.","insight":"A limitation."}'], model="custom-text-model"
    )

    assert _compress(agent, ctx)["compression_status"] == "completed"
    assert "response_format" not in calls[0][1]


def test_keynote_group_fallback_preserves_every_source(tmp_path):
    agent, ctx, calls = _context(tmp_path, ["Bad JSON"], repairs=0)
    references = [_reference("W1"), _reference("W2")]

    result = compress_keynotes(agent, ctx, prompt="Summarize both papers as JSON", references=references, group=True)

    assert len(calls) == 1
    assert result["compression_status"] == "fallback"
    assert [reference["paper_id"] for reference in result["original_keynotes"]] == ["W1", "W2"]
    assert all(reference["keynote"] in result["summary"] for reference in references)


def test_reference_selection_continues_after_one_capsule_fails(tmp_path):
    from src.agents.idea_agent.utils.workflow.ligagent_handlers import ka_reference_selection_stage

    agent, ctx, calls = _context(
        tmp_path,
        [
            '{"summary":"First evidence.","insight":"First limitation."}',
            "Bad JSON",
            "Bad JSON",
            "Bad JSON",
            '{"summary":"Third evidence.","insight":"Third limitation."}',
            '{"summary":"Remaining evidence."}',
        ],
    )
    ctx.state = {
        "topic": "A receptor topic",
        "rag_query": "A receptor query",
        "ranked_keynotes": [_reference(f"W{index}") for index in range(1, 5)],
        "mode": "standard",
    }

    result = ka_reference_selection_stage(agent, ctx)

    references = result.state_patch["curated_references"]
    assert result.status == "degraded"
    assert result.metrics["keynote_fallbacks"] == 1
    assert len(references) == 4
    assert references[0]["summary"] == "First evidence."
    assert references[1]["summary"] == _reference("W2")["keynote"]
    assert references[1]["reference_mode"] == "keynote_fallback"
    assert references[2]["summary"] == "Third evidence."
    assert references[3]["summary"] == "Remaining evidence."
    assert len(calls) == 6
    assert all("Paper W2" in prompt and "Paper W1" not in prompt for prompt, _kwargs in calls[2:4])
    assert len(list((tmp_path / "keynote_compression").glob("*.json"))) == 4
