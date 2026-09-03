"""Whole-document quality scoring and bounded revision for Research Plan Author."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
import re
from typing import Any

from src.agents.survey_agent.modules.pe import EVAL_CRITERIA

from .latex_safety import LatexSafetyError, split_equation_content
from .llm_json import call_required_json
from .markdown_renderer import render_quality_review_markdown, render_research_plan_markdown
from .semantic_validator import validate_composed_research_plan


AUTHOR_DOCUMENT_QUALITY_SCHEMA_VERSION = "research_plan_author_document_quality_v1"
AUTHOR_DOCUMENT_REVISION_SCHEMA_VERSION = "research_plan_author_document_revision_v1"
_RUBRIC_DIMENSIONS = (
    "Synthesis Quality",
    "Organization",
    "Readability",
    "Academic Rigor",
    "Clarity",
    "Coherence",
    "Comprehensiveness",
    "Critical Analysis",
    "Novelty and Insights",
    "Future Directions",
)
_SPECIAL_RUBRICS = {
    "mathematics_theory": (
        (
            "Theory Auditability",
            "Assess whether the manuscript turns its central proposal into an auditable chain of labeled definitions, assumptions, lemmas, equations, proof obligations, and explicit dependency links. Reward a reader being able to identify what must be checked next; do not require a completed proof.",
            0.35,
        ),
        (
            "Boundary and Status Discipline",
            "Assess whether candidate, unverified, expected-not-observed, no-information, and review-required statuses are precise and consistently attached to the relevant mathematical claims. Reward disciplined scope management that still advances the argument rather than repeatedly restating uncertainty.",
            0.25,
        ),
        (
            "Falsifiability and Decision Completeness",
            "Assess whether falsifiers, counterexample criteria, proof-obligation outcomes, no-information branches, and next actions close the proposal's decision logic. Reward concrete pre-registered responses to each meaningful branch.",
            0.25,
        ),
        (
            "Energy-Condition Defense",
            "Assess whether the manuscript carefully distinguishes NEC, ANEC/AANEC, null convergence or Ricci contraction, SEC, and independently assumed focusing conditions, including the limits of their implications. Reward accurate boundary defense rather than decorative terminology.",
            0.15,
        ),
    ),
    "computational_digital": (
        (
            "Computational Methodological Strength",
            "Assess task definition, data split, baselines, ablations, robustness, metrics, and reproducibility as one coherent computational plan.",
            1.0,
        ),
    ),
    "materials_chemical": (
        (
            "Mechanistic and Characterization Strength",
            "Assess the connection among mechanism, material variables, characterization, controls, design of experiments, and reproducibility.",
            1.0,
        ),
    ),
    "engineering_energy": (
        (
            "System-Boundary and Validation Strength",
            "Assess system boundaries, constraints, metrics, failure modes, layered validation, and engineering implementability.",
            1.0,
        ),
    ),
    "earth_environment_agro": (
        (
            "Spatiotemporal and Causal Design Strength",
            "Assess spatial and temporal units, sampling frame, covariates, confounding, causal interpretation, and extrapolation limits.",
            1.0,
        ),
    ),
    "life_veterinary": (
        (
            "Experimental Controls and Biological Validity",
            "Assess model choice, controls, repeats, assays, bias control, and biological interpretation boundaries.",
            1.0,
        ),
    ),
    "clinical_health": (
        (
            "Clinical Validity, Safety, and Governance Strength",
            "Assess PICO, endpoints, bias control, clinical relevance, safety, ethics, governance, and implementability.",
            1.0,
        ),
    ),
}
_VISIBLE_CITATION_TOKEN = re.compile(r"\[@[^\]]+\]")
_EVALUATION_MARKER = re.compile(r"<!--\s*author:section=[^>]+-->", flags=re.IGNORECASE)
_REVIEW_PRESENTATION_PREFIX = re.compile(
    r"\*\*(?:"
    r"Definition\.|"
    r"Proposition \((?:proposed|Candidate)\)\.|"
    r"Planned protocol\.|"
    r"Conditional outcome branch\.|"
    r"Human-review checklist\.|"
    r"Lemma(?: [^*]+)?|"
    r"Proof Obligation(?: [^*]+)?|"
    r"Equation \[[^*]+\]\.|"
    r"Pre-registered Branch \([^*]+\)\.|"
    r"Decision Status: No-information\."
    r")\*\*\s*",
    flags=re.IGNORECASE,
)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _setting_or_default(settings: Mapping[str, Any], key: str, default: Any) -> Any:
    """Preserve explicit falsy settings such as zero iterations or zero weight."""

    value = settings.get(key)
    return default if value is None else value


def _scorecard(
    scores: Mapping[str, int],
    special_scores: Mapping[str, int],
    special_weight: float,
    *,
    special_dimension_weights: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    core = (scores["Synthesis Quality"] + scores["Organization"]) / 2
    writing = (scores["Readability"] + scores["Academic Rigor"] + scores["Clarity"] + scores["Coherence"]) / 4
    depth = (scores["Comprehensiveness"] + scores["Critical Analysis"] + scores["Novelty and Insights"] + scores["Future Directions"]) / 4
    total = 0.33 * core + 0.33 * writing + 0.34 * depth
    normalized_special_weights = {
        dimension: max(0.0, float((special_dimension_weights or {}).get(dimension, 1.0)))
        for dimension in special_scores
    }
    special_weight_total = sum(normalized_special_weights.values())
    special = (
        sum(special_scores[dimension] * normalized_special_weights[dimension] for dimension in special_scores)
        / special_weight_total
        if special_scores and special_weight_total > 0
        else total
    )
    weight = min(1.0, max(0.0, float(special_weight))) if special_scores else 0.0
    return {
        "dimension_scores": dict(scores),
        "special_dimension_scores": dict(special_scores),
        "special_dimension_weights": normalized_special_weights,
        "core_quality": round(core, 4),
        "writing_quality": round(writing, 4),
        "content_depth": round(depth, 4),
        "total_score": round(total, 4),
        "final_100": round(total * 10, 2),
        "special_score": round(special, 4),
        "selection_score": round((1 - weight) * total + weight * special, 4),
        "special_score_weight": weight,
    }


def _block_lookup(document: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for section in [*(document.get("sections") or []), *(document.get("appendices") or [])]:
        if not isinstance(section, Mapping):
            continue
        section_id = _text(section.get("section_id"))
        for block in section.get("blocks") or []:
            if isinstance(block, Mapping):
                result[(section_id, _text(block.get("block_id")))] = _text(block.get("text"))
    return result


def _claim_lookup(document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _text(claim.get("claim_id")): dict(claim)
        for claim in document.get("claim_provenance") or []
        if isinstance(claim, Mapping) and _text(claim.get("claim_id"))
    }


def _normalise_evidence_text(value: object) -> str:
    """Compare Judge excerpts with the raw block after removing review-only decoration."""

    text = _EVALUATION_MARKER.sub("", _text(value))
    text = _VISIBLE_CITATION_TOKEN.sub("", text)
    text = _REVIEW_PRESENTATION_PREFIX.sub("", text)
    return " ".join(text.replace("$$", " ").split())


def _valid_evidence(
    items: object,
    *,
    blocks: Mapping[tuple[str, str], str],
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    if not isinstance(items, list) or not items:
        return None, ["evidence must be a non-empty list"]
    normalized: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, Mapping):
            warnings.append(f"evidence[{index}] must be an object and was discarded")
            continue
        section_id = _text(item.get("section_id"))
        block_id = _text(item.get("block_id"))
        excerpt = _text(item.get("excerpt"))
        assessment = _text(item.get("assessment"))
        block_text = blocks.get((section_id, block_id), "")
        normalized_excerpt = _normalise_evidence_text(excerpt)
        normalized_block = _normalise_evidence_text(block_text)
        missing = [
            field
            for field, value in {
                "section_id": section_id,
                "block_id": block_id,
                "excerpt": excerpt,
                "assessment": assessment,
            }.items()
            if not value
        ]
        if missing:
            warnings.append(f"evidence[{index}] is missing {', '.join(missing)} and was discarded")
            continue
        if (section_id, block_id) not in blocks:
            warnings.append(f"evidence[{index}] references an unknown section_id/block_id and was discarded")
            continue
        if not normalized_excerpt:
            warnings.append(f"evidence[{index}].excerpt has no retained manuscript text and was discarded")
            continue
        if normalized_excerpt not in normalized_block:
            warnings.append(f"evidence[{index}].excerpt is not found in its referenced block and was discarded")
            continue
        if len(normalized) < 3:
            normalized.append({"section_id": section_id, "block_id": block_id, "excerpt": excerpt, "assessment": assessment})
    if not normalized:
        return None, [*warnings, "no evidence entry could be reliably located in the manuscript"]
    return normalized, warnings


def _valid_references(
    items: object,
    *,
    blocks: Mapping[tuple[str, str], str],
    field_name: str,
) -> tuple[list[dict[str, str]], list[str]]:
    if not isinstance(items, list):
        return [], [f"{field_name} must be a list; location is pending review"]
    normalized: list[dict[str, str]] = []
    warnings: list[str] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, Mapping):
            warnings.append(f"{field_name}[{index}] must be an object and was discarded")
            continue
        section_id = _text(item.get("section_id"))
        block_id = _text(item.get("block_id"))
        if (section_id, block_id) not in blocks:
            warnings.append(f"{field_name}[{index}] references an unknown section_id/block_id and was discarded")
            continue
        if len(normalized) < 3:
            normalized.append({"section_id": section_id, "block_id": block_id})
    return normalized, warnings


def _response_summary(response: object) -> dict[str, Any]:
    """Keep structural Judge diagnostics without persisting model prose or prompts."""

    if not isinstance(response, Mapping):
        return {"response_type": type(response).__name__}
    strength = _mapping(response.get("maximum_strength"))
    return {
        "response_type": "object",
        "top_level_keys": sorted(_text(key) for key in response.keys())[:20],
        "dimension": _text(response.get("dimension")),
        "score": response.get("score") if isinstance(response.get("score"), (str, int, float, bool)) else type(response.get("score")).__name__,
        "rationale_present": bool(_text(response.get("rationale"))),
        "evidence_count": len(response.get("evidence")) if isinstance(response.get("evidence"), list) else None,
        "maximum_strength_present": strength.get("present") if isinstance(strength.get("present"), bool) else None,
        "major_weakness_count": len(response.get("major_weaknesses")) if isinstance(response.get("major_weaknesses"), list) else None,
        "polish_direction_count": len(response.get("polish_directions")) if isinstance(response.get("polish_directions"), list) else None,
    }


def _invalid_report(category: str, *errors: str) -> tuple[None, dict[str, Any]]:
    return None, {
        "failure_category": category,
        "validation_errors": [error for error in errors if error],
    }


def _parse_dimension_report(
    response: object,
    *,
    dimension: str,
    document: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not isinstance(response, Mapping):
        return _invalid_report("response_shape", "Judge response must be a JSON object")
    returned_dimension = _text(response.get("dimension"))
    if returned_dimension != dimension:
        return _invalid_report(
            "dimension_mismatch",
            f"response.dimension must equal the requested dimension '{dimension}'",
        )
    score = response.get("score")
    if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 10:
        return _invalid_report("score_contract", "response.score must be an integer from 1 through 10")
    rationale = _text(response.get("rationale"))
    if not rationale:
        return _invalid_report("rationale_contract", "response.rationale must be non-empty")
    blocks = _block_lookup(document)
    evidence, evidence_errors = _valid_evidence(response.get("evidence"), blocks=blocks)
    if evidence is None:
        return _invalid_report("grounding_contract", *evidence_errors)
    grounding_warnings = list(evidence_errors)
    strength = _mapping(response.get("maximum_strength"))
    if bool(strength.get("present")):
        strength_refs, strength_errors = _valid_references(
            strength.get("evidence_refs"),
            blocks=blocks,
            field_name="maximum_strength.evidence_refs",
        )
        if not _text(strength.get("description")):
            return _invalid_report("strength_contract", "maximum_strength.description must be non-empty when present=true")
        grounding_warnings.extend(strength_errors)
        strength = {
            "present": True,
            "description": _text(strength.get("description")),
            "evidence_refs": strength_refs,
            "location_status": "located" if strength_refs else "pending_review",
        }
    else:
        strength = {"present": False, "description": "", "evidence_refs": [], "location_status": "not_applicable"}
    weaknesses: list[dict[str, Any]] = []
    raw_weaknesses = response.get("major_weaknesses")
    if not isinstance(raw_weaknesses, list):
        return _invalid_report("weakness_contract", "major_weaknesses must be a list")
    for index, weakness in enumerate(raw_weaknesses[:3], start=1):
        if not isinstance(weakness, Mapping):
            return _invalid_report("weakness_contract", f"major_weaknesses[{index}] must be an object")
        refs, reference_errors = _valid_references(
            weakness.get("evidence_refs"),
            blocks=blocks,
            field_name=f"major_weaknesses[{index}].evidence_refs",
        )
        missing = [
            field
            for field, value in {
                "description": _text(weakness.get("description")),
                "impact": _text(weakness.get("impact")),
                "repair_direction": _text(weakness.get("repair_direction")),
            }.items()
            if not value
        ]
        if missing:
            return _invalid_report("weakness_contract", f"major_weaknesses[{index}] is missing {', '.join(missing)}")
        grounding_warnings.extend(reference_errors)
        weaknesses.append({
            "severity": _text(weakness.get("severity")) or "major",
            "description": _text(weakness.get("description")),
            "impact": _text(weakness.get("impact")),
            "repair_direction": _text(weakness.get("repair_direction")),
            "evidence_refs": refs,
            "location_status": "located" if refs else "pending_review",
        })
    directions: list[dict[str, Any]] = []
    raw_directions = response.get("polish_directions")
    if not isinstance(raw_directions, list) or not raw_directions:
        return _invalid_report("polish_contract", "polish_directions must be a non-empty list")
    for index, direction in enumerate(raw_directions[:3], start=1):
        if not isinstance(direction, Mapping) or not _text(direction.get("direction")):
            return _invalid_report("polish_contract", f"polish_directions[{index}].direction must be non-empty")
        try:
            priority = int(direction.get("priority") or len(directions) + 1)
        except (TypeError, ValueError):
            return _invalid_report("polish_contract", f"polish_directions[{index}].priority must be an integer")
        directions.append({
            "priority": priority,
            "direction": _text(direction.get("direction")),
            "expected_gain": _text(direction.get("expected_gain")),
        })
    return {
        "dimension": dimension,
        "score": score,
        "rationale": rationale,
        "evidence": evidence,
        "maximum_strength": strength,
        "major_weaknesses": weaknesses,
        "polish_directions": directions,
        "grounding_warnings": grounding_warnings,
    }, {"grounding_warnings": grounding_warnings}


def _judge_prompt(*, dimension: str, description: str, manuscript: str) -> str:
    payload = {
        "operation": "research_plan_document_quality_dimension",
        "dimension": dimension,
        "criterion_description": description,
        "manuscript_markdown": manuscript,
        "output_contract": {
            "dimension": dimension,
            "score": "integer 1..10",
            "rationale": "why this score is warranted",
            "evidence": [{"section_id": "existing marker", "block_id": "existing marker", "excerpt": "short phrase copied from the raw block text only", "assessment": "why it matters"}],
            "maximum_strength": {"present": "boolean", "description": "if present", "evidence_refs": [{"section_id": "", "block_id": ""}]},
            "major_weaknesses": [{"severity": "major or moderate", "description": "", "impact": "", "repair_direction": "", "evidence_refs": [{"section_id": "", "block_id": ""}]}],
            "polish_directions": [{"priority": 1, "direction": "specific revision", "expected_gain": "affected quality"}],
        },
    }
    return """You are a senior academic reviewer scoring one dimension of a complete research-plan manuscript. Read the full manuscript and score the requested dimension from 1 to 10 using the supplied criterion. Give a concrete, constructive assessment grounded in the manuscript itself. Identify its strongest contribution when one is present, identify major weaknesses when present, and give practical directions for a stronger next draft. The manuscript is a proposal: reward clear conditional reasoning, honest scope, and useful proof or validation obligations rather than demanding completed experiments or completed proofs. Use the invisible author markers only to locate evidence; never treat them as visible prose. For every evidence excerpt, copy a short phrase from the raw block text, excluding Markdown wrappers, generated citation suffixes, and marker comments. Return exactly one JSON object.\n\nINPUT_JSON:\n""" + json.dumps(payload, ensure_ascii=False)


def _revision_context(
    preparation: Mapping[str, Any],
    source_registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Expose the complete frozen upstream knowledge base to the reviser.

    This is an authoring context, not a section-local source permission list.
    The original Author preparation already owns its provenance; retaining the
    full context lets the reviser make substantive cross-agent connections.
    """

    knowledge_base = _mapping(source_registry.get("authoring_knowledge_base"))
    if knowledge_base:
        return deepcopy(knowledge_base)
    context = _mapping(_mapping(preparation.get("source_bundle")).get("author_context"))
    return {
        "source_catalog": {
            "citation_registry": deepcopy(list(source_registry.get("citation_registry") or [])),
            "evidence_cards_by_id": deepcopy(_mapping(source_registry.get("evidence_cards_by_id"))),
        },
        "upstream_artifacts": {
            "selected_direction": context.get("selected_direction"),
            "research_design": context.get("research_design"),
            "hypothesis_mapping": context.get("hypothesis_mapping"),
            "formal_reasoning": context.get("formal_reasoning"),
            "counterexample_analysis": context.get("counterexample_analysis"),
            "outcome_branches": context.get("outcome_branches"),
            "reasoning_context": context.get("reasoning_context"),
            "variables_and_operationalization": context.get("variables_and_operationalization"),
            "idea_evolution": _mapping(_mapping(preparation.get("source_bundle")).get("idea_evolution")),
            "survey_binding": _mapping(_mapping(preparation.get("source_bundle")).get("survey_binding")),
        },
        "unknown_items": deepcopy(list(source_registry.get("unknown_items") or [])),
        "review_items": deepcopy(list(source_registry.get("review_items") or [])),
    }


def _editable_block_context(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    claims = _claim_lookup(document)
    editable: list[dict[str, Any]] = []
    for section in [*(document.get("sections") or []), *(document.get("appendices") or [])]:
        if not isinstance(section, Mapping):
            continue
        section_id = _text(section.get("section_id"))
        for block in section.get("blocks") or []:
            if not isinstance(block, Mapping):
                continue
            claim_ids = [_text(claim_id) for claim_id in block.get("claim_ids") or [] if _text(claim_id)]
            editable.append(
                {
                    "section_id": section_id,
                    "block_id": _text(block.get("block_id")),
                    "claim_ids": claim_ids,
                    "supported_claims": [
                        {
                            "claim_id": claim_id,
                            "claim_kind": _text(claim.get("claim_kind")),
                            "statement": _text(claim.get("statement")),
                            "qualification": _text(claim.get("qualification")),
                        }
                        for claim_id in claim_ids
                        if isinstance((claim := claims.get(claim_id)), Mapping)
                    ],
                }
            )
    return editable


def _revision_prompt(
    *,
    document: Mapping[str, Any],
    reports: list[Mapping[str, Any]],
    preparation: Mapping[str, Any],
    source_registry: Mapping[str, Any],
    max_edits: int,
    partial_score_recovery: bool = False,
) -> str:
    editable_blocks = _editable_block_context(document)
    abstract = _mapping(document.get("abstract"))
    payload = {
        "operation": "research_plan_document_quality_revision",
        "manuscript_markdown": render_quality_review_markdown(document),
        "quality_reports": reports,
        "available_research_context": _revision_context(preparation, source_registry),
        "editable_blocks": editable_blocks,
        "abstract_claim_ids": [_text(claim_id) for claim_id in abstract.get("claim_ids") or [] if _text(claim_id)],
        "max_block_edits": max_edits,
        "output_contract": {
            "schema_version": AUTHOR_DOCUMENT_REVISION_SCHEMA_VERSION,
            "revision_summary": "short summary",
            "abstract_text": "optional complete replacement",
            "abstract_supporting_claim_ids": ["required only when abstract_text is supplied; choose existing abstract_claim_ids"],
            "block_edits": [{"section_id": "existing", "block_id": "existing", "text": "complete replacement", "supporting_claim_ids": ["one or more claim_ids already attached to this block"], "heading": "optional replacement"}],
        },
    }
    recovery_instruction = (
        "A subset of judge reports was unavailable for this draft. Use the available reports to make one focused recovery revision; "
        "the revised draft must earn a complete scorecard before it can compete for selection. "
        if partial_score_recovery
        else ""
    )
    return """You are revising a complete academic research plan after a detailed quality review. Strengthen the argument, depth, structure, mathematical explanation, transitions, and precision where the reports identify useful opportunities. Preserve the manuscript's strongest contributions. Work freely with the supplied research context, but keep the plan honest about what is proposed, conditional, or unresolved. For a mathematics-theory manuscript, make its reasoning auditable: use supplied candidates, proof obligations, falsifiers, no-information branches, and next actions to close the decision logic. Prefer a specific lemma, criterion, implication, or response over repeating that a dependency is undefined or needs confirmation. Do not invent missing definitions or completed proofs merely to improve a score. Return a compact set of high-value complete block replacements; do not rewrite blocks that do not benefit from revision. Existing citations, claim identifiers, and section structure are maintained by the Author backend, so focus on stronger scholarly prose and mathematical or methodological exposition. Every replacement must identify the already attached claims that support it; this preserves the proposal status of the underlying material while allowing deeper synthesis. Do not state a proposed or unverified result as completed, proved, observed, or universal. """ + recovery_instruction + """Return exactly one JSON object.\n\nINPUT_JSON:\n""" + json.dumps(payload, ensure_ascii=False)


def _apply_patch(document: Mapping[str, Any], patch: object, *, max_edits: int) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(patch, Mapping) or _text(patch.get("schema_version")) != AUTHOR_DOCUMENT_REVISION_SCHEMA_VERSION:
        return None, "revision response does not match the document revision contract"
    edits = patch.get("block_edits")
    if not isinstance(edits, list) or len(edits) > max_edits:
        return None, "revision has an invalid number of block edits"
    candidate = deepcopy(dict(document))
    block_lookup = {
        (_text(section.get("section_id")), _text(block.get("block_id"))): block
        for section in [*(candidate.get("sections") or []), *(candidate.get("appendices") or [])]
        if isinstance(section, dict)
        for block in section.get("blocks") or []
        if isinstance(block, dict)
    }
    seen: set[tuple[str, str]] = set()
    for edit in edits:
        if not isinstance(edit, Mapping):
            return None, "revision edit must be an object"
        key = (_text(edit.get("section_id")), _text(edit.get("block_id")))
        text = _text(edit.get("text"))
        if key not in block_lookup or key in seen or not text:
            return None, "revision edit targets an unknown, repeated, or empty block"
        if _VISIBLE_CITATION_TOKEN.search(text):
            return None, "revision may not add inline citation tokens; citations are derived by the Author backend"
        seen.add(key)
        block = block_lookup[key]
        supporting_claim_ids = [_text(claim_id) for claim_id in edit.get("supporting_claim_ids") or [] if _text(claim_id)]
        existing_claim_ids = {_text(claim_id) for claim_id in block.get("claim_ids") or [] if _text(claim_id)}
        if not supporting_claim_ids or set(supporting_claim_ids) - existing_claim_ids:
            return None, "revision edit must identify existing block claim_ids that support its replacement"
        block["text"] = text
        if "heading" in edit:
            block["heading"] = _text(edit.get("heading"))
    abstract_text = _text(patch.get("abstract_text"))
    if abstract_text:
        abstract = _mapping(candidate.get("abstract"))
        supporting_claim_ids = [_text(claim_id) for claim_id in patch.get("abstract_supporting_claim_ids") or [] if _text(claim_id)]
        abstract_claim_ids = {_text(claim_id) for claim_id in abstract.get("claim_ids") or [] if _text(claim_id)}
        if not supporting_claim_ids or set(supporting_claim_ids) - abstract_claim_ids:
            return None, "abstract revision must identify existing abstract claim_ids that support its replacement"
        abstract["text"] = abstract_text
        candidate["abstract"] = abstract
    if not edits and not abstract_text:
        return None, "revision contains no changes"
    for block in block_lookup.values():
        if _text(block.get("kind")) == "equation":
            try:
                fragments = split_equation_content(
                    block.get("text"),
                    label=f"quality revision block {_text(block.get('block_id'))}",
                )
                if not any(kind == "equation" for kind, _ in fragments):
                    raise LatexSafetyError(
                        f"quality revision block {_text(block.get('block_id'))} contains no valid mathematical expression"
                    )
            except LatexSafetyError as error:
                return None, str(error)
    return candidate, _text(patch.get("revision_summary"))


def optimize_research_plan_document(
    document: Mapping[str, Any],
    *,
    preparation: Mapping[str, Any],
    routing: Mapping[str, Any],
    source_registry: Mapping[str, Any],
    quality_config: Mapping[str, Any] | None,
    judge_llm_call: Callable[..., object] | None,
    revision_llm_call: Callable[..., object] | None,
    logger: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Score bounded document candidates and retain the best valid version."""

    settings = _mapping(quality_config)
    enabled = _as_bool(settings.get("enabled"), True)
    special_weight = float(_setting_or_default(settings, "special_score_weight", 0.25))
    partial_score_min_valid_dimensions = max(
        1,
        int(_setting_or_default(settings, "partial_score_min_valid_dimensions", 8)),
    )
    max_iterations = max(0, int(_setting_or_default(settings, "max_iterations", 2)))
    max_edits = max(1, int(_setting_or_default(settings, "max_revision_block_edits", 14)))
    concurrency = max(1, int(_setting_or_default(settings, "score_concurrency", 3)))
    judge_retries = max(1, int(_setting_or_default(settings, "judge_max_retries", 3)))
    template_family = _text(routing.get("template_family"))
    special = _SPECIAL_RUBRICS.get(template_family)
    effective_special_weight = special_weight if special is not None else 0.0
    special_dimension_weights = {
        dimension: weight
        for dimension, _description, weight in special or ()
    }
    audit: dict[str, Any] = {
        "schema_version": AUTHOR_DOCUMENT_QUALITY_SCHEMA_VERSION,
        "enabled": enabled,
        "model": _text(settings.get("model")),
        "template_family": template_family,
        "general_score_weight": round(1 - effective_special_weight, 4),
        "special_score_weight": round(effective_special_weight, 4),
        "special_dimensions": [
            {"dimension": dimension, "weight": weight}
            for dimension, _description, weight in special or ()
        ],
        "partial_score_min_valid_dimensions": partial_score_min_valid_dimensions,
        "candidates": [],
        "selected_candidate_index": 0,
        "winning_candidate_index": None,
        "selection_status": "UNRESOLVED",
        "warnings": [],
    }

    def score(candidate: Mapping[str, Any], index: int, parent_index: int | None, summary: str) -> dict[str, Any]:
        record: dict[str, Any] = {
            "candidate_index": index,
            "parent_index": parent_index,
            "revision_summary": summary,
            "markdown": render_research_plan_markdown(candidate),
            "status": "UNSCORED",
            "dimension_reports": [],
            "judge_attempts": [],
            "failed_dimensions": [],
        }
        if not enabled or judge_llm_call is None:
            record["status"] = "SKIPPED"
            return record
        manuscript = render_quality_review_markdown(candidate)
        requested = [(dimension, _text(_mapping(EVAL_CRITERIA.get(dimension)).get("description"))) for dimension in _RUBRIC_DIMENSIONS]
        if special is not None:
            requested.extend(
                (dimension, description)
                for dimension, description, _weight in special
            )
        reports: dict[str, dict[str, Any]] = {}

        def emit_attempt(attempt_record: Mapping[str, Any]) -> None:
            if logger is None:
                return
            level = (
                "WARNING"
                if attempt_record.get("grounding_warnings")
                else "INFO" if attempt_record.get("status") == "VALID" else "WARNING"
            )
            logger.emit(
                "document_quality",
                "dimension_score_attempt",
                level=level,
                status=str(attempt_record.get("status") or "WARNING"),
                candidate_index=index,
                dimension=attempt_record.get("dimension"),
                attempt=attempt_record.get("attempt"),
                failure_category=attempt_record.get("failure_category"),
                validation_errors=attempt_record.get("validation_errors") or [],
                grounding_warnings=attempt_record.get("grounding_warnings") or [],
                response_summary=attempt_record.get("response_summary") or {},
                error_type=attempt_record.get("error_type"),
                failure_detail=attempt_record.get("failure_detail"),
            )

        def judge_dimension(dimension: str, description: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
            attempts: list[dict[str, Any]] = []
            for attempt in range(judge_retries):
                attempt_number = attempt + 1
                try:
                    response = call_required_json(
                        judge_llm_call,
                        _judge_prompt(dimension=dimension, description=description, manuscript=manuscript),
                        stage=f"author_document_quality:{dimension}",
                    )
                    parsed, diagnostic = _parse_dimension_report(response, dimension=dimension, document=candidate)
                    attempt_record: dict[str, Any] = {
                        "dimension": dimension,
                        "attempt": attempt_number,
                        "response_summary": _response_summary(response),
                    }
                    if parsed is not None:
                        attempt_record["status"] = "VALID"
                        grounding_warnings = list(diagnostic.get("grounding_warnings") or [])
                        if grounding_warnings:
                            attempt_record["warning_category"] = "grounding_warning"
                            attempt_record["grounding_warnings"] = grounding_warnings
                        attempts.append(attempt_record)
                        emit_attempt(attempt_record)
                        return parsed, attempts
                    attempt_record.update(
                        {
                            "status": "INVALID",
                            "failure_category": diagnostic.get("failure_category") or "report_contract",
                            "validation_errors": list(diagnostic.get("validation_errors") or []),
                        }
                    )
                except Exception as error:
                    attempt_record = {
                        "dimension": dimension,
                        "attempt": attempt_number,
                        "status": "ERROR",
                        "failure_category": "judge_call_error",
                        "error_type": type(error).__name__,
                        "failure_detail": _text(error)[:400],
                    }
                attempts.append(attempt_record)
                emit_attempt(attempt_record)
            return None, attempts

        judge_attempts: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(concurrency, len(requested))) as executor:
            futures = {
                executor.submit(judge_dimension, dimension, description): dimension
                for dimension, description in requested
            }
            for future in as_completed(futures):
                dimension = futures[future]
                try:
                    parsed, dimension_attempts = future.result()
                except Exception as error:
                    parsed = None
                    dimension_attempts = [{
                        "dimension": dimension,
                        "attempt": 0,
                        "status": "ERROR",
                        "failure_category": "judge_worker_error",
                        "error_type": type(error).__name__,
                        "failure_detail": _text(error)[:400],
                    }]
                    emit_attempt(dimension_attempts[0])
                judge_attempts.extend(dimension_attempts)
                if parsed is None:
                    record["failed_dimensions"].append(dimension)
                    last_attempt = dimension_attempts[-1] if dimension_attempts else {}
                    category = _text(last_attempt.get("failure_category")) or "unknown_failure"
                    audit["warnings"].append(
                        f"candidate {index} judge report for {dimension} was unavailable after "
                        f"{len(dimension_attempts)} attempt(s): {category}"
                    )
                else:
                    reports[dimension] = parsed
        requested_index = {dimension: position for position, (dimension, _description) in enumerate(requested)}
        record["judge_attempts"] = sorted(
            judge_attempts,
            key=lambda attempt: (requested_index.get(_text(attempt.get("dimension")), len(requested)), int(attempt.get("attempt") or 0)),
        )
        record["failed_dimensions"] = [
            dimension for dimension, _description in requested if dimension in set(record["failed_dimensions"])
        ]
        record["dimension_reports"] = [reports[key] for key, _description in requested if key in reports]
        if len(reports) != len(requested):
            record["partial_scorecard"] = {
                "available_dimension_scores": {
                    dimension: reports[dimension]["score"]
                    for dimension, _description in requested
                    if dimension in reports
                },
                "missing_dimensions": list(record["failed_dimensions"]),
                "valid_dimension_count": len(reports),
                "requested_dimension_count": len(requested),
                "complete": False,
            }
            record["status"] = (
                "PARTIALLY_SCORED"
                if len(reports) >= partial_score_min_valid_dimensions
                else "JUDGE_FAILED"
            )
            return record
        ordinary = {dimension: reports[dimension]["score"] for dimension in _RUBRIC_DIMENSIONS}
        special_scores = {
            dimension: reports[dimension]["score"]
            for dimension, _description, _weight in special or ()
        }
        record["scorecard"] = _scorecard(
            ordinary,
            special_scores,
            effective_special_weight,
            special_dimension_weights=special_dimension_weights,
        )
        record["status"] = "SCORED"
        return record

    baseline = deepcopy(dict(document))
    candidates = [score(baseline, 0, None, "Initial composed manuscript")]
    candidate_documents = [baseline]
    if logger is not None:
        logger.emit(
            "document_quality",
            "candidate_scored",
            status=candidates[0]["status"],
            candidate_index=0,
            total_score=_mapping(candidates[0].get("scorecard")).get("total_score"),
            failed_dimension_count=len(candidates[0].get("failed_dimensions") or []),
            failed_dimensions=candidates[0].get("failed_dimensions") or [],
    )
    current = baseline
    current_index = 0
    partial_score_recovery_used = False
    for iteration in range(1, max_iterations + 1):
        current_record = candidates[current_index]
        current_status = _text(current_record.get("status"))
        is_partial_recovery = current_status == "PARTIALLY_SCORED"
        if current_status not in {"SCORED", "PARTIALLY_SCORED"} or revision_llm_call is None:
            break
        if is_partial_recovery and partial_score_recovery_used:
            break
        if is_partial_recovery:
            current_record["partial_score_recovery_attempted"] = True
        try:
            patch = call_required_json(
                revision_llm_call,
                _revision_prompt(
                    document=current,
                    reports=list(current_record["dimension_reports"]),
                    preparation=preparation,
                    source_registry=source_registry,
                    max_edits=max_edits,
                    partial_score_recovery=is_partial_recovery,
                ),
                stage="author_document_quality_revision",
            )
            revised, summary = _apply_patch(current, patch, max_edits=max_edits)
        except Exception as error:
            revised, summary = None, f"revision call failed: {type(error).__name__}"
        if revised is None:
            audit["warnings"].append(f"quality iteration {iteration} discarded: {summary}")
            break
        validation_errors = validate_composed_research_plan(revised, preparation=preparation, routing=routing, source_registry=source_registry)
        if validation_errors:
            audit["warnings"].append(f"quality iteration {iteration} discarded by final validation: {'; '.join(validation_errors)}")
            break
        candidate_index = len(candidates)
        candidate = score(revised, candidate_index, current_index, summary)
        candidates.append(candidate)
        candidate_documents.append(revised)
        if logger is not None:
            logger.emit(
                "document_quality",
                "candidate_scored",
                status=candidate["status"],
                candidate_index=candidate_index,
                parent_index=current_index,
                total_score=_mapping(candidate.get("scorecard")).get("total_score"),
                failed_dimension_count=len(candidate.get("failed_dimensions") or []),
                failed_dimensions=candidate.get("failed_dimensions") or [],
            )
        current = revised
        current_index = candidate_index
        if is_partial_recovery:
            partial_score_recovery_used = True
            break
    scored = [candidate for candidate in candidates if candidate.get("status") == "SCORED"]
    if scored:
        selected = max(scored, key=lambda candidate: (_mapping(candidate.get("scorecard")).get("selection_score", -1), -int(candidate["candidate_index"])))
        selected_index = int(selected["candidate_index"])
        selected_document = candidate_documents[selected_index]
        audit["winning_candidate_index"] = selected_index
        audit["selection_status"] = "COMPLETE_SCORECARD_SELECTED"
    else:
        selected = candidates[0]
        selected_index = 0
        selected_document = baseline
        audit["selection_status"] = (
            "PARTIAL_SCORECARD_RETAINED_AS_FALLBACK"
            if any(candidate.get("status") == "PARTIALLY_SCORED" for candidate in candidates)
            else "NO_COMPLETE_SCORECARD_RETAINED_AS_FALLBACK"
        )
        audit["warnings"].append("no complete quality scorecard was available; retained the initial manuscript without selecting a quality winner")
    audit["candidates"] = candidates
    audit["selected_candidate_index"] = selected_index
    return deepcopy(dict(selected_document)), audit


def render_document_quality_report(audit: Mapping[str, Any]) -> str:
    """Render a human-readable score report without exposing prompts or sources."""

    lines = ["# Research Plan Quality Report"]
    winning_index = audit.get("winning_candidate_index")
    if winning_index is None:
        lines.append(f"- Retained manuscript candidate: {audit.get('selected_candidate_index', 0)} (no quality winner selected)")
    else:
        lines.append(f"- Selected candidate: {winning_index}")
    for candidate in audit.get("candidates") or []:
        if not isinstance(candidate, Mapping):
            continue
        lines.append(f"## Candidate {candidate.get('candidate_index')} — {candidate.get('status')}")
        scorecard = _mapping(candidate.get("scorecard"))
        if scorecard:
            lines.append(f"- Total Score: {scorecard.get('total_score')} / 10")
            lines.append(f"- Selection Score: {scorecard.get('selection_score')} / 10")
            special_weights = _mapping(scorecard.get("special_dimension_weights"))
            if special_weights:
                lines.append(
                    "- Theory/domain score weights: "
                    + ", ".join(f"{dimension}={weight}" for dimension, weight in special_weights.items())
                )
        partial_scorecard = _mapping(candidate.get("partial_scorecard"))
        if partial_scorecard:
            lines.append(
                "- Partial scorecard: "
                + f"{partial_scorecard.get('valid_dimension_count')} of "
                + f"{partial_scorecard.get('requested_dimension_count')} reports were valid; "
                + "this candidate cannot be selected."
            )
            missing_dimensions = partial_scorecard.get("missing_dimensions") or []
            if missing_dimensions:
                lines.append("- Unavailable dimensions: " + ", ".join(_text(item) for item in missing_dimensions))
        failed_attempts = [
            attempt
            for attempt in candidate.get("judge_attempts") or []
            if isinstance(attempt, Mapping) and _text(attempt.get("status")) != "VALID"
        ]
        if failed_attempts:
            lines.append("#### Judge Diagnostics")
            for attempt in failed_attempts:
                detail = "; ".join(_text(error) for error in attempt.get("validation_errors") or [] if _text(error))
                if not detail:
                    detail = _text(attempt.get("failure_detail")) or _text(attempt.get("error_type"))
                lines.append(
                    f"- {attempt.get('dimension')} attempt {attempt.get('attempt')}: "
                    f"{attempt.get('failure_category') or 'unknown_failure'}"
                    + (f" — {detail}" if detail else "")
                )
        for report in candidate.get("dimension_reports") or []:
            if not isinstance(report, Mapping):
                continue
            lines.append(f"### {report.get('dimension')} — {report.get('score')} / 10")
            lines.append(_text(report.get("rationale")))
            for warning in report.get("grounding_warnings") or []:
                if _text(warning):
                    lines.append("**Grounding warning:** " + _text(warning))
            for evidence in report.get("evidence") or []:
                if isinstance(evidence, Mapping):
                    lines.append(
                        "**Grounding:** "
                        + f"{_text(evidence.get('section_id'))}/{_text(evidence.get('block_id'))} — "
                        + _text(evidence.get("assessment"))
                    )
            strength = _mapping(report.get("maximum_strength"))
            if strength.get("present"):
                lines.append("**Maximum strength:** " + _text(strength.get("description")))
                if _text(strength.get("location_status")) == "pending_review":
                    lines.append("**Location:** pending review")
            for weakness in report.get("major_weaknesses") or []:
                if isinstance(weakness, Mapping):
                    lines.append("**Major weakness:** " + _text(weakness.get("description")))
                    if _text(weakness.get("location_status")) == "pending_review":
                        lines.append("**Location:** pending review")
                    lines.append("**Direction:** " + _text(weakness.get("repair_direction")))
            for direction in report.get("polish_directions") or []:
                if isinstance(direction, Mapping):
                    lines.append("**Polish direction:** " + _text(direction.get("direction")))
    return "\n\n".join(line for line in lines if line.strip()) + "\n"


__all__ = [
    "AUTHOR_DOCUMENT_QUALITY_SCHEMA_VERSION",
    "AUTHOR_DOCUMENT_REVISION_SCHEMA_VERSION",
    "optimize_research_plan_document",
    "render_document_quality_report",
]
