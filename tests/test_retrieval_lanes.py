import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from src.agents.survey_agent.modules.work_collector import WorkCollector
from src.pipeline.research_identity import build_project_research_context
from src.pipeline.retrieval_lanes import (
    build_subhypothesis_retrieval_plan,
    subhypothesis_decomposition_context_payload,
)


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass


class _CapturingLogger:
    def __init__(self):
        self.messages = []

    def info(self, message, *args, **_kwargs):
        self.messages.append(message % args if args else message)

    def warning(self, *_args, **_kwargs):
        pass


def _crop_comparative_contract(
    project: dict,
    *,
    identifier: str = "crop_field",
    question: str = "Under which field conditions do image classifiers improve crop disease diagnosis versus standard CNN baselines?",
) -> dict:
    basis_ids = [item["id"] for item in project["research_design_inventory"]["design_basis"][:3]]
    return {
        "schema_version": "science_subhypothesis_v2",
        "sub_hypothesis_id": identifier,
        "title": "Field classifier comparison",
        "question": question,
        "question_kind": "COMPARATIVE_EVALUATION",
        "scientific_scope": {
            "research_object": ["crop disease diagnosis"],
            "comparison_frame": ["standard CNN baselines"],
            "condition_or_regime": ["field conditions"],
            "outcome_or_construct": ["diagnosis accuracy"],
        },
        "required_slots": [
            "candidate",
            "comparator",
            "comparison_condition",
            "comparable_endpoint",
            "mechanism_pathway",
            "boundary_case",
            "background_framework",
        ],
        "slot_definitions": {
            "candidate": {"meaning": "classifier being evaluated", "retrieval_concepts": ["image classifiers"], "minimum_evidence": "reported evaluation", "admission_rule": "evaluates the candidate"},
            "comparator": {"meaning": "comparison baseline", "retrieval_concepts": ["standard CNN"], "minimum_evidence": "explicit comparator", "admission_rule": "names a baseline"},
            "comparison_condition": {"meaning": "shared evaluation regime", "retrieval_concepts": ["field conditions"], "minimum_evidence": "field evaluation", "admission_rule": "reports the regime"},
            "comparable_endpoint": {"meaning": "shared endpoint", "retrieval_concepts": ["diagnosis accuracy"], "minimum_evidence": "quantitative endpoint", "admission_rule": "reports accuracy"},
            "mechanism_pathway": {"meaning": "explanatory route", "retrieval_concepts": ["domain adaptation"], "minimum_evidence": "mechanistic analysis", "admission_rule": "tests the route"},
            "boundary_case": {"meaning": "limiting regime", "retrieval_concepts": ["domain shift"], "minimum_evidence": "boundary analysis", "admission_rule": "reports a limitation"},
            "background_framework": {"meaning": "field synthesis", "retrieval_concepts": ["plant pathology review"], "minimum_evidence": "scholarly synthesis", "admission_rule": "maps the field"},
        },
        "research_role": "PRIMARY_QUESTION",
        "challenge_target": "the claim that image classifiers improve diagnosis under all field conditions",
        "design_basis_ids": basis_ids,
    }


def test_project_lanes_keep_broad_recall_and_gate_native_filters() -> None:
    materials = build_project_research_context(
        original_topic="machine learning for materials discovery",
        declared_domain="materials science",
        use_llm=False,
    )
    lanes = materials["retrieval_plan"]["query_lanes"]

    broad = lanes[0]
    assert broad["lane"] == "broad_anchor"
    assert broad["provider"] == "openalex"
    assert broad["hard_filter_applied"] is False
    assert broad["provider_filter"] == {}
    assert any(
        lane["provider"] == "openalex" and lane["hard_filter_applied"]
        for lane in lanes
    )
    assert any(
        lane["provider"] == "arxiv" and lane["hard_filter_applied"]
        for lane in lanes
    )

    parent_only = build_project_research_context(
        original_topic="fault diagnosis in electrical engineering systems",
        declared_domain="electrical engineering",
        use_llm=False,
    )
    parent_lanes = parent_only["retrieval_plan"]["query_lanes"]
    assert [lane["lane"] for lane in parent_lanes] == ["broad_anchor"]
    assert all(lane["hard_filter_applied"] is False for lane in parent_lanes)


def test_sh_context_inherits_project_background_and_rejects_legacy_overrides() -> None:
    project = build_project_research_context(
        original_topic="machine learning for crop disease diagnosis",
        declared_domain="agriculture",
        objective="Compare image models for crop disease diagnosis under field conditions",
        use_llm=False,
    )
    decomposition_payload = subhypothesis_decomposition_context_payload(project)
    plan = build_subhypothesis_retrieval_plan(
        project,
        [
            _crop_comparative_contract(
                project,
                identifier="benchmark",
                question="Which field-image benchmark protocols compare crop disease classifiers under field conditions?",
            ),
            {
                "id": "legacy_override",
                "question": "How should uncertainty in crop disease classifier evaluation be quantified under field conditions?",
                "discipline_override": "computer science",
            },
        ],
    )
    benchmark, legacy_override = plan["subhypotheses"]

    assert decomposition_payload["primary_discipline"] == project["primary_discipline"]
    assert decomposition_payload["research_design_inventory"]["design_basis"]
    assert benchmark["inherited_project_fingerprint"] == project["input_fingerprint"]
    assert (
        benchmark["effective_taxonomy_resolution"]["primary_discipline"]
        == project["taxonomy_resolution"]["primary_discipline"]
    )
    assert benchmark["effective_taxonomy_resolution"]["subhypothesis_taxonomy"]["source"] == (
        "project_domain_plus_subhypothesis"
    )
    assert len(benchmark["slot_recovery_tasks"]) == len(benchmark["required_slots"])
    assert {
        task["slot_name"] for task in benchmark["slot_recovery_tasks"]
    } == set(benchmark["required_slots"])
    assert legacy_override["validation"]["valid"] is False
    assert "unsupported_field:discipline_override" in legacy_override["validation"]["errors"]
    assert legacy_override["slot_recovery_tasks"] == []


def test_sh_contract_validates_scientific_fields_and_compiles_one_task_per_required_slot() -> None:
    project = build_project_research_context(
        original_topic="machine learning for crop disease diagnosis",
        declared_domain="agriculture",
        objective="Compare image models for crop disease diagnosis under field conditions",
        use_llm=False,
    )
    plan = build_subhypothesis_retrieval_plan(
        project,
        [
            {
                **_crop_comparative_contract(project, identifier="field_diagnosis"),
                "allowed_evidence_scope": {
                    "date_range": "2019-2026",
                    "publication_types": ["journal article", "conference paper"],
                },
                "excluded_evidence_scope": {"contexts": ["human medical imaging"]},
            },
        ],
    )
    sh = plan["subhypotheses"][0]
    tasks = {task["slot_name"]: task for task in sh["slot_recovery_tasks"]}

    assert sh["schema_version"] == "science_subhypothesis_v2"
    assert sh["inherited_project_fingerprint"] == project["input_fingerprint"]
    assert sh["question_kind"] == "COMPARATIVE_EVALUATION"
    assert sh["research_role"] == "PRIMARY_QUESTION"
    assert sh["validation"]["valid"] is True
    assert sh["design_basis_ids"] == ["DB1", "DB2", "DB3"]
    assert sh["retrieval_strategy"] == "slot_driven_required_slot_recovery"
    assert sh["allowed_evidence_scope"]["date_range"] == "2019-2026"
    assert sh["excluded_evidence_scope"]["contexts"] == ["human medical imaging"]

    assert set(tasks) == set(sh["required_slots"])
    assert "image classifiers" in tasks["candidate"]["query"]
    assert "domain adaptation" in tasks["mechanism_pathway"]["query"]
    assert "domain shift" in tasks["boundary_case"]["query"]
    assert "plant pathology review" in tasks["background_framework"]["query"]
    assert tasks["candidate"]["expected_evidence_role"] == "COMPARATIVE_OR_MEASUREMENT_EVIDENCE"
    assert tasks["mechanism_pathway"]["expected_evidence_role"] == "MECHANISTIC_EVIDENCE"
    assert tasks["boundary_case"]["expected_evidence_role"] == "LIMITING_OR_CHALLENGING_EVIDENCE"
    assert tasks["background_framework"]["expected_evidence_role"] == "BACKGROUND_CONTEXT"
    assert all(
        lane["slot_recovery_task_id"] == task["task_id"]
        for task in tasks.values()
        for lane in task["retrieval_plan"]["query_lanes"]
    )
    assert all(
        any(
            lane["lane"] == "broad_anchor" and not lane["hard_filter_applied"]
            for lane in task["retrieval_plan"]["query_lanes"]
        )
        for task in tasks.values()
    )


def test_sh_slot_lanes_expand_exact_openalex_filter_from_sh_semantic_scope() -> None:
    project = build_project_research_context(
        original_topic="grid-scale energy storage",
        declared_domain="energy",
        objective="Compare electrochemical storage designs for capacity retention and safety.",
        use_llm=False,
    )
    contract = _crop_comparative_contract(
        project,
        identifier="battery_mechanism",
        question=(
            "How do sulfur hosts and electrolyte formulations alter lithium-ion cell "
            "capacity retention under thermal-abuse testing?"
        ),
    )
    contract["scientific_scope"] = {
        "research_object": ["lithium-ion cells"],
        "intervention_or_input": ["sulfur host", "electrolyte formulation"],
        "comparison_frame": ["baseline lithium-ion cell designs"],
        "condition_or_regime": ["thermal-abuse testing"],
        "outcome_or_construct": ["capacity retention"],
    }
    contract["slot_definitions"]["candidate"]["retrieval_concepts"] = [
        "operando spectroscopy",
        "electrochemical impedance spectroscopy",
        "electrolyte formulation",
    ]

    sh = build_subhypothesis_retrieval_plan(project, [contract])["subhypotheses"][0]
    candidate_task = next(
        task for task in sh["slot_recovery_tasks"] if task["slot_name"] == "candidate"
    )
    exact_primary_lane = next(
        lane
        for lane in candidate_task["retrieval_plan"]["query_lanes"]
        if lane["lane"] == "exact_primary_discipline"
    )
    adjacent_precision_lane = next(
        lane
        for lane in candidate_task["retrieval_plan"]["query_lanes"]
        if lane["lane"] == "adjacent_precision"
    )

    assert exact_primary_lane["provider_filter"]["filter"] == "primary_topic.field.id:21"
    assert exact_primary_lane["discipline_filter_policy"] == "exact_primary"
    assert exact_primary_lane["execution_phase"] == "initial"
    assert adjacent_precision_lane["provider_filter"]["filter"] == "primary_topic.field.id:21|16|25"
    assert adjacent_precision_lane["discipline_filter_policy"] == "adjacent_precision"
    assert adjacent_precision_lane["execution_phase"] == "relaxed"
    assert any(
        lane["lane"] == "broad_anchor" and lane["provider_filter"] == {}
        for lane in candidate_task["retrieval_plan"]["query_lanes"]
    )
    assert candidate_task["effective_taxonomy_resolution"]["subhypothesis_taxonomy"][
        "expanded"
    ] is True


def test_overloaded_slot_compiles_short_alternative_query_variants_without_joint_requirements() -> None:
    project = build_project_research_context(
        original_topic="grid-scale lithium-ion energy storage",
        declared_domain="energy",
        objective="Assess degradation, safety, and material-design evidence for lithium-ion storage.",
        use_llm=False,
    )
    contract = _crop_comparative_contract(
        project,
        identifier="battery_variants",
        question=(
            "Which observations distinguish battery degradation mechanisms and design "
            "effects in lithium-ion cells?"
        ),
    )
    contract["scientific_scope"] = {
        "research_object": ["lithium-ion cells"],
        "comparison_frame": ["baseline lithium-ion cell designs"],
        "intervention_or_input": ["sulfur host", "low-cobalt cathode", "electrolyte formulation"],
        "outcome_or_construct": ["capacity retention"],
    }
    contract["slot_definitions"]["candidate"].update(
        {
            "meaning": "Observations that discriminate degradation mechanisms or design effects.",
            "retrieval_concepts": [
                "operando spectroscopy",
                "electrochemical impedance spectroscopy",
                "post-mortem electrode analysis",
                "thermal abuse testing",
                "sulfur host",
                "low-cobalt cathode",
                "electrolyte formulation",
                "capacity retention",
            ],
            "retrieval_query_variants": [
                {
                    "variant_id": "baseline_observation",
                    "purpose": "broad empirical recall",
                    "query_terms": [
                        "lithium-ion battery",
                        "capacity retention",
                        "degradation",
                    ],
                    "preferred_disciplines": ["energy", "materials_science"],
                },
                {
                    "variant_id": "operando_mechanism",
                    "purpose": "mechanistic observation",
                    "query_terms": [
                        "operando spectroscopy",
                        "lithium-ion electrode",
                        "degradation",
                    ],
                    "preferred_disciplines": ["materials_science", "chemistry"],
                },
                {
                    "variant_id": "impedance_kinetics",
                    "purpose": "transport or interfacial observation",
                    "query_terms": [
                        "electrochemical impedance spectroscopy",
                        "lithium-ion cell",
                        "ion ransport rate",
                    ],
                    "preferred_disciplines": ["materials_science", "energy"],
                },
                {
                    "variant_id": "postmortem_material_change",
                    "purpose": "material-change observation",
                    "query_terms": [
                        "post-mortem electrode analysis",
                        "lithium-ion cathode",
                        "degradation",
                    ],
                    "preferred_disciplines": ["materials_science", "chemistry"],
                },
                {
                    "variant_id": "safety_boundary",
                    "purpose": "safety or boundary evidence",
                    "query_terms": [
                        "thermal abuse testing",
                        "lithium-ion cells",
                        "electrolyte",
                    ],
                    "preferred_disciplines": ["energy", "engineering"],
                },
            ],
        }
    )

    sh = build_subhypothesis_retrieval_plan(project, [contract])["subhypotheses"][0]
    task = next(item for item in sh["slot_recovery_tasks"] if item["slot_name"] == "candidate")
    variants = task["query_variants"]
    lanes = task["retrieval_plan"]["query_lanes"]
    operando_precision = next(
        lane
        for lane in lanes
        if lane["query_variant_id"] == "operando_mechanism"
        and lane["lane"] == "adjacent_precision"
    )
    impedance_variant = next(
        variant for variant in variants if variant["variant_id"] == "impedance_kinetics"
    )

    assert len(variants) == 5
    assert all(2 <= len(variant["query_terms"]) <= 6 for variant in variants)
    assert all(
        any(
            lane["lane"] == "broad_anchor" and lane["provider_filter"] == {}
            for lane in lanes
            if lane["query_variant_id"] == variant["variant_id"]
        )
        for variant in variants
    )
    assert operando_precision["provider_filter"]["filter"] == "primary_topic.field.id:21|25|16"
    assert operando_precision["discipline_filter_policy"] == "adjacent_precision"
    assert impedance_variant["query_terms"][-1] == "ion transport rate"
    assert any(
        warning.startswith("canonicalized_common_typo:ion ransport rate")
        for warning in impedance_variant["query_quality_warnings"]
    )
    assert not any(
        all(
            term in variant["query"].casefold()
            for term in ("operando", "thermal abuse", "sulfur host", "low-cobalt")
        )
        for variant in variants
    )


def test_sh_contract_rejects_legacy_fields_and_short_non_question_input() -> None:
    project = build_project_research_context(
        original_topic="materials discovery",
        declared_domain="materials science",
        use_llm=False,
    )
    sh = build_subhypothesis_retrieval_plan(
        project,
        [{"id": "too_short", "question": "Review", "evidence_mode": "narrative"}],
    )["subhypotheses"][0]

    assert sh["validation"]["valid"] is False
    assert "unsupported_field:evidence_mode" in sh["validation"]["errors"]
    assert "unsupported_field:id" in sh["validation"]["errors"]
    assert "invalid_schema_version" in sh["validation"]["errors"]
    assert "question_not_independently_answerable" in sh["validation"]["errors"]


def test_sh_contract_rejects_design_basis_ids_outside_project_inventory() -> None:
    project = build_project_research_context(
        original_topic="machine learning for crop disease diagnosis",
        declared_domain="agriculture",
        use_llm=False,
    )
    contract = _crop_comparative_contract(project)
    contract["design_basis_ids"] = ["DB999"]

    sh = build_subhypothesis_retrieval_plan(project, [contract])["subhypotheses"][0]

    assert sh["validation"]["valid"] is False
    assert "unknown_design_basis_id:DB999" in sh["validation"]["errors"]
    assert sh["slot_recovery_tasks"] == []


def test_sh_contract_rejects_a_design_inventory_from_another_project() -> None:
    project = build_project_research_context(
        original_topic="machine learning for crop disease diagnosis",
        declared_domain="agriculture",
        use_llm=False,
    )
    unrelated_project = build_project_research_context(
        original_topic="adaptive materials under thermal cycling",
        declared_domain="materials science",
        use_llm=False,
    )
    stale_context = {
        **project,
        "research_design_inventory": unrelated_project["research_design_inventory"],
    }

    sh = build_subhypothesis_retrieval_plan(
        stale_context,
        [_crop_comparative_contract(project)],
    )["subhypotheses"][0]

    assert sh["validation"]["valid"] is False
    assert any(
        error.startswith("invalid_design_inventory:Research design inventory fingerprint")
        for error in sh["validation"]["errors"]
    )
    assert sh["slot_recovery_tasks"] == []


def test_work_collector_emits_one_auditable_event_for_each_compiled_subhypothesis() -> None:
    context = build_project_research_context(
        original_topic="machine learning for crop disease diagnosis",
        declared_domain="agriculture",
        use_llm=False,
    )
    logger = _CapturingLogger()
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(
            subhypotheses=[_crop_comparative_contract(context)],
            survey_run_id="sci_test",
        )
    )
    collector.logger = logger
    collector.get_project_research_context = lambda _topic: context

    collector._build_configured_subhypothesis_plan(context["original_topic"])
    collector._build_configured_subhypothesis_plan(context["original_topic"])

    science_events = [
        message
        for message in logger.messages
        if message.startswith("[SCIENCE] subhypothesis_declared:")
    ]
    assert len(science_events) == 1
    assert "project_id=sci_sci_test" in science_events[0]
    assert "sub_hypothesis_id=crop_field" in science_events[0]
    assert "summary=Under which field conditions do image classifiers improve crop disease diagnosis versus standard CNN baselines?" in science_events[0]
    assert "question_kind=COMPARATIVE_EVALUATION" in science_events[0]
    assert "slot_recovery_task_count=7" in science_events[0]


def test_sh_retrieval_logs_the_exact_query_and_native_filter() -> None:
    context = build_project_research_context(
        original_topic="machine learning for crop disease diagnosis",
        declared_domain="agriculture",
        use_llm=False,
    )
    subhypothesis = build_subhypothesis_retrieval_plan(
        context,
        [_crop_comparative_contract(context)],
    )["subhypotheses"][0]
    logger = _CapturingLogger()
    collector = object.__new__(WorkCollector)
    collector.logger = logger
    collector._execute_query_lane = lambda _lane: []

    collector._discover_subhypothesis_candidates([subhypothesis])

    candidate_log = next(
        message
        for message in logger.messages
        if "slot candidate task crop_field.candidate variant=baseline_observation lane "
        "crop_field.candidate.baseline_observation.exact_primary_discipline" in message
        and "returned 0 candidates" in message
    )
    assert "provider=openalex" in candidate_log
    assert "discipline_filter_policy=exact_primary" in candidate_log
    assert "native_filter=primary_topic.field.id:11" in candidate_log
    assert "query=crop disease diagnosis diagnosis accuracy image classifiers" in candidate_log
    assert "returned 0 candidates." in candidate_log


def _cached_sh_retrieval_collector(tmp_path):
    collector = object.__new__(WorkCollector)
    collector.cache_path = str(tmp_path)
    collector.config = SimpleNamespace(
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                sh_retrieval_cache_enabled=True,
                sh_retrieval_cache_success_ttl_seconds=3600,
                sh_retrieval_cache_empty_ttl_seconds=60,
                refresh_sh_retrieval_cache=False,
                invalidate_sh_retrieval_cache=False,
            )
        )
    )
    collector.logger = _CapturingLogger()
    return collector


def _cached_lane(**overrides):
    lane = {
        "lane_id": "SH1.candidate.baseline.broad_anchor",
        "lane": "broad_anchor",
        "provider": "openalex",
        "query": "lithium-ion battery capacity retention",
        "sub_hypothesis_id": "SH1",
        "slot_name": "candidate",
        "slot_recovery_task_id": "SH1.candidate",
        "query_variant_id": "baseline_observation",
        "discipline_filter_policy": "broad",
        "provider_filter": {},
    }
    lane.update(overrides)
    return lane


def test_sh_retrieval_lane_cache_reuses_normalized_provider_results(tmp_path) -> None:
    collector = _cached_sh_retrieval_collector(tmp_path)
    calls = 0

    def execute_lane(_lane):
        nonlocal calls
        calls += 1
        return [{"paperId": "W1", "title": "Original provider result"}]

    collector._execute_query_lane = execute_lane
    lane = _cached_lane()

    first_lane, first_papers = collector._execute_slot_recovery_lane(lane)
    first_papers[0]["title"] = "Mutated by later local processing"
    second_lane, second_papers = collector._execute_slot_recovery_lane(lane)

    assert calls == 1
    assert first_lane["retrieval_cache"]["status"] == "miss"
    assert second_lane["retrieval_cache"]["status"] == "hit"
    assert second_lane["retrieval_cache"]["network_request_made"] is False
    assert second_papers == [{"paperId": "W1", "title": "Original provider result"}]

    merged = collector._merge_retrieval_candidates([(second_lane, second_papers)])
    provenance = merged[0]["retrieval_provenance"][0]
    assert provenance["retrieval_cache"]["status"] == "hit"
    assert provenance["retrieval_cache"]["network_request_made"] is False


def test_sh_retrieval_lane_cache_key_keeps_native_filters_separate(tmp_path) -> None:
    collector = _cached_sh_retrieval_collector(tmp_path)
    calls = []

    def execute_lane(lane):
        calls.append(lane["provider_filter"].get("filter", "none"))
        return [{"paperId": f"W{len(calls)}", "title": lane["query"]}]

    collector._execute_query_lane = execute_lane
    broad = _cached_lane()
    exact = _cached_lane(
        lane_id="SH1.candidate.baseline.exact_primary_discipline",
        hard_filter_applied=True,
        discipline_filter_policy="exact_primary",
        provider_filter={
            "applied": True,
            "coverage": "exact",
            "policy": "hard_filter",
            "filter": "primary_topic.field.id:21",
            "resolved_field_ids": ["21"],
        },
    )

    collector._execute_slot_recovery_lane(broad)
    collector._execute_slot_recovery_lane(exact)
    _cached_exact_lane, _cached_exact_papers = collector._execute_slot_recovery_lane(exact)

    assert calls == ["none", "primary_topic.field.id:21"]
    assert _cached_exact_lane["retrieval_cache"]["status"] == "hit"


def test_sh_retrieval_lane_cache_short_caches_completed_empty_result(tmp_path) -> None:
    collector = _cached_sh_retrieval_collector(tmp_path)
    calls = 0

    def execute_lane(_lane):
        nonlocal calls
        calls += 1
        return []

    collector._execute_query_lane = execute_lane

    first_lane, first_papers = collector._execute_slot_recovery_lane(_cached_lane())
    second_lane, second_papers = collector._execute_slot_recovery_lane(_cached_lane())

    assert calls == 1
    assert first_papers == second_papers == []
    assert first_lane["retrieval_cache"]["state"] == "empty"
    assert second_lane["retrieval_cache"]["status"] == "hit"
    assert second_lane["retrieval_cache"]["state"] == "empty"


def test_sh_retrieval_lane_cache_refreshes_once_then_reuses_the_fresh_result(tmp_path) -> None:
    collector = _cached_sh_retrieval_collector(tmp_path)
    calls = 0

    def execute_lane(_lane):
        nonlocal calls
        calls += 1
        return [{"paperId": "W1", "title": f"Provider result {calls}"}]

    collector._execute_query_lane = execute_lane
    lane = _cached_lane()
    collector._execute_slot_recovery_lane(lane)
    collector.config.ModuleInfo.WorkCollector.refresh_sh_retrieval_cache = True

    refreshed_lane, refreshed_papers = collector._execute_slot_recovery_lane(lane)
    reused_lane, reused_papers = collector._execute_slot_recovery_lane(lane)

    assert calls == 2
    assert refreshed_lane["retrieval_cache"]["status"] == "refresh"
    assert refreshed_papers[0]["title"] == "Provider result 2"
    assert reused_lane["retrieval_cache"]["status"] == "hit"
    assert reused_papers == refreshed_papers


def test_sh_retrieval_lane_cache_does_not_turn_provider_failure_into_empty_result(tmp_path) -> None:
    class _FailedOpenAlex:
        def __init__(self):
            self.calls = 0

        def search_papers_with_status(self, *_args, **_kwargs):
            self.calls += 1
            return [], False

    openalex = _FailedOpenAlex()
    collector = _cached_sh_retrieval_collector(tmp_path)
    collector.data_manager = SimpleNamespace(openalex_api=openalex)

    first_lane, _first_papers = collector._execute_slot_recovery_lane(_cached_lane())
    second_lane, _second_papers = collector._execute_slot_recovery_lane(_cached_lane())

    assert openalex.calls == 2
    assert first_lane["retrieval_cache"]["status"] == "not_cached_failure"
    assert second_lane["retrieval_cache"]["status"] == "not_cached_failure"


def test_sh_retrieval_lane_cache_single_flight_coalesces_identical_concurrent_lanes(tmp_path) -> None:
    collector = _cached_sh_retrieval_collector(tmp_path)
    calls = 0
    call_lock = threading.Lock()

    def execute_lane(_lane):
        nonlocal calls
        with call_lock:
            calls += 1
        time.sleep(0.05)
        return [{"paperId": "W1", "title": "Shared result"}]

    collector._execute_query_lane = execute_lane
    lane = _cached_lane()
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda _index: collector._execute_slot_recovery_lane(lane),
                range(2),
            )
        )

    assert calls == 1
    assert {outcome[0]["retrieval_cache"]["status"] for outcome in outcomes} == {
        "miss",
        "hit",
    }


def test_zero_exact_precision_lane_does_not_make_a_slot_empty_or_trigger_fallback() -> None:
    broad_papers = [
        {"paperId": "W1", "title": "Broad lithium-ion observation"},
        {"paperId": "W2", "title": "Broad electrode observation"},
    ]

    class _SemanticScholar:
        def search_papers(self, **_kwargs):
            raise AssertionError("fallback must not run when a broad lane returned candidates")

    task = {
        "task_id": "SH2.discriminating_observation",
        "slot_name": "discriminating_observation",
        "expected_evidence_role": "DIRECT_OBSERVATION",
        "retrieval_plan": {
            "query_lanes": [
                {
                    "lane_id": "SH2.discriminating_observation.baseline.broad_anchor",
                    "lane": "broad_anchor",
                    "provider": "openalex",
                    "query": "lithium-ion battery capacity retention degradation",
                    "query_variant_id": "baseline_observation",
                    "execution_phase": "initial",
                    "discipline_filter_policy": "broad",
                },
                {
                    "lane_id": "SH2.discriminating_observation.baseline.exact_primary_discipline",
                    "lane": "exact_primary_discipline",
                    "provider": "openalex",
                    "query": "lithium-ion battery capacity retention degradation",
                    "query_variant_id": "baseline_observation",
                    "execution_phase": "initial",
                    "discipline_filter_policy": "exact_primary",
                    "hard_filter_applied": True,
                    "provider_filter": {
                        "applied": True,
                        "coverage": "exact",
                        "policy": "hard_filter",
                        "filter": "primary_topic.field.id:21",
                    },
                },
            ]
        },
    }
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                min_slot_candidates_before_relaxation=2,
                enable_slot_semantic_scholar_fallback=True,
            )
        )
    )
    collector.logger = _CapturingLogger()
    collector.data_manager = SimpleNamespace(semantic_scholar_api=_SemanticScholar())
    collector._execute_query_lane = lambda lane: (
        broad_papers if lane["lane"] == "broad_anchor" else []
    )

    candidates = collector._discover_subhypothesis_candidates(
        [{"sub_hypothesis_id": "SH2", "slot_recovery_tasks": [task]}]
    )
    summary = collector._slot_retrieval_summaries[0]

    assert [paper["paperId"] for paper in candidates] == ["W1", "W2"]
    assert summary["merged_unique_candidates"] == 2
    assert summary["zero_result_lanes"] == [
        "SH2.discriminating_observation.baseline.exact_primary_discipline"
    ]
    assert summary["relaxation_used"] is False
    assert summary["fallback_used"] is False
    assert summary["next_action"] == "none"


def test_slot_retrieval_uses_a_bounded_parallel_worker_pool() -> None:
    tasks = []
    for index in range(4):
        task_id = f"SH1.slot_{index}"
        tasks.append(
            {
                "task_id": task_id,
                "slot_name": f"slot_{index}",
                "expected_evidence_role": "DIRECT_OBSERVATION",
                "retrieval_plan": {
                    "query_lanes": [
                        {
                            "lane_id": f"{task_id}.baseline.broad_anchor",
                            "lane": "broad_anchor",
                            "provider": "openalex",
                            "query": f"bounded parallel query {index}",
                            "query_variant_id": "baseline_observation",
                            "execution_phase": "initial",
                            "discipline_filter_policy": "broad",
                        }
                    ]
                },
            }
        )

    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                slot_retrieval_parallel_workers=2,
                min_slot_candidates_before_relaxation=1,
                enable_slot_semantic_scholar_fallback=False,
            )
        )
    )
    collector.logger = _CapturingLogger()
    activity_lock = threading.Lock()
    active = 0
    max_active = 0

    def execute_lane(lane):
        nonlocal active, max_active
        with activity_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            return [
                {
                    "paperId": lane["lane_id"],
                    "title": lane["query"],
                }
            ]
        finally:
            with activity_lock:
                active -= 1

    collector._execute_query_lane = execute_lane

    candidates = collector._discover_subhypothesis_candidates(
        [{"sub_hypothesis_id": "SH1", "slot_recovery_tasks": tasks}]
    )

    assert len(candidates) == 4
    assert max_active == 2
    assert len(collector._slot_retrieval_summaries) == 4
    assert any(
        "Starting bounded SH slot retrieval pool: tasks=4 workers=2."
        in message
        for message in collector.logger.messages
    )


def test_slot_semantic_scholar_fallback_runs_once_only_after_all_enabled_lanes_are_empty() -> None:
    fallback_paper = {
        "paperId": "S1",
        "title": "Semantic Scholar lithium-ion degradation study",
    }

    class _SemanticScholar:
        def __init__(self):
            self.calls = []

        def search_papers(self, **kwargs):
            self.calls.append(kwargs)
            return {"data": [fallback_paper]}

    semantic_scholar = _SemanticScholar()
    task = {
        "task_id": "SH2.discriminating_observation",
        "slot_name": "discriminating_observation",
        "expected_evidence_role": "DIRECT_OBSERVATION",
        "retrieval_plan": {
            "query_lanes": [
                {
                    "lane_id": "SH2.discriminating_observation.baseline.broad_anchor",
                    "lane": "broad_anchor",
                    "provider": "openalex",
                    "query": "lithium-ion battery capacity retention degradation",
                    "query_variant_id": "baseline_observation",
                    "execution_phase": "initial",
                    "discipline_filter_policy": "broad",
                },
                {
                    "lane_id": "SH2.discriminating_observation.operando.broad_anchor",
                    "lane": "broad_anchor",
                    "provider": "openalex",
                    "query": "operando spectroscopy lithium-ion electrode degradation",
                    "query_variant_id": "operando_mechanism",
                    "execution_phase": "relaxed",
                    "discipline_filter_policy": "broad",
                },
                {
                    "lane_id": "SH2.discriminating_observation.operando.adjacent_precision",
                    "lane": "adjacent_precision",
                    "provider": "openalex",
                    "query": "operando spectroscopy lithium-ion electrode degradation",
                    "query_variant_id": "operando_mechanism",
                    "execution_phase": "relaxed",
                    "discipline_filter_policy": "adjacent_precision",
                    "hard_filter_applied": True,
                    "provider_filter": {
                        "applied": True,
                        "coverage": "exact",
                        "policy": "hard_filter",
                        "filter": "primary_topic.field.id:21|25|16",
                    },
                },
            ]
        },
    }
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                min_slot_candidates_before_relaxation=1,
                enable_slot_semantic_scholar_fallback=True,
                enable_adjacent_discipline_precision_lane=True,
            )
        )
    )
    collector.logger = _CapturingLogger()
    collector.data_manager = SimpleNamespace(semantic_scholar_api=semantic_scholar)
    collector._execute_query_lane = lambda _lane: []

    candidates = collector._discover_subhypothesis_candidates(
        [{"sub_hypothesis_id": "SH2", "slot_recovery_tasks": [task]}]
    )
    summary = collector._slot_retrieval_summaries[0]

    assert [paper["paperId"] for paper in candidates] == ["S1"]
    assert len(semantic_scholar.calls) == 1
    assert semantic_scholar.calls[0]["query"] == "lithium-ion battery capacity retention degradation"
    assert summary["relaxation_used"] is True
    assert summary["fallback_used"] is True
    assert summary["merged_unique_candidates"] == 1
    assert summary["next_action"] == "semantic_scholar_short_query_fallback_completed"
    provenance = candidates[0]["retrieval_provenance"]
    assert provenance[0]["lane"] == "semantic_scholar_fallback"
    assert provenance[0]["query_variant_id"] == "baseline_observation"


def test_work_collector_skips_arxiv_discovery_when_disabled() -> None:
    class _Arxiv:
        def search_papers(self, *_args, **_kwargs):
            raise AssertionError("disabled arXiv discovery must not make a network request")

    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(enable_arxiv_discovery=False)
        )
    )
    collector.data_manager = SimpleNamespace(arxiv_api=_Arxiv())

    papers = collector._execute_query_lane(
        {
            "provider": "arxiv",
            "query": "machine learning for materials discovery",
            "provider_filter": {
                "applied": True,
                "coverage": "exact",
                "policy": "hard_filter",
                "category_expression": "cat:cs.LG",
            },
        }
    )

    assert papers == []


def test_work_collector_omits_arxiv_lanes_when_discovery_is_disabled() -> None:
    context = build_project_research_context(
        original_topic="machine learning for crop disease diagnosis",
        declared_domain="agriculture",
        use_llm=False,
    )
    contract = _crop_comparative_contract(context, identifier="arxiv_disabled")
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(enable_arxiv_discovery=False)
        )
    )
    collector.get_project_research_context = lambda _topic: context

    compiled = collector.build_subhypothesis_retrieval_plan(
        [contract],
        context["original_topic"],
    )
    lanes = [
        lane
        for task in compiled["subhypotheses"][0]["slot_recovery_tasks"]
        for lane in task["retrieval_plan"]["query_lanes"]
    ]

    assert lanes
    assert all(lane["provider"] != "arxiv" for lane in lanes)

    # A cache created before the provider was disabled may still contain a
    # serialized arXiv lane.  It must be discarded before any task is logged
    # or sent to a provider.
    cached_with_arxiv = compiled["subhypotheses"]
    cached_with_arxiv[0]["slot_recovery_tasks"][0]["retrieval_plan"][
        "query_lanes"
    ].append(
        {
            "provider": "arxiv",
            "lane": "arxiv_frontier",
            "lane_id": "arxiv_disabled.candidate.arxiv_frontier",
            "query": "crop disease diagnosis preprint",
        }
    )
    assert all(
        lane["provider"] != "arxiv"
        for lane in collector._slot_recovery_task_lanes(cached_with_arxiv)
    )


def test_work_collector_executes_openalex_first_lanes_and_merges_provenance() -> None:
    context = build_project_research_context(
        original_topic="machine learning for materials discovery",
        declared_domain="materials science",
        use_llm=False,
    )
    openalex_paper = {
        "paperId": "W25",
        "openalex_id": "https://api.openalex.org/W25",
        "api_platform": "openalex",
        "title": "Machine learning for materials discovery",
        "externalIds": {"DOI": "10.1000/materials"},
    }
    arxiv_duplicate = {
        "paperId": "2501.12345",
        "paper_id": "2501.12345",
        "api_platform": "arxiv",
        "title": "Machine learning for materials discovery",
        "externalIds": {"ArXiv": "2501.12345"},
    }

    class _OpenAlex:
        def __init__(self):
            self.calls = []

        def search_papers(self, query, provider_filter=None, sort=None):
            self.calls.append((query, provider_filter, sort))
            return [openalex_paper]

        def resolve_work_id(self, _paper):
            return "W25"

    class _Arxiv:
        def __init__(self):
            self.calls = []

        def search_papers(self, query, provider_filter=None):
            self.calls.append((query, provider_filter))
            return [arxiv_duplicate]

    class _SemanticScholar:
        def search_papers(self, **_kwargs):
            raise AssertionError("Semantic Scholar is fallback-only and must not run")

    class _DataManager:
        def __init__(self):
            self.openalex_api = _OpenAlex()
            self.arxiv_api = _Arxiv()
            self.semantic_scholar_api = _SemanticScholar()
            self.download_requests = []

        def _resolve_paper_reference_id(self, paper):
            return paper["paperId"]

        def download_and_parse_papers(self, papers, limit):
            self.download_requests.append((papers, limit))
            return [paper["paperId"] for paper in papers]

    data_manager = _DataManager()
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                use_seed_filter_LLM=False,
                max_seed_paper_num=5,
                enable_arxiv_discovery=True,
            )
        )
    )
    collector.data_manager = data_manager
    collector.logger = _Logger()
    collector.expand_in_local_paper_graph = False
    collector.graph_paper_ids = set()
    collector.ignore_paper = set()
    collector._openalex_id_aliases = {}
    collector.get_project_research_context = lambda _topic: context

    seed_ids = collector.collect_seed_papers(context["original_topic"])

    assert seed_ids == ["W25"]
    assert any(call[1] is None for call in data_manager.openalex_api.calls)
    assert any(
        call[1] and call[1]["filter"] == "primary_topic.field.id:25"
        for call in data_manager.openalex_api.calls
    )
    assert len(data_manager.arxiv_api.calls) == 1
    downloaded_papers = data_manager.download_requests[0][0]
    assert downloaded_papers == [openalex_paper]
    provenance = openalex_paper["retrieval_provenance"]
    assert {record["provider"] for record in provenance} == {"openalex", "arxiv"}
    assert all(record["source_work_count"] == 1 for record in provenance)


def test_lane_balanced_selection_prevents_broad_results_from_starving_other_lanes() -> None:
    def paper(title, lane):
        return {
            "title": title,
            "retrieval_provenance": [{"lane": lane}],
        }

    broad_papers = [paper(f"broad-{index}", "broad_anchor") for index in range(5)]
    candidates = [
        *broad_papers,
        paper("exact-only", "exact_discipline"),
        paper("arxiv-only", "arxiv_frontier"),
        paper("empirical-only", "evidence_mode"),
    ]
    collector = object.__new__(WorkCollector)

    selected = collector._select_lane_balanced_seed_candidates(candidates, limit=5)

    assert [candidate["title"] for candidate in selected] == [
        "broad-0",
        "exact-only",
        "arxiv-only",
        "empirical-only",
        "broad-1",
    ]


def test_sh_seed_collection_runs_one_targeted_supplement_and_separates_context_seeds() -> None:
    context = build_project_research_context(
        original_topic="machine learning for crop disease diagnosis",
        declared_domain="agriculture",
        objective="Compare field image classifiers for crop disease diagnosis",
        use_llm=False,
    )
    papers = {
        "direct": {
            "paperId": "W1",
            "openalex_id": "https://api.openalex.org/W1",
                "api_platform": "openalex",
                "title": "Field experiment of image classifiers for crop disease diagnosis",
                "abstract": "The benchmark evaluation compares standard CNN baselines and reports diagnosis accuracy under field conditions.",
            "venue": "Journal A",
        },
        "mechanism": {
            "paperId": "W2",
            "openalex_id": "https://api.openalex.org/W2",
            "api_platform": "openalex",
            "title": "Domain adaptation mechanism for crop disease diagnosis",
            "abstract": "An ablation explains the mechanism under field conditions.",
            "venue": "Journal B",
        },
        "boundary": {
            "paperId": "W3",
            "openalex_id": "https://api.openalex.org/W3",
            "api_platform": "openalex",
            "title": "Adverse domain shift failure in crop disease diagnosis",
            "abstract": "False negatives reveal a limitation under field conditions.",
            "venue": "Journal C",
        },
        "review": {
            "paperId": "W4",
            "openalex_id": "https://api.openalex.org/W4",
            "api_platform": "openalex",
            "title": "Plant pathology review for crop disease diagnosis",
            "abstract": "A systematic review and taxonomy of image classifiers.",
            "venue": "Journal D",
        },
    }

    class _OpenAlex:
        def __init__(self):
            self.queries = []

        def search_papers(self, query, provider_filter=None, sort=None):
            self.queries.append((query, provider_filter, sort))
            query_text = query.casefold()
            if "adverse boundary condition" in query_text:
                return [papers["boundary"]]
            if "domain adaptation" in query_text:
                return [papers["mechanism"]]
            if "domain shift" in query_text:
                return [papers["boundary"]]
            if "plant pathology" in query_text:
                return [papers["review"]]
            if "failure" in query_text:
                return []
            return [papers["direct"]]

        def resolve_work_id(self, paper):
            return paper["paperId"]

    class _SemanticScholar:
        def search_papers(self, **_kwargs):
            raise AssertionError("Semantic Scholar must not run when SH lanes returned papers")

    class _DataManager:
        def __init__(self):
            self.openalex_api = _OpenAlex()
            self.semantic_scholar_api = _SemanticScholar()
            self.download_requests = []

        def _resolve_paper_reference_id(self, paper):
            return paper["paperId"]

        def download_and_parse_papers(self, candidates, limit):
            self.download_requests.append((candidates, limit))
            return [candidate["paperId"] for candidate in candidates]

    subhypotheses = [
        _crop_comparative_contract(context)
    ]
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(subhypotheses=subhypotheses),
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                use_seed_filter_LLM=False,
                LLM_seed_threshold=4,
                max_seed_paper_num=5,
                enable_subhypothesis_retrieval=True,
                subhypothesis_relevance_threshold=3,
                subhypothesis_max_unique_papers=6,
                subhypothesis_max_slots_per_paper=2,
                subhypothesis_max_supplement_rounds=1,
                subhypothesis_no_yield_stop_rounds=1,
                enable_evidence_refinement_retrieval=False,
            )
        ),
    )
    collector.data_manager = _DataManager()
    collector.logger = _Logger()
    collector.expand_in_local_paper_graph = False
    collector.graph_paper_ids = set()
    collector.ignore_paper = set()
    collector._openalex_id_aliases = {}
    collector.context_seed_paper_ids = set()
    collector.get_project_research_context = lambda _topic: context
    collector._store_subhypothesis_retrieval_artifact = lambda artifact: setattr(
        collector, "subhypothesis_retrieval_artifact", dict(artifact)
    )

    seed_ids = collector.collect_seed_papers(context["original_topic"])

    assert seed_ids == ["W1", "W2", "W3", "W4"]
    assert collector.context_seed_paper_ids == {"W4"}
    artifact = collector.subhypothesis_retrieval_artifact
    assert artifact["project_id"] == collector._project_id(context)
    assert artifact["project_context_fingerprint"] == context["input_fingerprint"]
    assert artifact["supplement"]["attempted"] is False
    assert artifact["evidence_coverage_ledger_final"]["complete"] is True
    assert artifact["evidence_coverage_ledger_final"]["project_id"] == artifact["project_id"]
    assert artifact["evidence_coverage_ledger_final"]["project_context_fingerprint"] == artifact["project_context_fingerprint"]
    report = artifact["evidence_coverage_ledger_final"]["subhypotheses"][0]
    assert report["missing_slots"] == []
    assert report["conclusion_admissibility"]["admissible"] is True
    downloaded = collector.data_manager.download_requests[0][0]
    assert all("sh_matches" in paper for paper in downloaded)
    assert all("slot_provenance" in paper for paper in downloaded)

    observed_graph_seeds = []
    collector.paper_graph_retriever = None
    collector.update_reference_graph = lambda paper_ids: observed_graph_seeds.extend(paper_ids) or []
    collector.expand_seed_papers_by_reference_and_citation(seed_ids)
    assert observed_graph_seeds == ["W1", "W2", "W3"]


def test_sh_semantic_candidates_do_not_trigger_formal_coverage_supplement() -> None:
    context = build_project_research_context(
        original_topic="machine learning for crop disease diagnosis",
        declared_domain="agriculture",
        use_llm=False,
    )
    direct_paper = {
        "paperId": "W1",
        "openalex_id": "https://api.openalex.org/W1",
        "api_platform": "openalex",
        "title": "Field experiment of image classifiers for crop disease diagnosis",
        "abstract": "The evaluation reports diagnosis accuracy under field conditions.",
    }
    subhypotheses = [
        _crop_comparative_contract(context)
    ]
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(subhypotheses=subhypotheses),
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                use_seed_filter_LLM=False,
                LLM_seed_threshold=4,
                max_seed_paper_num=5,
                subhypothesis_relevance_threshold=3,
                subhypothesis_max_unique_papers=6,
                subhypothesis_max_slots_per_paper=2,
            )
        ),
    )
    collector.logger = _Logger()
    collector.get_project_research_context = lambda _topic: context
    collector._store_subhypothesis_retrieval_artifact = lambda artifact: setattr(
        collector, "subhypothesis_retrieval_artifact", dict(artifact)
    )
    retrieval_rounds = []

    def discover(_subhypotheses, **kwargs):
        retrieval_round = kwargs.get("retrieval_round", 0)
        retrieval_rounds.append(retrieval_round)
        if retrieval_round:
            return []
        return [
            {
                **direct_paper,
                "retrieval_provenance": [
                    {
                        "sub_hypothesis_id": "crop_field",
                        "slot_recovery_task_id": "crop_field.candidate",
                        "slot_name": "candidate",
                        "expected_evidence_role": "COMPARATIVE_OR_MEASUREMENT_EVIDENCE",
                    }
                ],
            }
        ]

    collector._discover_subhypothesis_candidates = discover
    plan, valid_subhypotheses = collector._build_configured_subhypothesis_plan(
        context["original_topic"]
    )
    selected, _selection = collector._collect_sh_seed_candidates(
        context["original_topic"],
        context,
        plan,
        valid_subhypotheses,
    )

    assert [paper["paperId"] for paper in selected] == ["W1"]
    assert retrieval_rounds == [0]
    assert collector.subhypothesis_retrieval_artifact["supplement"] == {
        "attempted": False,
        "round": 0,
        "requested_slot_recovery_tasks": {},
        "new_unique_papers": 0,
        "no_yield_stop": False,
        "disabled_reason": "formal_slot_coverage_does_not_trigger_retrieval",
    }


def test_work_collector_does_not_run_ledger_direct_coverage_refinement() -> None:
    context = build_project_research_context(
        original_topic="machine learning for crop disease diagnosis",
        declared_domain="agriculture",
        objective="Compare field image classifiers for crop disease diagnosis",
        use_llm=False,
    )
    primary_candidate = {
        "paperId": "W1",
        "api_platform": "openalex",
        "title": "Machine learning benchmark evaluation of image classifiers for crop disease diagnosis",
        "abstract": "The field conditions study reports diagnosis accuracy.",
    }
    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        BasicInfo=SimpleNamespace(subhypotheses=[_crop_comparative_contract(context)]),
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(
                use_seed_filter_LLM=False,
                LLM_seed_threshold=4,
                max_seed_paper_num=5,
                subhypothesis_relevance_threshold=3,
                subhypothesis_max_unique_papers=6,
                subhypothesis_max_slots_per_paper=2,
            )
        ),
    )
    collector.logger = _Logger()
    collector.get_project_research_context = lambda _topic: context
    collector._store_subhypothesis_retrieval_artifact = lambda artifact: setattr(
        collector, "subhypothesis_retrieval_artifact", dict(artifact)
    )
    observed_refinement_kinds = []

    def execute_lane(lane):
        if lane.get("retrieval_stage") == "evidence_refinement":
            observed_refinement_kinds.append(lane["refinement_kind"])
            raise AssertionError("formal ledger coverage must not trigger refinement retrieval")
        if lane.get("slot_name") == "candidate" and not lane.get("retrieval_round"):
            return [primary_candidate]
        return []

    collector._execute_query_lane = execute_lane
    plan, valid_subhypotheses = collector._build_configured_subhypothesis_plan(
        context["original_topic"]
    )
    selected, _selection = collector._collect_sh_seed_candidates(
        context["original_topic"],
        context,
        plan,
        valid_subhypotheses,
    )

    artifact = collector.subhypothesis_retrieval_artifact
    refinement = artifact["evidence_refinement"]
    assert artifact["schema_version"] == "subhypothesis_slot_retrieval_execution_v5"
    assert artifact["evidence_coverage_ledger_final"]["refinement_resolution"] == []
    assert observed_refinement_kinds == []
    assert refinement["enabled"] is False
    assert refinement["new_unique_papers"] == 0
    assert refinement["execution"]["attempted"] is False
    assert refinement["execution"]["disabled_reason"] == (
        "formal_slot_coverage_does_not_trigger_retrieval"
    )
    assert {paper["paperId"] for paper in selected} == {"W1"}


def test_sh_discovery_budget_reserves_one_candidate_for_each_slot_recovery_task() -> None:
    context = build_project_research_context(
        original_topic="machine learning for crop disease diagnosis",
        declared_domain="agriculture",
        use_llm=False,
    )
    compiled = build_subhypothesis_retrieval_plan(
        context,
        [_crop_comparative_contract(context, identifier="sh_1")],
    )["subhypotheses"]

    def paper(index, task_id):
        return {
            "paperId": f"W{index}",
            "title": f"Paper {index}",
            "retrieval_provenance": [
                {
                    "sub_hypothesis_id": "sh_1",
                    "slot_recovery_task_id": task_id,
                }
            ],
        }

    collector = object.__new__(WorkCollector)
    collector.config = SimpleNamespace(
        ModuleInfo=SimpleNamespace(
            WorkCollector=SimpleNamespace(subhypothesis_max_unique_papers=4)
        )
    )
    papers = [
        paper(1, "sh_1.candidate"),
        paper(2, "sh_1.candidate"),
        paper(3, "sh_1.comparator"),
        paper(4, "sh_1.comparison_condition"),
        paper(5, "sh_1.comparable_endpoint"),
        paper(6, "sh_1.background_framework"),
    ]

    selected = collector._limit_subhypothesis_discovery_candidates(
        papers,
        compiled,
    )

    assert [paper["paperId"] for paper in selected] == ["W1", "W3", "W4", "W5"]
