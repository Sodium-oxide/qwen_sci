"""Project-level research identity and Survey-aware objective operationalization."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from src.pipeline.discipline_taxonomy import get_discipline_entry
from src.pipeline.research_design_inventory import (
    build_research_design_inventory,
    validate_research_design_inventory,
)
from src.pipeline.research_domain_resolution import resolve_project_domain_contract
from src.pipeline.retrieval_lanes import build_project_query_lanes


PROJECT_RESEARCH_CONTEXT_SCHEMA_VERSION = "project_research_context_v3"
_MAX_IDENTITY_TERMS = 12
_MAX_EVIDENCE_SPANS = 8
_MAX_EXCLUSION_TERMS = 10


def _as_text(value: Any, *, limit: int = 6000) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def _normalized_text(value: Any) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", _as_text(value).casefold()).split())


def _unique_texts(values: Any, *, limit: int) -> list[str]:
    if not isinstance(values, (list, tuple)):
        values = [values]
    cleaned: list[str] = []
    seen = set()
    for value in values:
        text = _as_text(value, limit=180)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _fingerprint_payload(
    *,
    original_topic: str,
    title: str,
    declared_domain: str,
    objective: str,
    research_brief: str,
) -> str:
    payload = {
        "schema_version": PROJECT_RESEARCH_CONTEXT_SCHEMA_VERSION,
        "original_topic": original_topic,
        "title": title,
        "declared_domain": declared_domain,
        "objective": objective,
        "research_brief": research_brief,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def project_research_context_fingerprint(
    *,
    original_topic: Any,
    title: Any = "",
    declared_domain: Any = "",
    objective: Any = "",
    research_brief: Any = "",
) -> str:
    """Return the stable cache key for one complete project-level input."""

    topic = _as_text(original_topic)
    return _fingerprint_payload(
        original_topic=topic,
        title=_as_text(title),
        declared_domain=_as_text(declared_domain),
        objective=_as_text(objective) or topic,
        research_brief=_as_text(research_brief),
    )


def audit_academic_operationalization(
    original_objective: Any,
    *,
    taxonomy_resolution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide whether a Survey goal needs a scoped, non-causal rewrite."""

    objective = _as_text(original_objective)
    normalized = _normalized_text(objective)
    tokens = normalized.split()
    reasons: list[str] = []
    broad_markers = (
        "use ai",
        "using ai",
        "artificial intelligence",
        "large language model",
        "smart ",
        "green ",
        "智能",
        "绿色",
        "人工智能",
        "大模型",
    )
    detail_markers = (
        "compared",
        "comparison",
        "baseline",
        "benchmark",
        "dataset",
        "metric",
        "performance",
        "under ",
        "condition",
        "failure",
        "limitation",
        "相比",
        "比较",
        "基线",
        "数据",
        "指标",
        "条件",
        "局限",
        "失效",
    )
    if not objective:
        reasons.append("missing_objective")
    elif len(tokens) <= 5 or len(objective) <= 28:
        reasons.append("too_brief_to_define_retrieval_scope")
    if any(marker in normalized or marker in objective for marker in broad_markers) and not any(
        marker in normalized or marker in objective for marker in detail_markers
    ):
        reasons.append("broad_solution_or_slogan_language")
    if taxonomy_resolution and taxonomy_resolution.get("status") == "ambiguous":
        reasons.append("cross_domain_scope_needs_object_task_anchors")
    return {
        "schema_version": "academic_operationalization_audit_v1",
        "original_objective": objective,
        "recommended_action": "operationalize" if reasons else "preserve",
        "needs_operationalization": bool(reasons),
        "detected_weaknesses": reasons,
    }


def _deterministic_operationalization(
    original_objective: str,
    *,
    primary_discipline: str | None,
    audit: Mapping[str, Any],
) -> dict[str, Any]:
    if not audit.get("needs_operationalization"):
        return {
            "applied": False,
            "mode": "survey_scope",
            "original_objective": original_objective,
            "normalized_objective": original_objective,
            "task_or_question": "",
            "research_object": "",
            "outcomes_or_readouts": [],
            "data_or_deployment_context": [],
            "baseline_requirements": [],
            "limitation_and_failure_conditions": [],
            "rewrite_reason": "The original objective already contains sufficient scope anchors.",
            "extractor": "deterministic_skip",
        }
    discipline_label = (
        get_discipline_entry(primary_discipline).label
        if get_discipline_entry(primary_discipline)
        else "the declared research domain"
    )
    normalized_objective = (
        f"For {original_objective}, which research objects, tasks, data or deployment "
        f"conditions, and evaluation criteria in {discipline_label} support reproducible "
        "advantages over explicit baselines, and where do limitations or failures occur?"
    )
    return {
        "applied": True,
        "mode": "survey_scope",
        "original_objective": original_objective,
        "normalized_objective": normalized_objective,
        "task_or_question": "Identify task, object, condition, evidence, and limitation boundaries.",
        "research_object": "",
        "outcomes_or_readouts": ["reported task performance", "evidence quality", "reproducibility"],
        "data_or_deployment_context": [],
        "baseline_requirements": ["explicit task-appropriate baseline"],
        "limitation_and_failure_conditions": ["reported limitation, failure mode, or boundary condition"],
        "rewrite_reason": "; ".join(audit.get("detected_weaknesses") or []),
        "extractor": "deterministic_domain_contract",
    }


def _parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    text = str(value or "").strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _safe_confidence(value: Any, fallback: float) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 3)
    except (TypeError, ValueError):
        return fallback


def _taxonomy_confidence(resolution: Mapping[str, Any]) -> float:
    if resolution.get("status") == "out_of_scope":
        return 1.0
    if resolution.get("status") == "unresolved":
        return 0.0
    return 0.9 if resolution.get("coverage") == "exact" else 0.65


def _normalize_llm_operationalization(
    payload: Mapping[str, Any],
    *,
    deterministic: Mapping[str, Any],
    audit: Mapping[str, Any],
) -> dict[str, Any]:
    if not audit.get("needs_operationalization"):
        return dict(deterministic)
    raw = payload.get("operationalization")
    if not isinstance(raw, Mapping):
        raw = payload
    normalized_objective = _as_text(
        raw.get("normalized_objective") or raw.get("academic_objective"),
        limit=1600,
    )
    if not normalized_objective:
        return dict(deterministic)
    result = dict(deterministic)
    result.update(
        {
            "applied": True,
            "mode": str(raw.get("mode") or "survey_scope").strip() or "survey_scope",
            "normalized_objective": normalized_objective,
            "task_or_question": _as_text(raw.get("task_or_question"), limit=800),
            "research_object": _as_text(raw.get("research_object"), limit=400),
            "outcomes_or_readouts": _unique_texts(raw.get("outcomes_or_readouts"), limit=8),
            "data_or_deployment_context": _unique_texts(raw.get("data_or_deployment_context"), limit=8),
            "baseline_requirements": _unique_texts(raw.get("baseline_requirements"), limit=8),
            "limitation_and_failure_conditions": _unique_texts(
                raw.get("limitation_and_failure_conditions"),
                limit=8,
            ),
            "rewrite_reason": _as_text(raw.get("rewrite_reason"), limit=800),
            "extractor": "llm",
        }
    )
    return result


def _recommended_sources(taxonomy_resolution: Mapping[str, Any]) -> list[dict[str, Any]]:
    provider_filters = taxonomy_resolution.get("provider_filters")
    filters = provider_filters if isinstance(provider_filters, Mapping) else {}
    openalex_filter = dict(filters.get("openalex") or {})
    arxiv_filter = dict(filters.get("arxiv") or {})
    semantic_filter = dict(filters.get("semantic_scholar") or {})
    return [
        {
            "provider": "openalex",
            "priority": 1,
            "role": "primary_discovery",
            "native_filter": openalex_filter,
        },
        {
            "provider": "arxiv",
            "priority": 2,
            "role": "conditional_preprint_discovery",
            "enabled_for_exact_mapping": bool(arxiv_filter.get("applied")),
            "native_filter": arxiv_filter,
        },
        {
            "provider": "semantic_scholar",
            "priority": 3,
            "role": "fallback_only",
            "native_filter": semantic_filter,
        },
    ]


def _retrieval_plan(
    *,
    original_topic: str,
    operationalization: Mapping[str, Any],
    identity: Mapping[str, Any],
    taxonomy_resolution: Mapping[str, Any],
    domain_contract: Mapping[str, Any],
) -> dict[str, Any]:
    return build_project_query_lanes(
        {
            "original_topic": original_topic,
            "taxonomy_resolution": taxonomy_resolution,
            "domain": domain_contract.get("domain", ""),
            "research_domains": domain_contract.get("research_domains", []),
            "domain_context": domain_contract.get("domain_context", {}),
            "core_entities": identity.get("core_entities", []),
            "retrieval_synonyms": identity.get("retrieval_synonyms", []),
            "exclusion_terms": identity.get("exclusion_terms", []),
            "academic_operationalization": operationalization,
        }
    )


def build_project_research_context(
    *,
    original_topic: Any,
    title: Any = "",
    declared_domain: Any = "",
    objective: Any = "",
    research_brief: Any = "",
    use_llm: bool = True,
    llm_call: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Build the current project-domain contract without provider calls.

    This deliberately has one runtime path: a v8-style domain contract is
    resolved first, then its canonical discovery taxonomy is used for provider
    filters.  The prior primary-discipline-only context is not consulted.
    """

    topic = _as_text(original_topic)
    title_text = _as_text(title)
    domain_text = _as_text(declared_domain)
    objective_text = _as_text(objective) or topic
    brief_text = _as_text(research_brief)
    domain_contract = resolve_project_domain_contract(
        original_topic=topic,
        title=title_text,
        declared_domain=domain_text,
        objective=objective_text or topic,
        research_brief=brief_text,
        use_llm=use_llm,
        llm_call=llm_call,
    )
    taxonomy_resolution = dict(domain_contract.get("discovery_taxonomy") or {})
    audit = audit_academic_operationalization(
        objective_text,
        taxonomy_resolution=taxonomy_resolution,
    )
    catalog_matches = [
        term
        for item in domain_contract.get("research_domains", [])
        if isinstance(item, Mapping)
        for term in item.get("matched_terms", [])
    ]
    domain_identity = dict(domain_contract.get("research_identity") or {})
    primary_discipline = domain_contract.get("primary_discipline") or None
    identity = {
        "identity_status": (
            "out_of_scope"
            if taxonomy_resolution.get("status") == "out_of_scope"
            else "resolved"
            if primary_discipline
            else "unresolved"
        ),
        "primary_discipline": primary_discipline,
        "secondary_disciplines": list(domain_contract.get("secondary_disciplines") or []),
        "domain_confidence": _safe_confidence(
            domain_contract.get("domain_confidence"),
            _taxonomy_confidence(taxonomy_resolution),
        ),
        "evidence_spans": list(domain_identity.get("evidence_spans") or catalog_matches[:_MAX_EVIDENCE_SPANS]),
        "core_entities": list(domain_identity.get("core_entities") or catalog_matches[:_MAX_IDENTITY_TERMS]),
        "retrieval_synonyms": list(
            domain_identity.get("retrieval_synonyms")
            or (domain_contract.get("domain_context") or {}).get("taxonomy_labels", [])
        ),
        "abbreviations": list(domain_contract.get("abbreviations") or []),
        "exclusion_terms": list(domain_contract.get("exclusion_terms") or []),
    }
    deterministic_operationalization = _deterministic_operationalization(
        objective_text,
        primary_discipline=primary_discipline,
        audit=audit,
    )
    operationalization = _normalize_llm_operationalization(
        domain_contract.get("llm_payload") or {},
        deterministic=deterministic_operationalization,
        audit=audit,
    )
    llm_used = domain_identity.get("source") == "llm_primary"

    context = {
        "input_fingerprint": _fingerprint_payload(
            original_topic=topic,
            title=title_text,
            declared_domain=domain_text,
            objective=objective_text,
            research_brief=brief_text,
        ),
        "original_topic": topic,
        "title": title_text,
        **domain_contract,
        "taxonomy_resolution": taxonomy_resolution,
        "original_objective": objective_text,
        "research_brief": brief_text,
        **identity,
        "academic_operationalization": operationalization,
        "recommended_sources": _recommended_sources(taxonomy_resolution),
        "retrieval_plan": _retrieval_plan(
            original_topic=topic,
            operationalization=operationalization,
            identity=identity,
            taxonomy_resolution=taxonomy_resolution,
            domain_contract=domain_contract,
        ),
        "identity_source": str(domain_contract.get("domain_resolution_source") or "catalog"),
        "llm_used": llm_used,
        "llm_error": str(domain_contract.get("llm_error") or ""),
        "schema_version": PROJECT_RESEARCH_CONTEXT_SCHEMA_VERSION,
    }
    context["research_design_inventory"] = build_research_design_inventory(
        context,
        use_llm=use_llm,
        llm_call=llm_call,
    )
    return context


def load_or_build_project_research_context(
    *,
    cache_path: str | Path | None,
    original_topic: Any,
    title: Any = "",
    declared_domain: Any = "",
    objective: Any = "",
    research_brief: Any = "",
    use_llm: bool = True,
    llm_call: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Load a matching context cache or build and persist it once."""

    topic = _as_text(original_topic)
    title_text = _as_text(title)
    domain_text = _as_text(declared_domain)
    objective_text = _as_text(objective) or topic
    brief_text = _as_text(research_brief)
    fingerprint = _fingerprint_payload(
        original_topic=topic,
        title=title_text,
        declared_domain=domain_text,
        objective=objective_text,
        research_brief=brief_text,
    )
    path = Path(cache_path) if cache_path else None
    if path and path.exists():
        try:
            cached = _parse_json_object(path.read_text(encoding="utf-8"))
            if (
                cached.get("schema_version") == PROJECT_RESEARCH_CONTEXT_SCHEMA_VERSION
                and cached.get("input_fingerprint") == fingerprint
            ):
                validate_research_design_inventory(
                    cached.get("research_design_inventory"),
                    project_context=cached,
                )
                return {**cached, "cache_status": "hit"}
        except (OSError, ValueError):
            pass

    context = build_project_research_context(
        original_topic=topic,
        title=title_text,
        declared_domain=domain_text,
        objective=objective_text,
        research_brief=brief_text,
        use_llm=use_llm,
        llm_call=llm_call,
    )
    if path:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(context, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            context["cache_write_error"] = "failed_to_persist"
    return {**context, "cache_status": "miss"}


def relevance_context_payload(context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return the bounded project contract used in per-paper relevance prompts."""

    payload = context if isinstance(context, Mapping) else {}
    operationalization = payload.get("academic_operationalization")
    normalized = operationalization if isinstance(operationalization, Mapping) else {}
    return {
        "input_fingerprint": str(payload.get("input_fingerprint") or ""),
        "original_topic": str(payload.get("original_topic") or ""),
        "declared_domain": str(payload.get("declared_domain") or ""),
        "domain": str(payload.get("domain") or ""),
        "research_domains": [
            str(item.get("label") or "")
            for item in list(payload.get("research_domains") or [])[:5]
            if isinstance(item, Mapping)
        ],
        "requires_human_confirmation": bool(payload.get("requires_human_confirmation")),
        "identity_status": str(payload.get("identity_status") or "unresolved"),
        "primary_discipline": str(payload.get("primary_discipline") or ""),
        "secondary_disciplines": list(payload.get("secondary_disciplines") or [])[:2],
        "core_entities": list(payload.get("core_entities") or [])[:_MAX_IDENTITY_TERMS],
        "include_anchors": list(
            (payload.get("retrieval_plan") or {}).get("include_anchors") or []
        )[:_MAX_IDENTITY_TERMS],
        "exclude_anchors": list(payload.get("exclusion_terms") or [])[:_MAX_EXCLUSION_TERMS],
        "normalized_objective": str(normalized.get("normalized_objective") or ""),
    }


def relatedness_cache_key(
    context: Mapping[str, Any] | None,
    seed_paper_id: Any,
    candidate_paper_id: Any,
) -> str:
    fingerprint = ""
    if isinstance(context, Mapping):
        fingerprint = str(context.get("input_fingerprint") or "")
    return hashlib.sha256(
        f"{fingerprint}||{str(seed_paper_id or '').strip()}||{str(candidate_paper_id or '').strip()}".encode(
            "utf-8"
        )
    ).hexdigest()
