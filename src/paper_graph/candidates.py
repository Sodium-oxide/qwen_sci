"""Partition extracted entities into grounded graph records and resumable candidates."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any

from src.paper_graph.evidence_repair import EVIDENCE_FIELDS, evidence_issues
from src.paper_graph.ingest import object_value, text, verified_evidence


def verified_candidates(payload: dict[str, Any], docs: list[dict[str, Any]]
                        ) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    resources = object_value(payload.get("ideation_resource"))
    root = ("ideation_resource",) if resources else ()
    resources = resources or payload
    failures = defaultdict(list)
    for issue in evidence_issues(payload, docs):
        failures[issue.entity_path].append(issue)
    candidates = []
    reasons = []

    def inspect(value, path, kind):
        entity = object_value(value)
        errors = [issue.message for issue in failures[path]]
        if not entity:
            errors.append("invalid_contribution" if kind == "Core" else "invalid_component")
        if not entity or any(not isinstance(entity.get(field), str) or not entity[field].strip()
                             for field in ("name", "summary")):
            errors.append("incomplete_contribution" if kind == "Core" else "incomplete_component")
        records = verified_evidence(entity, docs) if entity else []
        if failures[path] or not records:
            errors.append(("contribution_evidence_missing:" if kind == "Core" else "component_evidence_missing:")
                          + text(entity.get("name")))
        candidate = {"target_id": "/" + "/".join(str(part) for part in path), "entity_type": kind,
                     "name": text(entity.get("name")), "verification_status": "unverified" if errors else "verified",
                     "evidence_status": "unverified" if failures[path] or not records else "verified",
                     "reasons": sorted(set(errors)), "evidence_issues": [issue.as_dict() for issue in failures[path]],
                     "candidate": deepcopy(entity or value)}
        candidates.append(candidate)
        return entity, records, candidate

    def accepted(entity, records):
        return {**{key: value for key, value in entity.items() if key not in {*EVIDENCE_FIELDS, "components"}},
                "evidence_records": records, "verification_status": "verified"}

    cores = resources.get("core_contributions", payload.get("cores", []))
    if not isinstance(cores, list):
        reasons.append("missing_structured_contributions")
        cores = []
    core_entries = []
    by_alias = defaultdict(list)
    core_key = "core_contributions" if "core_contributions" in resources else "cores"
    core_root = root if core_key == "core_contributions" else ()
    for index, value in enumerate(cores):
        path = (*core_root, core_key, index)
        entity, records, candidate = inspect(value, path, "Core")
        core = {**accepted(entity, records), "components": []} if not candidate["reasons"] else None
        core_entries.append((entity, path, candidate, core))
        for alias in {text(entity.get("name")), text(entity.get("id"))} - {""}:
            by_alias[alias].append(index)

    def component(value, path, parents):
        entity, records, candidate = inspect(value, path, "Component")
        identities = {text(core_entries[parent][0].get("id") or core_entries[parent][0].get("name")).casefold()
                      for parent in parents}
        if not parents or len(identities) != 1:
            candidate["reasons"].append("unlinked_components")
        else:
            parent = next((parent for parent in parents if core_entries[parent][3] is not None), parents[0])
            core = core_entries[parent][3]
            if core is None:
                candidate["reasons"].append("parent_contribution_unverified:" + core_entries[parent][2]["target_id"])
            elif not candidate["reasons"]:
                core["components"].append(accepted(entity, records))
        if candidate["reasons"] and candidate["verification_status"] == "verified":
            candidate["verification_status"] = "blocked"

    for index, (entity, path, candidate, _) in enumerate(core_entries):
        components = entity.get("components", [])
        if not isinstance(components, list):
            reasons.append("invalid_components:" + candidate["name"])
            continue
        for position, value in enumerate(components):
            component(value, (*path, "components", position), [index])
    components = resources.get("components", [])
    if not isinstance(components, list):
        reasons.append("invalid_components")
        components = []
    for index, value in enumerate(components):
        entity = object_value(value)
        component(value, (*root, "components", index), by_alias.get(text(entity.get("related_to_core")), []))
    reasons.extend(reason for candidate in candidates for reason in candidate["reasons"])
    return {**resources, "core_contributions": [entry[3] for entry in core_entries if entry[3] is not None],
            "components": []}, candidates, sorted(set(reasons))
