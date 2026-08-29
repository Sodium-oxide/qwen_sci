"""Shared ontology guardrails for scientific interventions and mechanism roles.

The research pipeline handles two different worlds:

* epistemic operations describe how knowledge is collected or summarized;
* operational interventions change a physical, biological, chemical,
  environmental, engineering, or explicitly simulated system.

Treating the first class as the second creates grammatically complete but
scientifically meaningless causal chains (for example, ``literature review ->
cell proliferation``).  This module provides a small, deterministic gate used
by TanXi, Socrates, MingLi, and YanZhen so all stages enforce the same boundary.
"""
from __future__ import annotations

import re
from typing import Any


EPISTEMIC_METHOD_MARKERS = (
    "literature review", "systematic review", "scoping review", "narrative review",
    "meta-analysis", "evidence synthesis", "bibliometric", "survey of the literature",
    "review article", "perspective article", "consensus statement", "expert opinion",
    "knowledge synthesis", "paper review", "database search", "literature search",
)

DESCRIPTIVE_EVIDENCE_MARKERS = (
    "accumulating evidence", "evidence suggests", "evidence indicates", "has been reported",
    "review highlights", "review summarizes", "is associated with", "correlates with",
    "observational association", "descriptive analysis", "retrospective observation",
)

MEASUREMENT_RESOURCE_MARKERS = (
    "benchmark dataset", "validation dataset", "reference dataset", "literature corpus",
    "evidence base", "knowledge base", "review evidence", "publication count",
)

GENERIC_PLACEHOLDER_MARKERS = (
    "key controllable variable", "controllable variable named by", "targeted intervention",
    "proposed intervention", "appropriate intervention", "domain-appropriate intervention",
    "relevant parameter", "selected modality", "the intervention", "the input variable",
    "unresolved", "unspecified", "unknown intervention", "requires_direct_intervention_evidence",
)

DIRECT_EXPERIMENTAL_ACTION_MARKERS = (
    "knockout", "knock out", "knockdown", "knock down", "overexpress", "over-expression",
    "silence", "silencing", "crispr", "inhibit", "inhibition", "activate", "activation",
    "manipulated", "controlled", "block", "blocking",
    "agonist", "antagonist", "administer", "administration", "treat with", "treatment with",
    "treated with", "add ", "added ", "remove ", "deplete", "depletion", "neutralize",
    "transfect", "transduction", "mutate", "mutation", "delete", "deletion", "ablate",
    "ablation", "expose", "exposure", "irradiate", "stimulation", "stimulate", "perturb",
    "vary ", "varied ", "titrate", "clamp", "apply ",
)

DIRECT_COMPUTATIONAL_ACTION_MARKERS = (
    "parameter sweep", "set the parameter", "vary the parameter", "simulation intervention",
    "in silico perturb", "feature ablation", "component ablation", "remove the module",
    "disable the module", "replace the module", "modify the algorithm", "inject noise",
    "counterfactual simulation", "boundary-condition sweep",
)

MANIPULABLE_QUANTITY_MARKERS = (
    "concentration", "dose", "temperature", "pressure", "voltage", "current density", "ph",
    "frequency", "light intensity", "electric field", "magnetic field", "mechanical stress",
    "strain", "flow rate", "oxygen level", "glucose level", "cytokine level", "expression level",
    "gene dosage", "drug level", "incubation time", "exposure time", "humidity", "loading",
)

OBSERVATIONAL_DESIGN_MARKERS = (
    "observational study", "cohort study", "cross-sectional", "case-control", "retrospective",
    "prospective cohort", "association analysis", "correlation analysis", "stratify by",
)

# These terms describe what was seen, measured, classified, or inferred.  A
# result sentence may contain a verb such as ``suppressed`` while still being
# an observation ("alpha activity was suppressed"), rather than an operation
# a future experiment can apply.  This distinction is deliberately
# domain-neutral: it protects neuroscience, chemistry, materials, climate,
# and computational work from treating a readout as its own cause.
OBSERVATION_OR_READOUT_MARKERS = (
    "observed", "measured", "measurement", "increased", "decreased", "elevated", "suppressed",
    "reduced", "enhanced", "correlation", "correlated", "associated", "association", "signature",
    "feature", "classifier", "biomarker", "expression", "activity", "readout", "prediction",
    "predicted", "identified", "detected",
)

OBSERVATION_SUBJECT_MARKERS = (
    "activity", "expression", "biomarker", "signature", "feature", "classifier", "correlation",
    "association", "readout", "signal", "pattern", "state", "outcome", "response",
)

GENERIC_COMPUTATIONAL_ENTITY_MARKERS = (
    "computational model", "statistical model", "machine learning model", "ai model", "algorithm",
    "classifier", "predictive model", "representation model", "analysis pipeline",
)

# These are ontology heads, not forbidden domain words.  Whether a candidate
# is too generic is decided from its *structure* below: a bare "state" or
# "representation" is not a mechanism, while a project-bound phrase such as
# "vortex-pinning energy landscape" or "hippocampal theta--gamma coupling"
# may be.  Do not add field vocabularies here: water, signal, neural, digital,
# algorithm, solvent, and so on can all be the central scientific object of a
# legitimate project.
GENERIC_MEDIATOR_HEADS = {
    "activity", "biology", "effect", "information", "mechanism", "outcome",
    "pathway", "performance", "process", "representation", "result", "state",
    "system", "variable",
}

MECHANISM_RELATION_MARKERS = (
    "absorption", "adsorption", "aggregation", "binding", "coupling", "decay",
    "degradation", "diffusion", "disorder", "dissociation", "distribution", "energy",
    "exchange", "fidelity", "flow", "folding", "formation", "kinetic", "kinetics",
    "landscape", "migration", "nucleation", "oxidation", "pairing", "partition",
    "phase", "pinning", "reaction", "recombination", "relaxation", "resonance",
    "solvation", "stability", "transfer", "transport", "topology", "transition",
)

_ACTION_INTENT_RE = re.compile(
    r"\b(?:ablat(?:e|ion)|activat(?:e|ion)|administer(?:ed|ing)?|anneal(?:ed|ing)?|"
    r"apply|applied|bias(?:ed|ing)?|block(?:ed|ing)?|clamp(?:ed|ing)?|control(?:led|ling)?|"
    r"deplet(?:e|ed|ion)|disable(?:d|ing)?|expos(?:e|ed|ure)|heat(?:ed|ing)?|inhibit(?:ed|ion|ing)?|"
    r"inject(?:ed|ing)?|irradiat(?:e|ed|ion|ing)|knock(?:ed)?\s*(?:down|out)|load(?:ed|ing)?|"
    r"modif(?:y|ied|ication)|mutat(?:e|ed|ion)|perturb(?:ed|ation|ing)?|remove(?:d|ing)?|"
    r"replace(?:d|ment|ing)?|scan(?:ned|ning)?|set(?:ting)?|silenc(?:e|ed|ing)|stimulat(?:e|ed|ion|ing)|"
    r"strain(?:ed|ing)?|sweep(?:ing)?|titrate(?:d|ing)?|tune(?:d|ing)?|vary|varied|varying)\b",
    re.IGNORECASE,
)

_RESULT_CLAUSE_RE = re.compile(
    r"\b(?:was|were|is|are|become|became|remain(?:ed|s)?)\s+"
    r"(?:observed|measured|increased|decreased|elevated|suppressed|reduced|enhanced|detected|identified)\b",
    re.IGNORECASE,
)


def normalize_scientific_role_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _marker_hits(text: str, markers: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [marker for marker in markers if marker in lowered]


def _has_concrete_object(text: str) -> bool:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9+\-]{1,}|[\u4e00-\u9fff]{2,}", text)
    generic = {
        "the", "a", "an", "and", "or", "of", "in", "to", "for", "with", "using",
        "variable", "parameter", "intervention", "method", "modality", "condition", "system",
        "appropriate", "relevant", "selected", "proposed", "named", "source", "evidence",
    }
    return any(token.lower() not in generic for token in tokens)


def _scientific_tokens(text: str) -> list[str]:
    """Extract field-neutral identifiers, including formulas and CJK terms."""
    return re.findall(r"[A-Za-z\u0370-\u03ff][A-Za-z0-9_+\-./]*|[\u4e00-\u9fff]{2,}", text)


def _has_parameterized_computational_transformation(text: str) -> bool:
    """Distinguish an algorithm name from an actual in-silico intervention."""
    lowered = text.lower()
    if _marker_hits(lowered, DIRECT_COMPUTATIONAL_ACTION_MARKERS):
        return True
    return bool(re.search(
        r"\b(?:set|vary|sweep|tune|ablat(?:e|ion)|remove|replace|disable|inject)\b.*\b"
        r"(?:parameter|feature|component|module|weight|threshold|prior|algorithm|architecture|boundary)\b",
        lowered,
    ))


def _mediator_structure(text: str) -> dict[str, Any]:
    """Assess mediator specificity without prescribing a scientific field.

    A mediator needs either an explicit mechanism-bearing relation (binding,
    coupling, transport, proof-relevant energy landscape, ...) or at least two
    project-capable descriptors attached to a generic state/entity head.  The
    caller is still responsible for source traceability and project alignment.
    """
    tokens = _scientific_tokens(text)
    normalized = [token.lower() for token in tokens]
    content = [token for token in normalized if token not in {
        "a", "an", "and", "at", "by", "for", "from", "in", "of", "or", "the", "to", "with",
        "during", "under", "between", "via", "within",
    }]
    def generic_head(token: str) -> str:
        if token in GENERIC_MEDIATOR_HEADS:
            return token
        singular = token[:-1] if token.endswith("s") and len(token) > 3 else token
        return singular if singular in GENERIC_MEDIATOR_HEADS else ""

    head_hits = [head for token in content if (head := generic_head(token))]
    relation_hits = _marker_hits(text.lower(), MECHANISM_RELATION_MARKERS)
    # Capitalized identifiers, formula-like labels, and CJK object phrases are
    # strong entity signals without requiring a domain-specific dictionary.
    identifier_hits = [
        token for token in tokens
        if any(char.isupper() for char in token[1:]) or any(char.isdigit() for char in token)
        or "+" in token or "-" in token or "/" in token or re.search(r"[\u4e00-\u9fff]", token)
    ]
    descriptors = [token for token in content if not generic_head(token)]
    compact = len(content) <= 18
    # A relation can be sufficient with one named entity (e.g. ``CO2
    # adsorption``); otherwise require two descriptors so ``memory
    # representation`` and ``neural activity`` remain non-mechanistic.
    structurally_specific = compact and bool(
        relation_hits and (descriptors or identifier_hits)
        or len(descriptors) >= 2
        or identifier_hits and bool(head_hits)
    )
    generic_only = bool(head_hits) and not relation_hits and len(descriptors) < 2 and not identifier_hits
    return {
        "tokens": tokens,
        "generic_heads": head_hits,
        "mechanism_relation_hits": relation_hits,
        "project_capable_descriptors": descriptors,
        "identifier_hits": identifier_hits,
        "compact": compact,
        "structurally_specific": structurally_specific,
        "generic_only": generic_only,
    }


def classify_intervention_candidate(
    value: Any,
    *,
    evidence_grade: str = "",
    evidence_type: str = "",
) -> dict[str, Any]:
    """Classify whether ``value`` may occupy an intervention slot.

    Grades C/D may remain rationale, but never authorize a core intervention.
    This intentionally makes the intervention field stricter than ordinary
    mechanism evidence because a wrong category here invalidates the whole
    causal experiment.
    """
    text = normalize_scientific_role_text(value)
    lowered = text.lower()
    grade = str(evidence_grade or "").strip().upper()
    evidence_kind = str(evidence_type or "").strip().lower()
    result: dict[str, Any] = {
        "candidate": text,
        "category": "unresolved",
        "ontology_level": "unresolved",
        "admissible_as_intervention": False,
        "allowed_roles": ["unresolved"],
        "evidence_grade": grade,
        "evidence_type": evidence_kind,
        "matched_markers": [],
        "reason": "No intervention candidate was supplied.",
    }
    if not text:
        return result

    placeholder_hits = _marker_hits(lowered, GENERIC_PLACEHOLDER_MARKERS)
    epistemic_hits = _marker_hits(lowered, EPISTEMIC_METHOD_MARKERS)
    resource_hits = _marker_hits(lowered, MEASUREMENT_RESOURCE_MARKERS)
    descriptive_hits = _marker_hits(lowered, DESCRIPTIVE_EVIDENCE_MARKERS)
    observational_hits = _marker_hits(lowered, OBSERVATIONAL_DESIGN_MARKERS)
    observation_hits = _marker_hits(lowered, OBSERVATION_OR_READOUT_MARKERS)
    observation_subject_hits = _marker_hits(lowered, OBSERVATION_SUBJECT_MARKERS)
    computational_hits = _marker_hits(lowered, DIRECT_COMPUTATIONAL_ACTION_MARKERS)
    experimental_hits = _marker_hits(lowered, DIRECT_EXPERIMENTAL_ACTION_MARKERS)
    quantity_hits = _marker_hits(lowered, MANIPULABLE_QUANTITY_MARKERS)

    if placeholder_hits:
        result.update(
            category="generic_placeholder",
            ontology_level="linguistic_placeholder",
            allowed_roles=["retrieval_requirement"],
            matched_markers=placeholder_hits,
            reason="A placeholder names no concrete manipulable object or operation.",
        )
        return result
    if epistemic_hits or evidence_kind in {"review", "systematic_review", "meta_analysis", "perspective"}:
        result.update(
            category="epistemic_method",
            ontology_level="information",
            allowed_roles=["rationale", "related_work", "evidence_source"],
            matched_markers=epistemic_hits or [evidence_kind],
            reason="A knowledge-synthesis operation can support rationale but cannot change the studied system.",
        )
        return result
    if resource_hits:
        result.update(
            category="measurement_or_evidence_resource",
            ontology_level="information",
            allowed_roles=["measurement_resource", "benchmark", "rationale"],
            matched_markers=resource_hits,
            reason="A dataset or evidence resource may support measurement, but it is not an intervention.",
        )
        return result
    if descriptive_hits or observational_hits:
        result.update(
            category="observational_or_descriptive",
            ontology_level="observation",
            allowed_roles=["rationale", "alternative_explanation", "study_design"],
            matched_markers=descriptive_hits + observational_hits,
            reason="Descriptive or observational evidence does not itself manipulate the causal system.",
        )
        return result
    generic_computational_hits = _marker_hits(lowered, GENERIC_COMPUTATIONAL_ENTITY_MARKERS)
    computational_transformation = _has_parameterized_computational_transformation(text)
    if generic_computational_hits and not computational_transformation:
        result.update(
            category="model_or_analysis_without_parameterized_transformation",
            ontology_level="information",
            allowed_roles=["rationale", "measurement_method", "mediator_candidate"],
            matched_markers=generic_computational_hits,
            reason="A model, classifier, or analysis name is not an intervention without a parameterized transformation and controlled comparison.",
        )
        return result

    # An explicit, parameterized operation wins over a word that also names a
    # possible readout.  Thus ``feature ablation`` and ``stimulation of neural
    # activity`` are operations, while ``activity was elevated`` remains a
    # readout.  This priority is based on grammatical role, not topic words.
    action_intent = bool(_ACTION_INTENT_RE.search(text))
    direct_category = ""
    direct_markers: list[str] = []
    if computational_transformation:
        direct_category = "direct_computational_intervention"
        direct_markers = computational_hits or ["parameterized_computational_transformation"]
    elif action_intent and (experimental_hits or quantity_hits or "controlled variation" in lowered):
        direct_category = "direct_experimental_intervention"
        direct_markers = experimental_hits + quantity_hits

    if direct_category and _has_concrete_object(text):
        result.update(
            category=direct_category,
            ontology_level="computational_system" if computational_hits else "physical_system",
            matched_markers=direct_markers,
            allowed_roles=["intervention", "experimental_condition"],
        )
        if grade in {"C", "D"}:
            result["reason"] = (
                f"The operation is potentially manipulable, but evidence grade {grade} is too weak "
                "to authorize it as the core intervention."
            )
            result["allowed_roles"] = ["rationale", "candidate_intervention"]
            return result
        result["admissible_as_intervention"] = True
        result["reason"] = "The candidate names a concrete operation or manipulable quantity."
        return result

    result_clause = bool(_RESULT_CLAUSE_RE.search(text))
    if observation_hits and (observation_subject_hits or result_clause or not action_intent):
        result.update(
            category="OBSERVATION_OR_READOUT",
            ontology_level="observation",
            allowed_roles=["measurement_target", "outcome", "rationale", "evidence_source"],
            matched_markers=observation_hits + observation_subject_hits,
            reason="The candidate reports an observed, measured, classified, or correlated result rather than an operation that can be applied.",
        )
        return result

    result.update(
        category="entity_or_method_without_operation",
        ontology_level="physical_or_conceptual_entity",
        allowed_roles=["mediator_candidate", "rationale", "measurement_target"],
        matched_markers=direct_markers,
        reason="The text may name an entity or method, but it does not specify how that object is manipulated.",
    )
    return result


def classify_mediator_candidate(value: Any) -> dict[str, Any]:
    """Reject narrative claims and epistemic artifacts from mediator slots."""
    text = normalize_scientific_role_text(value)
    intervention = classify_intervention_candidate(text)
    lowered = text.lower()
    narrative = bool(_marker_hits(lowered, DESCRIPTIVE_EVIDENCE_MARKERS)) or len(text.split()) > 24
    structure = _mediator_structure(text)
    operational_action = bool(
        _marker_hits(lowered, DIRECT_EXPERIMENTAL_ACTION_MARKERS)
        or _marker_hits(lowered, DIRECT_COMPUTATIONAL_ACTION_MARKERS)
    )
    invalid_categories = {
        "unresolved", "generic_placeholder", "epistemic_method",
        "measurement_or_evidence_resource", "observational_or_descriptive",
    }
    # An observed/readout phrase is not promoted to a mechanism merely
    # because it is compact and has two scientific-looking descriptors.
    # Permit an exception only when the same phrase also names an explicit
    # mechanism-bearing relation (binding, coupling, diffusion, transport,
    # transition, feedback-like transfer, etc.).  Those relation families are
    # field-neutral and therefore apply to physics, chemistry, life science,
    # Earth science, engineering, mathematics, and computational research.
    observation_verdict = intervention.get("category") == "OBSERVATION_OR_READOUT"
    explicit_mechanism_evidence = bool(structure.get("mechanism_relation_hits"))
    observation_veto = bool(observation_verdict and not explicit_mechanism_evidence)
    admissible = (
        bool(text)
        and not narrative
        and not operational_action
        and not observation_veto
        and bool(structure.get("structurally_specific"))
        and intervention["category"] not in invalid_categories
    )
    return {
        "candidate": text,
        "category": "mechanistic_entity_or_state" if admissible else "non_mechanistic_narrative_or_artifact",
        "admissible_as_mediator": admissible,
        "reason": (
            "The candidate is a compact entity/state label that may be tested as a mediator."
            if admissible
            else (
                "An observation/readout cannot also serve as a mediator without additional explicit mechanism evidence."
                if observation_veto
                else "Mediator slots require a compact, structurally specific mechanism-bearing entity or state, not a generic scientific concept, review method, evidence narrative, resource, or full sentence."
            )
        ),
        "generic_mediator_hits": structure.get("generic_heads", []),
        "structural_specificity": structure,
        "source_role_assessment": intervention,
        "observation_verdict_veto": observation_veto,
        "explicit_mechanism_evidence": explicit_mechanism_evidence,
    }


def intervention_gate_from_values(values: list[dict[str, Any] | str]) -> dict[str, Any]:
    """Return the first admissible candidate and retain a full audit trail."""
    assessments: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, dict):
            candidate = value.get("candidate") or value.get("claim") or value.get("excerpt") or value.get("value")
            assessment = classify_intervention_candidate(
                candidate,
                evidence_grade=str(value.get("evidence_grade") or ""),
                evidence_type=str(value.get("evidence_type") or value.get("source_design") or ""),
            )
            assessment["candidate_source"] = str(value.get("candidate_source") or value.get("source") or "")
        else:
            assessment = classify_intervention_candidate(value)
        assessments.append(assessment)
        if assessment.get("admissible_as_intervention"):
            return {
                "verdict": "PASS",
                "admissible": True,
                "selected_intervention": assessment["candidate"],
                "selected_assessment": assessment,
                "assessments": assessments,
                "reason": assessment["reason"],
            }
    return {
        "verdict": "FAIL",
        "admissible": False,
        "selected_intervention": "",
        "selected_assessment": {},
        "assessments": assessments,
        "reason": (
            "No evidence-backed direct physical, chemical, biological, engineering, environmental, "
            "or explicit computational intervention was found."
        ),
    }
