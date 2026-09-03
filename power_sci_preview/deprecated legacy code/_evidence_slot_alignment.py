"""Contract-specific slot alignment over source-bound document propositions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
from typing import Any, Callable, Mapping
import unicodedata
from uuid import NAMESPACE_URL, uuid5

try:
    from ._evidence_assertion_validation import EVIDENCE_ASSERTION_SCHEMA_VERSION
    from ._evidence_proposition_extraction import _resolve_source_quote
    from ._llm import LLMJSONProtocolError, call_llm_json_contract
    from .config import SCIENCE_ALIGNMENT_LLM_MAX_PER_DOCUMENT
    from ._science_execution_policy import ScienceExecutionPolicy
    from ._science_llm_scheduler import LLMJob, run_science_llm_job
except ImportError:
    from _evidence_assertion_validation import EVIDENCE_ASSERTION_SCHEMA_VERSION
    from _evidence_proposition_extraction import _resolve_source_quote
    from _llm import LLMJSONProtocolError, call_llm_json_contract
    from config import SCIENCE_ALIGNMENT_LLM_MAX_PER_DOCUMENT
    from _science_execution_policy import ScienceExecutionPolicy
    from _science_llm_scheduler import LLMJob, run_science_llm_job


SLOT_SUPPORT_SCHEMA_VERSION = "slot_support_v8"
SLOT_ALIGNMENT_SCHEMA_VERSION = "contract_alignment_artifact_v8"
CONTRACT_TASK_ALIGNMENT_INDEX_SCHEMA_VERSION = "contract_task_alignment_index_v1"
COMPARISON_ALIGNMENT_PROTOCOL_REVISION = "comparison_alignment_v4"
SLOT_ALIGNMENT_PROMPT_REVISION = "contract_alignment_pair_matrix_v1"
ALIGNMENT_BATCH_REQUEST_SCHEMA_VERSION = "slot_alignment_batch_request_v1"
ALIGNMENT_BATCH_RESULT_SCHEMA_VERSION = "slot_alignment_batch_result_v1"
ALIGNMENT_BATCH_ARTIFACT_SCHEMA_VERSION = "slot_alignment_batch_artifact_v1"
MAX_ALIGNMENT_BATCH = 10
ALIGNMENT_VERDICTS = frozenset({
    "SUPPORTS",
    "CONSISTENT_WITH",
    "BOUNDARY",
    "ADVERSE",
    "NO_MATCH",
    "PENDING",
})
POSITIVE_ALIGNMENT_VERDICTS = frozenset({
    "SUPPORTS", "CONSISTENT_WITH", "BOUNDARY", "ADVERSE",
})
SOURCE_ENTAILMENT_VERDICTS = frozenset({"ENTAILED", "NOT_ENTAILED", "PENDING"})
_PARTIAL_EXCLUSIONARY_RE = re.compile(
    r"\b(?:no|none|never|only|exclusively|all|entire|throughout|absence|absent|"
    r"without|did\s+not|does\s+not|cannot|can't|fails?\s+to)\b",
    re.IGNORECASE,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normal(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", _text(value)).casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _alignment_eligible_proposition(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if _text(value.get("validator_verdict")) != "ACCEPTED_SOURCE_BOUND":
        return False
    source_span_ids = {
        _text(item) for item in value.get("source_span_ids", []) if _text(item)
    }
    source_evidence = [
        item for item in value.get("source_evidence", [])
        if isinstance(item, Mapping)
    ]
    return bool(
        source_span_ids
        and source_evidence
        and all(
            _text(item.get("source_span_id")) in source_span_ids
            and bool(_text(item.get("exact_quote")))
            for item in source_evidence
        )
    )


def _default_llm_call(**kwargs: Any) -> dict[str, Any]:
    result = call_llm_json_contract(
        system=str(kwargs["system"]),
        prompt=str(kwargs["prompt"]),
        max_tokens=int(kwargs.get("max_tokens") or 8000),
        required_list_key="decisions",
        protocol_name="SLOT_ALIGNMENT",
        allow_empty=False,
        expected_schema_version=ALIGNMENT_BATCH_RESULT_SCHEMA_VERSION,
    )
    return {
        "payload": dict(result["payload"]),
        "diagnostics": dict(result["diagnostics"]),
    }


def _model_id() -> str:
    try:
        from .config import QWEN_MODEL_ID
    except ImportError:
        from config import QWEN_MODEL_ID
    return str(QWEN_MODEL_ID or "")


def _contract_revision(contract: Mapping[str, Any]) -> tuple[str, str]:
    revision = _text(contract.get("contract_revision") or contract.get("declaration_hash"))
    declaration = _text(contract.get("declaration_hash") or contract.get("contract_revision"))
    return revision, declaration


def _flatten_text(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        output: list[str] = []
        for nested in value.values():
            output.extend(_flatten_text(nested))
        return output
    if isinstance(value, list):
        output = []
        for nested in value:
            output.extend(_flatten_text(nested))
        return output
    text = _text(value)
    return [text] if text else []


def _slot_contract_anchors(contract: Mapping[str, Any], slot_id: str) -> list[str]:
    definitions = (
        contract.get("slot_definitions")
        if isinstance(contract.get("slot_definitions"), Mapping)
        else {}
    )
    definition = (
        definitions.get(slot_id)
        if isinstance(definitions.get(slot_id), Mapping)
        else {}
    )
    question = (
        contract.get("research_question")
        if isinstance(contract.get("research_question"), Mapping)
        else {}
    )
    scope = (
        contract.get("scientific_scope")
        if isinstance(contract.get("scientific_scope"), Mapping)
        else {}
    )
    return list(dict.fromkeys([
        slot_id,
        *_flatten_text(definition),
        *_flatten_text(question.get("question_text")),
        *_flatten_text(scope),
    ]))


def _contract_anchor_valid(text: str, candidates: list[str]) -> bool:
    needle = _normal(text)
    return bool(needle and any(needle in _normal(candidate) for candidate in candidates))


def _contract_anchor(
    value: Any,
    *,
    contract: Mapping[str, Any],
    slot_id: str,
) -> dict[str, Any] | None:
    """Resolve an LLM-selected stable anchor identifier locally.

    A model must select an ID from the contract catalog rather than reproduce
    arbitrary contract prose.  This keeps anchor validation deterministic and
    separates a source-location failure from a relevance decision.
    """
    anchor_id = _text(value)
    if anchor_id == f"slot:{slot_id}":
        return {"anchor_id": anchor_id, "kind": "slot", "slot_id": slot_id}
    comparison = contract.get("comparison_contract_v4")
    comparison = comparison if isinstance(comparison, Mapping) else {}
    if anchor_id.startswith("arm:"):
        arm_id = anchor_id.removeprefix("arm:")
        for arm in [comparison.get("primary_arm"), *(comparison.get("comparator_arms") or [])]:
            if isinstance(arm, Mapping) and _text(arm.get("arm_id")) == arm_id:
                return {
                    "anchor_id": anchor_id,
                    "kind": "arm",
                    "arm_id": arm_id,
                    "canonical_label": _text(arm.get("canonical_label")),
                }
    if anchor_id.startswith("metric:"):
        metric_id = anchor_id.removeprefix("metric:")
        if metric_id in {
            _text(item) for item in comparison.get("required_metric_families", [])
        }:
            return {"anchor_id": anchor_id, "kind": "metric", "metric_id": metric_id}
    return None


def _proposition_entailment(proposition: Mapping[str, Any]) -> tuple[str, str]:
    audit = proposition.get("semantic_entailment")
    audit = audit if isinstance(audit, Mapping) else {}
    verdict = _text(audit.get("verdict")).upper()
    if verdict not in SOURCE_ENTAILMENT_VERDICTS:
        verdict = "PENDING"
    return verdict, _text(audit.get("reason"))


def _benchmark_arm_observations(
    proposition: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Find declared comparison arms directly in locatable source evidence.

    This is a source-identity operation, not a comparison conclusion. It lets
    an arm-only paper be retained without asking the generic slot matrix to
    pretend that it contains the other arm, a shared metric, and a protocol.
    """
    comparison = contract.get("comparison_contract_v4")
    comparison = comparison if isinstance(comparison, Mapping) else {}
    if comparison.get("schema_version") != "comparison_contract_v4":
        return []
    arms = [comparison.get("primary_arm"), *(comparison.get("comparator_arms") or [])]
    observations: list[dict[str, Any]] = []
    for arm in arms:
        if not isinstance(arm, Mapping):
            continue
        arm_id = _text(arm.get("arm_id"))
        forms = [
            _text(value) for value in [
                arm.get("canonical_label"), *(arm.get("accepted_surface_forms") or [])
            ] if _text(value)
        ]
        for evidence in proposition.get("source_evidence", []):
            if not isinstance(evidence, Mapping):
                continue
            quote = str(evidence.get("exact_quote") or "")
            for form in forms:
                resolved = _resolve_source_quote(quote, form)
                if resolved is None:
                    continue
                observations.append({
                    "arm_id": arm_id,
                    "relation": (
                        "PRIMARY" if arm_id == _text((comparison.get("primary_arm") or {}).get("arm_id"))
                        else "COMPARATOR"
                    ),
                    "source_anchor": {
                        "source_span_id": _text(evidence.get("source_span_id")),
                        "text": resolved["text"],
                        "source_start": resolved["source_start"],
                        "source_end": resolved["source_end"],
                        "grounding_mode": resolved["grounding_mode"],
                    },
                    "source_evidence": dict(evidence),
                })
                break
            if observations and observations[-1].get("arm_id") == arm_id:
                break
    return observations


def _validated_benchmark_observations(
    proposition: Mapping[str, Any],
    raw: Any,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep only source-locatable observations whose IDs exist in V4."""
    source = raw if isinstance(raw, Mapping) else {}
    comparison = contract.get("comparison_contract_v4")
    comparison = comparison if isinstance(comparison, Mapping) else {}
    if comparison.get("schema_version") != "comparison_contract_v4":
        return {}
    arm_ids = {
        _text(arm.get("arm_id"))
        for arm in [comparison.get("primary_arm"), *(comparison.get("comparator_arms") or [])]
        if isinstance(arm, Mapping) and _text(arm.get("arm_id"))
    }
    metric_ids = {
        _text(value) for value in comparison.get("required_metric_families", []) if _text(value)
    }
    axis_ids = {
        _text(value) for value in comparison.get("comparability_axes", []) if _text(value)
    }

    def anchored(item: Mapping[str, Any]) -> dict[str, Any] | None:
        anchor, _evidence = _source_anchor(item, proposition)
        return anchor

    arms = []
    for item in source.get("arm_matches", []):
        if not isinstance(item, Mapping) or _text(item.get("arm_id")) not in arm_ids:
            continue
        anchor = anchored(item)
        if anchor is not None:
            arms.append({"arm_id": _text(item.get("arm_id")), "source_anchor": anchor})
    metrics = []
    for item in source.get("metric_observations", []):
        if not isinstance(item, Mapping) or _text(item.get("metric_id")) not in metric_ids:
            continue
        anchor = anchored(item)
        if anchor is not None:
            metrics.append({
                "metric_id": _text(item.get("metric_id")),
                "value_text": _text(item.get("value_text")),
                "unit": _text(item.get("unit")),
                "source_anchor": anchor,
            })
    axes = []
    for item in source.get("comparability_observations", []):
        if not isinstance(item, Mapping) or _text(item.get("axis_id")) not in axis_ids:
            continue
        anchor = anchored(item)
        if anchor is not None:
            axes.append({
                "axis_id": _text(item.get("axis_id")),
                "value_text": _text(item.get("value_text")),
                "source_anchor": anchor,
            })
    direct_source = source.get("direct_comparison")
    direct_source = direct_source if isinstance(direct_source, Mapping) else {}
    direct_anchor = anchored(direct_source) if direct_source else None
    target_pairs = {
        frozenset(_text(arm_id) for arm_id in pair if _text(arm_id))
        for pair in comparison.get("target_comparison_pairs", [])
        if isinstance(pair, list) and len(pair) == 2
    }
    direct_arm_ids = frozenset({
        _text(direct_source.get("left_arm_id")),
        _text(direct_source.get("right_arm_id")),
    } - {""})
    direct = {}
    if (
        direct_anchor is not None
        and direct_arm_ids in target_pairs
        and bool(_text(direct_source.get("relation")))
    ):
        direct = {
            "left_arm_id": _text(direct_source.get("left_arm_id")),
            "right_arm_id": _text(direct_source.get("right_arm_id")),
            "relation": _text(direct_source.get("relation")),
            "metric_id": _text(direct_source.get("metric_id")),
            "left_value_text": _text(direct_source.get("left_value_text")),
            "right_value_text": _text(direct_source.get("right_value_text")),
            "unit": _text(direct_source.get("unit")),
            "common_task": _text(direct_source.get("common_task")),
            "protocol": _text(direct_source.get("protocol")),
            "source_anchor": direct_anchor,
        }
    return {
        "arm_matches": arms,
        "metric_observations": metrics,
        "comparability_observations": axes,
        "direct_comparison": direct,
    }


def _source_anchor(
    proposal: Mapping[str, Any],
    proposition: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    requested_span_id = _text(proposal.get("source_span_id"))
    evidence_items = [
        dict(item)
        for item in proposition.get("source_evidence", [])
        if isinstance(item, Mapping)
    ]
    requested_index = proposal.get("source_evidence_index")
    if isinstance(requested_index, int) and 0 <= requested_index < len(evidence_items):
        evidence_items = [evidence_items[requested_index]]
    elif requested_span_id:
        evidence_items = [
            item for item in evidence_items
            if _text(item.get("source_span_id")) == requested_span_id
        ]
    if not evidence_items:
        return None, {}
    requested = _text(
        proposal.get("source_anchor") or proposal.get("source_anchor_text")
    )
    if not requested:
        return None, {}
    for evidence in evidence_items:
        quote = str(evidence.get("exact_quote") or "")
        resolved = _resolve_source_quote(quote, requested)
        if resolved is None:
            continue
        return {
            "source_span_id": _text(evidence.get("source_span_id")),
            "text": resolved["text"],
            "source_start": resolved["source_start"],
            "source_end": resolved["source_end"],
            "grounding_mode": resolved["grounding_mode"],
        }, evidence
    return None, {}


def _partial_gate_eligibility(
    proposition: Mapping[str, Any],
    supports: list[dict[str, Any]],
) -> dict[str, Any]:
    reason_codes: list[str] = []
    statement = _text(proposition.get("canonical_statement"))
    if _text(proposition.get("attribution")).upper() != "CURRENT_AUTHORS":
        reason_codes.append("PARTIAL_GATE_REQUIRES_CURRENT_AUTHOR_ATTRIBUTION")
    if _text(proposition.get("claim_scope")).upper() != "LOCAL_FINDING":
        reason_codes.append("FULL_COVERAGE_REQUIRED_FOR_NONLOCAL_CLAIM")
    if _text(proposition.get("polarity")).upper() != "POSITIVE":
        reason_codes.append("FULL_COVERAGE_REQUIRED_FOR_NONPOSITIVE_CLAIM")
    if _text(proposition.get("modality")).upper() != "ASSERTED":
        reason_codes.append("PARTIAL_GATE_REQUIRES_ASSERTED_MODALITY")
    if _PARTIAL_EXCLUSIONARY_RE.search(statement):
        reason_codes.append("FULL_COVERAGE_REQUIRED_FOR_EXCLUSIONARY_CLAIM")
    if any(
        _text(item.get("alignment_verdict"))
        not in {"SUPPORTS", "CONSISTENT_WITH"}
        for item in supports
    ):
        reason_codes.append("FULL_COVERAGE_REQUIRED_FOR_NONPOSITIVE_SUPPORT")
    eligible = not reason_codes
    return {
        "schema_version": "partial_assertion_gate_eligibility_v1",
        "status": (
            "ELIGIBLE_FOR_PARTIAL_POSITIVE_ADMISSION"
            if eligible else "COMPLETE_DOCUMENT_REQUIRED"
        ),
        "reason_codes": reason_codes,
        "assertion_counts_toward_gate": False,
        "admission_may_count": eligible,
    }


def _alignment_prompt(
    contract: Mapping[str, Any],
    propositions: list[dict[str, Any]],
    target_slot_ids: list[str],
    *,
    alignment_run_id: str,
    batch_id: str,
    expected_pair_ids: list[str],
    repair_of_batch_id: str = "",
) -> str:
    question = (
        contract.get("research_question")
        if isinstance(contract.get("research_question"), Mapping)
        else {}
    )
    slot_definitions = (
        contract.get("slot_definitions")
        if isinstance(contract.get("slot_definitions"), Mapping)
        else {}
    )
    target_slot_definitions = {
        slot_id: slot_definitions.get(slot_id)
        for slot_id in target_slot_ids
        if slot_id in slot_definitions
    }
    request_envelope = {
        "schema_version": ALIGNMENT_BATCH_REQUEST_SCHEMA_VERSION,
        "alignment_run_id": alignment_run_id,
        "batch_id": batch_id,
        "repair_of_batch_id": repair_of_batch_id,
        "research_question_task_id": contract.get("research_question_task_id"),
        "question_kind": question.get("question_kind"),
        "question_text": question.get("question_text"),
        "target_slot_ids": target_slot_ids,
        "target_slot_definitions": target_slot_definitions,
        "scientific_scope": contract.get("scientific_scope"),
        "expected_pair_ids": expected_pair_ids,
    }
    return (
        "The source-entailment audit was completed before this call. Do not re-evaluate source entailment and do not "
        "use contract relevance as a reason to question it. Decide each expected pair independently. Return exactly "
        "one decision for every expected_pair_id. NO_MATCH is a required terminal decision: never omit an irrelevant "
        "pair and never return an empty decisions list. PENDING is allowed only when the supplied evidence genuinely "
        "cannot be assessed. Positive decisions must be grounded in the supplied source evidence. The runtime constructs "
        "source and contract anchors; do not return them. Return JSON only.\n"
        "Return exactly {\"schema_version\":\"slot_alignment_batch_result_v1\","
        "\"alignment_run_id\":...,\"batch_id\":...,\"expected_pair_ids\":[...],"
        "\"decisions\":[{\"pair_id\":...,"
        "\"verdict\":\"SUPPORTS|CONSISTENT_WITH|BOUNDARY|ADVERSE|NO_MATCH|PENDING\","
        "\"alignment_confidence\":0.0,\"reason_code\":...}]}"
        + " For BENCHMARK_COMPARISON, a decision may additionally contain comparison_evidence with arm_matches, "
        "metric_observations, comparability_observations, and direct_comparison; every value must be grounded by "
        "a copied source fragment.\n"
        + json.dumps(request_envelope, ensure_ascii=False)
        + "\nPropositions:\n"
        + json.dumps([
            {
                "proposition_id": item.get("proposition_id"),
                "canonical_statement": item.get("canonical_statement"),
                "source_evidence": [
                    {
                        "source_span_id": evidence.get("source_span_id"),
                        "exact_quote": evidence.get("exact_quote"),
                    }
                    for evidence in item.get("source_evidence", [])
                    if isinstance(evidence, Mapping)
                ],
                "claim_role": item.get("claim_role"),
                "attribution": item.get("attribution"),
                "quantities": item.get("quantities"),
                "boundary_conditions": item.get("boundary_conditions"),
            }
            for item in propositions
        ], ensure_ascii=False)
    )


def _resumable_prior_alignment(
    value: Mapping[str, Any] | None,
    *,
    artifact_base: Mapping[str, Any],
) -> dict[str, Any] | None:
    source = value if isinstance(value, Mapping) else {}
    if any((
        source.get("schema_version") != SLOT_ALIGNMENT_SCHEMA_VERSION,
        _text(source.get("document_version_id"))
        != _text(artifact_base.get("document_version_id")),
        _text(source.get("proposition_artifact_id"))
        != _text(artifact_base.get("proposition_artifact_id")),
        _text(source.get("research_question_contract_id"))
        != _text(artifact_base.get("research_question_contract_id")),
        _text(source.get("contract_revision"))
        != _text(artifact_base.get("contract_revision")),
        _text(source.get("research_question_task_id"))
        != _text(artifact_base.get("research_question_task_id")),
        _text(source.get("alignment_scope_revision"))
        != _text(artifact_base.get("alignment_scope_revision")),
        _text(source.get("comparison_alignment_protocol_revision"))
        != _text(artifact_base.get("comparison_alignment_protocol_revision")),
    )):
        return None
    return dict(source)


def align_propositions_to_contract(
    extraction: Mapping[str, Any],
    contract: Mapping[str, Any],
    policy: ScienceExecutionPolicy,
    *,
    task_scope: Mapping[str, Any],
    llm_call: Callable[..., dict[str, Any]] | None = None,
    prior_artifact: Mapping[str, Any] | None = None,
    prior_batch_artifacts: list[Mapping[str, Any]] | None = None,
    batch_checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    contract_id = _text(contract.get("contract_id"))
    revision, declaration_hash = _contract_revision(contract)
    research_question_task_id = _text(
        task_scope.get("research_question_task_id")
        or contract.get("research_question_task_id")
    )
    target_slot_ids = list(dict.fromkeys(
        _text(item) for item in task_scope.get("target_slot_ids", []) if _text(item)
    ))
    alignment_scope_id = _text(contract.get("alignment_scope_id")) or contract_id
    alignment_scope_revision = _text(contract.get("alignment_scope_revision")) or revision
    document_version_id = _text(
        extraction.get("document_version_id")
        or (extraction.get("document") or {}).get("document_version_id")
    )
    proposition_artifact_id = _text(
        extraction.get("artifact_id") or extraction.get("extraction_run_id")
    )
    artifact_base = {
        "schema_version": SLOT_ALIGNMENT_SCHEMA_VERSION,
        "artifact_id": "alignment_" + uuid5(
            NAMESPACE_URL,
            "|".join((
                document_version_id,
                proposition_artifact_id,
                contract_id,
                revision,
                declaration_hash,
                research_question_task_id,
                alignment_scope_revision,
            )),
        ).hex[:24],
        "document_version_id": document_version_id,
        "proposition_artifact_id": proposition_artifact_id,
        "research_question_contract_id": contract_id,
        "contract_revision": revision,
        "research_question_task_id": research_question_task_id,
        "alignment_scope_id": alignment_scope_id,
        "alignment_scope_revision": alignment_scope_revision,
        "target_slot_ids": target_slot_ids,
        # This revision invalidates only the contract-alignment cache when
        # comparison semantics change. The immutable document, source spans,
        # and proposition artifact remain reusable.
        "comparison_alignment_protocol_revision": (
            COMPARISON_ALIGNMENT_PROTOCOL_REVISION
        ),
        "contract_id": contract_id,
    }
    required_slots = target_slot_ids
    if not research_question_task_id or not required_slots:
        return {
            **artifact_base,
            "status": "TASK_SCOPE_INVALID",
            "reason_codes": ["TASK_SCOPE_REQUIRES_TASK_ID_AND_TARGET_SLOT_IDS"],
            "alignment_decisions": [],
            "slot_supports": [],
            "assertions": [],
            "slot_status": {},
        }
    all_propositions = [
        dict(item) for item in extraction.get("propositions", [])
        if _alignment_eligible_proposition(item)
    ]
    # Composition adds a broader source-bound reading but never replaces its
    # atomic evidence. Deduplication belongs to admission/synthesis, after
    # every source granularity has had an opportunity to align.
    propositions = all_propositions
    if not policy.use_llm or policy.slot_alignment_mode != "llm_primary":
        return {
            **artifact_base,
            "status": "DETERMINISTIC_DIAGNOSTIC",
            "reason_codes": ["LLM_SLOT_ALIGNMENT_DISABLED"],
            "alignment_decisions": [],
            "slot_supports": [],
            "assertions": [],
        }
    extraction_status = _text(extraction.get("status"))
    partial_document = extraction_status == "PROPOSITION_PARTIAL"
    if extraction_status not in {"PROPOSITION_READY", "PROPOSITION_PARTIAL"}:
        return {
            **artifact_base,
            "status": "SLOT_ALIGNMENT_PENDING",
            "reason_codes": ["DOCUMENT_EXTRACTION_NOT_COMPLETE"],
            "alignment_decisions": [],
            "slot_supports": [],
            "assertions": [],
        }

    propositions_by_id = {
        _text(item.get("proposition_id")): item for item in propositions
    }
    expected_pairs = {
        (proposition_id, slot_id)
        for proposition_id in propositions_by_id
        for slot_id in required_slots
    }
    alignment_run_id = _text(artifact_base.get("artifact_id"))
    decisions_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    failures: list[str] = []
    present_pairs: set[tuple[str, str]] = set()
    terminal_pairs: set[tuple[str, str]] = set()
    transport_pending_pairs: set[tuple[str, str]] = set()
    response_truncated_pairs: set[tuple[str, str]] = set()
    root_protocol_invalid_pairs: set[tuple[str, str]] = set()
    response_incomplete_pairs: set[tuple[str, str]] = set()
    batch_diagnostics: list[dict[str, Any]] = []
    batch_artifacts: list[dict[str, Any]] = []
    benchmark_observations_by_proposition: dict[str, dict[str, Any]] = {}

    prior = _resumable_prior_alignment(
        prior_artifact,
        artifact_base=artifact_base,
    )
    if prior is not None:
        for decision in prior.get("alignment_decisions", []):
            if not isinstance(decision, Mapping):
                continue
            pair = (
                _text(decision.get("proposition_id")),
                _text(decision.get("slot_id")),
            )
            if (
                pair not in expected_pairs
                or _text(decision.get("verdict")) == "PENDING"
                or _text(decision.get("terminal_status")) != "TERMINAL"
            ):
                continue
            decisions_by_pair[pair] = dict(decision)
            present_pairs.add(pair)
            terminal_pairs.add(pair)

    def pending_decision(
        proposition_id: str,
        slot_id: str,
        *,
        terminal_status: str,
        reason_codes: list[str],
        retry_batch_id: str = "",
    ) -> dict[str, Any]:
        return {
            "proposition_id": proposition_id,
            "slot_id": slot_id,
            "verdict": "PENDING",
            "source_entailment_verdict": _proposition_entailment(
                propositions_by_id[proposition_id]
            )[0],
            "source_entailment_reason": _proposition_entailment(
                propositions_by_id[proposition_id]
            )[1],
            "source_anchor": None,
            "source_evidence": {},
            "contract_anchor": {},
            "alignment_confidence": None,
            "terminal_status": terminal_status,
            "retry_batch_id": retry_batch_id,
            "reason_codes": list(dict.fromkeys(reason_codes)),
        }

    def pair_id(pair: tuple[str, str]) -> str:
        return f"{pair[0]}|{pair[1]}"

    def parse_pair_id(value: Any) -> tuple[str, str] | None:
        identifier = _text(value)
        if identifier.count("|") != 1:
            return None
        proposition_id, slot_id = identifier.split("|", 1)
        if not proposition_id or not slot_id:
            return None
        return proposition_id, slot_id

    def unpack_llm_result(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(value, Mapping):
            return {}, {}
        if isinstance(value.get("payload"), Mapping):
            return (
                dict(value["payload"]),
                dict(value.get("diagnostics") or {}),
            )
        return dict(value), {}

    def materialize_decision(
        pair: tuple[str, str],
        raw: Mapping[str, Any],
    ) -> dict[str, Any]:
        proposition_id, slot_id = pair
        proposition = propositions_by_id[proposition_id]
        source_entailment_verdict, source_entailment_reason = _proposition_entailment(
            proposition
        )
        source_evidence = next(
            (
                dict(item)
                for item in proposition.get("source_evidence", [])
                if isinstance(item, Mapping)
                and _text(item.get("source_span_id"))
                and _text(item.get("exact_quote"))
            ),
            {},
        )
        source_anchor = (
            {
                "source_span_id": _text(source_evidence.get("source_span_id")),
                "text": _text(source_evidence.get("exact_quote")),
                "source_start": 0,
                "source_end": len(_text(source_evidence.get("exact_quote"))),
                "grounding_mode": "PROPOSITION_SOURCE_EVIDENCE",
            }
            if source_evidence else None
        )
        verdict = _text(raw.get("verdict")).upper()
        reason_codes: list[str] = []
        if source_entailment_verdict != "ENTAILED" and verdict in POSITIVE_ALIGNMENT_VERDICTS:
            reason_codes.append("SOURCE_ENTAILMENT_NOT_VERIFIED")
            verdict = "PENDING"
        if verdict in POSITIVE_ALIGNMENT_VERDICTS and source_anchor is None:
            reason_codes.append("SOURCE_ANCHOR_INVALID")
            verdict = "PENDING"
        reason_code = _text(raw.get("reason_code"))
        if reason_code:
            reason_codes.append(reason_code)
        benchmark_observations = _validated_benchmark_observations(
            proposition,
            raw.get("comparison_evidence"),
            contract,
        )
        if benchmark_observations:
            benchmark_observations_by_proposition[proposition_id] = benchmark_observations
        return {
            "proposition_id": proposition_id,
            "slot_id": slot_id,
            "verdict": verdict,
            "source_entailment_verdict": source_entailment_verdict,
            "source_entailment_reason": source_entailment_reason,
            "source_anchor": source_anchor,
            "source_evidence": source_evidence,
            "contract_anchor": {
                "anchor_id": f"slot:{slot_id}",
                "kind": "slot",
                "slot_id": slot_id,
            },
            "alignment_confidence": raw.get("alignment_confidence"),
            "terminal_status": "TERMINAL" if verdict != "PENDING" else "PENDING_SEMANTIC",
            "retry_batch_id": "",
            "reason_codes": list(dict.fromkeys(reason_codes)),
        }

    call = llm_call or _default_llm_call

    def invoke_batch(task: Mapping[str, Any]) -> tuple[dict[str, Any], Any, Exception | None]:
        batch_id = _text(task.get("batch_id"))
        batch = list(task.get("batch") or [])
        batch_pairs = set(task.get("batch_pairs") or set())
        candidate_id = _text(task.get("candidate_id"))
        expected_pair_ids = [pair_id(pair) for pair in sorted(batch_pairs)]
        request = {
            "schema_version": ALIGNMENT_BATCH_REQUEST_SCHEMA_VERSION,
            "alignment_run_id": alignment_run_id,
            "batch_id": batch_id,
            "repair_of_batch_id": _text(task.get("repair_of_batch_id")),
            "expected_pair_ids": expected_pair_ids,
            "target_slot_ids": list(required_slots),
        }
        prompt = _alignment_prompt(
            contract,
            batch,
            required_slots,
            alignment_run_id=alignment_run_id,
            batch_id=batch_id,
            expected_pair_ids=expected_pair_ids,
            repair_of_batch_id=_text(task.get("repair_of_batch_id")),
        )
        try:
            payload = run_science_llm_job(
                LLMJob(
                    candidate_id=candidate_id,
                    stage="slot_alignment_batch",
                    batch_id=batch_id,
                    prompt_chars=len(prompt),
                    max_tokens=8000,
                    input_span_count=len(batch),
                    candidate_max_inflight=SCIENCE_ALIGNMENT_LLM_MAX_PER_DOCUMENT,
                ),
                lambda: call(
                    system=(
                        "You independently align each source-bound scientific proposition to every declared slot. "
                        "Return a complete JSON decision matrix without broadening either source or contract."
                    ),
                    prompt=prompt,
                    max_tokens=8000,
                    alignment_request=request,
                ),
            )
        except Exception as exc:
            return dict(task), None, exc
        return dict(task), payload, None

    def run_batch_tasks(tasks: list[dict[str, Any]]) -> list[tuple[dict[str, Any], Any, Exception | None]]:
        if not tasks:
            return []
        workers = min(SCIENCE_ALIGNMENT_LLM_MAX_PER_DOCUMENT, len(tasks))
        if workers == 1:
            return [invoke_batch(tasks[0])]
        results: list[tuple[dict[str, Any], Any, Exception | None]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(invoke_batch, task) for task in tasks]
            for future in as_completed(futures):
                results.append(future.result())
        return results

    def append_pending(
        task: Mapping[str, Any],
        pairs: set[tuple[str, str]],
        *,
        terminal_status: str,
        reason_codes: list[str],
    ) -> None:
        batch_id = _text(task.get("batch_id"))
        for proposition_id, slot_id in sorted(pairs):
            decisions_by_pair[(proposition_id, slot_id)] = pending_decision(
                proposition_id,
                slot_id,
                terminal_status=terminal_status,
                reason_codes=reason_codes,
                retry_batch_id=batch_id,
            )

    def batch_artifact(
        task: Mapping[str, Any],
        *,
        status: str,
        diagnostics: Mapping[str, Any],
        payload: Mapping[str, Any] | None = None,
        accepted_pairs: set[tuple[str, str]] | None = None,
        missing_pairs: set[tuple[str, str]] | None = None,
        foreign_pair_ids: list[str] | None = None,
        duplicate_pair_ids: list[str] | None = None,
        malformed_decision_indexes: list[int] | None = None,
        invalid_verdict_pair_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        expected = set(task.get("batch_pairs") or set())
        artifact = {
            "schema_version": ALIGNMENT_BATCH_ARTIFACT_SCHEMA_VERSION,
            "alignment_artifact_id": alignment_run_id,
            "alignment_run_id": alignment_run_id,
            "batch_id": _text(task.get("batch_id")),
            "repair_of_batch_id": _text(task.get("repair_of_batch_id")),
            "attempt": int(task.get("attempt") or 0),
            "status": status,
            "expected_pair_ids": [pair_id(pair) for pair in sorted(expected)],
            "accepted_pair_ids": [pair_id(pair) for pair in sorted(accepted_pairs or set())],
            "missing_pair_ids": [pair_id(pair) for pair in sorted(missing_pairs or set())],
            "foreign_pair_ids": sorted(foreign_pair_ids or []),
            "duplicate_pair_ids": sorted(duplicate_pair_ids or []),
            "malformed_decision_indexes": sorted(malformed_decision_indexes or []),
            "invalid_verdict_pair_ids": sorted(invalid_verdict_pair_ids or []),
            "response_diagnostics": dict(diagnostics),
            "parsed_response": dict(payload or {}),
        }
        batch_artifacts.append(artifact)
        if batch_checkpoint is not None:
            batch_checkpoint(dict(artifact))
        return artifact

    def validate_batch_payload(
        task: Mapping[str, Any],
        payload: Mapping[str, Any],
        diagnostics: Mapping[str, Any],
    ) -> dict[str, Any]:
        expected = set(task.get("batch_pairs") or set())
        expected_pair_ids = [pair_id(pair) for pair in sorted(expected)]
        batch_id = _text(task.get("batch_id"))
        base_diagnostics = {
            "batch_id": batch_id,
            "repair_of_batch_id": _text(task.get("repair_of_batch_id")),
            "attempt": int(task.get("attempt") or 0),
            **dict(diagnostics),
            "top_level_keys": sorted(payload.keys()),
        }
        if payload.get("schema_version") != ALIGNMENT_BATCH_RESULT_SCHEMA_VERSION:
            return {"status": "PENDING_ROOT_PROTOCOL_INVALID", "reason_codes": ["ALIGNMENT_ROOT_PROTOCOL_INVALID"], "missing_pairs": expected, "diagnostics": base_diagnostics}
        if (
            _text(payload.get("alignment_run_id")) != alignment_run_id
            or _text(payload.get("batch_id")) != batch_id
        ):
            return {"status": "PENDING_RESPONSE_INCOMPLETE", "reason_codes": ["ALIGNMENT_BATCH_ID_MISMATCH"], "missing_pairs": expected, "diagnostics": base_diagnostics}
        echoed_pairs = payload.get("expected_pair_ids")
        if (
            not isinstance(echoed_pairs, list)
            or len(echoed_pairs) != len(expected_pair_ids)
            or {_text(item) for item in echoed_pairs} != set(expected_pair_ids)
        ):
            return {"status": "PENDING_RESPONSE_INCOMPLETE", "reason_codes": ["ALIGNMENT_EXPECTED_PAIR_SET_MISMATCH"], "missing_pairs": expected, "diagnostics": base_diagnostics}
        raw_decisions = payload.get("decisions")
        if not isinstance(raw_decisions, list):
            return {"status": "PENDING_ROOT_PROTOCOL_INVALID", "reason_codes": ["ALIGNMENT_ROOT_PROTOCOL_INVALID"], "missing_pairs": expected, "diagnostics": base_diagnostics}
        accepted: dict[tuple[str, str], Mapping[str, Any]] = {}
        foreign_pair_ids: list[str] = []
        duplicate_pair_ids: list[str] = []
        malformed_indexes: list[int] = []
        invalid_verdict_pair_ids: list[str] = []
        invalid_pairs: set[tuple[str, str]] = set()
        for index, raw in enumerate(raw_decisions):
            if not isinstance(raw, Mapping):
                malformed_indexes.append(index)
                continue
            pair = parse_pair_id(raw.get("pair_id"))
            if pair is None:
                malformed_indexes.append(index)
                continue
            identifier = pair_id(pair)
            if pair not in expected:
                foreign_pair_ids.append(identifier)
                continue
            if pair in accepted or pair in invalid_pairs:
                duplicate_pair_ids.append(identifier)
                invalid_pairs.add(pair)
                accepted.pop(pair, None)
                continue
            verdict = _text(raw.get("verdict")).upper()
            if verdict not in ALIGNMENT_VERDICTS:
                invalid_verdict_pair_ids.append(identifier)
                invalid_pairs.add(pair)
                continue
            accepted[pair] = raw
        missing = expected - set(accepted)
        response_codes: list[str] = []
        if not raw_decisions:
            response_codes.append("ALIGNMENT_RESPONSE_EMPTY")
        if foreign_pair_ids:
            response_codes.append("ALIGNMENT_FOREIGN_PROPOSITION_ID")
        if duplicate_pair_ids:
            response_codes.append("ALIGNMENT_DUPLICATE_PAIR")
        if malformed_indexes:
            response_codes.append("ALIGNMENT_DECISION_MALFORMED")
        if invalid_verdict_pair_ids:
            response_codes.append("ALIGNMENT_VERDICT_INVALID")
        if missing:
            response_codes.append("ALIGNMENT_PAIR_TERMINAL_MISSING")
        return {
            "status": "COMPLETE" if not missing else "PENDING_RESPONSE_INCOMPLETE",
            "reason_codes": list(dict.fromkeys(response_codes)),
            "accepted": accepted,
            "missing_pairs": missing,
            "foreign_pair_ids": foreign_pair_ids,
            "duplicate_pair_ids": duplicate_pair_ids,
            "malformed_decision_indexes": malformed_indexes,
            "invalid_verdict_pair_ids": invalid_verdict_pair_ids,
            "diagnostics": base_diagnostics,
        }

    recovered_batch_ids: set[str] = set()
    for raw_batch in prior_batch_artifacts or []:
        if not isinstance(raw_batch, Mapping):
            continue
        if any((
            raw_batch.get("schema_version")
            != ALIGNMENT_BATCH_ARTIFACT_SCHEMA_VERSION,
            _text(raw_batch.get("alignment_artifact_id")) != alignment_run_id,
        )):
            continue
        batch_id = _text(raw_batch.get("batch_id"))
        raw_expected_pair_ids = raw_batch.get("expected_pair_ids")
        payload = raw_batch.get("parsed_response")
        if not batch_id or not isinstance(raw_expected_pair_ids, list) or not isinstance(payload, Mapping):
            continue
        recovered_pairs = {
            pair
            for value in raw_expected_pair_ids
            if (pair := parse_pair_id(value)) is not None
        }
        if not recovered_pairs or not recovered_pairs.issubset(expected_pairs):
            continue
        task = {
            "batch_id": batch_id,
            "batch_pairs": recovered_pairs,
            "repair_of_batch_id": _text(raw_batch.get("repair_of_batch_id")),
            "attempt": int(raw_batch.get("attempt") or 0),
        }
        validation = validate_batch_payload(
            task,
            dict(payload),
            dict(raw_batch.get("response_diagnostics") or {}),
        )
        accepted = dict(validation.get("accepted") or {})
        if not accepted:
            continue
        for pair, raw in accepted.items():
            decision = materialize_decision(pair, raw)
            decisions_by_pair[pair] = decision
            present_pairs.add(pair)
            if _text(decision.get("terminal_status")) == "TERMINAL":
                terminal_pairs.add(pair)
        batch_artifacts.append(dict(raw_batch))
        recovered_batch_ids.add(
            _text(raw_batch.get("repair_of_batch_id"))
            or batch_id.split("_repair_", 1)[0]
        )
        batch_diagnostics.append({
            "batch_id": batch_id,
            "status": "RESUMED",
            "expected_pair_count": len(recovered_pairs),
            "accepted_pair_count": len(accepted),
            "missing_pair_count": len(validation.get("missing_pairs") or []),
        })

    batch_tasks: list[dict[str, Any]] = []
    for offset in range(0, len(propositions), MAX_ALIGNMENT_BATCH):
        source_batch = propositions[offset:offset + MAX_ALIGNMENT_BATCH]
        base_batch_id = f"alignment_{offset // MAX_ALIGNMENT_BATCH + 1:04d}"
        batch_pairs = {
            (_text(proposition.get("proposition_id")), slot_id)
            for proposition in source_batch
            for slot_id in required_slots
            if (_text(proposition.get("proposition_id")), slot_id)
            not in decisions_by_pair
        }
        if not batch_pairs:
            continue
        batch = [
            proposition for proposition in source_batch
            if any(
                (_text(proposition.get("proposition_id")), slot_id) in batch_pairs
                for slot_id in required_slots
            )
        ]
        was_resumed = base_batch_id in recovered_batch_ids
        batch_tasks.append({
            "batch_index": offset // MAX_ALIGNMENT_BATCH,
            "batch_id": (
                f"{base_batch_id}_resume_1" if was_resumed else base_batch_id
            ),
            "batch": batch,
            "candidate_id": (
                _text(batch[0].get("paper_id")) if batch else document_version_id
            ),
            "batch_pairs": batch_pairs,
            "repair_of_batch_id": base_batch_id if was_resumed else "",
            "attempt": 1 if was_resumed else 0,
        })

    repair_tasks: list[dict[str, Any]] = []
    for task, raw_result, error in run_batch_tasks(batch_tasks):
        batch_pairs = set(task.get("batch_pairs") or set())
        batch_id = _text(task.get("batch_id"))
        if error is not None:
            if isinstance(error, LLMJSONProtocolError):
                diagnostics = dict(error.diagnostics)
                if error.code.endswith("_RESPONSE_TRUNCATED"):
                    terminal_status = "PENDING_RESPONSE_TRUNCATED"
                    reason_codes = ["ALIGNMENT_RESPONSE_TRUNCATED"]
                    response_truncated_pairs.update(batch_pairs)
                elif error.code.endswith("_EMPTY"):
                    diagnostics["error_code"] = error.code
                    validation = {
                        "status": "PENDING_RESPONSE_INCOMPLETE",
                        "reason_codes": ["ALIGNMENT_RESPONSE_EMPTY"],
                        "missing_pairs": batch_pairs,
                        "diagnostics": diagnostics,
                    }
                    batch_diagnostics.append({
                        "batch_id": batch_id,
                        "status": validation["status"],
                        "error_code": error.code,
                        **diagnostics,
                    })
                    batch_artifact(task, status=validation["status"], diagnostics=diagnostics, missing_pairs=batch_pairs)
                    repair_tasks.append({
                        **task,
                        "batch_id": f"{batch_id}_repair_1",
                        "repair_of_batch_id": batch_id,
                        "attempt": 1,
                    })
                    continue
                else:
                    terminal_status = "PENDING_ROOT_PROTOCOL_INVALID"
                    reason_codes = ["ALIGNMENT_ROOT_PROTOCOL_INVALID"]
                    root_protocol_invalid_pairs.update(batch_pairs)
                failures.append(f"{error.code}:{batch_id}")
                batch_diagnostics.append({
                    "batch_id": batch_id,
                    "status": terminal_status,
                    "error_code": error.code,
                    **diagnostics,
                })
            elif isinstance(error, ValueError):
                terminal_status = "PENDING_ROOT_PROTOCOL_INVALID"
                reason_codes = ["ALIGNMENT_ROOT_PROTOCOL_INVALID"]
                root_protocol_invalid_pairs.update(batch_pairs)
                failures.append(f"LLM_SLOT_ALIGNMENT_ROOT_INVALID:{batch_id}")
                batch_diagnostics.append({
                    "batch_id": batch_id,
                    "status": terminal_status,
                    "error_type": type(error).__name__,
                })
            else:
                terminal_status = "PENDING_TRANSPORT"
                reason_codes = ["ALIGNMENT_TRANSPORT_PENDING"]
                transport_pending_pairs.update(batch_pairs)
                failures.append(
                    f"LLM_SLOT_ALIGNMENT_TRANSPORT_FAILED:{batch_id}:{type(error).__name__}"
                )
                batch_diagnostics.append({
                    "batch_id": batch_id,
                    "status": terminal_status,
                    "error_type": type(error).__name__,
                })
            artifact_diagnostics = (
                {**dict(error.diagnostics), "error_code": error.code}
                if isinstance(error, LLMJSONProtocolError)
                else {"error_type": type(error).__name__}
            )
            batch_artifact(
                task,
                status=terminal_status,
                diagnostics=artifact_diagnostics,
                missing_pairs=batch_pairs,
            )
            append_pending(task, batch_pairs, terminal_status=terminal_status, reason_codes=reason_codes)
            continue
        payload, diagnostics = unpack_llm_result(raw_result)
        validation = validate_batch_payload(task, payload, diagnostics)
        accepted = dict(validation.get("accepted") or {})
        for pair, raw in accepted.items():
            decision = materialize_decision(pair, raw)
            decisions_by_pair[pair] = decision
            present_pairs.add(pair)
            if _text(decision.get("terminal_status")) == "TERMINAL":
                terminal_pairs.add(pair)
        missing = set(validation.get("missing_pairs") or set())
        status = _text(validation.get("status"))
        diagnostic = dict(validation.get("diagnostics") or {})
        batch_diagnostics.append({
            "batch_id": batch_id,
            "status": status,
            "expected_pair_count": len(batch_pairs),
            "accepted_pair_count": len(accepted),
            "missing_pair_count": len(missing),
            "reason_codes": list(validation.get("reason_codes") or []),
            **diagnostic,
        })
        batch_artifact(
            task,
            status=status,
            diagnostics=diagnostic,
            payload=payload,
            accepted_pairs=set(accepted),
            missing_pairs=missing,
            foreign_pair_ids=list(validation.get("foreign_pair_ids") or []),
            duplicate_pair_ids=list(validation.get("duplicate_pair_ids") or []),
            malformed_decision_indexes=list(validation.get("malformed_decision_indexes") or []),
            invalid_verdict_pair_ids=list(validation.get("invalid_verdict_pair_ids") or []),
        )
        if status == "PENDING_ROOT_PROTOCOL_INVALID":
            failures.append(f"LLM_SLOT_ALIGNMENT_ROOT_INVALID:{batch_id}")
            root_protocol_invalid_pairs.update(batch_pairs)
            append_pending(task, batch_pairs, terminal_status=status, reason_codes=list(validation.get("reason_codes") or []))
        elif missing:
            repair_proposition_ids = {proposition_id for proposition_id, _ in missing}
            repair_tasks.append({
                **task,
                "batch_id": f"{batch_id}_repair_1",
                "batch": [
                    proposition for proposition in task["batch"]
                    if _text(proposition.get("proposition_id")) in repair_proposition_ids
                ],
                "batch_pairs": missing,
                "repair_of_batch_id": batch_id,
                "attempt": 1,
            })

    for task, raw_result, error in run_batch_tasks(repair_tasks):
        batch_pairs = set(task.get("batch_pairs") or set())
        batch_id = _text(task.get("batch_id"))
        if error is not None:
            terminal_status = "PENDING_TRANSPORT"
            reason_codes = ["ALIGNMENT_TRANSPORT_PENDING", "ALIGNMENT_REPAIR_EXHAUSTED"]
            if isinstance(error, LLMJSONProtocolError):
                if error.code.endswith("_RESPONSE_TRUNCATED"):
                    terminal_status = "PENDING_RESPONSE_TRUNCATED"
                    reason_codes = ["ALIGNMENT_RESPONSE_TRUNCATED", "ALIGNMENT_REPAIR_EXHAUSTED"]
                    response_truncated_pairs.update(batch_pairs)
                else:
                    terminal_status = "PENDING_ROOT_PROTOCOL_INVALID"
                    reason_codes = ["ALIGNMENT_ROOT_PROTOCOL_INVALID", "ALIGNMENT_REPAIR_EXHAUSTED"]
                    root_protocol_invalid_pairs.update(batch_pairs)
            else:
                transport_pending_pairs.update(batch_pairs)
            failures.append(f"ALIGNMENT_REPAIR_FAILED:{batch_id}:{type(error).__name__}")
            diagnostics = (
                {**dict(error.diagnostics), "error_code": error.code}
                if isinstance(error, LLMJSONProtocolError)
                else {"error_type": type(error).__name__}
            )
            batch_diagnostics.append({"batch_id": batch_id, "status": terminal_status, "repair_exhausted": True, **diagnostics})
            batch_artifact(task, status=terminal_status, diagnostics=diagnostics, missing_pairs=batch_pairs)
            append_pending(task, batch_pairs, terminal_status=terminal_status, reason_codes=reason_codes)
            continue
        payload, diagnostics = unpack_llm_result(raw_result)
        validation = validate_batch_payload(task, payload, diagnostics)
        accepted = dict(validation.get("accepted") or {})
        for pair, raw in accepted.items():
            decision = materialize_decision(pair, raw)
            decisions_by_pair[pair] = decision
            present_pairs.add(pair)
            if _text(decision.get("terminal_status")) == "TERMINAL":
                terminal_pairs.add(pair)
        unresolved = set(validation.get("missing_pairs") or set())
        status = _text(validation.get("status"))
        diagnostic = dict(validation.get("diagnostics") or {})
        batch_diagnostics.append({
            "batch_id": batch_id,
            "status": status,
            "repair_exhausted": bool(unresolved),
            "expected_pair_count": len(batch_pairs),
            "accepted_pair_count": len(accepted),
            "missing_pair_count": len(unresolved),
            "reason_codes": list(validation.get("reason_codes") or []),
            **diagnostic,
        })
        batch_artifact(
            task,
            status=status,
            diagnostics=diagnostic,
            payload=payload,
            accepted_pairs=set(accepted),
            missing_pairs=unresolved,
            foreign_pair_ids=list(validation.get("foreign_pair_ids") or []),
            duplicate_pair_ids=list(validation.get("duplicate_pair_ids") or []),
            malformed_decision_indexes=list(validation.get("malformed_decision_indexes") or []),
            invalid_verdict_pair_ids=list(validation.get("invalid_verdict_pair_ids") or []),
        )
        if status == "PENDING_ROOT_PROTOCOL_INVALID":
            root_protocol_invalid_pairs.update(batch_pairs)
            failures.append(f"ALIGNMENT_REPAIR_ROOT_INVALID:{batch_id}")
            append_pending(
                task,
                batch_pairs,
                terminal_status="PENDING_ROOT_PROTOCOL_INVALID",
                reason_codes=[
                    *list(validation.get("reason_codes") or []),
                    "ALIGNMENT_REPAIR_EXHAUSTED",
                ],
            )
        elif unresolved:
            response_incomplete_pairs.update(unresolved)
            failures.append(f"ALIGNMENT_REPAIR_EXHAUSTED:{batch_id}")
            append_pending(
                task,
                unresolved,
                terminal_status="PENDING_RESPONSE_INCOMPLETE",
                reason_codes=[*list(validation.get("reason_codes") or []), "ALIGNMENT_REPAIR_EXHAUSTED"],
            )

    runtime_unassigned_pairs = expected_pairs - set(decisions_by_pair)
    if runtime_unassigned_pairs:
        failures.append("ALIGNMENT_RUNTIME_PAIR_UNASSIGNED")
        response_incomplete_pairs.update(runtime_unassigned_pairs)
        append_pending(
            {"batch_id": "alignment_runtime_unassigned"},
            runtime_unassigned_pairs,
            terminal_status="PENDING_RESPONSE_INCOMPLETE",
            reason_codes=["ALIGNMENT_RUNTIME_PAIR_UNASSIGNED"],
        )
    missing_pairs = set(response_incomplete_pairs)

    decisions = [
        decisions_by_pair[pair]
        for pair in sorted(decisions_by_pair)
    ]
    question = (
        contract.get("research_question")
        if isinstance(contract.get("research_question"), Mapping)
        else {}
    )
    supports: list[dict[str, Any]] = []
    for decision in decisions:
        proposition_id = decision["proposition_id"]
        slot_id = decision["slot_id"]
        proposition = propositions_by_id[proposition_id]
        assertion_id = "assert_" + uuid5(
            NAMESPACE_URL,
            "|".join((
                proposition_id,
                contract_id,
                revision,
                declaration_hash,
                research_question_task_id,
                alignment_scope_revision,
            )),
        ).hex[:24]
        support_id = "support_" + uuid5(
            NAMESPACE_URL, f"{assertion_id}|{slot_id}"
        ).hex[:24]
        verdict = decision["verdict"]
        support_status = (
            "VERIFIED_NONCOUNTING"
            if (
                verdict in POSITIVE_ALIGNMENT_VERDICTS
                and _text(decision.get("source_entailment_verdict")) == "ENTAILED"
            )
            else "NO_MATCH" if verdict == "NO_MATCH" else "PENDING"
        )
        supports.append({
            "schema_version": SLOT_SUPPORT_SCHEMA_VERSION,
            "slot_support_id": support_id,
            "assertion_id": assertion_id,
            "proposition_id": proposition_id,
            "paper_id": _text(proposition.get("paper_id")),
            "document_version_hash": _text(proposition.get("document_version_hash")),
            "source_span_ids": list(proposition.get("source_span_ids") or []),
            "research_question_contract_id": contract_id,
            "research_question_contract_revision": revision,
            "research_question_contract_hash": declaration_hash,
            "research_question_task_id": research_question_task_id,
            "alignment_scope_id": alignment_scope_id,
            "alignment_scope_revision": alignment_scope_revision,
            "question_kind": _text(question.get("question_kind")),
            "slot_id": slot_id,
            "alignment_verdict": verdict,
            "source_entailment_verdict": _text(
                decision.get("source_entailment_verdict")
            ),
            "source_entailment_reason": _text(
                decision.get("source_entailment_reason")
            ),
            "support_relation": verdict,
            "source_anchor": decision.get("source_anchor") or {},
            "contract_anchor": decision.get("contract_anchor") or {},
            "scope_mapping": [],
            "alignment_confidence": decision.get("alignment_confidence"),
            "alignment_method": "llm_complete_pair_matrix_v1",
            "validator_verdict": (
                "VERIFIED_SOURCE_BOUND"
                if (
                    _text(decision.get("source_entailment_verdict")) == "ENTAILED"
                    and verdict in POSITIVE_ALIGNMENT_VERDICTS
                )
                else "SOURCE_BOUND_NO_MATCH"
                if (
                    _text(decision.get("source_entailment_verdict")) == "ENTAILED"
                    and verdict == "NO_MATCH"
                )
                else "PENDING"
            ),
            "support_status": support_status,
            "terminal_status": _text(decision.get("terminal_status")),
            "retry_batch_id": _text(decision.get("retry_batch_id")),
            "admission_status": "PROJECT_CONTEXT_ONLY",
            "reason_codes": list(decision.get("reason_codes") or []),
            "counts_toward_gate": False,
            "direct_slot_eligible": False,
            "source_locations": list(proposition.get("source_locations") or []),
            "source_evidence": dict(decision.get("source_evidence") or {}),
        })

    supports_by_proposition: dict[str, list[dict[str, Any]]] = {}
    for support in supports:
        if (
            support.get("alignment_verdict") in POSITIVE_ALIGNMENT_VERDICTS
            and _text(support.get("source_entailment_verdict")) == "ENTAILED"
        ):
            supports_by_proposition.setdefault(
                _text(support.get("proposition_id")), []
            ).append(support)
    arm_observations_by_proposition = {
        proposition_id: _benchmark_arm_observations(proposition, contract)
        for proposition_id, proposition in propositions_by_id.items()
        if _proposition_entailment(proposition)[0] == "ENTAILED"
    }
    assertions: list[dict[str, Any]] = []
    assertion_proposition_ids = sorted({
        *supports_by_proposition,
        *(proposition_id for proposition_id, observations in arm_observations_by_proposition.items() if observations),
        *(
            proposition_id
            for proposition_id, observations in benchmark_observations_by_proposition.items()
            if observations.get("arm_matches")
        ),
    })
    for proposition_id in assertion_proposition_ids:
        proposition = propositions_by_id[proposition_id]
        proposition_supports = supports_by_proposition.get(proposition_id, [])
        assertion_id = (
            proposition_supports[0]["assertion_id"]
            if proposition_supports else "assert_" + uuid5(
                NAMESPACE_URL,
                "|".join((
                    proposition_id, contract_id, revision, declaration_hash,
                    research_question_task_id, alignment_scope_revision,
                )),
            ).hex[:24]
        )
        arm_observations = arm_observations_by_proposition.get(proposition_id, [])
        benchmark_observations = dict(
            benchmark_observations_by_proposition.get(proposition_id) or {}
        )
        combined_arm_observations = [
            *benchmark_observations.get("arm_matches", []),
            *arm_observations,
        ]
        seen_arm_observations: set[tuple[str, str, str]] = set()
        benchmark_observations["arm_matches"] = []
        for observation in combined_arm_observations:
            if not isinstance(observation, Mapping):
                continue
            anchor = observation.get("source_anchor")
            anchor = anchor if isinstance(anchor, Mapping) else {}
            identity = (
                _text(observation.get("arm_id")),
                _text(anchor.get("source_span_id")),
                _text(anchor.get("text")),
            )
            if identity in seen_arm_observations:
                continue
            seen_arm_observations.add(identity)
            benchmark_observations["arm_matches"].append(dict(observation))
        primary_source_evidence: dict[str, Any] = {}
        if proposition_supports:
            primary_source_evidence = dict(
                proposition_supports[0].get("source_evidence") or {}
            )
        elif arm_observations:
            primary_source_evidence = dict(
                arm_observations[0].get("source_evidence") or {}
            )
        if not primary_source_evidence:
            anchored_spans = {
                _text((item.get("source_anchor") or {}).get("source_span_id"))
                for item in benchmark_observations.get("arm_matches") or []
                if isinstance(item, Mapping)
            }
            primary_source_evidence = next(
                (
                    dict(item)
                    for item in proposition.get("source_evidence", [])
                    if isinstance(item, Mapping)
                    and _text(item.get("source_span_id")) in anchored_spans
                ),
                next(
                    (
                        dict(item)
                        for item in proposition.get("source_evidence", [])
                        if isinstance(item, Mapping)
                    ),
                    {},
                ),
            )
        assertions.append({
            "schema_version": EVIDENCE_ASSERTION_SCHEMA_VERSION,
            "assertion_id": assertion_id,
            "proposition_id": proposition_id,
            "paper_id": proposition.get("paper_id"),
            "document_version_hash": proposition.get("document_version_hash"),
            "source_span_ids": list(proposition.get("source_span_ids") or []),
            "source_unit_ids": list(proposition.get("source_unit_ids") or []),
            "sub_hypothesis_id": _text(contract.get("sub_hypothesis_id")),
            "research_question_contract_id": contract_id,
            "research_question_contract_revision": revision,
            "research_question_contract_hash": declaration_hash,
            "research_question_task_id": research_question_task_id,
            "alignment_scope_id": alignment_scope_id,
            "alignment_scope_revision": alignment_scope_revision,
            "question_kind": _text(question.get("question_kind")),
            "exact_quote": primary_source_evidence.get("exact_quote"),
            "canonical_statement": proposition.get("canonical_statement"),
            "scientific_proposition_fields": dict(proposition.get("fields") or {}),
            "claim_role": proposition.get("claim_role"),
            "assertion_kinds": list(proposition.get("assertion_kinds") or []),
            "relation_kind": proposition.get("relation_kind"),
            "polarity": proposition.get("polarity"),
            "modality": proposition.get("modality"),
            "attribution": proposition.get("attribution"),
            "claim_completeness": proposition.get("claim_completeness"),
            "claim_scope": proposition.get("claim_scope"),
            "specialized_fields": dict(proposition.get("specialized_fields") or {}),
            "structure_anchors": list(proposition.get("structure_anchors") or []),
            "section_heading": proposition.get("section_heading"),
            "quantities": list(proposition.get("quantities") or []),
            "normalization": dict(proposition.get("normalization") or {}),
            "semantic_entailment": {
                "schema_version": "semantic_entailment_status_v1",
                "verdict": _proposition_entailment(proposition)[0],
                "method": _text((proposition.get("semantic_entailment") or {}).get("method")),
                "reason": _proposition_entailment(proposition)[1],
            },
            "slot_support": proposition_supports,
            "slot_coverage": {
                slot: any(item.get("slot_id") == slot for item in proposition_supports)
                for slot in required_slots
            },
            "unsupported_slots": sorted(
                set(required_slots)
                - {item["slot_id"] for item in proposition_supports}
            ),
            "extraction_method": proposition.get("extraction_method"),
            "alignment_method": "llm_complete_pair_matrix_v1",
            "model_id": proposition.get("model_id") or _model_id(),
            "prompt_revision": {
                "proposition": proposition.get("prompt_revision"),
                "alignment": SLOT_ALIGNMENT_PROMPT_REVISION,
            },
            "validator_verdict": "VERIFIED_SOURCE_BOUND",
            "validator_reason_codes": (
                ["DOCUMENT_EXTRACTION_PARTIAL"] if partial_document else []
            ),
            "document_extraction_status": extraction_status,
            "document_coverage_complete": not partial_document,
            "partial_gate_eligibility": _partial_gate_eligibility(
                proposition, proposition_supports
            ) if partial_document else {
                "schema_version": "partial_assertion_gate_eligibility_v1",
                "status": "NOT_APPLICABLE_DOCUMENT_COMPLETE",
                "reason_codes": [],
                "assertion_counts_toward_gate": False,
                "admission_may_count": False,
            },
            "direct_slot_eligible": False,
            "counts_toward_gate": False,
            "evidence_family_id": (
                "family_" + uuid5(
                    NAMESPACE_URL,
                    "|".join(sorted(
                        _text(item) for item in proposition.get("component_proposition_ids", [])
                        if _text(item)
                    ) or [proposition_id]),
                ).hex[:24]
            ),
            "deduplication_role": (
                "COMPOSED_DERIVATIVE"
                if _text(proposition.get("composition_level")) == "COMPOSED"
                else "ATOMIC_PRIMARY"
            ),
            "comparison_evidence_v4": {
                "schema_version": "comparison_evidence_v4",
                "evidence_type": (
                    "ARM_EVIDENCE"
                    if benchmark_observations.get("arm_matches") else "SLOT_ALIGNMENT_ONLY"
                ),
                "arm_matches": benchmark_observations.get("arm_matches") or [],
                "metric_observations": benchmark_observations.get("metric_observations") or [],
                "comparability_observations": benchmark_observations.get("comparability_observations") or [],
                "counts_toward_arm_coverage": bool(benchmark_observations.get("arm_matches")),
                "counts_toward_comparison_conclusion": False,
                "direct_pair_comparison": benchmark_observations.get("direct_comparison") or {},
            },
            "source_locations": list(proposition.get("source_locations") or []),
        })

    pending_pairs = [
        decision for decision in decisions if decision.get("verdict") == "PENDING"
    ]
    semantic_entailment_verdicts = {
        _text(decision.get("source_entailment_verdict"))
        for decision in decisions
    }
    semantic_entailment_status = (
        "PASS"
        if semantic_entailment_verdicts == {"ENTAILED"}
        else "PARTIAL"
        if "ENTAILED" in semantic_entailment_verdicts
        else "PENDING"
    )
    slot_status: dict[str, dict[str, Any]] = {}
    for slot_id in required_slots:
        slot_decisions = [
            item for item in decisions if _text(item.get("slot_id")) == slot_id
        ]
        terminal_positive = [
            item for item in slot_decisions
            if _text(item.get("terminal_status")) == "TERMINAL"
            and _text(item.get("verdict")) in POSITIVE_ALIGNMENT_VERDICTS
        ]
        pending_for_slot = [
            item for item in slot_decisions
            if _text(item.get("terminal_status")) != "TERMINAL"
        ]
        slot_status[slot_id] = {
            "status": (
                "SATISFIED_WITH_PENDING_REMAINDER" if terminal_positive and pending_for_slot
                else "SATISFIED" if terminal_positive
                else "PENDING" if pending_for_slot
                else "TERMINAL_NO_POSITIVE_SUPPORT"
            ),
            "terminal_positive_pair_ids": [
                f"{_text(item.get('proposition_id'))}|{slot_id}"
                for item in terminal_positive
            ],
            "pending_pair_ids": [
                f"{_text(item.get('proposition_id'))}|{slot_id}"
                for item in pending_for_slot
            ],
        }
    status = (
        "ALIGNED_PARTIAL_DOCUMENT" if partial_document and not pending_pairs
        else "ALIGNED" if not pending_pairs
        else "PARTIAL"
    )
    reason_codes = list(dict.fromkeys([
        *failures,
        *(["DOCUMENT_EXTRACTION_PARTIAL"] if partial_document else []),
    ]))
    return {
        **artifact_base,
        "status": status,
        "reason_codes": reason_codes,
        "semantic_entailment_status": semantic_entailment_status,
        "expected_pair_ids": [f"{proposition_id}|{slot_id}" for proposition_id, slot_id in sorted(expected_pairs)],
        "present_pair_ids": [f"{proposition_id}|{slot_id}" for proposition_id, slot_id in sorted(present_pairs)],
        "terminal_pair_ids": [f"{proposition_id}|{slot_id}" for proposition_id, slot_id in sorted(terminal_pairs)],
        "returned_pair_ids": [f"{proposition_id}|{slot_id}" for proposition_id, slot_id in sorted(present_pairs)],
        "missing_pair_ids": [f"{proposition_id}|{slot_id}" for proposition_id, slot_id in sorted(missing_pairs)],
        "transport_pending_pair_ids": [
            f"{proposition_id}|{slot_id}"
            for proposition_id, slot_id in sorted(transport_pending_pairs)
        ],
        "response_truncated_pair_ids": [
            f"{proposition_id}|{slot_id}"
            for proposition_id, slot_id in sorted(response_truncated_pairs)
        ],
        "root_protocol_invalid_pair_ids": [
            f"{proposition_id}|{slot_id}"
            for proposition_id, slot_id in sorted(root_protocol_invalid_pairs)
        ],
        "response_incomplete_pair_ids": [
            f"{proposition_id}|{slot_id}"
            for proposition_id, slot_id in sorted(response_incomplete_pairs)
        ],
        "batch_diagnostics": batch_diagnostics,
        "batch_artifacts": batch_artifacts,
        "slot_status": slot_status,
        "whole_contract_alignment_status": "NOT_RUN",
        "alignment_decisions": decisions,
        "slot_supports": supports,
        "assertions": assertions,
    }
