"""Span-grounded semantic adjudication for domain-neutral gap candidates.

Candidate detectors are intentionally permissive.  This module is the first
strict gate: it checks whether the supplied source spans actually support the
candidate's relation, scope, and type-specific claims.  An optional LLM is an
auditor over bounded evidence, never a source of uncited scientific facts.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol
import json
import re

try:
    from ._gap_types import (
        CandidateStage,
        EvidenceMaturity,
        GapLifecyclePhase,
        GapRoute,
        GapType,
        ScopeStatus,
        SemanticVerdict,
        assessment_of,
        contract_for,
        missing_payload_fields,
        payload_of,
        synchronize_candidate_surface,
    )
except ImportError:
    from _gap_types import (
        CandidateStage,
        EvidenceMaturity,
        GapLifecyclePhase,
        GapRoute,
        GapType,
        ScopeStatus,
        SemanticVerdict,
        assessment_of,
        contract_for,
        missing_payload_fields,
        payload_of,
        synchronize_candidate_surface,
    )


class GapSemanticAuditor(Protocol):
    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        ...


class GapSemanticAuditInvocationError(RuntimeError):
    """A configured LLM semantic auditor could not produce an audit response.

    This deliberately represents only the external LLM invocation boundary.
    It must not be used for TanXi configuration, graph, checkpoint, or function
    interface failures: those are workflow failures and must remain visible to
    the caller instead of triggering a deterministic audit retry.
    """

    def __init__(self, *, role: str, cause: Exception) -> None:
        self.role = str(role or "positive")
        self.cause_type = type(cause).__name__
        self.cause_message = str(cause)
        super().__init__(
            f"LLM semantic audit invocation failed for {self.role}: "
            f"{self.cause_type}: {self.cause_message}"
        )


_CAUSAL_FAILURE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "PARALLEL_EFFECT_NOT_MEDIATION",
        re.compile(
            r"\b(?:affects?|modifies?|changes?|influences?)\b[^.;]{0,160}"
            r"\b(?:and|as well as)\b",
            re.IGNORECASE,
        ),
    ),
    ("CONTEXT_CONTRAST_NOT_PATH", re.compile(r"\b(?:while|whereas|in contrast)\b", re.IGNORECASE)),
    ("PRECEDENCE_NOT_CAUSATION", re.compile(r"\b(?:precedes?|before|after|subsequent(?:ly)?)\b", re.IGNORECASE)),
)


# The LLM sees one type-specific audit brief, never a generic "is this a
# research gap?" question.  The deterministic rule layer remains the final
# adjudicator and these questions cannot grant a primary route by themselves.
_TYPE_SPECIFIC_AUDIT_QUESTIONS: dict[GapType, tuple[str, ...]] = {
    GapType.EMPIRICAL_COVERAGE: (
        "Does each supplied span establish the declared phenomenon, object, and condition?",
        "Does the evidence establish a coverage gap rather than merely one paper's omission?",
    ),
    GapType.AUTHOR_STATED_LIMITATION: (
        "Does the exact limitation span state an unresolved item rather than generic future work?",
        "Does it identify the affected claim, object, method, or stated scope?",
    ),
    GapType.CAUSAL_IDENTIFICATION: (
        "Classify every asserted edge as causal, correlational, temporal, parallel, contrastive, model-derived, or unsupported.",
        "Are input, mediator, and outcome semantically distinct, context-compatible, and supported by independent spans where mediation is claimed?",
        "Is there a stated alternative explanation and an identification design that could distinguish it?",
    ),
    GapType.MECHANISM_COMPETITION: (
        "Do at least two source-supported mechanisms share a comparable input and endpoint?",
        "Is a discriminating prediction, intervention, or joint measurement actually specified?",
    ),
    GapType.BOUNDARY_HETEROGENEITY: (
        "Are the compared results about the same relation under distinct, named conditions rather than incomparable measurements?",
        "Can a boundary variable, threshold, interaction, or stratified test be grounded in the supplied spans?",
    ),
    GapType.CONTRADICTION_REPLICATION: (
        "Are there independent, comparable sources with genuinely conflicting result directions, magnitudes, or reproducibility outcomes?",
        "Would a known boundary variable fully explain the difference, in which case this must be a boundary rather than contradiction gap?",
    ),
    GapType.MEASUREMENT_OPERATIONALIZATION: (
        "Are construct, proxy, and target endpoint distinct and explicitly named?",
        "Do the spans establish missing validity, calibration, reliability, comparability, or an error model rather than merely use of a model output?",
    ),
    GapType.THEORY_MATHEMATICAL: (
        "Is there a formal claim/model/theorem, its assumptions, and known validity domain?",
        "Is the unresolved item a proof, counterexample, identifiability, equivalence, or assumption test rather than an untried application?",
    ),
    GapType.GENERALIZATION_TRANSPORTABILITY: (
        "Are source and target domains and the kind of distributional/structural shift explicit?",
        "Do the spans distinguish missing external validation from an unsupported generalization claim?",
    ),
    GapType.METHOD_DESIGN: (
        "Is a specific failure mode or bias grounded in a current method and is an alternative design evaluable?",
    ),
    GapType.DATA_COVERAGE: (
        "Is the missing variable, population/system, regime, or time horizon necessary for the stated claim and is an acquisition path feasible?",
    ),
    GapType.SCALE_INTEGRATION: (
        "Are source and target scales, a bridge variable, and a falsifiable coupling question explicit?",
    ),
    GapType.BENCHMARK_COMPARISON: (
        "Are the compared systems defined and is the missing common task, metric, or protocol necessary for a fair comparison?",
    ),
    GapType.TRANSLATION_IMPLEMENTATION: (
        "Is a validated claim separated from its deployment context, implementation barrier, and real-world feasibility question?",
    ),
}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normal(value: Any) -> str:
    """Normalise a supplied phrase for exact-with-whitespace source checks."""
    return re.sub(r"\s+", " ", _text(value)).casefold()


def normalize_semantic_confidence(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    raw = _text(value).strip().lower()
    if not raw:
        return 0.0
    labels = {
        "very_low": 0.15,
        "low": 0.3,
        "medium": 0.55,
        "moderate": 0.55,
        "high": 0.8,
        "very_high": 0.95,
    }
    normalized_label = re.sub(r"[\s-]+", "_", raw)
    if normalized_label in labels:
        return labels[normalized_label]
    try:
        numeric = float(raw.rstrip("%"))
    except (TypeError, ValueError):
        return 0.0
    if raw.endswith("%") or numeric > 1.0:
        numeric /= 100.0
    return max(0.0, min(1.0, numeric))


def _tokens(value: Any) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]*|[\u4e00-\u9fff]+", _text(value))
        if len(token) > 1
    }


def _nonempty(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, (list, tuple, set)):
        return any(_nonempty(item) for item in value)
    return bool(_text(value))


def _source_units(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in candidate.get("source_evidence_units", []) if isinstance(item, dict)]


def _source_spans(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    # The v2 candidate must carry its own explicitly bound source units.  Do
    # not augment them with historic graph edges, even if such fields survive
    # in a dirty project record: that would reintroduce the prohibited
    # causal-edge fallback described by the v2 cutover contract.
    spans = list(_source_units(candidate))
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for span in spans:
        key = (_text(span.get("source_unit_id")), _text(span.get("excerpt_hash")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(span)
    return deduped


def _scope_status(project: dict[str, Any], candidate: dict[str, Any]) -> str:
    """Classify only from the current v3 span/assertion admission record.

    A missing ``gap_source_admission_v3`` record is intentionally background:
    old project flags, lexical scope matches, causal-edge alignment, and
    inferred directness are not migration paths into a primary route.
    """
    paper_ids = {_text(item.get("paper_id")) for item in _source_spans(candidate) if _text(item.get("paper_id"))}
    question_contract = candidate.get("research_question_contract") if isinstance(candidate.get("research_question_contract"), dict) else {}
    contract_id = _text(question_contract.get("contract_id"))
    candidate_graph_contract = candidate.get("evidence_graph_contract") if isinstance(candidate.get("evidence_graph_contract"), dict) else {}
    expected_revision = _text(candidate_graph_contract.get("research_question_contract_revision"))
    expected_document_versions = {
        _text(item.get("document_version_hash"))
        for item in _source_spans(candidate)
        if _text(item.get("document_version_hash"))
    }
    records = [
        item
        for collection in (project.get("papergraph"), project.get("evidence"))
        if isinstance(collection, list)
        for item in collection
        if isinstance(item, dict) and _text(item.get("paper_id")) in paper_ids
    ]
    admissions = []
    for item in records:
        projection = item.get("evidence_projection_v4") if isinstance(item.get("evidence_projection_v4"), dict) else {}
        if projection.get("schema_version") != "evidence_projection_v4" or projection.get("status") != "CURRENT":
            continue
        if expected_document_versions and _text(projection.get("document_version_hash")) not in expected_document_versions:
            continue
        revisions = projection.get("research_question_contract_revisions") if isinstance(projection.get("research_question_contract_revisions"), dict) else {}
        if expected_revision and _text(revisions.get(contract_id)) != expected_revision:
            continue
        by_contract = item.get("gap_source_admissions_v4") if isinstance(item.get("gap_source_admissions_v4"), dict) else {}
        admission = by_contract.get(contract_id) if contract_id else None
        if not isinstance(admission, dict):
            continue
        if admission.get("schema_version") == "gap_source_admission_v4":
            admissions.append(admission)
    if not admissions:
        return ScopeStatus.BACKGROUND.value
    levels = {_text(item.get("admission_level")).upper() for item in admissions}
    if "DIRECT_EVIDENCE" in levels:
        return ScopeStatus.CORE.value
    if "HARD_REJECT" in levels:
        return ScopeStatus.OUT_OF_SCOPE.value
    return ScopeStatus.BACKGROUND.value


def build_semantic_audit_request(project: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Build the evidence-bounded request shared by positive and red-team auditors."""
    assessment = assessment_of(candidate)
    payload = payload_of(candidate)
    contract = contract_for(assessment["gap_type"])
    spans = [
        {
            "paper_id": _text(item.get("paper_id")),
            "document_version_hash": _text(item.get("document_version_hash")),
            "source_unit_id": _text(item.get("source_unit_id")),
            "excerpt_hash": _text(item.get("excerpt_hash")),
            "excerpt": _text(item.get("excerpt"))[:4000],
            "conditions": dict(item.get("conditions") or {}),
            "source_role": _text(item.get("evidence_role")),
        }
        for item in _source_spans(candidate)
    ]
    return {
        "schema_version": "gap_semantic_audit_request_v3",
        "project_scope": {
            "objective": _text(project.get("objective") or project.get("research_question")),
            "scientific_object": _text(project.get("scientific_object")),
        },
        "candidate": {
            "gap_id": _text(candidate.get("gap_id")),
            "candidate_identity": _text(candidate.get("candidate_identity")),
            "gap_type": assessment["gap_type"],
            "gap_subtype": assessment.get("gap_subtype", ""),
            "description": _text(candidate.get("description")),
            "research_question": dict(candidate.get("research_question") or {}),
            "type_payload": payload,
        },
        "required_semantic_checks": list(contract.required_semantic_checks),
        "type_specific_audit_questions": list(_TYPE_SPECIFIC_AUDIT_QUESTIONS[GapType(assessment["gap_type"])]),
        "source_spans": spans,
        "response_contract": {
            "verdicts": [item.value for item in SemanticVerdict],
            "required_fields": [
                "semantic_verdict",
                "confidence",
                "checks",
                "failure_codes",
                "supporting_source_unit_ids",
                "field_support",
                "reason",
            ],
            "field_support_item": {
                "source_unit_id": "one supplied source id",
                "document_version_hash": "the supplied current document version hash for that source id",
                "excerpt_hash": "the supplied excerpt hash for that source id",
                "supporting_phrase": "short exact phrase from that supplied excerpt",
                "phrase_char_start": "zero-based start offset in supplied excerpt",
                "phrase_char_end": "exclusive end offset in supplied excerpt",
                "supported_field": "payload field or semantic check supported by the phrase",
            },
            "confidence": "numeric value from 0 to 1; do not use qualitative labels",
            "rule": "Every positive check must cite supplied source_unit_id + document_version_hash + excerpt_hash + supporting_phrase + supported_field; do not use external knowledge.",
        },
    }


def llm_gap_semantic_auditor(request: dict[str, Any], *, role: str = "positive") -> dict[str, Any]:
    """Call the configured LLM as a constrained JSON auditor.

    The caller chooses when external model use is authorized.  This function
    never performs retrieval and the prompt explicitly prevents the model from
    filling missing scientific facts from its parameters.
    """
    try:
        from ._llm import call_llm_json
    except ImportError:
        from _llm import call_llm_json
    instruction = (
        "You are a source-span semantic auditor. Judge only the supplied evidence. "
        "Do not use external knowledge, do not infer an unquoted causal relation, and do not invent citations. "
        "Return one JSON object."
    )
    if role == "red_team":
        instruction += (
            " Act as a red team: identify parallel effects, temporal-only statements, condition contrasts, "
            "definition/rephrasing, co-reference gaps, scope mismatch, and evidence that does not entail the candidate."
        )
    try:
        return call_llm_json(
            system=instruction,
            prompt=(
                "Audit this candidate against its source spans and answer every type_specific_audit_question. "
                "Every passing check must include field_support items with source_unit_id, excerpt_hash, exact supporting_phrase, and supported_field. "
                "Set semantic_verdict to ENTAILED only when all required checks are explicitly supported.\n\n"
                "INPUT_JSON:\n"
                + json.dumps(request, ensure_ascii=False, sort_keys=True)
            ),
            max_tokens=1800,
        )
    except Exception as exc:
        raise GapSemanticAuditInvocationError(role=role, cause=exc) from exc


def _deterministic_audit(project: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    assessment = assessment_of(candidate)
    payload = payload_of(candidate)
    contract = contract_for(assessment["gap_type"])
    spans = _source_spans(candidate)
    source_ids = [_text(item.get("source_unit_id")) for item in spans if _text(item.get("source_unit_id"))]
    unique_span_ids = {(item.get("source_unit_id"), item.get("excerpt_hash")) for item in spans}
    checks: dict[str, bool] = {key: False for key in contract.required_semantic_checks}
    failures: list[str] = []
    text = " ".join(_text(item.get("excerpt")) for item in spans)
    # Discovery payload is the semantic audit's hard input boundary.  Fields
    # reserved for semantic enrichment or primary qualification must be
    # recorded as retrieval work, not used to erase a source-bound lead.
    missing_payload = missing_payload_fields(
        candidate,
        lifecycle_phase=GapLifecyclePhase.DISCOVERY,
    )
    semantic_payload_deficits = missing_payload_fields(
        candidate,
        lifecycle_phase=GapLifecyclePhase.SEMANTIC_AUDIT,
    )
    if missing_payload:
        failures.extend(f"MISSING_DISCOVERY_PAYLOAD:{field}" for field in missing_payload)
    if not spans:
        failures.append("SOURCE_SPANS_MISSING")
    scope = _scope_status(project, candidate)
    if scope == ScopeStatus.OUT_OF_SCOPE.value:
        failures.append("OUT_OF_SCOPE_SOURCE")

    provenance = (
        candidate.get("detection_provenance")
        if isinstance(candidate.get("detection_provenance"), dict)
        else {}
    )
    witness = provenance.get("witness") if isinstance(provenance.get("witness"), dict) else {}
    pattern_id = _text(provenance.get("pattern_id"))
    gap_type = GapType(assessment["gap_type"])
    if gap_type == GapType.CAUSAL_IDENTIFICATION:
        roles = [payload.get(key) for key in ("input", "mediator", "outcome") if _text(payload.get(key))]
        role_sets = [_tokens(value) for value in roles]
        distinct = len(role_sets) >= 2 and all(
            not (left <= right or right <= left)
            for index, left in enumerate(role_sets)
            for right in role_sets[index + 1 :]
        )
        checks["roles_distinct"] = distinct
        if not distinct:
            failures.append("SELF_REFERENTIAL_OR_REPHRASED_ROLE")
        if len(unique_span_ids) < 2 and _text(payload.get("mediator")):
            failures.append("SAME_SOURCE_SPAN_PATH")
        for failure, pattern in _CAUSAL_FAILURE_PATTERNS:
            if pattern.search(text):
                failures.append(failure)
        known_relations = payload.get("known_relations") if isinstance(payload.get("known_relations"), list) else []
        if assessment.get("gap_subtype") == "MEDIATION_UNRESOLVED" and len(known_relations) < 2:
            failures.append("MEDIATION_RELATIONS_NOT_EXPLICIT")
        checks["relations_entailed"] = bool(spans) and bool(known_relations) and not any(
            item in failures
            for item in (
                "SAME_SOURCE_SPAN_PATH",
                "PARALLEL_EFFECT_NOT_MEDIATION",
                "CONTEXT_CONTRAST_NOT_PATH",
                "PRECEDENCE_NOT_CAUSATION",
            )
        )
        checks["no_parallel_effect_interpretation"] = "PARALLEL_EFFECT_NOT_MEDIATION" not in failures
        checks["context_aligned"] = "CONTEXT_CONTRAST_NOT_PATH" not in failures
        checks["alternative_explanation_declared"] = bool(
            payload.get("alternative_explanations")
            or pattern_id == "ASSOCIATION_WITHOUT_IDENTIFICATION_DESIGN"
        )
        compatibility = candidate.get("compatibility") if isinstance(candidate.get("compatibility"), dict) else {}
        temporal_support = compatibility.get("temporal_support")
        checks["temporal_order_supported"] = bool(
            isinstance(temporal_support, dict)
            and str(temporal_support.get("status") or "").upper() == "SUPPORTED"
        ) or pattern_id == "ASSOCIATION_WITHOUT_IDENTIFICATION_DESIGN"
        # This check asks whether the *identification deficiency* is grounded;
        # an actual design is a primary-qualification requirement and cannot
        # be manufactured during semantic audit.
        checks["identification_design_available"] = bool(
            payload.get("identification_design")
            or payload.get("falsification_plan")
            or pattern_id == "ASSOCIATION_WITHOUT_IDENTIFICATION_DESIGN"
        )
    elif gap_type == GapType.EMPIRICAL_COVERAGE:
        checks["scope_aligned"] = scope != ScopeStatus.OUT_OF_SCOPE.value
        checks["direct_evidence_coverage_assessed"] = bool(
            spans
            and _text(payload.get("phenomenon"))
            and _text(payload.get("target_object"))
            and _text(payload.get("target_condition"))
            and _text(payload.get("coverage_dimension_missing"))
            and pattern_id == "DECLARED_SCOPE_WITH_MISSING_DIRECT_COVERAGE_DIMENSION"
        )
    elif gap_type == GapType.AUTHOR_STATED_LIMITATION:
        checks["limitation_entails_unknown"] = bool(spans and payload.get("author_stated_unknown"))
        if re.search(r"\bfuture work\b", _text(payload.get("author_stated_unknown")), re.IGNORECASE) and not _text(payload.get("affected_claim")):
            failures.append("GENERIC_FUTURE_WORK_NOT_LIMITATION")
        checks["scope_aligned"] = scope != ScopeStatus.OUT_OF_SCOPE.value
    elif gap_type == GapType.MECHANISM_COMPETITION:
        mechanisms = payload.get("candidate_mechanisms")
        checks["competing_paths_entailed"] = bool(spans and isinstance(mechanisms, (list, tuple, set)) and len(mechanisms) >= 2)
        checks["endpoint_comparable"] = bool(_text(payload.get("common_input")) and _text(payload.get("common_outcome")))
        # A competition candidate is semantically grounded when the two paths
        # and their missing discriminator are explicit.  The discriminator
        # itself belongs to the later design-ready package.
        checks["discriminator_available"] = bool(
            _nonempty(payload.get("discriminating_prediction"))
            or pattern_id == "TWO_DISTINCT_MECHANISM_PATHS_WITH_COMMON_ENDPOINT"
        )
    elif gap_type == GapType.CONTRADICTION_REPLICATION:
        source_count = len({_text(item.get("paper_id")) for item in spans if _text(item.get("paper_id"))})
        checks["independent_sources"] = source_count >= 2
        evidence_sets = payload.get("evidence_sets") if isinstance(payload.get("evidence_sets"), list) else []
        directions = {_text(item.get("result_direction")).upper() for item in evidence_sets if isinstance(item, dict)}
        checks["results_conflict"] = len(directions - {"", "UNSPECIFIED"}) >= 2
        checks["comparison_entailed"] = bool(spans)
    elif gap_type == GapType.BOUNDARY_HETEROGENEITY:
        checks["comparison_entailed"] = bool(spans)
        checks["conditions_distinct"] = bool(
            _text(payload.get("condition_a"))
            and _text(payload.get("condition_b"))
            and _text(payload.get("condition_a")) != _text(payload.get("condition_b"))
            and _text(payload.get("boundary_variable"))
        )
        checks["measurement_comparable"] = bool(payload.get("measurement_definition") or payload.get("base_relation"))
    elif gap_type == GapType.MEASUREMENT_OPERATIONALIZATION:
        checks["proxy_identified"] = bool(_text(payload.get("proxy_measure")))
        checks["target_identified"] = bool(_text(payload.get("target_measure")))
        checks["mapping_not_validated"] = bool(
            (
                _text(payload.get("validation_missing"))
                and _text(payload.get("mapping_status")).upper() in {"UNVALIDATED", "UNKNOWN", "PARTIAL"}
            )
            or pattern_id == "SOURCE_EXPLICIT_PROXY_TARGET_MAPPING_WITHOUT_VALIDATION"
        )
    elif gap_type == GapType.THEORY_MATHEMATICAL:
        checks["formal_statement_present"] = bool(_text(payload.get("formal_claim")))
        checks["assumptions_extracted"] = _nonempty(payload.get("assumptions"))
        checks["falsification_path_available"] = bool(
            _text(payload.get("counterexample_status"))
            or _text(payload.get("validation_path"))
            or pattern_id == "FORMAL_CLAIM_WITH_EXPLICIT_UNRESOLVED_CONDITION"
        )
    elif gap_type == GapType.GENERALIZATION_TRANSPORTABILITY:
        checks["source_domain_evidence"] = bool(spans and _text(payload.get("source_domain")) and _text(payload.get("model_or_claim")))
        checks["target_domain_defined"] = bool(_text(payload.get("target_domain")))
        checks["shift_defined"] = bool(
            _text(payload.get("shift_type"))
            and _text(payload.get("external_validation_status")).upper() in {"MISSING", "FAILED", "UNCERTAIN", "PARTIAL"}
        ) or pattern_id == "DECLARED_SOURCE_TARGET_SHIFT_WITHOUT_EXTERNAL_VALIDATION"
    elif gap_type == GapType.METHOD_DESIGN:
        checks["failure_mode_entailed"] = bool(
            spans and _text(payload.get("current_method")) and _text(payload.get("failure_mode"))
            and _text(payload.get("bias_or_identification_problem"))
        )
        checks["alternative_design_specified"] = bool(
            _text(payload.get("alternative_design")) and _text(payload.get("evaluation_criterion"))
        ) or pattern_id == "SOURCE_BOUND_METHOD_FAILURE_WITH_CLAIM_IMPACT"
    elif gap_type == GapType.DATA_COVERAGE:
        checks["coverage_measured"] = bool(
            spans
            and pattern_id == "QUANTIFIED_MISSING_DATA_DIMENSION_WITH_CLAIM_IMPACT"
        )
        checks["impact_entailed"] = bool(_text(payload.get("impact_on_claim")))
        checks["acquisition_feasible"] = bool(
            _text(payload.get("acquisition_path"))
            or pattern_id == "QUANTIFIED_MISSING_DATA_DIMENSION_WITH_CLAIM_IMPACT"
        )
    elif gap_type == GapType.SCALE_INTEGRATION:
        checks["scales_defined"] = bool(_text(payload.get("source_scale")) and _text(payload.get("target_scale")))
        checks["bridge_variable_defined"] = bool(
            _text(payload.get("bridge_variable"))
            or pattern_id == "TWO_SCALES_WITH_EXPLICIT_UNRESOLVED_BRIDGE"
        )
        checks["coupling_test_available"] = bool(_text(payload.get("coupling_question")))
    elif gap_type == GapType.BENCHMARK_COMPARISON:
        systems = payload.get("candidate_systems")
        checks["comparison_need_entailed"] = bool(spans and _text(payload.get("comparison_target")) and _text(payload.get("common_task_missing")))
        checks["systems_defined"] = bool(isinstance(systems, (list, tuple, set)) and len(systems) >= 2)
        checks["metric_need_defined"] = bool(
            _text(payload.get("shared_metric_missing")) and _text(payload.get("protocol_missing"))
        ) or pattern_id == "DEFINED_SYSTEMS_WITH_SOURCE_DECLARED_SHARED_EVALUATION_GAP"
    elif gap_type == GapType.TRANSLATION_IMPLEMENTATION:
        checks["validated_claim_entailed"] = bool(spans and _text(payload.get("validated_claim")))
        checks["deployment_context_defined"] = bool(_text(payload.get("deployment_context")))
        checks["barrier_entailed"] = bool(
            _text(payload.get("implementation_barrier")) and _text(payload.get("feasibility_question"))
        ) or pattern_id == "VALIDATED_CLAIM_WITH_SOURCE_DECLARED_DEPLOYMENT_BARRIER"
    else:
        raise ValueError(f"No deterministic semantic audit is implemented for {gap_type.value}")

    passed = bool(spans) and not missing_payload and all(checks.values()) and not failures
    return {
        "schema_version": "gap_semantic_audit_v3",
        "semantic_verdict": SemanticVerdict.ENTAILED.value if passed else SemanticVerdict.PARTIALLY_ENTAILED.value if spans else SemanticVerdict.UNVERIFIED.value,
        "confidence": 1.0 if passed else 0.4 if spans else 0.0,
        "checks": checks,
        "failure_codes": sorted(set(failures)),
        "semantic_payload_deficits": semantic_payload_deficits,
        "supporting_source_unit_ids": source_ids,
        "scope_status": scope,
        "reason": "Deterministic source-span audit; no external knowledge used.",
    }


def _validate_llm_response(response: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    response = response if isinstance(response, dict) else {}
    source_index = {
        str(item.get("source_unit_id") or ""): {
            "document_version_hash": str(item.get("document_version_hash") or ""),
            "excerpt_hash": str(item.get("excerpt_hash") or ""),
            "excerpt": _text(item.get("excerpt")),
        }
        for item in request["source_spans"]
        if item.get("source_unit_id")
    }
    allowed_sources = set(source_index)
    cited_sources = [str(item) for item in response.get("supporting_source_unit_ids", []) if str(item)]
    invalid_citations = [item for item in cited_sources if item not in allowed_sources]
    verdict = _text(response.get("semantic_verdict")).upper()
    if verdict not in {item.value for item in SemanticVerdict}:
        verdict = SemanticVerdict.UNVERIFIED.value
    checks = response.get("checks") if isinstance(response.get("checks"), dict) else {}
    raw_support = response.get("field_support") if isinstance(response.get("field_support"), list) else []
    field_support: list[dict[str, str]] = []
    invalid_field_support = False
    for item in raw_support:
        if not isinstance(item, dict):
            invalid_field_support = True
            continue
        source_unit_id = _text(item.get("source_unit_id"))
        document_version_hash = _text(item.get("document_version_hash"))
        excerpt_hash = _text(item.get("excerpt_hash"))
        phrase = _text(item.get("supporting_phrase"))
        phrase_start = item.get("phrase_char_start")
        phrase_end = item.get("phrase_char_end")
        supported_field = _text(item.get("supported_field"))
        if (
            not source_unit_id
            or source_unit_id not in source_index
            or not document_version_hash
            or document_version_hash != source_index[source_unit_id]["document_version_hash"]
            or not excerpt_hash
            or excerpt_hash != source_index[source_unit_id]["excerpt_hash"]
            or not phrase
            or not isinstance(phrase_start, int)
            or not isinstance(phrase_end, int)
            or not 0 <= phrase_start < phrase_end <= len(source_index[source_unit_id]["excerpt"])
            or source_index[source_unit_id]["excerpt"][phrase_start:phrase_end] != phrase
            or not supported_field
        ):
            invalid_field_support = True
            continue
        field_support.append(
            {
                "source_unit_id": source_unit_id,
                "document_version_hash": document_version_hash,
                "excerpt_hash": excerpt_hash,
                "supporting_phrase": phrase,
                "phrase_char_start": phrase_start,
                "phrase_char_end": phrase_end,
                "supported_field": supported_field,
            }
        )
    positive_checks = [str(key) for key, value in checks.items() if value is True]
    supported_fields = {item["supported_field"] for item in field_support}
    unsupported_positive_checks = [key for key in positive_checks if key not in supported_fields]
    audit_output_contract_failed = bool(
        invalid_citations
        or invalid_field_support
        or unsupported_positive_checks
        or (
            verdict == SemanticVerdict.ENTAILED.value
            and (not cited_sources or not field_support)
        )
    )
    if verdict == SemanticVerdict.ENTAILED.value and (not cited_sources or invalid_citations):
        verdict = SemanticVerdict.PARTIALLY_ENTAILED.value
        checks = {str(key): False for key in checks}
    if verdict == SemanticVerdict.ENTAILED.value and (not field_support or invalid_field_support or unsupported_positive_checks):
        verdict = SemanticVerdict.PARTIALLY_ENTAILED.value
        checks = {
            str(key): bool(value) and str(key) in supported_fields
            for key, value in checks.items()
        }
    return {
        "semantic_verdict": verdict,
        "confidence": normalize_semantic_confidence(response.get("confidence")),
        "checks": {str(key): bool(value) for key, value in checks.items()},
        "failure_codes": [str(item) for item in response.get("failure_codes", []) if str(item)]
        + (["LLM_INVALID_SOURCE_CITATION"] if invalid_citations else [])
        + (["LLM_FIELD_SUPPORT_INVALID"] if invalid_field_support else [])
        + (["LLM_FIELD_SUPPORT_MISSING:" + key for key in unsupported_positive_checks])
        + (["LLM_AUDIT_OUTPUT_CONTRACT_FAILED"] if audit_output_contract_failed else []),
        "supporting_source_unit_ids": cited_sources,
        "field_support": field_support,
        "audit_output_status": (
            "AUDIT_OUTPUT_CONTRACT_FAILED"
            if audit_output_contract_failed
            else "VALID"
        ),
        "audit_failure_class": (
            "AUDIT_OUTPUT_CONTRACT_FAILURE"
            if audit_output_contract_failed
            else ""
        ),
        "reason": _text(response.get("reason")),
    }


def audit_gap_candidate_semantics(
    project: dict[str, Any],
    candidate: dict[str, Any],
    *,
    positive_auditor: GapSemanticAuditor | None = None,
    red_team_auditor: GapSemanticAuditor | None = None,
) -> dict[str, Any]:
    """Audit one v2 candidate and update only its semantic assessment fields."""
    assessment = assessment_of(candidate)
    request = build_semantic_audit_request(project, candidate)
    deterministic = _deterministic_audit(project, candidate)
    positive = _validate_llm_response(positive_auditor(request), request) if positive_auditor else {}
    red_team = _validate_llm_response(red_team_auditor(request), request) if red_team_auditor else {}

    failure_codes = set(deterministic["failure_codes"])
    failure_codes.update(positive.get("failure_codes", []))
    failure_codes.update(red_team.get("failure_codes", []))
    audit_output_contract_failed = any(
        _text(audit.get("audit_output_status")) == "AUDIT_OUTPUT_CONTRACT_FAILED"
        for audit in (positive, red_team)
        if isinstance(audit, dict)
    )
    checks = dict(deterministic["checks"])
    if positive:
        for key, value in positive["checks"].items():
            checks[key] = checks.get(key, True) and value
    if red_team:
        for key, value in red_team["checks"].items():
            if value is False:
                checks[key] = False
    entailed = (
        deterministic["semantic_verdict"] == SemanticVerdict.ENTAILED.value
        and (not positive or positive["semantic_verdict"] == SemanticVerdict.ENTAILED.value)
        and (not red_team or red_team["semantic_verdict"] not in {SemanticVerdict.CONTRADICTED.value, SemanticVerdict.OUT_OF_SCOPE.value})
        and not failure_codes
    )
    if audit_output_contract_failed:
        verdict = SemanticVerdict.UNVERIFIED.value
    elif deterministic["scope_status"] == ScopeStatus.OUT_OF_SCOPE.value:
        verdict = SemanticVerdict.OUT_OF_SCOPE.value
    elif red_team and red_team["semantic_verdict"] == SemanticVerdict.CONTRADICTED.value:
        verdict = SemanticVerdict.CONTRADICTED.value
    elif entailed:
        verdict = SemanticVerdict.ENTAILED.value
    elif deterministic["supporting_source_unit_ids"]:
        verdict = SemanticVerdict.PARTIALLY_ENTAILED.value
    else:
        verdict = SemanticVerdict.UNVERIFIED.value

    result = dict(candidate)
    updated = dict(assessment)
    updated.update(
        {
            "candidate_stage": CandidateStage.SEMANTIC_AUDITED.value,
            "semantic_verdict": verdict,
            "semantic_confidence": min(
                1.0,
                max(
                    deterministic["confidence"],
                    normalize_semantic_confidence(positive.get("confidence")) if positive else 0.0,
                ),
            ),
            "semantic_failure_codes": sorted(failure_codes),
            "audit_output_status": (
                "AUDIT_OUTPUT_CONTRACT_FAILED"
                if audit_output_contract_failed
                else "VALID"
            ),
            "audit_failure_class": (
                "AUDIT_OUTPUT_CONTRACT_FAILURE"
                if audit_output_contract_failed
                else ""
            ),
            "scope_status": deterministic["scope_status"],
            "context_verdict": "ALIGNED" if checks.get("context_aligned", True) else "CONFLICTING",
            "temporal_verdict": "SUPPORTED" if checks.get("temporal_order_supported", False) else "UNRESOLVED",
            "source_role_verdict": "DIRECT" if deterministic["scope_status"] == ScopeStatus.CORE.value else "INDIRECT",
            "evidence_maturity": EvidenceMaturity.SEMANTICALLY_VALIDATED.value if verdict == SemanticVerdict.ENTAILED.value else EvidenceMaturity.SOURCE_BOUND.value if deterministic["supporting_source_unit_ids"] else EvidenceMaturity.LEAD.value,
            "route": GapRoute.DIAGNOSTIC.value,
            "decision_reasons": (
                ["AUDIT_OUTPUT_CONTRACT_FAILED"]
                if audit_output_contract_failed
                else sorted(failure_codes)
                or ["SEMANTIC_AUDIT_PASSED_PENDING_RETRIEVAL_AND_DESIGN"]
            ),
            "audit_refs": [
                {
                    "kind": "deterministic_semantic_audit",
                    "schema_version": "gap_semantic_audit_v3",
                    "supporting_source_unit_ids": deterministic["supporting_source_unit_ids"],
                }
            ],
        }
    )
    result["semantic_audit"] = {
        "schema_version": "gap_semantic_audit_result_v3",
        "candidate_identity": _text(candidate.get("candidate_identity")),
        # The value is incremented by synchronize_candidate_surface below.
        # Store that future value so qualification can reject a stale audit.
        "assessment_version": int(candidate.get("assessment_version") or 0) + 1,
        "graph_snapshot_ref": dict(candidate.get("graph_snapshot_ref") or {}),
        "retrieval_rebind_fingerprint": _text(
            (candidate.get("retrieval_rebind") or {}).get("rebind_fingerprint")
            if isinstance(candidate.get("retrieval_rebind"), dict)
            else ""
        ),
        "deterministic": deterministic,
        "positive": positive,
        "red_team": red_team,
        "checks": checks,
        "audit_output_status": (
            "AUDIT_OUTPUT_CONTRACT_FAILED"
            if audit_output_contract_failed
            else "VALID"
        ),
        "audit_failure_class": (
            "AUDIT_OUTPUT_CONTRACT_FAILURE"
            if audit_output_contract_failed
            else ""
        ),
    }
    return synchronize_candidate_surface(
        result,
        updated,
        semantic_assessment={
            "audit_request_schema": request["schema_version"],
            "deterministic": deterministic,
            "positive_field_support": list(positive.get("field_support") or []),
            "red_team_field_support": list(red_team.get("field_support") or []),
            "audit_output_status": (
                "AUDIT_OUTPUT_CONTRACT_FAILED"
                if audit_output_contract_failed
                else "VALID"
            ),
            "audit_failure_class": (
                "AUDIT_OUTPUT_CONTRACT_FAILURE"
                if audit_output_contract_failed
                else ""
            ),
        },
        increment_assessment_version=True,
    )
