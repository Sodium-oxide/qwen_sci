"""Workflow helpers for idea traces and fallback specs."""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, List

from src.agents.idea_agent.utils.workflow.idea_contract import normalize_idea_contract


_DEBATE_STATUSES = {
    "SCIENTIFICALLY_QUALIFIED",
    "SCIENTIFICALLY_QUALIFIED_WITH_UNCERTAINTY",
    "NEEDS_SCOPE_REDUCTION",
    "PROFILE_DRIFT",
    "REQUIRES_REVIEW",
    "LOWER_CONFIDENCE",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _texts(value: Any) -> List[str]:
    values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    result: List[str] = []
    seen = set()
    for value_item in values:
        item = _text(value_item)
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, (list, tuple)):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def build_survey_binding(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Project the immutable Survey identity into the public Idea result."""
    try:
        from src.agents.idea_agent.agent.artifacts import artifact_get

        context = artifact_get(artifact, "survey_idea_context", {})
    except (KeyError, TypeError):
        context = {}
    context = _mapping(context)
    manifest = _mapping(context.get("manifest"))
    handoff = _mapping(context.get("handoff"))
    manifest_path = _text(context.get("manifest_path") or manifest.get("manifest_path"))
    survey_run_id = _text(context.get("survey_run_id") or manifest.get("survey_run_id") or handoff.get("survey_run_id"))
    project_id = _text(context.get("project_id") or manifest.get("project_id") or handoff.get("project_id"))
    project_fingerprint = _text(
        context.get("project_context_fingerprint")
        or manifest.get("project_context_fingerprint")
        or handoff.get("project_context_fingerprint")
    )
    handoff_fingerprint = _text(
        context.get("handoff_fingerprint")
        or handoff.get("handoff_fingerprint")
        or manifest.get("handoff_fingerprint")
    )
    manifest_exists = bool(manifest_path and Path(manifest_path).is_file())
    status = "bound" if manifest_exists else "missing"
    return {
        "status": status,
        "manifest_path": manifest_path,
        "survey_run_id": survey_run_id,
        "project_id": project_id,
        "project_context_fingerprint": project_fingerprint,
        "handoff_fingerprint": handoff_fingerprint,
    }


def _direction_gap_records(direction: Dict[str, Any], artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
    intervention = _mapping(direction.get("scientific_intervention"))
    refs = _records(intervention.get("hypothesis_seed_refs"))
    context = {}
    try:
        from src.agents.idea_agent.agent.artifacts import artifact_get

        context = _mapping(artifact_get(artifact, "survey_idea_context", {}))
    except (KeyError, TypeError):
        pass
    handoff = _mapping(context.get("handoff"))
    gaps = _records(handoff.get("gaps"))
    gap_ids = set(_texts(direction.get("target_gap_ids")))
    if not gap_ids:
        gap_ids = {_text(item.get("gap_id")) for item in refs if _text(item.get("gap_id"))}
    records: List[Dict[str, Any]] = []
    for gap in gaps:
        gap_id = _text(gap.get("gap_id"))
        if gap_id and gap_id in gap_ids:
            records.append(
                {
                    "gap_id": gap_id,
                    "statement": _text(gap.get("statement")),
                    "gap_kind": _text(gap.get("gap_kind")),
                    "target_slot": _text(gap.get("target_slot")),
                    "target_object": _text(gap.get("target_object")),
                    "why_it_matters": _text(gap.get("why_it_matters")),
                }
            )
    for ref in refs:
        gap_id = _text(ref.get("gap_id"))
        if gap_id and gap_id in gap_ids and not any(item.get("gap_id") == gap_id for item in records):
            records.append({"gap_id": gap_id, "gap_route": _text(ref.get("gap_route")), "seed_status": _text(ref.get("seed_status"))})
    return records


def project_hypothesis(direction: Dict[str, Any]) -> Dict[str, Any]:
    """Return the stable, experiment-agent-facing scientific hypothesis contract."""
    intervention = _mapping(direction.get("scientific_intervention"))
    contract = _mapping(intervention.get("hypothesis_contract"))

    def value(key: str, default: Any = "") -> Any:
        raw = direction.get(key)
        if raw in (None, "", [], {}):
            raw = contract.get(key, default)
        return raw

    scientific_object = value("scientific_object", {})
    if not isinstance(scientific_object, dict):
        scientific_object = {"description": _text(scientific_object)} if _text(scientific_object) else {}
    assumptions = _texts(value("assumptions", []))
    return {
        "central_hypothesis": _text(value("central_hypothesis")),
        "scientific_object": scientific_object,
        "mechanism_or_relation": _text(value("mechanism_or_relation") or value("expected_mechanism")),
        "intervention_or_transformation": _text(value("intervention_or_transformation")),
        "expected_mechanism": _text(value("expected_mechanism")),
        "discriminating_observation": _text(value("discriminating_observation")),
        "evidence_requirement": _text(value("evidence_requirement")),
        "evidence_basis": value("evidence_basis", {}),
        "boundary_or_failure_condition": _text(value("boundary_or_failure_condition")),
        "claim_scope": _text(value("claim_scope")),
        "assumptions": assumptions,
    }


def build_experiment_handoff(direction: Dict[str, Any], artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Expose only claims and observations; never an executable experiment plan."""
    hypothesis = project_hypothesis(direction)
    intervention = _mapping(direction.get("scientific_intervention"))
    seed_refs = _records(intervention.get("hypothesis_seed_refs"))
    gap_records = _direction_gap_records(direction, artifact)
    gap_ids = _texts(direction.get("target_gap_ids")) or _texts([item.get("gap_id") for item in gap_records])
    evidence_roles: List[Dict[str, Any]] = []
    source_anchors: List[Dict[str, Any]] = []
    unknowns = _texts(
        direction.get("known_unknowns")
        or direction.get("unknowns")
        or direction.get("unknown_or_unverified")
    )
    evidence_roles.extend(_records(direction.get("evidence_roles")))
    source_anchors.extend(_records(direction.get("source_anchors")))
    for seed in seed_refs:
        for role in _records(seed.get("evidence_roles")):
            if role not in evidence_roles:
                evidence_roles.append(role)
        for anchor in _records(seed.get("source_anchors")):
            if anchor not in source_anchors:
                source_anchors.append(anchor)
        unknowns.extend(_texts(seed.get("unknown_or_unverified")))
    context = {}
    try:
        from src.agents.idea_agent.agent.artifacts import artifact_get

        context = _mapping(artifact_get(artifact, "survey_idea_context", {}))
    except (KeyError, TypeError):
        pass
    handoff = _mapping(context.get("handoff"))
    anchor_index = {
        _text(anchor.get("anchor_id")): dict(anchor)
        for anchor in _records(handoff.get("anchors"))
        if _text(anchor.get("anchor_id"))
    }
    for gap in gap_records:
        for anchor_id in _texts(next((item.get("anchor_ids") for item in _records(handoff.get("gaps")) if item.get("gap_id") == gap.get("gap_id")), [])):
            if anchor_id in anchor_index and anchor_index[anchor_id] not in source_anchors:
                source_anchors.append(anchor_index[anchor_id])
    roles_from_handoff = _records(handoff.get("evidence_roles"))
    gap_slots = _texts([gap.get("target_slot") for gap in gap_records])
    for role in roles_from_handoff:
        if (_text(role.get("gap_id")) in gap_ids or _text(role.get("target_slot")) in gap_slots) and role not in evidence_roles:
            evidence_roles.append(role)
    required_observations = _texts(
        direction.get("required_observations")
        or direction.get("discriminating_observation")
        or hypothesis.get("discriminating_observation")
    )
    required_observations.extend(_texts(direction.get("evidence_requirement") or hypothesis.get("evidence_requirement")))
    required_observations = _texts(required_observations)
    alternatives = _texts(direction.get("alternative_explanations"))
    if not alternatives:
        for event in _records(direction.get("debate_trace")):
            alternatives.extend(_texts(event.get("alternative_explanations")))
        alternatives = _texts(alternatives)
    risks = _texts(direction.get("risks"))
    return {
        "claim_to_test": hypothesis["central_hypothesis"],
        "gap_ids": gap_ids,
        "gap_records": gap_records,
        "scientific_object": hypothesis["scientific_object"],
        "mechanism_to_discriminate": hypothesis["mechanism_or_relation"],
        "claim_scope": hypothesis["claim_scope"],
        "assumptions": hypothesis["assumptions"],
        "boundary_conditions": _texts(hypothesis["boundary_or_failure_condition"]),
        "alternative_explanations": alternatives,
        "required_observations": required_observations,
        "evidence_roles": evidence_roles,
        "source_anchors": source_anchors,
        "risks": risks,
        "known_unknowns": _texts(unknowns),
    }


def build_direction_result_document(
    topic: str,
    direction: Dict[str, Any],
    artifact: Dict[str, Any],
    survey_binding: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    binding = dict(survey_binding or build_survey_binding(artifact))
    status = _text(direction.get("scientificity_status") or direction.get("debate_status")).upper()
    if status not in _DEBATE_STATUSES:
        status = "SCIENTIFICALLY_QUALIFIED_WITH_UNCERTAINTY"
    if binding.get("status") == "missing":
        status = "REQUIRES_REVIEW"
    direction_payload = {
        "direction_mode": _text(direction.get("direction_mode") or direction.get("idea_taste_mode")) or "default",
        "title": _text(direction.get("title")),
        "abstract": _text(direction.get("abstract")),
        "hypothesis": project_hypothesis(direction),
        "target_gap_ids": _texts(direction.get("target_gap_ids")),
        "gap_alignment": direction.get("gap_alignment") or [],
        "scientificity_status": status,
        "debate": _mapping(direction.get("debate_trace")) if isinstance(direction.get("debate_trace"), dict) else {
            "status": _text(direction.get("debate_status") or status),
            "trace": direction.get("debate_trace") or [],
        },
        "experiment_handoff": build_experiment_handoff(direction, artifact),
    }
    for mature_field in (
        "mature_idea",
        "maturity",
        "maturity_is_not_rank",
        "maturity_status",
        "lineage",
        "source_lineage",
        "idea_source",
        "independence_rationale",
        "anchor_policy",
        "anti_anchor",
        "anti_anchor_reason",
    ):
        if direction.get(mature_field) not in (None, "", [], {}):
            direction_payload[mature_field] = direction.get(mature_field)
    for identity_key in (
        "idea_id",
        "seed_id",
        "route_id",
        "route_signature",
        "route_policy",
        "legacy_direction_mode",
    ):
        if direction.get(identity_key) not in (None, "", [], {}):
            direction_payload[identity_key] = direction.get(identity_key)
    return {
        "schema_version": "idea_result_v5",
        "topic": topic,
        "survey_binding": binding,
        "directions": [direction_payload],
        "primary_direction": _text(direction.get("direction_mode") or direction.get("idea_taste_mode")) or "default",
        "legacy_best_entry": dict(direction),
    }

def build_mcts_evolution(best_entry: Dict[str, Any]) -> Dict[str, Any]:
    trace = best_entry.get("search_trace") or []
    iterations: List[Dict[str, Any]] = []
    for hop in trace:
        if not isinstance(hop, dict):
            continue
        entry = {
            "iteration": hop.get("iteration"),
            "node_id": hop.get("node_id"),
            "depth": hop.get("depth"),
            "title": hop.get("title"),
            "operator": hop.get("operator"),
            "defects": hop.get("defects"),
            "score": hop.get("score"),
            "visits": hop.get("visits"),
            "path": hop.get("path"),
            "action_summary": hop.get("action_summary"),
        }
        evaluation = hop.get("evaluation")
        if evaluation is not None:
            entry["evaluation"] = evaluation
        memory_refs = hop.get("memory_refs")
        if memory_refs:
            entry["memory_refs"] = memory_refs
        rationale = hop.get("rationale")
        if rationale:
            entry["rationale"] = rationale
        signature = hop.get("signature")
        if signature:
            entry["signature"] = signature
        iterations.append(entry)
    evolution = {
        "best_path": best_entry.get("search_path"),
        "best_operator": best_entry.get("operator"),
        "target_defects": best_entry.get("target_defects"),
        "iterations": iterations,
    }
    pareto = best_entry.get("pareto_candidates")
    if pareto:
        evolution["pareto_front"] = pareto
    return evolution


def build_fusion_evolution(best_entry: Dict[str, Any]) -> Dict[str, Any]:
    fusion_metadata = best_entry.get("fusion_metadata")
    if not isinstance(fusion_metadata, dict):
        fusion_metadata = {}

    return {
        "source_modes": best_entry.get("source_modes") or [],
        "host_idea_mode": fusion_metadata.get("host_idea_mode"),
        "selected_components": fusion_metadata.get("selected_components") or [],
        "rejected_components": fusion_metadata.get("rejected_components") or [],
        "conflicts_and_resolutions": fusion_metadata.get("conflicts_and_resolutions") or [],
        "fused_core_thesis": fusion_metadata.get("fused_core_thesis") or "",
        "why_stronger_than_each_input": fusion_metadata.get("why_stronger_than_each_input") or "",
        "minimal_validation_plan": fusion_metadata.get("minimal_validation_plan") or "",
        "post_fusion_evaluation": build_mcts_evolution(best_entry),
    }


def collect_reference_material(reference_batches: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    references: List[Dict[str, Any]] = []
    seen_titles = set()
    for batch in reference_batches or []:
        for paper in batch:
            if not isinstance(paper, dict):
                continue
            title = (paper.get("title") or "").strip()
            if not title:
                continue
            key = title.lower()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            entry = {
                "title": title,
                "authors": paper.get("authors") or [],
                "abstract": paper.get("abstract") or paper.get("summary"),
                "tldr": paper.get("tldr") or paper.get("summary"),
                "summary": paper.get("summary") or paper.get("insight"),
                "url": paper.get("url"),
                "year": paper.get("year"),
                "paper_id": paper.get("paper_id"),
                "node_id": paper.get("node_id"),
                "paper_domain": paper.get("paper_domain"),
                "source_keywords": paper.get("source_keywords"),
            }
            references.append(entry)
    return references


def derive_pipeline_steps(idea: Dict[str, Any]) -> List[str]:
    idea = normalize_idea_contract(idea, keep_extra=True)
    sections = [
        idea.get("method"),
        idea.get("abstract"),
        idea.get("core_contribution"),
    ]
    sentences: List[str] = []
    for section in sections:
        if not section:
            continue
        chunks = re.split(r"(?<=[.;])\s+", section)
        for chunk in chunks:
            cleaned = chunk.strip(" .;\n")
            if cleaned:
                sentences.append(cleaned)
            if len(sentences) >= 6:
                break
        if len(sentences) >= 3:
            break
    if not sentences:
        sentences = ["Outline the proposed method using available context."]
    return [f"Step {idx + 1}: {sentence}" for idx, sentence in enumerate(sentences)]


def fallback_algorithm_spec(idea: Dict[str, Any]) -> List[Dict[str, Any]]:
    pipeline = derive_pipeline_steps(idea)
    inputs = []
    components = idea.get("components") or []
    if isinstance(components, list):
        inputs.extend(
            [
                f"Component: {str(component).strip()}"
                for component in components
                if str(component).strip()
            ][:5]
        )
    if not inputs:
        inputs = ["Inputs implied by the idea description"]

    outputs = []
    core_contribution = str(idea.get("core_contribution") or "").strip()
    if core_contribution:
        outputs.append(core_contribution)
    if not outputs:
        outputs = ["Outputs implied by the idea description"]

    algorithm_entry = {
        "name": idea.get("title") or "Research Algorithm",
        "input": inputs,
        "output": outputs,
        "pipeline": pipeline,
    }
    return [algorithm_entry]
