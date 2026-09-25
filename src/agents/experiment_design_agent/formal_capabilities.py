"""Capability metadata for formal verification backends.

The registry is deliberately declarative.  It describes what a backend claims
to check; it does not promote a result to a stronger epistemic status.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


CAPABILITY_SCHEMA_VERSION = "formal_backend_capabilities_v1"

VERIFICATION_LEVELS = {
    "kernel_verified",
    "solver_verified",
    "rule_verified",
    "bounded_checked",
    "proof_draft",
    "unresolved",
}


_BACKENDS: dict[str, dict[str, Any]] = {
    "z3": {
        "backend": "z3",
        "verification_level": "solver_verified",
        "verification_method": "smt_unsat_or_witness",
        "certificate": False,
        "supports": {
            "sorts": ["real", "integer", "boolean"],
            "quantifiers": ["forall"],
            "operators": [
                "add", "sub", "mul", "div", "pow", "eq", "ne", "lt",
                "le", "gt", "ge", "and", "or", "not", "implies", "iff",
                "xor", "ite",
            ],
        },
    },
    "sympy": {
        "backend": "sympy",
        "verification_level": "solver_verified",
        "verification_method": "symbolic_identity_or_conditional_identity",
        "certificate": False,
        "supports": {
            "sorts": ["real", "integer"],
            "quantifiers": ["forall"],
            "operators": [
                "add", "sub", "mul", "div", "pow", "eq", "ne", "lt",
                "le", "gt", "ge", "and", "or", "not", "implies", "iff",
                "xor", "ite",
            ],
        },
    },
    "numerical": {
        "backend": "numerical",
        "verification_level": "bounded_checked",
        "verification_method": "candidate_point_search",
        "certificate": False,
        "supports": {
            "sorts": ["real", "integer"],
            "quantifiers": ["forall"],
            "operators": [
                "add", "sub", "mul", "div", "pow", "eq", "ne", "lt",
                "le", "gt", "ge", "and", "or", "not", "implies", "iff",
                "xor", "ite",
            ],
        },
    },
    "rules": {
        "backend": "rules",
        "verification_level": "rule_verified",
        "verification_method": "trusted_local_rule_set",
        "certificate": False,
        "supports": {
            "sorts": ["real", "integer", "boolean"],
            "quantifiers": ["forall"],
            "operators": [
                "add", "sub", "mul", "div", "pow", "eq", "ne", "lt",
                "le", "gt", "ge", "and", "or", "not", "implies", "iff",
                "xor", "ite",
            ],
        },
    },
    "lean": {
        "backend": "lean",
        "verification_level": "kernel_verified",
        "verification_method": "lean_kernel",
        "certificate": True,
        "supports": {
            "sorts": ["declared_by_theorem"],
            "quantifiers": ["declared_by_theorem"],
            "operators": ["declared_by_theorem"],
        },
    },
}


def backend_capabilities(backend: str) -> dict[str, Any]:
    """Return a defensive copy of one backend's declared capabilities."""

    try:
        return deepcopy(_BACKENDS[str(backend)])
    except KeyError as error:
        raise ValueError(f"unknown_formal_backend:{backend}") from error


def all_backend_capabilities() -> dict[str, dict[str, Any]]:
    """Return all registered capabilities for diagnostics and planning."""

    return deepcopy(_BACKENDS)


def result_metadata(backend: str, *, coverage: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build stable metadata embedded in a verification result."""

    capabilities = backend_capabilities(backend)
    return {
        "verification_level": capabilities["verification_level"],
        "verification_method": capabilities["verification_method"],
        "certificate": bool(capabilities["certificate"]),
        "coverage": deepcopy(coverage or capabilities["supports"]),
    }


def is_registered_backend(backend: str) -> bool:
    return str(backend) in _BACKENDS


__all__ = [
    "CAPABILITY_SCHEMA_VERSION",
    "VERIFICATION_LEVELS",
    "all_backend_capabilities",
    "backend_capabilities",
    "is_registered_backend",
    "result_metadata",
]
