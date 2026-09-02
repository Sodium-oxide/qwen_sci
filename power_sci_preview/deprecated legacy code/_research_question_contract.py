"""Domain-neutral V3 research-question and retrieval contracts.

An SH is a *question decomposition*, not an already accepted causal chain.
This module owns the V3 contract that tells retrieval and full-text extraction
which evidence is needed for a question.  It intentionally does not translate
historic ``causal_chain`` artefacts or V1/V2 retrieval plans: projects must be
re-decomposed into this schema before entering the V3 evidence pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Literal, Mapping, TypedDict

try:
    from ._gap_types import GapType, normalize_gap_type
except ImportError:
    from _gap_types import GapType, normalize_gap_type


RESEARCH_QUESTION_CONTRACT_VERSION = "research_question_contract_v3"
RESEARCH_QUESTION_CONTRACT_SCHEMA_REVISION = "v3_2_domain_contract"
RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION = "research_question_retrieval_plan_v3"
RETRIEVAL_TASK_SPEC_VERSION = "retrieval_task_spec_v3"
RETRIEVAL_WORK_ITEM_VERSION = "retrieval_work_item_v3"
RETRIEVAL_OBLIGATION_VERSION = "retrieval_obligation_v3"
PROVIDER_OUTCOME_VERSION = "provider_outcome_v3"
FOUNDATIONAL_CONTEXT_CONTRACT_VERSION = "foundational_context_contract_v3"
COMPARISON_CONTRACT_VERSION = "comparison_contract_v4"
RESEARCH_DOMAIN_CONTRACT_VERSION = "research_domain_contract_v1"


class ResearchDomainContract(TypedDict):
    schema_version: Literal["research_domain_contract_v1"]
    status: Literal["READY", "PENDING"]
    primary_domain_id: str
    active_domain_ids: list[str]
    taxonomy_nodes: list[dict[str, str]]
    source: Literal[
        "project_domain_resolution",
        "provider_taxonomy",
        "llm_taxonomy_classification",
    ]
    evidence_anchors: list[str]
    confidence: float
    reason_codes: list[str]


class ResearchQuestionTask(TypedDict):
    schema_version: Literal["research_question_task_v1"]
    task_id: str
    task_kind: Literal["OBJECT", "SYNTHESIS"]
    parent_task_id: str
    research_object: str
    population_or_system: str
    prediction_horizon: str
    measurement_definition: str
    outcome_definition: str
    data_quality_dimension: str
    data_quantity_dimension: str
    evidence_slot_ids: list[str]
    component_task_ids: list[str]
    scope_status: Literal["READY", "PENDING"]
    reason_codes: list[str]
    parent_contract_id: str
    alignment_scope_id: str
    alignment_scope_revision: str


def _normalize_object_components(value: Any) -> list[dict[str, str]]:
    raw = value if isinstance(value, list) else []
    components: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        research_object = _text(item.get("research_object") or item.get("object"))
        if not research_object:
            continue
        components.append({
            "task_id": _text(item.get("task_id") or item.get("id")),
            "research_object": research_object,
            "population_or_system": _text(item.get("population_or_system")),
            "prediction_horizon": _text(item.get("prediction_horizon") or item.get("time_window")),
            "measurement_definition": _text(item.get("measurement_definition")),
            "outcome_definition": _text(item.get("outcome_definition")),
            "data_quality_dimension": _text(item.get("data_quality_dimension")),
            "data_quantity_dimension": _text(item.get("data_quantity_dimension")),
        })
    return components


def build_research_question_tasks(
    contract: Mapping[str, Any],
) -> list[ResearchQuestionTask]:
    """Build object-scoped tasks without treating an umbrella object as one endpoint.

    The component list is an explicit LLM/user declaration.  The runtime does
    not split arbitrary prose with domain-specific heuristics; absent that
    declaration, it returns one task or a pending task when the scope is empty.
    """

    source = contract if isinstance(contract, Mapping) else {}
    parent_contract_id = _text(source.get("contract_id"))
    parent_contract_revision = _text(
        source.get("contract_revision") or source.get("declaration_hash")
    )
    question = source.get("research_question") if isinstance(source.get("research_question"), Mapping) else {}
    scope = source.get("scientific_scope") if isinstance(source.get("scientific_scope"), Mapping) else {}
    required_slots = [
        _text(item)
        for item in (source.get("evidence_contract") or {}).get("required_slots", [])
        if _text(item)
    ]
    components = _normalize_object_components(question.get("object_components"))
    if not components:
        components = [{
            "research_object": _text(scope.get("research_object")),
            "population_or_system": _text(scope.get("population_or_system")),
            "prediction_horizon": _text(scope.get("time_window")),
            "measurement_definition": _text(scope.get("measurement_definition")),
            "outcome_definition": _text(scope.get("outcome_definition")),
            "data_quality_dimension": "",
            "data_quantity_dimension": "",
        }]
    tasks: list[ResearchQuestionTask] = []
    used_ids: set[str] = set()
    for index, component in enumerate(components, start=1):
        raw_id = _text(component.get("task_id"))
        task_id = raw_id or f"RQ-OBJECT-{index}"
        if task_id in used_ids:
            task_id = f"{task_id}-{index}"
        used_ids.add(task_id)
        object_text = _text(component.get("research_object"))
        tasks.append({
            "schema_version": "research_question_task_v1",
            "task_id": task_id,
            "task_kind": "OBJECT",
            "parent_task_id": "RQ-SYNTHESIS" if len(components) > 1 else "",
            "research_object": object_text,
            "population_or_system": _text(component.get("population_or_system") or scope.get("population_or_system")),
            "prediction_horizon": _text(component.get("prediction_horizon") or scope.get("time_window")),
            "measurement_definition": _text(component.get("measurement_definition") or scope.get("measurement_definition")),
            "outcome_definition": _text(component.get("outcome_definition") or scope.get("outcome_definition")),
            "data_quality_dimension": _text(component.get("data_quality_dimension")),
            "data_quantity_dimension": _text(component.get("data_quantity_dimension")),
            "evidence_slot_ids": list(required_slots),
            "component_task_ids": [],
            "scope_status": "READY" if object_text else "PENDING",
            "reason_codes": [] if object_text else ["RESEARCH_OBJECT_REQUIRED"],
            "parent_contract_id": parent_contract_id,
            "alignment_scope_id": f"{parent_contract_id}:{task_id}" if parent_contract_id else task_id,
            "alignment_scope_revision": f"{parent_contract_revision}:{task_id}" if parent_contract_revision else task_id,
        })
    if len(tasks) > 1:
        tasks.append({
            "schema_version": "research_question_task_v1",
            "task_id": "RQ-SYNTHESIS",
            "task_kind": "SYNTHESIS",
            "parent_task_id": "",
            "research_object": _text(scope.get("research_object")),
            "population_or_system": _text(scope.get("population_or_system")),
            "prediction_horizon": _text(scope.get("time_window")),
            "measurement_definition": _text(scope.get("measurement_definition")),
            "outcome_definition": _text(scope.get("outcome_definition")),
            "data_quality_dimension": "cross-object coverage, quality, and quantity",
            "data_quantity_dimension": "cross-object coverage, quality, and quantity",
            "evidence_slot_ids": [],
            "component_task_ids": [str(item["task_id"]) for item in tasks],
            "scope_status": "READY" if _text(scope.get("research_object")) else "PENDING",
            "reason_codes": [] if _text(scope.get("research_object")) else ["SYNTHESIS_RESEARCH_OBJECT_REQUIRED"],
            "parent_contract_id": parent_contract_id,
            "alignment_scope_id": f"{parent_contract_id}:RQ-SYNTHESIS" if parent_contract_id else "RQ-SYNTHESIS",
            "alignment_scope_revision": f"{parent_contract_revision}:RQ-SYNTHESIS" if parent_contract_revision else "RQ-SYNTHESIS",
        })
    return tasks


def bind_research_question_task_scope(
    contract: Mapping[str, Any],
    task: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Create an execution-scoped view without inventing a second RQC.

    The persisted contract id/revision remain authoritative.  Only the
    scientific scope used by retrieval/alignment is narrowed to one object
    task, and the scope identity is carried separately for provenance.
    """
    bound = dict(contract) if isinstance(contract, Mapping) else {}
    task_value = task if isinstance(task, Mapping) else {}
    task_id = _text(task_value.get("task_id") or task_value.get("research_question_task_id"))
    if not task_id:
        return bound
    object_scope = task_value.get("object_scope") if isinstance(task_value.get("object_scope"), Mapping) else task_value
    scope = dict(bound.get("scientific_scope") or {}) if isinstance(bound.get("scientific_scope"), Mapping) else {}
    replacements = {
        "research_object": object_scope.get("research_object"),
        "population_or_system": object_scope.get("population_or_system"),
        "time_window": object_scope.get("prediction_horizon") or object_scope.get("time_window"),
        "measurement_definition": object_scope.get("measurement_definition"),
        "outcome_definition": object_scope.get("outcome_definition"),
    }
    for axis, value in replacements.items():
        normalized = _text(value)
        if normalized:
            scope[axis] = normalized
    bound["scientific_scope"] = scope
    bound["research_question_task_id"] = task_id
    target_slot_ids = [
        _text(value)
        for value in (
            task_value.get("target_slot_ids")
            if isinstance(task_value.get("target_slot_ids"), list)
            else [task_value.get("evidence_slot") or task_value.get("slot")]
        )
        if _text(value)
    ]
    bound["target_slot_ids"] = list(dict.fromkeys(target_slot_ids))
    bound["object_scope"] = {
        key: _text(value)
        for key, value in object_scope.items()
        if _text(value)
    }
    parent_id = _text(bound.get("contract_id"))
    parent_revision = _text(bound.get("contract_revision") or bound.get("declaration_hash"))
    bound["alignment_scope_id"] = f"{parent_id}:{task_id}" if parent_id else task_id
    bound["alignment_scope_revision"] = f"{parent_revision}:{task_id}" if parent_revision else task_id
    return bound

_COMPARISON_KINDS = frozenset({
    "METHOD_VS_METHOD",
    "MODEL_VS_MODEL",
    "SYSTEM_VS_SYSTEM",
})
_GENERIC_COMPARISON_ARM_TOKENS = frozenset({
    "algorithm", "algorithms", "alternative", "approach", "approaches",
    "arm", "baseline", "candidate", "candidates", "comparison",
    "comparative", "condition", "conditions", "control", "controls",
    "conventional", "data", "default", "different", "driven", "experimental",
    "framework", "frameworks", "general", "generic", "group", "groups",
    "method", "methods", "model", "models", "multiple", "new", "novel",
    "option", "options", "other", "others", "platform", "platforms",
    "primary", "proposed", "reference", "secondary", "standard", "strategy",
    "strategies", "system", "systems", "technique", "techniques", "test",
    "tests", "traditional", "treatment", "treatments", "variant", "variants",
    "version", "versions", "versus",
})
_COMPARISON_ARM_ORDINAL_TOKENS = frozenset({
    "a", "b", "c", "d", "e", "f", "first", "second", "third", "fourth",
    "i", "ii", "iii", "iv", "one", "two", "three", "four", "five",
})


class RetrievalWorkItemKind(str, Enum):
    """The two V3 retrieval intents are deliberately non-interchangeable."""

    SLOT_RECOVERY = "SLOT_RECOVERY"
    GAP_RESOLUTION = "GAP_RESOLUTION"


def research_question_cutover_audit_v3(project: Mapping[str, Any] | None) -> dict[str, Any]:
    """Verify that every active sub-hypothesis is a current V3 contract."""

    source = project if isinstance(project, Mapping) else {}
    declared_ids: list[str] = []
    stale_ids: list[str] = []
    invalid_ids: list[str] = []
    sub_hypotheses = source.get("sub_hypotheses")
    for index, sub_hypothesis in enumerate(
        sub_hypotheses if isinstance(sub_hypotheses, list) else []
    ):
        if not isinstance(sub_hypothesis, Mapping):
            continue
        sub_hypothesis_id = _text(
            sub_hypothesis.get("id")
            or sub_hypothesis.get("sub_hypothesis_id")
            or f"SH{index + 1}"
        )
        contract = sub_hypothesis.get("research_question_contract")
        if not isinstance(contract, Mapping):
            stale_ids.append(sub_hypothesis_id)
            continue
        if contract.get("schema_version") != RESEARCH_QUESTION_CONTRACT_VERSION:
            stale_ids.append(sub_hypothesis_id)
            continue
        if not _text(contract.get("contract_id")) or not _text(
            contract.get("contract_revision") or contract.get("declaration_hash")
        ):
            invalid_ids.append(sub_hypothesis_id)
            continue
        try:
            validate_research_question_contract(contract)
        except ValueError:
            invalid_ids.append(sub_hypothesis_id)
            continue
        declared_ids.append(sub_hypothesis_id)
    active = bool(declared_ids)
    return {
        "schema_version": "research_question_cutover_audit_v3",
        "status": (
            "CURRENT_V3"
            if active and not stale_ids and not invalid_ids
            else "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED"
        ),
        "v3_declared": active,
        "all_subhypotheses_v3": bool(active and not stale_ids and not invalid_ids),
        "declared_sub_hypothesis_ids": declared_ids,
        "stale_sub_hypothesis_ids": stale_ids,
        "invalid_sub_hypothesis_ids": invalid_ids,
        "legacy_causal_artifacts_accepted": False,
    }


class ProviderOutcomeKind(str, Enum):
    """Provider execution outcomes, distinct from scientific coverage."""

    SUCCESS_WITH_CANDIDATES = "SUCCESS_WITH_CANDIDATES"
    SUCCESS_EMPTY = "SUCCESS_EMPTY"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_ERROR = "NETWORK_ERROR"
    INVALID_QUERY = "INVALID_QUERY"
    AUTH_ERROR = "AUTH_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"


_RETRYABLE_PROVIDER_OUTCOMES = frozenset({
    ProviderOutcomeKind.TIMEOUT,
    ProviderOutcomeKind.RATE_LIMITED,
    ProviderOutcomeKind.NETWORK_ERROR,
    ProviderOutcomeKind.PARSE_ERROR,
    ProviderOutcomeKind.CIRCUIT_OPEN,
})

RESEARCH_ROLE_VALUES = frozenset({
    "PRIMARY_QUESTION",
    "BASELINE_ENABLER",
    "BOUNDARY_TEST",
    "FALSIFICATION_RULE",
    "FOUNDATIONAL_CONTEXT",
})
MAPPING_STATUS_VALUES = frozenset({
    "ESTABLISHED_CALIBRATION",
    "STANDARD_DEFINED",
    "EMPIRICALLY_ESTIMATED",
    "CONTESTED",
    "UNMAPPED",
    "PROJECT_DEFINED",
})
THRESHOLD_SOURCE_VALUES = frozenset({
    "NOT_APPLICABLE",
    "METROLOGY_CALIBRATION",
    "TASK_OR_ENGINEERING_REQUIREMENT",
    "STANDARD_OR_GUIDELINE",
    "EMPIRICAL_LITERATURE",
    "PROJECT_DEFINED",
})


class ResearchQuestionKind(str, Enum):
    EMPIRICAL_COVERAGE = "EMPIRICAL_COVERAGE"
    AUTHOR_STATED_LIMITATION = "AUTHOR_STATED_LIMITATION"
    CAUSAL_IDENTIFICATION = "CAUSAL_IDENTIFICATION"
    MECHANISM_COMPETITION = "MECHANISM_COMPETITION"
    BOUNDARY_HETEROGENEITY = "BOUNDARY_HETEROGENEITY"
    CONTRADICTION_REPLICATION = "CONTRADICTION_REPLICATION"
    MEASUREMENT_VALIDITY = "MEASUREMENT_VALIDITY"
    THEORY_MATHEMATICAL = "THEORY_MATHEMATICAL"
    GENERALIZATION_TRANSPORTABILITY = "GENERALIZATION_TRANSPORTABILITY"
    METHOD_DESIGN = "METHOD_DESIGN"
    DATA_COVERAGE = "DATA_COVERAGE"
    SCALE_INTEGRATION = "SCALE_INTEGRATION"
    BENCHMARK_COMPARISON = "BENCHMARK_COMPARISON"
    TRANSLATION_IMPLEMENTATION = "TRANSLATION_IMPLEMENTATION"


SCOPE_AXES: tuple[str, ...] = (
    "research_object",
    "population_or_system",
    "sample_or_model",
    "condition_or_regime",
    "intervention_or_exposure",
    "time_window",
    "spatial_scale",
    "temporal_scale",
    "method_or_design",
    "measurement_definition",
    "outcome_definition",
    "dataset_or_corpus",
    # These constraints are often decisive for boundary, transport, theory,
    # and implementation questions.  They must be declared explicitly rather
    # than hidden in a free-text note or inferred from a legacy SH.
    "theoretical_assumptions",
    "comparison_frame",
    "deployment_context",
)


@dataclass(frozen=True)
class QuestionKindSpec:
    kind: ResearchQuestionKind
    expected_gap_types: tuple[GapType, ...]
    required_slots: tuple[str, ...]
    optional_slots: tuple[str, ...]
    required_comparability_axes: tuple[str, ...]
    permitted_claim_relations: tuple[str, ...]
    package_kinds: tuple[str, ...]
    primary_mechanism_eligible: bool = False


QUESTION_KIND_SPECS: dict[ResearchQuestionKind, QuestionKindSpec] = {
    ResearchQuestionKind.EMPIRICAL_COVERAGE: QuestionKindSpec(
        ResearchQuestionKind.EMPIRICAL_COVERAGE,
        (GapType.EMPIRICAL_COVERAGE,),
        ("phenomenon", "target_object", "target_condition", "direct_observation"),
        ("coverage_dimension", "time_window"),
        ("research_object", "condition_or_regime", "outcome_definition"),
        ("OBSERVED", "DESCRIBED"),
        ("EMPIRICAL_TEST_PACKAGE",),
    ),
    ResearchQuestionKind.AUTHOR_STATED_LIMITATION: QuestionKindSpec(
        ResearchQuestionKind.AUTHOR_STATED_LIMITATION,
        (GapType.AUTHOR_STATED_LIMITATION,),
        ("author_stated_unknown", "affected_claim", "scope_of_limitation"),
        ("limitation_kind", "method_or_design"),
        ("research_object", "condition_or_regime"),
        ("LIMITS", "UNKNOWN", "UNTESTED"),
        ("FOLLOWUP_RESOLUTION_PACKAGE",),
    ),
    ResearchQuestionKind.CAUSAL_IDENTIFICATION: QuestionKindSpec(
        ResearchQuestionKind.CAUSAL_IDENTIFICATION,
        (GapType.CAUSAL_IDENTIFICATION,),
        ("exposure", "outcome", "identification_strategy", "alternative_explanation"),
        ("mediator", "moderator", "confounder", "target_estimand"),
        ("research_object", "condition_or_regime", "intervention_or_exposure", "outcome_definition"),
        ("CAUSES", "ASSOCIATED_WITH", "MEDIATES", "MODERATES"),
        ("MECHANISM_HYPOTHESIS_PACKAGE",),
        primary_mechanism_eligible=True,
    ),
    ResearchQuestionKind.MECHANISM_COMPETITION: QuestionKindSpec(
        ResearchQuestionKind.MECHANISM_COMPETITION,
        (GapType.MECHANISM_COMPETITION,),
        ("common_input", "common_outcome", "mechanism_a", "mechanism_b", "discriminating_prediction"),
        ("discriminating_intervention", "joint_measurement"),
        ("research_object", "condition_or_regime", "outcome_definition"),
        ("EXPLAINS", "MEDIATES", "CAUSES"),
        ("MECHANISM_DISCRIMINATION_PACKAGE",),
    ),
    ResearchQuestionKind.BOUNDARY_HETEROGENEITY: QuestionKindSpec(
        ResearchQuestionKind.BOUNDARY_HETEROGENEITY,
        (GapType.BOUNDARY_HETEROGENEITY,),
        ("base_relation", "boundary_variable", "condition_a", "condition_b", "comparable_endpoint"),
        ("threshold", "effect_difference"),
        ("research_object", "measurement_definition", "outcome_definition"),
        ("VALID_UNDER", "DIFFERS_UNDER", "MODERATES"),
        ("BOUNDARY_CONDITION_PACKAGE",),
    ),
    ResearchQuestionKind.CONTRADICTION_REPLICATION: QuestionKindSpec(
        ResearchQuestionKind.CONTRADICTION_REPLICATION,
        (GapType.CONTRADICTION_REPLICATION,),
        ("shared_claim", "result_a", "result_b", "comparability_axes"),
        ("effect_size", "replication_design", "unexplained_difference"),
        ("research_object", "condition_or_regime", "method_or_design", "measurement_definition", "outcome_definition"),
        ("CONTRADICTS", "REPLICATES", "OBSERVED"),
        ("REPLICATION_RESOLUTION_PACKAGE",),
    ),
    ResearchQuestionKind.MEASUREMENT_VALIDITY: QuestionKindSpec(
        ResearchQuestionKind.MEASUREMENT_VALIDITY,
        (GapType.MEASUREMENT_OPERATIONALIZATION,),
        ("construct", "proxy_measure", "target_measure", "mapping_status"),
        ("calibration", "measurement_error", "reference_standard"),
        ("research_object", "measurement_definition", "outcome_definition"),
        ("MEASURES", "PROXIES", "CALIBRATES_TO"),
        ("MEASUREMENT_VALIDATION_PACKAGE",),
    ),
    ResearchQuestionKind.THEORY_MATHEMATICAL: QuestionKindSpec(
        ResearchQuestionKind.THEORY_MATHEMATICAL,
        (GapType.THEORY_MATHEMATICAL,),
        ("formal_claim", "assumption", "validity_domain", "falsification_path"),
        ("proof", "counterexample", "identifiability"),
        ("research_object", "condition_or_regime", "spatial_scale", "temporal_scale"),
        ("ASSUMES", "DERIVES", "VALID_UNDER", "COUNTEREXAMPLE_TO"),
        ("THEORY_VALIDATION_PACKAGE",),
    ),
    ResearchQuestionKind.GENERALIZATION_TRANSPORTABILITY: QuestionKindSpec(
        ResearchQuestionKind.GENERALIZATION_TRANSPORTABILITY,
        (GapType.GENERALIZATION_TRANSPORTABILITY,),
        ("source_domain", "target_domain", "shift_type", "model_or_claim"),
        ("external_validation", "transport_assumption"),
        ("population_or_system", "condition_or_regime", "dataset_or_corpus", "measurement_definition"),
        ("GENERALIZES_TO", "FAILS_UNDER", "VALID_UNDER"),
        ("GENERALIZATION_VALIDATION_PACKAGE",),
    ),
    ResearchQuestionKind.METHOD_DESIGN: QuestionKindSpec(
        ResearchQuestionKind.METHOD_DESIGN,
        (GapType.METHOD_DESIGN,),
        ("current_method", "failure_mode", "bias_or_identification_problem", "evaluation_criterion"),
        ("alternative_design", "comparison_protocol"),
        ("research_object", "method_or_design", "measurement_definition", "outcome_definition"),
        ("FAILS_UNDER", "BIASES", "EVALUATES"),
        ("METHOD_EVALUATION_PACKAGE",),
    ),
    ResearchQuestionKind.DATA_COVERAGE: QuestionKindSpec(
        ResearchQuestionKind.DATA_COVERAGE,
        (GapType.DATA_COVERAGE,),
        ("required_variable", "coverage_dimension", "covered_range", "missing_range", "impact_on_claim"),
        ("acquisition_path", "data_quality"),
        ("population_or_system", "condition_or_regime", "time_window", "dataset_or_corpus"),
        ("COVERS", "OMITS", "REQUIRES"),
        ("DATA_ACQUISITION_PACKAGE",),
    ),
    ResearchQuestionKind.SCALE_INTEGRATION: QuestionKindSpec(
        ResearchQuestionKind.SCALE_INTEGRATION,
        (GapType.SCALE_INTEGRATION,),
        ("source_scale", "target_scale", "bridge_variable", "coupling_question"),
        ("scaling_assumption", "cross_scale_measurement"),
        ("spatial_scale", "temporal_scale", "outcome_definition"),
        ("BRIDGES", "COUPLES_TO", "SCALES_TO"),
        ("SCALE_INTEGRATION_PACKAGE",),
    ),
    ResearchQuestionKind.BENCHMARK_COMPARISON: QuestionKindSpec(
        ResearchQuestionKind.BENCHMARK_COMPARISON,
        (GapType.BENCHMARK_COMPARISON,),
        ("candidate_systems", "common_task", "shared_metric", "comparison_protocol"),
        ("baseline", "dataset_or_corpus"),
        ("method_or_design", "measurement_definition", "dataset_or_corpus", "outcome_definition"),
        ("BENCHMARKS_AGAINST", "EVALUATES", "USES_METRIC"),
        ("BENCHMARK_DESIGN_PACKAGE",),
    ),
    ResearchQuestionKind.TRANSLATION_IMPLEMENTATION: QuestionKindSpec(
        ResearchQuestionKind.TRANSLATION_IMPLEMENTATION,
        (GapType.TRANSLATION_IMPLEMENTATION,),
        ("validated_claim", "deployment_context", "implementation_barrier", "feasibility_question"),
        ("risk", "cost", "real_world_outcome"),
        ("population_or_system", "condition_or_regime", "method_or_design", "outcome_definition"),
        ("DEPLOYS_IN", "CONSTRAINED_BY", "VALIDATES_IN"),
        ("TRANSLATION_FEASIBILITY_PACKAGE",),
    ),
}


_KIND_ALIASES: dict[str, ResearchQuestionKind] = {
    **{item.value.lower(): item for item in ResearchQuestionKind},
    **{item.name.lower(): item for item in ResearchQuestionKind},
    "measurement_operationalization": ResearchQuestionKind.MEASUREMENT_VALIDITY,
    "measurement": ResearchQuestionKind.MEASUREMENT_VALIDITY,
    "theory": ResearchQuestionKind.THEORY_MATHEMATICAL,
    "boundary": ResearchQuestionKind.BOUNDARY_HETEROGENEITY,
    "contradiction": ResearchQuestionKind.CONTRADICTION_REPLICATION,
    "replication": ResearchQuestionKind.CONTRADICTION_REPLICATION,
    "generalization": ResearchQuestionKind.GENERALIZATION_TRANSPORTABILITY,
    "transportability": ResearchQuestionKind.GENERALIZATION_TRANSPORTABILITY,
    "translation": ResearchQuestionKind.TRANSLATION_IMPLEMENTATION,
    "implementation": ResearchQuestionKind.TRANSLATION_IMPLEMENTATION,
}

def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _text(value).lower()).strip("_")


def _unique(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        text = _text(value)
        key = text.lower()
        if text and key not in seen:
            output.append(text)
            seen.add(key)
    return output


def _text_list(value: Any) -> list[str]:
    return _unique(value if isinstance(value, (list, tuple, set)) else [value])


def _domain_taxonomy_nodes(value: Any) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, Mapping):
            continue
        domain_id = _text(item.get("domain") or item.get("id"))
        subfield_id = _text(item.get("subfield"))
        label = _text(item.get("label") or item.get("display_name") or domain_id)
        if domain_id:
            output.append({
                "taxonomy": _text(item.get("taxonomy")) or "internal_research_domain_catalog",
                "id": "/".join(part for part in (domain_id, subfield_id) if part),
                "label": label,
            })
    return output


def build_project_research_domain_contract(
    project: Mapping[str, Any],
) -> ResearchDomainContract:
    """Build the explicit domain contract from the resolved project identity."""

    resolution = project.get("domain_resolution") if isinstance(project.get("domain_resolution"), Mapping) else {}
    research_domains = [
        dict(item)
        for item in resolution.get("research_domains", [])
        if isinstance(item, Mapping)
    ]
    active = _unique(
        item.get("domain") for item in research_domains if _text(item.get("domain"))
    )
    primary = _text(resolution.get("primary_domain")) or (active[0] if active else "")
    identity = resolution.get("research_identity") if isinstance(resolution.get("research_identity"), Mapping) else {}
    context = resolution.get("domain_context") if isinstance(resolution.get("domain_context"), Mapping) else {}
    anchors = _unique([
        *list(identity.get("evidence_spans") or []),
        *list(identity.get("core_entities") or []),
        *list(context.get("retrieval_terms") or []),
        *[
            term
            for item in research_domains
            for term in list(item.get("matched_terms") or [])
        ],
    ])[:24]
    reason_codes: list[str] = []
    if not primary or primary == "general" or not active:
        reason_codes.append("PROJECT_DOMAIN_UNRESOLVED")
    if primary and primary not in active:
        reason_codes.append("PRIMARY_DOMAIN_NOT_ACTIVE")
    if not anchors:
        reason_codes.append("DOMAIN_EVIDENCE_ANCHORS_MISSING")
    try:
        confidence = max(0.0, min(1.0, float(identity.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
        reason_codes.append("DOMAIN_CONFIDENCE_INVALID")
    return {
        "schema_version": RESEARCH_DOMAIN_CONTRACT_VERSION,
        "status": "READY" if not reason_codes else "PENDING",
        "primary_domain_id": primary if not reason_codes else "",
        "active_domain_ids": active if not reason_codes else [],
        "taxonomy_nodes": _domain_taxonomy_nodes(research_domains),
        "source": "project_domain_resolution",
        "evidence_anchors": anchors,
        "confidence": confidence,
        "reason_codes": reason_codes,
    }


def validate_research_domain_contract(value: Any) -> ResearchDomainContract:
    source = value if isinstance(value, Mapping) else {}
    if source.get("schema_version") != RESEARCH_DOMAIN_CONTRACT_VERSION:
        raise ValueError("ResearchQuestionContractV3 requires research_domain_contract_v1")
    status = _text(source.get("status")).upper()
    if status not in {"READY", "PENDING"}:
        raise ValueError("Research-domain contract status must be READY or PENDING")
    provenance = _text(source.get("source"))
    if provenance not in {
        "project_domain_resolution",
        "provider_taxonomy",
        "llm_taxonomy_classification",
    }:
        raise ValueError("Research-domain contract source is invalid")
    primary = _text(source.get("primary_domain_id"))
    active = _text_list(source.get("active_domain_ids"))
    anchors = _text_list(source.get("evidence_anchors"))
    reason_codes = _text_list(source.get("reason_codes"))
    if status == "READY":
        if not primary or primary not in active:
            raise ValueError("READY research-domain contracts require an active primary domain")
        if not anchors:
            raise ValueError("READY research-domain contracts require source-grounded evidence anchors")
    elif not reason_codes:
        raise ValueError("PENDING research-domain contracts require reason_codes")
    taxonomy_nodes: list[dict[str, str]] = []
    for item in source.get("taxonomy_nodes", []) if isinstance(source.get("taxonomy_nodes"), list) else []:
        if not isinstance(item, Mapping):
            continue
        taxonomy = _text(item.get("taxonomy"))
        identifier = _text(item.get("id"))
        label = _text(item.get("label"))
        if taxonomy and label:
            taxonomy_nodes.append({"taxonomy": taxonomy, "id": identifier, "label": label})
    try:
        confidence = max(0.0, min(1.0, float(source.get("confidence") or 0.0)))
    except (TypeError, ValueError) as exc:
        raise ValueError("Research-domain contract confidence must be numeric") from exc
    return {
        "schema_version": RESEARCH_DOMAIN_CONTRACT_VERSION,
        "status": status,
        "primary_domain_id": primary,
        "active_domain_ids": active,
        "taxonomy_nodes": taxonomy_nodes,
        "source": provenance,
        "evidence_anchors": anchors,
        "confidence": confidence,
        "reason_codes": reason_codes,
    }


def _has_scientific_comparison_arm_identity(value: Any) -> bool:
    """Reject labels that identify only a generic comparison position."""

    tokens = re.findall(r"[a-z0-9]+", _text(value).casefold())
    if not tokens:
        return False
    return any(
        not token.isdigit()
        and token not in _GENERIC_COMPARISON_ARM_TOKENS
        and token not in _COMPARISON_ARM_ORDINAL_TOKENS
        for token in tokens
    )


def _normalized_comparison_arm_v4(value: Any, *, field: str) -> dict[str, Any]:
    """Validate a named comparison arm without inferring it from prose."""

    source = value if isinstance(value, Mapping) else {}
    arm_id = _text(source.get("arm_id"))
    canonical_label = _text(source.get("canonical_label"))
    surface_forms = _text_list(source.get("accepted_surface_forms"))
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,79}", arm_id):
        raise ValueError(
            f"comparison_contract_v4.{field}.arm_id must be a stable lower_snake_case identifier"
        )
    if not canonical_label:
        raise ValueError(f"comparison_contract_v4.{field}.canonical_label is required")
    if not _has_scientific_comparison_arm_identity(canonical_label):
        raise ValueError(
            f"comparison_contract_v4.{field}.canonical_label must name a scientifically meaningful arm; "
            "generic placeholders such as Model A, Method 1, or System B are not allowed"
        )
    if not surface_forms:
        raise ValueError(
            f"comparison_contract_v4.{field}.accepted_surface_forms must contain at least one retrievable form"
        )
    non_scientific_forms = [
        form for form in surface_forms
        if not _has_scientific_comparison_arm_identity(form)
    ]
    if non_scientific_forms:
        raise ValueError(
            f"comparison_contract_v4.{field}.accepted_surface_forms must name the same scientifically meaningful arm; "
            "generic placeholders are not retrievable arm identities"
        )
    return {
        "arm_id": arm_id,
        "canonical_label": canonical_label,
        "accepted_surface_forms": surface_forms,
    }


def _normalized_scope_entity_mappings_v4(
    value: Any,
    *,
    scientific_scope: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Normalize explicit source-surface mappings for a comparison scope.

    Scope aliases are a controlled part of the current comparison contract,
    not an opportunity to infer unmentioned entities from a document.  Each
    mapping must point back to the canonical value already declared for its
    scope axis, so later assertion extraction can preserve the source wording
    while retaining an auditable contract binding.
    """

    source = value if isinstance(value, Mapping) else {}
    if not source:
        return {}
    unsupported_axes = set(source) - set(SCOPE_AXES)
    if unsupported_axes:
        raise ValueError(
            "comparison_contract_v4.scope_entity_mappings contains unsupported scope axes: "
            + ", ".join(sorted(str(axis) for axis in unsupported_axes))
        )
    normalized: dict[str, list[dict[str, Any]]] = {}
    for axis, entries in source.items():
        canonical_scope_value = _text(scientific_scope.get(axis))
        if not canonical_scope_value:
            raise ValueError(
                "comparison_contract_v4.scope_entity_mappings may only map a declared scientific_scope axis: "
                + str(axis)
            )
        values = entries if isinstance(entries, list) else []
        if not values:
            raise ValueError(
                "comparison_contract_v4.scope_entity_mappings."
                + str(axis)
                + " must contain at least one explicit mapping"
            )
        normalized_entries: list[dict[str, Any]] = []
        seen_forms: set[str] = set()
        for index, item in enumerate(values):
            mapping = item if isinstance(item, Mapping) else {}
            canonical_value = _text(mapping.get("canonical_value"))
            surface_forms = _text_list(mapping.get("accepted_surface_forms"))
            if _key(canonical_value) != _key(canonical_scope_value):
                raise ValueError(
                    "comparison_contract_v4.scope_entity_mappings."
                    + str(axis)
                    + f"[{index}].canonical_value must equal the declared scientific_scope value"
                )
            if not surface_forms:
                raise ValueError(
                    "comparison_contract_v4.scope_entity_mappings."
                    + str(axis)
                    + f"[{index}].accepted_surface_forms must contain at least one source form"
                )
            duplicate_forms = {
                _key(form) for form in surface_forms
            } & seen_forms
            if duplicate_forms:
                raise ValueError(
                "comparison_contract_v4.scope_entity_mappings."
                    + str(axis)
                    + " must not repeat an accepted surface form"
                )
            seen_forms.update(_key(form) for form in surface_forms)
            normalized_entries.append({
                "mapping_id": _text(mapping.get("mapping_id")) or f"{axis}_{index + 1}",
                "canonical_value": canonical_scope_value,
                "accepted_surface_forms": surface_forms,
            })
        normalized[str(axis)] = normalized_entries
    return normalized


def _normalized_comparison_contract_v4(
    value: Any,
    *,
    question_kind: ResearchQuestionKind,
    scientific_scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize an arm-first comparison obligation.

    A comparison contract names the final arms and the conditions under which
    their independent evidence can be synthesized.  It deliberately does not
    require one source to contain both arms: that is a higher-grade direct-pair
    result, not a prerequisite for retaining evidence about either arm.
    """

    source = value if isinstance(value, Mapping) else {}
    _reject_legacy_comparison_artifacts_v3(source)
    if question_kind != ResearchQuestionKind.BENCHMARK_COMPARISON:
        if source:
            raise ValueError(
                "comparison_contract_v4 is only permitted for BENCHMARK_COMPARISON contracts"
            )
        return {}
    if source.get("schema_version") != COMPARISON_CONTRACT_VERSION:
        raise ValueError(
            "BENCHMARK_COMPARISON requires comparison_contract_v4; generic comparison slots are not a replacement"
        )
    comparison_kind = _text(source.get("comparison_kind")).upper()
    if comparison_kind not in _COMPARISON_KINDS:
        raise ValueError(
            "comparison_contract_v4.comparison_kind must be METHOD_VS_METHOD, MODEL_VS_MODEL, or SYSTEM_VS_SYSTEM"
        )
    primary_arm = _normalized_comparison_arm_v4(
        source.get("primary_arm"), field="primary_arm"
    )
    comparators_source = source.get("comparator_arms")
    if not isinstance(comparators_source, list) or not comparators_source:
        raise ValueError("comparison_contract_v4.comparator_arms must declare at least one named arm")
    comparator_arms = [
        _normalized_comparison_arm_v4(item, field=f"comparator_arms[{index}]")
        for index, item in enumerate(comparators_source)
    ]
    all_arms = [primary_arm, *comparator_arms]
    arm_ids = [item["arm_id"] for item in all_arms]
    if len(set(arm_ids)) != len(arm_ids):
        raise ValueError("comparison_contract_v4 arm_id values must be unique")
    labels = [_key(item["canonical_label"]) for item in all_arms]
    if len(set(labels)) != len(labels):
        raise ValueError("comparison_contract_v4 canonical arm labels must be distinct")

    arm_id_set = set(arm_ids)
    pair_source = source.get("target_comparison_pairs")
    if not isinstance(pair_source, list) or not pair_source:
        raise ValueError("comparison_contract_v4.target_comparison_pairs must explicitly list target pairs")
    pairs: list[list[str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for index, item in enumerate(pair_source):
        pair = _text_list(item)
        if len(pair) != 2 or pair[0] == pair[1]:
            raise ValueError(
                f"comparison_contract_v4.target_comparison_pairs[{index}] must contain two distinct arm ids"
            )
        if not set(pair).issubset(arm_id_set):
            raise ValueError(
                f"comparison_contract_v4.target_comparison_pairs[{index}] references an undeclared arm"
            )
        if primary_arm["arm_id"] not in pair:
            raise ValueError(
                "comparison_contract_v4 target pairs must compare the declared primary arm with a comparator arm"
            )
        normalized_pair = (
            primary_arm["arm_id"],
            pair[1] if pair[0] == primary_arm["arm_id"] else pair[0],
        )
        if normalized_pair in seen_pairs:
            raise ValueError("comparison_contract_v4.target_comparison_pairs must not duplicate an arm pair")
        seen_pairs.add(normalized_pair)
        pairs.append(list(normalized_pair))
    missing_comparators = {
        item["arm_id"] for item in comparator_arms
    } - {pair[1] for pair in pairs}
    if missing_comparators:
        raise ValueError(
            "comparison_contract_v4.target_comparison_pairs must include every comparator arm: "
            + ", ".join(sorted(missing_comparators))
        )

    comparability_axes = _unique(source.get("comparability_axes"))
    if not comparability_axes:
        raise ValueError("comparison_contract_v4.comparability_axes must be explicit")
    unsupported_axes = set(comparability_axes) - set(SCOPE_AXES)
    if unsupported_axes:
        raise ValueError(
            "comparison_contract_v4.comparability_axes contains unsupported scope axes: "
            + ", ".join(sorted(unsupported_axes))
        )
    required_metric_families = _unique(source.get("required_metric_families"))
    if not required_metric_families:
        raise ValueError("comparison_contract_v4.required_metric_families must name at least one metric family")
    if _text(source.get("evidence_acquisition_mode")).upper() != "ARM_FIRST":
        raise ValueError("comparison_contract_v4.evidence_acquisition_mode must be ARM_FIRST")
    if _text(source.get("cross_source_synthesis_mode")).upper() != "COMPARABILITY_GATED":
        raise ValueError("comparison_contract_v4.cross_source_synthesis_mode must be COMPARABILITY_GATED")
    if source.get("direct_pair_evidence_preferred") is not True:
        raise ValueError("comparison_contract_v4.direct_pair_evidence_preferred must be explicitly true")
    scope_entity_mappings = _normalized_scope_entity_mappings_v4(
        source.get("scope_entity_mappings_v4"),
        scientific_scope=(
            scientific_scope if isinstance(scientific_scope, Mapping) else {}
        ),
    )
    identity_material = {
        "schema_version": COMPARISON_CONTRACT_VERSION,
        "comparison_kind": comparison_kind,
        "primary_arm": primary_arm,
        "comparator_arms": comparator_arms,
        "target_comparison_pairs": pairs,
        "evidence_acquisition_mode": "ARM_FIRST",
        "cross_source_synthesis_mode": "COMPARABILITY_GATED",
        "required_metric_families": required_metric_families,
        "comparability_axes": comparability_axes,
        "direct_pair_evidence_preferred": True,
        "scope_entity_mappings": scope_entity_mappings,
    }
    contract_id = _text(source.get("comparison_contract_id")) or (
        "cc_" + sha256(
            json.dumps(identity_material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:20]
    )
    return {
        **identity_material,
        "comparison_contract_id": contract_id,
        "comparison_contract_fingerprint": "sha256:" + sha256(
            json.dumps(identity_material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


_UNSUPPORTED_LEGACY_COMPARISON_FIELDS = frozenset({
    "declared_causal_edge",
    "causal_chain",
    "comparison_core_axis",
    "comparison_axis",
    "gap_search_plan_v2",
    "legacy_gap_state",
})


def _reject_legacy_comparison_artifacts_v3(value: Any) -> None:
    source = value if isinstance(value, Mapping) else {}
    received = sorted(
        field for field in _UNSUPPORTED_LEGACY_COMPARISON_FIELDS if field in source
    )
    if received:
        raise ValueError(
            "CONTRACT_VALIDATION_ERROR: LEGACY_RETRIEVAL_CONTRACT_NOT_SUPPORTED: "
            + ", ".join(received)
        )


def incompatible_retrieval_artifact(
    value: Any,
    *,
    required_schema: str,
    artifact_kind: str,
) -> dict[str, str]:
    """Describe, but never adapt, a V1/V2 retrieval artifact."""

    source = value if isinstance(value, Mapping) else {}
    return {
        "status": "REJECTED_INCOMPATIBLE_RETRIEVAL_ARTIFACT",
        "reason_code": "LEGACY_RETRIEVAL_CONTRACT_NOT_SUPPORTED",
        "artifact_kind": _text(artifact_kind),
        "received_schema": _text(source.get("schema_version")) or "MISSING_SCHEMA_VERSION",
        "required_schema": _text(required_schema),
    }


def _validated_enum(value: Any, enum_type: type[Enum], *, field: str) -> str:
    text = str(value.value).upper() if isinstance(value, Enum) else _text(value).upper()
    allowed = {item.value for item in enum_type}
    if text not in allowed:
        raise ValueError(f"{field} must be one of: {', '.join(sorted(allowed))}")
    return text


def build_provider_outcome_v3(
    *,
    provider: str,
    query_variant_id: str,
    outcome: ProviderOutcomeKind | str,
    attempt: int = 1,
    raw_result_count: int = 0,
    query_fingerprint: str = "",
    diagnostic_code: str = "",
    retry_after_seconds: float | None = None,
) -> dict[str, Any]:
    """Create a typed provider outcome without inferring scientific coverage."""

    normalized_outcome = _validated_enum(outcome, ProviderOutcomeKind, field="outcome")
    return {
        "schema_version": PROVIDER_OUTCOME_VERSION,
        "provider": _text(provider),
        "query_variant_id": _text(query_variant_id),
        "attempt": max(1, int(attempt or 1)),
        "outcome": normalized_outcome,
        "retryable": normalized_outcome in {item.value for item in _RETRYABLE_PROVIDER_OUTCOMES},
        "retry_after_seconds": (
            max(0.0, float(retry_after_seconds)) if retry_after_seconds is not None else None
        ),
        "query_fingerprint": _text(query_fingerprint),
        "raw_result_count": max(0, int(raw_result_count or 0)),
        "diagnostic_code": _text(diagnostic_code),
    }


def validate_provider_outcome_v3(value: Any) -> dict[str, Any]:
    """Validate typed provider state; errors are not success-empty outcomes."""

    source = value if isinstance(value, Mapping) else {}
    if source.get("schema_version") != PROVIDER_OUTCOME_VERSION:
        raise ValueError(json.dumps(
            incompatible_retrieval_artifact(
                source,
                required_schema=PROVIDER_OUTCOME_VERSION,
                artifact_kind="provider_outcome",
            ),
            ensure_ascii=False,
            sort_keys=True,
        ))
    provider = _text(source.get("provider"))
    variant = _text(source.get("query_variant_id"))
    if not provider or not variant:
        raise ValueError("ProviderOutcomeV3 requires provider and query_variant_id")
    outcome = _validated_enum(source.get("outcome"), ProviderOutcomeKind, field="outcome")
    normalized = build_provider_outcome_v3(
        provider=provider,
        query_variant_id=variant,
        outcome=outcome,
        attempt=int(source.get("attempt") or 1),
        raw_result_count=int(source.get("raw_result_count") or 0),
        query_fingerprint=_text(source.get("query_fingerprint")),
        diagnostic_code=_text(source.get("diagnostic_code")),
        retry_after_seconds=source.get("retry_after_seconds"),
    )
    if outcome == ProviderOutcomeKind.SUCCESS_EMPTY.value and normalized["raw_result_count"]:
        raise ValueError("SUCCESS_EMPTY ProviderOutcomeV3 cannot carry provider candidates")
    if outcome == ProviderOutcomeKind.SUCCESS_WITH_CANDIDATES.value and not normalized["raw_result_count"]:
        raise ValueError("SUCCESS_WITH_CANDIDATES ProviderOutcomeV3 requires raw_result_count > 0")
    return normalized


def _normalized_enum(value: Any, allowed: frozenset[str], *, default: str = "") -> str:
    normalized = _text(value).upper()
    return normalized if normalized in allowed else default


def _normalized_slot_definitions(
    value: Any,
    required_slots: list[str],
    *,
    question_kind: str = "",
) -> dict[str, dict[str, Any]]:
    source = value if isinstance(value, dict) else {}
    definitions: dict[str, dict[str, Any]] = {}
    for slot in required_slots:
        raw = source.get(slot) if isinstance(source.get(slot), dict) else {}
        template = _slot_evidence_policy_template(question_kind, slot)
        definitions[slot] = {
            "meaning": _text(raw.get("meaning")),
            "retrieval_concepts": _text_list(raw.get("retrieval_concepts")),
            "minimum_evidence": _text(raw.get("minimum_evidence")),
            "admission_rule": _text(raw.get("admission_rule")),
            "admission_requirements": _normalized_slot_admission_requirements(
                raw.get("admission_requirements"), template["admission_requirements"]
            ),
            "reuse_policy": _normalized_slot_reuse_policy(
                raw.get("reuse_policy"), template["reuse_policy"]
            ),
        }
    return definitions


def _normalized_slot_admission_requirements(value: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    """Normalize source-bound requirements that make a V3 slot admissible.

    These are compiler-owned V3 semantics, not a translation from historic
    causal-chain fields.  They make the existing human/LLM slot definition
    executable by the assertion admission path.
    """

    source = value if isinstance(value, dict) else {}
    return {
        "required_features": _text_list(
            source.get("required_features") or defaults.get("required_features")
        ),
        "allowed_assertion_kinds": _text_list(
            source.get("allowed_assertion_kinds") or defaults.get("allowed_assertion_kinds")
        ),
        "allowed_relation_kinds": _text_list(
            source.get("allowed_relation_kinds") or defaults.get("allowed_relation_kinds")
        ),
        "requires_named_slot_value": bool(
            source.get("requires_named_slot_value", defaults.get("requires_named_slot_value", False))
        ),
        "requires_quantification": bool(
            source.get("requires_quantification", defaults.get("requires_quantification", False))
        ),
        "requires_comparison_relation": bool(
            source.get("requires_comparison_relation", defaults.get("requires_comparison_relation", False))
        ),
        "requires_reference_mapping": bool(
            source.get("requires_reference_mapping", defaults.get("requires_reference_mapping", False))
        ),
    }


def _normalized_slot_reuse_policy(value: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    """Normalize a V3 policy for provider skipping after source admission."""

    source = value if isinstance(value, dict) else {}

    def positive_int(name: str) -> int:
        try:
            return max(1, int(source.get(name, defaults.get(name, 1))))
        except (TypeError, ValueError):
            return max(1, int(defaults.get(name, 1)))

    return {
        "min_admitted_assertion_count": positive_int("min_admitted_assertion_count"),
        "min_distinct_span_count": positive_int("min_distinct_span_count"),
        "min_distinct_paper_count": positive_int("min_distinct_paper_count"),
        "require_independent_confirmation": bool(
            source.get(
                "require_independent_confirmation",
                defaults.get("require_independent_confirmation", False),
            )
        ),
        "allow_same_paper_multi_slot": bool(
            source.get("allow_same_paper_multi_slot", defaults.get("allow_same_paper_multi_slot", True))
        ),
        "coverage_bundle_requirement": _text(
            source.get("coverage_bundle_requirement")
            or defaults.get("coverage_bundle_requirement")
        ),
    }


def _slot_evidence_policy_template(question_kind: str, slot: str) -> dict[str, dict[str, Any]]:
    """Return domain-neutral V3 admission and reuse semantics for one slot."""

    kind = _text(question_kind).upper()
    normalized_slot = _text(slot)
    requirements: dict[str, Any] = {
        "required_features": [
            "source_bound_explicit_assertion",
            "current_scope_anchor",
            "slot_semantic_anchor",
        ],
        "allowed_assertion_kinds": [],
        "allowed_relation_kinds": [],
        "requires_named_slot_value": False,
        "requires_quantification": False,
        "requires_comparison_relation": False,
        "requires_reference_mapping": False,
    }
    policy: dict[str, Any] = {
        "min_admitted_assertion_count": 1,
        "min_distinct_span_count": 1,
        "min_distinct_paper_count": 1,
        "require_independent_confirmation": False,
        "allow_same_paper_multi_slot": True,
        "coverage_bundle_requirement": "",
    }
    named_value_slots = {
        "condition_a", "condition_b", "target_condition", "threshold",
        "proxy_measure", "target_measure", "shared_metric", "common_task",
        "comparable_endpoint", "source_domain", "target_domain", "covered_range",
        "missing_range", "required_variable", "coverage_dimension", "source_scale",
        "target_scale", "bridge_variable", "deployment_context",
    }
    if normalized_slot in named_value_slots:
        requirements["requires_named_slot_value"] = True
    if normalized_slot in {"condition_a", "condition_b", "comparable_endpoint", "comparison_protocol", "common_task", "shared_metric"}:
        requirements["requires_comparison_relation"] = True
    if normalized_slot in {"mapping_status", "proxy_measure", "target_measure"}:
        requirements["requires_reference_mapping"] = True
    if normalized_slot in {"threshold", "evaluation_criterion", "shared_metric", "comparable_endpoint"}:
        requirements["requires_quantification"] = True
    if kind in {
        ResearchQuestionKind.BOUNDARY_HETEROGENEITY.value,
        ResearchQuestionKind.CONTRADICTION_REPLICATION.value,
        ResearchQuestionKind.CAUSAL_IDENTIFICATION.value,
    }:
        policy["require_independent_confirmation"] = True
    if kind == ResearchQuestionKind.MEASUREMENT_VALIDITY.value and normalized_slot == "mapping_status":
        policy["require_independent_confirmation"] = True
    bundle_by_kind = {
        ResearchQuestionKind.BOUNDARY_HETEROGENEITY.value: (
            {"condition_a", "condition_b", "comparable_endpoint"}, "comparison_protocol"
        ),
        ResearchQuestionKind.BENCHMARK_COMPARISON.value: (
            {"candidate_systems", "common_task", "shared_metric", "comparison_protocol"}, "comparison_coverage_bundle_v4"
        ),
        ResearchQuestionKind.MEASUREMENT_VALIDITY.value: (
            {"construct", "proxy_measure", "target_measure", "mapping_status"}, "measurement_mapping"
        ),
    }
    bundle = bundle_by_kind.get(kind)
    if bundle and normalized_slot in bundle[0]:
        policy["coverage_bundle_requirement"] = bundle[1]
    return {"admission_requirements": requirements, "reuse_policy": policy}


def _normalized_joint_slot_groups(
    value: Any,
    *,
    question_kind: str,
    required_slots: list[str],
) -> list[dict[str, Any]]:
    """Compile coherent multi-slot evidence requirements for V3 contracts."""

    source = value if isinstance(value, list) else []
    if _text(question_kind).upper() == ResearchQuestionKind.BENCHMARK_COMPARISON.value:
        if source:
            raise ValueError(
                "BENCHMARK_COMPARISON must use comparison_contract_v4 instead of joint_slot_groups"
            )
        return []
    normalized: list[dict[str, Any]] = []
    known_slots = set(required_slots)
    for item in source:
        if not isinstance(item, dict):
            continue
        slot_ids = _unique(item.get("slot_ids"))
        if len(slot_ids) < 2 or not set(slot_ids).issubset(known_slots):
            continue
        bundle_id = _text(item.get("bundle_id"))
        if not bundle_id:
            continue
        normalized.append({
            "bundle_id": bundle_id,
            "slot_ids": slot_ids,
            "require_same_comparison_unit": bool(item.get("require_same_comparison_unit", True)),
            "require_named_conditions": bool(item.get("require_named_conditions", False)),
            "require_shared_endpoint": bool(item.get("require_shared_endpoint", False)),
        })
    if normalized:
        return normalized
    kind = _text(question_kind).upper()
    templates = {
        ResearchQuestionKind.BOUNDARY_HETEROGENEITY.value: {
            "bundle_id": "comparison_protocol",
            "slot_ids": ["condition_a", "condition_b", "comparable_endpoint"],
            "require_same_comparison_unit": True,
            "require_named_conditions": True,
            "require_shared_endpoint": True,
        },
        ResearchQuestionKind.BENCHMARK_COMPARISON.value: {
            "bundle_id": "comparison_coverage_bundle_v4",
            "slot_ids": ["candidate_systems", "common_task", "shared_metric", "comparison_protocol"],
            "require_same_comparison_unit": True,
            "require_named_conditions": False,
            "require_shared_endpoint": True,
        },
        ResearchQuestionKind.MEASUREMENT_VALIDITY.value: {
            "bundle_id": "measurement_mapping",
            "slot_ids": ["construct", "proxy_measure", "target_measure", "mapping_status"],
            "require_same_comparison_unit": True,
            "require_named_conditions": False,
            "require_shared_endpoint": False,
        },
    }
    template = templates.get(kind)
    if not template or not set(template["slot_ids"]).issubset(known_slots):
        return []
    return [template]


def _normalized_operationalization(value: Any) -> dict[str, str]:
    source = value if isinstance(value, dict) else {}
    return {
        "unit_of_analysis": _text(source.get("unit_of_analysis")),
        "primary_construct": _text(source.get("primary_construct")),
        "operational_measure": _text(source.get("operational_measure")),
        "comparison_unit": _text(source.get("comparison_unit")),
        "decision_rule": _text(source.get("decision_rule")),
    }


def _normalized_independence_contract(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "independent_falsification_target": _text(
            source.get("independent_falsification_target")
        ),
        "overlap_justification": _text(source.get("overlap_justification")),
        "depends_on_candidate_ids": _text_list(source.get("depends_on_candidate_ids")),
        "shared_context_keys": _text_list(source.get("shared_context_keys")),
    }


def _normalized_boundary_contract(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "boundary_variable": _text(source.get("boundary_variable")),
        "condition_a": _text(source.get("condition_a")),
        "condition_b": _text(source.get("condition_b")),
        "controlled_variables": _text_list(source.get("controlled_variables")),
        "comparable_endpoint": _text(source.get("comparable_endpoint")),
    }


def _normalized_measurement_mapping(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "status": _normalized_enum(
            source.get("status"), MAPPING_STATUS_VALUES
        ),
        "construct": _text(source.get("construct")),
        "proxy_measure": _text(source.get("proxy_measure")),
        "target_measure": _text(source.get("target_measure")),
        "mapping_basis": _text(source.get("mapping_basis")),
        "required_source_roles": _text_list(source.get("required_source_roles")),
    }


def _normalized_threshold_governance(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "threshold_source": _normalized_enum(
            source.get("threshold_source"), THRESHOLD_SOURCE_VALUES,
            default="NOT_APPLICABLE",
        ),
        "threshold_definition": _text(source.get("threshold_definition")),
        "allowed_claim": _text(source.get("allowed_claim")),
        "required_source_roles": _text_list(source.get("required_source_roles")),
    }


def normalize_question_kind(value: Any) -> ResearchQuestionKind | None:
    if isinstance(value, ResearchQuestionKind):
        return value
    return _KIND_ALIASES.get(_key(value))


def spec_for(value: Any) -> QuestionKindSpec:
    kind = normalize_question_kind(value)
    if kind is None:
        raise ValueError(f"Unknown research question kind: {_text(value)!r}")
    return QUESTION_KIND_SPECS[kind]


def _scope_value(source: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if isinstance(value, (list, tuple, set)):
            value = "; ".join(_unique(value))
        text = _text(value)
        if text:
            return text
    return ""


def normalize_scope(value: Any, *, project: dict[str, Any] | None = None, sub_hypothesis: dict[str, Any] | None = None) -> dict[str, str]:
    """Normalise a *declared* V3 scope tuple.

    ``scope_tuple`` is part of the question declaration, rather than a place
    to recover missing information from a project's historic SH fields.  All
    axes are therefore materialised, but an omitted value remains empty.  In
    particular this function must not infer scope from causal chains, old
    object/process/outcome slots, or project-level defaults.
    """
    source = value if isinstance(value, dict) else {}
    return {
        "research_object": _scope_value(source, "research_object", "object"),
        "population_or_system": _scope_value(source, "population_or_system", "system", "species_or_system"),
        "sample_or_model": _scope_value(source, "sample_or_model", "model", "model_or_sample"),
        "condition_or_regime": _scope_value(source, "condition_or_regime", "condition", "regime", "stage_or_regime"),
        "intervention_or_exposure": _scope_value(source, "intervention_or_exposure", "exposure", "intervention"),
        "time_window": _scope_value(source, "time_window", "time", "timepoint"),
        "spatial_scale": _scope_value(source, "spatial_scale"),
        "temporal_scale": _scope_value(source, "temporal_scale"),
        "method_or_design": _scope_value(source, "method_or_design", "method", "design"),
        "measurement_definition": _scope_value(source, "measurement_definition", "measurement", "instrument"),
        "outcome_definition": _scope_value(source, "outcome_definition", "outcome", "endpoint"),
        "dataset_or_corpus": _scope_value(source, "dataset_or_corpus", "dataset", "corpus"),
        "theoretical_assumptions": _scope_value(source, "theoretical_assumptions", "assumptions", "theory_assumptions"),
        "comparison_frame": _scope_value(source, "comparison_frame", "comparison", "reference_frame"),
        "deployment_context": _scope_value(source, "deployment_context", "deployment", "implementation_context"),
    }


def _normalize_expected_gap_types(value: Any, kind: ResearchQuestionKind) -> list[str]:
    raw = value if isinstance(value, (list, tuple, set)) else [value]
    output: list[str] = []
    for item in raw:
        gap_type = normalize_gap_type(item)
        if gap_type is not None and gap_type.value not in output:
            output.append(gap_type.value)
    if output:
        return output
    return [item.value for item in QUESTION_KIND_SPECS[kind].expected_gap_types]


def build_research_question_contract(
    project: dict[str, Any],
    sub_hypothesis: dict[str, Any],
    *,
    epistemic_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a new V3 contract from the current SH declaration.

    This is construction for a fresh V3 run, not an adapter for persisted
    legacy artefacts.  In particular, historic input/mediator/outcome fields
    and ``causal_chain`` are intentionally never read here.
    """
    project = project if isinstance(project, dict) else {}
    sub_hypothesis = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    is_existing_v3_declaration = bool(
        isinstance(sub_hypothesis.get("research_question_contract"), dict)
        and sub_hypothesis.get("research_question_contract", {}).get("schema_version")
        == RESEARCH_QUESTION_CONTRACT_VERSION
    )
    # A persisted V3 contract can be an explicit user declaration, but it is
    # never an immutable cache.  Rebuild the canonical contract below on every
    # annotation pass so changes to the SH, its scope, or its evidence slots
    # receive a new declaration hash and invalidate dependent evidence
    # artefacts.  This is not a migration path: only a current V3
    # declaration is considered here.
    existing = sub_hypothesis.get("research_question_contract")
    existing_v3 = (
        validate_research_question_contract(existing)
        if isinstance(existing, dict)
        and existing.get("schema_version") == RESEARCH_QUESTION_CONTRACT_VERSION
        else {}
    )
    profile = epistemic_profile if isinstance(epistemic_profile, dict) else (
        sub_hypothesis.get("epistemic_profile") if isinstance(sub_hypothesis.get("epistemic_profile"), dict) else {}
    )
    question_payload = sub_hypothesis.get("research_question") if isinstance(sub_hypothesis.get("research_question"), dict) else {}
    if not question_payload and not is_existing_v3_declaration:
        raise ValueError(
            "ResearchQuestionContractV3 must be explicitly declared on the "
            "sub-hypothesis; legacy SH fields are not a construction input."
        )
    # When callers provide a complete current-version contract directly, it
    # is the SH declaration.  We preserve its authored fields only when the
    # SH does not declare an overriding field; no historical causal artefact
    # is read or mapped.
    existing_question = existing_v3.get("research_question") if isinstance(existing_v3.get("research_question"), dict) else {}
    question = _text(
        question_payload.get("question_text")
        or question_payload.get("text")
        or existing_question.get("question_text")
    )
    if not question:
        raise ValueError(
            "ResearchQuestionContractV3 requires an explicit "
            "research_question.question_text; historic SH focus or causal "
            "fields are not a substitute."
        )
    kind = (
        normalize_question_kind(question_payload.get("question_kind"))
        or normalize_question_kind(existing_question.get("question_kind"))
    )
    if kind is None:
        raise ValueError(
            "ResearchQuestionContractV3 requires an explicit research_question.question_kind; "
            "the runtime must not infer a question type from legacy SH fields or prose."
        )
    spec = QUESTION_KIND_SPECS[kind]
    object_components = _normalize_object_components(
        question_payload.get("object_components")
        if isinstance(question_payload.get("object_components"), list)
        else existing_question.get("object_components")
    )
    if kind == ResearchQuestionKind.BENCHMARK_COMPARISON:
        _reject_legacy_comparison_artifacts_v3(question_payload)
        _reject_legacy_comparison_artifacts_v3(existing_v3)
    declared_scope = (
        question_payload.get("scientific_scope")
        if isinstance(question_payload.get("scientific_scope"), dict)
        else existing_v3.get("scientific_scope")
        if isinstance(existing_v3.get("scientific_scope"), dict)
        else {}
    )
    scope = normalize_scope(declared_scope)
    declared_domain_contract = (
        question_payload.get("research_domain_contract")
        if isinstance(question_payload.get("research_domain_contract"), Mapping)
        else existing_v3.get("research_domain_contract")
        if isinstance(existing_v3.get("research_domain_contract"), Mapping)
        else build_project_research_domain_contract(project)
    )
    research_domain_contract = validate_research_domain_contract(
        declared_domain_contract
    )
    claim_target = (
        question_payload.get("claim_target")
        if isinstance(question_payload.get("claim_target"), dict)
        else existing_v3.get("claim_target")
        if isinstance(existing_v3.get("claim_target"), dict)
        else {}
    )
    evidence_contract = (
        question_payload.get("evidence_contract")
        if isinstance(question_payload.get("evidence_contract"), dict)
        else existing_v3.get("evidence_contract")
        if isinstance(existing_v3.get("evidence_contract"), dict)
        else {}
    )
    required_slots = _unique(evidence_contract.get("required_slots"))
    if not required_slots:
        raise ValueError(
            "ResearchQuestionContractV3 declarations must explicitly list required_slots; "
            "the runtime does not infer them from the question kind"
        )
    missing_required_slots = [
        slot for slot in spec.required_slots if slot not in required_slots
    ]
    if missing_required_slots:
        raise ValueError(
            "ResearchQuestionContractV3 declaration is missing required slots for "
            f"{kind.value}: " + ", ".join(missing_required_slots)
        )
    slot_definitions = _normalized_slot_definitions(
        question_payload.get("slot_definitions")
        if isinstance(question_payload.get("slot_definitions"), dict)
        else existing_v3.get("slot_definitions"),
        required_slots,
        question_kind=kind.value,
    )
    joint_slot_groups = _normalized_joint_slot_groups(
        question_payload.get("joint_slot_groups")
        if isinstance(question_payload.get("joint_slot_groups"), list)
        else existing_v3.get("joint_slot_groups"),
        question_kind=kind.value,
        required_slots=required_slots,
    )
    comparison_contract = _normalized_comparison_contract_v4(
        question_payload.get("comparison_contract_v4")
        if isinstance(question_payload.get("comparison_contract_v4"), Mapping)
        else existing_v3.get("comparison_contract_v4"),
        question_kind=kind,
        scientific_scope=scope,
    )
    operationalization = _normalized_operationalization(
        question_payload.get("operationalization")
        if isinstance(question_payload.get("operationalization"), dict)
        else existing_v3.get("operationalization"),
    )
    research_role = _normalized_enum(
        question_payload.get("research_role") or existing_v3.get("research_role"),
        RESEARCH_ROLE_VALUES,
    )
    if not research_role:
        raise ValueError("ResearchQuestionContractV3 requires an explicit valid research_role")
    independence_contract = _normalized_independence_contract(
        question_payload.get("independence_contract")
        if isinstance(question_payload.get("independence_contract"), dict)
        else existing_v3.get("independence_contract"),
    )
    boundary_contract = _normalized_boundary_contract(
        question_payload.get("boundary_contract")
        if isinstance(question_payload.get("boundary_contract"), dict)
        else existing_v3.get("boundary_contract"),
    )
    measurement_mapping = _normalized_measurement_mapping(
        question_payload.get("measurement_mapping")
        if isinstance(question_payload.get("measurement_mapping"), dict)
        else existing_v3.get("measurement_mapping"),
    )
    threshold_governance = _normalized_threshold_governance(
        question_payload.get("threshold_governance")
        if isinstance(question_payload.get("threshold_governance"), dict)
        else existing_v3.get("threshold_governance"),
    )
    routing_contract = (
        question_payload.get("routing_contract")
        if isinstance(question_payload.get("routing_contract"), dict)
        else existing_v3.get("routing_contract")
        if isinstance(existing_v3.get("routing_contract"), dict)
        else {}
    )
    # Only a field inside the explicit V3 question declaration is eligible.
    # A top-level legacy causal_model must never be projected into V3.
    raw_causal_model = (
        question_payload.get("causal_model")
        if isinstance(question_payload.get("causal_model"), dict)
        else existing_v3.get("causal_model")
        if isinstance(existing_v3.get("causal_model"), dict)
        else {}
    )
    causal_model = {
        key: raw_causal_model.get(key)
        for key in (
            "exposure", "outcome", "mediators", "moderators", "confounders",
            "alternative_explanations", "target_estimand", "identification_strategy",
        )
        if key in raw_causal_model
    }
    if causal_model and kind not in {
        ResearchQuestionKind.CAUSAL_IDENTIFICATION,
        ResearchQuestionKind.MECHANISM_COMPETITION,
    }:
        raise ValueError(
            "causal_model is permitted only for CAUSAL_IDENTIFICATION or "
            "MECHANISM_COMPETITION research-question contracts"
        )
    declaration = {
        "schema_version": RESEARCH_QUESTION_CONTRACT_VERSION,
        "schema_revision": RESEARCH_QUESTION_CONTRACT_SCHEMA_REVISION,
        "project_id": _text(project.get("project_id")),
        "sub_hypothesis_id": _text(sub_hypothesis.get("id") or sub_hypothesis.get("sub_hypothesis_id")),
        "question_text": question,
        "question_kind": kind.value,
        "target_knowledge_need": _text(question_payload.get("target_knowledge_need") or existing_question.get("target_knowledge_need")) or kind.value,
        "expected_gap_type_priors": _normalize_expected_gap_types(
            question_payload.get("expected_gap_type_priors")
            or existing_question.get("expected_gap_type_priors"),
            kind,
        ),
        "object_components": object_components,
        "scientific_scope": scope,
        "research_domain_contract": research_domain_contract,
        "claim_target": claim_target,
        "evidence_contract": evidence_contract,
        "routing_contract": routing_contract,
        "research_role": research_role,
        "operationalization": operationalization,
        "slot_definitions": slot_definitions,
        "joint_slot_groups": joint_slot_groups,
        "comparison_contract_v4": comparison_contract,
        "independence_contract": independence_contract,
        "boundary_contract": boundary_contract,
        "measurement_mapping": measurement_mapping,
        "threshold_governance": threshold_governance,
        "design_basis_ids": _text_list(
            question_payload.get("design_basis_ids")
            or existing_v3.get("design_basis_ids")
        ),
        "causal_model": causal_model,
    }
    declaration_hash = sha256(json.dumps(declaration, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return validate_research_question_contract(
        {
            "schema_version": RESEARCH_QUESTION_CONTRACT_VERSION,
            "schema_revision": RESEARCH_QUESTION_CONTRACT_SCHEMA_REVISION,
            "contract_id": "rqc_" + declaration_hash[:20],
            "contract_revision": "rqc_rev_" + declaration_hash[:16],
            "declaration_hash": declaration_hash,
            "project_id": _text(project.get("project_id")),
            "sub_hypothesis_id": _text(sub_hypothesis.get("id") or sub_hypothesis.get("sub_hypothesis_id")),
            "research_question": {
                "question_text": question,
                "question_kind": kind.value,
            "target_knowledge_need": declaration["target_knowledge_need"],
            "expected_gap_type_priors": declaration["expected_gap_type_priors"],
            "object_components": object_components,
        },
            "scientific_scope": scope,
            "research_domain_contract": research_domain_contract,
            "claim_target": {
                "claim_kind": _text(claim_target.get("claim_kind")) or kind.value,
                "target_construct": _text(claim_target.get("target_construct")) or scope["research_object"],
                "target_relation": _text(claim_target.get("target_relation")),
                "allowed_claim_strength_ceiling": _text(claim_target.get("allowed_claim_strength_ceiling")) or "descriptive_scope_bound_claim",
            },
            "evidence_contract": {
                "required_slots": required_slots,
                "optional_slots": _unique(evidence_contract.get("optional_slots") or spec.optional_slots),
                "disqualifying_conditions": _unique(evidence_contract.get("disqualifying_conditions") or []),
                "required_comparability_axes": _unique(evidence_contract.get("required_comparability_axes") or spec.required_comparability_axes),
                "permitted_claim_relations": _unique(evidence_contract.get("permitted_claim_relations") or spec.permitted_claim_relations),
                "negative_evidence_requirements": _unique(evidence_contract.get("negative_evidence_requirements") or ["direct_resolution_search", "scope_aligned_disconfirmation_search"]),
            },
            "routing_contract": {
                "allowed_package_kinds": _unique(routing_contract.get("allowed_package_kinds") or spec.package_kinds),
                "can_compete_for_primary_research_package": bool(
                    routing_contract.get("can_compete_for_primary_research_package", True)
                    and research_role not in {"BASELINE_ENABLER", "FOUNDATIONAL_CONTEXT"}
                ),
                "can_compete_for_primary_mechanism_package": bool(
                    spec.primary_mechanism_eligible
                    and routing_contract.get("can_compete_for_primary_mechanism_package", True)
                ),
            },
            "research_role": research_role,
            "operationalization": operationalization,
            "slot_definitions": slot_definitions,
            "joint_slot_groups": joint_slot_groups,
            **({"comparison_contract_v4": comparison_contract} if comparison_contract else {}),
            "independence_contract": independence_contract,
            "boundary_contract": boundary_contract,
            "measurement_mapping": measurement_mapping,
            "threshold_governance": threshold_governance,
            "design_basis_ids": declaration["design_basis_ids"],
            **({"causal_model": causal_model} if causal_model else {}),
            "contract_source": "v3_question_constructor",
        }
    )


def validate_research_question_contract(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    if source.get("schema_version") != RESEARCH_QUESTION_CONTRACT_VERSION:
        raise ValueError("Research-question contract must use research_question_contract_v3; V1/V2 contracts are not accepted")
    if source.get("schema_revision") != RESEARCH_QUESTION_CONTRACT_SCHEMA_REVISION:
        raise ValueError(
            "Research-question contract must use the current v3_2_domain_contract schema revision"
        )
    question = source.get("research_question") if isinstance(source.get("research_question"), dict) else {}
    kind = normalize_question_kind(question.get("question_kind"))
    if kind is None:
        raise ValueError("Research-question contract has an unknown question_kind")
    if kind == ResearchQuestionKind.BENCHMARK_COMPARISON:
        _reject_legacy_comparison_artifacts_v3(source)
    question_text = _text(question.get("question_text"))
    if not question_text:
        raise ValueError("Research-question contract requires non-empty research_question.question_text")
    scope = source.get("scientific_scope") if isinstance(source.get("scientific_scope"), dict) else {}
    research_domain_contract = validate_research_domain_contract(
        source.get("research_domain_contract")
    )
    evidence = source.get("evidence_contract") if isinstance(source.get("evidence_contract"), dict) else {}
    routing = source.get("routing_contract") if isinstance(source.get("routing_contract"), dict) else {}
    causal_model = source.get("causal_model") if isinstance(source.get("causal_model"), dict) else {}
    if causal_model and kind not in {
        ResearchQuestionKind.CAUSAL_IDENTIFICATION,
        ResearchQuestionKind.MECHANISM_COMPETITION,
    }:
        raise ValueError("Non-causal research-question contracts must not carry causal_model")
    expected_gap_types = _normalize_expected_gap_types(question.get("expected_gap_type_priors"), kind)
    required_slots = _unique(evidence.get("required_slots"))
    if not required_slots:
        raise ValueError("Research-question contract requires non-empty evidence_contract.required_slots")
    operationalization = _normalized_operationalization(source.get("operationalization"))
    missing_operationalization = [
        field
        for field in ("unit_of_analysis", "primary_construct", "operational_measure", "decision_rule")
        if not operationalization[field]
    ]
    if missing_operationalization:
        raise ValueError(
            "Research-question contract requires operationalization fields: "
            + ", ".join(missing_operationalization)
        )
    slot_definitions = _normalized_slot_definitions(
        source.get("slot_definitions"), required_slots, question_kind=kind.value
    )
    joint_slot_groups = _normalized_joint_slot_groups(
        source.get("joint_slot_groups"),
        question_kind=kind.value,
        required_slots=required_slots,
    )
    comparison_contract = _normalized_comparison_contract_v4(
        source.get("comparison_contract_v4"),
        question_kind=kind,
        scientific_scope=scope,
    )
    incomplete_slots = [
        slot
        for slot, definition in slot_definitions.items()
        if not definition["meaning"]
        or not definition["retrieval_concepts"]
        or not definition["minimum_evidence"]
        or not definition["admission_rule"]
    ]
    if incomplete_slots:
        raise ValueError(
            "Research-question contract requires operational slot definitions: "
            + ", ".join(incomplete_slots)
        )
    research_role = _normalized_enum(
        source.get("research_role"), RESEARCH_ROLE_VALUES
    )
    if not research_role:
        raise ValueError("Research-question contract requires a valid research_role")
    design_basis_ids = _text_list(source.get("design_basis_ids"))
    if not design_basis_ids:
        raise ValueError(
            "Research-question contract requires design_basis_ids from the V3 design inventory"
        )
    independence_contract = _normalized_independence_contract(
        source.get("independence_contract")
    )
    if not independence_contract["independent_falsification_target"]:
        raise ValueError(
            "Research-question contract requires independence_contract.independent_falsification_target"
        )
    boundary_contract = _normalized_boundary_contract(source.get("boundary_contract"))
    if kind == ResearchQuestionKind.BOUNDARY_HETEROGENEITY:
        missing_boundary_fields = [
            field
            for field in (
                "boundary_variable",
                "condition_a",
                "condition_b",
                "comparable_endpoint",
            )
            if not boundary_contract[field]
        ]
        if missing_boundary_fields:
            raise ValueError(
                "Boundary-heterogeneity contracts require: "
                + ", ".join(missing_boundary_fields)
            )
        if _key(boundary_contract["condition_a"]) == _key(boundary_contract["condition_b"]):
            raise ValueError(
                "Boundary-heterogeneity contracts require distinct condition_a and condition_b"
            )
    measurement_mapping = _normalized_measurement_mapping(
        source.get("measurement_mapping")
    )
    if kind == ResearchQuestionKind.MEASUREMENT_VALIDITY:
        missing_mapping_fields = [
            field
            for field in ("status", "construct", "proxy_measure", "target_measure", "mapping_basis")
            if not measurement_mapping[field]
        ]
        if missing_mapping_fields:
            raise ValueError(
                "Measurement-validity contracts require measurement_mapping fields: "
                + ", ".join(missing_mapping_fields)
            )
    threshold_governance = _normalized_threshold_governance(
        source.get("threshold_governance")
    )
    if research_role == "FALSIFICATION_RULE":
        missing_threshold_fields = [
            field
            for field in ("threshold_definition", "allowed_claim")
            if not threshold_governance[field]
        ]
        if (
            threshold_governance["threshold_source"] == "NOT_APPLICABLE"
            or missing_threshold_fields
        ):
            raise ValueError(
                "FALSIFICATION_RULE contracts require threshold governance with a source, definition, and allowed claim"
            )
    normalized_scope = {axis: _text(scope.get(axis)) for axis in SCOPE_AXES}
    return {
        "schema_version": RESEARCH_QUESTION_CONTRACT_VERSION,
        "schema_revision": RESEARCH_QUESTION_CONTRACT_SCHEMA_REVISION,
        "contract_id": _text(source.get("contract_id")),
        "contract_revision": _text(source.get("contract_revision")),
        "declaration_hash": _text(source.get("declaration_hash")),
        "project_id": _text(source.get("project_id")),
        "sub_hypothesis_id": _text(source.get("sub_hypothesis_id")),
        "research_question_task_id": _text(source.get("research_question_task_id")),
        "alignment_scope_id": _text(source.get("alignment_scope_id")),
        "alignment_scope_revision": _text(source.get("alignment_scope_revision")),
        "object_scope": {
            str(key): _text(item)
            for key, item in (
                source.get("object_scope")
                if isinstance(source.get("object_scope"), Mapping)
                else {}
            ).items()
            if _text(item)
        },
        "research_question": {
            "question_text": question_text,
            "question_kind": kind.value,
            "target_knowledge_need": _text(question.get("target_knowledge_need")),
            "expected_gap_type_priors": expected_gap_types,
            "object_components": _normalize_object_components(question.get("object_components")),
        },
        "scientific_scope": normalized_scope,
        "research_domain_contract": research_domain_contract,
        "claim_target": dict(source.get("claim_target") or {}),
        "evidence_contract": {
            "required_slots": required_slots,
            "optional_slots": _unique(evidence.get("optional_slots")),
            "disqualifying_conditions": _unique(evidence.get("disqualifying_conditions")),
            "required_comparability_axes": _unique(evidence.get("required_comparability_axes")),
            "permitted_claim_relations": _unique(evidence.get("permitted_claim_relations")),
            "negative_evidence_requirements": _unique(evidence.get("negative_evidence_requirements")),
        },
        "routing_contract": {
            "allowed_package_kinds": _unique(routing.get("allowed_package_kinds")),
            "can_compete_for_primary_research_package": bool(routing.get("can_compete_for_primary_research_package")),
            "can_compete_for_primary_mechanism_package": bool(
                routing.get("can_compete_for_primary_mechanism_package")
            ) and kind == ResearchQuestionKind.CAUSAL_IDENTIFICATION,
        },
        "research_role": research_role,
        "operationalization": operationalization,
        "slot_definitions": slot_definitions,
        "joint_slot_groups": joint_slot_groups,
        **({"comparison_contract_v4": comparison_contract} if comparison_contract else {}),
        "independence_contract": independence_contract,
        "boundary_contract": boundary_contract,
        "measurement_mapping": measurement_mapping,
        "threshold_governance": threshold_governance,
        "design_basis_ids": design_basis_ids,
        **({"causal_model": dict(causal_model)} if causal_model else {}),
        "contract_source": _text(source.get("contract_source")) or "v3_question_constructor",
    }


def build_retrieval_obligation_v3(
    contract: Mapping[str, Any],
    *,
    slot_id: str,
    evidence_role: str,
    required_source_role: str,
    required_evidence_modes: Iterable[Any] = (),
) -> dict[str, Any]:
    """Compile a declared V3 contract slot into a retrieval obligation.

    There is intentionally no global causal-edge or comparison requirement.
    The active slot definition and scientific scope are the complete source of
    the obligation's scientific success criteria.
    """

    current = validate_research_question_contract(dict(contract))
    slot = _text(slot_id)
    definitions = current.get("slot_definitions") if isinstance(current.get("slot_definitions"), Mapping) else {}
    definition = definitions.get(slot) if isinstance(definitions.get(slot), Mapping) else {}
    if not slot or slot not in set((current.get("evidence_contract") or {}).get("required_slots") or []):
        raise ValueError("RetrievalObligationV3 requires a declared required slot_id")
    if not definition:
        raise ValueError("RetrievalObligationV3 requires the active slot definition")
    modes = _unique(required_evidence_modes) or ["FULLTEXT_SPAN_REQUIRED"]
    obligation = {
        "schema_version": RETRIEVAL_OBLIGATION_VERSION,
        "research_question_contract_id": _text(current.get("contract_id")),
        "research_question_contract_revision": _text(
            current.get("contract_revision") or current.get("declaration_hash")
        ),
        "slot_id": slot,
        "evidence_role": _text(evidence_role) or "DIRECT",
        "admission_requirement": _text(definition.get("admission_rule")),
        "minimum_evidence": _text(definition.get("minimum_evidence")),
        "source_roles": _unique([required_source_role]),
        "required_evidence_modes": modes,
        "scope_tuple": dict(current.get("scientific_scope") or {}),
        "retrieval_concepts": _unique(definition.get("retrieval_concepts") or []),
        "minimum_direct_assertions": 1,
    }
    comparison_contract = current.get("comparison_contract_v4")
    if isinstance(comparison_contract, Mapping):
        obligation["comparison_contract_id"] = _text(
            comparison_contract.get("comparison_contract_id")
        )
        obligation["comparison_comparability_axes"] = _unique(
            comparison_contract.get("comparability_axes")
        )
    return obligation


def validate_retrieval_obligation_v3(value: Any) -> dict[str, Any]:
    """Validate a V3 obligation and explicitly reject V1/V2 artifacts."""

    source = value if isinstance(value, Mapping) else {}
    if source.get("schema_version") != RETRIEVAL_OBLIGATION_VERSION:
        raise ValueError(json.dumps(
            incompatible_retrieval_artifact(
                source,
                required_schema=RETRIEVAL_OBLIGATION_VERSION,
                artifact_kind="retrieval_obligation",
            ),
            ensure_ascii=False,
            sort_keys=True,
        ))
    required = (
        "research_question_contract_id",
        "research_question_contract_revision",
        "slot_id",
        "evidence_role",
        "admission_requirement",
        "minimum_evidence",
    )
    missing = [field for field in required if not _text(source.get(field))]
    if missing:
        raise ValueError("RetrievalObligationV3 missing required fields: " + ", ".join(missing))
    source_roles = _unique(source.get("source_roles") or [])
    modes = _unique(source.get("required_evidence_modes") or [])
    concepts = _unique(source.get("retrieval_concepts") or [])
    scope = source.get("scope_tuple") if isinstance(source.get("scope_tuple"), Mapping) else {}
    if not source_roles or not modes or not concepts or not scope:
        raise ValueError("RetrievalObligationV3 requires source roles, evidence modes, retrieval concepts, and scope")
    return {
        **dict(source),
        "source_roles": source_roles,
        "required_evidence_modes": modes,
        "retrieval_concepts": concepts,
        "scope_tuple": dict(scope),
        "minimum_direct_assertions": max(1, int(source.get("minimum_direct_assertions") or 1)),
    }


def build_retrieval_work_item_v3(
    contract: Mapping[str, Any],
    *,
    work_item_kind: RetrievalWorkItemKind | str,
    target_slot_ids: Iterable[Any],
    obligations: Iterable[Mapping[str, Any]],
    plan_fingerprint: str,
    gap_candidate_id: str = "",
    gap_candidate_fingerprint: str = "",
    gap_type: str = "",
    graph_snapshot_id: str = "",
) -> dict[str, Any]:
    """Build one non-interchangeable V3 retrieval work item."""

    current = validate_research_question_contract(dict(contract))
    kind = _validated_enum(work_item_kind, RetrievalWorkItemKind, field="work_item_kind")
    slots = _unique(target_slot_ids)
    validated_obligations = [validate_retrieval_obligation_v3(item) for item in obligations]
    if not slots or not validated_obligations:
        raise ValueError("RetrievalWorkItemV3 requires target slots and declared obligations")
    declared_slots = set((current.get("evidence_contract") or {}).get("required_slots") or [])
    if not set(slots).issubset(declared_slots):
        raise ValueError("RetrievalWorkItemV3 target slots must belong to the active contract")
    obligation_slots = {str(item.get("slot_id") or "") for item in validated_obligations}
    if not set(slots).issubset(obligation_slots):
        raise ValueError("RetrievalWorkItemV3 requires an obligation for every target slot")
    candidate_fields = [_text(gap_candidate_id), _text(gap_candidate_fingerprint), _text(gap_type)]
    if kind == RetrievalWorkItemKind.SLOT_RECOVERY.value and any(candidate_fields):
        raise ValueError("SLOT_RECOVERY must not carry a gap candidate identity")
    if kind == RetrievalWorkItemKind.GAP_RESOLUTION.value and not all(candidate_fields):
        raise ValueError("GAP_RESOLUTION requires gap_candidate_id, gap_candidate_fingerprint, and gap_type")
    return {
        "schema_version": RETRIEVAL_WORK_ITEM_VERSION,
        "work_item_kind": kind,
        "project_id": _text(current.get("project_id")),
        "sub_hypothesis_id": _text(current.get("sub_hypothesis_id")),
        "research_question_contract_id": _text(current.get("contract_id")),
        "research_question_contract_revision": _text(
            current.get("contract_revision") or current.get("declaration_hash")
        ),
        "gap_candidate_id": _text(gap_candidate_id),
        "gap_candidate_fingerprint": _text(gap_candidate_fingerprint),
        "gap_type": _text(gap_type),
        "target_slot_ids": slots,
        "obligations": validated_obligations,
        "required_source_roles": _unique(
            role for obligation in validated_obligations for role in obligation["source_roles"]
        ),
        "required_evidence_modes": _unique(
            mode for obligation in validated_obligations for mode in obligation["required_evidence_modes"]
        ),
        "plan_fingerprint": _text(plan_fingerprint),
        "graph_snapshot_id": _text(graph_snapshot_id),
    }


def validate_retrieval_work_item_v3(value: Any) -> dict[str, Any]:
    """Validate an executable V3 work item with no legacy compatibility path."""

    source = value if isinstance(value, Mapping) else {}
    if source.get("schema_version") != RETRIEVAL_WORK_ITEM_VERSION:
        raise ValueError(json.dumps(
            incompatible_retrieval_artifact(
                source,
                required_schema=RETRIEVAL_WORK_ITEM_VERSION,
                artifact_kind="retrieval_work_item",
            ),
            ensure_ascii=False,
            sort_keys=True,
        ))
    kind = _validated_enum(source.get("work_item_kind"), RetrievalWorkItemKind, field="work_item_kind")
    required = (
        "sub_hypothesis_id",
        "research_question_contract_id",
        "research_question_contract_revision",
        "plan_fingerprint",
    )
    missing = [field for field in required if not _text(source.get(field))]
    if missing:
        raise ValueError("RetrievalWorkItemV3 missing required fields: " + ", ".join(missing))
    slots = _unique(source.get("target_slot_ids") or [])
    obligations = [
        validate_retrieval_obligation_v3(item)
        for item in source.get("obligations") or []
        if isinstance(item, Mapping)
    ]
    if not slots or not obligations:
        raise ValueError("RetrievalWorkItemV3 requires target_slot_ids and obligations")
    if kind == RetrievalWorkItemKind.GAP_RESOLUTION.value:
        for field in ("gap_candidate_id", "gap_candidate_fingerprint", "gap_type", "graph_snapshot_id"):
            if not _text(source.get(field)):
                raise ValueError(f"GAP_RESOLUTION RetrievalWorkItemV3 requires {field}")
    elif any(_text(source.get(field)) for field in ("gap_candidate_id", "gap_candidate_fingerprint", "gap_type")):
        raise ValueError("SLOT_RECOVERY RetrievalWorkItemV3 must not carry a gap candidate identity")
    return {
        **dict(source),
        "work_item_kind": kind,
        "target_slot_ids": slots,
        "obligations": obligations,
        "required_source_roles": _unique(source.get("required_source_roles") or []),
        "required_evidence_modes": _unique(source.get("required_evidence_modes") or []),
    }


def is_causal_question_contract(value: Any) -> bool:
    contract = validate_research_question_contract(value)
    return contract["research_question"]["question_kind"] in {
        ResearchQuestionKind.CAUSAL_IDENTIFICATION.value,
        ResearchQuestionKind.MECHANISM_COMPETITION.value,
    }


def expected_gap_types(value: Any) -> list[str]:
    return list(validate_research_question_contract(value)["research_question"]["expected_gap_type_priors"])


def _source_role_for_slot(kind: ResearchQuestionKind, slot: str) -> str:
    """Return a provider-facing evidence role without causal coercion."""
    if kind == ResearchQuestionKind.AUTHOR_STATED_LIMITATION:
        return "FULLTEXT_LIMITATION_OR_FOLLOWUP_EVIDENCE"
    if kind == ResearchQuestionKind.THEORY_MATHEMATICAL:
        return "FORMAL_PRIMARY_SOURCE_EVIDENCE"
    if kind == ResearchQuestionKind.CONTRADICTION_REPLICATION:
        return "INDEPENDENT_COMPARABLE_PRIMARY_EVIDENCE"
    if kind == ResearchQuestionKind.MEASUREMENT_VALIDITY:
        return "MEASUREMENT_OR_CALIBRATION_PRIMARY_EVIDENCE"
    if kind == ResearchQuestionKind.BENCHMARK_COMPARISON:
        return "COMMON_PROTOCOL_OR_BENCHMARK_EVIDENCE"
    if kind == ResearchQuestionKind.DATA_COVERAGE:
        return "DATASET_OR_COVERAGE_PRIMARY_EVIDENCE"
    if kind == ResearchQuestionKind.TRANSLATION_IMPLEMENTATION:
        return "REAL_WORLD_IMPLEMENTATION_EVIDENCE"
    if kind in {ResearchQuestionKind.CAUSAL_IDENTIFICATION, ResearchQuestionKind.MECHANISM_COMPETITION}:
        return "DIRECT_IDENTIFICATION_OR_DISCRIMINATION_EVIDENCE"
    return "DIRECT_PRIMARY_EVIDENCE"


def source_role_for_contract_slot(
    contract: dict[str, Any],
    kind: ResearchQuestionKind,
    slot: str,
) -> str:
    """Respect explicitly governed measurement or threshold source roles."""
    role = _source_role_for_slot(kind, slot)
    mapping = contract.get("measurement_mapping") if isinstance(contract.get("measurement_mapping"), dict) else {}
    threshold = contract.get("threshold_governance") if isinstance(contract.get("threshold_governance"), dict) else {}
    governed_roles = (
        threshold.get("required_source_roles")
        if str(contract.get("research_role") or "") == "FALSIFICATION_RULE"
        else mapping.get("required_source_roles")
        if kind == ResearchQuestionKind.MEASUREMENT_VALIDITY
        else []
    )
    governed_roles = _text_list(governed_roles)
    return governed_roles[0] if governed_roles else role


_SLOT_QUERY_DESIGN_TERMS: dict[str, tuple[str, ...]] = {
    "phenomenon": ("empirical characterization", "observed pattern"),
    "target_object": ("system comparison", "model or population"),
    "target_condition": ("regime boundary", "condition comparison"),
    "direct_observation": ("measurement", "empirical observation"),
    "coverage_dimension": ("coverage", "observed range"),
    "time_window": ("temporal coverage", "time-resolved observation"),
    "author_stated_unknown": ("limitation", "future work"),
    "affected_claim": ("claim evaluation", "evidence limitation"),
    "scope_of_limitation": ("scope boundary", "generalizability"),
    "exposure": ("exposure comparison", "intervention design"),
    "outcome": ("outcome measurement", "effect estimate"),
    "identification_strategy": ("identification strategy", "confounding control"),
    "alternative_explanation": ("alternative explanation", "competing account"),
    "common_input": ("shared condition", "common input"),
    "common_outcome": ("shared outcome", "comparative outcome"),
    "mechanism_a": ("candidate mechanism", "mechanistic evidence"),
    "mechanism_b": ("alternative mechanism", "mechanistic comparison"),
    "discriminating_prediction": ("discriminating prediction", "model comparison"),
    "base_relation": ("baseline relation", "comparative evidence"),
    "boundary_variable": ("boundary variable", "effect heterogeneity"),
    "condition_a": ("condition comparison", "regime contrast"),
    "condition_b": ("condition comparison", "regime contrast"),
    "comparable_endpoint": ("comparable endpoint", "measurement consistency"),
    "shared_claim": ("claim replication", "independent evidence"),
    "result_a": ("independent result", "replication"),
    "result_b": ("independent result", "replication"),
    "comparability_axes": ("comparability", "measurement alignment"),
    "construct": ("construct validation", "measurement validity"),
    "proxy_measure": ("proxy validation", "measurement comparison"),
    "target_measure": ("reference measurement", "calibration"),
    "mapping_status": ("measurement mapping", "calibration"),
    "formal_claim": ("formal derivation", "theoretical result"),
    "assumption": ("assumption validity", "theoretical condition"),
    "validity_domain": ("validity domain", "boundary condition"),
    "falsification_path": ("counterexample", "falsification"),
    "source_domain": ("source setting", "external validation"),
    "target_domain": ("target setting", "transportability"),
    "shift_type": ("distribution shift", "generalization"),
    "model_or_claim": ("model validation", "claim transport"),
    "current_method": ("method evaluation", "performance assessment"),
    "failure_mode": ("failure mode", "method limitation"),
    "bias_or_identification_problem": ("bias assessment", "identification problem"),
    "evaluation_criterion": ("evaluation criterion", "benchmark"),
    "required_variable": ("required variable", "data availability"),
    "covered_range": ("observed range", "coverage"),
    "missing_range": ("missing range", "data gap"),
    "impact_on_claim": ("claim sensitivity", "coverage limitation"),
    "source_scale": ("source scale", "cross-scale"),
    "target_scale": ("target scale", "cross-scale"),
    "bridge_variable": ("coupling variable", "cross-scale relation"),
    "coupling_question": ("scale coupling", "integration"),
    "candidate_systems": ("system comparison", "benchmark"),
    "common_task": ("common task", "comparison protocol"),
    "shared_metric": ("shared metric", "evaluation"),
    "comparison_protocol": ("comparison protocol", "benchmark design"),
    "validated_claim": ("implementation evidence", "external validation"),
    "deployment_context": ("deployment context", "real-world evaluation"),
    "implementation_barrier": ("implementation barrier", "feasibility"),
    "feasibility_question": ("feasibility", "implementation evaluation"),
}


_SLOT_FOCUS_AXES: dict[str, tuple[str, ...]] = {
    "phenomenon": ("target_construct", "measurement_or_outcome"),
    "target_object": ("research_object",),
    "target_condition": ("condition_or_regime", "measurement_or_outcome"),
    "direct_observation": ("measurement_or_outcome",),
    "construct": ("measurement_method", "target_construct", "measurement_or_outcome"),
    "proxy_measure": ("measurement_method", "measurement_or_outcome", "target_construct"),
    "target_measure": ("target_construct", "measurement_or_outcome"),
    "mapping_status": ("measurement_method", "target_construct", "measurement_or_outcome"),
}


_SLOT_PROVIDER_CONTEXT_GROUPS: dict[str, tuple[str, ...]] = {
    "target_condition": ("condition_or_regime",),
    "boundary_variable": ("condition_or_regime",),
    "condition_a": ("condition_or_regime",),
    "condition_b": ("condition_or_regime",),
    "validity_domain": ("condition_or_regime",),
    "source_domain": ("condition_or_regime",),
    "target_domain": ("condition_or_regime",),
    "shift_type": ("condition_or_regime",),
    "coverage_dimension": ("condition_or_regime",),
    "time_window": ("condition_or_regime",),
}


V3_PROVIDER_QUERY_PHRASE_BUDGET = 5


_FOUNDATIONAL_CONTEXT_KIND_BY_QUESTION_KIND: dict[ResearchQuestionKind, str] = {
    ResearchQuestionKind.EMPIRICAL_COVERAGE: "CANONICAL_CONSTRUCT_OR_MEASUREMENT_BASELINE",
    ResearchQuestionKind.AUTHOR_STATED_LIMITATION: "ESTABLISHED_BASELINE_OR_REFERENCE_CONTEXT",
    ResearchQuestionKind.CAUSAL_IDENTIFICATION: "CANONICAL_IDENTIFICATION_OR_MEASUREMENT_BASIS",
    ResearchQuestionKind.MECHANISM_COMPETITION: "CANONICAL_COMPETING_MODEL_FORMULATION",
    ResearchQuestionKind.BOUNDARY_HETEROGENEITY: "BASELINE_MODEL_OR_REFERENCE_REGIME",
    ResearchQuestionKind.CONTRADICTION_REPLICATION: "ESTABLISHED_REPLICATION_OR_REFERENCE_PROTOCOL",
    ResearchQuestionKind.MEASUREMENT_VALIDITY: "REFERENCE_MEASUREMENT_OR_CALIBRATION_BASIS",
    ResearchQuestionKind.THEORY_MATHEMATICAL: "CANONICAL_MODEL_THEOREM_OR_DERIVATION_BASIS",
    ResearchQuestionKind.GENERALIZATION_TRANSPORTABILITY: "ESTABLISHED_TRANSPORT_OR_TRANSFER_FRAMEWORK",
    ResearchQuestionKind.METHOD_DESIGN: "CANONICAL_METHOD_PRINCIPLE",
    ResearchQuestionKind.DATA_COVERAGE: "CANONICAL_DATA_OR_COVERAGE_STANDARD",
    ResearchQuestionKind.SCALE_INTEGRATION: "ESTABLISHED_CROSS_SCALE_OR_COUPLING_FRAMEWORK",
    ResearchQuestionKind.BENCHMARK_COMPARISON: "CANONICAL_BENCHMARK_OR_COMPARISON_PROTOCOL",
    ResearchQuestionKind.TRANSLATION_IMPLEMENTATION: "ESTABLISHED_IMPLEMENTATION_OR_DEPLOYMENT_FRAMEWORK",
}


def _scope_anchor_groups(contract: dict[str, Any]) -> dict[str, list[str]]:
    """Return declared retrieval anchors without conflating their roles.

    ``sample_or_model`` used to be folded into ``research_object``.  That
    made a provider rewrite unable to tell the non-removable scientific object
    from a removable model/context qualifier.  The V3 contract keeps the
    distinction explicit so every query variant can preserve an actual object.
    """

    scope = contract["scientific_scope"]
    claim = contract.get("claim_target") if isinstance(contract.get("claim_target"), dict) else {}
    mapping = (
        contract.get("measurement_mapping")
        if isinstance(contract.get("measurement_mapping"), dict)
        else {}
    )
    question = (
        contract.get("research_question")
        if isinstance(contract.get("research_question"), dict)
        else {}
    )
    measurement_method_values: list[Any] = [scope.get("method_or_design")]
    if _text(question.get("question_kind")) == ResearchQuestionKind.MEASUREMENT_VALIDITY.value:
        measurement_method_values.append(mapping.get("proxy_measure"))
    return {
        "research_object": _unique([scope.get("research_object")]),
        "population_or_system": _unique([scope.get("population_or_system")]),
        "target_construct": _unique([
            claim.get("target_construct"),
        ]),
        "condition_or_regime": _unique([
            scope.get("condition_or_regime"), scope.get("intervention_or_exposure"),
            scope.get("spatial_scale"), scope.get("temporal_scale"), scope.get("time_window"),
        ]),
        "measurement_or_outcome": _unique([
            scope.get("measurement_definition"), scope.get("outcome_definition"),
        ]),
        "measurement_method": _unique(measurement_method_values),
        "sample_or_model": _unique([scope.get("sample_or_model")]),
    }


def _query_blueprint_anchor_groups_v3(contract: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Compile the provider-neutral V3 semantic retrieval blueprint.

    This is intentionally sourced only from the current research-question
    contract.  Project titles, sibling hypotheses, historical searches, and
    legacy causal artefacts are not valid query-term sources.
    """

    groups = _scope_anchor_groups(contract)
    return {
        "required_anchor_groups": {
            "research_object": list(groups.get("research_object") or []),
        },
        "topic_anchor_groups": {
            "target_construct": list(groups.get("target_construct") or []),
            "measurement_or_outcome": list(groups.get("measurement_or_outcome") or []),
        },
        "method_anchor_groups": {
            "measurement_method": list(groups.get("measurement_method") or []),
        },
        "context_anchor_groups": {
            "population_or_system": list(groups.get("population_or_system") or []),
            "condition_or_regime": list(groups.get("condition_or_regime") or []),
            "sample_or_model": list(groups.get("sample_or_model") or []),
        },
    }


def _normalized_retrieval_anchor_groups_v3(value: Any) -> list[list[str]]:
    """Keep the persisted V3 retrieval-anchor collection structurally stable."""

    if not isinstance(value, (list, tuple, set)):
        return []
    groups: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for raw_group in value:
        if not isinstance(raw_group, (list, tuple, set)):
            continue
        normalized = _unique(raw_group)
        key = tuple(item.casefold() for item in normalized)
        if normalized and key not in seen:
            seen.add(key)
            groups.append(normalized[:12])
    return groups


def _retrieval_anchor_contract_v3(
    blueprint_groups: dict[str, dict[str, list[str]]],
    *,
    slot_anchors: Iterable[str] = (),
    design_terms: Iterable[str] = (),
) -> dict[str, Any]:
    """Materialize a typed, provider-neutral V3 retrieval anchor contract."""

    slot_anchor_values = list(slot_anchors)
    design_term_values = list(design_terms)
    required_section = (
        blueprint_groups.get("required_anchor_groups")
        if isinstance(blueprint_groups.get("required_anchor_groups"), dict)
        else {}
    )
    research_object_forms = _normalized_retrieval_anchor_groups_v3(
        [required_section.get("research_object") or []]
    )
    target_forms = _normalized_retrieval_anchor_groups_v3([slot_anchor_values])
    typed_groups: list[dict[str, Any]] = []
    if research_object_forms:
        typed_groups.append({
            "group_id": "research_object",
            "accepted_forms": list(research_object_forms[0]),
            "required": True,
            "match_policy": "provider_normalized_token_sequence_v1",
        })
    if target_forms:
        typed_groups.append({
            "group_id": "target_unknown",
            "accepted_forms": list(target_forms[0]),
            "required": True,
            "match_policy": "provider_normalized_token_sequence_v1",
        })
    optional_design_forms = _normalized_retrieval_anchor_groups_v3([design_term_values])
    if optional_design_forms:
        typed_groups.append({
            "group_id": "evidence_design",
            "accepted_forms": list(optional_design_forms[0]),
            "required": False,
            "match_policy": "provider_normalized_token_sequence_v1",
        })
    allowed_query_terms = _unique([
        *[
            term
            for group in typed_groups
            for term in (group.get("accepted_forms") or [])
        ],
        *slot_anchor_values,
        *design_term_values,
    ])
    return {
        "schema_version": "retrieval_anchor_contract_v3",
        "valid": bool(research_object_forms),
        "required_anchor_groups": typed_groups,
        "allowed_query_terms": allowed_query_terms,
        "anchor_source": "research_question_contract_v3",
        "anchor_match_policy_version": "provider_normalized_token_sequence_v1",
        "provider_query_compilation_policy_version": "provider_query_compilation_v3",
    }


def _query_ast_v3(
    groups: dict[str, list[str]],
    *,
    slot: str,
    slot_definition: dict[str, Any],
    slot_anchors: list[str] | None = None,
    query_mode: str,
    required_source_role: str,
) -> dict[str, Any]:
    """Represent retrieval intent before it is materialized for a provider.

    Providers may only support free-text search, so this is not provider query
    syntax. It records required concepts, alternative term groups, and
    comparability constraints from the declared V3 contract.
    """
    all_of = [
        {"role": "research_object", "terms": list(groups.get("research_object") or [])},
        {
            "role": "slot_requirement",
            "terms": _unique([
                *(slot_definition.get("retrieval_concepts") or []),
                *(slot_anchors or []),
            ]),
        },
        {
            "role": "measurement_method",
            "terms": list(groups.get("measurement_method") or []),
        },
    ]
    any_of = [
        {
            "role": "target_construct_or_measurement",
            "terms": _unique([
                *(groups.get("target_construct") or []),
                *(groups.get("measurement_or_outcome") or []),
            ]),
        },
    ]
    context = [
        {"role": "population_or_system", "terms": list(groups.get("population_or_system") or [])},
        {"role": "condition_or_regime", "terms": list(groups.get("condition_or_regime") or [])},
        {"role": "sample_or_model", "terms": list(groups.get("sample_or_model") or [])},
    ]
    return {
        "schema_version": "retrieval_query_ast_v3",
        "all_of": [entry for entry in all_of if entry["terms"]],
        "any_of": [entry for entry in any_of if entry["terms"]],
        "context": [entry for entry in context if entry["terms"]],
        "exclusions": [],
        "comparability_constraints": {
            "requires_common_comparison_unit": bool(
                contract_value := slot_definition.get("admission_rule")
            ) and "comparison" in _key(contract_value),
            "minimum_evidence": _text(slot_definition.get("minimum_evidence")),
        },
        "query_mode": query_mode,
        "required_source_role": required_source_role,
    }


def _foundation_context_key(contract: dict[str, Any]) -> str:
    """Derive a project-local reusable context key from declared scope only."""
    declared_keys = _text_list(
        (contract.get("independence_contract") or {}).get("shared_context_keys")
        if isinstance(contract.get("independence_contract"), dict)
        else []
    )
    if declared_keys:
        return declared_keys[0]
    groups = _scope_anchor_groups(contract)
    stable = {
        "research_object": groups.get("research_object") or [],
        "target_construct": groups.get("target_construct") or [],
        "measurement_or_outcome": groups.get("measurement_or_outcome") or [],
        "question_kind": str((contract.get("research_question") or {}).get("question_kind") or ""),
    }
    return "sharedctx_" + sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _question_kind_slot_semantic_anchors(
    contract: dict[str, Any],
    slot: str,
) -> list[str]:
    """Return extra anchors only when the current question kind requires them.

    This is not a default causal-edge adapter.  Causal-model fields are read
    solely for causal-identification questions; every other gap type remains
    governed by its own declared slots and retrieval concepts.
    """

    question = (
        contract.get("research_question")
        if isinstance(contract.get("research_question"), dict)
        else {}
    )
    question_kind = str(question.get("question_kind") or "").upper()
    if question_kind != ResearchQuestionKind.CAUSAL_IDENTIFICATION.value:
        return []
    causal = contract.get("causal_model") if isinstance(contract.get("causal_model"), dict) else {}
    values_by_slot = {
        "exposure": [causal.get("exposure")],
        "common_input": [causal.get("exposure")],
        "outcome": [causal.get("outcome")],
        "common_outcome": [causal.get("outcome")],
        "alternative_explanation": [causal.get("alternative_explanations")],
        "mechanism_a": [causal.get("mediators")],
        "mechanism_b": [causal.get("alternative_explanations"), causal.get("confounders")],
        "identification_strategy": [causal.get("identification_strategy")],
    }
    raw_values = values_by_slot.get(slot, [])
    flattened: list[Any] = []
    for value in raw_values:
        if isinstance(value, (list, tuple, set)):
            flattened.extend(value)
        else:
            flattened.append(value)
    return _unique(flattened)


def _contract_slot_anchors(contract: dict[str, Any], slot: str) -> list[str]:
    """Return only slot-specific concepts explicitly declared in V3."""
    definitions = (
        contract.get("slot_definitions")
        if isinstance(contract.get("slot_definitions"), dict)
        else {}
    )
    definition = definitions.get(slot) if isinstance(definitions.get(slot), dict) else {}
    boundary = (
        contract.get("boundary_contract")
        if isinstance(contract.get("boundary_contract"), dict)
        else {}
    )
    mapping = (
        contract.get("measurement_mapping")
        if isinstance(contract.get("measurement_mapping"), dict)
        else {}
    )
    threshold = (
        contract.get("threshold_governance")
        if isinstance(contract.get("threshold_governance"), dict)
        else {}
    )
    values: list[Any] = []
    if slot == "boundary_variable":
        values.append(boundary.get("boundary_variable"))
    elif slot == "condition_a":
        values.extend((boundary.get("boundary_variable"), boundary.get("condition_a")))
    elif slot == "condition_b":
        values.extend((boundary.get("boundary_variable"), boundary.get("condition_b")))
    elif slot == "comparable_endpoint":
        values.append(boundary.get("comparable_endpoint"))
    elif slot in {"construct", "proxy_measure", "target_measure", "mapping_status"}:
        values.extend((
            mapping.get("construct"),
            mapping.get("proxy_measure") if slot == "proxy_measure" else "",
            mapping.get("target_measure") if slot == "target_measure" else "",
            mapping.get("mapping_basis") if slot == "mapping_status" else "",
            mapping.get("status") if slot == "mapping_status" else "",
        ))
    values.append(definition.get("retrieval_concepts"))
    if str(contract.get("research_role") or "") == "FALSIFICATION_RULE":
        values.extend((
            threshold.get("threshold_definition"),
            threshold.get("threshold_source"),
            threshold.get("required_source_roles"),
        ))
    flattened: list[Any] = []
    for value in values:
        if isinstance(value, (list, tuple, set)):
            flattened.extend(value)
        else:
            flattened.append(value)
    return _unique(flattened)


def _provider_query_materialization_v3(
    scope_anchor_groups: dict[str, list[str]],
    *,
    slot: str,
    query_mode: str,
    slot_semantic_anchors: list[str] | None = None,
    slot_anchors: list[str] | None = None,
    requirement: str = "",
) -> dict[str, Any]:
    """Materialize a bounded provider query from a complete V3 blueprint.

    The V3 blueprint remains the exhaustive contract and audit record.  A
    provider query instead needs enough semantic specificity to find papers
    without making every regime, scale, time window, and sample descriptor a
    hard keyword.  Source spans, assertions, and typed slots remain the only
    direct-evidence admission authority.
    """

    groups = scope_anchor_groups
    design_terms = list(_SLOT_QUERY_DESIGN_TERMS.get(slot, ()))
    if not design_terms:
        design_terms = (
            ["independent replication", "comparison", "contradictory evidence"]
            if query_mode == "RESOLUTION_OR_DISCONFIRMATION"
            else ["empirical evidence", "study design"]
        )
    if query_mode == "RESOLUTION_OR_DISCONFIRMATION":
        design_terms.extend(("replication", "contradictory evidence"))
    design_terms = _unique(design_terms)
    if requirement:
        design_terms = _unique([requirement.replace("_", " "), *design_terms])

    preferred_topic_groups = (
        ("measurement_or_outcome", "target_construct")
        if slot in {"direct_observation", "shared_metric", "comparable_endpoint"}
        else ("target_construct", "measurement_or_outcome")
    )
    candidate_terms_by_group: dict[str, list[str]] = {
        "research_object": list(groups.get("research_object") or [])[:1],
        "slot_requirement": _unique([
            *(slot_semantic_anchors or []),
            *(slot_anchors or []),
        ]),
        "measurement_method": list(groups.get("measurement_method") or []),
        "topic": [],
        "context": [],
        "evidence_design": design_terms[:1],
    }
    for group in preferred_topic_groups:
        values = list(groups.get(group) or [])
        if values:
            candidate_terms_by_group["topic"] = values[:1]
            break
    for group in _SLOT_PROVIDER_CONTEXT_GROUPS.get(slot, ()):
        values = list(groups.get(group) or [])
        if values:
            candidate_terms_by_group["context"].append(values[0])

    # A provider query is a compact recall probe, not a serialized copy of the
    # full contract.  Reserve one phrase for each semantic role before adding
    # any optional condition.  This prevents a long list of slot synonyms from
    # crowding out the declared method, measurement target, or evidence design.
    retained_by_group: dict[str, list[str]] = {
        group: [] for group in candidate_terms_by_group
    }
    provider_terms: list[str] = []
    provider_term_groups: list[str] = []
    selected_term_keys: set[str] = set()

    def select_term(group: str) -> None:
        for term in candidate_terms_by_group[group]:
            normalized = term.casefold()
            if (
                not normalized
                or normalized in selected_term_keys
                or len(provider_terms) >= V3_PROVIDER_QUERY_PHRASE_BUDGET
            ):
                continue
            # A shorter phrase fully contained in an already retained phrase
            # adds no retrieval distinction and should not consume a role slot.
            if any(normalized in value.casefold() for value in provider_terms):
                continue
            provider_terms.append(term)
            provider_term_groups.append(group)
            retained_by_group[group].append(term)
            selected_term_keys.add(normalized)
            return

    for group in (
        "research_object",
        "slot_requirement",
        "measurement_method",
        "topic",
        "evidence_design",
        "context",
    ):
        select_term(group)

    all_context_groups = (
        "population_or_system",
        "condition_or_regime",
        "sample_or_model",
    )
    context_groups_retained = [
        group
        for group in all_context_groups
        if any(term in retained_by_group["context"] for term in (groups.get(group) or []))
    ]
    dropped_context_groups = [
        group
        for group in all_context_groups
        if groups.get(group) and group not in context_groups_retained
    ]
    dropped_terms_by_group = {
        group: [
            term
            for term in terms
            if term.casefold() not in {
                selected.casefold() for selected in retained_by_group[group]
            }
        ]
        for group, terms in candidate_terms_by_group.items()
    }
    budget_dropped_anchor_groups = [
        group
        for group, terms in candidate_terms_by_group.items()
        if (
            terms
            and not retained_by_group[group]
            and len(provider_terms) >= V3_PROVIDER_QUERY_PHRASE_BUDGET
        )
    ]
    return {
        "schema_version": "provider_query_materialization_v3",
        "policy": "role_balanced_slot_bounded_semantics",
        "phrase_budget": V3_PROVIDER_QUERY_PHRASE_BUDGET,
        "provider_terms": provider_terms,
        "provider_term_groups": provider_term_groups,
        "retained_anchor_groups": [
            group for group, terms in retained_by_group.items() if terms
        ],
        "dropped_context_groups": dropped_context_groups,
        "retained_terms_by_group": retained_by_group,
        "candidate_terms_by_group": candidate_terms_by_group,
        "dropped_terms_by_group": dropped_terms_by_group,
        "budget_dropped_anchor_groups": budget_dropped_anchor_groups,
        "evidence_design_terms": design_terms,
    }


def slot_focus_axes(slot: str, groups: dict[str, list[str]]) -> list[str]:
    """Return declared axes that distinguish one V3 evidence slot.

    A task's provider query retains sufficient neighboring scope to be
    scientifically meaningful, but its specification must say which declared
    axes make this task different from sibling slots.  This is intentionally
    domain-neutral and does not infer a causal graph for non-causal questions.
    """

    preferred = _SLOT_FOCUS_AXES.get(slot)
    if preferred:
        return [axis for axis in preferred if groups.get(axis)]
    return [axis for axis, values in groups.items() if values]


def retrieval_spec_semantic_fingerprint(spec: dict[str, Any]) -> str:
    """Fingerprint semantic provider intent, never an incidental task identifier."""

    blueprint = spec.get("query_blueprint_v3") if isinstance(spec.get("query_blueprint_v3"), dict) else {}
    retrieval_anchor_contract = (
        spec.get("retrieval_anchor_contract")
        if isinstance(spec.get("retrieval_anchor_contract"), dict)
        else {}
    )
    payload = {
        "slot_identity": _text(spec.get("slot_identity")),
        "target_slot_ids": sorted(_unique(spec.get("target_slot_ids") or [])),
        "query_mode": _text(spec.get("query_mode")),
        "target_slot_ids": sorted(_unique(spec.get("target_slot_ids") or [])),
        "query_blueprint_v3": {
            section: {
                key: sorted(_unique(value))
                for key, value in sorted((blueprint.get(section) or {}).items())
                if isinstance(value, list)
            }
            for section in (
                "required_anchor_groups",
                "topic_anchor_groups",
                "method_anchor_groups",
                "context_anchor_groups",
            )
        },
        "query_ast_v3": (
            blueprint.get("query_ast_v3")
            if isinstance(blueprint.get("query_ast_v3"), dict)
            else {}
        ),
        "slot_focus_axes": sorted(_unique(spec.get("slot_focus_axes") or [])),
        "evidence_design_terms": sorted(_unique(spec.get("evidence_design_terms") or [])),
        "required_source_role": _text(spec.get("required_source_role")),
        "comparison_contract_v4": (
            dict(spec.get("comparison_contract_v4") or {})
            if isinstance(spec.get("comparison_contract_v4"), Mapping)
            else {}
        ),
        "retrieval_anchor_contract": retrieval_anchor_contract,
        "provider_query_compilation_policy_version": str(
            retrieval_anchor_contract.get("provider_query_compilation_policy_version")
            or "provider_query_compilation_v3"
        ),
        "anchor_match_policy_version": str(
            retrieval_anchor_contract.get("anchor_match_policy_version")
            or "provider_normalized_token_sequence_v1"
        ),
    }
    return "sha256:" + sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def retrieval_spec_discovery_fingerprint(spec: dict[str, Any]) -> str:
    """Fingerprint the shareable discovery context of a V3 slot task.

    This deliberately excludes the slot identity and its slot-specific query
    clauses.  It can therefore identify a bounded raw-candidate pool shared
    by neighbouring tasks in one ResearchQuestionContractV3, but it is not an
    evidence identity and must never imply that either slot has been filled.
    """

    blueprint = (
        spec.get("query_blueprint_v3")
        if isinstance(spec.get("query_blueprint_v3"), dict)
        else {}
    )
    retrieval_anchor_contract = (
        spec.get("retrieval_anchor_contract")
        if isinstance(spec.get("retrieval_anchor_contract"), dict)
        else {}
    )
    payload = {
        "query_mode": _text(spec.get("query_mode")),
        "required_source_role": _text(spec.get("required_source_role")),
        "topic_anchor_groups": {
            key: sorted(_unique(value))
            for key, value in sorted(
                (blueprint.get("topic_anchor_groups") or {}).items()
            )
            if isinstance(value, list)
        },
        "context_anchor_groups": {
            key: sorted(_unique(value))
            for key, value in sorted(
                (blueprint.get("context_anchor_groups") or {}).items()
            )
            if isinstance(value, list)
        },
        "method_anchor_groups": {
            key: sorted(_unique(value))
            for key, value in sorted(
                (blueprint.get("method_anchor_groups") or {}).items()
            )
            if isinstance(value, list)
        },
        "provider_query_compilation_policy_version": str(
            retrieval_anchor_contract.get("provider_query_compilation_policy_version")
            or "provider_query_compilation_v3"
        ),
        "anchor_match_policy_version": str(
            retrieval_anchor_contract.get("anchor_match_policy_version")
            or "provider_normalized_token_sequence_v1"
        ),
    }
    return "sha256:" + sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def compile_retrieval_task_spec_v3(
    contract: dict[str, Any],
    *,
    slot: str,
    query_mode: str,
    required_source_role: str,
    requirement: str = "",
) -> dict[str, Any]:
    """Compile one V3 slot into a stable, task-id-free provider specification."""

    groups = _scope_anchor_groups(contract)
    question_kind = ResearchQuestionKind(
        _text((contract.get("research_question") or {}).get("question_kind"))
    )
    comparison_contract = (
        _normalized_comparison_contract_v4(
            contract.get("comparison_contract_v4"),
            question_kind=question_kind,
            scientific_scope=(
                contract.get("scientific_scope")
                if isinstance(contract.get("scientific_scope"), Mapping)
                else {}
            ),
        )
        if question_kind == ResearchQuestionKind.BENCHMARK_COMPARISON
        else {}
    )
    question_kind_slot_anchors = _question_kind_slot_semantic_anchors(contract, slot)
    slot_definition = (
        (contract.get("slot_definitions") or {}).get(slot)
        if isinstance(contract.get("slot_definitions"), dict)
        else {}
    )
    slot_definition = slot_definition if isinstance(slot_definition, dict) else {}
    slot_anchors = _unique([
        *question_kind_slot_anchors,
        *_contract_slot_anchors(contract, slot),
    ])
    materialization = _provider_query_materialization_v3(
        groups,
        slot=slot,
        query_mode=query_mode,
        slot_semantic_anchors=question_kind_slot_anchors,
        slot_anchors=slot_anchors,
        requirement=requirement,
    )
    design_terms = list(materialization["evidence_design_terms"])
    blueprint_groups = _query_blueprint_anchor_groups_v3(contract)
    retrieval_anchor_contract = _retrieval_anchor_contract_v3(
        blueprint_groups,
        slot_anchors=slot_anchors,
        design_terms=design_terms,
    )
    blueprint = {
        "schema_version": "retrieval_query_blueprint_v3",
        **blueprint_groups,
        "query_ast_v3": _query_ast_v3(
            groups,
            slot=slot,
            slot_definition=slot_definition,
            slot_anchors=slot_anchors,
            query_mode=query_mode,
            required_source_role=required_source_role,
        ),
        "slot_identity": slot,
        "slot_focus_axes": slot_focus_axes(slot, groups),
        "slot_evidence_terms": list(design_terms),
        "provider_query_materialization_v3": materialization,
        "query_mode": query_mode,
        "required_source_role": required_source_role,
        "variant_policy": "v3_typed_provider_query_variants_v1",
        **({"comparison_contract_v4": comparison_contract} if comparison_contract else {}),
    }
    provider_query = " ".join(materialization["provider_terms"])
    query_branch = f"{contract['sub_hypothesis_id']}:{slot or requirement or query_mode.lower()}"
    spec = {
        "schema_version": RETRIEVAL_TASK_SPEC_VERSION,
        "provider_query": provider_query,
        "query_branch": query_branch,
        "slot_identity": slot or requirement,
        "slot_focus_axes": slot_focus_axes(slot, groups),
        "scope_anchor_groups": groups,
        "retrieval_anchor_contract": retrieval_anchor_contract,
        "query_blueprint_v3": blueprint,
        "provider_query_materialization_v3": materialization,
        "evidence_design_terms": design_terms,
        "counterevidence_terms": (
            ["replication", "comparison", "contradiction", "validation"]
            if query_mode == "RESOLUTION_OR_DISCONFIRMATION"
            else []
        ),
        "query_mode": query_mode,
        "required_source_role": required_source_role,
        **({"comparison_contract_v4": comparison_contract} if comparison_contract else {}),
    }
    spec["semantic_fingerprint"] = retrieval_spec_semantic_fingerprint(spec)
    spec["discovery_fingerprint"] = retrieval_spec_discovery_fingerprint(spec)
    return spec


def compile_independent_confirmation_retrieval_spec_v3(
    contract: dict[str, Any],
    *,
    slot: str,
    required_source_role: str,
    missing_policy_requirements: Iterable[str] = (),
) -> dict[str, Any]:
    """Compile one V3 independent-confirmation retrieval specification.

    This is a narrow evidence-quality continuation for a partially satisfied
    positive slot.  It has no relation to the historic causal repair planner.
    """

    spec = compile_retrieval_task_spec_v3(
        contract,
        slot=slot,
        query_mode="POSITIVE_EVIDENCE",
        required_source_role=required_source_role,
        requirement="independent confirmation validation comparison",
    )
    terms = list((spec.get("provider_query_materialization_v3") or {}).get("provider_terms") or [])
    terms.extend(["independent", "validation", "comparison"])
    terms = _unique(terms)
    materialization = dict(spec.get("provider_query_materialization_v3") or {})
    materialization["provider_terms"] = terms
    materialization["independent_confirmation_requirement_ids"] = _unique(
        missing_policy_requirements
    )
    spec["provider_query_materialization_v3"] = materialization
    spec["provider_query"] = " ".join(terms)
    blueprint = dict(spec.get("query_blueprint_v3") or {})
    blueprint["provider_query_materialization_v3"] = dict(materialization)
    blueprint["slot_evidence_terms"] = _unique([
        *list(blueprint.get("slot_evidence_terms") or []),
        "independent", "validation", "comparison",
    ])
    blueprint["retrieval_purpose"] = "INDEPENDENT_CONFIRMATION"
    spec["query_blueprint_v3"] = blueprint
    spec["query_branch"] = f"{contract['sub_hypothesis_id']}:{slot}:independent_confirmation"
    spec["retrieval_purpose"] = "INDEPENDENT_CONFIRMATION"
    spec["semantic_fingerprint"] = "sha256:" + sha256(
        json.dumps({
            "base_semantic_fingerprint": spec.get("semantic_fingerprint"),
            "slot": slot,
            "purpose": "INDEPENDENT_CONFIRMATION",
            "missing_policy_requirements": materialization["independent_confirmation_requirement_ids"],
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    # This task uses a deliberately new confirmation query.  It must not
    # borrow the ordinary positive-slot discovery pool as a substitute for an
    # independent search.
    spec["discovery_fingerprint"] = "sha256:" + sha256(
        json.dumps({
            "semantic_fingerprint": spec["semantic_fingerprint"],
            "purpose": "INDEPENDENT_CONFIRMATION",
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return spec


def build_foundational_context_contract_v3(contract: dict[str, Any]) -> dict[str, Any]:
    """Create a V3-native L1 context task without causal-bridge semantics."""

    groups = _scope_anchor_groups(contract)
    object_anchors = list(groups["research_object"])
    construct_anchors = list(groups["target_construct"])
    applicable = bool(object_anchors and construct_anchors)
    question_kind = ResearchQuestionKind(contract["research_question"]["question_kind"])
    return {
        "schema_version": FOUNDATIONAL_CONTEXT_CONTRACT_VERSION,
        "foundation_kind": _FOUNDATIONAL_CONTEXT_KIND_BY_QUESTION_KIND[question_kind],
        "research_object_anchors": object_anchors,
        "target_construct_anchors": construct_anchors,
        "condition_or_regime_anchors": list(groups["condition_or_regime"]),
        "candidate_target": 2,
        "maximum_import_attempts": 6,
        "maximum_admitted": 1,
        "admission_role": "FOUNDATIONAL_CONTEXT",
        "shared_context_key": _foundation_context_key(contract),
        "counts_as_direct_primary_evidence": False,
        "counts_toward_core_slot_readiness": False,
        "status": (
            "FOUNDATIONAL_CONTEXT_RETRIEVAL_REQUIRED"
            if applicable else "FOUNDATIONAL_CONTEXT_NOT_APPLICABLE"
        ),
        "not_applicable_reason": (
            "A V3 foundational-context task requires declared research-object and target-construct anchors."
            if not applicable else ""
        ),
    }


def build_question_retrieval_plan(value: Any) -> dict[str, Any]:
    """Build V3 slot-recovery work items from the current evidence contract.

    Initial SH retrieval is strictly ``SLOT_RECOVERY``.  Candidate-specific
    resolution searches are deliberately absent here because they require a
    ``gap_search_plan_v3`` and a candidate identity from semantic audit.
    """
    contract = validate_research_question_contract(value)
    question = contract["research_question"]
    evidence = contract["evidence_contract"]
    kind = ResearchQuestionKind(question["question_kind"])
    slot_tasks: list[dict[str, Any]] = []
    if kind == ResearchQuestionKind.BENCHMARK_COMPARISON:
        # Query variants emitted from this one task independently collect each
        # declared arm, direct pairs, and comparability bridges.  Completing a
        # comparison is deliberately deferred to the cross-source synthesis
        # audit; a result about one arm is useful evidence, not a failed pair.
        comparison_slots = list(evidence["required_slots"])
        anchor_slot = "candidate_systems"
        source_role = source_role_for_contract_slot(contract, kind, anchor_slot)
        spec = compile_retrieval_task_spec_v3(
            contract,
            slot=anchor_slot,
            query_mode="POSITIVE_EVIDENCE",
            required_source_role=source_role,
        )
        spec["target_slot_ids"] = list(comparison_slots)
        spec["query_branch"] = (
            f"{contract['sub_hypothesis_id']}:arm_first_comparison_evidence"
        )
        spec["semantic_fingerprint"] = retrieval_spec_semantic_fingerprint(spec)
        spec["discovery_fingerprint"] = retrieval_spec_discovery_fingerprint(spec)
        obligations = [
            build_retrieval_obligation_v3(
                contract,
                slot_id=slot,
                evidence_role="DIRECT",
                required_source_role=source_role_for_contract_slot(contract, kind, slot),
            )
            for slot in comparison_slots
        ]
        work_item = build_retrieval_work_item_v3(
            contract,
            work_item_kind=RetrievalWorkItemKind.SLOT_RECOVERY,
            target_slot_ids=comparison_slots,
            obligations=obligations,
            plan_fingerprint=str(spec["semantic_fingerprint"]),
        )
        slot_tasks.append({
            "task_id": "rqtask_" + sha256(
                f"{contract['contract_id']}|arm_first_comparison_evidence".encode("utf-8")
            ).hexdigest()[:16],
            "slot": anchor_slot,
            "target_slot_ids": list(comparison_slots),
            "work_item_kind": RetrievalWorkItemKind.SLOT_RECOVERY.value,
            "query_mode": "POSITIVE_EVIDENCE",
            "required_source_role": source_role,
            "required_source_types": ["fulltext", "primary_study"],
            "reuse_policy": dict(
                (contract.get("slot_definitions") or {}).get(anchor_slot, {}).get("reuse_policy") or {}
            ),
            "retrieval_obligation_v3": obligations[0],
            "retrieval_obligations_v3": obligations,
            "retrieval_work_item_v3": work_item,
            "retrieval_spec_v3": spec,
            "result_interpretation": (
                "An arm-specific result may create ArmEvidenceAssertion coverage. "
                "Only a same-study direct pair or a comparability-gated cross-source "
                "synthesis may create a comparative conclusion."
            ),
        })
    else:
        for slot in evidence["required_slots"]:
            source_role = source_role_for_contract_slot(contract, kind, slot)
            spec = compile_retrieval_task_spec_v3(
                contract,
                slot=slot,
                query_mode="POSITIVE_EVIDENCE",
                required_source_role=source_role,
            )
            obligation = build_retrieval_obligation_v3(
                contract,
                slot_id=slot,
                evidence_role="DIRECT",
                required_source_role=source_role,
            )
            work_item = build_retrieval_work_item_v3(
                contract,
                work_item_kind=RetrievalWorkItemKind.SLOT_RECOVERY,
                target_slot_ids=[slot],
                obligations=[obligation],
                plan_fingerprint=str(spec["semantic_fingerprint"]),
            )
            slot_tasks.append(
                {
                    "task_id": "rqtask_" + sha256(
                        f"{contract['contract_id']}|slot_recovery|{slot}".encode("utf-8")
                    ).hexdigest()[:16],
                    "slot": slot,
                    "target_slot_ids": [slot],
                    "work_item_kind": RetrievalWorkItemKind.SLOT_RECOVERY.value,
                    "query_mode": "POSITIVE_EVIDENCE",
                    "required_source_role": source_role,
                    "required_source_types": ["fulltext", "primary_study"],
                    "reuse_policy": dict(
                        (contract.get("slot_definitions") or {}).get(slot, {}).get("reuse_policy") or {}
                    ),
                    "retrieval_obligation_v3": obligation,
                    "retrieval_obligations_v3": [obligation],
                    "retrieval_work_item_v3": work_item,
                    "retrieval_spec_v3": spec,
                    "result_interpretation": "A source-bound result may fill this evidence slot; no result is a coverage diagnostic only.",
                }
            )
    research_question_tasks = build_research_question_tasks(contract)
    object_tasks = [
        item for item in research_question_tasks
        if item.get("task_kind") == "OBJECT"
    ]
    if len(object_tasks) > 1:
        scoped_slot_tasks: list[dict[str, Any]] = []
        for object_task in object_tasks:
            object_id = str(object_task.get("task_id") or "")
            object_text = _text(object_task.get("research_object"))
            for base_task in slot_tasks:
                task = dict(base_task)
                task["task_id"] = f"{base_task.get('task_id')}:{object_id}"
                task["object_task_id"] = object_id
                task["object_scope"] = {
                    "research_object": object_text,
                    "population_or_system": _text(object_task.get("population_or_system")),
                    "prediction_horizon": _text(object_task.get("prediction_horizon")),
                    "measurement_definition": _text(object_task.get("measurement_definition")),
                    "outcome_definition": _text(object_task.get("outcome_definition")),
                    "data_quality_dimension": _text(object_task.get("data_quality_dimension")),
                    "data_quantity_dimension": _text(object_task.get("data_quantity_dimension")),
                }
                spec = dict(task.get("retrieval_spec_v3") or {})
                if object_text:
                    provider_query = _text(spec.get("provider_query"))
                    spec["provider_query"] = f"({object_text}) AND ({provider_query})" if provider_query else object_text
                spec["query_branch"] = f"{_text(spec.get('query_branch'))}:{object_id}"
                spec["object_task_id"] = object_id
                spec["semantic_fingerprint"] = retrieval_spec_semantic_fingerprint(spec)
                spec["discovery_fingerprint"] = retrieval_spec_discovery_fingerprint(spec)
                task["retrieval_spec_v3"] = spec
                obligation = dict(task.get("retrieval_obligation_v3") or {})
                obligation["scope_tuple"] = {
                    **dict(obligation.get("scope_tuple") or {}),
                    "research_object": object_text,
                    "population_or_system": _text(object_task.get("population_or_system")),
                    "time_window": _text(object_task.get("prediction_horizon")),
                    "measurement_definition": _text(object_task.get("measurement_definition")),
                    "outcome_definition": _text(object_task.get("outcome_definition")),
                }
                task["retrieval_obligation_v3"] = obligation
                task["retrieval_obligations_v3"] = [obligation]
                scoped_slot_tasks.append(task)
        slot_tasks = scoped_slot_tasks
    plan_revision = "rqr_rev_" + sha256(
        f"{contract['contract_revision']}|{RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "schema_version": RESEARCH_QUESTION_RETRIEVAL_PLAN_VERSION,
        "plan_revision": plan_revision,
        "query_compiler_version": "slot_obligation_query_compiler_v3",
        "scheduler_policy": "round_robin_by_subhypothesis_v3",
        "deduplication_policy": "work_item_and_contract_revision_scoped_v3",
        "project_id": str(contract.get("project_id") or ""),
        "research_question_contract_id": contract["contract_id"],
        "research_question_contract_revision": str(
            contract.get("contract_revision") or contract.get("declaration_hash") or ""
        ),
        "sub_hypothesis_id": contract["sub_hypothesis_id"],
        "question_kind": question["question_kind"],
        "research_role": str(contract.get("research_role") or "PRIMARY_QUESTION"),
        "design_basis_ids": list(contract.get("design_basis_ids") or []),
        "shared_context_keys": list(
            (contract.get("independence_contract") or {}).get("shared_context_keys")
            or []
        ),
        "expected_gap_type_priors": list(question["expected_gap_type_priors"]),
        "slot_tasks": slot_tasks,
        "tasks": list(slot_tasks),
        "research_question_tasks": research_question_tasks,
        "gap_resolution_requirements": list(evidence["negative_evidence_requirements"]),
        "scope_guard": {
            "required_comparability_axes": list(evidence["required_comparability_axes"]),
            "scope_tuple": contract["scientific_scope"],
        },
        "operationalization": dict(contract.get("operationalization") or {}),
        "slot_definitions": dict(contract.get("slot_definitions") or {}),
        "joint_slot_groups": list(contract.get("joint_slot_groups") or []),
        **({
            "comparison_contract_v4": dict(contract.get("comparison_contract_v4") or {}),
            "comparison_execution_policy": "arm_first_parallel_evidence_then_comparability_audit_v4",
        } if isinstance(contract.get("comparison_contract_v4"), Mapping) else {}),
        "independence_contract": dict(contract.get("independence_contract") or {}),
        "threshold_governance": dict(contract.get("threshold_governance") or {}),
        "rule": "A missing result from one query is a retrieval diagnostic, never evidence that a scientific gap exists.",
        "execution_contract": {
            "deduplicate_by": "semantic_fingerprint_then_candidate_identity_without_slot_completion_inference",
            "slot_admission_policy": "assertion_level_slot_support_and_reuse_policy_v3",
            "required_result_fields": [
                "task_id", "retrieval_work_item_v3", "executed_query",
                "query_fingerprint", "source_ids", "coverage_status",
            ],
            "no_result_status": "RETRIEVAL_COVERAGE_DIAGNOSTIC_ONLY",
            "prohibited_inference": "No retrieval task may convert an empty result set into a scientific-gap verdict.",
            "incompatible_artifact_policy": "V1/V2 retrieval plans, task specs, statuses, cache keys, and gap artifacts are rejected; they are never adapted or reused.",
            "gap_resolution_policy": "GAP_RESOLUTION can be compiled only from a current gap_search_plan_v3 with a candidate identity.",
        },
    }
