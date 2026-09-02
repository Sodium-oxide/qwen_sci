"""Pre-PaperGraph retrieval contracts and candidate-discovery utilities.

This module intentionally stops before evidence import.  Provider capabilities,
query execution diagnostics, canonical identity, and fusion scores can decide
which records are read first; they must not decide evidence strength, source
role, directness, independence, gap validity, or hypothesis eligibility.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
import unicodedata
from typing import Any, Mapping, Sequence


_IDENTITY_PRIORITY = (
    "doi",
    "openalex",
    "arxiv",
    "semantic_scholar",
    "pmid",
    "provider_uid",
    "title",
)
_STABLE_IDENTITY_KINDS = frozenset(_IDENTITY_PRIORITY[:-1])
_SECRET_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|authorization|bearer|credential|secret|password|access[_-]?token|refresh[_-]?token|client[_-]?secret)",
    flags=re.IGNORECASE,
)
_BEARER_VALUE_PATTERN = re.compile(r"\bbearer\s+[^\s,;]+", flags=re.IGNORECASE)
_INLINE_SECRET_PATTERN = re.compile(
    r"\b(api[_-]?key|authorization|credential|secret|password|access[_-]?token|refresh[_-]?token|client[_-]?secret)\s*([=:])\s*[^\s,;]+",
    flags=re.IGNORECASE,
)
_WHITESPACE_PATTERN = re.compile(r"\s+")
_IDENTIFIER_PATTERN = re.compile(r"[^a-z0-9]+")
_MISSING_IDENTIFIER_TOKENS = frozenset({"", "none", "null", "nan", "n/a", "-"})
_OPENALEX_BOOLEAN_TOKEN_PATTERN = re.compile(r"\b(?:AND|OR|NOT)\b", flags=re.IGNORECASE)
_OPENALEX_SEARCH_TOKEN_PATTERN = re.compile(r"(?u)[^\W_][\w+./-]*")
_OPENALEX_SEARCH_MAX_TERMS = 16
_OPENALEX_SEARCH_MAX_CHARS = 180

# These versions are part of retrieval execution identity.  A change here can
# alter whether a provider-safe lowering is admissible, so callers must never
# reuse a former local-compilation failure as though it were a completed search.
PROVIDER_QUERY_COMPILATION_POLICY_VERSION = "provider_query_compilation_v3"
ANCHOR_MATCH_POLICY_VERSION = "provider_normalized_token_sequence_v1"
RETRIEVAL_ANCHOR_CONTRACT_SCHEMA_V3 = "retrieval_anchor_contract_v3"

_CURRENT_ANCHOR_OK_STATUSES = frozenset({"not_requested", "verified"})


@dataclass(frozen=True)
class LiteratureProviderCapabilities:
    """A discovery-layer capability contract for one literature provider."""

    provider: str
    status: str
    query_syntax: str
    supported_query_features: tuple[str, ...]
    supports_abstracts: bool
    supports_doi: bool
    supports_venue: bool
    supports_citation_counts: bool
    supports_citation_edges: bool
    supports_pdf_links: bool
    content_types: tuple[str, ...]
    allowed_layers: tuple[str, ...]
    allows_socrates_direct_evidence: bool
    required_config: tuple[str, ...]
    optional_config: tuple[str, ...]
    rate_limit_policy: str
    supports_lanes: tuple[str, ...]


_ALL_LAYERS = ("L0_review", "L1_milestone", "L2_top_latest", "L3_preprint", "L4_regular")
_NON_PREPRINT_LAYERS = ("L0_review", "L1_milestone", "L2_top_latest", "L4_regular")
_SCIENCEDIRECT_DISCOVERY_LAYERS = ("L0_review", "L2_top_latest", "L4_regular")

LITERATURE_PROVIDER_CAPABILITIES: dict[str, LiteratureProviderCapabilities] = {
    "sciencedirect": LiteratureProviderCapabilities(
        provider="sciencedirect",
        status="live",
        query_syntax="ScienceDirect Search API text query; the connector sends relevance-ranked metadata requests",
        supported_query_features=("text", "relevance_sort", "offset"),
        supports_abstracts=True,
        supports_doi=True,
        supports_venue=True,
        supports_citation_counts=True,
        supports_citation_edges=False,
        supports_pdf_links=False,
        content_types=("journal_article", "review", "conference_paper"),
        allowed_layers=_SCIENCEDIRECT_DISCOVERY_LAYERS,
        allows_socrates_direct_evidence=True,
        required_config=("SCIENCEDIRECT_API_KEY",),
        optional_config=("SCIENCE_SCIENCEDIRECT_ENABLED",),
        rate_limit_policy="connector-owned credential-scoped response cache, global request interval, bounded retry, and run budget; it discovers metadata only and never asserts full-text access",
        supports_lanes=("direct_relevance", "impact", "recent_direct_evidence", "review_map", "mechanism_intervention"),
    ),
    "openalex": LiteratureProviderCapabilities(
        provider="openalex",
        status="live",
        query_syntax="OpenAlex Works search text with provider filters managed by the connector",
        supported_query_features=("text", "publication_year", "open_access", "type", "topics"),
        supports_abstracts=True,
        supports_doi=True,
        supports_venue=True,
        supports_citation_counts=True,
        supports_citation_edges=True,
        supports_pdf_links=True,
        content_types=("journal_article", "review", "conference_paper", "preprint", "dataset"),
        allowed_layers=_ALL_LAYERS,
        allows_socrates_direct_evidence=True,
        required_config=(),
        optional_config=("OPENALEX_API_KEY", "SCIENCE_OPENALEX_MAILTO", "SCIENCE_OPENALEX_ENABLED"),
        rate_limit_policy="connector-owned cache, global run budget, and a hard maximum of six requests per second",
        supports_lanes=("direct_relevance", "impact", "recent_direct_evidence", "review_map", "mechanism_intervention"),
    ),
    "semantic_scholar": LiteratureProviderCapabilities(
        provider="semantic_scholar",
        status="live",
        query_syntax="Semantic Scholar Graph API search text; selected enrichment and graph expansion are connector-controlled",
        supported_query_features=("text", "year", "fields_of_study", "open_access_pdf", "publication_types"),
        supports_abstracts=True,
        supports_doi=True,
        supports_venue=True,
        supports_citation_counts=True,
        supports_citation_edges=True,
        supports_pdf_links=True,
        content_types=("journal_article", "review", "conference_paper", "preprint"),
        allowed_layers=_NON_PREPRINT_LAYERS,
        allows_socrates_direct_evidence=False,
        required_config=(),
        optional_config=("SEMANTIC_SCHOLAR_API_KEY",),
        rate_limit_policy="connector-owned cooldown, bounded retries, response cache, and a run budget shared with graph traffic",
        supports_lanes=("direct_relevance", "impact", "recent_direct_evidence", "review_map"),
    ),
    "pubmed": LiteratureProviderCapabilities(
        provider="pubmed",
        status="live",
        query_syntax="NCBI PubMed E-utilities term syntax",
        supported_query_features=("text", "boolean", "field_tags", "publication_date", "publication_type", "mesh"),
        supports_abstracts=True,
        supports_doi=True,
        supports_venue=True,
        supports_citation_counts=False,
        supports_citation_edges=False,
        supports_pdf_links=False,
        content_types=("journal_article", "review", "clinical_trial", "meta_analysis"),
        allowed_layers=_NON_PREPRINT_LAYERS,
        allows_socrates_direct_evidence=True,
        required_config=(),
        optional_config=(),
        rate_limit_policy="connector-owned NCBI request handling and bounded provider calls",
        supports_lanes=("direct_relevance", "recent_direct_evidence", "review_map", "mechanism_intervention"),
    ),
    "arxiv": LiteratureProviderCapabilities(
        provider="arxiv",
        status="live",
        query_syntax="arXiv Atom API search query",
        supported_query_features=("text", "category", "submitted_date"),
        supports_abstracts=True,
        supports_doi=True,
        supports_venue=False,
        supports_citation_counts=False,
        supports_citation_edges=False,
        supports_pdf_links=True,
        content_types=("preprint",),
        allowed_layers=("L3_preprint",),
        allows_socrates_direct_evidence=False,
        required_config=(),
        optional_config=(),
        rate_limit_policy="connector-owned request interval, cooldown, and circuit state",
        supports_lanes=("recent_direct_evidence", "mechanism_intervention"),
    ),
    "biorxiv": LiteratureProviderCapabilities(
        provider="biorxiv",
        status="live",
        query_syntax="bioRxiv recent-feed scan with local lexical relevance filter",
        supported_query_features=("text", "date_window", "category"),
        supports_abstracts=True,
        supports_doi=True,
        supports_venue=False,
        supports_citation_counts=False,
        supports_citation_edges=False,
        supports_pdf_links=False,
        content_types=("preprint",),
        allowed_layers=("L3_preprint",),
        allows_socrates_direct_evidence=False,
        required_config=(),
        optional_config=(),
        rate_limit_policy="connector-owned bounded feed scan and short-lived zero-result cache",
        supports_lanes=("recent_direct_evidence", "mechanism_intervention"),
    ),
    "medrxiv": LiteratureProviderCapabilities(
        provider="medrxiv",
        status="live",
        query_syntax="medRxiv recent-feed scan with local lexical relevance filter",
        supported_query_features=("text", "date_window", "category"),
        supports_abstracts=True,
        supports_doi=True,
        supports_venue=False,
        supports_citation_counts=False,
        supports_citation_edges=False,
        supports_pdf_links=False,
        content_types=("preprint",),
        allowed_layers=("L3_preprint",),
        allows_socrates_direct_evidence=False,
        required_config=(),
        optional_config=(),
        rate_limit_policy="connector-owned bounded feed scan and short-lived zero-result cache",
        supports_lanes=("recent_direct_evidence", "mechanism_intervention"),
    ),
    "chemrxiv": LiteratureProviderCapabilities(
        provider="chemrxiv",
        status="live",
        query_syntax="Crossref bibliographic text query restricted to the ChemRxiv posted-content prefix",
        supported_query_features=("text", "posted_content", "doi_prefix"),
        supports_abstracts=False,
        supports_doi=True,
        supports_venue=False,
        supports_citation_counts=False,
        supports_citation_edges=False,
        supports_pdf_links=False,
        content_types=("preprint",),
        allowed_layers=("L3_preprint",),
        allows_socrates_direct_evidence=False,
        required_config=(),
        optional_config=(),
        rate_limit_policy="connector-owned Crossref request handling",
        supports_lanes=("recent_direct_evidence", "mechanism_intervention"),
    ),
}


def normalize_provider_name(provider: Any) -> str:
    return str(provider or "").strip().lower().replace("-", "_").replace(" ", "_")


def get_literature_provider_capabilities(provider: Any) -> LiteratureProviderCapabilities:
    """Return the registered contract or raise a clear error for an unknown provider."""

    normalized = normalize_provider_name(provider)
    if normalized not in LITERATURE_PROVIDER_CAPABILITIES:
        raise ValueError(f"Unknown literature provider capability: {provider}")
    return LITERATURE_PROVIDER_CAPABILITIES[normalized]


def list_literature_provider_capabilities() -> list[dict[str, Any]]:
    return [asdict(LITERATURE_PROVIDER_CAPABILITIES[name]) for name in sorted(LITERATURE_PROVIDER_CAPABILITIES)]


def _normalize_space(value: Any) -> str:
    return _WHITESPACE_PATTERN.sub(" ", str(value or "").strip())


def normalize_optional_identifier(value: Any) -> str:
    """Return a usable external identifier or an empty string for a missing sentinel.

    Providers encode absent optional identifiers in several scalar forms.  This
    function is intentionally limited to identifier fields; ordinary text such
    as titles must retain its original semantics.
    """

    normalized = _normalize_space(value)
    return "" if normalized.casefold() in _MISSING_IDENTIFIER_TOKENS else normalized


def _normalize_identifier(value: Any) -> str:
    return _IDENTIFIER_PATTERN.sub("_", str(value or "").strip().lower()).strip("_")


def _normalize_doi(value: Any) -> str:
    doi = normalize_optional_identifier(value).lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "http://dx.doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return normalize_optional_identifier(doi.strip().rstrip(".,;)"))


def _normalize_openalex_id(value: Any) -> str:
    identifier = normalize_optional_identifier(value).lower()
    for prefix in ("https://openalex.org/", "http://openalex.org/", "openalex:"):
        if identifier.startswith(prefix):
            identifier = identifier[len(prefix):]
    return _normalize_identifier(normalize_optional_identifier(identifier))


def _normalize_arxiv_id(value: Any) -> str:
    identifier = normalize_optional_identifier(value).lower()
    for prefix in ("https://arxiv.org/abs/", "http://arxiv.org/abs/", "arxiv:"):
        if identifier.startswith(prefix):
            identifier = identifier[len(prefix):]
    return _normalize_identifier(normalize_optional_identifier(identifier))


def _normalize_semantic_scholar_id(value: Any) -> str:
    return _normalize_identifier(normalize_optional_identifier(value))


def _normalize_pmid(value: Any) -> str:
    identifier = normalize_optional_identifier(value).lower()
    for prefix in ("pmid:", "https://pubmed.ncbi.nlm.nih.gov/"):
        if identifier.startswith(prefix):
            identifier = identifier[len(prefix):]
    return _normalize_identifier(normalize_optional_identifier(identifier.rstrip("/")))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_nonempty(*values: Any) -> str:
    for value in values:
        normalized = _normalize_space(value)
        if normalized:
            return normalized
    return ""


def _identifier_values(value: Any) -> Sequence[Any]:
    if isinstance(value, (list, tuple, set)):
        return tuple(value)
    return (value,)


def _first_optional_identifier(*values: Any) -> str:
    for value in values:
        for raw_value in _identifier_values(value):
            normalized = normalize_optional_identifier(raw_value)
            if normalized:
                return normalized
    return ""


def _candidate_value(candidate: Mapping[str, Any], key: str, *aliases: str) -> str:
    payload = _mapping(candidate.get("papergraph_input"))
    external_ids = _mapping(candidate.get("external_ids"))
    payload_external_ids = _mapping(payload.get("external_ids"))
    values: list[Any] = [candidate.get(key), payload.get(key)]
    for alias in (key, *aliases):
        values.extend((external_ids.get(alias), payload_external_ids.get(alias)))
    return _first_optional_identifier(*values)


def canonical_paper_identity(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Construct a conservative, provider-neutral canonical paper identity.

    Normalized title is only a last-resort identity.  It is deliberately not
    supplied as a matching alias when any stable external identifier exists.
    """

    doi = _normalize_doi(_candidate_value(candidate, "doi"))
    openalex = _normalize_openalex_id(_candidate_value(candidate, "openalex_id", "openalex"))
    arxiv = _normalize_arxiv_id(_candidate_value(candidate, "arxiv_id", "arxiv"))
    semantic_scholar = _normalize_semantic_scholar_id(
        _candidate_value(candidate, "semantic_scholar_id", "semantic_scholar", "s2")
    )
    pmid = _normalize_pmid(_candidate_value(candidate, "pmid", "pubmed", "pubmed_id"))
    provider_uid = _normalize_identifier(
        _first_optional_identifier(
            candidate.get("provider_uid"),
            candidate.get("provider_id"),
            candidate.get("paper_id"),
            candidate.get("uid"),
        )
    )
    title = _normalize_identifier(
        _first_nonempty(candidate.get("title"), _mapping(candidate.get("papergraph_input")).get("title"), candidate.get("citation"))
    )
    raw_aliases = {
        "doi": doi,
        "openalex": openalex,
        "arxiv": arxiv,
        "semantic_scholar": semantic_scholar,
        "pmid": pmid,
        "provider_uid": provider_uid,
        "title": title,
    }
    aliases = {kind: [value] for kind, value in raw_aliases.items() if value}
    for kind in _IDENTITY_PRIORITY:
        value = raw_aliases.get(kind, "")
        if value:
            return {
                "canonical_key": f"{kind}:{value}",
                "identity_kind": kind,
                "aliases": aliases,
                "matching_aliases": _matching_aliases(aliases),
            }
    return {
        "canonical_key": "title:unknown",
        "identity_kind": "title",
        "aliases": {},
        "matching_aliases": (),
    }


def _matching_aliases(aliases: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    stable = [f"{kind}:{value}" for kind in _STABLE_IDENTITY_KINDS for value in aliases.get(kind, ()) if value]
    if stable:
        return tuple(stable)
    return tuple(f"title:{value}" for value in aliases.get("title", ()) if value)


def _alias_values(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        return {}
    aliases: dict[str, list[str]] = {}
    for kind, raw_values in value.items():
        normalized_kind = str(kind or "").strip()
        values = raw_values if isinstance(raw_values, (list, tuple, set)) else [raw_values]
        for raw in values:
            normalized = (
                _normalize_alias_identifier(normalized_kind, raw)
                if normalized_kind in _STABLE_IDENTITY_KINDS
                else _normalize_space(raw)
            )
            if normalized and normalized not in aliases.setdefault(normalized_kind, []):
                aliases[normalized_kind].append(normalized)
    return aliases


def _normalize_alias_identifier(kind: str, value: Any) -> str:
    normalizers = {
        "doi": _normalize_doi,
        "openalex": _normalize_openalex_id,
        "arxiv": _normalize_arxiv_id,
        "semantic_scholar": _normalize_semantic_scholar_id,
        "pmid": _normalize_pmid,
        "provider_uid": lambda raw: _normalize_identifier(normalize_optional_identifier(raw)),
    }
    normalizer = normalizers.get(kind)
    return normalizer(value) if normalizer else normalize_optional_identifier(value)


def _merge_alias_maps(*values: Any) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for value in values:
        for kind, identifiers in _alias_values(value).items():
            bucket = merged.setdefault(kind, [])
            for identifier in identifiers:
                if identifier not in bucket:
                    bucket.append(identifier)
    return {kind: merged[kind] for kind in sorted(merged)}


def _merge_scalar_or_list(existing: Any, incoming: Any) -> Any:
    if isinstance(existing, list) or isinstance(incoming, list):
        values = list(existing) if isinstance(existing, list) else ([existing] if existing else [])
        for value in (incoming if isinstance(incoming, list) else [incoming]):
            if value not in values and value not in (None, ""):
                values.append(value)
        return values
    return existing if existing not in (None, "") else incoming


_DIRECT_EVIDENCE_KINDS = {
    "theoretical_framework",
    "experimental_evidence",
    "mechanism_discovery",
    "causal_validation",
    "causal_identification",
    "association",
}


def evidence_kind_from_query_branch(branch: Any) -> str:
    """Return the direct-evidence lane encoded in a retrieval branch."""

    normalized = _normalize_space(branch).lower()
    if "mechanism_discovery" in normalized:
        return "mechanism_discovery"
    if "causal_validation" in normalized:
        return "causal_validation"
    if "theoretical_framework" in normalized:
        return "theoretical_framework"
    if "experimental_evidence" in normalized:
        return "experimental_evidence"
    return ""


def _unique_text_values(*values: Any) -> list[str]:
    output: list[str] = []
    for value in values:
        items = value if isinstance(value, (list, tuple, set)) else [value]
        for item in items:
            normalized = _normalize_space(item)
            if normalized and normalized not in output:
                output.append(normalized)
    return output


def _merge_positive_count_maps(*values: Any) -> dict[str, int]:
    merged: dict[str, int] = {}
    for value in values:
        if not isinstance(value, Mapping):
            continue
        for raw_key, raw_count in value.items():
            key = _normalize_space(raw_key)
            if not key:
                continue
            try:
                count = max(0, int(raw_count or 0))
            except (TypeError, ValueError):
                continue
            if count:
                merged[key] = merged.get(key, 0) + count
    return merged


def annotate_candidate_query_provenance(
    candidate: Mapping[str, Any],
    *,
    query_branch: str = "",
    evidence_kind: str = "",
    provider: str = "",
    raw_hit_count: int = 0,
) -> dict[str, Any]:
    """Attach lossless query-lane provenance to one discovery hit.

    Candidate identity fusion is intentionally allowed to combine provider
    descriptions of one paper.  It must not erase the fact that the paper
    matched more than one semantic query branch.  ``query_branch`` remains a
    backwards-compatible *primary* branch; the ``matched_*`` fields are the
    authoritative, many-to-many retrieval provenance.
    """

    annotated = dict(candidate)
    primary_branch = _normalize_space(
        annotated.get("primary_query_branch") or annotated.get("query_branch") or query_branch
    )
    branches = _unique_text_values(
        annotated.get("matched_query_branches"),
        annotated.get("query_branch"),
        annotated.get("primary_query_branch"),
        query_branch,
    )
    if primary_branch:
        annotated["primary_query_branch"] = primary_branch
        annotated["query_branch"] = primary_branch
    if branches:
        annotated["matched_query_branches"] = branches

    kinds = _unique_text_values(
        annotated.get("matched_evidence_kinds"),
        annotated.get("evidence_kind"),
        evidence_kind,
        [evidence_kind_from_query_branch(branch) for branch in branches],
    )
    direct_kinds = [kind for kind in kinds if kind in _DIRECT_EVIDENCE_KINDS]
    if direct_kinds:
        annotated["matched_evidence_kinds"] = direct_kinds

    path_roles = _unique_text_values(
        annotated.get("matched_evidence_path_roles"),
        annotated.get("evidence_path_role"),
    )
    if path_roles:
        annotated["matched_evidence_path_roles"] = path_roles

    if raw_hit_count > 0:
        branch_counts = _merge_positive_count_maps(annotated.get("branch_raw_hit_counts"))
        provider_counts = _merge_positive_count_maps(annotated.get("provider_raw_hit_counts"))
        count_branch = _normalize_space(query_branch) or primary_branch
        count_provider = _normalize_space(provider) or _normalize_space(annotated.get("provider"))
        if count_branch:
            branch_counts[count_branch] = branch_counts.get(count_branch, 0) + int(raw_hit_count)
        if count_provider:
            provider_counts[count_provider] = provider_counts.get(count_provider, 0) + int(raw_hit_count)
        if branch_counts:
            annotated["branch_raw_hit_counts"] = branch_counts
        if provider_counts:
            annotated["provider_raw_hit_counts"] = provider_counts
    return annotated


def merge_candidate_identity(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> dict[str, Any]:
    """Merge discovery provenance without treating two provider records as evidence-independent."""

    merged = dict(existing)
    for key in (
        "title", "citation", "doi", "arxiv_id", "semantic_scholar_id", "openalex_id", "pmid", "url",
        "abstract", "year", "venue", "open_access_pdf",
    ):
        merged[key] = _merge_scalar_or_list(merged.get(key), incoming.get(key))
    for key in (
        "discovery_providers",
        "retrieval_lanes",
        "matched_query_branches",
        "matched_evidence_kinds",
        "matched_evidence_path_roles",
    ):
        merged[key] = _merge_scalar_or_list(merged.get(key), incoming.get(key))
    for key in ("external_ids", "venue_metadata", "citation_metrics", "retrieval_lane_ranks"):
        current = dict(_mapping(merged.get(key)))
        for name, value in _mapping(incoming.get(key)).items():
            if name not in current or current.get(name) in (None, "", [], {}):
                current[name] = value
            elif isinstance(current.get(name), Mapping) and isinstance(value, Mapping):
                current[name] = {**value, **current[name]}
        if current:
            merged[key] = current
    current_payload = dict(_mapping(merged.get("papergraph_input")))
    incoming_payload = _mapping(incoming.get("papergraph_input"))
    for key, value in incoming_payload.items():
        if key not in current_payload or current_payload.get(key) in (None, "", [], {}):
            current_payload[key] = value
    if current_payload:
        merged["papergraph_input"] = current_payload
    identity = canonical_paper_identity(merged)
    merged["canonical_paper_key"] = identity["canonical_key"]
    merged["paper_identity"] = {
        "kind": identity["identity_kind"],
        "canonical_key": identity["canonical_key"],
    }
    merged["paper_identity_aliases"] = _merge_alias_maps(
        existing.get("paper_identity_aliases"),
        incoming.get("paper_identity_aliases"),
        identity["aliases"],
    )
    merged["branch_raw_hit_counts"] = _merge_positive_count_maps(
        existing.get("branch_raw_hit_counts"), incoming.get("branch_raw_hit_counts")
    )
    merged["provider_raw_hit_counts"] = _merge_positive_count_maps(
        existing.get("provider_raw_hit_counts"), incoming.get("provider_raw_hit_counts")
    )
    return annotate_candidate_query_provenance(merged)


def dedupe_candidates_by_identity(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate candidate hits with stable-ID alias unioning.

    This is candidate discovery deduplication only.  It never marks multiple
    provider descriptions of one paper as independent scientific evidence.
    """

    values: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        item = annotate_candidate_query_provenance(candidate)
        providers = [str(value) for value in (item.get("discovery_providers") or []) if str(value).strip()]
        provider = _normalize_space(item.get("provider"))
        if provider and provider not in providers:
            providers.append(provider)
        if providers:
            item["discovery_providers"] = providers
        values.append(item)
    parent = list(range(len(values)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root if left_root < right_root else right_root

    alias_owner: dict[str, int] = {}
    identities: list[dict[str, Any]] = []
    for index, candidate in enumerate(values):
        identity = canonical_paper_identity(candidate)
        identities.append(identity)
        for alias in identity["matching_aliases"]:
            owner = alias_owner.get(alias)
            if owner is None:
                alias_owner[alias] = index
            else:
                union(owner, index)

    grouped: dict[int, list[int]] = {}
    for index in range(len(values)):
        grouped.setdefault(find(index), []).append(index)
    deduped: list[dict[str, Any]] = []
    for indexes in grouped.values():
        first = indexes[0]
        merged = dict(values[first])
        first_identity = identities[first]
        merged["canonical_paper_key"] = first_identity["canonical_key"]
        merged["paper_identity"] = {
            "kind": first_identity["identity_kind"],
            "canonical_key": first_identity["canonical_key"],
        }
        merged["paper_identity_aliases"] = first_identity["aliases"]
        for index in indexes[1:]:
            merged = merge_candidate_identity(merged, values[index])
        identity = canonical_paper_identity(merged)
        merged["canonical_paper_key"] = identity["canonical_key"]
        merged["paper_identity"] = {
            "kind": identity["identity_kind"],
            "canonical_key": identity["canonical_key"],
        }
        merged["paper_identity_aliases"] = _merge_alias_maps(
            merged.get("paper_identity_aliases"), identity["aliases"]
        )
        deduped.append(annotate_candidate_query_provenance(merged))
    return deduped


def _current_anchor_groups(
    anchor_contract: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Read only the typed V3 retrieval-anchor contract.

    Provider dispatch is deliberately not a compatibility reader for historic
    causal-edge or flat-term contracts.  Each group is an OR-set of
    explicitly approved forms, and every required group must be preserved.
    """

    if not isinstance(anchor_contract, Mapping):
        return []
    if str(anchor_contract.get("schema_version") or "") != RETRIEVAL_ANCHOR_CONTRACT_SCHEMA_V3:
        return []
    raw_groups = anchor_contract.get("required_anchor_groups")
    if not isinstance(raw_groups, (list, tuple)):
        return []
    groups: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for raw_group in raw_groups:
        if not isinstance(raw_group, Mapping) or raw_group.get("required") is False:
            continue
        group_id = _normalize_space(raw_group.get("group_id"))
        raw_forms = raw_group.get("accepted_forms")
        if not group_id or not isinstance(raw_forms, (list, tuple, set)):
            continue
        forms = [
            _normalize_space(value)
            for value in raw_forms
            if _normalize_space(value)
        ]
        unique_forms = list(dict.fromkeys(forms))[:12]
        key = (group_id.casefold(), tuple(form.casefold() for form in unique_forms))
        if not unique_forms or key in seen:
            continue
        seen.add(key)
        groups.append(
            {
                "group_id": group_id,
                "accepted_forms": unique_forms,
                "required": True,
                "match_policy": str(
                    raw_group.get("match_policy")
                    or ANCHOR_MATCH_POLICY_VERSION
                ),
            }
        )
    return groups


def anchor_contract_fingerprint(anchor_contract: Mapping[str, Any] | None) -> str:
    """Return an identity for the current typed V3 anchor contract only."""

    groups = _current_anchor_groups(anchor_contract)
    if not groups:
        return ""
    encoded = json.dumps(
        {
            "schema_version": RETRIEVAL_ANCHOR_CONTRACT_SCHEMA_V3,
            "match_policy_version": ANCHOR_MATCH_POLICY_VERSION,
            "groups": groups,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _provider_anchor_token_sequence(provider: str, value: Any) -> tuple[str, ...]:
    """Project text into the same lexical space used by provider lowering.

    This is intentionally stricter than a substring check.  The result keeps
    lexical tokens such as ``IL-6``, ``A/B`` and ``Na+`` intact while treating
    query grammar (parentheses, quotes and Boolean separators) as boundaries.
    It is generic to a provider, never to a scientific discipline.
    """

    normalized = unicodedata.normalize("NFKC", _normalize_space(value)).casefold()
    if not normalized:
        return ()
    normalized_provider = normalize_provider_name(provider)
    if normalized_provider == "openalex":
        normalized = _OPENALEX_BOOLEAN_TOKEN_PATTERN.sub(" ", normalized)
        normalized = normalized.replace("|", " ")
    pattern = re.compile(r"(?u)[^\W_][\w+./-]*")
    tokens: list[str] = []
    for raw_token in pattern.findall(normalized):
        token = raw_token.strip("._/-")
        if token:
            tokens.append(token)
    return tuple(tokens)


def _contains_anchor_token_sequence(
    query_tokens: Sequence[str],
    anchor_tokens: Sequence[str],
) -> bool:
    """Match a phrase with token boundaries and preserved order."""

    if not anchor_tokens or len(anchor_tokens) > len(query_tokens):
        return False
    width = len(anchor_tokens)
    return any(
        tuple(query_tokens[index:index + width]) == tuple(anchor_tokens)
        for index in range(len(query_tokens) - width + 1)
    )


def validate_anchor_preservation(
    query: str,
    anchor_contract: Mapping[str, Any] | None,
    *,
    provider: str,
    require_current_contract: bool = False,
    audit_stage: str = "compiled_query",
) -> dict[str, Any]:
    """Verify required anchors through a provider-normalized token projection.

    A V3 source query and its provider-lowered form are audited separately.
    The same projection is applied to both sides, so removal of provider
    grammar such as parentheses does not masquerade as semantic anchor loss.
    """

    has_contract = isinstance(anchor_contract, Mapping) and bool(anchor_contract)
    schema_version = str((anchor_contract or {}).get("schema_version") or "") if has_contract else ""
    groups = _current_anchor_groups(anchor_contract)
    if has_contract and require_current_contract and schema_version != RETRIEVAL_ANCHOR_CONTRACT_SCHEMA_V3:
        return {
            "status": "invalid_anchor_contract_schema",
            "audit_stage": audit_stage,
            "provider": normalize_provider_name(provider),
            "missing_groups": [],
            "missing_group_ids": [],
            "anchor_fingerprint": "",
            "contract_schema_version": schema_version,
            "match_policy_version": ANCHOR_MATCH_POLICY_VERSION,
        }
    if has_contract and require_current_contract and not groups:
        return {
            "status": "invalid_anchor_contract",
            "audit_stage": audit_stage,
            "provider": normalize_provider_name(provider),
            "missing_groups": [],
            "missing_group_ids": [],
            "anchor_fingerprint": anchor_contract_fingerprint(anchor_contract),
            "contract_schema_version": schema_version,
            "match_policy_version": ANCHOR_MATCH_POLICY_VERSION,
        }
    if not groups:
        return {
            "status": "not_requested",
            "audit_stage": audit_stage,
            "provider": normalize_provider_name(provider),
            "missing_groups": [],
            "missing_group_ids": [],
            "matched_group_forms": {},
            "anchor_fingerprint": "",
            "contract_schema_version": schema_version,
            "match_policy_version": ANCHOR_MATCH_POLICY_VERSION,
        }

    query_tokens = _provider_anchor_token_sequence(provider, query)
    missing_groups: list[list[str]] = []
    missing_group_ids: list[str] = []
    matched_group_forms: dict[str, str] = {}
    for group in groups:
        matched_form = next(
            (
                form
                for form in group["accepted_forms"]
                if _contains_anchor_token_sequence(
                    query_tokens,
                    _provider_anchor_token_sequence(provider, form),
                )
            ),
            "",
        )
        if matched_form:
            matched_group_forms[str(group["group_id"])] = matched_form
        else:
            missing_groups.append(list(group["accepted_forms"]))
            missing_group_ids.append(str(group["group_id"]))
    return {
        "status": "verified" if not missing_groups else "missing_required_anchor",
        "audit_stage": audit_stage,
        "provider": normalize_provider_name(provider),
        "missing_groups": missing_groups,
        "missing_group_ids": missing_group_ids,
        "matched_group_forms": matched_group_forms,
        "query_token_sequence": list(query_tokens),
        "anchor_fingerprint": anchor_contract_fingerprint(anchor_contract),
        "contract_schema_version": schema_version,
        "match_policy_version": ANCHOR_MATCH_POLICY_VERSION,
    }


def validate_provider_query(provider: str, query: str) -> dict[str, Any]:
    """Run conservative, provider-independent static syntax checks."""

    normalized_provider = normalize_provider_name(provider)
    errors: list[str] = []
    normalized = _normalize_space(query)
    if not normalized:
        errors.append("query_empty")
    if any(ord(character) < 32 for character in normalized):
        errors.append("query_contains_control_character")
    if normalized.count('"') % 2:
        errors.append("unbalanced_double_quote")
    if normalized.count("(") != normalized.count(")"):
        errors.append("unbalanced_parentheses")
    if re.search(r"\b(?:AND|OR)\s+(?:AND|OR)\b", normalized, flags=re.IGNORECASE):
        errors.append("adjacent_boolean_operators")
    if normalized_provider in {"arxiv", "biorxiv", "medrxiv", "chemrxiv"} and "[" in normalized:
        errors.append("unsupported_field_tag_syntax")
    return {
        "provider": normalized_provider,
        "valid": not errors,
        "errors": errors,
        "static_validation": "provider_syntax_safety_v1",
    }


def _openalex_required_anchor_positions(
    lexical_tokens: Sequence[str],
    anchor_contract: Mapping[str, Any] | None,
) -> set[int]:
    """Return token positions that must survive OpenAlex query compaction."""

    normalized_tokens = tuple(
        token.strip("._/-").casefold()
        for token in lexical_tokens
    )
    protected_positions: set[int] = set()
    for group in _current_anchor_groups(anchor_contract):
        matched_positions: range | None = None
        for form in group["accepted_forms"]:
            form_tokens = _provider_anchor_token_sequence("openalex", form)
            if not form_tokens or len(form_tokens) > len(normalized_tokens):
                continue
            for start in range(len(normalized_tokens) - len(form_tokens) + 1):
                if normalized_tokens[start:start + len(form_tokens)] == form_tokens:
                    matched_positions = range(start, start + len(form_tokens))
                    break
            if matched_positions is not None:
                break
        if matched_positions is not None:
            protected_positions.update(matched_positions)
    return protected_positions


def _openalex_compact_search_terms(
    lexical_source: str,
    anchor_contract: Mapping[str, Any] | None,
) -> tuple[str, list[str]]:
    lexical_tokens = _OPENALEX_SEARCH_TOKEN_PATTERN.findall(lexical_source)
    protected_positions = _openalex_required_anchor_positions(
        lexical_tokens,
        anchor_contract,
    )
    remaining_protected = [0] * (len(lexical_tokens) + 1)
    for index in range(len(lexical_tokens) - 1, -1, -1):
        remaining_protected[index] = remaining_protected[index + 1] + int(
            index in protected_positions
        )

    tokens: list[str] = []
    seen_unprotected: set[str] = set()
    transforms: list[str] = []
    for index, raw_token in enumerate(lexical_tokens):
        token = raw_token.strip("._/-")
        normalized_token = token.casefold()
        protected = index in protected_positions
        if not normalized_token or (len(normalized_token) < 2 and not protected):
            continue
        if not protected:
            if normalized_token in seen_unprotected:
                continue
            if len(tokens) + 1 + remaining_protected[index + 1] > _OPENALEX_SEARCH_MAX_TERMS:
                continue
            candidate = " ".join([*tokens, token])
            protected_suffix = [
                lexical_tokens[position].strip("._/-")
                for position in range(index + 1, len(lexical_tokens))
                if position in protected_positions
            ]
            if len(" ".join([candidate, *protected_suffix])) > _OPENALEX_SEARCH_MAX_CHARS:
                continue
            seen_unprotected.add(normalized_token)
        tokens.append(token)

    compact = _normalize_space(" ".join(tokens))
    if protected_positions:
        transforms.append("openalex_required_anchor_terms_preserved")
    if len(tokens) > _OPENALEX_SEARCH_MAX_TERMS:
        transforms.append("openalex_required_anchor_terms_exceed_preferred_limit")
    if len(compact) > _OPENALEX_SEARCH_MAX_CHARS:
        transforms.append("openalex_required_anchor_terms_exceed_preferred_length")
    return compact, transforms


def _compile_syntax_safe_query(
    provider: str,
    query: str,
    *,
    anchor_contract: Mapping[str, Any] | None = None,
) -> tuple[str, list[str]]:
    compiled = unicodedata.normalize("NFKC", _normalize_space(query)).replace("\u201c", '"').replace("\u201d", '"')
    transforms: list[str] = ["normalized_whitespace"] if compiled != str(query or "") else []
    normalized_provider = normalize_provider_name(provider)
    if normalized_provider == "openalex":
        # OpenAlex's ``search`` parameter is free text, not the Boolean query
        # language used by PubMed/ScienceDirect.  Passing an internal query
        # AST as text can yield malformed request URLs (especially when the
        # expression carries ``|`` path delimiters).  Compile it into a short,
        # deterministic bag of topical terms; evidence-path separation and
        # post-retrieval alignment retain the lost Boolean responsibility.
        source = compiled
        lexical_source = _OPENALEX_BOOLEAN_TOKEN_PATTERN.sub(" ", source)
        lexical_source = lexical_source.replace("|", " ")
        lexical_source = lexical_source.replace("(", " ").replace(")", " ")
        compact, openalex_transforms = _openalex_compact_search_terms(
            lexical_source,
            anchor_contract,
        )
        if compact and compact != source:
            compiled = compact
            transforms.append("openalex_boolean_expression_to_search_text")
        transforms.extend(openalex_transforms)
    if normalized_provider in {"arxiv", "biorxiv", "medrxiv", "chemrxiv"}:
        without_tags = re.sub(r"\[([^\]]*)\]", r" \1 ", compiled)
        without_tags = _normalize_space(without_tags)
        if without_tags != compiled:
            compiled = without_tags
            transforms.append("removed_unsupported_square_bracket_field_tags")
    return compiled, transforms


def compile_provider_query(
    provider: str,
    query: str,
    *,
    anchor_contract: Mapping[str, Any] | None = None,
    approved_synonyms: Sequence[str] = (),
    require_current_anchor_contract: bool = False,
) -> dict[str, Any]:
    """Compile one query while keeping semantic and provider layers separate.

    Approved synonyms are audit-only: this function never adds them.  The
    source query is checked before lowering and the provider form afterwards,
    so the caller can distinguish a malformed V2 plan from a compiler that
    would lose a required semantic anchor.
    """

    capabilities = get_literature_provider_capabilities(provider)
    source_anchors = validate_anchor_preservation(
        query,
        anchor_contract,
        provider=capabilities.provider,
        require_current_contract=require_current_anchor_contract,
        audit_stage="semantic_source_query",
    )
    compiled_query, transforms = _compile_syntax_safe_query(
        capabilities.provider,
        query,
        anchor_contract=anchor_contract,
    )
    syntax = validate_provider_query(capabilities.provider, compiled_query)
    compiled_anchors = validate_anchor_preservation(
        compiled_query,
        anchor_contract,
        provider=capabilities.provider,
        require_current_contract=require_current_anchor_contract,
        audit_stage="provider_compiled_query",
    )
    failure_kind = ""
    if source_anchors["status"] not in _CURRENT_ANCHOR_OK_STATUSES:
        failure_kind = (
            "query_plan_contract_error"
            if source_anchors["status"] in {"missing_required_anchor", "invalid_anchor_contract", "invalid_anchor_contract_schema"}
            else "query_plan_contract_error"
        )
    elif not syntax["valid"]:
        failure_kind = "provider_query_syntax_error"
    elif compiled_anchors["status"] not in _CURRENT_ANCHOR_OK_STATUSES:
        failure_kind = "provider_query_compilation_error"
    valid = not failure_kind
    compilation_identity = {
        "policy_version": PROVIDER_QUERY_COMPILATION_POLICY_VERSION,
        "anchor_match_policy_version": ANCHOR_MATCH_POLICY_VERSION,
        "provider": capabilities.provider,
        "semantic_source_query": str(query or ""),
        "provider_compiled_query": compiled_query,
        "anchor_contract_fingerprint": anchor_contract_fingerprint(anchor_contract),
    }
    return {
        "provider": capabilities.provider,
        "semantic_source_query": str(query or ""),
        "provider_compiled_query": compiled_query,
        # These names are retained only as descriptive aliases inside the new
        # V2 record, not as an old execution path.
        "source_query": str(query or ""),
        "compiled_query": compiled_query,
        "valid": valid,
        "submission_allowed": valid,
        "failure_kind": failure_kind,
        "submitted_to_provider": False,
        "syntax_validation": syntax,
        "source_anchor_validation": source_anchors,
        "compiled_anchor_validation": compiled_anchors,
        "anchor_validation": compiled_anchors,
        "syntax_transforms": transforms,
        "approved_synonyms": [_normalize_space(item) for item in approved_synonyms if _normalize_space(item)],
        "compilation_policy_version": PROVIDER_QUERY_COMPILATION_POLICY_VERSION,
        "anchor_match_policy_version": ANCHOR_MATCH_POLICY_VERSION,
        "compilation_fingerprint": "sha256:" + hashlib.sha256(
            json.dumps(compilation_identity, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "capability_contract": {
            "query_syntax": capabilities.query_syntax,
            "supported_query_features": list(capabilities.supported_query_features),
        },
        "discovery_only": True,
    }


def repair_provider_query(
    provider: str,
    current_query: str,
    error: Any,
    *,
    anchor_contract: Mapping[str, Any] | None = None,
    prior_queries: Sequence[str] = (),
    approved_synonyms: Sequence[str] = (),
) -> dict[str, Any]:
    """Make one bounded syntax-only repair, never a semantic-plan repair."""

    source = _normalize_space(current_query)
    error_text = _normalize_space(error).lower()
    candidate = source
    reason = "no_safe_repair"
    if "quote" in error_text and source.count('"') % 2:
        candidate = source + '"'
        reason = "closed_unbalanced_double_quote"
    elif "parenth" in error_text and source.count("(") > source.count(")"):
        candidate = source + (")" * (source.count("(") - source.count(")")))
        reason = "closed_unbalanced_parentheses"
    elif "boolean" in error_text or re.search(r"\b(?:AND|OR)\s+(?:AND|OR)\b", source, flags=re.IGNORECASE):
        candidate = re.sub(r"\b(AND|OR)\s+(?:AND|OR)\b", r"\1", source, flags=re.IGNORECASE)
        reason = "collapsed_adjacent_boolean_operators"
    elif "field" in error_text or "syntax" in error_text:
        candidate, transforms = _compile_syntax_safe_query(
            provider,
            source,
            anchor_contract=anchor_contract,
        )
        if transforms:
            reason = "+".join(transforms)
    candidate = _normalize_space(candidate)
    prior = {_normalize_space(value) for value in prior_queries if _normalize_space(value)}
    anchors = validate_anchor_preservation(
        candidate,
        anchor_contract,
        provider=provider,
        audit_stage="repair_candidate",
    )
    syntax = validate_provider_query(provider, candidate)
    accepted = (
        candidate != source
        and candidate not in prior
        and bool(syntax["valid"])
        and anchors["status"] in _CURRENT_ANCHOR_OK_STATUSES
    )
    rejection_reason = ""
    if not accepted:
        if anchors["status"] not in _CURRENT_ANCHOR_OK_STATUSES:
            rejection_reason = "provider_anchor_equivalence_not_established"
        elif candidate == source:
            rejection_reason = "no_effective_repair"
        elif candidate in prior:
            rejection_reason = "repeated_query_blocked"
        else:
            rejection_reason = "static_validation_failed"
    return {
        "provider": normalize_provider_name(provider),
        "original_query": source,
        "repaired_query": candidate if accepted else "",
        "accepted": accepted,
        "reason": reason if accepted else rejection_reason,
        "provider_error": _normalize_space(error),
        "syntax_validation": syntax,
        "anchor_validation": anchors,
        "approved_synonyms": [_normalize_space(item) for item in approved_synonyms if _normalize_space(item)],
        "repair_scope": "syntax_only_or_explicitly_approved_synonyms",
    }


_DEFAULT_LANE_WEIGHTS = {
    "direct_relevance": 1.0,
    "impact": 0.75,
    "recent_direct_evidence": 0.9,
    "review_map": 0.8,
    "mechanism_intervention": 1.0,
    "local_quality": 0.6,
}


def fuse_literature_candidates(
    query: str,
    lane_results: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    lane_weights: Mapping[str, float] | None = None,
    rrf_k: int = 60,
) -> dict[str, Any]:
    """Fuse discovery lanes using weighted RRF and preserve all lane provenance."""

    weights = dict(_DEFAULT_LANE_WEIGHTS)
    for lane, weight in _mapping(lane_weights).items():
        try:
            weights[str(lane)] = max(0.0, float(weight))
        except (TypeError, ValueError):
            continue
    denominator_offset = max(1, int(rrf_k))
    annotated: list[dict[str, Any]] = []
    lane_counts: dict[str, int] = {}
    for lane, results in lane_results.items():
        lane_name = str(lane or "unlabeled")
        valid_results = [item for item in results if isinstance(item, Mapping)]
        lane_counts[lane_name] = len(valid_results)
        for rank, result in enumerate(valid_results, start=1):
            item = dict(result)
            item["retrieval_lanes"] = _merge_scalar_or_list(item.get("retrieval_lanes"), [lane_name])
            ranks = dict(_mapping(item.get("retrieval_lane_ranks")))
            ranks[lane_name] = min(int(ranks.get(lane_name, rank) or rank), rank)
            item["retrieval_lane_ranks"] = ranks
            annotated.append(item)
    documents = dedupe_candidates_by_identity(annotated)
    fused: list[dict[str, Any]] = []
    for original_index, item in enumerate(documents):
        ranks = {str(name): int(rank) for name, rank in _mapping(item.get("retrieval_lane_ranks")).items()}
        active_weights = {lane: weights.get(lane, 1.0) for lane in ranks}
        score = sum(active_weights[lane] / (denominator_offset + rank) for lane, rank in ranks.items())
        merged = dict(item)
        merged["discovery_rrf_score"] = round(score, 12)
        merged["discovery_fusion"] = {
            "method": "weighted_rrf_v1",
            "query": _normalize_space(query),
            "rrf_k": denominator_offset,
            "lane_ranks": ranks,
            "lane_weights": active_weights,
            "discovery_only": True,
            "not_evidence_assessment": True,
        }
        merged["_discovery_fusion_original_index"] = original_index
        fused.append(merged)
    fused.sort(
        key=lambda item: (-float(item.get("discovery_rrf_score") or 0.0), int(item.get("_discovery_fusion_original_index") or 0))
    )
    for item in fused:
        item.pop("_discovery_fusion_original_index", None)
    return {
        "method": "weighted_rrf_v1",
        "query": _normalize_space(query),
        "rrf_k": denominator_offset,
        "lane_weights": weights,
        "lane_counts": lane_counts,
        "candidate_count_before_identity_dedupe": len(annotated),
        "candidate_count_after_identity_dedupe": len(fused),
        "documents": fused,
        "discovery_only": True,
        "not_evidence_assessment": True,
    }


def redact_retrieval_payload(value: Any) -> Any:
    """Recursively remove secret values while retaining operational diagnostics."""

    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            redacted[key_text] = "[REDACTED]" if _SECRET_KEY_PATTERN.search(key_text) else redact_retrieval_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_retrieval_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_retrieval_payload(item) for item in value]
    if isinstance(value, str):
        redacted = _BEARER_VALUE_PATTERN.sub("Bearer [REDACTED]", value)
        redacted = _INLINE_SECRET_PATTERN.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", redacted)
        return redacted
    return value


def create_retrieval_run(
    *,
    search_id: str,
    query: str,
    source_query: str = "",
    providers: Sequence[str] = (),
    anchor_contract: Mapping[str, Any] | None = None,
    provider_attempts: Sequence[Mapping[str, Any]] = (),
    query_compilations: Sequence[Mapping[str, Any]] = (),
    candidate_fusion: Mapping[str, Any] | None = None,
    discipline_taxonomy: Mapping[str, Any] | None = None,
    import_selection_reason: Any = None,
    strategy: str = "candidate_discovery",
) -> dict[str, Any]:
    """Create a compact, redacted retrieval-run artifact for a saved search."""

    run = {
        "schema_version": "retrieval_run_v1",
        "retrieval_run_id": f"retrieval_run:{_normalize_space(search_id) or 'unknown'}",
        "search_id": _normalize_space(search_id),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "strategy": _normalize_space(strategy) or "candidate_discovery",
        "query": _normalize_space(query),
        "source_query": _normalize_space(source_query),
        "providers": [normalize_provider_name(provider) for provider in providers if normalize_provider_name(provider)],
        "causal_anchor_contract_fingerprint": anchor_contract_fingerprint(anchor_contract),
        "provider_attempts": [dict(item) for item in provider_attempts if isinstance(item, Mapping)],
        "query_revisions_and_reasons": [dict(item) for item in query_compilations if isinstance(item, Mapping)],
        "candidate_fusion_provenance": dict(candidate_fusion or {}),
        "discipline_taxonomy": dict(discipline_taxonomy or {}),
        "import_selection_reason": import_selection_reason if import_selection_reason is not None else "candidate discovery only; PaperGraph gates remain authoritative",
        "scope_boundary": "pre_papergraph_candidate_discovery_only",
        "evidence_decisions": "not_recorded_here",
    }
    return redact_retrieval_payload(run)


def provider_doctor_snapshot(
    *,
    configuration_presence: Mapping[str, Any] | None = None,
    runtime_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an offline provider diagnostic without values or network calls."""

    configuration = _mapping(configuration_presence)
    state = _mapping(runtime_state)
    providers: list[dict[str, Any]] = []
    for capability in list_literature_provider_capabilities():
        optional = {
            name: bool(configuration.get(name)) if name in configuration else None
            for name in capability["optional_config"]
        }
        required = {
            name: bool(configuration.get(name)) if name in configuration else None
            for name in capability["required_config"]
        }
        provider_state = _mapping(state.get(capability["provider"]))
        providers.append(
            {
                "provider": capability["provider"],
                "status": capability["status"],
                "configuration_present": {"required": required, "optional": optional},
                "runtime_state": redact_retrieval_payload(dict(provider_state)),
                "allowed_layers": capability["allowed_layers"],
                "allows_socrates_direct_evidence": capability["allows_socrates_direct_evidence"],
                "rate_limit_policy": capability["rate_limit_policy"],
                "live_smoke_executed": False,
            }
        )
    return {
        "schema_version": "literature_provider_doctor_v1",
        "mode": "offline",
        "network_calls": 0,
        "providers": providers,
        "next_step": "Use a normal retrieval run for an opt-in live provider check; this doctor never sends a query.",
    }
