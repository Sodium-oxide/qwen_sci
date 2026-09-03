"""LLM-primary paper domain and evidence classification contracts."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Callable, Literal, Mapping, TypedDict

try:
    from ._science_execution_policy import ScienceExecutionPolicy
except ImportError:
    from _science_execution_policy import ScienceExecutionPolicy


PAPER_DOMAIN_ASSESSMENT_VERSION = "paper_domain_assessment_v2"
PAPER_CLASSIFICATION_VERSION = "paper_classification_v1"
PAPER_CLASSIFICATION_PROMPT_REVISION = "paper_classification_v1_1"


class DomainCompatibility(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


class PaperDomainAssessment(TypedDict):
    schema_version: Literal["paper_domain_assessment_v2"]
    status: Literal["CLASSIFIED", "PENDING", "REJECTED_PROTOCOL"]
    primary_domain_id: str
    active_domain_ids: list[str]
    provider_taxonomy_evidence: list[dict[str, str]]
    source_anchors: list[str]
    llm_model_id: str
    confidence: float
    reason_codes: list[str]


class PaperClassification(TypedDict):
    schema_version: Literal["paper_classification_v1"]
    publication_form: str
    evidence_genre: str
    research_design: str
    research_role: str
    retrieval_layer: str
    admission_status: str
    source_anchors: list[str]
    model_id: str
    prompt_revision: str
    status: str
    reason_codes: list[str]


PUBLICATION_FORMS = frozenset({
    "journal_article", "review_article", "book_chapter", "conference_paper",
    "conference_abstract", "thesis", "preprint", "dataset", "report", "unknown",
})
EVIDENCE_GENRES = frozenset({
    "primary_empirical", "primary_measurement", "primary_validation", "theoretical",
    "methodological", "dataset_description", "systematic_review", "narrative_review",
    "contextual_synthesis", "commentary", "unknown",
})
RESEARCH_DESIGNS = frozenset({
    "randomized_experiment", "controlled_experiment", "observational", "simulation",
    "measurement_campaign", "case_study", "review", "theoretical", "unknown",
})
RESEARCH_ROLES = frozenset({
    "CORE_DIRECT", "COMPONENT_SUPPORT", "BOUNDARY", "ADVERSE", "METHOD", "BACKGROUND",
    "OFF_TOPIC", "PENDING",
})

_LOW_INFORMATION_ANCHORS = frozenset({
    "mechanism", "mechanisms", "model", "models", "pathway", "pathways", "response",
    "responses", "system", "systems",
})
_PUBLICATION_FORM_ALIASES = {
    "article": "journal_article",
    "journal-article": "journal_article",
    "journal article": "journal_article",
    "review": "review_article",
    "review-article": "review_article",
    "book-chapter": "book_chapter",
    "book chapter": "book_chapter",
    "proceedings-article": "conference_paper",
    "conference paper": "conference_paper",
    "conference-abstract": "conference_abstract",
    "dissertation": "thesis",
    "posted-content": "preprint",
    "preprint": "preprint",
    "dataset": "dataset",
    "report": "report",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normal(value: Any) -> str:
    return " ".join(_text(value).lower().split())


def _unique(values: Any) -> list[str]:
    output: list[str] = []
    for value in values if isinstance(values, (list, tuple, set)) else [values]:
        text = _text(value)
        if text and text not in output:
            output.append(text)
    return output


def _model_id() -> str:
    try:
        from .config import QWEN_MODEL_ID
    except ImportError:
        from config import QWEN_MODEL_ID
    return _text(QWEN_MODEL_ID)


def _default_llm_call(**kwargs: Any) -> dict[str, Any]:
    try:
        from ._llm import call_llm_json
    except ImportError:
        from _llm import call_llm_json
    return call_llm_json(**kwargs)


def _catalog_keys() -> frozenset[str]:
    try:
        from ._models import RESEARCH_DOMAIN_CATALOG
    except ImportError:
        from _models import RESEARCH_DOMAIN_CATALOG
    return frozenset(str(key) for key in RESEARCH_DOMAIN_CATALOG)


def _flatten_taxonomy_items(value: Any, *, taxonomy: str) -> list[dict[str, str]]:
    values = value if isinstance(value, list) else [value]
    output: list[dict[str, str]] = []
    for item in values:
        if isinstance(item, Mapping):
            label = _text(item.get("display_name") or item.get("name") or item.get("label") or item.get("topic"))
            identifier = _text(item.get("id") or item.get("topic_id") or item.get("concept_id"))
        else:
            label = _text(item)
            identifier = ""
        if label:
            output.append({"taxonomy": taxonomy, "id": identifier, "label": label})
    return output


def provider_taxonomy_evidence(paper: Mapping[str, Any]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for key, taxonomy in (
        ("topics", "openalex"),
        ("concepts", "openalex"),
        ("fieldsOfStudy", "semantic_scholar"),
        ("fields_of_study", "semantic_scholar"),
        ("s2_fields_of_study", "semantic_scholar"),
    ):
        output.extend(_flatten_taxonomy_items(paper.get(key), taxonomy=taxonomy))
    provenance = paper.get("provider_provenance")
    if isinstance(provenance, Mapping):
        output.extend(_flatten_taxonomy_items(provenance.get("topics"), taxonomy="provider"))
        output.extend(_flatten_taxonomy_items(provenance.get("concepts"), taxonomy="provider"))
        output.extend(_flatten_taxonomy_items(provenance.get("fields_of_study"), taxonomy="provider"))
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in output:
        key = (item["taxonomy"], item["id"], item["label"])
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def publication_form_from_metadata(paper: Mapping[str, Any]) -> str:
    raw_types = paper.get("publication_types") or paper.get("publicationTypes") or paper.get("type") or []
    values = raw_types if isinstance(raw_types, (list, tuple, set)) else [raw_types]
    for value in values:
        normalized = _normal(value).replace("_", "-")
        if normalized in _PUBLICATION_FORM_ALIASES:
            return _PUBLICATION_FORM_ALIASES[normalized]
        if normalized.replace("-", "_") in PUBLICATION_FORMS:
            return normalized.replace("-", "_")
    return "unknown"


def _paper_metadata(paper: Mapping[str, Any], candidate_id: str) -> dict[str, Any]:
    taxonomy = provider_taxonomy_evidence(paper)
    return {
        "candidate_id": candidate_id,
        "title": _text(paper.get("title")),
        "abstract": _text(paper.get("abstract")),
        "venue": _text(paper.get("venue")),
        "publication_types": _unique(paper.get("publication_types") or paper.get("publicationTypes") or []),
        "provider_taxonomy": taxonomy,
    }


def _metadata_anchor_corpus(metadata: Mapping[str, Any]) -> str:
    return _normal(" ".join((
        _text(metadata.get("title")),
        _text(metadata.get("abstract")),
        _text(metadata.get("venue")),
        " ".join(_unique(metadata.get("publication_types"))),
        " ".join(_text(item.get("label")) for item in metadata.get("provider_taxonomy", []) if isinstance(item, Mapping)),
    )))


def _pending_domain_assessment(
    taxonomy: list[dict[str, str]],
    *reason_codes: str,
    status: str = "PENDING",
) -> PaperDomainAssessment:
    return {
        "schema_version": PAPER_DOMAIN_ASSESSMENT_VERSION,
        "status": status,
        "primary_domain_id": "",
        "active_domain_ids": [],
        "provider_taxonomy_evidence": taxonomy,
        "source_anchors": [],
        "llm_model_id": _model_id(),
        "confidence": 0.0,
        "reason_codes": list(reason_codes),
    }


def assess_paper_domains(
    papers: list[Mapping[str, Any]],
    policy: ScienceExecutionPolicy,
    *,
    llm_call: Callable[..., dict[str, Any]] | None = None,
) -> list[PaperDomainAssessment]:
    metadata = [_paper_metadata(paper, f"candidate_{index}") for index, paper in enumerate(papers)]
    if not policy.use_llm:
        return [
            _pending_domain_assessment(item["provider_taxonomy"], "LLM_DOMAIN_CLASSIFICATION_DISABLED")
            for item in metadata
        ]
    catalog_keys = sorted(_catalog_keys())
    call = llm_call or _default_llm_call
    try:
        payload = call(
            system=(
                "Classify scientific papers into the supplied closed research-domain catalog. Return JSON only. "
                "Use only title, abstract, venue, publication type, and provider taxonomy. Cite verbatim source anchors."
            ),
            prompt=(
                "Return exactly {\"assessments\":[{\"candidate_id\":...,\"primary_domain_id\":...,"
                "\"active_domain_ids\":[...],\"source_anchors\":[...],\"confidence\":0.0}]}. "
                "A source anchor must occur verbatim in the supplied metadata or provider taxonomy. "
                "Words such as mechanism, model, pathway, response, or system cannot be the sole evidence. "
                f"Allowed domain ids: {json.dumps(catalog_keys)}\nPapers:\n{json.dumps(metadata, ensure_ascii=False)}"
            ),
            max_tokens=max(1200, min(5000, 600 + 420 * len(metadata))),
        )
    except Exception as exc:
        return [
            _pending_domain_assessment(
                item["provider_taxonomy"],
                f"DOMAIN_CLASSIFICATION_PENDING:{type(exc).__name__}",
            )
            for item in metadata
        ]
    raw_assessments = payload.get("assessments")
    if not isinstance(raw_assessments, list):
        return [
            _pending_domain_assessment(
                item["provider_taxonomy"],
                "DOMAIN_CLASSIFICATION_PROTOCOL_INVALID",
                status="REJECTED_PROTOCOL",
            )
            for item in metadata
        ]
    by_id = {
        _text(item.get("candidate_id")): item
        for item in raw_assessments
        if isinstance(item, Mapping) and _text(item.get("candidate_id"))
    }
    output: list[PaperDomainAssessment] = []
    allowed = set(catalog_keys)
    for item in metadata:
        raw = by_id.get(item["candidate_id"])
        if not isinstance(raw, Mapping):
            output.append(_pending_domain_assessment(item["provider_taxonomy"], "DOMAIN_CLASSIFICATION_RESULT_MISSING"))
            continue
        primary = _text(raw.get("primary_domain_id"))
        active = _unique(raw.get("active_domain_ids"))
        anchors = _unique(raw.get("source_anchors"))
        corpus = _metadata_anchor_corpus(item)
        reason_codes: list[str] = []
        if primary not in allowed or any(domain not in allowed for domain in active):
            reason_codes.append("DOMAIN_ID_OUTSIDE_CATALOG")
        if primary and primary not in active:
            reason_codes.append("PRIMARY_DOMAIN_NOT_ACTIVE")
        invalid_anchors = [anchor for anchor in anchors if _normal(anchor) not in corpus]
        if invalid_anchors:
            reason_codes.append("DOMAIN_SOURCE_ANCHOR_INVALID")
        informative = [anchor for anchor in anchors if _normal(anchor) not in _LOW_INFORMATION_ANCHORS]
        if not informative:
            reason_codes.append("DOMAIN_ANCHOR_LOW_INFORMATION_ONLY")
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
            reason_codes.append("DOMAIN_CONFIDENCE_INVALID")
        output.append({
            "schema_version": PAPER_DOMAIN_ASSESSMENT_VERSION,
            "status": "CLASSIFIED" if not reason_codes else "REJECTED_PROTOCOL",
            "primary_domain_id": primary if not reason_codes else "",
            "active_domain_ids": active if not reason_codes else [],
            "provider_taxonomy_evidence": list(item["provider_taxonomy"]),
            "source_anchors": anchors if not reason_codes else [],
            "llm_model_id": _model_id(),
            "confidence": confidence if not reason_codes else 0.0,
            "reason_codes": reason_codes,
        })
    return output


def assess_paper_domain(
    paper: Mapping[str, Any],
    policy: ScienceExecutionPolicy,
    *,
    llm_call: Callable[..., dict[str, Any]] | None = None,
) -> PaperDomainAssessment:
    return assess_paper_domains([paper], policy, llm_call=llm_call)[0]


def classify_paper_content(
    paper: Mapping[str, Any],
    policy: ScienceExecutionPolicy,
    *,
    domain_assessment: Mapping[str, Any] | None = None,
    research_role: str = "PENDING",
    retrieval_layer: str = "",
    admission_status: str = "PENDING",
    llm_call: Callable[..., dict[str, Any]] | None = None,
) -> PaperClassification:
    publication_form = publication_form_from_metadata(paper)
    role = _text(research_role).upper()
    role = role if role in RESEARCH_ROLES else "PENDING"
    if not policy.use_llm:
        return {
            "schema_version": PAPER_CLASSIFICATION_VERSION,
            "publication_form": publication_form,
            "evidence_genre": "unknown",
            "research_design": "unknown",
            "research_role": role,
            "retrieval_layer": _text(retrieval_layer),
            "admission_status": "PENDING",
            "source_anchors": [],
            "model_id": _model_id(),
            "prompt_revision": PAPER_CLASSIFICATION_PROMPT_REVISION,
            "status": "CLASSIFICATION_PENDING",
            "reason_codes": ["LLM_PAPER_CLASSIFICATION_DISABLED"],
        }
    fulltext = _text(
        paper.get("full_text_excerpt") or paper.get("fulltext") or paper.get("extracted_text")
    )
    source = {
        "title": _text(paper.get("title")),
        "abstract": _text(paper.get("abstract")),
        "venue": _text(paper.get("venue")),
        "publication_form": publication_form,
        "publication_types": _unique(paper.get("publication_types") or paper.get("publicationTypes") or []),
        "domain_assessment": dict(domain_assessment or {}),
        "fulltext_excerpt": fulltext[:18000],
    }
    call = llm_call or _default_llm_call
    try:
        payload = call(
            system=(
                "Classify the scientific evidence content of one paper. Return JSON only. Publication form is metadata, "
                "not evidence strength. Cite verbatim source anchors and do not infer unreported experiments."
            ),
            prompt=(
                "Return exactly {\"evidence_genre\":...,\"research_design\":...,\"source_anchors\":[...],"
                "\"confidence\":0.0}. "
                f"Allowed evidence genres: {json.dumps(sorted(EVIDENCE_GENRES))}. "
                f"Allowed research designs: {json.dumps(sorted(RESEARCH_DESIGNS))}.\n"
                + json.dumps(source, ensure_ascii=False)
            ),
            max_tokens=1200,
        )
    except Exception as exc:
        return {
            "schema_version": PAPER_CLASSIFICATION_VERSION,
            "publication_form": publication_form,
            "evidence_genre": "unknown",
            "research_design": "unknown",
            "research_role": role,
            "retrieval_layer": _text(retrieval_layer),
            "admission_status": "PENDING",
            "source_anchors": [],
            "model_id": _model_id(),
            "prompt_revision": PAPER_CLASSIFICATION_PROMPT_REVISION,
            "status": "CLASSIFICATION_PENDING",
            "reason_codes": [f"LLM_PAPER_CLASSIFICATION_PENDING:{type(exc).__name__}"],
        }
    evidence_genre = _text(payload.get("evidence_genre")).lower()
    research_design = _text(payload.get("research_design")).lower()
    anchors = _unique(payload.get("source_anchors"))
    corpus = _normal(" ".join((source["title"], source["abstract"], source["fulltext_excerpt"])))
    protocol_reason_codes: list[str] = []
    if evidence_genre not in EVIDENCE_GENRES:
        protocol_reason_codes.append("EVIDENCE_GENRE_PROTOCOL_INVALID")
    if research_design not in RESEARCH_DESIGNS:
        protocol_reason_codes.append("RESEARCH_DESIGN_PROTOCOL_INVALID")
    if not anchors or any(_normal(anchor) not in corpus for anchor in anchors):
        protocol_reason_codes.append("PAPER_CLASSIFICATION_SOURCE_ANCHOR_INVALID")
    pending_reason_codes: list[str] = []
    if (
        evidence_genre
        in {"primary_empirical", "primary_measurement", "primary_validation"}
        and not fulltext
    ):
        pending_reason_codes.append("FULLTEXT_REQUIRED_FOR_PRIMARY_EVIDENCE_GENRE")
    status = (
        "REJECTED_PROTOCOL"
        if protocol_reason_codes
        else "CLASSIFICATION_PENDING"
        if pending_reason_codes
        else "CLASSIFIED"
    )
    reason_codes = [*protocol_reason_codes, *pending_reason_codes]
    classification_ready = status == "CLASSIFIED"
    return {
        "schema_version": PAPER_CLASSIFICATION_VERSION,
        "publication_form": publication_form,
        "evidence_genre": evidence_genre if classification_ready else "unknown",
        "research_design": research_design if not protocol_reason_codes else "unknown",
        "research_role": role,
        "retrieval_layer": _text(retrieval_layer),
        "admission_status": _text(admission_status).upper() if classification_ready else "PENDING",
        "source_anchors": anchors if not protocol_reason_codes else [],
        "model_id": _model_id(),
        "prompt_revision": PAPER_CLASSIFICATION_PROMPT_REVISION,
        "status": status,
        "reason_codes": reason_codes,
    }


def domain_compatibility(
    question_domain_contract: Mapping[str, Any] | None,
    paper_domain_assessment: Mapping[str, Any] | None,
) -> DomainCompatibility:
    question = question_domain_contract if isinstance(question_domain_contract, Mapping) else {}
    paper = paper_domain_assessment if isinstance(paper_domain_assessment, Mapping) else {}
    if _text(question.get("status")) != "READY" or _text(paper.get("status")) != "CLASSIFIED":
        return DomainCompatibility.UNKNOWN
    question_domains = set(_unique(question.get("active_domain_ids")))
    paper_domains = set(_unique(paper.get("active_domain_ids")))
    if not question_domains or not paper_domains:
        return DomainCompatibility.UNKNOWN
    return DomainCompatibility.MATCH if question_domains & paper_domains else DomainCompatibility.MISMATCH
