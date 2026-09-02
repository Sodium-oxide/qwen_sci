from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any
import ast
import json
import re
import time

try:
    from .log import log_event
    from ._hierarchical_hypothesis import (
        HIERARCHY_VERSION,
        audit_hierarchical_candidate,
        recombine_hierarchical_candidates,
        run_hierarchical_hypothesis_search,
    )
    from ._intervention_ontology import classify_intervention_candidate, classify_mediator_candidate, intervention_gate_from_values
except ImportError:
    from log import log_event
    from _hierarchical_hypothesis import (
        HIERARCHY_VERSION,
        audit_hierarchical_candidate,
        recombine_hierarchical_candidates,
        run_hierarchical_hypothesis_search,
    )
    from _intervention_ontology import classify_intervention_candidate, classify_mediator_candidate, intervention_gate_from_values



def run_mingli_hypothesis_evolution(
    project_id: str,
    gap_ids: list[str] | None = None,
    population_size: int = 24,
    generations: int = 4,
    top_k: int = 5,
    use_llm: bool = False,
) -> str:
    try:
        from ._gap_detection import build_temporal_knowledge_graph, detect_knowledge_gaps, detect_structural_knowledge_gaps, find_structural_analogy_transfers
        from ._models import Hypothesis
        from ._project import load_project, save_project
        from ._research_workflow import mingli_workflow_contract, record_workflow_status, workflow_tool_gate
        from ._utils import clamp_int, new_id
    except ImportError:
        from _gap_detection import build_temporal_knowledge_graph, detect_knowledge_gaps, detect_structural_knowledge_gaps, find_structural_analogy_transfers
        from _models import Hypothesis
        from _project import load_project, save_project
        from _research_workflow import mingli_workflow_contract, record_workflow_status, workflow_tool_gate
        from _utils import clamp_int, new_id
    project = load_project(project_id)
    gate = workflow_tool_gate(
        project,
        "run_mingli_hypothesis_evolution",
        {
            "gap_ids": list(gap_ids or []),
            "population_size": population_size,
            "generations": generations,
            "top_k": top_k,
            "use_llm": use_llm,
        },
    )
    if not gate.get("allowed"):
        run = dict(gate.get("result") or {})
        return json.dumps(run, ensure_ascii=False, indent=2)
    materialized_bridge_packages = ensure_restricted_component_bridge_hypothesis_packages(
        project,
        gap_ids=gap_ids,
    )
    if materialized_bridge_packages:
        project["updatedAt"] = time.time()
        save_project(project)
    blueprint = build_project_theory_blueprint(project)
    project["mechanism_blueprint"] = blueprint
    project["mechanism_blueprint_evidence_updates"] = [
        action
        for record in project.get("papergraph", [])
        if isinstance(record, dict)
        for action in classify_blueprint_evidence_action(blueprint, record)
    ]
    if not project.get("knowledge_gaps"):
        detect_knowledge_gaps(project_id, max_gaps=10)
        project = load_project(project_id)
    selected_gaps = select_gaps_for_hypothesis(project, gap_ids)
    if not selected_gaps:
        run = {
            "project_id": project_id,
            "status": "BLOCKED_NO_READY_HANDOFF",
            "terminal": True,
            "reason_code": "NO_ELIGIBLE_GAPS_AFTER_WORKFLOW_GATE",
            "allowed_next_stages": [],
            "blocked_stages": ["run_mingli_hypothesis_evolution"],
            "top_hypotheses": [],
        }
        record_workflow_status(project, stage="mingli", **mingli_workflow_contract(run))
        project.setdefault("mingli_hypothesis_evolution_runs", []).append(run)
        project["updatedAt"] = time.time()
        save_project(project)
        return json.dumps(run, ensure_ascii=False, indent=2)
    if not project.get("temporal_knowledge_graph"):
        build_temporal_knowledge_graph(project_id)
        project = load_project(project_id)
    if not project.get("structural_gap_analysis"):
        detect_structural_knowledge_gaps(project_id, max_gaps=8)
        project = load_project(project_id)
    if not project.get("structural_analogy_reports"):
        find_structural_analogy_transfers(project_id, threshold=0.55, max_results=8)
        project = load_project(project_id)

    population = seed_hypothesis_population(project, selected_gaps, clamp_int(population_size, 5, 80), use_llm=use_llm)
    if not population:
        blocked_gaps = [
            {
                "gap_id": gap.get("gap_id", ""),
                "intervention_type_gate": mingli_intervention_type_gate(project, gap, infer_gap_components(project, gap)),
            }
            for gap in selected_gaps
        ]
        run = {
            "mingli_run_id": new_id("mingli"),
            "project_id": project_id,
            "createdAt": time.time(),
            "gap_ids": [gap.get("gap_id") for gap in selected_gaps],
            "population_size": 0,
            "generations_completed": 0,
            "top_hypotheses": [],
            "status": "blocked_intervention_ontology",
            "reason": "No selected gap has an evidence-backed direct intervention.",
            "blocked_gaps": blocked_gaps,
        }
        run.update(record_workflow_status(project, stage="mingli", **mingli_workflow_contract(run)))
        project.setdefault("mingli_hypothesis_evolution_runs", []).append(run)
        project["updatedAt"] = time.time()
        save_project(project)
        log_event("SCIENCE", "mingli_hypothesis_evolution_blocked_intervention_ontology", project_id=project_id, gaps=len(blocked_gaps))
        return json.dumps(run, ensure_ascii=False, indent=2)
    lineage: list[dict[str, Any]] = [{"generation": 0, "population_size": len(population), "best_score": best_hypothesis_score(population)}]
    for generation in range(1, clamp_int(generations, 1, 20) + 1):
        winners = tournament_select_hypotheses(population, max(2, min(10, len(population) // 2)))
        offspring = evolve_hypothesis_offspring(project, winners, population_size=max(0, len(population) - len(winners)), generation=generation)
        population = score_hypothesis_population(project, winners + offspring)
        lineage.append({"generation": generation, "population_size": len(population), "best_score": best_hypothesis_score(population)})
        if len(lineage) >= 3 and abs(lineage[-1]["best_score"] - lineage[-2]["best_score"]) < 0.01:
            break

    finalists = select_diverse_hypothesis_finalists(population, top_k=clamp_int(top_k, 1, 20))
    persisted = []
    for item in finalists:
        hypothesis = Hypothesis(
            hypothesis_id=new_id("hyp"),
            gap_id=str(item.get("gap_id") or ""),
            statement=str(item.get("statement") or ""),
            mechanism=str(item.get("mechanism") or ""),
            expected_value=str(item.get("expected_value") or ""),
            test_plan=str(item.get("test_plan") or ""),
            sub_hypothesis_id=str(item.get("sub_hypothesis_id") or ""),
        )
        payload = asdict(hypothesis)
        source_gap = (
            item.get("source_gap")
            if isinstance(item.get("source_gap"), dict) and item.get("source_gap")
            else next(
                (
                    gap
                    for gap in selected_gaps
                    if str(gap.get("gap_id") or "") == str(item.get("gap_id") or "")
                ),
                {},
            )
        )
        hypothesis_package = (
            item.get("hypothesis_package")
            if isinstance(item.get("hypothesis_package"), dict) and item.get("hypothesis_package")
            else hypothesis_package_for_gap(project, str(item.get("gap_id") or ""))
        )
        payload.update(
            {
                "mingli_scores": item.get("scores", {}),
                "plausibility_check": item.get("plausibility_check", {}),
                "score": item.get("score"),
                "lineage": item.get("lineage", []),
                "competition_advantage": item.get("competition_advantage", ""),
                "verification_plan": item.get("verification_plan", {}),
                "source_gap": source_gap,
                "hypothesis_package": hypothesis_package,
                "coverage_audit": (hypothesis_package or {}).get("coverage_audit", {}),
                "compatibility_audit": (hypothesis_package or {}).get("compatibility_audit", {}),
                "conclusion_scope": (hypothesis_package or {}).get("conclusion_scope", {}),
                "final_object_claim_disclaimer": final_object_claim_disclaimer(
                    source_gap,
                    hypothesis_package,
                ),
                "gap_ids": item.get("gap_ids", []),
                "sub_hypothesis_id": item.get("sub_hypothesis_id", ""),
                "counterfactual_experiments": item.get("counterfactual_experiments", []),
                "mechanism_competition": item.get("mechanism_competition", {}),
                "candidate_type": item.get("candidate_type", "mechanism_completion"),
                "claim": item.get("claim", {}),
                "mechanism_edges": item.get("mechanism_edges", []),
                "competing_explanation": item.get("competing_explanation", ""),
                "discriminating_prediction": item.get("discriminating_prediction", ""),
                "boundary": item.get("boundary", ""),
                "falsifier": item.get("falsifier", ""),
                "experiment_design": item.get("experiment_design", {}),
                "experimental_protocol": {},
                "experimental_protocol_validation": {
                    "verdict": "DEFERRED_UNTIL_DEBATE_ACCEPTANCE",
                    "hard_gate_passed": False,
                    "execution_authorized": False,
                },
                "experiment_execution_status": "deferred_until_debate_acceptance",
                "theory_blueprint": item.get("theory_blueprint", blueprint),
                "tournament_generation": item.get("generation", 0),
                "scientific_hypothesis_hierarchy": item.get("scientific_hypothesis_hierarchy", {}),
                "hierarchical_search": item.get("hierarchical_search", {}),
                "hierarchical_gate": item.get("hierarchical_gate", {}),
                "hierarchy_schema_version": (
                    HIERARCHY_VERSION
                    if item.get("scientific_hypothesis_hierarchy")
                    else ""
                ),
            }
        )
        project.setdefault("hypotheses", []).append(payload)
        persisted.append(payload)
    run = {
        "mingli_run_id": new_id("mingli"),
        "project_id": project_id,
        "createdAt": time.time(),
        "gap_ids": [gap.get("gap_id") for gap in selected_gaps],
        "population_size": len(population),
        "generations_completed": len(lineage) - 1,
        "lineage_summary": lineage,
        "top_hypotheses": persisted,
        "method": (
            "frozen TanXi/Socrates contract + five-level source-constrained hierarchical search "
            "+ hard-gated tournament selection + same-contract mutation/recombination"
        ),
        "constraints_checked": {
            "traceable_to_gap": True,
            "papergraph_grounded": True,
            "testability_scored": True,
            "novelty_overlap_local": True,
            "scientific_claim_topology": True,
            "entity_and_causal_role_ontology": True,
            "operationalization_and_discrimination": True,
            "unsupported_precise_values_marked_to_be_optimized": True,
            "validation_safety_reproducibility": True,
            "frozen_contract_immutable": True,
        },
    }
    run.update(record_workflow_status(project, stage="mingli", **mingli_workflow_contract(run)))
    project.setdefault("mingli_hypothesis_evolution_runs", []).append(run)
    project["phase"] = "Hypothesis Generation"
    project["updatedAt"] = time.time()
    save_project(project)
    log_event("SCIENCE", "mingli_hypothesis_evolution", project_id=project_id, hypotheses=len(persisted))
    return json.dumps(run, ensure_ascii=False, indent=2)

def select_gaps_for_hypothesis(project: dict[str, Any], gap_ids: list[str] | None) -> list[dict[str, Any]]:
    gaps = [gap for gap in project.get("knowledge_gaps", []) if isinstance(gap, dict)]
    ready_packages = [
        item for item in project.get("hypothesis_packages", [])
        if isinstance(item, dict)
        and item.get("status") in {"READY_FOR_MINGLI", "READY_FOR_RESTRICTED_MINGLI"}
    ]
    package_primary_ids = {
        str(gap_id)
        for package in ready_packages
        for gap_id in package.get("primary_gap_ids", [])
        if str(gap_id)
    }

    # Filter out gaps without substantive descriptions — they cause MingLi to generate templates
    valid_gaps = []
    sub_hypothesis_evidence = {
        str(item.get("id") or ""): {
            "status": str(item.get("status") or ""),
            "primary_results": int(
                (item.get("retrieval") or {}).get("total_results") or 0
            ) if isinstance(item.get("retrieval"), dict) else 0,
        }
        for item in project.get("sub_hypotheses", [])
        if isinstance(item, dict)
    }
    for gap in gaps:
        desc = str(gap.get("description") or "").strip()
        # Must have at least 20 chars of real content (not just boilerplate)
        sub_hypothesis_id = str(gap.get("sub_hypothesis_id") or "")
        evidence_state = sub_hypothesis_evidence.get(sub_hypothesis_id, {})
        evidence_status = str(evidence_state.get("status") or "")
        component_bridge_candidate = bool(
            gap.get("restricted_component_bridge_hypothesis_allowed") is True
            or gap.get("component_bridge_gap_synthesis_ready") is True
        )
        legacy_preprint_only_alert = (
            evidence_status == "evidence_insufficient_preprint"
            and int(evidence_state.get("primary_results") or 0) > 0
        )
        if legacy_preprint_only_alert:
            gap["preprint_evidence_nonblocking"] = True
            log_event(
                "SCIENCE",
                "mingli_legacy_preprint_alert_nonblocking",
                gap_id=gap.get("gap_id"),
                sub_hypothesis_id=sub_hypothesis_id,
            )
        if (
            sub_hypothesis_id
            and evidence_status
            and evidence_status not in {
                "ready_for_causal_gap_detection",
                "ready_for_component_bridge_gap_synthesis",
            }
            and not legacy_preprint_only_alert
            and not component_bridge_candidate
        ):
            gap["requires_human_review"] = True
            gap["hypothesis_blocked_reason"] = f"sub-hypothesis {sub_hypothesis_id} has evidence status {evidence_status}"
            log_event("WARN", "mingli_subhypothesis_evidence_gate", gap_id=gap.get("gap_id"), sub_hypothesis_id=sub_hypothesis_id, status=evidence_status)
            continue
        if len(desc) >= 20 and not desc.lower().startswith(("none", "null", "n/a", "todo")):
            valid_gaps.append(gap)
        else:
            # Mark incomplete gaps for downstream awareness
            gap["requires_human_review"] = True
            log_event("WARN", "gap_incomplete_description", gap_id=gap.get("gap_id"), desc_len=len(desc))

    if package_primary_ids:
        # A modern project may explore variants of a coherent package, but
        # cannot use an unrelated high-ranked gap just because it has a good
        # novelty score.  Structural roles are read from the package itself;
        # they do not consume this causal-mechanism list.
        valid_gaps = [g for g in valid_gaps if str(g.get("gap_id") or "") in package_primary_ids]
    if gap_ids:
        wanted = set(gap_ids)
        valid_gaps = [g for g in valid_gaps if g.get("gap_id") in wanted]

    # A hypothesis must start from the core evidence corpus, not a landscape
    # extension. This is project-local and therefore works for any science
    # domain; it does not hard-code battery, medical, or physics vocabulary.
    try:
        from ._gap_detection import classify_scientific_gap_track, mechanism_gap_relevance
    except ImportError:
        from _gap_detection import classify_scientific_gap_track, mechanism_gap_relevance
    eligible = []
    for gap in valid_gaps:
        triage = classify_scientific_gap_track(gap)
        gap["gap_track"] = triage["track"]
        package_resolution = hypothesis_package_gate(project, str(gap.get("gap_id") or ""))
        package = package_resolution["package"]
        package_gate = package_resolution["gate"]
        restricted_bridge_ready = bool(
            str(package.get("package_type") or package.get("hypothesis_package_type") or "")
            == "restricted_component_bridge"
            and package_gate.get("ready") is True
            and package_gate.get("status") == "READY_FOR_RESTRICTED_MINGLI"
            and gap.get("restricted_component_bridge_hypothesis_allowed") is True
        )
        if restricted_bridge_ready:
            gap["mechanism_relevance"] = {
                "eligible_for_mechanism_hypothesis": False,
                "eligible_for_restricted_bridge_hypothesis": True,
                "restricted_component_bridge_gap": True,
                "reason": (
                    "Policy-complete component-bridge package may seed only a capped "
                    "first hypothesis, followed by Socrates enrichment before debate."
                ),
            }
            eligible.append(gap)
            continue
        if not triage["eligible_for_hypothesis_generation"]:
            gap["hypothesis_blocked_reason"] = "Secondary research opportunities cannot directly seed a scientific hypothesis."
            continue
        relevance = gap.get("mechanism_relevance") if isinstance(gap.get("mechanism_relevance"), dict) else mechanism_gap_relevance(project, gap)
        gap["mechanism_relevance"] = relevance
        if relevance.get("eligible_for_mechanism_hypothesis"):
            eligible.append(gap)
    if valid_gaps and not eligible:
        log_event("WARN", "no_primary_core_grounded_gaps_for_mingli", total=len(valid_gaps))
    if not valid_gaps and gaps:
        log_event("WARN", "no_valid_gaps_after_filter", total=len(gaps), valid=0)

    return sorted(
        eligible,
        key=lambda gap: (
            -float((gap.get("mechanism_relevance") or {}).get("score") or 0.0),
            -float(gap.get("exploration_value_score") or 0.0),
            -int(gap.get("novelty_score") or 0),
            str(gap.get("gap_id", "")),
        ),
    )[:3]


def ensure_restricted_component_bridge_hypothesis_packages(
    project: dict[str, Any],
    *,
    gap_ids: list[str] | None = None,
) -> list[str]:
    """Materialize the one capped package required by a TanXi bridge handoff.

    Socrates deliberately does not build a direct-core contract for this route.
    The package is therefore created at the MingLi boundary and carries the
    explicit prohibition on final-object/direct-core claims.
    """
    try:
        from ._hypothesis_coverage import build_hypothesis_packages, coverage_and_compatibility_gate
    except ImportError:
        from _hypothesis_coverage import build_hypothesis_packages, coverage_and_compatibility_gate
    wanted = {str(item) for item in (gap_ids or []) if str(item)}
    canonical_gaps = [item for item in project.get("knowledge_gaps", []) if isinstance(item, dict)]
    candidates = [
        item
        for item in canonical_gaps
        if str(item.get("gap_id") or "")
        and (not wanted or str(item.get("gap_id") or "") in wanted)
        and (
            item.get("restricted_component_bridge_hypothesis_allowed") is True
            or item.get("component_bridge_gap_synthesis_ready") is True
        )
        and item.get("restricted_bridge_role_contract_ready") is not False
        and (
            (item.get("hypothesis_readiness") or {}).get("ready_for_hypothesis_generation") is True
            or str((item.get("hypothesis_readiness") or {}).get("status") or "")
            == "READY_FOR_RESTRICTED_BRIDGE_HYPOTHESIS"
        )
    ]
    candidates.sort(
        key=lambda item: (
            -float(item.get("exploration_value_score") or item.get("mechanistic_priority") or 0.0),
            str(item.get("gap_id") or ""),
        )
    )
    if not candidates:
        return []
    anchor = candidates[0]
    anchor_id = str(anchor.get("gap_id") or "")
    current_packages = [item for item in project.get("hypothesis_packages", []) if isinstance(item, dict)]
    for package in current_packages:
        if (
            str(package.get("package_type") or package.get("hypothesis_package_type") or "")
            == "restricted_component_bridge"
            and anchor_id in {str(item) for item in package.get("primary_gap_ids", []) if str(item)}
            and coverage_and_compatibility_gate(package).get("ready") is True
        ):
            return []
    generated = build_hypothesis_packages(project, [anchor], all_gaps=canonical_gaps)
    restricted_packages = [
        item for item in generated
        if isinstance(item, dict)
        and str(item.get("package_type") or item.get("hypothesis_package_type") or "")
        == "restricted_component_bridge"
        and anchor_id in {str(value) for value in item.get("primary_gap_ids", []) if str(value)}
        and coverage_and_compatibility_gate(item).get("ready") is True
    ]
    if not restricted_packages:
        return []
    project["hypothesis_packages"] = [
        package
        for package in current_packages
        if not (
            str(package.get("package_type") or package.get("hypothesis_package_type") or "")
            == "restricted_component_bridge"
            and anchor_id in {str(item) for item in package.get("primary_gap_ids", []) if str(item)}
        )
    ] + restricted_packages
    return [anchor_id]


def final_object_claim_disclaimer(
    gap: dict[str, Any] | None = None,
    hypothesis_package: dict[str, Any] | None = None,
) -> str:
    """Return the mandatory conclusion disclaimer for a bridge-route hypothesis."""
    package = hypothesis_package if isinstance(hypothesis_package, dict) else {}
    source_gap = gap if isinstance(gap, dict) else {}
    restricted = (
        str(package.get("package_type") or package.get("hypothesis_package_type") or "")
        == "restricted_component_bridge"
        or source_gap.get("restricted_component_bridge_hypothesis_allowed") is True
        or source_gap.get("component_bridge_gap_synthesis_ready") is True
        or str(source_gap.get("gap_track") or "") == "COMPONENT_BRIDGE_GAP_SYNTHESIS"
    )
    if not restricted:
        return ""
    return str(
        package.get("final_object_claim_disclaimer")
        or source_gap.get("final_object_claim_disclaimer")
        or "限制声明：该假设仅由组件/桥接证据支持，不得声称最终研究对象已经得到验证。"
    )


def seed_hypothesis_population(project: dict[str, Any], gaps: list[dict[str, Any]], population_size: int, use_llm: bool = False) -> list[dict[str, Any]]:
    seeds: list[dict[str, Any]] = []
    analogies = collect_project_analogies(project)
    hotspots = collect_project_hotspots(project)
    per_gap = max(1, population_size // max(1, len(gaps)))
    for gap in gaps:
        components = infer_gap_components(project, gap)
        intervention_gate = mingli_intervention_type_gate(project, gap, components)
        if not intervention_gate.get("admissible"):
            log_event(
                "SCIENCE",
                "mingli_population_gap_blocked_intervention_ontology",
                gap_id=gap.get("gap_id", ""),
                reason=intervention_gate.get("reason", ""),
            )
            continue
        for variant in range(per_gap):
            analogy = analogies[(len(seeds) + variant) % len(analogies)] if analogies else {}
            hotspot = hotspots[(len(seeds) + variant) % len(hotspots)] if hotspots else {}
            seed = make_hypothesis_seed(project, gap, components, variant, analogy=analogy, hotspot=hotspot)
            package = hypothesis_package_for_gap(project, str(gap.get("gap_id") or ""))
            if package:
                seed["hypothesis_package"] = package
            hierarchy_search = run_hierarchical_hypothesis_search(
                project,
                gap,
                seed,
                hypothesis_package=package,
                # One external-LLM trajectory per gap is enough to obtain
                # proposal diversity; deterministic variants cover the rest
                # without multiplying model cost by population size.
                use_llm=bool(use_llm and variant == 0),
            )
            if hierarchy_search.get("status") != "READY":
                log_event(
                    "SCIENCE",
                    "mingli_hierarchical_seed_rejected",
                    project_id=project.get("project_id", ""),
                    gap_id=gap.get("gap_id", ""),
                    variant=variant,
                    blocked_level=hierarchy_search.get("blocked_level", ""),
                    rejection_count=len(hierarchy_search.get("rejection_feedback", [])),
                )
                continue
            refined = hierarchy_search.get("refined_candidate")
            if not isinstance(refined, dict):
                continue
            seeds.append(refined)
            if len(seeds) >= population_size:
                break
        if len(seeds) >= population_size:
            break
    return score_hypothesis_population(project, seeds)

def infer_gap_components(project: dict[str, Any], gap: dict[str, Any]) -> dict[str, str]:
    try:
        from ._pipeline import project_records_for_mapping
        from ._utils import is_unknown_value, normalize_label
    except ImportError:
        from _pipeline import project_records_for_mapping
        from _utils import is_unknown_value, normalize_label
    description = str(gap.get("description") or "")
    methods = sorted({normalize_label(record.get("method", "")) for record in project_records_for_mapping(project) if not is_unknown_value(record.get("method", ""))})
    scenarios = sorted({normalize_label(record.get("scenario", "")) for record in project_records_for_mapping(project) if not is_unknown_value(record.get("scenario", ""))})
    benchmarks = sorted({normalize_label(record.get("benchmark", "")) for record in project_records_for_mapping(project) if not is_unknown_value(record.get("benchmark", ""))})
    intervention_methods = [
        method for method in methods
        if classify_intervention_candidate(method).get("admissible_as_intervention")
    ]
    method = (
        first_matching_label(description, intervention_methods)
        or (intervention_methods[0] if intervention_methods else "REQUIRES_DIRECT_INTERVENTION_EVIDENCE")
    )
    scenario = first_matching_label(description, scenarios) or (scenarios[0] if scenarios else str(project.get("domain") or "target scenario"))
    benchmark = first_matching_label(description, benchmarks) or (benchmarks[0] if benchmarks else "mechanistic validity")
    benchmark = normalize_hypothesis_benchmark(benchmark, scenario, project)
    return {
        "method": method,
        "scenario": scenario,
        "benchmark": benchmark,
        "excluded_epistemic_methods": ", ".join(
            candidate for candidate in methods
            if classify_intervention_candidate(candidate).get("category") == "epistemic_method"
        ),
    }

def normalize_hypothesis_benchmark(benchmark: str, scenario: str, project: dict[str, Any]) -> str:
    try:
        from ._literature_import import is_generic_phrase
        from ._utils import normalize_space
    except ImportError:
        from _literature_import import is_generic_phrase
        from _utils import normalize_space
    clean = normalize_space(benchmark).lower()
    generic = {
        "benchmark",
        "benchmark data",
        "benchmark dataset",
        "dataset",
        "validation dataset",
        "evaluation metric",
        "performance metric",
        "primary benchmark",
        "mechanistic validity",
    }
    if clean not in generic and not is_generic_phrase(clean):
        return benchmark
    text = normalize_space(f"{scenario} {project.get('domain', '')} {project.get('objective', '')}").lower()
    if any(term in text for term in ("reaction", "chemical", "molecular", "catalyst", "synthesis", "ligat", "cycloaddition")):
        return "reaction yield, rate constant, selectivity, stability, and functional outcome"
    if any(term in text for term in ("image", "imaging", "microscopy", "spectroscopy", "sensor")):
        return "signal-to-noise ratio, resolution, specificity, and measurement reproducibility"
    if any(term in text for term in ("protein", "cell", "gene", "clinical", "patient", "disease", "organism")):
        return "target specificity, biological response, safety margin, and reproducibility"
    if any(term in text for term in ("material", "device", "battery", "polymer", "semiconductor", "alloy")):
        return "stability, efficiency, transport, durability, and failure-mode metrics"
    if any(term in text for term in ("climate", "ecology", "environment", "geology", "agriculture")):
        return "forecast skill, process attribution, robustness across regimes, and uncertainty calibration"
    if any(term in text for term in ("algorithm", "model", "ai", "simulation", "control", "robot", "grid")):
        return "predictive accuracy, robustness, constraint satisfaction, calibration, and deployment cost"
    return "scenario-specific measurable outcome, uncertainty, robustness, and failure-mode metrics"

def first_matching_label(text: str, labels: list[str]) -> str:
    lowered = text.lower()
    for label in labels:
        if label and label.lower() in lowered:
            return label
    return ""

def specific_mechanism_text(
    project: dict[str, Any],
    method: str,
    scenario: str,
    benchmark: str,
    gap: dict[str, Any],
    semantic_gate: dict[str, Any],
) -> str:
    capability = method_capability_description(method)
    target = scenario_target_description(scenario, project)
    bridge = semantic_gate.get("bridge_terms", []) if isinstance(semantic_gate.get("bridge_terms"), list) else []
    requirements = semantic_gate.get("requirements", []) if isinstance(semantic_gate.get("requirements"), list) else []
    affordances = semantic_gate.get("scenario_affordances", []) if isinstance(semantic_gate.get("scenario_affordances"), list) else []
    bridge_text = (
        f"The required bridge is {', '.join(str(item) for item in bridge[:4])}."
        if bridge
        else "No explicit bridge concept is currently visible; this must be treated as a human-review assumption rather than a validated mechanism."
    )
    requirement_text = (
        f"The method requires {', '.join(str(item) for item in requirements)}, while the scenario exposes {', '.join(str(item) for item in affordances) or 'no explicit matching data modality'}."
        if requirements
        else "The method's input requirements are broad or not clearly specified; the experiment must make them explicit."
    )
    return (
        f"Concrete mechanism chain: (1) method capability: {method} contributes through {capability}; "
        f"(2) scenario target: in {scenario}, the affected process is {target}; "
        f"(3) measurable consequence: the bridge must produce a preregistered change in {benchmark}. "
        f"{requirement_text} {bridge_text} "
        f"The decisive prediction is that this concrete bridge, not a generic representation change, will alter {benchmark}; "
        f"if the bridge data or causal link is absent, the hypothesis should fail rather than be reinterpreted post hoc."
    )

def method_capability_description(method: str) -> str:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    text = normalize_space(method).lower()
    if any(term in text for term in ("cycloaddition", "ligation", "click", "reaction", "synthesis", "conjugation")):
        return "forming or transforming molecular bonds with measurable kinetics, selectivity, compatibility, and product stability"
    if any(term in text for term in ("printing", "bioprint", "fabrication", "manufacturing", "assembly")):
        return "controlling spatial organization, material architecture, and process-structure-property relationships"
    if any(term in text for term in ("spectroscopy", "microscopy", "imaging", "sensor", "assay")):
        return "turning a latent physical, chemical, or biological state into a calibrated observable signal"
    if any(term in text for term in ("kernel density", "kde", "arcgis", "gis")):
        return "estimating spatial density over coordinate-indexed observations"
    if any(term in text for term in ("single-cell", "scrna", "transcript", "omics")):
        return "resolving cell-state or molecular-expression heterogeneity across samples"
    if any(term in text for term in ("graph neural", "gnn", "knowledge graph", "network")):
        return "propagating evidence across explicitly defined nodes and relationships"
    if any(term in text for term in ("causal", "counterfactual", "intervention")):
        return "separating candidate causes from correlational associations under stated assumptions"
    if any(term in text for term in ("simulation", "model", "digital twin")):
        return "testing mechanistic predictions under controlled parameter variations"
    if any(term in text for term in ("deep learning", "machine learning", "classification", "prediction")):
        return "learning predictive structure from measurable input features"
    return "a specified operation that must be mapped to observable inputs and outputs before validation"

def scenario_target_description(scenario: str, project: dict[str, Any]) -> str:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    text = normalize_space(f"{scenario} {project.get('domain', '')} {project.get('objective', '')}").lower()
    if any(term in text for term in ("protein", "cell", "gene", "cancer", "clinical", "patient")):
        return "a measurable biological or clinical mechanism such as expression, pathway activation, response, adverse effect, or persistence"
    if any(term in text for term in ("material", "battery", "catalyst", "chemical", "reaction")):
        return "a measurable material, molecular, or reaction mechanism under controlled conditions"
    if any(term in text for term in ("climate", "ecology", "drought", "environment")):
        return "a measurable environmental process, spatial pattern, temporal regime, or ecosystem response"
    if any(term in text for term in ("grid", "control", "power", "robot", "engineering")):
        return "a controllable system state, stability margin, safety constraint, or operational performance metric"
    return "the scenario-specific measurable process named by the project evidence"


def socrates_contract_for_gap(project: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    """Load the most recent evidence contract produced for this TanXi gap."""
    contracts = project.get("socrates_mechanism_contracts", {})
    if not isinstance(contracts, dict):
        return {}
    contract = contracts.get(str(gap.get("gap_id") or ""))
    return dict(contract) if isinstance(contract, dict) else {}


def hypothesis_package_for_gap(project: dict[str, Any], gap_id: str) -> dict[str, Any]:
    """Resolve the persisted, compatibility-audited package for a gap.

    Direct API users may still generate a hypothesis from legacy projects that
    predate packages.  Once a project has packages, however, a gap inside an
    incomplete package cannot bypass its coverage gate by calling MingLi
    directly.
    """
    try:
        from ._hypothesis_coverage import package_for_gap
    except ImportError:
        from _hypothesis_coverage import package_for_gap
    return package_for_gap(project, str(gap_id or ""))


def hypothesis_package_gate(project: dict[str, Any], gap_id: str) -> dict[str, Any]:
    """Resolve and evaluate the single Package gate MingLi must honor."""
    try:
        from ._hypothesis_coverage import coverage_and_compatibility_gate
    except ImportError:
        from _hypothesis_coverage import coverage_and_compatibility_gate
    package = hypothesis_package_for_gap(project, gap_id)
    gate = coverage_and_compatibility_gate(package) if package else {
        "status": "NO_PACKAGE",
        "ready": False,
        "reasons": ["No HypothesisPackage contains this gap."],
    }
    return {"package": package, "gate": gate}


def hypothesis_source_lineage_for_gap(
    project: dict[str, Any],
    gap: dict[str, Any],
    package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the source-text lineage MingLi should preserve in its idea JSON."""
    source_package = package if isinstance(package, dict) else hypothesis_package_for_gap(
        project,
        str(gap.get("gap_id") or ""),
    )
    if isinstance(source_package, dict):
        lineage = source_package.get("hypothesis_source_lineage")
        if isinstance(lineage, dict) and lineage:
            return lineage
    bundle = gap.get("mechanism_evidence_bundle") if isinstance(gap.get("mechanism_evidence_bundle"), dict) else {}
    slot_lineage = bundle.get("slot_source_lineage") if isinstance(bundle.get("slot_source_lineage"), dict) else {}
    accepted = [
        item for item in bundle.get("accepted_source_text_handoffs", [])
        if isinstance(item, dict)
    ]
    if slot_lineage or accepted:
        return {
            "schema_version": "hypothesis_source_lineage_v1",
            "status": "SOURCE_TEXT_LINEAGE_AVAILABLE" if slot_lineage else "SOURCE_TEXT_HANDOFFS_AVAILABLE",
            "required_slots": ["input", "mechanism", "outcome", "measurement"],
            "missing_slots": [],
            "slots": dict(slot_lineage),
            "accepted_source_text_handoffs": accepted,
            "source_gap_ids": [str(gap.get("gap_id") or "")],
        }
    return {
        "schema_version": "hypothesis_source_lineage_v1",
        "status": "SOURCE_TEXT_LINEAGE_MISSING",
        "required_slots": ["input", "mechanism", "outcome", "measurement"],
        "missing_slots": ["input", "mechanism", "outcome", "measurement"],
        "slots": {},
        "source_gap_ids": [str(gap.get("gap_id") or "")],
    }


def validate_mingli_gap_handoff(project: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    """Require one project-bound, *gap-scoped* Socrates handoff.

    The project-wide ``artifact_versions.gaps`` value is intentionally not a
    validity gate: it advances when Socrates writes an unrelated gap contract.
    The handoff instead binds to the scientific snapshot and revision of the
    exact gap that MingLi is about to use.
    """
    try:
        from ._science_state import science_gap_handoff_snapshot, science_gap_snapshot_hash
    except ImportError:
        from _science_state import science_gap_handoff_snapshot, science_gap_snapshot_hash
    project_id = str(project.get("project_id") or "")
    gap_id = str(gap.get("gap_id") or "")
    gap_project_id = str(gap.get("project_id") or project_id)
    if gap_project_id != project_id:
        raise ValueError(
            f"Cross-project gap reference rejected: project={project_id}, gap_project={gap_project_id}, gap_id={gap_id}"
        )
    package_resolution = hypothesis_package_gate(project, gap_id)
    restricted_package = (
        package_resolution.get("package")
        if isinstance(package_resolution.get("package"), dict)
        else {}
    )
    restricted_gate = (
        package_resolution.get("gate")
        if isinstance(package_resolution.get("gate"), dict)
        else {}
    )
    if str(restricted_package.get("package_type") or restricted_package.get("hypothesis_package_type") or "") == "restricted_component_bridge":
        canonical_gap = next(
            (
                item for item in project.get("knowledge_gaps", [])
                if isinstance(item, dict) and str(item.get("gap_id") or "") == gap_id
            ),
            None,
        )
        if not isinstance(canonical_gap, dict):
            raise ValueError(f"Unknown gap_id for project {project_id}: {gap_id}")
        if not (
            restricted_gate.get("ready") is True
            and restricted_gate.get("status") == "READY_FOR_RESTRICTED_MINGLI"
            and restricted_package.get("may_support_final_object_claim") is not True
            and str(restricted_package.get("claim_strength_cap") or "") == "no_final_object_claim_validation"
            and restricted_package.get("post_draft_socrates_enrichment_required") is True
            and (
                canonical_gap.get("restricted_component_bridge_hypothesis_allowed") is True
                or canonical_gap.get("component_bridge_gap_synthesis_ready") is True
            )
        ):
            raise ValueError(
                f"Restricted component-bridge MingLi handoff is not policy-complete for project {project_id}, gap {gap_id}."
            )
        return {
            "schema_version": "mingli_gap_handoff.v1",
            "handoff_type": "restricted_component_bridge",
            "project_id": project_id,
            "gap_id": gap_id,
            "hypothesis_package_id": restricted_package.get("hypothesis_package_id"),
            "package_type": "restricted_component_bridge",
            "status": "READY_FOR_RESTRICTED_BRIDGE_HYPOTHESIS",
            "claim_strength_cap": "no_final_object_claim_validation",
            "post_draft_socrates_enrichment_required": True,
            "final_object_claim_disclaimer": final_object_claim_disclaimer(canonical_gap, restricted_package),
            "may_support_final_object_claim": False,
            "reason": "Component-bridge gap is admitted for a first MingLi draft, followed by Socrates enrichment before debate.",
        }
    contract = socrates_contract_for_gap(project, gap)
    if not contract:
        raise ValueError(
            f"MingLi requires READY_FOR_HYPOTHESIS Socrates contract for project {project_id}, gap {gap_id}."
        )
    readiness = contract.get("hypothesis_readiness") if isinstance(contract.get("hypothesis_readiness"), dict) else {}
    status = str(contract.get("contract_status") or readiness.get("contract_status") or "")
    required = readiness.get("required") if isinstance(readiness.get("required"), dict) else {}
    scientific_gate = (
        readiness.get("scientific_readiness_gate")
        if isinstance(readiness.get("scientific_readiness_gate"), dict)
        else contract.get("scientific_readiness_gate")
        if isinstance(contract.get("scientific_readiness_gate"), dict)
        else {}
    )
    if not (
        status == "READY_FOR_HYPOTHESIS"
        and readiness.get("ready_for_hypothesis_generation") is True
        and scientific_gate.get("state") == "READY"
        and isinstance(readiness.get("mode_contract"), dict)
        and readiness["mode_contract"].get("status") == "READY"
        and all(
            required.get(name) is True
            for name in (
                "research_mode_contract",
                "causal_variable",
                "measurement",
                "falsification",
                "comparison",
                "minimal_falsification",
                "same_project_snapshot_and_subhypothesis",
                "project_topic_alignment",
                "published_theory_or_mechanism_framework",
                "published_mode_appropriate_direct_evidence",
            )
        )
        and (
            str(readiness.get("research_mode") or "") != "CONTROLLED_INTERVENTION"
            or (
                required.get("intervention") is True
                and required.get("published_direct_experiment") is True
            )
        )
    ):
        raise ValueError(
            f"Socrates contract is not READY_FOR_HYPOTHESIS for project {project_id}, gap {gap_id}; status={status or 'missing'}"
        )
    handoff = contract.get("gap_handoff") if isinstance(contract.get("gap_handoff"), dict) else {}
    if str(handoff.get("project_id") or "") != project_id or str(handoff.get("gap_id") or "") != gap_id:
        raise ValueError(f"Invalid Socrates gap handoff identity for project {project_id}, gap {gap_id}.")

    expected_store_id = str(handoff.get("state_store_id") or "")
    current_store_id = str(project.get("state_store_id") or "")
    if expected_store_id and expected_store_id != current_store_id:
        raise ValueError(
            f"stale science state for gap {gap_id}: expected state store {expected_store_id}, current {current_store_id}"
        )

    canonical_gap = next(
        (
            item for item in project.get("knowledge_gaps", [])
            if isinstance(item, dict) and str(item.get("gap_id") or "") == gap_id
        ),
        None,
    )
    if not isinstance(canonical_gap, dict):
        raise ValueError(f"Unknown gap_id for project {project_id}: {gap_id}")

    expected_hash = str(handoff.get("gap_snapshot_hash") or "")
    current_hash = str(canonical_gap.get("gap_snapshot_hash") or science_gap_snapshot_hash(canonical_gap))
    if expected_hash:
        expected_revision = int(handoff.get("gap_revision") or 0)
        current_revision = int(canonical_gap.get("gap_revision") or 0)
        if expected_hash != current_hash or (expected_revision and expected_revision != current_revision):
            raise ValueError(
                f"stale science state for gap {gap_id}: expected gap revision/hash "
                f"{expected_revision}/{expected_hash[:12]}, current {current_revision}/{current_hash[:12]}"
            )
        return handoff

    # Safe migration path for contracts written before gap-local revisions.
    # The old global artifact counter is too coarse, but its persisted core
    # snapshot still lets us prove that the exact gap has not changed.
    expected_snapshot = handoff.get("gap_snapshot") if isinstance(handoff.get("gap_snapshot"), dict) else {}
    current_snapshot = science_gap_handoff_snapshot(canonical_gap)
    if json.dumps(expected_snapshot, ensure_ascii=False, sort_keys=True) != json.dumps(
        current_snapshot, ensure_ascii=False, sort_keys=True
    ):
        raise ValueError(
            f"stale science state for gap {gap_id}: legacy gap snapshot no longer matches the current scientific object"
        )
    return handoff


def socrates_contract_summary(contract: dict[str, Any]) -> str:
    """Render source-cited Socrates excerpts without promoting them to fact."""
    evidence = contract.get("evidence", {}) if isinstance(contract.get("evidence"), dict) else {}
    parts: list[str] = []
    for field in ("identity", "location_or_scope", "dynamics", "reversibility", "observability", "intervention", "counterfactual"):
        entries = evidence.get(field, [])
        if not isinstance(entries, list) or not entries:
            continue
        first = entries[0] if isinstance(entries[0], dict) else {}
        excerpt = str(first.get("excerpt") or "").strip()
        citation = str(first.get("citation") or "").strip()
        if excerpt and citation:
            parts.append(f"{field}: {excerpt} [{citation}]")
    return " ".join(parts[:3])


def _mingli_slot_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("value", "normalized_value", "candidate", "text", "label", "name"):
            text = _mingli_slot_text(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, (list, tuple, set)):
        return "; ".join(text for text in (_mingli_slot_text(item) for item in value) if text)
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"unresolved", "unknown", "none", "n/a", "generic_placeholder"}:
        return ""
    if lowered.startswith("requires_") or lowered.startswith("requires-"):
        return ""
    if "fragment_refs" in lowered and ("'value': ''" in lowered or '"value": ""' in lowered):
        return ""
    return text


def mingli_intervention_type_gate(
    project: dict[str, Any],
    gap: dict[str, Any],
    components: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve a concrete intervention without promoting epistemic methods.

    Candidate order is intentionally evidence-first: a validated Socrates
    intervention outranks a sub-hypothesis variable, which outranks explicitly
    extracted operating conditions. PaperGraph ``method`` labels are used only
    when they themselves describe a direct operation.
    """
    components = components or infer_gap_components(project, gap)
    package = hypothesis_package_for_gap(project, str(gap.get("gap_id") or ""))
    if str(package.get("package_type") or package.get("hypothesis_package_type") or "") == "restricted_component_bridge":
        slots = package.get("slots") if isinstance(package.get("slots"), dict) else {}
        sub_hypothesis = subhypothesis_for_gap(project, gap)
        slot_audit = (
            package.get("restricted_component_bridge_slot_audit")
            if isinstance(package.get("restricted_component_bridge_slot_audit"), dict)
            else {}
        )
        missing_slots = [
            role
            for role in ("input", "mechanism", "outcome", "comparison")
            if not _mingli_slot_text(slots.get(role))
        ]
        if slot_audit.get("ready") is False:
            missing_slots = list(slot_audit.get("missing_roles") or missing_slots)
        design_condition = _mingli_slot_text(
            slots.get("input")
            or sub_hypothesis.get("independent_variable")
            or components.get("method")
        )
        if missing_slots or not design_condition:
            return {
                "verdict": "FAIL",
                "admissible": False,
                "selected_intervention": design_condition,
                "selected_assessment": {
                    "candidate": design_condition,
                    "category": "restricted_component_bridge_followup_design",
                    "ontology_level": "bridge_hypothesis_followup",
                    "admissible_as_intervention": False,
                },
                "assessments": [],
                "research_mode": "RESTRICTED_COMPONENT_BRIDGE_FOLLOWUP",
                "reason": (
                    "Restricted component-bridge MingLi requires materialized "
                    "input/mechanism/outcome/comparison slots before drafting."
                ),
                "missing_slots": missing_slots,
                "excluded_epistemic_methods": [],
                "claim_strength_cap": "no_final_object_claim_validation",
                "post_draft_socrates_enrichment_required": True,
                "final_object_claim_disclaimer": final_object_claim_disclaimer(gap, package),
            }
        return {
            "verdict": "PASS",
            "admissible": True,
            "selected_intervention": design_condition,
            "selected_assessment": {
                "candidate": design_condition,
                "category": "restricted_component_bridge_followup_design",
                "ontology_level": "bridge_hypothesis_followup",
                "admissible_as_intervention": True,
            },
            "assessments": [],
            "research_mode": "RESTRICTED_COMPONENT_BRIDGE_FOLLOWUP",
            "reason": (
                "This package is a component-bridge follow-up. Socrates enriches the first draft before debate; "
                "the final conclusion carries a no-final-object-validation disclaimer."
            ),
            "excluded_epistemic_methods": [],
            "claim_strength_cap": "no_final_object_claim_validation",
            "post_draft_socrates_enrichment_required": True,
            "final_object_claim_disclaimer": final_object_claim_disclaimer(gap, package),
        }
    contract = socrates_contract_for_gap(project, gap)
    readiness = contract.get("hypothesis_readiness") if isinstance(contract.get("hypothesis_readiness"), dict) else {}
    mode_contract = readiness.get("mode_contract") if isinstance(readiness.get("mode_contract"), dict) else {}
    research_mode = str(readiness.get("research_mode") or mode_contract.get("mode") or "CONTROLLED_INTERVENTION")
    if research_mode not in {"CONTROLLED_INTERVENTION", "COMPUTATIONAL_INTERVENTION"}:
        normalized = readiness.get("normalized_core_chain") if isinstance(readiness.get("normalized_core_chain"), dict) else {}
        bundle = gap.get("mechanism_evidence_bundle") if isinstance(gap.get("mechanism_evidence_bundle"), dict) else {}
        design_condition = str(
            normalized.get("input_or_intervention")
            or bundle.get("intervention")
            or contract.get("input")
            or contract.get("assumptions")
            or ""
        ).strip()
        admissible = bool(design_condition and mode_contract.get("status") == "READY")
        return {
            "verdict": "PASS" if admissible else "FAIL",
            "admissible": admissible,
            "selected_intervention": design_condition,
            "selected_assessment": {
                "candidate": design_condition,
                "category": "mode_specific_design_condition",
                "ontology_level": "research_design",
                "admissible_as_intervention": admissible,
            },
            "assessments": [],
            "research_mode": research_mode,
            "reason": (
                "The Socrates-approved research mode supplies a concrete premise, exposure, observation plan, or measurement configuration."
                if admissible else "The non-interventional research mode lacks an approved, concrete design condition."
            ),
            "excluded_epistemic_methods": [],
        }
    evidence = contract.get("evidence") if isinstance(contract.get("evidence"), dict) else {}
    ledger = contract.get("evidence_ledger") if isinstance(contract.get("evidence_ledger"), dict) else {}
    intervention_ledger = ledger.get("intervention") if isinstance(ledger.get("intervention"), dict) else {}
    candidates: list[dict[str, Any] | str] = []
    for entry in evidence.get("intervention", []) if isinstance(evidence.get("intervention"), list) else []:
        if isinstance(entry, dict):
            candidates.append({
                **entry,
                "candidate": entry.get("excerpt"),
                "evidence_grade": entry.get("evidence_grade") or intervention_ledger.get("evidence_grade"),
                "candidate_source": "socrates.evidence.intervention",
            })
    causal_plan = contract.get("causal_inference_plan") if isinstance(contract.get("causal_inference_plan"), dict) else {}
    prior_gate = causal_plan.get("intervention_type_gate") if isinstance(causal_plan.get("intervention_type_gate"), dict) else {}
    if prior_gate.get("admissible") and prior_gate.get("selected_intervention"):
        candidates.append({
            "candidate": prior_gate.get("selected_intervention"),
            "candidate_source": "socrates.causal_inference_plan",
        })
    sub_hypothesis = subhypothesis_for_gap(project, gap)
    if sub_hypothesis.get("independent_variable"):
        candidates.append({
            "candidate": sub_hypothesis.get("independent_variable"),
            "candidate_source": "sub_hypothesis.independent_variable",
        })
    ingredients = gap.get("hypothesis_ingredients") if isinstance(gap.get("hypothesis_ingredients"), dict) else {}
    for key in ("interventions", "operating_conditions", "numerical_bounds"):
        for value in ingredients.get(key, []) if isinstance(ingredients.get(key), list) else []:
            candidates.append({"candidate": value, "candidate_source": f"hypothesis_ingredients.{key}"})
    candidates.append({"candidate": components.get("method"), "candidate_source": "operational_method"})
    gate = intervention_gate_from_values(candidates)
    gate["excluded_epistemic_methods"] = [
        assessment.get("candidate")
        for assessment in gate.get("assessments", [])
        if assessment.get("category") == "epistemic_method"
    ]
    gate["research_mode"] = research_mode
    return gate


def subhypothesis_for_gap(project: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    target_id = str(gap.get("sub_hypothesis_id") or "")
    if not target_id:
        return {}
    for item in project.get("sub_hypotheses", []):
        if isinstance(item, dict) and str(item.get("id") or "") == target_id:
            return item
    return {}


def causal_counterfactual_experiments(
    gap: dict[str, Any],
    sub_hypothesis: dict[str, Any],
    *,
    variable: str,
    outcome: str,
) -> list[dict[str, Any]]:
    causal_chain = sub_hypothesis.get("causal_chain", []) if isinstance(sub_hypothesis.get("causal_chain"), list) else []
    mediator = str(causal_chain[1] if len(causal_chain) > 2 else causal_chain[0] if causal_chain else gap.get("causal_gap", {}).get("missing_kind") or "the proposed mediator")
    focus = str(sub_hypothesis.get("focus") or gap.get("description") or "the proposed mechanism")
    return [
        {
            "experiment_id": f"cf_{str(gap.get('gap_id') or 'candidate')[:16]}",
            "question": f"Does changing {variable} alter {outcome} through {mediator}, rather than only correlating with it?",
            "design": f"Compare matched control and intervention conditions that vary {variable} while measuring {mediator} and {outcome}; include a negative control that leaves {variable} unchanged.",
            "predicted_outcome_if_mechanism_true": f"The intervention changes {mediator} before or together with a reproducible directional change in {outcome}.",
            "predicted_outcome_if_mechanism_false": f"{outcome} does not change systematically when {variable} is varied, or it changes without the predicted mediator response.",
            "observability": outcome,
            "intervention": variable,
            "source_boundary": f"Proposal generated for {focus}; concrete instruments and thresholds require source-backed evidence.",
        }
    ]


def causal_mechanism_competition(
    gap: dict[str, Any],
    sub_hypothesis: dict[str, Any],
    *,
    variable: str,
    outcome: str,
) -> dict[str, Any]:
    causal_chain = sub_hypothesis.get("causal_chain", []) if isinstance(sub_hypothesis.get("causal_chain"), list) else []
    primary = " → ".join(str(item) for item in causal_chain if str(item).strip()) or str(gap.get("description") or "primary causal chain")
    alternatives = [str(item) for item in sub_hypothesis.get("alternative_mechanisms", []) if str(item).strip()]
    return {
        "phenomenon": outcome,
        "candidates": [{"id": "M1", "mechanism": primary, "prediction": f"Varying {variable} changes the named mediator before {outcome}."}]
        + [
            {"id": f"M{index + 2}", "mechanism": alternative, "prediction": "Produces the outcome without the primary mediator pattern."}
            for index, alternative in enumerate(alternatives[:3])
        ],
        "discriminating_experiment": f"Use matched interventions and measurements that separately observe the primary mediator and {outcome}; compare their ordering and effect sizes across controls.",
        "decision_rule": "Favor the mechanism whose preregistered mediator and outcome pattern is observed; retain multiple mechanisms when effects are non-additive or no discriminator is decisive.",
    }


def build_project_theory_blueprint(project: dict[str, Any]) -> dict[str, Any]:
    """Create an auditable, domain-neutral causal prior from project evidence."""
    try:
        from ._gap_detection import canonical_causal_node_key
    except ImportError:
        from _gap_detection import canonical_causal_node_key
    existing = project.get("mechanism_blueprint") if isinstance(project.get("mechanism_blueprint"), dict) else {}
    graph = project.get("causal_evidence_graph", {}) if isinstance(project.get("causal_evidence_graph"), dict) else {}
    nodes = [item for item in graph.get("nodes", []) if isinstance(item, dict)]
    node_by_id = {str(item.get("id") or ""): item for item in nodes}
    blueprint_nodes: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()
    for node in nodes:
        label = str(node.get("label") or "").strip()
        key = canonical_causal_node_key(label)
        if not label or not key or key in seen_nodes:
            continue
        seen_nodes.add(key)
        blueprint_nodes.append(
            {
                "id": key,
                "label": label,
                "roles": list(node.get("types") or []),
                "status": "SUPPORTED" if node.get("supporting_references") else "INFERRED",
                "sources": list(node.get("supporting_references") or [])[:6],
            }
        )
    blueprint_edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str]] = set()
    for edge in graph.get("edges", []) if isinstance(graph.get("edges"), list) else []:
        if not isinstance(edge, dict) or str(edge.get("relation") or "") in {"observed_by", "intervenes_on"}:
            continue
        source = node_by_id.get(str(edge.get("source") or ""), {})
        target = node_by_id.get(str(edge.get("target") or ""), {})
        source_key = canonical_causal_node_key(str(source.get("label") or ""))
        target_key = canonical_causal_node_key(str(target.get("label") or ""))
        if not source_key or not target_key or (source_key, target_key) in seen_edges:
            continue
        seen_edges.add((source_key, target_key))
        has_direct_source = bool(str(edge.get("citation") or "") and str(edge.get("evidence_excerpt") or ""))
        blueprint_edges.append(
            {
                "source": source_key,
                "target": target_key,
                "relation": str(edge.get("relation") or "leads_to"),
                "status": "SUPPORTED" if has_direct_source else "INFERRED",
                "evidence_grade": "B" if has_direct_source else "C",
                "sources": [str(edge.get("citation") or "")] if str(edge.get("citation") or "") else [],
                "context": dict(edge.get("context") or {}) if isinstance(edge.get("context"), dict) else {},
            }
        )
    prior_edges = existing.get("theory_priors") if isinstance(existing.get("theory_priors"), list) else []
    if not prior_edges and isinstance(project.get("theory_priors"), list):
        prior_edges = project["theory_priors"]
    return {
        "version": "mechanism_blueprint_v1",
        "domain": str(project.get("domain") or ""),
        "status": "initial_prior_updated_by_project_evidence",
        "nodes": blueprint_nodes[:80],
        "edges": blueprint_edges[:120],
        "theory_priors": [item for item in prior_edges if isinstance(item, dict)][:40],
        "update_policy": {
            "support": "Directly supports an existing edge in the stated context.",
            "refine": "Adds context, direction, time/order, magnitude, or mediator to an existing edge.",
            "challenge": "Supplies a counterexample, contradiction, or applicability boundary.",
            "extend": "Adds a new node or relation as an explicit prior pending evidence.",
        },
    }


def classify_blueprint_evidence_action(blueprint: dict[str, Any], record: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        from ._gap_detection import canonical_causal_node_key
    except ImportError:
        from _gap_detection import canonical_causal_node_key
    actions: list[dict[str, Any]] = []
    known_pairs = {(str(edge.get("source") or ""), str(edge.get("target") or "")) for edge in blueprint.get("edges", []) if isinstance(edge, dict)}
    citation = str(record.get("citation") or record.get("title") or "")
    for chain in record.get("causal_chains", []) if isinstance(record.get("causal_chains"), list) else []:
        if not isinstance(chain, dict):
            continue
        values = [str(chain.get("trigger") or "")]
        values.extend(str(step.get("claim") or step.get("text") or "") if isinstance(step, dict) else str(step) for step in chain.get("steps", []) if str(step))
        values.append(str(chain.get("outcome") or ""))
        keys = [canonical_causal_node_key(value) for value in values if canonical_causal_node_key(value)]
        for source, target in zip(keys, keys[1:]):
            action = "support" if (source, target) in known_pairs else "extend"
            text = " ".join(str(chain.get(key) or "") for key in ("trigger_evidence", "outcome_evidence")) + " " + str(record.get("limitation") or "")
            if any(marker in text.lower() for marker in ("contradict", "not causal", "fails", "inconsistent", "boundary")):
                action = "challenge"
            elif action == "support" and any(marker in text.lower() for marker in ("time", "stage", "condition", "dose", "temperature", "scale")):
                action = "refine"
            actions.append({"action": action, "source": source, "target": target, "citation": citation})
    return actions[:12]


def hypothesis_mechanism_edges(
    contract: dict[str, Any],
    variable: str,
    outcome: str,
) -> list[dict[str, Any]]:
    mediator = str(contract.get("proposed_mediator") or "the proposed mediator")
    ledger = contract.get("evidence_ledger") if isinstance(contract.get("evidence_ledger"), dict) else {}
    identity = ledger.get("identity") if isinstance(ledger.get("identity"), dict) else {}
    downstream = ledger.get("dynamics") if isinstance(ledger.get("dynamics"), dict) else {}
    return [
        {
            "source": variable,
            "relation": "acts_through",
            "target": mediator,
            "status": str(identity.get("status") or "SPECULATIVE"),
            "evidence_grade": str(identity.get("evidence_grade") or "D"),
            "sources": list(identity.get("sources") or []),
        },
        {
            "source": mediator,
            "relation": "changes",
            "target": outcome,
            "status": str(downstream.get("status") or "INFERRED"),
            "evidence_grade": str(downstream.get("evidence_grade") or "C"),
            "sources": list(downstream.get("sources") or []),
        },
    ]

def make_hypothesis_seed(
    project: dict[str, Any],
    gap: dict[str, Any],
    components: dict[str, str],
    variant: int,
    *,
    analogy: dict[str, Any],
    hotspot: dict[str, Any],
) -> dict[str, Any]:
    try:
        from ._gap_detection import semantic_plausibility_for_pair
        from ._utils import new_id
    except ImportError:
        from _gap_detection import semantic_plausibility_for_pair
        from _utils import new_id
    method = components["method"]
    scenario = components["scenario"]
    benchmark = components["benchmark"]
    conditions = [
        "under explicit failure-mode stress tests",
        "in a longitudinal or temporally stratified validation setting",
        "with ablation against the nearest dense PaperGraph neighborhood",
        "under cross-cohort or cross-material generalization",
    ]
    condition = conditions[variant % len(conditions)]
    transferred = ""
    # A distant analogy may inspire a mechanism only when its proposed method
    # is already inside this project's core entity boundary.  Otherwise it is a
    # prompt-level metaphor, not admissible scientific input.
    if analogy.get("candidate_methods_to_transfer"):
        candidate_transfer = str(analogy["candidate_methods_to_transfer"][0])
        if is_core_mechanism_entity(project, candidate_transfer):
            transferred = candidate_transfer
            method = transferred
    if hotspot.get("concept") and variant % 2 == 1:
        condition = f"while tracking emerging hotspot '{hotspot.get('concept')}'"
    semantic_gate = semantic_plausibility_for_pair(project, method, scenario, gap)
    socrates_contract = socrates_contract_for_gap(project, gap)
    socrates_evidence = socrates_contract_summary(socrates_contract)
    sub_hypothesis = subhypothesis_for_gap(project, gap)
    intervention_gate = mingli_intervention_type_gate(project, gap, components)
    variable = str(intervention_gate.get("selected_intervention") or "REQUIRES_DIRECT_INTERVENTION_EVIDENCE")
    dependent_variables = sub_hypothesis.get("dependent_variables", []) if isinstance(sub_hypothesis.get("dependent_variables"), list) else []
    causal_outcome = ", ".join(str(item) for item in dependent_variables if str(item).strip()) or benchmark
    boundary = str(sub_hypothesis.get("threshold_to_test") or sub_hypothesis.get("quantifiable_bounds") or hypothesis_boundary_condition(gap))
    if str(gap.get("gap_type") or "") == "contradiction":
        statement = (
            f"If the competing claims about {scenario} are evaluated under matched {variable} conditions, "
            f"then {benchmark} will separate which mechanism holds and identify the boundary condition {boundary}."
        )
    else:
        statement = (
            f"If {method} is used to perturb or stratify {variable} in {scenario} {condition}, "
            f"then {causal_outcome} will show a directional or non-monotonic boundary at {boundary}."
        )
    mechanism = specific_mechanism_text(project, method, scenario, benchmark, gap, semantic_gate)
    if socrates_evidence:
        mechanism += f" Socrates retrieved the following field-level source evidence: {socrates_evidence}"
    if analogy:
        mechanism += f" The structural analogy to {analogy.get('analog_source_scenario')} supports transfer because the encoded problem structures are similar."
    causal_chain = sub_hypothesis.get("causal_chain", []) if isinstance(sub_hypothesis.get("causal_chain"), list) else []
    if not causal_chain:
        causal_chain = [
        f"Input/intervention: vary {variable} for {method} in {scenario}",
        (
            f"Mechanism: interpret {method} through the Socrates source-cited mechanism dossier before making a stronger causal claim."
            if socrates_evidence
            else f"Mechanism: {method} must act through {method_capability_description(method)} on {scenario_target_description(scenario, project)}"
        ),
        f"Observable output: measure {causal_outcome} and locate boundary condition {boundary}",
        ]
    counterfactual_experiments = causal_counterfactual_experiments(
        gap,
        sub_hypothesis,
        variable=variable,
        outcome=causal_outcome,
    )
    mechanism_competition = causal_mechanism_competition(
        gap,
        sub_hypothesis,
        variable=variable,
        outcome=causal_outcome,
    )
    candidate_types = (
        "mechanism_completion",
        "competitive_mechanism",
        "theory_challenge",
    )
    candidate_type = candidate_types[variant % len(candidate_types)]
    theory_blueprint = (
        project.get("mechanism_blueprint")
        if isinstance(project.get("mechanism_blueprint"), dict)
        else build_project_theory_blueprint(project)
    )
    mechanism_edges = hypothesis_mechanism_edges(socrates_contract, variable, causal_outcome)
    competition_candidates = (
        mechanism_competition.get("candidates", [])
        if isinstance(mechanism_competition.get("candidates"), list)
        else []
    )
    alternative_mechanisms = [
        str(item.get("mechanism") or "").strip()
        for item in competition_candidates[1:]
        if isinstance(item, dict) and str(item.get("mechanism") or "").strip()
    ]
    competing_explanation = (
        alternative_mechanisms[0]
        if alternative_mechanisms
        else f"The observed {causal_outcome} may arise through an unmeasured common cause or a direct path that does not require the proposed mediator."
    )
    discriminating_prediction = str(
        mechanism_competition.get("discriminating_experiment")
        or f"If the proposed mediator is necessary, changing {variable} should change the mediator before {causal_outcome}, and blocking the mediator should remove that effect."
    )
    falsifier = (
        f"Reject or revise this candidate if changing {variable} does not alter {causal_outcome}, "
        "if the mediator is not temporally prior to the outcome, or if the same outcome persists after the mediator is blocked."
    )
    if candidate_type == "competitive_mechanism":
        statement += f" This candidate explicitly compares the primary pathway against: {competing_explanation}"
    elif candidate_type == "theory_challenge":
        statement += f" This candidate tests whether the proposed relationship changes across the stated boundary: {boundary}."
    else:
        statement += " This candidate tests whether the currently incomplete path is mediated by the proposed mechanism."
    experiment_design = {
        "intervention": f"Systematically vary {variable} using the domain-appropriate implementation of {method}.",
        "control": "Use matched baseline, sham/negative, and mediator-blocked or alternative-mechanism controls where feasible.",
        "replicates": "Use independently prepared experimental units and predefine replication after a domain-appropriate power analysis.",
        "time_course": f"Measure the proposed mediator and {causal_outcome} across an ordered time course appropriate to the system dynamics.",
        "readout": causal_outcome,
        "statistical_test": "Pre-register a model that tests intervention effects, mediator dependence, and the interaction with the boundary condition.",
        "success_criteria": f"The predicted mediator pattern precedes and explains a reproducible change in {causal_outcome} relative to all matched controls.",
        "failure_criteria": falsifier,
    }
    return {
        "candidate_id": new_id("hcand"),
        "gap_id": gap.get("gap_id"),
        "gap_ids": [str(gap.get("gap_id"))] if gap.get("gap_id") else [],
        "candidate_type": candidate_type,
        "statement": statement,
        "mechanism": mechanism,
        "claim": {
            "object": scenario,
            "condition": condition,
            "time_window": "the pre-specified observation window appropriate to the system dynamics",
            "intervention": f"Vary {variable} through {method}",
            "expected_result": f"A discriminable change in {causal_outcome}",
        },
        "causal_chain": causal_chain,
        "mechanism_edges": mechanism_edges,
        "competing_explanation": competing_explanation,
        "discriminating_prediction": discriminating_prediction,
        "boundary": boundary,
        "falsifier": falsifier,
        "experiment_design": experiment_design,
        # A seed is a scientific claim, not a registered protocol.  The
        # execution-level planner is deliberately deferred until this claim
        # survives MingLi's semantic gate and the Socratic debate.
        "experimental_protocol": {},
        "theory_blueprint": theory_blueprint,
        "sub_hypothesis_id": str(sub_hypothesis.get("id") or gap.get("sub_hypothesis_id") or ""),
        "expected_value": gap.get("value_argument") or "Potential to convert a mapped knowledge gap into a testable scientific mechanism.",
        "test_plan": (
            f"Build a minimal benchmark for {scenario}; compare {method} against canonical baselines; measure {benchmark}; "
            "include negative controls, ablations, and failure-mode analysis."
        ),
        "verification_plan": {
            "primary_metric": benchmark,
            "baselines": ["nearest dense PaperGraph method", "domain-standard baseline"],
            "falsification_condition": (
                f"No directional, non-monotonic, or mechanism-separating change in {benchmark} when {variable} crosses {boundary}."
            ),
            "counterfactual_experiments": counterfactual_experiments,
            "mechanism_competition": mechanism_competition,
        },
        "counterfactual_experiments": counterfactual_experiments,
        "mechanism_competition": mechanism_competition,
        "semantic_plausibility": semantic_gate,
        "intervention_type_gate": intervention_gate,
        "socrates_mechanism_contract": socrates_contract,
        "source_gap": gap,
        "lineage": [{"generation": 0, "operation": "seed", "gap_id": gap.get("gap_id"), "analogy_used": analogy.get("analog_source_scenario", "")}],
        "generation": 0,
    }

def score_hypothesis_population(project: dict[str, Any], population: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [score_hypothesis_candidate(project, candidate) for candidate in population]

def score_hypothesis_candidate(project: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._gap_detection import local_idea_overlap
    except ImportError:
        from _gap_detection import local_idea_overlap
    gap = candidate.get("source_gap") if isinstance(candidate.get("source_gap"), dict) else {}
    statement = str(candidate.get("statement") or "")
    local_overlap = local_idea_overlap(project, statement)
    strongest_overlap = float(local_overlap[0]["overlap_score"]) if local_overlap else 0.0
    novelty = max(0.0, min(1.0, (int(gap.get("novelty_score") or 5) / 10.0) * (1.0 - 0.5 * strongest_overlap)))
    plausibility_check = hypothesis_disciplinary_plausibility(project, candidate)
    mechanism_base = 0.65 if candidate.get("mechanism") and len(str(candidate.get("mechanism"))) >= 80 else 0.35
    plausibility = max(0.05, min(1.0, 0.5 * mechanism_base + 0.5 * float(plausibility_check.get("score", 0.5))))
    refs = len(gap.get("supporting_references", [])) if isinstance(gap.get("supporting_references"), list) else 0
    grounding = min(1.0, refs / 3.0)
    intervention_gate = candidate.get("intervention_type_gate") if isinstance(candidate.get("intervention_type_gate"), dict) else {}
    intervention_valid = bool(intervention_gate.get("admissible"))
    hierarchy_present = bool(candidate.get("hierarchical_search") or candidate.get("scientific_hypothesis_hierarchy"))
    hierarchy_audit = audit_hierarchical_candidate(candidate) if hierarchy_present else {
        "verdict": "LEGACY_NOT_PRESENT",
        "hard_gate_passed": True,
    }
    hierarchy_valid = bool(hierarchy_audit.get("hard_gate_passed"))
    has_minimal_test_plan = all(
        term in str(candidate.get("test_plan", "")).lower()
        for term in ("baseline", "measure")
    )
    testability = (
        0.85 if intervention_valid and hierarchy_valid and hierarchy_present and has_minimal_test_plan
        else 0.45 if intervention_valid and hierarchy_valid and hierarchy_present
        else 0.75 if intervention_valid and has_minimal_test_plan
        else 0.35 if intervention_valid
        else 0.0
    )
    impact = min(1.0, (float(gap.get("exploration_value_score") or gap.get("novelty_score") or 5) / 10.0) + 0.1)
    surprise = hypothesis_surprise_score(project, candidate)
    score = round(0.22 * novelty + 0.22 * plausibility + 0.18 * grounding + 0.18 * testability + 0.14 * impact + 0.06 * surprise, 4)
    if not intervention_valid or not hierarchy_valid:
        # Category validity is a hard precondition, not another soft feature
        # that can be outweighed by novelty or fluent mechanism prose.
        score = 0.0
    scored = dict(candidate)
    scored["scores"] = {
        "novelty": round(novelty, 3),
        "plausibility": round(plausibility, 3),
        "grounding": round(grounding, 3),
        "testability": round(testability, 3),
        "impact": round(impact, 3),
        "surprise": round(surprise, 3),
        "strongest_local_overlap": round(strongest_overlap, 3),
        "intervention_ontology": 1.0 if intervention_valid else 0.0,
        "hierarchical_scientific_contract": 1.0 if hierarchy_valid else 0.0,
    }
    scored["eligible_for_hypothesis_generation"] = bool(intervention_valid and hierarchy_valid)
    scored["hierarchical_gate"] = hierarchy_audit
    scored["plausibility_check"] = plausibility_check
    scored["score"] = score
    scored["competition_advantage"] = (
        "Ranks well because it is traceable to a high-value gap, has an explicit mechanism, passes generic disciplinary plausibility checks, "
        "and includes falsifiable validation criteria."
    )
    return scored

def hypothesis_disciplinary_plausibility(project: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._gap_detection import semantic_plausibility_for_pair
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _gap_detection import semantic_plausibility_for_pair
        from _utils import normalize_space, unique_preserve_order
    gap = candidate.get("source_gap") if isinstance(candidate.get("source_gap"), dict) else {}
    components = infer_gap_components(project, gap)
    text = normalize_space(
        " ".join(str(candidate.get(key) or "") for key in ("statement", "mechanism", "test_plan", "expected_value"))
    ).lower()
    method = normalize_space(components.get("method", "")).lower()
    scenario = normalize_space(components.get("scenario", "")).lower()
    combined = f"{method} {scenario} {text}"
    issues: list[str] = []
    suggestions: list[str] = []
    semantic_gate = candidate.get("semantic_plausibility") if isinstance(candidate.get("semantic_plausibility"), dict) else semantic_plausibility_for_pair(project, method, scenario, gap)
    if semantic_gate.get("verdict") == "REJECT":
        issues.append(f"Method-scenario semantic gate rejected the pair: {semantic_gate.get('reason')}")
        suggestions.append("Regenerate from a gap with an explicit data/modality/mechanism bridge or mark for human review.")
    elif semantic_gate.get("verdict") == "HUMAN_REVIEW":
        issues.append(f"Method-scenario semantic bridge is under-specified: {semantic_gate.get('reason')}")
        suggestions.append("Add the missing bridge representation before treating the hypothesis as plausible.")
    if "changes the information, intervention, or representation pathway" in text:
        issues.append("Mechanism uses a forbidden generic template rather than a concrete causal operation.")
        suggestions.append("Specify the method capability, scenario target process, bridge data, and falsification condition.")

    requirement_rules = [
        {
            "method_terms": ("lstm", "rnn", "recurrent neural", "sequence model"),
            "required_context": ("sequence", "time series", "temporal", "trajectory", "signal", "longitudinal", "text", "token"),
            "issue": "Sequence models require an ordered sequence representation; the current scenario does not clearly expose one.",
            "suggestion": "Define the sequential observable first, or use a representation better matched to spatial/graph/field data.",
        },
        {
            "method_terms": ("cnn", "convolutional", "vision transformer", "image model"),
            "required_context": ("image", "imaging", "spatial", "microscopy", "map", "field", "grid", "spectrogram"),
            "issue": "Image/convolutional models require a spatial or image-like representation that is not explicit.",
            "suggestion": "Specify the image/grid/field encoding and invariances before treating the transfer as plausible.",
        },
        {
            "method_terms": ("graph neural", "gnn", "message passing", "network embedding"),
            "required_context": ("graph", "network", "molecule", "citation", "mesh", "topology", "interaction", "relational"),
            "issue": "Graph methods require nodes and edges; the candidate does not clearly define the graph construction.",
            "suggestion": "Define nodes, edges, and conservation/causal constraints before testing the graph method.",
        },
        {
            "method_terms": ("causal", "intervention", "counterfactual"),
            "required_context": ("intervention", "causal", "confound", "randomized", "instrument", "mechanism", "natural experiment"),
            "issue": "Causal claims require intervention, identifiability, or confounding assumptions that are not explicit.",
            "suggestion": "State the causal graph or identifiability assumptions and include falsification checks.",
        },
    ]
    for rule in requirement_rules:
        if any(term in combined for term in rule["method_terms"]) and not any(non_negated_phrase_in_text(term, combined) for term in rule["required_context"]):
            issues.append(rule["issue"])
            suggestions.append(rule["suggestion"])

    constraint_terms = ("conservation", "symmetry", "constraint", "safety", "ethics", "clinical", "physical law", "mass", "energy", "charge")
    if any(term in scenario for term in ("physical", "quantum", "coulomb", "fluid", "climate", "battery", "biological", "clinical")) and not any(term in text for term in constraint_terms):
        issues.append("The hypothesis touches a constrained scientific system but does not explicitly state domain constraints or invariants.")
        suggestions.append("Add the relevant physical, biological, clinical, or engineering constraints as hard checks in the test plan.")

    score = 0.82
    if issues:
        score -= min(0.55, 0.18 * len(issues))
    if semantic_gate.get("verdict") == "REJECT":
        score -= 0.3
    elif semantic_gate.get("verdict") == "HUMAN_REVIEW":
        score -= 0.12
    if "baseline" in text and ("falsification" in text or "negative control" in text or "stress" in text):
        score += 0.08
    score = max(0.15, min(1.0, score))
    return {
        "score": round(score, 3),
        "issues": issues,
        "suggestions": unique_preserve_order(suggestions),
        "semantic_plausibility": semantic_gate,
        "requires_human_review": bool(issues),
    }

def hypothesis_control_variable(gap: dict[str, Any], method: str, scenario: str) -> str:
    try:
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _utils import normalize_space, unique_preserve_order
    text = normalize_space(
        " ".join(
            str(item)
            for item in [
                gap.get("description", ""),
                gap.get("suggested_research_path", ""),
                method,
                scenario,
            ]
        )
    )
    patterns = [
        r"\b(?:concentration|dose|temperature|pressure|voltage|frequency|resolution|scale|sample size|time step|threshold|ratio|loading|coverage|depth|rate)\b",
        r"\b(?:noise level|data quality|constraint strength|parameter|boundary condition|operating regime)\b",
    ]
    hits: list[str] = []
    for pattern in patterns:
        hits.extend(match.group(0).lower() for match in re.finditer(pattern, text, flags=re.IGNORECASE))
    if hits:
        return unique_preserve_order(hits)[0]
    if str(gap.get("gap_type") or "") == "contradiction":
        return "the experimental, observational, or simulation conditions that differ between the claims"
    return "REQUIRES_DIRECT_INTERVENTION_EVIDENCE"

def hypothesis_boundary_condition(gap: dict[str, Any]) -> str:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    text = normalize_space(f"{gap.get('description', '')} {gap.get('suggested_research_path', '')}")
    numeric = re.search(
        r"\b(?:[<>]=?\s*)?\d+(?:\.\d+)?\s*(?:%|k|c|v|mv|a|ma|hz|khz|mhz|s|ms|us|nm|um|mm|cm|m|pa|bar|mol|mM|M|cycles?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if numeric:
        return normalize_space(numeric.group(0))
    if any(term in text.lower() for term in ("challenge", "contradict", "conflict", "debate", "unclear")):
        return "the condition where the competing explanations diverge"
    return "a preregistered stress threshold rather than an open-ended improvement claim"

def non_negated_phrase_in_text(phrase: str, text: str) -> bool:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    normalized = normalize_space(phrase).lower()
    lowered = text.lower()
    for match in re.finditer(re.escape(normalized).replace(r"\ ", r"\s+"), lowered):
        prefix = lowered[max(0, match.start() - 40) : match.start()]
        if any(marker in prefix for marker in ("without", "no ", "not ", "lack", "lacks", "missing", "absent")):
            continue
        return True
    return False

def hypothesis_surprise_score(project: dict[str, Any], candidate: dict[str, Any]) -> float:
    try:
        from ._gap_detection import concepts_are_connected, literature_coverage_factor, record_field
        from ._literature_scoring import fields_are_incompatible
    except ImportError:
        from _gap_detection import concepts_are_connected, literature_coverage_factor, record_field
        from _literature_scoring import fields_are_incompatible
    gap = candidate.get("source_gap") if isinstance(candidate.get("source_gap"), dict) else {}
    components = infer_gap_components(project, gap)
    method = components.get("method", "")
    scenario = components.get("scenario", "")
    connected = concepts_are_connected(project, method, scenario) if method and scenario else True
    source_field = record_field({"title": method, "abstract": method})
    target_field = record_field({"title": scenario, "abstract": scenario})
    field_distance = 0.25 if fields_are_incompatible(source_field, target_field) else 0.0
    gap_type_bonus = 0.2 if str(gap.get("gap_type") or "") in {"migration", "structural", "contradiction", "anomaly"} else 0.0
    connection_bonus = 0.35 if not connected else 0.08
    overlap_penalty = min(0.25, float(gap.get("literature_coverage_factor") or 0.0) * 0.25)
    return round(max(0.0, min(1.0, 0.35 + field_distance + gap_type_bonus + connection_bonus - overlap_penalty)), 3)

def select_diverse_hypothesis_finalists(population: list[dict[str, Any]], top_k: int = 5, max_similarity: float = 0.7) -> list[dict[str, Any]]:
    try:
        from ._gap_detection import text_jaccard
    except ImportError:
        from _gap_detection import text_jaccard
    ordered = sorted(population, key=lambda item: (-float(item.get("score", 0.0)), item.get("statement", "")))
    selected: list[dict[str, Any]] = []
    used_gap_ids: set[str] = set()
    for candidate in ordered:
        if candidate.get("eligible_for_hypothesis_generation") is False:
            continue
        semantic_gate = candidate.get("semantic_plausibility") if isinstance(candidate.get("semantic_plausibility"), dict) else {}
        if semantic_gate.get("verdict") == "REJECT":
            continue
        statement = str(candidate.get("statement") or "")
        too_similar = any(text_jaccard(statement, str(existing.get("statement") or "")) >= max_similarity for existing in selected)
        same_gap_saturated = str(candidate.get("gap_id") or "") in used_gap_ids and len(used_gap_ids) < top_k
        if too_similar or same_gap_saturated:
            continue
        selected.append(candidate)
        if candidate.get("gap_id"):
            used_gap_ids.add(str(candidate.get("gap_id")))
        if len(selected) >= top_k:
            return selected
    for candidate in ordered:
        if candidate.get("eligible_for_hypothesis_generation") is False:
            continue
        semantic_gate = candidate.get("semantic_plausibility") if isinstance(candidate.get("semantic_plausibility"), dict) else {}
        if semantic_gate.get("verdict") == "REJECT":
            continue
        if candidate not in selected:
            selected.append(candidate)
        if len(selected) >= top_k:
            break
    return selected[:top_k]

def tournament_select_hypotheses(population: list[dict[str, Any]], n_winners: int) -> list[dict[str, Any]]:
    ordered = sorted(population, key=lambda item: (-float(item.get("score", 0.0)), item.get("statement", "")))
    winners: list[dict[str, Any]] = []
    for index in range(0, len(ordered), 2):
        pair = ordered[index : index + 2]
        if pair:
            winners.append(pair[0])
        if len(winners) >= n_winners:
            break
    return winners

def evolve_hypothesis_offspring(
    project: dict[str, Any],
    winners: list[dict[str, Any]],
    population_size: int,
    generation: int,
) -> list[dict[str, Any]]:
    try:
        from ._pipeline import project_records_for_mapping
        from ._utils import is_unknown_value, new_id, normalize_label, trim_text, unique_preserve_order
    except ImportError:
        from _pipeline import project_records_for_mapping
        from _utils import is_unknown_value, new_id, normalize_label, trim_text, unique_preserve_order
    if not winners:
        return []
    offspring: list[dict[str, Any]] = []
    methods = sorted({normalize_label(record.get("method", "")) for record in project_records_for_mapping(project) if not is_unknown_value(record.get("method", ""))})
    scenarios = sorted({normalize_label(record.get("scenario", "")) for record in project_records_for_mapping(project) if not is_unknown_value(record.get("scenario", ""))})
    benchmarks = sorted({normalize_label(record.get("benchmark", "")) for record in project_records_for_mapping(project) if not is_unknown_value(record.get("benchmark", ""))})
    while len(offspring) < population_size:
        parent = winners[len(offspring) % len(winners)]
        child = dict(parent)
        child["candidate_id"] = new_id("hcand")
        child["generation"] = generation
        if parent.get("hierarchical_search") and parent.get("scientific_hypothesis_hierarchy"):
            operation = [
                "discriminator_strengthening",
                "boundary_stress_refinement",
                "validation_refinement",
                "same_contract_recombination",
            ][len(offspring) % 4]
            if operation == "same_contract_recombination" and len(winners) > 1:
                other = winners[(len(offspring) + 1) % len(winners)]
                recombined = recombine_hierarchical_candidates(parent, other)
                if recombined.get("status") == "READY" and isinstance(recombined.get("candidate"), dict):
                    child = dict(recombined["candidate"])
                    child["candidate_id"] = new_id("hcand")
                    child["generation"] = generation
                else:
                    operation = "same_contract_recombination_rejected"
                    child["recombination_rejection"] = recombined
            hierarchy = json.loads(json.dumps(child.get("scientific_hypothesis_hierarchy", {}), ensure_ascii=False))
            topology = hierarchy.get("SCIENTIFIC_CLAIM_TOPOLOGY", {}) if isinstance(hierarchy.get("SCIENTIFIC_CLAIM_TOPOLOGY"), dict) else {}
            operational = hierarchy.get("OPERATIONALIZATION_AND_DISCRIMINATION", {}) if isinstance(hierarchy.get("OPERATIONALIZATION_AND_DISCRIMINATION"), dict) else {}
            validation = hierarchy.get("VALIDATION_SAFETY_AND_REPRODUCIBILITY", {}) if isinstance(hierarchy.get("VALIDATION_SAFETY_AND_REPRODUCIBILITY"), dict) else {}
            if operation == "discriminator_strengthening":
                decisive = str(operational.get("decisive_prediction") or child.get("discriminating_prediction") or "")
                decisive += " The primary and competing explanations must be fitted or tested on the same units, inputs, and preregistered boundary."
                operational["decisive_prediction"] = decisive
                child["discriminating_prediction"] = decisive
            elif operation == "boundary_stress_refinement":
                boundaries = list(topology.get("boundary_conditions") or [])
                stress = "the nearest source-compatible regime where the competing predictions diverge, with its exact setting left TO_BE_OPTIMIZED"
                if stress not in boundaries:
                    boundaries.append(stress)
                topology["boundary_conditions"] = boundaries
                child["boundary"] = stress
            elif operation == "validation_refinement":
                tests = list(validation.get("alternative_mechanism_tests") or [])
                extra = "Repeat the decisive discriminator with an orthogonal observable while preserving the same frozen causal roles."
                if extra not in tests:
                    tests.append(extra)
                validation["alternative_mechanism_tests"] = tests
            hierarchy["SCIENTIFIC_CLAIM_TOPOLOGY"] = topology
            hierarchy["OPERATIONALIZATION_AND_DISCRIMINATION"] = operational
            hierarchy["VALIDATION_SAFETY_AND_REPRODUCIBILITY"] = validation
            child["scientific_hypothesis_hierarchy"] = hierarchy
            child["lineage"] = list(parent.get("lineage", [])) + [
                {
                    "generation": generation,
                    "operation": operation,
                    "parent_candidate_id": parent.get("candidate_id"),
                    "frozen_contract_signature": (
                        parent.get("hierarchical_search", {}) or {}
                    ).get("contract_signature", ""),
                }
            ]
            hierarchy_audit = audit_hierarchical_candidate(child)
            if not hierarchy_audit.get("hard_gate_passed"):
                # A mutation may lose diversity, but it may not weaken a hard
                # scientific contract.  Revert content and retain the failed
                # proposal only as lineage feedback.
                reverted = dict(parent)
                reverted["candidate_id"] = child["candidate_id"]
                reverted["generation"] = generation
                reverted["lineage"] = list(parent.get("lineage", [])) + [
                    {
                        "generation": generation,
                        "operation": "hierarchical_mutation_rejected",
                        "attempted_operation": operation,
                        "audit": hierarchy_audit,
                    }
                ]
                child = reverted
            else:
                child["hierarchical_gate"] = hierarchy_audit
            offspring.append(child)
            continue
        operation = ["constraint_insertion", "method_mutation", "scenario_crossover", "cross_gap_crossover"][len(offspring) % 4]
        if operation == "method_mutation" and methods:
            method = methods[(generation + len(offspring)) % len(methods)]
            child["statement"] = re.sub(r"If .*? is applied", f"If {method} is applied", str(child.get("statement")), count=1)
            child["mechanism"] = f"Mutated method pathway: {method} is substituted to test whether the mechanism survives a method-level perturbation. " + str(child.get("mechanism", ""))
        elif operation == "scenario_crossover" and len(winners) > 1 and scenarios:
            other = winners[(len(offspring) + 1) % len(winners)]
            scenario = scenarios[(generation + len(offspring)) % len(scenarios)]
            child["statement"] = str(child.get("statement", "")) + f" A crossover variant also tests transfer into {scenario}."
            child["mechanism"] = str(child.get("mechanism", "")) + f" Crossover lineage borrows constraints from {other.get('candidate_id')}."
        elif operation == "cross_gap_crossover" and len(winners) > 1:
            other = next(
                (item for item in winners if item.get("gap_id") and item.get("gap_id") != parent.get("gap_id")),
                winners[(len(offspring) + 1) % len(winners)],
            )
            child["gap_ids"] = unique_preserve_order(
                [str(parent.get("gap_id") or ""), str(other.get("gap_id") or "")]
                + [str(item) for item in parent.get("gap_ids", []) if item]
                + [str(item) for item in other.get("gap_ids", []) if item]
            )
            child["statement"] = (
                str(child.get("statement", ""))
                + " A cross-gap variant tests whether the mechanism remains valid when the second gap's boundary condition is imposed: "
                + trim_text(str(other.get("statement") or ""), 180)
            )
            child["mechanism"] = (
                str(child.get("mechanism", ""))
                + f" Cross-gap crossover combines evidence from {parent.get('gap_id')} and {other.get('gap_id')} to test whether one gap resolves or sharpens the other."
            )
        else:
            benchmark = benchmarks[(generation + len(offspring)) % len(benchmarks)] if benchmarks else "failure-mode robustness"
            child["statement"] = str(child.get("statement", "")) + f" The decisive test is constrained to {benchmark} under an explicit stress regime."
            child["test_plan"] = str(child.get("test_plan", "")) + f" Add a preregistered stress test for {benchmark}."
        child["lineage"] = list(parent.get("lineage", [])) + [
            {"generation": generation, "operation": operation, "parent_candidate_id": parent.get("candidate_id")}
        ]
        offspring.append(child)
    return offspring

def collect_project_analogies(project: dict[str, Any]) -> list[dict[str, Any]]:
    reports = project.get("structural_analogy_reports", [])
    analogies: list[dict[str, Any]] = []
    for report in reports:
        if isinstance(report, dict):
            analogies.extend([item for item in report.get("analogy_transfers", []) if isinstance(item, dict)])
    return analogies

def collect_project_hotspots(project: dict[str, Any]) -> list[dict[str, Any]]:
    tkg = project.get("temporal_knowledge_graph", {}) if isinstance(project.get("temporal_knowledge_graph"), dict) else {}
    return [item for item in tkg.get("hotspot_predictions", []) if isinstance(item, dict)]

def best_hypothesis_score(population: list[dict[str, Any]]) -> float:
    return max((float(item.get("score") or 0.0) for item in population), default=0.0)

def generate_idea(
    project_id: str,
    gap: dict[str, Any] | str = "",
    gap_id: str = "",
    style: str = "innovative",
    parent_hypothesis_id: str = "",
    use_llm: bool = False,
) -> str:
    try:
        from ._models import Hypothesis
        from ._project import load_project, save_project
        from ._utils import new_id, normalize_key
    except ImportError:
        from _models import Hypothesis
        from _project import load_project, save_project
        from _utils import new_id, normalize_key
    project = load_project(project_id)
    selected_gap = mingli_resolve_gap(project, gap=gap, gap_id=gap_id)
    package_resolution = hypothesis_package_gate(project, str(selected_gap.get("gap_id") or ""))
    hypothesis_package = package_resolution["package"]
    package_gate = package_resolution["gate"]
    package_architecture_active = bool(project.get("hypothesis_packages") or project.get("research_coverage_map"))
    if package_architecture_active and not package_gate.get("ready"):
        lineage_blocked = bool(
            str(package_gate.get("status") or "") == "SOURCE_TEXT_LINEAGE_INCOMPLETE"
            or str(hypothesis_package.get("status") or "") == "SOURCE_TEXT_LINEAGE_INCOMPLETE"
            or (
                package_gate.get("missing_source_lineage_slots")
                and not package_gate.get("missing_required_coverage")
                and not package_gate.get("incompatible_edges")
            )
        )
        blocked_status = (
            "blocked_source_text_lineage_incomplete"
            if lineage_blocked
            else "blocked_hypothesis_package_coverage"
        )
        blocked_reason = (
            "; ".join(str(item) for item in package_gate.get("reasons", []) if str(item))
            or (
                "Hypothesis package source-text lineage is incomplete."
                if lineage_blocked
                else "Hypothesis package coverage is incomplete."
            )
        )
        science_state_handoff = {
            "schema_version": "mingli_gap_handoff.v1",
            "project_id": project_id,
            "gap_id": selected_gap.get("gap_id", ""),
            "status": "NOT_EVALUATED_PACKAGE_GATE_BLOCKED",
            "blocked_by": blocked_status,
            "reason": blocked_reason,
        }
        blocked = {
            "draft_idea_id": new_id("idea"),
            "project_id": project_id,
            "gap_id": selected_gap.get("gap_id", ""),
            "hypothesis_package": hypothesis_package,
            "coverage_and_compatibility_gate": package_gate,
            "science_state_handoff": science_state_handoff,
            "style": style,
            "candidate": {},
            "idea_json": {},
            "use_llm_requested": bool(use_llm),
            "status": blocked_status,
            "reason": blocked_reason,
            "createdAt": time.time(),
        }
        project.setdefault("mingli_draft_ideas", []).append(blocked)
        project["updatedAt"] = time.time()
        save_project(project)
        log_event(
            "SCIENCE",
            "mingli_source_text_lineage_blocked" if lineage_blocked else "mingli_hypothesis_package_blocked",
            project_id=project_id,
            gap_id=selected_gap.get("gap_id"),
            package_id=hypothesis_package.get("hypothesis_package_id"),
            missing_source_lineage_slots=list(package_gate.get("missing_source_lineage_slots") or []),
        )
        return json.dumps(
            {
                "thought": (
                    "MingLi refused to generate because the package lacks accepted source-text lineage for required slots."
                    if lineage_blocked
                    else "MingLi refused to bypass an incomplete coverage or compatibility audit."
                ),
                "action": {
                    "type": (
                        "repair_source_text_lineage"
                        if lineage_blocked
                        else "repair_hypothesis_package"
                    ),
                    "gap_id": selected_gap.get("gap_id", ""),
                },
                **blocked,
                "next_step": (
                    "Complete accepted source-text lineage for the missing input/mechanism/outcome/measurement slots before calling MingLi."
                    if lineage_blocked
                    else "Fill the missing structural coverage slots or use a compatible, scope-bound mechanism path."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    science_state_handoff = validate_mingli_gap_handoff(project, selected_gap)
    components = infer_gap_components(project, selected_gap)
    intervention_gate = mingli_intervention_type_gate(project, selected_gap, components)
    if not intervention_gate.get("admissible"):
        blocked = {
            "draft_idea_id": new_id("idea"),
            "project_id": project_id,
            "gap_id": selected_gap.get("gap_id", ""),
            "science_state_handoff": science_state_handoff,
            "style": style,
            "candidate": {},
            "idea_json": {},
            "intervention_type_gate": intervention_gate,
            "use_llm_requested": bool(use_llm),
            "status": "blocked_intervention_ontology",
            "reason": intervention_gate.get("reason"),
            "createdAt": time.time(),
        }
        project.setdefault("mingli_draft_ideas", []).append(blocked)
        project["updatedAt"] = time.time()
        save_project(project)
        log_event(
            "SCIENCE",
            "mingli_intervention_ontology_blocked",
            project_id=project_id,
            gap_id=selected_gap.get("gap_id", ""),
            excluded_epistemic_methods=intervention_gate.get("excluded_epistemic_methods", []),
        )
        return json.dumps(
            {
                "thought": "MingLi refused to convert an epistemic, observational, or placeholder method into a causal intervention.",
                "action": {"type": "retrieve_or_define_direct_intervention", "gap_id": selected_gap.get("gap_id", "")},
                **blocked,
                "next_step": "Return to Socrates/ZhiZhi for an A/B-grade direct intervention or obtain an expert-specified manipulable variable.",
            },
            ensure_ascii=False,
            indent=2,
        )
    analogies = collect_project_analogies(project)
    hotspots = collect_project_hotspots(project)
    variant = 1 if normalize_key(style) == "innovative" else 0
    candidate = make_hypothesis_seed(
        project,
        selected_gap,
        components,
        variant,
        analogy=analogies[0] if analogies else {},
        hotspot=hotspots[0] if hotspots else {},
    )
    candidate["style"] = style
    if hypothesis_package:
        candidate["hypothesis_package"] = hypothesis_package
    disclaimer = final_object_claim_disclaimer(selected_gap, hypothesis_package)
    if disclaimer:
        candidate["final_object_claim_disclaimer"] = disclaimer
    candidate["parent_hypothesis_id"] = parent_hypothesis_id or None
    if parent_hypothesis_id:
        candidate.setdefault("lineage", []).append(
            {"generation": 0, "operation": "manual_parent_link", "parent_hypothesis_id": parent_hypothesis_id}
        )
    if normalize_key(style) == "conservative":
        candidate["statement"] = conservative_hypothesis_statement(candidate, components)
        candidate["mechanism"] = (
            f"The conservative mechanism tests the most direct pathway suggested by the gap: {components['method']} in "
            f"{components['scenario']}, with {components['benchmark']} as the decisive readout. "
            f"It must vary {hypothesis_control_variable(selected_gap, components['method'], components['scenario'])} and report the "
            f"boundary condition {hypothesis_boundary_condition(selected_gap)} rather than only a broad improvement claim."
        )
    else:
        candidate["statement"] = innovative_hypothesis_statement(candidate, components, selected_gap)
        candidate["mechanism"] += " MingLi treats this as a structural mutation rather than a surface rephrasing."
    hierarchy_search = run_hierarchical_hypothesis_search(
        project,
        selected_gap,
        candidate,
        hypothesis_package=hypothesis_package,
        use_llm=bool(use_llm),
    )
    if hierarchy_search.get("status") != "READY":
        blocked = {
            "draft_idea_id": new_id("idea"),
            "project_id": project_id,
            "gap_id": selected_gap.get("gap_id", ""),
            "science_state_handoff": science_state_handoff,
            "style": style,
            "candidate": candidate,
            "idea_json": {},
            "hierarchical_search": hierarchy_search,
            "use_llm_requested": bool(use_llm),
            "status": "blocked_scientific_hypothesis_hierarchy",
            "reason": (
                "No proposal passed the frozen-contract, ontology, operationalization, "
                "parameter-provenance, and validation hard gates."
            ),
            "createdAt": time.time(),
        }
        project.setdefault("mingli_draft_ideas", []).append(blocked)
        project["updatedAt"] = time.time()
        save_project(project)
        log_event(
            "SCIENCE",
            "mingli_hierarchical_search_blocked",
            project_id=project_id,
            gap_id=selected_gap.get("gap_id", ""),
            blocked_level=hierarchy_search.get("blocked_level", ""),
            rejection_count=len(hierarchy_search.get("rejection_feedback", [])),
        )
        return json.dumps(
            {
                "thought": "MingLi retained the upstream scientific question but no five-layer refinement passed all hard gates.",
                "action": {
                    "type": "repair_source_bound_hypothesis_contract",
                    "gap_id": selected_gap.get("gap_id", ""),
                },
                **blocked,
                "next_step": "Repair the reported entity/provenance or design requirement in Socrates; do not bypass it with fluent prose.",
            },
            ensure_ascii=False,
            indent=2,
        )
    refined = hierarchy_search.get("refined_candidate")
    if isinstance(refined, dict):
        candidate = refined
    candidate = score_hypothesis_candidate(project, candidate)
    idea = mingli_candidate_to_idea_json(project, candidate)
    if disclaimer:
        idea["final_object_claim_disclaimer"] = disclaimer
    draft = {
        "draft_idea_id": new_id("idea"),
        "project_id": project_id,
        "gap_id": selected_gap.get("gap_id", ""),
        "science_state_handoff": science_state_handoff,
        "style": style,
        "candidate": candidate,
        "idea_json": idea,
        "final_object_claim_disclaimer": disclaimer,
        "use_llm_requested": bool(use_llm),
        "status": "draft",
        "createdAt": time.time(),
    }
    project.setdefault("mingli_draft_ideas", []).append(draft)
    project["phase"] = "Hypothesis Generation"
    project["updatedAt"] = time.time()
    save_project(project)
    return json.dumps(
        {
            "thought": "Generated a gap-traceable MingLi draft idea and scored it for novelty, plausibility, grounding, testability, impact, and surprise.",
            "action": {"type": "generate_idea", "gap_id": selected_gap.get("gap_id", ""), "style": style},
            **draft,
            "next_step": "Call finalize_idea to verify the minimum falsifiable hypothesis; construct the detailed experiment protocol only after debate acceptance.",
        },
        ensure_ascii=False,
        indent=2,
    )


def combine_finalized_hypotheses(project_id: str, hypothesis_ids: list[str]) -> str:
    """Create an auditable composite only from compatible finalized ideas.

    The composite does not claim that unrelated mechanisms are synergistic.
    It explicitly states the joint prediction and carries every parent gap and
    hypothesis id, so YanZhen can reject the conjunction independently.
    """
    try:
        from ._project import load_project, save_project
        from ._utils import new_id
        from ._literature_search import query_terms
    except ImportError:
        from _project import load_project, save_project
        from _utils import new_id
        from _literature_search import query_terms
    project = load_project(project_id)
    wanted = {str(item) for item in hypothesis_ids if str(item)}
    parents = [item for item in project.get("hypotheses", []) if isinstance(item, dict) and str(item.get("hypothesis_id") or "") in wanted]
    if len(parents) < 2:
        return json.dumps({"status": "not_combined", "reason": "at least two finalized hypotheses are required"}, ensure_ascii=False, indent=2)
    entity_sets = [set(query_terms(" ".join(str(item.get(key) or "") for key in ("statement", "mechanism", "expected_value")))) for item in parents]
    common = set.intersection(*entity_sets) if entity_sets else set()
    if len(common) < 1:
        return json.dumps({"status": "not_combined", "reason": "parent hypotheses have no shared project-local mechanism entity", "parent_hypothesis_ids": sorted(wanted)}, ensure_ascii=False, indent=2)
    parent_ids = [str(item.get("hypothesis_id") or "") for item in parents]
    parent_gaps = [str(item.get("gap_id") or "") for item in parents if str(item.get("gap_id") or "")]
    primary = parents[0]
    composite = {
        "hypothesis_id": new_id("hyp"),
        "gap_id": primary.get("gap_id", ""),
        "gap_ids": parent_gaps,
        "hypothesis_type": "combined",
        "parent_hypothesis_ids": parent_ids,
        "statement": (
            "Combined hypothesis: under a shared, pre-registered operating regime, the parent mechanisms should each produce "
            "their stated intermediate observation; the joint outcome is supported only if their combined intervention outperforms "
            "every single-mechanism intervention without reversing either parent falsification criterion."
        ),
        "mechanism": "This is a conjunction of independently grounded mechanisms, not a claim that they are automatically compatible. " + " ".join(
            f"Parent {item.get('hypothesis_id')}: {str(item.get('mechanism') or '')[:500]}" for item in parents
        ),
        "expected_value": "Tests whether independently supported mechanisms interact constructively, additively, or antagonistically under matched conditions.",
        "test_plan": (
            "Run the parent interventions singly and jointly under identical controls; measure each parent mediator before endpoints; "
            "pre-register interaction, additivity, and failure criteria."
        ),
        "verification_plan": {
            "parents": parent_ids,
            "required_controls": ["each parent intervention alone", "joint intervention", "matched no-intervention control"],
            "falsification_condition": "Reject the composite if either parent mediator fails, or if the joint condition is not distinguishable from the best single parent condition.",
        },
        "lineage": [{"generation": 1, "operation": "evidence_bounded_combination", "parent_hypothesis_ids": parent_ids}],
        "status": "finalized",
        "createdAt": time.time(),
    }
    project.setdefault("hypotheses", []).append(composite)
    project.setdefault("mingli_combinations", []).append({"createdAt": time.time(), "composite_hypothesis_id": composite["hypothesis_id"], "parents": parent_ids})
    save_project(project)
    return json.dumps({"status": "combined", "hypothesis": composite}, ensure_ascii=False, indent=2)

EXPERIMENT_PROTOCOL_VERSION = "structured_experiment_protocol_v1"
EXPERIMENT_PROTOCOL_UNRESOLVED_PREFIXES = (
    "requires_expert_input:",
    "tbd:",
    "unknown:",
    "not_specified:",
)
EXPERIMENT_PROTOCOL_REQUIRED_PATHS = (
    ("research_question",),
    ("causal_claim",),
    ("model_system", "system_type"),
    ("model_system", "experimental_unit"),
    ("model_system", "species"),
    ("model_system", "cell_type"),
    ("model_system", "lineage_state"),
    ("model_system", "inclusion_exclusion_criteria", "inclusion"),
    ("model_system", "inclusion_exclusion_criteria", "exclusion"),
    ("intervention", "target"),
    ("intervention", "modality"),
    ("intervention", "dose_or_strength"),
    ("intervention", "delivery_method"),
    ("intervention", "timing"),
    ("time_course", "biological_rationale"),
    ("time_course", "measurement_timepoints"),
    ("readouts", "primary"),
    ("readouts", "secondary"),
    ("readouts", "mechanistic"),
    ("readouts", "orthogonal_validation"),
    ("replication_and_bias_control", "biological_replicates"),
    ("replication_and_bias_control", "technical_replicates"),
    ("replication_and_bias_control", "randomization"),
    ("replication_and_bias_control", "blinding"),
    ("replication_and_bias_control", "batch_control"),
    ("analysis_plan", "statistical_test"),
    ("analysis_plan", "multiple_testing_policy"),
    ("analysis_plan", "effect_size"),
    ("analysis_plan", "confidence_interval"),
    ("analysis_plan", "power_analysis_assumptions"),
    ("success_criteria", "minimum_meaningful_effect_size"),
    ("success_criteria", "confidence_interval_requirement"),
    ("success_criteria", "preregistered_primary_endpoint"),
    ("success_criteria", "rescue_or_epistasis_requirement"),
    ("failure_criteria", "minimum_meaningful_effect_size"),
    ("failure_criteria", "confidence_interval_requirement"),
    ("failure_criteria", "primary_endpoint_failure"),
    ("failure_criteria", "rescue_failure"),
    ("failure_criteria", "alternative_mechanism_preferred"),
    ("failure_criteria", "replication_or_regime_shift_failure"),
    ("alternative_explanations",),
    ("regime_shift_tests",),
    ("data_and_code_reproducibility", "data_management"),
    ("data_and_code_reproducibility", "code_or_analysis_artifact"),
    ("data_and_code_reproducibility", "environment_capture"),
    ("data_and_code_reproducibility", "protocol_versioning"),
)
EXPERIMENT_PROTOCOL_ARM_NAMES = (
    "treatment",
    "vehicle_or_mock_control",
    "positive_control",
    "negative_control",
    "rescue_or_epistasis_arm",
)


def experiment_protocol_context(project: dict[str, Any], idea: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    sources = (
        project.get("experiment_context"),
        project.get("structured_experiment_context"),
        idea.get("experiment_context"),
        idea.get("structured_experiment_context"),
    )
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
    return merged


def experiment_protocol_value(
    context: dict[str, Any],
    section: str,
    key: str,
    fallback: Any,
) -> Any:
    section_value = context.get(section)
    if isinstance(section_value, dict) and section_value.get(key) not in (None, "", [], {}):
        return section_value[key]
    if context.get(key) not in (None, "", [], {}):
        return context[key]
    return fallback


def experiment_protocol_pending(field: str) -> str:
    return f"REQUIRES_EXPERT_INPUT: specify {field} from the project system, resources, and evidence."


def experiment_protocol_not_applicable(field: str, context: dict[str, Any]) -> str:
    declared_non_biological = bool(
        context.get("non_biological_system")
        or (context.get("model_system", {}).get("non_biological_system") if isinstance(context.get("model_system"), dict) else False)
    )
    if declared_non_biological:
        return f"NOT_APPLICABLE: {field} does not apply because the project declares a non-biological system."
    return experiment_protocol_pending(field)


def experiment_protocol_path_value(protocol: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = protocol
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def experiment_protocol_is_unresolved(value: Any) -> bool:
    if value in (None, "", [], {}):
        return True
    if isinstance(value, str):
        text = value.strip().lower()
        return any(text.startswith(prefix) for prefix in EXPERIMENT_PROTOCOL_UNRESOLVED_PREFIXES)
    if isinstance(value, list):
        return not value or any(experiment_protocol_is_unresolved(item) for item in value)
    return False


def experiment_protocol_valid_not_applicable(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip().lower().startswith("not_applicable:"):
        return False
    return len(value.split(":", 1)[1].strip()) >= 12


def experiment_protocol_display_value(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(experiment_protocol_display_value(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{key}: {experiment_protocol_display_value(item)}" for key, item in value.items())
    return str(value or "")


def validate_structured_experiment_protocol(protocol: dict[str, Any]) -> dict[str, Any]:
    missing_fields: list[str] = []
    unresolved_fields: list[str] = []
    invalid_not_applicable: list[str] = []
    invalid_intervention_ontology: list[str] = []
    for path in EXPERIMENT_PROTOCOL_REQUIRED_PATHS:
        value = experiment_protocol_path_value(protocol, path)
        label = ".".join(path)
        if value in (None, "", [], {}):
            missing_fields.append(label)
            continue
        if experiment_protocol_valid_not_applicable(value):
            continue
        if isinstance(value, str) and value.strip().lower().startswith("not_applicable:"):
            invalid_not_applicable.append(label)
            continue
        if experiment_protocol_is_unresolved(value):
            unresolved_fields.append(label)
    arms = protocol.get("experimental_arms")
    if not isinstance(arms, list):
        missing_fields.append("experimental_arms")
    else:
        arms_by_name = {
            str(item.get("arm") or ""): item
            for item in arms
            if isinstance(item, dict)
        }
        for arm_name in EXPERIMENT_PROTOCOL_ARM_NAMES:
            arm = arms_by_name.get(arm_name)
            label = f"experimental_arms.{arm_name}"
            if not arm:
                missing_fields.append(label)
            elif experiment_protocol_is_unresolved(arm.get("description")):
                unresolved_fields.append(label)
            elif str(arm.get("description") or "").strip().lower().startswith("not_applicable:") and not experiment_protocol_valid_not_applicable(arm.get("description")):
                invalid_not_applicable.append(label)
    for readout_type in ("primary", "secondary", "mechanistic", "orthogonal_validation"):
        values = protocol.get("readouts", {}).get(readout_type) if isinstance(protocol.get("readouts"), dict) else None
        label = f"readouts.{readout_type}"
        if not isinstance(values, list) or not values:
            missing_fields.append(label)
        elif any(
            experiment_protocol_is_unresolved(item.get("name") if isinstance(item, dict) else item)
            for item in values
        ):
            unresolved_fields.append(label)
    regime_shift_tests = protocol.get("regime_shift_tests")
    if isinstance(regime_shift_tests, list) and len(regime_shift_tests) < 2:
        unresolved_fields.append("regime_shift_tests.minimum_two_conditions")
    intervention = protocol.get("intervention") if isinstance(protocol.get("intervention"), dict) else {}
    target = str(intervention.get("target") or "")
    modality = str(intervention.get("modality") or "")
    target_assessment = classify_intervention_candidate(target)
    combined_assessment = classify_intervention_candidate(
        f"{modality} {target}" if modality and not experiment_protocol_is_unresolved(modality) else target
    )
    intervention_assessment = target_assessment if target_assessment.get("admissible_as_intervention") else combined_assessment
    if not intervention_assessment.get("admissible_as_intervention"):
        invalid_intervention_ontology.append("intervention.target_or_modality")
    protocol["intervention_type_gate"] = {
        "verdict": "PASS" if intervention_assessment.get("admissible_as_intervention") else "FAIL",
        "admissible": bool(intervention_assessment.get("admissible_as_intervention")),
        "selected_intervention": intervention_assessment.get("candidate", "") if intervention_assessment.get("admissible_as_intervention") else "",
        "selected_assessment": intervention_assessment,
    }
    verdict = (
        "READY_FOR_EXECUTION"
        if not (missing_fields or unresolved_fields or invalid_not_applicable or invalid_intervention_ontology)
        else "REQUIRES_EXPERT_INPUT"
    )
    return {
        "verdict": verdict,
        "hard_gate_passed": verdict == "READY_FOR_EXECUTION",
        "execution_authorized": verdict == "READY_FOR_EXECUTION",
        "missing_fields": sorted(set(missing_fields)),
        "unresolved_fields": sorted(set(unresolved_fields)),
        "invalid_not_applicable": sorted(set(invalid_not_applicable)),
        "invalid_intervention_ontology": sorted(set(invalid_intervention_ontology)),
        "intervention_type_gate": protocol["intervention_type_gate"],
        "next_action": (
            "Protocol is complete enough for execution subject to institutional and safety approval."
            if verdict == "READY_FOR_EXECUTION"
            else "A domain expert must supply or explicitly justify every unresolved protocol field before execution."
        ),
    }


def build_structured_experiment_protocol(
    project: dict[str, Any],
    idea: dict[str, Any],
    gap: dict[str, Any],
    components: dict[str, str],
    constraints: str = "academic lab scale",
) -> dict[str, Any]:
    context = experiment_protocol_context(project, idea)
    candidate = idea.get("candidate") if isinstance(idea.get("candidate"), dict) else {}
    method = str(components.get("method") or "the proposed intervention")
    scenario = str(components.get("scenario") or project.get("domain") or "the target system")
    benchmark = str(components.get("benchmark") or "the primary outcome")
    causal_claim = str(idea.get("abstract") or idea.get("mechanism") or candidate.get("mechanism") or idea.get("hypothesis") or "").strip()
    research_question = str(idea.get("research_question") or idea.get("hypothesis") or gap.get("description") or "").strip()
    idea_gate = idea.get("intervention_type_gate") if isinstance(idea.get("intervention_type_gate"), dict) else {}
    context_intervention = context.get("intervention") if isinstance(context.get("intervention"), dict) else {}
    protocol_intervention_gate = intervention_gate_from_values([
        {
            "candidate": context_intervention.get("target"),
            "candidate_source": "expert_experiment_context.intervention.target",
        },
        {
            "candidate": idea_gate.get("selected_intervention"),
            "candidate_source": "mingli.intervention_type_gate",
        },
        {"candidate": method, "candidate_source": "gap.operational_method"},
    ])
    target = str(
        protocol_intervention_gate.get("selected_intervention")
        or experiment_protocol_pending("a direct physical, chemical, biological, engineering, environmental, or computational intervention")
    )
    mediator = str(candidate.get("competing_explanation") or idea.get("competing_explanation") or "").strip()
    alternatives = experiment_protocol_value(
        context,
        "",
        "alternative_explanations",
        [mediator] if mediator else [experiment_protocol_pending("a plausible alternative mechanism")],
    )
    if isinstance(alternatives, str):
        alternatives = [alternatives]
    if not isinstance(alternatives, list):
        alternatives = [experiment_protocol_pending("a plausible alternative mechanism")]
    provided_arms = context.get("experimental_arms") if isinstance(context.get("experimental_arms"), list) else []
    arms_by_name = {
        str(item.get("arm") or ""): item
        for item in provided_arms
        if isinstance(item, dict)
    }
    default_arms = {
        "treatment": f"Apply {target} through the selected modality at the pre-specified strength and timing.",
        "vehicle_or_mock_control": experiment_protocol_pending("a vehicle, sham, or mock control matched to the intervention"),
        "positive_control": experiment_protocol_pending("a positive control known to move the primary readout"),
        "negative_control": experiment_protocol_pending("a negative control that preserves all non-target procedures"),
        "rescue_or_epistasis_arm": experiment_protocol_pending("a rescue or epistasis arm that can distinguish the primary pathway from alternatives"),
    }
    experimental_arms = [
        {
            "arm": arm_name,
            "description": str((arms_by_name.get(arm_name) or {}).get("description") or default_arms[arm_name]),
        }
        for arm_name in EXPERIMENT_PROTOCOL_ARM_NAMES
    ]
    readouts_context = context.get("readouts") if isinstance(context.get("readouts"), dict) else {}
    model_system_context = context.get("model_system") if isinstance(context.get("model_system"), dict) else {}
    inclusion_exclusion_context = (
        model_system_context.get("inclusion_exclusion_criteria")
        if isinstance(model_system_context.get("inclusion_exclusion_criteria"), dict)
        else context.get("inclusion_exclusion_criteria")
    )
    if not isinstance(inclusion_exclusion_context, dict):
        inclusion_exclusion_context = {}
    def readout_values(key: str, fallback: list[dict[str, str]]) -> list[dict[str, str]]:
        supplied = readouts_context.get(key)
        if isinstance(supplied, list) and supplied:
            return [item if isinstance(item, dict) else {"name": str(item)} for item in supplied]
        return fallback
    protocol = {
        "protocol_version": EXPERIMENT_PROTOCOL_VERSION,
        "research_question": research_question or experiment_protocol_pending("the research question"),
        "causal_claim": causal_claim or experiment_protocol_pending("the causal claim and its evidence boundary"),
        "constraints": constraints,
        "model_system": {
            "system_type": experiment_protocol_value(context, "model_system", "system_type", scenario),
            "experimental_unit": experiment_protocol_value(context, "model_system", "experimental_unit", experiment_protocol_pending("the experimental unit or analysis unit")),
            "species": experiment_protocol_value(context, "model_system", "species", experiment_protocol_not_applicable("species", context)),
            "cell_type": experiment_protocol_value(context, "model_system", "cell_type", experiment_protocol_not_applicable("cell type", context)),
            "lineage_state": experiment_protocol_value(context, "model_system", "lineage_state", experiment_protocol_not_applicable("lineage state", context)),
            "inclusion_exclusion_criteria": {
                "inclusion": inclusion_exclusion_context.get("inclusion") or experiment_protocol_pending("inclusion criteria"),
                "exclusion": inclusion_exclusion_context.get("exclusion") or experiment_protocol_pending("exclusion criteria"),
            },
        },
        "intervention": {
            "target": target,
            "modality": experiment_protocol_value(context, "intervention", "modality", experiment_protocol_pending("an intervention modality")),
            "dose_or_strength": experiment_protocol_value(context, "intervention", "dose_or_strength", experiment_protocol_pending("dose, strength, or parameter range")),
            "delivery_method": experiment_protocol_value(context, "intervention", "delivery_method", experiment_protocol_pending("delivery or actuation method")),
            "timing": experiment_protocol_value(context, "intervention", "timing", experiment_protocol_pending("intervention timing")),
        },
        "intervention_type_gate": protocol_intervention_gate,
        "experimental_arms": experimental_arms,
        "time_course": {
            "biological_rationale": experiment_protocol_value(
                context,
                "time_course",
                "biological_rationale",
                f"Measure the putative mediator and {benchmark} in temporal order so the proposed causal direction can be distinguished from a concurrent association.",
            ),
            "measurement_timepoints": experiment_protocol_value(context, "time_course", "measurement_timepoints", experiment_protocol_pending("measurement timepoints")),
        },
        "readouts": {
            "primary": readout_values("primary", [{"name": benchmark, "role": "pre-registered primary endpoint"}]),
            "secondary": readout_values("secondary", [{"name": experiment_protocol_pending("a secondary outcome that tests generality or cost"), "role": "secondary endpoint"}]),
            "mechanistic": readout_values("mechanistic", [{"name": experiment_protocol_pending("a mechanism-specific mediator readout"), "role": "causal-path readout"}]),
            "orthogonal_validation": readout_values("orthogonal_validation", [{"name": experiment_protocol_pending("an independent measurement modality"), "role": "orthogonal validation"}]),
        },
        "replication_and_bias_control": {
            "biological_replicates": experiment_protocol_value(context, "replication_and_bias_control", "biological_replicates", experiment_protocol_not_applicable("biological replicates", context)),
            "technical_replicates": experiment_protocol_value(context, "replication_and_bias_control", "technical_replicates", experiment_protocol_pending("technical replicate plan")),
            "randomization": experiment_protocol_value(context, "replication_and_bias_control", "randomization", experiment_protocol_pending("randomization procedure")),
            "blinding": experiment_protocol_value(context, "replication_and_bias_control", "blinding", experiment_protocol_pending("blinding or an explicit non-applicability rationale")),
            "batch_control": experiment_protocol_value(context, "replication_and_bias_control", "batch_control", experiment_protocol_pending("batch-control plan")),
        },
        "analysis_plan": {
            "statistical_test": experiment_protocol_value(context, "analysis_plan", "statistical_test", experiment_protocol_pending("statistical or model-comparison test")),
            "multiple_testing_policy": experiment_protocol_value(context, "analysis_plan", "multiple_testing_policy", experiment_protocol_pending("multiple-testing policy or non-applicability rationale")),
            "effect_size": experiment_protocol_value(context, "analysis_plan", "effect_size", experiment_protocol_pending("effect-size estimand and minimum meaningful magnitude")),
            "confidence_interval": experiment_protocol_value(context, "analysis_plan", "confidence_interval", experiment_protocol_pending("confidence or credible interval requirement")),
            "power_analysis_assumptions": experiment_protocol_value(context, "analysis_plan", "power_analysis_assumptions", experiment_protocol_pending("power-analysis assumptions and planned sample size")),
        },
        "success_criteria": {
            "minimum_meaningful_effect_size": experiment_protocol_value(context, "success_criteria", "minimum_meaningful_effect_size", experiment_protocol_pending("the minimum meaningful effect size")),
            "confidence_interval_requirement": experiment_protocol_value(context, "success_criteria", "confidence_interval_requirement", experiment_protocol_pending("the confidence-interval requirement")),
            "preregistered_primary_endpoint": experiment_protocol_value(context, "success_criteria", "preregistered_primary_endpoint", experiment_protocol_pending("the pre-registered primary endpoint threshold")),
            "rescue_or_epistasis_requirement": experiment_protocol_value(context, "success_criteria", "rescue_or_epistasis_requirement", experiment_protocol_pending("the rescue or epistasis success pattern")),
        },
        "failure_criteria": {
            "minimum_meaningful_effect_size": experiment_protocol_value(context, "failure_criteria", "minimum_meaningful_effect_size", experiment_protocol_pending("the practically unacceptable effect-size range")),
            "confidence_interval_requirement": experiment_protocol_value(context, "failure_criteria", "confidence_interval_requirement", experiment_protocol_pending("the confidence interval that would rule out practical utility")),
            "primary_endpoint_failure": experiment_protocol_value(context, "failure_criteria", "primary_endpoint_failure", experiment_protocol_pending("the primary-endpoint failure rule")),
            "rescue_failure": experiment_protocol_value(context, "failure_criteria", "rescue_failure", experiment_protocol_pending("the rescue or epistasis failure rule")),
            "alternative_mechanism_preferred": experiment_protocol_value(context, "failure_criteria", "alternative_mechanism_preferred", experiment_protocol_pending("the comparison rule that would favor an alternative mechanism")),
            "replication_or_regime_shift_failure": experiment_protocol_value(context, "failure_criteria", "replication_or_regime_shift_failure", experiment_protocol_pending("the second-model, second-batch, or regime-shift failure rule")),
        },
        "alternative_explanations": alternatives,
        "regime_shift_tests": experiment_protocol_value(context, "", "regime_shift_tests", [experiment_protocol_pending("at least two regime-shift conditions")]),
        "data_and_code_reproducibility": {
            "data_management": experiment_protocol_value(context, "data_and_code_reproducibility", "data_management", experiment_protocol_pending("data management, provenance, and access plan")),
            "code_or_analysis_artifact": experiment_protocol_value(context, "data_and_code_reproducibility", "code_or_analysis_artifact", experiment_protocol_pending("versioned code, analysis, or instrument configuration artifact")),
            "environment_capture": experiment_protocol_value(context, "data_and_code_reproducibility", "environment_capture", experiment_protocol_pending("software, hardware, reagent, or instrument-environment capture")),
            "protocol_versioning": experiment_protocol_value(context, "data_and_code_reproducibility", "protocol_versioning", experiment_protocol_pending("versioned protocol and deviation log")),
        },
        "evidence_basis": {
            "supporting_references": list(gap.get("supporting_references") or [])[:8],
            "mechanism_boundary": str(idea.get("boundary") or candidate.get("boundary") or ""),
            "constraints_source": "project and idea experimental context",
        },
    }
    protocol["validation"] = validate_structured_experiment_protocol(protocol)
    return protocol


def structured_experiment_legacy_summary(protocol: dict[str, Any]) -> dict[str, str]:
    arms = protocol.get("experimental_arms", []) if isinstance(protocol.get("experimental_arms"), list) else []
    readouts = protocol.get("readouts", {}) if isinstance(protocol.get("readouts"), dict) else {}
    return {
        "setup": (
            f"Model system: {experiment_protocol_display_value(protocol.get('model_system'))}. "
            f"Intervention: {experiment_protocol_display_value(protocol.get('intervention'))}. "
            f"Time course: {experiment_protocol_display_value(protocol.get('time_course'))}."
        ),
        "metrics": experiment_protocol_display_value(readouts),
        "baselines": experiment_protocol_display_value(arms),
        "falsification_criteria": experiment_protocol_display_value(protocol.get("failure_criteria")),
    }


def build_minimal_falsifiable_hypothesis(
    project: dict[str, Any],
    idea: dict[str, Any],
    gap: dict[str, Any],
    components: dict[str, str],
) -> dict[str, Any]:
    """Build the MingLi-stage causal claim without pretending it is executable.

    This is intentionally smaller than :func:`build_structured_experiment_protocol`.
    At this point the system needs a source-bound intervention -> mediator ->
    outcome statement, a comparison, and a minimal failure condition.  Sample
    size, blinding, equipment, data governance, and the rest of the execution
    protocol belong after a hypothesis has survived the debate.
    """
    try:
        from ._socrates import (
            mechanism_comparison_is_usable,
            mechanism_falsification_is_usable,
            mechanism_output_is_usable,
        )
    except ImportError:
        from _socrates import (
            mechanism_comparison_is_usable,
            mechanism_falsification_is_usable,
            mechanism_output_is_usable,
        )
    contract = socrates_contract_for_gap(project, gap)
    readiness = contract.get("hypothesis_readiness") if isinstance(contract.get("hypothesis_readiness"), dict) else {}
    research_mode = str(readiness.get("research_mode") or "CONTROLLED_INTERVENTION")
    mode_contract = readiness.get("mode_contract") if isinstance(readiness.get("mode_contract"), dict) else {}
    normalized_chain = readiness.get("normalized_core_chain") if isinstance(readiness.get("normalized_core_chain"), dict) else {}
    scientific_gate = readiness.get("scientific_readiness_gate") if isinstance(readiness.get("scientific_readiness_gate"), dict) else {}
    bundle = gap.get("mechanism_evidence_bundle") if isinstance(gap.get("mechanism_evidence_bundle"), dict) else {}
    intervention_gate = idea.get("intervention_type_gate") if isinstance(idea.get("intervention_type_gate"), dict) else mingli_intervention_type_gate(project, gap, components)
    intervention = str(
        intervention_gate.get("selected_intervention")
        or normalized_chain.get("input_or_intervention")
        or ""
    ).strip()
    mediator = str(
        normalized_chain.get("mediator")
        or contract.get("proposed_mediator")
        or bundle.get("mediator")
        or ""
    ).strip()
    outcome = str(
        normalized_chain.get("observable_outcome")
        or contract.get("output")
        or bundle.get("outcome")
        or ""
    ).strip()
    comparison_audit = scientific_gate.get("comparison") if isinstance(scientific_gate.get("comparison"), dict) else {}
    falsification_audit = scientific_gate.get("falsification") if isinstance(scientific_gate.get("falsification"), dict) else {}
    comparison = str(
        comparison_audit.get("value") or contract.get("comparison") or bundle.get("comparison") or ""
    ).strip()
    falsification = str(
        falsification_audit.get("value") or contract.get("falsification") or bundle.get("falsification") or ""
    ).strip()
    mediator_gate = classify_mediator_candidate(mediator)
    mediator_specific = bool(mediator_gate.get("admissible_as_mediator"))
    mode_design_valid = bool(mode_contract.get("status") == "READY")
    design_evidence = bundle.get("research_design_evidence") if isinstance(bundle.get("research_design_evidence"), dict) else {}
    hypothesis_source_lineage = hypothesis_source_lineage_for_gap(project, gap)
    mode_claim_type = {
        "CONTROLLED_INTERVENTION": "intervention-mediated causal claim",
        "COMPUTATIONAL_INTERVENTION": "parameterized computational counterfactual",
        "OBSERVATIONAL_MODEL_DISCRIMINATION": "competing-model discriminating prediction",
        "INSTRUMENTATION_OR_MEASUREMENT": "measurement-transfer and uncertainty claim",
        "LABORATORY_CONSTRAINT": "laboratory parameter-constraint propagation claim",
        "NATURAL_EXPERIMENT_OR_QUASI_EXPERIMENT": "identified exposure-outcome causal claim",
        "THEORETICAL_OR_FORMAL": "assumption-bound formal prediction or counterexample claim",
    }.get(research_mode, "unresolved research-design claim")
    return {
        "version": "minimal_falsifiable_hypothesis_v2",
        "intervention": intervention,
        "mediator": mediator,
        "outcome": outcome,
        "comparison": comparison,
        "falsification": falsification,
        "source_gap_id": str(gap.get("gap_id") or ""),
        "sub_hypothesis_id": str(gap.get("sub_hypothesis_id") or ""),
        "research_mode": research_mode,
        "mode_specific_claim_type": mode_claim_type,
        "research_design_evidence": {
            "recommended_mode": design_evidence.get("recommended_mode") or research_mode,
            "supporting_fragment_ids": list(design_evidence.get("supporting_fragment_ids") or []),
            "source": design_evidence.get("source") or "",
            "mode_contract_required": dict(mode_contract.get("required") or {}),
        },
        "evidence_bundle_ids": list(bundle.get("direct_evidence_ids") or []),
        "hypothesis_source_lineage": hypothesis_source_lineage,
        "validation": {
            "direct_intervention": bool(intervention_gate.get("admissible")) if research_mode == "CONTROLLED_INTERVENTION" else True,
            "mode_specific_design": mode_design_valid,
            "specific_mediator": mediator_specific,
            "measurable_outcome": mechanism_output_is_usable(outcome),
            "comparison": mechanism_comparison_is_usable(comparison),
            "falsification": mechanism_falsification_is_usable(falsification),
            "intervention_type_gate": intervention_gate,
        },
    }


def validate_minimal_falsifiable_hypothesis(minimal: dict[str, Any]) -> dict[str, Any]:
    """Validate only the pre-protocol requirements for an initial hypothesis."""
    validation = minimal.get("validation") if isinstance(minimal.get("validation"), dict) else {}
    research_mode = str(minimal.get("research_mode") or "CONTROLLED_INTERVENTION")
    checks = {
        "mode_specific_design": bool(validation.get("mode_specific_design", research_mode == "CONTROLLED_INTERVENTION")),
        "specific_mediator": bool(validation.get("specific_mediator")),
        "measurable_outcome": bool(validation.get("measurable_outcome")),
        "comparison": bool(validation.get("comparison")),
        "minimal_falsification": bool(validation.get("falsification")),
        "same_subhypothesis_evidence": bool(minimal.get("sub_hypothesis_id") and minimal.get("evidence_bundle_ids")),
    }
    if research_mode == "CONTROLLED_INTERVENTION":
        checks["direct_intervention"] = bool(validation.get("direct_intervention"))
    missing = [name for name, passed in checks.items() if not passed]
    return {
        "verdict": "PASS" if not missing else "REJECT",
        "checks": checks,
        "missing": missing,
        "next_stage": (
            "Socratic debate; defer execution protocol planning until the hypothesis is accepted."
            if not missing else "Return to Socrates/TanXi; do not create a full execution protocol for this draft."
        ),
    }


def design_experiment(
    project_id: str,
    idea: dict[str, Any] | str = "",
    idea_id: str = "",
    constraints: str = "academic lab scale",
) -> str:
    try:
        from ._project import load_project, save_project
        from ._utils import new_id
    except ImportError:
        from _project import load_project, save_project
        from _utils import new_id
    project = load_project(project_id)
    idea_json = mingli_resolve_idea_json(project, idea=idea, idea_id=idea_id)
    gap = mingli_resolve_gap(project, gap_id=str(idea_json.get("gap_id") or ""))
    components = infer_gap_components(project, gap)
    protocol = build_structured_experiment_protocol(project, idea_json, gap, components, constraints=constraints)
    protocol_validation = validate_structured_experiment_protocol(protocol)
    protocol["validation"] = protocol_validation
    experiment = structured_experiment_legacy_summary(protocol)
    idea_json["experimental_protocol"] = protocol
    idea_json["experiments"] = experiment
    idea_json["risks"] = mingli_risk_text(gap, experiment)
    record = {
        "experiment_plan_id": new_id("exp"),
        "project_id": project_id,
        "idea_id": idea_id,
        "gap_id": gap.get("gap_id", ""),
        "constraints": constraints,
        "idea_json": idea_json,
        "structured_experiment_protocol": protocol,
        "protocol_validation": protocol_validation,
        "falsification_criteria": protocol.get("failure_criteria", {}),
        "createdAt": time.time(),
    }
    project.setdefault("mingli_experiment_plans", []).append(record)
    if idea_id:
        for draft in project.get("mingli_draft_ideas", []):
            if isinstance(draft, dict) and draft.get("draft_idea_id") == idea_id:
                draft["idea_json"] = idea_json
                draft["experiment_plan_id"] = record["experiment_plan_id"]
                draft["status"] = "experiment_designed" if protocol_validation["hard_gate_passed"] else "experiment_design_requires_expert_input"
                break
    project["updatedAt"] = time.time()
    save_project(project)
    next_step = (
        "Call finalize_idea; it will run mandatory uniqueness verification before persisting the hypothesis."
        if protocol_validation["hard_gate_passed"]
        else "Provide the listed expert inputs or explicit non-applicability rationales, then rerun design_experiment before finalizing."
    )
    return json.dumps(
        {
            "thought": "GeWu produced a structured, auditable experiment protocol and applied its execution hard gate.",
            "action": {"type": "design_experiment", "gap_id": gap.get("gap_id", ""), "constraints": constraints},
            **record,
            "next_step": next_step,
        },
        ensure_ascii=False,
        indent=2,
    )


def design_experiment_for_accepted_hypothesis(
    project_id: str,
    hypothesis_id: str,
    constraints: str = "academic lab scale",
) -> str:
    """Create the detailed execution protocol only after debate acceptance.

    Keeping this separate from ``finalize_idea`` makes the stage boundary
    auditable.  The planner can now honestly report missing power, blinding,
    instrumentation, or data-governance inputs without causing an otherwise
    valid early scientific hypothesis to be rejected.
    """
    try:
        from ._project import load_project, save_project
        from ._utils import new_id
    except ImportError:
        from _project import load_project, save_project
        from _utils import new_id
    project = load_project(project_id)
    hypothesis = next(
        (
            item for item in project.get("hypotheses", [])
            if isinstance(item, dict) and str(item.get("hypothesis_id") or "") == str(hypothesis_id or "")
        ),
        None,
    )
    if not isinstance(hypothesis, dict):
        raise ValueError(f"Unknown finalized hypothesis_id: {hypothesis_id}")
    idea = hypothesis.get("mingli_final_idea") if isinstance(hypothesis.get("mingli_final_idea"), dict) else {}
    if not idea and str(hypothesis.get("source_hypothesis_id") or ""):
        source_id = str(hypothesis.get("source_hypothesis_id") or "")
        source = next(
            (
                item for item in project.get("hypotheses", [])
                if isinstance(item, dict) and str(item.get("hypothesis_id") or "") == source_id
            ),
            {},
        )
        source_idea = source.get("mingli_final_idea") if isinstance(source.get("mingli_final_idea"), dict) else {}
        if source_idea:
            idea = dict(source_idea)
            idea["hypothesis"] = str(hypothesis.get("statement") or idea.get("hypothesis") or "")
            idea["abstract"] = str(hypothesis.get("mechanism") or idea.get("abstract") or "")
    if not idea:
        raise ValueError("Accepted-hypothesis experiment planning requires the persisted MingLi final idea.")
    gap = mingli_resolve_gap(project, gap_id=str(hypothesis.get("gap_id") or idea.get("gap_id") or ""))
    components = infer_gap_components(project, gap)
    protocol = build_structured_experiment_protocol(project, idea, gap, components, constraints=constraints)
    validation = validate_structured_experiment_protocol(protocol)
    protocol["validation"] = validation
    plan = {
        "experiment_plan_id": new_id("exp"),
        "project_id": project_id,
        "hypothesis_id": str(hypothesis_id),
        "gap_id": str(gap.get("gap_id") or ""),
        "constraints": constraints,
        "structured_experiment_protocol": protocol,
        "protocol_validation": validation,
        "createdAt": time.time(),
        "stage": "post_debate_execution_planning",
    }
    project.setdefault("mingli_experiment_plans", []).append(plan)
    hypothesis["experimental_protocol"] = protocol
    hypothesis["experimental_protocol_validation"] = validation
    hypothesis["experiment_plan_id"] = plan["experiment_plan_id"]
    hypothesis["experiment_execution_status"] = (
        "authorized_subject_to_institutional_approval"
        if validation.get("hard_gate_passed") else "requires_expert_input_after_debate"
    )
    project["updatedAt"] = time.time()
    save_project(project)
    log_event(
        "SCIENCE",
        "post_debate_execution_protocol_planned",
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        verdict=validation.get("verdict"),
    )
    return json.dumps(
        {
            "status": "planned" if validation.get("hard_gate_passed") else "requires_expert_input",
            "hypothesis_id": hypothesis_id,
            "experiment_plan": plan,
            "next_step": validation.get("next_action"),
        },
        ensure_ascii=False,
        indent=2,
    )

def detect_hypothesis_template(idea: dict[str, Any]) -> dict[str, Any]:
    """Detect if a hypothesis uses forbidden generic templates.

    Returns a dict with is_template (bool), matched_patterns (list), and severity.
    """
    hyp_text = " ".join(
        str(idea.get(k) or "") for k in ("title", "hypothesis", "abstract", "related_work")
    ).lower()

    forbidden_patterns = [
        ("conflicting claims", "generic conflicting-claims template"),
        ("retested under matched", "generic retest-under-matched-conditions template"),
        ("mechanism-stress intervention", "generic mechanism-stress template"),
        ("reaction yield, rate constant, selectivity", "generic cross-domain metric list"),
        ("stability, and functional outcome", "generic cross-domain metric list"),
    ]
    matched = []
    for pattern, label in forbidden_patterns:
        if pattern in hyp_text:
            matched.append(label)

    # Check for extreme genericness: hypothesis has no numbers, no units, no chemical formulas
    import re as _re
    has_specifics = bool(
        _re.search(r"\d+\.?\d*\s*(nm|μm|mm|°c|°C|mV|V|A|mol|wt%|at%|hrs?|hours?|cycles?|ppm|K)", hyp_text)
        or _re.search(r"[A-Z][a-z]{0,2}\d|[IVX]{2,}|Li[A-Z]|V\([IVX]+\)", hyp_text)
        or _re.search(r"\b\d+\s*%", hyp_text)
    )

    is_template = bool(matched) or (not has_specifics and len(hyp_text) > 50)
    return {
        "is_template": is_template,
        "matched_patterns": matched,
        "has_domain_specifics": has_specifics,
        "severity": "REJECT" if matched else ("WARN" if not has_specifics and len(hyp_text) > 50 else "OK"),
    }


def enforce_hypothesis_specificity(idea: dict[str, Any]) -> dict[str, Any]:
    """Enforce that a hypothesis contains domain-specific, non-template content.

    Checks 4 dimensions:
    - numerical_bounds: at least one concrete number, unit, or formula
    - operating_condition: a named controllable variable or regime
    - measurable_metric: a domain-specific measurable outcome (not a generic list)
    - causal_chain: an explicit causal or mechanistic pathway (not a vague link)

    Returns a dict with verdict (PASS / WARN / REJECT), per-dimension status,
    and a list of missing dimensions.
    """
    hyp_text = " ".join(
        str(idea.get(k) or "") for k in ("title", "hypothesis", "abstract", "related_work")
    ).lower()

    # --- numerical_bounds ---
    has_numbers = bool(
        re.search(r"\d+\.?\d*\s*(nm|μm|mm|°c|°C|mV|V|A|mol|wt%|at%|hrs?|hours?|cycles?|ppm|K|kPa|MPa|GHz|MHz|kHz|Hz|s\b|ms|μs)", hyp_text)
        or re.search(r"[A-Z][a-z]{0,2}\d|[IVX]{2,}|Li[A-Z]|V\([IVX]+\)", hyp_text)
        or re.search(r"\b\d+\s*%", hyp_text)
        or re.search(r"\b\d+\.\d+\b", hyp_text)
    )

    # --- operating_condition ---
    condition_markers = [
        "temperature", "pressure", "voltage", "concentration", "dose", "frequency",
        "flow rate", "pH", "humidity", "strain", "stress", "loading", "ratio",
        "time step", "sample size", "threshold", "regime", "boundary condition",
        "operating condition", "under the condition", "when", "while varying",
    ]
    has_condition = any(marker in hyp_text for marker in condition_markers)

    # --- measurable_metric ---
    generic_metric_lists = [
        "reaction yield, rate constant, selectivity",
        "stability, and functional outcome",
        "signal-to-noise ratio, resolution, specificity",
        "predictive accuracy, robustness, constraint satisfaction",
    ]
    has_specific_metric = True
    for generic in generic_metric_lists:
        if generic in hyp_text:
            has_specific_metric = False
            break
    if not has_specific_metric:
        # Check if there is at least one non-generic measurable term
        specific_metric_markers = [
            "yield", "conversion", "selectivity", "ee", "er",
            "accuracy", "precision", "recall", "f1", "auc", "rmse", "mae",
            "efficiency", "throughput", "latency", "bandwidth",
            "survival", "mortality", "incidence", "prevalence",
            "biomass", "diversity", "richness", "evenness",
            "conductivity", "resistivity", "capacitance", "impedance",
            "resolution", "sensitivity", "specificity", "limit of detection",
        ]
        has_specific_metric = any(marker in hyp_text for marker in specific_metric_markers)

    # --- causal_chain ---
    causal_markers = [
        "mechanism", "pathway", "causal", "because", "leads to",
        "results in", "triggers", "mediated by", "downstream",
        "upstream", "feedback", "cascade", "coupling",
    ]
    anti_causal = [
        "changes the information", "intervention, or representation pathway",
        "affects the system", "improves performance",
    ]
    has_causal = any(marker in hyp_text for marker in causal_markers) and not any(anti in hyp_text for anti in anti_causal)

    dimensions = {
        "numerical_bounds": has_numbers,
        "operating_condition": has_condition,
        "measurable_metric": has_specific_metric,
        "causal_chain": has_causal,
    }
    missing = [dim for dim, ok in dimensions.items() if not ok]

    if len(missing) == 0:
        verdict = "PASS"
    elif len(missing) <= 1:
        verdict = "WARN"
    else:
        verdict = "REJECT"

    return {
        "verdict": verdict,
        "dimensions": dimensions,
        "missing_dimensions": missing,
        "guidance": (
            f"Hypothesis is missing specificity in: {', '.join(missing)}. "
            "Add concrete numbers/units, a named operating condition, a domain-specific metric, "
            "and an explicit causal pathway."
            if missing else "Hypothesis passes all specificity checks."
        ),
    }


def is_core_mechanism_entity(project: dict[str, Any], value: str) -> bool:
    try:
        from ._gap_detection import mechanism_entity_profile
        from ._literature_search import query_terms
    except ImportError:
        from _gap_detection import mechanism_entity_profile
        from _literature_search import query_terms
    profile = mechanism_entity_profile(project)
    terms = set(query_terms(value))
    if not terms or not profile.get("record_count"):
        return False
    return bool(terms & set(profile.get("entities", [])))


def mingli_acceptance_check(idea: dict[str, Any], gap: dict[str, Any]) -> dict[str, Any]:
    """Apply only the generation-stage contract for a MingLi hypothesis.

    MingLi must make a grounded, falsifiable scientific claim, but it must not
    be asked to complete YanZhen's mechanism audit.  In particular, detailed
    dynamics, reversibility, counterfactual stress tests, and independent
    observations are deliberately deferred to the verifier and debate stages.
    """
    hypothesis_package = idea.get("hypothesis_package") if isinstance(idea.get("hypothesis_package"), dict) else {}
    try:
        from ._hypothesis_coverage import coverage_and_compatibility_gate
    except ImportError:
        from _hypothesis_coverage import coverage_and_compatibility_gate
    package_gate = coverage_and_compatibility_gate(hypothesis_package) if hypothesis_package else {}
    package_ready = not hypothesis_package or package_gate.get("ready") is True
    minimal = idea.get("minimal_falsifiable_hypothesis") if isinstance(idea.get("minimal_falsifiable_hypothesis"), dict) else {}
    if minimal:
        minimal_validation = validate_minimal_falsifiable_hypothesis(minimal)
        checks = {
            **dict(minimal_validation.get("checks") or {}),
            "papergraph_grounding": bool([
                ref for ref in gap.get("supporting_references", []) if str(ref).strip()
            ]),
            "hypothesis_package_coverage": package_ready,
        }
        missing = [name for name, passed in checks.items() if not passed]
        return {
            "verdict": "PASS" if not missing else "REJECT",
            "checks": checks,
            "intervention_type_gate": ((minimal.get("validation") or {}).get("intervention_type_gate") or {}),
            "missing": missing,
            "minimal_falsifiable_hypothesis": minimal,
            "deferred_to_yanzhen": [
                "sample_size", "randomization", "blinding", "data_management", "equipment_configuration",
                "detailed_dynamics", "reversibility", "full_protocol_controls",
            ],
            "hypothesis_package": hypothesis_package,
            "coverage_and_compatibility_gate": package_gate,
            "guidance": (
                "The minimal causal hypothesis passes. Debate it before constructing the execution-level protocol."
                if not missing else "Return to Socrates/TanXi; missing minimal causal requirements: " + ", ".join(missing)
            ),
        }

    hypothesis_text = " ".join(
        str(idea.get(key) or "")
        for key in ("hypothesis", "abstract")
    ).lower()
    causal_chain = idea.get("causal_chain")
    chain_items = [str(item).strip() for item in causal_chain] if isinstance(causal_chain, list) else []
    experiments = idea.get("experiments") if isinstance(idea.get("experiments"), dict) else {}
    intervention_gate = idea.get("intervention_type_gate") if isinstance(idea.get("intervention_type_gate"), dict) else {}
    if not intervention_gate:
        protocol = idea.get("experimental_protocol") if isinstance(idea.get("experimental_protocol"), dict) else {}
        intervention = protocol.get("intervention") if isinstance(protocol.get("intervention"), dict) else {}
        gate_candidates: list[dict[str, Any]] = [
            {
                "candidate": f"{intervention.get('modality', '')} {intervention.get('target', '')}",
                "candidate_source": "experimental_protocol.intervention",
            }
        ]
        if isinstance(idea.get("controllable_variables"), list):
            gate_candidates.extend(
                {"candidate": value, "candidate_source": "idea.controllable_variables"}
                for value in idea.get("controllable_variables", [])
                if str(value).strip()
            )
        intervention_gate = intervention_gate_from_values(gate_candidates)

    causal_markers = (
        "mechanism", "pathway", "mediated", "through", "because", "leads to",
        "results in", "triggers", "causal", "bridge",
    )
    falsification_markers = (
        "falsif", "reject", "refute", "negative control", "does not", "fail if",
    )
    has_mechanism = (
        len(chain_items) >= 2
        and any(marker in hypothesis_text for marker in causal_markers)
    )
    has_falsification = (
        any(marker in hypothesis_text for marker in falsification_markers)
        or bool(str(experiments.get("falsification_criteria") or "").strip())
    )
    has_grounding = bool([
        ref for ref in gap.get("supporting_references", [])
        if str(ref).strip()
    ])
    has_test_plan = all(str(experiments.get(key) or "").strip() for key in ("setup", "metrics", "baselines"))

    checks = {
        "testable_mechanism": has_mechanism,
        "falsification_condition": has_falsification,
        "papergraph_grounding": has_grounding,
        "executable_test_plan": has_test_plan,
        "direct_intervention_ontology": bool(intervention_gate.get("admissible")),
    }
    missing = [name for name, passed in checks.items() if not passed]
    return {
        "verdict": "PASS" if not missing else "REJECT",
        "checks": checks,
        "intervention_type_gate": intervention_gate,
        "missing": missing,
        "deferred_to_yanzhen": [
            "concrete_mediator", "scope", "dynamics", "intervention",
            "counterfactual", "reversibility", "two_independent_observations",
            "cross_domain_structure_mapping", "null_hypothesis",
            "alternative_hypothesis", "three_testable_subhypotheses",
        ],
        "guidance": (
            "MingLi needs only a testable mechanism, a falsification condition, at least one PaperGraph reference, and an executable test plan. "
            "Detailed mechanism operationalization belongs to YanZhen and the Socratic debate."
            if not missing
            else "Complete only these MingLi-stage requirements: " + ", ".join(missing)
        ),
    }


def check_hypothesis_evidence_alignment(idea: dict[str, Any], papergraph: list[dict[str, Any]]) -> dict[str, Any]:
    """Check if a hypothesis is anchored to the PaperGraph's core topics.

    Extracts significant terms from the hypothesis and checks overlap with
    PaperGraph paper titles/abstracts. Returns a verdict and details.
    """
    # Build hypothesis text
    hyp_text = " ".join(
        str(idea.get(k) or "") for k in ("title", "hypothesis", "abstract", "related_work")
    ).lower()

    if not hyp_text.strip():
        return {"verdict": "ALIGNED", "score": 1.0, "reason": "empty hypothesis text"}

    # Extract significant terms from hypothesis (skip stopwords and short words)
    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "dare", "ought",
        "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
        "into", "through", "during", "before", "after", "above", "below",
        "between", "and", "but", "or", "nor", "not", "so", "yet", "both",
        "either", "neither", "each", "every", "all", "any", "few", "more",
        "most", "other", "some", "such", "no", "only", "own", "same",
        "than", "too", "very", "just", "because", "if", "when", "where",
        "how", "what", "which", "who", "whom", "this", "that", "these",
        "those", "it", "its", "we", "our", "their", "they", "them",
        "then", "about", "up", "out", "under", "over", "again", "further",
        "once", "here", "there", "also", "while", "although", "though",
        "however", "therefore", "thus", "hence", "since", "until",
        "study", "research", "method", "approach", "paper", "based",
        "using", "used", "new", "novel", "propose", "proposed", "show",
        "results", "analysis", "model", "system", "data", "use",
    }
    words = re.findall(r"[a-z][a-z\-]{2,}", hyp_text)
    hyp_terms = [w for w in words if w not in stopwords and len(w) > 2]

    if not hyp_terms:
        return {"verdict": "ALIGNED", "score": 1.0, "reason": "no significant terms extracted"}

    # Build PaperGraph corpus (titles + abstracts)
    pg_text = " ".join(
        str(p.get("title") or "") + " " + str(p.get("abstract") or "")
        for p in papergraph
        if isinstance(p, dict)
    ).lower()

    if not pg_text.strip():
        return {"verdict": "ALIGNED", "score": 1.0, "reason": "empty PaperGraph"}

    # Check overlap: how many hypothesis terms appear in PaperGraph
    matched = [t for t in set(hyp_terms) if t in pg_text]
    score = len(matched) / max(1, len(set(hyp_terms)))

    if score >= 0.3:
        verdict = "ALIGNED"
    elif score >= 0.15:
        verdict = "PARTIAL"
    else:
        verdict = "DRIFTED"

    return {
        "verdict": verdict,
        "score": round(score, 3),
        "hypothesis_terms": sorted(set(hyp_terms))[:20],
        "matched_terms": sorted(matched)[:20],
        "papergraph_paper_count": len([p for p in papergraph if isinstance(p, dict)]),
        "reason": (
            f"{len(matched)}/{len(set(hyp_terms))} hypothesis terms found in PaperGraph"
            + (f" (matched: {', '.join(sorted(matched)[:10])})" if matched else "")
        ),
    }


def finalize_idea(
    project_id: str,
    idea_json: dict[str, Any] | str = "",
    idea_id: str = "",
    live_search: bool = False,
    providers: list[str] | None = None,
) -> str:
    try:
        from ._models import Hypothesis
        from ._pipeline import verify_uniqueness
        from ._project import default_literature_providers, load_project, save_project
        from ._utils import new_id
    except ImportError:
        from _models import Hypothesis
        from _pipeline import verify_uniqueness
        from _project import default_literature_providers, load_project, save_project
        from _utils import new_id
    project = load_project(project_id)
    idea = mingli_resolve_idea_json(project, idea=idea_json, idea_id=idea_id)
    gap_id = str(idea.get("gap_id") or "")
    gap = mingli_resolve_gap(project, gap_id=gap_id)
    final_claim_disclaimer = final_object_claim_disclaimer(
        gap,
        idea.get("hypothesis_package") if isinstance(idea.get("hypothesis_package"), dict) else {},
    )
    if final_claim_disclaimer:
        idea["final_object_claim_disclaimer"] = final_claim_disclaimer
    hierarchy_present = bool(
        idea.get("hierarchical_search")
        or idea.get("scientific_hypothesis_hierarchy")
    )
    if hierarchy_present:
        hierarchy_audit = audit_hierarchical_candidate(idea)
        if not hierarchy_audit.get("hard_gate_passed"):
            rejected = {
                "status": "rejected_scientific_hypothesis_hierarchy",
                "reason": (
                    "The five-layer hypothesis no longer matches its frozen upstream contract "
                    "or fails an ontology, operationalization, parameter-provenance, validation, "
                    "safety, or reproducibility hard gate."
                ),
                "idea_json": idea,
                "hierarchical_gate": hierarchy_audit,
                "gap_id": gap_id,
            }
            project.setdefault("mingli_rejected_ideas", []).append(rejected)
            project["updatedAt"] = time.time()
            save_project(project)
            log_event(
                "WARN",
                "hypothesis_rejected_scientific_hierarchy",
                gap_id=gap_id,
            )
            return json.dumps(rejected, ensure_ascii=False, indent=2)
        idea["hierarchical_gate"] = hierarchy_audit
    missing = mingli_final_schema_missing(idea)
    if missing:
        raise ValueError(f"finalize_idea requires complete MingLi JSON; missing: {', '.join(missing)}")
    components = infer_gap_components(project, gap)
    minimal = (
        idea.get("minimal_falsifiable_hypothesis")
        if isinstance(idea.get("minimal_falsifiable_hypothesis"), dict)
        else build_minimal_falsifiable_hypothesis(project, idea, gap, components)
    )
    minimal_validation = validate_minimal_falsifiable_hypothesis(minimal)
    intervention_gate = (
        (minimal.get("validation") or {}).get("intervention_type_gate")
        if isinstance(minimal.get("validation"), dict)
        else {}
    )
    if not isinstance(intervention_gate, dict) or not intervention_gate.get("admissible"):
        rejected = {
            "status": "rejected_intervention_ontology",
            "reason": (
                "The proposed intervention is an epistemic/observational method, measurement resource, "
                "generic placeholder, or otherwise lacks a concrete manipulable operation."
            ),
            "idea_json": idea,
            "intervention_type_gate": intervention_gate,
            "minimal_falsifiable_hypothesis": minimal,
            "gap_id": gap_id,
        }
        project.setdefault("mingli_rejected_ideas", []).append(rejected)
        project["updatedAt"] = time.time()
        save_project(project)
        log_event("WARN", "hypothesis_rejected_intervention_ontology", gap_id=gap_id)
        return json.dumps(rejected, ensure_ascii=False, indent=2)
    if minimal_validation.get("verdict") != "PASS":
        rejected = {
            "status": "rejected_minimal_falsifiability",
            "reason": "MingLi initial hypotheses require an intervention, specific mediator, measurable outcome, comparison, and observable falsifier before protocol planning.",
            "idea_json": idea,
            "minimal_falsifiable_hypothesis": minimal,
            "minimal_falsifiability_validation": minimal_validation,
            "gap_id": gap_id,
        }
        project.setdefault("mingli_rejected_ideas", []).append(rejected)
        project["updatedAt"] = time.time()
        save_project(project)
        log_event("WARN", "hypothesis_rejected_minimal_falsifiability", gap_id=gap_id, missing=minimal_validation.get("missing"))
        return json.dumps(rejected, ensure_ascii=False, indent=2)
    idea["minimal_falsifiable_hypothesis"] = minimal
    idea["experiment_planning_status"] = "deferred_until_debate_acceptance"
    experimental_protocol: dict[str, Any] = {}
    experimental_protocol_validation = {
        "verdict": "DEFERRED_UNTIL_DEBATE_ACCEPTANCE",
        "hard_gate_passed": False,
        "execution_authorized": False,
        "reason": "The complete execution protocol is intentionally planned only after a minimally falsifiable hypothesis survives debate.",
    }
    semantic_gate = idea.get("semantic_plausibility") if isinstance(idea.get("semantic_plausibility"), dict) else {}
    if semantic_gate.get("verdict") == "REJECT":
        rejected = {
            "status": "rejected_semantic_plausibility",
            "reason": "MingLi idea failed method-scenario semantic plausibility gate; regenerate with an explicit bridge mechanism.",
            "idea_json": idea,
            "semantic_plausibility": semantic_gate,
            "gap_id": gap_id,
        }
        project.setdefault("mingli_rejected_ideas", []).append(rejected)
        project["updatedAt"] = time.time()
        save_project(project)
        return json.dumps(rejected, ensure_ascii=False, indent=2)

    verification_text = " ".join(str(idea.get(key) or "") for key in ("title", "hypothesis", "abstract", "related_work"))
    uniqueness = json.loads(
        verify_uniqueness(
            project_id,
            verification_text,
            precision="high",
            live_search=live_search,
            providers=providers or default_literature_providers(domain=str(project.get("domain", "")), query=verification_text),
            # Finalization owns this project snapshot and writes it once
            # below. Do not advance state_version in a nested audit save.
            project_snapshot=project,
            persist=False,
        )
    )
    # Preserve the normal uniqueness audit, but commit it atomically with the
    # hypothesis rather than from a separate stale writer.
    project.setdefault("uniqueness_checks", []).append(uniqueness)
    live_summary = uniqueness.get("live_search") if isinstance(uniqueness.get("live_search"), dict) else {}
    if live_search and live_summary.get("status") == "error":
        failed = {
            "status": "verification_failed",
            "reason": "Mandatory live literature verification failed; do not finalize until search succeeds.",
            "idea_json": idea,
            "uniqueness_check": uniqueness,
            "gap_id": gap_id,
        }
        project.setdefault("mingli_rejected_ideas", []).append(failed)
        project["updatedAt"] = time.time()
        save_project(project)
        return json.dumps(failed, ensure_ascii=False, indent=2)
    if uniqueness.get("verdict") == "overlap_risk":
        rejected = {
            "status": "rejected_overlap",
            "reason": "Mandatory novelty verification found high local overlap; regenerate or structurally mutate the idea.",
            "idea_json": idea,
            "uniqueness_check": uniqueness,
            "gap_id": gap_id,
        }
        project.setdefault("mingli_rejected_ideas", []).append(rejected)
        project["updatedAt"] = time.time()
        save_project(project)
        return json.dumps(rejected, ensure_ascii=False, indent=2)

    # Template detection: reject hypotheses that use forbidden generic structures
    template_check = detect_hypothesis_template(idea)
    if template_check.get("severity") == "REJECT":
        rejected = {
            "status": "rejected_template",
            "reason": (
                "Hypothesis uses a forbidden generic template. "
                f"Matched patterns: {', '.join(template_check.get('matched_patterns', []))}. "
                "Regenerate with domain-specific variables, metrics, and concrete mechanisms."
            ),
            "template_check": template_check,
            "idea_json": idea,
            "gap_id": gap_id,
        }
        project.setdefault("mingli_rejected_ideas", []).append(rejected)
        project["updatedAt"] = time.time()
        save_project(project)
        log_event("WARN", "hypothesis_rejected_template", gap_id=gap_id, patterns=template_check.get("matched_patterns"))
        return json.dumps(rejected, ensure_ascii=False, indent=2)

    # Specificity is a useful diagnostic, but numerical/detail requirements belong
    # to YanZhen and the debate rather than MingLi's initial acceptance gate.
    specificity_check = enforce_hypothesis_specificity(idea)
    mingli_acceptance = mingli_acceptance_check(idea, gap)
    if mingli_acceptance.get("verdict") == "REJECT":
        rejected = {
            "status": "rejected_mingli_acceptance",
            "reason": (
                "Hypothesis is missing a required MingLi-stage element. "
                f"Missing: {', '.join(mingli_acceptance.get('missing', []))}. "
                "Do not attempt the YanZhen mechanism-audit checklist at this stage."
            ),
            "mingli_acceptance": mingli_acceptance,
            "specificity_check": specificity_check,
            "template_check": template_check,
            "idea_json": idea,
            "gap_id": gap_id,
        }
        project.setdefault("mingli_rejected_ideas", []).append(rejected)
        project["updatedAt"] = time.time()
        save_project(project)
        log_event("WARN", "hypothesis_rejected_mingli_acceptance", gap_id=gap_id, missing=mingli_acceptance.get("missing"))
        return json.dumps(rejected, ensure_ascii=False, indent=2)
    if specificity_check.get("verdict") == "REJECT":
        log_event(
            "WARN",
            "mingli_specificity_deferred",
            gap_id=gap_id,
            missing=specificity_check.get("missing_dimensions"),
        )

    hypothesis = Hypothesis(
        hypothesis_id=new_id("hyp"),
        gap_id=gap_id,
        statement=str(idea.get("hypothesis") or ""),
        mechanism=str(idea.get("abstract") or ""),
        expected_value=str(idea.get("related_work") or ""),
        test_plan=json.dumps(idea.get("experiments", {}), ensure_ascii=False),
        status="finalized",
    )
    # Evidence alignment check
    papergraph = project.get("papergraph", [])
    alignment = check_hypothesis_evidence_alignment(idea, papergraph)
    if alignment.get("verdict") == "DRIFTED":
        log_event(
            "WARN",
            "hypothesis_evidence_drift",
            project_id=project_id,
            score=alignment.get("score"),
            reason=alignment.get("reason"),
        )

    payload = asdict(hypothesis)
    payload.update(
        {
            "mingli_final_idea": idea,
            "uniqueness_check": uniqueness,
            "source_gap": gap,
            "socrates_mechanism_contract": idea.get("socrates_mechanism_contract", {}),
            "hypothesis_package": idea.get("hypothesis_package", {}),
            "coverage_audit": idea.get("coverage_audit", {}),
            "compatibility_audit": idea.get("compatibility_audit", {}),
            "conclusion_scope": idea.get("conclusion_scope", {}),
            "final_object_claim_disclaimer": final_claim_disclaimer,
            "parent_hypothesis_id": idea.get("parent_hypothesis_id"),
            "tournament_generation": idea.get("tournament_generation", 1),
            "lineage": idea.get("lineage", []),
            "evidence_alignment": alignment,
            "template_check": template_check,
            "specificity_check": specificity_check,
            "mingli_acceptance": mingli_acceptance,
            "minimal_falsifiable_hypothesis": minimal,
            "minimal_falsifiability_validation": minimal_validation,
            "experimental_protocol": experimental_protocol,
            "experimental_protocol_validation": experimental_protocol_validation,
            "experiment_execution_status": "deferred_until_debate_acceptance",
            "scientific_hypothesis_hierarchy": idea.get("scientific_hypothesis_hierarchy", {}),
            "hierarchical_search": idea.get("hierarchical_search", {}),
            "hierarchical_gate": idea.get("hierarchical_gate", {}),
            "hierarchy_schema_version": idea.get("hierarchy_schema_version", ""),
            "constraints_checked": {
                "traceable_to_gap": bool(gap_id),
                "papergraph_grounded": bool(gap.get("supporting_references")),
                "mandatory_uniqueness_verification": True,
                "live_literature_verification": bool(live_search),
                "minimal_hypothesis_has_intervention_mediator_outcome_comparison_falsifier": True,
                "evidence_alignment_verdict": alignment.get("verdict"),
                "evidence_alignment_score": alignment.get("score"),
                "template_severity": template_check.get("severity"),
                "has_domain_specifics": template_check.get("has_domain_specifics"),
                "specificity_verdict": specificity_check.get("verdict"),
                "specificity_missing": specificity_check.get("missing_dimensions", []),
                "mingli_acceptance_verdict": mingli_acceptance.get("verdict"),
                "mingli_acceptance_missing": mingli_acceptance.get("missing", []),
                "scientific_hypothesis_hierarchy": (
                    idea.get("hierarchical_gate", {}).get("verdict")
                    if isinstance(idea.get("hierarchical_gate"), dict)
                    else "LEGACY_NOT_PRESENT"
                ),
                "frozen_scientific_contract": bool(
                    (idea.get("hierarchical_search", {}) or {}).get("contract_signature")
                ),
                "unsupported_precise_values_policy": "TO_BE_OPTIMIZED",
                "structured_experiment_protocol_hard_gate": "DEFERRED_UNTIL_DEBATE_ACCEPTANCE",
                "final_object_claim_disclaimer": final_claim_disclaimer,
            },
        }
    )
    project.setdefault("hypotheses", []).append(payload)
    project.setdefault("mingli_finalized_ideas", []).append(payload)
    if idea_id:
        for draft in project.get("mingli_draft_ideas", []):
            if isinstance(draft, dict) and draft.get("draft_idea_id") == idea_id:
                draft["status"] = "finalized"
                draft["hypothesis_id"] = hypothesis.hypothesis_id
                break
    project["phase"] = "Hypothesis Generation"
    project["updatedAt"] = time.time()
    save_project(project)
    log_event("SCIENCE", "mingli_idea_finalized", project_id=project_id, hypothesis_id=hypothesis.hypothesis_id, gap_id=gap_id)
    return json.dumps(
        {
            "status": "finalized",
            "hypothesis_id": hypothesis.hypothesis_id,
            "finalized_idea": idea,
            "uniqueness_check": uniqueness,
            "stored_hypothesis": payload,
            "final_object_claim_disclaimer": final_claim_disclaimer,
        },
        ensure_ascii=False,
        indent=2,
    )

def mingli_resolve_gap(project: dict[str, Any], gap: dict[str, Any] | str = "", gap_id: str = "") -> dict[str, Any]:
    try:
        from ._gap_detection import classify_scientific_gap_track, dedupe_knowledge_gaps, parse_gap_input
        from ._utils import find_by_id
    except ImportError:
        from _gap_detection import classify_scientific_gap_track, dedupe_knowledge_gaps, parse_gap_input
        from _utils import find_by_id
    gaps = [item for item in project.get("knowledge_gaps", []) if isinstance(item, dict)]
    tanxi = project.get("tanxi_gap_analysis", {}) if isinstance(project.get("tanxi_gap_analysis"), dict) else {}
    tanxi_ranked = [item for item in tanxi.get("ranked_gaps", []) if isinstance(item, dict)]
    # Resolve an explicit foreign key before semantic deduplication. Similar
    # TanXi gaps may intentionally carry different ids and evidence contracts;
    # deduping first can keep an older canonical id and make a freshly selected
    # ranked id appear to be unknown.
    exact_candidates = tanxi_ranked + gaps

    def _allows_mingli_seed(candidate: dict[str, Any]) -> bool:
        triage = classify_scientific_gap_track(candidate)
        if triage.get("eligible_for_hypothesis_generation"):
            return True
        candidate_gap_id = str(candidate.get("gap_id") or "")
        if not candidate_gap_id:
            return False
        package_resolution = hypothesis_package_gate(project, candidate_gap_id)
        package = package_resolution["package"]
        gate = package_resolution["gate"]
        return bool(
            str(package.get("package_type") or package.get("hypothesis_package_type") or "") == "restricted_component_bridge"
            and gate.get("ready") is True
            and gate.get("status") == "READY_FOR_RESTRICTED_MINGLI"
            and package.get("may_support_final_object_claim") is not True
            and str(package.get("claim_strength_cap") or "") == "no_final_object_claim_validation"
            and package.get("post_draft_socrates_enrichment_required") is True
            and (
                candidate.get("restricted_component_bridge_hypothesis_allowed") is True
                or candidate.get("component_bridge_gap_synthesis_ready") is True
            )
        )

    if gap_id:
        found = find_by_id(exact_candidates, "gap_id", gap_id)
        if found is None:
            found = next(
                (
                    item for item in exact_candidates
                    if str(gap_id) in {
                        str(value).strip()
                        for value in (item.get("merged_gap_ids") or [])
                        if str(value or "").strip()
                    }
                ),
                None,
            )
        if found is None:
            raise ValueError(f"Unknown gap_id for project {project.get('project_id', '')}: {gap_id}")
        if not _allows_mingli_seed(found):
            raise ValueError("The requested gap is neither a primary scientific gap nor a policy-complete restricted component-bridge package.")
        return found
    all_gaps = dedupe_knowledge_gaps(exact_candidates)
    if isinstance(gap, dict) and gap:
        parsed = parse_gap_input(gap)
        if parsed.get("gap_id"):
            found = find_by_id(all_gaps, "gap_id", str(parsed.get("gap_id")))
            selected_gap = found or parsed
            if not _allows_mingli_seed(selected_gap):
                raise ValueError("A secondary research opportunity cannot directly seed a MingLi hypothesis unless it is a policy-complete restricted component-bridge package.")
            return selected_gap
        if not _allows_mingli_seed(parsed):
            raise ValueError("A secondary research opportunity cannot directly seed a MingLi hypothesis unless it is a policy-complete restricted component-bridge package.")
        return parsed
    if isinstance(gap, str) and gap.strip():
        parsed = parse_gap_input(gap)
        if parsed.get("gap_id"):
            found = find_by_id(all_gaps, "gap_id", str(parsed.get("gap_id")))
            selected_gap = found or parsed
            if not _allows_mingli_seed(selected_gap):
                raise ValueError("A secondary research opportunity cannot directly seed a MingLi hypothesis unless it is a policy-complete restricted component-bridge package.")
            return selected_gap
        if not _allows_mingli_seed(parsed):
            raise ValueError("A secondary research opportunity cannot directly seed a MingLi hypothesis unless it is a policy-complete restricted component-bridge package.")
        return parsed
    selected = select_gaps_for_hypothesis(project, None)
    if not selected:
        selected = [
            item for item in tanxi_ranked
            if classify_scientific_gap_track(item)["eligible_for_hypothesis_generation"]
            and bool((item.get("mechanism_relevance") or {}).get("eligible_for_mechanism_hypothesis"))
        ][:1]
    if not selected:
        selected = [item for item in exact_candidates if _allows_mingli_seed(item)][:1]
    if not selected:
        raise ValueError(
            "No primary scientific gap with core evidence is available for MingLi. "
            "Use secondary opportunities to expand measurement or benchmark evidence, then rerun TanXi."
        )
    return selected[0]

def mingli_fallback_gap_from_papergraph(project: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._gap_detection import assess_gap_dict, detect_gap_signal_gaps, detect_mechanism_issue_gaps, make_gap, record_reference
        from ._pipeline import project_records_for_mapping
        from ._utils import normalize_label
    except ImportError:
        from _gap_detection import assess_gap_dict, detect_gap_signal_gaps, detect_mechanism_issue_gaps, make_gap, record_reference
        from _pipeline import project_records_for_mapping
        from _utils import normalize_label
    mechanism = detect_mechanism_issue_gaps(project, limit=1)
    if mechanism:
        return mechanism[0]
    signals = detect_gap_signal_gaps(project, limit=1)
    if signals:
        return signals[0]
    records = project_records_for_mapping(project)
    if not records:
        return {}
    record = records[0]
    citation = record_reference(record)
    method = normalize_label(record.get("method", "")) or "the reported method"
    scenario = normalize_label(record.get("scenario", "")) or normalize_label(project.get("domain", "")) or "the target system"
    benchmark = normalize_label(record.get("benchmark", "")) or "the primary performance metric"
    gap = make_gap(
        gap_type="mechanism_problem",
        description=(
            f"PaperGraph contains evidence for {method} in {scenario}, but no explicit source-grounded limitation or contradiction "
            f"was available for MingLi; require a mechanism-specific validation around {benchmark} before proposing a broad hypothesis."
        ),
        supporting_references=[citation] if citation else [],
        suggested_research_path=(
            f"Extract a concrete causal link from the source text, then test how a controllable variable in {method} changes {benchmark} "
            f"in {scenario} under matched controls."
        ),
        value_argument="This fallback preserves evidence traceability and prevents a matrix-only pseudo-gap from silently driving hypothesis generation.",
    )
    return assess_gap_dict(project, gap)

def mingli_resolve_idea_json(project: dict[str, Any], idea: dict[str, Any] | str = "", idea_id: str = "") -> dict[str, Any]:
    try:
        from ._utils import trim_text
    except ImportError:
        from _utils import trim_text
    if idea_id:
        for collection_name in ("mingli_draft_ideas", "mingli_experiment_plans"):
            for item in project.get(collection_name, []):
                if isinstance(item, dict) and item.get("draft_idea_id") == idea_id:
                    value = item.get("idea_json")
                    if isinstance(value, dict):
                        return dict(value)
                if isinstance(item, dict) and item.get("experiment_plan_id") == idea_id:
                    value = item.get("idea_json")
                    if isinstance(value, dict):
                        return dict(value)
        raise ValueError(f"Unknown MingLi idea_id: {idea_id}")
    if isinstance(idea, dict):
        return dict(idea)
    if isinstance(idea, str) and idea.strip():
        try:
            parsed = json.loads(idea)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return {"title": trim_text(idea, 90), "hypothesis": idea}
    raise ValueError("Provide idea_json or idea_id.")

def mingli_candidate_to_idea_json(project: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    gap = candidate.get("source_gap") if isinstance(candidate.get("source_gap"), dict) else {}
    hypothesis_package = candidate.get("hypothesis_package") if isinstance(candidate.get("hypothesis_package"), dict) else {}
    try:
        from ._hypothesis_coverage import coverage_and_compatibility_gate
    except ImportError:
        from _hypothesis_coverage import coverage_and_compatibility_gate
    package_gate = coverage_and_compatibility_gate(hypothesis_package) if hypothesis_package else {}
    package_slots = hypothesis_package.get("slots") if isinstance(hypothesis_package.get("slots"), dict) else {}
    package_scope = hypothesis_package.get("conclusion_scope") if isinstance(hypothesis_package.get("conclusion_scope"), dict) else {}
    refs = gap.get("supporting_references", []) if isinstance(gap.get("supporting_references"), list) else []
    title = mingli_title_from_statement(str(candidate.get("statement", "")))
    experiments = candidate.get("verification_plan", {}) if isinstance(candidate.get("verification_plan"), dict) else {}
    components = infer_gap_components(project, gap)
    intervention_gate = (
        candidate.get("intervention_type_gate")
        if isinstance(candidate.get("intervention_type_gate"), dict)
        else mingli_intervention_type_gate(project, gap, components)
    )
    control_variable = str(intervention_gate.get("selected_intervention") or "REQUIRES_DIRECT_INTERVENTION_EVIDENCE")
    boundary = hypothesis_boundary_condition(gap)
    minimal = build_minimal_falsifiable_hypothesis(
        project,
        {
            "intervention_type_gate": intervention_gate,
            "hypothesis": str(candidate.get("statement") or ""),
        },
        gap,
        components,
    )
    # These legacy fields remain present for existing consumers, but now
    # describe only the minimum causal test.  They are not a 45-field protocol
    # and cannot trigger execution validation during MingLi finalization.
    legacy_experiments = {
        "setup": f"Apply {package_slots.get('input') or minimal.get('intervention') or control_variable} to the declared target system.",
        "metrics": str(package_slots.get("measurement") or minimal.get("outcome") or components["benchmark"]),
        "baselines": str(package_slots.get("comparison") or minimal.get("comparison") or "REQUIRES_EXPLICIT_COMPARISON"),
        "falsification_criteria": str(package_slots.get("falsification") or minimal.get("falsification") or "REQUIRES_MINIMAL_FALSIFICATION"),
    }
    scope_text = str(package_slots.get("scope") or "").strip()
    allowed_scope = ", ".join(str(item) for item in package_scope.get("allowed", []) if str(item))
    forbidden_scope = ", ".join(str(item) for item in package_scope.get("forbidden", []) if str(item))
    hierarchy_present = bool(
        candidate.get("hierarchical_search")
        or candidate.get("scientific_hypothesis_hierarchy")
    )
    hierarchical_gate = (
        audit_hierarchical_candidate(candidate)
        if hierarchy_present
        else {
            "verdict": "LEGACY_NOT_PRESENT",
            "hard_gate_passed": True,
        }
    )
    return {
        "title": title,
        "hypothesis": str(candidate.get("statement") or ""),
        "abstract": (
            f"This proposal addresses the PaperGraph gap '{gap.get('description', '')}'. "
            f"It hypothesizes a testable mechanism: {candidate.get('mechanism', '')} "
            f"The study is designed to be falsifiable through {candidate.get('test_plan', '')} "
            + (f"Its declared scope is {scope_text}. " if scope_text else "")
            + (f"Allowed conclusion strength: {allowed_scope}. " if allowed_scope else "")
            + (f"Forbidden extrapolations: {forbidden_scope}." if forbidden_scope else "")
        ),
        "related_work": (
            f"Grounding evidence comes from: {', '.join(str(ref) for ref in refs[:5]) or 'PaperGraph records requiring expansion'}. "
            "The proposal differs by testing the mapped gap directly with explicit baselines, ablations, and failure-mode criteria."
        ),
        "experiments": legacy_experiments,
        "minimal_falsifiable_hypothesis": minimal,
        "hypothesis_source_lineage": (
            hypothesis_package.get("hypothesis_source_lineage")
            if isinstance(hypothesis_package.get("hypothesis_source_lineage"), dict)
            else minimal.get("hypothesis_source_lineage")
        ),
        "experiment_planning_status": "deferred_until_debate_acceptance",
        "risks": mingli_risk_text(gap, experiments),
        "tournament_generation": int(candidate.get("generation") or 1),
        "parent_hypothesis_id": candidate.get("parent_hypothesis_id"),
        "gap_id": str(candidate.get("gap_id") or gap.get("gap_id") or ""),
        "lineage": candidate.get("lineage", []),
        "scores": candidate.get("scores", {}),
        "semantic_plausibility": candidate.get("semantic_plausibility", {}),
        "intervention_type_gate": intervention_gate,
        "socrates_mechanism_contract": candidate.get("socrates_mechanism_contract", {}),
        "hypothesis_package": hypothesis_package,
        "coverage_and_compatibility_gate": package_gate,
        "coverage_audit": hypothesis_package.get("coverage_audit", {}),
        "compatibility_audit": hypothesis_package.get("compatibility_audit", {}),
        "conclusion_scope": package_scope,
        "competing_mechanism_gap_ids": hypothesis_package.get("competing_mechanism_gap_ids", []),
        "causal_chain": candidate.get("causal_chain", []),
        "controllable_variables": [control_variable],
        "measurable_outputs": [str(package_slots.get("measurement") or components["benchmark"])],
        "boundary_conditions": [str(package_slots.get("boundary") or boundary)],
        "scientific_hypothesis_hierarchy": candidate.get("scientific_hypothesis_hierarchy", {}),
        "hierarchical_search": candidate.get("hierarchical_search", {}),
        "hierarchical_gate": hierarchical_gate,
        "hierarchy_schema_version": (
            HIERARCHY_VERSION if hierarchy_present else ""
        ),
    }

def mingli_title_from_statement(statement: str) -> str:
    try:
        from ._models import Hypothesis
        from ._utils import normalize_space, trim_text
    except ImportError:
        from _models import Hypothesis
        from _utils import normalize_space, trim_text
    clean = normalize_space(statement)
    clean = re.sub(r"^if\s+", "", clean, flags=re.IGNORECASE)
    clean = clean.split(", then", 1)[0]
    clean = clean.split(" will ", 1)[0]
    return trim_text(clean[:1].upper() + clean[1:] if clean else "Gap-Grounded Testable Hypothesis", 120)

def conservative_hypothesis_statement(candidate: dict[str, Any], components: dict[str, str]) -> str:
    gap = candidate.get("source_gap") if isinstance(candidate.get("source_gap"), dict) else {}
    variable = hypothesis_control_variable(gap, components["method"], components["scenario"])
    boundary = hypothesis_boundary_condition(gap)
    return (
        f"If {components['method']} is evaluated in {components['scenario']} while explicitly varying {variable}, "
        f"then {components['benchmark']} should identify the limiting boundary {boundary} against domain-standard baselines."
    )

def innovative_hypothesis_statement(candidate: dict[str, Any], components: dict[str, str], gap: dict[str, Any]) -> str:
    try:
        from ._utils import trim_text
    except ImportError:
        from _utils import trim_text
    bundle = gap.get("mechanism_evidence_bundle") if isinstance(gap.get("mechanism_evidence_bundle"), dict) else {}
    chain = bundle.get("causal_chain") if isinstance(bundle.get("causal_chain"), dict) else {}
    seed_contract = (
        gap.get("mechanism_seed_contract")
        if isinstance(gap.get("mechanism_seed_contract"), dict)
        else bundle.get("mechanism_seed_contract")
        if isinstance(bundle.get("mechanism_seed_contract"), dict)
        else {}
    )
    mechanism_seed = (
        seed_contract.get("mechanism_seed")
        if isinstance(seed_contract.get("mechanism_seed"), dict)
        else {}
    )

    def role_value(role: str, label: str) -> str:
        chain_entry = chain.get(role) if isinstance(chain.get(role), dict) else {}
        seed_entry = mechanism_seed.get(role) if isinstance(mechanism_seed.get(role), dict) else {}
        for candidate_value in (
            chain_entry.get("value"),
            chain_entry.get("candidate"),
            seed_entry.get("value"),
        ):
            value = str(candidate_value or "").strip()
            if value and value.lower() not in {"unresolved", "unknown", "none", "n/a"}:
                return value
        return f"unresolved {label}"

    intervention = role_value("input", "input")
    mediator = role_value("mediator", "mediator")
    outcome = role_value("outcome", "outcome")
    comparison = str(bundle.get("comparison") or gap.get("comparison") or "matched intervention-control conditions").strip()
    falsification = str(bundle.get("falsification") or gap.get("falsification") or "the specified outcome does not change under the matched comparison").strip()
    if str(gap.get("gap_type") or "") == "contradiction":
        return (
            f"If {intervention} is applied in {components['scenario']} against {comparison}, then {outcome} will distinguish "
            f"whether {mediator} explains the disagreement; reject this claim if {falsification}."
        )
    return (
        f"If {intervention} is applied in {components['scenario']} relative to {comparison}, then it will change {outcome} "
        f"through {mediator}; reject the hypothesis if {falsification}."
    )

def mingli_risk_text(gap: dict[str, Any], experiment: dict[str, Any]) -> str:
    risks = [
        "The mapped gap may be a retrieval or extraction artifact rather than a true scientific opening.",
        "The proposed mechanism may fail under ablation or regime-shift tests.",
        "Available datasets, instruments, or simulations may not expose the decisive variable cleanly.",
    ]
    if not gap.get("supporting_references"):
        risks.append("PaperGraph grounding is weak; collect stronger evidence before expensive experiments.")
    return " ".join(risks)

def mingli_final_schema_missing(idea: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in ("title", "hypothesis", "abstract", "related_work", "risks"):
        if not str(idea.get(key) or "").strip():
            missing.append(key)
    experiments = idea.get("experiments")
    if not isinstance(experiments, dict):
        missing.append("experiments")
    else:
        for key in ("setup", "metrics", "baselines"):
            if not str(experiments.get(key) or "").strip():
                missing.append(f"experiments.{key}")
    if "tournament_generation" not in idea:
        missing.append("tournament_generation")
    if "parent_hypothesis_id" not in idea:
        missing.append("parent_hypothesis_id")
    if not str(idea.get("gap_id") or "").strip():
        missing.append("gap_id")
    return missing

def create_hypothesis(
    project_id: str,
    gap_id: str,
    statement: str,
    mechanism: str,
    expected_value: str,
    test_plan: str,
) -> str:
    try:
        from ._models import Hypothesis
        from ._project import load_project, save_project
        from ._utils import new_id
    except ImportError:
        from _models import Hypothesis
        from _project import load_project, save_project
        from _utils import new_id
    project = load_project(project_id)
    if gap_id:
        mingli_resolve_gap(project, gap_id=gap_id)
    hypothesis = Hypothesis(
        hypothesis_id=new_id("hyp"),
        gap_id=gap_id,
        statement=statement,
        mechanism=mechanism,
        expected_value=expected_value,
        test_plan=test_plan,
    )
    project.setdefault("hypotheses", []).append(asdict(hypothesis))
    project["phase"] = "Hypothesis Generation"
    project["updatedAt"] = time.time()
    save_project(project)
    log_event("SCIENCE", "hypothesis_created", project_id=project_id, hypothesis_id=hypothesis.hypothesis_id)
    return json.dumps(asdict(hypothesis), ensure_ascii=False, indent=2)

