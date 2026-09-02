"""Contracts and services for the optional quantitative modeling sidecar."""

from src.agents.quantitative_modeling.contracts import (
    QUANTITATIVE_IDEAS_SCHEMA_VERSION,
    QuantitativeContractError,
)

__all__ = [
    "QUANTITATIVE_IDEAS_SCHEMA_VERSION",
    "QuantitativeContractError",
]
