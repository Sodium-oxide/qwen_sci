"""Strict cross-role adapters owned by role A."""

from .part_b_adapter import (
    b_candidate_to_contract,
    build_validation_report_v2,
    candidate_contract_to_b_object,
    validate_contract_with_part_b,
)

__all__ = [
    "b_candidate_to_contract",
    "build_validation_report_v2",
    "candidate_contract_to_b_object",
    "validate_contract_with_part_b",
]
