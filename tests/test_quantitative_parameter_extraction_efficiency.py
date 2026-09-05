from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from src.agents.idea_agent.agent import base as agent_base
from src.agents.quantitative_modeling.model_synthesis import build_quantitative_model_llm_call
from src.agents.quantitative_modeling.parameter_contracts import (
    PARAMETER_DISCOVERY_SCHEMA_VERSION,
    model_blueprint_identity,
    normalize_model_blueprint,
)
from src.agents.quantitative_modeling.parameter_evidence.extraction import (
    PARAMETER_EVIDENCE_RESPONSE_SCHEMA,
    ParameterEvidenceExtractionError,
    _select_relevant_sections,
    _parse_response,
    extract_parameter_evidence_candidates,
)
from src.agents.quantitative_modeling.parameter_evidence.fulltext import fetch_open_access_fulltexts
from src.agents.quantitative_modeling.parameter_evidence.providers import ParameterEvidenceSettings
from src.agents.idea_agent.utils.core.chat_transport import normalize_responses_kwargs
from src.config import load_config
from src.llm.provider_registry import resolve_provider


def _blueprint() -> dict[str, object]:
    return normalize_model_blueprint(
        {
            "schema_version": "quantitative_model_blueprint_v1",
            "lineage": {
                "science_run_id": "run",
                "survey_run_id": "survey",
                "project_id": "project",
                "project_context_fingerprint": "context",
                "selected_direction_id": "direction",
                "quantitative_idea_id": "Q1",
                "version": 0,
                "parent_version": None,
                "created_from_artifact": "sidecar.json",
            },
            "title": "Decay",
            "scientific_question": "How fast does the state decay?",
            "model_scope": "One state",
            "symbolic_model_intent": "dx/dt=-kx",
            "permitted_system_types": ["ODE_IVP"],
            "parameter_requests": [
                {
                    "parameter_id": "k",
                    "mathir_symbol": "k",
                    "meaning": "decay rate",
                    "unit": "s^-1",
                    "dimension": "T^-1",
                    "role": "MATERIAL_PROPERTY",
                    "value_kind": "SCALAR",
                    "evidence_requirement": "USER_OR_LITERATURE",
                    "required_conditions": ["temperature_K"],
                    "retrieval_queries": ["measured decay rate"],
                }
            ],
            "symbolic_constraints": ["k > 0"],
            "revision_context": {},
        }
    )


def _source(path: Path) -> dict[str, object]:
    return {
        "document_id": "PFD-001",
        "path": str(path),
        "title": "Measured decay rate",
        "doi": "10.1000/example",
        "year": 2025,
        "discovery_sources": ["openalex"],
        "cross_validated": True,
        "parameter_request_ids": ["k"],
        "evidence_status": "EXTRACTED_FULLTEXT",
    }


def _response(quote: str) -> str:
    return (
        "<QUANTITATIVE_PARAMETER_EVIDENCE_JSON>"
        + json.dumps(
            {
                "candidates": [
                    {
                        "parameter_id": "k",
                        "mathir_symbol": "k",
                        "raw_value": "k = 2.0 s^-1",
                        "normalized_value": 2.0,
                        "normalized_unit": "s^-1",
                        "source_kind": "PRIMARY_MEASUREMENT",
                        "evidence_locator": {
                            "document_type": "TXT",
                            "section": "Results",
                            "table_or_figure": "",
                            "page": None,
                            "quoted_text": quote,
                        },
                        "conditions": {"temperature_K": 300.0},
                        "uncertainty": {},
                        "transformation": {"applied": False, "formula": ""},
                    }
                ]
            }
        )
        + "</QUANTITATIVE_PARAMETER_EVIDENCE_JSON>"
    )


def test_native_json_response_schema_and_plain_json_fallback_are_bounded() -> None:
    assert PARAMETER_EVIDENCE_RESPONSE_SCHEMA["properties"]["candidates"]["maxItems"] == 8
    assert _parse_response('{"candidates":[]}', allow_plain_json=True) == []
    with pytest.raises(ParameterEvidenceExtractionError):
        _parse_response('{"candidates":[]}', allow_plain_json=False)
    too_many = json.dumps({"candidates": [{"parameter_id": "k"}] * 3})
    with pytest.raises(ParameterEvidenceExtractionError, match="more than two"):
        _parse_response(too_many, allow_plain_json=True)


def test_responses_transport_maps_extraction_schema_to_text_format() -> None:
    normalized = normalize_responses_kwargs(
        {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "quantitative_parameter_evidence",
                    "strict": True,
                    "schema": PARAMETER_EVIDENCE_RESPONSE_SCHEMA,
                },
            }
        }
    )

    assert "response_format" not in normalized
    assert normalized["text"]["format"]["type"] == "json_schema"
    assert normalized["text"]["format"]["name"] == "quantitative_parameter_evidence"
    assert normalized["text"]["format"]["schema"] == PARAMETER_EVIDENCE_RESPONSE_SCHEMA


def test_extraction_callback_uses_dynamic_tokens_and_native_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_config("src/config/default.yaml")

    class FakeAgent:
        def __init__(self, config: object, provider_name: str | None = None) -> None:
            self.provider = resolve_provider(config, provider_name or "qwen")
            self.calls: list[dict[str, object]] = []

        def chat(self, _prompt: str, **kwargs: object) -> str:
            self.calls.append(kwargs)
            return '{"candidates": []}'

    monkeypatch.setattr(agent_base, "AgentBase", FakeAgent)
    callback = build_quantitative_model_llm_call(config=config, model="qwen3-max-2026-01-23")
    callback("targeted text", phase="parameter_extraction", parameter_count=1)
    agent = callback.agent

    assert agent.calls[0]["max_output_tokens"] == 768
    response_format = agent.calls[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True


def test_targeted_selection_keeps_parameter_page_and_adjacent_context() -> None:
    text, selection = _select_relevant_sections(
        blueprint=_blueprint(),
        source_document={"parameter_request_ids": ["k"]},
        pages=["Introduction\nNo model values.", "Results\nk = 2.0 s^-1 at 300 K.", "Appendix\nUnrelated details."],
        context_pages_before=1,
        context_pages_after=0,
        max_snippet_characters=1000,
    )

    assert selection["matched_parameter_ids"] == ["k"]
    assert selection["selected_pages"] == [1, 2]
    assert "[page=2]" in text
    assert "k = 2.0 s^-1" in text
    assert "[page=3]" not in text


def test_extraction_skips_llm_when_no_parameter_terms_match(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_text("This document contains only qualitative prose.", encoding="utf-8")
    calls: list[str] = []

    collection = extract_parameter_evidence_candidates(
        blueprint=_blueprint(),
        source_document=_source(path),
        llm_call=lambda prompt: calls.append(prompt),
    )

    assert collection["candidates"] == []
    assert collection["extraction"]["status"] == "SKIPPED_NO_PARAMETER_EVIDENCE"
    assert collection["extraction"]["skipped"] is True
    assert calls == []


def test_extraction_uses_targeted_prompt_and_parameter_phase(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    quote = "Results: k = 2.0 s^-1 at 300 K."
    path.write_text("Introduction\nUnrelated.\n" + quote, encoding="utf-8")
    calls: list[tuple[str, str]] = []

    def llm(prompt: str, *, phase: str) -> str:
        calls.append((prompt, phase))
        return _response(quote)

    collection = extract_parameter_evidence_candidates(
        blueprint=_blueprint(),
        source_document=_source(path),
        llm_call=llm,
        max_snippet_characters=1000,
    )

    assert collection["candidates"][0]["candidate_id"] == "PEC-Q1-k-001"
    assert calls[0][1] == "parameter_extraction"
    assert "Requested parameter subset:" in calls[0][0]
    assert "Results: k = 2.0 s^-1 at 300 K." in calls[0][0]
    assert "symbolic_model_intent" not in calls[0][0]


def test_extraction_reuses_section_and_llm_response_caches(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    quote = "Results: k = 2.0 s^-1 at 300 K."
    path.write_text(quote, encoding="utf-8")
    section_cache = tmp_path / "section_windows"
    response_cache = tmp_path / "llm_responses"
    calls = 0

    def llm(prompt: str, *, phase: str) -> str:
        nonlocal calls
        calls += 1
        assert phase == "parameter_extraction"
        return _response(quote)

    first = extract_parameter_evidence_candidates(
        blueprint=_blueprint(),
        source_document=_source(path),
        llm_call=llm,
        section_cache_directory=section_cache,
        llm_response_cache_directory=response_cache,
    )
    second = extract_parameter_evidence_candidates(
        blueprint=_blueprint(),
        source_document=_source(path),
        llm_call=lambda _prompt: (_ for _ in ()).throw(AssertionError("LLM cache was not used")),
        section_cache_directory=section_cache,
        llm_response_cache_directory=response_cache,
    )

    assert calls == 1
    assert first["candidates"] == second["candidates"]
    assert list(section_cache.glob("*.json"))
    assert list(response_cache.glob("*.json"))


def test_invalid_llm_cache_is_recomputed_once(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    quote = "Results: k = 2.0 s^-1 at 300 K."
    path.write_text(quote, encoding="utf-8")
    response_cache = tmp_path / "llm_responses"
    calls = 0

    def llm(_prompt: str, *, phase: str) -> str:
        nonlocal calls
        calls += 1
        assert phase == "parameter_extraction"
        return _response(quote)

    extract_parameter_evidence_candidates(
        blueprint=_blueprint(),
        source_document=_source(path),
        llm_call=llm,
        llm_response_cache_directory=response_cache,
    )
    cache_path = next(response_cache.glob("*.json"))
    cache_path.write_text(json.dumps({"response": "not-json"}), encoding="utf-8")

    collection = extract_parameter_evidence_candidates(
        blueprint=_blueprint(),
        source_document=_source(path),
        llm_call=llm,
        llm_response_cache_directory=response_cache,
    )

    assert calls == 2
    assert collection["candidates"][0]["normalized_value"] == 2.0


def test_fulltext_downloads_in_parallel_but_commits_input_order(tmp_path: Path) -> None:
    blueprint = _blueprint()
    discovery = {
        "schema_version": PARAMETER_DISCOVERY_SCHEMA_VERSION,
        "blueprint_identity": model_blueprint_identity(blueprint),
        "lineage": blueprint["lineage"],
        "papers": [
            {
                "paper_id": f"PD-{index:03d}",
                "title": f"Paper {index}",
                "doi": f"10.1000/{index}",
                "year": 2025,
                "discovery_sources": ["openalex"],
                "cross_validated": False,
                "parameter_request_ids": ["k"],
                "oa_candidates": [{"source": "openalex", "pdf_url": f"https://example.org/{index}.pdf"}],
            }
            for index in range(1, 4)
        ],
    }
    settings = ParameterEvidenceSettings(fulltext_workers=3, max_fulltext_documents_per_parameter=3)
    active = 0
    peak = 0
    lock = threading.Lock()

    class Response:
        status_code = 200
        headers = {"Content-Type": "application/pdf"}
        content = b"%PDF-parameter"

        def close(self) -> None:
            return None

    class Client:
        def get(self, url: str, **_kwargs: object) -> Response:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02 if url.endswith("/1.pdf") else 0.04)
            with lock:
                active -= 1
            return Response()

    manifest = fetch_open_access_fulltexts(
        blueprint=blueprint,
        discovery=discovery,
        output_directory=tmp_path / "fulltext",
        settings=settings,
        http_client=Client(),
    )

    assert 2 <= peak <= settings.fulltext_per_host_concurrency
    assert [document["title"] for document in manifest["documents"]] == ["Paper 1", "Paper 2", "Paper 3"]
    assert [document["document_id"] for document in manifest["documents"]] == ["PFD-001", "PFD-002", "PFD-003"]
