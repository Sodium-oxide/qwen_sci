"""Typed retrieval outcomes and capability-aware operator preconditions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping


@dataclass(frozen=True)
class RetrievalResult:
    status: str
    hits: tuple[dict[str, Any], ...] = ()
    provider: str = "paper_graph"
    query: str = ""
    reason: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in {"success", "no_hits", "unavailable", "error", "budget_exhausted"}:
            raise ValueError(f"Unknown retrieval status: {self.status}")
        if (self.status == "success") != bool(self.hits):
            raise ValueError("Only successful retrieval may contain hits; success requires hits.")

    def __bool__(self) -> bool:
        return self.status == "success" and bool(self.hits)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.hits)

    def __len__(self) -> int:
        return len(self.hits)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "hits": list(self.hits), "provider": self.provider,
                "query": self.query, "reason": self.reason, "diagnostics": self.diagnostics}


def retrieve(store: Any, query: str, *, top_k: int, budget_available: bool = True) -> RetrievalResult:
    if not budget_available:
        return RetrievalResult("budget_exhausted", query=query, reason="Retrieval budget exhausted.")
    if not query.strip():
        return RetrievalResult("no_hits", query=query, reason="No eligible query was generated.")
    try:
        hits = tuple(store.search(query=query, top_k=top_k, component_hits_per_core=2))
    except (FileNotFoundError, ImportError) as exc:
        return RetrievalResult("unavailable", query=query, reason=str(exc))
    except Exception as exc:
        return RetrievalResult("error", query=query, reason=str(exc))
    return RetrievalResult("success" if hits else "no_hits", hits=hits, query=query)


def probe_paper_graph(store: Any) -> RetrievalResult | None:
    """Check installed artifacts without initializing embeddings or doing network IO."""
    if store is None:
        return RetrievalResult("unavailable", reason="Paper graph provider is not configured.")
    disabled = getattr(store, "_disabled_error", None)
    if isinstance(disabled, str) and disabled:
        return RetrievalResult("unavailable", reason=disabled)
    index_dir = getattr(store, "index_dir", None)
    if isinstance(index_dir, (str, Path)) and getattr(store, "_index", None) is None:
        from src.paper_graph.artifacts import index_generation
        try:
            generation = index_generation(index_dir)
        except (OSError, ValueError) as exc:
            return RetrievalResult("error", reason=str(exc))
        missing = [str(generation / name) for name in ("faiss.index", "meta.json")
                   if not (generation / name).is_file()]
        if missing:
            return RetrievalResult("unavailable", reason="Missing component index files: " + ", ".join(missing))
    db_path = getattr(store, "db_path", None)
    if isinstance(db_path, (str, Path)) and not Path(db_path).is_file():
        return RetrievalResult("unavailable", reason="Paper graph database not found: " + str(db_path))
    return None


@dataclass
class CapabilityState:
    available: set[str] = field(default_factory=set)
    unavailable: dict[str, str] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    acquisition_requests: list[dict[str, Any]] = field(default_factory=list)

    def record(self, result: RetrievalResult) -> None:
        self.events.append(result.to_dict())
        if result.status == "unavailable":
            self.unavailable[result.provider] = result.reason or "Unavailable"
            self.available.discard(result.provider)
        elif result.status in {"success", "no_hits"}:
            self.unavailable.pop(result.provider, None)
            self.available.add(result.provider)

    def eligible(self, required: list[str]) -> bool:
        return all(capability in self.available and capability not in self.unavailable for capability in required)

    def request(self, result: RetrievalResult, *, skill: str) -> None:
        request = {"skill": skill, "provider": result.provider, "query": result.query,
                   "status": result.status, "reason": result.reason}
        if request not in self.acquisition_requests:
            self.acquisition_requests.append(request)


def operator_retrieval_policy(skill: Any, result: RetrievalResult) -> str:
    if result:
        return "grounded"
    policy = getattr(skill, "evidence_policy", "exploratory")
    return "skip" if policy == "required" else "exploratory"
