"""V3 source-span, assertion, inference, and admission primitives.

The module is deliberately domain neutral.  A source span is immutable source
material; an explicit assertion is a normalised statement that quotes that
material; a derived inference is a bounded interpretation over explicit
assertions.  Derived inferences have a route ceiling and never masquerade as
primary evidence.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

try:
    from ._research_question_contract import (
        RESEARCH_QUESTION_CONTRACT_VERSION,
        SCOPE_AXES,
        bind_research_question_task_scope,
        validate_research_question_contract,
    )
    from ._science_execution_policy import ScienceExecutionPolicy, resolve_science_execution_policy
    from ._evidence_document_sections import (
        DOCUMENT_SCHEMA_VERSION as DOCUMENT_SCHEMA_VERSION_V4,
        build_document_record as build_document_record_v4,
        structure_document_sections,
    )
    from ._evidence_spans import (
        SOURCE_SPAN_SCHEMA_VERSION as SOURCE_SPAN_SCHEMA_VERSION_V6,
        build_evidence_spans,
    )
    from ._evidence_assertion_validation import (
        EVIDENCE_ASSERTION_SCHEMA_VERSION as EVIDENCE_ASSERTION_SCHEMA_VERSION_V4,
    )
    from ._evidence_proposition_extraction import (
        EVIDENCE_UNIT_REGISTRY_REVISION,
        PROPOSITION_COMPOSITION_PROMPT_REVISION,
        PROPOSITION_EXTRACTION_SCHEMA_VERSION,
        PROPOSITION_PROMPT_REVISION,
        extract_document_propositions,
        proposition_model_id,
        _source_span_cache_key,
    )
    from ._evidence_slot_alignment import align_propositions_to_contract
    from ._sh_retrieval import select_review_evidence_units
    from ._evidence_admission import (
        EVIDENCE_ADMISSION_SCHEMA_VERSION as EVIDENCE_ADMISSION_SCHEMA_VERSION_V4,
        GAP_SOURCE_ADMISSION_SCHEMA_VERSION as GAP_SOURCE_ADMISSION_SCHEMA_VERSION_V4,
        build_evidence_admission,
    )
except ImportError:
    from _research_question_contract import (
        RESEARCH_QUESTION_CONTRACT_VERSION,
        SCOPE_AXES,
        bind_research_question_task_scope,
        validate_research_question_contract,
    )
    from _science_execution_policy import ScienceExecutionPolicy, resolve_science_execution_policy
    from _evidence_document_sections import (
        DOCUMENT_SCHEMA_VERSION as DOCUMENT_SCHEMA_VERSION_V4,
        build_document_record as build_document_record_v4,
        structure_document_sections,
    )
    from _evidence_spans import (
        SOURCE_SPAN_SCHEMA_VERSION as SOURCE_SPAN_SCHEMA_VERSION_V6,
        build_evidence_spans,
    )
    from _evidence_assertion_validation import (
        EVIDENCE_ASSERTION_SCHEMA_VERSION as EVIDENCE_ASSERTION_SCHEMA_VERSION_V4,
    )
    from _evidence_proposition_extraction import (
        EVIDENCE_UNIT_REGISTRY_REVISION,
        PROPOSITION_COMPOSITION_PROMPT_REVISION,
        PROPOSITION_EXTRACTION_SCHEMA_VERSION,
        PROPOSITION_PROMPT_REVISION,
        extract_document_propositions,
        proposition_model_id,
        _source_span_cache_key,
    )
    from _evidence_slot_alignment import align_propositions_to_contract
    from _sh_retrieval import select_review_evidence_units
    from _evidence_admission import (
        EVIDENCE_ADMISSION_SCHEMA_VERSION as EVIDENCE_ADMISSION_SCHEMA_VERSION_V4,
        GAP_SOURCE_ADMISSION_SCHEMA_VERSION as GAP_SOURCE_ADMISSION_SCHEMA_VERSION_V4,
        build_evidence_admission,
    )


SOURCE_SPAN_SCHEMA_VERSION = SOURCE_SPAN_SCHEMA_VERSION_V6
EVIDENCE_ASSERTION_SCHEMA_VERSION = EVIDENCE_ASSERTION_SCHEMA_VERSION_V4
DERIVED_INFERENCE_SCHEMA_VERSION = "derived_inference_v3"
HETEROGENEOUS_EVIDENCE_GRAPH_SCHEMA_VERSION = "heterogeneous_evidence_graph_v4"
GAP_SOURCE_ADMISSION_SCHEMA_VERSION = GAP_SOURCE_ADMISSION_SCHEMA_VERSION_V4
DOCUMENT_SCHEMA_VERSION = DOCUMENT_SCHEMA_VERSION_V4
EVIDENCE_LINK_SCHEMA_VERSION = "evidence_link_v4"
EVIDENCE_PROJECTION_SCHEMA_VERSION = "evidence_projection_v4"
EVIDENCE_ADMISSION_SCHEMA_VERSION = EVIDENCE_ADMISSION_SCHEMA_VERSION_V4

# A V3 document is deliberately admitted in stages.  In particular,
# bibliographic metadata and an abstract can help select a document, but they
# can never be promoted into a direct evidence slot merely because their text
# contains relevant terms.
EVIDENCE_MATERIAL_STAGES = frozenset({
    "METADATA_DISCOVERED",
    "SOURCE_ADMITTED",
    "FULLTEXT_ACQUIRED",
    "SPAN_EXTRACTED",
    "ASSERTION_EXTRACTED",
    "ASSERTION_ADMITTED",
    "DIRECT_SLOT_ADMITTED",
})

_SENTENCE_RE = re.compile(r"(?<=[.!?。；;])\s+")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+\-./]*|[\u4e00-\u9fff]{2,}")
_LIMITATION_RE = re.compile(r"\b(?:remain(?:s)?\s+(?:unknown|unclear|unresolved)|not\s+(?:well\s+)?(?:understood|established|tested|evaluated|examined)|did\s+not\s+(?:test|evaluate|examine|establish|determine)|has\s+not\s+been\s+(?:established|tested|evaluated|examined)|limited\s+by|limitation|insufficient\s+evidence|cannot\s+(?:distinguish|determine)|unknown)\b", re.IGNORECASE)
_AUTHOR_LIMITATION_ATTRIBUTION_RE = re.compile(
    r"\b(?:we|our|this|the\s+(?:present|current)\s+study|this\s+(?:study|work|analysis|experiment|method|approach)|authors?)\b"
    r"[^.?!;]{0,100}\b(?:did\s+not|have\s+not|has\s+not|were?\s+not|cannot|could\s+not|limitation|limited)\b"
    r"|\b(?:limitations?\s+(?:of|in)\s+(?:this|our|the\s+(?:present|current))\s+(?:study|work|analysis|experiment|method|approach))\b"
    r"|\b(?:authors?\s+(?:note|acknowledge|report|state))\b",
    re.IGNORECASE,
)
_AUTHOR_LIMITATION_TARGET_RE = re.compile(
    r"\b(?:did\s+not|have\s+not|has\s+not|were?\s+not|cannot|could\s+not)\s+"
    r"(?:be\s+)?(?:well\s+)?(?:test(?:ed)?|evaluat(?:ed|e)|examin(?:ed|e)|establish(?:ed)?|determin(?:ed|e)|distinguish(?:ed)?)\s+"
    r"(?P<tested_target>[^.?!;]{3,180})"
    r"|\b(?:limited\s+by|limitation(?:s)?\s+(?:of|in|include(?:s)?)|insufficient\s+evidence\s+(?:for|on)|lack\s+of)\s+"
    r"(?P<limitation_target>[^.?!;]{3,180})",
    re.IGNORECASE,
)
_AUTHOR_LIMITATION_GENERIC_TARGETS = frozenset({
    "it", "them", "this", "that", "these", "those", "unknown", "unclear",
    "unresolved", "not tested", "not evaluated", "not examined",
})
_CAUSAL_RE = re.compile(r"\b(?:caus(?:e|es|ed|ing)|causal|driv(?:e|es|en|ing)|mediate(?:s|d|ing)?|intervention|confound(?:er|ing)?|randomi[sz](?:e|ed|ation))\b", re.IGNORECASE)
_ASSOCIATION_RE = re.compile(r"\b(?:associat(?:e|es|ed|ion)|correlat(?:e|es|ed|ion)|predict(?:s|ed|ing)?|linked\s+to)\b", re.IGNORECASE)
_MEASUREMENT_RE = re.compile(r"\b(?:measure(?:s|d|ment)?|proxy|surrogate|instrument|sensor|assay|calibrat(?:e|ed|ion)|valid(?:ity|ated)|reliab(?:le|ility)|error)\b", re.IGNORECASE)
_THEORY_RE = re.compile(r"\b(?:theorem|lemma|proposition|proof|axiom|assum(?:e|es|ed|ption)|counterexample|identifiab(?:le|ility)|derive(?:s|d|d?))\b", re.IGNORECASE)
_METHOD_RE = re.compile(r"\b(?:method|protocol|design|bias|estimator|algorithm|ablation|failure mode|computational cost)\b", re.IGNORECASE)
_DATA_RE = re.compile(r"\b(?:dataset|data\s+coverage|missing\s+(?:data|variable|sample)|sampling|cohort|corpus|label)\b", re.IGNORECASE)
_SCALE_RE = re.compile(r"\b(?:cross[ -]?scale|multi[ -]?scale|micro(?:scopic)?|macro(?:scopic)?|meso(?:scopic)?|scaling|coarse[ -]?grain)\b", re.IGNORECASE)
_BENCHMARK_RE = re.compile(r"\b(?:benchmark|baseline|common\s+(?:task|metric)|shared\s+metric|evaluation protocol|fair comparison)\b", re.IGNORECASE)
_COMPARISON_RELATION_RE = re.compile(
    r"\b(?:versus|vs\.?|compared(?:\s+(?:with|to|for|on|using|under))?|comparison\s+(?:of|between)|"
    r"compared\s+between|relative\s+to|outperformed?|underperformed?|agreement\s+between)\b",
    re.IGNORECASE,
)
_COMPARISON_PROTOCOL_RE = re.compile(
    r"\b(?:same|identical|common|shared|standardized?)\s+(?:protocol|task|sample|dataset|"
    r"conditions?|evaluation|experiment|measurement)\b|\b(?:benchmark(?:ing)?|calibrat(?:ed|ion))\b",
    re.IGNORECASE,
)
_COMPARISON_METRIC_RE = re.compile(
    r"\b(?:accuracy|precision|recall|specificity|sensitivity|error|bias|agreement|"
    r"correlation|coefficient|score|rate|yield|response|performance)\b",
    re.IGNORECASE,
)
_TRANSLATION_RE = re.compile(r"\b(?:deployment|implement(?:ation|ed)|real[ -]?world|feasib(?:le|ility)|cost|safety|adoption|field study)\b", re.IGNORECASE)
_BOUNDARY_RE = re.compile(r"\b(?:boundary|regime|threshold|heterogen(?:eity|ous)|context[- ]dependent|under\s+.+(?:condition|regime)|interaction)\b", re.IGNORECASE)
_CONTRADICTION_RE = re.compile(r"\b(?:contradict(?:s|ory|ion)|inconsistent|failed\s+to\s+replicate|replication|opposite\s+(?:effect|direction))\b", re.IGNORECASE)
_RESULT_RE = re.compile(r"\b(?:we\s+(?:find|found|observe|observed|show|showed|demonstrate|demonstrated)|results?\s+(?:show|indicate|suggest)|increas(?:e|ed)|decreas(?:e|ed)|higher|lower)\b", re.IGNORECASE)
_INTERVENTION_RE = re.compile(r"\b(?:randomi[sz](?:ed|ation)|perturb(?:ed|ation)?|manipulat(?:ed|ion)|treated|control(?:led)?|ablat(?:ed|ion)|knockout|versus|compared\s+with)\b", re.IGNORECASE)
_FORMAL_RE = re.compile(r"\b(?:proof|theorem|lemma|proposition|axiom|derive(?:d|s)?)\b", re.IGNORECASE)
_MODAL_RE = re.compile(r"\b(?:may|might|could|suggest(?:s|ed)?|possible|potential|hypothesi[sz](?:e|ed))\b", re.IGNORECASE)
_NEGATION_RE = re.compile(r"\b(?:not|no|never|without|cannot|failed)\b", re.IGNORECASE)
_UNKNOWN_RE = re.compile(r"\b(?:unknown|unclear|unresolved|not\s+(?:known|understood|established|tested|evaluated|examined))\b", re.IGNORECASE)
_METHOD_FAILURE_RE = re.compile(r"\b(?:fails?|failure|biased|bias|unstable|intractable|not\s+identifiable|cannot\s+estimate)\b", re.IGNORECASE)
_MEASUREMENT_VALIDATION_RE = re.compile(r"\b(?:validated?|calibrat(?:ed|ion)|gold\s+standard|reference\s+standard|cross[- ]instrument|reliab(?:ility|le))\b", re.IGNORECASE)
_MEASUREMENT_ERROR_RE = re.compile(r"\b(?:measurement\s+error|error\s+model|uncertainty|misclassif|noise|bias)\b", re.IGNORECASE)
_COUNTEREXAMPLE_RE = re.compile(r"\b(?:counterexample|counter[- ]example|violat(?:es?|ion)|fails?\s+under)\b", re.IGNORECASE)
_DATASET_DESCRIPTION_RE = re.compile(r"\b(?:dataset|corpus|cohort|sample|observations?)\b", re.IGNORECASE)
_DEPLOYMENT_OUTCOME_RE = re.compile(r"\b(?:deployed?|implemented?|field\s+(?:trial|study)|real[- ]world|operational)\b", re.IGNORECASE)
_PROOF_RE = re.compile(r"\b(?:prove(?:d|s)?|proof|derive(?:d|s)?)\b", re.IGNORECASE)
_EXPLICIT_CAUSAL_PROPOSITION_RE = re.compile(
    r"\b(?:causes?|caused|drives?|driven|mediates?|mediated|"
    r"leads?\s+to|results?\s+in|produces?|induces?|"
    r"effect\s+of\s+.+?\s+on)\b",
    re.IGNORECASE,
)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normal(value: Any) -> str:
    return _text(value).lower()


def _tokens(value: Any) -> set[str]:
    return {item.lower() for item in _TOKEN_RE.findall(_normal(value)) if len(item) > 1}


def _unique(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _text(value)
        key = text.lower()
        if text and key not in seen:
            output.append(text)
            seen.add(key)
    return output


def _contract_version_fields(contract: dict[str, Any]) -> tuple[str, str]:
    """Return the immutable V2 revision and declaration-hash identities."""

    contract = contract if isinstance(contract, dict) else {}
    revision = _text(
        contract.get("contract_revision") or contract.get("declaration_hash")
    )
    declaration_hash = _text(
        contract.get("declaration_hash") or contract.get("contract_revision")
    )
    return revision, declaration_hash


def _version_matches_contract(value: dict[str, Any], contract: dict[str, Any]) -> bool:
    """Require explicit identity for one current V2 contract revision.

    A contract id alone is deliberately insufficient.  A scientific-contract
    revision may retain an external id while changing its evidence semantics;
    the old assertion remains an auditable historical artifact but cannot be
    interpreted as current evidence.
    """

    revision, declaration_hash = _contract_version_fields(contract)
    if not revision or not declaration_hash:
        return False
    actual_revision = _text(value.get("research_question_contract_revision"))
    actual_hash = _text(value.get("research_question_contract_hash"))
    return actual_revision == revision and actual_hash == declaration_hash


def _paper_id(record: dict[str, Any]) -> str:
    identifier = _text(record.get("paper_id") or record.get("doi"))
    if identifier:
        return identifier
    title = _text(record.get("title"))
    return "paper_" + sha256(title.encode("utf-8")).hexdigest()[:20]


def _has_fulltext_material(record: dict[str, Any]) -> bool:
    """Return whether the record contains a versioned body-level text source.

    This is intentionally structural rather than relevance based.  An
    abstract, title, DOI, or metadata provider flag cannot be used to cross
    this boundary.  A direct slot begins only once a body/full-text source is
    actually available for span extraction.
    """

    source = record if isinstance(record, dict) else {}
    payload = source.get("papergraph_input") if isinstance(source.get("papergraph_input"), dict) else {}
    values = (
        source.get("methods"), source.get("method"), source.get("results"),
        source.get("result"), source.get("discussion"), source.get("conclusion"),
        source.get("full_text_excerpt"), source.get("fulltext"),
        source.get("pdf_text"), source.get("extracted_text"),
        payload.get("methods"), payload.get("method"), payload.get("results"),
        payload.get("result"), payload.get("discussion"), payload.get("conclusion"),
        payload.get("full_text_excerpt"),
    )
    return any(_text(value) for value in values)


def _document_material_stage(record: dict[str, Any]) -> str:
    """Classify a source without allowing a metadata-to-evidence shortcut."""

    if _has_fulltext_material(record):
        return "FULLTEXT_ACQUIRED"
    return "METADATA_DISCOVERED"


def _has_explicit_causal_proposition(quote: str) -> bool:
    """Distinguish a stated causal proposition from causal-word co-occurrence.

    Mentioning ``causal inference``, a ``causal mechanism``, or a causal
    variable in the same sentence as two terms is not an assertion that one
    caused the other.  This deliberately small lexical guard does *not* infer
    causality; it only decides whether an already source-bound sentence may
    be labelled as a source-stated causal relation.  The final direct-slot
    decision also requires the contract-specific admission review.
    """

    normalized = _text(quote)
    if not normalized or not _EXPLICIT_CAUSAL_PROPOSITION_RE.search(normalized):
        return False
    # These forms describe a research topic or possible explanation, not a
    # proposition linking source-stated endpoints.
    if re.search(r"\b(?:causal\s+(?:inference|analysis|mechanism|model)|may\s+cause|might\s+cause|could\s+cause)\b", normalized, re.IGNORECASE):
        return False
    return True


def _document_text_sections(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return source-addressable content units without flattening their type.

    The v2 evidence layer must preserve captions, table cells, equations, and
    supplements as distinct source material.  A table cell should never be
    silently concatenated with prose just because both arrived in one Markdown
    extraction result.  Callers may supply structured objects with page and
    layout metadata; plain legacy text stays usable only as explicitly typed
    body/abstract content, never as a fabricated table or figure record.
    """
    record = record if isinstance(record, dict) else {}
    payload = record.get("papergraph_input") if isinstance(record.get("papergraph_input"), dict) else {}
    output: list[dict[str, Any]] = []

    def add(
        section: str,
        value: Any,
        *,
        span_kind: str,
        source_field: str,
        default_source_type: str = "fulltext",
        index: int | None = None,
    ) -> None:
        if isinstance(value, dict):
            text_value = value.get("text") or value.get("quote") or value.get("content") or value.get("value")
            metadata = value
        else:
            text_value = value
            metadata = {}
        text = _text(text_value)
        if not text:
            return
        suffix = f":{index}" if index is not None else ""
        output.append(
            {
                "section": f"{section}{suffix}",
                "section_base": section,
                "source_field": source_field,
                "span_kind": _text(metadata.get("span_kind")) or span_kind,
                "source_type": _text(metadata.get("source_type")) or default_source_type,
                "text": text,
                "page_number": metadata.get("page_number", record.get("page_number")),
                "paragraph_index": metadata.get("paragraph_index"),
                "bounding_box": metadata.get("bounding_box"),
                "ocr_confidence": metadata.get("ocr_confidence"),
                "layout_confidence": metadata.get("layout_confidence"),
                "char_start": metadata.get("char_start"),
                "char_end": metadata.get("char_end"),
            }
        )

    scalar_fields = (
        ("title", record.get("title") or payload.get("title"), "title", "title", "metadata"),
        ("abstract", record.get("abstract") or payload.get("abstract"), "abstract", "abstract", "abstract"),
        ("methods", record.get("methods") or record.get("method") or payload.get("methods") or payload.get("method"), "body_sentence", "methods", "fulltext"),
        ("results", record.get("results") or record.get("result") or payload.get("results") or payload.get("result"), "body_sentence", "results", "fulltext"),
        ("discussion", record.get("discussion") or payload.get("discussion"), "body_sentence", "discussion", "fulltext"),
        ("conclusion", record.get("conclusion") or payload.get("conclusion"), "body_sentence", "conclusion", "fulltext"),
        ("fulltext", record.get("full_text_excerpt") or record.get("fulltext") or record.get("pdf_text") or record.get("extracted_text") or payload.get("full_text_excerpt"), "body_sentence", "fulltext", "fulltext"),
        ("supplement", record.get("supplement") or record.get("supplement_text") or payload.get("supplement") or payload.get("supplement_text"), "supplement", "supplement", "supplement"),
    )
    for section, value, span_kind, source_field, source_type in scalar_fields:
        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                add(section, item, span_kind=span_kind, source_field=source_field, default_source_type=source_type, index=index)
        else:
            add(section, value, span_kind=span_kind, source_field=source_field, default_source_type=source_type)

    typed_collections = (
        ("figure_caption", record.get("figure_captions") or record.get("figure_caption") or payload.get("figure_captions"), "figure_caption", "figure_caption"),
        ("table_caption", record.get("table_captions") or record.get("table_caption") or payload.get("table_captions"), "table_caption", "table_caption"),
        ("table_cell", record.get("table_cells") or payload.get("table_cells"), "table_cell", "table_cell"),
        ("equation", record.get("equations") or record.get("equation_latex") or record.get("equation") or payload.get("equations"), "equation", "equation"),
        ("supplement", record.get("supplement_spans") or payload.get("supplement_spans"), "supplement", "supplement"),
    )
    for section, values, span_kind, source_field in typed_collections:
        if values is None:
            continue
        if not isinstance(values, (list, tuple)):
            values = [values]
        for index, item in enumerate(values):
            add(section, item, span_kind=span_kind, source_field=source_field, default_source_type="supplement" if span_kind == "supplement" else "fulltext", index=index)
    return output


def document_version_hash(record: dict[str, Any]) -> str:
    return _text(build_document_record_v4(record).get("document_version_hash"))


def _build_document_record_v3_removed(record: dict[str, Any]) -> dict[str, Any]:
    """Create one immutable V3 document-version record.

    The record owns acquisition/provenance information.  Assertions never
    embed it and a document at ``METADATA_DISCOVERED`` is intentionally not a
    source from which direct-slot evidence can be admitted.
    """
    record = record if isinstance(record, dict) else {}
    extraction_quality = record.get("extraction_quality") if isinstance(record.get("extraction_quality"), dict) else {}
    version_hash = document_version_hash(record)
    material_stage = _document_material_stage(record)
    access = record.get("full_text_acquisition") if isinstance(record.get("full_text_acquisition"), dict) else {}
    return {
        "schema_version": DOCUMENT_SCHEMA_VERSION,
        "paper_id": _paper_id(record),
        "document_id": "doc_" + sha256(_paper_id(record).encode("utf-8")).hexdigest()[:24],
        "document_version_id": "docv_" + sha256(
            f"{_paper_id(record)}|{version_hash}".encode("utf-8")
        ).hexdigest()[:24],
        "document_version_hash": version_hash,
        "content_hash": version_hash,
        "title": _text(record.get("title")),
        "doi_or_stable_identifier": _text(record.get("doi") or record.get("arxiv_id") or record.get("url") or _paper_id(record)),
        "publication_type": _text(record.get("publication_type")) or "UNSPECIFIED",
        # ``source_type`` in PaperGraph often means the import provider
        # (manual/API/metadata), not the epistemic text layer.  Keep those
        # concepts separate and infer document source type only from content.
        "source_type": _text(record.get("document_source_type") or record.get("evidence_source_type")) or ("fulltext" if any(unit.get("source_type") == "fulltext" for unit in _document_text_sections(record)) else "abstract"),
        "source_language": _text(record.get("source_language") or record.get("language")) or "UNSPECIFIED",
        "text_extraction_method": _text(record.get("text_extraction_method") or extraction_quality.get("text_extraction_method") or record.get("extractor")) or "UNSPECIFIED",
        "ocr_quality": record.get("ocr_quality", extraction_quality.get("ocr_confidence")),
        "ingestion_timestamp": record.get("ingestion_timestamp") or record.get("imported_at") or record.get("created_at"),
        "source_url": _text(record.get("source_pdf_url") or record.get("url")),
        "retrieved_at": access.get("retrieved_at") or record.get("imported_at") or record.get("created_at"),
        "license_or_access_basis": _text(
            access.get("license_or_access_basis")
            or access.get("access_basis")
            or record.get("license_or_access_basis")
        ) or "UNSPECIFIED",
        "fulltext_quality": (
            _text(access.get("quality"))
            or _text(record.get("fulltext_quality"))
            or ("NOT_ACQUIRED" if material_stage == "METADATA_DISCOVERED" else "UNASSESSED")
        ),
        "evidence_material_stage": material_stage,
    }


def _build_source_spans_v3_removed(record: dict[str, Any], *, window_size: int = 1) -> list[dict[str, Any]]:
    """Create immutable, source-addressable spans from all usable text forms."""
    record = record if isinstance(record, dict) else {}
    document = build_document_record(record)
    paper_id = document["paper_id"]
    version = document["document_version_hash"]
    spans: list[dict[str, Any]] = []
    extraction_quality = record.get("extraction_quality") if isinstance(record.get("extraction_quality"), dict) else {}
    for unit in _document_text_sections(record):
        section = _text(unit.get("section"))
        section_text = _text(unit.get("text"))
        if not section_text:
            continue
        sentences = [item for item in _SENTENCE_RE.split(section_text) if _text(item)]
        cursor = 0
        for index, sentence in enumerate(sentences):
            quote = _text(sentence)
            if not quote:
                continue
            char_start = section_text.find(sentence, cursor)
            if char_start < 0:
                char_start = cursor
            char_end = char_start + len(sentence)
            cursor = char_end
            material = f"{paper_id}|{version}|{section}|{index}|{char_start}|{char_end}|{quote}"
            span_id = "span_" + sha256(material.encode("utf-8")).hexdigest()[:24]
            spans.append(
                {
                    "schema_version": SOURCE_SPAN_SCHEMA_VERSION,
                    "paper_id": paper_id,
                    "document_id": document["document_id"],
                    "document_version_id": document["document_version_id"],
                    "document_version_hash": version,
                    "source_span_id": span_id,
                    "source_unit_id": span_id,
                    "span_kind": _text(unit.get("span_kind")) or "body_sentence",
                    "source_type": _text(unit.get("source_type")) or "fulltext",
                    "section": section,
                    "source_field": _text(unit.get("source_field")) or section,
                    "source_locator": f"{section}:sentences:{index + 1}",
                    "sentence_start": index,
                    "sentence_end": index,
                    "paragraph_index": unit.get("paragraph_index"),
                    "char_start": int(unit["char_start"]) + char_start if isinstance(unit.get("char_start"), int) else char_start,
                    "char_end": int(unit["char_start"]) + char_end if isinstance(unit.get("char_start"), int) else char_end,
                    "page_number": unit.get("page_number"),
                    "bounding_box": unit.get("bounding_box"),
                    "quote": quote[:4000],
                    "excerpt": quote[:4000],
                    "quote_hash": sha256(quote.encode("utf-8")).hexdigest(),
                    "excerpt_hash": sha256(quote.encode("utf-8")).hexdigest(),
                    "binding_status": "SOURCE_UNIT_VERIFIED",
                    "evidence_material_stage": "SPAN_EXTRACTED",
                    "section_disposition": "INCLUDED",
                    "source_material_status": "SOURCE_BOUND_FULLTEXT",
                    "extraction_quality": {
                        "text_integrity": _text(extraction_quality.get("text_integrity")) or "UNASSESSED",
                        "ocr_confidence": unit.get("ocr_confidence", extraction_quality.get("ocr_confidence")),
                        "layout_confidence": unit.get("layout_confidence", extraction_quality.get("layout_confidence")),
                    },
                }
            )
    return spans


def build_document_record(record: dict[str, Any]) -> dict[str, Any]:
    return build_document_record_v4(record if isinstance(record, dict) else {})


def build_source_spans(
    record: dict[str, Any],
    *,
    window_size: int = 1,
    policy: ScienceExecutionPolicy | None = None,
    use_llm: bool | None = None,
    llm_call: Any | None = None,
) -> list[dict[str, Any]]:
    del window_size
    effective_policy = policy or resolve_science_execution_policy({}, use_llm=use_llm)
    section_set = structure_document_sections(
        record if isinstance(record, dict) else {},
        effective_policy,
        llm_call=llm_call,
    )
    return list(build_evidence_spans(section_set).get("source_spans") or [])


def _assertion_kind(quote: str) -> list[str]:
    kinds: list[str] = []
    if _LIMITATION_RE.search(quote) and _author_limitation_provenance_v3(quote)["status"] == "VERIFIED":
        kinds.append("AUTHOR_LIMITATION")
    if _UNKNOWN_RE.search(quote):
        kinds.append("AUTHOR_UNKNOWN")
    if _MEASUREMENT_RE.search(quote):
        kinds.append("MEASUREMENT_DEFINITION")
    if _MEASUREMENT_VALIDATION_RE.search(quote):
        kinds.append("MEASUREMENT_VALIDATION")
    if _MEASUREMENT_ERROR_RE.search(quote):
        kinds.append("MEASUREMENT_ERROR")
    if _THEORY_RE.search(quote):
        kinds.append("FORMAL_ASSUMPTION" if re.search(r"\bassum", quote, re.IGNORECASE) else "FORMAL_PROPOSITION")
    if _COUNTEREXAMPLE_RE.search(quote):
        kinds.append("FORMAL_COUNTEREXAMPLE")
    if _METHOD_RE.search(quote):
        kinds.append("METHOD_DESCRIPTION")
    if _METHOD_FAILURE_RE.search(quote):
        kinds.append("METHOD_FAILURE")
    if _DATA_RE.search(quote):
        kinds.append("DATASET_COVERAGE")
    if _DATASET_DESCRIPTION_RE.search(quote):
        kinds.append("DATASET_DESCRIPTION")
    if _SCALE_RE.search(quote):
        kinds.append("SCALE_STATEMENT")
    if _BENCHMARK_RE.search(quote):
        kinds.append("BENCHMARK_RESULT")
    if _TRANSLATION_RE.search(quote):
        kinds.append("IMPLEMENTATION_CONSTRAINT")
    if _DEPLOYMENT_OUTCOME_RE.search(quote):
        kinds.append("DEPLOYMENT_OUTCOME")
    if _BOUNDARY_RE.search(quote):
        kinds.append("SCOPE_CONDITION")
    if _CONTRADICTION_RE.search(quote):
        kinds.append("REPLICATION_RESULT")
    if _has_explicit_causal_proposition(quote):
        kinds.append("CAUSAL_CLAIM")
    elif _ASSOCIATION_RE.search(quote):
        kinds.append("ASSOCIATION_RESULT")
    if _RESULT_RE.search(quote):
        kinds.append("EMPIRICAL_RESULT")
    return _unique(kinds)


def _author_limitation_provenance_v3(
    quote: str,
    span: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = _text(quote)
    source = span if isinstance(span, dict) else {}
    attribution_match = _AUTHOR_LIMITATION_ATTRIBUTION_RE.search(text)
    target_match = _AUTHOR_LIMITATION_TARGET_RE.search(text)
    affected_target = _text(
        target_match.group("tested_target")
        or target_match.group("limitation_target")
    ) if target_match else ""
    affected_tokens = [
        token for token in _TOKEN_RE.findall(affected_target.casefold())
        if token not in _AUTHOR_LIMITATION_GENERIC_TARGETS and len(token) > 2
    ]
    truncated = (
        len(text) < 24
        or text.endswith(("...", "…", "-", ",", ":"))
        or text.casefold() in {"unknown", "not tested", "not evaluated", "not examined"}
    )
    has_locator = (
        bool(_text(source.get("source_span_id") or source.get("source_unit_id")))
        and bool(_text(source.get("quote_hash")))
        and (
            bool(_text(source.get("source_locator") or source.get("section")))
            or (
                isinstance(source.get("char_start"), int)
                and isinstance(source.get("char_end"), int)
                and int(source["char_start"]) < int(source["char_end"])
            )
        )
    )
    verified = bool(
        _LIMITATION_RE.search(text)
        and attribution_match
        and affected_tokens
        and not truncated
        and (not source or has_locator)
    )
    return {
        "schema_version": "author_limitation_provenance_v3",
        "status": "VERIFIED" if verified else "REJECTED",
        "author_attribution_phrase": _text(attribution_match.group(0)) if attribution_match else "",
        "affected_object_or_method": affected_target,
        "has_locatable_source_context": has_locator if source else True,
        "source_span_id": _text(source.get("source_span_id") or source.get("source_unit_id")),
        "quote_hash": _text(source.get("quote_hash")),
        "quote_char_start": 0,
        "quote_char_end": len(text),
        "rejection_reason": (
            "AUTHOR_ATTRIBUTION_REQUIRED"
            if not attribution_match
            else "AFFECTED_OBJECT_OR_METHOD_REQUIRED"
            if not affected_tokens
            else "TRUNCATED_OR_TABLE_VALUE_NOT_ALLOWED"
            if truncated
            else "LOCATABLE_SOURCE_CONTEXT_REQUIRED"
            if source and not has_locator
            else ""
        ),
    }


def _attribution(quote: str, kinds: list[str]) -> str:
    if "AUTHOR_LIMITATION" in kinds or "AUTHOR_UNKNOWN" in kinds:
        return "AUTHOR_LIMITATION"
    if _MODAL_RE.search(quote):
        return "AUTHOR_HYPOTHESIS"
    if re.search(r"\b(?:previous|prior|earlier)\s+(?:study|studies|work)\b", quote, re.IGNORECASE):
        return "CITED_WORK_SUMMARY"
    return "AUTHOR_RESULT" if "EMPIRICAL_RESULT" in kinds else "AUTHOR_ASSERTION"


def _epistemic_basis(quote: str, kinds: list[str]) -> str:
    if "AUTHOR_LIMITATION" in kinds or "AUTHOR_UNKNOWN" in kinds:
        return "AUTHOR_STATED_UNKNOWN"
    if _FORMAL_RE.search(quote):
        return "FORMAL_DERIVATION"
    if _INTERVENTION_RE.search(quote):
        return "INTERVENTIONAL"
    if "ASSOCIATION_RESULT" in kinds:
        return "OBSERVATIONAL_ASSOCIATION"
    if "MEASUREMENT_DEFINITION" in kinds:
        return "MEASUREMENT_OR_PROXY"
    if "EMPIRICAL_RESULT" in kinds:
        return "DIRECT_OBSERVATION"
    return "AUTHOR_ASSERTED"


def _relation_kind(quote: str, kinds: list[str]) -> str:
    if "AUTHOR_LIMITATION" in kinds or "AUTHOR_UNKNOWN" in kinds:
        return "UNKNOWN"
    if _has_explicit_causal_proposition(quote):
        return "CAUSES" if _INTERVENTION_RE.search(quote) else "CAUSAL_CLAIM"
    if _ASSOCIATION_RE.search(quote):
        return "ASSOCIATED_WITH"
    if "MEASUREMENT_VALIDATION" in kinds:
        return "CALIBRATES_TO"
    if "MEASUREMENT_DEFINITION" in kinds:
        return "MEASURES"
    if "FORMAL_ASSUMPTION" in kinds:
        return "ASSUMES"
    if "FORMAL_COUNTEREXAMPLE" in kinds:
        return "COUNTEREXAMPLE_TO"
    if "FORMAL_PROPOSITION" in kinds:
        return "DERIVES"
    if "DATASET_COVERAGE" in kinds:
        return "COVERS"
    if "BENCHMARK_RESULT" in kinds:
        return "BENCHMARKS_AGAINST"
    if "IMPLEMENTATION_CONSTRAINT" in kinds:
        return "CONSTRAINED_BY"
    if "DEPLOYMENT_OUTCOME" in kinds:
        return "DEPLOYS_IN"
    if "SCOPE_CONDITION" in kinds:
        return "VALID_UNDER"
    if "REPLICATION_RESULT" in kinds:
        return "CONTRADICTS"
    return "DESCRIBES"


def _assertion_polarity(quote: str) -> str:
    """Preserve textual polarity without turning a result word into causality."""
    lower = _normal(quote)
    if _NEGATION_RE.search(quote):
        return "NEGATED"
    if re.search(r"\b(?:increase(?:d)?|higher|positive|improv(?:e|ed)|supports?)\b", lower):
        return "POSITIVE"
    if re.search(r"\b(?:decrease(?:d)?|lower|negative|worse|fails?)\b", lower):
        return "NEGATIVE"
    return "UNSPECIFIED"


def _quantification(quote: str) -> dict[str, Any]:
    values = re.findall(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:\s*(?:%|×|x))?", quote)
    p_values = re.findall(r"\bp\s*[<=>]\s*0?\.\d+(?:\d+)?", quote, flags=re.IGNORECASE)
    confidence = re.findall(r"\b\d+(?:\.\d+)?\s*%\s*(?:CI|confidence interval)\b", quote, flags=re.IGNORECASE)
    return {
        "reported_values": values[:12],
        "p_values": p_values[:8],
        "confidence_intervals": confidence[:8],
    }


def _study_design_from_quote(quote: str, kinds: list[str]) -> dict[str, Any]:
    return {
        "design_signals": _unique(
            [
                "interventional" if _INTERVENTION_RE.search(quote) else "",
                "formal" if _FORMAL_RE.search(quote) else "",
                "measurement" if any(kind.startswith("MEASUREMENT") for kind in kinds) else "",
                "benchmark" if "BENCHMARK_RESULT" in kinds else "",
                "replication" if "REPLICATION_RESULT" in kinds else "",
                "deployment" if "DEPLOYMENT_OUTCOME" in kinds else "",
            ]
        ),
        "primary_source": True,
    }


def _normalization(contract: dict[str, Any], relation: str, quote: str) -> dict[str, Any]:
    target = contract.get("claim_target") if isinstance(contract.get("claim_target"), dict) else {}
    declared_subject = _text(target.get("target_construct"))
    predicate = relation
    declared_object = _text(target.get("target_relation"))
    source_anchored_entities = [
        value
        for value in (declared_subject, declared_object)
        if value and _normal(value) in _normal(quote)
    ]
    return {
        # A declared question target is an alignment requirement, not an
        # entity assertion.  Only retain a normalized entity when the exact
        # span contains it, so downstream graph nodes cannot be filled from
        # unseen contract language.
        "subject": declared_subject if declared_subject in source_anchored_entities else "",
        "predicate": predicate,
        "object": declared_object if declared_object in source_anchored_entities else "",
        "source_anchored_entities": source_anchored_entities,
    }


def _scope_bindings_from_span_v3(
    span: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Bind declared scope values only to text observable in one source span."""

    declared_scope = dict(contract.get("scientific_scope") or {})
    comparison_contract = _comparison_contract_v4(contract)
    declared_aliases = (
        comparison_contract.get("scope_entity_mappings_v4")
        if isinstance(comparison_contract.get("scope_entity_mappings_v4"), Mapping)
        else {}
    )
    quote = _text(span.get("quote"))
    quote_tokens = _tokens(quote)
    source_span_id = _text(span.get("source_span_id") or span.get("source_unit_id"))
    bindings: dict[str, dict[str, Any]] = {}
    for axis in SCOPE_AXES:
        declared_value = _text(declared_scope.get(axis))
        declared_tokens = _tokens(declared_value)
        if not declared_tokens:
            continue
        alias_entries = (
            declared_aliases.get(axis)
            if isinstance(declared_aliases.get(axis), list)
            else []
        )
        alias_match: tuple[re.Match[str], Mapping[str, Any]] | None = None
        for entry in alias_entries:
            if not isinstance(entry, Mapping):
                continue
            if _normal(entry.get("canonical_value")) != _normal(declared_value):
                continue
            for surface_form in entry.get("accepted_surface_forms") or []:
                surface_text = _text(surface_form)
                if not surface_text:
                    continue
                candidate = re.search(re.escape(surface_text), quote, re.IGNORECASE)
                if candidate is None:
                    continue
                if alias_match is None or len(candidate.group(0)) > len(alias_match[0].group(0)):
                    alias_match = (candidate, entry)
        if alias_match is not None:
            matched_alias, entry = alias_match
            bindings[axis] = {
                "schema_version": "source_scope_binding_v3",
                "canonical_value": declared_value,
                "source_text": _text(matched_alias.group(0)),
                "source_span_id": source_span_id,
                "mapping_method": "EXPLICIT_SCOPE_ALIAS",
                "mapping_confidence": 1.0,
                "scope_entity_mapping_id": _text(entry.get("mapping_id")),
            }
            continue
        exact_match = re.search(re.escape(declared_value), quote, re.IGNORECASE)
        matching_token_count = len(declared_tokens & quote_tokens)
        matched = bool(exact_match) or declared_tokens.issubset(quote_tokens) or (
            len(declared_tokens) >= 3 and matching_token_count >= 2
        )
        if not matched:
            continue
        if exact_match:
            source_text = _text(exact_match.group(0))
            mapping_method = "EXACT_SOURCE_PHRASE"
            confidence = 1.0
        else:
            token_matches = list(re.finditer(r"[A-Za-z0-9][A-Za-z0-9_-]*", quote))
            matched_tokens = [
                match for match in token_matches
                if _normal(match.group(0)) in declared_tokens
            ]
            source_text = _text(
                quote[matched_tokens[0].start():matched_tokens[-1].end()]
            ) if matched_tokens else ""
            mapping_method = "SOURCE_TOKEN_WINDOW"
            confidence = round(matching_token_count / max(1, len(declared_tokens)), 3)
        if not source_text:
            continue
        bindings[axis] = {
            "schema_version": "source_scope_binding_v3",
            "canonical_value": declared_value,
            "source_text": source_text,
            "source_span_id": source_span_id,
            "mapping_method": mapping_method,
            "mapping_confidence": confidence,
            "scope_entity_mapping_id": "",
        }
    return bindings


def _scope_from_span(span: dict[str, Any], contract: dict[str, Any]) -> dict[str, str]:
    bindings = _scope_bindings_from_span_v3(span, contract)
    return {
        axis: _text((bindings.get(axis) or {}).get("canonical_value"))
        for axis in SCOPE_AXES
    }


def _slot_marker_hits(quote: str, contract: dict[str, Any]) -> dict[str, bool]:
    kind = str((contract.get("research_question") or {}).get("question_kind") or "")
    lower = _normal(quote)
    if kind == "BENCHMARK_COMPARISON":
        comparison_contract = _comparison_contract_v4(contract)
        arm_mentions = _comparison_arm_mentions_v4(
            quote,
            comparison_contract,
            source_span_id="",
        )
        has_named_arm = bool(arm_mentions)
        has_pair_relation = len(arm_mentions) >= 2 and bool(
            _COMPARISON_RELATION_RE.search(quote)
        )
        has_metric = bool(_COMPARISON_METRIC_RE.search(quote))
        has_protocol = bool(_COMPARISON_PROTOCOL_RE.search(quote))
        return {
            "candidate_systems": has_named_arm,
            "common_task": has_pair_relation,
            "shared_metric": has_pair_relation and has_metric,
            "comparison_protocol": has_pair_relation and has_protocol,
        }
    rules: dict[str, tuple[str, ...]] = {
        "phenomenon": ("observ", "detect", "found", "result"),
        "target_object": tuple(_tokens((contract.get("scientific_scope") or {}).get("research_object"))),
        "target_condition": ("under", "condition", "regime", "during", "across"),
        "direct_observation": ("observ", "measur", "result", "data"),
        "author_stated_unknown": ("unknown", "unclear", "unresolved", "not tested", "limitation", "insufficient"),
        "affected_claim": ("effect", "relationship", "mechanism", "measurement", "model", "claim"),
        "scope_of_limitation": ("under", "condition", "sample", "system", "method"),
        "exposure": ("expos", "intervention", "treat", "perturb", "manipulat"),
        "outcome": ("outcome", "effect", "response", "result", "performance"),
        "identification_strategy": ("random", "control", "instrument", "quasi", "longitudinal", "confound"),
        "alternative_explanation": ("alternative", "confound", "bias", "cannot distinguish"),
        "construct": ("construct", "latent", "property", "quantity"),
        "proxy_measure": ("proxy", "surrogate", "indicator", "instrument", "sensor", "assay"),
        "target_measure": ("reference", "gold standard", "direct measure", "validation"),
        "mapping_status": ("valid", "calibrat", "correspond", "error", "reliab"),
        "formal_claim": ("theorem", "proposition", "lemma", "equation", "model"),
        "assumption": ("assum", "axiom", "given"),
        "validity_domain": ("valid", "under", "regime", "condition", "domain"),
        "falsification_path": ("counterexample", "test", "falsif", "violate"),
        "current_method": ("method", "protocol", "algorithm", "estimator"),
        "failure_mode": ("fail", "error", "bias", "limitation"),
        "bias_or_identification_problem": ("bias", "confound", "identif", "selection"),
        "evaluation_criterion": ("accuracy", "error", "metric", "performance"),
        "required_variable": ("variable", "feature", "covariate", "label"),
        "coverage_dimension": ("coverage", "sample", "population", "regime", "time"),
        "covered_range": ("cover", "across", "range", "sampled"),
        "missing_range": ("missing", "absent", "not available", "underrepresented"),
        "impact_on_claim": ("affect", "limit", "bias", "conclusion"),
        "source_scale": ("micro", "local", "fine", "small scale"),
        "target_scale": ("macro", "global", "coarse", "large scale"),
        "bridge_variable": ("bridge", "coupl", "aggregate", "scale"),
        "coupling_question": ("link", "coupl", "transfer", "integrat"),
        "validated_claim": ("validated", "demonstrated", "established"),
        "deployment_context": ("deployment", "field", "real-world", "implementation"),
        "implementation_barrier": ("barrier", "cost", "safety", "adoption", "constraint"),
        "feasibility_question": ("feasib", "deploy", "implement"),
        "base_relation": ("relationship", "effect", "associated", "causal"),
        "boundary_variable": ("condition", "regime", "threshold", "context"),
        "condition_a": ("under", "condition", "regime"),
        "condition_b": ("versus", "compared", "different", "across"),
        "comparable_endpoint": ("outcome", "effect", "response", "metric"),
        "shared_claim": ("result", "effect", "claim", "relationship"),
        "result_a": ("increase", "decrease", "positive", "negative"),
        "result_b": ("increase", "decrease", "positive", "negative"),
        "comparability_axes": ("condition", "method", "measure", "sample"),
        "common_input": ("input", "exposure", "intervention", "condition"),
        "common_outcome": ("outcome", "effect", "response"),
        "mechanism_a": ("mechanism", "pathway", "process"),
        "mechanism_b": ("alternative", "competing", "mechanism", "pathway"),
        "discriminating_prediction": ("distinguish", "prediction", "test", "discriminat"),
        "source_domain": ("source domain", "training", "original", "development"),
        "target_domain": ("target domain", "external", "deployment", "new domain"),
        "shift_type": ("shift", "distribution", "transfer", "generaliz"),
        "model_or_claim": ("model", "claim", "prediction", "effect"),
    }
    required = list((contract.get("evidence_contract") or {}).get("required_slots") or [])
    outcome: dict[str, bool] = {}
    for slot in required:
        markers = rules.get(str(slot), ())
        outcome[str(slot)] = bool(markers and any(marker in lower for marker in markers))
    if kind == "AUTHOR_STATED_LIMITATION" and _LIMITATION_RE.search(quote):
        outcome["author_stated_unknown"] = True
        # The affected claim can be a relation, measurement, model, or any
        # explicitly limited question clause.  Avoid requiring the literal
        # word "claim"—authors rarely use it in a limitation sentence.
        outcome["affected_claim"] = bool(
            _CAUSAL_RE.search(quote)
            or _ASSOCIATION_RE.search(quote)
            or _MEASUREMENT_RE.search(quote)
            or _THEORY_RE.search(quote)
            or _METHOD_RE.search(quote)
            or re.search(r"\b(?:whether|how|why|effect|relationship|outcome|model|result)\b", quote, re.IGNORECASE)
        )
    return outcome


def _slot_declared_values(contract: dict[str, Any], slot: str) -> list[str]:
    """Return V2-declared values that may satisfy one named slot.

    The source must still contain one of these values.  This only narrows an
    assertion to the current contract; it never turns declaration text into
    evidence or reads a historic causal-chain field.
    """

    boundary = contract.get("boundary_contract") if isinstance(contract.get("boundary_contract"), dict) else {}
    mapping = contract.get("measurement_mapping") if isinstance(contract.get("measurement_mapping"), dict) else {}
    threshold = contract.get("threshold_governance") if isinstance(contract.get("threshold_governance"), dict) else {}
    scope = contract.get("scientific_scope") if isinstance(contract.get("scientific_scope"), dict) else {}
    operationalization = contract.get("operationalization") if isinstance(contract.get("operationalization"), dict) else {}
    values_by_slot = {
        "condition_a": [boundary.get("condition_a")],
        "condition_b": [boundary.get("condition_b")],
        "comparable_endpoint": [boundary.get("comparable_endpoint"), scope.get("outcome_definition")],
        "construct": [mapping.get("construct"), operationalization.get("primary_construct")],
        "proxy_measure": [mapping.get("proxy_measure"), operationalization.get("operational_measure")],
        "target_measure": [mapping.get("target_measure")],
        "mapping_status": [mapping.get("mapping_basis"), mapping.get("status")],
        "target_condition": [scope.get("condition_or_regime")],
        "target_object": [scope.get("research_object")],
        "shared_metric": [scope.get("outcome_definition"), operationalization.get("operational_measure")],
        "common_task": [operationalization.get("comparison_unit"), operationalization.get("unit_of_analysis")],
        "threshold": [threshold.get("threshold_definition")],
        "evaluation_criterion": [operationalization.get("decision_rule")],
        "deployment_context": [scope.get("deployment_context")],
    }
    return _unique(values_by_slot.get(slot, []))


def _contains_declared_slot_value(quote: str, values: Iterable[str]) -> bool:
    quote_tokens = _tokens(quote)
    for value in values:
        value_tokens = _tokens(value)
        if value_tokens and value_tokens.issubset(quote_tokens):
            return True
    return False


def _matched_declared_slot_values(quote: str, values: Iterable[str]) -> list[str]:
    """Return the declared slot values explicitly present in a source quote."""

    quote_tokens = _tokens(quote)
    return [
        _text(value)
        for value in values
        if (value_tokens := _tokens(value)) and value_tokens.issubset(quote_tokens)
    ]


def _comparison_unit_signature(
    scope_tuple: Mapping[str, Any],
    *,
    scope_bindings: Mapping[str, Any] | None = None,
    shared_metric: str = "",
    require_comparison_components: bool = False,
) -> str:
    """Return the source-stated unit that can join complementary slot spans.

    A document identity alone is not a comparison unit.  Complementary spans
    may form a V2 coherence bundle only when they state the same declared
    scope axis in their own text.  The signature intentionally uses no domain
    vocabulary and remains empty when no such source-bound axis is present.
    """

    axes = (
        "research_object",
        "population_or_system",
        "sample_or_model",
        "measurement_definition",
        "outcome_definition",
    )
    bindings = scope_bindings if isinstance(scope_bindings, Mapping) else {}
    source_values = {
        axis: _text(
            (bindings.get(axis) or {}).get("source_text")
            if isinstance(bindings.get(axis), Mapping)
            else scope_tuple.get(axis)
        )
        for axis in axes
    }
    if not require_comparison_components:
        return "|".join(
            f"{axis}={_normal(value)}"
            for axis, value in source_values.items()
            if value
        )
    object_or_system = next(
        (
            source_values[axis]
            for axis in ("research_object", "population_or_system", "sample_or_model")
            if source_values.get(axis)
        ),
        "",
    )
    endpoint = next(
        (
            source_values[axis]
            for axis in ("outcome_definition", "measurement_definition")
            if source_values.get(axis)
        ),
        "",
    )
    metric = _text(shared_metric)
    if not object_or_system or not endpoint or not metric:
        return ""
    material = "|".join((
        f"object_or_system={_normal(object_or_system)}",
        f"endpoint={_normal(endpoint)}",
        f"metric={_normal(metric)}",
    ))
    return "sha256:" + sha256(material.encode("utf-8")).hexdigest()


def _comparison_contract_v4(contract: Mapping[str, Any]) -> dict[str, Any]:
    value = contract.get("comparison_contract_v4")
    return dict(value) if isinstance(value, Mapping) and value.get("schema_version") == "comparison_contract_v4" else {}


def _comparison_arm_mentions_v4(
    quote: str,
    comparison_contract: Mapping[str, Any],
    *,
    source_span_id: str,
) -> list[dict[str, str]]:
    quote_normalized = _normal(quote)
    arms = [
        comparison_contract.get("primary_arm"),
        *(comparison_contract.get("comparator_arms") or []),
    ]
    matches: list[dict[str, str]] = []
    for arm in arms:
        if not isinstance(arm, Mapping):
            continue
        arm_id = _text(arm.get("arm_id"))
        forms = _unique([
            arm.get("canonical_label"), *(arm.get("accepted_surface_forms") or []),
        ])
        matched = next(
            (form for form in forms if _normal(form) and _normal(form) in quote_normalized),
            "",
        )
        if arm_id and matched:
            matches.append({
                "arm_id": arm_id,
                "surface_text": matched,
                "source_span_id": source_span_id,
            })
    return matches


def _comparison_relation_type_v4(quote: str) -> str:
    lower = _normal(quote)
    if re.search(r"\b(?:two|both)\s+(?:conditions?|regimes?|settings?)\b", lower):
        return "CONDITION_VS_CONDITION"
    if re.search(r"\b(?:two|both)\s+systems?\b", lower):
        return "SYSTEM_VS_SYSTEM"
    if re.search(r"\b(?:two|both)\s+models?\b", lower):
        return "MODEL_VS_MODEL"
    if re.search(r"\b(?:two|both)\s+(?:methods?|techniques?|assays?|algorithms?)\b", lower):
        return "METHOD_VS_METHOD"
    signal_types = {
        "METHOD_VS_METHOD": bool(re.search(
            r"\b(?:method|technique|instrument|assay|algorithm|approach|measurement)\b", lower
        )),
        "MODEL_VS_MODEL": bool(re.search(r"\b(?:model|classifier|predictor|network)\b", lower)),
        "SYSTEM_VS_SYSTEM": bool(re.search(r"\b(?:system|device|platform|apparatus)\b", lower)),
        "CONDITION_VS_CONDITION": bool(re.search(r"\b(?:condition|regime|setting)\b", lower)),
    }
    active = [kind for kind, present in signal_types.items() if present]
    return active[0] if len(active) == 1 else "NONE"


def _comparison_phrase(match: re.Match[str] | None) -> str:
    return _text(match.group(0)) if match is not None else ""


def _extract_comparison_frame_v4(
    quote: str,
    contract: Mapping[str, Any],
    *,
    source_span_id: str,
    scope_tuple: Mapping[str, Any],
    scope_bindings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract one source-bound arm or direct-pair evidence frame."""

    comparison_contract = _comparison_contract_v4(contract)
    if not comparison_contract:
        return {}
    arm_mentions = _comparison_arm_mentions_v4(
        quote, comparison_contract, source_span_id=source_span_id
    )
    arm_ids = {item["arm_id"] for item in arm_mentions}
    primary_arm = comparison_contract.get("primary_arm") or {}
    primary_id = _text(primary_arm.get("arm_id"))
    direct_pairs = {
        tuple(_unique(pair))
        for pair in comparison_contract.get("target_comparison_pairs") or []
        if isinstance(pair, list) and len(_unique(pair)) == 2
    }
    matched_pair = next(
        (
            pair for pair in direct_pairs
            if set(pair).issubset(arm_ids) and primary_id in pair
        ),
        (),
    )
    relation_match = _COMPARISON_RELATION_RE.search(quote)
    protocol_match = _COMPARISON_PROTOCOL_RE.search(quote)
    metric_match = _COMPARISON_METRIC_RE.search(quote)
    comparison_unit = {
        axis: _text(scope_tuple.get(axis))
        for axis in comparison_contract.get("comparability_axes") or []
        if _text(scope_tuple.get(axis))
    }
    comparison_unit_bindings = {
        axis: dict(binding)
        for axis, binding in (scope_bindings or {}).items()
        if axis in comparison_unit and isinstance(binding, Mapping)
    }
    object_anchor_present = bool(
        comparison_unit.get("research_object")
        or comparison_unit.get("population_or_system")
        or comparison_unit.get("sample_or_model")
    )
    endpoint = _text(comparison_unit.get("outcome_definition")) or _comparison_phrase(metric_match)
    metric = _comparison_phrase(metric_match) or endpoint
    protocol = _comparison_phrase(protocol_match)
    expected_relation_type = _text(comparison_contract.get("comparison_kind"))
    relation_type = _comparison_relation_type_v4(quote)
    missing: list[str] = []
    if not matched_pair:
        missing.append("declared_direct_arm_pair")
    if not relation_match:
        missing.append("explicit_comparison_relation")
    if relation_type != expected_relation_type:
        missing.append("comparison_relation_type")
    if not object_anchor_present or not endpoint:
        missing.append("comparison_unit")
    if not metric:
        missing.append("shared_metric")
    if not protocol:
        missing.append("comparison_protocol")
    if not missing:
        admission_status = "DIRECT_PAIR_ADMITTED"
    elif len(arm_mentions) == 1:
        admission_status = "COMPONENT_ONLY"
    elif len(arm_mentions) >= 2:
        admission_status = "PARTIAL_COMPARABILITY"
    else:
        admission_status = "REJECTED"
    unit_signature = _comparison_unit_signature(
        comparison_unit,
        scope_bindings=comparison_unit_bindings,
        shared_metric=metric,
        require_comparison_components=True,
    )
    reason_codes: list[str] = []
    if relation_type == "SYSTEM_VS_SYSTEM" and expected_relation_type == "METHOD_VS_METHOD":
        reason_codes.append("COMPARISON_RELATION_IS_SYSTEM_NOT_METHOD")
    elif relation_type != expected_relation_type:
        reason_codes.append("COMPARISON_RELATION_TYPE_MISMATCH")
    if not arm_mentions:
        reason_codes.append("GENERIC_METHOD_MENTION_ONLY")
    elif not matched_pair:
        reason_codes.append("MISSING_COMPARATOR_ARM")
    if not object_anchor_present:
        reason_codes.append("OUT_OF_SCOPE_RESEARCH_OBJECT")
    if not endpoint or not metric:
        reason_codes.append("MISSING_SHARED_ENDPOINT")
    if not unit_signature:
        reason_codes.append("MISSING_COMPARISON_UNIT")
    if not protocol:
        reason_codes.append("MISSING_COMPARISON_PROTOCOL")
    metric_signature = (
        "metric=" + _normal(metric) if metric else ""
    )
    protocol_signature = (
        "protocol=" + _normal(protocol) if protocol else ""
    )
    return {
        "schema_version": "comparison_frame_v4",
        "comparison_contract_id": _text(comparison_contract.get("comparison_contract_id")),
        "comparison_relation_type": relation_type,
        "expected_comparison_relation_type": expected_relation_type,
        "arm_mentions": arm_mentions,
        "matched_direct_pair": list(matched_pair),
        "comparison_relation_span_id": source_span_id if relation_match else "",
        "comparison_relation_text": _comparison_phrase(relation_match),
        "comparison_unit": comparison_unit,
        "comparison_unit_bindings_v4": comparison_unit_bindings,
        "comparison_unit_id": unit_signature,
        "comparison_unit_signature": unit_signature,
        "shared_metric": {
            "text": metric,
            "source_span_id": source_span_id if metric else "",
            "signature": metric_signature,
        },
        "protocol": {
            "text": protocol,
            "source_span_id": source_span_id if protocol else "",
            "signature": protocol_signature,
        },
        "admission_status": admission_status,
        "missing_requirement_ids": missing,
        "diagnostic_reason_codes": _unique(reason_codes),
    }


def _quote_has_comparison_unit(quote: str) -> bool:
    return bool(_INTERVENTION_RE.search(quote) or re.search(
        r"\b(?:versus|vs\.?|compared\s+(?:with|to)|between|relative\s+to|difference\s+between|respectively)\b",
        quote,
        re.IGNORECASE,
    ))


def _quote_has_reference_mapping(quote: str) -> bool:
    return bool(_MEASUREMENT_VALIDATION_RE.search(quote) or re.search(
        r"\b(?:mapped?|mapping|correspond(?:s|ence)?|agreement|traceab(?:le|ility)|reference)\b",
        quote,
        re.IGNORECASE,
    ))


def _has_current_contract_scope_anchor(quote: str, contract: dict[str, Any]) -> bool:
    """Require a specific current-contract scope anchor in the source quote."""

    quote_tokens = _tokens(quote)
    scope = contract.get("scientific_scope") if isinstance(contract.get("scientific_scope"), dict) else {}
    candidates = [
        scope.get("research_object"),
        scope.get("population_or_system"),
        scope.get("sample_or_model"),
        scope.get("measurement_definition"),
        scope.get("outcome_definition"),
    ]
    for value in candidates:
        value_tokens = _tokens(value)
        if not value_tokens:
            continue
        if value_tokens.issubset(quote_tokens):
            return True
        # A long declared phrase may be expressed in a source with a shorter,
        # exact noun phrase.  Two specific shared tokens are enough to bind it
        # to the current contract, while one generic token is never enough.
        if len(value_tokens) >= 3 and len(value_tokens & quote_tokens) >= 2:
            return True
    return False


def _slot_supports(
    quote: str,
    contract: dict[str, Any],
    *,
    assertion_id: str,
    paper_id: str,
    document_version_hash: str,
    source_span_ids: list[str],
    source_unit_ids: list[str],
    quote_hash: str,
    source_locations: list[dict[str, Any]],
    source_type: str,
    span_kind: str,
    assertion_kinds: list[str],
    relation_kind: str,
    scope_tuple: dict[str, str],
    scope_bindings: Mapping[str, Any] | None,
    quantification: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return source-bound, slot-specific V3 admission decisions.

    A marker hit is merely a candidate signal.  ``ADMITTED`` requires the
    explicit assertion to meet the contract's declared requirement profile.
    This is deliberately stricter than the legacy boolean coverage surface.
    """

    definitions = contract.get("slot_definitions") if isinstance(contract.get("slot_definitions"), dict) else {}
    required_slots = list((contract.get("evidence_contract") or {}).get("required_slots") or [])
    marker_hits = _slot_marker_hits(quote, contract)
    quote_tokens = _tokens(quote)
    comparison_frame = _extract_comparison_frame_v4(
        quote,
        contract,
        source_span_id=source_span_ids[0] if source_span_ids else "",
        scope_tuple=scope_tuple,
        scope_bindings=scope_bindings,
    )
    supports: list[dict[str, Any]] = []
    for slot in required_slots:
        if comparison_frame:
            frame_status = _text(comparison_frame.get("admission_status"))
            arm_mentions = list(comparison_frame.get("arm_mentions") or [])
            comparison_unit = comparison_frame.get("comparison_unit")
            shared_metric = comparison_frame.get("shared_metric")
            protocol = comparison_frame.get("protocol")
            slot_requirement_present = {
                # Arm-first collection deliberately admits evidence for either
                # declared arm. A two-arm match is only required by the direct
                # comparison artifact, never by a single-source assertion.
                "candidate_systems": len(arm_mentions) >= 1,
                "common_task": bool(comparison_unit),
                "shared_metric": bool(
                    isinstance(shared_metric, Mapping) and _text(shared_metric.get("text"))
                ),
                "comparison_protocol": bool(
                    isinstance(protocol, Mapping) and _text(protocol.get("text"))
                ),
            }.get(str(slot), False)
            direct = frame_status == "DIRECT_PAIR_ADMITTED" and slot_requirement_present
            has_named_arm = bool(arm_mentions)
            source_is_context_only = (
                _text(source_type).lower() != "fulltext"
                or _text(span_kind).lower() in {"title", "abstract"}
            )
            frame_missing = list(comparison_frame.get("missing_requirement_ids") or [])
            if not slot_requirement_present:
                frame_missing.append(f"comparison_slot:{slot}")
            if not has_named_arm:
                status = "REJECTED"
            elif not direct:
                status = "INCOMPLETE"
            elif source_is_context_only:
                status = "CONTEXT_ONLY"
            else:
                status = "ADMITTED"
            supports.append({
                "schema_version": "slot_support_v3",
                "slot_id": str(slot),
                "assertion_id": assertion_id,
                "paper_id": paper_id,
                "document_version_hash": document_version_hash,
                "source_span_ids": list(source_span_ids),
                "source_unit_ids": list(source_unit_ids),
                "quote_hash": quote_hash,
                "source_locations": [dict(item) for item in source_locations],
                "support_status": status,
                "supported_requirement_ids": (
                    ["named_declared_arm_pair", "explicit_comparison_relation", f"comparison_slot:{slot}"]
                    if direct else []
                ),
                "missing_requirement_ids": sorted(set(frame_missing)),
                "assertion_kind": list(assertion_kinds),
                "relation_kind": relation_kind,
                "scope_tuple": dict(scope_tuple or {}),
                "matched_declared_slot_values": [
                    _text(item.get("surface_text")) for item in arm_mentions
                ],
                "comparison_unit_signature": _text(
                    comparison_frame.get("comparison_unit_signature")
                ),
                "comparison_frame_v4": dict(comparison_frame),
                "diagnostic_reason_codes": list(
                    comparison_frame.get("diagnostic_reason_codes") or []
                ),
                "slot_specificity": "DIRECT" if status == "ADMITTED" else "PARTIAL" if has_named_arm else "NONE",
                "admission_reason": (
                    "The current full-text span explicitly compares a declared arm pair under a shared source-bound frame."
                    if status == "ADMITTED"
                    else "The span names one declared comparison arm but is component context, not direct pair evidence."
                    if frame_status == "COMPONENT_ONLY"
                    else "The span names comparison arms but lacks one or more direct comparison requirements: "
                    + ", ".join(sorted(set(frame_missing)))
                    if has_named_arm else "The span contains no comparison-contract declared arm."
                ),
            })
            continue
        definition = definitions.get(slot) if isinstance(definitions.get(slot), dict) else {}
        requirements = definition.get("admission_requirements") if isinstance(definition.get("admission_requirements"), dict) else {}
        declared_values = _slot_declared_values(contract, str(slot))
        matched_declared_values = _matched_declared_slot_values(quote, declared_values)
        slot_terms = _tokens(" ".join(definition.get("retrieval_concepts") or []))
        has_scope_anchor = _has_current_contract_scope_anchor(quote, contract)
        has_slot_anchor = bool(slot_terms & quote_tokens)
        marker_hit = bool(marker_hits.get(slot))
        supported_requirements: list[str] = []
        missing_requirements: list[str] = []
        has_slot_semantic_anchor = (
            marker_hit
            or has_slot_anchor
            or _contains_declared_slot_value(quote, declared_values)
        )
        if has_slot_semantic_anchor:
            supported_requirements.append("slot_semantic_anchor")
        else:
            missing_requirements.append("slot_semantic_anchor")
        if has_scope_anchor or _contains_declared_slot_value(quote, declared_values):
            supported_requirements.append("current_scope_anchor")
        else:
            missing_requirements.append("current_scope_anchor")
        if has_slot_anchor or _contains_declared_slot_value(quote, declared_values):
            supported_requirements.append("declared_slot_anchor")
        else:
            missing_requirements.append("declared_slot_anchor")
        if requirements.get("requires_named_slot_value"):
            if matched_declared_values:
                supported_requirements.append("named_slot_value")
            else:
                missing_requirements.append("named_slot_value")
        if requirements.get("requires_quantification"):
            if any(quantification.get(key) for key in ("reported_values", "p_values", "confidence_intervals")):
                supported_requirements.append("quantification")
            else:
                missing_requirements.append("quantification")
        if requirements.get("requires_comparison_relation"):
            if _quote_has_comparison_unit(quote):
                supported_requirements.append("comparison_relation")
            else:
                missing_requirements.append("comparison_relation")
        if requirements.get("requires_reference_mapping"):
            if _quote_has_reference_mapping(quote) or relation_kind == "CALIBRATES_TO":
                supported_requirements.append("reference_mapping")
            else:
                missing_requirements.append("reference_mapping")
        allowed_kinds = set(requirements.get("allowed_assertion_kinds") or [])
        if allowed_kinds and not (allowed_kinds & set(assertion_kinds)):
            missing_requirements.append("allowed_assertion_kind")
        allowed_relations = set(requirements.get("allowed_relation_kinds") or [])
        if allowed_relations and relation_kind not in allowed_relations:
            missing_requirements.append("allowed_relation_kind")
        source_is_context_only = (
            _text(source_type).lower() != "fulltext"
            or _text(span_kind).lower() in {"title", "abstract"}
        )
        status = (
            "REJECTED"
            if not has_slot_semantic_anchor
            else "INCOMPLETE"
            if missing_requirements
            else "CONTEXT_ONLY"
            if source_is_context_only
            else "ADMITTED"
        )
        supports.append({
            "schema_version": "slot_support_v3",
            "slot_id": str(slot),
            "assertion_id": assertion_id,
            "paper_id": paper_id,
            "document_version_hash": document_version_hash,
            "source_span_ids": list(source_span_ids),
            "source_unit_ids": list(source_unit_ids),
            "quote_hash": quote_hash,
            "source_locations": [dict(item) for item in source_locations],
            "support_status": status,
            "supported_requirement_ids": sorted(set(supported_requirements)),
            "missing_requirement_ids": sorted(set(missing_requirements)),
            "assertion_kind": list(assertion_kinds),
            "relation_kind": relation_kind,
            "scope_tuple": dict(scope_tuple or {}),
            "matched_declared_slot_values": matched_declared_values,
            "comparison_unit_signature": _comparison_unit_signature(scope_tuple),
            "slot_specificity": "DIRECT" if status == "ADMITTED" else "PARTIAL" if has_slot_semantic_anchor else "NONE",
            "admission_reason": (
                "All V3 slot-specific source-bound requirements are present."
                if status == "ADMITTED"
                else "Source span is relevant context only and cannot fill a direct evidence slot."
                if status == "CONTEXT_ONLY"
                else "Source span is related but misses declared slot-specific requirements."
                if status == "INCOMPLETE"
                else "Source span does not contain the required slot semantics."
            ),
        })
    return supports


def _slot_coverage_from_support(slot_support: list[dict[str, Any]]) -> dict[str, bool]:
    return {
        str(item.get("slot_id") or ""): (
            item.get("support_status") == "VERIFIED_NONCOUNTING"
            and item.get("admission_status") == "DIRECT_SLOT_ADMITTED"
        )
        for item in slot_support
        if str(item.get("slot_id") or "")
    }


def _extract_explicit_assertions_v3_removed(
    record: dict[str, Any],
    question_contract: dict[str, Any],
    *,
    source_spans: list[dict[str, Any]] | None = None,
    use_llm: bool = False,
) -> list[dict[str, Any]]:
    """Extract only assertions whose quote and source span can be verified."""
    contract = validate_research_question_contract(question_contract)
    spans = source_spans if isinstance(source_spans, list) else build_source_spans(record)
    assertions: list[dict[str, Any]] = []
    for span in spans:
        if not isinstance(span, dict) or span.get("schema_version") != SOURCE_SPAN_SCHEMA_VERSION:
            continue
        quote = _text(span.get("quote"))
        if not quote:
            continue
        kinds = _assertion_kind(quote)
        author_limitation_provenance = (
            _author_limitation_provenance_v3(quote, span)
            if "AUTHOR_LIMITATION" in kinds
            else {}
        )
        if author_limitation_provenance and author_limitation_provenance["status"] != "VERIFIED":
            kinds = [kind for kind in kinds if kind != "AUTHOR_LIMITATION"]
        provisional_slot_hits = _slot_marker_hits(quote, contract)
        if not kinds and not any(provisional_slot_hits.values()):
            continue
        relation = _relation_kind(quote, kinds)
        normalization = _normalization(contract, relation, quote)
        contract_revision, contract_hash = _contract_version_fields(contract)
        material = (
            f"{span.get('source_span_id')}|{relation}|{'|'.join(kinds)}|"
            f"{contract.get('contract_id')}|{contract_revision}|{contract_hash}"
        )
        assertion_id = "assert_" + sha256(material.encode("utf-8")).hexdigest()[:24]
        scope_bindings = _scope_bindings_from_span_v3(span, contract)
        scope_tuple = {
            axis: _text((scope_bindings.get(axis) or {}).get("canonical_value"))
            for axis in SCOPE_AXES
        }
        quantification = _quantification(quote)
        slot_support = _slot_supports(
            quote,
            contract,
            assertion_id=assertion_id,
            paper_id=_text(span.get("paper_id")),
            document_version_hash=_text(span.get("document_version_hash")),
            source_span_ids=[span["source_span_id"]],
            source_unit_ids=[_text(span.get("source_unit_id"))],
            quote_hash=_text(span.get("quote_hash")),
            source_locations=[{
                key: span.get(key)
                for key in (
                    "source_locator", "source_field", "section", "page_number",
                    "paragraph_index", "sentence_start", "sentence_end",
                    "char_start", "char_end",
                )
                if span.get(key) not in {None, ""}
            }],
            source_type=_text(span.get("source_type")),
            span_kind=_text(span.get("span_kind")),
            assertion_kinds=kinds,
            relation_kind=relation,
            scope_tuple=scope_tuple,
            scope_bindings=scope_bindings,
            quantification=quantification,
        )
        slot_coverage = _slot_coverage_from_support(slot_support)
        assertions.append(
            {
                "schema_version": EVIDENCE_ASSERTION_SCHEMA_VERSION,
                "assertion_id": assertion_id,
                "paper_id": _text(span.get("paper_id")),
                "document_version_hash": _text(span.get("document_version_hash")),
                "source_span_ids": [span["source_span_id"]],
                "source_unit_ids": [span["source_unit_id"]],
                "sub_hypothesis_id": _text(contract.get("sub_hypothesis_id")),
                "research_question_contract_id": _text(contract.get("contract_id")),
                "research_question_contract_revision": contract_revision,
                "research_question_contract_hash": contract_hash,
                "textual_explicitness": "EXPLICIT",
                "assertion_origin": "SOURCE_EXPLICIT",
                "derivation_status": "NOT_DERIVED",
                "evidence_material_stage": "ASSERTION_EXTRACTED",
                "causal_relation_status": (
                    "SOURCE_STATED_CAUSAL"
                    if relation in {"CAUSES", "CAUSAL_CLAIM"}
                    else "NOT_A_CAUSAL_ASSERTION"
                ),
                "attribution": _attribution(quote, kinds),
                "assertion_kinds": kinds,
                "relation_kind": relation,
                "subject": normalization["subject"],
                "predicate": normalization["predicate"],
                "object": normalization["object"],
                "polarity": _assertion_polarity(quote),
                "modality": "SUGGESTIVE" if _MODAL_RE.search(quote) else "ASSERTED",
                "epistemic_basis": _epistemic_basis(quote, kinds),
                "scope_tuple": scope_tuple,
                "scope_bindings_v3": scope_bindings,
                "study_design": _study_design_from_quote(quote, kinds),
                "quantification": quantification,
                "slot_support": slot_support,
                "slot_coverage": slot_coverage,
                "comparison_frame_v4": next(
                    (
                        dict(item.get("comparison_frame_v4") or {})
                        for item in slot_support
                        if isinstance(item, Mapping)
                        and isinstance(item.get("comparison_frame_v4"), Mapping)
                    ),
                    {},
                ),
                "quote_hash": span.get("quote_hash"),
                "quote_char_start": 0,
                "quote_char_end": len(quote),
                **({"author_limitation_provenance_v3": author_limitation_provenance} if author_limitation_provenance else {}),
                "extraction_status": "EXTRACTED",
                "normalization": normalization,
                "extraction_method": "deterministic_span_grounded_v3",
                "unsupported_slots": [
                    item["slot_id"]
                    for item in slot_support
                    if item.get("admission_status") != "DIRECT_SLOT_ADMITTED"
                ],
            }
        )
    if use_llm:
        assertions.extend(_llm_explicit_assertion_suggestions(spans, contract))
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...], str]] = set()
    for assertion in assertions:
        key = (
            _text(assertion.get("quote_hash")),
            tuple(sorted(_unique(assertion.get("assertion_kinds") or []))),
            _text(assertion.get("research_question_contract_id")),
            _text(assertion.get("research_question_contract_revision")),
            _text(assertion.get("research_question_contract_hash")),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(assertion)
    return deduped


def _llm_explicit_assertion_suggestions_v3_removed(spans: list[dict[str, Any]], contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Optionally add quote-verified semantic labels for difficult wording.

    The LLM is intentionally not asked to infer a relation.  It can only
    select an allowed assertion kind and copy an exact quote from one supplied
    span; every suggestion is locally verified before it becomes an assertion.
    """
    try:
        try:
            from ._llm import call_llm_json
        except ImportError:
            from _llm import call_llm_json
        allowed_kinds = [
            "AUTHOR_LIMITATION", "AUTHOR_UNKNOWN", "MEASUREMENT_DEFINITION", "MEASUREMENT_VALIDATION",
            "MEASUREMENT_ERROR", "FORMAL_ASSUMPTION", "FORMAL_PROPOSITION", "FORMAL_COUNTEREXAMPLE",
            "METHOD_DESCRIPTION", "METHOD_FAILURE", "DATASET_DESCRIPTION", "DATASET_COVERAGE",
            "SCALE_STATEMENT", "BENCHMARK_RESULT", "IMPLEMENTATION_CONSTRAINT", "DEPLOYMENT_OUTCOME",
            "SCOPE_CONDITION", "REPLICATION_RESULT", "CAUSAL_CLAIM", "ASSOCIATION_RESULT", "EMPIRICAL_RESULT",
        ]
        source_by_id = {str(item.get("source_span_id") or ""): item for item in spans if isinstance(item, dict)}
        payload = call_llm_json(
            system=(
                "You extract only explicit, verbatim scientific statements from supplied source spans. "
                "Never infer missing facts, never use external knowledge, and never rewrite a source quote. Return JSON only."
            ),
            prompt=(
                "For each source span, return zero or more assertions only when an exact quote supports one allowed kind. "
                "Return {\"assertions\":[{\"source_span_id\":...,\"quote\":...,\"assertion_kind\":...}]}\n"
                f"Allowed assertion kinds: {json.dumps(allowed_kinds)}\n"
                "Each item must also include quote_char_start and quote_char_end measured within that source span's quote. "
                "Label AUTHOR_LIMITATION only when the exact sentence attributes the limitation to the authors or their study, names an affected object or method, and is not a table cell, fragment, or truncated sentence. "
                f"Source spans: {json.dumps([{'source_span_id': item.get('source_span_id'), 'quote': item.get('quote')} for item in spans[:32]], ensure_ascii=False)}"
            ),
            max_tokens=2400,
            fallback_list_key="assertions",
        )
    except Exception:
        return []
    suggestions = payload.get("assertions") if isinstance(payload.get("assertions"), list) else []
    output: list[dict[str, Any]] = []
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        span = source_by_id.get(_text(suggestion.get("source_span_id")))
        quote = _text(suggestion.get("quote"))
        kind = _text(suggestion.get("assertion_kind"))
        span_quote = _text(span.get("quote")) if isinstance(span, dict) else ""
        start = suggestion.get("quote_char_start")
        end = suggestion.get("quote_char_end")
        offsets_valid = (
            isinstance(start, int)
            and isinstance(end, int)
            and 0 <= start < end <= len(span_quote)
            and _normal(span_quote[start:end]) == _normal(quote)
        )
        if (
            not span
            or kind not in allowed_kinds
            or not quote
            or _normal(quote) not in _normal(span_quote)
            or not offsets_valid
        ):
            continue
        author_limitation_provenance = (
            _author_limitation_provenance_v3(quote, span)
            if kind == "AUTHOR_LIMITATION"
            else {}
        )
        if author_limitation_provenance and author_limitation_provenance["status"] != "VERIFIED":
            continue
        contract_revision, contract_hash = _contract_version_fields(contract)
        material = (
            f"{span.get('source_span_id')}|{kind}|{quote}|{contract.get('contract_id')}|"
            f"{contract_revision}|{contract_hash}"
        )
        relation = _relation_kind(quote, [kind])
        normalization = _normalization(contract, relation, quote)
        quantification = _quantification(quote)
        assertion_id = "assert_" + sha256(material.encode("utf-8")).hexdigest()[:24]
        scope_bindings = _scope_bindings_from_span_v3(span, contract)
        scope_tuple = {
            axis: _text((scope_bindings.get(axis) or {}).get("canonical_value"))
            for axis in SCOPE_AXES
        }
        slot_support = _slot_supports(
            quote,
            contract,
            assertion_id=assertion_id,
            paper_id=_text(span.get("paper_id")),
            document_version_hash=_text(span.get("document_version_hash")),
            source_span_ids=[span["source_span_id"]],
            source_unit_ids=[_text(span.get("source_unit_id"))],
            quote_hash=_text(span.get("quote_hash")),
            source_locations=[{
                key: span.get(key)
                for key in (
                    "source_locator", "source_field", "section", "page_number",
                    "paragraph_index", "sentence_start", "sentence_end",
                    "char_start", "char_end",
                )
                if span.get(key) not in {None, ""}
            }],
            source_type=_text(span.get("source_type")),
            span_kind=_text(span.get("span_kind")),
            assertion_kinds=[kind],
            relation_kind=relation,
            scope_tuple=scope_tuple,
            scope_bindings=scope_bindings,
            quantification=quantification,
        )
        slot_coverage = _slot_coverage_from_support(slot_support)
        output.append(
            {
                "schema_version": EVIDENCE_ASSERTION_SCHEMA_VERSION,
                "assertion_id": assertion_id,
                "paper_id": _text(span.get("paper_id")),
                "document_version_hash": _text(span.get("document_version_hash")),
                "source_span_ids": [span["source_span_id"]],
                "source_unit_ids": [span["source_unit_id"]],
                "sub_hypothesis_id": _text(contract.get("sub_hypothesis_id")),
                "research_question_contract_id": _text(contract.get("contract_id")),
                "research_question_contract_revision": contract_revision,
                "research_question_contract_hash": contract_hash,
                "textual_explicitness": "EXPLICIT",
                "assertion_origin": "SOURCE_EXPLICIT",
                "derivation_status": "NOT_DERIVED",
                "evidence_material_stage": "ASSERTION_EXTRACTED",
                "causal_relation_status": (
                    "SOURCE_STATED_CAUSAL"
                    if relation in {"CAUSES", "CAUSAL_CLAIM"}
                    else "NOT_A_CAUSAL_ASSERTION"
                ),
                "attribution": _attribution(quote, [kind]),
                "assertion_kinds": [kind],
                "relation_kind": relation,
                "subject": normalization["subject"],
                "predicate": normalization["predicate"],
                "object": normalization["object"],
                "polarity": _assertion_polarity(quote),
                "modality": "SUGGESTIVE" if _MODAL_RE.search(quote) else "ASSERTED",
                "epistemic_basis": _epistemic_basis(quote, [kind]),
                "scope_tuple": scope_tuple,
                "scope_bindings_v3": scope_bindings,
                "study_design": _study_design_from_quote(quote, [kind]),
                "quantification": quantification,
                "slot_support": slot_support,
                "slot_coverage": slot_coverage,
                "comparison_frame_v4": next(
                    (
                        dict(item.get("comparison_frame_v4") or {})
                        for item in slot_support
                        if isinstance(item, Mapping)
                        and isinstance(item.get("comparison_frame_v4"), Mapping)
                    ),
                    {},
                ),
                "quote_hash": sha256(quote.encode("utf-8")).hexdigest(),
                "quote_char_start": start,
                "quote_char_end": end,
                **({"author_limitation_provenance_v3": author_limitation_provenance} if author_limitation_provenance else {}),
                "normalization": normalization,
                "extraction_method": "llm_span_parser_then_exact_quote_validator_v3",
                "unsupported_slots": [
                    item["slot_id"]
                    for item in slot_support
                    if item.get("admission_status") != "DIRECT_SLOT_ADMITTED"
                ],
            }
        )
    return output


def extract_explicit_assertions(
    record: dict[str, Any],
    question_contract: dict[str, Any],
    *,
    source_spans: list[dict[str, Any]] | None = None,
    policy: ScienceExecutionPolicy | None = None,
    use_llm: bool | None = None,
    llm_call: Any | None = None,
) -> list[dict[str, Any]]:
    contract = validate_research_question_contract(question_contract)
    effective_policy = policy or resolve_science_execution_policy({}, use_llm=use_llm)
    if isinstance(source_spans, list):
        document = build_document_record(record)
        span_set = {
            "schema_version": "evidence_span_set_v6",
            "document": document,
            "source_spans": source_spans,
            "coverage_manifest": [{
                "source_span_id": item.get("source_span_id"),
                "section_heading": item.get("section_heading"),
                "section_disposition": item.get("section_disposition"),
                "status": "PENDING" if item.get("extraction_eligible") is True else "SKIPPED",
                "reason_codes": list(item.get("eligibility_reason_codes") or []),
            } for item in source_spans if isinstance(item, dict)],
            "status": "STRUCTURED",
            "reason_codes": [],
        }
    else:
        section_set = structure_document_sections(record, effective_policy, llm_call=llm_call)
        span_set = build_evidence_spans(section_set)
    extraction = extract_document_propositions(span_set, effective_policy, llm_call=llm_call)
    alignment = align_propositions_to_contract(
        extraction,
        contract,
        effective_policy,
        task_scope={
            "research_question_task_id": _text(contract.get("research_question_task_id")),
            "target_slot_ids": list(contract.get("target_slot_ids") or []),
        },
        llm_call=llm_call,
    )
    return list(alignment.get("assertions") or [])


def _assertion_source_span(
    assertion: dict[str, Any],
    source_spans_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    embedded = assertion.get("source_span")
    if isinstance(embedded, dict):
        return embedded
    index = source_spans_by_id if isinstance(source_spans_by_id, dict) else {}
    for span_id in assertion.get("source_span_ids", []):
        span = index.get(_text(span_id))
        if isinstance(span, dict):
            return span
    return {}


def compare_scope(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    required_axes: Iterable[str],
    source_spans_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    left_scope = left.get("scope_tuple") if isinstance(left.get("scope_tuple"), dict) else {}
    right_scope = right.get("scope_tuple") if isinstance(right.get("scope_tuple"), dict) else {}
    aligned: list[str] = []
    mismatched: list[str] = []
    unknown: list[str] = []
    bridge_axes: set[str] = set()

    def explicit_bridge_axes(assertion: dict[str, Any]) -> set[str]:
        """Return only source-bound, explicit scope bridges.

        A declared SH scope is not a bridge argument.  A bridge must be
        attached to the source span that stated it, identify the axes it
        bridges, and quote a phrase that is actually present in that span.
        This leaves room for formal scale/transport arguments without letting
        arbitrary record metadata erase an otherwise material scope mismatch.
        """
        span = _assertion_source_span(assertion, source_spans_by_id)
        bridge = assertion.get("scope_bridge") if isinstance(assertion.get("scope_bridge"), dict) else (
            span.get("scope_bridge") if isinstance(span.get("scope_bridge"), dict) else {}
        )
        phrase = _text(bridge.get("supporting_phrase") or bridge.get("quote"))
        span_quote = _normal(span.get("quote") or assertion.get("quote"))
        axes = {
            _text(axis)
            for axis in bridge.get("bridged_axes", [])
            if _text(axis)
        }
        if bridge.get("textual_explicitness") != "EXPLICIT" or not phrase or _normal(phrase) not in span_quote:
            return set()
        return axes

    bridge_axes = explicit_bridge_axes(left) & explicit_bridge_axes(right)
    for axis in _unique(required_axes):
        left_value = _normal(left_scope.get(axis))
        right_value = _normal(right_scope.get(axis))
        if left_value and right_value:
            if left_value == right_value or axis in bridge_axes:
                aligned.append(axis)
            else:
                mismatched.append(axis)
        else:
            unknown.append(axis)
    status = (
        "MISMATCHED"
        if mismatched
        else "PARTIALLY_ALIGNED"
        if aligned and unknown
        else "INSUFFICIENT_SCOPE_INFORMATION"
        if unknown
        else "ALIGNED"
    )
    return {
        "status": status,
        "aligned_axes": aligned,
        "mismatched_axes": mismatched,
        "unknown_axes": unknown,
        "bridge_axes": sorted(bridge_axes),
        "alignment_basis": "EXPLICIT_SOURCE_BOUND_SCOPE_BRIDGE" if bridge_axes else "DIRECT_SCOPE_COMPARISON",
    }


def _assertion_paper_ids(assertion: dict[str, Any]) -> set[str]:
    span = _assertion_source_span(assertion)
    values = [assertion.get("paper_id"), span.get("paper_id")]
    ids = {_text(value) for value in values if _text(value)}
    # Direct unit-level calls may not yet have PaperGraph document metadata.
    # Preserve a deterministic *provisional* source identity for diagnostic
    # comparison only.  It is never primary evidence and real graph assembly
    # always supplies paper ids from source spans.
    if not ids:
        ids = {
            "provisional:" + _text(item)
            for item in assertion.get("source_span_ids", [])
            if _text(item)
        }
    return ids


def _comparable_relation(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Require the same explicit relation and compatible normalized claim.

    Contract targets are not evidence.  The guard therefore uses them only to
    determine whether two assertions declare the *same* target; it does not
    treat an empty normalization as similarity.
    """
    if _text(left.get("relation_kind")) != _text(right.get("relation_kind")):
        return False
    left_norm = left.get("normalization") if isinstance(left.get("normalization"), dict) else {}
    right_norm = right.get("normalization") if isinstance(right.get("normalization"), dict) else {}
    compared = [
        ("subject", _normal(left_norm.get("subject")), _normal(right_norm.get("subject"))),
        ("object", _normal(left_norm.get("object")), _normal(right_norm.get("object"))),
    ]
    populated = [(field, a, b) for field, a, b in compared if a or b]
    # A caller that has only source spans and relation labels has not claimed
    # subject/object compatibility.  Allow only a provisional diagnostic
    # comparison; graph-built assertions contain populated normalizations.
    if not populated:
        return True
    left_anchored = {_normal(value) for value in left_norm.get("source_anchored_entities", []) if _normal(value)}
    right_anchored = {_normal(value) for value in right_norm.get("source_anchored_entities", []) if _normal(value)}
    return all(
        a and b and a == b and a in left_anchored and b in right_anchored
        for _field, a, b in populated
    )


def build_comparability_pair_index(
    assertions: list[dict[str, Any]],
    contracts: list[dict[str, Any]],
    *,
    per_bucket_pair_limit: int = 64,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """Plan the bounded, source-independent comparisons for a V2 graph.

    Pair planning is intentionally shared by derived-inference and graph-level
    comparability projections.  It prevents two independently quadratic loops
    from examining the same assertion universe, while preserving an explicit
    diagnostic whenever a semantically comparable bucket exceeds its budget.
    """
    contract_by_id = {
        _text(contract.get("contract_id")): validate_research_question_contract(contract)
        for contract in contracts
        if isinstance(contract, dict) and _text(contract.get("contract_id"))
    }
    limit = max(1, int(per_bucket_pair_limit or 1))
    buckets: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for assertion in assertions:
        if not isinstance(assertion, dict):
            continue
        assertion_id = _text(assertion.get("assertion_id"))
        contract_id = _text(assertion.get("research_question_contract_id"))
        if not assertion_id or contract_id not in contract_by_id:
            continue
        if not list(assertion.get("admitted_slot_ids_v4") or []):
            continue
        if not list(assertion.get("source_span_ids") or []) or not _text(assertion.get("document_version_hash")):
            continue
        normalization = assertion.get("normalization") if isinstance(assertion.get("normalization"), dict) else {}
        predicate = _normal(normalization.get("predicate") or assertion.get("predicate"))
        subject = _normal(normalization.get("subject") or assertion.get("subject"))
        obj = _normal(normalization.get("object") or assertion.get("object"))
        if not predicate:
            continue
        buckets.setdefault((contract_id, predicate, subject, obj), []).append(assertion)
    pairs_by_contract: dict[str, list[tuple[str, str]]] = defaultdict(list)
    diagnostics: list[dict[str, Any]] = []
    candidate_pair_count = 0
    representative_candidate_pair_count = 0
    selected_pair_count = 0
    truncated_bucket_count = 0
    processed_bucket_count = 0
    representative_limit = 4

    def representative_assertions(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep a bounded, slot-diverse assertion set for one paper."""
        ordered = sorted(
            members,
            key=lambda item: (
                -len({
                    _text(slot)
                    for slot in item.get("admitted_slot_ids_v4", [])
                    if _text(slot)
                }),
                -len({
                    _text(kind)
                    for kind in item.get("assertion_kinds", [])
                    if _text(kind)
                }),
                -sum(
                    1
                    for value in (
                        item.get("scope_tuple")
                        if isinstance(item.get("scope_tuple"), dict)
                        else {}
                    ).values()
                    if _text(value)
                ),
                _text(item.get("assertion_id")),
            ),
        )
        selected: list[dict[str, Any]] = []
        seen_slot_signatures: set[tuple[str, ...]] = set()
        for item in ordered:
            signature = tuple(sorted({
                _text(slot)
                for slot in item.get("admitted_slot_ids_v4", [])
                if _text(slot)
            }))
            if signature in seen_slot_signatures:
                continue
            seen_slot_signatures.add(signature)
            selected.append(item)
            if len(selected) >= representative_limit:
                return selected
        for item in ordered:
            if item in selected:
                continue
            selected.append(item)
            if len(selected) >= representative_limit:
                break
        return selected

    for bucket_key, members in sorted(buckets.items()):
        contract_id = bucket_key[0]
        by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for assertion in members:
            paper_ids = _assertion_paper_ids(assertion)
            if len(paper_ids) != 1 or not _comparable_relation(assertion, assertion):
                continue
            by_paper[next(iter(paper_ids))].append(assertion)
        paper_ids = sorted(by_paper)
        source_counts = [len(by_paper[paper_id]) for paper_id in paper_ids]
        candidate_count = max(
            0,
            (sum(source_counts) ** 2 - sum(count ** 2 for count in source_counts)) // 2,
        )
        representatives_by_paper = {
            paper_id: representative_assertions(by_paper[paper_id])
            for paper_id in paper_ids
        }
        representative_counts = [
            len(representatives_by_paper[paper_id]) for paper_id in paper_ids
        ]
        representative_candidate_count = max(
            0,
            (
                sum(representative_counts) ** 2
                - sum(count ** 2 for count in representative_counts)
            ) // 2,
        )
        selected: list[tuple[str, str]] = []
        # Enumerate at most the actual pair budget.  The previous nested
        # assertion loop visited every combination merely to discover that it
        # would keep the first ``limit``.  Here the deterministic distance
        # order visits no more than ``limit`` paper pairs, while rotating each
        # paper's bounded representatives to retain slot-role diversity.
        for distance in range(1, len(paper_ids)):
            if len(selected) >= limit:
                break
            for left_index, left_paper in enumerate(paper_ids[:-distance]):
                right_paper = paper_ids[left_index + distance]
                left_values = representatives_by_paper[left_paper]
                right_values = representatives_by_paper[right_paper]
                pair_index = len(selected)
                left = left_values[pair_index % len(left_values)]
                right = right_values[(pair_index // len(left_values)) % len(right_values)]
                selected.append((
                    _text(left.get("assertion_id")),
                    _text(right.get("assertion_id")),
                ))
                if len(selected) >= limit:
                    break
        candidate_pair_count += candidate_count
        representative_candidate_pair_count += representative_candidate_count
        selected_pair_count += len(selected)
        pairs_by_contract[contract_id].extend(selected)
        if candidate_count > len(selected):
            truncated_bucket_count += 1
            diagnostics.append(
                {
                    "schema_version": "comparability_pair_planner_diagnostic_v1",
                    "reason": "COMPARABILITY_SEARCH_SPACE_TRUNCATED",
                    "research_question_contract_id": contract_id,
                    "bucket_key": {
                        "predicate": bucket_key[1],
                        "subject": bucket_key[2],
                        "object": bucket_key[3],
                    },
                    "candidate_pair_count": candidate_count,
                    "representative_candidate_pair_count": representative_candidate_count,
                    "selected_pair_count": len(selected),
                    "omitted_pair_count": max(0, candidate_count - len(selected)),
                    "representative_assertion_limit_per_paper": representative_limit,
                    "per_bucket_pair_limit": limit,
                    "interpretation": (
                        "The bounded comparison budget was exhausted; omitted pairs are "
                        "unassessed rather than evidence of no heterogeneity."
                    ),
                }
            )
        processed_bucket_count += 1
        if progress_callback is not None:
            progress_callback({
                "processed_bucket_count": processed_bucket_count,
                "bucket_count": len(buckets),
                "candidate_pair_count": candidate_pair_count,
                "selected_pair_count": selected_pair_count,
                "truncated_bucket_count": truncated_bucket_count,
            })
    return {
        "schema_version": "comparability_pair_index_v1",
        "pairs_by_contract": {
            contract_id: pairs
            for contract_id, pairs in sorted(pairs_by_contract.items())
        },
        "summary": {
            "bucket_count": len(buckets),
            "candidate_pair_count": candidate_pair_count,
            "representative_candidate_pair_count": representative_candidate_pair_count,
            "selected_pair_count": selected_pair_count,
            "truncated_bucket_count": truncated_bucket_count,
            "per_bucket_pair_limit": limit,
            "representative_assertion_limit_per_paper": representative_limit,
        },
        "diagnostics": diagnostics,
    }


def derive_inferences(
    assertions: list[dict[str, Any]],
    question_contract: dict[str, Any],
    *,
    source_spans_by_id: dict[str, dict[str, Any]] | None = None,
    pair_index: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Create bounded diagnostic inferences; none can become primary evidence."""
    contract = validate_research_question_contract(question_contract)
    required_axes = list((contract.get("evidence_contract") or {}).get("required_comparability_axes") or [])
    output: list[dict[str, Any]] = []
    assertions_by_id = {
        _text(assertion.get("assertion_id")): assertion
        for assertion in assertions
        if isinstance(assertion, dict) and _text(assertion.get("assertion_id"))
    }
    contract_id = _text(contract.get("contract_id"))
    planned_pairs = (
        (pair_index or {}).get("pairs_by_contract", {}).get(contract_id, [])
        if isinstance(pair_index, dict)
        else []
    )
    if pair_index is None:
        planned_pairs = [
            (_text(left.get("assertion_id")), _text(right.get("assertion_id")))
            for left_index, left in enumerate(assertions)
            if isinstance(left, dict)
            for right in assertions[left_index + 1 :]
            if isinstance(right, dict)
        ]
    for pair in planned_pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        left, right = assertions_by_id.get(_text(pair[0])), assertions_by_id.get(_text(pair[1]))
        if not isinstance(left, dict) or not isinstance(right, dict):
            continue
        if left.get("source_span_ids") == right.get("source_span_ids"):
            continue
        left_papers = _assertion_paper_ids(left)
        right_papers = _assertion_paper_ids(right)
        if not left_papers or not right_papers or left_papers & right_papers:
            continue
        if not _comparable_relation(left, right):
            continue
        scope = compare_scope(
            left,
            right,
            required_axes=required_axes,
            source_spans_by_id=source_spans_by_id,
        )
        kind = ""
        interpretation = ""
        if scope["status"] == "ALIGNED" and left.get("polarity") != right.get("polarity"):
            kind = "CROSS_SOURCE_COMPARISON"
            interpretation = (
                "Comparable assertions have divergent polarities; retrieve a common-protocol comparison before calling this a contradiction."
            )
        elif scope["status"] == "MISMATCHED":
            kind = "SCOPE_MISMATCH"
            interpretation = "The same relation appears under non-aligned scopes; this is a boundary lead, not a resolved heterogeneity claim."
        elif scope["status"] in {"INSUFFICIENT_SCOPE_INFORMATION", "PARTIALLY_ALIGNED"}:
            kind = "SCOPE_INFORMATION_SHORTAGE"
            interpretation = (
                "Assertions cannot be compared until missing declared comparability axes are recovered from source context; "
                "this is a retrieval/extraction diagnostic, not a scientific-gap signal."
            )
        if not kind:
            continue
        material = f"{kind}|{left.get('assertion_id')}|{right.get('assertion_id')}"
        output.append(
            {
                "schema_version": DERIVED_INFERENCE_SCHEMA_VERSION,
                "inference_id": "infer_" + sha256(material.encode("utf-8")).hexdigest()[:24],
                "inference_kind": kind,
                "input_assertion_ids": [left.get("assertion_id"), right.get("assertion_id")],
                "derived_from_assertion_ids": [left.get("assertion_id"), right.get("assertion_id")],
                "input_source_span_ids": list(left.get("source_span_ids") or []) + list(right.get("source_span_ids") or []),
                "input_paper_ids": sorted(left_papers | right_papers),
                "derivation_rule": "independent_source_scope_and_relation_comparison_v4",
                "scope_alignment": scope,
                "candidate_interpretation": interpretation,
                "alternative_interpretations": ["measurement_definition_differs", "study_design_differs", "unreported_scope_difference"],
                "route_ceiling": "DIAGNOSTIC" if kind == "SCOPE_INFORMATION_SHORTAGE" else "TARGETED_RETRIEVAL",
                "cannot_support": ["direct_causal_claim", "validated_gap_by_itself", "primary_source_span_gate", "primary_research_package"],
            }
        )
    return output


def build_heterogeneous_evidence_graph_v4_from_tanxi_view(
    evidence_view: dict[str, Any],
    *,
    per_bucket_pair_limit: int = 64,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """Build a V4 graph input from immutable, already-admitted V4 evidence.

    TanXi operates after retrieval has persisted source spans and explicit
    assertions.  Re-extracting those records here would reread full texts,
    repeat LLM work, and make a graph build depend on mutable extraction
    settings.  The evidence view is therefore the only TanXi graph input:
    assertions remain source-local, admissions come from the retrieval ledger,
    and derived inferences use one bounded pair plan.
    """
    source = evidence_view if isinstance(evidence_view, dict) else {}
    if _text(source.get("schema_version")) != "tanxi_evidence_view_v4":
        raise ValueError(
            "V4 evidence graph construction requires tanxi_evidence_view_v4"
        )
    contracts = [
        validate_research_question_contract(item)
        for item in source.get("contracts", [])
        if isinstance(item, dict)
    ]
    contracts_by_id = {
        _text(contract.get("contract_id")): contract
        for contract in contracts
        if _text(contract.get("contract_id"))
    }
    spans = [item for item in source.get("source_spans", []) if isinstance(item, dict)]
    incompatible_spans = [
        item for item in spans
        if _text(item.get("schema_version")) != SOURCE_SPAN_SCHEMA_VERSION
    ]
    if incompatible_spans:
        raise ValueError("V4 evidence graph rejects non-V4 source-span artifacts")
    span_ids = {
        _text(item.get("source_span_id") or item.get("source_unit_id"))
        for item in spans
        if _text(item.get("source_span_id") or item.get("source_unit_id"))
    }
    spans_by_id = {
        _text(item.get("source_span_id") or item.get("source_unit_id")): item
        for item in spans
        if _text(item.get("source_span_id") or item.get("source_unit_id"))
    }
    artifact_integrity_errors = [
        dict(item)
        for item in source.get("artifact_integrity_errors_v4", [])
        if isinstance(item, dict)
    ]
    assertions: list[dict[str, Any]] = []
    admissions: dict[str, dict[str, Any]] = {}
    for raw_assertion in source.get("assertions", []):
        if not isinstance(raw_assertion, dict):
            continue
        assertion = dict(raw_assertion)
        if _text(assertion.get("schema_version")) != EVIDENCE_ASSERTION_SCHEMA_VERSION:
            raise ValueError("V4 evidence graph rejects non-V4 assertion artifacts")
        if (
            _text(assertion.get("textual_explicitness")) != "EXPLICIT"
            or _text(assertion.get("assertion_origin")) != "SOURCE_EXPLICIT"
            or _text(assertion.get("derivation_status")) not in {"", "NOT_DERIVED"}
        ):
            # Derived interpretations belong to the diagnostic inference
            # layer.  They cannot enter the canonical assertion/admission
            # ledger through a text-extraction lookalike.
            artifact_integrity_errors.append({
                "schema_version": "artifact_integrity_error_v3",
                "error_code": "NONEXPLICIT_OR_DERIVED_ASSERTION_IN_CANONICAL_LAYER",
                "assertion_id": _text(assertion.get("assertion_id")),
                "excluded_from_evidence_graph": True,
            })
            continue
        assertion_id = _text(assertion.get("assertion_id"))
        contract_id = _text(assertion.get("research_question_contract_id"))
        integrity_error = _assertion_provenance_integrity_error(assertion)
        if integrity_error is not None:
            artifact_integrity_errors.append(integrity_error)
            continue
        if contract_id not in contracts_by_id:
            artifact_integrity_errors.append(
                {
                    "schema_version": "artifact_integrity_error_v4",
                    "error_code": "ASSERTION_CURRENT_CONTRACT_NOT_FOUND",
                    "assertion_id": assertion_id,
                    "paper_id": _text(assertion.get("paper_id")),
                    "research_question_contract_id": contract_id,
                    "excluded_from_evidence_graph": True,
                }
            )
            continue
        if any(
            _text(span_id) not in span_ids
            for span_id in assertion.get("source_span_ids", [])
        ):
            artifact_integrity_errors.append(
                {
                    "schema_version": "artifact_integrity_error_v4",
                    "error_code": "ASSERTION_REFERENCES_UNAVAILABLE_SOURCE_SPAN",
                    "assertion_id": assertion_id,
                    "paper_id": _text(assertion.get("paper_id")),
                    "research_question_contract_id": contract_id,
                    "excluded_from_evidence_graph": True,
                }
            )
            continue
        assertion_spans = [
            spans_by_id[_text(span_id)]
            for span_id in assertion.get("source_span_ids", [])
            if _text(span_id) in spans_by_id
        ]
        if not assertion_spans or any(
            _text(span.get("source_type")) != "fulltext"
            or _text(span.get("span_kind")) in {"title", "abstract"}
            or _text(span.get("section_disposition")) != "INCLUDED"
            or _text(span.get("source_material_status")) != "SOURCE_BOUND_FULLTEXT"
            or _text(span.get("binding_status")) != "SOURCE_UNIT_VERIFIED"
            or not _text(span.get("source_locator"))
            for span in assertion_spans
        ):
            artifact_integrity_errors.append(
                {
                    "schema_version": "artifact_integrity_error_v4",
                    "error_code": "DIRECT_ADMISSION_REQUIRES_FULLTEXT_SOURCE_SPAN",
                    "assertion_id": assertion_id,
                    "paper_id": _text(assertion.get("paper_id")),
                    "research_question_contract_id": contract_id,
                    "excluded_from_evidence_graph": True,
                }
            )
            continue
        admitted_slots = sorted({
            _text(slot_id)
            for slot_id in assertion.get("admitted_slot_ids_v4", [])
            if _text(slot_id)
        })
        comparison_evidence = assertion.get("comparison_evidence_v4")
        comparison_evidence = (
            comparison_evidence
            if isinstance(comparison_evidence, Mapping)
            else {}
        )
        is_arm_coverage_assertion = (
            assertion.get("counts_toward_arm_coverage") is True
            and _text(comparison_evidence.get("evidence_type")) == "ARM_EVIDENCE"
            and any(
                isinstance(match, Mapping) and _text(match.get("arm_id"))
                for match in comparison_evidence.get("arm_matches", [])
            )
        )
        if not admitted_slots and not is_arm_coverage_assertion:
            artifact_integrity_errors.append(
                {
                    "schema_version": "artifact_integrity_error_v4",
                    "error_code": "ASSERTION_NOT_ADMITTED_BY_V4_EVIDENCE_LEDGER",
                    "assertion_id": assertion_id,
                    "paper_id": _text(assertion.get("paper_id")),
                    "research_question_contract_id": contract_id,
                    "excluded_from_evidence_graph": True,
                }
        )
            continue
        assertion["admitted_slot_ids_v4"] = admitted_slots
        assertion["evidence_material_stage"] = (
            "ARM_COVERAGE_ADMITTED"
            if is_arm_coverage_assertion and not admitted_slots
            else "ASSERTION_ADMITTED"
        )
        assertions.append(assertion)
        admission_key = f"{_text(assertion.get('paper_id'))}:{contract_id}"
        admission = admissions.setdefault(
            admission_key,
            {
                "schema_version": GAP_SOURCE_ADMISSION_SCHEMA_VERSION,
                "paper_id": _text(assertion.get("paper_id")),
                "research_question_contract_id": contract_id,
                "direct_evidence_eligible": bool(admitted_slots),
                "slot_eligible": bool(admitted_slots),
                "eligible_slot_ids": [],
                "admitted_assertion_ids": [],
                "arm_coverage_assertion_ids": [],
                "admission_policy": "V4_EVIDENCE_LEDGER_SOURCE_ADMISSION",
            },
        )
        if is_arm_coverage_assertion:
            admission["arm_coverage_assertion_ids"].append(assertion_id)
        if admitted_slots:
            admission["direct_evidence_eligible"] = True
            admission["slot_eligible"] = True
        admission["eligible_slot_ids"] = sorted(
            set(admission["eligible_slot_ids"]) | set(admitted_slots)
        )
        admission["admitted_assertion_ids"].append(assertion_id)
    for admission in admissions.values():
        admission["admitted_assertion_ids"] = sorted(set(admission["admitted_assertion_ids"]))
        admission["arm_coverage_assertion_ids"] = sorted(
            set(admission.get("arm_coverage_assertion_ids") or [])
        )
    assertion_admissions = [
        {
            "schema_version": EVIDENCE_ADMISSION_SCHEMA_VERSION,
            "admission_id": "eadm_" + sha256(
                f"{_text(assertion.get('assertion_id'))}|{slot_id}|"
                f"{_text(assertion.get('research_question_contract_id'))}|"
                f"{_text(assertion.get('document_version_hash'))}".encode("utf-8")
            ).hexdigest()[:24],
            "status": "ADMITTED_DIRECT_SLOT",
            "assertion_id": _text(assertion.get("assertion_id")),
            "source_span_ids": [
                _text(span_id) for span_id in assertion.get("source_span_ids", [])
                if _text(span_id)
            ],
            "paper_id": _text(assertion.get("paper_id")),
            "document_version_hash": _text(assertion.get("document_version_hash")),
            "research_question_contract_id": _text(
                assertion.get("research_question_contract_id")
            ),
            "slot_id": slot_id,
            "admission_basis": "FULLTEXT_SOURCE_SPAN_PLUS_EXPLICIT_ASSERTION_PLUS_SLOT_REVIEW",
        }
        for assertion in assertions
        for slot_id in assertion.get("admitted_slot_ids_v4", [])
        if _text(slot_id)
    ]
    pair_index = build_comparability_pair_index(
        assertions,
        contracts,
        per_bucket_pair_limit=per_bucket_pair_limit,
        progress_callback=progress_callback,
    )
    # A comparison conclusion is intentionally not a property of any one
    # document.  The TanXi view is the production graph path, so retain each
    # arm-local assertion above and assemble the strict, project-level result
    # here.  This only consumes persisted assertions and never reopens the
    # document/proposition pipeline.
    comparison_synthesis_artifacts: list[dict[str, Any]] = []
    for contract in contracts:
        if not _comparison_contract_v4(contract):
            continue
        contract_id = _text(contract.get("contract_id"))
        comparison_synthesis_artifacts.append(
            build_comparison_synthesis_artifact_v4(
                contract,
                [
                    assertion
                    for assertion in assertions
                    if _text(assertion.get("research_question_contract_id"))
                    == contract_id
                ],
            )
        )
    inferences: list[dict[str, Any]] = []
    for contract in contracts:
        contract_id = _text(contract.get("contract_id"))
        inferences.extend(
            derive_inferences(
                [
                    assertion
                    for assertion in assertions
                    if _text(assertion.get("research_question_contract_id")) == contract_id
                ],
                contract,
                source_spans_by_id=spans_by_id,
                pair_index=pair_index,
            )
        )
    evidence_links = build_evidence_links(assertions, contracts)
    entities: dict[str, dict[str, Any]] = {}
    relations: list[dict[str, Any]] = []
    for assertion in assertions:
        normalization = assertion.get("normalization") if isinstance(assertion.get("normalization"), dict) else {}
        subject = _text(assertion.get("subject") or normalization.get("subject"))
        predicate = _text(assertion.get("predicate") or normalization.get("predicate"))
        obj = _text(assertion.get("object") or normalization.get("object"))
        for node in _relation_nodes(assertion):
            current = entities.setdefault(node["entity_id"], {**node, "roles": []})
            if node["node_type"] not in current["roles"]:
                current["roles"].append(node["node_type"])
        relations.append(
            {
                "relation_id": "rel_" + sha256(
                    f"{assertion['assertion_id']}|{predicate}".encode("utf-8")
                ).hexdigest()[:20],
                "assertion_id": assertion["assertion_id"],
                "relation_kind": predicate,
                "subject": subject,
                "object": obj,
                "textual_explicitness": "EXPLICIT",
                "epistemic_basis": assertion.get("epistemic_basis"),
                "scope_tuple": assertion.get("scope_tuple"),
                "source_assertion_id": assertion.get("assertion_id"),
                "document_version_hash": assertion.get("document_version_hash"),
                "primary_eligible": False,
            }
        )
    documents = [item for item in source.get("documents", []) if isinstance(item, dict)]
    return {
        "schema_version": HETEROGENEOUS_EVIDENCE_GRAPH_SCHEMA_VERSION,
        "source_spans": spans,
        "assertions": assertions,
        "documents": documents,
        "evidence_links": evidence_links,
        "derived_inferences": inferences,
        "relations": relations,
        "entities": list(entities.values()),
        "source_admissions": admissions,
        "evidence_admissions": assertion_admissions,
        "unlinked_source_records": [],
        "artifact_integrity_errors_v4": artifact_integrity_errors,
        "comparability_pair_index": pair_index,
        "comparison_synthesis_artifacts_v4": comparison_synthesis_artifacts,
        "diagnostics": list(pair_index.get("diagnostics") or []),
        "summary": {
            "source_span_count": len(spans),
            "explicit_assertion_count": len(assertions),
            "derived_inference_count": len(inferences),
            "relation_count": len(relations),
            "evidence_link_count": len(evidence_links),
            "direct_slot_admission_count": len(assertion_admissions),
            "assertion_kind_counts": dict(Counter(kind for item in assertions for kind in item.get("assertion_kinds", []))),
            "epistemic_basis_counts": dict(Counter(_text(item.get("epistemic_basis")) for item in assertions)),
            "unlinked_source_record_count": 0,
            "artifact_integrity_error_count": len(artifact_integrity_errors),
            "comparability_pair_planner": dict(pair_index.get("summary") or {}),
            "comparison_arm_coverage_count": sum(
                len(item.get("arm_coverage") or {})
                for item in comparison_synthesis_artifacts
            ),
            "comparison_synthesis_ready_count": sum(
                1
                for item in comparison_synthesis_artifacts
                for synthesis in item.get("syntheses") or []
                if isinstance(synthesis, Mapping)
                and _text(synthesis.get("conclusion_status")) == "READY"
            ),
            "comparison_synthesis_pending_count": sum(
                1
                for item in comparison_synthesis_artifacts
                for synthesis in item.get("syntheses") or []
                if isinstance(synthesis, Mapping)
                and _text(synthesis.get("conclusion_status")) == "PENDING"
            ),
            "comparison_synthesis_failed_count": sum(
                1
                for item in comparison_synthesis_artifacts
                for synthesis in item.get("syntheses") or []
                if isinstance(synthesis, Mapping)
                and _text(synthesis.get("comparability_status")) == "FAIL"
            ),
        },
    }


def _comparison_pair_id_v4(pair: Iterable[Any]) -> str:
    """Return the canonical identity of one declared target comparison pair."""

    arm_ids = _unique(pair)
    return "::".join(arm_ids) if len(arm_ids) == 2 else ""


def _direct_pair_coverage_bundles_v4(
    record: Mapping[str, Any],
    document: Mapping[str, Any],
    contract: Mapping[str, Any],
    assertions: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build high-grade same-study direct-pair bundles from one source version."""

    comparison_contract = _comparison_contract_v4(contract)
    if not comparison_contract:
        return []
    required_slots = set(
        _unique((contract.get("evidence_contract") or {}).get("required_slots"))
    )
    expected_relation_type = _text(comparison_contract.get("comparison_kind"))
    expected_contract_id = _text(comparison_contract.get("comparison_contract_id"))
    bundles: list[dict[str, Any]] = []
    for assertion in assertions:
        frame = assertion.get("comparison_frame_v4")
        if not isinstance(frame, Mapping):
            continue
        direct_pair = _unique(frame.get("matched_direct_pair") or [])
        direct_pair_id = _comparison_pair_id_v4(direct_pair)
        arm_ids = _unique(
            item.get("arm_id")
            for item in frame.get("arm_mentions") or []
            if isinstance(item, Mapping)
        )
        shared_metric = frame.get("shared_metric")
        protocol = frame.get("protocol")
        support_slots = {
            _text(item.get("slot_id"))
            for item in assertion.get("slot_support") or []
            if isinstance(item, Mapping)
            and item.get("admission_status") == "DIRECT_SLOT_ADMITTED"
        }
        document_version_hash = _text(assertion.get("document_version_hash"))
        source_span_ids = _unique(assertion.get("source_span_ids"))
        direct = (
            _text(frame.get("admission_status")) == "DIRECT_PAIR_ADMITTED"
            and _text(frame.get("comparison_contract_id")) == expected_contract_id
            and _text(frame.get("comparison_relation_type")) == expected_relation_type
            and direct_pair_id in {
                _comparison_pair_id_v4(pair)
                for pair in comparison_contract.get("target_comparison_pairs") or []
            }
            and len(arm_ids) >= 2
            and bool(_text(frame.get("comparison_unit_signature")))
            and isinstance(shared_metric, Mapping)
            and bool(_text(shared_metric.get("signature")))
            and isinstance(protocol, Mapping)
            and bool(_text(protocol.get("signature")))
            and bool(source_span_ids)
            and document_version_hash == _text(document.get("document_version_hash"))
            and required_slots.issubset(support_slots)
        )
        if not direct:
            continue
        material = "|".join([
            expected_contract_id,
            _text(assertion.get("assertion_id")),
            _text(assertion.get("paper_id") or _paper_id(dict(record))),
            document_version_hash,
            _text(frame.get("comparison_unit_signature")),
            _text(shared_metric.get("signature")),
            _text(protocol.get("signature")),
        ])
        bundles.append({
            "schema_version": "direct_pair_comparison_v4",
            "coverage_bundle_id": "cmpbundle_" + sha256(
                material.encode("utf-8")
            ).hexdigest()[:24],
            "bundle_id": "direct_pair_comparison_v4",
            "comparison_contract_id": expected_contract_id,
            "comparison_relation_type": expected_relation_type,
            "direct_pair": direct_pair,
            "direct_pair_id": direct_pair_id,
            "arm_ids": arm_ids,
            "slot_ids": sorted(required_slots),
            "admission_status": "DIRECT_SLOT_ADMITTED",
            "participating_assertion_ids": [_text(assertion.get("assertion_id"))],
            "participating_source_span_ids": source_span_ids,
            "source_span_ids": source_span_ids,
            "paper_id": _text(assertion.get("paper_id") or _paper_id(dict(record))),
            "document_version_hash": document_version_hash,
            "document_version_ids": [_text(document.get("document_version_id"))],
            "comparison_signature": _text(frame.get("comparison_unit_signature")),
            "comparison_unit_signature": _text(frame.get("comparison_unit_signature")),
            "shared_metric_signature": _text(shared_metric.get("signature")),
            "protocol_signature": _text(protocol.get("signature")),
            "coherence_mode": "same_study_direct_pair",
            "adjudication": "DIRECT_COMPARISON_ADMITTED",
            "admission_reason": (
                "A current full-text source span explicitly compares a declared arm pair "
                "with a source-bound unit, metric, and protocol."
            ),
        })
    return bundles


def build_comparison_synthesis_artifact_v4(
    contract: Mapping[str, Any],
    assertions: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Audit whether separately collected arm evidence may form a comparison.

    Arm coverage is intentionally permissive. A cross-source conclusion is
    created only when each requested pair has source-bound observations for
    the same declared metric, identical reported units, and every declared
    comparability axis with matching source-grounded values. This function
    never invents a conversion, a common protocol, or a directional result.
    """
    comparison = _comparison_contract_v4(contract)
    if not comparison:
        return {}
    contract_id = _text(comparison.get("comparison_contract_id"))
    usable = [
        dict(assertion) for assertion in assertions
        if isinstance(assertion, Mapping)
        and _text(assertion.get("validator_verdict")) == "VERIFIED_SOURCE_BOUND"
        and _text(assertion.get("research_question_contract_id")) == _text(contract.get("contract_id"))
    ]
    by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for assertion in usable:
        evidence = assertion.get("comparison_evidence_v4")
        evidence = evidence if isinstance(evidence, Mapping) else {}
        for arm in evidence.get("arm_matches", []):
            if not isinstance(arm, Mapping) or not _text(arm.get("arm_id")):
                continue
            by_arm[_text(arm.get("arm_id"))].append(assertion)
    arm_coverage = {
        arm_id: sorted({_text(item.get("assertion_id")) for item in items if _text(item.get("assertion_id"))})
        for arm_id, items in sorted(by_arm.items())
    }
    syntheses: list[dict[str, Any]] = []
    for pair in comparison.get("target_comparison_pairs", []):
        arm_ids = _unique(pair)
        if len(arm_ids) != 2:
            continue
        left, right = arm_ids
        pair_arms = frozenset((left, right))
        direct_candidates = []
        for assertion in usable:
            evidence = assertion.get("comparison_evidence_v4")
            evidence = evidence if isinstance(evidence, Mapping) else {}
            direct = evidence.get("direct_pair_comparison")
            direct = direct if isinstance(direct, Mapping) else {}
            direct_pair_arms = frozenset({
                _text(direct.get("left_arm_id")),
                _text(direct.get("right_arm_id")),
            } - {""})
            if direct_pair_arms != pair_arms:
                continue
            if not all(_text(direct.get(field)) for field in (
                "relation", "metric_id", "left_value_text", "right_value_text",
                "unit", "common_task", "protocol",
            )):
                continue
            direct_candidates.append((assertion, direct))
        if direct_candidates:
            assertion, direct = direct_candidates[0]
            syntheses.append({
                "schema_version": "comparison_synthesis_artifact_v4",
                "comparison_contract_id": contract_id,
                "target_pair": [left, right],
                "comparability_status": "PASS",
                "conclusion_status": "READY",
                "evidence_grade": "DIRECT_PAIR_COMPARISON",
                "participating_assertion_ids": [_text(assertion.get("assertion_id"))],
                "metric_mapping": {
                    "metric_id": _text(direct.get("metric_id")),
                    "left_value_text": _text(direct.get("left_value_text")),
                    "right_value_text": _text(direct.get("right_value_text")),
                },
                "unit_conversion": {
                    "status": "SAME_STUDY_REPORTED_UNIT",
                    "unit": _text(direct.get("unit")),
                },
                "condition_compatibility": "PASS_SAME_STUDY_COMMON_TASK",
                "population_compatibility": "PASS_SAME_STUDY",
                "protocol_compatibility": "PASS_SAME_STUDY_REPORTED_PROTOCOL",
                "uncertainty_handling": "SOURCE_VALUES_RETAINED_NO_UNSUPPORTED_AGGREGATION",
                "reason_codes": [],
            })
            continue
        left_candidates = by_arm.get(left, [])
        right_candidates = by_arm.get(right, [])
        diagnostics: list[str] = []
        if not left_candidates:
            diagnostics.append(f"ARM_EVIDENCE_MISSING:{left}")
        if not right_candidates:
            diagnostics.append(f"ARM_EVIDENCE_MISSING:{right}")
        selected: tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]] | None = None
        if left_candidates and right_candidates:
            for left_assertion in left_candidates:
                left_evidence = left_assertion.get("comparison_evidence_v4") or {}
                for right_assertion in right_candidates:
                    right_evidence = right_assertion.get("comparison_evidence_v4") or {}
                    for left_metric in left_evidence.get("metric_observations", []):
                        if not isinstance(left_metric, Mapping):
                            continue
                        for right_metric in right_evidence.get("metric_observations", []):
                            if not isinstance(right_metric, Mapping):
                                continue
                            if (
                                _text(left_metric.get("metric_id"))
                                != _text(right_metric.get("metric_id"))
                                or not _text(left_metric.get("value_text"))
                                or not _text(right_metric.get("value_text"))
                                or not _text(left_metric.get("unit"))
                                or _normal(left_metric.get("unit"))
                                != _normal(right_metric.get("unit"))
                            ):
                                continue
                            left_axes = {
                                _text(item.get("axis_id")): _normal(item.get("value_text"))
                                for item in left_evidence.get("comparability_observations", [])
                                if isinstance(item, Mapping) and _text(item.get("axis_id")) and _text(item.get("value_text"))
                            }
                            right_axes = {
                                _text(item.get("axis_id")): _normal(item.get("value_text"))
                                for item in right_evidence.get("comparability_observations", [])
                                if isinstance(item, Mapping) and _text(item.get("axis_id")) and _text(item.get("value_text"))
                            }
                            axes = _unique(comparison.get("comparability_axes"))
                            if all(
                                left_axes.get(axis) and left_axes.get(axis) == right_axes.get(axis)
                                for axis in axes
                            ):
                                selected = (
                                    left_assertion, right_assertion,
                                    dict(left_metric), dict(right_metric),
                                )
                                break
                        if selected is not None:
                            break
                    if selected is not None:
                        break
                if selected is not None:
                    break
        if selected is None and not diagnostics:
            diagnostics.append("COMPARABILITY_AUDIT_INCOMPLETE_OR_INCOMPATIBLE")
        if selected is None:
            status = "PENDING" if any(code.startswith("ARM_EVIDENCE_MISSING") for code in diagnostics) else "FAIL"
            syntheses.append({
                "schema_version": "comparison_synthesis_artifact_v4",
                "comparison_contract_id": contract_id,
                "target_pair": [left, right],
                "comparability_status": status,
                "conclusion_status": "PENDING",
                "participating_assertion_ids": [],
                "reason_codes": diagnostics,
            })
            continue
        left_assertion, right_assertion, left_metric, right_metric = selected
        syntheses.append({
            "schema_version": "comparison_synthesis_artifact_v4",
            "comparison_contract_id": contract_id,
            "target_pair": [left, right],
            "comparability_status": "PASS",
            "conclusion_status": "READY",
            "evidence_grade": "CROSS_SOURCE_COMPARABILITY_GATED",
            "participating_assertion_ids": [
                _text(left_assertion.get("assertion_id")),
                _text(right_assertion.get("assertion_id")),
            ],
            "metric_mapping": {
                "metric_id": _text(left_metric.get("metric_id")),
                "left_value_text": _text(left_metric.get("value_text")),
                "right_value_text": _text(right_metric.get("value_text")),
            },
            "unit_conversion": {"status": "IDENTICAL_UNIT", "unit": _text(left_metric.get("unit"))},
            "condition_compatibility": "PASS",
            "population_compatibility": "PASS",
            "protocol_compatibility": "PASS",
            "uncertainty_handling": "SOURCE_VALUES_RETAINED_NO_UNSUPPORTED_AGGREGATION",
            "reason_codes": [],
        })
    return {
        "schema_version": "comparison_evidence_set_v4",
        "comparison_contract_id": contract_id,
        "arm_coverage": arm_coverage,
        "syntheses": syntheses,
        "direct_pair_evidence_preferred": True,
    }


def _record_contract_links(record: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Return only explicit SH/contract links declared by the import path.

    A source record must never be broadcast to every active research question.
    Such broadcasting makes an unassigned document silently look scope-aligned
    and is precisely the kind of fallback that the v2 evidence architecture
    forbids.  A document may be deliberately multi-bound, but every binding
    must be visible in its record or import context.
    """
    record = record if isinstance(record, dict) else {}
    context = record.get("import_context") if isinstance(record.get("import_context"), dict) else {}
    sub_hypothesis_ids = {
        _text(value)
        for value in (
            record.get("sub_hypothesis_id"),
            context.get("sub_hypothesis_id"),
        )
        if _text(value)
    }
    contract_ids = {
        _text(value)
        for value in (
            record.get("research_question_contract_id"),
            context.get("research_question_contract_id"),
        )
        if _text(value)
    }
    for binding in record.get("subhypothesis_bindings", []):
        if not isinstance(binding, dict):
            continue
        sub_hypothesis_id = _text(binding.get("sub_hypothesis_id"))
        contract_id = _text(binding.get("research_question_contract_id"))
        if sub_hypothesis_id:
            sub_hypothesis_ids.add(sub_hypothesis_id)
        if contract_id:
            contract_ids.add(contract_id)
    return sub_hypothesis_ids, contract_ids


def _cached_document_proposition_extraction(
    record: Mapping[str, Any],
    document: Mapping[str, Any],
    policy: ScienceExecutionPolicy,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    extraction = record.get("document_proposition_artifact")
    if not isinstance(extraction, Mapping) or any((
        _text(extraction.get("schema_version")) != PROPOSITION_EXTRACTION_SCHEMA_VERSION,
        _text(extraction.get("status")) != "PROPOSITION_READY",
        _text(extraction.get("document_version_hash")) != _text(document.get("document_version_hash")),
        _text(extraction.get("prompt_revision")) != PROPOSITION_PROMPT_REVISION,
        _text(extraction.get("evidence_unit_registry_revision"))
        != EVIDENCE_UNIT_REGISTRY_REVISION,
        _text(extraction.get("composition_prompt_revision"))
        != PROPOSITION_COMPOSITION_PROMPT_REVISION,
        _text(extraction.get("model_id")) != proposition_model_id(),
        _text(extraction.get("policy_schema_version")) != policy.schema_version,
        extraction.get("effective_use_llm") is not policy.use_llm,
        dict(extraction.get("effective_policy") or {}) != policy.to_dict(),
    )):
        return None
    sections = [
        dict(item) for item in record.get("document_sections_v5", [])
        if isinstance(item, Mapping)
    ]
    spans = [
        dict(item) for item in record.get("source_spans_v6", [])
        if isinstance(item, Mapping)
    ]
    document_hash = _text(document.get("document_version_hash"))
    if not sections or not spans:
        return None
    if any(_text(item.get("document_version_hash")) != document_hash for item in sections):
        return None
    if any(
        _text(item.get("schema_version")) != SOURCE_SPAN_SCHEMA_VERSION
        or _text(item.get("document_version_hash")) != document_hash
        for item in spans
    ):
        return None
    coverage_by_span_id = {
        _text(item.get("source_span_id")): item
        for item in extraction.get("coverage_manifest", [])
        if isinstance(item, Mapping) and _text(item.get("source_span_id"))
    }
    covered_span_ids = set(coverage_by_span_id)
    expected_span_ids = {
        _text(item.get("source_span_id"))
        for item in spans
        if _text(item.get("source_span_id"))
    }
    review_span_ids = {
        _text(item)
        for item in extraction.get("review_source_span_ids", [])
        if _text(item)
    } or expected_span_ids
    if not review_span_ids.issubset(expected_span_ids) or covered_span_ids != review_span_ids:
        return None
    if any(
        _text(coverage_by_span_id[span_id].get("source_span_cache_key"))
        != _source_span_cache_key(
            span,
            document_version_hash=document_hash,
        )
            for span_id, span in {
            _text(item.get("source_span_id")): item
            for item in spans
        }.items()
        if span_id in review_span_ids
    ):
        return None
    section_set = {
        "schema_version": "document_section_set_v6",
        "document": dict(document),
        "sections": sections,
        "status": "STRUCTURED",
        "reason_codes": [],
    }
    span_set = {
        "schema_version": "evidence_span_set_v6",
        "document": dict(document),
        "sections": sections,
        "source_spans": spans,
        "review_source_span_ids": sorted(review_span_ids),
        "review_selection": dict(extraction.get("review_selection") or {})
        if isinstance(extraction.get("review_selection"), Mapping)
        else {},
        "coverage_manifest": list(extraction.get("coverage_manifest") or []),
        "status": "STRUCTURED",
        "reason_codes": [],
    }
    return section_set, span_set, dict(extraction)


def extract_record_evidence_assertions(
    record: dict[str, Any],
    question_contracts: Iterable[dict[str, Any]],
    *,
    policy: ScienceExecutionPolicy | None = None,
    use_llm: bool | None = None,
    contract_ids: set[str] | None = None,
    llm_call: Any | None = None,
    project_id: str = "",
) -> dict[str, Any]:
    source = record if isinstance(record, dict) else {}
    effective_policy = policy or resolve_science_execution_policy({}, use_llm=use_llm)
    contracts = [
        validate_research_question_contract(item)
        for item in question_contracts
        if isinstance(item, dict)
        and item.get("schema_version") == RESEARCH_QUESTION_CONTRACT_VERSION
    ]
    contracts_by_id = {
        _text(contract.get("contract_id")): contract
        for contract in contracts if _text(contract.get("contract_id"))
    }
    requested = (
        {_text(item) for item in contract_ids if _text(item)}
        if contract_ids is not None else None
    )
    linked_contract_bindings: dict[tuple[str, str], dict[str, Any]] = {}
    for binding in source.get("subhypothesis_bindings", []):
        if not isinstance(binding, dict):
            continue
        contract_id = _text(binding.get("research_question_contract_id"))
        contract = contracts_by_id.get(contract_id)
        if not contract or (requested is not None and contract_id not in requested):
            continue
        if _version_matches_contract(binding, contract):
            task_id = _text(binding.get("research_question_task_id"))
            if task_id:
                linked_contract_bindings.setdefault(
                    (contract_id, task_id), dict(binding)
                )
    document = build_document_record_v4(source)
    cached = _cached_document_proposition_extraction(
        source,
        document,
        effective_policy,
    )
    cache_status = "HIT" if cached is not None else "MISS"
    prior_alignment_batch_artifacts: list[dict[str, Any]] = []
    alignment_batch_checkpoint = None
    if cached is not None:
        section_set, span_set, extraction = cached
    else:
        section_set = structure_document_sections(source, effective_policy, llm_call=llm_call)
        span_set = build_evidence_spans(section_set)
        sh_review_context = (
            source.get("sh_review_context")
            if isinstance(source.get("sh_review_context"), Mapping)
            else {}
        )
        if sh_review_context.get("enabled") is True:
            review_selection = select_review_evidence_units(
                span_set.get("source_spans") or [],
                sh_review_context.get("contract")
                if isinstance(sh_review_context.get("contract"), Mapping)
                else {},
                matched_branches=sh_review_context.get("matched_branches") or [],
                max_spans_per_paper=int(
                    sh_review_context.get("max_spans_per_paper") or 12
                ),
            )
            span_set["review_source_span_ids"] = list(
                review_selection.get("selected_source_span_ids") or []
            )
            span_set["review_selection"] = review_selection
        prior_batch_artifacts: list[dict[str, Any]] = []
        batch_checkpoint = None
        if project_id:
            try:
                from ._evidence_preparation_store import (
                    load_alignment_batch_artifacts,
                    load_atomic_proposition_batches,
                    persist_alignment_batch_artifact,
                    persist_atomic_proposition_batch,
                )
            except ImportError:
                from _evidence_preparation_store import (
                    load_alignment_batch_artifacts,
                    load_atomic_proposition_batches,
                    persist_alignment_batch_artifact,
                    persist_atomic_proposition_batch,
                )
            prior_batch_artifacts = load_atomic_proposition_batches(
                project_id=project_id,
                paper_id=_paper_id(source),
                document=dict(span_set.get("document") or {}),
            )
            document_version_id = _text(
                (span_set.get("document") or {}).get("document_version_id")
            )

            def batch_checkpoint(batch_artifact: dict[str, Any]) -> None:
                persist_atomic_proposition_batch(
                    project_id=project_id,
                    paper_id=_paper_id(source),
                    document_version_id=document_version_id,
                    batch_artifact=batch_artifact,
                )

            prior_alignment_batch_artifacts = load_alignment_batch_artifacts(
                project_id=project_id,
                paper_id=_paper_id(source),
                document=dict(span_set.get("document") or {}),
            )

            def alignment_batch_checkpoint(
                batch_artifact: dict[str, Any],
            ) -> None:
                persist_alignment_batch_artifact(
                    project_id=project_id,
                    paper_id=_paper_id(source),
                    document_version_id=document_version_id,
                    batch_artifact=batch_artifact,
                )

        extraction = extract_document_propositions(
            span_set,
            effective_policy,
            llm_call=llm_call,
            prior_artifact=(
                source.get("document_proposition_artifact")
                if isinstance(source.get("document_proposition_artifact"), Mapping)
                else None
            ),
            prior_batch_artifacts=prior_batch_artifacts,
            batch_checkpoint=batch_checkpoint,
        )
    assertions: list[dict[str, Any]] = []
    slot_supports: list[dict[str, Any]] = []
    alignments: dict[str, dict[str, Any]] = {}
    admissions: dict[str, dict[str, Any]] = {}
    prior_alignments = (
        source.get("contract_alignment_artifacts")
        if isinstance(source.get("contract_alignment_artifacts"), Mapping)
        else {}
    )

    def _prior_task_alignment(contract_id: str, task_id: str) -> Mapping[str, Any] | None:
        raw_prior = prior_alignments.get(contract_id)
        if not isinstance(raw_prior, Mapping):
            return None
        task_alignments = raw_prior.get("task_alignments")
        if isinstance(task_alignments, Mapping) and isinstance(task_alignments.get(task_id), Mapping):
            return task_alignments[task_id]
        return None

    def _bundle_alignment(
        contract_id: str,
        members: list[tuple[str, dict[str, Any]]],
    ) -> dict[str, Any] | None:
        """Run one matrix for all task-local slots of one SH contract.

        The returned task projections are rebuilt below, so the persisted
        evidence remains contract/task scoped even though the model sees one
        compact paper-level matrix.
        """

        if len(members) < 2:
            return None
        prior_members = [
            _prior_task_alignment(contract_id, task_id)
            for task_id, _ in members
        ]
        if all(
            isinstance(item, Mapping)
            and isinstance(item.get("bundle_review"), Mapping)
            and item["bundle_review"].get("shared_matrix") is True
            for item in prior_members
        ):
            first_prior = dict(prior_members[0])
            first_prior["alignment_decisions"] = [
                dict(item)
                for prior in prior_members
                for item in prior.get("alignment_decisions", [])
                if isinstance(item, Mapping)
            ]
            first_prior["slot_supports"] = [
                dict(item)
                for prior in prior_members
                for item in prior.get("slot_supports", [])
                if isinstance(item, Mapping)
            ]
            first_prior["assertions"] = [
                dict(item)
                for prior in prior_members
                for item in prior.get("assertions", [])
                if isinstance(item, Mapping)
            ]
            return first_prior
        if any(item is not None for item in prior_members):
            return None
        _first_task_id, first_contract = members[0]
        all_slots: list[str] = []
        merged_definitions: dict[str, Any] = {}
        for _task_id, member_contract in members:
            for slot_id in member_contract.get("target_slot_ids") or []:
                slot = _text(slot_id)
                if slot and slot not in all_slots:
                    all_slots.append(slot)
            definitions = member_contract.get("slot_definitions")
            if isinstance(definitions, Mapping):
                for slot_id, definition in definitions.items():
                    if slot_id not in merged_definitions:
                        merged_definitions[slot_id] = definition
        if not all_slots:
            return None
        bundle_contract = dict(first_contract)
        bundle_contract["research_question_task_id"] = f"paper_bundle::{contract_id}"
        bundle_contract["target_slot_ids"] = list(all_slots)
        bundle_contract["slot_definitions"] = merged_definitions
        evidence_contract = (
            dict(bundle_contract.get("evidence_contract") or {})
            if isinstance(bundle_contract.get("evidence_contract"), Mapping)
            else {}
        )
        evidence_contract["required_slots"] = list(all_slots)
        bundle_contract["evidence_contract"] = evidence_contract
        return align_propositions_to_contract(
            extraction,
            bundle_contract,
            effective_policy,
            task_scope={
                "research_question_task_id": f"paper_bundle::{contract_id}",
                "target_slot_ids": list(all_slots),
            },
            llm_call=llm_call,
            prior_artifact=None,
            prior_batch_artifacts=prior_alignment_batch_artifacts,
            batch_checkpoint=alignment_batch_checkpoint,
        )

    def _project_bundle_alignment(
        bundle: Mapping[str, Any],
        contract: Mapping[str, Any],
        task_id: str,
    ) -> dict[str, Any]:
        slots = {
            _text(item)
            for item in contract.get("target_slot_ids") or []
            if _text(item)
        }
        projected = dict(bundle)
        projected["research_question_task_id"] = task_id
        projected["target_slot_ids"] = sorted(slots)
        revision, declaration_hash = _contract_version_fields(contract)
        projected["artifact_id"] = "alignment_" + uuid5(
            NAMESPACE_URL,
            "|".join((
                _text(extraction.get("document_version_id") or (extraction.get("document") or {}).get("document_version_id")),
                _text(extraction.get("artifact_id") or extraction.get("extraction_run_id")),
                _text(contract.get("contract_id")),
                revision,
                declaration_hash,
                task_id,
                _text(contract.get("alignment_scope_revision") or revision),
            )),
        ).hex[:24]
        projected["alignment_scope_id"] = _text(contract.get("alignment_scope_id")) or _text(contract.get("contract_id"))
        projected["alignment_scope_revision"] = _text(contract.get("alignment_scope_revision")) or revision
        projected["alignment_decisions"] = [
            dict(item)
            for item in bundle.get("alignment_decisions", [])
            if isinstance(item, Mapping) and _text(item.get("slot_id")) in slots
        ]
        support_id_map: dict[str, str] = {}
        assertion_id_map: dict[str, str] = {}
        projected_supports: list[dict[str, Any]] = []
        for raw_support in bundle.get("slot_supports", []):
            if not isinstance(raw_support, Mapping) or _text(raw_support.get("slot_id")) not in slots:
                continue
            support = dict(raw_support)
            old_support_id = _text(support.get("slot_support_id"))
            old_assertion_id = _text(support.get("assertion_id"))
            new_assertion_id = assertion_id_map.setdefault(
                old_assertion_id,
                "assert_bundle_" + sha256(f"{old_assertion_id}|{task_id}".encode("utf-8")).hexdigest()[:24],
            )
            new_support_id = "support_bundle_" + sha256(
                f"{old_support_id}|{task_id}".encode("utf-8")
            ).hexdigest()[:24]
            support_id_map[old_support_id] = new_support_id
            support["slot_support_id"] = new_support_id
            support["assertion_id"] = new_assertion_id
            support["research_question_task_id"] = task_id
            support["research_question_contract_id"] = _text(contract.get("contract_id"))
            support["research_question_contract_revision"] = _contract_version_fields(contract)[0]
            support["research_question_contract_hash"] = _contract_version_fields(contract)[1]
            projected_supports.append(support)
        projected["slot_supports"] = projected_supports
        projected_assertions: list[dict[str, Any]] = []
        for raw_assertion in bundle.get("assertions", []):
            if not isinstance(raw_assertion, Mapping):
                continue
            raw_supports = [
                dict(item)
                for item in raw_assertion.get("slot_support", [])
                if isinstance(item, Mapping) and _text(item.get("slot_id")) in slots
            ]
            if not raw_supports:
                continue
            assertion = dict(raw_assertion)
            old_assertion_id = _text(assertion.get("assertion_id"))
            new_assertion_id = assertion_id_map.setdefault(
                old_assertion_id,
                "assert_bundle_" + sha256(f"{old_assertion_id}|{task_id}".encode("utf-8")).hexdigest()[:24],
            )
            assertion["assertion_id"] = new_assertion_id
            assertion["research_question_task_id"] = task_id
            assertion["research_question_contract_id"] = _text(contract.get("contract_id"))
            assertion["research_question_contract_revision"] = _contract_version_fields(contract)[0]
            assertion["research_question_contract_hash"] = _contract_version_fields(contract)[1]
            assertion["slot_support"] = [
                {
                    **support,
                    "slot_support_id": support_id_map.get(
                        _text(support.get("slot_support_id")),
                        _text(support.get("slot_support_id")),
                    ),
                    "assertion_id": new_assertion_id,
                }
                for support in raw_supports
            ]
            assertion["slot_coverage"] = {
                slot: any(_text(item.get("slot_id")) == slot for item in assertion["slot_support"])
                for slot in slots
            }
            projected_assertions.append(assertion)
        projected["assertions"] = projected_assertions
        projected["slot_status"] = {
            slot: dict(value)
            for slot, value in (bundle.get("slot_status") or {}).items()
            if slot in slots and isinstance(value, Mapping)
        }
        projected_pending = [
            item
            for item in projected["alignment_decisions"]
            if _text(item.get("terminal_status")) != "TERMINAL"
        ]
        projected["status"] = "COMPLETE" if not projected_pending else "SLOT_ALIGNMENT_PENDING"
        projected["pending_pair_count"] = len(projected_pending)
        projected["terminal_pair_count"] = len(projected["alignment_decisions"]) - len(projected_pending)
        projected["reason_codes"] = (
            [] if not projected_pending else ["TASK_LOCAL_ALIGNMENT_PENDING"]
        )
        projected["bundle_review"] = {
            "schema_version": "paper_sh_alignment_bundle_v1",
            "contract_id": _text(contract.get("contract_id")),
            "task_id": task_id,
            "source_task_id": _text(bundle.get("research_question_task_id")),
            "slot_ids": sorted(slots),
            "shared_matrix": True,
        }
        projected["alignment_method"] = "llm_paper_sh_bundle_v1"
        return projected

    alignment_bundle_cache: dict[str, dict[str, Any] | None] = {}
    linked_by_contract: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for linked_contract_id, linked_task_id in linked_contract_bindings:
        linked_by_contract[linked_contract_id].append((
            linked_task_id,
            bind_research_question_task_scope(
                contracts_by_id[linked_contract_id],
                linked_contract_bindings[(linked_contract_id, linked_task_id)],
            ),
        ))
    for contract_id, task_id in sorted(linked_contract_bindings):
        contract = bind_research_question_task_scope(
            contracts_by_id[contract_id],
            linked_contract_bindings[(contract_id, task_id)],
        )
        bundle = alignment_bundle_cache.get(contract_id)
        if contract_id not in alignment_bundle_cache:
            bundle = _bundle_alignment(contract_id, linked_by_contract.get(contract_id, []))
            alignment_bundle_cache[contract_id] = bundle
        if isinstance(bundle, Mapping):
            alignment = _project_bundle_alignment(bundle, contract, task_id)
        else:
            raw_prior_alignment = _prior_task_alignment(contract_id, task_id)
            alignment = align_propositions_to_contract(
                extraction,
                contract,
                effective_policy,
                task_scope={
                    "research_question_task_id": _text(contract.get("research_question_task_id")),
                    "target_slot_ids": list(contract.get("target_slot_ids") or []),
                },
                llm_call=llm_call,
                prior_artifact=(
                    raw_prior_alignment
                    if isinstance(raw_prior_alignment, Mapping)
                    else None
                ),
                prior_batch_artifacts=prior_alignment_batch_artifacts,
                batch_checkpoint=alignment_batch_checkpoint,
            )
        contract_assertions = list(alignment.get("assertions") or [])
        contract_supports = list(alignment.get("slot_supports") or [])
        alignment_index = alignments.setdefault(contract_id, {
            "schema_version": "contract_task_alignment_index_v1",
            "research_question_contract_id": contract_id,
            "task_alignments": {},
            "whole_contract_alignment": {"status": "NOT_RUN"},
        })
        alignment_index["task_alignments"][task_id] = alignment
        admission = build_evidence_admission(
            source,
            contract_id=contract_id,
            contract_revision=_contract_version_fields(contract)[0],
            contract_hash=_contract_version_fields(contract)[1],
            extraction_status=_text(extraction.get("status")),
            alignment_status=_text(alignment.get("status")),
            assertions=contract_assertions,
            research_question_task_id=_text(
                contract.get("research_question_task_id")
            ),
        )
        admission_index = admissions.setdefault(contract_id, {
            "schema_version": "contract_task_admission_index_v1",
            "research_question_contract_id": contract_id,
            "task_admissions": {},
        })
        admission_index["task_admissions"][task_id] = admission
        support_admission_by_id = {
            _text(item.get("slot_support_id")): _text(item.get("admission_status"))
            for item in admission.get("support_admissions", [])
            if isinstance(item, Mapping) and _text(item.get("slot_support_id"))
        }
        for support in contract_supports:
            if isinstance(support, dict):
                support["admission_status"] = support_admission_by_id.get(
                    _text(support.get("slot_support_id")), "CONTEXT_RETAINED"
                )
                support["counts_toward_slot_gate"] = (
                    support["admission_status"] == "DIRECT_SLOT_ADMITTED"
                )
        admitted_support_ids = {
            _text(item)
            for item in admission.get("admitted_slot_support_ids", [])
            if _text(item)
        }
        arm_coverage_assertion_ids = {
            _text(item)
            for item in admission.get("arm_evidence_assertion_ids", [])
            if _text(item)
        }
        for assertion in contract_assertions:
            admitted_slots = sorted({
                _text(support.get("slot_id"))
                for support in assertion.get("slot_support", [])
                if isinstance(support, Mapping)
                and _text(support.get("slot_support_id")) in admitted_support_ids
                and _text(support.get("slot_id"))
            })
            for support in assertion.get("slot_support", []):
                if isinstance(support, dict):
                    support["admission_status"] = support_admission_by_id.get(
                        _text(support.get("slot_support_id")), "CONTEXT_RETAINED"
                    )
                    support["counts_toward_slot_gate"] = (
                        support["admission_status"] == "DIRECT_SLOT_ADMITTED"
                    )
            assertion["admitted_slot_ids_v4"] = admitted_slots
            assertion["admission_status"] = (
                "DIRECT_SLOT_ADMITTED" if admitted_slots else "CONTEXT_RETAINED"
            )
            assertion["counts_toward_arm_coverage"] = (
                _text(assertion.get("assertion_id"))
                in arm_coverage_assertion_ids
            )
            # A paper-level assertion never proves a two-arm conclusion.
            # That permission belongs exclusively to the V4 synthesis artifact.
            assertion["counts_toward_comparison_conclusion"] = False
        assertions.extend(contract_assertions)
        slot_supports.extend(contract_supports)
    return {
        "schema_version": "record_evidence_assertion_extraction_v4",
        "paper_id": _paper_id(source),
        "document": dict(span_set.get("document") or {}),
        "document_sections": list(section_set.get("sections") or []),
        "source_spans": list(span_set.get("source_spans") or []),
        "coverage_manifest": list(extraction.get("coverage_manifest") or []),
        "document_proposition_artifact": dict(extraction),
        "document_proposition_cache_status": cache_status,
        "propositions": list(extraction.get("propositions") or []),
        "assertion_candidates": list(extraction.get("assertion_candidates") or []),
        "rejected_proposition_candidates": list(extraction.get("rejected_candidates") or []),
        "assertions": assertions,
        "slot_supports": slot_supports,
        "contract_alignment_artifacts": alignments,
        "gap_source_admissions_v4": admissions,
        "linked_sub_hypothesis_ids": sorted({
            _text(contracts_by_id[item].get("sub_hypothesis_id"))
            for item, _task_id in linked_contract_bindings
            if _text(contracts_by_id[item].get("sub_hypothesis_id"))
        }),
        "linked_research_question_contract_ids": sorted({
            contract_id for contract_id, _task_id in linked_contract_bindings
        }),
        "unlinked_to_research_question": bool(
            span_set.get("source_spans") and not linked_contract_bindings
        ),
        "extraction_status": _text(extraction.get("status")),
        "reason_codes": list(extraction.get("reason_codes") or []),
        "effective_policy": effective_policy.to_dict(),
        "review_source_span_ids": list(
            extraction.get("review_source_span_ids")
            or span_set.get("review_source_span_ids")
            or []
        ),
        "review_selection": dict(
            extraction.get("review_selection")
            or span_set.get("review_selection")
            or {}
        )
        if isinstance(
            extraction.get("review_selection") or span_set.get("review_selection"),
            Mapping,
        )
        else {},
    }


def build_evidence_links(
    assertions: Iterable[dict[str, Any]],
    question_contracts: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create candidate-independent assertion-to-contract evidence links.

    An assertion says what a source stated; an evidence link says which role
    that assertion has for a particular research question.  Keeping the role
    here prevents a source span from being globally labelled as "direct" or
    "partial causal" and then reused incorrectly by another gap type.
    """
    contracts_by_id = {
        _text(item.get("contract_id")): item
        for item in question_contracts
        if isinstance(item, dict) and _text(item.get("contract_id"))
    }
    links: list[dict[str, Any]] = []
    for assertion in assertions:
        if not isinstance(assertion, dict):
            continue
        contract_id = _text(assertion.get("research_question_contract_id"))
        contract = contracts_by_id.get(contract_id)
        if not contract or not _version_matches_contract(assertion, contract):
            continue
        assertion_id = _text(assertion.get("assertion_id"))
        paper_id = _text(assertion.get("paper_id"))
        document_hash = _text(assertion.get("document_version_hash"))
        span_ids = [
            _text(span_id)
            for span_id in assertion.get("source_span_ids", [])
            if _text(span_id)
        ]
        if not assertion_id or not paper_id or not document_hash or not span_ids:
            # Assertions are the reference-first provenance boundary.  Do not
            # recover a missing document hash through an embedded span: that
            # would silently reintroduce duplicate source state and hide a
            # malformed artifact from the evidence graph audit.
            continue
        kinds = {str(item) for item in assertion.get("assertion_kinds") or []}
        role = "SUPPORTS"
        if "AUTHOR_LIMITATION" in kinds or "AUTHOR_UNKNOWN" in kinds:
            role = "IDENTIFIES_LIMITATION"
        elif "SCOPE_CONDITION" in kinds:
            role = "QUALIFIES_SCOPE"
        elif "MEASUREMENT_DEFINITION" in kinds or "MEASUREMENT_VALIDATION" in kinds or "MEASUREMENT_ERROR" in kinds:
            role = "PROVIDES_MEASUREMENT"
        elif "METHOD_FAILURE" in kinds:
            role = "IDENTIFIES_CONFOUNDER"
        elif "FORMAL_ASSUMPTION" in kinds:
            role = "PROVIDES_FORMAL_ASSUMPTION"
        elif "DATASET_COVERAGE" in kinds or "DATASET_DESCRIPTION" in kinds:
            role = "PROVIDES_COVERAGE_EVIDENCE"
        elif "BENCHMARK_RESULT" in kinds:
            role = "PROVIDES_BENCHMARK_CONTEXT"
        elif "IMPLEMENTATION_CONSTRAINT" in kinds or "DEPLOYMENT_OUTCOME" in kinds:
            role = "PROVIDES_IMPLEMENTATION_CONSTRAINT"
        material = f"{assertion_id}|{contract_id}|{role}"
        links.append(
            {
                "schema_version": EVIDENCE_LINK_SCHEMA_VERSION,
                "evidence_link_id": "elink_" + sha256(material.encode("utf-8")).hexdigest()[:24],
                "assertion_id": assertion_id,
                "source_span_ids": span_ids,
                "paper_id": paper_id,
                "document_version_hash": document_hash,
                "research_question_contract_id": contract_id,
                "research_question_contract_revision": _text(
                    assertion.get("research_question_contract_revision")
                ),
                "research_question_contract_hash": _text(
                    assertion.get("research_question_contract_hash")
                ),
                "evidence_link_role": role,
                "slot_coverage": dict(assertion.get("slot_coverage") or {}),
                "scope_tuple": dict(assertion.get("scope_tuple") or {}),
                "primary_eligible": False,
                "reason": "Evidence-link role is question-relative; assertion semantics remain source-local.",
            }
        )
    return links


def _assertion_provenance_integrity_error(
    assertion: dict[str, Any],
) -> dict[str, Any] | None:
    """Describe a malformed reference-first assertion without repairing it.

    V2 assertions are the provenance boundary between a text span and a
    question-relative evidence link.  A graph must never recover omitted
    provenance from an embedded span or a document copy: that would both hide
    an artifact error and reintroduce duplicate source state.
    """
    if not isinstance(assertion, dict):
        return {
            "schema_version": "artifact_integrity_error_v2",
            "error_code": "ASSERTION_ARTIFACT_INVALID",
            "assertion_id": "",
            "paper_id": "",
            "research_question_contract_id": "",
            "missing_fields": ["assertion_object"],
            "excluded_from_evidence_graph": True,
        }
    missing_fields: list[str] = []
    if not _text(assertion.get("assertion_id")):
        missing_fields.append("assertion_id")
    if not _text(assertion.get("paper_id")):
        missing_fields.append("paper_id")
    if not _text(assertion.get("document_version_hash")):
        missing_fields.append("document_version_hash")
    if not _text(assertion.get("research_question_contract_revision")):
        missing_fields.append("research_question_contract_revision")
    if not _text(assertion.get("research_question_contract_hash")):
        missing_fields.append("research_question_contract_hash")
    span_ids = [
        _text(span_id)
        for span_id in assertion.get("source_span_ids", [])
        if _text(span_id)
    ]
    if not span_ids:
        missing_fields.append("source_span_ids")
    if not missing_fields:
        return None
    return {
        "schema_version": "artifact_integrity_error_v2",
        "error_code": "ASSERTION_PROVENANCE_INCOMPLETE",
        "assertion_id": _text(assertion.get("assertion_id")),
        "paper_id": _text(assertion.get("paper_id")),
        "research_question_contract_id": _text(
            assertion.get("research_question_contract_id")
        ),
        "missing_fields": missing_fields,
        "excluded_from_evidence_graph": True,
    }


def _relation_nodes(assertion: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose normalized relation endpoints as typed heterogeneous nodes."""
    normalization = assertion.get("normalization") if isinstance(assertion.get("normalization"), dict) else {}
    values = {
        "CONSTRUCT": _text(normalization.get("subject")),
        "RELATION_TARGET": _text(normalization.get("object")),
    }
    scope = assertion.get("scope_tuple") if isinstance(assertion.get("scope_tuple"), dict) else {}
    for axis, node_type in (
        ("condition_or_regime", "CONDITION_REGIME"),
        ("population_or_system", "POPULATION_SYSTEM"),
        ("intervention_or_exposure", "INTERVENTION_EXPOSURE"),
        ("measurement_definition", "MEASUREMENT_PROXY_INSTRUMENT"),
        ("method_or_design", "METHOD_DESIGN"),
        ("dataset_or_corpus", "DATASET_COVERAGE_DIMENSION"),
        ("spatial_scale", "SCALE_LEVEL"),
        ("temporal_scale", "SCALE_LEVEL"),
    ):
        if _text(scope.get(axis)):
            values[node_type] = _text(scope.get(axis))
    nodes: list[dict[str, Any]] = []
    for node_type, label in values.items():
        if not label:
            continue
        node_id = "entity_" + sha256(f"{node_type}|{label.casefold()}".encode("utf-8")).hexdigest()[:20]
        nodes.append({"entity_id": node_id, "node_type": node_type, "label": label})
    return nodes


def build_heterogeneous_evidence_graph(
    project: dict[str, Any],
    *,
    policy: ScienceExecutionPolicy | None = None,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    """Build a V4 graph from one LLM-primary extraction policy."""
    project = project if isinstance(project, dict) else {}
    contracts = [
        item.get("research_question_contract")
        for item in project.get("sub_hypotheses", [])
        if isinstance(item, dict) and isinstance(item.get("research_question_contract"), dict)
    ]
    valid_contracts = [validate_research_question_contract(item) for item in contracts]
    records = [item for item in project.get("papergraph", []) if isinstance(item, dict)]
    effective_policy = policy or resolve_science_execution_policy(project, use_llm=use_llm)
    spans: list[dict[str, Any]] = []
    assertions: list[dict[str, Any]] = []
    persisted_assertion_integrity_errors: list[dict[str, Any]] = []
    current_contract_ids = {
        _text(contract.get("contract_id"))
        for contract in valid_contracts
        if _text(contract.get("contract_id"))
    }
    admissions: dict[str, dict[str, Any]] = {}
    unlinked_records: list[dict[str, Any]] = []
    for record in records:
        # Persisted assertions are immutable artifacts, not an optional cache
        # that a fresh extraction may silently overwrite.  Audit malformed
        # assertions belonging to a current contract before deriving the
        # in-memory projection; a historical, explicitly different revision
        # remains outside this current graph.
        for persisted_assertion in record.get("evidence_assertions_v4", []):
            if not isinstance(persisted_assertion, dict):
                persisted_assertion_integrity_errors.append(
                    _assertion_provenance_integrity_error(persisted_assertion)
                    or {}
                )
                continue
            persisted_contract_id = _text(
                persisted_assertion.get("research_question_contract_id")
            )
            if persisted_contract_id and persisted_contract_id not in current_contract_ids:
                continue
            integrity_error = _assertion_provenance_integrity_error(
                persisted_assertion
            )
            if integrity_error is not None:
                persisted_assertion_integrity_errors.append(integrity_error)
        extracted_record = extract_record_evidence_assertions(
            record,
            valid_contracts,
            policy=effective_policy,
        )
        record_spans = list(extracted_record["source_spans"])
        per_record_assertions = list(extracted_record["assertions"])
        record_admissions = dict(extracted_record["gap_source_admissions_v4"])
        spans.extend(record_spans)
        assertions.extend(per_record_assertions)
        record["evidence_document_v4"] = dict(extracted_record.get("document") or {})
        record["document_sections_v5"] = list(extracted_record.get("document_sections") or [])
        record["source_spans_v6"] = record_spans
        record["scientific_propositions"] = list(
            extracted_record.get("propositions") or []
        )
        record["evidence_assertions_v4"] = per_record_assertions
        record["slot_supports_v4"] = list(extracted_record.get("slot_supports") or [])
        record["gap_source_admissions_v4"] = record_admissions
        record["evidence_projection_v4"] = {
            "schema_version": EVIDENCE_PROJECTION_SCHEMA_VERSION,
            "document_version_hash": _text((extracted_record.get("document") or {}).get("document_version_hash")),
            "research_question_contract_revisions": {
                _text(contract.get("contract_id")): _text(contract.get("contract_revision") or contract.get("declaration_hash"))
                for contract in valid_contracts
                if _text(contract.get("contract_id"))
            },
            "extraction_schema_versions": {
                "source_span": SOURCE_SPAN_SCHEMA_VERSION,
                "evidence_assertion": EVIDENCE_ASSERTION_SCHEMA_VERSION,
                "source_admission": GAP_SOURCE_ADMISSION_SCHEMA_VERSION,
            },
            "status": "CURRENT",
            "effective_policy": effective_policy.to_dict(),
        }
        # A direct, unkeyed admission field is unsafe once one document can be
        # evaluated against several research questions.  The only authority is
        # the v3 map keyed by research-question contract id.
        record.pop("gap_source_admission", None)
        for contract_id, admission in record_admissions.items():
            admissions[f"{_paper_id(record)}:{contract_id}"] = admission
        if extracted_record["unlinked_to_research_question"]:
            unlinked_records.append(
                {
                    "paper_id": _paper_id(record),
                    "reason": "DOCUMENT_HAS_SOURCE_SPANS_BUT_NO_EXPLICIT_RESEARCH_QUESTION_BINDING",
                    "source_span_count": len(record_spans),
                }
            )
    artifact_integrity_errors: list[dict[str, Any]] = [
        item for item in persisted_assertion_integrity_errors if isinstance(item, dict)
    ]
    graph_assertions: list[dict[str, Any]] = []
    for assertion in assertions:
        integrity_error = _assertion_provenance_integrity_error(assertion)
        if integrity_error is not None:
            artifact_integrity_errors.append(integrity_error)
            continue
        graph_assertions.append(assertion)
    assertions = graph_assertions

    # Comparison conclusions are project-level artifacts. Per-paper alignment
    # may retain either declared arm, while synthesis alone decides whether
    # two independently sourced measurements are comparable.
    comparison_synthesis_artifacts: list[dict[str, Any]] = []
    for contract in valid_contracts:
        if not _comparison_contract_v4(contract):
            continue
        branch_assertions = [
            item
            for item in assertions
            if _text(item.get("sub_hypothesis_id"))
            == _text(contract.get("sub_hypothesis_id"))
        ]
        comparison_synthesis_artifacts.append(
            build_comparison_synthesis_artifact_v4(contract, branch_assertions)
        )

    inferences: list[dict[str, Any]] = []
    for contract in valid_contracts:
        branch_assertions = [item for item in assertions if _text(item.get("sub_hypothesis_id")) == _text(contract.get("sub_hypothesis_id"))]
        inferences.extend(
            derive_inferences(
                branch_assertions,
                contract,
                source_spans_by_id={
                    _text(span.get("source_span_id") or span.get("source_unit_id")): span
                    for span in spans
                    if isinstance(span, dict)
                    and _text(span.get("source_span_id") or span.get("source_unit_id"))
                },
            )
        )
    evidence_links = build_evidence_links(assertions, valid_contracts)
    entities: dict[str, dict[str, Any]] = {}
    relations: list[dict[str, Any]] = []
    for assertion in assertions:
        normalization = assertion.get("normalization") if isinstance(assertion.get("normalization"), dict) else {}
        subject = _text(assertion.get("subject") or normalization.get("subject"))
        predicate = _text(assertion.get("predicate") or normalization.get("predicate"))
        obj = _text(assertion.get("object") or normalization.get("object"))
        for node in _relation_nodes(assertion):
            current = entities.setdefault(node["entity_id"], {**node, "roles": []})
            if node["node_type"] not in current["roles"]:
                current["roles"].append(node["node_type"])
        relations.append(
            {
                "relation_id": "rel_" + sha256(f"{assertion['assertion_id']}|{predicate}".encode("utf-8")).hexdigest()[:20],
                "assertion_id": assertion["assertion_id"],
                "relation_kind": predicate,
                "subject": subject,
                "object": obj,
                "textual_explicitness": "EXPLICIT",
                "epistemic_basis": assertion.get("epistemic_basis"),
                "scope_tuple": assertion.get("scope_tuple"),
                "source_assertion_id": assertion.get("assertion_id"),
                "document_version_hash": assertion.get("document_version_hash"),
                "primary_eligible": False,
            }
        )
    return {
        "schema_version": HETEROGENEOUS_EVIDENCE_GRAPH_SCHEMA_VERSION,
        "source_spans": spans,
        "assertions": assertions,
        "documents": [
            build_document_record(record)
            for record in records
        ],
        "evidence_links": evidence_links,
        "derived_inferences": inferences,
        "relations": relations,
        "entities": list(entities.values()),
        "source_admissions": admissions,
        "comparison_synthesis_artifacts_v4": comparison_synthesis_artifacts,
        "unlinked_source_records": unlinked_records,
        "artifact_integrity_errors_v2": artifact_integrity_errors,
        "summary": {
            "source_span_count": len(spans),
            "explicit_assertion_count": len(assertions),
            "derived_inference_count": len(inferences),
            "relation_count": len(relations),
            "evidence_link_count": len(evidence_links),
            "assertion_kind_counts": dict(Counter(kind for item in assertions for kind in item.get("assertion_kinds", []))),
            "epistemic_basis_counts": dict(Counter(_text(item.get("epistemic_basis")) for item in assertions)),
            "unlinked_source_record_count": len(unlinked_records),
            "artifact_integrity_error_count": len(artifact_integrity_errors),
            "comparison_arm_coverage_count": sum(
                len(item.get("arm_coverage") or [])
                for item in comparison_synthesis_artifacts
            ),
            "comparison_synthesis_ready_count": sum(
                1
                for item in comparison_synthesis_artifacts
                for synthesis in item.get("syntheses") or []
                if isinstance(synthesis, Mapping)
                and _text(synthesis.get("conclusion_status")) == "READY"
            ),
            "comparison_synthesis_pending_count": sum(
                1
                for item in comparison_synthesis_artifacts
                for synthesis in item.get("syntheses") or []
                if isinstance(synthesis, Mapping)
                and _text(synthesis.get("conclusion_status")) == "PENDING"
            ),
            "comparison_synthesis_failed_count": sum(
                1
                for item in comparison_synthesis_artifacts
                for synthesis in item.get("syntheses") or []
                if isinstance(synthesis, Mapping)
                and _text(synthesis.get("comparability_status")) == "FAIL"
            ),
        },
    }
