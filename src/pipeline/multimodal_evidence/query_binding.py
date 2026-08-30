"""External epistemic bindings for data-anchored SH query variants."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


SUPPORTED_EPISTEMIC_ROLES = frozenset(
    {
        "support",
        "counter",
        "alternative_explanation",
        "boundary",
        "measurement_confound",
        "discriminating_test",
    }
)


def normalize_query_variant_bindings(value: Any) -> list[dict[str, str]]:
    """Validate outer-only metadata without expanding the SH schema."""

    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("query_variant_bindings must be a list.")
    bindings: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, item in enumerate(value, start=1):
        if not isinstance(item, Mapping):
            raise ValueError(f"query_variant_binding {index} must be an object.")
        binding = {
            "sub_hypothesis_id": _text(item.get("sub_hypothesis_id"), limit=120),
            "slot_name": _text(item.get("slot_name"), limit=160),
            "query_variant_id": _text(item.get("query_variant_id"), limit=80),
            "epistemic_role": _text(item.get("epistemic_role"), limit=80).casefold(),
            "evidence_mode": _text(item.get("evidence_mode"), limit=80).casefold(),
            "required_result": _text(item.get("required_result"), limit=700),
            "claim_id": _text(item.get("claim_id"), limit=120),
        }
        if not all(binding[key] for key in ("sub_hypothesis_id", "slot_name", "query_variant_id", "epistemic_role", "required_result", "claim_id")):
            raise ValueError(f"query_variant_binding {index} has a missing required field.")
        if binding["epistemic_role"] not in SUPPORTED_EPISTEMIC_ROLES:
            raise ValueError(
                f"query_variant_binding {index} has unsupported epistemic_role '{binding['epistemic_role']}'."
            )
        key = (binding["sub_hypothesis_id"], binding["slot_name"], binding["query_variant_id"])
        if key in seen:
            raise ValueError(f"Duplicate query_variant_binding for {'.'.join(key)}.")
        seen.add(key)
        bindings.append(binding)
    return bindings


def query_binding_lookup(value: Any) -> dict[tuple[str, str, str], dict[str, str]]:
    return {
        (binding["sub_hypothesis_id"], binding["slot_name"], binding["query_variant_id"]): binding
        for binding in normalize_query_variant_bindings(value)
    }


def _text(value: Any, *, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]
