"""Errors raised by the durable web Job control plane."""

from __future__ import annotations


class JobError(RuntimeError):
    """Base class for Job control-plane errors."""


class JobNotFoundError(JobError):
    """Raised when a Job ID is not registered in the configured store."""


class JobConflictError(JobError):
    """Raised when an idempotency or ownership constraint conflicts."""


class JobStateError(JobError):
    """Raised when an invalid Job state transition is requested."""


class JobLeaseLost(JobStateError):
    """Raised when a worker no longer owns the current execution attempt."""


class JobInputError(JobError):
    """Raised when frozen Job inputs fail integrity validation."""
