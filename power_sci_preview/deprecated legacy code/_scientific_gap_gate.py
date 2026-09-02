from __future__ import annotations

from hashlib import sha256
from typing import Any, Callable
import json
import re


CAUSAL_SCIENTIFIC_GAP_TYPES = frozenset(
    {
        "causal_chain_break",
        "causal_mediation_unresolved",
        "direct_mechanism_gap",
        "mechanism_gap",
        "mechanism_problem",
        "cross_hypothesis_coupling",
        "implicit_tabi",
    }
)

INTERVENTION_READY = "INTERVENTION_READY"
MEASURABLE_BIOMARKER = "MEASURABLE_BIOMARKER"
# Backward-compatible serialized value.  The gate now interprets it as a
# measurable state variable in any natural-science field, not only biology.
MEASURABLE_STATE_VARIABLE = MEASURABLE_BIOMARKER
PHYSICAL_STRUCTURE = "PHYSICAL_STRUCTURE"
ABSTRACT_STATE = "ABSTRACT_STATE"
METHOD_TOOL = "METHOD_TOOL"
RELATIONAL_CLAUSE = "RELATIONAL_CLAUSE"
MEASURABLE_OUTCOME = "MEASURABLE_OUTCOME"
UNKNOWN_ENTITY = "UNKNOWN_ENTITY"

_METHOD_MARKERS_BY_DOMAIN = {
    "mathematics_statistics_computing": (
        "finite element", "monte carlo", "bayesian inference", "numerical integration", "pde solver",
        "optimization algorithm", "proof assistant", "regression", "classifier", "simulation",
        "finite-element method", "monte carlo method", "bayesian reasoning", "numerical simulation",
    ),
    "physics_astronomy": (
        "x-ray diffraction", "neutron scattering", "interferometry", "particle detector",
        "spectroscopy", "telescope", "raman spectroscopy", "diffraction", "scattering", "interferometer", "spectral analysis",
    ),
    "chemistry_materials": (
        "chromatography", "mass spectrometry", "nuclear magnetic resonance", "nmr", "titration",
        "calorimetry", "electrochemical workstation", "xrd", "sem imaging", "tem imaging",
        "atomic force microscopy", "nanoindentation", "tensile test", "chromatographic analysis", "mass-spectrometric analysis", "nmr spectroscopy",
        "titrimetric analysis", "calorimetric analysis", "nanoindentation testing", "uniaxial tensile testing",
    ),
    "biology_medicine": (
        "sequencing", "rna-seq", "single-cell", "microscopy", "flow cytometry", "pcr",
        "western blot", "elisa", "assay", "mri", "computed tomography", "pet imaging",
        "ultrasound", "biopsy", "clinical trial", "sequence analysis", "microscopic examination", "flow-cytometric analysis", "magnetic resonance imaging",
        "computed-tomographic imaging", "ultrasonography", "tissue biopsy", "detection method",
    ),
    "agriculture_food": (
        "field trial", "plot experiment", "soil assay", "high-throughput phenotyping",
        "agricultural field experiment", "field-plot experiment", "soil testing", "high-throughput phenotyping analysis",
    ),
    "earth_environment": (
        "remote sensing", "gis analysis", "lidar", "core sampling", "weather radar",
        "seismic tomography", "eddy covariance", "remote-sensing analysis", "geographic information system", "laser radar",
        "geological core sampling", "meteorological radar", "seismic tomographic imaging", "eddy-covariance measurement",
    ),
    "engineering_energy": (
        "computational fluid dynamics", "cfd", "digital image correlation", "fatigue test",
        "wind tunnel", "impedance spectroscopy", "hardware-in-the-loop", "vibration testing", "fatigue testing",
        "wind-tunnel experiment", "impedance-spectroscopic analysis", "hardware-in-the-loop simulation",
    ),
}
_ABSTRACT_MARKERS_BY_DOMAIN = {
    "general": (
        "education", "adaptation", "well-adapted", "health", "wellbeing", "homeostasis",
        "fitness", "resilience", "ripple effect", "cascade effect", "scientific impact",
        "system performance", "overall quality", "immune education", "adaptive state", "health state", "steady state",
        "system resilience", "ripple-effect state", "cascade-effect state", "scientific influence", "aggregate performance", "composite quality",
    ),
    "life_environment": (
        "immune response", "ecological function", "ecosystem health", "immune-system response", "ecosystem function", "ecological health",
    ),
}
_STRUCTURE_MARKERS_BY_DOMAIN = {
    "physics_chemistry_materials": (
        "crystal lattice", "grain boundary", "phase boundary", "catalyst surface", "electrode",
        "porous scaffold", "thin film", "heterojunction", "crystalline lattice", "crystalline grain boundary", "interphase boundary", "catalytic surface",
        "electrode structure", "thin-film structure", "heterojunction structure",
    ),
    "biology_medicine": (
        "root cap", "membrane", "tissue", "organelle", "capsule", "biofilm", "chromosome",
        "cell wall", "vascular bundle", "plant root cap", "cell membrane", "biological tissue", "cellular organelle", "biological membrane", "chromosomal structure",
        "cell-wall structure", "plant vascular bundle",
    ),
    "agriculture_earth_environment": (
        "canopy", "soil aggregate", "rhizosphere", "aquifer", "fault zone", "sediment layer",
        "atmospheric boundary layer", "vegetation canopy", "soil aggregate structure", "plant rhizosphere", "groundwater aquifer", "geological fault zone",
        "sedimentary layer", "planetary boundary layer",
    ),
    "engineering_energy": (
        "interface", "composite matrix", "reactor", "turbine blade", "bearing", "bridge girder",
        "circuit", "heat exchanger", "material interface", "composite-material matrix", "chemical reactor", "turbomachinery blade", "mechanical bearing",
        "bridge main girder", "electrical circuit", "thermal heat exchanger",
    ),
}
_STATE_VARIABLE_MARKERS_BY_DOMAIN = {
    "mathematics_statistics_computing": (
        "lyapunov exponent", "condition number", "loss value", "posterior probability",
        "convergence rate", "error norm", "lyapunov characteristic exponent", "matrix condition number", "bayesian posterior probability", "numerical convergence rate", "numerical error norm",
    ),
    "physics_astronomy": (
        "magnetic susceptibility", "field strength", "spin polarization", "band gap", "carrier density",
        "velocity", "temperature", "pressure", "potential", "magnetic susceptibility coefficient", "electromagnetic field strength", "electron spin polarization", "electronic band gap", "charge-carrier concentration",
    ),
    "chemistry_materials": (
        "concentration", "reaction rate", "redox potential", "ph value", "phase fraction",
        "phase transition", "phase-transition", "lattice distortion", "distortion", "charge transfer",
        "conductivity", "resistance", "impedance", "capacitance", "energy barrier",
        "free energy", "entropy", "stiffness", "viscosity", "porosity", "stress", "strain", "permeability",
        "chemical concentration", "chemical reaction rate", "oxidation-reduction potential", "material phase fraction", "phase transformation", "crystal-lattice distortion", "structural distortion", "interfacial charge transfer", "electrical conductivity", "electrical resistance", "electrical impedance",
        "electrical capacitance", "activation-energy barrier", "gibbs free energy", "thermodynamic entropy", "mechanical stiffness", "dynamic viscosity", "material porosity", "mechanical stress", "mechanical strain", "hydraulic permeability",
    ),
    "biology_medicine": (
        "cytokine", "chemokine", "protein", "transcript", "metabolite", "expression", "abundance",
        "methylation", "copy number", "cell count", "viral load", "il-", "tnf", "ifn", "cytokine level",
        "chemokine level", "protein abundance", "transcript abundance", "metabolite abundance", "gene-expression level", "relative abundance", "dna methylation", "genomic copy number", "cellular count", "pathogen viral load",
    ),
    "agriculture_food": (
        "soil moisture", "soil nitrate", "nutrient content", "chlorophyll content", "water-use efficiency",
        "grain protein", "soil water content", "soil nitrate nitrogen", "plant nutrient content", "leaf chlorophyll content", "crop water-use efficiency", "grain protein content",
    ),
    "earth_environment": (
        "groundwater level", "pollutant concentration", "carbon flux", "aerosol optical depth", "salinity",
        "dissolved oxygen", "biodiversity index", "groundwater-table level", "environmental pollutant concentration", "ecosystem carbon flux", "atmospheric aerosol optical depth",
        "water salinity", "dissolved-oxygen concentration", "ecological biodiversity index",
    ),
    "engineering_energy": (
        "vibration amplitude", "thermal conductivity", "heat flux", "current density", "state of charge",
        "fatigue crack length", "bearing temperature", "mechanical vibration amplitude", "material thermal conductivity", "thermal heat-flux density", "electrical current density",
        "battery state of charge", "material fatigue-crack length", "mechanical-bearing temperature",
    ),
    "general_quantitative": (
        "ratio", "proportion", "fraction", "activity", "accessibility", "transport rate", "flux", "density",
        "level", "amplitude", "relative proportion", "measured activity", "transport flux", "material density", "measured level", "signal amplitude",
    ),
}
_OUTCOME_MARKERS_BY_DOMAIN = {
    "general": (
        "frequency", "rate", "yield", "survival", "mortality", "incidence", "severity", "score",
        "efficiency", "accuracy", "error", "mass", "length", "count", "lifetime", "failure rate",
        "response", "oscillation frequency", "process rate", "reaction yield", "production output", "organism survival", "organism mortality", "event incidence", "outcome severity", "evaluation score",
        "process efficiency", "measurement accuracy", "prediction error", "object count", "service lifetime", "engineering failure rate", "inflammatory outcome",
    ),
    "agriculture_environment": (
        "crop yield", "disease incidence", "emission intensity", "removal efficiency",
        "agricultural crop yield", "crop-disease incidence", "environmental emission intensity", "pollutant removal rate",
    ),
    "engineering_materials": (
        "fracture toughness", "energy efficiency", "device lifetime", "prediction error",
        "material fracture toughness", "system energy efficiency", "electronic-device lifetime", "model prediction error",
    ),
}


def _flatten_marker_groups(groups: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(marker for markers in groups.values() for marker in markers))


_METHOD_MARKERS = _flatten_marker_groups(_METHOD_MARKERS_BY_DOMAIN)
_ABSTRACT_MARKERS = _flatten_marker_groups(_ABSTRACT_MARKERS_BY_DOMAIN)
_STRUCTURE_MARKERS = _flatten_marker_groups(_STRUCTURE_MARKERS_BY_DOMAIN)
_BIOMARKER_MARKERS = _flatten_marker_groups(_STATE_VARIABLE_MARKERS_BY_DOMAIN)
_OUTCOME_MARKERS = _flatten_marker_groups(_OUTCOME_MARKERS_BY_DOMAIN)
_RELATIONAL_PREDICATE_RE = re.compile(
    r"\b(?:affect(?:s|ed|ing)?|caus(?:e|es|ed|ing)|lead(?:s|ing)?\s+to|regulat(?:e|es|ed|ing)|"
    r"influenc(?:e|es|ed|ing)|result(?:s|ed|ing)?\s+in|drive(?:s|n|ing)?|promot(?:e|es|ed|ing)|"
    r"instruct(?:s|ed|ing)?|mediate(?:s|d|ing)?|induc(?:e|es|ed|ing))\b",
    re.IGNORECASE,
)
_TEMPORAL_FORWARD_MARKERS = (
    "before", "after", "subsequent", "subsequently", "then", "later", "followed by",
    "precedes", "preceded", "time-lag", "time lag", "prior to", "subsequent to", "afterwards", "thereafter", "temporal lag",
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokens(value: Any) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_+\-./]*|[\u4e00-\u9fff]{2,}", _clean(value))
        if token.lower() not in {
            "a", "an", "and", "by", "for", "from", "in", "of", "or", "the", "to", "via", "with",
            "effect", "effects", "change", "changes", "response", "system", "process",
        }
    }


def _contains_marker(text: str, markers: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [marker for marker in markers if marker in lowered]


def _domain_marker_hits(text: str, groups: dict[str, tuple[str, ...]]) -> dict[str, list[str]]:
    lowered = text.lower()
    return {
        domain: [marker for marker in markers if marker in lowered]
        for domain, markers in groups.items()
        if any(marker in lowered for marker in markers)
    }


def classify_scientific_entity(value: Any, *, role: str = "") -> dict[str, Any]:
    """Assign an operational scientific type using deterministic, auditable rules.

    This is intentionally a conservative fallback rather than a biomedical-only
    dictionary. Existing input/intervention ontologies remain authoritative for
    whether an operation is actually admissible in the source-bound experiment.
    """
    text = _clean(value)
    if not text:
        return {
            "version": "scientific_entity_type_v2_all_natural_sciences",
            "value": "",
            "entity_type": UNKNOWN_ENTITY,
            "role": role,
            "measurable": False,
            "perturbable": False,
            "allowed_as_mediator": False,
            "reason": "No entity text was supplied.",
            "matched_markers": [],
            "matched_domains": [],
        }
    try:
        from ._intervention_ontology import classify_intervention_candidate
    except ImportError:
        from _intervention_ontology import classify_intervention_candidate
    intervention = classify_intervention_candidate(text)
    method_domains = _domain_marker_hits(text, _METHOD_MARKERS_BY_DOMAIN)
    abstract_domains = _domain_marker_hits(text, _ABSTRACT_MARKERS_BY_DOMAIN)
    structure_domains = _domain_marker_hits(text, _STRUCTURE_MARKERS_BY_DOMAIN)
    state_variable_domains = _domain_marker_hits(text, _STATE_VARIABLE_MARKERS_BY_DOMAIN)
    outcome_domains = _domain_marker_hits(text, _OUTCOME_MARKERS_BY_DOMAIN)
    method_hits = [marker for hits in method_domains.values() for marker in hits]
    abstract_hits = [marker for hits in abstract_domains.values() for marker in hits]
    structure_hits = [marker for hits in structure_domains.values() for marker in hits]
    biomarker_hits = [marker for hits in state_variable_domains.values() for marker in hits]
    outcome_hits = [marker for hits in outcome_domains.values() for marker in hits]
    relational = bool(_RELATIONAL_PREDICATE_RE.search(text))
    if intervention.get("admissible_as_intervention"):
        entity_type = INTERVENTION_READY
        reason = "The source text names a concrete manipulable operation or quantity."
        markers = list(intervention.get("matched_markers") or [])
    elif relational and len(_tokens(text)) >= 3:
        entity_type = RELATIONAL_CLAUSE
        reason = "The candidate is a causal proposition, not one atomic scientific entity."
        markers = ["causal_predicate"]
    elif method_hits:
        entity_type = METHOD_TOOL
        reason = "The candidate names a measurement or analysis tool."
        markers = method_hits
    elif abstract_hits:
        entity_type = ABSTRACT_STATE
        reason = "The candidate is an abstract or system-level state without an operational readout."
        markers = abstract_hits
    elif biomarker_hits:
        entity_type = MEASURABLE_BIOMARKER
        reason = "The candidate names a measurable state variable in a natural-science system."
        markers = biomarker_hits
    elif structure_hits:
        entity_type = PHYSICAL_STRUCTURE
        reason = "The candidate names a physical structure that requires a structure-specific manipulation."
        markers = structure_hits
    elif outcome_hits or re.search(r"(?:%|\b\d+(?:\.\d+)?\b|increase|decrease|elevated|reduced|rise|fall|higher|lower)", text, re.I):
        entity_type = MEASURABLE_OUTCOME
        reason = "The candidate names a quantitative or observable outcome."
        markers = outcome_hits or ["quantitative_readout"]
    else:
        entity_type = UNKNOWN_ENTITY
        reason = "The deterministic typer cannot establish operational identity; LLM or human entity resolution is required."
        markers = []
    measurable = entity_type in {MEASURABLE_BIOMARKER, MEASURABLE_OUTCOME, INTERVENTION_READY}
    perturbable = entity_type in {INTERVENTION_READY, PHYSICAL_STRUCTURE}
    return {
        "version": "scientific_entity_type_v2_all_natural_sciences",
        "value": text,
        "entity_type": entity_type,
        "role": role,
        "measurable": measurable,
        "perturbable": perturbable,
        "allowed_as_mediator": entity_type in {MEASURABLE_BIOMARKER, INTERVENTION_READY, PHYSICAL_STRUCTURE},
        "reason": reason,
        "matched_markers": markers,
        "matched_domains": sorted({
            *method_domains,
            *abstract_domains,
            *structure_domains,
            *state_variable_domains,
            *outcome_domains,
        }),
        "intervention_ontology": intervention,
    }


def causal_entity_equivalence(left: Any, right: Any) -> dict[str, Any]:
    left_text = _clean(left)
    right_text = _clean(right)
    left_tokens = _tokens(left_text)
    right_tokens = _tokens(right_text)
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    left_norm = " ".join(sorted(left_tokens))
    right_norm = " ".join(sorted(right_tokens))
    containment = bool(
        left_norm and right_norm and min(len(left_tokens), len(right_tokens)) >= 2
        and (left_tokens <= right_tokens or right_tokens <= left_tokens)
    )
    exact = bool(left_norm and left_norm == right_norm)
    equivalent = bool(exact or containment or jaccard >= 0.72)
    return {
        "equivalent": equivalent,
        "verdict": "REDUNDANT_CAUSAL_EDGE" if equivalent else "DISTINCT_OR_UNRESOLVED",
        "token_jaccard": round(jaccard, 3),
        "containment": containment,
        "left_tokens": sorted(left_tokens),
        "right_tokens": sorted(right_tokens),
        "reason": (
            "The two causal roles are lexical equivalents or one merely nests the other."
            if equivalent else "No deterministic lexical equivalence was established; semantic identity remains subject to LLM audit."
        ),
    }


def causal_edge_temporal_order_audit(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_context = left.get("context") if isinstance(left.get("context"), dict) else {}
    right_context = right.get("context") if isinstance(right.get("context"), dict) else {}
    left_unit = _clean(left.get("source_unit_id") or (left.get("source_evidence") or {}).get("source_unit_id"))
    right_unit = _clean(right.get("source_unit_id") or (right.get("source_evidence") or {}).get("source_unit_id"))
    left_hash = _clean(left.get("excerpt_hash") or (left.get("source_evidence") or {}).get("excerpt_hash"))
    right_hash = _clean(right.get("excerpt_hash") or (right.get("source_evidence") or {}).get("excerpt_hash"))
    same_minimal_source = bool((left_unit and left_unit == right_unit) or (left_hash and left_hash == right_hash))
    explicit_fields = []
    for key in ("temporal_order", "sequence_order", "time_order", "lag", "phase_order"):
        left_value = _clean(left_context.get(key))
        right_value = _clean(right_context.get(key))
        if left_value or right_value:
            explicit_fields.append({"field": key, "left": left_value, "right": right_value})
    evidence_text = " ".join(
        _clean(value)
        for value in (
            left.get("evidence_excerpt"), right.get("evidence_excerpt"),
            left_context.get("temporal_order"), right_context.get("temporal_order"),
        )
        if _clean(value)
    ).lower()
    marker_hits = [marker for marker in _TEMPORAL_FORWARD_MARKERS if marker in evidence_text]
    left_time = _clean(left_context.get("timepoint"))
    right_time = _clean(right_context.get("timepoint"))
    distinct_timepoints = bool(left_time and right_time and left_time.lower() != right_time.lower())
    affirmative = bool(explicit_fields or marker_hits or distinct_timepoints)
    passes = bool(affirmative and not same_minimal_source)
    return {
        "version": "causal_temporal_order_v1",
        "passes": passes,
        "affirmative_temporal_evidence": affirmative,
        "independent_minimal_source_units": not same_minimal_source,
        "same_minimal_source_unit": same_minimal_source,
        "temporal_marker_hits": marker_hits,
        "explicit_temporal_fields": explicit_fields,
        "left_timepoint": left_time,
        "right_timepoint": right_time,
        "reason": (
            "Positive temporal ordering and distinct minimal evidence units are present."
            if passes else
            "Both edges come from the same minimal source unit; a rewritten sentence cannot establish mediation."
            if same_minimal_source else
            "No affirmative evidence establishes that the upstream change precedes the proposed downstream effect."
        ),
    }


def causal_role_hard_gate(input_value: Any, mediator_value: Any, outcome_value: Any) -> dict[str, Any]:
    input_type = classify_scientific_entity(input_value, role="input")
    mediator_type = classify_scientific_entity(mediator_value, role="mediator")
    outcome_type = classify_scientific_entity(outcome_value, role="outcome")
    mediator_outcome = causal_entity_equivalence(mediator_value, outcome_value)
    input_mediator = causal_entity_equivalence(input_value, mediator_value)
    failures: list[str] = []
    if mediator_type["entity_type"] in {ABSTRACT_STATE, METHOD_TOOL, RELATIONAL_CLAUSE, UNKNOWN_ENTITY}:
        failures.append("MEDIATOR_ENTITY_TYPE_INVALID")
    if not mediator_type.get("allowed_as_mediator"):
        failures.append("MEDIATOR_NOT_MEASURABLE_OR_OPERATIONAL")
    if outcome_type["entity_type"] in {METHOD_TOOL, RELATIONAL_CLAUSE, UNKNOWN_ENTITY}:
        failures.append("OUTCOME_ENTITY_TYPE_INVALID")
    if mediator_outcome.get("equivalent"):
        failures.append("MEDIATOR_OUTCOME_REDUNDANT")
    if input_mediator.get("equivalent"):
        failures.append("INPUT_MEDIATOR_REDUNDANT")
    return {
        "version": "causal_role_hard_gate_v1",
        "passes": not failures,
        "failure_codes": list(dict.fromkeys(failures)),
        "entity_types": {"input": input_type, "mediator": mediator_type, "outcome": outcome_type},
        "semantic_folding": {
            "input_vs_mediator": input_mediator,
            "mediator_vs_outcome": mediator_outcome,
        },
        "reason": (
            "Input, mediator, and outcome are distinct operational scientific roles."
            if not failures else "Causal entity gate failed: " + ", ".join(dict.fromkeys(failures))
        ),
    }


def research_path_from_entity_types(input_value: Any, mediator_value: Any, outcome_value: Any) -> str:
    input_text = _clean(input_value) or "the source-bound input"
    mediator_text = _clean(mediator_value) or "the proposed mediator"
    outcome_text = _clean(outcome_value) or "the source-bound outcome"
    input_type = classify_scientific_entity(input_text, role="input")
    mediator_type = classify_scientific_entity(mediator_text, role="mediator")
    if mediator_type["entity_type"] == INTERVENTION_READY:
        mediator_test = f"apply a specific inhibition/knockout of {mediator_text} and a matched rescue"
    elif mediator_type["entity_type"] == MEASURABLE_BIOMARKER:
        mediator_test = (
            f"measure {mediator_text} longitudinally and estimate its mediated proportion with a source-appropriate "
            "causal mediation, multi-omics, or genetic-instrument analysis"
        )
    elif mediator_type["entity_type"] == PHYSICAL_STRUCTURE:
        mediator_test = f"compare structure-preserving controls with ablation, excision, or a structure-specific mutant of {mediator_text}"
    else:
        return (
            f"Resolve {mediator_text} into one measurable mechanism variable before proposing an experiment; "
            "do not describe an abstract state or measurement method as something to block or rescue."
        )
    if input_type["entity_type"] == PHYSICAL_STRUCTURE:
        input_test = f"use an intact-versus-excised or structure-specific mutant comparison for {input_text}"
    elif input_type["entity_type"] == INTERVENTION_READY:
        input_test = f"vary {input_text} with a matched control"
    else:
        input_test = f"define source-grounded levels or conditions of {input_text}"
    return f"First {input_test}; then {mediator_test}; finally measure {outcome_text} on a time-resolved, matched-control design."


def causal_mediation_preflight(
    input_value: Any,
    mediator_value: Any,
    outcome_value: Any,
    first_edge: dict[str, Any],
    second_edge: dict[str, Any],
) -> dict[str, Any]:
    roles = causal_role_hard_gate(input_value, mediator_value, outcome_value)
    temporal = causal_edge_temporal_order_audit(first_edge, second_edge)
    failures = list(roles.get("failure_codes") or [])
    if not temporal.get("passes"):
        failures.append("TEMPORAL_ORDER_UNPROVEN")
    return {
        "version": "causal_mediation_preflight_v1",
        "passes": not failures,
        "verdict": "PASS" if not failures else "REJECT",
        "failure_codes": list(dict.fromkeys(failures)),
        "causal_role_gate": roles,
        "temporal_order": temporal,
        "suggested_research_path": research_path_from_entity_types(input_value, mediator_value, outcome_value),
        "reason": (
            "The triad has distinct operational roles and affirmative temporal evidence."
            if not failures else "Causal mediation preflight failed: " + ", ".join(dict.fromkeys(failures))
        ),
    }


def _gap_causal_values(gap: dict[str, Any]) -> tuple[str, str, str]:
    mediation = gap.get("causal_mediation") if isinstance(gap.get("causal_mediation"), dict) else {}
    known = mediation.get("known") if isinstance(mediation.get("known"), dict) else {}
    first = known.get("A_to_B") if isinstance(known.get("A_to_B"), dict) else {}
    second = known.get("B_to_C") if isinstance(known.get("B_to_C"), dict) else {}
    readiness = gap.get("causal_readiness_verdict") if isinstance(gap.get("causal_readiness_verdict"), dict) else {}
    fields = readiness.get("causal_fields") if isinstance(readiness.get("causal_fields"), dict) else {}
    input_field = fields.get("input") if isinstance(fields.get("input"), dict) else {}
    mediator_field = fields.get("mediator") if isinstance(fields.get("mediator"), dict) else {}
    outcome_field = fields.get("outcome") if isinstance(fields.get("outcome"), dict) else {}
    return (
        _clean(input_field.get("value") or gap.get("intervention") or first.get("source")),
        _clean(mediator_field.get("value") or gap.get("proposed_mediator") or gap.get("mechanism_hint") or first.get("target") or second.get("source")),
        _clean(outcome_field.get("value") or gap.get("outcome") or second.get("target")),
    )


def is_causal_scientific_gap(gap: dict[str, Any]) -> bool:
    return str(gap.get("gap_type") or "") in CAUSAL_SCIENTIFIC_GAP_TYPES or isinstance(gap.get("causal_mediation"), dict)


def _normalize_llm_verdict(payload: dict[str, Any]) -> str:
    raw = _clean(payload.get("verdict") or payload.get("scientific_verdict")).upper()
    aliases = {
        "ACCEPT": "PASS", "VALID": "PASS", "SCIENTIFICALLY_VALID": "PASS",
        "NEEDS_REVIEW": "REVIEW_REQUIRED", "REVIEW": "REVIEW_REQUIRED",
        "NEEDS_ENTITY_RESOLUTION": "REVIEW_REQUIRED", "HUMAN_REVIEW": "REVIEW_REQUIRED",
        "FAIL": "REJECT", "INVALID": "REJECT",
    }
    return aliases.get(raw, raw if raw in {"PASS", "REJECT", "REVIEW_REQUIRED"} else "REVIEW_REQUIRED")


def audit_causal_gap_with_llm(
    project: dict[str, Any],
    gap: dict[str, Any],
    *,
    llm_callable: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the non-generative scientific veto for one causal gap.

    The LLM can reject or request entity resolution, but can never override a
    deterministic hard-rule failure or invent missing evidence.
    """
    input_value, mediator_value, outcome_value = _gap_causal_values(gap)
    hard_gate = causal_role_hard_gate(input_value, mediator_value, outcome_value)
    mediation = gap.get("causal_mediation") if isinstance(gap.get("causal_mediation"), dict) else {}
    context = mediation.get("context_compatibility") if isinstance(mediation.get("context_compatibility"), dict) else {}
    temporal = context.get("temporal_order") if isinstance(context.get("temporal_order"), dict) else {}
    if mediation and not temporal:
        known = mediation.get("known") if isinstance(mediation.get("known"), dict) else {}
        first = known.get("A_to_B") if isinstance(known.get("A_to_B"), dict) else {}
        second = known.get("B_to_C") if isinstance(known.get("B_to_C"), dict) else {}
        temporal = causal_edge_temporal_order_audit(first, second)
    system = (
        "You are a conservative scientific causal-gap auditor. Judge the supplied source-bound candidate, not the topic's importance. "
        "Reject textual co-occurrence, rephrased or nested mediator/outcome roles, methods used as entities, abstract states used as manipulable mediators, "
        "unproven temporal order, and experiments that cannot be operationalized. Do not invent entities, evidence, measurements, papers, or procedures. "
        "Return JSON only."
    )
    prompt_payload = {
        "project": {
            "domain": _clean(project.get("domain"))[:500],
            "objective": _clean(project.get("objective"))[:800],
        },
        "candidate": {
            "gap_id": _clean(gap.get("gap_id")),
            "gap_type": _clean(gap.get("gap_type")),
            "description": _clean(gap.get("description") or gap.get("gap_description"))[:1200],
            "input_A": input_value,
            "mediator_M": mediator_value,
            "outcome_Y": outcome_value,
            "supporting_references": list(gap.get("supporting_references") or [])[:8],
            "source_units": list(gap.get("source_evidence_units") or [])[:4],
            "temporal_audit": temporal,
            "hard_rule_audit": hard_gate,
        },
        "required_output": {
            "verdict": "PASS | REJECT | REVIEW_REQUIRED",
            "scientifically_coherent": "boolean",
            "operationally_testable": "boolean",
            "causal_roles_distinct": "boolean",
            "temporal_order_supported": "boolean",
            "reason_codes": "list of short codes",
            "reason": "brief explanation grounded only in supplied material",
        },
    }
    error = ""
    raw: dict[str, Any] = {}
    try:
        if llm_callable is None:
            try:
                from ._llm import call_llm_json
            except ImportError:
                from _llm import call_llm_json
            raw = call_llm_json(system=system, prompt=json.dumps(prompt_payload, ensure_ascii=False), max_tokens=900)
        else:
            try:
                raw = llm_callable(system=system, prompt=json.dumps(prompt_payload, ensure_ascii=False), max_tokens=900)
            except TypeError:
                raw = llm_callable(project, gap)
        if not isinstance(raw, dict):
            raise TypeError("causal-gap LLM auditor returned a non-object")
        llm_verdict = _normalize_llm_verdict(raw)
    except Exception as exc:  # Runtime configuration or parse failure is an auditable state, never silent acceptance.
        error = f"{type(exc).__name__}: {exc}"
        llm_verdict = "UNAVAILABLE"
    hard_pass = bool(hard_gate.get("passes"))
    temporal_pass = bool(not mediation or temporal.get("passes"))
    llm_pass = llm_verdict == "PASS"
    passes_for_socrates = bool(hard_pass and temporal_pass and llm_pass)
    if not hard_pass or not temporal_pass:
        final_verdict = "REJECT"
    elif llm_verdict == "REJECT":
        final_verdict = "REJECT"
    elif llm_verdict == "PASS":
        final_verdict = "PASS"
    else:
        final_verdict = "REVIEW_REQUIRED"
    audit = {
        "version": "scientific_causal_gap_audit_v1",
        "gap_id": _clean(gap.get("gap_id")),
        "attempted": True,
        "hard_rule_audit": hard_gate,
        "temporal_order": temporal,
        "llm_verdict": llm_verdict,
        "llm_payload": raw,
        "llm_error": error,
        "verdict": final_verdict,
        "passes": final_verdict == "PASS",
        "passes_for_socrates": passes_for_socrates,
        "suggested_research_path": research_path_from_entity_types(input_value, mediator_value, outcome_value),
        "reason": (
            hard_gate.get("reason") if not hard_pass else
            temporal.get("reason") if mediation and not temporal_pass else
            _clean(raw.get("reason")) if raw else
            "The LLM scientific audit was unavailable; the candidate requires review and cannot enter Socrates."
        ),
    }
    audit["audit_hash"] = sha256(
        json.dumps({key: value for key, value in audit.items() if key != "audit_hash"}, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return audit


def scientific_causal_gap_audit_is_intact(audit: dict[str, Any]) -> bool:
    if not isinstance(audit, dict) or audit.get("version") != "scientific_causal_gap_audit_v1":
        return False
    expected = _clean(audit.get("audit_hash"))
    if not expected:
        return False
    actual = sha256(
        json.dumps(
            {key: value for key, value in audit.items() if key != "audit_hash"},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return expected == actual
