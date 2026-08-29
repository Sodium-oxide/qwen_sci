"""Domain-neutral research-gap ontology and qualification contracts.

The evidence graph is deliberately allowed to recall broad *candidates*.  This
module owns the stricter vocabulary used after recall: a gap's scientific type,
the provenance of its signal, semantic status, evidence maturity, and workflow
route are separate dimensions.  No domain keywords, legacy project migrations,
or subject-specific exceptions live here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, TypedDict


class GapType(str, Enum):
    EMPIRICAL_COVERAGE = "EMPIRICAL_COVERAGE_GAP"
    AUTHOR_STATED_LIMITATION = "AUTHOR_STATED_LIMITATION_GAP"
    CAUSAL_IDENTIFICATION = "CAUSAL_IDENTIFICATION_GAP"
    MECHANISM_COMPETITION = "MECHANISM_COMPETITION_GAP"
    BOUNDARY_HETEROGENEITY = "BOUNDARY_HETEROGENEITY_GAP"
    CONTRADICTION_REPLICATION = "CONTRADICTION_REPLICATION_GAP"
    MEASUREMENT_OPERATIONALIZATION = "MEASUREMENT_OPERATIONALIZATION_GAP"
    THEORY_MATHEMATICAL = "THEORY_MATHEMATICAL_GAP"
    GENERALIZATION_TRANSPORTABILITY = "GENERALIZATION_TRANSPORTABILITY_GAP"
    METHOD_DESIGN = "METHOD_DESIGN_GAP"
    DATA_COVERAGE = "DATA_COVERAGE_GAP"
    SCALE_INTEGRATION = "SCALE_INTEGRATION_GAP"
    BENCHMARK_COMPARISON = "BENCHMARK_COMPARISON_GAP"
    TRANSLATION_IMPLEMENTATION = "TRANSLATION_IMPLEMENTATION_GAP"


# Subtypes are controlled vocabularies rather than detector-local free text.
# They let a downstream package distinguish, for example, proxy validity from
# calibration without collapsing either one into a causal mediator claim.
class CausalGapSubtype(str, Enum):
    CAUSAL_DIRECTION_UNIDENTIFIED = "CAUSAL_DIRECTION_UNIDENTIFIED"
    CONFOUNDING_UNRESOLVED = "CONFOUNDING_UNRESOLVED"
    MEDIATION_UNRESOLVED = "MEDIATION_UNRESOLVED"
    MODERATION_UNRESOLVED = "MODERATION_UNRESOLVED"
    INTERVENTION_EFFECT_UNTESTED = "INTERVENTION_EFFECT_UNTESTED"
    IDENTIFICATION_DESIGN_MISSING = "IDENTIFICATION_DESIGN_MISSING"


class MeasurementGapSubtype(str, Enum):
    PROXY_VALIDITY = "PROXY_VALIDITY"
    CALIBRATION = "CALIBRATION"
    CROSS_INSTRUMENT_COMPARABILITY = "CROSS_INSTRUMENT_COMPARABILITY"
    LABEL_RELIABILITY = "LABEL_RELIABILITY"
    MEASUREMENT_ERROR = "MEASUREMENT_ERROR"


class BoundaryGapSubtype(str, Enum):
    REGIME_BOUNDARY = "REGIME_BOUNDARY"
    SCALE_DEPENDENCE = "SCALE_DEPENDENCE"
    POPULATION_HETEROGENEITY = "POPULATION_HETEROGENEITY"
    ENVIRONMENT_DEPENDENCE = "ENVIRONMENT_DEPENDENCE"
    TEMPORAL_NONSTATIONARITY = "TEMPORAL_NONSTATIONARITY"


class TheoryGapSubtype(str, Enum):
    ASSUMPTION_UNTESTED = "ASSUMPTION_UNTESTED"
    THEOREM_EXTENSION = "THEOREM_EXTENSION"
    COUNTEREXAMPLE_UNKNOWN = "COUNTEREXAMPLE_UNKNOWN"
    IDENTIFIABILITY = "IDENTIFIABILITY"
    MODEL_EQUIVALENCE = "MODEL_EQUIVALENCE"


GAP_SUBTYPES_BY_TYPE: dict[GapType, frozenset[str]] = {
    GapType.EMPIRICAL_COVERAGE: frozenset({"DIRECT_EVIDENCE_ABSENT", "CONDITION_COVERAGE_ABSENT", "LONGITUDINAL_COVERAGE_ABSENT"}),
    GapType.AUTHOR_STATED_LIMITATION: frozenset({"EXPLICIT_EDGE_UNKNOWN", "DECLARED_MISSING_EDGE", "UNTESTED_LIMITATION"}),
    GapType.CAUSAL_IDENTIFICATION: frozenset(item.value for item in CausalGapSubtype),
    GapType.MECHANISM_COMPETITION: frozenset({"COMPETING_MECHANISMS", "DISCRIMINATING_TEST_MISSING"}),
    GapType.BOUNDARY_HETEROGENEITY: frozenset({*(item.value for item in BoundaryGapSubtype), "CONTEXT_DEPENDENT_EFFECT"}),
    GapType.CONTRADICTION_REPLICATION: frozenset({"OPPOSITE_POLARITY", "EFFECT_SIZE_DISCREPANCY", "REPLICATION_FAILURE"}),
    GapType.MEASUREMENT_OPERATIONALIZATION: frozenset(item.value for item in MeasurementGapSubtype),
    GapType.THEORY_MATHEMATICAL: frozenset(item.value for item in TheoryGapSubtype),
    GapType.GENERALIZATION_TRANSPORTABILITY: frozenset({"COVARIATE_SHIFT", "LABEL_SHIFT", "CONCEPT_SHIFT", "STRUCTURAL_SHIFT", "EXTERNAL_VALIDATION_MISSING"}),
    GapType.METHOD_DESIGN: frozenset({"BIAS_UNRESOLVED", "IDENTIFICATION_FAILURE", "COMPUTATIONAL_LIMIT", "PROTOCOL_FAILURE"}),
    GapType.DATA_COVERAGE: frozenset({"VARIABLE_MISSING", "POPULATION_COVERAGE", "REGIME_COVERAGE", "TIME_HORIZON_COVERAGE"}),
    GapType.SCALE_INTEGRATION: frozenset({"CROSS_SCALE_COUPLING", "CROSS_CONTEXT_COUPLING", "SCALE_BRIDGE_MISSING"}),
    GapType.BENCHMARK_COMPARISON: frozenset({"COMMON_TASK_MISSING", "SHARED_METRIC_MISSING", "PROTOCOL_MISSING"}),
    GapType.TRANSLATION_IMPLEMENTATION: frozenset({"DEPLOYMENT_FEASIBILITY", "IMPLEMENTATION_BARRIER", "REAL_WORLD_VALIDATION_MISSING"}),
}


class GapCandidate(TypedDict, total=False):
    """Canonical v2 candidate surface shared by every detector and package.

    ``gap_assessment`` remains the authority for mutable adjudication fields;
    the top-level copies are synchronised projections for agents, reporting,
    and schema consumers.  This prevents a caller from treating a legacy
    ``gap_state`` as an alternative authority.
    """

    schema_version: str
    gap_id: str
    candidate_identity: str
    gap_type: str
    gap_subtype: str
    signal_type: str
    candidate_stage: str
    route: str
    research_question: dict[str, Any]
    evidence_refs: list[dict[str, str]]
    source_span_refs: list[dict[str, str]]
    detection_context_ref: dict[str, Any]
    detection_provenance: dict[str, Any]
    type_payload: dict[str, Any]
    semantic_assessment: dict[str, Any]
    retrieval_assessment: dict[str, Any]
    qualification: dict[str, Any]
    primary_source_span_gate: dict[str, Any]
    gap_assessment: dict[str, Any]
    assessment_version: int
    retrieval_version: int
    package_version: int


class GapSignalType(str, Enum):
    AUTHOR_STATED = "AUTHOR_STATED"
    LITERATURE_CONTRADICTION = "LITERATURE_CONTRADICTION"
    INFERRED_FROM_EVIDENCE = "INFERRED_FROM_EVIDENCE"
    CORPUS_COVERAGE = "CORPUS_COVERAGE"
    MODEL_OR_THEORY = "MODEL_OR_THEORY"


class CandidateStage(str, Enum):
    RAW_CANDIDATE = "RAW_CANDIDATE"
    PATH_CANDIDATE = "PATH_CANDIDATE"
    SEMANTIC_AUDITED = "SEMANTIC_AUDITED"
    RETRIEVAL_PLANNED = "RETRIEVAL_PLANNED"
    QUALIFIED = "QUALIFIED"


class GapLifecyclePhase(str, Enum):
    """Contract phase used to validate a candidate's typed payload.

    A field required to publish or package a scientific gap must not also be
    required merely to discover a source-bound lead.  Keeping these phases
    explicit prevents a primary-qualification requirement from silently
    suppressing type-directed retrieval.
    """

    DISCOVERY = "DISCOVERY"
    SEMANTIC_AUDIT = "SEMANTIC_AUDIT"
    PRIMARY_QUALIFICATION = "PRIMARY_QUALIFICATION"


class SemanticVerdict(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    ENTAILED = "ENTAILED"
    PARTIALLY_ENTAILED = "PARTIALLY_ENTAILED"
    CONTRADICTED = "CONTRADICTED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class EvidenceMaturity(str, Enum):
    LEAD = "LEAD"
    SOURCE_BOUND = "SOURCE_BOUND"
    SEMANTICALLY_VALIDATED = "SEMANTICALLY_VALIDATED"
    DESIGN_READY = "DESIGN_READY"


class ScopeStatus(str, Enum):
    CORE = "CORE"
    COMPONENT_BRIDGE = "COMPONENT_BRIDGE"
    BACKGROUND = "BACKGROUND"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class GapRoute(str, Enum):
    REJECT = "REJECT"
    DIAGNOSTIC = "DIAGNOSTIC"
    SECONDARY_RESEARCH = "SECONDARY_RESEARCH"
    TARGETED_RETRIEVAL = "TARGETED_RETRIEVAL"
    PRIMARY_CANDIDATE = "PRIMARY_CANDIDATE"


class ResearchPackageKind(str, Enum):
    EMPIRICAL_TEST = "EMPIRICAL_TEST_PACKAGE"
    FOLLOWUP_RESOLUTION = "FOLLOWUP_RESOLUTION_PACKAGE"
    MECHANISM_HYPOTHESIS = "MECHANISM_HYPOTHESIS_PACKAGE"
    MECHANISM_DISCRIMINATION = "MECHANISM_DISCRIMINATION_PACKAGE"
    BOUNDARY_CONDITION = "BOUNDARY_CONDITION_PACKAGE"
    REPLICATION_RESOLUTION = "REPLICATION_RESOLUTION_PACKAGE"
    MEASUREMENT_VALIDATION = "MEASUREMENT_VALIDATION_PACKAGE"
    THEORY_VALIDATION = "THEORY_VALIDATION_PACKAGE"
    GENERALIZATION_VALIDATION = "GENERALIZATION_VALIDATION_PACKAGE"
    METHOD_EVALUATION = "METHOD_EVALUATION_PACKAGE"
    DATA_ACQUISITION = "DATA_ACQUISITION_PACKAGE"
    SCALE_INTEGRATION = "SCALE_INTEGRATION_PACKAGE"
    BENCHMARK_DESIGN = "BENCHMARK_DESIGN_PACKAGE"
    TRANSLATION_FEASIBILITY = "TRANSLATION_FEASIBILITY_PACKAGE"


@dataclass(frozen=True)
class GapDiscoverySpec:
    """Minimum source-bound structure needed to emit one typed gap lead.

    These are discovery requirements, not final package requirements.  They
    describe what a detector must observe before it may emit a candidate, and
    explicitly name the false-positive conditions it must rule out.
    """

    minimum_source_units: int
    minimum_distinct_papers: int
    required_assertion_kinds: tuple[str, ...]
    required_graph_patterns: tuple[str, ...]
    required_scope_axes: tuple[str, ...]
    allowed_signal_types: tuple[GapSignalType, ...]
    false_positive_guards: tuple[str, ...]


@dataclass(frozen=True)
class GapTypeContract:
    """Discovery, audit, and primary obligations for one scientific gap type."""

    gap_type: GapType
    package_kind: ResearchPackageKind
    discovery_spec: GapDiscoverySpec
    candidate_required_payload_fields: tuple[str, ...]
    semantic_required_payload_fields: tuple[str, ...]
    primary_required_payload_fields: tuple[str, ...]
    required_semantic_checks: tuple[str, ...]
    required_retrieval_axes: tuple[str, ...]
    primary_mechanism_eligible: bool = False

    @property
    def required_payload_fields(self) -> tuple[str, ...]:
        """Return the primary-qualification fields used by package consumers.

        This is a current-contract projection, not a legacy artifact adapter:
        callers that do not select a lifecycle phase continue to receive the
        strictest, publication/package-facing requirement set.
        """

        return self.primary_required_payload_fields

    def payload_fields_for_phase(
        self,
        phase: GapLifecyclePhase | str,
    ) -> tuple[str, ...]:
        normalized = normalize_gap_lifecycle_phase(phase)
        if normalized is GapLifecyclePhase.DISCOVERY:
            return self.candidate_required_payload_fields
        if normalized is GapLifecyclePhase.SEMANTIC_AUDIT:
            return self.semantic_required_payload_fields
        return self.primary_required_payload_fields


_SOURCE_BOUND_SIGNALS = (
    GapSignalType.AUTHOR_STATED,
    GapSignalType.LITERATURE_CONTRADICTION,
    GapSignalType.INFERRED_FROM_EVIDENCE,
    GapSignalType.CORPUS_COVERAGE,
    GapSignalType.MODEL_OR_THEORY,
)


def _discovery_spec(
    *,
    minimum_source_units: int = 1,
    minimum_distinct_papers: int = 1,
    required_assertion_kinds: tuple[str, ...] = (),
    required_graph_patterns: tuple[str, ...] = (),
    required_scope_axes: tuple[str, ...] = (),
    allowed_signal_types: tuple[GapSignalType, ...] = _SOURCE_BOUND_SIGNALS,
    false_positive_guards: tuple[str, ...] = (),
) -> GapDiscoverySpec:
    return GapDiscoverySpec(
        minimum_source_units=minimum_source_units,
        minimum_distinct_papers=minimum_distinct_papers,
        required_assertion_kinds=required_assertion_kinds,
        required_graph_patterns=required_graph_patterns,
        required_scope_axes=required_scope_axes,
        allowed_signal_types=allowed_signal_types,
        false_positive_guards=false_positive_guards,
    )


GAP_TYPE_CONTRACTS: dict[GapType, GapTypeContract] = {
    GapType.EMPIRICAL_COVERAGE: GapTypeContract(
        gap_type=GapType.EMPIRICAL_COVERAGE,
        package_kind=ResearchPackageKind.EMPIRICAL_TEST,
        discovery_spec=_discovery_spec(
            required_graph_patterns=("DECLARED_SCOPE_WITH_DIRECT_EVIDENCE_COVERAGE",),
            required_scope_axes=("research_object", "condition_or_regime"),
            false_positive_guards=("CORPUS_ABSENCE_IS_NOT_A_GAP", "TARGET_CONDITION_REQUIRED"),
        ),
        candidate_required_payload_fields=("phenomenon", "target_object", "target_condition", "coverage_dimension_missing"),
        semantic_required_payload_fields=("phenomenon", "target_object", "target_condition", "available_direct_evidence_count", "coverage_dimension_missing"),
        primary_required_payload_fields=("phenomenon", "target_object", "target_condition", "available_direct_evidence_count", "coverage_dimension_missing"),
        required_semantic_checks=("scope_aligned", "direct_evidence_coverage_assessed"),
        required_retrieval_axes=("coverage", "prior_resolution"),
    ),
    GapType.AUTHOR_STATED_LIMITATION: GapTypeContract(
        gap_type=GapType.AUTHOR_STATED_LIMITATION,
        package_kind=ResearchPackageKind.FOLLOWUP_RESOLUTION,
        discovery_spec=_discovery_spec(
            required_assertion_kinds=("AUTHOR_LIMITATION",),
            required_graph_patterns=("EXPLICIT_LIMITATION_SPAN",),
            false_positive_guards=("GENERIC_FUTURE_WORK_IS_NOT_A_LIMITATION",),
        ),
        candidate_required_payload_fields=("limitation_kind", "author_stated_unknown", "affected_claim", "limitation_span_id"),
        semantic_required_payload_fields=("limitation_kind", "author_stated_unknown", "affected_claim", "scope_of_limitation", "limitation_span_id"),
        primary_required_payload_fields=("limitation_kind", "author_stated_unknown", "affected_claim", "scope_of_limitation", "limitation_span_id"),
        required_semantic_checks=("limitation_entails_unknown", "scope_aligned"),
        required_retrieval_axes=("prior_resolution",),
    ),
    GapType.CAUSAL_IDENTIFICATION: GapTypeContract(
        gap_type=GapType.CAUSAL_IDENTIFICATION,
        package_kind=ResearchPackageKind.MECHANISM_HYPOTHESIS,
        discovery_spec=_discovery_spec(
            required_assertion_kinds=("CAUSAL_CLAIM",),
            required_graph_patterns=("DECLARED_INPUT_OUTCOME_RELATION",),
            required_scope_axes=("intervention_or_exposure", "outcome_definition"),
            false_positive_guards=("PARALLEL_EFFECT_IS_NOT_CAUSAL_IDENTIFICATION", "ROLE_COLLAPSE_FORBIDDEN"),
        ),
        candidate_required_payload_fields=("input", "outcome", "identification_missing"),
        semantic_required_payload_fields=("input", "outcome", "identification_missing", "alternative_explanations"),
        primary_required_payload_fields=("input", "outcome", "identification_missing", "alternative_explanations", "identification_design"),
        required_semantic_checks=(
            "relations_entailed",
            "roles_distinct",
            "no_parallel_effect_interpretation",
            "context_aligned",
            "alternative_explanation_declared",
            "temporal_order_supported",
            "identification_design_available",
        ),
        required_retrieval_axes=("direct_evidence", "prior_resolution"),
        primary_mechanism_eligible=True,
    ),
    GapType.MECHANISM_COMPETITION: GapTypeContract(
        gap_type=GapType.MECHANISM_COMPETITION,
        package_kind=ResearchPackageKind.MECHANISM_DISCRIMINATION,
        discovery_spec=_discovery_spec(
            minimum_source_units=2,
            required_assertion_kinds=("CAUSAL_CLAIM",),
            required_graph_patterns=("TWO_DISTINCT_MECHANISM_PATHS", "COMMON_ENDPOINT"),
            required_scope_axes=("intervention_or_exposure", "outcome_definition"),
            false_positive_guards=("CONCEPT_CO_OCCURRENCE_IS_NOT_COMPETITION", "ENDPOINT_COMPARABILITY_REQUIRED"),
        ),
        candidate_required_payload_fields=("common_input", "common_outcome", "candidate_mechanisms"),
        semantic_required_payload_fields=("common_input", "common_outcome", "candidate_mechanisms"),
        primary_required_payload_fields=("common_input", "common_outcome", "candidate_mechanisms", "discriminating_prediction"),
        required_semantic_checks=("competing_paths_entailed", "endpoint_comparable", "discriminator_available"),
        required_retrieval_axes=("discriminating_evidence", "prior_resolution"),
    ),
    GapType.BOUNDARY_HETEROGENEITY: GapTypeContract(
        gap_type=GapType.BOUNDARY_HETEROGENEITY,
        package_kind=ResearchPackageKind.BOUNDARY_CONDITION,
        discovery_spec=_discovery_spec(
            minimum_source_units=2,
            required_graph_patterns=("COMPARABLE_RELATION_ACROSS_CONDITIONS",),
            required_scope_axes=("condition_or_regime",),
            false_positive_guards=("DIFFERENT_SYSTEMS_ARE_NOT_AUTOMATICALLY_A_BOUNDARY",),
        ),
        candidate_required_payload_fields=("base_relation", "boundary_variable", "condition_a", "condition_b"),
        semantic_required_payload_fields=("base_relation", "boundary_variable", "condition_a", "condition_b", "effect_difference"),
        primary_required_payload_fields=("base_relation", "boundary_variable", "condition_a", "condition_b", "effect_difference", "threshold_unknown"),
        required_semantic_checks=("comparison_entailed", "conditions_distinct", "measurement_comparable"),
        required_retrieval_axes=("boundary_evidence", "prior_resolution"),
    ),
    GapType.CONTRADICTION_REPLICATION: GapTypeContract(
        gap_type=GapType.CONTRADICTION_REPLICATION,
        package_kind=ResearchPackageKind.REPLICATION_RESOLUTION,
        discovery_spec=_discovery_spec(
            minimum_source_units=2,
            minimum_distinct_papers=2,
            required_graph_patterns=("INDEPENDENT_COMPARABLE_CONFLICTING_RESULTS",),
            false_positive_guards=("UNALIGNED_SCOPE_IS_NOT_A_CONTRADICTION",),
        ),
        candidate_required_payload_fields=("shared_claim", "evidence_sets", "comparability_verdict"),
        semantic_required_payload_fields=("shared_claim", "evidence_sets", "comparability_verdict", "unexplained_difference"),
        primary_required_payload_fields=("shared_claim", "evidence_sets", "comparability_verdict", "unexplained_difference"),
        required_semantic_checks=("independent_sources", "results_conflict", "comparison_entailed"),
        required_retrieval_axes=("replication", "meta_analysis", "prior_resolution"),
    ),
    GapType.MEASUREMENT_OPERATIONALIZATION: GapTypeContract(
        gap_type=GapType.MEASUREMENT_OPERATIONALIZATION,
        package_kind=ResearchPackageKind.MEASUREMENT_VALIDATION,
        discovery_spec=_discovery_spec(
            required_assertion_kinds=("MEASUREMENT_DEFINITION",),
            required_graph_patterns=("CONSTRUCT_PROXY_TARGET_MAPPING",),
            false_positive_guards=("MODEL_OUTPUT_ALONE_IS_NOT_A_MEASUREMENT_GAP",),
        ),
        candidate_required_payload_fields=("construct", "proxy_measure", "target_measure"),
        semantic_required_payload_fields=("construct", "proxy_measure", "target_measure", "mapping_status"),
        primary_required_payload_fields=("construct", "proxy_measure", "target_measure", "mapping_status", "validation_missing"),
        required_semantic_checks=("proxy_identified", "target_identified", "mapping_not_validated"),
        required_retrieval_axes=("calibration", "external_validation", "prior_resolution"),
    ),
    GapType.THEORY_MATHEMATICAL: GapTypeContract(
        gap_type=GapType.THEORY_MATHEMATICAL,
        package_kind=ResearchPackageKind.THEORY_VALIDATION,
        discovery_spec=_discovery_spec(
            required_assertion_kinds=("FORMAL_PROPOSITION", "FORMAL_ASSUMPTION"),
            required_graph_patterns=("FORMAL_CLAIM_WITH_VALIDITY_CONDITIONS",),
            false_positive_guards=("UNUSED_THEORY_IS_NOT_A_THEORY_GAP",),
        ),
        candidate_required_payload_fields=("formal_claim", "assumptions"),
        semantic_required_payload_fields=("formal_claim", "assumptions", "known_validity_domain"),
        primary_required_payload_fields=("formal_claim", "assumptions", "known_validity_domain", "counterexample_status"),
        required_semantic_checks=("formal_statement_present", "assumptions_extracted", "falsification_path_available"),
        required_retrieval_axes=("proof", "counterexample", "prior_resolution"),
    ),
    GapType.GENERALIZATION_TRANSPORTABILITY: GapTypeContract(
        gap_type=GapType.GENERALIZATION_TRANSPORTABILITY,
        package_kind=ResearchPackageKind.GENERALIZATION_VALIDATION,
        discovery_spec=_discovery_spec(
            required_graph_patterns=("DECLARED_SOURCE_TARGET_DOMAIN_SHIFT",),
            false_positive_guards=("SINGLE_FAILURE_IS_NOT_A_GENERALIZATION_GAP",),
        ),
        candidate_required_payload_fields=("source_domain", "target_domain", "model_or_claim"),
        semantic_required_payload_fields=("source_domain", "target_domain", "shift_type", "model_or_claim"),
        primary_required_payload_fields=("source_domain", "target_domain", "shift_type", "model_or_claim", "external_validation_status"),
        required_semantic_checks=("source_domain_evidence", "target_domain_defined", "shift_defined"),
        required_retrieval_axes=("external_validation", "transportability", "prior_resolution"),
    ),
    GapType.METHOD_DESIGN: GapTypeContract(
        gap_type=GapType.METHOD_DESIGN,
        package_kind=ResearchPackageKind.METHOD_EVALUATION,
        discovery_spec=_discovery_spec(
            required_assertion_kinds=("METHOD_DESCRIPTION",),
            required_graph_patterns=("METHOD_FAILURE_OR_BIAS_EVIDENCE",),
            false_positive_guards=("GENERIC_OPTIMIZATION_IS_NOT_A_METHOD_GAP",),
        ),
        candidate_required_payload_fields=("current_method", "failure_mode"),
        semantic_required_payload_fields=("current_method", "failure_mode", "bias_or_identification_problem"),
        primary_required_payload_fields=("current_method", "failure_mode", "bias_or_identification_problem", "alternative_design", "evaluation_criterion"),
        required_semantic_checks=("failure_mode_entailed", "alternative_design_specified"),
        required_retrieval_axes=("method_comparison", "bias_analysis", "prior_resolution"),
    ),
    GapType.DATA_COVERAGE: GapTypeContract(
        gap_type=GapType.DATA_COVERAGE,
        package_kind=ResearchPackageKind.DATA_ACQUISITION,
        discovery_spec=_discovery_spec(
            required_assertion_kinds=("DATASET_COVERAGE",),
            required_graph_patterns=("COVERAGE_DIMENSION_WITH_CLAIM_IMPACT",),
            false_positive_guards=("SMALL_DATASET_ALONE_IS_NOT_A_DATA_GAP",),
        ),
        candidate_required_payload_fields=("impact_on_claim",),
        semantic_required_payload_fields=("impact_on_claim",),
        primary_required_payload_fields=("missing_variables", "missing_population_or_system", "missing_regime", "missing_time_horizon", "impact_on_claim", "acquisition_path"),
        required_semantic_checks=("coverage_measured", "impact_entailed", "acquisition_feasible"),
        required_retrieval_axes=("dataset_coverage", "prior_resolution"),
    ),
    GapType.SCALE_INTEGRATION: GapTypeContract(
        gap_type=GapType.SCALE_INTEGRATION,
        package_kind=ResearchPackageKind.SCALE_INTEGRATION,
        discovery_spec=_discovery_spec(
            minimum_source_units=2,
            required_assertion_kinds=("SCALE_STATEMENT",),
            required_graph_patterns=("TWO_SCALES_WITHOUT_BRIDGE",),
            false_positive_guards=("MULTIPLE_SCALES_ALONE_ARE_NOT_A_SCALE_GAP",),
        ),
        candidate_required_payload_fields=("source_scale", "target_scale", "coupling_question"),
        semantic_required_payload_fields=("source_scale", "target_scale", "bridge_variable", "coupling_question"),
        primary_required_payload_fields=("source_scale", "target_scale", "bridge_variable", "coupling_question"),
        required_semantic_checks=("scales_defined", "bridge_variable_defined", "coupling_test_available"),
        required_retrieval_axes=("multiscale_evidence", "prior_resolution"),
    ),
    GapType.BENCHMARK_COMPARISON: GapTypeContract(
        gap_type=GapType.BENCHMARK_COMPARISON,
        package_kind=ResearchPackageKind.BENCHMARK_DESIGN,
        discovery_spec=_discovery_spec(
            minimum_source_units=2,
            required_graph_patterns=("DEFINED_COMPARISON_TARGETS_WITHOUT_SHARED_EVALUATION",),
            false_positive_guards=("ABSENT_BENCHMARK_ALONE_IS_NOT_A_GAP",),
        ),
        candidate_required_payload_fields=("comparison_target", "candidate_systems"),
        semantic_required_payload_fields=("comparison_target", "candidate_systems"),
        primary_required_payload_fields=("comparison_target", "candidate_systems", "common_task_missing", "shared_metric_missing", "protocol_missing"),
        required_semantic_checks=("comparison_need_entailed", "systems_defined", "metric_need_defined"),
        required_retrieval_axes=("benchmark", "comparison_protocol", "prior_resolution"),
    ),
    GapType.TRANSLATION_IMPLEMENTATION: GapTypeContract(
        gap_type=GapType.TRANSLATION_IMPLEMENTATION,
        package_kind=ResearchPackageKind.TRANSLATION_FEASIBILITY,
        discovery_spec=_discovery_spec(
            required_assertion_kinds=("IMPLEMENTATION_CONSTRAINT",),
            required_graph_patterns=("VALIDATED_CLAIM_WITH_DEPLOYMENT_BARRIER",),
            false_positive_guards=("NOT_YET_APPLIED_IS_NOT_A_TRANSLATION_GAP",),
        ),
        candidate_required_payload_fields=("validated_claim", "deployment_context", "implementation_barrier"),
        semantic_required_payload_fields=("validated_claim", "deployment_context", "implementation_barrier", "feasibility_question"),
        primary_required_payload_fields=("validated_claim", "deployment_context", "implementation_barrier", "feasibility_question"),
        required_semantic_checks=("validated_claim_entailed", "deployment_context_defined", "barrier_entailed"),
        required_retrieval_axes=("implementation_evidence", "real_world_validation", "prior_resolution"),
    ),
}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_gap_lifecycle_phase(value: Any) -> GapLifecyclePhase:
    """Return a current lifecycle phase or reject ambiguous historic labels."""

    if isinstance(value, GapLifecyclePhase):
        return value
    text = _text(getattr(value, "value", value)).upper()
    for phase in GapLifecyclePhase:
        if text == phase.value or text == phase.name:
            return phase
    raise ValueError(f"Unsupported gap lifecycle phase: {_text(value)!r}")


def normalize_gap_type(value: Any) -> GapType | None:
    if isinstance(value, GapType):
        return value
    text = _text(getattr(value, "value", value)).upper()
    for item in GapType:
        if text == item.value or text == item.name:
            return item
    return None


def normalize_gap_subtype(gap_type: GapType | str, value: Any) -> str:
    """Return a controlled subtype or raise for a cross-type subtype leak."""
    normalized_type = normalize_gap_type(gap_type)
    if normalized_type is None:
        raise ValueError(f"Unknown v2 gap type: {_text(gap_type)!r}")
    subtype = _text(getattr(value, "value", value)).upper()
    if not subtype:
        return ""
    allowed = GAP_SUBTYPES_BY_TYPE[normalized_type]
    if subtype not in allowed:
        raise ValueError(
            f"Subtype {subtype!r} is not registered for {normalized_type.value}; "
            "detector-local free-text subtypes are disabled"
        )
    return subtype


def contract_for(value: Any) -> GapTypeContract:
    gap_type = normalize_gap_type(value)
    if gap_type is None:
        raise ValueError(f"Unknown v2 gap type: {_text(value)!r}")
    return GAP_TYPE_CONTRACTS[gap_type]


def validate_gap_type_contract(contract: GapTypeContract) -> GapTypeContract:
    """Validate one current typed contract before detector execution.

    Contract validation deliberately rejects missing lifecycle partitions.  It
    never fills a phase from a historical ``required_payload_fields`` value,
    because that would recreate the discovery/primary conflation this schema
    split removes.
    """

    if not isinstance(contract, GapTypeContract):
        raise ValueError("Gap type contract must use GapTypeContract")
    if not isinstance(contract.gap_type, GapType):
        raise ValueError("Gap type contract contains an unknown gap type")
    if not isinstance(contract.package_kind, ResearchPackageKind):
        raise ValueError("Gap type contract contains an unknown package kind")
    discovery = contract.discovery_spec
    if not isinstance(discovery, GapDiscoverySpec):
        raise ValueError("Gap type contract requires GapDiscoverySpec")
    if discovery.minimum_source_units < 1:
        raise ValueError("Gap discovery minimum_source_units must be at least one")
    if discovery.minimum_distinct_papers < 1:
        raise ValueError("Gap discovery minimum_distinct_papers must be at least one")
    if discovery.minimum_distinct_papers > discovery.minimum_source_units:
        raise ValueError("Gap discovery cannot require more papers than source units")
    allowed_signals = set(discovery.allowed_signal_types)
    if not allowed_signals or not allowed_signals.issubset(set(GapSignalType)):
        raise ValueError("Gap discovery spec contains an unsupported signal type")
    phase_fields = {
        GapLifecyclePhase.DISCOVERY: contract.candidate_required_payload_fields,
        GapLifecyclePhase.SEMANTIC_AUDIT: contract.semantic_required_payload_fields,
        GapLifecyclePhase.PRIMARY_QUALIFICATION: contract.primary_required_payload_fields,
    }
    for phase, fields in phase_fields.items():
        normalized = tuple(_text(field) for field in fields)
        if not normalized or any(not field for field in normalized):
            raise ValueError(f"Gap type contract has empty {phase.value} payload fields")
        if len(set(normalized)) != len(normalized):
            raise ValueError(f"Gap type contract duplicates {phase.value} payload fields")
    if not set(contract.candidate_required_payload_fields).issubset(
        set(contract.semantic_required_payload_fields)
    ):
        raise ValueError("Semantic payload fields must include all discovery payload fields")
    if not set(contract.semantic_required_payload_fields).issubset(
        set(contract.primary_required_payload_fields)
    ):
        raise ValueError("Primary payload fields must include all semantic payload fields")
    if not contract.required_semantic_checks or not contract.required_retrieval_axes:
        raise ValueError("Gap type contract requires semantic checks and retrieval axes")
    return contract


def validate_gap_type_contract_registry(
    registry: dict[GapType, GapTypeContract] | None = None,
) -> dict[GapType, GapTypeContract]:
    """Validate the complete, current registry with no legacy adaptation."""

    active = registry if isinstance(registry, dict) else GAP_TYPE_CONTRACTS
    if set(active) != set(GapType):
        raise ValueError("Gap type contract registry must define every current GapType")
    for gap_type, contract in active.items():
        validated = validate_gap_type_contract(contract)
        if validated.gap_type is not gap_type:
            raise ValueError("Gap type contract registry key/type mismatch")
    return active


validate_gap_type_contract_registry()


def initial_gap_assessment(
    *,
    gap_type: GapType | str,
    signal_type: GapSignalType | str,
    candidate_stage: CandidateStage | str = CandidateStage.RAW_CANDIDATE,
) -> dict[str, Any]:
    normalized_type = normalize_gap_type(gap_type)
    if normalized_type is None:
        raise ValueError(f"Unknown v2 gap type: {_text(gap_type)!r}")
    return {
        "schema_version": "gap_assessment_v2",
        "gap_type": normalized_type.value,
        "gap_subtype": "",
        "signal_type": str(getattr(signal_type, "value", signal_type)),
        "candidate_stage": str(getattr(candidate_stage, "value", candidate_stage)),
        "semantic_verdict": SemanticVerdict.UNVERIFIED.value,
        "semantic_confidence": 0.0,
        "semantic_failure_codes": [],
        "scope_status": ScopeStatus.BACKGROUND.value,
        "context_verdict": "INCOMPLETE",
        "temporal_verdict": "UNRESOLVED",
        "source_role_verdict": "UNVERIFIED",
        "novelty_verdict": "UNCHECKED",
        "evidence_maturity": EvidenceMaturity.LEAD.value,
        "route": GapRoute.DIAGNOSTIC.value,
        "decision_reasons": [],
        "missing_evidence_axes": [],
        "audit_refs": [],
    }


def _source_span_refs(candidate: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in candidate.get("source_evidence_units", []):
        if not isinstance(item, dict):
            continue
        paper_id = _text(item.get("paper_id"))
        source_unit_id = _text(item.get("source_unit_id"))
        excerpt_hash = _text(item.get("excerpt_hash"))
        key = (paper_id, source_unit_id, excerpt_hash)
        if not source_unit_id or key in seen:
            continue
        seen.add(key)
        refs.append(
            {
                "paper_id": paper_id,
                "source_unit_id": source_unit_id,
                "excerpt_hash": excerpt_hash,
                "source_field": _text(item.get("source_field")),
            }
        )
    return refs


def synchronize_candidate_surface(
    candidate: dict[str, Any],
    assessment: dict[str, Any] | None = None,
    *,
    semantic_assessment: dict[str, Any] | None = None,
    retrieval_assessment: dict[str, Any] | None = None,
    increment_assessment_version: bool = False,
    increment_retrieval_version: bool = False,
) -> dict[str, Any]:
    """Synchronise a candidate's public v2 surface from one assessment record.

    This is deliberately a constructor/update primitive, not a legacy
    migration adapter.  It accepts only ``gap_candidate_v2`` and refuses to
    manufacture an assessment from historic state labels.
    """
    if candidate.get("schema_version") != "gap_candidate_v2":
        raise ValueError("Candidate surface synchronisation requires gap_candidate_v2")
    active = dict(assessment if isinstance(assessment, dict) else assessment_of(candidate))
    if active.get("schema_version") != "gap_assessment_v2":
        raise ValueError("Candidate surface requires gap_assessment_v2")
    normalized_type = normalize_gap_type(active.get("gap_type"))
    if normalized_type is None:
        raise ValueError("Candidate assessment contains an unknown gap_type")
    subtype = normalize_gap_subtype(normalized_type, active.get("gap_subtype"))
    active["gap_type"] = normalized_type.value
    active["gap_subtype"] = subtype
    result = dict(candidate)
    result["gap_assessment"] = active
    assertion_ids = list(dict.fromkeys(
        _text(item)
        for item in (
            result.get("assertion_ids")
            or result.get("source_assertion_ids")
            or (result.get("evidence_graph_contract") or {}).get("assertion_ids")
            or []
        )
        if _text(item)
    ))
    slot_support_ids = list(dict.fromkeys(
        _text(item)
        for item in (
            result.get("slot_support_ids")
            or [
                support_id
                for unit in result.get("source_evidence_units", [])
                if isinstance(unit, dict)
                for support_id in unit.get("slot_support_ids", [])
            ]
        )
        if _text(item)
    ))
    source_units = [
        item for item in result.get("source_evidence_units", [])
        if isinstance(item, dict)
    ]
    lineage_complete = bool(
        assertion_ids
        and slot_support_ids
        and source_units
        and all(
            _text(item.get("assertion_id"))
            and _text(item.get("source_span_id") or item.get("source_unit_id"))
            and _text(item.get("document_version_hash"))
            and _text(item.get("exact_quote") or item.get("excerpt"))
            for item in source_units
        )
    )
    formal_gate_passed = bool(
        active.get("route") == GapRoute.PRIMARY_CANDIDATE.value
        and active.get("candidate_stage") == CandidateStage.QUALIFIED.value
        and active.get("semantic_verdict") == SemanticVerdict.ENTAILED.value
        and active.get("scope_status") == ScopeStatus.CORE.value
        and active.get("evidence_maturity") == EvidenceMaturity.DESIGN_READY.value
        and isinstance(result.get("primary_source_span_gate"), dict)
        and result["primary_source_span_gate"].get("status") == "PASSED"
    )
    reportable = formal_gate_passed and lineage_complete
    diagnostic_only = active.get("route") == GapRoute.REJECT.value
    gap_status = (
        "REPORTABLE_GAP"
        if reportable
        else "DIAGNOSTIC"
        if diagnostic_only
        else "EXPLORATORY_GAP_CANDIDATE"
    )
    result["assertion_ids"] = assertion_ids
    result["slot_support_ids"] = slot_support_ids
    result["gap_status"] = gap_status
    result["reportable"] = reportable
    result["reportability"] = {
        "schema_version": "gap_reportability_v1",
        "status": gap_status,
        "formal_gate_passed": formal_gate_passed,
        "source_lineage_complete": lineage_complete,
        "scientific_conclusion_allowed": reportable,
        "missing_requirements": [
            *([] if formal_gate_passed else ["FORMAL_GAP_QUALIFICATION"]),
            *([] if assertion_ids else ["ASSERTION_IDS"]),
            *([] if slot_support_ids else ["SLOT_SUPPORT_IDS"]),
            *([] if lineage_complete else ["ASSERTION_TO_SOURCE_LINEAGE"]),
        ],
        "next_retrieval_requirements": list(active.get("missing_evidence_axes") or []),
    }
    result.update(
        {
            "gap_type": normalized_type.value,
            "gap_subtype": subtype,
            "signal_type": _text(active.get("signal_type")),
            "candidate_stage": _text(active.get("candidate_stage")),
            "route": _text(active.get("route")),
            "evidence_refs": _source_span_refs(result),
            "source_span_refs": _source_span_refs(result),
            "qualification": {
                "schema_version": "gap_qualification_v2",
                "route": _text(active.get("route")),
                "scope_status": _text(active.get("scope_status")),
                "semantic_verdict": _text(active.get("semantic_verdict")),
                "evidence_maturity": _text(active.get("evidence_maturity")),
                "novelty_verdict": _text(active.get("novelty_verdict")),
                "decision_reasons": list(active.get("decision_reasons") or []),
            },
        }
    )
    existing_semantic = result.get("semantic_assessment") if isinstance(result.get("semantic_assessment"), dict) else {}
    semantic = dict(existing_semantic)
    if isinstance(semantic_assessment, dict):
        semantic.update(semantic_assessment)
    semantic.update(
        {
            "schema_version": "semantic_assessment_v2",
            "verdict": _text(active.get("semantic_verdict")),
            "confidence": float(active.get("semantic_confidence") or 0.0),
            "failure_codes": list(active.get("semantic_failure_codes") or []),
        }
    )
    result["semantic_assessment"] = semantic
    if isinstance(retrieval_assessment, dict):
        result["retrieval_assessment"] = dict(retrieval_assessment)
    result["assessment_version"] = int(result.get("assessment_version") or 0) + int(increment_assessment_version)
    result["retrieval_version"] = int(result.get("retrieval_version") or 0) + int(increment_retrieval_version)
    result["package_version"] = int(result.get("package_version") or 0)
    return result


def assessment_of(candidate: dict[str, Any]) -> dict[str, Any]:
    assessment = candidate.get("gap_assessment")
    if not isinstance(assessment, dict):
        raise ValueError("v2 gap candidate is missing gap_assessment")
    if assessment.get("schema_version") != "gap_assessment_v2":
        raise ValueError("Unsupported gap assessment schema; migration fallbacks are intentionally disabled")
    if normalize_gap_type(assessment.get("gap_type")) is None:
        raise ValueError("gap_assessment contains an unknown gap_type")
    normalize_gap_subtype(assessment.get("gap_type"), assessment.get("gap_subtype"))
    return assessment


def payload_of(candidate: dict[str, Any]) -> dict[str, Any]:
    payload = candidate.get("type_payload")
    if not isinstance(payload, dict):
        raise ValueError("v2 gap candidate is missing type_payload")
    return payload


def _payload_value_present(value: Any) -> bool:
    """Distinguish a missing field from a legitimate numeric zero or false flag."""
    if value is None:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    if isinstance(value, bool):
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return bool(_text(value))


def missing_payload_fields(
    candidate: dict[str, Any],
    *,
    lifecycle_phase: GapLifecyclePhase | str = GapLifecyclePhase.PRIMARY_QUALIFICATION,
) -> list[str]:
    """Return missing payload fields for one explicit lifecycle phase.

    The default remains primary qualification for package-facing callers.
    Detector and semantic-audit callers can now request their own phase
    without lowering the primary contract or inventing a compatibility path.
    """

    assessment = assessment_of(candidate)
    contract = contract_for(assessment.get("gap_type"))
    payload = payload_of(candidate)
    phase = normalize_gap_lifecycle_phase(lifecycle_phase)
    required = list(contract.payload_fields_for_phase(phase))
    if (
        phase is GapLifecyclePhase.PRIMARY_QUALIFICATION
        and assessment.get("gap_type") == GapType.CAUSAL_IDENTIFICATION.value
        and assessment.get("gap_subtype") == CausalGapSubtype.MEDIATION_UNRESOLVED.value
    ):
        required.extend(["mediator", "known_relations"])
    return [field for field in required if not _payload_value_present(payload.get(field))]


def package_kind_for(candidate: dict[str, Any]) -> ResearchPackageKind:
    return contract_for(assessment_of(candidate).get("gap_type")).package_kind


def is_primary_mechanism_candidate(candidate: dict[str, Any]) -> bool:
    assessment = assessment_of(candidate)
    contract = contract_for(assessment.get("gap_type"))
    question_contract = candidate.get("research_question_contract") if isinstance(candidate.get("research_question_contract"), dict) else {}
    routing = question_contract.get("routing_contract") if isinstance(question_contract.get("routing_contract"), dict) else {}
    question_kind = str((question_contract.get("research_question") or {}).get("question_kind") or "")
    source_span_gate = candidate.get("primary_source_span_gate")
    return bool(
        contract.primary_mechanism_eligible
        and assessment.get("gap_type") == GapType.CAUSAL_IDENTIFICATION.value
        and question_kind == "CAUSAL_IDENTIFICATION"
        and routing.get("can_compete_for_primary_mechanism_package") is True
        and assessment.get("gap_subtype") in {item.value for item in CausalGapSubtype}
        and contract.package_kind == ResearchPackageKind.MECHANISM_HYPOTHESIS
        and assessment.get("route") == GapRoute.PRIMARY_CANDIDATE.value
        and assessment.get("candidate_stage") == CandidateStage.QUALIFIED.value
        and assessment.get("semantic_verdict") == SemanticVerdict.ENTAILED.value
        and assessment.get("scope_status") == ScopeStatus.CORE.value
        and assessment.get("evidence_maturity") == EvidenceMaturity.DESIGN_READY.value
        and isinstance(source_span_gate, dict)
        and source_span_gate.get("status") == "PASSED"
    )


def is_primary_research_candidate(candidate: dict[str, Any]) -> bool:
    assessment = assessment_of(candidate)
    source_span_gate = candidate.get("primary_source_span_gate")
    return bool(
        assessment.get("route") == GapRoute.PRIMARY_CANDIDATE.value
        and assessment.get("candidate_stage") == CandidateStage.QUALIFIED.value
        and assessment.get("semantic_verdict") == SemanticVerdict.ENTAILED.value
        and assessment.get("scope_status") == ScopeStatus.CORE.value
        and assessment.get("evidence_maturity") == EvidenceMaturity.DESIGN_READY.value
        and isinstance(source_span_gate, dict)
        and source_span_gate.get("status") == "PASSED"
    )


def group_by_gap_type(candidates: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {item.value: [] for item in GapType}
    for candidate in candidates:
        assessment = assessment_of(candidate)
        grouped[assessment["gap_type"]].append(candidate)
    return {key: value for key, value in grouped.items() if value}


def group_by_semantic_status(candidates: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {item.value: [] for item in SemanticVerdict}
    for candidate in candidates:
        assessment = assessment_of(candidate)
        verdict = _text(assessment.get("semantic_verdict"))
        if verdict in grouped:
            grouped[verdict].append(candidate)
    return {key: value for key, value in grouped.items() if value}


def group_by_route(candidates: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {item.value: [] for item in GapRoute}
    for candidate in candidates:
        assessment = assessment_of(candidate)
        route = _text(assessment.get("route"))
        if route in grouped:
            grouped[route].append(candidate)
    return {key: value for key, value in grouped.items() if value}
