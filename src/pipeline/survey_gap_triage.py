"""Confidence-aware triage and bounded verification for Survey gaps.

The triage layer is deliberately fail-open.  It removes only explicit
contradictions, scope violations, and source misalignment; plausible or weak
gaps remain available to Idea as provisional or exploratory seeds.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .survey_idea_handoff import canonical_fingerprint, stable_identifier


SURVEY_GAP_TRIAGE_SCHEMA_VERSION = "survey_gap_triage_v1"
TARGETED_VERIFICATION_TOP_K = 15
_ROUTES = {
    "core_hypothesis",
    "provisional_hypothesis",
    "exploratory_frontier",
    "supporting_constraint",
    "verification_only",
    "future_work_seed",
    "exclude",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _texts(value: Any) -> list[str]:
    values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        item_text = _text(item)
        if item_text and item_text not in seen:
            seen.add(item_text)
            result.append(item_text)
    return result


def _profile_id(profile_resolution: Mapping[str, Any] | None) -> str:
    payload = dict(profile_resolution or {})
    return _text(payload.get("profile_id") or payload.get("profile_id_hint")).casefold()


def _confidence(gap: Mapping[str, Any], *, deterministic: bool) -> float:
    nested_audit = _mapping(gap.get("gap_audit"))
    raw = gap.get(
        "existence_confidence",
        gap.get("confidence", nested_audit.get("existence_confidence", nested_audit.get("confidence"))),
    )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0
    if deterministic and value <= 0:
        value = 0.85 if _text(gap.get("source_pointer")) or gap.get("source_pointer") else 0.75
    return max(0.0, min(1.0, value))


def _alignment(gap: Mapping[str, Any]) -> str:
    explicit = _text(gap.get("source_alignment"))
    if explicit in {"aligned", "partially_aligned", "unresolved_alignment", "misaligned"}:
        return explicit
    pointers = gap.get("source_pointers") or gap.get("source_pointer")
    if isinstance(pointers, Mapping) and _text(pointers.get("artifact")) and _text(pointers.get("json_pointer")):
        return "aligned"
    if any(_text(pointer.get("artifact")) and _text(pointer.get("json_pointer")) for pointer in _records(pointers)):
        return "aligned"
    return "unresolved_alignment"


def _mechanism_link(gap: Mapping[str, Any]) -> str:
    text = " ".join(
        _text(gap.get(key)) for key in ("gap_kind", "target_slot", "statement", "rationale")
    ).casefold()
    if re.search(r"\b(mechan|caus|pathway|mediator|identif|proof|theorem|assumption|counterexample|boundary|regime)\w*\b", text):
        return "explicit"
    if re.search(r"\b(relation|explain|attribution|effect|validity|construct)\w*\b", text):
        return "candidate"
    return "none"


def _kind_route(gap: Mapping[str, Any], profile_id: str) -> str:
    text = " ".join(
        _text(gap.get(key)) for key in ("gap_kind", "target_slot", "statement", "candidate_defect_tags")
    ).casefold()
    if re.search(r"\bfuture\s+work\b|\bnext\s+study\b|\bremains?\s+to\s+be\s+studied\b", text):
        return "future_work_seed"
    evaluation_only = bool(re.search(
        r"\bbenchmark\w*\b|\bevaluation[- ]only\b|\bprotocol[- ]only\b|\bmetric[- ]only\b|\baudit\b|\bmonitoring\b|\breporting\b",
        text,
    ))
    mechanism = _mechanism_link(gap) != "none"
    if evaluation_only:
        if mechanism:
            return "provisional_hypothesis"
        return "verification_only"
    implementation_only = bool(re.search(
        r"\b(?:missing|lack(?:s|ing)?|need(?:s)?)\s+(?:implementation|software|code|dataset|data\s+pipeline|feature)\b",
        text,
    ))
    if implementation_only and not mechanism:
        return "exclude"
    if re.search(r"\bduplicate\b", text) and not mechanism:
        return "exclude"
    measurement = bool(re.search(r"measurement|characteriz|assay|construct|calibrat|endpoint|observab", text))
    boundary = bool(re.search(r"boundary|regime|generaliz|transport|scope|condition|population|dose|exposure", text))
    comparator = bool(re.search(r"comparator|counterfactual|control(?:\s+group)?|comparative", text))
    if profile_id == "formal_theoretical" and re.search(r"assumption|proof|theorem|formal|counterexample|derivation", text):
        return "core_hypothesis"
    if profile_id in {"clinical_health", "life_molecular_mechanistic"} and (
        mechanism or comparator or boundary
    ):
        return "core_hypothesis"
    if measurement and profile_id in {
        "physical_materials_chemical",
        "clinical_health",
        "life_molecular_mechanistic",
        "earth_environment_agro",
        "generic_scientific",
    }:
        # A measurement gap is a scientific hypothesis in measurement-native
        # profiles, but remains a supporting constraint in other profiles.
        if profile_id in {
            "physical_materials_chemical",
            "clinical_health",
            "life_molecular_mechanistic",
            "earth_environment_agro",
        }:
            return "core_hypothesis"
        return "supporting_constraint"
    if mechanism:
        return "core_hypothesis"
    if boundary:
        return "supporting_constraint"
    return "provisional_hypothesis"


def _profile_object_compatible(gap: Mapping[str, Any], profile_id: str) -> bool:
    text = " ".join(_text(gap.get(key)) for key in ("gap_kind", "target_slot", "statement")).casefold()
    signals = {
        "formal_theoretical": r"assumption|proof|theorem|formal|counterexample|derivation|relation",
        "physical_materials_chemical": r"material|process|composition|structure|reaction|property|characteriz|measurement",
        "life_molecular_mechanistic": r"cell|gene|protein|pathway|biological|phenotype|assay|mechanism|perturb",
        "clinical_health": r"patient|clinical|cohort|intervention|outcome|exposure|confound|endpoint|measurement",
        "earth_environment_agro": r"environment|earth|climate|ecosystem|soil|crop|observation|attribution|exposure",
        "energy_engineering_systems": r"engineer|energy|system|device|process|operating|performance|safety|mechanism",
    }
    pattern = signals.get(profile_id)
    return True if not pattern else bool(re.search(pattern, text))


def _audit_status(gap: Mapping[str, Any], confidence: float, alignment: str, contradicted: bool) -> str:
    if contradicted:
        return "contradicted"
    status = _text(gap.get("status")).casefold()
    if status in {"rejected", "contradicted"}:
        return "contradicted"
    if status in {"out_of_scope", "misaligned"}:
        return "out_of_scope" if status == "out_of_scope" else "misaligned"
    if alignment == "misaligned":
        return "misaligned"
    if confidence >= 0.75 and alignment == "aligned":
        return "verified"
    if confidence >= 0.4 and alignment in {"aligned", "partially_aligned", "unresolved_alignment"}:
        return "plausible"
    return "weakly_supported"


def _predicate_audit(gap: Mapping[str, Any]) -> dict[str, bool]:
    statement = _text(gap.get("statement"))
    text = " ".join(
        _text(gap.get(key)) for key in ("gap_kind", "target_slot", "statement", "target_object", "rationale")
    ).casefold()
    return {
        "has_research_object": bool(_text(gap.get("target_object")) or _text(gap.get("subhypothesis_id")) or len(statement.split()) >= 4),
        "has_scientific_relation": bool(re.search(r"mechan|caus|relation|condition|boundary|measure|proof|counterexample|identif|compar", text)),
        "has_unresolved_predicate": bool(re.search(r"unresolved|unknown|missing|lack|not established|not identified|not covered|deficit|gap|future work", text)),
        "has_statement": bool(statement),
    }


def _verification_status(audit_status: str, confidence: float, checked: bool) -> str:
    if not checked:
        return "not_checked"
    if audit_status == "verified":
        return "verified"
    if audit_status == "plausible" and confidence >= 0.4:
        return "plausible"
    if audit_status == "contradicted":
        return "contradicted"
    return "unsupported"


def _candidate_records(
    ledger: Mapping[str, Any], adjudication: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    records = [dict(item) for item in _records(ledger.get("gaps"))]
    payload = dict(adjudication or {})
    groups = {
        _text(group.get("group_id")): group
        for group in _records(_mapping(payload.get("synthesis")))
        if _text(group.get("group_id"))
    }
    for decision in _records(payload.get("decisions")):
        if _text(decision.get("decision")) not in {"accept", "merge"}:
            continue
        group = groups.get(_text(decision.get("group_id")))
        representative = dict(_mapping(group.get("representative"))) if group else {}
        if representative:
            records.append(representative)
    return records


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _verify_with_llm(record: Mapping[str, Any], llm_call: Callable[[str], Any] | None) -> str | None:
    if llm_call is None:
        return None
    prompt = (
        "Verify whether this source-grounded scientific gap is contradicted by its supplied evidence. "
        "Return JSON only: {\"status\": \"verified|plausible|unsupported|contradicted\", "
        "\"reason\": \"...\"}. Do not reject a gap merely because the source does not use the word gap.\n"
        + json.dumps(dict(record), ensure_ascii=False, sort_keys=True)
    )
    try:
        response = llm_call(prompt)
        payload = json.loads(str(response)) if not isinstance(response, Mapping) else dict(response)
    except Exception:
        return None
    status = _text(payload.get("status")).casefold()
    return status if status in {"verified", "plausible", "unsupported", "contradicted"} else None


def build_gap_triage_artifact(
    *,
    gap_ledger: Mapping[str, Any],
    adjudication: Mapping[str, Any] | None = None,
    profile_resolution: Mapping[str, Any] | None = None,
    llm_call: Callable[[str], Any] | None = None,
    top_k: int = TARGETED_VERIFICATION_TOP_K,
) -> dict[str, Any]:
    """Build a fail-open triage artifact with bounded targeted verification."""

    top_k = TARGETED_VERIFICATION_TOP_K
    records = _candidate_records(gap_ledger, adjudication)
    profile_id = _profile_id(profile_resolution or _mapping(gap_ledger.get("profile_resolution")))
    contradictory_ids: set[str] = set()
    for item in _records(_mapping(adjudication).get("contradictions")):
        contradictory_ids.update(_texts(item.get("candidate_ids")))
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, record in enumerate(records):
        gap_id = _text(record.get("gap_id") or record.get("candidate_id")) or stable_identifier(
            "gap", record.get("subhypothesis_id"), record.get("gap_kind"), record.get("target_slot"), record.get("statement")
        )
        confidence = _confidence(
            record,
            deterministic=(
                _text(record.get("source_kind")) != "accepted_llm_gap_candidate"
                and not _text(_mapping(record.get("gap_audit")).get("candidate_id"))
            ),
        )
        alignment = _alignment(record)
        audit = _audit_status(record, confidence, alignment, gap_id in contradictory_ids or _text(record.get("candidate_id")) in contradictory_ids)
        route = _kind_route(record, profile_id)
        predicate = _predicate_audit(record)
        predicate["profile_object_compatible"] = _profile_object_compatible(record, profile_id)
        if not predicate["has_statement"]:
            audit, route = "misaligned", "exclude"
        elif not predicate["profile_object_compatible"] and audit != "verified":
            route = "exploratory_frontier"
        elif audit == "plausible" and route == "core_hypothesis":
            route = "provisional_hypothesis"
        elif audit == "weakly_supported" and route in {"core_hypothesis", "provisional_hypothesis"}:
            route = "exploratory_frontier"
        if audit in {"contradicted", "misaligned", "out_of_scope"}:
            route = "exclude"
        if route == "verification_only":
            novelty_role = "not_scored"
        elif route == "future_work_seed":
            novelty_role = "secondary"
        elif route == "provisional_hypothesis":
            novelty_role = "secondary"
        elif route == "supporting_constraint":
            novelty_role = "not_scored"
        else:
            novelty_role = "primary"
        required = audit in {"plausible", "weakly_supported"} and route != "exclude"
        item = {
            "gap_id": gap_id,
            "candidate_id": _text(record.get("candidate_id")),
            "audit_status": audit,
            "source_alignment": alignment,
            "existence_confidence": round(confidence, 6),
            "mechanism_link": _mechanism_link(record),
            "predicate_audit": predicate,
            "eligibility_route": route,
            "novelty_role": novelty_role,
            "verification_required": required,
            "hypothesis_seed": route in {"core_hypothesis", "provisional_hypothesis", "exploratory_frontier", "future_work_seed"},
            "verification_status": "pending" if required else "not_checked",
        }
        priority_rank = {"high": 3, "medium": 2, "low": 1}.get(_text(record.get("priority")), 1)
        mechanism_rank = {"explicit": 3, "candidate": 2, "none": 1}[item["mechanism_link"]]
        scored.append((float(priority_rank) * 10 + confidence * 5 + mechanism_rank, -index, item))
    scored.sort(key=lambda value: (value[0], value[1]), reverse=True)
    eligible_scored = [item for _, _, item in scored if item["eligibility_route"] != "exclude"]
    selected = {item["gap_id"] for item in eligible_scored[:top_k]}
    for _, _, item in scored:
        checked = item["gap_id"] in selected
        item["verification_required"] = bool(checked and item["verification_required"])
        item["verification_status"] = _verification_status(item["audit_status"], item["existence_confidence"], checked)
        if checked:
            llm_status = _verify_with_llm(next((record for record in records if _text(record.get("gap_id") or record.get("candidate_id")) == item["gap_id"]), {}), llm_call)
            if llm_status:
                item["verification_status"] = llm_status
                item["verification_required"] = False
                if llm_status == "verified":
                    item["audit_status"] = "verified"
                    if (
                        item["source_alignment"] in {"aligned", "partially_aligned"}
                        and item["mechanism_link"] in {"candidate", "explicit"}
                        and item["eligibility_route"]
                        in {"provisional_hypothesis", "exploratory_frontier"}
                    ):
                        item["eligibility_route"] = "core_hypothesis"
                        item["novelty_role"] = "primary"
                elif llm_status == "contradicted":
                    item["audit_status"] = "contradicted"
                    item["eligibility_route"] = "exclude"
                    item["novelty_role"] = "not_scored"
                elif llm_status == "unsupported" and item["eligibility_route"] in {"core_hypothesis", "provisional_hypothesis"}:
                    item["audit_status"] = "weakly_supported"
                    item["eligibility_route"] = "exploratory_frontier"
                    item["novelty_role"] = "secondary"
    # Keep at least one *open deterministic* gap available when the audit is
    # inconclusive. Explicitly rejected, contradicted, misaligned, and
    # out-of-scope records never qualify for this fail-open floor.
    eligible = [item for _, _, item in scored if item["eligibility_route"] != "exclude"]
    deterministic_open_ids = {
        _text(gap.get("gap_id"))
        for gap in _records(gap_ledger.get("gaps"))
        if _text(gap.get("status")).casefold()
        not in {"rejected", "contradicted", "misaligned", "out_of_scope", "resolved"}
    }
    if not eligible and deterministic_open_ids:
        fallback = next(
            (item for _, _, item in scored if item["gap_id"] in deterministic_open_ids),
            None,
        )
        if fallback is not None:
            fallback.update({
                "audit_status": "weakly_supported",
                "eligibility_route": "exploratory_frontier",
                "novelty_role": "secondary",
                "hypothesis_seed": True,
                "verification_status": "not_checked",
            })
    payload = {
        "schema_version": SURVEY_GAP_TRIAGE_SCHEMA_VERSION,
        "top_k": int(top_k),
        "profile_id": profile_id,
        "gaps": [item for _, _, item in sorted(scored, key=lambda value: value[2]["gap_id"])],
        "verified_gap_ids": [item["gap_id"] for _, _, item in scored if item["verification_status"] == "verified"],
        "provisional_gap_ids": [item["gap_id"] for _, _, item in scored if item["eligibility_route"] in {"provisional_hypothesis", "exploratory_frontier"}],
        "supporting_constraint_ids": [item["gap_id"] for _, _, item in scored if item["eligibility_route"] == "supporting_constraint"],
        "verification_only_gap_ids": [item["gap_id"] for _, _, item in scored if item["eligibility_route"] == "verification_only"],
        "future_work_seed_ids": [item["gap_id"] for _, _, item in scored if item["eligibility_route"] == "future_work_seed"],
        "excluded_gap_ids": [item["gap_id"] for _, _, item in scored if item["eligibility_route"] == "exclude"],
    }
    payload["triage_fingerprint"] = canonical_fingerprint(payload)
    return payload


def triage_gap_records(**kwargs: Any) -> dict[str, Any]:
    return build_gap_triage_artifact(**kwargs)


__all__ = [
    "SURVEY_GAP_TRIAGE_SCHEMA_VERSION",
    "TARGETED_VERIFICATION_TOP_K",
    "build_gap_triage_artifact",
    "triage_gap_records",
]
