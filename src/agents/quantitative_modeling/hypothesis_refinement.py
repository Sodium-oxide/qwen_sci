"""Human-approved, bounded Q-version refinement driven by qualified simulations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.agents.quantitative_modeling.result_ledger import qualified_ledger_entries, validate_result_ledger
from src.pipeline.science_run import utc_now


HYPOTHESIS_REFINEMENT_PROPOSAL_SCHEMA_VERSION = "quantitative_hypothesis_refinement_v1"
REVISION_ACCEPTANCE_SCHEMA_VERSION = "quantitative_revision_acceptance_v1"


class HypothesisRefinementError(ValueError):
    """Raised when a proposal would bypass human approval or the v2 ceiling."""


def _text(value: object) -> str:
    return str(value or "").strip()


def _text_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise HypothesisRefinementError(f"{field} must be a list")
    values = [_text(item) for item in value]
    if not values or any(not item for item in values):
        raise HypothesisRefinementError(f"{field} must contain non-empty text")
    return list(dict.fromkeys(values))


def build_hypothesis_refinement_proposal(
    *,
    ledger: Mapping[str, object],
    revision_reason: str,
    hypothesis_delta: str,
    model_delta: Sequence[str],
    parameter_or_boundary_delta: Sequence[str],
    expected_discriminating_result: str,
    falsification_condition: str,
) -> dict[str, Any]:
    """Build a proposal only; it cannot alter a Q model or launch execution."""

    normalized_ledger = validate_result_ledger(ledger)
    identity = normalized_ledger["model_identity"]
    parent_version = int(identity["version"])
    if parent_version >= 2:
        raise HypothesisRefinementError("Q@v2 is the final permitted version; v3 cannot be proposed")
    qualified = qualified_ledger_entries(normalized_ledger)
    if not qualified:
        raise HypothesisRefinementError("only a ledger with qualified results can support a revision proposal")
    reason = _text(revision_reason)
    if not reason:
        raise HypothesisRefinementError("revision_reason is required")
    normalized_hypothesis_delta = _text(hypothesis_delta)
    normalized_expected_result = _text(expected_discriminating_result)
    normalized_falsification = _text(falsification_condition)
    if not normalized_hypothesis_delta or not normalized_expected_result or not normalized_falsification:
        raise HypothesisRefinementError(
            "hypothesis_delta, expected_discriminating_result, and falsification_condition are required"
        )
    return {
        "schema_version": HYPOTHESIS_REFINEMENT_PROPOSAL_SCHEMA_VERSION,
        "created_at": utc_now(),
        "quantitative_idea_id": identity["quantitative_idea_id"],
        "parent_version": parent_version,
        "proposed_version": parent_version + 1,
        "revision_reason": reason,
        "qualified_result_references": [entry["execution_id"] for entry in qualified],
        "relation_summary": list(dict.fromkeys(entry["hypothesis_relation"] for entry in qualified)),
        "hypothesis_delta": normalized_hypothesis_delta,
        "model_delta": _text_list(model_delta, field="model_delta"),
        "parameter_or_boundary_delta": _text_list(
            parameter_or_boundary_delta,
            field="parameter_or_boundary_delta",
        ),
        "expected_discriminating_result": normalized_expected_result,
        "falsification_condition": normalized_falsification,
        "requires_new_execution": True,
        "approval_status": "PROPOSED",
    }


def accept_hypothesis_refinement_proposal(
    proposal: Mapping[str, object], *, accept: bool
) -> dict[str, Any]:
    """Return the immutable acceptance record; rejected proposals stay unchanged."""

    if not accept:
        raise HypothesisRefinementError("revision proposal was not accepted; no Q version was created")
    payload = dict(proposal)
    if payload.get("schema_version") != HYPOTHESIS_REFINEMENT_PROPOSAL_SCHEMA_VERSION:
        raise HypothesisRefinementError("unsupported refinement proposal schema")
    if payload.get("approval_status") != "PROPOSED" or payload.get("requires_new_execution") is not True:
        raise HypothesisRefinementError("only an unmodified proposed revision requiring new execution can be accepted")
    parent_version = int(payload.get("parent_version", -1))
    proposed_version = int(payload.get("proposed_version", -1))
    if parent_version < 0 or parent_version >= 2 or proposed_version != parent_version + 1:
        raise HypothesisRefinementError("revision proposal violates the Q@v0 -> v1 -> v2 ceiling")
    return {
        "schema_version": REVISION_ACCEPTANCE_SCHEMA_VERSION,
        "accepted_at": utc_now(),
        "quantitative_idea_id": _text(payload.get("quantitative_idea_id")),
        "parent_version": parent_version,
        "version": proposed_version,
        "proposal_schema_version": HYPOTHESIS_REFINEMENT_PROPOSAL_SCHEMA_VERSION,
        "proposal_created_at": _text(payload.get("created_at")),
        "requires_new_execution": True,
        "approval_status": "ACCEPTED",
    }


__all__ = [
    "HYPOTHESIS_REFINEMENT_PROPOSAL_SCHEMA_VERSION",
    "REVISION_ACCEPTANCE_SCHEMA_VERSION",
    "HypothesisRefinementError",
    "accept_hypothesis_refinement_proposal",
    "build_hypothesis_refinement_proposal",
]
