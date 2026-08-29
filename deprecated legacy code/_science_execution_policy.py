"""Single-source execution policy for the scientific evidence pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping


SCIENCE_EXECUTION_POLICY_VERSION = "science_execution_policy_v1"
SCIENCE_LLM_MAX_INFLIGHT = 4


@dataclass(frozen=True)
class ScienceExecutionPolicy:
    schema_version: str = SCIENCE_EXECUTION_POLICY_VERSION
    use_llm: bool = True
    decomposition_mode: str = "llm_primary"
    retrieval_ranking_mode: str = "llm_assisted"
    fulltext_structuring_mode: str = "llm_primary"
    assertion_extraction_mode: str = "llm_primary"
    slot_alignment_mode: str = "llm_primary"
    semantic_audit_mode: str = "llm_primary"
    on_llm_error: str = "defer"
    connect_timeout_seconds: int = 12
    total_timeout_seconds: int = 240
    max_transport_retries: int = 1
    max_inflight: int = SCIENCE_LLM_MAX_INFLIGHT
    deterministic_hints_count_toward_gate: bool = False
    deterministic_hints_direct_slot_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _explicit_project_policy(project: Mapping[str, Any] | None) -> dict[str, Any]:
    source = project if isinstance(project, Mapping) else {}
    value = source.get("science_execution_policy")
    return dict(value) if isinstance(value, Mapping) else {}


def resolve_science_execution_policy(
    project: Mapping[str, Any] | None = None,
    *,
    use_llm: bool | None = None,
) -> ScienceExecutionPolicy:
    """Resolve one immutable policy at the run boundary.

    Runtime override wins over an explicit project policy.  Missing values do
    not consult historic per-stage booleans; the new pipeline defaults to LLM
    primary execution.
    """

    configured = _explicit_project_policy(project)
    configured_use_llm = configured.get("use_llm")
    effective_use_llm = (
        use_llm
        if isinstance(use_llm, bool)
        else configured_use_llm
        if isinstance(configured_use_llm, bool)
        else True
    )
    policy = ScienceExecutionPolicy(
        use_llm=effective_use_llm,
        decomposition_mode=str(configured.get("decomposition_mode") or "llm_primary"),
        retrieval_ranking_mode=str(configured.get("retrieval_ranking_mode") or "llm_assisted"),
        fulltext_structuring_mode=str(configured.get("fulltext_structuring_mode") or "llm_primary"),
        assertion_extraction_mode=str(configured.get("assertion_extraction_mode") or "llm_primary"),
        slot_alignment_mode=str(configured.get("slot_alignment_mode") or "llm_primary"),
        semantic_audit_mode=str(configured.get("semantic_audit_mode") or "llm_primary"),
        connect_timeout_seconds=max(1, int(configured.get("connect_timeout_seconds") or 12)),
        total_timeout_seconds=max(1, int(configured.get("total_timeout_seconds") or 240)),
        max_transport_retries=max(
            0,
            min(
                1,
                int(
                    configured["max_transport_retries"]
                    if isinstance(configured.get("max_transport_retries"), int)
                    else 1
                ),
            ),
        ),
        max_inflight=max(
            1,
            min(
                SCIENCE_LLM_MAX_INFLIGHT,
                int(configured.get("max_inflight") or SCIENCE_LLM_MAX_INFLIGHT),
            ),
        ),
    )
    if not effective_use_llm:
        policy = replace(
            policy,
            decomposition_mode="disabled",
            retrieval_ranking_mode="disabled",
            fulltext_structuring_mode="disabled",
            assertion_extraction_mode="disabled",
            slot_alignment_mode="disabled",
            semantic_audit_mode="disabled",
        )
    return policy


def persist_effective_science_execution_policy(
    project: dict[str, Any],
    policy: ScienceExecutionPolicy,
) -> dict[str, Any]:
    if not isinstance(project, dict):
        raise TypeError("project must be a dictionary")
    project["effective_science_execution_policy"] = policy.to_dict()
    return project
