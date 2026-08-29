"""Top-level LigAgent control flow and final idea persistence helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agents.idea_agent.agent.artifacts import artifact_get, artifact_set
from src.agents.idea_agent.agent.prompts import PROMPTS
from src.agents.idea_agent.utils.core.json_utils import write_json_file
from src.agents.idea_agent.utils.workflow.idea_helpers import (
    build_direction_result_document,
    build_fusion_evolution,
    build_mcts_evolution,
    build_survey_binding,
    collect_reference_material,
)
from src.agents.idea_agent.utils.workflow.result_persistence import (
    compact_candidate_entry,
    compact_direction_document,
    compact_result_payload,
    persist_idea_portfolio_files,
)
from src.agents.idea_agent.utils.workflow.stage_contract import StageContext
from src.agents.idea_agent.utils.workflow.idea_contract import (
    mature_idea_legacy_text,
    normalize_mature_ideas,
)
from src.agents.idea_agent.utils.workflow.workflow_runtime import (
    StageSpec,
    WorkflowEdge,
    WorkflowSpec,
)
from src.agents.idea_agent.utils.workflow.ligagent_helpers import (
    build_profile_aware_materialization,
    collect_rag_citations,
)
from src.agents.idea_agent.utils.workflow.ligagent_utils import (
    align_public_idea_entry,
    collect_paper_context_entries,
    generate_idea_introduction,
)


def build_main_workflow(agent, logger) -> WorkflowSpec:
    ablation_results = artifact_get(agent.artifact, "ablation_results", [])
    has_ablation = bool(ablation_results)

    if has_ablation:
        flow = [
            "advanced_analysis", "re_analysis_replan",
            "mature_idea_portfolio_generation", "mature_idea_adjudication",
            "route_context_preparation", "idea_generation", "diversity_adjudication",
            "cross_seed_debate", "portfolio_synthesis", "primary_idea_materialization",
        ]
        logger.info("📋 ablation_results present — using flow: %s", " -> ".join(flow))
        transitions = {
            "advanced_analysis": [WorkflowEdge("re_analysis_replan")],
            "re_analysis_replan": [WorkflowEdge("mature_idea_portfolio_generation")],
            "mature_idea_portfolio_generation": [WorkflowEdge("mature_idea_adjudication")],
            "mature_idea_adjudication": [WorkflowEdge("route_context_preparation")],
            "route_context_preparation": [WorkflowEdge("idea_generation")],
            "idea_generation": [WorkflowEdge("diversity_adjudication")],
            "diversity_adjudication": [WorkflowEdge("cross_seed_debate")],
            "cross_seed_debate": [WorkflowEdge("portfolio_synthesis")],
            "portfolio_synthesis": [WorkflowEdge("primary_idea_materialization")],
        }
        entry_stage = "advanced_analysis"
    else:
        flow = [
            "knowledge_aquisition", "advanced_analysis",
            "mature_idea_portfolio_generation", "mature_idea_adjudication",
            "route_context_preparation", "idea_generation", "diversity_adjudication",
            "cross_seed_debate", "portfolio_synthesis", "primary_idea_materialization",
        ]
        logger.info("📋 ablation_results empty — using flow: %s", " -> ".join(flow))
        transitions = {
            "knowledge_aquisition": [WorkflowEdge("advanced_analysis")],
            "advanced_analysis": [WorkflowEdge("mature_idea_portfolio_generation")],
            "mature_idea_portfolio_generation": [WorkflowEdge("mature_idea_adjudication")],
            "mature_idea_adjudication": [WorkflowEdge("route_context_preparation")],
            "route_context_preparation": [WorkflowEdge("idea_generation")],
            "idea_generation": [WorkflowEdge("diversity_adjudication")],
            "diversity_adjudication": [WorkflowEdge("cross_seed_debate")],
            "cross_seed_debate": [WorkflowEdge("portfolio_synthesis")],
            "portfolio_synthesis": [WorkflowEdge("primary_idea_materialization")],
        }
        entry_stage = "knowledge_aquisition"

    # build main workflow spec with conditional transitions based on RAG hits
    return WorkflowSpec(
        name="ligagent.main",
        entry_stage=entry_stage,
        stages=_build_stage_specs(agent),
        transitions=transitions,
    )


def make_stage_context(agent, workflow_name: str, **inputs: Any) -> StageContext:
    return StageContext(
        agent=agent,
        artifact=agent.artifact,
        workflow_name=workflow_name,
        session=getattr(agent, "session", None),
        runtime=getattr(agent, "runtime", None),
        inputs=inputs,
        logger=getattr(agent, "logger", None),
    )


def _build_stage_specs(agent) -> Dict[str, StageSpec]:
    return {
        "knowledge_aquisition": StageSpec(
            name="knowledge_aquisition",
            handler=agent._execute_knowledge_acquisition_stage,
            description="Semantic Scholar seed -> RAG query -> OutcomeRAG -> citation expansion -> triage",
            record_step=True,
            allowed_artifact_namespaces={"retrieval"},
        ),
        "advanced_analysis": StageSpec(
            name="advanced_analysis",
            handler=agent._execute_advanced_analysis_stage,
            description="Diagnose survey gaps and derive a conservative 1.1 root idea",
            record_step=True,
            allowed_artifact_namespaces={"analysis", "run"},
        ),
        "idea_generation": StageSpec(
            name="idea_generation",
            handler=agent._execute_idea_generation_stage,
            description="Prepare context, run memory-guided MCTS, materialize and persist best idea",
            record_step=True,
            allowed_artifact_namespaces={"ideation", "persistence"},
        ),
        "re_analysis_replan": StageSpec(
            name="re_analysis_replan",
            handler=agent._execute_reanalysis_replan_stage,
            description="Apply minimal evidence-driven patches to the mature idea",
            record_step=True,
            allowed_artifact_namespaces={"run", "retrieval", "analysis"},
        ),
        "mature_idea_portfolio_generation": StageSpec(
            name="mature_idea_portfolio_generation",
            handler=agent._execute_mature_idea_portfolio_generation_stage,
            description="Collect and preserve multiple mature-idea seeds",
            record_step=True,
        ),
        "mature_idea_adjudication": StageSpec(
            name="mature_idea_adjudication",
            handler=agent._execute_mature_idea_adjudication_stage,
            description="Adjudicate mature-idea independence and maturity state",
            record_step=True,
        ),
        "route_context_preparation": StageSpec(
            name="route_context_preparation",
            handler=agent._execute_route_context_preparation_stage,
            description="Prepare idea-scoped evidence and route contexts",
            record_step=True,
        ),
        "diversity_adjudication": StageSpec(
            name="diversity_adjudication",
            handler=agent._execute_diversity_adjudication_stage,
            description="Adjudicate route clusters and homogeneous variants",
            record_step=True,
        ),
        "cross_seed_debate": StageSpec(
            name="cross_seed_debate",
            handler=agent._execute_cross_seed_debate_stage,
            description="Compare representative candidates across mature-idea seeds",
            record_step=True,
        ),
        "portfolio_synthesis": StageSpec(
            name="portfolio_synthesis",
            handler=agent._execute_portfolio_synthesis_stage,
            description="Select primary, competitive, high-risk, and rejected ideas",
            record_step=True,
        ),
        "primary_idea_materialization": StageSpec(
            name="primary_idea_materialization",
            handler=agent._execute_primary_idea_materialization_stage,
            description="Expose the selected primary idea for Experiment Agent compatibility",
            record_step=True,
        ),
    }


def run_agent_loop(agent, logger) -> None:
    """Run the explicit top-level LigAgent workflow."""
    spec = build_main_workflow(agent, logger)
    agent.workflow_executor.run(
        spec,
        make_stage_context(agent, workflow_name=spec.name),
    )


def build_idea_result_payload(
    best_entry: Dict[str, Any],
    paper_entries: List[Dict[str, Any]],
    artifact: Dict[str, Any],
    chat_fn,
    model: str,
    logger,
    prompts: Optional[Dict[str, str]] = None,
    mature_idea_override: Optional[str] = None,
    refinement_scope_override: Optional[str] = None,
    direction_synthesis: Optional[Dict[str, Any]] = None,
    scientific_debate: Optional[Dict[str, Any]] = None,
    mature_idea_contexts: Optional[List[Dict[str, Any]]] = None,
    mature_ideas: Optional[List[Dict[str, Any]]] = None,
    idea_portfolio: Optional[Dict[str, Any]] = None,
    introduction_max_output_tokens: Optional[int] = None,
    introduction_json_repair_attempts: Optional[int] = None,
) -> Dict[str, Any]:
    prompts = prompts or PROMPTS
    topic_history = artifact_get(artifact, "topic", [])
    topic = topic_history[-1] if topic_history else "unspecified topic"
    mature_idea_records = normalize_mature_ideas(
        mature_ideas if isinstance(mature_ideas, list) else artifact_get(artifact, "mature_ideas", []),
        legacy_value=artifact_get(artifact, "mature_idea", ""),
    )
    mature_idea = str(
        mature_idea_override
        if mature_idea_override is not None
        else artifact_get(artifact, "mature_idea", "")
    ).strip()
    stored_mature_idea_contexts = artifact_get(artifact, "mature_idea_contexts", [])
    mature_idea_context_records = [
        dict(item)
        for item in (
            mature_idea_contexts
            if isinstance(mature_idea_contexts, list)
            else stored_mature_idea_contexts if isinstance(stored_mature_idea_contexts, list) else []
        )
        if isinstance(item, dict)
    ]
    refinement_scope = str(
        refinement_scope_override
        if refinement_scope_override is not None
        else artifact_get(artifact, "refinement_scope", "")
    ).strip()
    entries = paper_entries or collect_paper_context_entries(
        artifact, artifact_get(artifact, "references", [])
    )
    public_entry = align_public_idea_entry(
        chat_fn=chat_fn,
        prompt_template=prompts["idea_result_alignment"],
        model=model,
        topic=topic,
        best_entry=best_entry,
        mature_idea=mature_idea,
        refinement_scope=refinement_scope,
        paper_entries=entries,
        logger=logger,
    )
    materialization = build_profile_aware_materialization(
        public_entry,
        topic,
        prompts,
        chat_fn,
        model,
        logger,
    )
    introduction = generate_idea_introduction(
        chat_fn=chat_fn,
        prompt_template=prompts["idea_introduction"],
        model=model,
        topic=topic,
        best_entry=public_entry,
        paper_entries=entries,
        mature_idea=mature_idea,
        logger=logger,
        max_output_tokens=introduction_max_output_tokens or 25600,
        json_repair_attempts=(
            2
            if introduction_json_repair_attempts is None
            else introduction_json_repair_attempts
        ),
    )
    component_entries = public_entry.get("components_with_explanations")
    if not isinstance(component_entries, list):
        raw_components = public_entry.get("components") or []
        raw_explanations = public_entry.get("component_explanations") or {}
        component_entries = []
        if isinstance(raw_components, list):
            for component in raw_components:
                name = str(component).strip()
                if not name:
                    continue
                explanation = ""
                if isinstance(raw_explanations, dict):
                    explanation = str(raw_explanations.get(name, "")).strip()
                component_entries.append(
                    {
                        "component": name,
                        "explanation": explanation,
                    }
                )
    reference_titles: List[str] = []
    seen_reference_titles = set()
    rag_entries = artifact_get(artifact, "rag_hits", [])
    if isinstance(rag_entries, list):
        for rag_entry in rag_entries:
            hits = []
            if isinstance(rag_entry, dict):
                hits = rag_entry.get("hits") or []
            elif isinstance(rag_entry, list):
                hits = rag_entry
            for title in collect_rag_citations(hits):
                if not title:
                    continue
                key = title.lower()
                if key in seen_reference_titles:
                    continue
                seen_reference_titles.add(key)
                reference_titles.append(title)
    for reference in collect_reference_material(artifact_get(artifact, "references", [])):
        if not isinstance(reference, dict):
            continue
        title = str(reference.get("title") or "").strip()
        if not title:
            continue
        key = title.lower()
        if key in seen_reference_titles:
            continue
        seen_reference_titles.add(key)
        reference_titles.append(title)
    for title in best_entry.get("retrieved_core_titles") or []:
        cleaned = str(title or "").strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen_reference_titles:
            continue
        seen_reference_titles.add(key)
        reference_titles.append(cleaned)
    mcts_evolution = build_mcts_evolution(best_entry)
    payload = {
        "title": public_entry.get("title"),
        "abstract": public_entry.get("abstract"),
        "method": public_entry.get("method"),
        "introduction": introduction,
        "components": component_entries,
        "algorithm": materialization.get("legacy_algorithm", []),
        "scientific_spec": materialization.get("scientific_spec", {}),
        "materialization_profile": materialization.get("profile_id", "generic_scientific"),
        "reference_papers": reference_titles,
        "mcts_evolution": mcts_evolution,
        "mature_ideas": mature_idea_records,
        "mature_idea": mature_idea or mature_idea_legacy_text(mature_idea_records),
        "mature_idea_contexts": mature_idea_context_records,
    }
    if best_entry.get("idea_source"):
        payload["idea_source"] = best_entry.get("idea_source")
    if isinstance(best_entry.get("source_modes"), list) and best_entry.get("source_modes"):
        payload["source_modes"] = best_entry.get("source_modes")
    if isinstance(best_entry.get("fusion_metadata"), dict) and best_entry.get("fusion_metadata"):
        payload["fusion_metadata"] = best_entry.get("fusion_metadata")
    if best_entry.get("idea_source") == "fused":
        payload["fusion_evolution"] = build_fusion_evolution(best_entry)
    if best_entry.get("idea_contract"):
        payload["idea_contract"] = best_entry.get("idea_contract")
    directions: List[Dict[str, Any]] = []
    if isinstance(scientific_debate, dict) and isinstance(scientific_debate.get("directions"), list):
        directions = [item for item in scientific_debate.get("directions", []) if isinstance(item, dict)]
    elif isinstance(direction_synthesis, dict) and isinstance(direction_synthesis.get("directions"), list):
        directions = [item for item in direction_synthesis.get("directions", []) if isinstance(item, dict)]
    if not directions:
        directions = [dict(best_entry)]
    survey_binding = build_survey_binding(artifact)
    direction_documents = [
        build_direction_result_document(topic, direction, artifact, survey_binding)
        for direction in directions
    ]
    public_directions = [document["directions"][0] for document in direction_documents]
    if isinstance(direction_synthesis, dict) and direction_synthesis:
        payload["directions"] = public_directions
        payload["cross_direction_notes"] = list(
            direction_synthesis.get("cross_direction_notes") or []
        )
        payload["direction_synthesis"] = direction_synthesis
    else:
        payload["directions"] = public_directions
    if isinstance(scientific_debate, dict) and scientific_debate:
        payload["debate_result"] = scientific_debate
        payload["debate_trace"] = list(scientific_debate.get("debate_trace") or [])
    mode_names = [str(item.get("direction_mode") or "").strip() for item in public_directions]
    primary_direction = (
        str(
            best_entry.get("route_id")
            or best_entry.get("direction_mode")
            or best_entry.get("idea_taste_mode")
            or "default"
        )
        if best_entry
        else "default"
    )
    payload.update(
        {
            "schema_version": "idea_result_v5",
            "topic": topic,
            "survey_binding": survey_binding,
            "directions": public_directions,
            "primary_direction": primary_direction,
            "legacy_best_entry": dict(best_entry),
        }
    )
    for key in ("title", "abstract", "core_contribution", "method", "risks"):
        if public_entry.get(key):
            best_entry[key] = public_entry[key]
    best_entry["introduction"] = introduction
    payload["legacy_best_entry"] = dict(best_entry)
    return payload


def save_idea_result_payload(
    payload: Dict[str, Any],
    idea_result_path: Path,
    logger,
) -> None:
    try:
        idea_result_path.parent.mkdir(parents=True, exist_ok=True)
        write_json_file(idea_result_path, compact_result_payload(payload))
        logger.info("💾 Saved idea result to %s", idea_result_path)
    except OSError as exc:
        logger.error("⚠️ Failed to persist idea_result.json: %s", exc)


def save_candidate_payload(
    payload: Dict[str, Any],
    candidate_path: Path,
    logger,
) -> None:
    try:
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        write_json_file(candidate_path, compact_candidate_entry(payload))
        logger.info("💾 Saved idea candidate to %s", candidate_path)
    except OSError as exc:
        logger.error("⚠️ Failed to persist idea_candidate.json: %s", exc)


def _persist_debug_artifacts(
    run_dir: Path,
    best_entry: Dict[str, Any],
    direction_synthesis: Optional[Dict[str, Any]],
    scientific_debate: Optional[Dict[str, Any]],
    logger,
) -> Dict[str, str]:
    enabled = str(os.getenv("IDEA_AGENT_PERSIST_DEBUG_ARTIFACTS", "")).strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return {}
    debug_dir = run_dir / "debug_artifacts"
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("⚠️ Failed to create debug artifact directory: %s", exc)
        return {}
    artifacts: Dict[str, Any] = {
        "best_entry": best_entry,
        "mcts_trace": best_entry.get("search_trace") or [],
        "pareto_candidates": best_entry.get("pareto_candidates") or {},
    }
    if isinstance(direction_synthesis, dict):
        artifacts["direction_synthesis"] = direction_synthesis
    if isinstance(scientific_debate, dict):
        artifacts["debate_result"] = scientific_debate
    refs: Dict[str, str] = {}
    for name, value in artifacts.items():
        path = debug_dir / f"{name}.json"
        try:
            write_json_file(path, value)
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("⚠️ Failed to persist debug artifact %s: %s", name, exc)
            continue
        refs[name] = str(path.relative_to(run_dir))
    logger.info("🧾 Saved optional debug artifacts under %s", debug_dir)
    return refs


def persist_final_idea(
    best_entry: Dict[str, Any],
    paper_entries: List[Dict[str, Any]],
    artifact: Dict[str, Any],
    idea_result_path: Path,
    chat_fn,
    model: str,
    logger,
    prompts: Optional[Dict[str, str]] = None,
    persist_to_artifact: bool = True,
    mature_idea_override: Optional[str] = None,
    refinement_scope_override: Optional[str] = None,
    direction_synthesis: Optional[Dict[str, Any]] = None,
    scientific_debate: Optional[Dict[str, Any]] = None,
    mature_idea_contexts: Optional[List[Dict[str, Any]]] = None,
    mature_ideas: Optional[List[Dict[str, Any]]] = None,
    idea_portfolio: Optional[Dict[str, Any]] = None,
    introduction_max_output_tokens: Optional[int] = None,
    introduction_json_repair_attempts: Optional[int] = None,
) -> Dict[str, Any]:
    payload = build_idea_result_payload(
        best_entry,
        paper_entries=paper_entries,
        artifact=artifact,
        chat_fn=chat_fn,
        model=model,
        logger=logger,
        prompts=prompts,
        mature_idea_override=mature_idea_override,
        refinement_scope_override=refinement_scope_override,
        direction_synthesis=direction_synthesis,
        scientific_debate=scientific_debate,
        mature_idea_contexts=mature_idea_contexts,
        mature_ideas=mature_ideas,
        idea_portfolio=idea_portfolio,
        introduction_max_output_tokens=introduction_max_output_tokens,
        introduction_json_repair_attempts=introduction_json_repair_attempts,
    )
    debug_artifact_refs = _persist_debug_artifacts(
        idea_result_path.parent,
        best_entry,
        direction_synthesis,
        scientific_debate,
        logger,
    )
    full_direction_documents = [
        compact_direction_document(direction)
        for direction in payload.get("directions", [])
        if isinstance(direction, dict)
    ]
    persisted_payload = compact_result_payload(payload)
    persisted_payload.pop("direction_synthesis", None)
    persisted_payload.pop("debate_result", None)
    persisted_payload.pop("cross_direction_notes", None)
    # `idea_result.json` is the single-primary compatibility handoff. The full
    # direction portfolio remains available in `idea_directions.json` and the
    # portfolio artifacts written below.
    primary_id = str(best_entry.get("idea_id") or best_entry.get("seed_id") or "").strip()
    primary_route_id = str(best_entry.get("route_id") or "").strip()
    primary_direction = next(
        (
            item for item in full_direction_documents
            if primary_id
            and str(item.get("idea_id") or item.get("seed_id") or "").strip() == primary_id
            and (not primary_route_id or str(item.get("route_id") or "").strip() == primary_route_id)
        ),
        full_direction_documents[0] if full_direction_documents else {},
    )
    if primary_direction:
        persisted_payload["directions"] = [primary_direction]
    if debug_artifact_refs:
        persisted_payload["artifact_refs"] = debug_artifact_refs
    if persist_to_artifact:
        artifact_set(artifact, "idea_result", persisted_payload)
        artifact_set(artifact, "idea_direction_results", persisted_payload.get("directions") or [])
        artifact_set(
            artifact,
            "idea_hypotheses",
            [direction.get("hypothesis", {}) for direction in persisted_payload.get("directions", []) if isinstance(direction, dict)],
        )
    save_idea_result_payload(persisted_payload, idea_result_path, logger)
    portfolio_to_persist = idea_portfolio
    if portfolio_to_persist is None:
        stored_portfolio = artifact_get(artifact, "idea_portfolio", {})
        portfolio_to_persist = stored_portfolio if isinstance(stored_portfolio, dict) and stored_portfolio else None
    if portfolio_to_persist is not None:
        persist_idea_portfolio_files(
            idea_result_path.parent,
            portfolio_to_persist,
            mature_ideas or persisted_payload.get("mature_ideas", []),
            logger,
        )
    try:
        write_json_file(idea_result_path.parent / "idea_directions.json", {
            "schema_version": "idea_directions_v1",
            "topic": persisted_payload.get("topic", ""),
            "survey_binding": persisted_payload.get("survey_binding", {}),
            "directions": full_direction_documents,
            "primary_direction": persisted_payload.get("primary_direction", ""),
        })
    except OSError as exc:
        logger.error("⚠️ Failed to persist idea_directions.json: %s", exc)
    return persisted_payload
