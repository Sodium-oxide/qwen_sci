"""Structured failures exposed by role A."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorDetail:
    code: str
    message: str
    field_path: str = ""
    context: dict[str, Any] | None = None


class PowerCoreError(RuntimeError):
    """Base class for deterministic role-A failures."""

    code = "POWER_CORE_ERROR"

    def __init__(self, message: str, *, field_path: str = "", context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = ErrorDetail(self.code, message, field_path, context)


class ContractValidationError(PowerCoreError):
    code = "CONTRACT_VALIDATION_FAILED"


class UnknownSchemaError(PowerCoreError):
    code = "UNKNOWN_SCHEMA"


class UnsafeArtifactPathError(PowerCoreError):
    code = "UNSAFE_ARTIFACT_PATH"


class ImmutableArtifactConflict(PowerCoreError):
    code = "IMMUTABLE_ARTIFACT_CONFLICT"


class IdempotencyConflict(PowerCoreError):
    code = "IDEMPOTENCY_CONFLICT"


class InvalidStateTransition(PowerCoreError):
    code = "INVALID_STATE_TRANSITION"


class StateJournalCorruption(PowerCoreError):
    code = "STATE_JOURNAL_CORRUPTION"


class ApprovalRequired(PowerCoreError):
    code = "APPROVAL_REQUIRED"


class ArtifactIntegrityError(PowerCoreError):
    code = "ARTIFACT_INTEGRITY_FAILED"

