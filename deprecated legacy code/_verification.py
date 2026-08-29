from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any
import ast
import json
import math
import re
import time
import xml.etree.ElementTree as ET

try:
    from .log import log_event
    from ._intervention_ontology import intervention_gate_from_values
except ImportError:
    from log import log_event
    from _intervention_ontology import intervention_gate_from_values



def classify_method_domain(method_text: str) -> str:
    """Classify a method into a broad methodological family for adaptability checking."""
    lower = method_text.lower()
    statistical_markers = (
        "regression", "sem", "structural equation", "anova", "factor analysis",
        "path analysis", "mediation", "moderation", "latent variable", "survey",
        "questionnaire", "likert", "correlation", "variance", "hypothesis test",
        "t-test", "chi-square", "logistic", "probit",
    )
    computational_markers = (
        "neural network", "deep learning", "cnn", "rnn", "transformer", "gan",
        "reinforcement", "optimization", "simulation", "finite element", "molecular dynamics",
        "monte carlo", "dft", "density functional", "agent-based",
    )
    experimental_markers = (
        "spectroscopy", "microscopy", "chromatography", "diffraction", "xps",
        "tem", "sem imaging", "electrochemical", "impedance", "voltammetry",
        "synthesis", "characterization", "assay", "western blot", "pcr",
    )
    analytical_markers = (
        "thermodynamic", "kinetic", "mechanism", "rate equation", "mass balance",
        "energy balance", "transport", "diffusion", "reaction", "catalysis",
    )
    if any(marker in lower for marker in statistical_markers):
        return "statistical_modeling"
    if any(marker in lower for marker in computational_markers):
        return "computational_simulation"
    if any(marker in lower for marker in experimental_markers):
        return "experimental_characterization"
    if any(marker in lower for marker in analytical_markers):
        return "analytical_modeling"
    return "general"

def check_internal_consistency(
    hypothesis: str,
    reasoning_chain: list[str] | None = None,
) -> str:
    report = yanzhen_internal_consistency_report(hypothesis, reasoning_chain or [])
    return json.dumps(report, ensure_ascii=False, indent=2)

def check_data_consistency(
    hypothesis: str,
    cited_data: list[Any] | None = None,
    original_sources: list[Any] | None = None,
) -> str:
    report = yanzhen_data_consistency_report(hypothesis, cited_data or [], original_sources or [])
    return json.dumps(report, ensure_ascii=False, indent=2)

def regime_shift_test(
    mechanism: str,
    original_conditions: dict[str, Any] | None = None,
    shifted_conditions: list[dict[str, Any]] | list[str] | None = None,
) -> str:
    report = yanzhen_regime_shift_report(mechanism, original_conditions or {}, shifted_conditions or [])
    return json.dumps(report, ensure_ascii=False, indent=2)

def detect_selective_citation(
    cited_papers: list[Any] | None = None,
    full_paper_contexts: list[Any] | None = None,
) -> str:
    report = yanzhen_selective_citation_report(cited_papers or [], full_paper_contexts or [])
    return json.dumps(report, ensure_ascii=False, indent=2)

def causal_chain_audit(
    causal_chain: list[str] | None = None,
    evidence_for_each: list[Any] | None = None,
) -> str:
    report = yanzhen_causal_chain_report(causal_chain or [], evidence_for_each or [])
    return json.dumps(report, ensure_ascii=False, indent=2)


def yanzhen_claim_edges(hypothesis_record: dict[str, Any], reasoning_chain: list[str], mechanism: str) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for item in hypothesis_record.get("mechanism_edges", []) if isinstance(hypothesis_record.get("mechanism_edges"), list) else []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if source and target:
            edges.append({"source": source, "target": target, "relation": str(item.get("relation") or "leads_to")})
    contract = hypothesis_record.get("socrates_mechanism_contract") if isinstance(hypothesis_record.get("socrates_mechanism_contract"), dict) else {}
    if contract:
        source = str(contract.get("input") or "").strip()
        mediator = str(contract.get("proposed_mediator") or "").strip()
        target = str(contract.get("output") or "").strip()
        if source and mediator:
            edges.append({"source": source, "target": mediator, "relation": "acts_through"})
        if mediator and target:
            edges.append({"source": mediator, "target": target, "relation": "changes"})
    if not edges:
        for link in reasoning_chain[:3]:
            edges.append({"source": str(link), "target": "claimed outcome", "relation": "requires audit"})
    unique: dict[tuple[str, str, str], dict[str, str]] = {}
    for edge in edges:
        unique[(edge["source"], edge["target"], edge["relation"])] = edge
    return list(unique.values())[:6]


def yanzhen_counterevidence_query_plan(claim_edges: list[dict[str, str]], domain: str, limit: int = 3) -> list[dict[str, str]]:
    plan: list[dict[str, str]] = []
    for edge in claim_edges[:max(1, int(limit))]:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if not source or not target:
            continue
        plan.extend(
            [
                {"attack": "mediator_not_necessary", "claim": f"{source} -> {target}", "query": f"{source} {target} direct pathway mediator not necessary"},
                {"attack": "alternative_or_common_cause", "claim": f"{source} -> {target}", "query": f"{source} {target} alternative mechanism common cause confounding"},
                {"attack": "boundary_or_nonreplication", "claim": f"{source} -> {target}", "query": f"{source} {target} context dependent contradictory nonreplication boundary condition"},
            ]
        )
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in plan:
        key = " ".join(item["query"].lower().split())
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped[: max(1, int(limit)) * 3]


def yanzhen_local_counterevidence(project: dict[str, Any], claim_edges: list[dict[str, str]]) -> list[dict[str, Any]]:
    challenge_markers = (
        "not causal", "correlation", "association", "no effect", "failed", "failure", "inconsistent",
        "contradict", "alternative", "context-dependent", "context dependent", "boundary", "not necessary",
        "not sufficient", "confound", "common cause", "nonreplication", "does not reproduce",
    )
    findings: list[dict[str, Any]] = []
    for paper in project.get("papergraph", []):
        if not isinstance(paper, dict) or paper.get("active", True) is False:
            continue
        text = yanzhen_context_text(paper)
        lowered = text.lower()
        if not any(marker in lowered for marker in challenge_markers):
            continue
        for edge in claim_edges:
            source_terms = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", str(edge["source"]).lower()))
            target_terms = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", str(edge["target"]).lower()))
            if source_terms and not any(term in lowered for term in source_terms):
                continue
            if target_terms and not any(term in lowered for term in target_terms):
                continue
            excerpt = next((sentence for sentence in re.split(r"(?<=[.!?])\s+", text) if any(marker in sentence.lower() for marker in challenge_markers)), text[:400])
            findings.append(
                {
                    "claim": f"{edge['source']} -> {edge['target']}",
                    "citation": str(paper.get("citation") or paper.get("title") or ""),
                    "excerpt": excerpt[:500],
                    "source": "project_papergraph",
                    "status": "challenge_candidate_requires_context_review",
                }
            )
    return findings[:12]


def yanzhen_external_counterevidence_search(query_plan: list[dict[str, str]], enabled: bool = True) -> dict[str, Any]:
    report: dict[str, Any] = {"executed": bool(enabled), "queries": query_plan, "results": [], "errors": []}
    if not enabled or not query_plan:
        return report
    try:
        from ._literature_search import search_semantic_scholar
    except ImportError:
        from _literature_search import search_semantic_scholar
    for item in query_plan:
        try:
            payload = search_semantic_scholar(item["query"], max_results=3)
            results = payload.get("results", []) if isinstance(payload, dict) else []
            report["results"].extend(
                {
                    "claim": item["claim"],
                    "attack": item["attack"],
                    "title": str(result.get("title") or ""),
                    "citation": str(result.get("citation") or result.get("title") or ""),
                    "abstract": str(result.get("abstract") or "")[:700],
                    "source": "external_counterevidence_search",
                    "status": "unreviewed_counterevidence_candidate",
                }
                for result in results if isinstance(result, dict)
            )
        except Exception as exc:
            report["errors"].append(f"{item['attack']}: {str(exc)[:180]}")
    report["results"] = report["results"][:12]
    return report


def yanzhen_controversy_matrix(
    project: dict[str, Any],
    claim_edges: list[dict[str, str]],
    supporting_sources: list[Any],
    challenge_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    support = [
        {"citation": str(item.get("citation") or item.get("title") or ""), "excerpt": yanzhen_context_text(item)[:420]}
        for item in supporting_sources if isinstance(item, dict)
    ][:4]
    matrix: list[dict[str, Any]] = []
    for edge in claim_edges:
        claim = f"{edge['source']} -> {edge['target']}"
        challenges = [item for item in challenge_candidates if str(item.get("claim") or "") == claim][:4]
        substantiated_challenge = any(str(item.get("source") or "") == "project_papergraph" for item in challenges)
        matrix.append(
            {
                "claim": claim,
                "supporting_evidence": support,
                "challenge_evidence": challenges,
                "alternative_explanations": [
                    f"A direct {edge['source']} -> {edge['target']} route bypasses the proposed mediator.",
                    f"An unmeasured common cause may jointly affect {edge['source']} and {edge['target']}.",
                    "The relation may be limited to a specific model, stage, regime, dose, or measurement method.",
                ],
                "current_conclusion": "REQUIRES_REVISION_OR_CONTEXT_RESOLUTION" if substantiated_challenge else "NOT_REJECTED_UNDER_CURRENT_EVIDENCE",
                "decisive_experiment": (
                    f"Control plausible common causes; perturb {edge['source']}; block or bypass the proposed intermediate where applicable; "
                    f"then measure {edge['target']} across matched time, scale, or regime conditions."
                ),
            }
        )
    return matrix

def run_yanzhen_mechanism_verification(
    project_id: str,
    hypothesis_id: str = "",
    hypothesis: str = "",
    reasoning_chain: list[str] | None = None,
    cited_data: list[Any] | None = None,
    original_sources: list[Any] | None = None,
    shifted_conditions: list[dict[str, Any]] | list[str] | None = None,
    external_counterevidence_search: bool = True,
) -> str:
    try:
        from ._project import load_project, save_project
        from ._utils import find_by_id, unique_preserve_order
    except ImportError:
        from _project import load_project, save_project
        from _utils import find_by_id, unique_preserve_order
    project = load_project(project_id)
    hypothesis_record: dict[str, Any] = {}
    if hypothesis_id:
        found = find_by_id(project.get("hypotheses", []), "hypothesis_id", hypothesis_id)
        if found is None:
            raise ValueError(f"Unknown hypothesis_id for project {project_id}: {hypothesis_id}")
        hypothesis_record = found
    text = hypothesis or yanzhen_hypothesis_text(hypothesis_record)
    if not text:
        raise ValueError("YanZhen requires hypothesis text or hypothesis_id.")
    mechanism = yanzhen_mechanism_text(hypothesis_record) or text
    chain = reasoning_chain or extract_causal_chain(text + " " + mechanism)
    project_sources = original_sources if original_sources is not None else yanzhen_sources_for_hypothesis(project, hypothesis_record)
    project_citations = cited_data if cited_data is not None else yanzhen_cited_data_for_hypothesis(project, hypothesis_record)
    shifts = shifted_conditions or default_regime_shifts(text + " " + mechanism)
    if len(shifts) < 2:
        shifts = list(shifts) + default_regime_shifts(text + " " + mechanism)[: 2 - len(shifts)]
    claim_edges = yanzhen_claim_edges(hypothesis_record, chain, mechanism)
    counterevidence_query_plan = yanzhen_counterevidence_query_plan(
        claim_edges,
        str(project.get("domain") or ""),
    )
    local_counterevidence = yanzhen_local_counterevidence(project, claim_edges)
    external_counterevidence = yanzhen_external_counterevidence_search(
        counterevidence_query_plan,
        enabled=external_counterevidence_search,
    )
    external_candidates = [
        item for item in external_counterevidence.get("results", [])
        if isinstance(item, dict)
    ]
    controversy_matrix = yanzhen_controversy_matrix(
        project,
        claim_edges,
        project_sources,
        local_counterevidence + external_candidates,
    )

    layer_1 = yanzhen_internal_consistency_report(text, chain)
    chain_report = yanzhen_causal_chain_report(chain, project_citations)
    if chain_report.get("verdict") == "FAIL":
        layer_1["issues_found"] = unique_preserve_order(layer_1.get("issues_found", []) + chain_report.get("unsupported_links", []))
        layer_1["logical_chain_intact"] = False
        layer_1["verdict"] = "FAIL"
    citation_report = yanzhen_selective_citation_report(project_citations, project_sources)
    layer_2 = yanzhen_data_consistency_report(text + " " + mechanism, project_citations, project_sources)
    if citation_report.get("selective_citation_detected"):
        layer_2["selective_citation_detected"] = True
        layer_2["verdict"] = "FAIL"
    layer_3 = yanzhen_regime_shift_report(mechanism, yanzhen_original_conditions(text + " " + mechanism), shifts)
    feasibility = yanzhen_feasibility_audit(text + " " + mechanism)
    intervention_ontology = yanzhen_intervention_ontology_audit(hypothesis_record, text, mechanism)
    if intervention_ontology.get("verdict") == "FAIL":
        feasibility["issues_found"] = unique_preserve_order(
            list(feasibility.get("issues_found", []))
            + [str(intervention_ontology.get("reason") or "Intervention ontology mismatch.")]
        )
        feasibility["controllable_or_intervenable"] = False
        feasibility["verdict"] = "FAIL"
    feasibility["intervention_ontology"] = intervention_ontology
    adaptability = check_method_scenario_adaptability(text, mechanism, str(project.get("domain") or ""), project)
    overall = yanzhen_overall_verdict(layer_1, layer_2, layer_3, feasibility, adaptability)
    if overall == "NOT_REJECTED_UNDER_CURRENT_EVIDENCE" and any(
        item.get("current_conclusion") == "REQUIRES_REVISION_OR_CONTEXT_RESOLUTION"
        for item in controversy_matrix
    ):
        overall = "REQUIRES_HUMAN_REVIEW"
    detailed = yanzhen_detailed_reasoning(layer_1, layer_2, layer_3, chain_report, citation_report)
    mechanism_report = {
        "hypothesis_id": hypothesis_id or str(hypothesis_record.get("hypothesis_id") or ""),
        "layer_1_internal_consistency": layer_1,
        "layer_2_data_consistency": layer_2,
        "layer_3_regime_shift_test": layer_3,
        "causal_chain_audit": chain_report,
        "selective_citation_audit": citation_report,
        "feasibility_audit": feasibility,
        "intervention_ontology_audit": intervention_ontology,
        "domain_adaptability_audit": adaptability,
        "adversarial_counterevidence_retrieval": external_counterevidence,
        "local_counterevidence": local_counterevidence,
        "controversy_matrix": controversy_matrix,
        "overall_verdict": overall,
        "verdict": yanzhen_public_verdict(overall),
        "required_actions": [],
        "unsupported_claims": [],
        "detailed_reasoning": detailed,
        "cawm_reference_note": "CAWM risk follows the pattern where correct-looking conclusions are defended by brittle or inconsistent mechanisms that fail under regime shift.",
    }
    mechanism_report["unsupported_claims"] = yanzhen_unsupported_claims(mechanism_report)
    mechanism_report["required_actions"] = yanzhen_required_actions(mechanism_report)
    report = {
        "thought": "YanZhen independently attacked the proposed model through counterevidence retrieval, alternative-path analysis, common-cause challenges, context limits, and standard consistency checks.",
        "action": {
            "type": "run_yanzhen_mechanism_verification",
            "hypothesis_id": hypothesis_id,
            "layers_executed": ["internal_consistency", "data_consistency", "regime_shift_test", "counterevidence_retrieval", "controversy_matrix"],
        },
        "mechanism_fidelity_report": mechanism_report,
    }
    project.setdefault("mechanism_reports", []).append(report["mechanism_fidelity_report"])
    project["phase"] = "Mechanism Verification"
    project["updatedAt"] = time.time()
    save_project(project)
    log_event("SCIENCE", "yanzhen_mechanism_verified", project_id=project_id, hypothesis_id=hypothesis_id, verdict=overall)
    return json.dumps(report, ensure_ascii=False, indent=2)

def run_mechanism_check(
    project_id: str,
    hypothesis_id: str,
    shifted_conditions: list[str] | None = None,
) -> str:
    return run_yanzhen_mechanism_verification(
        project_id,
        hypothesis_id=hypothesis_id,
        shifted_conditions=shifted_conditions or ["different dataset distribution", "changed key parameter regime"],
    )

def ask_socratic_questions(
    project_id: str = "",
    hypothesis_id: str = "",
    hypothesis: str = "",
    question_types: list[str] | None = None,
    max_questions: int = 12,
) -> str:
    try:
        from ._debate import debate_hypothesis_record, debate_hypothesis_text, duzhi_generate_questions, socratic_overall_severity
        from ._project import load_project, save_project
        from ._utils import normalize_key
    except ImportError:
        from _debate import debate_hypothesis_record, debate_hypothesis_text, duzhi_generate_questions, socratic_overall_severity
        from _project import load_project, save_project
        from _utils import normalize_key
    project = load_project(project_id) if project_id else {}
    record = debate_hypothesis_record(project, hypothesis_id) if project and hypothesis_id else {}
    text = hypothesis or debate_hypothesis_text(record)
    if not text:
        raise ValueError("DuZhi requires hypothesis text or hypothesis_id.")
    mechanism = yanzhen_mechanism_text(record) or text
    sources = yanzhen_sources_for_hypothesis(project, record) if project else []
    selected_types = [normalize_key(item) for item in (question_types or []) if str(item).strip()]
    questions = duzhi_generate_questions(
        hypothesis_text=text,
        mechanism=mechanism,
        sources=sources,
        allowed_types=selected_types,
        max_questions=max_questions,
    )
    report = {
        "thought": "DuZhi generated structured Socratic questions targeting definitions, constraints, causal links, evidence gaps, and counterexamples.",
        "action": {
            "type": "ask_socratic_questions",
            "hypothesis_id": hypothesis_id,
            "question_types": selected_types or ["all"],
        },
        "questions": questions,
        "overall_severity": socratic_overall_severity(questions),
        "must_revise": any(item.get("severity") in {"high", "fatal"} for item in questions),
    }
    if project:
        project.setdefault("socratic_question_reports", []).append(report)
        project["phase"] = "Socratic Debate"
        project["updatedAt"] = time.time()
        save_project(project)
    return json.dumps(report, ensure_ascii=False, indent=2)

def ask_critical_questions(
    project_id: str = "",
    hypothesis_id: str = "",
    hypothesis: str = "",
    question_types: list[str] | None = None,
    max_questions: int = 12,
) -> str:
    return ask_socratic_questions(project_id, hypothesis_id, hypothesis, question_types, max_questions)

def find_counterexamples(
    project_id: str = "",
    hypothesis_id: str = "",
    hypothesis: str = "",
    max_questions: int = 6,
) -> str:
    return ask_socratic_questions(
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        hypothesis=hypothesis,
        question_types=["counterexample_challenge"],
        max_questions=max_questions,
    )

def stress_test_assumptions(
    project_id: str = "",
    hypothesis_id: str = "",
    hypothesis: str = "",
    max_questions: int = 8,
) -> str:
    return ask_socratic_questions(
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        hypothesis=hypothesis,
        question_types=["constraint_check", "counterexample_challenge"],
        max_questions=max_questions,
    )

def moderate_round(
    project_id: str,
    round_name: str,
    proponent_position: str = "",
    opponent_questions: list[dict[str, Any]] | None = None,
    yanzhen_report: dict[str, Any] | None = None,
) -> str:
    try:
        from ._project import load_project, save_project
    except ImportError:
        from _project import load_project, save_project
    questions = opponent_questions or []
    project = load_project(project_id)
    verdict = "advance"
    if any(item.get("severity") == "fatal" for item in questions):
        verdict = "revise"
    report_body = yanzhen_report.get("mechanism_fidelity_report", {}) if isinstance(yanzhen_report, dict) else {}
    if not report_body and isinstance(yanzhen_report, dict):
        report_body = yanzhen_report
    if not report_body:
        report_body = latest_yanzhen_report(project)
    if report_body.get("overall_verdict") == "CAWM_DETECTED":
        verdict = "revise"
    result = {
        "round_name": round_name,
        "proponent_position": proponent_position,
        "opponent_questions": questions,
        "yanzhen_summary": report_body,
        "verdict": verdict,
        "adopted_revision_requirements": [
            str(item.get("required_revision") or "")
            for item in questions
            if item.get("severity") in {"high", "fatal"} and item.get("required_revision")
        ],
    }
    project.setdefault("debate_round_moderations", []).append(result)
    project["updatedAt"] = time.time()
    save_project(project)
    return json.dumps(result, ensure_ascii=False, indent=2)

def latest_yanzhen_report(project: dict[str, Any]) -> dict[str, Any]:
    reports = project.get("mechanism_reports", [])
    if isinstance(reports, list) and reports:
        latest = reports[-1]
        return latest if isinstance(latest, dict) else {}
    return {}

def summarize_positions(
    proponent_position: str = "",
    opponent_questions: list[dict[str, Any]] | None = None,
    yanzhen_report: dict[str, Any] | None = None,
) -> str:
    try:
        from ._debate import debate_unresolved_issues
        from ._utils import trim_text
    except ImportError:
        from _debate import debate_unresolved_issues
        from _utils import trim_text
    questions = opponent_questions or []
    report_body = yanzhen_report.get("mechanism_fidelity_report", {}) if isinstance(yanzhen_report, dict) else {}
    summary = {
        "proponent_core_claim": trim_text(proponent_position, 500),
        "opponent_high_severity_issues": [
            item for item in questions if item.get("severity") in {"high", "fatal"}
        ],
        "yanzhen_overall_verdict": report_body.get("overall_verdict", "not_run"),
        "shared_dispute_points": debate_unresolved_issues(questions, report_body),
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)

def extract_emergent_method(
    debate_report: dict[str, Any] | str,
) -> str:
    try:
        from ._llm import parse_jsonish_dict
    except ImportError:
        from _llm import parse_jsonish_dict
    parsed = parse_jsonish_dict(debate_report)
    refined = parsed.get("refined_hypothesis") if isinstance(parsed.get("refined_hypothesis"), dict) else {}
    if not refined:
        body = parsed.get("debate_report") if isinstance(parsed.get("debate_report"), dict) else {}
        refined = body.get("refined_hypothesis") if isinstance(body.get("refined_hypothesis"), dict) else {}
    method = {
        "emergent_method": refined.get("hypothesis") or refined.get("statement") or "",
        "causal_chain": refined.get("causal_chain", []),
        "falsification_conditions": refined.get("falsification_conditions", []),
        "evidence_requirements": refined.get("evidence_requirements", []),
    }
    return json.dumps(method, ensure_ascii=False, indent=2)

def yanzhen_internal_consistency_report(hypothesis: str, reasoning_chain: list[str]) -> dict[str, Any]:
    try:
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _utils import normalize_space, unique_preserve_order
    text = normalize_space(hypothesis)
    chain = [normalize_space(str(item)) for item in reasoning_chain if normalize_space(str(item))]
    issues = mechanism_internal_issues(text, " ".join(chain) if chain else text)
    if len(chain) < 2:
        issues.append("Reasoning chain has fewer than two explicit causal/logical steps.")
    contradiction_terms = (
        ("increase", "decrease"),
        ("improve", "worsen"),
        ("stable", "unstable"),
        ("necessary", "unnecessary"),
        ("always", "never"),
    )
    lowered = text.lower()
    for left, right in contradiction_terms:
        if left in lowered and right in lowered and not any(marker in lowered for marker in ("trade-off", "boundary", "except", "unless")):
            issues.append(f"Potential unresolved contradiction: both '{left}' and '{right}' appear without a boundary condition.")
            break
    formula_like = bool(re.search(r"[A-Za-z]\s*[=<>]\s*[-+*/A-Za-z0-9().^ ]+", text))
    formula_application_correct = True
    if formula_like and not any(unit in lowered for unit in ("unit", "dimension", "scale", "boundary", "assumption", "parameter")):
        formula_application_correct = False
        issues.append("Formula-like claim appears without units, dimensional check, or boundary assumptions.")
    logical_chain_intact = not any("too short" in issue.lower() or "fewer than" in issue.lower() for issue in issues)
    return {
        "logical_chain_intact": logical_chain_intact and not issues,
        "formula_application_correct": formula_application_correct,
        "issues_found": unique_preserve_order(issues),
        "reasoning_chain": chain,
        "verdict": "PASS" if not issues and formula_application_correct else "FAIL",
    }

def yanzhen_data_consistency_report(hypothesis: str, cited_data: list[Any], original_sources: list[Any]) -> dict[str, Any]:
    try:
        from ._gap_detection import text_jaccard
        from ._models import Hypothesis
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _gap_detection import text_jaccard
        from _models import Hypothesis
        from _utils import normalize_space, unique_preserve_order
    cited_texts = [yanzhen_context_text(item) for item in cited_data if yanzhen_context_text(item)]
    source_texts = [yanzhen_context_text(item) for item in original_sources if yanzhen_context_text(item)]
    evidence_text = " ".join(cited_texts or source_texts)
    alignment = text_jaccard(normalize_space(hypothesis), evidence_text) if evidence_text else 0.0
    source_alignment = text_jaccard(normalize_space(hypothesis), " ".join(source_texts)) if source_texts else 0.0
    contradictions = yanzhen_evidence_contradictions(hypothesis, source_texts)
    missing = []
    if not cited_texts and not source_texts:
        missing.append("No cited data or original source context was provided.")
    elif alignment < 0.08:
        missing.append("Hypothesis mechanism has low lexical/semantic overlap with cited evidence.")
    if contradictions:
        missing.extend(contradictions)
    original_text_alignment = "high" if source_alignment >= 0.22 else "medium" if source_alignment >= 0.08 else "low"
    citation_report = yanzhen_selective_citation_report(cited_data, original_sources)
    verdict = "PASS" if not missing and not citation_report.get("selective_citation_detected") else "FAIL"
    return {
        "mechanism_matches_data": not missing,
        "selective_citation_detected": bool(citation_report.get("selective_citation_detected")),
        "original_text_alignment": original_text_alignment,
        "alignment_score": round(alignment, 4),
        "issues_found": unique_preserve_order(missing + citation_report.get("issues_found", [])),
        "verdict": verdict,
    }

def yanzhen_regime_shift_report(
    mechanism: str,
    original_conditions: dict[str, Any],
    shifted_conditions: list[dict[str, Any]] | list[str],
) -> dict[str, Any]:
    try:
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _utils import normalize_space, unique_preserve_order
    shifts = normalize_shifted_conditions(shifted_conditions)
    if len(shifts) < 2:
        shifts.extend(default_regime_shifts(mechanism)[: 2 - len(shifts)])
    text = normalize_space(mechanism).lower()
    issues: list[str] = []
    if not any(term in text for term in ("boundary", "limit", "assumption", "condition", "regime", "scale", "unless", "when")):
        issues.append("Mechanism does not state boundary conditions or validity regime.")
    if any(term in text for term in ("always", "guarantee", "universal", "all cases", "never fails")):
        issues.append("Universal mechanism wording is brittle under regime shift.")
    high_risk_shifts = 0
    for shift in shifts:
        parameter = str(shift.get("parameter") or "").lower()
        shifted = str(shift.get("shifted_value") or "").lower()
        if any(term in parameter + " " + shifted for term in ("10x", "0.1x", "extreme", "different domain", "distribution shift", "low data", "high noise")):
            high_risk_shifts += 1
    if not original_conditions:
        issues.append("Original conditions are not explicit, so regime-shift comparison is under-specified.")
    if issues and high_risk_shifts >= 1:
        stability = "collapses_unexpectedly"
        risk = "HIGH"
    elif issues:
        stability = "degrades_gracefully"
        risk = "MEDIUM"
    else:
        stability = "stable"
        risk = "LOW"
    return {
        "shifted_conditions_tested": [render_shift_condition(shift) for shift in shifts[:8]],
        "mechanism_stability": stability,
        "cawm_risk_level": risk,
        "issues_found": unique_preserve_order(issues),
        "verdict": "PASS" if risk in {"LOW", "MEDIUM"} and stability != "collapses_unexpectedly" else "FAIL",
    }

def yanzhen_selective_citation_report(cited_papers: list[Any], full_paper_contexts: list[Any]) -> dict[str, Any]:
    try:
        from ._literature_search import query_terms
        from ._utils import unique_preserve_order
    except ImportError:
        from _literature_search import query_terms
        from _utils import unique_preserve_order
    cited_texts = [yanzhen_context_text(item) for item in cited_papers if yanzhen_context_text(item)]
    full_texts = [yanzhen_context_text(item) for item in full_paper_contexts if yanzhen_context_text(item)]
    issues: list[str] = []
    if cited_texts and len(full_texts) >= len(cited_texts) + 3:
        cited_terms = set(query_terms(" ".join(cited_texts)))
        full_terms = set(query_terms(" ".join(full_texts)))
        omitted_terms = sorted((full_terms - cited_terms) & yanzhen_conflict_or_limitation_terms())
        if omitted_terms:
            issues.append(f"Potential cherry-picking: uncited source context contains limitation/conflict terms {omitted_terms[:8]}.")
    if cited_texts and not full_texts:
        issues.append("Cited papers were provided without broader source contexts; selective citation cannot be ruled out.")
    if not cited_texts:
        issues.append("No explicit cited papers/data were provided.")
    return {
        "selective_citation_detected": bool(issues),
        "cited_count": len(cited_texts),
        "context_count": len(full_texts),
        "issues_found": unique_preserve_order(issues),
        "verdict": "FAIL" if issues else "PASS",
    }

def yanzhen_causal_chain_report(causal_chain: list[str], evidence_for_each: list[Any]) -> dict[str, Any]:
    try:
        from ._gap_detection import text_jaccard
        from ._utils import normalize_space
    except ImportError:
        from _gap_detection import text_jaccard
        from _utils import normalize_space
    chain = [normalize_space(str(item)) for item in causal_chain if normalize_space(str(item))]
    evidence = [yanzhen_context_text(item) for item in evidence_for_each if yanzhen_context_text(item)]
    unsupported: list[str] = []
    if not chain:
        unsupported.append("No explicit causal chain was extracted.")
    for index, link in enumerate(chain):
        evidence_text = evidence[index] if index < len(evidence) else " ".join(evidence)
        if not evidence_text or text_jaccard(link, evidence_text) < 0.04:
            unsupported.append(f"Unsupported causal link: {link}")
    return {
        "causal_chain": chain,
        "links_checked": len(chain),
        "unsupported_links": unsupported,
        "verdict": "PASS" if chain and not unsupported else "FAIL",
    }

def yanzhen_hypothesis_text(hypothesis: dict[str, Any]) -> str:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    final = hypothesis.get("mingli_final_idea") if isinstance(hypothesis.get("mingli_final_idea"), dict) else {}
    parts = [
        final.get("title", ""),
        final.get("hypothesis", ""),
        final.get("abstract", ""),
        hypothesis.get("statement", ""),
        hypothesis.get("expected_value", ""),
    ]
    return normalize_space(" ".join(str(part) for part in parts if part))

def yanzhen_mechanism_text(hypothesis: dict[str, Any]) -> str:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    final = hypothesis.get("mingli_final_idea") if isinstance(hypothesis.get("mingli_final_idea"), dict) else {}
    experiments = final.get("experiments") if isinstance(final.get("experiments"), dict) else {}
    return normalize_space(
        " ".join(
            str(part)
            for part in (
                hypothesis.get("mechanism", ""),
                final.get("abstract", ""),
                experiments.get("setup", ""),
                hypothesis.get("test_plan", ""),
            )
            if part
        )
    )

def yanzhen_sources_for_hypothesis(project: dict[str, Any], hypothesis: dict[str, Any]) -> list[Any]:
    try:
        from ._pipeline import project_records_for_mapping
        from ._utils import record_context_text, references_for_gap
    except ImportError:
        from _pipeline import project_records_for_mapping
        from _utils import record_context_text, references_for_gap
    gap_id = str(hypothesis.get("gap_id") or "")
    refs = set(references_for_gap(project, gap_id))
    records = project_records_for_mapping(project)
    if refs:
        matched = [
            record
            for record in records
            if str(record.get("citation") or record.get("title") or "") in refs
            or any(ref.lower() in record_context_text(record).lower() for ref in refs)
        ]
        if matched:
            return matched
    return records[:12]

def yanzhen_cited_data_for_hypothesis(project: dict[str, Any], hypothesis: dict[str, Any]) -> list[Any]:
    try:
        from ._utils import references_for_gap
    except ImportError:
        from _utils import references_for_gap
    refs = references_for_gap(project, str(hypothesis.get("gap_id") or ""))
    if refs:
        return refs
    source_gap = hypothesis.get("source_gap") if isinstance(hypothesis.get("source_gap"), dict) else {}
    refs = source_gap.get("supporting_references", []) if isinstance(source_gap.get("supporting_references"), list) else []
    return refs

def yanzhen_original_conditions(text: str) -> dict[str, Any]:
    lowered = text.lower()
    conditions: dict[str, Any] = {}
    for key, terms in {
        "data_distribution": ("dataset", "cohort", "sample", "distribution", "population"),
        "scale": ("scale", "size", "resolution", "step", "frequency", "concentration", "dose"),
        "environment": ("temperature", "pressure", "noise", "humidity", "field", "medium", "climate"),
        "domain": ("domain", "scenario", "system", "material", "organism", "patient", "network"),
    }.items():
        if any(term in lowered for term in terms):
            conditions[key] = "mentioned_but_not_quantified"
    return conditions

def extract_causal_chain(text: str) -> list[str]:
    try:
        from ._utils import split_sentences, trim_text
    except ImportError:
        from _utils import split_sentences, trim_text
    sentences = split_sentences(text)
    chain: list[str] = []
    for sentence in sentences:
        lowered = sentence.lower()
        if any(marker in lowered for marker in ("because", "therefore", "leads to", "causes", "drives", "mediates", "if ", " then ", "->")):
            chain.append(trim_text(sentence, 240))
    return chain[:8]

def default_regime_shifts(text: str) -> list[dict[str, str]]:
    lowered = text.lower()
    shifts: list[dict[str, str]] = []
    if any(term in lowered for term in ("dataset", "model", "learning", "classification", "prediction", "ai", "algorithm")):
        shifts.append({"parameter": "data_distribution", "original_value": "training/reference distribution", "shifted_value": "out-of-distribution or low-data setting"})
        shifts.append({"parameter": "noise_level", "original_value": "nominal signal quality", "shifted_value": "high-noise or missing-data condition"})
    if any(term in lowered for term in ("temperature", "pressure", "energy", "material", "chemical", "reaction", "battery", "climate", "physical", "quantum")):
        shifts.append({"parameter": "scale_or_environment", "original_value": "nominal experimental regime", "shifted_value": "10x/0.1x parameter scaling or changed environment"})
        shifts.append({"parameter": "boundary_condition", "original_value": "reported boundary condition", "shifted_value": "adjacent physical/chemical/climate regime"})
    if any(term in lowered for term in ("cell", "protein", "gene", "patient", "clinical", "organism", "disease", "ecology", "crop")):
        shifts.append({"parameter": "biological_context", "original_value": "reported cohort/model organism/context", "shifted_value": "different cohort, tissue, organism, or stress condition"})
        shifts.append({"parameter": "intervention_dose_or_time", "original_value": "reported dose/time window", "shifted_value": "0.1x/10x dose, duration, or sampling interval"})
    if not shifts:
        shifts.extend(
            [
                {"parameter": "scale", "original_value": "nominal scale", "shifted_value": "10x larger and 0.1x smaller scale"},
                {"parameter": "domain_transfer", "original_value": "original scenario", "shifted_value": "adjacent but distinct scenario or dataset distribution"},
            ]
        )
    return shifts[:6]

def normalize_shifted_conditions(shifted_conditions: list[dict[str, Any]] | list[str]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in shifted_conditions:
        if isinstance(item, dict):
            normalized.append(
                {
                    "parameter": str(item.get("parameter") or item.get("name") or "condition"),
                    "original_value": str(item.get("original_value") or item.get("original") or "nominal"),
                    "shifted_value": str(item.get("shifted_value") or item.get("shifted") or item.get("value") or ""),
                }
            )
        else:
            normalized.append({"parameter": "condition", "original_value": "nominal", "shifted_value": str(item)})
    return [item for item in normalized if item.get("shifted_value")]

def render_shift_condition(shift: dict[str, Any]) -> str:
    return f"{shift.get('parameter')}: {shift.get('original_value')} -> {shift.get('shifted_value')}"

def yanzhen_context_text(item: Any) -> str:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    if isinstance(item, dict):
        return normalize_space(
            " ".join(
                str(item.get(key) or "")
                for key in ("title", "citation", "abstract", "conclusion", "limitation", "contribution", "method", "scenario", "benchmark", "text")
            )
        )
    return normalize_space(str(item))

def yanzhen_evidence_contradictions(hypothesis: str, source_texts: list[str]) -> list[str]:
    try:
        from ._models import Hypothesis
    except ImportError:
        from _models import Hypothesis
    issues: list[str] = []
    source = " ".join(source_texts).lower()
    hypo = hypothesis.lower()
    if any(term in hypo for term in ("improve", "increase", "enhance")) and any(
        term in source for term in ("no improvement", "not improve", "failed to improve", "decrease", "worse")
    ):
        issues.append("Original source context includes negative or contradictory outcome language.")
    if any(term in hypo for term in ("causes", "causal", "drives")) and any(
        term in source for term in ("correlation", "association", "observational", "not causal", "cannot infer caus")
    ):
        issues.append("Hypothesis makes causal claims while source context appears correlational or warns against causal inference.")
    return issues

def yanzhen_conflict_or_limitation_terms() -> set[str]:
    return {
        "limitation",
        "limitations",
        "unclear",
        "unknown",
        "conflict",
        "contradict",
        "failed",
        "failure",
        "bias",
        "noise",
        "artifact",
        "uncertain",
        "not",
        "cannot",
        "underpowered",
        "negative",
    }

def check_method_scenario_adaptability(
    hypothesis_text: str,
    mechanism_text: str,
    domain: str,
    project: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _utils import normalize_space, unique_preserve_order
    """Check whether the method's essential requirements are compatible with the scenario's data characteristics.

    This prevents "forced migration" — combining a method and scenario that only
    overlap at the text level but are fundamentally incompatible (e.g., applying
    Structural Equation Modeling to XPS/TEM electrochemical data).

    Returns a structured report with verdict, compatibility_details, and
    adaptation_conditions (what would need to hold for the method to work).
    """
    combined = normalize_space(f"{hypothesis_text} {mechanism_text}").lower()
    domain_lower = domain.lower()

    method_family = classify_method_domain(combined)
    scenario_family = classify_method_domain(f"{domain} {combined}")

    # Define data-type requirements for each method family
    method_requirements: dict[str, dict[str, Any]] = {
        "statistical_modeling": {
            "requires": ["structured_variables", "sample_size", "measurement_model"],
            "data_types": ["survey_data", "questionnaire_responses", "numerical_measurements", "panel_data"],
            "incompatible_with": ["spectral_data", "microscopy_images", "electrochemical_signals", "molecular_structures"],
            "adaptation_conditions": [
                "Define explicit latent variables and observed indicators measurable in the target scenario",
                "Establish a validated measurement instrument or scale for the scenario",
                "Demonstrate sufficient sample size (N >= 10x number of estimated parameters)",
            ],
        },
        "computational_simulation": {
            "requires": ["mathematical_model", "boundary_conditions", "validation_data"],
            "data_types": ["simulation_output", "numerical_benchmarks", "experimental_validation_data"],
            "incompatible_with": ["pure_survey_data", "qualitative_interviews"],
            "adaptation_conditions": [
                "Provide a governing equation system or validated surrogate model",
                "Specify initial and boundary conditions consistent with the scenario",
                "Identify experimental data for validation against simulation output",
            ],
        },
        "experimental_characterization": {
            "requires": ["physical_sample", "instrument_access", "reproducible_protocol"],
            "data_types": ["spectra", "images", "electrochemical_curves", "diffraction_patterns"],
            "incompatible_with": ["pure_textual_data", "abstract_social_concepts"],
            "adaptation_conditions": [
                "Identify physical samples or materials available for characterization",
                "Specify instrument and measurement protocol",
                "Define reproducibility criteria and error bars",
            ],
        },
        "analytical_modeling": {
            "requires": ["governing_equations", "parameter_values", "validity_regime"],
            "data_types": ["physical_constants", "transport_coefficients", "reaction_rates"],
            "incompatible_with": ["subjective_opinions", "likert_scales"],
            "adaptation_conditions": [
                "Derive or cite the governing equations for the system",
                "Provide parameter values or estimation methods",
                "State the validity regime (temperature, pressure, scale)",
            ],
        },
    }

    # Define scenario data-type indicators
    scenario_data_indicators: dict[str, list[str]] = {
        "spectral_data": ("xps", "tem", "sem image", "spectroscop", "raman", "ftir", "nmr", "xrd", "diffraction", "spectrum"),
        "electrochemical_signals": ("impedance", "voltammetry", "cyclic volt", "eis", "battery", "cathode", "anode", "electrolyte", "charge-discharge"),
        "molecular_structures": ("molecular", "protein structure", "crystal structure", "dft", "ligand", "binding"),
        "survey_data": ("survey", "questionnaire", "likert", "respondent", "sample size", "n=", "participants"),
        "numerical_measurements": ("measurement", "sensor", "time series", "numerical data", "dataset"),
        "simulation_output": ("simulation", "finite element", "molecular dynamics", "monte carlo"),
    }

    # Detect what data types the scenario actually provides
    scenario_text = f"{domain} {combined}"
    detected_data_types: list[str] = []
    for dtype, markers in scenario_data_indicators.items():
        if any(marker in scenario_text for marker in markers):
            detected_data_types.append(dtype)

    # Check for incompatibilities
    requirements = method_requirements.get(method_family, {})
    incompatible_types = set(requirements.get("incompatible_with", []))
    detected_set = set(detected_data_types)
    incompatibilities = sorted(incompatible_types & detected_set)

    issues: list[str] = []
    adaptation_needed: list[str] = []

    if incompatibilities:
        issues.append(
            f"Method family '{method_family}' is fundamentally incompatible with "
            f"scenario data types: {', '.join(incompatibilities)}. "
            f"The method requires {', '.join(requirements.get('data_types', []))} "
            f"but the scenario produces {', '.join(detected_data_types)}."
        )
        adaptation_needed.extend(requirements.get("adaptation_conditions", []))

    # Check for cross-domain migration without bridging evidence
    if method_family != "general" and scenario_family != "general" and method_family != scenario_family:
        # Method and scenario belong to different families — check for bridging evidence
        bridge_markers = ("adapt", "transfer", "cross-domain", "interdisciplinary", "novel application", "first application")
        has_bridge = any(marker in combined for marker in bridge_markers)
        if not has_bridge:
            issues.append(
                f"Cross-domain migration detected: method family '{method_family}' applied to "
                f"scenario family '{scenario_family}' without explicit bridging evidence or adaptation rationale."
            )
            adaptation_needed.append(
                f"Provide explicit rationale for applying {method_family} methods to {scenario_family} data"
            )

    # Check method prerequisites against scenario context
    requires = requirements.get("requires", [])
    for req in requires:
        req_markers = {
            "structured_variables": ("variable", "factor", "construct", "indicator", "latent", "observed"),
            "sample_size": ("sample", "n=", "participants", "observations", "cases", "data points"),
            "measurement_model": ("measurement", "scale", "instrument", "validated", "reliability", "cronbach"),
            "mathematical_model": ("equation", "model", "governing", "differential", "algebraic"),
            "boundary_conditions": ("boundary", "initial condition", "constraint", "assumption"),
            "validation_data": ("validation", "benchmark", "ground truth", "experimental data"),
            "physical_sample": ("sample", "specimen", "material", "substrate", "electrode"),
            "instrument_access": ("instrument", "microscope", "spectrometer", "diffractometer", "potentiostat"),
            "reproducible_protocol": ("protocol", "procedure", "standard", "reproducib"),
            "governing_equations": ("equation", "law", "principle", "conservation"),
            "parameter_values": ("parameter", "coefficient", "constant", "value"),
            "validity_regime": ("regime", "range", "valid", "applicable", "condition"),
        }
        markers = req_markers.get(req, ())
        if markers and not any(m in combined for m in markers):
            issues.append(f"Method prerequisite '{req}' is not addressed in the hypothesis or mechanism text.")

    verdict = "PASS"
    if incompatibilities:
        verdict = "FAIL"
    elif len(issues) >= 2:
        verdict = "WARN"

    return {
        "method_family": method_family,
        "scenario_family": scenario_family,
        "detected_scenario_data_types": detected_data_types,
        "incompatibilities": incompatibilities,
        "issues_found": unique_preserve_order(issues),
        "adaptation_conditions": adaptation_needed,
        "verdict": verdict,
        "policy": (
            "Methods must be compatible with the data types the scenario can produce. "
            "Cross-domain migration requires explicit bridging evidence. "
            "A FAIL verdict indicates the method's essential requirements cannot be satisfied "
            "by the scenario's data characteristics."
        ),
    }

def yanzhen_intervention_ontology_audit(
    hypothesis_record: dict[str, Any],
    hypothesis_text: str = "",
    mechanism_text: str = "",
) -> dict[str, Any]:
    """Fail hypotheses that confuse knowledge operations with interventions."""
    candidates: list[dict[str, Any] | str] = []
    idea = hypothesis_record.get("mingli_final_idea") if isinstance(hypothesis_record.get("mingli_final_idea"), dict) else {}
    for owner, payload in (("hypothesis", hypothesis_record), ("mingli_final_idea", idea)):
        gate = payload.get("intervention_type_gate") if isinstance(payload.get("intervention_type_gate"), dict) else {}
        if gate.get("selected_intervention"):
            candidates.append({
                "candidate": gate.get("selected_intervention"),
                "candidate_source": f"{owner}.intervention_type_gate",
            })
        protocol = payload.get("experimental_protocol") if isinstance(payload.get("experimental_protocol"), dict) else {}
        intervention = protocol.get("intervention") if isinstance(protocol.get("intervention"), dict) else {}
        if intervention:
            candidates.append({
                "candidate": f"{intervention.get('modality', '')} {intervention.get('target', '')}",
                "candidate_source": f"{owner}.experimental_protocol.intervention",
            })
        claim = payload.get("claim") if isinstance(payload.get("claim"), dict) else {}
        if claim.get("intervention"):
            candidates.append({
                "candidate": claim.get("intervention"),
                "candidate_source": f"{owner}.claim.intervention",
            })
    # Unstructured tool calls are still supported, but only as a last resort.
    if not candidates:
        candidates.append({
            "candidate": f"{hypothesis_text} {mechanism_text}",
            "candidate_source": "unstructured_hypothesis_text",
        })
    gate = intervention_gate_from_values(candidates)
    return {
        **gate,
        "verdict": "PASS" if gate.get("admissible") else "FAIL",
        "policy": (
            "Only a concrete manipulation of a physical, biological, chemical, engineering, environmental, "
            "or explicitly simulated object may occupy the intervention slot. Reviews, evidence summaries, "
            "datasets, observational associations, and placeholders are rationale or measurement resources only."
        ),
    }


def yanzhen_feasibility_audit(text: str) -> dict[str, Any]:
    try:
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _utils import normalize_space, unique_preserve_order
    lowered = normalize_space(text).lower()
    issues: list[str] = []
    observable_terms = (
        "measure", "metric", "observable", "readout", "assay", "spectrum", "image", "signal",
        "dataset", "simulation", "experiment", "benchmark", "score", "rate", "yield", "accuracy",
        "stability", "response", "performance", "validation",
    )
    control_terms = (
        "vary", "control", "intervention", "dose", "concentration", "temperature", "pressure",
        "parameter", "ablation", "baseline", "condition", "setting", "treatment", "input",
    )
    boundary_terms = ("boundary", "condition", "regime", "assumption", "range", "scale", "limit", "under", "unless")
    if not any(term in lowered for term in observable_terms):
        issues.append("No observable, measurement, benchmark, or validation readout is stated.")
    if not any(term in lowered for term in control_terms):
        issues.append("No controllable variable, intervention, baseline, or experimental/simulation condition is stated.")
    if not any(term in lowered for term in boundary_terms):
        issues.append("No validity range, boundary condition, or assumption is stated.")
    if any(term in lowered for term in ("impossible", "violates", "cannot be measured", "unobservable")):
        issues.append("The mechanism text contains explicit infeasibility language.")
    verdict = "PASS" if not issues else "WARN"
    if any("explicit infeasibility" in issue for issue in issues):
        verdict = "FAIL"
    return {
        "observable_or_measurable": not any("observable" in issue for issue in issues),
        "controllable_or_intervenable": not any("controllable" in issue for issue in issues),
        "boundary_conditions_stated": not any("validity range" in issue for issue in issues),
        "issues_found": unique_preserve_order(issues),
        "verdict": verdict,
    }

def yanzhen_overall_verdict(
    layer_1: dict[str, Any],
    layer_2: dict[str, Any],
    layer_3: dict[str, Any],
    feasibility: dict[str, Any] | None = None,
    adaptability: dict[str, Any] | None = None,
) -> str:
    if layer_3.get("verdict") == "FAIL" or layer_3.get("cawm_risk_level") == "HIGH":
        return "CAWM_DETECTED"
    if isinstance(feasibility, dict) and feasibility.get("verdict") == "FAIL":
        return "CAWM_DETECTED"
    if isinstance(adaptability, dict) and adaptability.get("verdict") == "FAIL":
        return "CAWM_DETECTED"
    if layer_1.get("verdict") == "FAIL" or layer_2.get("verdict") == "FAIL":
        return "REQUIRES_HUMAN_REVIEW"
    if isinstance(feasibility, dict) and feasibility.get("verdict") == "WARN":
        return "REQUIRES_HUMAN_REVIEW"
    if isinstance(adaptability, dict) and adaptability.get("verdict") == "WARN":
        return "REQUIRES_HUMAN_REVIEW"
    if layer_3.get("cawm_risk_level") == "MEDIUM":
        return "REQUIRES_HUMAN_REVIEW"
    return "MECHANISM_VERIFIED"

def yanzhen_public_verdict(overall: str) -> str:
    if overall == "MECHANISM_VERIFIED":
        return "PASS"
    if overall == "CAWM_DETECTED":
        return "REJECTED"
    return "REQUIRES_REVISION"

def yanzhen_unsupported_claims(report: dict[str, Any]) -> list[str]:
    try:
        from ._utils import normalize_space, trim_text, unique_preserve_order
    except ImportError:
        from _utils import normalize_space, trim_text, unique_preserve_order
    claims: list[str] = []
    chain = report.get("causal_chain_audit", {}) if isinstance(report.get("causal_chain_audit"), dict) else {}
    claims.extend(str(item) for item in chain.get("unsupported_links", []) if item)
    for layer_key in ("layer_1_internal_consistency", "layer_2_data_consistency", "selective_citation_audit", "feasibility_audit"):
        layer = report.get(layer_key, {}) if isinstance(report.get(layer_key), dict) else {}
        for issue in layer.get("issues_found", []) if isinstance(layer.get("issues_found"), list) else []:
            issue_text = str(issue)
            if any(term in issue_text.lower() for term in ("unsupported", "no cited", "low lexical", "no observable", "no controllable", "no validity")):
                claims.append(issue_text)
    # Include domain adaptability issues as unsupported claims
    adaptability = report.get("domain_adaptability_audit", {}) if isinstance(report.get("domain_adaptability_audit"), dict) else {}
    if adaptability.get("verdict") in {"FAIL", "WARN"}:
        for issue in adaptability.get("issues_found", []):
            claims.append(str(issue))
    return unique_preserve_order(trim_text(item, 220) for item in claims if normalize_space(item))[:12]

def yanzhen_required_actions(report: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        from ._supplement import extract_academic_keyword
    except ImportError:
        from _supplement import extract_academic_keyword
    actions: list[dict[str, Any]] = []
    if report.get("unsupported_claims"):
        claims = report.get("unsupported_claims", [])[:5]
        suggested_queries = []
        for claim in claims:
            terms = extract_academic_keyword(str(claim), max_keywords=5)
            if terms:
                suggested_queries.append({"claim": claim, "suggested_query": " ".join(terms)})
        actions.append(
            {
                "action": "zhizhi_supplement_evidence",
                "reason": "Unsupported causal or evidence links require targeted literature completion before accepting the hypothesis.",
                "claims": claims,
                "suggested_search_queries": suggested_queries,
            }
        )
    layer_1 = report.get("layer_1_internal_consistency", {}) if isinstance(report.get("layer_1_internal_consistency"), dict) else {}
    if layer_1.get("verdict") == "FAIL":
        issues = layer_1.get("issues_found", [])[:5]
        actions.append(
            {
                "action": "mingli_rewrite_causal_chain",
                "reason": "Internal consistency failed.",
                "issues": issues,
                "suggested_revision": (
                    "Rewrite the causal chain to address each specific issue: "
                    + "; ".join(str(issue) for issue in issues[:3])
                    + ". Ensure every link has a PaperGraph citation or is marked as a testable assumption."
                ),
            }
        )
    layer_2 = report.get("layer_2_data_consistency", {}) if isinstance(report.get("layer_2_data_consistency"), dict) else {}
    if layer_2.get("verdict") == "FAIL":
        issues = layer_2.get("issues_found", [])[:5]
        actions.append(
            {
                "action": "separate_supported_from_speculative_claims",
                "reason": "Mechanism-data alignment is insufficient or selective citation cannot be ruled out.",
                "issues": issues,
                "suggested_revision": (
                    "For each claim in the hypothesis, annotate whether it is (a) supported by a specific PaperGraph citation, "
                    "(b) supported by general domain knowledge, or (c) speculative and requiring experimental validation. "
                    "Remove or downgrade claims in category (c) that lack any evidence pathway."
                ),
            }
        )
    layer_3 = report.get("layer_3_regime_shift_test", {}) if isinstance(report.get("layer_3_regime_shift_test"), dict) else {}
    if layer_3.get("verdict") == "FAIL" or layer_3.get("cawm_risk_level") in {"MEDIUM", "HIGH"}:
        shifted = layer_3.get("shifted_conditions_tested", [])[:6]
        actions.append(
            {
                "action": "restrict_validity_regime_and_add_shift_tests",
                "reason": "Regime-shift stability is not yet strong enough.",
                "shifted_conditions": shifted,
                "suggested_revision": (
                    "Narrow the hypothesis validity to explicitly stated boundary conditions. "
                    "Add at least two regime-shift predictions specifying what happens when key parameters "
                    "change (e.g., different dataset, different scale, different environment)."
                ),
            }
        )
    feasibility = report.get("feasibility_audit", {}) if isinstance(report.get("feasibility_audit"), dict) else {}
    if feasibility.get("verdict") in {"WARN", "FAIL"}:
        actions.append(
            {
                "action": "pre_experiment_feasibility_check",
                "reason": "Observable/control/boundary conditions are incomplete.",
                "issues": feasibility.get("issues_found", [])[:5],
            }
        )
    # Domain adaptability audit — the new check
    adaptability = report.get("domain_adaptability_audit", {}) if isinstance(report.get("domain_adaptability_audit"), dict) else {}
    if adaptability.get("verdict") == "FAIL":
        incompatibilities = adaptability.get("incompatibilities", [])
        adaptation_conditions = adaptability.get("adaptation_conditions", [])
        method_family = adaptability.get("method_family", "unknown")
        scenario_family = adaptability.get("scenario_family", "unknown")
        actions.append(
            {
                "action": "resolve_method_scenario_incompatibility",
                "reason": (
                    f"Method family '{method_family}' is fundamentally incompatible with scenario data types. "
                    f"The scenario produces {', '.join(adaptability.get('detected_scenario_data_types', []))} "
                    f"but the method requires {', '.join(incompatibilities)}."
                ),
                "incompatibilities": incompatibilities,
                "method_family": method_family,
                "scenario_family": scenario_family,
                "suggested_revision": (
                    "Either (a) replace the method with one compatible with the scenario's data types, "
                    "(b) narrow the hypothesis to a sub-claim where the method's requirements can be met, or "
                    "(c) explicitly state all adaptation conditions and provide bridging evidence. "
                    + " Required adaptation conditions: "
                    + "; ".join(adaptation_conditions[:3])
                ),
                "adaptation_conditions": adaptation_conditions,
            }
        )
    elif adaptability.get("verdict") == "WARN":
        actions.append(
            {
                "action": "address_domain_adaptability_concerns",
                "reason": "Cross-domain migration detected without sufficient bridging evidence.",
                "issues": adaptability.get("issues_found", [])[:5],
                "suggested_revision": (
                    "Provide explicit bridging rationale for applying the method to this scenario. "
                    "Address each prerequisite listed in the issues. "
                    "Consider narrowing the hypothesis to conditions where the method is validated."
                ),
            }
        )
    return actions

def yanzhen_detailed_reasoning(
    layer_1: dict[str, Any],
    layer_2: dict[str, Any],
    layer_3: dict[str, Any],
    chain_report: dict[str, Any],
    citation_report: dict[str, Any],
) -> str:
    return (
        f"Layer 1 verdict={layer_1.get('verdict')}; issues={layer_1.get('issues_found', [])}. "
        f"Causal chain verdict={chain_report.get('verdict')}; unsupported={chain_report.get('unsupported_links', [])}. "
        f"Layer 2 verdict={layer_2.get('verdict')}; alignment={layer_2.get('original_text_alignment')}; issues={layer_2.get('issues_found', [])}. "
        f"Selective citation verdict={citation_report.get('verdict')}; issues={citation_report.get('issues_found', [])}. "
        f"Layer 3 verdict={layer_3.get('verdict')}; stability={layer_3.get('mechanism_stability')}; CAWM risk={layer_3.get('cawm_risk_level')}. "
        "A hypothesis is accepted only if all layers pass and regime-shift risk remains low."
    )

def mechanism_internal_issues(statement: str, mechanism: str) -> list[str]:
    issues: list[str] = []
    if len(mechanism.strip()) < 40:
        issues.append("Mechanism description is too short to audit.")
    causal_markers = ("because", "therefore", "leads to", "causes", "if ", "then", "->")
    if not any(marker in mechanism.lower() for marker in causal_markers):
        issues.append("Mechanism lacks explicit causal links.")
    if statement and not shared_terms(statement, mechanism):
        issues.append("Mechanism shares too few key terms with the hypothesis statement.")
    return issues

def shared_terms(left: str, right: str) -> bool:
    left_terms = {term for term in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", left.lower())}
    right_terms = {term for term in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", right.lower())}
    return bool(left_terms & right_terms)

