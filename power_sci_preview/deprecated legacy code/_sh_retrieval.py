"""SH-level retrieval planning and deterministic corpus selection.

The retrieval boundary is intentionally separate from proposition extraction.
This module only compiles one sub-hypothesis into a bounded discovery plan and
selects a diverse paper corpus.  Source-grounded evidence remains the
authority for assertions and admission.
"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

try:
    from .config import SCIENCE_DIR
except ImportError:
    from config import SCIENCE_DIR


SH_RETRIEVAL_PLAN_SCHEMA_VERSION = "sh_retrieval_plan_v1"
SH_CORPUS_SELECTION_SCHEMA_VERSION = "sh_corpus_selection_v1"
SH_RETRIEVAL_RUN_SCHEMA_VERSION = "sh_retrieval_run_v1"
SH_REVIEW_SELECTION_SCHEMA_VERSION = "sh_review_selection_v1"
SH_SYNTHESIS_SCHEMA_VERSION = "sh_evidence_synthesis_v1"
MAX_ADDITIONAL_WAVES = 1
MAX_ADDITIONAL_PAPERS_PER_SLOT = 5

DEFAULT_SH_LAYER_QUOTAS: dict[str, int] = {
    "L2_top_latest": 18,
    "L4_regular": 24,
    "L0_review": 3,
    "L1_milestone": 1,
    "L3_preprint": 0,
}

_EXCLUDED_REVIEW_SECTION_RE = re.compile(
    r"\b(?:references?|bibliography|acknowledg(?:e)?ments?|supplement(?:ary)?|author contributions?|data availability|conflict(?:s)? of interest)\b",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[\w][\w-]{2,}", re.UNICODE)
_QUANTITY_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*%|\bp\s*[<=>]\s*\.?\d+|\b(?:95%?\s*CI|confidence interval|reynolds|temperature|velocity|scaling|exponent)\b)",
    re.IGNORECASE,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _stable_candidate_key(candidate: Mapping[str, Any]) -> str:
    for key in (
        "doi",
        "openalex_id",
        "semantic_scholar_id",
        "arxiv_id",
        "pmid",
        "url",
        "title",
    ):
        value = _text(candidate.get(key)).casefold()
        if value:
            return f"{key}:{value}"
    payload = "|".join(
        _text(candidate.get(key)).casefold()
        for key in ("title", "year", "venue", "abstract")
    )
    return "fallback:" + sha256(payload.encode("utf-8", errors="ignore")).hexdigest()[:24]


def _unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _text(value)
        key = normalized.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _flatten_text(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [text for nested in value.values() for text in _flatten_text(nested)]
    if isinstance(value, (list, tuple, set)):
        return [text for nested in value for text in _flatten_text(nested)]
    text = _text(value)
    return [text] if text else []


def _review_anchor_terms(contract: Mapping[str, Any], matched_branches: Iterable[Any]) -> list[str]:
    terms: list[str] = []
    question = contract.get("research_question") if isinstance(contract.get("research_question"), Mapping) else {}
    scope = contract.get("scientific_scope") if isinstance(contract.get("scientific_scope"), Mapping) else {}
    terms.extend(_flatten_text(question.get("question_text")))
    terms.extend(_flatten_text(scope))
    definitions = contract.get("slot_definitions") if isinstance(contract.get("slot_definitions"), Mapping) else {}
    for definition in definitions.values():
        if isinstance(definition, Mapping):
            terms.extend(_flatten_text(definition.get("retrieval_concepts")))
            terms.extend(_flatten_text(definition.get("required_terms")))
    terms.extend(_flatten_text(matched_branches))
    return _unique(terms)


def _review_tokens(value: Any) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN_RE.findall(" ".join(_flatten_text(value)))
        if len(token) >= 3
    }


def select_review_evidence_units(
    source_spans: Iterable[Mapping[str, Any]],
    contract: Mapping[str, Any],
    *,
    matched_branches: Iterable[Any] = (),
    max_spans_per_paper: int = 12,
) -> dict[str, Any]:
    """Select a bounded, source-preserving review set before any LLM call.

    This is a recall-oriented input reducer only. It cannot create an
    assertion or grant alignment; source quote grounding and contract
    admission remain downstream validators.
    """

    source_span_items = [
        dict(item) for item in source_spans if isinstance(item, Mapping)
    ]
    candidates: list[dict[str, Any]] = []
    anchors = _review_anchor_terms(contract, matched_branches)
    anchor_tokens = _review_tokens(anchors)
    limit = max(1, int(max_spans_per_paper or 12))
    for source_span in source_span_items:
        span = dict(source_span)
        span_id = _text(span.get("source_span_id"))
        quote = _text(span.get("quote"))
        if not span_id or not quote or span.get("extraction_eligible") is not True:
            continue
        heading = _text(span.get("section_heading") or span.get("section_title"))
        if _EXCLUDED_REVIEW_SECTION_RE.search(heading):
            continue
        text = f"{heading} {quote}"
        tokens = _review_tokens(text)
        exact_hits = sum(1 for anchor in anchors if _text(anchor).casefold() in text.casefold())
        token_hits = len(tokens & anchor_tokens)
        score = exact_hits * 8.0 + min(token_hits, 12) * 0.75
        if heading:
            score += 1.5
        if _QUANTITY_RE.search(quote):
            score += 2.0
        span_kind = _text(span.get("span_kind")).casefold()
        if span_kind in {"table", "figure_caption"}:
            score += 1.0
        length = len(quote)
        long_span = length >= 1000
        if long_span:
            score -= min(2.0, length / 10000.0)
        section_key = heading.casefold() or _text(span.get("section_id")).casefold() or "unknown"
        candidates.append({
            **span,
            "review_selection_score": round(score, 4),
            "review_selection_section": section_key,
            "review_selection_long_span": long_span,
        })
    candidates.sort(
        key=lambda item: (
            -float(item.get("review_selection_score") or 0.0),
            int(item.get("quote_char_start") or 0),
            _text(item.get("source_span_id")),
        )
    )
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    selected_sections: set[str] = set()
    long_limit = min(limit, 6)
    long_selected = 0
    for item in candidates:
        section_key = _text(item.get("review_selection_section")) or "unknown"
        if section_key in selected_sections:
            continue
        if item.get("review_selection_long_span") and long_selected >= long_limit:
            continue
        selected.append({**item, "review_selection_reason": "SECTION_DIVERSITY_FIRST"})
        selected_ids.add(_text(item.get("source_span_id")))
        selected_sections.add(section_key)
        long_selected += bool(item.get("review_selection_long_span"))
        if len(selected) >= limit:
            break
    for item in candidates:
        span_id = _text(item.get("source_span_id"))
        if not span_id or span_id in selected_ids:
            continue
        if item.get("review_selection_long_span") and long_selected >= long_limit:
            continue
        selected.append({**item, "review_selection_reason": "INCREMENTAL_ANCHOR_RELEVANCE"})
        selected_ids.add(span_id)
        long_selected += bool(item.get("review_selection_long_span"))
        if len(selected) >= limit:
            break
    selected.sort(key=lambda item: (int(item.get("quote_char_start") or 0), _text(item.get("source_span_id"))))
    for rank, item in enumerate(selected, start=1):
        item["review_selection_rank"] = rank
    return {
        "schema_version": SH_REVIEW_SELECTION_SCHEMA_VERSION,
        "max_spans_per_paper": limit,
        "candidate_count": len(candidates),
        "selected_count": len(selected),
        "selected_source_span_ids": [
            _text(item.get("source_span_id")) for item in selected
        ],
        "excluded_section_count": sum(
            1
            for source_span in source_span_items
            if _EXCLUDED_REVIEW_SECTION_RE.search(
                _text(source_span.get("section_heading") or source_span.get("section_title"))
            )
        ),
        "selected_spans": selected,
        "selection_policy": "LOCAL_RECALL_REDUCTION_ONLY_SOURCE_BOUND_VALIDATION_DOWNSTREAM",
    }


def build_targeted_gap_query(
    obligation: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    sub_hypothesis_id: str = "",
) -> dict[str, Any]:
    """Compile one bounded, scope-preserving follow-up query from a gap."""

    slot_id = _text(obligation.get("slot_id"))
    definitions = contract.get("slot_definitions") if isinstance(contract.get("slot_definitions"), Mapping) else {}
    definition = definitions.get(slot_id) if isinstance(definitions.get(slot_id), Mapping) else {}
    terms = _unique([
        *_flatten_text((contract.get("scientific_scope") or {})),
        *_flatten_text(definition.get("retrieval_concepts")),
        *_flatten_text(definition.get("required_terms")),
        *_flatten_text(obligation.get("missing_requirements")),
        _text(obligation.get("missing_evidence")),
    ])
    query = " ".join(terms[:18])
    branch_id = f"{_text(sub_hypothesis_id)}:{slot_id}:targeted_gap" if slot_id else f"{_text(sub_hypothesis_id)}:targeted_gap"
    return {
        "schema_version": "sh_targeted_gap_query_v1",
        "branch_id": branch_id,
        "slot_id": slot_id,
        "query_mode": "POSITIVE_EVIDENCE",
        "query_text": query,
        "target_layers": ["L2_top_latest", "L4_regular"],
        "max_papers": MAX_ADDITIONAL_PAPERS_PER_SLOT,
        "wave_limit": MAX_ADDITIONAL_WAVES,
        "status": "PLANNED" if query else "UNRESOLVABLE_MISSING_ANCHORS",
    }


def synthesize_sh_evidence(
    contract: Mapping[str, Any],
    paper_reviews: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate source-bound paper results without making unsupported claims."""

    required_slots = [
        _text(slot)
        for slot in ((contract.get("evidence_contract") or {}).get("required_slots") or [])
        if _text(slot)
    ]
    slot_assertions: dict[str, list[dict[str, Any]]] = {slot: [] for slot in required_slots}
    background_assertions: list[dict[str, Any]] = []
    paper_count_by_slot: dict[str, set[str]] = {slot: set() for slot in required_slots}
    span_count_by_slot: dict[str, set[str]] = {slot: set() for slot in required_slots}
    arm_observations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for review in paper_reviews:
        if not isinstance(review, Mapping):
            continue
        paper_id = _text(review.get("paper_id"))
        assertions = review.get("assertions") if isinstance(review.get("assertions"), list) else []
        supports = review.get("slot_supports") if isinstance(review.get("slot_supports"), list) else []
        support_by_assertion: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for support in supports:
            if isinstance(support, Mapping):
                support_by_assertion[_text(support.get("assertion_id"))].append(support)
        for assertion in assertions:
            if not isinstance(assertion, Mapping):
                continue
            assertion_id = _text(assertion.get("assertion_id"))
            matched = False
            for support in support_by_assertion.get(assertion_id, []):
                slot_id = _text(support.get("slot_id"))
                if slot_id not in slot_assertions:
                    continue
                status = _text(support.get("support_status") or support.get("admission_status")).upper()
                if status not in {"ADMITTED", "DIRECT_SLOT_ADMITTED", "SUPPORTS", "CONSISTENT_WITH"}:
                    continue
                item = {
                    "paper_id": paper_id,
                    "assertion_id": assertion_id,
                    "slot_id": slot_id,
                    "source_span_ids": list(support.get("source_span_ids") or assertion.get("source_span_ids") or []),
                    "counts_toward_gate": False,
                    "source_bound": True,
                }
                if item not in slot_assertions[slot_id]:
                    slot_assertions[slot_id].append(item)
                paper_count_by_slot[slot_id].add(paper_id)
                span_count_by_slot[slot_id].update(str(value) for value in item["source_span_ids"] if str(value))
                matched = True
                frame = support.get("comparison_frame_v4")
                if isinstance(frame, Mapping):
                    for arm in frame.get("arm_mentions") or []:
                        if isinstance(arm, Mapping) and _text(arm.get("arm_id")):
                            arm_observations[_text(arm.get("arm_id"))].append(item)
            if not matched:
                background_assertions.append({
                    "paper_id": paper_id,
                    "assertion_id": assertion_id,
                    "counts_toward_gate": False,
                    "source_bound": True,
                    "classification": "BACKGROUND_OR_COMPONENT_PENDING_ADMISSION",
                })
    comparison_contract = contract.get("comparison_contract_v4") if isinstance(contract.get("comparison_contract_v4"), Mapping) else {}
    expected_arms = [
        _text((comparison_contract.get("primary_arm") or {}).get("arm_id")),
        *[
            _text(item.get("arm_id"))
            for item in comparison_contract.get("comparator_arms") or []
            if isinstance(item, Mapping)
        ],
    ]
    comparison_bundles: list[dict[str, Any]] = []
    if comparison_contract and expected_arms and all(arm_observations.get(arm) for arm in expected_arms):
        comparison_bundles.append({
            "schema_version": "comparison_bundle_v1",
            "comparison_contract_id": _text(comparison_contract.get("comparison_contract_id")),
            "arm_ids": expected_arms,
            "source_assertion_ids": sorted({
                _text(item.get("assertion_id"))
                for arm in expected_arms
                for item in arm_observations.get(arm, [])
                if _text(item.get("assertion_id"))
            }),
            "status": "READY_FOR_CROSS_PAPER_COMPARISON",
            "counts_toward_gate": False,
        })
    coverage: dict[str, dict[str, Any]] = {}
    for slot in required_slots:
        papers = sorted(paper_count_by_slot[slot])
        spans = sorted(span_count_by_slot[slot])
        coverage[slot] = {
            "slot_id": slot,
            "positive_assertion_count": len(slot_assertions[slot]),
            "distinct_paper_count": len(papers),
            "distinct_span_count": len(spans),
            "status": "SATISFIED" if slot_assertions[slot] else "UNRESOLVED",
            "policy_verdict": "SATISFIED_BY_NEW_EVIDENCE" if slot_assertions[slot] else "UNSATISFIED",
        }
    return {
        "schema_version": SH_SYNTHESIS_SCHEMA_VERSION,
        "slot_assertions": slot_assertions,
        "comparison_bundles": comparison_bundles,
        "mechanism_bridges": [],
        "background_assertions": background_assertions,
        "coverage": coverage,
        "scientific_obligations": {
            "comparison_requires_cross_paper_synthesis": bool(comparison_contract),
            "direct_conclusion_ready": bool(comparison_bundles),
        },
    }


def persist_sh_retrieval_run(run: Mapping[str, Any]) -> dict[str, Any]:
    """Persist compact SH-level artifacts for deterministic resume/audit."""

    project_id = _text(run.get("project_id")) or "unscoped_project"
    sub_id = _text(run.get("sub_hypothesis_id")) or "unknown_sh"
    run_id = _text(run.get("run_id")) or "shrun_" + uuid4().hex[:20]
    safe_component = lambda value, fallback: re.sub(
        r"[^A-Za-z0-9._-]+", "_", _text(value)
    ).strip("._-")[:120] or fallback
    base = (
        Path(SCIENCE_DIR)
        / "prepared_evidence"
        / "sh_runs"
        / safe_component(project_id, "unscoped_project")
        / safe_component(sub_id, "unknown_sh")
        / safe_component(run_id, "sh_run")
    )
    base.mkdir(parents=True, exist_ok=True)

    def write(name: str, value: Any) -> str:
        path = base / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
        temporary.replace(path)
        return str(path)

    payload = dict(run)
    payload.update({
        "schema_version": SH_RETRIEVAL_RUN_SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": float(payload.get("created_at") or time.time()),
    })
    artifact_metadata = {
        "schema_version": "sh_retrieval_artifact_metadata_v1",
        "project_id": project_id,
        "sub_hypothesis_id": sub_id,
        "contract_id": _text(payload.get("contract_id")),
        "contract_revision": _text(payload.get("contract_revision")),
        "retrieval_run_id": run_id,
        "model_id": _text(payload.get("model_id")),
        "prompt_revision": _text(payload.get("prompt_revision")),
        "source_span_cache_key": _text(payload.get("source_span_cache_key")),
        "created_at": payload["created_at"],
        "status": _text(payload.get("status")) or "PLANNED",
        "diagnostics": dict(payload.get("diagnostics") or {}),
    }
    refs = {
        "query_plan": write("query_plan.json", payload.get("query_plan") or {}),
        "candidate_pool": write("candidate_pool.json", payload.get("candidate_pool") or []),
        "selected_corpus": write("selected_corpus.json", payload.get("selected_corpus") or {}),
        "paper_reviews": write("paper_reviews.json", payload.get("paper_reviews") or []),
        "synthesis": write("synthesis.json", payload.get("synthesis") or {}),
        "coverage": write("coverage.json", payload.get("coverage") or {}),
        "metadata": write("metadata.json", artifact_metadata),
    }
    manifest = {
        **payload,
        "artifact_refs": refs,
        "status": _text(payload.get("status")) or "COMPLETED",
        "diagnostics": dict(payload.get("diagnostics") or {}),
    }
    refs["manifest"] = write("manifest.json", manifest)
    return {**payload, "artifact_refs": refs}


def load_sh_retrieval_run(
    *,
    project_id: str,
    sub_hypothesis_id: str,
    run_id: str,
    contract_revision: str = "",
    query_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Load a compatible SH run for interruption-safe local resume.

    Only persisted discovery/review artifacts are reused.  The contract and
    query plan are checked before reuse so a changed V3 declaration cannot
    silently consume an older corpus.
    """

    safe_component = lambda value, fallback: re.sub(
        r"[^A-Za-z0-9._-]+", "_", _text(value)
    ).strip("._-")[:120] or fallback
    base = (
        Path(SCIENCE_DIR)
        / "prepared_evidence"
        / "sh_runs"
        / safe_component(project_id, "unscoped_project")
        / safe_component(sub_hypothesis_id, "unknown_sh")
        / safe_component(run_id, "sh_run")
    )
    manifest_path = base / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None
    if _text(manifest.get("schema_version")) != SH_RETRIEVAL_RUN_SCHEMA_VERSION:
        return None
    if _text(manifest.get("project_id")) != _text(project_id):
        return None
    if _text(manifest.get("sub_hypothesis_id")) != _text(sub_hypothesis_id):
        return None
    expected_revision = _text(contract_revision)
    if expected_revision and _text(manifest.get("contract_revision")) != expected_revision:
        return None
    if isinstance(query_plan, Mapping):
        persisted_plan = manifest.get("query_plan")
        if not isinstance(persisted_plan, Mapping):
            return None
        persisted_fingerprint = sha256(
            json.dumps(persisted_plan, ensure_ascii=False, sort_keys=True, default=str).encode(
                "utf-8", errors="ignore"
            )
        ).hexdigest()
        expected_fingerprint = sha256(
            json.dumps(query_plan, ensure_ascii=False, sort_keys=True, default=str).encode(
                "utf-8", errors="ignore"
            )
        ).hexdigest()
        if persisted_fingerprint != expected_fingerprint:
            return None
    refs = manifest.get("artifact_refs") if isinstance(manifest.get("artifact_refs"), Mapping) else {}
    loaded = dict(manifest)
    for key in ("candidate_pool", "selected_corpus", "paper_reviews", "synthesis", "coverage"):
        path_value = refs.get(key)
        if not path_value:
            continue
        try:
            value = json.loads(Path(str(path_value)).read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            continue
        loaded[key] = value
    loaded["resume_status"] = "COMPATIBLE_LOCAL_ARTIFACTS_LOADED"
    return loaded


def _merge_anchor_groups(scopes: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = defaultdict(list)
    for scope in scopes:
        groups = scope.get("scope_anchor_groups")
        if not isinstance(groups, Mapping):
            continue
        for group, values in groups.items():
            if isinstance(values, (list, tuple, set)):
                merged[str(group)].extend(values)
            elif values not in (None, ""):
                merged[str(group)].append(values)
    return {group: _unique(values) for group, values in sorted(merged.items()) if _unique(values)}


def build_sh_candidate_scope(
    contract: Mapping[str, Any],
    task_scopes: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a broad metadata scope for one SH discovery pass.

    This scope is only used before full-text review.  Each paper is still
    reviewed against its task-local scope before any assertion can be admitted.
    """

    scopes = [scope for scope in task_scopes if isinstance(scope, Mapping)]
    contract_id = _text(contract.get("contract_id"))
    contract_hash = _text(
        contract.get("declaration_hash")
        or contract.get("contract_revision")
        or contract.get("contract_hash")
    )
    slot_anchors = _unique(
        value
        for scope in scopes
        for value in (scope.get("slot_anchors") or [])
    )
    focus_axes = _unique(
        value
        for scope in scopes
        for value in (scope.get("slot_focus_axes") or [])
    )
    exclusions = _unique(
        value
        for scope in scopes
        for value in (scope.get("explicit_exclusion_terms") or [])
    )
    query_ast_items = [
        {
            "role": "slot_requirement",
            "terms": [anchor],
        }
        for anchor in slot_anchors
    ]
    return {
        "schema_version": "slot_candidate_scope_v3",
        "scope_kind": "SH_DISCOVERY",
        "research_question_contract_id": contract_id,
        "research_question_contract_hash": contract_hash,
        "sub_hypothesis_id": _text(contract.get("sub_hypothesis_id")),
        "evidence_slot": "SH_DISCOVERY",
        "query_branch": "SH_DISCOVERY",
        "scope_anchor_groups": _merge_anchor_groups(scopes),
        "slot_focus_axes": focus_axes,
        "slot_anchors": slot_anchors,
        "explicit_exclusion_terms": exclusions,
        "query_blueprint_v3": {
            "schema_version": "query_blueprint_v3",
            "query_ast_v3": {
                "all_of": query_ast_items,
                "exclusions": exclusions,
            },
        },
        "task_scope_ids": _unique(
            scope.get("research_question_task_id")
            for scope in scopes
        ),
    }


def build_sh_query_plan(
    tasks: Iterable[Mapping[str, Any]],
    *,
    project_id: str,
    sub_hypothesis_id: str,
    contract: Mapping[str, Any],
    groupchat_id: str = "",
    run_id: str = "",
    wave_id: str = "",
) -> dict[str, Any]:
    """Compile all non-foundational V3 tasks into one SH discovery plan."""

    branches: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, Mapping):
            continue
        mode = _text(task.get("query_mode")).upper()
        if mode == "FOUNDATIONAL_CONTEXT":
            continue
        spec = task.get("retrieval_spec_v3")
        if not isinstance(spec, Mapping):
            continue
        query = _text(spec.get("provider_query"))
        branch = _text(
            spec.get("query_branch")
            or task.get("query_branch")
            or f"{sub_hypothesis_id}:{task.get('slot') or task.get('requirement') or task.get('task_id')}"
        )
        if not query or not branch:
            continue
        branches.append({
            **dict(spec),
            "project_id": project_id,
            "sub_hypothesis_id": sub_hypothesis_id,
            "groupchat_id": groupchat_id,
            "run_id": run_id,
            "retrieval_wave_id": wave_id,
            "query": query,
            "branch": branch,
            "query_branch": branch,
            "query_branch_id": branch,
            "query_branch_role": mode,
            "research_question_task_id": _text(task.get("task_id")),
            "evidence_slot": _text(task.get("slot") or task.get("requirement")),
            "research_question_contract_id": _text(contract.get("contract_id")),
            "research_question_contract_hash": _text(
                contract.get("declaration_hash")
                or contract.get("contract_revision")
            ),
            "retrieval_obligation_v3": (
                dict(task.get("retrieval_obligation_v3") or {})
                if isinstance(task.get("retrieval_obligation_v3"), Mapping)
                else {}
            ),
            "retrieval_obligations_v3": [
                dict(item)
                for item in task.get("retrieval_obligations_v3", [])
                if isinstance(item, Mapping)
            ],
            "retrieval_work_item_v3": (
                dict(task.get("retrieval_work_item_v3") or {})
                if isinstance(task.get("retrieval_work_item_v3"), Mapping)
                else {}
            ),
            "sh_discovery_batch": True,
        })
    return {
        "schema_version": SH_RETRIEVAL_PLAN_SCHEMA_VERSION,
        "project_id": project_id,
        "sub_hypothesis_id": sub_hypothesis_id,
        "research_question_contract_id": _text(contract.get("contract_id")),
        "research_question_contract_hash": _text(
            contract.get("declaration_hash")
            or contract.get("contract_revision")
        ),
        "retrieval_wave_id": wave_id,
        "branches": branches,
        "branch_count": len(branches),
        "query_dispatch_policy": "ONE_SH_DISCOVERY_BATCH_ALL_NON_FOUNDATIONAL_BRANCHES",
    }


def select_sh_paper_quota(
    candidates: Iterable[Mapping[str, Any]],
    *,
    quotas: Mapping[str, Any] | None = None,
    key_fn: Callable[[Mapping[str, Any]], str] | None = None,
) -> dict[str, Any]:
    """Select one deterministic, layered SH corpus without duplicate papers."""

    effective_quotas = dict(DEFAULT_SH_LAYER_QUOTAS)
    if isinstance(quotas, Mapping):
        for layer, value in quotas.items():
            try:
                effective_quotas[str(layer)] = max(0, int(value or 0))
            except (TypeError, ValueError):
                continue
    key_builder = key_fn or _stable_candidate_key
    deduplicated: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        item = dict(candidate)
        key = _text(key_builder(item))
        if not key:
            continue
        if key in deduplicated:
            duplicate_count += 1
            existing = deduplicated[key]
            branches = _unique([
                *(existing.get("matched_query_branches") or []),
                *(item.get("matched_query_branches") or []),
                existing.get("query_branch"),
                item.get("query_branch"),
            ])
            if branches:
                existing["matched_query_branches"] = branches
            continue
        item["sh_candidate_key"] = key
        initial_branch = _text(item.get("query_branch") or item.get("branch_id"))
        if initial_branch and not item.get("matched_query_branches"):
            item["matched_query_branches"] = [initial_branch]
        deduplicated[key] = item

    by_layer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in deduplicated.values():
        layer = _text(item.get("stratified_layer") or item.get("layer") or "L4_regular")
        by_layer[layer].append(item)
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    for layer, limit in effective_quotas.items():
        ranked = sorted(
            by_layer.get(layer, []),
            key=lambda item: (
                -float(item.get("candidate_score") or item.get("relevance_score") or 0.0),
                -int(item.get("citation_count") or 0),
                _text(item.get("title")).casefold(),
                _text(item.get("sh_candidate_key")),
            ),
        )
        for index, item in enumerate(ranked):
            if index < limit:
                selected_keys.add(_text(item.get("sh_candidate_key")))
                selected.append({
                    **item,
                    "selected": True,
                    "sh_selection_status": "SELECTED",
                    "sh_selection_layer": layer,
                    "sh_selection_rank": index + 1,
                })
            else:
                rejected.append({
                    "selected": False,
                    "sh_candidate_key": _text(item.get("sh_candidate_key")),
                    "paper_id": _text(item.get("paper_id")),
                    "layer": layer,
                    "reason_code": "QUOTA_NOT_SELECTED",
                })
    for key, item in deduplicated.items():
        if key not in selected_keys and not any(
            _text(row.get("sh_candidate_key")) == key for row in rejected
        ):
            rejected.append({
                "selected": False,
                "sh_candidate_key": key,
                "paper_id": _text(item.get("paper_id")),
                "layer": _text(item.get("stratified_layer") or item.get("layer") or "L4_regular"),
                "reason_code": "QUOTA_NOT_SELECTED",
            })
    return {
        "schema_version": SH_CORPUS_SELECTION_SCHEMA_VERSION,
        "quotas": effective_quotas,
        "input_count": sum(len(items) for items in by_layer.values()),
        "deduplicated_count": len(deduplicated),
        "duplicate_count": duplicate_count,
        "selected_count": len(selected),
        "selected": selected,
        "rejected": rejected,
        "selected_by_layer": {
            layer: sum(1 for item in selected if item.get("sh_selection_layer") == layer)
            for layer in effective_quotas
        },
    }


def unresolved_sh_obligations(
    slot_coverage: Mapping[str, Any] | None,
    *,
    required_slots: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Return only slot-level gaps that justify an additional retrieval wave."""

    coverage = slot_coverage if isinstance(slot_coverage, Mapping) else {}
    obligations: list[dict[str, Any]] = []
    for slot in _unique(required_slots):
        entry = coverage.get(slot)
        if not isinstance(entry, Mapping):
            obligations.append({"slot_id": slot, "reason_code": "SLOT_NOT_EVALUATED"})
            continue
        verdict = _text(entry.get("policy_verdict") or entry.get("slot_status")).upper()
        if verdict in {"SATISFIED", "SATISFIED_BY_NEW_EVIDENCE", "SATISFIED_BY_REUSE"}:
            continue
        obligations.append({
            "slot_id": slot,
            "reason_code": "SLOT_COVERAGE_INCOMPLETE",
            "policy_verdict": verdict,
            "missing_requirements": list(entry.get("missing_policy_requirements") or []),
        })
    return obligations
