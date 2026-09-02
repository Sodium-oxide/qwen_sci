"""Type-directed authoring contracts for research proposals.

``ResearchPackageKind`` already says what scientific deficit was qualified.
This module says how that deficit may be written as a proposal.  It never
maps a non-causal package to input/mediator/outcome fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from ._gap_types import ResearchPackageKind
except ImportError:
    from _gap_types import ResearchPackageKind


PROPOSAL_AUTHORING_CONTRACT_VERSION = "proposal_authoring_contract_v2"


@dataclass(frozen=True)
class ProposalAuthoringContract:
    package_kind: ResearchPackageKind
    proposal_kind: str
    required_sections: tuple[str, ...]
    required_design_fields: tuple[str, ...]
    success_criteria: tuple[str, ...]
    prohibited_claim_patterns: tuple[str, ...]


_BASE_SECTIONS = (
    "research_question",
    "gap_statement",
    "scope_and_nonclaims",
    "evidence_basis",
    "aims",
    "type_specific_design",
    "analysis_and_decision_rules",
    "risks_and_limitations",
)


def _contract(
    kind: ResearchPackageKind,
    proposal_kind: str,
    design: tuple[str, ...],
    criteria: tuple[str, ...],
    prohibited: tuple[str, ...],
) -> ProposalAuthoringContract:
    return ProposalAuthoringContract(kind, proposal_kind, _BASE_SECTIONS, design, criteria, prohibited)


PROPOSAL_AUTHORING_CONTRACTS: dict[ResearchPackageKind, ProposalAuthoringContract] = {
    ResearchPackageKind.EMPIRICAL_TEST: _contract(
        ResearchPackageKind.EMPIRICAL_TEST, "EMPIRICAL_COVERAGE_PROPOSAL",
        ("target_object", "target_condition", "sampling_or_observation_plan", "measurement_plan", "coverage_decision_rule"),
        ("prespecified coverage threshold", "scope-bounded observation rule"),
        ("causal mechanism is established",),
    ),
    ResearchPackageKind.FOLLOWUP_RESOLUTION: _contract(
        ResearchPackageKind.FOLLOWUP_RESOLUTION, "LIMITATION_FOLLOWUP_PROPOSAL",
        ("verbatim_limitation", "affected_claim", "resolution_design", "post_limitation_resolution_check"),
        ("limitation directly addressed", "prior resolution distinguished"),
        ("generic future work establishes a gap",),
    ),
    ResearchPackageKind.MECHANISM_HYPOTHESIS: _contract(
        ResearchPackageKind.MECHANISM_HYPOTHESIS, "CAUSAL_IDENTIFICATION_PROPOSAL",
        ("target_estimand", "comparison_or_intervention", "identification_assumptions", "alternative_explanations", "falsification_plan"),
        ("estimand identified under declared assumptions", "alternative explanation discriminated"),
        ("association proves causation",),
    ),
    ResearchPackageKind.MECHANISM_DISCRIMINATION: _contract(
        ResearchPackageKind.MECHANISM_DISCRIMINATION, "MECHANISM_DISCRIMINATION_PROPOSAL",
        ("candidate_mechanisms", "common_endpoint", "discriminating_prediction", "discriminating_design"),
        ("observable predictions separate mechanisms", "shared endpoint is measured"),
        ("one candidate mechanism is already true",),
    ),
    ResearchPackageKind.BOUNDARY_CONDITION: _contract(
        ResearchPackageKind.BOUNDARY_CONDITION, "BOUNDARY_HETEROGENEITY_PROPOSAL",
        ("base_relation", "boundary_variable", "condition_comparison", "comparability_controls", "boundary_decision_rule"),
        ("conditions comparable before difference interpretation", "boundary threshold or heterogeneity estimate"),
        ("different studies automatically contradict",),
    ),
    ResearchPackageKind.REPLICATION_RESOLUTION: _contract(
        ResearchPackageKind.REPLICATION_RESOLUTION, "REPLICATION_RESOLUTION_PROPOSAL",
        ("shared_claim", "replication_or_reanalysis_plan", "comparability_audit", "resolution_rule"),
        ("independent results assessed under aligned conditions", "unexplained discrepancy classified"),
        ("unmatched results prove contradiction",),
    ),
    ResearchPackageKind.MEASUREMENT_VALIDATION: _contract(
        ResearchPackageKind.MEASUREMENT_VALIDATION, "MEASUREMENT_VALIDATION_PROPOSAL",
        ("construct", "proxy_measure", "target_or_reference_measure", "calibration_plan", "reliability_plan"),
        ("mapping validity or calibration criterion", "measurement error is quantified"),
        ("proxy equals construct without validation",),
    ),
    ResearchPackageKind.THEORY_VALIDATION: _contract(
        ResearchPackageKind.THEORY_VALIDATION, "THEORY_MATHEMATICAL_PROPOSAL",
        ("formal_claim", "assumptions", "proof_or_counterexample_strategy", "validity_domain"),
        ("proof obligation or counterexample criterion", "assumption boundary stated"),
        ("empirical intervention is required",),
    ),
    ResearchPackageKind.GENERALIZATION_VALIDATION: _contract(
        ResearchPackageKind.GENERALIZATION_VALIDATION, "GENERALIZATION_TRANSPORTABILITY_PROPOSAL",
        ("source_domain", "target_domain", "shift_definition", "external_validation_protocol", "transport_rule"),
        ("target-domain performance/claim assessed", "shift-specific limitation reported"),
        ("one failure proves universal non-generalization",),
    ),
    ResearchPackageKind.METHOD_EVALUATION: _contract(
        ResearchPackageKind.METHOD_EVALUATION, "METHOD_DESIGN_EVALUATION_PROPOSAL",
        ("current_method", "failure_mode", "alternative_design", "bias_analysis", "evaluation_criterion"),
        ("alternative is evaluably distinct", "failure or bias is measured"),
        ("method change establishes a mechanism",),
    ),
    ResearchPackageKind.DATA_ACQUISITION: _contract(
        ResearchPackageKind.DATA_ACQUISITION, "DATA_COVERAGE_ACQUISITION_PROPOSAL",
        ("coverage_deficiency", "impact_on_claim", "acquisition_plan", "quality_assurance", "coverage_completion_rule"),
        ("missing coverage is measured", "acquired data meet declared quality/coverage rule"),
        ("missing data prove phenomenon absence",),
    ),
    ResearchPackageKind.SCALE_INTEGRATION: _contract(
        ResearchPackageKind.SCALE_INTEGRATION, "SCALE_INTEGRATION_PROPOSAL",
        ("source_scale", "target_scale", "bridge_variable", "coupling_or_aggregation_rule", "bridge_test"),
        ("cross-scale relation is tested", "bridge assumptions are stated"),
        ("single-scale mediator explains all scales",),
    ),
    ResearchPackageKind.BENCHMARK_DESIGN: _contract(
        ResearchPackageKind.BENCHMARK_DESIGN, "BENCHMARK_COMPARISON_PROPOSAL",
        ("candidate_systems", "common_task", "shared_metric", "evaluation_protocol", "reproducibility_plan"),
        ("fair comparison protocol passes", "results are reproducible under the protocol"),
        ("benchmark score proves scientific truth",),
    ),
    ResearchPackageKind.TRANSLATION_FEASIBILITY: _contract(
        ResearchPackageKind.TRANSLATION_FEASIBILITY, "TRANSLATION_IMPLEMENTATION_PROPOSAL",
        ("validated_source_claim", "deployment_context", "implementation_barrier", "feasibility_criterion", "real_world_validation_plan"),
        ("feasibility criterion is assessed in declared setting", "deployment limitations are reported"),
        ("lack of deployment is a theoretical gap",),
    ),
}


def authoring_contract_for_package(package: dict[str, Any]) -> ProposalAuthoringContract:
    try:
        kind = ResearchPackageKind(str(package.get("package_kind") or ""))
    except ValueError as exc:
        raise ValueError("Proposal V2 requires a recognized ResearchPackageKind") from exc
    return PROPOSAL_AUTHORING_CONTRACTS[kind]


def authoring_contract_payload(package: dict[str, Any]) -> dict[str, Any]:
    contract = authoring_contract_for_package(package)
    return {
        "schema_version": PROPOSAL_AUTHORING_CONTRACT_VERSION,
        "package_kind": contract.package_kind.value,
        "proposal_kind": contract.proposal_kind,
        "required_sections": list(contract.required_sections),
        "required_design_fields": list(contract.required_design_fields),
        "success_criteria": list(contract.success_criteria),
        "prohibited_claim_patterns": list(contract.prohibited_claim_patterns),
    }
