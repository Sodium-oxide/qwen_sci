from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from typing import Any, Dict, List

from src.agents.idea_agent.agent.artifacts import artifact_get
from src.agents.idea_agent.agent.prompts import PROMPTS
from src.agents.idea_agent.agent.prompts.advanced_analysis import render_advanced_analysis_prompt
from src.agents.idea_agent.utils.core.config_loader import get_config_value
from src.agents.idea_agent.utils.core.json_utils import pretty_json
from src.agents.idea_agent.utils.core.logger import suspend_console_handlers
from src.agents.idea_agent.utils.core.progress import iter_with_progress
from src.agents.idea_agent.utils.core.response_parsing import JsonObjectResponseError
from src.agents.idea_agent.utils.mcts.idea_taste_presets import IDEA_TASTE_PRESETS
from src.agents.idea_agent.utils.mcts.idea_routes import IDEA_ROUTE_POLICIES
from src.agents.idea_agent.utils.mcts.scientific_intervention_ontology import (
    format_scientific_intervention_profile_for_prompt,
    get_scientific_intervention_profile,
    resolve_scientific_intervention_profile,
)
from src.agents.idea_agent.utils.prompting.prompt_views import format_paper_capsules_prompt_view
from src.agents.idea_agent.utils.workflow.idea_contract import (
    mature_idea_legacy_text,
    normalize_idea_contract,
    normalize_mature_ideas,
)
from src.agents.idea_agent.utils.workflow.advanced_analysis_contract import (
    build_advanced_analysis_repair_prompt,
    validate_advanced_analysis_response,
)
from src.agents.idea_agent.utils.workflow.idea_diversity import filter_independent_mature_ideas
from src.agents.idea_agent.utils.workflow.mature_idea_sources import (
    build_mature_idea_evidence_context,
    collect_mature_idea_sources,
)
from src.agents.idea_agent.utils.workflow.multimodal_data_anchoring import (
    DATA_ANCHORED_PRIORITY,
    apply_data_anchored_idea_constraints,
    build_data_anchored_coverage_schedule,
    is_data_anchored,
)
from src.agents.idea_agent.utils.workflow.idea_debate import debate_direction_set
from src.agents.idea_agent.utils.workflow.idea_helpers import build_direction_result_document
from src.agents.idea_agent.utils.workflow.idea_synthesis import synthesize_direction_set
from src.agents.idea_agent.utils.workflow.idea_portfolio import build_idea_portfolio
from src.agents.idea_agent.utils.workflow.ligagent_flow import (
    make_stage_context,
    persist_final_idea,
    save_candidate_payload,
    save_idea_result_payload,
)
from src.agents.idea_agent.utils.workflow.result_persistence import compact_candidate_entry
from src.agents.idea_agent.utils.workflow.ligagent_helpers import (
    build_replanned_idea_entry,
    collect_rag_citation_references,
    collect_analysis_background_lines,
    collect_rag_citations,
    collect_rag_contents,
    extract_experiment_findings_from_raw_ablation,
    extract_root_idea_from_analysis,
    generate_rag_query,
    merge_title_lists,
    normalize_analysis_entry,
    paper_context_with_rag,
    prior_component_seed,
    result_to_best_entry,
    retrieve_outcome_rag,
    root_idea_to_mature_idea_text,
    root_idea_to_refinement_scope_text,
    should_preserve_current_mature_idea,
    preserve_mature_idea_as_root,
)
from src.agents.idea_agent.utils.workflow.ligagent_utils import (
    collect_paper_context_entries,
)
from src.agents.idea_agent.utils.workflow.stage_contract import (
    ArtifactPatch,
    StageContext,
    StageResult,
)


def _safe_result_filename_component(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = text.rstrip(" .")
    return text[:180] or "legacy-primary"


def _logger(agent: Any, ctx: StageContext) -> Any:
    return ctx.logger or getattr(agent, "logger", None)


def _runtime(agent: Any, ctx: StageContext) -> Any:
    return ctx.runtime or getattr(agent, "runtime", None)


def _session(agent: Any, ctx: StageContext) -> Any:
    return ctx.session or getattr(agent, "session", None)


def _select_refinement_seeds(
    seed_specs: list[Dict[str, Any] | None],
    best_scores_by_seed: Dict[str, float],
    top_seed_count: int,
) -> list[Dict[str, Any]]:
    """Select the highest-scoring mature seeds for the refinement phase.

    Seeds without a successful screening score are retained only when there
    are fewer successful seeds than the requested slot count. This keeps the
    two-stage search fail-open while ensuring failed screening results do not
    displace viable candidates when enough successful seeds exist.
    """

    if top_seed_count <= 0:
        return []
    successful = [
        seed
        for seed in seed_specs
        if seed is not None and str(seed.get("idea_id") or "").strip() in best_scores_by_seed
    ]
    unsuccessful = [
        seed
        for seed in seed_specs
        if seed is not None and str(seed.get("idea_id") or "").strip() not in best_scores_by_seed
    ]
    successful.sort(
        key=lambda seed: (
            float(best_scores_by_seed[str(seed.get("idea_id") or "")]),
            str(seed.get("idea_id") or ""),
        ),
        reverse=True,
    )
    unsuccessful.sort(key=lambda seed: str(seed.get("idea_id") or ""))
    return (successful + unsuccessful)[:top_seed_count]


def _build_route_matrix_tasks(
    seed_specs: list[Dict[str, Any] | None],
    route_specs: list[Any],
) -> list[tuple[Dict[str, Any] | None, Any]]:
    """Return the deterministic seed-by-route task matrix for one MCTS phase."""

    return [(seed, route) for seed in seed_specs for route in route_specs]


def _resolve_screening_routes(
    configured_route_ids: Any,
    route_count: int,
) -> list[Any]:
    """Resolve the compact screening set while retaining a deterministic fallback."""

    route_by_id = {route.route_id: route for route in IDEA_ROUTE_POLICIES}
    if isinstance(configured_route_ids, (list, tuple)):
        routes = [
            route_by_id[str(route_id)]
            for route_id in configured_route_ids
            if str(route_id) in route_by_id
        ]
        if routes:
            return routes[: max(1, route_count)]
    return list(IDEA_ROUTE_POLICIES)[: max(1, route_count)]


def _two_stage_mcts_budget(
    *,
    screening_seed_count: int,
    screening_route_count: int,
    screening_iterations: int,
    refinement_seed_count: int,
    refinement_route_count: int,
    refinement_iterations: int,
) -> Dict[str, int]:
    """Calculate ordinary MCTS searches and iteration budget for both phases."""

    screening_searches = screening_seed_count * screening_route_count
    refinement_searches = refinement_seed_count * refinement_route_count
    screening_total = screening_searches * screening_iterations
    refinement_total = refinement_searches * refinement_iterations
    return {
        "screening_searches": screening_searches,
        "refinement_searches": refinement_searches,
        "screening_iterations": screening_total,
        "refinement_iterations": refinement_total,
        "total_iterations": screening_total + refinement_total,
    }


def _chat(agent: Any, ctx: StageContext, op_name: str):
    runtime = _runtime(agent, ctx)
    session = _session(agent, ctx)
    default_stage = ctx.stage_name or ctx.workflow_name
    workflow_name = ctx.workflow_name

    def _invoke(prompt: str, **kwargs: Any) -> str:
        stage = str(kwargs.pop("stage", "") or "").strip() or default_stage
        return runtime.llm_text(
            session=session,
            stage=stage,
            workflow_name=workflow_name,
            op_name=op_name,
            prompt=prompt,
            **kwargs,
        )

    return _invoke


def _score_keynote_reference(
    agent: Any,
    ctx: StageContext,
    topic: str,
    rag_query: str,
    reference: Dict[str, Any],
) -> Dict[str, Any]:
    runtime = _runtime(agent, ctx)
    session = _session(agent, ctx)
    prompt = PROMPTS["keynote_scoring"].format(
        topic=topic,
        rag_query=rag_query,
        title=str(reference.get("title") or reference.get("paper_title") or "").strip(),
        keynote=str(reference.get("keynote") or "").strip(),
    )
    payload = runtime.llm_json(
        session=session,
        stage="ka_keynote_scoring",
        workflow_name=ctx.workflow_name,
        op_name="keynote_scoring",
        prompt=prompt,
        model=agent.model,
        temperature=0.0,
        max_output_tokens=512,
    )
    scored = dict(reference)
    scored["score"] = int(payload["score"])
    return scored


def _compress_single_keynote_reference(
    agent: Any,
    ctx: StageContext,
    topic: str,
    rag_query: str,
    reference: Dict[str, Any],
) -> Dict[str, Any]:
    runtime = _runtime(agent, ctx)
    session = _session(agent, ctx)
    prompt = PROMPTS["keynote_single_compression"].format(
        topic=topic,
        rag_query=rag_query,
        title=str(reference.get("title") or reference.get("paper_title") or "").strip(),
        keynote=str(reference.get("keynote") or "").strip(),
    )
    payload = runtime.llm_json(
        session=session,
        stage="ka_keynote_single_compression",
        workflow_name=ctx.workflow_name,
        op_name="keynote_single_compression",
        prompt=prompt,
        model=agent.model,
        temperature=0.1,
        max_output_tokens=2048,
    )
    return {
        "paper_id": reference.get("paper_id"),
        "node_id": reference.get("node_id"),
        "title": reference.get("title"),
        "paper_title": reference.get("paper_title"),
        "summary": str(payload["summary"]).strip(),
        "insight": str(payload["insight"]).strip(),
        "authors": reference.get("authors") or [],
        "source": reference.get("source") or "survey_keynote",
        "source_keywords": reference.get("source_keywords") or rag_query,
        "paper_domain": reference.get("paper_domain"),
        "venue": reference.get("venue"),
        "year": reference.get("year"),
        "score": int(reference["score"]),
        "reference_mode": "paper_summary",
    }


def _summarize_remaining_keynotes(
    agent: Any,
    ctx: StageContext,
    topic: str,
    rag_query: str,
    references: List[Dict[str, Any]],
) -> Dict[str, Any]:
    runtime = _runtime(agent, ctx)
    session = _session(agent, ctx)
    prompt = PROMPTS["keynote_group_summary"].format(
        topic=topic,
        rag_query=rag_query,
        papers=pretty_json(
            [
                {
                    "title": reference.get("title"),
                    "score": reference.get("score"),
                    "keynote": reference.get("keynote"),
                }
                for reference in references
            ]
        ),
    )
    payload = runtime.llm_json(
        session=session,
        stage="ka_keynote_group_summary",
        workflow_name=ctx.workflow_name,
        op_name="keynote_group_summary",
        prompt=prompt,
        model=agent.model,
        temperature=0.1,
        max_output_tokens=4096,
    )
    return {
        "paper_id": "remaining_survey_cited_papers",
        "node_id": "remaining_survey_cited_papers",
        "title": f"Remaining survey-cited papers ({len(references)})",
        "paper_title": f"Remaining survey-cited papers ({len(references)})",
        "summary": str(payload["summary"]).strip(),
        "insight": "",
        "authors": [],
        "source": "survey_keynote_rollup",
        "source_keywords": rag_query,
        "paper_domain": "",
        "venue": "",
        "year": "",
        "score": int(references[0]["score"]),
        "reference_mode": "group_summary",
    }


def execute_knowledge_acquisition_stage(agent: Any, ctx: StageContext) -> StageResult:
    spec = agent._build_knowledge_acquisition_workflow()
    nested = agent.workflow_executor.run(
        spec,
        make_stage_context(agent, workflow_name=spec.name),
    )
    summary = nested.state.get("summary") or (
        "\nIn this knowledge_aquisition action, no explicit retrieval outcome was recorded."
    )
    return StageResult(
        status=nested.status,
        step_summary=summary,
        metrics={
            "mode": nested.state.get("mode"),
            "rag_hits": len(nested.state.get("rag_hits", [])),
            "references": len(nested.state.get("curated_references", [])),
        },
    )


def execute_advanced_analysis_stage(agent: Any, ctx: StageContext) -> StageResult:
    artifact = agent.artifact
    logger = _logger(agent, ctx)
    session = _session(agent, ctx)
    runtime = _runtime(agent, ctx)

    topic_history = artifact_get(artifact, "topic", [])
    topic = topic_history[-1] if topic_history else "unspecified topic"
    reference_batches = artifact_get(artifact, "references", [])
    references = reference_batches[-1] if reference_batches else []
    mature_idea = artifact_get(artifact, "mature_idea", "")
    mature_idea_source = artifact_get(artifact, "mature_idea_source", "")
    mature_idea_records = filter_independent_mature_ideas(
        artifact_get(artifact, "mature_ideas", [])
    )
    if not mature_idea_records and mature_idea:
        mature_idea_records = normalize_mature_ideas(
            mature_idea,
            default_source=str(mature_idea_source or "legacy") or "legacy",
        )
    refinement_scope = artifact_get(artifact, "refinement_scope", "")
    refinement_scope_source = artifact_get(artifact, "refinement_scope_source", "")
    ablation_results = artifact_get(artifact, "ablation_results", [])
    rag_contents = artifact_get(artifact, "rag_contents", [])
    latest_rag_contents = rag_contents[-1] if rag_contents else []
    project_context: Dict[str, Any] = {}
    paper_repository = getattr(agent, "paper_repository", None)
    load_project_context = getattr(paper_repository, "load_project_context", None)
    if callable(load_project_context):
        loaded_project_context = load_project_context()
        if isinstance(loaded_project_context, dict):
            project_context = loaded_project_context
    resolved_profile = resolve_scientific_intervention_profile(
        {},
        project_context=project_context or None,
    ) or get_scientific_intervention_profile("generic_scientific")
    profile_id = resolved_profile.profile_id if resolved_profile is not None else "generic_scientific"
    raw_ablation = (ctx.inputs or {}).get("raw_ablation")
    if raw_ablation is None:
        artifact_raw_ablation = artifact_get(artifact, "ablation_results_raw", {})
        raw_ablation = artifact_raw_ablation if isinstance(artifact_raw_ablation, dict) else None

    experiment_findings = None
    if isinstance(raw_ablation, dict):
        extractor_cfg = get_config_value(
            agent.config,
            "agent.experiment_findings_extraction",
            {},
        )

        def _extractor_chat(prompt: str, **kwargs: Any) -> str:
            extractor_stage = str(kwargs.pop("stage", "") or "experiment_findings_extraction").strip()
            return runtime.llm_text(
                session=session,
                stage=extractor_stage,
                workflow_name=ctx.workflow_name,
                op_name="experiment_findings_extraction",
                prompt=prompt,
                **kwargs,
            )

        experiment_findings = extract_experiment_findings_from_raw_ablation(
            raw_ablation,
            chat_fn=_extractor_chat,
            logger=logger,
            extractor_config=extractor_cfg,
        )

    prompt = PROMPTS["advanced_analysis"].format(
        topic=topic,
        mature_idea=(mature_idea or "").strip(),
        mature_idea_source=(mature_idea_source or "empty").strip(),
        refinement_scope=(refinement_scope or "").strip(),
        refinement_scope_source=(refinement_scope_source or "empty").strip(),
        survey_contents="\n".join(latest_rag_contents) if isinstance(latest_rag_contents, list) else "",
        papers=format_paper_capsules_prompt_view(references),
        experiment_findings=(
            pretty_json(experiment_findings)
            if isinstance(experiment_findings, dict) and experiment_findings
            else "None"
        ),
    )
    survey_context = artifact_get(artifact, "survey_idea_context", {})
    if isinstance(survey_context, dict) and survey_context.get("handoff"):
        prompt = (
            "== Verified Survey -> Idea handoff (authoritative gap boundary) ==\n"
            + pretty_json(survey_context["handoff"])
            + "\n\n"
            + prompt
        )
    multimodal_projection = (
        survey_context.get("multimodal_evidence_projection")
        if isinstance(survey_context, dict)
        else None
    )
    if isinstance(multimodal_projection, dict) and multimodal_projection:
        prompt = (
            "== Bounded supplied-data projection (not literature evidence) ==\n"
            + pretty_json(multimodal_projection)
            + "\nUse this only as dataset-local observation context. Do not describe it as proving "
            "a mechanism, a universal result, or a first discovery. Preserve candidate mechanisms, "
            "alternative explanations, measurement artifacts, and the stated claim limits.\n\n"
            + prompt
        )
    prompt = render_advanced_analysis_prompt(prompt, profile_id)
    prompt = (
        "== Scientific intervention profile (fixed before analysis) ==\n"
        + format_scientific_intervention_profile_for_prompt(
            resolved_profile.to_payload() if resolved_profile is not None else {"profile_id": profile_id}
        )
        + "\n\n"
        + prompt
    )
    require_grounded_fields = (
        not bool(str(mature_idea or "").strip())
        or str(mature_idea_source or "").strip().casefold() in {"empty", "input_inferred"}
    )
    require_gap_ids = bool(isinstance(survey_context, dict) and survey_context.get("handoff"))

    def _request_advanced_analysis(op_name: str, request_prompt: str) -> tuple[Any, List[str]]:
        try:
            candidate = runtime.llm_json(
                session=session,
                stage=ctx.stage_name,
                workflow_name=ctx.workflow_name,
                op_name=op_name,
                prompt=request_prompt,
                model=agent.model,
                max_output_tokens=65536,
                response_format={"type": "json_object"},
                require_json_object=True,
            )
        except JsonObjectResponseError as exc:
            return None, [str(exc)]
        return candidate, validate_advanced_analysis_response(
            candidate,
            require_grounded_fields=require_grounded_fields,
            require_gap_ids=require_gap_ids,
        )

    raw_response, contract_errors = _request_advanced_analysis("advanced_analysis", prompt)
    try:
        contract_retries = max(
            0,
            int(get_config_value(agent.config, "agent.advanced_analysis_contract_retries", 2) or 0),
        )
    except (TypeError, ValueError):
        contract_retries = 2
    for attempt in range(1, contract_retries + 1):
        if not contract_errors:
            break
        logger.warning(
            "⚠️ Advanced analysis contract violation; requesting repair %s/%s: %s",
            attempt,
            contract_retries,
            "; ".join(contract_errors[:8]),
        )
        raw_response, contract_errors = _request_advanced_analysis(
            f"advanced_analysis_contract_repair_{attempt}",
            build_advanced_analysis_repair_prompt(prompt, raw_response, contract_errors),
        )
    if contract_errors:
        raise ValueError(
            "Advanced analysis output failed the required contract after "
            f"{contract_retries} repair attempt(s): {'; '.join(contract_errors[:12])}"
        )
    response = normalize_analysis_entry(raw_response)
    if isinstance(response, (dict, list)):
        logger.info(
            "📝 Advanced Analysis Result:\n%s",
            pretty_json(response),
        )
    else:
        logger.info("📝 Advanced Analysis Result:\n%s", response)

    if experiment_findings is not None:
        response["experiment_findings"] = experiment_findings
    root_idea = extract_root_idea_from_analysis(response, topic=topic)
    preserved_mature_idea = False
    if isinstance(mature_idea, str) and mature_idea.strip():
        preserve_original, preserve_reason = should_preserve_current_mature_idea(
            response,
            root_idea,
            mature_idea,
        )
        if preserve_original:
            preserved_mature_idea = True
            response["preserve_current_idea"] = {
                "keep_original": True,
                "reason": preserve_reason,
            }
            root_idea = preserve_mature_idea_as_root(
                topic,
                mature_idea,
                target_defects=list(root_idea.get("target_defects") or ["unclear_mechanism"]),
                reason=preserve_reason,
            )
            response["tldr"] = preserve_reason
    response["root_idea"] = root_idea
    existing_background = set(artifact_get(artifact, "background_knowledge", []))
    background_lines = [
        line
        for line in collect_analysis_background_lines(response)
        if line not in existing_background
    ]
    if session is not None:
        session.set_slot("analysis.latest", response)
    replace_patch: Dict[str, Any] = {"root_idea": root_idea}
    grounded_mature_idea = str(response.get("grounded_mature_idea") or "").strip()
    survey_context = artifact_get(artifact, "survey_idea_context", {})
    survey_handoff = survey_context.get("handoff") if isinstance(survey_context, dict) else {}
    response_seed_records = normalize_mature_ideas(
        response.get("mature_ideas") if isinstance(response, dict) else [],
        default_source="problem_reframing",
    )
    source_inputs = [*mature_idea_records, *response_seed_records]
    if grounded_mature_idea and not source_inputs:
        source_inputs.append(
            normalize_mature_ideas(
                grounded_mature_idea,
                default_source="problem_reframing",
            )[0]
        )
    analyzed_mature_ideas = collect_mature_idea_sources(
        existing=source_inputs,
        survey_handoff=survey_handoff,
        prior_candidate=artifact_get(artifact, "latest_candidate", {}),
        experiment_results=ablation_results,
        analysis=response,
        max_ideas=int(get_config_value(agent.config, "run.max_mature_ideas", 12) or 12),
        allow_problem_reframing=bool(get_config_value(agent.config, "run.allow_problem_reframing", True)),
        allow_unanchored_seed=bool(get_config_value(agent.config, "run.allow_unanchored_seed", True)),
        allow_high_risk_seed=bool(get_config_value(agent.config, "run.allow_high_risk_seed", True)),
    )
    if analyzed_mature_ideas:
        replace_patch["mature_ideas"] = analyzed_mature_ideas
        replace_patch["mature_idea"] = mature_idea_legacy_text(analyzed_mature_ideas)
        replace_patch["mature_idea_source"] = "analysis_grounded_collection"
    grounded_refinement_scope = str(response.get("grounded_refinement_scope") or "").strip()
    current_mature_source = str(mature_idea_source or ("empty" if not str(mature_idea or "").strip() else "unknown"))
    current_scope_source = str(
        refinement_scope_source or ("empty" if not str(refinement_scope or "").strip() else "unknown")
    )
    if current_mature_source in {"empty", "input_inferred"}:
        promoted = grounded_mature_idea or root_idea_to_mature_idea_text(root_idea)
        if promoted:
            replace_patch["mature_idea"] = promoted
            replace_patch["mature_idea_source"] = "analysis_grounded"
            if session is not None:
                session.set_slot("mature_idea.latest", promoted)
    if current_scope_source in {"empty", "input_inferred"} and grounded_refinement_scope:
        replace_patch["refinement_scope"] = grounded_refinement_scope
        replace_patch["refinement_scope_source"] = "analysis_grounded"
    elif current_scope_source in {"empty", "input_inferred"}:
        fallback_scope = root_idea_to_refinement_scope_text(root_idea)
        if fallback_scope:
            replace_patch["refinement_scope"] = fallback_scope
            replace_patch["refinement_scope_source"] = "analysis_grounded"
    promoted_root_to_mature = False
    if (
        isinstance(mature_idea, str)
        and mature_idea.strip()
        and current_mature_source not in {"empty", "input_inferred"}
        and not ablation_results
        and not preserved_mature_idea
    ):
        promoted_mature_idea = root_idea_to_mature_idea_text(root_idea)
        if promoted_mature_idea:
            replace_patch["mature_idea"] = promoted_mature_idea
            promoted_root_to_mature = True
            if session is not None:
                session.set_slot("mature_idea.latest", promoted_mature_idea)
            logger.info(
                "🪴 Advanced analysis promoted calibrated root_idea to mature_idea for no-ablation continuation."
            )
    step = (
        "\nIn this advanced_analysis action, I analyzed the retrieved references and summarized my findings: "
        f"{response.get('tldr', 'No TL;DR provided.')}"
    )
    return StageResult(
        artifact_patch=ArtifactPatch(
            replace=replace_patch,
            append={
                "analysis": [response],
                "background_knowledge": background_lines,
            }
        ),
        step_summary=step,
        metrics={
            "reference_count": len(references),
            "background_lines": len(background_lines),
            "root_idea_title": root_idea.get("title"),
            "experiment_findings_used": bool(experiment_findings),
            "promoted_root_to_mature_idea": promoted_root_to_mature,
            "preserved_mature_idea": preserved_mature_idea,
        },
    )


def _build_mode_result_document(
    topic: str,
    direction: Dict[str, Any],
    source_entry: Dict[str, Any],
    artifact: Dict[str, Any],
    survey_binding: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a mode document from the raw candidate, then compact its legacy view."""
    mode_payload = build_direction_result_document(
        topic,
        source_entry,
        artifact,
        survey_binding,
    )
    mode = str(direction.get("direction_mode") or direction.get("idea_taste_mode") or "default").strip() or "default"
    mode_payload["primary_direction"] = mode
    mode_payload["legacy_best_entry"] = compact_candidate_entry(source_entry)
    return mode_payload


def execute_idea_generation_stage(agent: Any, ctx: StageContext) -> StageResult:
    artifact = agent.artifact
    logger = _logger(agent, ctx)
    session = _session(agent, ctx)

    topic_history = artifact_get(artifact, "topic", [])
    topic = topic_history[-1]
    reference_batches = artifact_get(artifact, "references", [])
    latest_batch = reference_batches[-1] if reference_batches else []
    batch_list = [latest_batch] if latest_batch else reference_batches
    paper_entries = collect_paper_context_entries(artifact, batch_list)
    latest_candidate = artifact_get(artifact, "latest_candidate", {})
    latest_candidate_payload = (
        normalize_idea_contract(latest_candidate, allow_legacy=True, keep_extra=True)
        if isinstance(latest_candidate, dict) and latest_candidate
        else None
    )
    root_idea = artifact_get(artifact, "root_idea", {})
    root_idea_payload = (
        normalize_idea_contract(root_idea, allow_legacy=True, keep_extra=True)
        if isinstance(root_idea, dict) and root_idea
        else None
    )
    mature_idea = artifact_get(artifact, "mature_idea", "")
    mature_ideas = normalize_mature_ideas(
        artifact_get(artifact, "mature_ideas", []),
        legacy_value=mature_idea,
        default_source=str(artifact_get(artifact, "mature_idea_source", "user_input") or "user_input"),
    )
    refinement_scope = artifact_get(artifact, "refinement_scope", "")
    component_decisions = artifact_get(artifact, "component_decisions", [])
    prior_components, prior_component_explanations = prior_component_seed(
        latest_candidate_payload,
        root_idea_payload,
    )
    context = {
        "analysis": artifact_get(artifact, "analysis", []),
        "latest_candidate": latest_candidate_payload,
        "root_idea": root_idea_payload,
        "background_knowledge": artifact_get(artifact, "background_knowledge", []),
        "paper_context": paper_context_with_rag(paper_entries, artifact),
        "component_decisions": (
            [decision for decision in component_decisions if isinstance(decision, dict)]
            if isinstance(component_decisions, list)
            else []
        ),
    }
    survey_context = artifact_get(artifact, "survey_idea_context", {})
    if isinstance(survey_context, dict) and survey_context:
        context["survey_idea_handoff"] = dict(survey_context.get("handoff") or {})
        context["survey_gap_ledger"] = dict(survey_context.get("gap_ledger") or {})
        context["defect_tags"] = list(survey_context.get("defect_tags") or [])
        context["project_context"] = dict(survey_context.get("project_context") or {})
        if isinstance(survey_context.get("multimodal_evidence_projection"), dict):
            context["multimodal_evidence_projection"] = deepcopy(
                survey_context["multimodal_evidence_projection"]
            )
        context["paper_context"] = (
            "Verified Survey handoff:\n"
            + pretty_json(context["survey_idea_handoff"])
            + "\n\n"
            + str(context.get("paper_context") or "")
        )
    paper_repository = getattr(agent, "paper_repository", None)
    load_project_context = getattr(paper_repository, "load_project_context", None)
    if callable(load_project_context):
        project_context = load_project_context()
        if isinstance(project_context, dict) and project_context:
            context["project_context"] = project_context
    handoff_for_public_facts = context.get("survey_idea_handoff")
    if isinstance(handoff_for_public_facts, dict):
        context["public_facts"] = {
            "topic": topic,
            "verified_facts": deepcopy(
                handoff_for_public_facts.get("verified_facts")
                or handoff_for_public_facts.get("field_consensus")
                or []
            ),
            "hard_constraints": deepcopy(
                handoff_for_public_facts.get("hard_constraints")
                or handoff_for_public_facts.get("constraints")
                or []
            ),
            "profile_resolution": deepcopy(handoff_for_public_facts.get("profile_resolution") or {}),
        }
    analysis_history = artifact_get(artifact, "analysis", [])
    latest_analysis = analysis_history[-1] if analysis_history else {}
    mature_ideas = collect_mature_idea_sources(
        existing=mature_ideas,
        survey_handoff=context.get("survey_idea_handoff", {}),
        prior_candidate=latest_candidate_payload,
        experiment_results=artifact_get(artifact, "ablation_results", []),
        analysis=latest_analysis,
        max_ideas=int(get_config_value(agent.config, "run.max_mature_ideas", 12) or 12),
        allow_problem_reframing=bool(get_config_value(agent.config, "run.allow_problem_reframing", True)),
        allow_unanchored_seed=bool(get_config_value(agent.config, "run.allow_unanchored_seed", True)),
        allow_high_risk_seed=bool(get_config_value(agent.config, "run.allow_high_risk_seed", True)),
        multimodal_evidence_projection=context.get("multimodal_evidence_projection"),
    )
    mature_idea_contexts = [
        build_mature_idea_evidence_context(
            idea,
            topic=topic,
            survey_handoff=context.get("survey_idea_handoff", {}),
            references=paper_entries,
            ablation_results=artifact_get(artifact, "ablation_results", []),
            public_facts=context.get("public_facts", {}),
            multimodal_evidence_projection=context.get("multimodal_evidence_projection"),
        )
        for idea in mature_ideas
    ]
    context["mature_idea_contexts"] = mature_idea_contexts
    if isinstance(mature_idea, str) and mature_idea.strip():
        context["mature_idea"] = mature_idea.strip()
    if mature_ideas:
        context["mature_ideas"] = mature_ideas
        context["mature_idea"] = mature_idea_legacy_text(mature_ideas) or context.get("mature_idea", "")
    if isinstance(refinement_scope, str) and refinement_scope.strip():
        context["refinement_scope"] = refinement_scope.strip()
    if prior_components:
        context["prior_components"] = prior_components
        context["prior_component_explanations"] = prior_component_explanations

    agent.mcts.reload_symbolic_memory()
    ligagent_pro = bool(get_config_value(agent.config, "run.LigAgent-Pro", False))

    materialization_model = str(
        get_config_value(agent.config, "fusion.model", "") or agent.model
    ).strip()
    materialize_chat = _chat(agent, ctx, "idea_materialization")
    completed_modes: List[Dict[str, Any]] = []
    mode_results: Dict[str, Any] = {}

    def _complete_mode(
        mode: str,
        result: Any,
        seed: Dict[str, Any] | None = None,
        route: Any = None,
    ) -> None:
        entry = result_to_best_entry(result, mode)
        if seed:
            seed_id = str(seed.get("idea_id") or seed.get("seed_id") or "legacy-primary")
            entry["idea_id"] = seed_id
            entry["seed_id"] = seed_id
            if not entry.get("target_gap_ids"):
                entry["target_gap_ids"] = list(seed.get("target_gap_ids") or [])
            entry.setdefault("gap_alignment", deepcopy(seed.get("gap_alignment") or ""))
            entry["mature_idea"] = deepcopy(seed)
            for field_name in (
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
                if seed.get(field_name) not in (None, "", [], {}):
                    entry[field_name] = deepcopy(seed[field_name])
        if route is not None:
            entry["route_id"] = route.route_id
            entry["route_signature"] = {
                "mature_idea": deepcopy(seed.get("route_signature") if seed else {}),
                "route_id": route.route_id,
                "required_structural_change": route.required_structural_change,
            }
            entry["route_policy"] = route.to_payload()
            entry["legacy_direction_mode"] = route.legacy_mode
            entry["direction_mode"] = route.route_id
            entry["idea_taste_mode"] = route.legacy_mode
        else:
            entry.setdefault("seed_id", str(seed.get("idea_id") if seed else "legacy-primary"))
            entry.setdefault("route_id", f"legacy:{mode}")
            entry.setdefault("route_signature", {"route_id": f"legacy:{mode}", "direction_mode": mode})
        if seed is not None and is_data_anchored(seed):
            entry = apply_data_anchored_idea_constraints(entry, seed=seed)
        completed_modes.append({
            "mode": mode,
            "result": result,
            "entry": entry,
            "seed": seed,
            "route": route,
        })

    route_matrix_enabled = bool(get_config_value(agent.config, "run.route_matrix_enabled", True))
    active_mature_ideas = [
        idea for idea in mature_ideas
        if str(idea.get("maturity_status") or "").casefold() != "rejected"
        and str(idea.get("independence_status") or "").casefold() != "collapsed_duplicate"
    ]
    seed_specs: List[Dict[str, Any] | None] = [
        idea for idea in active_mature_ideas if not is_data_anchored(idea)
    ]
    two_stage_matrix_enabled = route_matrix_enabled and bool(seed_specs)
    if not seed_specs:
        seed_specs = [None]
    if route_matrix_enabled and (mature_ideas or ligagent_pro):
        if two_stage_matrix_enabled:
            screening_route_expansions = int(
                get_config_value(
                    agent.config,
                    "portfolio.screening_route_expansions_per_seed",
                    2,
                )
                or 2
            )
            route_specs = _resolve_screening_routes(
                get_config_value(agent.config, "portfolio.screening_route_ids", None),
                screening_route_expansions,
            )
        else:
            max_route_expansions = int(
                get_config_value(
                    agent.config,
                    "portfolio.max_route_expansions_per_seed",
                    len(IDEA_ROUTE_POLICIES),
                )
                or len(IDEA_ROUTE_POLICIES)
            )
            route_specs = list(IDEA_ROUTE_POLICIES)[: max(1, max_route_expansions)]
    else:
        route_specs = [None]
    tasks = _build_route_matrix_tasks(seed_specs, route_specs)
    screening_iterations_per_search = int(
        get_config_value(
            agent.config,
            "mcts.screening_max_iterations",
            getattr(agent.mcts.config, "screening_max_iterations", 6),
        )
        or getattr(agent.mcts.config, "screening_max_iterations", 6)
    )
    raw_data_budget_cap = get_config_value(
        agent.config,
        "survey.multimodal_evidence.data_sh_mcts_budget_cap",
        0.50,
    )
    try:
        data_budget_cap = float(raw_data_budget_cap)
    except (TypeError, ValueError):
        data_budget_cap = 0.50
    shared_context = agent.mcts.prepare_root_context(topic, context)
    data_schedule = build_data_anchored_coverage_schedule(
        shared_context.get("gap_hypothesis_seeds", []) if isinstance(shared_context, dict) else [],
        ordinary_task_count=len(tasks),
        iterations_per_search=screening_iterations_per_search,
        budget_cap=data_budget_cap,
    )
    data_seed_by_subhypothesis = {
        str(seed.get("subhypothesis_id") or "").strip(): dict(seed)
        for seed in (shared_context.get("gap_hypothesis_seeds", []) if isinstance(shared_context, dict) else [])
        if isinstance(seed, dict) and is_data_anchored(seed)
    }
    coverage_tasks: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for assignment in data_schedule.get("assignments", []):
        if not isinstance(assignment, dict):
            continue
        source_seed = data_seed_by_subhypothesis.get(
            str(assignment.get("subhypothesis_id") or "").strip()
        )
        if source_seed is None:
            continue
        coverage_seed = deepcopy(source_seed)
        coverage_seed.update(
            {
                "idea_id": "data-coverage-" + str(
                    assignment.get("subhypothesis_id") or coverage_seed.get("seed_id")
                ),
                "title": "Data-anchored coverage: " + str(
                    assignment.get("subhypothesis_id") or "supplied observation"
                ),
                "abstract": str(coverage_seed.get("gap_statement") or "").strip(),
                "hypothesis": str(coverage_seed.get("gap_statement") or "").strip(),
                "target_gap_ids": [coverage_seed.get("gap_id")],
                "maturity_status": "provisional",
                "idea_source": "survey_gap",
                "data_anchored_coverage_assignment": deepcopy(assignment),
            }
        )
        coverage_tasks.append((coverage_seed, assignment))
    total_mcts_searches = len(coverage_tasks) + len(tasks)
    logger.info(
        "🧭 MCTS screening schedule: %s search(es), including %s data-SH coverage pass(es) before %s ordinary task(s); %s iteration(s) per ordinary search.",
        total_mcts_searches,
        len(coverage_tasks),
        len(tasks),
        screening_iterations_per_search,
    )

    def _mcts_task_identity(seed: Dict[str, Any] | None, route: Any) -> tuple[str, str]:
        seed_id = str(seed.get("idea_id") if seed else "legacy-primary")
        route_id = str(route.route_id if route is not None else "default")
        return seed_id, route_id

    def _route_context(seed: Dict[str, Any] | None, route: Any) -> Dict[str, Any]:
        isolated = deepcopy(context)
        if seed is not None:
            seed_id = str(seed.get("idea_id") or "").strip()
            cached_contexts = context.get("mature_idea_contexts") or []
            evidence_context = next(
                (
                    deepcopy(item)
                    for item in cached_contexts
                    if isinstance(item, dict) and str(item.get("idea_id") or "").strip() == seed_id
                ),
                None,
            )
            if evidence_context is None:
                evidence_context = build_mature_idea_evidence_context(
                    seed,
                    topic=topic,
                    survey_handoff=context.get("survey_idea_handoff", {}),
                    references=paper_entries,
                    ablation_results=artifact_get(artifact, "ablation_results", []),
                    public_facts=context.get("public_facts", {}),
                    multimodal_evidence_projection=context.get("multimodal_evidence_projection"),
                )
            isolated["mature_idea_evidence_context"] = evidence_context
            isolated["public_facts"] = deepcopy(evidence_context.get("public_facts") or {})
            isolated["survey_gap_ledger"] = {
                "gaps": deepcopy(evidence_context.get("gap_explanation") or [])
            }
            isolated["defect_tags"] = [
                str(gap.get("gap_kind") or "").strip()
                for gap in evidence_context.get("gap_explanation") or []
                if isinstance(gap, dict) and str(gap.get("gap_kind") or "").strip()
            ]
            scoped_analysis = {
                "mature_idea": deepcopy(seed),
                "idea_source": evidence_context.get("idea_source"),
                "lineage": deepcopy(seed.get("lineage")),
                "gap_explanation": deepcopy(evidence_context.get("gap_explanation") or []),
                "evidence_subset": deepcopy(evidence_context.get("evidence_subset") or []),
                "mechanism_chain": deepcopy(evidence_context.get("mechanism_chain") or []),
                "validation_targets": deepcopy(evidence_context.get("validation_targets") or []),
            }
            isolated["analysis"] = [scoped_analysis]
            isolated["background_knowledge"] = deepcopy(evidence_context.get("evidence_subset") or [])
            isolated["retrieval_queries"] = list(evidence_context.get("retrieval_queries") or [])
            isolated["counterexamples"] = deepcopy(evidence_context.get("counterexamples") or [])
            isolated["validation_targets"] = list(evidence_context.get("validation_targets") or [])
            isolated["mechanism_chain"] = list(evidence_context.get("mechanism_chain") or [])
            isolated["survey_idea_handoff"] = deepcopy(evidence_context.get("survey_handoff") or {})
            isolated["paper_context"] = (
                "== Public scientific facts and hard constraints ==\n"
                + pretty_json(evidence_context.get("public_facts") or {})
                + "\n\n== Idea-specific evidence subset ==\n"
                + pretty_json(
                    {
                        "gap_explanation": evidence_context.get("gap_explanation") or [],
                        "evidence_subset": evidence_context.get("evidence_subset") or [],
                        "counterexamples": evidence_context.get("counterexamples") or [],
                        "mechanism_chain": evidence_context.get("mechanism_chain") or [],
                        "validation_targets": evidence_context.get("validation_targets") or [],
                        "retrieval_queries": evidence_context.get("retrieval_queries") or [],
                        "multimodal_evidence_context": evidence_context.get("multimodal_evidence_context") or {},
                        "anchor_policy": evidence_context.get("anchor_policy"),
                    }
                )
            )
            seed_text = str(
                seed.get("hypothesis")
                or seed.get("central_hypothesis")
                or seed.get("abstract")
                or seed.get("title")
                or ""
            ).strip()
            isolated.update({
                "mature_idea": seed_text,
                "mature_idea_record": deepcopy(seed),
                "mature_ideas": [deepcopy(seed)],
                "idea_id": seed.get("idea_id"),
                "seed_id": seed.get("idea_id"),
                "target_gap_ids": list(seed.get("target_gap_ids") or []),
                "gap_alignment": deepcopy(seed.get("gap_alignment") or ""),
                "refinement_scope": seed.get("refinement_scope") or isolated.get("refinement_scope", ""),
            })
            if is_data_anchored(seed):
                isolated["data_anchored_context"] = deepcopy(seed)
                isolated["data_anchored_mcts_depth_multiplier"] = float(
                    seed.get("mcts_depth_multiplier") or 1.75
                )
        if route is not None:
            isolated["route_id"] = route.route_id
            isolated["route_policy"] = route.to_payload()
            isolated["route_signature"] = {
                "mature_idea": deepcopy(seed.get("route_signature") if seed else {}),
                "route_id": route.route_id,
            }
            isolated["paper_context"] = (
                str(isolated.get("paper_context") or "")
                + "\n\n== Independent route policy ==\n"
                + pretty_json(route.to_payload())
            )
        return isolated

    for coverage_number, (coverage_seed, assignment) in enumerate(coverage_tasks, start=1):
        coverage_context = _route_context(coverage_seed, None)
        coverage_context["mcts_iteration_budget"] = int(
            assignment.get("iteration_budget") or 0
        )
        coverage_context["data_anchored_mcts_depth_multiplier"] = float(
            assignment.get("mcts_depth_multiplier") or 1.75
        )
        coverage_context["data_anchored_coverage_assignment"] = deepcopy(assignment)
        coverage_mode = "evidence_first"
        coverage_route_id = "data_coverage:" + str(
            assignment.get("subhypothesis_id") or coverage_number
        )
        logger.info(
            "🚀 Data-SH coverage %s/%s started (subhypothesis_id=%s; budget=%s).",
            coverage_number,
            len(coverage_tasks),
            assignment.get("subhypothesis_id"),
            assignment.get("iteration_budget"),
        )
        try:
            result = agent.build_mcts_for_mode(
                coverage_mode,
                seed_id=str(coverage_seed.get("idea_id") or "data-coverage"),
                route_id=coverage_route_id,
            ).search(topic, coverage_context)
        except Exception as exc:
            assignment["materialized_branch_ids"] = []
            assignment["coverage_status"] = "failed"
            logger.warning(
                "⚠️ Data-SH coverage failed (subhypothesis_id=%s): %s",
                assignment.get("subhypothesis_id"),
                exc,
            )
            mode_results[coverage_route_id] = None
            continue
        required_branch_ids = {
            str(branch.get("branch_id") or "").strip()
            for branch in assignment.get("coverage_branches", [])
            if isinstance(branch, dict) and str(branch.get("branch_id") or "").strip()
        }
        materialized_branch_ids = {
            str((item.get("data_anchored_coverage_branch") or {}).get("branch_id") or "").strip()
            for item in (getattr(result, "trace", []) or [])
            if isinstance(item, dict)
            and isinstance(item.get("data_anchored_coverage_branch"), dict)
        }
        materialized_branch_ids.discard("")
        assignment["materialized_branch_ids"] = sorted(materialized_branch_ids)
        assignment["coverage_status"] = (
            "complete"
            if required_branch_ids.issubset(materialized_branch_ids)
            else "incomplete_missing_required_branches"
        )
        mode_results[coverage_route_id] = result
        if result.best and assignment["coverage_status"] == "complete":
            _complete_mode(coverage_route_id, result, seed=coverage_seed)
        elif assignment["coverage_status"] != "complete":
            logger.warning(
                "⚠️ Data-SH coverage is incomplete (subhypothesis_id=%s; missing branches=%s); "
                "its candidate will not enter the portfolio.",
                assignment.get("subhypothesis_id"),
                sorted(required_branch_ids - materialized_branch_ids),
            )

    def _run_matrix_tasks(
        task_batch: list[tuple[Dict[str, Any] | None, Any]],
        *,
        phase: str,
        iterations: int,
    ) -> dict[tuple[str, str], Any]:
        """Run one route-matrix phase and return results keyed by seed/route."""

        if not task_batch:
            return {}
        agent.mcts.symbolic_memory_path.parent.mkdir(parents=True, exist_ok=True)
        agent.mcts.symbolic_memory.save(str(agent.mcts.symbolic_memory_path))
        max_workers = min(
            max(1, int(get_config_value(agent.config, "run.idea_route_matrix_max_workers", 8) or 8)),
            max(1, int(get_config_value(agent.config, "mcts.max_parallel_seeds", 4) or 4))
            * max(1, int(get_config_value(agent.config, "mcts.max_parallel_routes", 5) or 5)),
            len(task_batch),
        )
        logger.info(
            "🧵 MCTS %s phase will use up to %s parallel worker(s) for %s task(s) × %s iteration(s).",
            phase,
            max_workers,
            len(task_batch),
            iterations,
        )

        def _run_task(
            task_number: int,
            seed: Dict[str, Any] | None,
            route: Any,
        ) -> Any:
            seed_id, route_id = _mcts_task_identity(seed, route)
            logger.info(
                "🚀 MCTS %s %s/%s started (seed_id=%s, route_id=%s, iterations=%s).",
                phase,
                task_number,
                len(task_batch),
                seed_id,
                route_id,
                iterations,
            )
            task_context = _route_context(seed, route)
            task_context["mcts_iteration_budget"] = iterations
            if route is None:
                return agent.mcts.search(topic=topic, context=task_context)
            return agent.build_mcts_for_mode(
                route.legacy_mode,
                seed_id=str(seed.get("idea_id") if seed else "legacy-primary"),
                route_id=route.route_id,
            ).search(topic, task_context)

        results: dict[tuple[str, str], Any] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_run_task, task_number, seed, route): (seed, route)
                for task_number, (seed, route) in enumerate(task_batch, start=1)
            }
            for future in as_completed(futures):
                seed, route = futures[future]
                mode = route.route_id if route is not None else "default"
                seed_id, route_id = _mcts_task_identity(seed, route)
                key = (seed_id, route_id)
                result = None
                try:
                    result = future.result()
                except Exception as exc:
                    logger.warning(
                        "⚠️ MCTS %s failed (seed_id=%s, route_id=%s); fallback may be used: %s",
                        phase,
                        seed_id,
                        route_id,
                        exc,
                    )
                results[key] = result
                mode_results[f"{seed_id}:{mode}"] = result
                logger.info(
                    "✅ MCTS %s completed (seed_id=%s, route_id=%s; candidate=%s).",
                    phase,
                    seed_id,
                    route_id,
                    "yes" if result is not None and result.best else "no",
                )
        return results

    if len(tasks) == 1 and tasks[0][0] is None and tasks[0][1] is None:
        logger.info("🚀 MCTS 1/1 started (seed_id=legacy-primary, route_id=default).")
        with suspend_console_handlers(logger):
            result = agent.mcts.search(topic=topic, context=context)
        mode_label = getattr(getattr(agent.mcts, "idea_taste_preset", None), "mode", None) or "default"
        mode_results[mode_label] = result
        logger.info(
            "✅ MCTS 1/1 completed (seed_id=legacy-primary, route_id=default; candidate=%s).",
            "yes" if result.best else "no",
        )
        if result.best:
            _complete_mode(mode_label, result)
    elif two_stage_matrix_enabled and tasks:
        screening_results = _run_matrix_tasks(
            tasks,
            phase="screening",
            iterations=screening_iterations_per_search,
        )
        initial_best_by_seed: dict[str, tuple[float, Any, Any]] = {}
        for seed, route in tasks:
            seed_id, route_id = _mcts_task_identity(seed, route)
            result = screening_results.get((seed_id, route_id))
            if result is None or not result.best or seed is None:
                continue
            try:
                score = float(result.best.evaluation.composite)
            except (AttributeError, TypeError, ValueError):
                score = 0.0
            previous = initial_best_by_seed.get(seed_id)
            if previous is None or score > previous[0]:
                initial_best_by_seed[seed_id] = (score, result, route)

        top_seed_count = int(
            get_config_value(agent.config, "portfolio.refinement_top_seeds", 3) or 3
        )
        top_seeds = _select_refinement_seeds(
            seed_specs,
            {
                seed_id: score_and_result[0]
                for seed_id, score_and_result in initial_best_by_seed.items()
            },
            top_seed_count,
        )
        refinement_iterations = int(
            get_config_value(
                agent.config,
                "mcts.refinement_max_iterations",
                getattr(agent.mcts.config, "max_iterations", 8),
            )
            or getattr(agent.mcts.config, "max_iterations", 8)
        )
        refinement_route_count = int(
            get_config_value(
                agent.config,
                "portfolio.refinement_route_expansions_per_seed",
                len(IDEA_ROUTE_POLICIES),
            )
            or len(IDEA_ROUTE_POLICIES)
        )
        refinement_routes = list(IDEA_ROUTE_POLICIES)[: max(1, refinement_route_count)]
        refinement_tasks = _build_route_matrix_tasks(top_seeds, refinement_routes)
        mcts_budget = _two_stage_mcts_budget(
            screening_seed_count=len(seed_specs),
            screening_route_count=len(route_specs),
            screening_iterations=screening_iterations_per_search,
            refinement_seed_count=len(top_seeds),
            refinement_route_count=len(refinement_routes),
            refinement_iterations=refinement_iterations,
        )
        logger.info(
            "🧭 MCTS two-stage budget: screening=%s seed(s) × %s route(s) × %s iteration(s)=%s; "
            "refinement=%s seed(s) × %s route(s) × %s iteration(s)=%s; total ordinary iterations=%s.",
            len(seed_specs),
            len(route_specs),
            screening_iterations_per_search,
            mcts_budget["screening_iterations"],
            len(top_seeds),
            len(refinement_routes),
            refinement_iterations,
            mcts_budget["refinement_iterations"],
            mcts_budget["total_iterations"],
        )
        refinement_results = _run_matrix_tasks(
            refinement_tasks,
            phase="refinement",
            iterations=refinement_iterations,
        )
        refined_seed_ids: set[str] = set()
        for seed, route in refinement_tasks:
            seed_id, route_id = _mcts_task_identity(seed, route)
            result = refinement_results.get((seed_id, route_id))
            if result is not None and result.best:
                _complete_mode(route.route_id, result, seed=seed, route=route)
                refined_seed_ids.add(seed_id)
        for seed in top_seeds:
            seed_id = str(seed.get("idea_id") or "")
            if seed_id in refined_seed_ids:
                continue
            fallback = initial_best_by_seed.get(seed_id)
            if fallback is not None:
                _, result, route = fallback
                _complete_mode(route.route_id, result, seed=seed, route=route)
    elif tasks:
        standard_results = _run_matrix_tasks(
            tasks,
            phase="standard",
            iterations=int(getattr(agent.mcts.config, "max_iterations", 0) or 0),
        )
        for seed, route in tasks:
            seed_id, route_id = _mcts_task_identity(seed, route)
            result = standard_results.get((seed_id, route_id))
            if result is not None and result.best:
                mode = route.route_id if route is not None else "default"
                _complete_mode(mode, result, seed=seed, route=route)

    if not completed_modes:
        logger.warning("⚠️ MCTS search returned no candidate; keeping latest candidate unchanged.")
        replace_patch = (
            {"latest_candidate": latest_candidate_payload}
            if latest_candidate_payload is not None
            else {}
        )
        return StageResult(
            status="degraded",
            artifact_patch=ArtifactPatch(replace=replace_patch),
            step_summary=(
                "\nIn this idea_generation action, MCTS returned no candidate "
                "and no fallback legacy path was used."
            ),
            metrics={"experience_count": 0},
        )

    mode_order = {
        route.route_id: idx for idx, route in enumerate(IDEA_ROUTE_POLICIES)
    }
    mode_order.update({mode: idx for idx, mode in enumerate(IDEA_TASTE_PRESETS.keys())})
    completed_modes.sort(
        key=lambda item: (
            mode_order.get(item["mode"], len(mode_order)),
            str((item.get("seed") or {}).get("idea_id") or ""),
        )
    )
    raw_mode_entries = [item["entry"] for item in completed_modes]
    matrix_mode = any(route is not None for route in route_specs)
    if ligagent_pro and not matrix_mode:
        expected_modes = (
            [route.route_id for route in route_specs if route is not None]
            if any(route is not None for route in route_specs)
            else list(IDEA_TASTE_PRESETS.keys())
        )
        synthesis_result = synthesize_direction_set(
            raw_mode_entries,
            expected_modes=expected_modes,
            shared_candidates=raw_mode_entries,
            mode_results=mode_results,
            topic=topic,
            logger=logger,
        )
        mode_entries = list(synthesis_result.get("directions") or raw_mode_entries)
    else:
        synthesis_result = {
            "synthesis_mode": "mature_idea_route_matrix" if matrix_mode else "single_direction_compatibility",
            "directions": list(raw_mode_entries),
            "cross_direction_notes": [],
            "fallbacks": [],
            "direction_count": len(raw_mode_entries),
            "expected_direction_modes": [item.get("idea_taste_mode", "default") for item in raw_mode_entries],
            "matrix_cells": [
                {
                    "idea_id": item.get("idea_id") or item.get("seed_id"),
                    "route_id": item.get("route_id"),
                }
                for item in raw_mode_entries
                if item.get("route_id")
            ],
        }
        mode_entries = raw_mode_entries
    if ligagent_pro:
        profile_payload = (
            shared_context.get("scientific_intervention_profile")
            if isinstance(shared_context, dict)
            else None
        )
        profile_payload = profile_payload if isinstance(profile_payload, dict) else {}
        debate_result = debate_direction_set(
            mode_entries,
            topic=topic,
            survey_handoff=(shared_context.get("survey_idea_handoff") if isinstance(shared_context, dict) else None),
            profile_id=str(profile_payload.get("profile_id") or "generic_scientific"),
            profile_context=format_scientific_intervention_profile_for_prompt(profile_payload),
            runtime=_runtime(agent, ctx),
            session=session,
            workflow_name=ctx.workflow_name,
            model=materialization_model,
            logger=logger,
            max_rounds=int(get_config_value(agent.config, "debate.internal_max_rounds", 2) or 2),
            max_parallel_internal=int(get_config_value(agent.config, "debate.max_parallel_internal", 1) or 1),
            internal_prompt_limit=int(get_config_value(agent.config, "debate.internal_debate_prompt_limit", get_config_value(agent.config, "debate.prompt_char_limit", 80000)) or 80000),
            cross_seed_prompt_limit=int(get_config_value(agent.config, "debate.cross_seed_debate_prompt_limit", get_config_value(agent.config, "debate.prompt_char_limit", 60000)) or 60000),
            cross_seed_max_rounds=int(get_config_value(agent.config, "debate.cross_seed_max_rounds", 1) or 1),
            max_parallel_cross_seed=int(get_config_value(agent.config, "debate.max_parallel_cross_seed", 1) or 1),
            run_cross_seed=bool(get_config_value(agent.config, "debate.enabled", True)),
        )
        mode_entries = list(debate_result.get("directions") or mode_entries)
    else:
        debate_result = {
            "debate_mode": "single_direction_compatibility",
            "directions": list(mode_entries),
            "debate_trace": [],
            "failures": [],
            "round_count": 0,
            "direction_count": len(mode_entries),
        }
    idea_portfolio = build_idea_portfolio(
        mode_entries,
        mature_ideas,
        topic=topic,
        max_candidates_per_seed=int(get_config_value(agent.config, "portfolio.max_candidates_per_seed", 5) or 5),
        max_same_route_ratio=float(get_config_value(agent.config, "diversity.max_same_route_ratio", 0.60) or 0.60),
        debate_result=debate_result,
        has_survey_handoff=bool(isinstance(shared_context, dict) and shared_context.get("survey_idea_handoff")),
        min_independent_ideas=int(get_config_value(agent.config, "portfolio.min_independent_ideas", 2) or 2),
        primary_selection_policy=str(get_config_value(agent.config, "portfolio.primary_selection_policy", "scientific_maturity_diversity_validation") or "scientific_maturity_diversity_validation"),
        diversity_enabled=bool(get_config_value(agent.config, "diversity.enabled", True)),
        min_route_distance=float(get_config_value(agent.config, "diversity.min_route_distance", 0.35) or 0.35),
        regenerate_collapsed_routes=bool(get_config_value(agent.config, "diversity.regenerate_collapsed_routes", False)),
        preserve_high_risk_unique_candidates=bool(get_config_value(agent.config, "diversity.preserve_high_risk_unique_candidates", True)),
    )
    primary_entry = idea_portfolio.get("selected_primary_idea") or {}
    if isinstance(shared_context, dict) and shared_context.get("survey_idea_handoff"):
        portfolio_fallbacks = list(idea_portfolio.get("competitive_ideas", [])) + list(idea_portfolio.get("high_risk_ideas", []))
        fallback_pool = [
            item for item in portfolio_fallbacks
            if item.get("target_gap_ids") and item.get("invariant_status") != "violated"
        ]
    else:
        fallback_pool = list(mode_entries)
    if not primary_entry and isinstance(shared_context, dict) and shared_context.get("survey_idea_handoff") and not fallback_pool:
        logger.error("⚠️ Portfolio primary selection blocked: all candidates violate Survey invariants.")
        return StageResult(
            status="degraded",
            artifact_patch=ArtifactPatch(replace={
                "idea_portfolio": idea_portfolio,
                "data_anchored_mcts_schedule": data_schedule,
                "route_clusters": idea_portfolio.get("route_clusters", []),
                "diversity_report": idea_portfolio.get("diversity_report", {}),
            }),
            step_summary="\nIdea generation degraded because no Survey-aligned candidate satisfied the structural invariants.",
            metrics={"invariant_failure": True, "mode_count": len(mode_entries)},
        )
    best_entry = primary_entry or max(
        fallback_pool or mode_entries,
        key=lambda item: float(item.get("search_score") or 0.0),
    )
    best_entry.setdefault("search_score", 0.0)
    synthesis_result["primary_direction"] = best_entry.get("direction_mode") or best_entry.get("idea_taste_mode")
    best_entry["retrieved_core_titles"] = merge_title_lists(
        best_entry.get("retrieved_core_titles") or [],
        *[entry.get("retrieved_core_titles") or [] for entry in mode_entries],
    )
    save_candidate_payload(
        best_entry,
        agent.run_dir / "idea_candidate.json",
        logger,
    )
    final_payload = persist_final_idea(
        best_entry=best_entry,
        paper_entries=paper_entries,
        artifact=artifact,
        idea_result_path=agent.idea_result_path,
        chat_fn=materialize_chat,
        model=materialization_model,
        logger=logger,
        prompts=PROMPTS,
        persist_to_artifact=False,
        direction_synthesis=synthesis_result,
        scientific_debate=debate_result,
        mature_idea_contexts=mature_idea_contexts,
        mature_ideas=mature_ideas,
        idea_portfolio=idea_portfolio,
        introduction_max_output_tokens=int(
            get_config_value(agent.config, "agent.introduction_max_output_tokens", 25600) or 25600
        ),
        introduction_json_repair_attempts=int(
            get_config_value(agent.config, "agent.introduction_json_repair_attempts", 2) or 0
        ),
    )
    for source_entry in mode_entries:
        if not isinstance(source_entry, dict):
            continue
        mode = str(source_entry.get("direction_mode") or source_entry.get("idea_taste_mode") or "default").strip() or "default"
        direction = source_entry
        mode_payload = _build_mode_result_document(
            topic,
            direction,
            source_entry,
            artifact,
            final_payload.get("survey_binding"),
        )
        save_idea_result_payload(
            mode_payload,
            agent.run_dir
            / "mode_idea_results"
            / (
                f"{_safe_result_filename_component(direction.get('idea_id') or direction.get('seed_id'))}_"
                f"{_safe_result_filename_component(mode)}.json"
            ),
            logger,
        )

    pareto_lines = []
    pareto_count = 0
    for item in completed_modes:
        mode = item["mode"]
        result = item["result"]
        for label, cand in result.pareto.items():
            if cand:
                pareto_count += 1
                pareto_lines.append(
                    f"{mode}/{label}: {cand.node.state.title} (score={cand.evaluation.composite:.2f})"
                )
    pareto_summary = "; ".join(pareto_lines) if pareto_lines else "no Pareto picks"
    all_experiences: List[Any] = []
    all_evaluations: List[Any] = []
    for item in completed_modes:
        result = item["result"]
        all_experiences.extend(result.experiences)
        if result.best is not None:
            all_evaluations.append(result.best.to_dict()["evaluation"])
    if session is not None:
        session.set_slot("idea.latest", best_entry)
        session.set_slot("idea_result.latest", final_payload)
    step = (
        f"\nIn this idea_generation action, I ran memory-guided MCTS over '{topic}'. "
        f"{'The mature-idea × route matrix used isolated roots and contexts. ' if matrix_mode else ''}"
        f"{'All legacy idea taste modes were retained. ' if ligagent_pro and not matrix_mode else ''}"
        f"{'A direction-preserving synthesis pass retained all expected modes. ' if ligagent_pro else ''}"
        f"{'A fail-open scientific debate pass calibrated claims and scope. ' if ligagent_pro else ''}"
        f"Best idea: {best_entry['title']} (score={best_entry['search_score']:.2f}). "
        f"Pareto set -> {pareto_summary}. Persisted {len(all_experiences)} defect->fix lifts to long-term memory."
    )
    return StageResult(
        artifact_patch=ArtifactPatch(
            replace={
                "latest_candidate": best_entry,
                "mature_idea_contexts": mature_idea_contexts,
                "idea_result": final_payload,
                "ligagent_pro_candidates": mode_entries if (ligagent_pro or matrix_mode) else [],
                "fusion_result": {},
                "synthesis_result": synthesis_result,
                "debate_result": debate_result,
                "idea_portfolio": idea_portfolio,
                "route_clusters": idea_portfolio.get("route_clusters", []),
                "diversity_report": idea_portfolio.get("diversity_report", {}),
                "cross_seed_debate_result": debate_result.get("cross_seed_debate", {}),
                "idea_direction_results": final_payload.get("directions", []),
                "idea_hypotheses": [
                    item.get("hypothesis", {})
                    for item in final_payload.get("directions", [])
                    if isinstance(item, dict)
                ],
            },
            append={
                "evaluations": all_evaluations,
                "ltm_experiences": all_experiences,
            },
        ),
        step_summary=step,
        metrics={
            "experience_count": len(all_experiences),
            "pareto_count": pareto_count,
            "search_score": best_entry["search_score"],
            "mode_count": len(mode_entries),
            "mature_idea_count": len(mature_ideas),
            "route_count": len([route for route in route_specs if route is not None]),
            "fusion_used": False,
            "synthesis_used": bool(ligagent_pro),
        },
    )


def execute_reanalysis_replan_stage(agent: Any, ctx: StageContext) -> StageResult:
    artifact = agent.artifact
    logger = _logger(agent, ctx)
    runtime = _runtime(agent, ctx)
    session = _session(agent, ctx)

    analysis_entries = artifact_get(artifact, "analysis", [])
    analysis = analysis_entries[-1] if analysis_entries else {}
    ablation_results = artifact_get(artifact, "ablation_results", [])
    mature_idea = artifact_get(artifact, "mature_idea", "")
    mature_idea_records = filter_independent_mature_ideas(
        [
            idea for idea in normalize_mature_ideas(artifact_get(artifact, "mature_ideas", []))
            if str(idea.get("maturity_status") or "").casefold() != "rejected"
            and str(idea.get("independence_status") or "").casefold() != "collapsed_duplicate"
        ],
    )
    if not mature_idea_records and mature_idea:
        mature_idea_records = normalize_mature_ideas(mature_idea)
    refinement_scope = artifact_get(artifact, "refinement_scope", "")
    root_idea = artifact_get(artifact, "root_idea", {})
    latest_candidate = artifact_get(artifact, "latest_candidate", {})
    topic = artifact_get(artifact, "topic", [])[-1]

    seeds = mature_idea_records or [{"idea_id": "legacy-primary", "title": mature_idea, "hypothesis": mature_idea}]
    responses: List[Dict[str, Any]] = []
    for index, seed in enumerate(seeds):
        seed_text = mature_idea_legacy_text([seed]) or mature_idea or "(no mature idea yet)"
        prompt = PROMPTS["re_analysis_replan"].format(
            topic=topic,
            mature_idea=seed_text,
            refinement_scope=(seed.get("refinement_scope") or refinement_scope or "").strip(),
            analysis=pretty_json({**analysis, "mature_idea": seed}) if isinstance(analysis, dict) else str(analysis),
            ablation_results=pretty_json(ablation_results) if ablation_results else "[]",
        )
        response_i = runtime.llm_json(
            session=session,
            stage=ctx.stage_name,
            workflow_name=ctx.workflow_name,
            op_name=f"re_analysis_replan_{seed.get('idea_id') or index}",
            prompt=prompt,
            model=agent.model,
        )
        responses.append(response_i if isinstance(response_i, dict) else {})
    response = responses[0] if responses else {}

    component_decisions = [
        decision
        for item in responses
        for decision in (item.get("component_decisions", []) if isinstance(item.get("component_decisions", []), list) else [])
    ]
    search_keywords = [str(item.get("search_keywords") or "").strip() for item in responses if str(item.get("search_keywords") or "").strip()]
    search_kw = search_keywords[0] if search_keywords else ""

    replace_patch: Dict[str, Any] = {}
    updated_records: List[Dict[str, Any]] = []
    for seed, seed_response in zip(seeds, responses):
        updated = deepcopy(seed)
        if seed_response.get("mature_idea"):
            updated["hypothesis"] = seed_response["mature_idea"]
            updated["central_hypothesis"] = seed_response["mature_idea"]
            updated["abstract"] = seed_response["mature_idea"]
        updated.setdefault("lineage", [])
        lineage = updated["lineage"] if isinstance(updated["lineage"], list) else [updated["lineage"]]
        lineage.append({"event": "ablation_replan", "replan_id": f"replan:{updated.get('idea_id', 'legacy-primary')}"})
        updated["lineage"] = lineage
        updated["replan_id"] = f"replan:{updated.get('idea_id', 'legacy-primary')}"
        updated_records.append(updated)
    if updated_records:
        replace_patch["mature_ideas"] = updated_records
        replace_patch["mature_idea"] = mature_idea_legacy_text(updated_records)

    append_patch: Dict[str, List[Any]] = {}
    if component_decisions:
        append_patch["component_decisions"] = list(component_decisions)
    if search_keywords:
        append_patch["retrieval_keywords"] = search_keywords

    updated_mature_idea = str(response.get("mature_idea") or mature_idea or "").strip()
    replanned_entry = build_replanned_idea_entry(
        latest_candidate=latest_candidate,
        root_idea=root_idea,
        mature_idea=updated_mature_idea,
        component_decisions=component_decisions if isinstance(component_decisions, list) else [],
    )
    reference_batches = artifact_get(artifact, "references", [])
    latest_batch = reference_batches[-1] if reference_batches else []
    batch_list = [latest_batch] if latest_batch else reference_batches
    paper_entries = collect_paper_context_entries(artifact, batch_list)
    materialization_model = str(
        get_config_value(agent.config, "fusion.model", "") or agent.model
    ).strip()
    materialize_chat = _chat(agent, ctx, "idea_materialization")
    persist_final_idea(
        best_entry=replanned_entry,
        paper_entries=paper_entries,
        artifact=artifact,
        idea_result_path=agent.run_dir / "replanned_idea_result.json",
        chat_fn=materialize_chat,
        model=materialization_model,
        logger=logger,
        prompts=PROMPTS,
        persist_to_artifact=False,
        mature_idea_override=updated_mature_idea,
        refinement_scope_override=(refinement_scope or "").strip(),
        mature_ideas=updated_records,
        introduction_max_output_tokens=int(
            get_config_value(agent.config, "agent.introduction_max_output_tokens", 25600) or 25600
        ),
        introduction_json_repair_attempts=int(
            get_config_value(agent.config, "agent.introduction_json_repair_attempts", 2) or 0
        ),
    )

    if session is not None and updated_records:
        session.set_slot("mature_idea.latest", updated_records)
    n_decisions = len(component_decisions)
    decision_summary = "; ".join(
        f"{d['component']}->{d['decision']}" for d in component_decisions if isinstance(d, dict)
    ) or "no component decisions"
    step = (
        f"\nIn this re_analysis_replan action, I made {n_decisions} component-level "
        f"modification(s) based on ablation evidence: [{decision_summary}]. "
        f"Updated mature idea for MCTS root node."
    )
    return StageResult(
        artifact_patch=ArtifactPatch(
            replace=replace_patch,
            append=append_patch,
        ),
        step_summary=step,
        metrics={
            "component_decisions": n_decisions,
            "updated_mature_idea": bool(updated_records),
            "updated_search_keywords": bool(search_keywords),
            "mature_idea_count": len(updated_records),
        },
    )


def _workflow_phase_stage(agent: Any, ctx: StageContext, phase: str) -> StageResult:
    """Record an explicit compatibility phase without duplicating network work."""
    return StageResult(
        state_patch={"idea_workflow_phase": phase},
        step_summary=f"\nIdea workflow phase: {phase}.",
        metrics={"phase": phase},
    )


def execute_mature_idea_portfolio_generation_stage(agent: Any, ctx: StageContext) -> StageResult:
    artifact = agent.artifact
    topic_history = artifact_get(artifact, "topic", [])
    topic = topic_history[-1] if topic_history else ""
    existing = normalize_mature_ideas(
        artifact_get(artifact, "mature_ideas", []),
        legacy_value=artifact_get(artifact, "mature_idea", ""),
    )
    analysis_entries = artifact_get(artifact, "analysis", [])
    survey_context = artifact_get(artifact, "survey_idea_context", {})
    survey_handoff = (
        dict(survey_context.get("handoff") or {})
        if isinstance(survey_context, dict)
        else {}
    )
    multimodal_projection = (
        survey_context.get("multimodal_evidence_projection")
        if isinstance(survey_context, dict)
        else None
    )
    mature_ideas = collect_mature_idea_sources(
        existing=existing,
        survey_handoff=survey_handoff,
        prior_candidate=artifact_get(artifact, "latest_candidate", {}),
        experiment_results=artifact_get(artifact, "ablation_results", []),
        analysis=analysis_entries[-1] if analysis_entries else {},
        max_ideas=int(get_config_value(agent.config, "run.max_mature_ideas", 12) or 12),
        allow_problem_reframing=bool(get_config_value(agent.config, "run.allow_problem_reframing", True)),
        allow_unanchored_seed=bool(get_config_value(agent.config, "run.allow_unanchored_seed", True)),
        allow_high_risk_seed=bool(get_config_value(agent.config, "run.allow_high_risk_seed", True)),
        multimodal_evidence_projection=multimodal_projection,
    )
    return StageResult(
        artifact_patch=ArtifactPatch(replace={
            "mature_ideas": mature_ideas,
            "mature_idea": mature_idea_legacy_text(mature_ideas),
        }),
        state_patch={"idea_workflow_phase": "mature_idea_portfolio_generation", "topic": topic},
        step_summary="\nGenerated the multi-source mature-idea portfolio.",
        metrics={"mature_idea_count": len(mature_ideas)},
    )


def execute_mature_idea_adjudication_stage(agent: Any, ctx: StageContext) -> StageResult:
    artifact = agent.artifact
    adjudicated = filter_independent_mature_ideas(
        artifact_get(artifact, "mature_ideas", []),
        return_rejected=True,
    )
    accepted = adjudicated.get("accepted", [])
    rejected = adjudicated.get("rejected", [])
    return StageResult(
        artifact_patch=ArtifactPatch(replace={
            "mature_ideas": accepted + rejected,
            "mature_idea": mature_idea_legacy_text(accepted),
        }),
        state_patch={"idea_workflow_phase": "mature_idea_adjudication"},
        step_summary="\nAdjudicated mature-idea independence while retaining rejected records for the portfolio.",
        metrics={"independent_mature_ideas": len(accepted), "collapsed_mature_ideas": len(rejected)},
    )


def execute_route_context_preparation_stage(agent: Any, ctx: StageContext) -> StageResult:
    artifact = agent.artifact
    topic_history = artifact_get(artifact, "topic", [])
    topic = topic_history[-1] if topic_history else ""
    references = collect_paper_context_entries(artifact, artifact_get(artifact, "references", []))
    survey_context = artifact_get(artifact, "survey_idea_context", {})
    handoff = (
        dict(survey_context.get("handoff") or {})
        if isinstance(survey_context, dict)
        else {}
    )
    multimodal_projection = (
        survey_context.get("multimodal_evidence_projection")
        if isinstance(survey_context, dict)
        else None
    )
    mature_ideas = artifact_get(artifact, "mature_ideas", [])
    contexts = [
        build_mature_idea_evidence_context(
            idea,
            topic=topic,
            survey_handoff=handoff if isinstance(handoff, dict) else {},
            references=references,
            ablation_results=artifact_get(artifact, "ablation_results", []),
            multimodal_evidence_projection=multimodal_projection,
        )
        for idea in mature_ideas
        if isinstance(idea, dict)
        and str(idea.get("maturity_status") or "").casefold() != "rejected"
        and str(idea.get("independence_status") or "").casefold() != "collapsed_duplicate"
    ]
    return StageResult(
        artifact_patch=ArtifactPatch(replace={"mature_idea_contexts": contexts}),
        state_patch={"idea_workflow_phase": "route_context_preparation"},
        step_summary="\nPrepared isolated evidence contexts for mature-idea route expansion.",
        metrics={"route_context_count": len(contexts)},
    )


def execute_diversity_adjudication_stage(agent: Any, ctx: StageContext) -> StageResult:
    artifact = agent.artifact
    portfolio = artifact_get(artifact, "idea_portfolio", {})
    return StageResult(
        artifact_patch=ArtifactPatch(replace={
            "route_clusters": list(portfolio.get("route_clusters", [])) if isinstance(portfolio, dict) else [],
            "diversity_report": dict(portfolio.get("diversity_report", {})) if isinstance(portfolio, dict) else {},
        }),
        state_patch={"idea_workflow_phase": "diversity_adjudication"},
        step_summary="\nMaterialized route clusters and the portfolio diversity adjudication.",
        metrics={"diversity_failure": bool(portfolio.get("diversity_report", {}).get("diversity_failure")) if isinstance(portfolio, dict) else False},
    )


def execute_cross_seed_debate_stage(agent: Any, ctx: StageContext) -> StageResult:
    debate_result = artifact_get(agent.artifact, "debate_result", {})
    cross_seed = debate_result.get("cross_seed_debate", {}) if isinstance(debate_result, dict) else {}
    return StageResult(
        artifact_patch=ArtifactPatch(replace={"cross_seed_debate_result": cross_seed}),
        state_patch={"idea_workflow_phase": "cross_seed_debate"},
        step_summary="\nExposed bounded cross-seed Debate comparisons for portfolio synthesis.",
        metrics={"cross_seed_pair_count": len(cross_seed.get("pairs", [])) if isinstance(cross_seed, dict) else 0},
    )


def execute_portfolio_synthesis_stage(agent: Any, ctx: StageContext) -> StageResult:
    portfolio = artifact_get(agent.artifact, "idea_portfolio", {})
    return StageResult(
        state_patch={"idea_workflow_phase": "portfolio_synthesis"},
        step_summary="\nSynthesized primary, competitive, high-risk, and rejected portfolio views.",
        metrics={"portfolio_candidate_count": len(portfolio.get("competitive_ideas", [])) + 1 if isinstance(portfolio, dict) and portfolio.get("selected_primary_idea") else 0},
    )


def execute_primary_idea_materialization_stage(agent: Any, ctx: StageContext) -> StageResult:
    portfolio = artifact_get(agent.artifact, "idea_portfolio", {})
    primary = portfolio.get("selected_primary_idea", {}) if isinstance(portfolio, dict) else {}
    return StageResult(
        artifact_patch=ArtifactPatch(replace={"latest_candidate": primary}) if primary else ArtifactPatch(),
        state_patch={"idea_workflow_phase": "primary_idea_materialization"},
        step_summary="\nMaterialized the portfolio primary idea through the legacy Experiment-Agent handoff.",
        metrics={"primary_materialized": bool(primary)},
    )


def ka_route_stage(agent: Any, ctx: StageContext) -> StageResult:
    artifact = agent.artifact
    retrieval_keywords = artifact_get(artifact, "retrieval_keywords", [])
    search_keywords = retrieval_keywords[-1]
    topic_history = artifact_get(artifact, "topic", [])
    topic = topic_history[-1] if topic_history else search_keywords
    mature_idea = (artifact_get(artifact, "mature_idea", "") or "").strip()
    refinement_scope = (artifact_get(artifact, "refinement_scope", "") or "").strip()
    mode = "mature_idea" if mature_idea else "standard"
    return StageResult(
        state_patch={
            "mode": mode,
            "topic": topic,
            "search_keywords": search_keywords,
            "mature_idea": mature_idea,
            "refinement_scope": refinement_scope,
            "rag_query": "",
            "rag_hits": [],
            "survey_contents": [],
            "citation_titles": [],
            "citation_references": [],
            "ranked_keynotes": [],
            "curated_references": [],
            "retrieval_source": "",
            "summary": "",
        },
        next_stage="ka_query_generation",
        metrics={"mode": mode},
    )


def ka_query_generation_stage(agent: Any, ctx: StageContext) -> StageResult:
    logger = _logger(agent, ctx)

    mode = ctx.state["mode"]
    mature_idea = ctx.state.get("mature_idea", "")
    refinement_scope = ctx.state.get("refinement_scope", "")
    topic = ctx.state["topic"]
    search_keywords = ctx.state["search_keywords"]
    query_topic = search_keywords or topic
    rag_query = generate_rag_query(
        query_topic,
        PROMPTS,
        _chat(agent, ctx, "rag_query_generation"),
        agent.model,
        logger,
        mature_idea=mature_idea if mature_idea else None,
        refinement_scope=refinement_scope if refinement_scope else None,
    )
    logger.info(
        "🔎 Generated RAG Query%s: %s",
        " (mature idea)" if mode == "mature_idea" else "",
        rag_query,
    )
    return StageResult(
        state_patch={
            "rag_query": rag_query,
        },
        metrics={"rag_query_length": len(rag_query)},
    )


def ka_outcome_rag_stage(agent: Any, ctx: StageContext) -> StageResult:
    session = _session(agent, ctx)
    rag_query = ctx.state["rag_query"]
    rag_hits = retrieve_outcome_rag(
        query=rag_query,
        top_k=5,
        paper_repository=agent.paper_repository,
        logger=_logger(agent, ctx),
    )
    survey_contents = collect_rag_contents(rag_hits)
    citation_references = collect_rag_citation_references(rag_hits)
    citation_titles = collect_rag_citations(rag_hits)
    if session is not None:
        session.set_slot("rag.latest", {"query": rag_query, "hits": rag_hits})
    return StageResult(
        artifact_patch=ArtifactPatch(
            append={
                "rag_query": [rag_query],
                "rag_hits": [{"query": rag_query, "hits": rag_hits}],
                "rag_contents": [survey_contents],
            }
        ),
        state_patch={
            "rag_hits": rag_hits,
            "survey_contents": survey_contents,
            "citation_titles": citation_titles,
            "citation_references": citation_references,
        },
        metrics={
            "rag_hits": len(rag_hits),
            "citation_titles": len(citation_titles),
        },
    )


def ka_keynote_ranking_stage(agent: Any, ctx: StageContext) -> StageResult:
    logger = _logger(agent, ctx)
    topic = ctx.state["topic"]
    rag_query = ctx.state["rag_query"]
    citation_references = ctx.state.get("citation_references", [])
    keynote_references = agent.paper_repository.retrieve_keynotes_by_paper_ids(citation_references)
    scored_keynotes = []
    for reference in iter_with_progress(
        keynote_references,
        description="Scoring keynotes",
        total=len(keynote_references),
    ):
        scored_keynotes.append(
            _score_keynote_reference(agent, ctx, topic, rag_query, {**reference, "source_keywords": rag_query})
        )
    scored_keynotes.sort(key=lambda item: int(item["score"]), reverse=True)
    retrieval_source = "survey_keynotes"
    if logger is not None:
        for idx, reference in enumerate(scored_keynotes, 1):
            title = str(reference.get("title") or reference.get("paper_title") or "").strip()
            logger.info("📚 Survey Paper %d Title: %s", idx, title)
            logger.info("📚 Survey Paper %d Score: %s", idx, int(reference["score"]))
    return StageResult(
        state_patch={
            "ranked_keynotes": scored_keynotes,
            "retrieval_source": retrieval_source,
        },
        metrics={
            "keynote_references": len(keynote_references),
            "scored_keynotes": len(scored_keynotes),
            "retrieval_source": retrieval_source,
        },
    )


def ka_reference_selection_stage(agent: Any, ctx: StageContext) -> StageResult:
    session = _session(agent, ctx)
    topic = ctx.state["topic"]
    rag_query = ctx.state["rag_query"]
    rag_hits = ctx.state.get("rag_hits", [])
    ranked_keynotes = list(ctx.state.get("ranked_keynotes", []) or [])
    keynote_keep_top_k = min(1, int(get_config_value(agent.config, "agent.paper_keynote_keep_top_k", 5)))
    top_keynotes = ranked_keynotes[:keynote_keep_top_k]
    remaining_keynotes = ranked_keynotes[keynote_keep_top_k:]
    curated_references = [
        _compress_single_keynote_reference(agent, ctx, topic, rag_query, reference)
        for reference in top_keynotes
    ]
    if remaining_keynotes:
        curated_references.append(
            _summarize_remaining_keynotes(agent, ctx, topic, rag_query, remaining_keynotes)
        )
    mode = ctx.state["mode"]
    retrieval_source = ctx.state.get("retrieval_source", "")
    top_kept = len(top_keynotes)
    rolled_up = len(remaining_keynotes)
    if mode == "mature_idea":
        summary = (
            f"\nIn this knowledge_aquisition action, I used the mature idea to generate "
            f"a focused query '{rag_query}', retrieved {len(rag_hits)} survey hits, "
            f"and materialized {len(curated_references)} survey-cited paper capsules "
            f"via {retrieval_source or 'survey keynotes'} "
            f"({top_kept} individual paper summaries, {rolled_up} papers rolled into one summary)."
        )
    else:
        summary = (
            f"\nIn this knowledge_aquisition action, I generated a focused query '{rag_query}', "
            f"retrieved {len(rag_hits)} survey hits, and materialized {len(curated_references)} "
            f"survey-cited paper capsules via {retrieval_source or 'survey keynotes'} "
            f"({top_kept} individual paper summaries, {rolled_up} papers rolled into one summary)."
        )
    if session is not None:
        session.set_slot("references.latest", curated_references)
    return StageResult(
        artifact_patch=ArtifactPatch(
            append={"references": [curated_references]},
        ),
        state_patch={
            "curated_references": curated_references,
            "summary": summary,
        },
        metrics={"curated_references": len(curated_references)},
    )
