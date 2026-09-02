from __future__ import annotations

from collections import Counter
from typing import Any
import re

try:
    from ._evidence_standards import (
        evidence_standard_retrieval_policy,
        get_evidence_standard,
        normalize_evidence_standard_id,
    )
    from ._epistemic_profile import infer_epistemic_profile, normalize_epistemic_profile
    from ._evidence_roles import summarize_project_evidence_role_coverage
    from ._research_question_contract import (
        RESEARCH_QUESTION_CONTRACT_VERSION,
        build_research_question_contract,
        build_question_retrieval_plan,
        validate_research_question_contract,
    )
except ImportError:
    from _evidence_standards import (
        evidence_standard_retrieval_policy,
        get_evidence_standard,
        normalize_evidence_standard_id,
    )
    from _epistemic_profile import infer_epistemic_profile, normalize_epistemic_profile
    from _evidence_roles import summarize_project_evidence_role_coverage
    from _research_question_contract import (
        RESEARCH_QUESTION_CONTRACT_VERSION,
        build_research_question_contract,
        build_question_retrieval_plan,
        validate_research_question_contract,
    )


ANNOTATION_SCHEMA_VERSION = "subhypothesis_annotation_v3"
ANNOTATION_SUMMARY_SCHEMA_VERSION = "subhypothesis_annotation_summary_v3"

HYPOTHESIS_TYPES = frozenset({
    "clinical_intervention",
    "policy_population",
    "environmental_ecological",
    "basic_mechanism",
    "surveillance_monitoring",
    "combined_strategy",
    "unresolved",
})
SCALES = frozenset({"micro", "meso", "macro", "cross_scale"})
RESEARCH_MODE_PRIORS = frozenset({
    "CONTROLLED_INTERVENTION",
    "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT",
    "OBSERVATIONAL_MODEL_DISCRIMINATION",
    "COMPUTATIONAL_INTERVENTION",
    "INSTRUMENTATION_OR_MEASUREMENT",
    "LABORATORY_CONSTRAINT",
    "THEORETICAL_OR_FORMAL",
    "UNRESOLVED_RESEARCH_DESIGN",
})
PRIORITY_TIERS = frozenset({"QUICK_WIN", "MOONSHOT", "FILL_IN", "DROP_OR_DEFER"})
PRIORITY_TIER_RETRIEVAL_ORDER = {
    "QUICK_WIN": 0,
    "MOONSHOT": 1,
    "FILL_IN": 2,
    "DROP_OR_DEFER": 3,
}
RETRIEVAL_ORDERS = frozenset({"tier_then_decomposition", "priority", "decomposition"})

TYPE_ALIASES = {
    "healthcare_practice": "clinical_intervention",
    "clinical": "clinical_intervention",
    "medical": "clinical_intervention",
    "policy": "policy_population",
    "population": "policy_population",
    "public_health": "policy_population",
    "environmental": "environmental_ecological",
    "ecological": "environmental_ecological",
    "ecology": "environmental_ecological",
    "mechanism": "basic_mechanism",
    "basic": "basic_mechanism",
    "fundamental": "basic_mechanism",
    "surveillance": "surveillance_monitoring",
    "monitoring": "surveillance_monitoring",
    "measurement": "surveillance_monitoring",
    "combined": "combined_strategy",
    "combination": "combined_strategy",
    "integrated": "combined_strategy",
}

MODE_ALIASES = {
    "controlled": "CONTROLLED_INTERVENTION",
    "controlled_intervention": "CONTROLLED_INTERVENTION",
    "intervention": "CONTROLLED_INTERVENTION",
    "experiment": "CONTROLLED_INTERVENTION",
    "experimental": "CONTROLLED_INTERVENTION",
    "natural_experiment": "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT",
    "natural_experiment_or_quasi_experiment": "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT",
    "quasi_experiment": "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT",
    "quasi_experimental": "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT",
    "observational": "OBSERVATIONAL_MODEL_DISCRIMINATION",
    "observational_model_discrimination": "OBSERVATIONAL_MODEL_DISCRIMINATION",
    "computational": "COMPUTATIONAL_INTERVENTION",
    "computational_intervention": "COMPUTATIONAL_INTERVENTION",
    "simulation": "COMPUTATIONAL_INTERVENTION",
    "instrumentation": "INSTRUMENTATION_OR_MEASUREMENT",
    "instrumentation_or_measurement": "INSTRUMENTATION_OR_MEASUREMENT",
    "measurement": "INSTRUMENTATION_OR_MEASUREMENT",
    "laboratory_constraint": "LABORATORY_CONSTRAINT",
    "lab_constraint": "LABORATORY_CONSTRAINT",
    "theoretical": "THEORETICAL_OR_FORMAL",
    "formal": "THEORETICAL_OR_FORMAL",
    "theoretical_or_formal": "THEORETICAL_OR_FORMAL",
}

_EPISTEMIC_TO_LEGACY_RESEARCH_MODE = {
    "experimental_intervention": "CONTROLLED_INTERVENTION",
    "observational_inference": "OBSERVATIONAL_MODEL_DISCRIMINATION",
    "theoretical_derivation": "THEORETICAL_OR_FORMAL",
    "mathematical_proof": "THEORETICAL_OR_FORMAL",
    "computational_simulation": "COMPUTATIONAL_INTERVENTION",
    "engineering_validation": "INSTRUMENTATION_OR_MEASUREMENT",
    "classification_description": "OBSERVATIONAL_MODEL_DISCRIMINATION",
    "synthesis_evaluation": "OBSERVATIONAL_MODEL_DISCRIMINATION",
}

TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "clinical_intervention": (
        "clinical", "patient", "therapy", "treatment", "healthcare", "hospital",
        "prescribing", "stewardship", "trial", "randomized", "controlled trial",
        "diagnostic-guided", "care pathway", "dose regimen",
    ),
    "policy_population": (
        "policy", "regulation", "ban", "mandate", "national action plan",
        "governance", "population-level", "public health", "jurisdiction",
        "incentive", "adoption", "implementation", "market", "standard",
        "difference-in-differences", "interrupted time series",
    ),
    "environmental_ecological": (
        "environment", "ecological", "ecology", "ecosystem", "agriculture",
        "livestock", "soil", "water", "wastewater", "field site", "field study",
        "climate", "atmospheric", "ocean", "hydrology", "geology", "biodiversity",
        "resistome", "land use", "biogeochemical",
    ),
    "basic_mechanism": (
        "mechanism", "pathway", "compound", "molecule", "protein", "gene", "cell",
        "material", "catalyst", "reaction", "phase", "surface", "interface",
        "crystal", "polymer", "semiconductor", "mic", "phage", "antimicrobial peptide",
        "in vitro", "animal model", "ablation", "perturbation", "simulation",
        "model", "theorem", "proof", "derivation", "equation", "parameter",
    ),
    "surveillance_monitoring": (
        "surveillance", "monitoring", "genomic tracking", "sensor", "detector",
        "remote sensing", "early warning", "sampling network", "assay platform",
        "observatory", "instrument", "calibration", "measurement system",
        "benchmark", "screening", "metrology", "detection limit",
    ),
    "combined_strategy": (
        "combined", "combination", "synergy", "synergistic", "integrated",
        "multi-component", "multicomponent", "additive", "joint", "portfolio",
        "bundle", "coordinated", "cross-scale", "multi-scale", "one health",
    ),
}

SCALE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "micro": (
        "molecule", "molecular", "atom", "atomic", "protein", "gene", "cell",
        "crystal", "surface", "interface", "phase", "reaction", "compound",
        "catalyst", "particle", "mic", "in vitro",
    ),
    "meso": (
        "device", "reactor", "module", "organism", "sample", "plot", "field site",
        "laboratory system", "pilot", "hospital", "clinic", "facility", "farm",
        "sensor network", "cohort",
    ),
    "macro": (
        "population", "national", "regional", "jurisdiction", "policy", "ecosystem",
        "climate", "global", "market", "supply chain", "watershed", "landscape",
        "planetary", "public health",
    ),
    "cross_scale": (
        "cross-scale", "multi-scale", "multiscale", "one health", "integrated",
        "combined", "system-level", "human-animal-environment", "micro to macro",
    ),
}

MODE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "CONTROLLED_INTERVENTION": (
        "controlled experiment", "controlled trial", "randomized", "randomised",
        "intervention", "perturbation", "ablation", "knockout", "dose-response",
        "treated with", "exposed to", "control group", "baseline",
    ),
    "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT": (
        "natural experiment", "quasi-experiment", "quasi experiment",
        "interrupted time series", "difference-in-differences", "difference in differences",
        "regression discontinuity", "instrumental variable", "policy shock",
        "exogenous shock",
    ),
    "OBSERVATIONAL_MODEL_DISCRIMINATION": (
        "observational", "cohort", "case-control", "cross-sectional", "longitudinal",
        "time series", "monitoring", "field observation", "survey", "remote sensing",
        "competing prediction", "model discrimination",
    ),
    "COMPUTATIONAL_INTERVENTION": (
        "simulation", "in silico", "computational", "algorithm", "model ablation",
        "parameter sweep", "sensitivity analysis", "counterfactual simulation",
        "numerical model",
    ),
    "INSTRUMENTATION_OR_MEASUREMENT": (
        "instrument", "sensor", "detector", "calibration", "reference material",
        "measurement uncertainty", "detection limit", "signal-to-noise",
        "precision", "accuracy", "metrology",
    ),
    "LABORATORY_CONSTRAINT": (
        "rate constant", "binding constant", "half-life", "diffusion coefficient",
        "cross section", "material parameter", "quantitative parameter",
        "laboratory measurement", "constraint",
    ),
    "THEORETICAL_OR_FORMAL": (
        "theorem", "proof", "lemma", "axiom", "derivation", "closed-form",
        "analytical solution", "formal model", "mathematical model",
        "theoretical prediction",
    ),
}

STRATEGY_WEIGHTS = {
    # User-facing default: prioritize high-impact, feasible, still-interesting
    # branches.  Strategic alignment is scored and reported separately; the
    # default overall follows the requested 0.40 / 0.35 / 0.25 core mix.
    "balanced": {"impact": 0.40, "feasibility": 0.35, "novelty": 0.25, "strategic_alignment": 0.00},
    "quick_wins": {"impact": 0.25, "feasibility": 0.45, "novelty": 0.15, "strategic_alignment": 0.15},
    "moonshots": {"impact": 0.45, "feasibility": 0.15, "novelty": 0.30, "strategic_alignment": 0.10},
    "policy_action": {"impact": 0.35, "feasibility": 0.25, "novelty": 0.10, "strategic_alignment": 0.30},
    "mechanism_discovery": {"impact": 0.30, "feasibility": 0.20, "novelty": 0.35, "strategic_alignment": 0.15},
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_text(item) for item in value)
    return str(value or "")


def _project_context_text(project: dict[str, Any]) -> str:
    return _clean(
        " ".join(
            _flatten_text(item)
            for item in (
                project.get("title"),
                project.get("domain"),
                project.get("declared_domain"),
                project.get("objective"),
                project.get("strategic_need"),
            )
        )
    ).lower()


def _subhypothesis_text(sub_hypothesis: dict[str, Any]) -> str:
    sub_bits = [
        sub_hypothesis.get("focus"),
        sub_hypothesis.get("primary_field"),
        sub_hypothesis.get("scientific_object"),
        sub_hypothesis.get("retrieval_query"),
        sub_hypothesis.get("evidence_mode"),
        sub_hypothesis.get("independent_variable"),
        sub_hypothesis.get("dependent_variables"),
        sub_hypothesis.get("controls"),
        sub_hypothesis.get("comparison"),
        sub_hypothesis.get("causal_chain"),
        sub_hypothesis.get("causal_contract"),
        sub_hypothesis.get("evidence_paths"),
        sub_hypothesis.get("alternative_mechanisms"),
    ]
    return _clean(" ".join(_flatten_text(item) for item in sub_bits)).lower()


def _project_subhypothesis_text(project: dict[str, Any], sub_hypothesis: dict[str, Any]) -> str:
    return _clean(f"{_subhypothesis_text(sub_hypothesis)} {_project_context_text(project)}").lower()


def _matches(text: str, patterns: tuple[str, ...]) -> list[str]:
    return [pattern for pattern in patterns if pattern in text]


def _normalize_hypothesis_type(value: Any) -> str:
    key = _key(value)
    resolved = TYPE_ALIASES.get(key, key)
    return resolved if resolved in HYPOTHESIS_TYPES else ""


def _normalize_scale(value: Any) -> str:
    key = _key(value)
    return key if key in SCALES else ""


def _normalize_mode(value: Any) -> str:
    raw = str(value or "").strip()
    upper = raw.upper()
    if upper in RESEARCH_MODE_PRIORS:
        return upper
    return MODE_ALIASES.get(_key(raw), "")


def _strategy(value: Any) -> str:
    key = _key(value)
    return key if key in STRATEGY_WEIGHTS else "balanced"


def normalize_retrieval_order(value: Any) -> str:
    key = _key(value)
    return key if key in RETRIEVAL_ORDERS else "tier_then_decomposition"


def _infer_hypothesis_type(text: str, sub_hypothesis: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    scores = {
        hypothesis_type: len(_matches(text, keywords))
        for hypothesis_type, keywords in TYPE_KEYWORDS.items()
    }
    evidence_paths = sub_hypothesis.get("evidence_paths")
    if isinstance(evidence_paths, list) and len(evidence_paths) >= 2:
        scores["combined_strategy"] += 1 if _matches(text, TYPE_KEYWORDS["combined_strategy"]) else 0
    evidence_mode = str(sub_hypothesis.get("evidence_mode") or "").lower()
    if evidence_mode == "predictive_generalization":
        scores["surveillance_monitoring"] += 1
    if not any(scores.values()):
        return "unresolved", {"scores": scores, "matched_terms": {}}
    priority = {
        "combined_strategy": 6,
        "policy_population": 5,
        "environmental_ecological": 4,
        "surveillance_monitoring": 3,
        "clinical_intervention": 2,
        "basic_mechanism": 1,
    }
    selected = max(scores, key=lambda name: (scores[name], priority[name]))
    return selected, {
        "scores": scores,
        "matched_terms": {
            name: _matches(text, keywords)[:10]
            for name, keywords in TYPE_KEYWORDS.items()
            if _matches(text, keywords)
        },
    }


def _infer_scale(text: str, hypothesis_type: str) -> str:
    scores = {scale: len(_matches(text, keywords)) for scale, keywords in SCALE_KEYWORDS.items()}
    if scores["cross_scale"]:
        return "cross_scale"
    if hypothesis_type == "combined_strategy":
        return "cross_scale"
    if hypothesis_type in {"policy_population", "environmental_ecological"}:
        return "macro"
    if hypothesis_type in {"clinical_intervention", "surveillance_monitoring"} and not scores["micro"]:
        return "meso"
    if any(scores.values()):
        priority = {"cross_scale": 4, "macro": 3, "meso": 2, "micro": 1}
        return max(scores, key=lambda name: (scores[name], priority[name]))
    return "micro" if hypothesis_type == "basic_mechanism" else "meso"


def _infer_research_mode(text: str, hypothesis_type: str) -> str:
    scores = {mode: len(_matches(text, keywords)) for mode, keywords in MODE_KEYWORDS.items()}
    for preferred in (
        "THEORETICAL_OR_FORMAL",
        "COMPUTATIONAL_INTERVENTION",
        "INSTRUMENTATION_OR_MEASUREMENT",
        "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT",
        "CONTROLLED_INTERVENTION",
        "OBSERVATIONAL_MODEL_DISCRIMINATION",
        "LABORATORY_CONSTRAINT",
    ):
        if scores.get(preferred):
            return preferred
    defaults = {
        "clinical_intervention": "CONTROLLED_INTERVENTION",
        "policy_population": "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT",
        "environmental_ecological": "OBSERVATIONAL_MODEL_DISCRIMINATION",
        "basic_mechanism": "CONTROLLED_INTERVENTION",
        "surveillance_monitoring": "INSTRUMENTATION_OR_MEASUREMENT",
        "combined_strategy": "OBSERVATIONAL_MODEL_DISCRIMINATION",
    }
    return defaults.get(hypothesis_type, "UNRESOLVED_RESEARCH_DESIGN")


def _clamp_score(value: Any, default: int = 5) -> int:
    try:
        numeric = int(round(float(value)))
    except (TypeError, ValueError):
        numeric = int(default)
    return max(1, min(10, numeric))


def _significant_terms(value: Any) -> set[str]:
    stop = {
        "the", "and", "for", "with", "from", "that", "this", "into", "can", "could",
        "would", "should", "research", "study", "effect", "effects", "role",
        "mechanism", "evidence", "using", "through", "between", "across",
    }
    return {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_+\-./]{2,}", str(value or "").lower())
        if token not in stop
    }


def _strategic_alignment(project: dict[str, Any], sub_hypothesis: dict[str, Any], text: str) -> int:
    strategic_need = _clean(project.get("strategic_need"))
    if not strategic_need:
        return 6
    strategic_terms = _significant_terms(strategic_need)
    if not strategic_terms:
        return 6
    hypothesis_terms = _significant_terms(text)
    overlap = strategic_terms & hypothesis_terms
    ratio = len(overlap) / max(1, min(10, len(strategic_terms)))
    return _clamp_score(5 + round(5 * ratio), default=6)


def _score_priority(
    project: dict[str, Any],
    sub_hypothesis: dict[str, Any],
    *,
    hypothesis_type: str,
    scale: str,
    research_mode_prior: str,
    strategy: str,
    text: str,
) -> dict[str, Any]:
    impact_base = {
        "clinical_intervention": 7,
        "policy_population": 8,
        "environmental_ecological": 8,
        "basic_mechanism": 7,
        "surveillance_monitoring": 6,
        "combined_strategy": 8,
    }
    feasibility_base = {
        "clinical_intervention": 7,
        "policy_population": 5,
        "environmental_ecological": 5,
        "basic_mechanism": 6,
        "surveillance_monitoring": 8,
        "combined_strategy": 4,
    }
    novelty_base = {
        "clinical_intervention": 5,
        "policy_population": 6,
        "environmental_ecological": 7,
        "basic_mechanism": 7,
        "surveillance_monitoring": 4,
        "combined_strategy": 6,
    }
    impact = impact_base.get(hypothesis_type, 6)
    feasibility = feasibility_base.get(hypothesis_type, 5)
    novelty = novelty_base.get(hypothesis_type, 6)

    if _matches(text, ("global", "safety", "security", "energy", "health", "food", "climate", "scalable", "stability", "efficiency")):
        impact += 1
    if _matches(text, ("fundamental", "root cause", "mechanistic bottleneck", "limiting factor")):
        impact += 1
    if sub_hypothesis.get("comparison") and sub_hypothesis.get("dependent_variables") and sub_hypothesis.get("falsification_condition"):
        feasibility += 1
    if research_mode_prior in {"COMPUTATIONAL_INTERVENTION", "INSTRUMENTATION_OR_MEASUREMENT", "THEORETICAL_OR_FORMAL"}:
        feasibility += 1
    if research_mode_prior in {"NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT", "OBSERVATIONAL_MODEL_DISCRIMINATION"} and scale == "macro":
        feasibility -= 1
    if _matches(text, ("long-term", "multi-year", "national", "global", "ecosystem", "population-wide")):
        feasibility -= 1
    if _matches(text, ("novel", "new", "emerging", "unknown", "unclear", "underexplored", "unresolved", "frontier")):
        novelty += 1
    if _matches(text, ("established", "standard", "routine", "well-studied", "systematic review", "meta-analysis")):
        novelty -= 1

    strategic_alignment = _strategic_alignment(project, sub_hypothesis, text)
    if strategy == "policy_action":
        if hypothesis_type == "policy_population":
            impact += 1
            strategic_alignment += 2
        if hypothesis_type in {"clinical_intervention", "surveillance_monitoring"} and _matches(
            text,
            ("implementation", "adoption", "stewardship", "monitoring", "surveillance", "decision-support"),
        ):
            feasibility += 1
            strategic_alignment += 1
    if strategy == "mechanism_discovery":
        if hypothesis_type == "basic_mechanism":
            impact += 1
            novelty += 1
            strategic_alignment += 1
        if research_mode_prior in {"THEORETICAL_OR_FORMAL", "LABORATORY_CONSTRAINT", "COMPUTATIONAL_INTERVENTION"}:
            feasibility += 1
        if _matches(text, ("source-bound", "mechanistic gap", "mediator", "rate constant", "parameter", "ablation")):
            novelty += 1
            strategic_alignment += 1
    impact = _clamp_score(impact)
    feasibility = _clamp_score(feasibility)
    novelty = _clamp_score(novelty)
    strategic_alignment = _clamp_score(strategic_alignment)
    overall = _priority_overall(
        {
            "impact": impact,
            "feasibility": feasibility,
            "novelty": novelty,
            "strategic_alignment": strategic_alignment,
        },
        strategy=strategy,
    )
    return {
        "impact": impact,
        "feasibility": feasibility,
        "novelty": novelty,
        "strategic_alignment": strategic_alignment,
        "overall": overall,
        "tier": _priority_tier(impact, feasibility, overall),
        "strategy": strategy,
    }


def _priority_overall(priority: dict[str, Any], *, strategy: str) -> float:
    weights = STRATEGY_WEIGHTS.get(_strategy(strategy), STRATEGY_WEIGHTS["balanced"])
    weighted = sum(float(weights[key]) * _clamp_score(priority.get(key), default=5) for key in weights)
    return round(max(0.0, min(1.0, weighted / 10.0)), 3)


def _priority_tier(impact: int, feasibility: int, overall: float) -> str:
    if impact >= 7 and feasibility >= 7:
        return "QUICK_WIN"
    if impact >= 7 and feasibility <= 5:
        return "MOONSHOT"
    if impact <= 6 and feasibility >= 7:
        return "FILL_IN"
    if overall < 0.45 or (impact <= 4 and feasibility <= 5):
        return "DROP_OR_DEFER"
    return "MOONSHOT" if impact >= 7 else "FILL_IN"


def normalize_subhypothesis_annotation(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    hypothesis_type = _normalize_hypothesis_type(raw.get("hypothesis_type")) or "unresolved"
    scale = _normalize_scale(raw.get("scale")) or ("cross_scale" if hypothesis_type == "combined_strategy" else "micro")
    epistemic_profile = normalize_epistemic_profile(raw.get("epistemic_profile") or raw)
    requested_standard = str(raw.get("evidence_standard_id") or "").strip()
    profile_standard = str(epistemic_profile.get("evidence_standard_id") or "").strip()
    # ``basic_mechanism_v1`` was historically injected as a generic fallback.
    # It must not override a newly recognized observational, formal, or
    # computational profile merely because an old project persisted it.
    if not requested_standard or (
        requested_standard == "basic_mechanism_v1"
        and profile_standard
        and profile_standard != "experimental_causal_v1"
    ):
        requested_standard = profile_standard
    standard_id = normalize_evidence_standard_id(requested_standard, hypothesis_type=hypothesis_type)
    raw_standard_ids = raw.get("evidence_standard_ids") or raw.get("evidence_standards") or []
    if isinstance(raw_standard_ids, str):
        raw_standard_ids = [raw_standard_ids]
    standard_ids = []
    for value in [
        standard_id,
        *(epistemic_profile.get("evidence_standard_ids") or []),
        *raw_standard_ids,
    ]:
        normalized_id = normalize_evidence_standard_id(value, hypothesis_type=hypothesis_type)
        if normalized_id and normalized_id not in standard_ids:
            standard_ids.append(normalized_id)
    standard = get_evidence_standard(standard_id, hypothesis_type=hypothesis_type)
    research_mode_prior = (
        _normalize_mode(raw.get("research_mode_prior"))
        or _normalize_mode(raw.get("declared_research_mode"))
        or _EPISTEMIC_TO_LEGACY_RESEARCH_MODE.get(str(epistemic_profile.get("primary_mode") or ""), "")
        or str(standard.get("default_research_mode_prior") or "UNRESOLVED_RESEARCH_DESIGN")
    )
    priority_raw = raw.get("priority") if isinstance(raw.get("priority"), dict) else {}
    strategy = _strategy(priority_raw.get("strategy") or raw.get("strategy"))
    priority = {
        "impact": _clamp_score(priority_raw.get("impact"), default=5),
        "feasibility": _clamp_score(priority_raw.get("feasibility"), default=5),
        "novelty": _clamp_score(priority_raw.get("novelty"), default=5),
        "strategic_alignment": _clamp_score(priority_raw.get("strategic_alignment"), default=5),
    }
    priority["overall"] = _priority_overall(priority, strategy=strategy)
    priority["tier"] = _priority_tier(priority["impact"], priority["feasibility"], priority["overall"])
    priority["strategy"] = strategy
    research_question_contract = raw.get("research_question_contract")
    if isinstance(research_question_contract, dict) and research_question_contract.get("schema_version") == RESEARCH_QUESTION_CONTRACT_VERSION:
        research_question_contract = validate_research_question_contract(research_question_contract)
    else:
        research_question_contract = {}
    # A current V3 SH is intentionally a research-question contract rather
    # than an implicit causal triad.  Keep any legacy causal metadata outside
    # the annotation projection; the V3 graph never consumes it.
    if research_question_contract:
        question_kind = str((research_question_contract.get("research_question") or {}).get("question_kind") or "")
        causal_model = research_question_contract.get("causal_model")
        if question_kind not in {"CAUSAL_IDENTIFICATION", "MECHANISM_COMPETITION"} and causal_model:
            raise ValueError("Non-causal V3 SH annotations may not carry causal_model")
    # The plan is a deterministic projection of the validated contract rather
    # than mutable SH metadata. Rebuild it here so persistence cannot retain a
    # stale slot plan after a question-contract revision.
    research_question_retrieval_plan = (
        build_question_retrieval_plan(research_question_contract)
        if research_question_contract
        else {}
    )
    return {
        "schema_version": ANNOTATION_SCHEMA_VERSION,
        "hypothesis_type": hypothesis_type,
        "scale": scale,
        "research_mode_prior": research_mode_prior if research_mode_prior in RESEARCH_MODE_PRIORS else "UNRESOLVED_RESEARCH_DESIGN",
        "epistemic_profile": epistemic_profile,
        "claim_types": list(epistemic_profile.get("claim_types") or []),
        "requires_intervention": bool(epistemic_profile.get("requires_intervention") is True),
        "evidence_standard_id": standard_id,
        "evidence_standard_ids": standard_ids,
        "priority": priority,
        "retrieval_policy": evidence_standard_retrieval_policy(standard_id, hypothesis_type=hypothesis_type),
        "research_question_contract": research_question_contract,
        "research_question_retrieval_plan": research_question_retrieval_plan,
        "annotation_source": str(raw.get("annotation_source") or "deterministic_registry_v3"),
        "classification_audit": raw.get("classification_audit") if isinstance(raw.get("classification_audit"), dict) else {},
    }


def infer_subhypothesis_annotation(
    project: dict[str, Any],
    sub_hypothesis: dict[str, Any],
    strategy: str = "balanced",
) -> dict[str, Any]:
    project = project if isinstance(project, dict) else {}
    sub_hypothesis = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    normalized_strategy = _strategy(strategy)
    existing = sub_hypothesis.get("hypothesis_annotation") if isinstance(sub_hypothesis.get("hypothesis_annotation"), dict) else {}
    epistemic_profile = infer_epistemic_profile(project, sub_hypothesis)
    research_question_contract = build_research_question_contract(
        project,
        sub_hypothesis,
        epistemic_profile=epistemic_profile,
    )
    research_question_retrieval_plan = build_question_retrieval_plan(research_question_contract)
    local_text = _subhypothesis_text(sub_hypothesis)
    priority_text = _project_subhypothesis_text(project, sub_hypothesis)
    inferred_type, type_audit = _infer_hypothesis_type(local_text, sub_hypothesis)
    hypothesis_type = (
        _normalize_hypothesis_type(sub_hypothesis.get("hypothesis_type"))
        or _normalize_hypothesis_type(existing.get("hypothesis_type"))
        or inferred_type
    )
    scale = (
        _normalize_scale(sub_hypothesis.get("scale"))
        or _normalize_scale(existing.get("scale"))
        or _infer_scale(local_text, hypothesis_type)
    )
    research_mode_prior = (
        _normalize_mode(sub_hypothesis.get("declared_research_mode"))
        or _normalize_mode(sub_hypothesis.get("research_mode"))
        or _normalize_mode(existing.get("research_mode_prior"))
        or _EPISTEMIC_TO_LEGACY_RESEARCH_MODE.get(str(epistemic_profile.get("primary_mode") or ""), "")
        or _infer_research_mode(local_text, hypothesis_type)
    )
    requested_standard = str(
        sub_hypothesis.get("evidence_standard_hint")
        or existing.get("evidence_standard_id")
        or ""
    ).strip()
    if (
        not requested_standard
        and not isinstance(sub_hypothesis.get("epistemic_profile"), dict)
        and hypothesis_type != "basic_mechanism"
    ):
        # Preserve legacy specialized SH contracts. Newly decomposed items
        # carry an explicit epistemic profile and therefore select the newer
        # claim-compatible standard below.
        requested_standard = normalize_evidence_standard_id("", hypothesis_type=hypothesis_type)
    if not requested_standard or (
        requested_standard == "basic_mechanism_v1"
        and str(epistemic_profile.get("evidence_standard_id") or "") != "experimental_causal_v1"
    ):
        requested_standard = str(epistemic_profile.get("evidence_standard_id") or "")
    evidence_standard_id = normalize_evidence_standard_id(
        requested_standard,
        hypothesis_type=hypothesis_type,
    )
    priority = _score_priority(
        project,
        sub_hypothesis,
        hypothesis_type=hypothesis_type,
        scale=scale,
        research_mode_prior=research_mode_prior,
        strategy=normalized_strategy,
        text=priority_text,
    )
    mode_matches = {
        mode: _matches(local_text, keywords)[:10]
        for mode, keywords in MODE_KEYWORDS.items()
        if _matches(local_text, keywords)
    }
    return normalize_subhypothesis_annotation(
        {
            "hypothesis_type": hypothesis_type,
            "scale": scale,
            "research_mode_prior": research_mode_prior,
            "epistemic_profile": epistemic_profile,
            "research_question_contract": research_question_contract,
            "research_question_retrieval_plan": research_question_retrieval_plan,
            "evidence_standard_id": evidence_standard_id,
            "priority": priority,
            "strategy": normalized_strategy,
            "annotation_source": "deterministic_registry_v2",
            "classification_audit": {
                "type_inference": type_audit,
                "research_mode_matches": mode_matches,
                "epistemic_profile": epistemic_profile.get("classification_audit") or {},
                "llm_or_existing_hints_normalized": bool(existing or sub_hypothesis.get("hypothesis_type") or sub_hypothesis.get("evidence_standard_hint")),
            },
        }
    )


def retrieval_budget_for_subhypothesis(
    sub_hypothesis: dict[str, Any],
    *,
    base_peer_reviewed_full_text_target: int = 10,
    base_direct_core_full_text_target: int = 10,
    base_batch_size: int = 18,
    base_max_rounds: int = 3,
    strategy: str = "balanced",
) -> dict[str, Any]:
    """Return deterministic execution budget implied by an SH annotation.

    The evidence standard sets what evidence shape can count for the question.
    The priority tier sets how much retrieval effort to spend by default.
    Crucially, the standard also carries a claim-strength cap, so a lower
    target for ecological or monitoring evidence cannot be laundered into a
    stronger clinical or universal causal conclusion downstream.
    """

    sub_hypothesis = sub_hypothesis if isinstance(sub_hypothesis, dict) else {}
    annotation = (
        sub_hypothesis.get("hypothesis_annotation")
        if isinstance(sub_hypothesis.get("hypothesis_annotation"), dict)
        else {}
    )
    normalized_strategy = _strategy(strategy)
    normalized = normalize_subhypothesis_annotation({
        **annotation,
        "priority": {
            **(annotation.get("priority") if isinstance(annotation.get("priority"), dict) else {}),
            "strategy": normalized_strategy,
        },
        "strategy": normalized_strategy,
    })
    priority = normalized.get("priority") if isinstance(normalized.get("priority"), dict) else {}
    retrieval_policy = (
        normalized.get("retrieval_policy")
        if isinstance(normalized.get("retrieval_policy"), dict)
        else {}
    )
    configured_default_total = 10
    requested_total = max(1, int(base_peer_reviewed_full_text_target or configured_default_total))
    standard_total = max(
        1,
        int(retrieval_policy.get("peer_reviewed_full_text_target") or requested_total),
    )
    # Production SH retrieval has one fixed corpus-size contract. Evidence
    # standards still control which designs count as core, but caller budgets
    # cannot silently expand one SH beyond the 10-paper full-text limit.
    effective_total = configured_default_total
    standard_direct = max(
        1,
        int(retrieval_policy.get("direct_core_full_text_target") or base_direct_core_full_text_target or 1),
    )
    effective_direct = min(effective_total, standard_direct)
    gate_total = effective_total
    gate_direct = effective_direct
    discovery_total = effective_total
    discovery_direct = effective_direct
    effective_batch_size = max(1, int(base_batch_size or 1))
    effective_max_rounds = max(1, int(base_max_rounds or 1))
    tier = str(priority.get("tier") or "FILL_IN")
    lightweight = tier == "DROP_OR_DEFER"
    budget_policy = "evidence_standard_default"

    if lightweight:
        # Priority can change execution order, but every SH must still build the
        # same 10-full-text portfolio needed for gap generation.
        effective_batch_size = max(10, effective_batch_size)
        budget_policy = "uniform_10_fulltext_portfolio"
    elif tier == "FILL_IN":
        effective_batch_size = min(effective_batch_size, 16)
        budget_policy = "fill_in_standard_gate_modest_discovery"

    return {
        "schema_version": "subhypothesis_retrieval_priority_budget_v1",
        "strategy": _strategy(strategy),
        "tier": tier if tier in PRIORITY_TIERS else "FILL_IN",
        "budget_policy": budget_policy,
        "lightweight_retrieval": lightweight,
        "peer_reviewed_full_text_target": int(gate_total),
        "direct_core_full_text_target": int(min(gate_total, gate_direct)),
        "discovery_peer_reviewed_full_text_target": int(discovery_total),
        "discovery_direct_core_full_text_target": int(min(discovery_total, discovery_direct)),
        "batch_size": int(effective_batch_size),
        "max_rounds": int(effective_max_rounds),
        "evidence_standard_id": str(normalized.get("evidence_standard_id") or ""),
        "claim_strength_cap": str(retrieval_policy.get("claim_strength_cap") or ""),
        "standard_peer_reviewed_full_text_target": int(standard_total),
        "standard_direct_core_full_text_target": int(min(standard_total, standard_direct)),
        "caller_peer_reviewed_full_text_target": int(requested_total),
        "caller_direct_core_full_text_target": int(base_direct_core_full_text_target or 0),
    }


def rank_subhypotheses_for_retrieval(
    sub_hypotheses: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    strategy: str = "balanced",
    retrieval_order: str = "tier_then_decomposition",
) -> list[dict[str, Any]]:
    """Order SHs for retrieval without dropping branches.

    Default ``tier_then_decomposition`` keeps the scientific narrative order
    inside each tier, so tiny deterministic score differences do not make later
    SHs appear to "skip ahead" in the logs.  The legacy score-first behavior is
    still available as ``retrieval_order="priority"`` for strategy experiments.

    DROP_OR_DEFER branches remain in the returned list so reports can explain
    that they received lightweight treatment rather than silently disappearing
    from the workflow.
    """

    normalized_strategy = _strategy(strategy)
    normalized_order = normalize_retrieval_order(retrieval_order)
    candidates = [
        item
        for item in (sub_hypotheses or [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]

    def sort_key(indexed_item: tuple[int, dict[str, Any]]) -> tuple[Any, ...]:
        original_index, item = indexed_item
        annotation = (
            item.get("hypothesis_annotation")
            if isinstance(item.get("hypothesis_annotation"), dict)
            else {}
        )
        normalized = normalize_subhypothesis_annotation({
            **annotation,
            "priority": {
                **(annotation.get("priority") if isinstance(annotation.get("priority"), dict) else {}),
                "strategy": normalized_strategy,
            },
            "strategy": normalized_strategy,
        })
        priority = normalized.get("priority") if isinstance(normalized.get("priority"), dict) else {}
        tier = str(priority.get("tier") or "FILL_IN")
        tier_rank = PRIORITY_TIER_RETRIEVAL_ORDER.get(tier, PRIORITY_TIER_RETRIEVAL_ORDER["FILL_IN"])
        if normalized_order == "decomposition":
            return (original_index, str(item.get("id") or ""))
        if normalized_order == "priority":
            return (
                tier_rank,
                -float(priority.get("overall") or 0.0),
                -int(priority.get("impact") or 0),
                -int(priority.get("feasibility") or 0),
                -int(priority.get("novelty") or 0),
                original_index,
                str(item.get("id") or ""),
            )
        return (
            tier_rank,
            original_index,
            str(item.get("id") or ""),
        )

    ranked = [item for _, item in sorted(enumerate(candidates), key=sort_key)]
    for rank, item in enumerate(ranked, start=1):
        annotation = (
            item.get("hypothesis_annotation")
            if isinstance(item.get("hypothesis_annotation"), dict)
            else {}
        )
        normalized = normalize_subhypothesis_annotation({
            **annotation,
            "priority": {
                **(annotation.get("priority") if isinstance(annotation.get("priority"), dict) else {}),
                "strategy": normalized_strategy,
            },
            "strategy": normalized_strategy,
        })
        priority = normalized.get("priority") if isinstance(normalized.get("priority"), dict) else {}
        tier = str(priority.get("tier") or "FILL_IN")
        budget = retrieval_budget_for_subhypothesis(item, strategy=normalized_strategy)
        item["retrieval_priority"] = {
            "schema_version": "subhypothesis_retrieval_priority_v1",
            "strategy": normalized_strategy,
            "retrieval_order": normalized_order,
            "rank": rank,
            "tier": tier if tier in PRIORITY_TIERS else "FILL_IN",
            "overall": float(priority.get("overall") or 0.0),
            "impact": int(priority.get("impact") or 0),
            "feasibility": int(priority.get("feasibility") or 0),
            "novelty": int(priority.get("novelty") or 0),
            "budget_policy": budget.get("budget_policy"),
            "lightweight_retrieval": bool(budget.get("lightweight_retrieval")),
            "claim_strength_cap": budget.get("claim_strength_cap"),
        }
    return ranked


def annotate_project_subhypotheses(
    project: dict[str, Any],
    strategy: str = "balanced",
) -> dict[str, Any]:
    project = project if isinstance(project, dict) else {}
    sub_hypotheses = project.get("sub_hypotheses")
    if not isinstance(sub_hypotheses, list):
        sub_hypotheses = []
        project["sub_hypotheses"] = sub_hypotheses
    normalized_strategy = _strategy(strategy)
    annotations_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(sub_hypotheses):
        if not isinstance(item, dict):
            continue
        sub_id = str(item.get("id") or f"SH{index + 1}").strip()
        is_declared_v3 = bool(
            isinstance(item.get("research_question"), dict)
            or item.get("evidence_pipeline_schema") == "research_question_evidence_v3"
            or (
                isinstance(item.get("research_question_contract"), dict)
                and item.get("research_question_contract", {}).get("schema_version")
                == RESEARCH_QUESTION_CONTRACT_VERSION
            )
        )
        if not is_declared_v3:
            # V3 is a hard cutover.  A legacy SH is neither converted nor
            # marked as V3 merely because this annotation helper knows how to
            # build a generic question contract.  It must be re-decomposed.
            item["evidence_pipeline_schema"] = "STALE_SCHEMA"
            item["legacy_causal_artifacts_status"] = "STALE_SCHEMA"
            item["hypothesis_annotation_status"] = "research_question_contract_v3_required"
            annotations_by_id[sub_id] = {
                "schema_version": ANNOTATION_SCHEMA_VERSION,
                "status": "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED",
                "research_question_contract": {},
                "research_question_retrieval_plan": {},
                "annotation_source": "hard_cutover_no_legacy_adapter",
            }
            continue
        try:
            annotation = infer_subhypothesis_annotation(project, item, strategy=normalized_strategy)
        except ValueError:
            item["evidence_pipeline_schema"] = "STALE_SCHEMA"
            item["legacy_causal_artifacts_status"] = "STALE_SCHEMA"
            item["hypothesis_annotation_status"] = "research_question_contract_v3_required"
            annotations_by_id[sub_id] = {
                "schema_version": ANNOTATION_SCHEMA_VERSION,
                "status": "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED",
                "research_question_contract": {},
                "research_question_retrieval_plan": {},
                "annotation_source": "stale_or_incomplete_v3_contract_requires_redecomposition",
            }
            continue
        item["hypothesis_annotation"] = annotation
        item["research_question_contract"] = dict(annotation.get("research_question_contract") or {})
        item["research_question_retrieval_plan"] = dict(annotation.get("research_question_retrieval_plan") or {})
        if isinstance(item.get("research_question_retrieval_execution"), dict):
            item["research_question_retrieval_execution"] = dict(
                item["research_question_retrieval_execution"]
            )
        # Explicit hard-cutover marker for downstream systems.  Old causal
        # alignment artefacts may remain stored for audit/history but are
        # never inputs to the V3 evidence or gap route.
        item["evidence_pipeline_schema"] = "research_question_evidence_v3"
        item["legacy_causal_artifacts_status"] = "STALE_SCHEMA"
        item["hypothesis_annotation_status"] = "ready"
        item["retrieval_priority"] = {
            "schema_version": "subhypothesis_retrieval_priority_v1",
            "strategy": normalized_strategy,
            "rank": 0,
            "tier": (annotation.get("priority") or {}).get("tier"),
            "overall": (annotation.get("priority") or {}).get("overall"),
            "impact": (annotation.get("priority") or {}).get("impact"),
            "feasibility": (annotation.get("priority") or {}).get("feasibility"),
            "novelty": (annotation.get("priority") or {}).get("novelty"),
            "claim_strength_cap": (annotation.get("retrieval_policy") or {}).get("claim_strength_cap"),
        }
        if sub_id:
            annotations_by_id[sub_id] = annotation

    summary = _annotation_summary(annotations_by_id, strategy=normalized_strategy)
    summary["epistemic_role_coverage"] = summarize_project_evidence_role_coverage(sub_hypotheses)
    project["subhypothesis_annotation_summary"] = summary
    try:
        from ._project import apply_v3_subhypothesis_relationships
    except ImportError:
        from _project import apply_v3_subhypothesis_relationships
    project["shared_knowledge_registry"] = apply_v3_subhypothesis_relationships(
        sub_hypotheses
    )
    decomposition = project.get("objective_decomposition")
    if isinstance(decomposition, dict):
        decomposition["subhypothesis_annotation_summary"] = summary
        decomposition_items = decomposition.get("sub_hypotheses")
        if isinstance(decomposition_items, list) and decomposition_items is not sub_hypotheses:
            for index, item in enumerate(decomposition_items):
                if not isinstance(item, dict):
                    continue
                sub_id = str(item.get("id") or f"SH{index + 1}").strip()
                annotation = annotations_by_id.get(sub_id)
                if annotation and annotation.get("status") == "RESEARCH_QUESTION_CONTRACT_V3_REQUIRED":
                    item["evidence_pipeline_schema"] = "STALE_SCHEMA"
                    item["legacy_causal_artifacts_status"] = "STALE_SCHEMA"
                    item["hypothesis_annotation_status"] = "research_question_contract_v3_required"
                elif annotation:
                    item["hypothesis_annotation"] = annotation
                    item["research_question_contract"] = dict(annotation.get("research_question_contract") or {})
                    item["research_question_retrieval_plan"] = dict(annotation.get("research_question_retrieval_plan") or {})
                    item["evidence_pipeline_schema"] = "research_question_evidence_v3"
                    item["legacy_causal_artifacts_status"] = "STALE_SCHEMA"
                    item["hypothesis_annotation_status"] = "ready"
                    item["retrieval_priority"] = {
                        "schema_version": "subhypothesis_retrieval_priority_v1",
                        "strategy": normalized_strategy,
                        "rank": 0,
                        "tier": (annotation.get("priority") or {}).get("tier"),
                        "overall": (annotation.get("priority") or {}).get("overall"),
                        "impact": (annotation.get("priority") or {}).get("impact"),
                        "feasibility": (annotation.get("priority") or {}).get("feasibility"),
                        "novelty": (annotation.get("priority") or {}).get("novelty"),
                        "claim_strength_cap": (annotation.get("retrieval_policy") or {}).get("claim_strength_cap"),
                    }
    return summary


def _annotation_summary(annotations_by_id: dict[str, dict[str, Any]], *, strategy: str) -> dict[str, Any]:
    by_type = Counter(str(item.get("hypothesis_type") or "") for item in annotations_by_id.values())
    by_scale = Counter(str(item.get("scale") or "") for item in annotations_by_id.values())
    by_standard = Counter(str(item.get("evidence_standard_id") or "") for item in annotations_by_id.values())
    by_tier = Counter(str((item.get("priority") or {}).get("tier") or "") for item in annotations_by_id.values())
    ordered = sorted(
        annotations_by_id,
        key=lambda sub_id: (
            PRIORITY_TIER_RETRIEVAL_ORDER.get(
                str((annotations_by_id[sub_id].get("priority") or {}).get("tier") or "FILL_IN"),
                PRIORITY_TIER_RETRIEVAL_ORDER["FILL_IN"],
            ),
            -float((annotations_by_id[sub_id].get("priority") or {}).get("overall") or 0.0),
            sub_id,
        ),
    )
    return {
        "schema_version": ANNOTATION_SUMMARY_SCHEMA_VERSION,
        "strategy": strategy,
        "total": len(annotations_by_id),
        "by_hypothesis_type": dict(sorted(by_type.items())),
        "by_scale": dict(sorted(by_scale.items())),
        "by_evidence_standard": dict(sorted(by_standard.items())),
        "by_priority_tier": dict(sorted(by_tier.items())),
        "priority_by_sub_hypothesis_id": {
            sub_id: annotations_by_id[sub_id].get("priority", {})
            for sub_id in sorted(annotations_by_id)
        },
        "evidence_standard_by_sub_hypothesis_id": {
            sub_id: str(annotations_by_id[sub_id].get("evidence_standard_id") or "")
            for sub_id in sorted(annotations_by_id)
        },
        "ordered_sub_hypothesis_ids": ordered,
    }
