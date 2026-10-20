"""Budgeted, lossless review packets; compact selection views live separately."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from src.agents.idea_agent.utils.mcts.review_contracts import canonical_json, content_hash, scientific_content


def token_bound(text: str) -> int:
    """Conservative UTF-8 byte bound; offline and independent of tokenizer caches."""
    return len(text.encode("utf-8"))


def _leaves(value: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, Mapping) and value:
        return [leaf for key, child in value.items() for leaf in _leaves(child, f"{path}.{key}" if path else str(key))]
    if isinstance(value, list) and value:
        return [leaf for i, child in enumerate(value) for leaf in _leaves(child, f"{path}[{i}]")]
    return [(path, value if isinstance(value, str) else canonical_json(value))]


@dataclass(frozen=True)
class ReviewPacket:
    text: str
    included_paths: tuple[str, ...]
    omitted_paths: tuple[str, ...]
    partial_paths: tuple[str, ...]
    content_hash: str

    @property
    def complete(self) -> bool:
        return not self.omitted_paths and not self.partial_paths

    def coverage(self) -> dict[str, Any]:
        return {"included_paths": list(self.included_paths), "omitted_paths": list(self.omitted_paths),
                "partial_paths": list(self.partial_paths), "content_hash": self.content_hash,
                "complete": self.complete}


def build_review_packets(payload: Mapping[str, Any], *, prompt_prefix: str = "", token_budget: int = 48000,
                         scientific_only: bool = True) -> list[ReviewPacket]:
    """Every scientific leaf is transmitted, including tails of long strings.

    A field split across packets is partial in each packet. Only a combined
    review can claim to have examined the complete field.
    """
    snapshot = scientific_content(payload) if scientific_only else dict(payload)
    leaves = _leaves(snapshot)
    all_paths = tuple(path for path, _ in leaves)
    digest = content_hash(snapshot)
    # Leave room for coverage metadata and per-chunk labels in every prompt.
    reserve = 1200
    available = token_budget - token_bound(prompt_prefix) - reserve
    if available < 256:
        raise ValueError("Review prompt prefix/coverage exceeds the token budget; increase review_prompt_token_budget or partition task context.")
    chunks: list[tuple[str, str, bool]] = []
    for path, value in leaves:
        capacity = available - token_bound(path) * 6 - 300
        if capacity < 64:
            raise ValueError(f"Candidate field path exceeds review packet budget: {path}")
        if token_bound(value) <= capacity:
            chunks.append((path, value, False))
            continue
        start = 0
        while start < len(value):
            end = min(len(value), start + capacity)
            while token_bound(value[start:end]) > capacity:
                end = start + max(1, (end - start) // 2)
            chunks.append((path, value[start:end], True))
            start = end
    groups: list[list[tuple[str, str, bool]]] = [[]]
    used = 0
    for item in chunks:
        cost = token_bound(item[0]) * 6 + token_bound(item[1]) + 300
        if groups[-1] and used + cost > available:
            groups.append([])
            used = 0
        groups[-1].append(item)
        used += cost
    packets = []
    for index, group in enumerate(groups):
        included = tuple(dict.fromkeys(path for path, _, partial in group if not partial))
        partial = tuple(dict.fromkeys(path for path, _, split in group if split))
        omitted = tuple(path for path in all_paths if path not in included)
        ancestors = set()
        for path in included:
            ancestors.update(path[:m.start()] for m in re.finditer(r"\.|\[", path))
        included = (*included, *sorted(p for p in ancestors if all(
            leaf in included for leaf in all_paths if leaf.startswith(p + ".") or leaf.startswith(p + "[")
        )))
        if not omitted and not partial:
            included = ("$", *included)
        coverage = {"included_paths": included, "omitted_path_count": len(omitted), "partial_paths": partial,
                    "content_hash": digest, "packet": index + 1, "packets": len(groups)}
        text = "\n== Candidate review coverage ==\n" + canonical_json(coverage) + "\n"
        text += "Fields absent from this packet are unassessed. Do not infer missing content.\n"
        text += "\n".join(f"FIELD {path}{' (continued segment)' if split else ''}:\n{value}" for path, value, split in group)
        if token_bound(prompt_prefix + text) > token_budget:
            raise ValueError("Review packet exceeds the total prompt budget.")
        packets.append(ReviewPacket(text, included, omitted, partial, digest))
    return packets


def aggregate_review_payloads(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep issues and assessments; scores are averaged, not summed per packet."""
    merged: dict[str, Any] = {}
    numeric: dict[str, list[float]] = {}
    list_keys = {"review_issues", "requirement_reviews", "reviewed_issue_ids", "reviewed_claim_ids", "claim_reviews", "detected_defects", "failure_modes"}
    for payload in payloads:
        for key, value in payload.items():
            if key in list_keys and isinstance(value, list):
                merged.setdefault(key, []).extend(value)
            elif isinstance(value, (float, int)) and not isinstance(value, bool):
                numeric.setdefault(key, []).append(float(value))
            elif key in {"feedback", "defect_fix_summary"}:
                merged[key] = "\n".join(filter(None, [merged.get(key, ""), str(value or "")]))
            else:
                merged[key] = value
    for key, values in numeric.items():
        merged[key] = sum(values) / len(values)
    return merged
