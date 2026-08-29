from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Mapping
import ast
import hashlib
import json
import math
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from threading import Lock

try:
    from .config import (
        SCIENCE_DOMAIN_EMBEDDINGS_ENABLED,
        SCIENCE_DOMAIN_EMBEDDING_MODEL_PATH,
        SCIENCE_DOMAIN_EMBEDDING_REJECT_THRESHOLD,
        SCIENCE_DOMAIN_EMBEDDING_REVIEW_THRESHOLD,
        SCIENCE_L2_TOP_LATEST_YEAR_MIN,
        SCIENCE_ZHIZHI_MAX_IMPORT_TOP_K,
    )
    from .log import log_event
except ImportError:
    from config import (
        SCIENCE_DOMAIN_EMBEDDINGS_ENABLED,
        SCIENCE_DOMAIN_EMBEDDING_MODEL_PATH,
        SCIENCE_DOMAIN_EMBEDDING_REJECT_THRESHOLD,
        SCIENCE_DOMAIN_EMBEDDING_REVIEW_THRESHOLD,
        SCIENCE_L2_TOP_LATEST_YEAR_MIN,
        SCIENCE_ZHIZHI_MAX_IMPORT_TOP_K,
    )
    from log import log_event


DOMAIN_FIELD_PROTOTYPES = {
    "physics": "Fundamental physical laws, quantum phenomena, matter, fields, and measurement.",
    "mathematics": "Mathematical proofs, algebra, geometry, analysis, probability, and differential equations.",
    "computer_science": "Algorithms, software, artificial intelligence, machine learning, and computation.",
    "quantitative_biology": "Quantitative models, bioinformatics, systems biology, and biological networks.",
    "quantitative_finance": "Computational and mathematical finance, securities pricing, risk, portfolios, and markets.",
    "statistics": "Statistical inference, probability, experimental design, and uncertainty quantification.",
    "electrical_engineering": "Circuits, signals, control systems, communications, and engineered devices.",
    "engineering": "Mechanical, civil, aerospace, manufacturing, energy, and biomedical engineering systems.",
    "economics": "Economic behavior, markets, policy, econometrics, and incentives.",
    "medicine": "Human health, disease, diagnosis, clinical care, therapeutics, and epidemiology.",
    "biology": "Cells, organisms, genes, proteins, development, physiology, and evolution.",
    "agriculture": "Crops, plants, soil, livestock, food systems, agronomy, and precision agriculture.",
    "chemistry": "Molecules, reactions, catalysis, materials chemistry, electrochemistry, and synthesis.",
    "materials_science": "Materials structure, electronic and energy materials, nanomaterials, polymers, and manufacturing.",
    "earth_environmental_science": "Climate, atmosphere, oceans, geology, hydrology, environmental processes, and remote sensing.",
}

_DOMAIN_EMBEDDER: Any = None
_DOMAIN_EMBEDDER_LOAD_ATTEMPTED = False
_LOCAL_SCORING_CACHE_LOCK = Lock()
_PUBLICATION_QUALITY_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_RESEARCH_FIELD_CACHE: dict[tuple[Any, ...], str] = {}
_MECHANISM_EVIDENCE_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_LOCAL_SCORING_CACHE_LIMIT = 4096
RESEARCH_DOMAIN_PROFILE_ARTIFACT_VERSION = "research_domain_profile_artifact_v1"


def _stable_list_value(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item or "").strip().lower() for item in value)
    if isinstance(value, str):
        return tuple(part for part in re.split(r"[\s,;]+", value.strip().lower()) if part)
    return ()


def _stable_mapping_value(value: Any) -> str:
    """Make nested provider metadata safe to include in a cache key."""
    if not isinstance(value, (dict, list, tuple, set)):
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _paper_scoring_cache_key(result: dict[str, Any]) -> tuple[Any, ...]:
    payload = result.get("papergraph_input") if isinstance(result.get("papergraph_input"), dict) else {}
    return (
        *(str(result.get(key) or "").strip().lower() for key in (
            "title", "abstract", "venue", "year", "provider", "url", "open_access_pdf", "doi",
            "citation", "method", "scenario", "benchmark",
        )),
        str(result.get("citation_count") or ""),
        str(result.get("influential_citation_count") or ""),
        str(result.get("reference_count") or ""),
        _stable_list_value(result.get("publication_types")),
        _stable_list_value(result.get("arxiv_categories")),
        _stable_list_value(payload.get("arxiv_categories")),
        _stable_mapping_value(result.get("venue_metadata")),
        _stable_mapping_value(payload.get("venue_metadata")),
        _stable_mapping_value(result.get("citation_metrics")),
        _stable_mapping_value(payload.get("citation_metrics")),
    )


def _cached_mapping_copy(value: dict[str, Any]) -> dict[str, Any]:
    copied = dict(value)
    for key, item in tuple(copied.items()):
        if isinstance(item, list):
            copied[key] = list(item)
        elif isinstance(item, dict):
            copied[key] = dict(item)
    return copied


def _bounded_cache_store(cache: dict[Any, Any], key: Any, value: Any) -> None:
    if len(cache) >= _LOCAL_SCORING_CACHE_LIMIT:
        for oldest in list(cache)[: max(1, _LOCAL_SCORING_CACHE_LIMIT // 8)]:
            cache.pop(oldest, None)
    cache[key] = value



def literature_selection_base_score(item: dict[str, Any]) -> float:
    relevance = float(item.get("relevance_score") or 0.0)
    quality = float(item.get("publication_quality_score") or publication_quality_assessment(item)["quality_score"])
    impact = literature_impact_score(item)
    recency = literature_recency_score(item)
    layer_bonus = {
        "L0_review": 0.12,
        "L1_milestone": 0.1,
        "L2_top_latest": 0.08,
        "L3_preprint": 0.03,
        "L4_regular": 0.0,
    }.get(str(item.get("stratified_layer") or ""), 0.0)
    return 0.42 * relevance + 0.28 * quality + 0.18 * impact + 0.12 * recency + layer_bonus

def zhizhi_import_minimum_plan(limit: int) -> dict[str, int]:
    try:
        from ._models import ZHIZHI_IMPORT_LAYER_PRIORITY, ZHIZHI_IMPORT_MIN_PER_LAYER
        from ._utils import clamp_int
    except ImportError:
        from _models import ZHIZHI_IMPORT_LAYER_PRIORITY, ZHIZHI_IMPORT_MIN_PER_LAYER
        from _utils import clamp_int
    remaining = clamp_int(limit, 1, SCIENCE_ZHIZHI_MAX_IMPORT_TOP_K)
    plan: dict[str, int] = {}
    for layer in ZHIZHI_IMPORT_LAYER_PRIORITY:
        target = min(int(ZHIZHI_IMPORT_MIN_PER_LAYER.get(layer, 0)), remaining)
        if target > 0:
            plan[layer] = target
            remaining -= target
        if remaining <= 0:
            break
    return plan

def zhizhi_import_priority_score(item: dict[str, Any]) -> float:
    try:
        from ._literature_search import is_review_like_paper
        from ._utils import numeric_value
    except ImportError:
        from _literature_search import is_review_like_paper
        from _utils import numeric_value
    score = literature_selection_base_score(item)
    layer = str(item.get("stratified_layer") or "")
    if layer == "L0_review" and is_review_like_paper(item):
        score += 0.08
    if layer == "L1_milestone" and numeric_value(item.get("citation_count")) > 0:
        score += 0.05
    if layer == "L2_top_latest" and is_l2_top_latest_window_paper(item):
        score += 0.05
    if item.get("zhizhi_import_reason"):
        score += 0.01
    return score


def is_l2_top_latest_window_paper(result: dict[str, Any]) -> bool:
    year_text = str(result.get("year") or "")
    match = re.search(r"\b(19|20)\d{2}\b", year_text)
    if not match:
        return False
    year = int(match.group(0))
    current_year = time.localtime().tm_year
    return SCIENCE_L2_TOP_LATEST_YEAR_MIN <= year <= current_year

def zhizhi_import_candidate_key(item: dict[str, Any]) -> str:
    try:
        from ._literature_search import literature_result_unique_key
    except ImportError:
        from _literature_search import literature_result_unique_key
    result_index = item.get("result_index")
    if result_index is not None:
        return f"result_index:{result_index}"
    return literature_result_unique_key(item)

def literature_result_text_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    try:
        from ._literature_search import query_terms
    except ImportError:
        from _literature_search import query_terms
    text_a = " ".join(query_terms(" ".join(str(a.get(key) or "") for key in ("title", "abstract", "query_branch")))[:24])
    text_b = " ".join(query_terms(" ".join(str(b.get(key) or "") for key in ("title", "abstract", "query_branch")))[:24])
    terms_a = set(query_terms(text_a))
    terms_b = set(query_terms(text_b))
    if not terms_a or not terms_b:
        return 0.0
    return len(terms_a & terms_b) / max(1, len(terms_a | terms_b))

def domain_topic_profile(
    text: str,
    query: str = "",
    use_llm: bool | None = None,
) -> dict[str, Any]:
    try:
        from ._science_execution_policy import resolve_science_execution_policy
        from ._utils import normalize_space
    except ImportError:
        from _science_execution_policy import resolve_science_execution_policy
        from _utils import normalize_space
    use_llm = resolve_science_execution_policy({}, use_llm=use_llm).use_llm
    base_text = normalize_space(" ".join([text, query]))
    if use_llm:
        llm_profile = infer_domain_topic_profile_with_llm(base_text, query=query)
        if llm_profile:
            return llm_profile
    return infer_domain_topic_profile_heuristic(base_text, query=query)


def build_research_domain_profile_artifact(
    *,
    domain: str,
    query: str,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    """Resolve one immutable domain profile for an entire retrieval scope."""

    started = time.perf_counter()
    profile = domain_topic_profile(
        domain or query,
        query=query,
        use_llm=use_llm,
    )
    revision_payload = {
        "schema_version": RESEARCH_DOMAIN_PROFILE_ARTIFACT_VERSION,
        "domain": str(domain or "").strip(),
        "query": str(query or "").strip(),
        "profile": profile,
    }
    revision = hashlib.sha256(
        json.dumps(
            revision_payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:24]
    return {
        **revision_payload,
        "profile_revision": f"rdp_{revision}",
        "profile_source": str(profile.get("profile_source") or ""),
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }

def infer_domain_topic_profile_with_llm(text: str, query: str = "") -> dict[str, Any] | None:
    try:
        from ._llm import call_llm_json
    except ImportError:
        from _llm import call_llm_json
    try:
        payload = call_llm_json(
            system=(
                "You are a domain-agnostic science retrieval planner. Work for any field: mathematics, "
                "physics, chemistry, biology, medicine, agriculture, engineering, materials, earth science, "
                "climate, ecology, computer science, AI, humanities-adjacent science, and interdisciplinary topics. "
                "Do not assume the field is power systems unless the input says so. Return compact JSON only."
            ),
            prompt=(
                "Return one strict JSON object with keys: profile, anchors, noise_markers, core_topics, "
                "expected_topics, retrieval_facets. No markdown.\n"
                "core_topics: 4-8 substantive subfields. Each item has branch, query, expected_terms, min_hits.\n"
                "expected_topics: one item per core topic, with name, terms, min_hits.\n"
                "retrieval_facets: at most 4 generic search facets such as review, latest, benchmark, "
                "or measurement. Do not create milestone/foundation retrieval facets; historical "
                "foundations are handled by a separate causal-contract workflow.\n"
                f"Domain/context: {text}\n"
                f"Original query: {query}\n"
            ),
            max_tokens=3200,
            fallback_list_key="core_topics",
        )
    except Exception as exc:
        log_event("WARN", "domain_profile_llm_failed", error=str(exc))
        return None
    profile = normalize_domain_topic_profile(payload, text)
    profile["profile_source"] = "llm"
    return profile

def infer_domain_topic_profile_heuristic(text: str, query: str = "") -> dict[str, Any]:
    try:
        from ._literature_search import query_terms
        from ._models import research_domain_subfield_topics
        from ._utils import normalize_space
    except ImportError:
        from _literature_search import query_terms
        from _models import research_domain_subfield_topics
        from _utils import normalize_space
    anchors = query_terms(text)[:14]
    topic_seed = normalize_space(query or text)
    if not topic_seed:
        topic_seed = "scientific research"
    catalog_topics = []
    for item in research_domain_subfield_topics(text, max_topics=4, terms_per_topic=5):
        terms = [str(term) for term in item.get("terms", []) if str(term).strip()]
        if not terms:
            continue
        catalog_topics.append(
            {
                "branch": f"catalog_{item['domain']}_{item['subfield']}",
                "query": f"{topic_seed} {' '.join(terms[:4])}",
                "expected_terms": terms,
                "min_hits": 1,
                "rationale": f"Catalog-matched subfield: {item['domain']} / {item['subfield']}.",
                "topic_type": "catalog_subfield",
            }
        )
    generic_topics = [
        {
            "branch": "field_map_reviews",
            "query": f"{topic_seed} review survey roadmap progress perspective systematic review",
            "expected_terms": ["review", "survey", "roadmap", "progress"],
            "rationale": "Find high-impact reviews to establish the field map.",
            "topic_type": "retrieval_facet",
        },
        {
            "branch": "methods_and_mechanisms",
            "query": f"{topic_seed} method model algorithm mechanism experiment framework",
            "expected_terms": ["method", "model", "algorithm", "mechanism", "experiment"],
            "rationale": "Cover method/mechanism families rather than only one wording of the topic.",
            "topic_type": "retrieval_facet",
        },
        {
            "branch": "applications_systems_scenarios",
            "query": f"{topic_seed} application system scenario case study deployment",
            "expected_terms": ["application", "system", "scenario", "case study", "deployment"],
            "rationale": "Cover application settings and scenario-specific literature.",
            "topic_type": "retrieval_facet",
        },
        {
            "branch": "benchmarks_data_validation",
            "query": f"{topic_seed} benchmark dataset validation evaluation metric measurement",
            "expected_terms": ["benchmark", "dataset", "validation", "evaluation", "metric"],
            "rationale": "Cover evaluation, reproducibility, and benchmark evidence.",
            "topic_type": "retrieval_facet",
        },
        {
            "branch": "latest_preprints_frontier",
            "query": f"{topic_seed} latest recent arxiv preprint frontier breakthrough",
            "expected_terms": ["latest", "recent", "preprint", "frontier"],
            "rationale": "Capture emerging work that may not yet be cited.",
            "topic_type": "retrieval_facet",
        },
    ]
    return {
        "profile": slug_label(text) or "generic_science",
        "profile_source": "heuristic",
        "profile_confidence": "low",
        "anchors": anchors,
        "noise_markers": [],
        "core_topics": catalog_topics,
        "retrieval_facets": generic_topics,
        "expected_topics": [
            {
                "name": item["branch"],
                "terms": item["expected_terms"],
                "min_hits": item["min_hits"],
                "topic_type": "catalog_subfield",
            }
            for item in catalog_topics
        ],
        "coverage_note": (
            "Catalog-matched subfield branches complement generic retrieval facets; heuristic fallback cannot certify full coverage."
            if catalog_topics
            else "Heuristic fallback can ensure retrieval-style breadth but cannot certify substantive subfield coverage."
        ),
    }

def normalize_domain_topic_profile(payload: dict[str, Any], fallback_text: str) -> dict[str, Any]:
    try:
        from ._literature_search import query_terms
        from ._utils import clamp_int, scalar, string_list
    except ImportError:
        from _literature_search import query_terms
        from _utils import clamp_int, scalar, string_list
    anchors = string_list(payload.get("anchors"))[:20] or query_terms(fallback_text)[:14]
    noise_markers = string_list(payload.get("noise_markers"))[:20]
    core_topics = normalize_profile_topic_list(payload.get("core_topics"), default_prefix="branch")
    retrieval_facets = normalize_profile_topic_list(payload.get("retrieval_facets"), default_prefix="facet")
    if not retrieval_facets:
        retrieval_facets = infer_domain_topic_profile_heuristic(fallback_text).get("retrieval_facets", [])
    expected_topics: list[dict[str, Any]] = []
    for item in payload.get("expected_topics") or []:
        if not isinstance(item, dict):
            name = scalar(item)
            terms = query_terms(name)[:5]
            min_hits = 2
        else:
            name = scalar(item.get("name"))
            terms = string_list(item.get("terms"))[:8]
            min_hits = clamp_int(item.get("min_hits", 2), 1, 10)
        if name and terms:
            expected_topics.append({"name": name, "terms": terms, "min_hits": min_hits, "topic_type": "subfield"})
    if not core_topics:
        fallback = infer_domain_topic_profile_heuristic(fallback_text)
        fallback["profile_source"] = "heuristic_after_invalid_llm"
        return fallback
    if not expected_topics:
        expected_topics = [
            {
                "name": item["branch"],
                "terms": item.get("expected_terms") or query_terms(item["query"])[:5],
                "min_hits": clamp_int(item.get("min_hits", 2), 1, 10),
                "topic_type": "subfield",
            }
            for item in core_topics
        ]
    return {
        "profile": slug_label(str(payload.get("profile") or fallback_text)) or "science_domain",
        "profile_confidence": "high",
        "anchors": anchors,
        "noise_markers": noise_markers,
        "core_topics": core_topics[:8],
        "retrieval_facets": retrieval_facets[:6],
        "expected_topics": expected_topics[:10],
    }

def normalize_profile_topic_list(raw_topics: Any, default_prefix: str) -> list[dict[str, Any]]:
    try:
        from ._utils import clamp_int, normalize_space, scalar, string_list
    except ImportError:
        from _utils import clamp_int, normalize_space, scalar, string_list
    topics: list[dict[str, Any]] = []
    for index, item in enumerate(raw_topics or []):
        if not isinstance(item, dict):
            continue
        branch = slug_label(str(item.get("branch") or f"branch_{index + 1}"))
        query_text = normalize_space(str(item.get("query") or ""))
        if not query_text:
            continue
        topics.append(
            {
                "branch": branch,
                "query": query_text,
                "expected_terms": string_list(item.get("expected_terms"))[:8],
                "min_hits": clamp_int(item.get("min_hits", 2), 1, 10),
                "rationale": scalar(item.get("rationale")),
                "topic_type": str(item.get("topic_type") or default_prefix),
            }
        )
    return topics

def slug_label(text: str) -> str:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    value = normalize_space(text).lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")[:80]


def local_domain_embedding_model() -> Any | None:
    global _DOMAIN_EMBEDDER, _DOMAIN_EMBEDDER_LOAD_ATTEMPTED
    if _DOMAIN_EMBEDDER_LOAD_ATTEMPTED:
        return _DOMAIN_EMBEDDER
    _DOMAIN_EMBEDDER_LOAD_ATTEMPTED = True
    if not SCIENCE_DOMAIN_EMBEDDINGS_ENABLED or not SCIENCE_DOMAIN_EMBEDDING_MODEL_PATH:
        return None
    model_path = Path(SCIENCE_DOMAIN_EMBEDDING_MODEL_PATH)
    if not model_path.is_dir():
        log_event("WARN", "domain_embedding_model_unavailable", model_path=str(model_path))
        return None
    try:
        from sentence_transformers import SentenceTransformer
        _DOMAIN_EMBEDDER = SentenceTransformer(str(model_path))
        log_event("SCIENCE", "domain_embedding_model_loaded", model_path=str(model_path))
    except Exception as exc:
        log_event("WARN", "domain_embedding_model_load_failed", error=str(exc)[:200])
    return _DOMAIN_EMBEDDER


def domain_embedding_runtime_status(*, prewarm: bool = False) -> dict[str, Any]:
    configured_path = str(SCIENCE_DOMAIN_EMBEDDING_MODEL_PATH or "").strip()
    if not SCIENCE_DOMAIN_EMBEDDINGS_ENABLED:
        return {
            "enabled": False,
            "configured_path": configured_path,
            "status": "disabled",
            "loaded": False,
        }
    if not configured_path:
        return {
            "enabled": True,
            "configured_path": "",
            "status": "missing_model_path",
            "loaded": False,
        }
    model = local_domain_embedding_model() if prewarm else _DOMAIN_EMBEDDER
    return {
        "enabled": True,
        "configured_path": configured_path,
        "status": "loaded" if model is not None else "unavailable",
        "loaded": model is not None,
    }


def cosine_similarity(left: Any, right: Any) -> float:
    numerator = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) * float(value) for value in left))
    right_norm = math.sqrt(sum(float(value) * float(value) for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return max(-1.0, min(1.0, numerator / (left_norm * right_norm)))


def semantic_domain_similarity(target_text: str, paper_text: str) -> dict[str, Any]:
    model = local_domain_embedding_model()
    if model is None:
        return {"available": False, "similarity": None, "source": "structured_fallback"}
    if not str(target_text or "").strip() or not str(paper_text or "").strip():
        return {"available": True, "similarity": None, "source": "local_embedding"}
    try:
        target_embedding, paper_embedding = model.encode([target_text, paper_text])
    except Exception as exc:
        log_event("WARN", "domain_embedding_similarity_failed", error=str(exc)[:200])
        return {"available": False, "similarity": None, "source": "structured_fallback"}
    return {
        "available": True,
        "similarity": round(cosine_similarity(target_embedding, paper_embedding), 4),
        "source": "local_embedding",
    }


def infer_field_by_embedding(result: dict[str, Any]) -> str:
    model = local_domain_embedding_model()
    if model is None:
        return ""
    text = " ".join(str(result.get(key) or "") for key in ("title", "abstract", "venue"))
    if not text.strip():
        return ""
    fields = list(DOMAIN_FIELD_PROTOTYPES)
    try:
        embeddings = model.encode([text] + [DOMAIN_FIELD_PROTOTYPES[field] for field in fields])
    except Exception as exc:
        log_event("WARN", "domain_embedding_field_inference_failed", error=str(exc)[:200])
        return ""
    paper_embedding = embeddings[0]
    scores = [cosine_similarity(paper_embedding, prototype) for prototype in embeddings[1:]]
    if not scores:
        return ""
    best_index = max(range(len(scores)), key=lambda index: scores[index])
    return fields[best_index] if scores[best_index] >= 0.35 else ""


def catalog_mechanism_evidence(
    result: dict[str, Any],
    target_field: str = "",
    target_text: str = "",
) -> dict[str, Any]:
    """Assess mechanism evidence against the existing natural-science catalog.

    A shared top-level field is not sufficient. The paper must also contain a
    discriminating action/evidence marker and, when a target question is
    available, at least two question-specific terms.
    """
    try:
        from ._models import RESEARCH_DOMAIN_CATALOG, research_domain_for_field, research_domain_profile
        from ._retrieval_strategy import DOMAIN_EVIDENCE_PROFILES
    except ImportError:
        from _models import RESEARCH_DOMAIN_CATALOG, research_domain_for_field, research_domain_profile
        from _retrieval_strategy import DOMAIN_EVIDENCE_PROFILES
    cache_key = (
        _paper_scoring_cache_key(result),
        str(target_field or "").strip().lower(),
        str(target_text or "").strip().lower(),
    )
    with _LOCAL_SCORING_CACHE_LOCK:
        cached = _MECHANISM_EVIDENCE_CACHE.get(cache_key)
    if cached is not None:
        return _cached_mapping_copy(cached)
    text = " ".join(
        str(result.get(key) or "")
        for key in ("title", "abstract", "venue", "citation", "method", "scenario", "benchmark")
    ).lower()
    target_profile = research_domain_profile(f"{target_field} {target_text}")
    target_domain = research_domain_for_field(target_field)
    target_domains = list(target_profile.get("active_domains") or [])
    if target_domain != "general" and target_domain not in target_domains:
        target_domains.insert(0, target_domain)
    result_profile = research_domain_profile(text)
    result_domains = list(result_profile.get("active_domains") or [])
    overlap = sorted(set(target_domains) & set(result_domains))
    # The catalog deliberately contains precise multi-word subfield terms such
    # as ``superconducting materials``.  A paper may contain the discriminating
    # scientific token (``superconducting``) without repeating the whole catalog
    # phrase.  Use those existing catalog terms as a bounded fallback instead of
    # adding discipline-specific exceptions here.
    catalog_domain_term_hits: dict[str, list[str]] = {}
    catalog_token_stopwords = {
        "analysis", "applied", "data", "engineering", "general", "human",
        "method", "model", "research", "science", "scientific", "study",
        "system", "systems", "technology", "theory", "using",
    }
    text_tokens = set(re.findall(r"[a-z][a-z0-9_-]{4,}", text))

    def _catalog_token_matches(candidate: str) -> bool:
        if candidate in text_tokens:
            return True
        # Conservative morphology fallback for long technical words, e.g.
        # superconductivity/superconducting.  Ten-character agreement avoids
        # turning short generic stems into accidental domain evidence.
        return len(candidate) >= 10 and any(
            len(token) >= 10 and token[:10] == candidate[:10]
            for token in text_tokens
        )

    for domain in target_domains:
        spec = RESEARCH_DOMAIN_CATALOG.get(str(domain), {})
        catalog_terms = [
            *(
                str(term).lower()
                for term in spec.get("domain_specific_terms", spec.get("keywords", ()))
            ),
            *(
                str(term).lower()
                for terms in spec.get("subfields", {}).values()
                for term in terms
            ),
        ]
        hits: list[str] = []
        for term in catalog_terms:
            term_tokens = [
                token
                for token in re.findall(r"[a-z][a-z0-9_-]{4,}", term)
                if token not in catalog_token_stopwords
            ]
            if term and term in text:
                hits.append(term)
            elif any(_catalog_token_matches(token) for token in term_tokens):
                hits.extend(token for token in term_tokens if _catalog_token_matches(token))
        if hits:
            catalog_domain_term_hits[str(domain)] = list(dict.fromkeys(hits))[:8]
            if domain not in result_domains:
                result_domains.append(str(domain))
    overlap = sorted(set(target_domains) & set(result_domains))
    mechanism_terms = [
        "causal", "controls", "determines", "drives", "governs", "induces",
        "intervention", "mechanism", "mediates", "perturbation", "regulates",
        "rescue", "suppresses", "switches",
    ]
    for domain in target_domains:
        mechanism_terms.extend(DOMAIN_EVIDENCE_PROFILES.get(str(domain), {}).get("direct", ()))
    mechanism_hits = list(dict.fromkeys(term for term in mechanism_terms if term in text))
    low_signal = {
        "analysis", "data", "effect", "human", "method", "model", "paper", "research",
        "result", "science", "study", "system", "using",
    }
    target_terms = [
        term
        for term in re.findall(r"[a-z][a-z0-9_-]{2,}", str(target_text or "").lower())
        if term not in low_signal
    ]
    context_hits = list(dict.fromkeys(term for term in target_terms if term in text))
    context_requirement_met = len(context_hits) >= 2 if target_terms else bool(overlap)
    assessment = {
        "qualified": bool(overlap) and bool(mechanism_hits) and context_requirement_met,
        "target_domains": target_domains,
        "result_domains": result_domains,
        "domain_overlap": overlap,
        "catalog_domain_term_hits": catalog_domain_term_hits,
        "mechanism_hits": mechanism_hits[:8],
        "context_hits": context_hits[:8],
        "catalog_version": str(target_profile.get("catalog_version") or ""),
    }
    with _LOCAL_SCORING_CACHE_LOCK:
        _bounded_cache_store(_MECHANISM_EVIDENCE_CACHE, cache_key, _cached_mapping_copy(assessment))
    return assessment


def biological_mechanism_evidence(result: dict[str, Any], target_field: str = "") -> dict[str, Any]:
    """Backward-compatible alias for persisted records created before v2."""
    return catalog_mechanism_evidence(result, target_field=target_field)


def domain_relevance_assessment(
    result: dict[str, Any],
    domain: str = "",
    query: str = "",
    *,
    domain_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        from ._literature_search import is_preprint_literature_result, query_terms
        from ._models import PREPRINT_API_PROVIDERS
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _literature_search import is_preprint_literature_result, query_terms
        from _models import PREPRINT_API_PROVIDERS
        from _utils import normalize_space, unique_preserve_order
    profile = (
        dict(domain_profile)
        if isinstance(domain_profile, Mapping)
        else domain_topic_profile(domain or query, query=query, use_llm=False)
    )
    text = normalize_space(
        " ".join(
            str(result.get(key) or "")
            for key in ("title", "abstract", "venue", "citation", "method", "scenario", "benchmark")
        )
    ).lower()
    query_term_list = query_terms(query)
    query_hits = [term for term in query_term_list if term in text]
    anchors = [term.lower() for term in profile.get("anchors", []) if str(term).strip()]
    anchor_hits = [term for term in anchors if term in text]
    topic_hits: list[str] = []
    for topic in profile.get("expected_topics", []):
        terms = [str(term).lower() for term in topic.get("terms", [])]
        if any(term in text for term in terms):
            topic_hits.append(str(topic.get("name") or terms[0]))
    noise_hits = [marker for marker in profile.get("noise_markers", []) if marker in text]
    query_score = len(query_hits) / max(1, len(query_term_list))
    anchor_score = len(anchor_hits) / max(1, min(len(anchors), 8))
    topic_score = min(1.0, len(topic_hits) / 2.0)
    score = round(min(1.0, 0.45 * query_score + 0.35 * anchor_score + 0.2 * topic_score), 4)
    flags: list[str] = []
    target_field = infer_research_field({"title": domain, "abstract": query, "venue": ""}) if (domain or query) else "general"
    result_field = str(result.get("inferred_field") or "") or infer_research_field(result)
    mechanism_evidence = catalog_mechanism_evidence(
        result,
        target_field=target_field,
        target_text=f"{domain} {query}",
    )
    strong_text_signal = len(query_hits) >= max(2, min(4, len(query_term_list) // 3)) or len(anchor_hits) >= 2 or bool(topic_hits)
    field_mismatch = fields_are_incompatible(target_field, result_field)
    if noise_hits:
        flags.append("cross_domain_noise_marker")
    if field_mismatch:
        flags.append("field_mismatch")
        if not strong_text_signal:
            score = round(score * 0.35, 4)
    if score < 0.16:
        flags.append("low_domain_relevance")
    if topic_hits:
        flags.append("domain_topic_hit")
    provider = normalize_space(str(result.get("provider") or result.get("venue") or "")).lower()
    is_preprint = is_preprint_literature_result(result) or provider in PREPRINT_API_PROVIDERS or any(name in provider for name in PREPRINT_API_PROVIDERS)
    core_alignment = core_domain_alignment(result, domain=domain, query=query)
    if core_alignment["enabled"]:
        if not core_alignment["passes"]:
            if mechanism_evidence["qualified"]:
                flags.append("biological_mechanism_exception")
                score = round(max(score, 0.3), 4)
            else:
                flags.append("core_domain_mismatch")
                score = round(score * 0.45, 4)
        elif core_alignment["specific_hit_count"] >= 2:
            score = round(min(1.0, score + 0.08), 4)
            flags.append("core_domain_hit")
    if is_preprint and score < 0.16:
        flags.append("weak_preprint_domain_relevance")
    preprint_has_signal = bool(query_hits or anchor_hits or topic_hits)
    verdict = "keep"
    if noise_hits:
        verdict = "reject"
    elif core_alignment["enabled"] and not core_alignment["passes"] and not mechanism_evidence["qualified"]:
        verdict = "reject"
    elif field_mismatch and not strong_text_signal and score < 0.25:
        verdict = "reject"
    elif is_preprint and score < 0.06 and not preprint_has_signal:
        verdict = "reject"
    return {
        "profile": profile.get("profile"),
        "target_field": target_field,
        "result_field": result_field,
        "score": score,
        "query_hits": unique_preserve_order(query_hits)[:12],
        "anchor_hits": unique_preserve_order(anchor_hits)[:12],
        "topic_hits": unique_preserve_order(topic_hits),
        "noise_hits": unique_preserve_order(noise_hits),
        "flags": unique_preserve_order(flags),
        "is_preprint": is_preprint,
        "core_domain_alignment": core_alignment,
        "domain_mechanism_evidence": mechanism_evidence,
        "biological_mechanism_evidence": mechanism_evidence,
        "verdict": verdict,
        "requires_human_review": bool(
            (is_preprint and score < 0.16 and verdict != "reject")
            or (field_mismatch and verdict != "reject")
            or (mechanism_evidence["qualified"] and not core_alignment["passes"])
        ),
    }

def _record_domain_gate_assessment(
    result: dict[str, Any],
    relevance: dict[str, Any],
    *,
    verdict: str,
    decision_stage: str,
    reason: str,
    review: dict[str, Any] | None = None,
    matched_exclusions: list[str] | None = None,
) -> bool:
    review_data = review if isinstance(review, dict) else {}
    result["domain_gate"] = {
        "verdict": verdict,
        "decision_stage": decision_stage,
        "rejecting_stage": decision_stage if verdict == "reject" else "",
        "reason": reason,
        "primary_relevance_verdict": str(relevance.get("verdict") or "unknown"),
        "primary_relevance_score": relevance.get("score"),
        "review_verdict": str(review_data.get("verdict") or "not_run"),
        "review_score": review_data.get("score"),
        "matched_exclusion_markers": list(matched_exclusions or []),
        "requires_human_review": verdict in {"review", "override"} or bool(review_data.get("requires_human_review")),
    }
    return verdict == "reject"


def domain_gate_review_rescue(result: dict[str, Any], review: dict[str, Any]) -> tuple[bool, str]:
    try:
        from ._literature_search import is_preprint_literature_result
        from ._utils import numeric_value
    except ImportError:
        from _literature_search import is_preprint_literature_result
        from _utils import numeric_value
    semantic_similarity = float(review.get("semantic_similarity") or 0.0)
    probability_overlap = float((review.get("probability_alignment") or {}).get("overlap") or 0.0)
    mechanism_evidence = review.get("domain_mechanism_evidence") or review.get("biological_mechanism_evidence") or {}
    plausible_bridge = (
        semantic_similarity >= SCIENCE_DOMAIN_EMBEDDING_REJECT_THRESHOLD
        or probability_overlap >= 0.16
        or bool(mechanism_evidence.get("qualified"))
    )
    if bool(review.get("distinct_physics_conflict")) or not plausible_bridge:
        return False, ""
    if is_preprint_literature_result(result):
        return True, "Preprint has nontrivial semantic or interdisciplinary evidence and is retained for review."
    if numeric_value(result.get("citation_count")) >= 20:
        return True, "Highly cited paper has nontrivial semantic or interdisciplinary evidence and is retained for review."
    if float(result.get("publication_quality_score") or 0.0) >= 0.85:
        return True, "High-quality paper has nontrivial semantic or interdisciplinary evidence and is retained for review."
    return False, ""


def should_reject_for_domain(result: dict[str, Any], domain: str = "", query: str = "") -> bool:
    try:
        from ._literature_search import is_preprint_literature_result
        from ._utils import numeric_value
    except ImportError:
        from _literature_search import is_preprint_literature_result
        from _utils import numeric_value
    assessment = result.get("domain_relevance")
    if not isinstance(assessment, dict):
        assessment = domain_relevance_assessment(result, domain=domain, query=query)
        result["domain_relevance"] = assessment
    if not domain:
        return _record_domain_gate_assessment(
            result,
            assessment,
            verdict="keep",
            decision_stage="no_domain_constraint",
            reason="No project domain was supplied, so no domain exclusion gate was applied.",
        )
    review = domain_review_assessment(result, domain=domain, query=query)
    result["domain_review"] = review
    rescue_allowed, rescue_reason = domain_gate_review_rescue(result, review)
    if assessment.get("verdict") == "reject" and review.get("verdict") == "reject" and not rescue_allowed:
        return _record_domain_gate_assessment(
            result,
            assessment,
            verdict="reject",
            decision_stage="primary_and_domain_review",
            reason=str(review.get("reason") or "Primary and secondary domain gates rejected the candidate."),
            review=review,
        )
    if review.get("verdict") == "reject" and not rescue_allowed:
        return _record_domain_gate_assessment(
            result,
            assessment,
            verdict="reject",
            decision_stage="domain_review",
            reason=str(review.get("reason") or "Secondary domain review rejected the candidate."),
            review=review,
        )
    if rescue_allowed:
        review = {
            **review,
            "verdict": "review",
            "rescue_applied": True,
            "reason": rescue_reason,
        }
        result["domain_review"] = review
    # Domain exclusion marker check: reject papers from clearly different disciplines
    exclusion_markers = domain_exclusion_markers(domain)
    if exclusion_markers:
        paper_text = " ".join(
            str(result.get(key) or "")
            for key in ("title", "abstract", "venue")
        ).lower()
        matched_exclusions = [marker for marker in exclusion_markers if marker in paper_text]
        if matched_exclusions:
            probability_overlap = float((review.get("probability_alignment") or {}).get("overlap") or 0.0)
            semantic_similarity = float(review.get("semantic_similarity") or 0.0)
            if probability_overlap < 0.12 and semantic_similarity < SCIENCE_DOMAIN_EMBEDDING_REJECT_THRESHOLD:
                log_event(
                    "SCIENCE",
                    "domain_exclusion_marker_hit",
                    domain=domain,
                    title=str(result.get("title", ""))[:80],
                    markers=matched_exclusions,
                )
                return _record_domain_gate_assessment(
                    result,
                    assessment,
                    verdict="reject",
                    decision_stage="exclusion_marker",
                    reason="Project-domain exclusion markers matched without semantic or interdisciplinary overlap.",
                    review=review,
                    matched_exclusions=matched_exclusions,
                )
            review = {
                **review,
                "verdict": "review",
                "soft_exclusion_markers": matched_exclusions,
                "reason": "Exclusion-like terms occurred, but cross-domain probability overlap requires review rather than rejection.",
            }
            result["domain_review"] = review
    # Preprint providers generally cannot supply a meaningful citation count at
    # first posting. Semantic and reviewer gates above still reject irrelevant
    # material; zero citations must not become a second P0 rejection criterion.
    if is_preprint_literature_result(result):
        return _record_domain_gate_assessment(
            result,
            assessment,
            verdict="review" if review.get("verdict") == "review" else "keep",
            decision_stage="preprint_protection",
            reason="Preprint passed hard domain gates; citation count is not used as an exclusion criterion.",
            review=review,
        )
    score = float(assessment.get("score") or 0.0)
    quality = float(result.get("publication_quality_score") or publication_quality_assessment(result)["quality_score"])
    citations = numeric_value(result.get("citation_count"))
    if "field_mismatch" in set(assessment.get("flags") or []) and score < 0.18 and citations <= 5:
        if review.get("verdict") == "review":
            return _record_domain_gate_assessment(
                result,
                assessment,
                verdict="review",
                decision_stage="low_signal_field_mismatch",
                reason="Low-signal field mismatch is retained for review because the secondary assessment found a plausible bridge.",
                review=review,
            )
        return _record_domain_gate_assessment(
            result,
            assessment,
            verdict="reject",
            decision_stage="low_signal_field_mismatch",
            reason="Candidate has a low-signal field mismatch with insufficient citation support.",
            review=review,
        )
    if score < 0.1 and quality < 0.55 and citations <= 0:
        if review.get("verdict") == "review":
            return _record_domain_gate_assessment(
                result,
                assessment,
                verdict="review",
                decision_stage="low_relevance_low_quality",
                reason="Low-quality candidate is retained for review because the secondary assessment found a plausible bridge.",
                review=review,
            )
        return _record_domain_gate_assessment(
            result,
            assessment,
            verdict="reject",
            decision_stage="low_relevance_low_quality",
            reason="Candidate has low domain relevance, low quality, and no citation support.",
            review=review,
        )
    return _record_domain_gate_assessment(
        result,
        assessment,
        verdict="review" if review.get("verdict") == "review" else "keep",
        decision_stage="domain_review" if review.get("verdict") == "review" else "accepted",
        reason=str(review.get("reason") or "Candidate passed primary relevance, domain review, and quality gates."),
        review=review,
    )


def domain_review_assessment(
    result: dict[str, Any],
    domain: str,
    query: str = "",
    min_confidence: float = 0.6,
) -> dict[str, Any]:
    """Perform a second, domain-general audit before or after import.

    The retrieval gate answers "does this text loosely match?". This reviewer
    additionally checks whether the candidate has enough *target-domain*
    anchors to justify a different detected field. It catches surface-word
    collisions such as a target term reused by astrophysics, optics, or quantum
    materials without hard-coding one research topic's vocabulary.
    """
    try:
        from ._literature_search import query_terms
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _literature_search import query_terms
        from _utils import normalize_space, unique_preserve_order
    text = normalize_space(
        " ".join(
            str(result.get(key) or "")
            for key in ("title", "abstract", "scenario", "contribution", "limitation", "venue")
        )
    ).lower()
    low_signal_terms = {
        "analysis", "background", "data", "evidence", "human", "humans", "latest", "method", "model",
        "paper", "recent", "research", "review", "science", "study", "studies", "survey", "system", "systems",
    }
    query_first = [term for term in query_terms(query) if term not in low_signal_terms]
    domain_terms = [term for term in query_terms(domain) if term not in low_signal_terms]
    target_terms = unique_preserve_order(query_first + domain_terms)[:12]
    target_hits = [term for term in target_terms if term in text]
    coverage = len(target_hits) / max(1, len(target_terms))
    relevance = result.get("domain_relevance")
    has_retrieval_assessment = isinstance(relevance, dict)
    if not has_retrieval_assessment:
        if normalize_space(query):
            relevance = domain_relevance_assessment(result, domain=domain, query=query)
        else:
            relevance = {
                "verdict": "not_assessed",
                "score": None,
                "reason": "No retrieval query or preserved relevance assessment was available for the post-import audit.",
            }
    target_field = str(relevance.get("target_field") or "") or infer_research_field(
        {"title": domain, "abstract": query, "venue": ""}
    )
    result_field = (
        str(relevance.get("result_field") or "")
        or str(result.get("inferred_field") or "")
        or infer_research_field(result)
    )
    mechanism_evidence = relevance.get("domain_mechanism_evidence")
    if not isinstance(mechanism_evidence, dict):
        mechanism_evidence = catalog_mechanism_evidence(
            result,
            target_field=target_field,
            target_text=f"{domain} {query}",
        )
    same_research_domain_family = not fields_are_incompatible(target_field, result_field)
    foreign_field = fields_are_incompatible(target_field, result_field) or (
        target_field not in {"", "general", "multidisciplinary"}
        and result_field not in {"", "general", "multidisciplinary"}
        and target_field != result_field
        and not same_research_domain_family
    )
    try:
        from ._domain_terms import domain_probability_alignment
    except ImportError:
        from _domain_terms import domain_probability_alignment
    target_text = normalize_space(f"{domain} {query}")
    probability_alignment = domain_probability_alignment(
        target_text,
        text,
        target_field=target_field,
        result_field=result_field,
    )
    semantic_assessment = semantic_domain_similarity(target_text, text)
    relevance_score = relevance.get("score") if isinstance(relevance.get("score"), (int, float)) else 0.0
    structured_similarity = min(
        1.0,
        0.5 * coverage + 0.3 * max(0.0, float(relevance_score)) + 0.2 * float(probability_alignment.get("overlap") or 0.0),
    )
    semantic_similarity = semantic_assessment.get("similarity")
    if not isinstance(semantic_similarity, (int, float)):
        semantic_similarity = structured_similarity
        semantic_source = "structured_catalog_overlap"
    else:
        semantic_source = str(semantic_assessment.get("source") or "local_embedding")
    distinct_physics_conflict = (
        foreign_field
        and target_field in {"astrophysics", "high_energy_physics", "nuclear_physics", "photonics"}
        and result_field in {"astrophysics", "high_energy_physics", "nuclear_physics", "photonics"}
    )
    probability_bridge = float(probability_alignment.get("overlap") or 0.0) >= 0.16 and not distinct_physics_conflict
    cross_field_tolerated = not foreign_field or probability_bridge or mechanism_evidence["qualified"]
    review_threshold = max(0.12, min(0.35, float(min_confidence) * 0.35, SCIENCE_DOMAIN_EMBEDDING_REVIEW_THRESHOLD + 0.08))
    verdict = "keep"
    reason = "Target-domain anchors and field context are consistent."
    if relevance.get("verdict") == "reject" and not mechanism_evidence["qualified"]:
        if (semantic_similarity >= review_threshold and not distinct_physics_conflict) or cross_field_tolerated:
            verdict = "review"
            reason = "Primary lexical relevance is low, but semantic or cross-domain evidence warrants review rather than rejection."
        else:
            verdict = "reject"
            reason = "Primary domain-relevance gate rejected the candidate with no semantic or interdisciplinary bridge."
    elif relevance.get("verdict") == "reject" and mechanism_evidence["qualified"]:
        verdict = "review"
        reason = "Catalog-grounded mechanism evidence matches the target domain, so the primary lexical rejection requires review rather than deactivation."
    elif distinct_physics_conflict:
        verdict = "reject"
        reason = "Distinct physics subfields conflict without an explicit bridge in the target domain."
    elif foreign_field and semantic_similarity < review_threshold and not cross_field_tolerated:
        verdict = "reject"
        reason = "Semantic similarity and cross-domain probability overlap are both too low for the detected field mismatch."
    elif foreign_field and not cross_field_tolerated:
        if mechanism_evidence["qualified"]:
            verdict = "review"
            reason = "Catalog-grounded mechanism evidence matches the target domain despite an ambiguous field label; retain for review."
        else:
            verdict = "review"
            reason = "Detected field differs from the target and needs review before use as core evidence."
    elif foreign_field or semantic_similarity < review_threshold or coverage < review_threshold:
        verdict = "review"
        reason = "Some target evidence exists, but semantic consistency or field context remains ambiguous."
    return {
        "verdict": verdict,
        "score": round(coverage, 4),
        "target_field": target_field,
        "result_field": result_field,
        "foreign_field": foreign_field,
        "target_terms": target_terms,
        "target_hits": target_hits,
        "retrieval_assessment_preserved": has_retrieval_assessment,
        "domain_mechanism_evidence": mechanism_evidence,
        "biological_mechanism_evidence": mechanism_evidence,
        "probability_alignment": probability_alignment,
        "semantic_similarity": round(float(semantic_similarity), 4),
        "semantic_similarity_source": semantic_source,
        "cross_field_tolerated": cross_field_tolerated,
        "distinct_physics_conflict": distinct_physics_conflict,
        "reason": reason,
    }

def domain_exclusion_markers(domain: str = "") -> set[str]:
    """Return exclusion markers for the given domain.

    These markers identify papers that are clearly from a *different* major
    discipline and should be rejected even if they share some surface-level
    keyword overlap (e.g., 'neural network' in a chemistry project).
    """
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    if not domain:
        return set()
    domain_lower = normalize_space(domain).lower()

    # Build exclusion markers based on domain family
    exclusions: set[str] = set()

    def _domain_matches(terms: tuple[str, ...]) -> bool:
        """Check if any trigger term appears as a whole word in the domain string."""
        import re as _re
        for term in terms:
            if _re.search(r'\b' + _re.escape(term) + r'\b', domain_lower):
                return True
        return False

    # Physical / materials / chemistry domains should exclude pure clinical / social / finance
    if _domain_matches(("battery", "catalyst", "material", "polymer", "semiconductor", "alloy", "chemistry", "chemical")):
        exclusions.update({
            "clinical trial", "patient cohort", "epidemiological", "public health",
            "stock market", "financial return", "gdp", "macroeconomic",
            "social media", "survey respondents", "questionnaire",
        })

    # Bio / medical domains should exclude pure physics / math / finance
    if _domain_matches(("protein", "cell", "gene", "clinical", "patient", "disease", "organism", "cancer", "biomedical")):
        exclusions.update({
            "dark matter", "gravitational wave", "black hole", "cosmological",
            "stock market", "financial return", "gdp", "macroeconomic",
            "partial differential equation", "algebraic geometry", "number theory",
        })

    # CS / AI domains should exclude pure clinical / materials / ecology
    if _domain_matches(("algorithm", "neural network", "deep learning", "robotics", "compiler", "operating system")):
        exclusions.update({
            "clinical trial", "patient cohort", "epidemiological",
            "crystal structure", "x-ray diffraction", "catalytic activity",
            "species richness", "community ecology", "biodiversity",
        })

    # Ecology / environmental should exclude pure CS / finance / high-energy physics
    if _domain_matches(("climate", "ecology", "environment", "geology", "agriculture")):
        exclusions.update({
            "stock market", "financial return", "gdp",
            "collider", "quark", "hadron", "lattice gauge",
            "compiler optimization", "operating system",
        })

    # Math / stats should exclude pure experimental sciences
    if _domain_matches(("mathematics", "statistics", "topology", "algebra")):
        exclusions.update({
            "clinical trial", "in vivo", "in vitro",
            "battery performance", "catalytic activity",
            "field experiment", "crop yield",
        })

    return exclusions


def core_domain_alignment(result: dict[str, Any], domain: str = "", query: str = "") -> dict[str, Any]:
    try:
        from ._literature_search import is_preprint_literature_result, is_review_like_paper
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _literature_search import is_preprint_literature_result, is_review_like_paper
        from _utils import normalize_space, unique_preserve_order
    seed_text = normalize_space(f"{domain} {query}")
    core_terms = core_domain_terms(seed_text)
    if len(core_terms) < 3:
        return {
            "enabled": False,
            "passes": True,
            "reason": "not enough specific core terms to enforce strict alignment",
            "core_terms": core_terms,
        }
    text = normalize_space(
        " ".join(
            str(result.get(key) or "")
            for key in ("title", "abstract", "citation", "method", "scenario", "benchmark")
        )
    ).lower()
    hits = [term for term in core_terms if term in text]
    specific_terms = [term for term in core_terms if core_domain_term_is_specific(term)]
    specific_hits = [term for term in specific_terms if term in text]
    preprint = is_preprint_literature_result(result)
    min_hits = 3 if len(core_terms) >= 8 else 2
    min_specific = 2 if len(specific_terms) >= 4 else 1
    # Preprints already go through the same core-domain and noise checks as
    # journal papers. Requiring an extra lexical hit here made relevant early
    # work with concise metadata systematically disappear from L3 while the
    # identical semantic standard admitted it in L4.
    passes = len(hits) >= min_hits and (not specific_terms or len(specific_hits) >= min_specific)
    if is_review_like_paper(result) and len(hits) >= max(2, min_hits - 1):
        passes = True
    return {
        "enabled": True,
        "passes": passes,
        "core_terms": core_terms[:18],
        "core_hit_count": len(hits),
        "core_hits": unique_preserve_order(hits)[:12],
        "specific_terms": specific_terms[:12],
        "specific_hit_count": len(specific_hits),
        "specific_hits": unique_preserve_order(specific_hits)[:10],
        "min_core_hits": min_hits,
        "min_specific_hits": min_specific if specific_terms else 0,
        "is_preprint": preprint,
        "reason": (
            "core topic terms sufficiently covered"
            if passes
            else "title/abstract do not cover enough user-specified core topic terms"
        ),
    }

def core_domain_terms(seed_text: str) -> list[str]:
    try:
        from ._literature_search import query_terms
        from ._utils import unique_preserve_order
    except ImportError:
        from _literature_search import query_terms
        from _utils import unique_preserve_order
    generic = {
        "review",
        "survey",
        "roadmap",
        "progress",
        "perspective",
        "systematic",
        "seminal",
        "foundational",
        "highly",
        "cited",
        "landmark",
        "classic",
        "influential",
        "latest",
        "recent",
        "frontier",
        "breakthrough",
        "method",
        "model",
        "algorithm",
        "mechanism",
        "experiment",
        "framework",
        "application",
        "system",
        "scenario",
        "case",
        "study",
        "deployment",
        "benchmark",
        "dataset",
        "validation",
        "evaluation",
        "metric",
        "measurement",
        "preprint",
        "arxiv",
        "paper",
        "science",
        "research",
        "technology",
    }
    raw_terms = query_terms(seed_text)
    terms = [term for term in raw_terms if term not in generic and len(term) >= 3]
    phrase_terms = extract_core_domain_phrases(seed_text)
    return unique_preserve_order(phrase_terms + terms)[:24]

def extract_core_domain_phrases(seed_text: str) -> list[str]:
    try:
        from ._literature_search import query_terms
    except ImportError:
        from _literature_search import query_terms
    tokens = [term for term in query_terms(seed_text) if len(term) >= 3]
    phrases: list[str] = []
    for size in (3, 2):
        for index in range(0, max(0, len(tokens) - size + 1)):
            window = tokens[index : index + size]
            if any(core_domain_term_is_specific(term) for term in window):
                phrases.append(" ".join(window))
    return phrases[:10]

def core_domain_term_is_specific(term: str) -> bool:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    value = normalize_space(term).lower()
    if any(char.isdigit() for char in value):
        return True
    if len(value) >= 7:
        return True
    if any(marker in value for marker in ("-", "_", "+", "/")):
        return True
    return False

def literature_domain_coverage_diagnostic(
    search_id: str,
    domain: str = "",
    query: str = "",
    live_validate: bool = False,
    use_llm: bool | None = None,
    max_live_probes: int = 4,
) -> dict[str, Any]:
    try:
        from ._literature_search import live_probe_literature_branch
        from ._project import load_search
        from ._utils import clamp_int, normalize_space
    except ImportError:
        from _literature_search import live_probe_literature_branch
        from _project import load_search
        from _utils import clamp_int, normalize_space
    search_record = load_search(search_id)
    results = [item for item in search_record.get("results", []) if isinstance(item, dict)]
    profile = domain_topic_profile(
        domain or query or str(search_record.get("query") or ""),
        query=query or str(search_record.get("query") or ""),
        use_llm=use_llm,
    )
    expected_topics = profile.get("expected_topics", [])
    represented: list[dict[str, Any]] = []
    blind_spots: list[dict[str, Any]] = []
    corpus = [
        normalize_space(
            " ".join(str(item.get(key) or "") for key in ("title", "abstract", "method", "scenario", "benchmark", "citation"))
        ).lower()
        for item in results
    ]
    if not expected_topics:
        blind_spots.append(
            {
                "topic": "substantive_subfield_map_missing",
                "hit_count": 0,
                "min_hits": 1,
                "terms": [],
                "suggested_query": normalize_space(f"{query or search_record.get('query', '')} major subfields review survey"),
                "risk": (
                    "No substantive subfield map is available. The retrieval may cover generic facets "
                    "(review/method/application) while still missing important domain branches."
                ),
                "requires_user_or_llm_branch_confirmation": True,
            }
        )
    for topic in expected_topics:
        name = str(topic.get("name") or "")
        terms = [str(term).lower() for term in topic.get("terms", []) if str(term).strip()]
        min_hits = clamp_int(topic.get("min_hits", 2), 1, 10)
        hit_count = sum(1 for text in corpus if any(term in text for term in terms))
        entry = {"topic": name, "hit_count": hit_count, "min_hits": min_hits, "terms": terms}
        if hit_count >= min_hits:
            represented.append(entry)
        else:
            blind_spots.append(
                {
                    **entry,
                    "suggested_query": normalize_space(f"{query or search_record.get('query', '')} {' '.join(terms[:4])}"),
                    "risk": "If this is a known dense subfield, TanXi may mistake retrieval absence for a true knowledge gap.",
                }
            )
    live_probe_reports: list[dict[str, Any]] = []
    if live_validate and blind_spots:
        for spot in blind_spots[: clamp_int(max_live_probes, 0, 8)]:
            report = live_probe_literature_branch(str(spot.get("suggested_query") or ""), providers=search_record.get("providers", []))
            spot["live_probe"] = report
            if int(report.get("total_results") or 0) > 0:
                spot["false_negative_risk"] = True
                spot["risk"] = (
                    "Live probe found literature for this missing branch; current PaperGraph may be incomplete, "
                    "so TanXi should not treat this absence as a true unexplored gap."
                )
            live_probe_reports.append(report)
    return {
        "profile": profile.get("profile"),
        "profile_source": profile.get("profile_source", ""),
        "search_id": search_id,
        "total_results": len(results),
        "represented_topics": represented,
        "blind_spots": blind_spots,
        "live_validate": live_validate,
        "live_probe_reports": live_probe_reports,
        "coverage_warning": bool(blind_spots),
        "needs_user_branch_confirmation": bool(blind_spots),
    }

def literature_relevance_score(
    query: str,
    result: dict[str, Any],
    quality_assessment: dict[str, Any] | None = None,
) -> tuple[float, list[str], str, dict[str, Any]]:
    try:
        from ._literature_search import query_terms
        from ._utils import normalize_space, unique_preserve_order
    except ImportError:
        from _literature_search import query_terms
        from _utils import normalize_space, unique_preserve_order
    quality = quality_assessment if isinstance(quality_assessment, dict) else publication_quality_assessment(result)
    terms = query_terms(query)
    if not terms:
        components = {
            "text_score": 0.0,
            "recency_score": literature_recency_score(result),
            "impact_score": literature_impact_score(result),
            "venue_score": quality["venue_score"],
            "publication_quality_score": quality["quality_score"],
            "base_score": 0.0,
            "text_weight": 0.62,
            "recency_weight": 0.1,
            "impact_weight": 0.18,
            "venue_weight": 0.1,
        }
        return 0.0, [], "No query terms.", components

    title = normalize_space(result.get("title", "")).lower()
    abstract = normalize_space(result.get("abstract", "")).lower()
    citation = normalize_space(result.get("citation", "")).lower()
    title_matches = [term for term in terms if term in title]
    abstract_matches = [term for term in terms if term in abstract]
    citation_matches = [term for term in terms if term in citation]
    phrase = normalize_space(query).lower()
    phrase_bonus = 0.0
    if phrase and phrase in title:
        phrase_bonus += 0.35
    elif phrase and phrase in abstract:
        phrase_bonus += 0.2

    title_coverage = len(title_matches) / len(terms)
    abstract_coverage = len(abstract_matches) / len(terms)
    citation_coverage = len(citation_matches) / len(terms)
    text_score = min(1.0, 0.62 * title_coverage + 0.28 * abstract_coverage + 0.1 * citation_coverage + phrase_bonus)
    recency_score = literature_recency_score(result)
    impact_score = literature_impact_score(result)
    venue_score = quality["venue_score"]
    citation_field = infer_research_field(result)
    citation_baseline = field_citation_baseline(citation_field)
    if text_score <= 0:
        recency_weight = 0.04
        impact_weight = 0.04
        venue_weight = 0.02
    else:
        recency_weight = 0.1
        impact_weight = 0.18
        venue_weight = 0.1
    text_weight = 1.0 - recency_weight - impact_weight - venue_weight
    base_score = min(
        1.0,
        text_weight * text_score
        + recency_weight * recency_score
        + impact_weight * impact_score
        + venue_weight * venue_score,
    )
    score = min(1.0, round(base_score * quality["quality_score"], 4))
    components = {
        "text_score": round(text_score, 4),
        "recency_score": round(recency_score, 4),
        "impact_score": round(impact_score, 4),
        "citation_field": citation_field,
        "citation_baseline": round(citation_baseline, 2),
        "venue_score": round(venue_score, 4),
        "publication_quality_score": round(quality["quality_score"], 4),
        "base_score": round(base_score, 4),
        "text_weight": round(text_weight, 4),
        "recency_weight": round(recency_weight, 4),
        "impact_weight": round(impact_weight, 4),
        "venue_weight": round(venue_weight, 4),
    }
    matched = unique_preserve_order(title_matches + abstract_matches + citation_matches)
    reason = (
        f"title={len(title_matches)}/{len(terms)}, "
        f"abstract={len(abstract_matches)}/{len(terms)}, "
        f"citation={len(citation_matches)}/{len(terms)}, "
        f"phrase_bonus={round(phrase_bonus, 2)}, "
        f"recency={components['recency_score']}, "
        f"impact={components['impact_score']}, "
        f"venue={components['venue_score']}, "
        f"quality={components['publication_quality_score']}"
    )
    return score, matched, reason, components

def literature_recency_score(result: dict[str, Any]) -> float:
    year_text = str(result.get("year") or "")
    match = re.search(r"\b(19|20)\d{2}\b", year_text)
    if not match:
        return 0.25
    year = int(match.group(0))
    current_year = time.localtime().tm_year
    age = current_year - year
    if age <= 1:
        return 1.0
    if age <= 3:
        return 0.85
    if age <= 5:
        return 0.7
    if age <= 10:
        return 0.45
    return 0.2

def literature_impact_score(result: dict[str, Any]) -> float:
    try:
        from ._utils import numeric_value
    except ImportError:
        from _utils import numeric_value
    citation_count = numeric_value(result.get("citation_count"))
    influential_count = numeric_value(result.get("influential_citation_count"))
    field = infer_research_field(result)
    baseline = field_citation_baseline(field)
    if is_recent_paper(result, max_age=2) and citation_count <= 2:
        if publication_channel_is_strong(result):
            return 0.55
        return 0.35
    if citation_count <= 0 and influential_count <= 0:
        return 0.0
    citation_score = min(1.0, math.log1p(citation_count) / math.log1p(baseline))
    influential_score = min(1.0, math.log1p(influential_count) / math.log1p(max(50.0, baseline * 0.3)))
    return round(max(citation_score, 0.75 * citation_score + 0.25 * influential_score), 4)


def venue_evidence_assessment(
    result: dict[str, Any],
    *,
    quartile: str = "",
    flags: list[str] | None = None,
) -> dict[str, Any]:
    """Assess venue strength from curated and provider-native evidence.

    A small local venue catalogue is useful but cannot cover every legitimate
    journal in neuroscience, materials, climate, physics, chemistry, and the
    life sciences.  OpenAlex supplies source-core and field-normalized impact
    metadata for many works.  This function keeps the two evidence sources
    distinct: provider metrics create an auditable *metric-supported* L2
    route, rather than silently pretending that a previously unknown journal
    has a curated Q1 label.
    """
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space

    selected_flags = {str(flag or "") for flag in (flags or [])}
    payload = result.get("papergraph_input") if isinstance(result.get("papergraph_input"), dict) else {}
    venue_name = normalize_space(str(result.get("venue") or payload.get("venue") or "")).lower()
    metadata = result.get("venue_metadata")
    if not isinstance(metadata, dict):
        metadata = payload.get("venue_metadata") if isinstance(payload.get("venue_metadata"), dict) else {}
    metrics = result.get("citation_metrics") if isinstance(result.get("citation_metrics"), dict) else {}
    if not metrics and isinstance(payload.get("citation_metrics"), dict):
        metrics = payload["citation_metrics"]
    openalex_metrics = metrics.get("openalex") if isinstance(metrics.get("openalex"), dict) else {}
    percentile = (
        openalex_metrics.get("citation_normalized_percentile")
        if isinstance(openalex_metrics.get("citation_normalized_percentile"), dict)
        else {}
    )
    try:
        percentile_value = float(percentile.get("value"))
    except (TypeError, ValueError):
        percentile_value = 0.0
    try:
        fwci = float(openalex_metrics.get("fwci"))
    except (TypeError, ValueError):
        fwci = 0.0
    source_type = normalize_space(str(metadata.get("source_type") or "")).lower()
    source_is_core = bool(metadata.get("is_core"))
    formal_journal = source_type == "journal"
    citation_top_decile = bool(percentile.get("is_in_top_10_percent")) or percentile_value >= 0.90
    high_normalized_impact = citation_top_decile or fwci >= 1.5
    curated_top = (
        str(quartile or "").upper() == "Q1"
        or "reputable_venue" in selected_flags
        or str(result.get("venue_quality") or "") == "reputable"
        or is_reputable_venue(venue_name)
    )

    if "suspicious_venue_or_publisher" in selected_flags or "journal_quartile_suspicious" in selected_flags:
        status = "suspicious_venue"
        eligible_for_l2 = False
        reason = "venue is marked suspicious by the local quality assessment"
    elif curated_top:
        status = "curated_top_venue"
        eligible_for_l2 = True
        reason = "curated Q1 or reputable-venue evidence"
    elif formal_journal and source_is_core and high_normalized_impact:
        status = "provider_metric_supported_venue"
        eligible_for_l2 = True
        reason = "OpenAlex core journal plus field-normalized top-decile or FWCI evidence"
    elif formal_journal and source_is_core:
        status = "provider_core_journal_unconfirmed"
        eligible_for_l2 = False
        reason = "OpenAlex identifies a core journal, but no high normalized-impact evidence is available"
    elif formal_journal:
        status = "formal_journal_unverified"
        eligible_for_l2 = False
        reason = "formal journal metadata lacks curated or provider-metric top-venue evidence"
    else:
        status = "venue_unverified"
        eligible_for_l2 = False
        reason = "no curated or provider-native venue evidence"
    return {
        "status": status,
        "eligible_for_l2": eligible_for_l2,
        "source": (
            "curated_venue_catalogue"
            if curated_top
            else "openalex_source_and_normalized_impact"
            if metadata
            else "none"
        ),
        "source_is_core": source_is_core,
        "source_type": source_type,
        "citation_normalized_percentile": round(percentile_value, 6),
        "fwci": round(fwci, 4),
        "reason": reason,
    }


def venue_tier_assessment(
    result: dict[str, Any],
    *,
    quartile: str = "",
    flags: list[str] | None = None,
    venue_evidence: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Separate publication-channel calibre from a paper's evidentiary role.

    ``L2`` and ``L4`` describe the role a paper can play for the current
    scientific question.  They must not be reused as a claim that an L4 paper
    was published in an ordinary journal.  The tier below is intentionally
    provider- and domain-neutral: curated identities are a fallback, while
    OpenAlex source and normalized-impact metadata remain first-class evidence.
    """
    try:
        from ._models import PREPRINT_VENUES
        from ._utils import normalize_space
    except ImportError:
        from _models import PREPRINT_VENUES
        from _utils import normalize_space

    selected_flags = {str(flag or "") for flag in (flags or [])}
    payload = result.get("papergraph_input") if isinstance(result.get("papergraph_input"), dict) else {}
    venue = normalize_space(str(result.get("venue") or payload.get("venue") or "")).lower()
    metadata = result.get("venue_metadata") if isinstance(result.get("venue_metadata"), dict) else {}
    if not metadata and isinstance(payload.get("venue_metadata"), dict):
        metadata = payload["venue_metadata"]
    evidence = venue_evidence if isinstance(venue_evidence, dict) else {}
    source_is_core = bool(metadata.get("is_core")) or bool(evidence.get("source_is_core"))
    source_type = normalize_space(str(metadata.get("source_type") or evidence.get("source_type") or "")).lower()
    formal_journal = source_type == "journal" or any(
        "journal article" in str(item or "").lower()
        for item in (result.get("publication_types") or payload.get("publication_types") or [])
    )

    if "suspicious_venue_or_publisher" in selected_flags or "journal_quartile_suspicious" in selected_flags:
        return {
            "tier": "SUSPICIOUS",
            "source": "quality_suspicion_gate",
            "reason": "venue or publisher is marked suspicious",
        }
    if venue in PREPRINT_VENUES or "preprint_not_peer_reviewed" in selected_flags:
        return {
            "tier": "PREPRINT",
            "source": "publication_channel",
            "reason": "record is a preprint rather than a formal journal article",
        }
    if bool(evidence.get("eligible_for_l2")) or str(quartile or "").upper() == "Q1" or is_reputable_venue(venue):
        return {
            "tier": "TOP_VENUE",
            "source": str(evidence.get("source") or "curated_venue_identity"),
            "reason": str(evidence.get("reason") or "curated or provider-supported top venue"),
        }
    if formal_journal and source_is_core:
        return {
            "tier": "STRONG_FORMAL_VENUE",
            "source": "openalex_core_source",
            "reason": "OpenAlex identifies the source as a core journal, without enough impact evidence for TOP_VENUE",
        }
    if formal_journal or bool(venue):
        return {
            "tier": "FORMAL_VENUE_UNVERIFIED",
            "source": "source_metadata_incomplete",
            "reason": "formal publication record lacks sufficient curated or provider-native venue evidence",
        }
    return {
        "tier": "VENUE_UNVERIFIED",
        "source": "missing_venue_metadata",
        "reason": "no formal venue identity was supplied",
    }


def publication_quality_assessment(result: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._models import PREPRINT_VENUES
        from ._utils import normalize_space, numeric_value
    except ImportError:
        from _models import PREPRINT_VENUES
        from _utils import normalize_space, numeric_value
    cache_key = _paper_scoring_cache_key(result)
    with _LOCAL_SCORING_CACHE_LOCK:
        cached = _PUBLICATION_QUALITY_CACHE.get(cache_key)
    if cached is not None:
        return _cached_mapping_copy(cached)
    venue = normalize_space(result.get("venue", "")).lower()
    url_blob = " ".join(
        normalize_space(result.get(key, "")).lower()
        for key in ("url", "open_access_pdf", "doi")
    )
    provider = normalize_space(result.get("provider", "")).lower()
    citation_count = numeric_value(result.get("citation_count"))
    reference_count = numeric_value(result.get("reference_count"))
    metric = journal_metric_for_venue(venue)
    quartile = metric.get("quartile", "")
    quartile_score = journal_quartile_score(quartile)
    flags: list[str] = []
    criteria: list[str] = []
    suspicion_type = ""
    quality = 0.72
    venue_score = quartile_score if quartile else 0.45

    if not venue:
        flags.append("missing_venue")
        criteria.append("venue metadata is missing")
        quality -= 0.08
        venue_score = 0.35
    elif is_suspicious_venue(venue) or has_suspicious_publisher(url_blob):
        flags.append("suspicious_venue_or_publisher")
        suspicion_type = "predatory_or_vanity"
        criteria.append("venue/publisher matched curated suspicious list")
        quality -= 0.42
        venue_score = 0.0
    elif quartile == "suspicious":
        flags.append("suspicious_venue_or_publisher")
        flags.append("journal_quartile_suspicious")
        suspicion_type = "predatory_or_vanity"
        criteria.append("venue matched curated suspicious journal metric table")
        quality -= 0.42
        venue_score = 0.0
    elif quartile == "unclassified":
        flags.append("unclassified_venue")
        flags.append("requires_human_venue_review")
        criteria.append("venue matched curated unclassified/preprint/open-access table; manual review recommended")
        quality -= 0.06
        venue_score = quartile_score
    elif quartile:
        flags.append(f"journal_quartile_{quartile.lower()}")
        criteria.append(f"venue matched curated journal metric table: {quartile}")
        if quartile == "Q1":
            flags.append("reputable_venue")
            quality += 0.2
        elif quartile == "Q2":
            quality += 0.1
        elif quartile == "Q3":
            quality -= 0.04
        elif quartile == "Q4":
            quality -= 0.15
    elif is_reputable_venue(venue):
        flags.append("reputable_venue")
        criteria.append("venue matched curated reputable list")
        quality += 0.2
        venue_score = 1.0
    elif venue in PREPRINT_VENUES:
        flags.append("preprint_not_peer_reviewed")
        criteria.append("venue is a preprint server, not final peer-reviewed venue")
        quality -= 0.05
        venue_score = 0.6
    else:
        flags.append("unverified_venue")
        criteria.append("venue did not match suspicious, reputable, preprint, or curated quartile tables")

    if citation_count <= 0:
        if is_recent_paper(result, max_age=2):
            flags.append("new_paper_protection")
            criteria.append("paper is within 2-year protection window; low citations are not treated as low quality")
        elif is_mature_paper(result, minimum_age=2):
            flags.append("zero_citations_mature_paper")
            criteria.append("paper is older than 2 years and has zero Semantic Scholar citations")
            quality -= 0.16
        else:
            flags.append("zero_citations_recent_or_unknown")
            criteria.append("paper age unknown/recent with zero citations")
            quality -= 0.04
    elif citation_count >= 200:
        flags.append("highly_cited")
        criteria.append("citation count exceeds high-impact threshold")
        quality += 0.12
    elif citation_count >= 50:
        flags.append("well_cited")
        criteria.append("citation count exceeds medium/high threshold")
        quality += 0.08
    elif citation_count >= 10:
        flags.append("some_citations")
        criteria.append("citation count exceeds minimum nontrivial threshold")
        quality += 0.04

    if reference_count == 0 and provider == "semantic_scholar":
        if is_recent_paper(result, max_age=2):
            flags.append("incomplete_s2_metadata_recent")
            criteria.append("Semantic Scholar reference metadata is missing for a recent paper; marked for data completeness review")
        else:
            flags.append("missing_reference_count")
            criteria.append("Semantic Scholar reports zero references for a non-recent paper")
            quality -= 0.04

    quality = round(max(0.1, min(1.0, quality)), 4)
    venue_evidence = venue_evidence_assessment(
        result,
        quartile=quartile,
        flags=flags,
    )
    venue_tier = venue_tier_assessment(
        result,
        quartile=quartile,
        flags=flags,
        venue_evidence=venue_evidence,
    )
    assessment = {
        "quality_score": quality,
        "venue_score": round(max(0.0, min(1.0, venue_score)), 4),
        "venue_quality": venue_quality_label(flags),
        "journal_quartile": quartile,
        "journal_metric_source": metric.get("source", ""),
        "inferred_field": infer_research_field(result),
        "suspicion_type": suspicion_type,
        "flags": flags,
        "criteria": criteria,
        "reason": "; ".join(criteria),
        "venue_evidence": venue_evidence,
        "venue_tier": venue_tier,
    }
    with _LOCAL_SCORING_CACHE_LOCK:
        _bounded_cache_store(_PUBLICATION_QUALITY_CACHE, cache_key, _cached_mapping_copy(assessment))
    return assessment

def is_suspicious_venue(venue: str) -> bool:
    try:
        from ._models import SUSPICIOUS_VENUES
    except ImportError:
        from _models import SUSPICIOUS_VENUES
    if venue in SUSPICIOUS_VENUES:
        return True
    return any(pattern in venue for pattern in SUSPICIOUS_VENUES)

def has_suspicious_publisher(text: str) -> bool:
    try:
        from ._models import SUSPICIOUS_PUBLISHER_PATTERNS
    except ImportError:
        from _models import SUSPICIOUS_PUBLISHER_PATTERNS
    return any(pattern in text for pattern in SUSPICIOUS_PUBLISHER_PATTERNS)

def is_reputable_venue(venue: str) -> bool:
    try:
        from ._models import REPUTABLE_VENUES, REPUTABLE_VENUE_PATTERNS
    except ImportError:
        from _models import REPUTABLE_VENUES, REPUTABLE_VENUE_PATTERNS
    normalized_venue = str(venue or "").strip().lower()
    if normalized_venue in REPUTABLE_VENUES:
        return True
    # The curated catalogue contains the flagship ``Nature`` title but cannot
    # enumerate every specialist title in the peer-reviewed Nature portfolio.
    # This is a publication-channel fallback, deliberately independent of
    # field vocabulary and of whether the paper is direct evidence for the
    # active question.  Directness is enforced separately through
    # ``research_role`` and the L2 qualification gate.
    if normalized_venue.startswith("nature "):
        return True
    generic_names = {"nature", "science", "cell", "ecology", "oikos"}
    if any(name not in generic_names and name in normalized_venue for name in REPUTABLE_VENUES):
        return True
    return any(pattern in normalized_venue for pattern in REPUTABLE_VENUE_PATTERNS)

def journal_metric_for_venue(venue: str) -> dict[str, str]:
    try:
        from ._models import JOURNAL_METRICS
        from ._utils import normalize_space
    except ImportError:
        from _models import JOURNAL_METRICS
        from _utils import normalize_space
    if not venue:
        return {}
    venue = normalize_space(venue).lower()
    if venue in JOURNAL_METRICS:
        return JOURNAL_METRICS[venue]
    venue_compact = re.sub(r"[^a-z0-9]+", "", venue)
    generic_names = {"arxiv", "nature", "science", "cell", "ecology", "oikos", "research", "small", "chem"}
    for name, metric in JOURNAL_METRICS.items():
        name_compact = re.sub(r"[^a-z0-9]+", "", name)
        if name_compact == venue_compact:
            return metric
        if name not in generic_names and name in venue:
            return metric
    return {}

def journal_quartile_score(quartile: str) -> float:
    normalized = str(quartile or "").strip().lower()
    return {
        "q1": 1.0,
        "q2": 0.7,
        "q3": 0.4,
        "q4": 0.2,
        "unknown": 0.3,
        "unclassified": 0.2,
        "suspicious": 0.0,
    }.get(normalized, 0.3)

def is_mature_paper(result: dict[str, Any], minimum_age: int = 2) -> bool:
    year_text = str(result.get("year") or "")
    match = re.search(r"\b(19|20)\d{2}\b", year_text)
    if not match:
        return False
    return time.localtime().tm_year - int(match.group(0)) >= minimum_age

def is_recent_paper(result: dict[str, Any], max_age: int = 2) -> bool:
    year_text = str(result.get("year") or "")
    match = re.search(r"\b(19|20)\d{2}\b", year_text)
    if not match:
        return False
    return time.localtime().tm_year - int(match.group(0)) <= max_age

def publication_channel_is_strong(result: dict[str, Any]) -> bool:
    quality = publication_quality_assessment_no_citation(result)
    return quality.get("venue_quality") == "reputable" or quality.get("journal_quartile") in {"Q1", "Q2"}

def publication_quality_assessment_no_citation(result: dict[str, Any]) -> dict[str, Any]:
    try:
        from ._models import PREPRINT_VENUES
        from ._utils import normalize_space
    except ImportError:
        from _models import PREPRINT_VENUES
        from _utils import normalize_space
    venue = normalize_space(result.get("venue", "")).lower()
    url_blob = " ".join(normalize_space(result.get(key, "")).lower() for key in ("url", "open_access_pdf", "doi"))
    metric = journal_metric_for_venue(venue)
    if not venue:
        return {"venue_quality": "missing", "journal_quartile": ""}
    if is_suspicious_venue(venue) or has_suspicious_publisher(url_blob) or metric.get("quartile") == "suspicious":
        return {"venue_quality": "suspicious", "journal_quartile": metric.get("quartile", "")}
    if metric.get("quartile") in {"Q1", "Q2"} or is_reputable_venue(venue):
        return {"venue_quality": "reputable", "journal_quartile": metric.get("quartile", "")}
    if venue in PREPRINT_VENUES:
        return {"venue_quality": "preprint", "journal_quartile": ""}
    return {"venue_quality": "unverified", "journal_quartile": metric.get("quartile", "")}

def infer_research_field(result: dict[str, Any]) -> str:
    try:
        from ._models import research_field_for_text
        from ._utils import normalize_space
    except ImportError:
        from _models import research_field_for_text
        from _utils import normalize_space
    cache_key = _paper_scoring_cache_key(result)
    with _LOCAL_SCORING_CACHE_LOCK:
        cached = _RESEARCH_FIELD_CACHE.get(cache_key)
    if cached is not None:
        return cached
    text = " ".join(
        normalize_space(result.get(key, "")).lower()
        for key in ("title", "abstract", "venue")
    )
    arxiv_field = infer_arxiv_field(result)
    if arxiv_field:
        inferred = arxiv_field
        with _LOCAL_SCORING_CACHE_LOCK:
            _bounded_cache_store(_RESEARCH_FIELD_CACHE, cache_key, inferred)
        return inferred
    embedding_field = infer_field_by_embedding(result)
    if embedding_field:
        inferred = embedding_field
        with _LOCAL_SCORING_CACHE_LOCK:
            _bounded_cache_store(_RESEARCH_FIELD_CACHE, cache_key, inferred)
        return inferred
    model_organisms = (
        "drosophila", "zebrafish", "caenorhabditis", "c. elegans", "arabidopsis",
        "mus musculus", "murine", "xenopus", "saccharomyces", "yeast",
    )
    if any(term in text for term in model_organisms):
        inferred = "biology"
        with _LOCAL_SCORING_CACHE_LOCK:
            _bounded_cache_store(_RESEARCH_FIELD_CACHE, cache_key, inferred)
        return inferred
    if catalog_mechanism_evidence(result, target_field="biology")["qualified"]:
        inferred = "biology"
        with _LOCAL_SCORING_CACHE_LOCK:
            _bounded_cache_store(_RESEARCH_FIELD_CACHE, cache_key, inferred)
        return inferred
    metric = journal_metric_for_venue(normalize_space(result.get("venue", "")).lower())
    if metric.get("field"):
        inferred = metric["field"]
        with _LOCAL_SCORING_CACHE_LOCK:
            _bounded_cache_store(_RESEARCH_FIELD_CACHE, cache_key, inferred)
        return inferred
    catalog_field = research_field_for_text(text)
    inferred = catalog_field if catalog_field != "general" else "general"
    with _LOCAL_SCORING_CACHE_LOCK:
        _bounded_cache_store(_RESEARCH_FIELD_CACHE, cache_key, inferred)
    return inferred

def fields_are_incompatible(target_field: str, result_field: str) -> bool:
    try:
        from ._models import research_domain_for_field
    except ImportError:
        from _models import research_domain_for_field
    target = str(target_field or "general")
    result = str(result_field or "general")
    if not target or not result or target in {"general", "multidisciplinary"} or result in {"general", "multidisciplinary"}:
        return False
    if target == result:
        return False
    target_domain = research_domain_for_field(target)
    result_domain = research_domain_for_field(result)
    if target_domain != "general" and target_domain == result_domain:
        distinct_physics_fields = {
            "astrophysics",
            "high_energy_physics",
            "nuclear_physics",
            "complex_systems",
            "instrumentation",
            "photonics",
        }
        if target in distinct_physics_fields and result in distinct_physics_fields:
            return True
        return False
    related_domains = (
        {"physics", "mathematics", "statistics", "electrical_engineering"},
        {"physics", "chemistry", "materials_science", "engineering", "electrical_engineering", "earth_environmental_science"},
        {"computer_science", "mathematics", "statistics", "engineering", "electrical_engineering"},
        {"biology", "quantitative_biology", "medicine", "statistics"},
        {"chemistry", "biology", "quantitative_biology", "medicine", "agriculture", "earth_environmental_science", "materials_science"},
        {"biology", "agriculture", "earth_environmental_science", "engineering"},
        {"quantitative_finance", "economics", "mathematics", "statistics"},
    )
    if any(target_domain in group and result_domain in group for group in related_domains):
        return False
    groups = [
        {"physics", "astrophysics", "high_energy_physics", "nuclear_physics", "condensed_matter", "quantum_physics", "complex_systems", "computational_science", "instrumentation", "photonics"},
        {"chemistry", "chemical_biology", "biochemistry", "electrochemistry"},
        {"materials_science", "materials", "materials_energy", "condensed_matter", "electrochemistry"},
        {"biology", "quantitative_biology", "biomedical", "medicine", "digital_medicine", "biophysics", "plant_biology", "ecology", "biochemistry", "cell_biology", "developmental_biology", "molecular_biology", "genetics", "genomics", "systems_biology", "synthetic_biology"},
        {"agriculture", "plant_biology", "ecology", "agriculture", "food_science"},
        {"computer_science", "artificial_intelligence", "statistics", "information_theory", "robotics"},
        {"engineering", "electrical_engineering", "automation_control", "energy_engineering", "electronics", "communications"},
        {"earth_environmental_science", "environmental_science", "earth_science", "ecology", "agriculture"},
        {"mathematics", "statistics", "information_theory"},
        {"quantitative_finance", "finance", "economics", "social_science"},
    ]
    return not any(target in group and result in group for group in groups)

def infer_arxiv_field(result: dict[str, Any]) -> str:
    try:
        from ._literature_search import arxiv_categories
        from ._models import ARXIV_CATEGORY_FIELD_MAP
        from ._utils import normalize_space
    except ImportError:
        from _literature_search import arxiv_categories
        from _models import ARXIV_CATEGORY_FIELD_MAP
        from _utils import normalize_space
    categories: list[str] = []
    raw = result.get("arxiv_categories")
    if isinstance(raw, list):
        categories.extend(str(item) for item in raw)
    elif isinstance(raw, str):
        categories.extend(re.split(r"[\s,;]+", raw))
    payload = result.get("papergraph_input") if isinstance(result.get("papergraph_input"), dict) else {}
    raw_payload = payload.get("arxiv_categories")
    if isinstance(raw_payload, list):
        categories.extend(str(item) for item in raw_payload)
    elif isinstance(raw_payload, str):
        categories.extend(re.split(r"[\s,;]+", raw_payload))
    for category in categories:
        normalized = normalize_space(category).lower()
        if not normalized:
            continue
        if normalized in ARXIV_CATEGORY_FIELD_MAP:
            return ARXIV_CATEGORY_FIELD_MAP[normalized]
        prefix = normalized.split(".", 1)[0]
        if prefix in ARXIV_CATEGORY_FIELD_MAP:
            return ARXIV_CATEGORY_FIELD_MAP[prefix]
    return ""

def field_citation_baseline(field: str) -> float:
    return {
        "astrophysics": 500.0,
        "high_energy_physics": 250.0,
        "nuclear_physics": 250.0,
        "complex_systems": 300.0,
        "biophysics": 500.0,
        "computational_science": 350.0,
        "earth_science": 450.0,
        "instrumentation": 300.0,
        "information_theory": 300.0,
        "ecology": 300.0,
        "environmental_science": 450.0,
        "materials_energy": 250.0,
        "materials": 350.0,
        "electrochemistry": 200.0,
        "chemistry": 500.0,
        "physics": 350.0,
        "biology": 600.0,
        "plant_biology": 500.0,
        "medicine": 800.0,
        "digital_medicine": 800.0,
        "computer_science": 500.0,
        "artificial_intelligence": 600.0,
        "communications": 500.0,
        "biomedical": 800.0,
        "biochemistry": 700.0,
        "chemical_biology": 600.0,
        "multidisciplinary": 600.0,
        "mathematics": 250.0,
        "statistics": 300.0,
        "quantitative_biology": 500.0,
        "quantitative_finance": 300.0,
        "electrical_engineering": 400.0,
        "automation_control": 350.0,
        "energy_engineering": 500.0,
        "agriculture": 250.0,
        "electronics": 500.0,
        "robotics": 450.0,
        "photonics": 400.0,
        "transportation": 300.0,
        "finance": 300.0,
        "economics": 300.0,
        "social_science": 350.0,
        "general": 500.0,
    }.get(field, 400.0)

def venue_quality_label(flags: list[str]) -> str:
    if "suspicious_venue_or_publisher" in flags:
        return "suspicious"
    if "reputable_venue" in flags:
        return "reputable"
    if "preprint_not_peer_reviewed" in flags:
        return "preprint"
    if "unclassified_venue" in flags:
        return "unclassified"
    if "missing_venue" in flags:
        return "missing"
    return "unverified"

def strip_markup(text: str) -> str:
    try:
        from ._utils import normalize_space
    except ImportError:
        from _utils import normalize_space
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_space(text)

