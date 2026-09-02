"""Versioned, provenance-first research evidence graph.

This module is the project-level home for V3 source-bound evidence
artefacts.  It deliberately does not infer a causal relation from a missing
edge.  A graph snapshot is an immutable, reproducible view of documents,
source spans, explicit assertions, their question-relative evidence links,
and diagnostic-only derived inferences.

The graph has three logical layers in one JSON-safe representation:

* canonical evidence: documents, source spans, assertions;
* semantic projection: normalized mentions, asserted relations and scope;
* research task lineage: contracts, candidates, packages and proposals.

Only the first two layers are materialized here.  Downstream artefacts bind to
``graph_snapshot_ref`` and are invalidated rather than silently repaired when
their input snapshot changes.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
import json
import time
from typing import Any

try:
    from ._evidence_assertions import (
        build_heterogeneous_evidence_graph,
        build_heterogeneous_evidence_graph_v4_from_tanxi_view,
        document_version_hash,
    )
    from ._research_question_contract import SCOPE_AXES, validate_research_question_contract
except ImportError:
    from _evidence_assertions import (
        build_heterogeneous_evidence_graph,
        build_heterogeneous_evidence_graph_v4_from_tanxi_view,
        document_version_hash,
    )
    from _research_question_contract import SCOPE_AXES, validate_research_question_contract


RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION = "research_evidence_graph_v4"
GRAPH_VIEW_SCHEMA_VERSION = "research_graph_view_v3"
GRAPH_QUALITY_SCHEMA_VERSION = "research_graph_quality_v3"
RESEARCH_TASK_GRAPH_SCHEMA_VERSION = "research_task_graph_v3"
COMPARABILITY_ASSESSMENT_SCHEMA_VERSION = "comparability_assessment_v3"
SOURCE_ASSERTION_PROJECTION_SCHEMA_VERSION = "source_assertion_projection_v3"
DETECTOR_ADMISSION_PROJECTION_POLICY_REVISION = "direct_slot_admission_projection_v1"
DETECTION_CONTEXT_SCHEMA_VERSION = "gap_detection_context_v3"
CONTRACT_SCOPED_PROJECTION_SCHEMA_VERSION = "contract_scoped_detection_projection_v3"
DETECTOR_RESULT_SCHEMA_VERSION = "gap_detector_result_v3"
DETECTION_CONTEXT_POLICY_REVISION = "source_bound_contract_scoped_v1"


_ACTIVE_VALIDATED_DETECTION_CONTEXT: ContextVar[
    tuple[int, str, str] | frozenset[tuple[int, str, str]] | None
] = (
    ContextVar("active_validated_detection_context", default=None)
)


@dataclass(frozen=True)
class DetectionContext:
    """Immutable detector input assembled from one V3 contract projection.

    The context is intentionally not a project view and not a global assertion
    projection.  A detector receives exactly one research-question contract,
    its provenance-directed graph closure, and source assertions admitted for
    that closure.  This makes cross-SH leakage and legacy artifact reuse
    explicit validation failures instead of post-hoc filtering concerns.
    """

    schema_version: str
    detector_context_fingerprint: str
    detector_policy_version: str
    project_id: str
    graph_snapshot_ref: dict[str, Any]
    research_question_contract: dict[str, Any]
    graph_view: dict[str, Any]
    contract_scoped_projection: dict[str, Any]
    assertions: list[dict[str, Any]]
    source_units_by_assertion: dict[str, list[dict[str, Any]]]
    relation_index: dict[str, list[dict[str, Any]]]
    entity_index: dict[str, list[dict[str, Any]]]
    scope_index: dict[str, list[dict[str, Any]]]
    comparability_index: dict[str, dict[str, Any]]
    slot_coverage_ledger: dict[str, dict[str, Any]]


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _current_contracts(project: dict[str, Any]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for subhypothesis in project.get("sub_hypotheses", []):
        if not isinstance(subhypothesis, dict):
            continue
        contract = subhypothesis.get("research_question_contract")
        if isinstance(contract, dict):
            contracts.append(validate_research_question_contract(contract))
    return sorted(contracts, key=lambda item: _text(item.get("contract_id")))


def _snapshot_inputs(project: dict[str, Any], contracts: list[dict[str, Any]]) -> dict[str, Any]:
    records = [item for item in project.get("papergraph", []) if isinstance(item, dict)]
    document_refs = []
    for record in records:
        paper_id = _text(record.get("paper_id") or record.get("id") or record.get("doi") or record.get("title"))
        document_refs.append({
            "paper_id": paper_id,
            "document_version_hash": document_version_hash(record),
        })
    return {
        "project_id": _text(project.get("project_id")),
        "documents": sorted(document_refs, key=lambda item: (item["paper_id"], item["document_version_hash"])),
        "contracts": [
            {
                "contract_id": _text(item.get("contract_id")),
                "contract_revision": _text(item.get("contract_revision") or item.get("declaration_hash")),
            }
            for item in contracts
        ],
        "normalization_policy_revision": _text(project.get("evidence_normalization_policy_revision")) or "research_evidence_graph_v4_llm_primary_policy",
        "extraction_policy": dict(
            project.get("effective_science_execution_policy")
            or project.get("science_execution_policy")
            or {}
        ),
        "assertion_review_revision": _text(project.get("assertion_review_revision")),
        "detector_admission_projection_policy_revision": (
            DETECTOR_ADMISSION_PROJECTION_POLICY_REVISION
        ),
    }


def _snapshot_inputs_from_tanxi_view(evidence_view: dict[str, Any]) -> dict[str, Any]:
    """Return stable graph inputs without carrying paper text into the graph key."""
    source = evidence_view if isinstance(evidence_view, dict) else {}
    documents = [item for item in source.get("documents", []) if isinstance(item, dict)]
    contracts = [
        validate_research_question_contract(item)
        for item in source.get("contracts", [])
        if isinstance(item, dict)
    ]
    return {
        "project_id": _text(source.get("project_id")),
        "documents": sorted(
            [
                {
                    "paper_id": _text(item.get("paper_id")),
                    "document_version_hash": _text(item.get("document_version_hash")),
                }
                for item in documents
            ],
            key=lambda item: (item["paper_id"], item["document_version_hash"]),
        ),
        "contracts": [
            {
                "contract_id": _text(item.get("contract_id")),
                "contract_revision": _text(
                    item.get("contract_revision") or item.get("declaration_hash")
                ),
            }
            for item in sorted(contracts, key=lambda item: _text(item.get("contract_id")))
        ],
        "evidence_view_fingerprint": _text(source.get("input_fingerprint")),
        "normalization_policy_revision": "research_evidence_graph_v4_reference_first_view",
        "extraction_policy": "immutable_v3_explicit_assertion_artifacts",
        "assertion_review_revision": "",
        "detector_admission_projection_policy_revision": DETECTOR_ADMISSION_PROJECTION_POLICY_REVISION,
    }


def tanxi_evidence_graph_input_fingerprint(evidence_view: dict[str, Any]) -> str:
    """Return the immutable, reference-first graph cache key for TanXi.

    ``load_tanxi_evidence_view`` computes this key from contract/execution
    refs and admitted assertion/span/document identities.  The graph layer
    deliberately consumes that key rather than rehashing quotes, full text,
    timestamps, or a materialized project snapshot.
    """
    source = evidence_view if isinstance(evidence_view, dict) else {}
    fingerprint = _text(source.get("input_fingerprint"))
    if fingerprint.startswith("sha256:"):
        return fingerprint
    inputs = _snapshot_inputs_from_tanxi_view(source)
    return "sha256:" + _digest(inputs)


def _contract_bound_records(project: dict[str, Any], contracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return document copies with explicit contract bindings only.

    V3 extraction correctly refuses an unbound document.  Its record cache is
    not part of the scientific document, however, so graph materialization
    must not mutate a PaperGraph item and thereby cause an otherwise identical
    source document to acquire a fresh graph version on the next run.
    """
    del contracts
    output: list[dict[str, Any]] = []
    for raw_record in project.get("papergraph", []):
        if not isinstance(raw_record, dict):
            continue
        record = dict(raw_record)
        output.append(record)
    return output


def _node(node_id: str, node_type: str, **fields: Any) -> dict[str, Any]:
    return {"node_id": node_id, "node_type": node_type, **{key: value for key, value in fields.items() if value not in (None, "", [], {})}}


def _edge(edge_type: str, source_id: str, target_id: str, **fields: Any) -> dict[str, Any]:
    material = {"edge_type": edge_type, "source_id": source_id, "target_id": target_id, **fields}
    return {
        "edge_id": "redge_" + _digest(material)[:24],
        "edge_type": edge_type,
        "source_id": source_id,
        "target_id": target_id,
        **{key: value for key, value in fields.items() if value not in (None, "", [], {})},
    }


_SOURCE_BODY_FIELDS = frozenset({
    "quote",
    "excerpt",
    "source_quote",
    "supporting_phrase",
    "document",
    "full_text",
    "fulltext",
})


def _reference_only_value(value: Any) -> Any:
    """Remove source bodies from a durable graph projection.

    The detached TanXi evidence view may carry a bounded in-memory quote so
    semantic audit can inspect it during this invocation.  Graph artifacts
    are not that runtime cache: they retain only identities, hashes, and
    locators that can be resolved back through the evidence registries.
    """
    if isinstance(value, dict):
        return {
            str(key): _reference_only_value(item)
            for key, item in value.items()
            if str(key) not in _SOURCE_BODY_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_reference_only_value(item) for item in value]
    return copy.deepcopy(value)


def _document_reference(document: dict[str, Any]) -> dict[str, Any]:
    """Project a paper document into graph-safe bibliographic metadata."""
    source = document if isinstance(document, dict) else {}
    return {
        key: copy.deepcopy(source[key])
        for key in (
            "schema_version",
            "paper_id",
            "document_version_hash",
            "document_version_id",
            "title",
            "doi_or_stable_identifier",
            "publication_type",
            "source_type",
            "source_language",
            "text_extraction_method",
            "ocr_quality",
        )
        if key in source
    }


def _source_span_reference(span: dict[str, Any]) -> dict[str, Any]:
    """Project one source span without copying its excerpt into a snapshot."""
    source = span if isinstance(span, dict) else {}
    reference = {
        key: copy.deepcopy(source[key])
        for key in (
            "schema_version",
            "paper_id",
            "document_version_hash",
            "source_span_id",
            "source_unit_id",
            "span_kind",
            "source_field",
            "section",
            "source_locator",
            "source_type",
            "page_number",
            "paragraph_index",
            "sentence_start",
            "sentence_end",
            "char_start",
            "char_end",
            "bounding_box",
            "binding_status",
            "evidence_material_stage",
            "section_disposition",
            "source_material_status",
            "extraction_quality",
        )
        if key in source
    }
    quote_hash = _text(source.get("quote_hash") or source.get("excerpt_hash"))
    if quote_hash:
        reference["quote_hash"] = quote_hash
    return reference


def _semantic_projection(evidence_graph: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build explicit, provenance-bound projection nodes and edges.

    A normalized relation is represented by a ``RELATION_ASSERTION`` node,
    never by an unsupported direct fact edge between canonical entities.
    """
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    citation_by_document: dict[tuple[str, str], str] = {}
    citation_by_version: dict[str, str] = {}
    for document in evidence_graph.get("documents", []):
        if not isinstance(document, dict):
            continue
        paper_id = _text(document.get("paper_id"))
        version_hash = _text(document.get("document_version_hash"))
        logical_document_id = "doc_" + _digest({"paper_id": paper_id})[:24]
        document_id = "docv_" + _digest({
            "paper_id": paper_id,
            "document_version_hash": version_hash,
        })[:24]
        citation_id = "cite_" + _digest({
            "paper_id": paper_id,
            "doi_or_stable_identifier": document.get("doi_or_stable_identifier"),
            "document_version_hash": version_hash,
        })[:24]
        document_reference = _document_reference(document)
        nodes[logical_document_id] = _node(logical_document_id, "DOCUMENT", paper_id=paper_id)
        nodes[document_id] = _node(document_id, "DOCUMENT_VERSION", **document_reference)
        nodes[citation_id] = _node(
            citation_id,
            "CITATION_RECORD",
            paper_id=paper_id,
            title=document.get("title"),
            doi_or_stable_identifier=document.get("doi_or_stable_identifier"),
            document_version_hash=version_hash,
        )
        edges.append(_edge("HAS_VERSION", logical_document_id, document_id))
        citation_by_document[(paper_id, version_hash)] = citation_id
        if version_hash:
            citation_by_version[version_hash] = citation_id
    for span in evidence_graph.get("source_spans", []):
        if not isinstance(span, dict):
            continue
        span_id = _text(span.get("source_span_id") or span.get("source_unit_id"))
        document_id = "docv_" + _digest({
            "paper_id": span.get("paper_id"),
            "document_version_hash": span.get("document_version_hash"),
        })[:24]
        if not span_id:
            continue
        nodes[span_id] = _node(
            span_id,
            "SOURCE_SPAN",
            **_source_span_reference(span),
        )
        if document_id:
            edges.append(_edge("CONTAINS_SOURCE_SPAN", document_id, span_id))
    for assertion in evidence_graph.get("assertions", []):
        if not isinstance(assertion, dict):
            continue
        assertion_id = _text(assertion.get("assertion_id"))
        if not assertion_id:
            continue
        nodes[assertion_id] = _node(
            assertion_id,
            "EVIDENCE_ASSERTION",
            **_reference_only_value(assertion),
        )
        for span_id in assertion.get("source_span_ids", []):
            if _text(span_id):
                edges.append(_edge("EXPRESSES_ASSERTION", _text(span_id), assertion_id))
        normalization = assertion.get("normalization") if isinstance(assertion.get("normalization"), dict) else {}
        for role, value in (("SUBJECT", normalization.get("subject") or assertion.get("subject")), ("OBJECT", normalization.get("object") or assertion.get("object"))):
            label = _text(value)
            if not label:
                continue
            mention_id = "mention_" + _digest({"assertion_id": assertion_id, "role": role, "label": label})[:24]
            # Mention identity is source-local.  Canonicalization is therefore
            # an explicit, reviewable projection and never an assertion that
            # two strings denote the same scientific construct.
            entity_id = "entity_" + _digest({"mention_id": mention_id, "source_anchored": True})[:24]
            nodes[mention_id] = _node(
                mention_id,
                "ENTITY_MENTION",
                surface_text=label,
                role=role,
                assertion_id=assertion_id,
                source_anchored=True,
            )
            nodes[entity_id] = _node(
                entity_id,
                "CANONICAL_ENTITY",
                canonical_label=label,
                normalization_method="lexical_candidate",
                normalization_confidence=0.0,
                review_status="UNREVIEWED",
                justification_assertion_ids=[assertion_id],
                normalization_status="SOURCE_BOUND_UNREVIEWED",
            )
            edges.append(_edge("MENTIONS", assertion_id, mention_id, role=role))
            edges.append(_edge("NORMALIZES_TO", mention_id, entity_id, method="source_bound_normalization", review_status="UNREVIEWED"))
        predicate = _text(normalization.get("predicate") or assertion.get("predicate"))
        subject = _text(normalization.get("subject") or assertion.get("subject"))
        obj = _text(normalization.get("object") or assertion.get("object"))
        # The assertion layer may expose a typed relation while one endpoint
        # remains source-unknown.  Keep that *partial relation assertion* for
        # audit and targeted retrieval; never invent the missing endpoint or
        # emit a direct entity-to-entity fact edge.
        if predicate:
            relation_id = "rassert_" + _digest({"assertion_id": assertion_id, "predicate": predicate, "subject": subject, "object": obj})[:24]
            nodes[relation_id] = _node(
                relation_id,
                "RELATION_ASSERTION",
                predicate=predicate,
                subject_label=subject,
                object_label=obj,
                textual_explicitness="EXPLICIT",
                epistemic_basis=assertion.get("epistemic_basis"),
                modality=assertion.get("modality"),
                polarity=assertion.get("polarity"),
                document_version_hash=assertion.get("document_version_hash"),
                source_span_ids=list(assertion.get("source_span_ids") or []),
                endpoint_status="COMPLETE" if subject and obj else "PARTIAL_SOURCE_EXPLICIT",
                primary_eligible=False,
            )
            edges.append(_edge("ASSERTS_RELATION", assertion_id, relation_id))
        citation_id = citation_by_document.get(
            (_text(assertion.get("paper_id")), _text(assertion.get("document_version_hash")))
        ) or citation_by_version.get(_text(assertion.get("document_version_hash")))
        if citation_id:
            edges.append(_edge("CITES", assertion_id, citation_id))
        scope = assertion.get("scope_tuple") if isinstance(assertion.get("scope_tuple"), dict) else {}
        for axis in SCOPE_AXES:
            value = _text(scope.get(axis))
            if not value:
                continue
            scope_id = "scope_" + _digest({"axis": axis, "value": value.casefold()})[:24]
            nodes[scope_id] = _node(scope_id, "SCOPE_VALUE", axis=axis, value=value)
            edges.append(_edge("HAS_SCOPE_VALUE", assertion_id, scope_id, axis=axis))
    for link in evidence_graph.get("evidence_links", []):
        if not isinstance(link, dict):
            continue
        link_id = _text(link.get("evidence_link_id"))
        assertion_id = _text(link.get("assertion_id"))
        contract_id = _text(link.get("research_question_contract_id"))
        if not link_id:
            continue
        nodes[link_id] = _node(
            link_id,
            "EVIDENCE_LINK",
            **_reference_only_value(link),
        )
        if assertion_id:
            edges.append(_edge("USES_ASSERTION", link_id, assertion_id, role=link.get("evidence_link_role")))
        if contract_id:
            # A contract is retained even when its only edge is a
            # question-relative evidence link.  The full payload replaces this
            # placeholder later in ``build_research_evidence_graph``.
            nodes.setdefault(contract_id, _node(contract_id, "RESEARCH_QUESTION_CONTRACT"))
            edges.append(_edge("BINDS_TO_RESEARCH_QUESTION", link_id, contract_id))
    for inference in evidence_graph.get("derived_inferences", []):
        if not isinstance(inference, dict):
            continue
        inference_id = _text(inference.get("inference_id")) or "inference_" + _digest(inference)[:24]
        inference_payload = _reference_only_value(inference)
        # A graph-level permission boundary takes precedence over an extractor
        # hint: derived data may guide retrieval, never prove a primary fact.
        inference_payload.update({"primary_eligible": False, "route_ceiling": "DIAGNOSTIC"})
        nodes[inference_id] = _node(inference_id, "DERIVED_INFERENCE", **inference_payload)
        for assertion_id in inference.get("derived_from_assertion_ids", []) or inference.get("source_assertion_ids", []):
            if _text(assertion_id):
                edges.append(_edge("DERIVED_FROM", inference_id, _text(assertion_id), primary_eligible=False))
    return sorted(nodes.values(), key=lambda item: item["node_id"]), sorted(edges, key=lambda item: item["edge_id"])


def _source_assertion_projection(evidence_graph: dict[str, Any]) -> dict[str, Any]:
    """Freeze the detector-readable assertion subset inside the V3 snapshot.

    The compact projection is not a second, independently rebuilt graph.  It
    preserves the explicit assertion payload required by the typed detector
    plugins, while the public semantic topology remains the V3 node/edge
    ledger.  Derived inferences retain their diagnostic-only ceiling.
    """
    admissions = {
        (
            _text(item.get("paper_id")),
            _text(item.get("research_question_contract_id")),
        ): item
        for item in (evidence_graph.get("source_admissions") or {}).values()
        if isinstance(item, dict)
        and _text(item.get("paper_id"))
        and _text(item.get("research_question_contract_id"))
    }
    all_assertions = _list_of_dicts(evidence_graph.get("assertions"))
    admitted_assertions: list[dict[str, Any]] = []
    background_assertions: list[dict[str, Any]] = []
    admitted_ids: set[str] = set()
    admitted_by_contract: dict[str, int] = {}
    background_by_contract: dict[str, int] = {}
    for assertion in all_assertions:
        contract_id = _text(assertion.get("research_question_contract_id"))
        admission = admissions.get((_text(assertion.get("paper_id")), contract_id), {})
        if admission.get("direct_evidence_eligible") is True:
            admitted_assertions.append(_reference_only_value(assertion))
            assertion_id = _text(assertion.get("assertion_id"))
            if assertion_id:
                admitted_ids.add(assertion_id)
            admitted_by_contract[contract_id] = admitted_by_contract.get(contract_id, 0) + 1
        else:
            background_assertions.append(_reference_only_value(assertion))
            background_by_contract[contract_id] = background_by_contract.get(contract_id, 0) + 1
    admitted_inferences: list[dict[str, Any]] = []
    for inference in _list_of_dicts(evidence_graph.get("derived_inferences")):
        input_ids = {
            _text(assertion_id)
            for assertion_id in (
                inference.get("derived_from_assertion_ids")
                or inference.get("source_assertion_ids")
                or inference.get("input_assertion_ids")
            )
            if _text(assertion_id)
        }
        if input_ids and input_ids.issubset(admitted_ids):
            admitted_inferences.append(_reference_only_value(inference))
    summary = dict(evidence_graph.get("summary") or {})
    summary.update(
        {
            "detector_admitted_assertion_count": len(admitted_assertions),
            "all_contract_bound_assertion_count": len(all_assertions),
            "detector_admitted_assertion_count_by_contract": admitted_by_contract,
            "background_assertion_count": len(background_assertions),
            "background_assertion_count_by_contract": background_by_contract,
            "detector_admitted_derived_inference_count": len(admitted_inferences),
        }
    )
    return {
        "schema_version": SOURCE_ASSERTION_PROJECTION_SCHEMA_VERSION,
        "assertions": admitted_assertions,
        "derived_inferences": admitted_inferences,
        "artifact_integrity_errors_v4": _list_of_dicts(
            evidence_graph.get("artifact_integrity_errors_v4")
        ),
        "summary": summary,
        "admission_policy": (
            "Only paper-contract pairs with gap_source_admission_v3 "
            "direct_evidence_eligible=true are detector-visible."
        ),
    }


def graph_quality_audit(snapshot: dict[str, Any]) -> dict[str, Any]:
    node_rows = [item for item in snapshot.get("nodes", []) if isinstance(item, dict)]
    nodes = {str(item.get("node_id") or "") for item in node_rows}
    assertions = {
        str(item.get("node_id") or ""): item
        for item in snapshot.get("nodes", [])
        if isinstance(item, dict) and item.get("node_type") == "EVIDENCE_ASSERTION"
    }
    errors: list[dict[str, Any]] = []
    for edge in snapshot.get("edges", []):
        if not isinstance(edge, dict):
            continue
        if str(edge.get("source_id") or "") not in nodes or str(edge.get("target_id") or "") not in nodes:
            errors.append({"code": "GRAPH_DANGLING_EDGE", "edge_id": edge.get("edge_id")})
    for assertion_id, assertion in assertions.items():
        if _text(assertion.get("schema_version")) != "evidence_assertion_v4":
            errors.append({"code": "NON_V3_ASSERTION", "assertion_id": assertion_id})
        if (
            _text(assertion.get("textual_explicitness")) != "EXPLICIT"
            or _text(assertion.get("assertion_origin")) != "SOURCE_EXPLICIT"
            or _text(assertion.get("derivation_status")) not in {"", "NOT_DERIVED"}
        ):
            errors.append({"code": "NONEXPLICIT_ASSERTION_IN_CANONICAL_LAYER", "assertion_id": assertion_id})
        if not assertion.get("source_span_ids"):
            errors.append({"code": "ASSERTION_WITHOUT_SOURCE_SPAN", "assertion_id": assertion_id})
        if not assertion.get("document_version_hash"):
            errors.append({"code": "ASSERTION_WITHOUT_DOCUMENT_VERSION", "assertion_id": assertion_id})
    edges_by_type: dict[str, list[dict[str, Any]]] = {}
    for edge in snapshot.get("edges", []):
        if isinstance(edge, dict):
            edges_by_type.setdefault(str(edge.get("edge_type") or ""), []).append(edge)
    source_spans = {
        str(item.get("node_id") or ""): item
        for item in node_rows
        if item.get("node_type") == "SOURCE_SPAN"
    }
    for span_id, span in source_spans.items():
        if _text(span.get("schema_version")) != "source_span_v6":
            errors.append({"code": "NON_V3_SOURCE_SPAN", "source_span_id": span_id})
        if not _text(span.get("document_version_hash")):
            errors.append({"code": "SOURCE_SPAN_WITHOUT_DOCUMENT_VERSION", "source_span_id": span_id})
        if not any(str(edge.get("target_id") or "") == span_id for edge in edges_by_type.get("CONTAINS_SOURCE_SPAN", [])):
            errors.append({"code": "SOURCE_SPAN_WITHOUT_DOCUMENT_PROVENANCE", "source_span_id": span_id})
    admissions = [
        item for item in snapshot.get("evidence_admissions", []) if isinstance(item, dict)
    ]
    for admission in admissions:
        assertion_id = _text(admission.get("assertion_id"))
        slot_id = _text(admission.get("slot_id"))
        if _text(admission.get("schema_version")) != "evidence_admission_v4":
            errors.append({"code": "NON_V3_EVIDENCE_ADMISSION", "assertion_id": assertion_id})
            continue
        assertion = assertions.get(assertion_id)
        if not assertion or not slot_id:
            errors.append({"code": "ADMISSION_ASSERTION_OR_SLOT_MISSING", "assertion_id": assertion_id})
            continue
        if slot_id not in {_text(item) for item in assertion.get("admitted_slot_ids_v4", [])}:
            errors.append({"code": "ADMISSION_SLOT_NOT_BOUND_TO_ASSERTION", "assertion_id": assertion_id, "slot_id": slot_id})
        for span_id in admission.get("source_span_ids", []):
            span = source_spans.get(_text(span_id))
            if (
                not span
                or _text(span.get("source_type")) != "fulltext"
                or _text(span.get("span_kind")) in {"title", "abstract"}
            ):
                errors.append({"code": "DIRECT_ADMISSION_NONFULLTEXT_SPAN", "assertion_id": assertion_id, "source_span_id": _text(span_id)})
    evidence_links = {
        str(item.get("node_id") or ""): item
        for item in node_rows
        if item.get("node_type") == "EVIDENCE_LINK"
    }
    for link_id, link in evidence_links.items():
        assertion_edges = [
            edge for edge in edges_by_type.get("USES_ASSERTION", [])
            if str(edge.get("source_id") or "") == link_id
        ]
        contract_edges = [
            edge for edge in edges_by_type.get("BINDS_TO_RESEARCH_QUESTION", [])
            if str(edge.get("source_id") or "") == link_id
        ]
        if len(assertion_edges) != 1 or len(contract_edges) != 1:
            errors.append({"code": "EVIDENCE_LINK_WITHOUT_COMPLETE_ASSERTION_CONTRACT_BINDING", "evidence_link_id": link_id})
            continue
        assertion_id = str(assertion_edges[0].get("target_id") or "")
        if assertion_id not in assertions:
            errors.append({"code": "EVIDENCE_LINK_TARGET_NOT_ASSERTION", "evidence_link_id": link_id})
        elif _text(link.get("assertion_id")) != assertion_id:
            errors.append({"code": "EVIDENCE_LINK_ASSERTION_FIELD_MISMATCH", "evidence_link_id": link_id})
        if not _text(link.get("research_question_contract_id")) or _text(link.get("research_question_contract_id")) != str(contract_edges[0].get("target_id") or ""):
            errors.append({"code": "EVIDENCE_LINK_CONTRACT_FIELD_MISMATCH", "evidence_link_id": link_id})
    for inference in (item for item in node_rows if item.get("node_type") == "DERIVED_INFERENCE"):
        inference_id = str(inference.get("node_id") or "")
        derived_from = [
            edge for edge in edges_by_type.get("DERIVED_FROM", [])
            if str(edge.get("source_id") or "") == inference_id
        ]
        if inference.get("primary_eligible") is not False or not derived_from:
            errors.append({"code": "DERIVED_INFERENCE_PERMISSION_OR_PROVENANCE_INVALID", "inference_id": inference_id})
        elif any(str(edge.get("target_id") or "") not in assertions for edge in derived_from):
            errors.append({"code": "DERIVED_INFERENCE_DERIVES_FROM_NON_ASSERTION", "inference_id": inference_id})
    relation_nodes = [item for item in snapshot.get("nodes", []) if isinstance(item, dict) and item.get("node_type") == "RELATION_ASSERTION"]
    relation_assertion_sources = {
        str(edge.get("target_id") or ""): str(edge.get("source_id") or "")
        for edge in snapshot.get("edges", [])
        if isinstance(edge, dict) and edge.get("edge_type") == "ASSERTS_RELATION"
    }
    for relation in relation_nodes:
        relation_id = str(relation.get("node_id") or "")
        assertion_id = relation_assertion_sources.get(relation_id, "")
        if not assertion_id:
            errors.append({"code": "RELATION_WITHOUT_ASSERTION_PROVENANCE", "relation_id": relation.get("node_id")})
            continue
        assertion = assertions.get(assertion_id, {})
        if not relation.get("document_version_hash") or not relation.get("source_span_ids"):
            errors.append({"code": "RELATION_WITHOUT_SOURCE_PROVENANCE", "relation_id": relation_id})
        elif not assertion.get("source_span_ids") or not assertion.get("document_version_hash"):
            errors.append({"code": "RELATION_ASSERTION_PROVENANCE_CHAIN_BROKEN", "relation_id": relation_id})
    relation_ids = {str(item.get("node_id") or "") for item in relation_nodes}
    comparability_nodes = [item for item in node_rows if item.get("node_type") == "COMPARABILITY_ASSESSMENT"]
    for comparison in comparability_nodes:
        comparison_id = str(comparison.get("node_id") or "")
        compared = {
            str(value) for value in comparison.get("compared_relation_assertion_ids", [])
            if str(value)
        }
        comparison_edges = {
            str(edge.get("target_id") or "")
            for edge in edges_by_type.get("COMPARES_RELATION_ASSERTION", [])
            if str(edge.get("source_id") or "") == comparison_id
        }
        if (
            comparison.get("primary_eligible") is not False
            or len(compared) < 2
            or not compared.issubset(relation_ids)
            or comparison_edges != compared
            or not comparison.get("evidence_refs")
        ):
            errors.append({"code": "COMPARABILITY_ASSESSMENT_PROVENANCE_OR_PERMISSION_INVALID", "comparability_assessment_id": comparison_id})
    document_ids = {
        str(item.get("node_id") or "")
        for item in node_rows
        if item.get("node_type") == "DOCUMENT_VERSION"
    }
    span_document_targets = {
        str(edge.get("source_id") or "")
        for edge in snapshot.get("edges", [])
        if isinstance(edge, dict) and edge.get("edge_type") == "CONTAINS_SOURCE_SPAN"
    }
    # A metadata-only document is allowed to exist in a project graph, but is
    # not eligible to support a scientific relation.  It is reported as a
    # coverage warning rather than poisoning a source-complete, otherwise
    # usable snapshot.
    warnings = [
        {"code": "DOCUMENT_VERSION_WITHOUT_SOURCE_SPAN", "document_id": document_id}
        for document_id in sorted(document_ids - span_document_targets)
    ]
    workflow_integrity = (
        snapshot.get("workflow_integrity")
        if isinstance(snapshot.get("workflow_integrity"), dict)
        else {}
    )
    artifact_errors = _list_of_dicts(
        workflow_integrity.get("artifact_integrity_errors_v4")
    )
    if artifact_errors:
        errors.extend(
            {
                "code": "REFERENCE_FIRST_ARTIFACT_INTEGRITY_ERROR",
                "assertion_id": _text(item.get("assertion_id")),
                "missing_fields": list(item.get("missing_fields") or []),
            }
            for item in artifact_errors
        )
    return {
        "schema_version": GRAPH_QUALITY_SCHEMA_VERSION,
        "passes": not errors,
        "error_count": len(errors),
        "errors": errors,
        "warning_count": len(warnings),
        "warnings": warnings,
        "metrics": {
            "node_count": len(nodes),
            "edge_count": len([item for item in snapshot.get("edges", []) if isinstance(item, dict)]),
            "assertion_count": len(assertions),
            "relation_assertion_count": len(relation_nodes),
            "comparability_assessment_count": len(comparability_nodes),
            "document_version_count": len(document_ids),
            "source_span_count": len(source_spans),
            "evidence_link_count": len(evidence_links),
            "provenance_complete_assertion_count": sum(1 for item in assertions.values() if item.get("source_span_ids") and item.get("document_version_hash")),
            "artifact_integrity_error_count": len(artifact_errors),
        },
    }


def _comparability_assessments(
    evidence_graph: dict[str, Any],
    contracts: list[dict[str, Any]],
    *,
    pair_index: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Materialize auditable, contract-scoped assertion comparisons.

    Comparability is an assessment object, not an inferred direct relation.
    It remains useful when insufficient: detectors can request the missing
    axes without treating unmatched studies as a contradiction.
    """
    try:
        from ._evidence_assertions import compare_scope
    except ImportError:
        from _evidence_assertions import compare_scope
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    contracts_by_id = {_text(item.get("contract_id")): item for item in contracts}
    assertions_by_contract: dict[str, dict[str, dict[str, Any]]] = {}
    for assertion in evidence_graph.get("assertions", []):
        if isinstance(assertion, dict) and _text(assertion.get("assertion_id")):
            contract_id = _text(assertion.get("research_question_contract_id"))
            assertions_by_contract.setdefault(contract_id, {})[
                _text(assertion.get("assertion_id"))
            ] = assertion
    planned_pairs_by_contract = (
        pair_index.get("pairs_by_contract", {})
        if isinstance(pair_index, dict) and isinstance(pair_index.get("pairs_by_contract"), dict)
        else {}
    )
    for contract_id, assertions_by_id in assertions_by_contract.items():
        contract = contracts_by_id.get(contract_id, {})
        required_axes = list((contract.get("evidence_contract") or {}).get("required_comparability_axes") or [])
        for pair in planned_pairs_by_contract.get(contract_id, []):
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            left_id, right_id = _text(pair[0]), _text(pair[1])
            left, right = assertions_by_id.get(left_id), assertions_by_id.get(right_id)
            if not isinstance(left, dict) or not isinstance(right, dict):
                continue
            left_predicate = _text((left.get("normalization") or {}).get("predicate") or left.get("predicate"))
            right_predicate = _text((right.get("normalization") or {}).get("predicate") or right.get("predicate"))
            if not left_predicate or left_predicate != right_predicate:
                continue
            assessment = compare_scope(left, right, required_axes=required_axes)
            verdict_by_status = {
                "ALIGNED": "ALIGNED",
                "PARTIALLY_ALIGNED": "PARTIALLY_ALIGNED",
                "MISMATCHED": "MISMATCHED",
                "INSUFFICIENT_SCOPE_INFORMATION": "INSUFFICIENT",
            }
            assessment_id = "cmp_" + _digest({
                "contract_id": contract_id,
                "left": min(left_id, right_id),
                "right": max(left_id, right_id),
                "required_axes": required_axes,
            })[:24]
            relation_ids = [
                "rassert_" + _digest({
                    "assertion_id": assertion_id,
                    "predicate": _text((assertion.get("normalization") or {}).get("predicate") or assertion.get("predicate")),
                    "subject": _text((assertion.get("normalization") or {}).get("subject") or assertion.get("subject")),
                    "object": _text((assertion.get("normalization") or {}).get("object") or assertion.get("object")),
                })[:24]
                for assertion_id, assertion in ((left_id, left), (right_id, right))
            ]
            nodes.append(_node(
                assessment_id,
                "COMPARABILITY_ASSESSMENT",
                schema_version=COMPARABILITY_ASSESSMENT_SCHEMA_VERSION,
                research_question_contract_id=contract_id,
                compared_relation_assertion_ids=relation_ids,
                compared_scope_axes=required_axes,
                verdict=verdict_by_status.get(_text(assessment.get("status")), "INSUFFICIENT"),
                mismatch_axes=list(assessment.get("mismatched_axes") or []),
                unknown_axes=list(assessment.get("unknown_axes") or []),
                aligned_axes=list(assessment.get("aligned_axes") or []),
                evidence_refs=[left_id, right_id],
                assessment_basis="EXPLICIT_SOURCE_BOUND_SCOPE_COMPARISON",
                primary_eligible=False,
            ))
            for relation_id in relation_ids:
                edges.append(_edge("COMPARES_RELATION_ASSERTION", assessment_id, relation_id))
    return nodes, edges


def _task_node_id(node_type: str, item: dict[str, Any], *, fallback: str = "") -> str:
    identity = _text(item.get({
        "GAP_CANDIDATE": "gap_id",
        "RETRIEVAL_TASK": "task_id",
        "RETRIEVAL_ASSESSMENT": "assessment_id",
        "RESEARCH_PACKAGE": "research_package_id",
        "SOCRATES_TYPE_REVIEW": "gap_id",
        "PROPOSAL_BRIEF": "proposal_brief_id",
        "PROPOSAL_ARTIFACT": "proposal_id",
        "PROPOSAL_AUDIT": "proposal_id",
    }.get(node_type, "")) or fallback)
    # Task-node identity follows the durable artefact identity.  Mutable
    # lifecycle fields belong in a new task-graph *version*, not in a new node
    # id, so audit views can compare the same package/review/proposal over
    # time.
    return f"task_{node_type.lower()}_" + _digest({"type": node_type, "identity": identity})[:24]


def build_research_task_graph(project: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Build the versioned workflow layer without mutating evidence nodes.

    This graph deliberately stores only references to the immutable evidence
    snapshot.  A document change invalidates task artefacts, whereas a task
    state change merely produces a new task-graph revision.
    """
    if _text(snapshot.get("schema_version")) != RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION:
        raise ValueError("Research task graph requires research_evidence_graph_v4")
    graph_ref = graph_snapshot_ref(snapshot)
    edges: list[dict[str, Any]] = []
    nodes: dict[str, dict[str, Any]] = {}
    contract_nodes = {
        _text(item.get("node_id")): item
        for item in snapshot.get("nodes", [])
        if isinstance(item, dict) and item.get("node_type") == "RESEARCH_QUESTION_CONTRACT"
    }
    for contract_id, contract in contract_nodes.items():
        nodes[contract_id] = dict(contract)
    for link in (
        item for item in snapshot.get("nodes", [])
        if isinstance(item, dict) and item.get("node_type") == "EVIDENCE_LINK"
    ):
        link_id = _text(link.get("node_id"))
        contract_id = _text(link.get("research_question_contract_id"))
        if not link_id:
            continue
        nodes[link_id] = dict(link)
        if contract_id in nodes:
            edges.append(_edge("ASSOCIATES_EVIDENCE_LINK", contract_id, link_id))

    gap_candidates = [
        item for item in [
            *(project.get("knowledge_gaps") if isinstance(project.get("knowledge_gaps"), list) else []),
            *((project.get("tanxi_gap_analysis") or {}).get("ranked_gaps", []) if isinstance(project.get("tanxi_gap_analysis"), dict) else []),
        ] if isinstance(item, dict)
    ]
    seen_candidates: set[str] = set()
    candidate_ids: dict[str, str] = {}
    for candidate in gap_candidates:
        identity = _text(candidate.get("candidate_identity") or candidate.get("gap_id"))
        if not identity or identity in seen_candidates:
            continue
        seen_candidates.add(identity)
        task_id = _task_node_id("GAP_CANDIDATE", candidate, fallback=identity)
        candidate_ids[identity] = task_id
        if _text(candidate.get("gap_id")):
            candidate_ids[_text(candidate.get("gap_id"))] = task_id
        assessment = candidate.get("gap_assessment") if isinstance(candidate.get("gap_assessment"), dict) else {}
        nodes[task_id] = _node(
            task_id,
            "GAP_CANDIDATE",
            gap_id=_text(candidate.get("gap_id")),
            candidate_identity=identity,
            gap_type=_text(candidate.get("gap_type") or assessment.get("gap_type")),
            route=_text(assessment.get("route")),
            graph_snapshot_ref=dict(candidate.get("graph_snapshot_ref") or graph_ref),
        )
        contract = candidate.get("research_question_contract") if isinstance(candidate.get("research_question_contract"), dict) else {}
        contract_id = _text(contract.get("contract_id"))
        if contract_id in nodes:
            edges.append(_edge("GENERATES_GAP_CANDIDATE", contract_id, task_id))
        for unit in candidate.get("source_evidence_units", []):
            if not isinstance(unit, dict):
                continue
            link_id = _text(unit.get("evidence_link_id"))
            if link_id:
                edges.append(_edge("EVIDENCE_LINK_SUPPORTS_GAP", link_id, task_id, diagnostic_only=False))
        retrieval = candidate.get("retrieval_assessment") if isinstance(candidate.get("retrieval_assessment"), dict) else {}
        retrieval_plan = candidate.get("retrieval_plan") if isinstance(candidate.get("retrieval_plan"), dict) else {}
        if retrieval_plan:
            retrieval_task_id = _task_node_id("RETRIEVAL_TASK", retrieval_plan, fallback=identity)
            nodes[retrieval_task_id] = _node(
                retrieval_task_id,
                "RETRIEVAL_TASK",
                candidate_identity=identity,
                objective=_text(retrieval_plan.get("objective")),
                missing_axes=list(retrieval_plan.get("missing_axes") or [retrieval_plan.get("missing_axis")] if retrieval_plan.get("missing_axis") else []),
                graph_snapshot_ref=graph_ref,
                primary_eligible=False,
            )
            edges.append(_edge("HAS_RETRIEVAL_TASK", task_id, retrieval_task_id))
        if retrieval:
            retrieval_id = _task_node_id("RETRIEVAL_ASSESSMENT", retrieval, fallback=identity)
            nodes[retrieval_id] = _node(
                retrieval_id,
                "RETRIEVAL_ASSESSMENT",
                schema_version=_text(retrieval.get("schema_version")),
                candidate_identity=identity,
                novelty_verdict=_text(retrieval.get("novelty_verdict")),
                coverage_status=_text(retrieval.get("coverage_status") or "RECORDED"),
                remaining_missing_axes=list(retrieval.get("remaining_missing_axes") or []),
                graph_snapshot_ref=graph_ref,
                primary_eligible=False,
            )
            edges.append(_edge("HAS_RETRIEVAL_ASSESSMENT", task_id, retrieval_id))

    packages = _list_of_dicts(project.get("research_packages"))
    package_ids: dict[str, str] = {}
    for package in packages:
        package_id = _text(package.get("research_package_id"))
        if not package_id:
            continue
        task_id = _task_node_id("RESEARCH_PACKAGE", package, fallback=package_id)
        package_ids[package_id] = task_id
        nodes[task_id] = _node(
            task_id,
            "RESEARCH_PACKAGE",
            research_package_id=package_id,
            package_version=int(package.get("package_version") or 0),
            gap_id=_text(package.get("gap_id")),
            package_kind=_text(package.get("package_kind")),
            lifecycle_status=_text(package.get("lifecycle_status")),
            graph_snapshot_ref=dict(package.get("graph_snapshot_ref") or {}),
        )
        gap_task_id = candidate_ids.get(_text(package.get("candidate_identity") or package.get("gap_id")))
        if gap_task_id:
            edges.append(_edge("QUALIFIES_AS_RESEARCH_PACKAGE", gap_task_id, task_id))

    reviews = project.get("socrates_type_reviews") if isinstance(project.get("socrates_type_reviews"), dict) else {}
    for review in _list_of_dicts(list(reviews.values())):
        task_id = _task_node_id("SOCRATES_TYPE_REVIEW", review, fallback=_text(review.get("research_package_id")))
        nodes[task_id] = _node(
            task_id,
            "SOCRATES_TYPE_REVIEW",
            research_package_id=_text(review.get("research_package_id")),
            package_version=int(review.get("package_version") or 0),
            review_mode=_text(review.get("review_mode")),
            status=_text(review.get("status")),
            review_ready=review.get("review_ready") is True,
            graph_snapshot_ref=graph_ref,
        )
        package_task_id = package_ids.get(_text(review.get("research_package_id")))
        if package_task_id:
            edges.append(_edge("HAS_SOCRATES_REVIEW", package_task_id, task_id))

    briefs = _list_of_dicts(project.get("proposal_briefs"))
    brief_ids: dict[str, str] = {}
    for brief in briefs:
        brief_id = _text(brief.get("proposal_brief_id"))
        if not brief_id:
            continue
        task_id = _task_node_id("PROPOSAL_BRIEF", brief, fallback=brief_id)
        brief_ids[brief_id] = task_id
        nodes[task_id] = _node(
            task_id,
            "PROPOSAL_BRIEF",
            proposal_brief_id=brief_id,
            proposal_kind=_text(brief.get("proposal_kind")),
            lifecycle_status=_text(brief.get("lifecycle_status")),
            graph_snapshot_ref=dict(brief.get("graph_snapshot_ref") or {}),
        )
        package_task_id = package_ids.get(_text((brief.get("research_package_ref") or {}).get("research_package_id")))
        if package_task_id:
            edges.append(_edge("FREEZES_AS_PROPOSAL_BRIEF", package_task_id, task_id))

    for proposal in _list_of_dicts(project.get("research_proposals")):
        proposal_id = _text(proposal.get("proposal_id"))
        if not proposal_id:
            continue
        task_id = _task_node_id("PROPOSAL_ARTIFACT", proposal, fallback=proposal_id)
        nodes[task_id] = _node(
            task_id,
            "PROPOSAL_ARTIFACT",
            proposal_id=proposal_id,
            proposal_kind=_text(proposal.get("proposal_kind")),
            lifecycle_status=_text(proposal.get("lifecycle_status")),
            graph_snapshot_ref=dict(proposal.get("graph_snapshot_ref") or {}),
        )
        brief_task_id = brief_ids.get(_text((proposal.get("proposal_brief_ref") or {}).get("proposal_brief_id")))
        if brief_task_id:
            edges.append(_edge("MATERIALIZES_PROPOSAL", brief_task_id, task_id))
        audit = proposal.get("audit") if isinstance(proposal.get("audit"), dict) else {}
        if audit:
            audit_id = _task_node_id("PROPOSAL_AUDIT", audit, fallback=proposal_id)
            nodes[audit_id] = _node(
                audit_id,
                "PROPOSAL_AUDIT",
                proposal_id=proposal_id,
                status=_text(audit.get("status")),
                passes=audit.get("passes") is True,
                graph_snapshot_ref=dict(proposal.get("graph_snapshot_ref") or {}),
            )
            edges.append(_edge("HAS_PROPOSAL_AUDIT", task_id, audit_id))

    input_fingerprint = _digest({
        "graph_snapshot_ref": graph_ref,
        # Task topology is not enough: a package's lifecycle status, a
        # retrieval coverage verdict, or a Socrates readiness decision can
        # change while the same IDs remain connected.  Version the compact
        # task-node payload as well, while preserving the immutable evidence
        # snapshot reference separately.
        "nodes": sorted(nodes.values(), key=lambda item: item["node_id"]),
        "edges": sorted((edge["edge_type"], edge["source_id"], edge["target_id"]) for edge in edges),
    })
    existing = _list_of_dicts(project.get("research_task_graphs"))
    current = next((item for item in existing if item.get("input_fingerprint") == input_fingerprint and item.get("build_status") == "CURRENT"), None)
    if current:
        return current
    graph_id = "rtg_" + _digest({"project_id": project.get("project_id"), "evidence_graph_id": graph_ref.get("graph_id")})[:20]
    versions = [int(item.get("task_graph_version") or 0) for item in existing if item.get("task_graph_id") == graph_id]
    return {
        "schema_version": RESEARCH_TASK_GRAPH_SCHEMA_VERSION,
        "task_graph_id": graph_id,
        "task_graph_version": max(versions, default=0) + 1,
        "project_id": _text(project.get("project_id")),
        "graph_snapshot_ref": graph_ref,
        "input_fingerprint": input_fingerprint,
        "build_status": "CURRENT",
        "nodes": sorted(nodes.values(), key=lambda item: item["node_id"]),
        "edges": sorted(edges, key=lambda item: item["edge_id"]),
        "created_at": time.time(),
    }


def persist_research_task_graph(project: dict[str, Any], snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Persist one task-lineage version attached to the active evidence graph."""
    evidence_snapshot = snapshot if isinstance(snapshot, dict) else active_research_evidence_graph(project)
    task_graph = build_research_task_graph(project, evidence_snapshot)
    current_ref = project.get("active_research_task_graph_ref") if isinstance(project.get("active_research_task_graph_ref"), dict) else {}
    if current_ref.get("input_fingerprint") == task_graph.get("input_fingerprint"):
        return task_graph
    graphs = _list_of_dicts(project.get("research_task_graphs"))
    for graph in graphs:
        if graph.get("build_status") == "CURRENT":
            graph["build_status"] = "SUPERSEDED"
            graph["superseded_by"] = {
                "task_graph_id": task_graph["task_graph_id"],
                "task_graph_version": task_graph["task_graph_version"],
                "input_fingerprint": task_graph["input_fingerprint"],
            }
    graphs.append(task_graph)
    project["research_task_graphs"] = graphs
    project["active_research_task_graph_ref"] = {
        "task_graph_id": task_graph["task_graph_id"],
        "task_graph_version": task_graph["task_graph_version"],
        "input_fingerprint": task_graph["input_fingerprint"],
        "graph_snapshot_ref": dict(task_graph["graph_snapshot_ref"]),
    }
    return task_graph


def build_research_evidence_graph(project: dict[str, Any]) -> dict[str, Any]:
    """Reject the removed full-project graph construction route."""
    raise ValueError(
        "TANXI_V3_EVIDENCE_VIEW_REQUIRED: Build Research Evidence Graph V3 only "
        "from the persisted V3 TanXi evidence view inside the AutoGen GroupChat."
    )


def build_research_evidence_graph_from_tanxi_view(
    evidence_view: dict[str, Any],
    *,
    prior_snapshot: dict[str, Any] | None = None,
    per_bucket_pair_limit: int = 64,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """Build V4 directly from persisted V4 TanXi evidence, without extraction."""
    source = evidence_view if isinstance(evidence_view, dict) else {}
    contracts = [
        validate_research_question_contract(item)
        for item in source.get("contracts", [])
        if isinstance(item, dict)
    ]
    inputs = _snapshot_inputs_from_tanxi_view(source)
    fingerprint = tanxi_evidence_graph_input_fingerprint(source)
    prior = prior_snapshot if isinstance(prior_snapshot, dict) else {}
    if (
        prior.get("build_status") == "CURRENT"
        and _text(prior.get("input_fingerprint")) == fingerprint
        and _text(prior.get("snapshot_id"))
    ):
        return dict(prior)
    if _text(source.get("schema_version")) != "tanxi_evidence_view_v4":
        raise ValueError(
            "ResearchGraph requires tanxi_evidence_view_v4"
        )
    evidence_graph = build_heterogeneous_evidence_graph_v4_from_tanxi_view(
        source,
        per_bucket_pair_limit=per_bucket_pair_limit,
        progress_callback=progress_callback,
    )
    nodes, edges = _semantic_projection(evidence_graph)
    pair_index = evidence_graph.get("comparability_pair_index") if isinstance(
        evidence_graph.get("comparability_pair_index"), dict
    ) else {}
    comparison_nodes, comparison_edges = _comparability_assessments(
        evidence_graph,
        contracts,
        pair_index=pair_index,
    )
    nodes.extend(comparison_nodes)
    edges.extend(comparison_edges)
    nodes_by_id = {str(item.get("node_id") or ""): item for item in nodes}
    for contract in contracts:
        contract_id = _text(contract.get("contract_id"))
        if contract_id:
            nodes_by_id[contract_id] = _node(
                contract_id,
                "RESEARCH_QUESTION_CONTRACT",
                **contract,
            )
    graph_id = "reg_" + _digest({"project_id": inputs["project_id"]})[:20]
    graph_version = int(prior.get("graph_version") or 0) + 1
    snapshot_id = "rgs_" + _digest({
        "graph_id": graph_id,
        "graph_version": graph_version,
        "input_fingerprint": fingerprint,
    })[:24]
    snapshot = {
        "schema_version": RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION,
        "graph_id": graph_id,
        "graph_version": graph_version,
        "snapshot_id": snapshot_id,
        "project_id": inputs["project_id"],
        "build_status": "CURRENT",
        "input_fingerprint": fingerprint,
        "build_inputs": inputs,
        "document_version_refs": list(inputs["documents"]),
        "research_question_contract_refs": list(inputs["contracts"]),
        "normalization_policy_revision": inputs["normalization_policy_revision"],
        "invalidates": [graph_snapshot_ref(prior)] if prior else [],
        "source_evidence_graph_schema_version": evidence_graph.get("schema_version"),
        "evidence_pipeline_schema_version": "evidence_pipeline_v4",
        "source_assertion_projection": _source_assertion_projection(evidence_graph),
        # Cross-paper comparison synthesis is a graph-level, immutable result.
        # It is deliberately separate from source assertions so no individual
        # paper can appear to prove a two-arm conclusion by itself.
        "comparison_synthesis_artifacts_v4": [
            _reference_only_value(item)
            for item in evidence_graph.get("comparison_synthesis_artifacts_v4", [])
            if isinstance(item, dict)
        ],
        "evidence_admissions": [
            _reference_only_value(item)
            for item in evidence_graph.get("evidence_admissions", [])
            if isinstance(item, dict)
        ],
        "nodes": sorted(nodes_by_id.values(), key=lambda item: item["node_id"]),
        "edges": sorted(edges, key=lambda item: item["edge_id"]),
        "summary": dict(evidence_graph.get("summary") or {}),
        "comparability_pair_index_summary": dict(pair_index.get("summary") or {}),
        "comparability_diagnostics": list(pair_index.get("diagnostics") or []),
        "created_at": time.time(),
    }
    integrity_errors = _list_of_dicts(evidence_graph.get("artifact_integrity_errors_v4"))
    snapshot["workflow_integrity"] = {
        "status": "INTEGRITY_ERROR" if integrity_errors else "PASS",
        "artifact_integrity_error_count": len(integrity_errors),
        "artifact_integrity_errors_v4": integrity_errors,
        "scientific_interpretation_allowed": not integrity_errors,
    }
    snapshot["quality_audit"] = graph_quality_audit(snapshot)
    return snapshot


def graph_snapshot_ref(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_id": _text(snapshot.get("snapshot_id")),
        "graph_id": _text(snapshot.get("graph_id")),
        "graph_version": int(snapshot.get("graph_version") or 0),
        "input_fingerprint": _text(snapshot.get("input_fingerprint")),
        "schema_version": _text(snapshot.get("schema_version")),
    }


def bind_candidate_to_graph_snapshot(candidate: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Bind candidate source units to unique V3 assertion/span/link objects.

    This is a strict provenance join, not semantic retrieval.  A unit that
    cannot be matched to exactly one explicit assertion in the candidate's
    research-question contract remains marked ``GRAPH_BINDING_UNRESOLVED``;
    callers must route it to evidence extraction/retrieval rather than guess.
    """
    if _text(snapshot.get("schema_version")) != RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION:
        raise ValueError("Candidate binding requires research_evidence_graph_v4")
    output = dict(candidate)
    graph_quality = snapshot.get("quality_audit") if isinstance(snapshot.get("quality_audit"), dict) else {}
    graph_quality_passes = graph_quality.get("passes") is True
    contract = output.get("research_question_contract") if isinstance(output.get("research_question_contract"), dict) else {}
    contract_id = _text(contract.get("contract_id"))
    node_list = [item for item in snapshot.get("nodes", []) if isinstance(item, dict)]
    assertion_nodes = [item for item in node_list if item.get("node_type") == "EVIDENCE_ASSERTION"]
    link_nodes = [item for item in node_list if item.get("node_type") == "EVIDENCE_LINK"]
    assertions_by_id = {str(item.get("node_id") or ""): item for item in assertion_nodes}
    links_by_assertion: dict[str, list[dict[str, Any]]] = {}
    for link in link_nodes:
        assertion_id = _text(link.get("assertion_id"))
        if assertion_id:
            links_by_assertion.setdefault(assertion_id, []).append(link)
    bound_units: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for raw_unit in output.get("source_evidence_units", []):
        if not isinstance(raw_unit, dict):
            continue
        unit = dict(raw_unit)
        span_id = _text(unit.get("source_span_id") or unit.get("source_unit_id"))
        assertion_id = _text(unit.get("assertion_id") or unit.get("evidence_assertion_id"))
        matches: list[dict[str, Any]] = []
        if assertion_id and assertion_id in assertions_by_id:
            matches = [assertions_by_id[assertion_id]]
        elif span_id:
            matches = [
                item for item in assertion_nodes
                if span_id in {str(value) for value in item.get("source_span_ids", [])}
                and (not contract_id or _text(item.get("research_question_contract_id")) == contract_id)
            ]
        if len(matches) != 1:
            unit["graph_binding_status"] = "GRAPH_BINDING_UNRESOLVED"
            diagnostics.append({
                "source_unit_id": _text(unit.get("source_unit_id")),
                "source_span_id": span_id,
                "reason": "NO_UNIQUE_EXPLICIT_ASSERTION_FOR_SOURCE_UNIT",
                "match_count": len(matches),
            })
            bound_units.append(unit)
            continue
        assertion = matches[0]
        assertion_id = _text(assertion.get("node_id"))
        eligible_links = [
            item for item in links_by_assertion.get(assertion_id, [])
            if not contract_id or _text(item.get("research_question_contract_id")) == contract_id
        ]
        if len(eligible_links) != 1:
            unit["graph_binding_status"] = "GRAPH_BINDING_UNRESOLVED"
            diagnostics.append({
                "source_unit_id": _text(unit.get("source_unit_id")),
                "assertion_id": assertion_id,
                "reason": "NO_UNIQUE_EVIDENCE_LINK_FOR_ASSERTION_AND_CONTRACT",
                "match_count": len(eligible_links),
            })
            bound_units.append(unit)
            continue
        link = eligible_links[0]
        unit.update(
            {
                "assertion_id": assertion_id,
                "evidence_assertion_id": assertion_id,
                "source_span_id": span_id or _text((assertion.get("source_span_ids") or [""])[0]),
                "evidence_link_id": _text(link.get("node_id")),
                "evidence_link_role": _text(link.get("evidence_link_role")),
                "graph_binding_status": "GRAPH_BOUND",
            }
        )
        bound_units.append(unit)
    output["source_evidence_units"] = bound_units
    output["graph_snapshot_ref"] = graph_snapshot_ref(snapshot)
    output["assertion_refs"] = sorted(
        {
            _text(unit.get("assertion_id") or unit.get("evidence_assertion_id"))
            for unit in bound_units
            if isinstance(unit, dict) and _text(unit.get("assertion_id") or unit.get("evidence_assertion_id"))
        }
    )
    output["source_span_refs"] = sorted(
        {
            _text(unit.get("source_span_id") or unit.get("source_unit_id"))
            for unit in bound_units
            if isinstance(unit, dict) and _text(unit.get("source_span_id") or unit.get("source_unit_id"))
        }
    )
    output["evidence_link_refs"] = sorted(
        {
            _text(unit.get("evidence_link_id"))
            for unit in bound_units
            if isinstance(unit, dict) and _text(unit.get("evidence_link_id"))
        }
    )
    # Comparability assessments are source-bound diagnostics.  Carry exact
    # node references on a candidate when its source assertions participate;
    # their verdict never upgrades a candidate by itself.
    source_assertion_ids = {
        _text(unit.get("assertion_id") or unit.get("evidence_assertion_id"))
        for unit in bound_units
        if isinstance(unit, dict)
    }
    relation_by_assertion = {
        _text(edge.get("source_id")): _text(edge.get("target_id"))
        for edge in snapshot.get("edges", [])
        if isinstance(edge, dict) and edge.get("edge_type") == "ASSERTS_RELATION"
    }
    source_relation_ids = {
        relation_by_assertion[assertion_id]
        for assertion_id in source_assertion_ids
        if assertion_id in relation_by_assertion
    }
    comparability_refs = []
    for node in node_list:
        if node.get("node_type") != "COMPARABILITY_ASSESSMENT":
            continue
        compared = {_text(value) for value in node.get("compared_relation_assertion_ids", []) if _text(value)}
        if compared and source_relation_ids & compared:
            comparability_refs.append(
                {
                    "comparability_assessment_id": _text(node.get("node_id")),
                    "verdict": _text(node.get("verdict")),
                    "mismatch_axes": list(node.get("mismatch_axes") or []),
                    "unknown_axes": list(node.get("unknown_axes") or []),
                    "evidence_refs": list(node.get("evidence_refs") or []),
                    "diagnostic_only": True,
                }
            )
    output["scope_comparability_refs"] = comparability_refs
    output["derived_inference_refs"] = []
    if not graph_quality_passes:
        diagnostics.append(
            {
                "reason": "RESEARCH_EVIDENCE_GRAPH_QUALITY_AUDIT_FAILED",
                "graph_errors": list(graph_quality.get("errors") or []),
            }
        )
    output["graph_binding_audit"] = {
        "schema_version": "candidate_graph_binding_audit_v3",
        "status": "PASSED" if bound_units and not diagnostics else "BLOCKED",
        "graph_quality_passes": graph_quality_passes,
        "bound_source_unit_count": sum(1 for item in bound_units if item.get("graph_binding_status") == "GRAPH_BOUND"),
        "unresolved_source_unit_count": len(diagnostics),
        "diagnostics": diagnostics,
    }
    return output


def persist_research_evidence_graph(project: dict[str, Any]) -> dict[str, Any]:
    """Reject direct graph persistence outside the V3 GroupChat TanXi stage."""
    raise ValueError(
        "BLOCKED_V3_GROUPCHAT_ONLY: Persist the detached evidence graph through "
        "ScienceStateManager.persist_tanxi_evidence_graph during TanXi."
    )


def _graph_change_impact(prior_snapshot: dict[str, Any], current_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Describe dependency changes that can invalidate downstream artefacts."""
    before = prior_snapshot.get("build_inputs") if isinstance(prior_snapshot.get("build_inputs"), dict) else {}
    after = current_snapshot.get("build_inputs") if isinstance(current_snapshot.get("build_inputs"), dict) else {}
    before_documents = {
        _text(item.get("paper_id")): _text(item.get("document_version_hash"))
        for item in before.get("documents", []) if isinstance(item, dict)
    }
    after_documents = {
        _text(item.get("paper_id")): _text(item.get("document_version_hash"))
        for item in after.get("documents", []) if isinstance(item, dict)
    }
    before_contracts = {
        _text(item.get("contract_id")): _text(item.get("contract_revision"))
        for item in before.get("contracts", []) if isinstance(item, dict)
    }
    after_contracts = {
        _text(item.get("contract_id")): _text(item.get("contract_revision"))
        for item in after.get("contracts", []) if isinstance(item, dict)
    }
    changed_documents = {
        paper_id
        for paper_id in set(before_documents) | set(after_documents)
        if before_documents.get(paper_id) != after_documents.get(paper_id)
    }
    changed_contracts = {
        contract_id
        for contract_id in set(before_contracts) | set(after_contracts)
        if before_contracts.get(contract_id) != after_contracts.get(contract_id)
    }
    global_reasons = [
        reason
        for reason, key in (
            ("NORMALIZATION_POLICY_CHANGED", "normalization_policy_revision"),
            ("EXTRACTION_POLICY_CHANGED", "extraction_policy"),
            ("ASSERTION_REVIEW_REVISION_CHANGED", "assertion_review_revision"),
        )
        if before.get(key) != after.get(key)
    ]
    return {
        "changed_document_ids": sorted(item for item in changed_documents if item),
        "changed_contract_ids": sorted(item for item in changed_contracts if item),
        "global_reasons": global_reasons,
    }


def _artifact_is_impacted(item: dict[str, Any], impact: dict[str, Any]) -> bool:
    if impact.get("global_reasons"):
        return True
    changed_documents = set(impact.get("changed_document_ids") or [])
    changed_contracts = set(impact.get("changed_contract_ids") or [])
    contract = item.get("research_question_contract") if isinstance(item.get("research_question_contract"), dict) else {}
    contract_id = _text(
        contract.get("contract_id")
        or item.get("research_question_contract_id")
        or ((item.get("research_question") or {}).get("contract_id") if isinstance(item.get("research_question"), dict) else "")
    )
    if contract_id and contract_id in changed_contracts:
        return True
    records = [
        *(_list_of_dicts(item.get("source_evidence_units"))),
        *(_list_of_dicts(item.get("source_lineage"))),
        *(_list_of_dicts(item.get("evidence_bundle"))),
        *(_list_of_dicts(item.get("evidence_basis"))),
    ]
    return any(_text(record.get("paper_id")) in changed_documents for record in records)


def _invalidate_downstream_artifacts(
    project: dict[str, Any],
    current_ref: dict[str, Any],
    *,
    prior_snapshot: dict[str, Any],
    current_snapshot: dict[str, Any],
) -> None:
    """Mark only derivatives affected by document/contract/policy changes."""
    impact = _graph_change_impact(prior_snapshot, current_snapshot)
    invalidation_reason = [
        *[f"DOCUMENT_VERSION_CHANGED:{item}" for item in impact["changed_document_ids"]],
        *[f"RESEARCH_QUESTION_CONTRACT_CHANGED:{item}" for item in impact["changed_contract_ids"]],
        *list(impact["global_reasons"]),
    ] or ["SOURCE_EVIDENCE_GRAPH_SNAPSHOT_CHANGED"]
    def mark_candidate(candidate: dict[str, Any]) -> None:
        bound_ref = candidate.get("graph_snapshot_ref") if isinstance(candidate.get("graph_snapshot_ref"), dict) else {}
        if bound_ref and bound_ref.get("input_fingerprint") != current_ref.get("input_fingerprint") and _artifact_is_impacted(candidate, impact):
            candidate["lifecycle_status"] = "STALE_GRAPH_SNAPSHOT"
            candidate["invalidated_by"] = current_ref
            candidate.setdefault("decision_reasons", []).extend(invalidation_reason)
            assessment = candidate.get("gap_assessment") if isinstance(candidate.get("gap_assessment"), dict) else {}
            if assessment:
                assessment["route"] = "TARGETED_RETRIEVAL"
                assessment["decision_reasons"] = list(assessment.get("decision_reasons") or []) + invalidation_reason
                candidate["gap_assessment"] = assessment

    for candidate in project.get("knowledge_gaps", []):
        if isinstance(candidate, dict):
            mark_candidate(candidate)
    tanxi = project.get("tanxi_gap_analysis") if isinstance(project.get("tanxi_gap_analysis"), dict) else {}
    for candidate in tanxi.get("ranked_gaps", []) if isinstance(tanxi.get("ranked_gaps"), list) else []:
        if isinstance(candidate, dict):
            mark_candidate(candidate)
    for collection_key, id_key in (("research_packages", "research_package_id"), ("proposal_briefs", "proposal_brief_id"), ("research_proposals", "proposal_id")):
        collection = project.get(collection_key)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            bound_ref = item.get("graph_snapshot_ref") if isinstance(item.get("graph_snapshot_ref"), dict) else {}
            if bound_ref and bound_ref.get("input_fingerprint") != current_ref.get("input_fingerprint") and _artifact_is_impacted(item, impact):
                item["lifecycle_status"] = "STALE_GRAPH_SNAPSHOT"
                item["invalidated_by"] = current_ref
                item.setdefault("decision_reasons", []).extend(invalidation_reason)
    reviews = project.get("socrates_type_reviews") if isinstance(project.get("socrates_type_reviews"), dict) else {}
    for review in reviews.values():
        if not isinstance(review, dict):
            continue
        package_id = _text(review.get("research_package_id"))
        package = next(
            (
                item for item in project.get("research_packages", [])
                if isinstance(item, dict) and _text(item.get("research_package_id")) == package_id
            ),
            {},
        )
        package_ref = package.get("graph_snapshot_ref") if isinstance(package.get("graph_snapshot_ref"), dict) else {}
        if package_ref and package_ref.get("input_fingerprint") != current_ref.get("input_fingerprint") and _artifact_is_impacted(package, impact):
            review["lifecycle_status"] = "STALE_GRAPH_SNAPSHOT"
            review["invalidated_by"] = current_ref
            review["review_ready"] = False
            review["status"] = "TYPE_SPECIFIC_REVIEW_STALE"


def active_research_evidence_graph(project: dict[str, Any]) -> dict[str, Any]:
    ref = project.get("active_research_evidence_graph_ref") if isinstance(project.get("active_research_evidence_graph_ref"), dict) else {}
    for item in project.get("research_evidence_graphs", []):
        if isinstance(item, dict) and item.get("graph_id") == ref.get("graph_id") and int(item.get("graph_version") or 0) == int(ref.get("graph_version") or 0):
            return dict(item)
    project_id = _text(project.get("project_id"))
    if project_id and ref:
        try:
            from ._project import science_state_manager
        except ImportError:
            from _project import science_state_manager
        snapshot = science_state_manager().get_research_evidence_graph(project_id, ref)
        if isinstance(snapshot, dict):
            return snapshot
    raise ValueError(
        "DETACHED_RESEARCH_EVIDENCE_GRAPH_REQUIRED: V3 graph bodies are immutable "
        "artifacts and must be resolved by project_id, not rebuilt from a materialized project."
    )


def graph_view(
    snapshot: dict[str, Any],
    *,
    research_question_contract_id: str = "",
    gap_type: str = "",
    required_scope_axes: list[str] | tuple[str, ...] | None = None,
    source_quality_policy: str = "SOURCE_BOUND_EXPLICIT_ONLY",
    include_derived_inferences: bool = False,
) -> dict[str, Any]:
    """Return a contract-scoped graph view without promoting inferences."""
    if _text(snapshot.get("schema_version")) != RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION:
        raise ValueError("GraphView requires research_evidence_graph_v4")
    contract_id = _text(research_question_contract_id)
    nodes_by_id = {str(item.get("node_id") or ""): item for item in snapshot.get("nodes", []) if isinstance(item, dict)}
    raw_edges = [item for item in snapshot.get("edges", []) if isinstance(item, dict)]
    if source_quality_policy not in {"SOURCE_BOUND_EXPLICIT_ONLY", "SOURCE_BOUND_WITH_DIAGNOSTICS"}:
        raise ValueError("GraphView source_quality_policy is unsupported")
    if include_derived_inferences and source_quality_policy != "SOURCE_BOUND_WITH_DIAGNOSTICS":
        raise ValueError("Derived inferences require SOURCE_BOUND_WITH_DIAGNOSTICS")
    if not contract_id:
        selected_ids = set(nodes_by_id)
    else:
        # Query only the provenance-directed closure.  An undirected graph
        # traversal would jump through a canonical entity shared by unrelated
        # questions and silently leak the entire corpus into an SH view.
        selected_ids = {contract_id}
        link_ids = {
            str(edge.get("source_id") or "")
            for edge in raw_edges
            if edge.get("edge_type") == "BINDS_TO_RESEARCH_QUESTION"
            and str(edge.get("target_id") or "") == contract_id
        }
        selected_ids.update(link_ids)
        assertion_ids = {
            str(edge.get("target_id") or "")
            for edge in raw_edges
            if edge.get("edge_type") == "USES_ASSERTION" and str(edge.get("source_id") or "") in link_ids
        }
        selected_ids.update(assertion_ids)
        # Iterate to a fixed point so semantic edge ordering cannot silently
        # omit a canonical entity, citation, or document provenance node.
        changed = True
        while changed:
            changed = False
            for edge in raw_edges:
                source_id, target_id = str(edge.get("source_id") or ""), str(edge.get("target_id") or "")
                should_add = False
                if edge.get("edge_type") == "EXPRESSES_ASSERTION" and target_id in assertion_ids:
                    should_add = True
                elif edge.get("edge_type") in {"MENTIONS", "ASSERTS_RELATION", "HAS_SCOPE_VALUE", "CITES"} and source_id in assertion_ids:
                    should_add = True
                elif edge.get("edge_type") == "NORMALIZES_TO" and source_id in selected_ids:
                    should_add = True
                elif edge.get("edge_type") == "CONTAINS_SOURCE_SPAN" and target_id in selected_ids:
                    should_add = True
                elif edge.get("edge_type") == "HAS_VERSION" and target_id in selected_ids:
                    should_add = True
                elif edge.get("edge_type") == "COMPARES_RELATION_ASSERTION" and target_id in selected_ids:
                    should_add = True
                if should_add and source_id not in selected_ids:
                    selected_ids.add(source_id)
                    changed = True
                if should_add and edge.get("edge_type") in {"MENTIONS", "ASSERTS_RELATION", "HAS_SCOPE_VALUE", "NORMALIZES_TO", "CITES"} and target_id not in selected_ids:
                    selected_ids.add(target_id)
                    changed = True
    nodes = [nodes_by_id[item] for item in sorted(selected_ids) if item in nodes_by_id]
    if not include_derived_inferences:
        nodes = [item for item in nodes if item.get("node_type") != "DERIVED_INFERENCE"]
    requested_axes = {_text(item) for item in (required_scope_axes or []) if _text(item)}
    if requested_axes:
        available_axes = {
            _text(item.get("axis"))
            for item in nodes
            if item.get("node_type") == "SCOPE_VALUE" and _text(item.get("axis"))
        }
        missing_axes = sorted(requested_axes - available_axes)
    else:
        missing_axes = []
    allowed_ids = {str(item.get("node_id") or "") for item in nodes}
    edges = [
        item for item in raw_edges
        if isinstance(item, dict) and str(item.get("source_id") or "") in allowed_ids and str(item.get("target_id") or "") in allowed_ids
    ]
    return {
        "schema_version": GRAPH_VIEW_SCHEMA_VERSION,
        "graph_snapshot_ref": graph_snapshot_ref(snapshot),
        "research_question_contract_id": contract_id,
        "gap_type": _text(gap_type),
        "required_scope_axes": sorted(requested_axes),
        "missing_scope_axes": missing_axes,
        "source_quality_policy": source_quality_policy,
        "include_derived_inferences": include_derived_inferences,
        "nodes": nodes,
        "edges": edges,
        "query_policy": "SOURCE_BOUND_ONLY" if not include_derived_inferences else "SOURCE_BOUND_PLUS_DIAGNOSTIC_INFERENCES",
    }


def _require_current_graph_snapshot(snapshot: Any) -> dict[str, Any]:
    """Validate the immutable V3 graph identity needed by detector inputs."""

    if not isinstance(snapshot, dict):
        raise ValueError("Detection context requires a research_evidence_graph_v4 snapshot")
    if _text(snapshot.get("schema_version")) != RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION:
        raise ValueError("Detection context requires research_evidence_graph_v4")
    reference = graph_snapshot_ref(snapshot)
    if (
        not reference["graph_id"]
        or reference["graph_version"] < 1
        or not reference["input_fingerprint"].startswith("sha256:")
    ):
        raise ValueError("Detection context requires a complete immutable V3 graph reference")
    if not _text(snapshot.get("project_id")):
        raise ValueError("Detection context requires a graph project_id")
    return reference


def _validate_graph_view_for_detection(
    snapshot: dict[str, Any],
    view: Any,
) -> dict[str, Any]:
    """Reject a stale, broad, or historical graph view before projection."""

    snapshot_ref = _require_current_graph_snapshot(snapshot)
    if not isinstance(view, dict) or _text(view.get("schema_version")) != GRAPH_VIEW_SCHEMA_VERSION:
        raise ValueError("Detection context requires research_graph_view_v3")
    if view.get("graph_snapshot_ref") != snapshot_ref:
        raise ValueError("Detection graph view is not bound to the current snapshot reference")
    if not _text(view.get("research_question_contract_id")):
        raise ValueError("Detection graph view requires one research_question_contract_id")
    if not isinstance(view.get("nodes"), list) or not isinstance(view.get("edges"), list):
        raise ValueError("Detection graph view requires node and edge lists")
    node_ids = [
        _text(item.get("node_id"))
        for item in view["nodes"]
        if isinstance(item, dict)
    ]
    if not node_ids or len(node_ids) != len(set(node_ids)) or any(not item for item in node_ids):
        raise ValueError("Detection graph view contains invalid node identities")
    return view


def _current_source_assertion_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
    projection = snapshot.get("source_assertion_projection")
    if not isinstance(projection, dict):
        raise ValueError("Detection context requires a source_assertion_projection_v3")
    if _text(projection.get("schema_version")) != SOURCE_ASSERTION_PROJECTION_SCHEMA_VERSION:
        raise ValueError("Detection context rejects historic source assertion projections")
    if not isinstance(projection.get("assertions"), list):
        raise ValueError("source_assertion_projection_v3 requires an assertions list")
    return projection


def _stable_identity_list(values: list[Any] | tuple[Any, ...] | set[Any]) -> list[str]:
    return sorted({_text(value) for value in values if _text(value)})


def _slot_coverage_ledger(
    contract: dict[str, Any],
    assertions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Build a detector-local direct-evidence slot ledger from admitted assertions."""

    evidence_contract = contract.get("evidence_contract") if isinstance(contract.get("evidence_contract"), dict) else {}
    slot_definitions = contract.get("slot_definitions") if isinstance(contract.get("slot_definitions"), dict) else {}
    required_slots = _stable_identity_list(list(evidence_contract.get("required_slots") or []))
    optional_slots = _stable_identity_list(list(evidence_contract.get("optional_slots") or []))
    ledger: dict[str, dict[str, Any]] = {}
    for slot_id in [*required_slots, *[slot for slot in optional_slots if slot not in required_slots]]:
        supporting_assertion_ids: list[str] = []
        supporting_paper_ids: list[str] = []
        for assertion in assertions:
            covered = False
            coverage = assertion.get("slot_coverage") if isinstance(assertion.get("slot_coverage"), dict) else {}
            if coverage.get(slot_id) is True:
                covered = True
            for support in assertion.get("slot_support") or []:
                if not isinstance(support, dict) or _text(support.get("slot_id")) != slot_id:
                    continue
                if (
                    _text(support.get("support_status")) == "VERIFIED_NONCOUNTING"
                    and slot_id in {
                        _text(slot) for slot in assertion.get("admitted_slot_ids_v4") or []
                    }
                ):
                    covered = True
            if covered:
                supporting_assertion_ids.append(_text(assertion.get("assertion_id")))
                supporting_paper_ids.append(_text(assertion.get("paper_id")))
        definition = slot_definitions.get(slot_id) if isinstance(slot_definitions.get(slot_id), dict) else {}
        ledger[slot_id] = {
            "slot_id": slot_id,
            "required": slot_id in required_slots,
            "coverage_status": "SUPPORTED" if supporting_assertion_ids else "MISSING",
            "supporting_assertion_ids": _stable_identity_list(supporting_assertion_ids),
            "supporting_paper_ids": _stable_identity_list(supporting_paper_ids),
            "minimum_evidence": _text(definition.get("minimum_evidence")),
            "admission_rule": _text(definition.get("admission_rule")),
        }
    return ledger


def build_contract_scoped_detection_projection(
    snapshot: dict[str, Any],
    graph_view_payload: dict[str, Any],
) -> dict[str, Any]:
    """Materialize the only evidence projection a V3 gap detector may read.

    The filtering occurs while building the detector input, never after a
    detector has received the global source assertion projection.  It accepts
    current V3 artifacts only and preserves source references instead of text
    bodies, so a historical project field cannot be used as an implicit fill.
    """

    view = _validate_graph_view_for_detection(snapshot, graph_view_payload)
    source_projection = _current_source_assertion_projection(snapshot)
    snapshot_ref = graph_snapshot_ref(snapshot)
    contract_id = _text(view.get("research_question_contract_id"))
    nodes_by_id = {
        _text(item.get("node_id")): item
        for item in view.get("nodes", [])
        if isinstance(item, dict) and _text(item.get("node_id"))
    }
    contract_nodes = [
        node for node in nodes_by_id.values()
        if node.get("node_type") == "RESEARCH_QUESTION_CONTRACT"
        and _text(node.get("node_id")) == contract_id
    ]
    if len(contract_nodes) != 1:
        raise ValueError("Contract-scoped projection requires exactly one current contract node")
    contract = validate_research_question_contract(contract_nodes[0])
    if _text(contract.get("contract_id")) != contract_id or not _text(contract.get("contract_revision")):
        raise ValueError("Contract-scoped projection has an invalid contract identity")

    assertion_nodes = {
        node_id: node for node_id, node in nodes_by_id.items()
        if node.get("node_type") == "EVIDENCE_ASSERTION"
    }
    admitted_assertions: list[dict[str, Any]] = []
    for raw_assertion in source_projection.get("assertions", []):
        if not isinstance(raw_assertion, dict):
            continue
        assertion_id = _text(raw_assertion.get("assertion_id"))
        assertion_contract_id = _text(raw_assertion.get("research_question_contract_id"))
        if assertion_contract_id != contract_id:
            continue
        if not assertion_id or assertion_id not in assertion_nodes:
            raise ValueError("Contract-scoped projection found an admitted assertion outside its graph view")
        graph_assertion = assertion_nodes[assertion_id]
        graph_contract_id = _text(graph_assertion.get("research_question_contract_id"))
        if graph_contract_id and graph_contract_id != contract_id:
            raise ValueError("Contract-scoped projection assertion contract mismatch")
        source_version = _text(raw_assertion.get("document_version_hash"))
        graph_version = _text(graph_assertion.get("document_version_hash"))
        if source_version and graph_version and source_version != graph_version:
            raise ValueError("Contract-scoped projection assertion document version mismatch")
        admitted_assertions.append(_reference_only_value(raw_assertion))
    admitted_assertions.sort(key=lambda item: _text(item.get("assertion_id")))
    assertion_ids = _stable_identity_list([item.get("assertion_id") for item in admitted_assertions])
    assertion_id_set = set(assertion_ids)

    edges = [
        _reference_only_value(item)
        for item in view.get("edges", [])
        if isinstance(item, dict)
        and _text(item.get("source_id")) in nodes_by_id
        and _text(item.get("target_id")) in nodes_by_id
    ]
    edges.sort(key=lambda item: _text(item.get("edge_id")))
    relation_ids_by_assertion: dict[str, list[str]] = {item: [] for item in assertion_ids}
    entity_ids_by_assertion: dict[str, list[str]] = {item: [] for item in assertion_ids}
    scope_ids_by_assertion: dict[str, list[str]] = {item: [] for item in assertion_ids}
    for edge in edges:
        source_id, target_id = _text(edge.get("source_id")), _text(edge.get("target_id"))
        if source_id not in assertion_id_set:
            continue
        if edge.get("edge_type") == "ASSERTS_RELATION":
            relation_ids_by_assertion[source_id].append(target_id)
        elif edge.get("edge_type") == "MENTIONS":
            entity_ids_by_assertion[source_id].append(target_id)
        elif edge.get("edge_type") == "HAS_SCOPE_VALUE":
            scope_ids_by_assertion[source_id].append(target_id)

    relation_index = {
        assertion_id: [
            _reference_only_value(nodes_by_id[node_id])
            for node_id in _stable_identity_list(relation_ids)
            if node_id in nodes_by_id and nodes_by_id[node_id].get("node_type") == "RELATION_ASSERTION"
        ]
        for assertion_id, relation_ids in relation_ids_by_assertion.items()
    }
    entity_index = {
        assertion_id: [
            _reference_only_value(nodes_by_id[node_id])
            for node_id in _stable_identity_list(entity_ids)
            if node_id in nodes_by_id
            and nodes_by_id[node_id].get("node_type") in {"ENTITY_MENTION", "CANONICAL_ENTITY"}
        ]
        for assertion_id, entity_ids in entity_ids_by_assertion.items()
    }
    scope_index = {
        assertion_id: [
            _reference_only_value(nodes_by_id[node_id])
            for node_id in _stable_identity_list(scope_ids)
            if node_id in nodes_by_id and nodes_by_id[node_id].get("node_type") == "SCOPE_VALUE"
        ]
        for assertion_id, scope_ids in scope_ids_by_assertion.items()
    }

    source_units_by_assertion: dict[str, list[dict[str, Any]]] = {}
    for assertion in admitted_assertions:
        assertion_id = _text(assertion.get("assertion_id"))
        span_ids = _stable_identity_list(list(assertion.get("source_span_ids") or []))
        source_units: list[dict[str, Any]] = []
        for span_id in span_ids:
            span = nodes_by_id.get(span_id)
            if not isinstance(span, dict) or span.get("node_type") != "SOURCE_SPAN":
                raise ValueError("Contract-scoped projection assertion has no source-bound span node")
            span_version = _text(span.get("document_version_hash"))
            assertion_version = _text(assertion.get("document_version_hash"))
            if span_version and assertion_version and span_version != assertion_version:
                raise ValueError("Contract-scoped projection source span document version mismatch")
            source_units.append(_reference_only_value(span))
        source_units_by_assertion[assertion_id] = source_units

    relation_ids = {
        _text(item.get("node_id"))
        for rows in relation_index.values() for item in rows if isinstance(item, dict)
    }
    comparability_index: dict[str, dict[str, Any]] = {}
    for node_id, node in nodes_by_id.items():
        if node.get("node_type") != "COMPARABILITY_ASSESSMENT":
            continue
        compared_relation_ids = _stable_identity_list(list(node.get("compared_relation_assertion_ids") or []))
        if compared_relation_ids and not set(compared_relation_ids).intersection(relation_ids):
            continue
        comparability_index[node_id] = _reference_only_value(node)

    diagnostic_inferences: list[dict[str, Any]] = []
    if view.get("include_derived_inferences") is True:
        for raw_inference in source_projection.get("derived_inferences", []):
            if not isinstance(raw_inference, dict):
                continue
            input_ids = _stable_identity_list(
                list(
                    raw_inference.get("derived_from_assertion_ids")
                    or raw_inference.get("source_assertion_ids")
                    or raw_inference.get("input_assertion_ids")
                    or []
                )
            )
            if input_ids and set(input_ids).issubset(assertion_id_set):
                diagnostic_inferences.append(_reference_only_value(raw_inference))
    diagnostic_inferences.sort(key=lambda item: _text(item.get("inference_id")))

    slot_coverage_ledger = _slot_coverage_ledger(contract, admitted_assertions)
    node_refs = [
        _reference_only_value(node)
        for _, node in sorted(nodes_by_id.items())
    ]
    projection = {
        "schema_version": CONTRACT_SCOPED_PROJECTION_SCHEMA_VERSION,
        "policy_revision": DETECTION_CONTEXT_POLICY_REVISION,
        "graph_snapshot_ref": snapshot_ref,
        "research_question_contract_id": contract_id,
        "contract_revision": _text(contract.get("contract_revision")),
        "gap_type": _text(view.get("gap_type")),
        "required_scope_axes": list(view.get("required_scope_axes") or []),
        "missing_scope_axes": list(view.get("missing_scope_axes") or []),
        "source_quality_policy": _text(view.get("source_quality_policy")),
        "assertion_ids": assertion_ids,
        "assertions": admitted_assertions,
        "source_units_by_assertion": source_units_by_assertion,
        "relation_index": relation_index,
        "entity_index": entity_index,
        "scope_index": scope_index,
        "comparability_index": comparability_index,
        "slot_coverage_ledger": slot_coverage_ledger,
        "diagnostic_inferences": diagnostic_inferences,
        "node_refs": node_refs,
        "edge_refs": edges,
    }
    projection["projection_fingerprint"] = _contract_scoped_projection_fingerprint(projection)
    return projection


def _contract_scoped_projection_fingerprint(projection: dict[str, Any]) -> str:
    """Hash the complete detector-visible projection, not only its identifier list."""

    material = {
        str(key): _reference_only_value(value)
        for key, value in projection.items()
        if str(key) != "projection_fingerprint"
    }
    return "sha256:" + _digest(material)


def _detection_context_fingerprint(
    *,
    snapshot_ref: dict[str, Any],
    contract: dict[str, Any],
    projection: dict[str, Any],
    graph_view_payload: dict[str, Any],
) -> str:
    return "sha256:" + _digest(
        {
            "schema_version": DETECTION_CONTEXT_SCHEMA_VERSION,
            "policy_revision": DETECTION_CONTEXT_POLICY_REVISION,
            "graph_snapshot_ref": snapshot_ref,
            "research_question_contract_id": _text(contract.get("contract_id")),
            "contract_revision": _text(contract.get("contract_revision")),
            "projection_fingerprint": _text(projection.get("projection_fingerprint")),
            "gap_type": _text(graph_view_payload.get("gap_type")),
            "required_scope_axes": list(graph_view_payload.get("required_scope_axes") or []),
            "source_quality_policy": _text(graph_view_payload.get("source_quality_policy")),
            "include_derived_inferences": bool(graph_view_payload.get("include_derived_inferences")),
        }
    )


def build_detection_context(
    snapshot: dict[str, Any],
    *,
    research_question_contract_id: str,
    gap_type: str = "",
    required_scope_axes: list[str] | tuple[str, ...] | None = None,
    source_quality_policy: str = "SOURCE_BOUND_EXPLICIT_ONLY",
    include_derived_inferences: bool = False,
) -> DetectionContext:
    """Build a strictly V3, single-contract input for one detector invocation."""

    snapshot_ref = _require_current_graph_snapshot(snapshot)
    view = graph_view(
        snapshot,
        research_question_contract_id=_text(research_question_contract_id),
        gap_type=gap_type,
        required_scope_axes=required_scope_axes,
        source_quality_policy=source_quality_policy,
        include_derived_inferences=include_derived_inferences,
    )
    projection = build_contract_scoped_detection_projection(snapshot, view)
    contract_nodes = [
        item for item in view.get("nodes", [])
        if isinstance(item, dict)
        and item.get("node_type") == "RESEARCH_QUESTION_CONTRACT"
        and _text(item.get("node_id")) == _text(research_question_contract_id)
    ]
    if len(contract_nodes) != 1:
        raise ValueError("Detection context requires exactly one research-question contract node")
    contract = validate_research_question_contract(contract_nodes[0])
    fingerprint = _detection_context_fingerprint(
        snapshot_ref=snapshot_ref,
        contract=contract,
        projection=projection,
        graph_view_payload=view,
    )
    return DetectionContext(
        schema_version=DETECTION_CONTEXT_SCHEMA_VERSION,
        detector_context_fingerprint=fingerprint,
        detector_policy_version=DETECTION_CONTEXT_POLICY_REVISION,
        project_id=_text(snapshot.get("project_id")),
        graph_snapshot_ref=copy.deepcopy(snapshot_ref),
        research_question_contract=copy.deepcopy(contract),
        graph_view=_reference_only_value(view),
        contract_scoped_projection=copy.deepcopy(projection),
        assertions=copy.deepcopy(projection["assertions"]),
        source_units_by_assertion=copy.deepcopy(projection["source_units_by_assertion"]),
        relation_index=copy.deepcopy(projection["relation_index"]),
        entity_index=copy.deepcopy(projection["entity_index"]),
        scope_index=copy.deepcopy(projection["scope_index"]),
        comparability_index=copy.deepcopy(projection["comparability_index"]),
        slot_coverage_ledger=copy.deepcopy(projection["slot_coverage_ledger"]),
    )


def build_contract_detection_contexts_v3(
    snapshot: dict[str, Any],
    *,
    source_quality_policy: str = "SOURCE_BOUND_EXPLICIT_ONLY",
) -> dict[str, DetectionContext]:
    """Build one fully validated V3 detection context per RQC contract.

    Detector type is deliberately not part of a contract's evidence view.  A
    detector carries its own type and policy in its result fingerprint, while
    the immutable context describes only the current graph, contract, and
    admitted source-bound assertions.  This avoids rebuilding the same graph
    closure for every detector without widening a detector's input scope.
    """

    _require_current_graph_snapshot(snapshot)
    contract_nodes = sorted(
        (
            item
            for item in snapshot.get("nodes", [])
            if isinstance(item, dict)
            and item.get("node_type") == "RESEARCH_QUESTION_CONTRACT"
            and _text(item.get("node_id"))
        ),
        key=lambda item: _text(item.get("node_id")),
    )
    contexts: dict[str, DetectionContext] = {}
    for contract_node in contract_nodes:
        contract = validate_research_question_contract(contract_node)
        contract_id = _text(contract.get("contract_id"))
        context = build_detection_context(
            snapshot,
            research_question_contract_id=contract_id,
            required_scope_axes=list(
                (contract.get("evidence_contract") or {}).get(
                    "required_comparability_axes", []
                )
            ),
            source_quality_policy=source_quality_policy,
        )
        contexts[contract_id] = validate_detection_context(context)
    return contexts


def detection_context_ref(context: DetectionContext) -> dict[str, Any]:
    """Return the durable, text-free reference that detector results must carry."""

    validated = _validated_detection_context_for_runtime(context)
    projection = validated.contract_scoped_projection
    return {
        "schema_version": DETECTION_CONTEXT_SCHEMA_VERSION,
        "detector_context_fingerprint": validated.detector_context_fingerprint,
        "detector_policy_version": validated.detector_policy_version,
        "graph_snapshot_ref": copy.deepcopy(validated.graph_snapshot_ref),
        "research_question_contract_id": _text(validated.research_question_contract.get("contract_id")),
        "contract_revision": _text(validated.research_question_contract.get("contract_revision")),
        "contract_scoped_projection_fingerprint": _text(projection.get("projection_fingerprint")),
    }


def _validated_detection_context_for_runtime(context: Any) -> DetectionContext:
    """Use the active detector-call seal or perform a complete V3 validation.

    The seal exists only inside :func:`detection_context_validation_scope`.
    It cannot validate a mapping, an old schema, or a context from another
    invocation; callers outside that narrow execution scope always execute
    the complete integrity check below.
    """

    if isinstance(context, DetectionContext) and _context_is_active_for_runtime(context):
        return context
    return validate_detection_context(context)


def _detection_context_runtime_key(
    context: DetectionContext,
) -> tuple[int, str, str]:
    return (
        id(context),
        _text(context.detector_context_fingerprint),
        _text((context.contract_scoped_projection or {}).get("projection_fingerprint")),
    )


def _context_is_active_for_runtime(context: DetectionContext) -> bool:
    active = _ACTIVE_VALIDATED_DETECTION_CONTEXT.get()
    key = _detection_context_runtime_key(context)
    return active == key or (isinstance(active, frozenset) and key in active)


@contextmanager
def _prevalidated_detection_contexts_scope(
    contexts: list[DetectionContext] | tuple[DetectionContext, ...],
):
    """Expose contexts already validated at an internal run boundary.

    This private scope is only for an immediate registry execution after
    ``build_contract_detection_contexts_v3`` or a worker's first strong
    validation.  It does not alter the public validator: standalone calls
    still recompute the complete V3 integrity boundary.
    """

    keys = frozenset(
        _detection_context_runtime_key(context)
        for context in contexts
        if isinstance(context, DetectionContext)
    )
    token = _ACTIVE_VALIDATED_DETECTION_CONTEXT.set(keys)
    try:
        yield
    finally:
        _ACTIVE_VALIDATED_DETECTION_CONTEXT.reset(token)


@contextmanager
def detection_context_validation_scope(context: DetectionContext):
    """Perform one strong validation for a detector invocation.

    Candidate construction can then perform bounded identity lookups against
    the exact same in-memory context.  The public validator remains strict
    outside this lexical scope, so persisted or externally supplied contexts
    never receive an implicit trust upgrade.
    """

    validated = (
        context
        if isinstance(context, DetectionContext)
        and _context_is_active_for_runtime(context)
        else validate_detection_context(context)
    )
    token = _ACTIVE_VALIDATED_DETECTION_CONTEXT.set(
        _detection_context_runtime_key(validated)
    )
    try:
        yield validated
    finally:
        _ACTIVE_VALIDATED_DETECTION_CONTEXT.reset(token)


def validate_detection_context(context: Any) -> DetectionContext:
    """Validate a current context without adapting dicts or historic artifacts."""

    if not isinstance(context, DetectionContext):
        raise ValueError("Gap detectors require DetectionContext; historical context mappings are rejected")
    if context.schema_version != DETECTION_CONTEXT_SCHEMA_VERSION:
        raise ValueError("Gap detectors require gap_detection_context_v3")
    if context.detector_policy_version != DETECTION_CONTEXT_POLICY_REVISION:
        raise ValueError("Gap detection context has an unsupported policy revision")
    if not _text(context.project_id):
        raise ValueError("Gap detection context requires a project_id")
    snapshot_ref = context.graph_snapshot_ref
    if (
        not isinstance(snapshot_ref, dict)
        or _text(snapshot_ref.get("schema_version")) != RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION
        or not _text(snapshot_ref.get("input_fingerprint")).startswith("sha256:")
    ):
        raise ValueError("Gap detection context has an invalid V3 graph reference")
    contract = validate_research_question_contract(context.research_question_contract)
    projection = context.contract_scoped_projection
    if not isinstance(projection, dict) or projection.get("schema_version") != CONTRACT_SCOPED_PROJECTION_SCHEMA_VERSION:
        raise ValueError("Gap detection context has no current contract-scoped projection")
    if projection.get("graph_snapshot_ref") != snapshot_ref:
        raise ValueError("Gap detection context projection snapshot mismatch")
    if _text(projection.get("research_question_contract_id")) != _text(contract.get("contract_id")):
        raise ValueError("Gap detection context projection contract mismatch")
    if _text(projection.get("contract_revision")) != _text(contract.get("contract_revision")):
        raise ValueError("Gap detection context projection revision mismatch")
    if not _text(projection.get("projection_fingerprint")).startswith("sha256:"):
        raise ValueError("Gap detection context projection fingerprint is invalid")
    if projection.get("projection_fingerprint") != _contract_scoped_projection_fingerprint(projection):
        raise ValueError("Gap detection context projection content does not match its fingerprint")
    view = context.graph_view
    if not isinstance(view, dict) or view.get("schema_version") != GRAPH_VIEW_SCHEMA_VERSION:
        raise ValueError("Gap detection context graph view is invalid")
    view_node_refs = [
        _reference_only_value(item)
        for item in sorted(
            (item for item in view.get("nodes", []) if isinstance(item, dict)),
            key=lambda item: _text(item.get("node_id")),
        )
    ]
    view_edge_refs = [
        _reference_only_value(item)
        for item in sorted(
            (item for item in view.get("edges", []) if isinstance(item, dict)),
            key=lambda item: _text(item.get("edge_id")),
        )
    ]
    if view_node_refs != projection.get("node_refs") or view_edge_refs != projection.get("edge_refs"):
        raise ValueError("Gap detection context graph view is not the contract-scoped projection view")
    for field_name in (
        "assertions",
        "source_units_by_assertion",
        "relation_index",
        "entity_index",
        "scope_index",
        "comparability_index",
        "slot_coverage_ledger",
    ):
        if getattr(context, field_name) != projection.get(field_name):
            raise ValueError(f"Gap detection context {field_name} diverges from its projection")
    expected = _detection_context_fingerprint(
        snapshot_ref=snapshot_ref,
        contract=contract,
        projection=projection,
        graph_view_payload=view,
    )
    if context.detector_context_fingerprint != expected:
        raise ValueError("Gap detection context fingerprint does not match its bound inputs")
    return context


def _detector_identity(value: Any, *, field_name: str) -> str:
    identity = _text(value)
    if not identity:
        raise ValueError(f"{field_name} requires a non-empty stable identifier")
    return identity


def detector_input_fingerprint(
    context: DetectionContext,
    *,
    detector_id: str,
    detector_policy_version: str,
) -> str:
    """Fingerprint a detector's exact V3 input boundary and implementation policy."""

    validated = _validated_detection_context_for_runtime(context)
    return "sha256:" + _digest(
        {
            "schema_version": DETECTOR_RESULT_SCHEMA_VERSION,
            "kind": "detector_input",
            "detection_context": detection_context_ref(validated),
            "detector_id": _detector_identity(detector_id, field_name="detector_id"),
            "detector_policy_version": _detector_identity(
                detector_policy_version,
                field_name="detector_policy_version",
            ),
        }
    )


def detector_result_fingerprint(
    context: DetectionContext,
    *,
    detector_id: str,
    detector_policy_version: str,
    candidate_identities: list[str] | tuple[str, ...] = (),
    rejected_pattern_ids: list[str] | tuple[str, ...] = (),
    diagnostic_ids: list[str] | tuple[str, ...] = (),
) -> str:
    """Fingerprint a detector result without admitting an unbound legacy result."""

    input_fingerprint = detector_input_fingerprint(
        context,
        detector_id=detector_id,
        detector_policy_version=detector_policy_version,
    )
    return "sha256:" + _digest(
        {
            "schema_version": DETECTOR_RESULT_SCHEMA_VERSION,
            "detector_input_fingerprint": input_fingerprint,
            "candidate_identities": _stable_identity_list(list(candidate_identities)),
            "rejected_pattern_ids": _stable_identity_list(list(rejected_pattern_ids)),
            "diagnostic_ids": _stable_identity_list(list(diagnostic_ids)),
        }
    )


def get_research_graph_view(
    project_id: str,
    *,
    research_question_contract_id: str = "",
    gap_type: str = "",
    required_scope_axes: list[str] | tuple[str, ...] | None = None,
    include_derived_inferences: bool = False,
) -> dict[str, Any]:
    """Load a persisted V3 snapshot and expose a safe UI/report projection."""
    try:
        from ._project import science_state_manager
    except ImportError:
        from _project import science_state_manager
    snapshot = science_state_manager().get_active_research_evidence_graph(project_id)
    if not isinstance(snapshot, dict):
        raise ValueError("DETACHED_RESEARCH_EVIDENCE_GRAPH_REQUIRED")
    return graph_view(
        snapshot,
        research_question_contract_id=research_question_contract_id,
        gap_type=gap_type,
        required_scope_axes=required_scope_axes,
        source_quality_policy=(
            "SOURCE_BOUND_WITH_DIAGNOSTICS"
            if include_derived_inferences
            else "SOURCE_BOUND_EXPLICIT_ONLY"
        ),
        include_derived_inferences=include_derived_inferences,
    )


def build_and_persist_research_evidence_graph(project_id: str) -> dict[str, Any]:
    """Reject direct graph construction outside the V3 GroupChat TanXi stage."""
    raise ValueError(
        "BLOCKED_V3_GROUPCHAT_ONLY: Research Evidence Graph V3 is built by TanXi "
        "from the persisted V3 evidence ledger; direct full-project graph construction is disabled."
    )
