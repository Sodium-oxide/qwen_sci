"""Domain-neutral research-mode contracts for hypothesis readiness.

Scientific hypotheses are not all controlled wet-lab interventions.  A
theorem, an astronomical model discriminator, a natural experiment, an
instrument calibration claim, and an in-silico ablation can all be falsifiable
without pretending to be the same kind of experiment.  This module makes that
distinction explicit before Socrates hands a gap to MingLi.

The modes describe the *epistemic design*, not a discipline.  They intentionally
contain no physics, life-science, chemistry, or neuroscience vocabulary.
"""
from __future__ import annotations

import re
from typing import Any

try:
    from ._input_ontology import classify_input_candidate
    from ._intervention_ontology import classify_intervention_candidate, classify_mediator_candidate
    from ._outcome_ontology import classify_outcome_candidate
except ImportError:
    from _input_ontology import classify_input_candidate
    from _intervention_ontology import classify_intervention_candidate, classify_mediator_candidate
    from _outcome_ontology import classify_outcome_candidate


CONTROLLED_INTERVENTION = "CONTROLLED_INTERVENTION"
NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT = "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT"
OBSERVATIONAL_MODEL_DISCRIMINATION = "OBSERVATIONAL_MODEL_DISCRIMINATION"
COMPUTATIONAL_INTERVENTION = "COMPUTATIONAL_INTERVENTION"
INSTRUMENTATION_OR_MEASUREMENT = "INSTRUMENTATION_OR_MEASUREMENT"
LABORATORY_CONSTRAINT = "LABORATORY_CONSTRAINT"
THEORETICAL_OR_FORMAL = "THEORETICAL_OR_FORMAL"
UNRESOLVED_RESEARCH_DESIGN = "UNRESOLVED_RESEARCH_DESIGN"

RESEARCH_MODES = {
    CONTROLLED_INTERVENTION,
    NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT,
    OBSERVATIONAL_MODEL_DISCRIMINATION,
    COMPUTATIONAL_INTERVENTION,
    INSTRUMENTATION_OR_MEASUREMENT,
    LABORATORY_CONSTRAINT,
    THEORETICAL_OR_FORMAL,
}

_MODE_ALIASES = {
    "controlled": CONTROLLED_INTERVENTION,
    "controlled_intervention": CONTROLLED_INTERVENTION,
    "experiment": CONTROLLED_INTERVENTION,
    "experimental": CONTROLLED_INTERVENTION,
    "natural_experiment": NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT,
    "natural_experiment_or_quasi_experiment": NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT,
    "quasi_experiment": NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT,
    "observational": OBSERVATIONAL_MODEL_DISCRIMINATION,
    "observational_model_discrimination": OBSERVATIONAL_MODEL_DISCRIMINATION,
    "computational": COMPUTATIONAL_INTERVENTION,
    "computational_intervention": COMPUTATIONAL_INTERVENTION,
    "instrumentation": INSTRUMENTATION_OR_MEASUREMENT,
    "instrumentation_or_measurement": INSTRUMENTATION_OR_MEASUREMENT,
    "measurement": INSTRUMENTATION_OR_MEASUREMENT,
    "laboratory_constraint": LABORATORY_CONSTRAINT,
    "lab_constraint": LABORATORY_CONSTRAINT,
    "parameter_constraint": LABORATORY_CONSTRAINT,
    "theoretical": THEORETICAL_OR_FORMAL,
    "formal": THEORETICAL_OR_FORMAL,
    "theoretical_or_formal": THEORETICAL_OR_FORMAL,
    "unresolved_research_design": UNRESOLVED_RESEARCH_DESIGN,
}

_NATURAL_MARKERS = (
    "natural experiment", "quasi-experiment", "quasi experiment", "policy shock",
    "exogenous shock", "instrumental variable", "difference-in-differences",
    "difference in differences", "regression discontinuity", "interrupted time series",
)
_OBSERVATIONAL_MARKERS = (
    "observational", "cohort", "survey", "remote sensing", "telescope", "time series",
    "field observation", "monitoring", "population sample", "cross-sectional", "case-control",
    "model discrimination", "competing prediction",
)
_COMPUTATIONAL_MARKERS = (
    "simulation", "in silico", "algorithm", "model ablation", "feature ablation",
    "parameter sweep", "boundary-condition", "counterfactual simulation",
)
_COMPUTATIONAL_OPERATION_MARKERS = (
    "variation", "vary", "sweep", "ablation", "replace", "substitute", "parameter",
    "model", "repeated", "repeat", "iteration", "scenario", "sensitivity", "monte carlo",
    "initial condition", "boundary condition", "reintroduction", "resampling",
)
_CONTROLLED_DESIGN_MARKERS = (
    "controlled experiment", "controlled trial", "randomized", "randomised",
    "assigned to", "manipulated", "perturbed", "treated with", "exposed to",
    "varied ", "variation of", "dose-response", "dose response",
)
_INSTRUMENTATION_MARKERS = (
    "calibration", "instrument", "detector", "sensor", "reference material", "blank",
    "transfer function", "point-spread", "measurement uncertainty", "resolution", "noise floor",
)
_INSTRUMENT_CONFIGURATION_MARKERS = (
    "calibration", "configuration", "detector gain", "reference material", "reference source",
    "blank", "instrument setting", "sensor setting", "alignment setting",
)
_INSTRUMENT_TRANSFER_MARKERS = (
    "transfer function", "drift", "measurement bias", "systematic error", "noise floor",
    "point-spread", "response function", "resolution", "uncertainty propagation",
)
_INSTRUMENT_OUTCOME_MARKERS = (
    "signal-to-noise", "signal to noise", "uncertainty", "measurement error", "detection limit",
    "bias", "resolution", "precision", "accuracy",
)
_LAB_CONSTRAINT_MARKERS = (
    "constrain", "constraint", "cross section", "half-life", "half life", "rate constant",
    "diffusion coefficient", "binding constant", "material parameter", "quantitative parameter",
    "calibrated parameter", "measured parameter",
)
_THEORY_MARKERS = (
    "theorem", "proof", "axiom", "lemma", "derivation", "formal", "analytical solution",
    "closed-form", "closed form", "mathematical model", "theoretical prediction",
)
_QUANTITATIVE_MARKERS = (
    "quantitative", "measured", "measurement", "estimate", "estimate", "rate", "coefficient",
    "constant", "uncertainty", "confidence interval", "standard deviation", "calibrated",
)
_MODEL_PROPAGATION_MARKERS = (
    "model input", "inference", "propagate", "propagation", "prediction", "network", "simulation",
    "numerical", "parameterization", "constraint",
)


def _text(*values: Any) -> str:
    return " ".join(str(value or "") for value in values).strip()


def _compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _mode_value(value: Any) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return _MODE_ALIASES.get(key, str(value or "").strip().upper() if str(value or "").strip().upper() in RESEARCH_MODES else "")


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _instrumentation_signature(input_value: str, mediator: str, outcome: str, comparison: str) -> bool:
    return bool(
        _contains_any(input_value, _INSTRUMENT_CONFIGURATION_MARKERS)
        and _contains_any(mediator, _INSTRUMENT_TRANSFER_MARKERS)
        and _contains_any(outcome, _INSTRUMENT_OUTCOME_MARKERS)
        and _comparison(comparison)
    )


def _source_bound_design_text(bundle: dict[str, Any]) -> str:
    design = bundle.get("research_design_evidence") if isinstance(bundle.get("research_design_evidence"), dict) else {}
    if str(design.get("status") or "").upper() not in {"SOURCE_BOUND", "SUPPORTED", "PASSED"}:
        return ""
    fragments = design.get("fragment_alignments") if isinstance(design.get("fragment_alignments"), list) else []
    return _text(
        *(
            item.get("excerpt") for item in fragments
            if isinstance(item, dict)
            and (
                item.get("semantic_verdict") == "ALIGNED_TRIADIC_EVIDENCE"
                or item.get("source_bound_design_evidence") is True
            )
        )
    ).lower()


def _source_bound_fragment_ids(bundle: dict[str, Any]) -> list[str]:
    design = bundle.get("research_design_evidence") if isinstance(bundle.get("research_design_evidence"), dict) else {}
    fragments = design.get("fragment_alignments") if isinstance(design.get("fragment_alignments"), list) else []
    return [
        str(item.get("source_unit_id") or "")
        for item in fragments
        if isinstance(item, dict)
        and (
            item.get("semantic_verdict") == "ALIGNED_TRIADIC_EVIDENCE"
            or item.get("source_bound_design_evidence") is True
        )
        and str(item.get("source_unit_id") or "")
    ][:16]


def _declared_research_mode(source: dict[str, Any]) -> str:
    """Return only intentional, human/declaration-like design statements.

    A generated gap's ``research_mode`` is intentionally excluded.  It may
    already have inherited an off-topic paper.  Project/sub-hypothesis level
    declarations remain useful priors, provided the matching design signature
    is also complete below.
    """
    if not isinstance(source, dict):
        return ""
    for key in ("declared_research_mode", "declared_research_design", "research_design", "research_mode"):
        value = source.get(key)
        if isinstance(value, dict):
            value = value.get("mode") or value.get("recommended_mode") or value.get("value")
        resolved = _mode_value(value)
        if resolved:
            return resolved
    return ""


def _design_candidate(
    mode: str,
    required_signals: dict[str, bool],
    *,
    fragment_ids: list[str],
    source: str,
) -> dict[str, Any]:
    total = max(1, len(required_signals))
    passed = sum(bool(value) for value in required_signals.values())
    complete = passed == total
    # A complete source-bound design is decisive.  Incomplete candidates are
    # still retained for diagnostics but receive a strictly sub-threshold
    # score so a keyword occurrence cannot steal the research mode.
    score = round((passed / total) if complete else (passed / total) * 0.49, 3)
    return {
        "mode": mode,
        "score": score,
        "complete_signature": complete,
        "required_signals": required_signals,
        "fragment_ids": list(fragment_ids),
        "source": source,
    }


def infer_research_design(
    project: dict[str, Any],
    subhypothesis: dict[str, Any],
    causal_bundle: dict[str, Any],
    evidence_fragments: list[dict[str, Any]] | None = None,
    *,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score research-design signatures from source-bound causal evidence.

    This function is domain-neutral: it distinguishes *how a claim is tested*
    (calculation, constrained laboratory measurement, observation,
    instrumentation, formal derivation, or controlled intervention) without
    inserting any discipline-specific ontology.  It never reads
    ``gap.research_mode``.
    """
    causal_bundle = causal_bundle if isinstance(causal_bundle, dict) else {}
    contract = contract if isinstance(contract, dict) else {}
    fragments = evidence_fragments if isinstance(evidence_fragments, list) else []
    input_value = _compact(causal_bundle.get("intervention") or contract.get("input"))
    mediator_value = _compact(causal_bundle.get("mediator") or contract.get("proposed_mediator") or contract.get("mediator"))
    outcome_value = _compact(causal_bundle.get("outcome") or contract.get("output"))
    comparison_value = _compact(causal_bundle.get("comparison") or contract.get("comparison"))
    falsification_value = _compact(causal_bundle.get("falsification") or contract.get("falsification"))
    design_text = _source_bound_design_text(causal_bundle)
    if not design_text:
        design_text = _text(
            input_value, mediator_value, outcome_value, comparison_value,
            contract.get("context"), subhypothesis.get("focus"), subhypothesis.get("retrieval_query"),
        ).lower()
        source = "contract_and_design_prior"
    else:
        source = "source_bound_design_inference"
    fragment_ids = _source_bound_fragment_ids(causal_bundle)
    if not fragment_ids:
        fragment_ids = [
            str(item.get("source_unit_id") or "")
            for item in fragments
            if isinstance(item, dict) and item.get("semantic_verdict") == "ALIGNED_TRIADIC_EVIDENCE"
        ][:16]
    intervention = classify_intervention_candidate(input_value)
    controlled_input = classify_input_candidate(
        input_value,
        research_mode=CONTROLLED_INTERVENTION,
        source_unit_ids=fragment_ids,
        # Research-mode inference decides what kind of provenance the already
        # source-bound phrase represents.  The final mode contract performs
        # the mandatory provenance check again.
        require_source_bound=False,
    )
    mediator = classify_mediator_candidate(mediator_value)
    combined = _text(input_value, mediator_value, outcome_value, comparison_value, falsification_value, design_text).lower()
    has_comparator = _comparison(comparison_value)
    candidates = [
        _design_candidate(
            INSTRUMENTATION_OR_MEASUREMENT,
            {
                "configuration_or_calibration_change": _contains_any(input_value.lower(), _INSTRUMENT_CONFIGURATION_MARKERS),
                "error_transfer_mechanism": _contains_any(mediator_value.lower(), _INSTRUMENT_TRANSFER_MARKERS),
                "signal_or_uncertainty_readout": _contains_any(outcome_value.lower(), _INSTRUMENT_OUTCOME_MARKERS),
                "reference_or_calibration_comparator": has_comparator,
            },
            fragment_ids=fragment_ids, source=source,
        ),
        _design_candidate(
            COMPUTATIONAL_INTERVENTION,
            {
                "parameterized_transformation": (
                    intervention.get("category") == "direct_computational_intervention"
                    or _contains_any(input_value.lower(), _COMPUTATIONAL_MARKERS)
                    or (
                        _contains_any(design_text, _COMPUTATIONAL_MARKERS)
                        and _contains_any(
                            _text(input_value, design_text).lower(),
                            _COMPUTATIONAL_OPERATION_MARKERS,
                        )
                    )
                ),
                "model_or_simulation_mechanism": _contains_any(_text(mediator_value, design_text).lower(), _COMPUTATIONAL_MARKERS) or "model" in _text(mediator_value, design_text).lower(),
                "calculable_output": bool(outcome_value),
                "baseline_comparator": has_comparator,
            },
            fragment_ids=fragment_ids, source=source,
        ),
        _design_candidate(
            LABORATORY_CONSTRAINT,
            {
                "controlled_sample_or_condition": bool(intervention.get("admissible_as_intervention")) or _contains_any(input_value.lower(), ("temperature", "pressure", "concentration", "composition", "dose", "sample", "condition")),
                "quantitative_parameter_constraint": _contains_any(_text(input_value, mediator_value, outcome_value).lower(), _LAB_CONSTRAINT_MARKERS),
                "repeatable_quantitative_measurement": bool(outcome_value) and _contains_any(_text(outcome_value, design_text).lower(), _QUANTITATIVE_MARKERS),
                "model_or_inference_propagation": _contains_any(_text(mediator_value, design_text).lower(), _MODEL_PROPAGATION_MARKERS),
                "reference_or_uncertainty_comparator": has_comparator,
                "explicit_falsification": _falsification(falsification_value),
            },
            fragment_ids=fragment_ids, source=source,
        ),
        _design_candidate(
            OBSERVATIONAL_MODEL_DISCRIMINATION,
            {
                "competing_predictions": bool(contract.get("competing_predictions") or contract.get("alternative_predictions")) or _contains_any(combined, ("competing", "alternative", "discriminate")),
                "measurement_or_sampling_plan": _contains_any(combined, _OBSERVATIONAL_MARKERS),
                "discriminating_readout": bool(outcome_value),
                "model_discriminator_or_threshold": has_comparator or _contains_any(combined, ("threshold", "decision rule")),
            },
            fragment_ids=fragment_ids, source=source,
        ),
        _design_candidate(
            NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT,
            {
                "specified_exposure_or_shock": bool(input_value) and _contains_any(combined, _NATURAL_MARKERS),
                "identification_strategy": _contains_any(combined, _NATURAL_MARKERS),
                "confounding_or_comparator": has_comparator or bool(contract.get("confounders") or contract.get("adjustment_set")),
                "observable_outcome": bool(outcome_value),
            },
            fragment_ids=fragment_ids, source=source,
        ),
        _design_candidate(
            THEORETICAL_OR_FORMAL,
            {
                "explicit_assumptions": bool(contract.get("assumptions") or contract.get("premises") or input_value),
                "derivation_or_proof_obligation": _contains_any(combined, _THEORY_MARKERS),
                "calculable_prediction_or_theorem": bool(outcome_value),
                "counterexample_or_failure_condition": _falsification(falsification_value),
            },
            fragment_ids=fragment_ids, source=source,
        ),
        _design_candidate(
            CONTROLLED_INTERVENTION,
            {
                "operational_intervention": bool(
                    intervention.get("admissible_as_intervention")
                    or (
                        controlled_input.get("ontology_valid")
                        and _contains_any(design_text, _CONTROLLED_DESIGN_MARKERS)
                    )
                ),
                "specific_mechanism": bool(mediator.get("admissible_as_mediator")),
                "observable_outcome": bool(outcome_value),
            },
            fragment_ids=fragment_ids, source=source,
        ),
    ]
    complete = [item for item in candidates if item.get("complete_signature")]
    # Ties are resolved by signature specificity, not by keyword ordering.
    specificity = {
        INSTRUMENTATION_OR_MEASUREMENT: 7,
        LABORATORY_CONSTRAINT: 6,
        COMPUTATIONAL_INTERVENTION: 5,
        NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT: 4,
        OBSERVATIONAL_MODEL_DISCRIMINATION: 3,
        THEORETICAL_OR_FORMAL: 2,
        CONTROLLED_INTERVENTION: 1,
    }
    selected = max(complete, key=lambda item: (float(item.get("score") or 0.0), specificity.get(str(item.get("mode") or ""), 0)), default=None)
    return {
        "version": "research_design_inference_v2",
        "recommended_mode": str(selected.get("mode") if selected else UNRESOLVED_RESEARCH_DESIGN),
        "confidence": float(selected.get("score") or 0.0) if selected else 0.0,
        "mode_candidates": candidates,
        "conflicts": [],
        "supporting_fragment_ids": fragment_ids,
        "source": source,
    }


def resolve_research_mode(
    project: dict[str, Any],
    gap: dict[str, Any],
    contract: dict[str, Any],
    bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Infer epistemic design from a trusted causal chain, not stray paper words.

    The gap itself is intentionally not an authoritative explicit source:
    TanXi gaps can be created from a limitation or an imported full-text
    fragment.  Instrumentation in particular requires a complete
    configuration -> transfer/error -> signal/uncertainty signature, rather
    than a single occurrence of ``detector`` or ``measurement``.
    """
    bundle = bundle if isinstance(bundle, dict) else {}
    subhypothesis = {}
    target = str(gap.get("sub_hypothesis_id") or bundle.get("sub_hypothesis_id") or "")
    for item in project.get("sub_hypotheses", []) if isinstance(project.get("sub_hypotheses"), list) else []:
        if isinstance(item, dict) and str(item.get("id") or "") == target:
            subhypothesis = item
            break
    inference = infer_research_design(project, subhypothesis, bundle, contract=contract)
    inferred_mode = str(inference.get("recommended_mode") or UNRESOLVED_RESEARCH_DESIGN)
    candidate_by_mode = {
        str(item.get("mode") or ""): item
        for item in inference.get("mode_candidates", [])
        if isinstance(item, dict)
    }
    # Explicit project/subhypothesis design declarations have priority, but
    # only where the matching mode's structural signature is actually
    # complete.  A stale/generated gap declaration is never consulted.
    for owner, source in (("sub_hypothesis", subhypothesis), ("project", project), ("contract", contract)):
        declared = _declared_research_mode(source)
        candidate = candidate_by_mode.get(declared, {})
        # A deliberate project/subhypothesis/contract design declaration is a
        # higher-quality prior than a keyword.  Instrumentation remains the
        # exception: it always needs the full calibration→transfer→readout
        # signature because that ontology is uniquely easy to contaminate.
        if declared and (declared != INSTRUMENTATION_OR_MEASUREMENT or candidate.get("complete_signature")):
            inference.update({
                "recommended_mode": declared,
                "confidence": 1.0,
                "source": f"{owner}.declared_research_design",
                "declared_mode": declared,
            })
            break
    return {
        "mode": str(inference.get("recommended_mode") or inferred_mode),
        "source": str(inference.get("source") or "source_bound_design_inference"),
        "confidence": inference.get("confidence", 0.0),
        "mode_candidates": list(inference.get("mode_candidates") or []),
        "supporting_fragment_ids": list(inference.get("supporting_fragment_ids") or []),
        "research_design_inference": inference,
    }


def _comparison(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in (" vs ", "versus", "compared", "comparison", "control", "baseline", "matched", "reference", "blank", "alternative", "null", "without"))


def _falsification(value: str) -> bool:
    lowered = value.lower()
    return bool(value) and any(marker in lowered for marker in (
        "falsif", "fail if", "does not", "no change", "unchanged", "null", "reject", "refute", "counterexample", "inconsistent", "absent",
    ))


def _value(contract: dict[str, Any], bundle: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = bundle.get(key) if key in bundle else contract.get(key)
        if isinstance(value, dict):
            value = value.get("value") or value.get("candidate") or value.get("claim")
        compact = _compact(value)
        if compact:
            return compact
    return ""


def _has_explicit_field(contract: dict[str, Any], bundle: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return bool(_value(contract, bundle, *keys))


def mode_specific_hypothesis_contract(
    project: dict[str, Any],
    gap: dict[str, Any],
    contract: dict[str, Any],
    bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the smallest falsifiable contract appropriate for one mode.

    This does not waive evidence requirements.  It merely refuses to demand a
    laboratory manipulation from a theorem or an astronomical observation.
    The Socrates caller additionally validates source traceability, formal
    publication status, project identity, and project/topic alignment.
    """
    bundle = bundle if isinstance(bundle, dict) else {}
    resolution = resolve_research_mode(project, gap, contract, bundle)
    mode = resolution["mode"]
    input_value = _value(contract, bundle, "intervention", "input", "exposure", "configuration", "assumptions")
    mediator = _value(contract, bundle, "mediator", "proposed_mediator", "mechanism", "identification_strategy")
    outcome = _value(contract, bundle, "outcome", "output", "prediction", "readout")
    comparison = _value(contract, bundle, "comparison", "control", "baseline", "decision_rule")
    falsification = _value(contract, bundle, "falsification", "failure_condition", "counterexample_condition")
    text = _text(input_value, mediator, outcome, comparison, falsification, contract.get("context"), gap.get("description")).lower()
    provenance = bundle.get("causal_field_provenance") if isinstance(bundle.get("causal_field_provenance"), dict) else {}
    input_provenance = provenance.get("input") if isinstance(provenance.get("input"), dict) else {}
    outcome_provenance = provenance.get("outcome") if isinstance(provenance.get("outcome"), dict) else {}
    source_bound_bundle = str(bundle.get("version") or "").startswith("gap_evidence_bundle_v")
    input_assessment = classify_input_candidate(
        input_value,
        research_mode=mode,
        source_unit_ids=list(input_provenance.get("source_unit_ids") or []),
        require_source_bound=source_bound_bundle,
    )
    mediator_assessment = classify_mediator_candidate(mediator)
    target_subhypothesis = next(
        (
            item for item in (project.get("sub_hypotheses") or [])
            if isinstance(item, dict) and str(item.get("id") or "") == str(gap.get("sub_hypothesis_id") or bundle.get("sub_hypothesis_id") or "")
        ),
        {},
    )
    target_outcome_terms = [
        *(str(item) for item in (target_subhypothesis.get("dependent_variables") or []) if str(item).strip()),
        str((target_subhypothesis.get("causal_chain") or [""])[-1]) if target_subhypothesis.get("causal_chain") else "",
        outcome,
    ]
    outcome_assessment = classify_outcome_candidate(
        outcome,
        research_mode=mode,
        target_outcome_terms=target_outcome_terms,
        source_unit_ids=list(outcome_provenance.get("source_unit_ids") or []),
        require_target_alignment=True,
        require_source_bound=source_bound_bundle,
    )
    common = {
        "specific_mediator_or_discriminating_mechanism": bool(mediator_assessment.get("admissible_as_mediator")),
        "observable_or_calculable_outcome": bool(outcome_assessment.get("admissible_as_outcome")),
        "explicit_falsification": _falsification(falsification),
    }
    if mode == CONTROLLED_INTERVENTION:
        required = {
            "operational_intervention": bool(input_assessment.get("admissible_as_input")),
            **common,
            "matched_control_or_comparator": _comparison(comparison),
        }
    elif mode == NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT:
        required = {
            "specified_exposure_or_shock": bool(input_assessment.get("admissible_as_input")),
            "identification_strategy": _has_explicit_field(contract, bundle, ("identification_strategy", "design", "comparison")) or any(marker in text for marker in _NATURAL_MARKERS),
            "confounding_or_comparator": _comparison(comparison) or _has_explicit_field(contract, bundle, ("confounders", "adjustment_set")),
            **common,
        }
    elif mode == OBSERVATIONAL_MODEL_DISCRIMINATION:
        required = {
            "specified_natural_or_model_condition": bool(input_assessment.get("admissible_as_input")),
            "competing_predictions": _has_explicit_field(contract, bundle, ("competing_predictions", "alternative_predictions", "alternative_mechanisms")) or "competing" in text or "alternative" in text,
            "measurement_or_sampling_plan": _has_explicit_field(contract, bundle, ("measurement_plan", "sampling_plan", "observability")) or any(marker in text for marker in _OBSERVATIONAL_MARKERS),
            "discriminating_readout": bool(outcome_assessment.get("admissible_as_outcome")),
            "model_discriminator_or_threshold": _comparison(comparison) or _has_explicit_field(contract, bundle, ("decision_rule", "discriminator", "threshold")),
            "explicit_falsification": _falsification(falsification),
        }
    elif mode == COMPUTATIONAL_INTERVENTION:
        required = {
            "parameterized_transformation_or_ablation": bool(input_assessment.get("admissible_as_input")),
            **common,
            "baseline_or_ablation_comparator": _comparison(comparison),
        }
    elif mode == INSTRUMENTATION_OR_MEASUREMENT:
        required = {
            "configuration_or_calibration_change": bool(input_assessment.get("admissible_as_input")),
            "transfer_or_error_mechanism": bool(mediator_assessment.get("admissible_as_mediator")) and _contains_any(mediator.lower(), _INSTRUMENT_TRANSFER_MARKERS),
            "signal_or_uncertainty_readout": bool(outcome_assessment.get("admissible_as_outcome")) and _contains_any(outcome.lower(), _INSTRUMENT_OUTCOME_MARKERS),
            "calibration_or_reference_comparator": _comparison(comparison),
            "explicit_falsification": _falsification(falsification),
        }
    elif mode == LABORATORY_CONSTRAINT:
        lab_candidate = next(
            (
                item for item in (resolution.get("mode_candidates") or [])
                if isinstance(item, dict) and item.get("mode") == LABORATORY_CONSTRAINT
            ),
            {},
        )
        lab_signals = lab_candidate.get("required_signals") if isinstance(lab_candidate.get("required_signals"), dict) else {}
        required = {
            "controlled_sample_or_condition": bool(input_assessment.get("admissible_as_input")) and bool(lab_signals.get("controlled_sample_or_condition")),
            "quantitative_parameter_constraint": bool(lab_signals.get("quantitative_parameter_constraint")),
            "measurement_protocol_or_observable": bool(lab_signals.get("repeatable_quantitative_measurement")),
            "model_or_inference_propagation": bool(lab_signals.get("model_or_inference_propagation")),
            "reference_or_uncertainty_comparator": bool(lab_signals.get("reference_or_uncertainty_comparator")),
            "explicit_falsification": bool(lab_signals.get("explicit_falsification")),
        }
    elif mode == UNRESOLVED_RESEARCH_DESIGN:
        required = {"source_bound_research_design": False}
    else:  # THEORETICAL_OR_FORMAL
        required = {
            "explicit_assumptions": bool(input_assessment.get("admissible_as_input")),
            "derivation_or_proof_obligation": _has_explicit_field(contract, bundle, ("derivation", "proof_obligation", "proof", "formal_obligation")) or any(marker in text for marker in ("derive", "derivation", "proof", "theorem")),
            "theorem_or_calculable_prediction": bool(outcome_assessment.get("admissible_as_outcome")),
            "counterexample_or_failure_condition": _falsification(falsification),
        }
    missing = [name for name, passed in required.items() if not passed]
    return {
        "version": "research_mode_contract_v1",
        "mode": mode,
        "mode_resolution": resolution,
        "status": "READY" if not missing else "BLOCKED",
        "required": required,
        "missing_requirements": missing,
        "normalized_core_chain": {
            "input_or_intervention": input_value,
            "mediator": mediator,
            "observable_outcome": outcome,
            "comparison": comparison,
            "falsification": falsification,
        },
        "role_assessments": {
            "input": input_assessment,
            "mediator": mediator_assessment,
            "outcome": outcome_assessment,
        },
    }
