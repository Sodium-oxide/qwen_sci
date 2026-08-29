import json
from types import SimpleNamespace

from src.agents.survey_agent.modules.pe import (
    PAPER_RELATEDNESS_BASED_ON_TITLE_AND_ABSTRACT,
    SEED_PAPER_SELECTION,
)
from src.agents.survey_agent.modules.work_collector import WorkCollector
from src.cli import _build_root_parser
from src.pipeline.research_identity import (
    build_project_research_context,
    load_or_build_project_research_context,
    project_research_context_fingerprint,
    relatedness_cache_key,
    relevance_context_payload,
)


def test_context_cache_runs_identity_llm_only_once_for_same_inputs(tmp_path) -> None:
    calls: list[str] = []

    def llm_call(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(
            {
                "domain": "Machine Learning for Crop Disease Diagnosis",
                "research_domains": [
                    "Machine Learning",
                    "Agricultural And Biological Sciences",
                ],
                "primary_discipline": "computer_science",
                "secondary_disciplines": ["agricultural_biological_sciences"],
                "domain_confidence": 0.86,
                "evidence_spans": ["machine learning", "crop disease"],
                "core_entities": ["crop disease"],
                "retrieval_synonyms": ["plant disease classification"],
                "abbreviations": [],
                "exclusion_terms": ["model", "humanities-only crop history"],
                "operationalization": {
                    "normalized_objective": "Which machine-learning methods improve crop disease diagnosis across data and deployment conditions?",
                    "task_or_question": "Compare crop disease diagnosis methods.",
                    "research_object": "crop disease",
                    "outcomes_or_readouts": ["diagnostic performance"],
                    "data_or_deployment_context": ["field imagery"],
                    "baseline_requirements": ["classical vision baseline"],
                    "limitation_and_failure_conditions": ["distribution shift"],
                    "rewrite_reason": "The objective is broad.",
                },
            }
        )

    cache_path = tmp_path / "research_context.json"
    first = load_or_build_project_research_context(
        cache_path=cache_path,
        original_topic="machine learning for crop disease diagnosis",
        objective="Use AI for crop disease diagnosis",
        use_llm=True,
        llm_call=llm_call,
    )
    second = load_or_build_project_research_context(
        cache_path=cache_path,
        original_topic="machine learning for crop disease diagnosis",
        objective="Use AI for crop disease diagnosis",
        use_llm=True,
        llm_call=lambda _prompt: (_ for _ in ()).throw(AssertionError("cache miss")),
    )

    assert len(calls) == 2
    assert first["cache_status"] == "miss"
    assert second["cache_status"] == "hit"
    assert first["original_topic"] == second["original_topic"]
    assert first["primary_discipline"] == "computer_science"
    assert first["secondary_disciplines"] == ["agricultural_biological_sciences"]
    assert first["evidence_spans"] == ["machine learning", "crop disease"]
    assert "model" not in first["exclusion_terms"]
    assert first["recommended_sources"][0]["provider"] == "openalex"
    assert all(source["provider"] != "pubmed" for source in first["recommended_sources"])
    assert first["retrieval_plan"]["execution_policy"] == "limited_query_lanes"
    assert first["research_design_inventory"]["schema_version"] == "research_design_inventory_v1"
    assert len(first["research_design_inventory"]["design_basis"]) >= 3


def test_context_marks_unmapped_domains_for_human_confirmation() -> None:
    hss_context = build_project_research_context(
        original_topic="historical analysis of industrial policy",
        use_llm=False,
    )
    unknown_context = build_project_research_context(
        original_topic="optimization of resource allocation",
        use_llm=False,
    )

    assert hss_context["identity_status"] == "unresolved"
    assert hss_context["primary_discipline"] is None
    assert unknown_context["identity_status"] == "unresolved"
    assert unknown_context["primary_discipline"] is None
    assert hss_context["requires_human_confirmation"] is True
    assert unknown_context["requires_human_confirmation"] is True


def test_context_cache_without_design_inventory_is_rebuilt(tmp_path) -> None:
    cache_path = tmp_path / "research_context.json"
    context = load_or_build_project_research_context(
        cache_path=cache_path,
        original_topic="thermal stability of solid electrolytes",
        objective="Assess thermal stability of solid electrolytes under cycling conditions.",
        use_llm=False,
    )
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    cached.pop("research_design_inventory")
    cache_path.write_text(json.dumps(cached), encoding="utf-8")

    rebuilt = load_or_build_project_research_context(
        cache_path=cache_path,
        original_topic="thermal stability of solid electrolytes",
        objective="Assess thermal stability of solid electrolytes under cycling conditions.",
        use_llm=False,
    )

    assert context["cache_status"] == "miss"
    assert rebuilt["cache_status"] == "miss"
    assert rebuilt["research_design_inventory"]["design_basis"]


def test_design_inventory_llm_items_require_source_grounded_anchors() -> None:
    calls: list[str] = []

    def llm_call(prompt: str) -> dict:
        calls.append(prompt)
        if "Build a compact, domain-neutral research design inventory" in prompt:
            return {
                "design_basis": [
                    {
                        "kind": "research_object",
                        "statement": "The project studies solid electrolytes.",
                        "anchors": ["solid electrolytes"],
                        "evidence_spans": ["solid electrolytes"],
                    },
                    {
                        "kind": "outcome_or_construct",
                        "statement": "The project assesses thermal stability.",
                        "anchors": ["thermal stability"],
                        "evidence_spans": ["thermal stability"],
                    },
                    {
                        "kind": "condition_or_regime",
                        "statement": "The project includes cycling conditions.",
                        "anchors": ["cycling conditions"],
                        "evidence_spans": ["cycling conditions"],
                    },
                    {
                        "kind": "measurement",
                        "statement": "The project assesses stability under thermal conditions.",
                        "anchors": ["thermal stability"],
                        "evidence_spans": ["thermal stability"],
                    },
                ]
            }
        return {
            "domain": "Materials Science",
            "research_domains": ["Materials Science"],
            "primary_discipline": "materials_science",
            "evidence_spans": ["thermal stability", "solid electrolytes"],
            "core_entities": ["solid electrolytes"],
        }

    context = build_project_research_context(
        original_topic="thermal stability of solid electrolytes",
        objective="Assess thermal stability of solid electrolytes under cycling conditions.",
        use_llm=True,
        llm_call=llm_call,
    )
    inventory = context["research_design_inventory"]

    assert len(calls) == 2
    assert inventory["llm_used"] is True
    assert inventory["inventory_source"] == "llm_source_grounded_plus_project_declaration"
    llm_items = [
        item
        for item in inventory["design_basis"]
        if item["source"] == "llm_source_grounded"
    ]
    assert len(llm_items) == 4
    assert all(
        span.casefold() in "thermal stability of solid electrolytes assess thermal stability of solid electrolytes under cycling conditions."
        for item in llm_items
        for span in item["evidence_spans"]
    )


def test_operationalization_preserves_original_and_skips_specific_objective() -> None:
    broad_context = build_project_research_context(
        original_topic="Use AI to solve crop disease problems",
        use_llm=False,
    )
    specific_objective = (
        "How does solid electrolyte composition affect battery cycle life under thermal "
        "stress compared with a fixed baseline composition?"
    )
    specific_context = build_project_research_context(
        original_topic=specific_objective,
        objective=specific_objective,
        use_llm=False,
    )

    broad_operationalization = broad_context["academic_operationalization"]
    specific_operationalization = specific_context["academic_operationalization"]
    assert broad_operationalization["applied"] is True
    assert broad_operationalization["mode"] == "survey_scope"
    assert broad_operationalization["original_objective"] == "Use AI to solve crop disease problems"
    assert specific_operationalization["applied"] is False
    assert specific_operationalization["normalized_objective"] == specific_objective


def test_relevance_contract_is_bounded_and_cache_keys_are_project_specific() -> None:
    context = build_project_research_context(
        original_topic="machine learning for crop disease diagnosis",
        use_llm=False,
    )
    payload = relevance_context_payload(context)
    different_context = {**context, "input_fingerprint": "different-project"}

    assert payload["original_topic"] == "machine learning for crop disease diagnosis"
    assert "taxonomy_resolution" not in payload
    assert relatedness_cache_key(context, "W1", "W2") != relatedness_cache_key(
        different_context,
        "W1",
        "W2",
    )
    assert project_research_context_fingerprint(
        original_topic="crop disease diagnosis",
        objective="visual diagnosis",
    ) != project_research_context_fingerprint(
        original_topic="crop disease diagnosis",
        objective="multimodal early warning",
    )


def test_llm_evidence_spans_preserve_the_actual_source_text() -> None:
    context = build_project_research_context(
        original_topic="Machine learning for crop disease diagnosis",
        use_llm=True,
        llm_call=lambda _prompt: {
            "domain": "Machine Learning for Crop Disease Diagnosis",
            "research_domains": ["Machine Learning", "Agricultural And Biological Sciences"],
            "primary_discipline": "computer_science",
            "secondary_disciplines": ["agricultural_biological_sciences"],
            "evidence_spans": ["machine-learning", "machine learning", "crop disease"],
        },
    )

    assert context["evidence_spans"] == ["Machine learning", "crop disease"]


def test_v8_style_project_domain_contract_is_primary_and_v1_cache_is_not_used(tmp_path) -> None:
    calls: list[str] = []
    cache_path = tmp_path / "research_context.json"
    topic = (
        "Develop personalized medicine from patient genetics with artificial intelligence "
        "and machine learning for pharmacology and biomedical engineering."
    )
    title = "Personalized medicine platform"
    declared_domain = "Biomedical Engineering and Pharmacology"
    objective = (
        "Assess personalized medicine using patient genetics, artificial intelligence, "
        "machine learning, pharmacology, and biomedical engineering."
    )
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": "project_research_context_v1",
                "input_fingerprint": project_research_context_fingerprint(
                    original_topic=topic,
                    title=title,
                    declared_domain=declared_domain,
                    objective=objective,
                ),
                "primary_discipline": "medicine",
            }
        ),
        encoding="utf-8",
    )

    def llm_call(_prompt: str) -> str:
        calls.append(_prompt)
        return json.dumps(
            {
                "domain": "Personalized Medicine",
                "research_domains": [
                    "Genetics Genomics And Heredity",
                    "Artificial Intelligence",
                    "Pharmacology And Pharmacodynamics",
                    "Machine Learning",
                    "Biomedical Engineering",
                ],
                "primary_discipline": "medicine",
                "domain_confidence": 0.93,
                "evidence_spans": [
                    "personalized medicine",
                    "patient genetics",
                    "artificial intelligence",
                    "machine learning",
                    "pharmacology",
                    "biomedical engineering",
                ],
                "core_entities": ["patient genetics"],
                "retrieval_synonyms": ["precision medicine"],
            }
        )

    context = load_or_build_project_research_context(
        cache_path=cache_path,
        original_topic=topic,
        title=title,
        declared_domain=declared_domain,
        objective=objective,
        use_llm=True,
        llm_call=llm_call,
    )

    assert len(calls) == 2
    assert context["schema_version"] == "project_research_context_v3"
    assert context["cache_status"] == "miss"
    assert context["declared_domain"] == "Biomedical Engineering and Pharmacology"
    assert context["domain"] == "Personalized Medicine"
    assert [item["label"] for item in context["research_domains"]] == [
        "Genetics Genomics And Heredity",
        "Artificial Intelligence",
        "Pharmacology And Pharmacodynamics",
        "Machine Learning",
        "Biomedical Engineering",
    ]
    assert context["primary_discipline"] == "medicine"
    assert context["domain_resolution_source"] == "llm_primary_catalog_validated"
    assert context["requires_human_confirmation"] is True
    assert context["research_design_inventory"]["schema_version"] == "research_design_inventory_v1"


def test_project_created_event_and_early_context_artifact_are_published_once(
    tmp_path,
) -> None:
    class Logger:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def info(self, message, *_args, **_kwargs) -> None:
            self.messages.append(str(message))

    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(
            survey_run_id="20260822-170051-000001",
            base_dir=str(tmp_path),
            research_context={},
            project_context_artifact_path="",
        )
    )
    logger = Logger()
    collector.logger = logger
    collector._project_created_event_emitted = False
    context = build_project_research_context(
        original_topic="Personalized medicine using genomics and pharmacology",
        declared_domain="Biomedical Engineering and Pharmacology",
        use_llm=True,
        llm_call=lambda _prompt: {
            "domain": "Personalized Medicine",
            "research_domains": [
                "Genetics Genomics And Heredity",
                "Pharmacology And Pharmacodynamics",
                "Biomedical Engineering",
            ],
            "evidence_spans": ["Personalized medicine", "genomics", "pharmacology"],
        },
    )

    collector._publish_project_context(context)
    collector._publish_project_context(context)

    artifact_path = tmp_path / "project_context.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    events = [message for message in logger.messages if "project_created" in message]
    assert events == [
        "[SCIENCE] project_created: "
        "project_id=sci_20260822_170051_000001, "
        "declared_domain=Biomedical Engineering and Pharmacology, "
        "domain=Personalized Medicine, "
        "research_domains=Genetics Genomics And Heredity|Pharmacology And Pharmacodynamics|Biomedical Engineering, "
        "domain_resolution_source=llm_primary_catalog_validated, "
        "requires_human_confirmation=True"
    ]
    assert artifact["project_id"] == "sci_20260822_170051_000001"
    assert artifact["domain"] == "Personalized Medicine"
    assert collector.config.BasicInfo.project_context_artifact_path == str(artifact_path)


def test_survey_cli_accepts_project_domain_confirmation_inputs() -> None:
    args = _build_root_parser().parse_args(
        [
            "survey",
            "--topic",
            "personalized medicine",
            "--declared-domain",
            "Biomedical Engineering and Pharmacology",
            "--research-title",
            "Patient-specific therapeutics",
            "--research-objective",
            "Assess personalized medicine evidence",
            "--research-brief",
            "Use patient genomics and pharmacology evidence.",
        ]
    )

    assert args.declared_domain == "Biomedical Engineering and Pharmacology"
    assert args.research_title == "Patient-specific therapeutics"
    assert args.research_objective == "Assess personalized medicine evidence"
    assert args.research_brief == "Use patient genomics and pharmacology evidence."


def test_seed_and_relatedness_prompts_require_project_context_anchors() -> None:
    research_context = json.dumps(
        {
            "primary_discipline": "agricultural_biological_sciences",
            "include_anchors": ["crop disease"],
            "exclude_anchors": ["crop history"],
        }
    )
    seed_prompt = SEED_PAPER_SELECTION.format(
        topic="AI for crop disease",
        research_context=research_context,
        title="Crop disease classification",
        abstract="A field-imaging study.",
    )
    relatedness_prompt = PAPER_RELATEDNESS_BASED_ON_TITLE_AND_ABSTRACT.format(
        research_context=research_context,
        seed_title="Crop disease classification",
        seed_abstract="Field images.",
        candidate_title="Vision model for disease diagnosis",
        candidate_abstract="Crop disease benchmark.",
    )

    assert "Project research context" in seed_prompt
    assert "matched_anchors" in seed_prompt
    assert "Generic overlap" in seed_prompt
    assert 'If identity_status is "unresolved"' in seed_prompt
    assert "Project research context" in relatedness_prompt
    assert "Pairwise similarity alone is insufficient" in relatedness_prompt
    assert 'If identity_status is "unresolved"' in relatedness_prompt
