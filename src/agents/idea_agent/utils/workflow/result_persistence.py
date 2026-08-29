"""Compact projections for persisted Idea Agent artifacts.

The MCTS workflow keeps rich objects in memory for search and synthesis.  This
module defines the smaller, stable views written to the run directory.  The
writer still uses the repository's pretty JSON format; only redundant fields
and nested diagnostics are removed here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Dict, Iterable, List
from pathlib import Path

from src.agents.idea_agent.utils.core.json_utils import write_json_file


_SCALAR_TYPES = (str, int, float, bool)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _records(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _project_records(
    value: Any,
    fields: Iterable[str],
    *,
    max_text_chars: int | None = None,
) -> List[Dict[str, Any]]:
    allowed = tuple(fields)
    projected: List[Dict[str, Any]] = []
    seen = set()
    for record in _records(value):
        item: Dict[str, Any] = {}
        for field in allowed:
            if field not in record or record[field] in (None, "", [], {}):
                continue
            raw = record[field]
            if isinstance(raw, Mapping):
                item[field] = dict(raw)
            elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
                item[field] = list(raw)
            elif isinstance(raw, _SCALAR_TYPES):
                if max_text_chars and isinstance(raw, str) and len(raw) > max_text_chars:
                    item[field] = raw[:max_text_chars].rstrip() + "…"
                else:
                    item[field] = raw
        if not item:
            continue
        marker = repr(sorted((key, repr(value)) for key, value in item.items()))
        if marker in seen:
            continue
        seen.add(marker)
        projected.append(item)
    return projected


def compact_experiment_handoff(handoff: Any) -> Dict[str, Any]:
    """Keep claim routing identifiers while dropping repeated evidence payloads."""
    if not isinstance(handoff, Mapping):
        return {}
    result: Dict[str, Any] = {}
    scalar_fields = (
        "claim_to_test",
        "scientific_object",
        "mechanism_to_discriminate",
        "claim_scope",
        "assumptions",
        "boundary_conditions",
        "alternative_explanations",
        "required_observations",
        "risks",
        "known_unknowns",
    )
    for field in scalar_fields:
        value = handoff.get(field)
        if value not in (None, "", [], {}):
            result[field] = value
    result["gap_ids"] = list(handoff.get("gap_ids") or [])
    result["gap_records"] = _project_records(
        handoff.get("gap_records"),
        (
            "gap_id",
            "gap_kind",
            "target_slot",
            "target_object",
            "statement",
            "why_it_matters",
            "gap_route",
            "seed_status",
        ),
    )
    result["evidence_roles"] = _project_records(
        handoff.get("evidence_roles"),
        (
            "role_id",
            "evidence_role_id",
            "subhypothesis_id",
            "gap_id",
            "target_slot",
            "role",
            "evidence_role",
            "expected_role",
            "allowed_support_kinds",
            "anchor_ids",
            "background_paper_ids",
            "paper_ids",
            "qualified_paper_ids",
            "claim_limits",
            "forbidden_as_direct_evidence",
            "status",
            "required",
        ),
        max_text_chars=1200,
    )
    result["source_anchors"] = _project_records(
        handoff.get("source_anchors"),
        (
            "anchor_id",
            "anchor_type",
            "claim_anchor",
            "label",
            "gap_id",
            "supports_gap_ids",
            "subhypothesis_id",
            "target_slot",
            "paper_id",
            "paper_ids",
            "paper_title",
            "title",
            "section",
            "locator",
            "source_pointer",
            "source_type",
            "text_excerpt",
        ),
        max_text_chars=1200,
    )
    return result


def compact_direction_document(direction: Any) -> Dict[str, Any]:
    """Project one public direction without embedding its MCTS candidate."""
    if not isinstance(direction, Mapping):
        return {}
    fields = (
        "idea_id",
        "seed_id",
        "route_id",
        "route_signature",
        "route_policy",
        "legacy_direction_mode",
        "mature_idea",
        "maturity",
        "maturity_is_not_rank",
        "maturity_status",
        "reframed_problem_id",
        "rejected_gap_ids",
        "invariant_status",
        "invariant_violations",
        "portfolio_score",
        "rejection_reason",
        "duplicate_of",
        "lineage",
        "source_lineage",
        "anti_anchor",
        "anti_anchor_reason",
        "direction_mode",
        "title",
        "abstract",
        "direction_summary",
        "hypothesis",
        "falsifier",
        "target_gap_ids",
        "gap_alignment",
        "scientificity_status",
        "debate",
        "experiment_handoff",
        "source_candidate_ids",
        "idea_source",
        "synthesis_notes",
    )
    result: Dict[str, Any] = {}
    for field in fields:
        value = direction.get(field)
        if value in (None, "", [], {}):
            continue
        if field == "experiment_handoff":
            result[field] = compact_experiment_handoff(value)
        elif field == "debate" and isinstance(value, Mapping):
            result[field] = compact_debate_summary(value)
        elif field == "gap_alignment":
            result[field] = _project_records(
                value,
                ("gap_id", "alignment", "relation", "status", "reason", "evidence_role_ids"),
            ) or value
        else:
            result[field] = value
    if "direction_mode" not in result:
        result["direction_mode"] = _text(direction.get("idea_taste_mode")) or "default"
    return result


def compact_candidate_entry(entry: Any) -> Dict[str, Any]:
    """Return the fields needed to reload a candidate as a future root seed."""
    if not isinstance(entry, Mapping):
        return {}
    fields = (
        "idea_id",
        "seed_id",
        "route_id",
        "route_signature",
        "route_policy",
        "legacy_direction_mode",
        "mature_idea",
        "maturity",
        "maturity_is_not_rank",
        "maturity_status",
        "reframed_problem_id",
        "rejected_gap_ids",
        "invariant_status",
        "invariant_violations",
        "portfolio_score",
        "rejection_reason",
        "duplicate_of",
        "lineage",
        "source_lineage",
        "anti_anchor",
        "anti_anchor_reason",
        "title",
        "abstract",
        "core_contribution",
        "method",
        "risks",
        "tags",
        "operator",
        "target_defects",
        "rationale",
        "memory_refs",
        "components",
        "component_explanations",
        "root_domains",
        "discipline_resolution",
        "scientific_intervention",
        "direction_mode",
        "direction_summary",
        "central_hypothesis",
        "scientific_object",
        "mechanism_or_relation",
        "intervention_or_transformation",
        "expected_mechanism",
        "discriminating_observation",
        "boundary_or_failure_condition",
        "claim_scope",
        "falsifier",
        "assumptions",
        "target_gap_ids",
        "gap_alignment",
        "evidence_requirement",
        "evidence_basis",
        "evaluation",
        "search_score",
        "search_path",
        "retrieved_core_titles",
        "idea_taste_mode",
        "idea_source",
        "source_modes",
        "scientificity_status",
        "synthesis_notes",
        "debate_status",
        "debate_failure_reason",
    )
    result: Dict[str, Any] = {}
    for field in fields:
        value = entry.get(field)
        if value in (None, "", [], {}):
            continue
        if field == "scientific_intervention":
            result[field] = _compact_intervention(value)
        elif field == "evaluation" and isinstance(value, Mapping):
            result[field] = _compact_evaluation(value)
        elif field == "gap_alignment":
            result[field] = _project_records(
                value,
                ("gap_id", "alignment", "relation", "status", "reason", "evidence_role_ids"),
            ) or value
        else:
            result[field] = value
    return result


def compact_mature_idea_contexts(value: Any) -> List[Dict[str, Any]]:
    """Persist bounded, idea-scoped evidence layers rather than raw Survey snapshots."""

    contexts: List[Dict[str, Any]] = []
    for context in _records(value):
        result: Dict[str, Any] = {}
        for field in (
            "idea_id",
            "idea_source",
            "public_facts",
            "retrieval_queries",
            "counterexamples",
            "mechanism_chain",
            "validation_targets",
            "anchor_policy",
            "anti_anchor",
            "anti_anchor_reason",
        ):
            raw = context.get(field)
            if raw not in (None, "", [], {}):
                result[field] = raw
        result["gap_explanation"] = _project_records(
            context.get("gap_explanation"),
            (
                "gap_id",
                "statement",
                "gap_kind",
                "target_slot",
                "target_object",
                "why_it_matters",
            ),
            max_text_chars=1600,
        )
        result["evidence_subset"] = _project_records(
            context.get("evidence_subset"),
            (
                "paper_id",
                "title",
                "paper_title",
                "abstract",
                "summary",
                "tldr",
                "url",
                "year",
            ),
            max_text_chars=1800,
        )[:8]
        scoped_handoff = context.get("survey_handoff")
        if isinstance(scoped_handoff, Mapping):
            result["survey_handoff"] = {
                key: scoped_handoff[key]
                for key in ("survey_run_id", "project_id", "topic", "profile_resolution", "constraints", "gaps", "gap_triage")
                if scoped_handoff.get(key) not in (None, "", [], {})
            }
            result["survey_handoff"]["gaps"] = _project_records(
                scoped_handoff.get("gaps"),
                ("gap_id", "statement", "gap_kind", "target_slot", "target_object", "why_it_matters"),
                max_text_chars=1600,
            )
            if isinstance(scoped_handoff.get("gap_triage"), Mapping):
                result["survey_handoff"]["gap_triage"] = {
                    "gaps": _project_records(
                        scoped_handoff["gap_triage"].get("gaps"),
                        ("gap_id", "eligibility_route", "status", "priority"),
                    )
                }
        if result:
            contexts.append(result)
    return contexts


def compact_mature_ideas(value: Any) -> List[Dict[str, Any]]:
    """Persist the mature-idea roster without raw generation state."""
    fields = (
        "idea_id", "title", "hypothesis", "central_hypothesis", "scientific_object",
        "mechanism", "mechanism_or_relation", "assumptions", "evidence_basis",
        "target_gap_ids", "gap_alignment", "refinement_scope", "falsifier",
        "maturity_status", "maturity", "maturity_is_not_rank", "idea_source",
        "lineage", "source_lineage", "route_signature", "independence_status",
        "independence_rationale", "anti_anchor", "anti_anchor_reason", "reframed_problem_id", "rejected_gap_ids",
    )
    return _project_records(value, fields, max_text_chars=2400)


def compact_route_clusters(value: Any) -> List[Dict[str, Any]]:
    fields = ("cluster_id", "seed_id", "seed_ids", "route_id", "route_ids", "route_signature", "candidate_ids", "candidate_count", "representative")
    clusters = _project_records(value, fields, max_text_chars=1800)
    for cluster in clusters:
        representative = cluster.get("representative")
        if isinstance(representative, Mapping):
            cluster["representative"] = compact_candidate_entry(representative)
    return clusters


def compact_idea_portfolio(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: Dict[str, Any] = {
        "schema_version": value.get("schema_version", "idea_portfolio_v1"),
        "topic": value.get("topic", ""),
        "mature_ideas": compact_mature_ideas(value.get("mature_ideas")),
        "route_clusters": compact_route_clusters(value.get("route_clusters")),
        "diversity_report": value.get("diversity_report") or {},
        "selection_rationale": value.get("selection_rationale", ""),
        "debate_summary": compact_stage_summary(value.get("debate_summary"), kind="debate") if isinstance(value.get("debate_summary"), Mapping) else {},
    }
    for field in ("selected_primary_idea", "competitive_ideas", "high_risk_ideas", "rejected_ideas"):
        raw = value.get(field)
        if field == "selected_primary_idea":
            result[field] = compact_candidate_entry(raw)
        elif isinstance(raw, (list, tuple)):
            result[field] = [compact_candidate_entry(item) for item in raw if isinstance(item, Mapping)]
        else:
            result[field] = []
    return {key: item for key, item in result.items() if item not in (None, "", [], {})}


def persist_idea_portfolio_files(
    run_dir: Path,
    portfolio: Mapping[str, Any] | None,
    mature_ideas: Any,
    logger: Any = None,
) -> Dict[str, str]:
    """Write portfolio projections; persistence failures never block the main result."""
    output: Dict[str, str] = {}
    documents = {
        "idea_portfolio.json": compact_idea_portfolio(portfolio or {}),
        "mature_ideas.json": {"schema_version": "mature_ideas_v1", "mature_ideas": compact_mature_ideas(mature_ideas)},
        "idea_route_clusters.json": {
            "schema_version": "idea_route_clusters_v1",
            "route_clusters": compact_route_clusters((portfolio or {}).get("route_clusters", [])),
        },
    }
    for filename, document in documents.items():
        if not document:
            continue
        try:
            path = Path(run_dir) / filename
            write_json_file(path, document)
            output[filename] = str(path)
        except (OSError, TypeError, ValueError) as exc:
            if logger is not None:
                try:
                    logger.warning("⚠️ Failed to persist %s: %s", filename, exc)
                except Exception:
                    pass
    return output


def _compact_intervention(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    fields = (
        "schema_version",
        "profile_id",
        "contribution_mode",
        "seed_id",
        "route_id",
        "route_policy",
        "direction_mode",
        "direction_summary",
        "scientific_object_schema",
        "hypothesis_contract",
        "hypothesis_seed_refs",
        "gap_seed_status",
    )
    result = {field: value[field] for field in fields if value.get(field) not in (None, "", [], {})}
    if isinstance(value.get("gap_routing"), Mapping):
        result["gap_routing"] = {
            key: _project_records(items, ("gap_id", "seed_id", "target_slot", "gap_route", "seed_status"))
            for key, items in value["gap_routing"].items()
            if _project_records(items, ("gap_id", "seed_id", "target_slot", "gap_route", "seed_status"))
        }
    return result


def _compact_evaluation(value: Mapping[str, Any]) -> Dict[str, Any]:
    allowed = (
        "novelty",
        "surprise",
        "feasibility",
        "clarity",
        "impact",
        "risk",
        "conciseness",
        "alignment_score",
        "complexity_penalty",
        "protocol_score",
        "explanatory_power",
        "identifiability",
        "boundary_calibration",
        "claim_overreach_penalty",
        "novelty_axes",
        "profile_id",
        "confidence",
        "failure_modes",
        "fairness_protocol",
        "feedback",
        "detected_defects",
        "defect_fix_summary",
        "composite",
    )
    return {field: value[field] for field in allowed if field in value}


def compact_mcts_evolution(evolution: Any) -> Dict[str, Any]:
    if not isinstance(evolution, Mapping):
        return {}
    result: Dict[str, Any] = {}
    for field in ("best_path", "best_operator", "target_defects"):
        if evolution.get(field) not in (None, "", [], {}):
            result[field] = evolution[field]
    iterations = []
    for item in _records(evolution.get("iterations")):
        projected = {
            field: item[field]
            for field in (
                "iteration",
                "node_id",
                "depth",
                "title",
                "operator",
                "defects",
                "score",
                "visits",
                "action_summary",
            )
            if field in item
        }
        if projected:
            iterations.append(projected)
    result["iterations"] = iterations
    pareto = evolution.get("pareto_front")
    if isinstance(pareto, Mapping):
        result["pareto_front"] = {
            str(label): _compact_pareto_candidate(candidate)
            for label, candidate in pareto.items()
            if candidate is not None
        }
    return result


def _compact_pareto_candidate(candidate: Any) -> Dict[str, Any]:
    if not isinstance(candidate, Mapping):
        return {}
    idea = candidate.get("idea") if isinstance(candidate.get("idea"), Mapping) else {}
    evaluation = candidate.get("evaluation") if isinstance(candidate.get("evaluation"), Mapping) else {}
    result = {
        field: idea[field]
        for field in ("title", "direction_mode", "idea_taste_mode", "target_gap_ids")
        if field in idea
    }
    for field in ("score", "path"):
        if field in candidate:
            result[field] = candidate[field]
    if "composite" in evaluation and "score" not in result:
        result["score"] = evaluation["composite"]
    return result


def compact_debate_summary(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: Dict[str, Any] = {}
    for field in ("status", "round_count", "failure_reason", "direction_mode", "debate_status", "mode", "representative_count", "pairs", "failures", "identity_violations", "gap_mapping_violation"):
        if value.get(field) not in (None, "", [], {}):
            result[field] = value[field]
    trace = []
    for event in _records(value.get("trace") or value.get("debate_trace")):
        trace.append(_compact_debate_event(event))
    if trace:
        result["trace"] = trace
    if "round" in value and not trace:
        result.update(_compact_debate_event(value))
    return result


def _compact_debate_event(event: Mapping[str, Any]) -> Dict[str, Any]:
    fields = (
        "round",
        "direction_mode",
        "question_type",
        "target_claim",
        "scientific_concern",
        "opponent_concern",
        "severity",
        "required_revision",
        "revision_applied",
        "changed_field",
        "actual_missing_fields",
        "profile_drift_fields",
        "preflight_missing",
        "postflight_missing",
        "preflight_changed_fields",
        "postflight_changed_fields",
        "preflight_profile_drift_fields",
        "postflight_profile_drift_fields",
        "alternative_explanations",
        "falsifier",
        "next_observation",
        "final_scope",
        "final_status",
        "identity_violations",
        "gap_mapping_violation",
        "status",
        "challenge",
        "revision",
    )
    result: Dict[str, Any] = {}
    for field in fields:
        value = event.get(field)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, str) and len(value) > 2000:
            value = value[:2000].rstrip() + "…"
        result[field] = value
    return result


def compact_stage_summary(value: Any, *, kind: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: Dict[str, Any] = {}
    for field in (
        "synthesis_mode",
        "debate_mode",
        "debate_layers",
        "round_count",
        "direction_count",
        "primary_direction",
        "expected_direction_modes",
        "cross_direction_notes",
        "fallbacks",
        "failures",
        "matrix_cells",
        "seed_groups",
        "route_clusters",
        "diversity_report",
        "internal_debate",
        "cross_seed_debate",
        "pairs",
    ):
        if value.get(field) not in (None, "", [], {}):
            result[field] = value[field]
    directions = []
    for direction in _records(value.get("directions")):
        item = {
            field: direction[field]
            for field in ("idea_id", "seed_id", "route_id", "direction_mode", "idea_taste_mode", "title", "scientificity_status", "debate_status")
            if direction.get(field) not in (None, "", [], {})
        }
        if item:
            directions.append(item)
    if directions:
        result["directions"] = directions
    result["kind"] = kind
    return result


def compact_result_payload(payload: Any) -> Dict[str, Any]:
    """Build the persisted public result without raw stage snapshots."""
    if not isinstance(payload, Mapping):
        return {}
    result: Dict[str, Any] = {}
    public_fields = (
        "schema_version",
        "title",
        "abstract",
        "method",
        "introduction",
        "components",
        "algorithm",
        "scientific_spec",
        "materialization_profile",
        "reference_papers",
        "idea_source",
        "source_modes",
        "fusion_metadata",
        "fusion_evolution",
        "idea_contract",
        "topic",
        "mature_idea",
        "mature_ideas",
        "mature_idea_contexts",
        "survey_binding",
        "primary_direction",
        "cross_direction_notes",
        "artifact_refs",
    )
    for field in public_fields:
        value = payload.get(field)
        if value not in (None, "", [], {}):
            if field == "mature_idea_contexts":
                result[field] = compact_mature_idea_contexts(value)
            elif field == "mature_ideas":
                result[field] = compact_mature_ideas(value)
            elif field == "fusion_evolution" and isinstance(value, Mapping):
                result[field] = compact_fusion_evolution(value)
            else:
                result[field] = value

    result["directions"] = [
        compact_direction_document(direction)
        for direction in _records(payload.get("directions"))
        if compact_direction_document(direction)
    ]
    if isinstance(payload.get("mcts_evolution"), Mapping):
        result["mcts_evolution"] = compact_mcts_evolution(payload["mcts_evolution"])
    if isinstance(payload.get("direction_synthesis"), Mapping):
        result["direction_synthesis"] = compact_stage_summary(
            payload["direction_synthesis"], kind="direction_synthesis"
        )
    if isinstance(payload.get("debate_result"), Mapping):
        result["debate_result"] = compact_stage_summary(payload["debate_result"], kind="debate")
    if payload.get("debate_trace"):
        result["debate_trace"] = [
            compact_debate_summary(item) for item in _records(payload.get("debate_trace"))
        ]
    if isinstance(payload.get("legacy_best_entry"), Mapping):
        result["legacy_best_entry"] = compact_candidate_entry(payload["legacy_best_entry"])
    elif isinstance(payload.get("idea"), Mapping):
        result["candidate"] = compact_candidate_entry(payload)

    result["persistence"] = {
        "mode": "public_compact",
        "omitted_fields": [
            "search_trace",
            "pareto_candidates",
            "raw_direction_synthesis_directions",
            "raw_debate_result_directions",
            "nested_idea_result",
            "full_legacy_best_entry",
        ],
    }
    return result


def compact_fusion_evolution(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result = {
        field: value[field]
        for field in (
            "source_modes",
            "host_idea_mode",
            "selected_components",
            "rejected_components",
            "conflicts_and_resolutions",
            "fused_core_thesis",
            "why_stronger_than_each_input",
            "minimal_validation_plan",
        )
        if value.get(field) not in (None, "", [], {})
    }
    if isinstance(value.get("post_fusion_evaluation"), Mapping):
        result["post_fusion_evaluation"] = compact_mcts_evolution(value["post_fusion_evaluation"])
    return result
