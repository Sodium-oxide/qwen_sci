"""Typed registry boundary for trusted PDE solver adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class PDEAdapter(Protocol):
    """Minimal contract implemented by a fixed numerical adapter."""

    solver_id: str

    def __call__(
        self,
        document: Mapping[str, object],
        limits: Mapping[str, int | float],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RegisteredPDEAdapter:
    solver_id: str
    family_ids: tuple[str, ...]
    adapter: Callable[[Mapping[str, object], Mapping[str, int | float]], dict[str, Any]]


class PDEAdapterRegistry:
    """Reject duplicate solver IDs and expose one fixed dispatch boundary."""

    def __init__(self) -> None:
        self._by_family: dict[str, RegisteredPDEAdapter] = {}
        self._by_solver: dict[str, RegisteredPDEAdapter] = {}

    def register(
        self,
        *,
        solver_id: str,
        family_ids: tuple[str, ...],
        adapter: Callable[[Mapping[str, object], Mapping[str, int | float]], dict[str, Any]],
    ) -> None:
        normalized_solver = str(solver_id).strip()
        normalized_families = tuple(dict.fromkeys(str(item).strip() for item in family_ids))
        if not normalized_solver or not normalized_families or any(not item for item in normalized_families):
            raise ValueError("solver_id and family_ids are required")
        if normalized_solver in self._by_solver:
            raise ValueError(f"solver adapter is already registered: {normalized_solver}")
        entry = RegisteredPDEAdapter(normalized_solver, normalized_families, adapter)
        for family_id in normalized_families:
            if family_id in self._by_family:
                raise ValueError(f"PDE family is already registered: {family_id}")
            self._by_family[family_id] = entry
        self._by_solver[normalized_solver] = entry

    def get(self, family_id: str) -> RegisteredPDEAdapter | None:
        return self._by_family.get(str(family_id).strip())

    def contains(self, family_id: str) -> bool:
        return self.get(family_id) is not None

    def families(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_family))


__all__ = ["PDEAdapter", "PDEAdapterRegistry", "RegisteredPDEAdapter"]
