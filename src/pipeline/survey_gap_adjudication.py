"""Coverage, synthesis, deduplication, and adjudication for gap candidates."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .survey_gap_candidates import (
    GapCandidate,
    build_gap_candidate_payload,
    validate_gap_candidate_payload,
)
from .survey_idea_handoff import GAP_DECISIONS, canonical_fingerprint, stable_identifier


SURVEY_GAP_COVERAGE_SCHEMA_VERSION = "survey_gap_coverage_v1"
SURVEY_GAP_ADJUDICATION_SCHEMA_VERSION = "survey_gap_adjudication_v1"

SURVEY_GAP_COVERAGE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Survey Gap Coverage Matrix v1",
    "type": "object",
    "required": ["schema_version", "coverage_matrix_version", "rows"],
    "properties": {
        "schema_version": {"const": SURVEY_GAP_COVERAGE_SCHEMA_VERSION},
        "coverage_matrix_version": {"const": SURVEY_GAP_COVERAGE_SCHEMA_VERSION},
        "project_id": {"type": "string"},
        "survey_run_id": {"type": "string"},
        "project_context_fingerprint": {"type": "string"},
        "rows": {"type": "array", "items": {"type": "object"}},
        "status_counts": {"type": "object"},
        "contradiction_ids": {"type": "array", "items": {"type": "string"}},
    },
}

SURVEY_GAP_ADJUDICATION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Survey Gap Adjudication v1",
    "type": "object",
    "required": ["schema_version", "coverage", "synthesis", "contradictions", "decisions"],
    "properties": {
        "schema_version": {"const": SURVEY_GAP_ADJUDICATION_SCHEMA_VERSION},
        "coverage": {"type": "object"},
        "synthesis": {"type": "object"},
        "contradictions": {"type": "array", "items": {"type": "object"}},
        "decisions": {"type": "array", "items": {"type": "object"}},
        "artifact_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}


def _text(value: Any, *, limit: int = 12000) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:limit]


def _texts(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _text(item)
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            result.append(text)
    return result


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _candidate_payload(candidate: GapCandidate | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(candidate, GapCandidate):
        return build_gap_candidate_payload(candidate)
    payload = dict(candidate)
    payload.setdefault("schema_version", "survey_gap_candidate_v1")
    payload.setdefault("subhypothesis_id", _text(payload.get("sub_hypothesis_id")) or "GLOBAL")
    payload.setdefault("gap_kind", _text(payload.get("category")) or "unmapped_gap:llm_candidate")
    payload.setdefault("target_slot", _text(payload.get("slot")) or "scientific_constraint")
    payload.setdefault("statement", _candidate_text(payload) or "Unresolved scientific constraint.")
    payload.setdefault(
        "candidate_id",
        stable_identifier(
            "gap_candidate",
            payload["subhypothesis_id"],
            payload["gap_kind"],
            payload["target_slot"],
            _candidate_text(payload).casefold(),
        ),
    )
    payload.setdefault("confidence", 0.5)
    payload.setdefault("status", "candidate")
    payload.setdefault("support_level", "speculative")
    payload.setdefault("paper_ids", [])
    payload.setdefault("candidate_defect_tags", [payload["gap_kind"]])
    payload.setdefault("candidate_contribution_modes", [])
    payload.setdefault("source_pointers", [])
    return payload


def _candidate_key(candidate: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _text(candidate.get("subhypothesis_id") or candidate.get("sub_hypothesis_id")) or "GLOBAL",
        _text(candidate.get("target_slot")) or "scientific_constraint",
        _text(candidate.get("gap_kind")) or "unmapped_gap:llm_candidate",
    )


def _candidate_text(candidate: Mapping[str, Any]) -> str:
    return _text(candidate.get("statement") or candidate.get("gap_statement") or candidate.get("limitation"))


def _tokens(value: str) -> set[str]:
    aliases = {
        "comparator": "compar",
        "comparison": "compar",
        "comparative": "compar",
        "defined": "define",
        "defines": "define",
    }
    return {
        aliases.get(token, token)
        for token in re.findall(r"[a-z0-9]{3,}|[\u4e00-\u9fff]{2,}", value.casefold())
        if token not in {"the", "and", "that", "this", "with", "from", "there", "需要", "现有"}
    }


def _similar(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if _candidate_key(left) != _candidate_key(right):
        return False
    left_text = _candidate_text(left)
    right_text = _candidate_text(right)
    if not left_text or not right_text:
        return False
    if left_text.casefold() == right_text.casefold():
        return True
    left_tokens = _tokens(left_text)
    right_tokens = _tokens(right_text)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    return (
        overlap / len(left_tokens | right_tokens) >= 0.62
        or overlap / min(len(left_tokens), len(right_tokens)) >= 0.7
    )


def _source_pointers(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    pointers = candidate.get("source_pointers") or candidate.get("source_pointer") or []
    if isinstance(pointers, Mapping):
        pointers = [pointers]
    return [dict(pointer) for pointer in pointers if isinstance(pointer, Mapping)]


def deduplicate_gap_candidates(
    candidates: Sequence[GapCandidate | Mapping[str, Any]],
) -> dict[str, Any]:
    """Group semantically repeated candidates without discarding provenance."""

    payloads = [_candidate_payload(candidate) for candidate in candidates]
    groups: list[dict[str, Any]] = []
    assigned: set[int] = set()
    for index, candidate in enumerate(payloads):
        if index in assigned:
            continue
        members = [index]
        assigned.add(index)
        for other_index in range(index + 1, len(payloads)):
            if other_index not in assigned and _similar(candidate, payloads[other_index]):
                members.append(other_index)
                assigned.add(other_index)
        member_payloads = [payloads[item] for item in members]
        ordered_ids = sorted(_text(item.get("candidate_id")) for item in member_payloads)
        group_id = stable_identifier("gap_group", *_candidate_key(candidate), *ordered_ids)
        representative = max(
            member_payloads,
            key=lambda item: (float(item.get("confidence") or 0.0), _text(item.get("candidate_id"))),
        )
        merged = dict(representative)
        merged["candidate_ids"] = ordered_ids
        merged["paper_ids"] = sorted({paper_id for item in member_payloads for paper_id in _texts(item.get("paper_ids"))})
        merged["source_pointers"] = [pointer for item in member_payloads for pointer in _source_pointers(item)]
        merged["candidate_defect_tags"] = sorted({tag for item in member_payloads for tag in _texts(item.get("candidate_defect_tags"))})
        merged["candidate_contribution_modes"] = sorted({mode for item in member_payloads for mode in _texts(item.get("candidate_contribution_modes"))})
        merged["support_level"] = "cross_source" if len(merged["source_pointers"]) > 1 else _text(merged.get("support_level")) or "speculative"
        merged["group_id"] = group_id
        groups.append({
            "group_id": group_id,
            "candidate_ids": ordered_ids,
            "representative": merged,
            "paper_ids": merged["paper_ids"],
            "source_pointers": merged["source_pointers"],
        })
    groups.sort(key=lambda group: group["group_id"])
    return {
        "schema_version": SURVEY_GAP_COVERAGE_SCHEMA_VERSION,
        "groups": groups,
        "candidates": [group["representative"] for group in groups],
        "duplicate_group_count": sum(1 for group in groups if len(group["candidate_ids"]) > 1),
    }


def merge_duplicate_gap_candidates(
    candidates: Sequence[GapCandidate | Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return deduplicate_gap_candidates(candidates)["candidates"]


deduplicate_candidates = deduplicate_gap_candidates


def _stance(item: Mapping[str, Any]) -> str:
    for key in ("supports", "supported", "confirms"):
        if item.get(key) is True:
            return "support"
    for key in ("contradicts", "challenged", "challenges", "negative_result"):
        if item.get(key) is True:
            return "challenge"
    for key in ("stance", "polarity", "finding_direction", "evidence_direction", "claim_stance", "relationship"):
        value = _text(item.get(key)).casefold()
        if value:
            if any(token in value for token in ("support", "confirm", "positive", "consistent", "improv", "increase", "成立")):
                return "support"
            if any(token in value for token in ("challenge", "contradict", "negative", "against", "fail", "decreas", "no effect", "不支持", "反例")):
                return "challenge"
    text = _candidate_text(item) or _text(item.get("abstract") or item.get("text") or item.get("result"))
    if re.search(r"(?i)\b(contradict|challenge|no effect|failed|not support|against|counterexample)\b|不支持|反例", text):
        return "challenge"
    if re.search(r"(?i)\b(support|confirm|consistent|significant increase|improve)\b|支持|证实", text):
        return "support"
    return ""


def detect_gap_contradictions(
    candidates: Sequence[GapCandidate | Mapping[str, Any]],
    papers: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Detect explicit opposing stances while avoiding topic-only conflicts."""

    payloads = [_candidate_payload(candidate) for candidate in candidates]
    contradictions: list[dict[str, Any]] = []
    for index, left in enumerate(payloads):
        for right in payloads[index + 1 :]:
            if _candidate_key(left)[:2] != _candidate_key(right)[:2]:
                continue
            left_stance = _stance(left)
            right_stance = _stance(right)
            explicit = (
                _text(right.get("contradicts_candidate_id")) == _text(left.get("candidate_id"))
                or _text(left.get("contradicts_candidate_id")) == _text(right.get("candidate_id"))
                or bool(set(_texts(left.get("conflicts_with"))) & {_text(right.get("candidate_id"))})
            )
            if not explicit and not ({left_stance, right_stance} == {"support", "challenge"}):
                continue
            candidate_ids = sorted([_text(left.get("candidate_id")), _text(right.get("candidate_id"))])
            contradictions.append({
                "contradiction_id": stable_identifier("gap_contradiction", *candidate_ids),
                "candidate_ids": candidate_ids,
                "paper_ids": sorted({paper_id for item in (left, right) for paper_id in _texts(item.get("paper_ids"))}),
                "description": "Candidate evidence contains opposing explicit stances for the same scientific slot.",
                "severity": "high",
            })
    paper_records = [dict(item) for item in (papers or []) if isinstance(item, Mapping)]
    candidate_by_id = {
        _text(item.get("candidate_id")): item
        for item in payloads
        if _text(item.get("candidate_id"))
    }
    for paper in paper_records:
        paper_id = _text(paper.get("paper_id") or paper.get("paperId"))
        for candidate_id in _texts(paper.get("contradicts_candidate_ids") or paper.get("contradicts_candidates")):
            if candidate_id in candidate_by_id:
                contradictions.append({
                    "contradiction_id": stable_identifier("paper_candidate_contradiction", paper_id, candidate_id),
                    "candidate_ids": [candidate_id],
                    "paper_ids": [paper_id] if paper_id else [],
                    "description": "A paper explicitly marks the candidate as contradicted.",
                    "severity": "high",
                })
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for paper in paper_records:
        sh_id = _text(paper.get("subhypothesis_id") or paper.get("sub_hypothesis_id"))
        slot = _text(paper.get("target_slot") or paper.get("slot"))
        if sh_id and slot and _stance(paper):
            by_key[(sh_id, slot)].append(paper)
    for key, records in by_key.items():
        for index, left in enumerate(records):
            for right in records[index + 1 :]:
                if _stance(left) == _stance(right):
                    continue
                paper_ids = sorted({_text(left.get("paper_id") or left.get("paperId")), _text(right.get("paper_id") or right.get("paperId"))} - {""})
                if not paper_ids:
                    continue
                contradictions.append({
                    "contradiction_id": stable_identifier("paper_contradiction", key[0], key[1], *paper_ids),
                    "candidate_ids": [],
                    "paper_ids": paper_ids,
                    "description": "Paper records report opposing directions for the same sub-hypothesis slot.",
                    "severity": "high",
                })
    unique: dict[str, dict[str, Any]] = {item["contradiction_id"]: item for item in contradictions}
    return [unique[key] for key in sorted(unique)]


def build_coverage_matrix(
    *,
    gap_ledger: Mapping[str, Any] | None = None,
    candidates: Sequence[GapCandidate | Mapping[str, Any]] = (),
    evidence_plan: Mapping[str, Any] | None = None,
    contradictions: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build slot-level coverage states from plan, deterministic gaps, and candidates."""

    ledger = _mapping(gap_ledger)
    plan = _mapping(evidence_plan)
    if not plan and isinstance(ledger.get("evidence_plan"), Mapping):
        plan = dict(ledger["evidence_plan"])
    if isinstance(plan.get("survey_evidence_plan"), Mapping):
        plan = dict(plan["survey_evidence_plan"])
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for sh in _records(plan.get("subhypotheses")):
        sh_id = _text(sh.get("sub_hypothesis_id")) or "GLOBAL"
        covered = set(_texts(sh.get("covered_slots")))
        background = set(_texts(sh.get("background_only_slots")))
        missing = set(_texts(sh.get("missing_slots")))
        for slot in _texts(sh.get("required_slots")):
            state = "covered" if slot in covered else "qualified" if slot in background else "uncovered" if slot in missing else "unverified"
            rows[(sh_id, slot)] = {
                "subhypothesis_id": sh_id,
                "target_slot": slot,
                "required": True,
                "base_status": state,
                "status": state,
                "deterministic_gap_ids": [],
                "candidate_ids": [],
                "paper_ids": [],
                "contradiction_ids": [],
            }
        for cluster in _records(sh.get("relevant_clusters")):
            for slot in _texts(cluster.get("uncovered_required_slots")):
                key = (sh_id, slot)
                row = rows.setdefault(key, {
                    "subhypothesis_id": sh_id,
                    "target_slot": slot,
                    "required": True,
                    "base_status": "uncovered",
                    "status": "uncovered",
                    "deterministic_gap_ids": [],
                    "candidate_ids": [],
                    "paper_ids": [],
                    "contradiction_ids": [],
                })
                if row["status"] in {"unverified", "covered", "qualified"}:
                    row["status"] = "uncovered"
    for gap in _records(ledger.get("gaps")):
        key = (_text(gap.get("subhypothesis_id")) or "GLOBAL", _text(gap.get("target_slot")) or "scientific_constraint")
        row = rows.setdefault(key, {
            "subhypothesis_id": key[0], "target_slot": key[1], "required": False,
            "base_status": "uncovered", "status": "uncovered", "deterministic_gap_ids": [],
            "candidate_ids": [], "paper_ids": [], "contradiction_ids": [],
        })
        row["deterministic_gap_ids"].append(_text(gap.get("gap_id")))
        row["status"] = "uncovered"
    candidate_items = [*candidates, *_records(ledger.get("candidate_gaps"))]
    candidate_payloads = [_candidate_payload(candidate) for candidate in candidate_items]
    for candidate in candidate_payloads:
        key = _candidate_key(candidate)[:2]
        row = rows.setdefault(key, {
            "subhypothesis_id": key[0], "target_slot": key[1], "required": False,
            "base_status": "unverified", "status": "unverified", "deterministic_gap_ids": [],
            "candidate_ids": [], "paper_ids": [], "contradiction_ids": [],
        })
        row["candidate_ids"].append(_text(candidate.get("candidate_id")))
        row["paper_ids"].extend(_texts(candidate.get("paper_ids")))
        if row["status"] == "uncovered":
            row["status"] = "candidate_pending"
        elif row["status"] == "unverified":
            row["status"] = "candidate_pending"
    for contradiction in contradictions:
        contradiction_id = _text(contradiction.get("contradiction_id"))
        candidate_ids = set(_texts(contradiction.get("candidate_ids")))
        for row in rows.values():
            if candidate_ids & set(row["candidate_ids"]):
                row["contradiction_ids"].append(contradiction_id)
                row["status"] = "contradicted"
    ordered_rows = []
    for row in sorted(rows.values(), key=lambda item: (item["subhypothesis_id"], item["target_slot"])):
        for key in ("deterministic_gap_ids", "candidate_ids", "paper_ids", "contradiction_ids"):
            row[key] = sorted(set(row[key]))
        ordered_rows.append(row)
    counts: dict[str, int] = defaultdict(int)
    for row in ordered_rows:
        counts[row["status"]] += 1
    return {
        "schema_version": SURVEY_GAP_COVERAGE_SCHEMA_VERSION,
        "coverage_matrix_version": SURVEY_GAP_COVERAGE_SCHEMA_VERSION,
        "project_id": _text(ledger.get("project_id") or plan.get("project_id")),
        "survey_run_id": _text(ledger.get("survey_run_id")),
        "project_context_fingerprint": _text(ledger.get("project_context_fingerprint") or plan.get("project_context_fingerprint")),
        "rows": ordered_rows,
        "status_counts": dict(sorted(counts.items())),
        "contradiction_ids": sorted({_text(item.get("contradiction_id")) for item in contradictions if _text(item.get("contradiction_id"))}),
    }


def validate_coverage_matrix_payload(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["payload must be a JSON object"]
    errors: list[str] = []
    if payload.get("schema_version") != SURVEY_GAP_COVERAGE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {SURVEY_GAP_COVERAGE_SCHEMA_VERSION}")
    if payload.get("coverage_matrix_version") != SURVEY_GAP_COVERAGE_SCHEMA_VERSION:
        errors.append("coverage_matrix_version does not match schema_version")
    if not isinstance(payload.get("rows"), list):
        errors.append("payload.rows must be a list")
    return errors


def build_cross_paper_synthesis_prompt(group: Mapping[str, Any]) -> str:
    return """Synthesize one scientific gap candidate from multiple paper-grounded observations. Return one JSON object with statement, rationale, confidence, and claim_scope. Preserve uncertainty and do not turn disagreement into consensus.\n\nCandidate group:\n""" + json.dumps(dict(group), ensure_ascii=False, indent=2)


def synthesize_cross_paper_gaps(
    candidates: Sequence[GapCandidate | Mapping[str, Any]],
    *,
    papers: Sequence[Mapping[str, Any]] | None = None,
    llm_call: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Merge repeated candidates and optionally ask an LLM for cross-paper wording."""

    deduped = deduplicate_gap_candidates(candidates)
    groups = deduped["groups"]
    paper_by_id = {
        _text(paper.get("paper_id") or paper.get("paperId")): dict(paper)
        for paper in (papers or [])
        if isinstance(paper, Mapping)
        and _text(paper.get("paper_id") or paper.get("paperId"))
    }
    for group in groups:
        group["paper_evidence"] = [
            {
                key: paper.get(key)
                for key in ("paper_id", "paperId", "title", "abstract", "sections", "finding", "result", "stance", "limitation")
                if paper.get(key) not in (None, "")
            }
            for paper_id in group.get("paper_ids", [])
            if (paper := paper_by_id.get(paper_id)) is not None
        ]
    if llm_call is not None:
        for group in groups:
            response = llm_call(build_cross_paper_synthesis_prompt(group))
            if isinstance(response, Mapping):
                parsed = dict(response)
            else:
                try:
                    parsed = json.loads(str(response or ""))
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed = {}
            if isinstance(parsed, Mapping) and _text(parsed.get("statement")):
                representative = group["representative"]
                representative["statement"] = _text(parsed.get("statement"))
                representative["rationale"] = _text(parsed.get("rationale") or representative.get("rationale"))
                if parsed.get("confidence") is not None:
                    try:
                        representative["confidence"] = max(0.0, min(1.0, float(parsed["confidence"])))
                    except (TypeError, ValueError):
                        pass
                representative["support_level"] = "cross_source"
    return {
        "schema_version": SURVEY_GAP_COVERAGE_SCHEMA_VERSION,
        "groups": groups,
        "candidates": [group["representative"] for group in groups],
    }


synthesize_cross_paper_evidence = synthesize_cross_paper_gaps


def build_gap_adjudication_prompt(
    groups: Sequence[Mapping[str, Any]],
    contradictions: Sequence[Mapping[str, Any]],
) -> str:
    return """Adjudicate Survey gap candidates. Return one JSON object with decisions, each decision containing group_id, decision (accept, downgrade, merge, reject, or pending_verification), and reason. Accept only source-grounded, non-contradictory candidates. Do not invent evidence.\n\nGroups:\n""" + json.dumps(list(groups), ensure_ascii=False, indent=2) + "\n\nContradictions:\n" + json.dumps(list(contradictions), ensure_ascii=False, indent=2)


def adjudicate_gap_candidates(
    candidates: Sequence[GapCandidate | Mapping[str, Any]],
    *,
    papers: Sequence[Mapping[str, Any]] | None = None,
    llm_call: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic or LLM-assisted decisions for deduplicated candidates."""

    synthesis = synthesize_cross_paper_gaps(candidates, papers=papers)
    contradictions = detect_gap_contradictions(candidates, papers=papers)
    contradiction_ids = {candidate_id for item in contradictions for candidate_id in _texts(item.get("candidate_ids"))}
    llm_decisions: dict[str, dict[str, Any]] = {}
    if llm_call is not None and synthesis["groups"]:
        response = llm_call(build_gap_adjudication_prompt(synthesis["groups"], contradictions))
        if isinstance(response, Mapping):
            parsed = dict(response)
        else:
            try:
                parsed = json.loads(str(response or ""))
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = {}
        for decision in _records(_mapping(parsed).get("decisions")):
            group_id = _text(decision.get("group_id"))
            if not group_id:
                candidate_id = _text(decision.get("candidate_id"))
                group_id = next(
                    (
                        group["group_id"]
                        for group in synthesis["groups"]
                        if candidate_id in set(_texts(group.get("candidate_ids")))
                    ),
                    "",
                )
            if group_id:
                llm_decisions[group_id] = decision
    decisions: list[dict[str, Any]] = []
    for group in synthesis["groups"]:
        group_id = group["group_id"]
        representative = group["representative"]
        member_ids = set(_texts(group.get("candidate_ids")))
        if member_ids & contradiction_ids:
            decision, reason = "pending_verification", "Opposing evidence requires explicit verification before acceptance."
        elif len(member_ids) > 1:
            decision, reason = "merge", "Repeated candidates were merged while retaining all source pointers."
        elif float(representative.get("confidence") or 0.0) >= 0.65 and _source_pointers(representative):
            decision, reason = "accept", "Candidate is source-grounded and meets the confidence threshold."
        elif float(representative.get("confidence") or 0.0) >= 0.35:
            decision, reason = "downgrade", "Candidate remains plausible but needs stronger evidence or narrower wording."
        else:
            decision, reason = "pending_verification", "Candidate confidence is below the acceptance threshold."
        supplied = llm_decisions.get(group_id)
        if supplied:
            supplied_decision = _text(supplied.get("decision"))
            source_grounded = bool(_source_pointers(representative))
            evidence_eligible = source_grounded and float(representative.get("confidence") or 0.0) >= 0.65
            can_override = supplied_decision in GAP_DECISIONS
            if supplied_decision == "accept" and (member_ids & contradiction_ids or not evidence_eligible):
                can_override = False
            if supplied_decision == "merge" and decision != "merge":
                can_override = False
            if can_override:
                decision = supplied_decision
                reason = _text(supplied.get("reason")) or reason
        decisions.append({
            "adjudication_id": stable_identifier("gap_adjudication", group_id),
            "group_id": group_id,
            "candidate_id": _text(representative.get("candidate_id")),
            "decision": decision,
            "reason": reason,
            "contradiction": bool(member_ids & contradiction_ids),
        })
    return {
        "schema_version": SURVEY_GAP_ADJUDICATION_SCHEMA_VERSION,
        "decisions": decisions,
        "contradictions": contradictions,
        "synthesis": synthesis,
    }


def build_gap_coverage_artifact(
    *,
    gap_ledger: Mapping[str, Any] | None = None,
    candidates: Sequence[GapCandidate | Mapping[str, Any]] = (),
    evidence_plan: Mapping[str, Any] | None = None,
    papers: Sequence[Mapping[str, Any]] | None = None,
    llm_call: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    adjudication = adjudicate_gap_candidates(candidates, papers=papers, llm_call=llm_call)
    coverage = build_coverage_matrix(
        gap_ledger=gap_ledger,
        candidates=candidates,
        evidence_plan=evidence_plan,
        contradictions=adjudication["contradictions"],
    )
    payload = {
        "schema_version": SURVEY_GAP_ADJUDICATION_SCHEMA_VERSION,
        "coverage": coverage,
        "synthesis": adjudication["synthesis"],
        "contradictions": adjudication["contradictions"],
        "decisions": adjudication["decisions"],
    }
    payload["artifact_fingerprint"] = canonical_fingerprint(payload)
    return payload


def validate_gap_adjudication_payload(payload: Any, *, verify_fingerprint: bool = False) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["payload must be a JSON object"]
    errors: list[str] = []
    if payload.get("schema_version") != SURVEY_GAP_ADJUDICATION_SCHEMA_VERSION:
        errors.append(f"schema_version must be {SURVEY_GAP_ADJUDICATION_SCHEMA_VERSION}")
    for key in ("coverage", "synthesis"):
        if not isinstance(payload.get(key), Mapping):
            errors.append(f"payload.{key} must be an object")
    for key in ("contradictions", "decisions"):
        if not isinstance(payload.get(key), list):
            errors.append(f"payload.{key} must be a list")
    for decision in _records(payload.get("decisions")):
        if _text(decision.get("decision")) not in GAP_DECISIONS:
            errors.append("payload.decisions contains an unsupported decision")
    if verify_fingerprint:
        expected = _text(payload.get("artifact_fingerprint"))
        if expected != canonical_fingerprint(payload, exclude_fields={"artifact_fingerprint"}):
            errors.append("artifact_fingerprint does not match canonical payload")
    return errors


build_coverage_and_adjudication = build_gap_coverage_artifact


__all__ = [
    "SURVEY_GAP_COVERAGE_SCHEMA_VERSION",
    "SURVEY_GAP_ADJUDICATION_SCHEMA_VERSION",
    "SURVEY_GAP_ADJUDICATION_SCHEMA",
    "SURVEY_GAP_COVERAGE_SCHEMA",
    "build_coverage_and_adjudication",
    "build_cross_paper_synthesis_prompt",
    "build_gap_adjudication_prompt",
    "build_gap_coverage_artifact",
    "build_coverage_matrix",
    "deduplicate_candidates",
    "deduplicate_gap_candidates",
    "detect_gap_contradictions",
    "validate_coverage_matrix_payload",
    "validate_gap_adjudication_payload",
    "merge_duplicate_gap_candidates",
    "synthesize_cross_paper_evidence",
    "synthesize_cross_paper_gaps",
    "adjudicate_gap_candidates",
]
