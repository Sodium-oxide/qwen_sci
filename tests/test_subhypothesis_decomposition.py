import json
from types import SimpleNamespace

import pytest
from omegaconf import OmegaConf

from src.agents.survey_agent.modules.work_collector import WorkCollector
from src.agents.survey_agent.modules.survey_generator import SurveyGenerator
from src.agents.survey_agent.utils import api_call
from src.pipeline.research_identity import build_project_research_context
from src.pipeline.research_question_contract import QUESTION_KIND_SPECS
from src.pipeline.retrieval_lanes import build_subhypothesis_retrieval_plan
from src.pipeline.subhypothesis_decomposition import (
    SUBHYPOTHESIS_DECOMPOSITION_MODEL,
    SUBHYPOTHESIS_DECOMPOSITION_PROVIDER,
    build_subhypothesis_decomposition_prompt,
    load_or_build_subhypothesis_decomposition,
    parse_subhypothesis_decomposition_response,
    subhypothesis_decomposition_response_diagnostic,
)


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass


def _contract(
    context: dict,
    *,
    identifier: str,
    title: str,
    question: str,
    question_kind: str,
    research_role: str,
    scientific_scope: dict[str, list[str]],
    challenge_target: str,
    exclusion_terms: list[str],
) -> dict:
    required_slots = list(QUESTION_KIND_SPECS[question_kind]["required_slots"])
    return {
        "schema_version": "science_subhypothesis_v2",
        "sub_hypothesis_id": identifier,
        "title": title,
        "question": question,
        "question_kind": question_kind,
        "scientific_scope": scientific_scope,
        "required_slots": required_slots,
        "slot_definitions": {
            slot: {
                "meaning": f"Evidence requirement for {slot}.",
                "retrieval_concepts": [
                    *scientific_scope.get("research_object", []),
                    *scientific_scope.get("outcome_or_construct", []),
                    slot.replace("_", " "),
                ],
                "minimum_evidence": "A scholarly work reports directly relevant evidence.",
                "admission_rule": "The work supports evaluation of this slot in the declared scope.",
            }
            for slot in required_slots
        },
        "research_role": research_role,
        "challenge_target": challenge_target,
        "design_basis_ids": [
            item["id"] for item in context["research_design_inventory"]["design_basis"][:3]
        ],
        "exclusion_terms": exclusion_terms,
    }


def _precision_medicine_subhypotheses(context: dict) -> list[dict]:
    return [
        _contract(
            context,
            identifier="clinical_benefit",
            title="Clinical benefit under genomic stratification",
            question="For which genomically stratified patients do personalized treatments improve clinical response compared with standard care?",
            question_kind="COMPARATIVE_EVALUATION",
            research_role="PRIMARY_QUESTION",
            scientific_scope={"research_object": ["personalized treatment"], "comparison_frame": ["standard care"], "outcome_or_construct": ["clinical response"], "condition_or_regime": ["prospective clinical use"]},
            challenge_target="the claim that personalized treatments improve clinical response for every genomically stratified population",
            exclusion_terms=["consumer wellness recommendation"],
        ),
        _contract(
            context,
            identifier="target_selection_mechanism",
            title="Molecular target selection mechanisms",
            question="Which genomic and biological mechanisms make molecular target selection actionable for individualized drug design and dose selection?",
            question_kind="MECHANISM_EXPLANATION",
            research_role="BASELINE_ENABLER",
            scientific_scope={"research_object": ["individualized drug design"], "intervention_or_input": ["multi-omic target identification"], "outcome_or_construct": ["target actionability"]},
            challenge_target="the assumption that molecular target selection is actionable without an identifiable mechanism",
            exclusion_terms=["non-therapeutic ancestry inference"],
        ),
        _contract(
            context,
            identifier="implementation_boundaries",
            title="Safety and implementation boundaries",
            question="What safety, bias, manufacturing, and regulatory limitations prevent personalized medicines from delivering benefits across patient subgroups?",
            question_kind="BOUNDARY_HETEROGENEITY",
            research_role="BOUNDARY_TEST",
            scientific_scope={"research_object": ["personalized medicine implementation"], "condition_or_regime": ["real-world clinical deployment"], "outcome_or_construct": ["adverse events and equitable access"]},
            challenge_target="the claim that personalized medicine delivers uniform benefits across patient subgroups",
            exclusion_terms=["unregulated direct-to-consumer marketing"],
        ),
        _contract(
            context,
            identifier="evidence_landscape",
            title="Evidence landscape and translation",
            question="Which validation measures establish whether precision medicine evidence can be translated across therapeutic areas?",
            question_kind="MEASUREMENT_VALIDITY",
            research_role="FOUNDATIONAL_CONTEXT",
            scientific_scope={"research_object": ["precision medicine evidence"], "outcome_or_construct": ["evidence maturity"], "measurement_or_endpoint": ["validation standards"]},
            challenge_target="the assumption that current validation standards establish translational readiness",
            exclusion_terms=["fictional future-health scenarios"],
        ),
    ]


def _project_context() -> dict:
    return build_project_research_context(
        original_topic="Can individualized medicines be designed and manufactured from each patient's genetics and biology?",
        declared_domain="medicine",
        objective="Assess evidence for personalized medicine, individualized drug design, dosing, and manufacturing.",
        use_llm=False,
    )


def test_prompt_and_response_compile_to_one_slot_recovery_task_per_required_slot() -> None:
    context = _project_context()
    prompt = build_subhypothesis_decomposition_prompt(context)
    raw_subhypotheses = _precision_medicine_subhypotheses(context)

    parsed = parse_subhypothesis_decomposition_response(
        json.dumps({"subhypotheses": raw_subhypotheses}),
        project_context=context,
    )
    plan = build_subhypothesis_retrieval_plan(context, parsed)

    assert "Produce 3 to 6" in prompt
    assert "science_subhypothesis_v2" in prompt
    assert "research_design_inventory" in prompt
    assert "retrieval_query_variants is optional" in prompt
    assert "2-6 short canonical English query_terms" in prompt
    assert context["primary_discipline"] in prompt
    assert len(parsed) == 4
    assert all(item["validation"]["valid"] for item in plan["subhypotheses"])
    assert all(
        len(item["slot_recovery_tasks"]) == len(item["required_slots"])
        for item in plan["subhypotheses"]
    )
    assert all(
        task["query"]
        for item in plan["subhypotheses"]
        for task in item["slot_recovery_tasks"]
    )


def test_optional_retrieval_query_variants_are_validated_and_preserved() -> None:
    context = _project_context()
    raw_subhypotheses = _precision_medicine_subhypotheses(context)
    first = dict(raw_subhypotheses[0])
    first["slot_definitions"] = dict(first["slot_definitions"])
    first_slot = first["required_slots"][0]
    first_definition = dict(first["slot_definitions"][first_slot])
    first_definition["retrieval_query_variants"] = [
        {
            "variant_id": "baseline_recall",
            "purpose": "broad candidate recall",
            "query_terms": ["personalized medicine", "treatment response"],
            "preferred_disciplines": ["medicine"],
        },
        {
            "variant_id": "pharmacogenomic_path",
            "purpose": "genetic contribution path",
            "query_terms": ["pharmacogenetic dosing", "drug response"],
            "preferred_disciplines": ["medicine", "chemistry"],
        },
    ]
    first["slot_definitions"][first_slot] = first_definition
    raw_subhypotheses[0] = first

    parsed = parse_subhypothesis_decomposition_response(
        {"subhypotheses": raw_subhypotheses},
        project_context=context,
    )
    plan = build_subhypothesis_retrieval_plan(context, parsed)
    task = plan["subhypotheses"][0]["slot_recovery_tasks"][0]

    assert task["query_variants"][0]["variant_id"] == "baseline_recall"
    assert task["query_variants"][1]["preferred_disciplines"] == ["medicine", "chemistry"]
    assert all(
        lane["query_variant_id"] in {"baseline_recall", "pharmacogenomic_path"}
        for lane in task["retrieval_plan"]["query_lanes"]
    )


def test_optional_precision_hints_and_llm_role_wording_do_not_reject_a_valid_sh() -> None:
    context = _project_context()
    raw_subhypotheses = _precision_medicine_subhypotheses(context)
    first = dict(raw_subhypotheses[0])
    first["slot_definitions"] = dict(first["slot_definitions"])
    first_slot = first["required_slots"][0]
    first_definition = dict(first["slot_definitions"][first_slot])
    first_definition["retrieval_query_variants"] = [
        {
            "variant_id": "economic_comparison",
            "purpose": "compare system-level cost evidence",
            "query_terms": ["personalized medicine", "treatment cost"],
            "preferred_disciplines": ["economics", "medicine"],
        }
    ]
    first["slot_definitions"][first_slot] = first_definition
    first["research_role"] = "system-level comparative assessment"
    raw_subhypotheses[0] = first

    parsed = parse_subhypothesis_decomposition_response(
        {"subhypotheses": raw_subhypotheses},
        project_context=context,
    )
    plan = build_subhypothesis_retrieval_plan(context, parsed)
    normalized = plan["subhypotheses"][0]
    variant = normalized["slot_definitions"][first_slot]["retrieval_query_variants"][0]

    assert normalized["validation"]["valid"] is True
    assert normalized["research_role"] == "PRIMARY_QUESTION"
    assert variant["preferred_disciplines"] == ["medicine"]
    assert (
        "dropped_unsupported_retrieval_query_variant_discipline:"
        f"{first_slot}:economics"
    ) in normalized["validation"]["warnings"]
    assert (
        "fallback_research_role:SYSTEM-LEVEL COMPARATIVE ASSESSMENT:PRIMARY_QUESTION"
        in normalized["validation"]["warnings"]
    )


@pytest.mark.parametrize("count", [2, 7])
def test_response_rejects_out_of_range_subhypothesis_count(count: int) -> None:
    context = _project_context()
    raw_subhypotheses = _precision_medicine_subhypotheses(context)
    while len(raw_subhypotheses) < count:
        clone = dict(raw_subhypotheses[-1])
        clone["sub_hypothesis_id"] = f"extra_{len(raw_subhypotheses)}"
        raw_subhypotheses.append(clone)

    with pytest.raises(ValueError, match="3-6"):
        parse_subhypothesis_decomposition_response(
            {"subhypotheses": raw_subhypotheses[:count]},
            project_context=context,
        )


def test_response_rejects_missing_required_slot_definition() -> None:
    context = _project_context()
    raw_subhypotheses = _precision_medicine_subhypotheses(context)
    raw_subhypotheses[0] = dict(raw_subhypotheses[0])
    raw_subhypotheses[0]["slot_definitions"] = dict(raw_subhypotheses[0]["slot_definitions"])
    raw_subhypotheses[0]["slot_definitions"].pop("candidate")

    with pytest.raises(ValueError, match="missing_slot_definition:candidate"):
        parse_subhypothesis_decomposition_response(
            {"subhypotheses": raw_subhypotheses},
            project_context=context,
        )


def test_decomposition_cache_reuses_validated_qwen_result(tmp_path) -> None:
    calls: list[str] = []
    context = _project_context()
    cache_path = tmp_path / "subhypothesis_decomposition.json"

    def qwen_call(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps({"subhypotheses": _precision_medicine_subhypotheses(context)})

    first = load_or_build_subhypothesis_decomposition(
        cache_path=cache_path,
        project_context=context,
        llm_call=qwen_call,
    )
    second = load_or_build_subhypothesis_decomposition(
        cache_path=cache_path,
        project_context=context,
        llm_call=lambda _prompt: (_ for _ in ()).throw(AssertionError("cache miss")),
    )

    assert len(calls) == 1
    assert first["cache_status"] == "miss"
    assert second["cache_status"] == "hit"
    assert first["subhypotheses"] == second["subhypotheses"]
    assert first["provider"] == SUBHYPOTHESIS_DECOMPOSITION_PROVIDER
    assert first["model"] == SUBHYPOTHESIS_DECOMPOSITION_MODEL


def test_raw_qwen_response_diagnostic_runs_before_parse_failure_and_redacts_secrets() -> None:
    context = _project_context()
    diagnostics: list[dict[str, str]] = []

    with pytest.raises(ValueError, match="subhypotheses list"):
        load_or_build_subhypothesis_decomposition(
            cache_path=None,
            project_context=context,
            llm_call=lambda _prompt: {
                "output": "not the required JSON object",
                "api_key": "sk-example-secret-value",
            },
            raw_response_observer=diagnostics.append,
        )

    assert diagnostics == [
        {
            "response_type": "dict",
            "preview": '{"output": "not the required JSON object", "api_key": "<redacted>"}',
        }
    ]
    direct = subhypothesis_decomposition_response_diagnostic(
        "Bearer token-value-for-test"
    )
    assert direct["response_type"] == "str"
    assert direct["preview"] == "Bearer <redacted>"


def _collector_for_auto_decomposition(tmp_path, agent) -> WorkCollector:
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(
            subhypotheses=[],
            subhypothesis_decomposition={},
            subhypothesis_decomposition_path="",
        ),
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                subhypothesis_decomposition_provider="qwen",
                subhypothesis_decomposition_model="qwen3.8-max",
                subhypothesis_decomposition_min_count=3,
                subhypothesis_decomposition_max_count=6,
                subhypothesis_decomposition_temperature=0.1,
                subhypothesis_decomposition_max_output_tokens=16000,
                subhypothesis_decomposition_cache_enabled=True,
                auto_decompose_subhypotheses=True,
            )
        ),
    )
    collector.cache_path = str(tmp_path)
    collector.logger = _Logger()
    collector._subhypothesis_decomposition_agent = agent
    collector.subhypothesis_decomposition_artifact = {}
    return collector


def test_work_collector_auto_decomposes_with_qwen_and_preserves_manual_priority(tmp_path) -> None:
    class _QwenAgent:
        def __init__(self):
            self.calls = []

        def remote_chat(self, prompt, **kwargs):
            self.calls.append((prompt, kwargs))
            return json.dumps({"subhypotheses": _precision_medicine_subhypotheses(context)})

    agent = _QwenAgent()
    collector = _collector_for_auto_decomposition(tmp_path, agent)
    context = _project_context()

    generated = collector._resolved_subhypotheses(context)
    cached = collector._auto_decompose_subhypotheses(context)

    assert len(generated) == 4
    assert len(cached) == 4
    assert len(agent.calls) == 1
    assert agent.calls[0][1]["response_format"] == "json_object"
    assert agent.calls[0][1]["max_output_tokens"] == 16000
    assert collector.config.BasicInfo.subhypothesis_decomposition["source"] == "automatic_qwen"
    assert collector.config.BasicInfo.subhypothesis_decomposition["cache_status"] == "hit"

    collector.config.BasicInfo.subhypotheses = _precision_medicine_subhypotheses(context)
    collector.config.BasicInfo.subhypothesis_decomposition = {}
    collector._auto_decompose_subhypotheses = lambda _context: (_ for _ in ()).throw(
        AssertionError("manual SH must not call Qwen")
    )
    assert collector._resolved_subhypotheses(context) == _precision_medicine_subhypotheses(context)
    assert collector.config.BasicInfo.subhypothesis_decomposition["source"] == "manual_configuration"


def test_work_collector_logs_raw_qwen_preview_before_invalid_response_is_rejected(tmp_path) -> None:
    class _CapturingLogger:
        def __init__(self):
            self.messages = []

        def info(self, message, *args, **_kwargs):
            self.messages.append(message % args if args else message)

        def warning(self, *_args, **_kwargs):
            pass

    class _QwenAgent:
        def remote_chat(self, _prompt, **_kwargs):
            return {"output": "Qwen declined to emit JSON", "authorization": "Bearer hidden"}

    collector = _collector_for_auto_decomposition(tmp_path, _QwenAgent())
    collector.logger = _CapturingLogger()

    with pytest.raises(ValueError, match="subhypotheses list"):
        collector._auto_decompose_subhypotheses(_project_context())

    diagnostic_log = next(
        message
        for message in collector.logger.messages
        if message.startswith("SH decomposition raw response type=")
    )
    assert "type=dict" in diagnostic_log
    assert '"output": "Qwen declined to emit JSON"' in diagnostic_log
    assert "<redacted>" in diagnostic_log
    assert "hidden" not in diagnostic_log


def test_chat_agent_provider_override_keeps_the_survey_model_unchanged(monkeypatch) -> None:
    project_config = OmegaConf.create(
        {
            "llm": {
                "providers": {
                    "openai": {
                        "api_key": "openai-key",
                        "base_url": "https://openai.invalid/v1",
                    },
                    "qwen": {
                        "api_key": "qwen-key",
                        "base_url": "https://qwen.invalid/v1",
                    },
                }
            }
        }
    )
    survey_config = OmegaConf.create(
        {
            "APIInfo": {
                "llm_provider": "openai",
                "llm_api_key": "openai-key",
                "llm_api_base_url": "https://openai.invalid/v1",
                "llm_model_name": "gpt-5.4-mini",
                "llm_max_context_length": 100000,
                "use_stream_mode": False,
                "batch_chat_agent_worker": 1,
                "chat_timeout": 30,
                "low_flow_mode": False,
                "low_flow_latency": 0,
            }
        }
    )
    monkeypatch.setattr(api_call, "load_config", lambda: project_config)

    agent = api_call.ChatAgent(
        survey_config,
        provider_override="qwen",
        model_override="qwen3.8-max",
    )

    assert agent.provider_name == "qwen"
    assert agent.model_name == "qwen3.8-max"
    assert agent.remote_url == "https://qwen.invalid/v1/chat/completions"
    assert agent.token == "qwen-key"
    assert survey_config.APIInfo.llm_model_name == "gpt-5.4-mini"


def test_survey_json_persists_subhypothesis_decomposition(tmp_path) -> None:
    markdown_path = tmp_path / "survey.md"
    json_path = tmp_path / "survey.json"
    generator = object.__new__(SurveyGenerator)
    generator.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(
            save_path=str(markdown_path),
            save_json_path=str(json_path),
            topic="precision medicine",
            research_context={"input_fingerprint": "project-fingerprint"},
            subhypothesis_decomposition={"source": "automatic_qwen"},
            subhypothesis_retrieval={"schema_version": "subhypothesis_retrieval_execution_v1"},
            debug=False,
        )
    )
    generator.save_survey("Survey body", [])

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["subhypothesis_decomposition"] == {"source": "automatic_qwen"}
