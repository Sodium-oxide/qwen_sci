"""Research-mode-aware ontology for a hypothesis input.

An input is the condition whose alternatives define a scientific comparison.
It is not always a laboratory intervention: it may be a natural regime, a
model family, a formal premise, or an instrument configuration.  The rules in
this module describe epistemic roles rather than scientific disciplines.
"""
from __future__ import annotations

import re
from typing import Any

try:
    from ._intervention_ontology import classify_intervention_candidate
except ImportError:
    from _intervention_ontology import classify_intervention_candidate


_GENERIC_EXACT = {
    "", "analysis", "experiment", "input", "intervention", "method", "model",
    "observation", "parameter", "research", "study", "system", "variable",
    "condition", "simulation", "measurement", "data",
}
_GENERIC_TOKENS = {
    "a", "an", "and", "analysis", "by", "condition", "data", "experiment",
    "for", "from", "in", "input", "intervention", "measurement", "method",
    "model", "observation", "of", "on", "or", "parameter", "research",
    "simulation", "study", "system", "the", "to", "under", "using", "variable",
    "with",
}
_RESULT_CLAUSE = re.compile(
    r"\b(?:was|were|is|are|became|remained)\s+"
    r"(?:observed|measured|increased|decreased|elevated|suppressed|predicted|detected)\b",
    re.IGNORECASE,
)
_CONTROLLED_HEADS = (
    "concentration", "composition", "dose", "electric field", "exposure", "field",
    "frequency", "geometry", "humidity", "material treatment", "ph", "pressure",
    "processing", "stimulus", "strain", "stress", "temperature", "time", "voltage",
)
_COMPUTATIONAL_HEADS = (
    "ablation", "algorithm", "assumption switch", "boundary condition", "initial condition",
    "mass model", "model family", "module replacement", "parameter", "parameter set",
    "parameter sweep", "prior", "rate set", "resolution", "solver", "threshold",
)
_OBSERVATIONAL_HEADS = (
    "event", "exposure", "gradient", "mass ratio", "model family", "natural condition",
    "population stratum", "regime", "sampling stratum", "source class", "time window",
    "trajectory", "environmental", "observational",
)
_THEORETICAL_HEADS = (
    "assumption", "axiom", "boundary", "constraint", "initial condition", "limit",
    "premise", "regularity", "symmetry", "topology", "conservation", "domain",
)
_INSTRUMENT_HEADS = (
    "calibration", "detector geometry", "gain", "measurement protocol", "noise floor",
    "reference", "resolution", "sampling rate", "sampling window", "sensor geometry",
    "wavelength window", "configuration",
)
_LAB_HEADS = (
    "composition", "concentration", "field", "flow", "geometry", "material", "pressure",
    "reactant", "sample", "strain", "stress", "temperature", "time", "voltage",
)


def _compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokens(value: Any) -> list[str]:
    return [
        token.lower() for token in re.findall(
            r"[A-Za-z\u0370-\u03ff][A-Za-z0-9_+./-]*|[\u4e00-\u9fff]{2,}",
            _compact(value),
        )
    ]


def _content_tokens(value: Any) -> list[str]:
    expanded: list[str] = []
    for token in _tokens(value):
        expanded.append(token)
        expanded.extend(part for part in re.split(r"[+./_-]+", token) if len(part) >= 3)
    return list(dict.fromkeys(token for token in expanded if token not in _GENERIC_TOKENS))


def _has_marker(text: str, markers: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [marker for marker in markers if marker in lowered]


def _specific(text: str, markers: list[str]) -> bool:
    content = _content_tokens(text)
    return bool(len(content) >= 2 or markers and content)


def classify_input_candidate(
    value: Any,
    *,
    research_mode: str,
    source_unit_ids: list[str] | None = None,
    require_source_bound: bool = True,
) -> dict[str, Any]:
    """Classify a causal input under the declared epistemic design.

    ``ontology_valid`` answers whether the phrase has the right scientific
    role. ``admissible_as_input`` additionally requires source provenance when
    requested.  This prevents a model from inventing a plausible condition.
    """
    text = _compact(value)
    lowered = text.lower()
    mode = str(research_mode or "UNRESOLVED_RESEARCH_DESIGN").strip().upper()
    ids = list(dict.fromkeys(str(item) for item in (source_unit_ids or []) if str(item)))
    base = {
        "version": "input_ontology_v1",
        "candidate": text,
        "normalized_value": text,
        "research_mode": mode,
        "category": "unresolved",
        "ontology_valid": False,
        "admissible_as_input": False,
        "admissible_as_intervention": False,
        "source_bound": bool(ids),
        "source_unit_ids": ids,
        "matched_markers": [],
        "reason": "No input candidate was supplied.",
    }
    if not text:
        return base
    if lowered in _GENERIC_EXACT or _RESULT_CLAUSE.search(text):
        return {
            **base,
            "category": "generic_or_observed_result",
            "reason": "A generic research word or observed result cannot define the comparison input.",
        }

    intervention = classify_intervention_candidate(text)
    markers: list[str] = []
    category = ""
    normalized = text
    ontology_valid = False

    if mode == "CONTROLLED_INTERVENTION":
        markers = _has_marker(text, _CONTROLLED_HEADS)
        ontology_valid = bool(intervention.get("admissible_as_intervention") or _specific(text, markers))
        category = "controlled_operation_or_condition"
        if ontology_valid and not intervention.get("admissible_as_intervention"):
            normalized = f"controlled variation of {text}"
    elif mode == "COMPUTATIONAL_INTERVENTION":
        markers = _has_marker(text, _COMPUTATIONAL_HEADS)
        ontology_valid = bool(
            intervention.get("category") == "direct_computational_intervention"
            or _specific(text, markers)
        )
        category = "parameterized_computational_condition"
        if ontology_valid and intervention.get("category") != "direct_computational_intervention":
            normalized = f"controlled computational variation of {text}"
    elif mode in {"OBSERVATIONAL_MODEL_DISCRIMINATION", "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT"}:
        markers = _has_marker(text, _OBSERVATIONAL_HEADS)
        ontology_valid = _specific(text, markers)
        category = "natural_or_observational_condition"
    elif mode == "THEORETICAL_OR_FORMAL":
        markers = _has_marker(text, _THEORETICAL_HEADS)
        ontology_valid = _specific(text, markers)
        category = "formal_premise_or_boundary_condition"
    elif mode == "INSTRUMENTATION_OR_MEASUREMENT":
        markers = _has_marker(text, _INSTRUMENT_HEADS)
        ontology_valid = _specific(text, markers)
        category = "measurement_configuration"
    elif mode == "LABORATORY_CONSTRAINT":
        markers = _has_marker(text, _LAB_HEADS)
        ontology_valid = bool(intervention.get("admissible_as_intervention") or _specific(text, markers))
        category = "controlled_laboratory_condition"
        if ontology_valid and not intervention.get("admissible_as_intervention"):
            normalized = f"controlled laboratory variation of {text}"
    else:
        category = "mode_unresolved"

    provenance_valid = bool(ids) or not require_source_bound
    admissible = bool(ontology_valid and provenance_valid)
    return {
        **base,
        "normalized_value": normalized,
        "category": category,
        "ontology_valid": ontology_valid,
        "admissible_as_input": admissible,
        "admissible_as_intervention": bool(
            admissible and mode in {"CONTROLLED_INTERVENTION", "COMPUTATIONAL_INTERVENTION"}
        ),
        "matched_markers": markers,
        "reason": (
            f"The source-bound phrase is a valid {mode} input."
            if admissible
            else "The candidate is not specific for the research mode."
            if not ontology_valid
            else "The input role is plausible but lacks a paper-qualified source unit."
        ),
    }
