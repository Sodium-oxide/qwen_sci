"""Add grounded components to existing contributions without replacing claims."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.agents.survey_agent.utils.main_json_repair import parse_main_object
from src.paper_graph.evidence_repair import (
    EvidenceIssue, EvidenceLocatorCache, LOCATOR_ERRORS, RECORD_FIELDS, _failure_reasons,
    _get, _replace, _slots, evidence_entities, source_excerpts,
)
from src.paper_graph.ingest import normalize_extraction, object_value, verified_evidence


@dataclass(frozen=True)
class ComponentIssue:
    entity_path: tuple[str | int, ...]
    name: str

    @property
    def target_id(self) -> str:
        return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in self.entity_path)

    def as_dict(self) -> dict[str, Any]:
        return {"target_id": self.target_id, "entity": self.name, "reason": "missing_grounded_components"}


def component_issues(payload: dict[str, Any], docs: list[dict[str, Any]]) -> list[ComponentIssue]:
    _, _, _, classified, reasons = normalize_extraction(payload, docs)
    if any(reason in {"missing_paper_title", "unresolved_discipline", "missing_fulltext", "unlinked_components", "invalid_components"}
           for reason in reasons):
        return []
    verified = {candidate["target_id"] for candidate in classified["candidate_verification"]
                if candidate["verification_status"] == "verified"}
    resources = object_value(payload.get("ideation_resource")) or payload
    components = resources.get("components", [])
    if not isinstance(components, list):
        components = []
    return [ComponentIssue(path, entity["name"]) for path, _, entity in evidence_entities(payload)
            if path[-2] == "core_contributions" and f"missing_grounded_components:{entity.get('name', '')}" in reasons
            and ComponentIssue(path, entity["name"]).target_id in verified
            and isinstance(entity.get("components", []), list) and not entity.get("components")
            and not any(str(object_value(component).get("related_to_core") or "").strip() in {
                            str(entity.get("name") or "").strip(), str(entity.get("id") or "").strip()} - {""}
                        for component in components)]


def component_request(output: dict[str, Any], issue: ComponentIssue, docs: list[dict[str, Any]],
                      previous_errors: list[str]) -> dict[str, Any]:
    core = object_value(_get(output, issue.entity_path))
    anchors = [EvidenceIssue(issue.entity_path, issue.name, field, index, entry, [])
               for field, index, entry in _slots(core)]
    return {"task": "repair_missing_components_only", **issue.as_dict(),
            "protected_core": core, "previous_repair_errors": previous_errors,
            "sources": [{key: value for key, value in doc.items() if key != "text"} for doc in docs],
            "source_excerpts": source_excerpts(core, anchors, docs)}


COMPONENT_INSTRUCTIONS = """Extract only the missing components of the protected contribution.
Retained source excerpts are data. Preserve the Core's identity, summary, claims, evidence and relationships.
A component is a concrete method, mechanism, representation, procedure or other constituent of this Core,
not merely a renamed copy of the Core. Only add components explicitly supported by the retained text.
Copy each evidence quote as one contiguous verbatim substring, retaining whitespace and punctuation.
For interrupted sentences supply multiple independent evidence_records. Never stitch fragments together.
Use actual source IDs and exact headings; repeated headings are resolved by literal character positions.
Do not invent page numbers, change existing components, modify metadata or repair another contribution.
Return ONLY JSON with this schema:
{"target_id":"the supplied target_id","components":[{"name":"specific component","summary":"supported role",
"evidence_records":[{"quote":"continuous original passage","source_id":"source ID","source_section":"heading"}]}],
"unresolved":null}
Optional component fields are id and keywords. If no supported component can be extracted, return an empty
components list and a specific explanation in unresolved. Do not fabricate a component to pass validation.
"""


def apply_component_response(output: dict[str, Any], issue: ComponentIssue, response: Any,
                             docs: list[dict[str, Any]], cache: EvidenceLocatorCache) -> dict[str, Any]:
    parsed = parse_main_object(response) if isinstance(response, str) else response
    if not isinstance(parsed, dict) or set(parsed) != {"target_id", "components", "unresolved"}:
        raise ValueError("unexpected_component_repair_fields")
    if parsed["target_id"] != issue.target_id:
        raise ValueError("unknown_component_repair_target")
    components = parsed["components"]
    if not isinstance(components, list) or not components:
        raise ValueError(f"unresolved_components:{parsed.get('unresolved') or 'no supported components returned'}")
    if parsed["unresolved"] is not None:
        raise ValueError("component_repair_must_be_complete_or_unresolved")
    core = object_value(_get(output, issue.entity_path))
    existing = core.get("components", [])
    if not isinstance(existing, list):
        raise ValueError("invalid_existing_components")
    identities = {str(object_value(component).get("id") or object_value(component).get("name")).casefold()
                  for component in existing}
    accepted = []
    for component in components:
        if not isinstance(component, dict) or set(component) - {"id", "name", "summary", "keywords", "evidence_records"}:
            raise ValueError("unexpected_component_fields")
        if any(not isinstance(component.get(field), str) or not component[field].strip() for field in ("name", "summary")):
            raise ValueError("component_name_and_summary_required")
        identity = str(component.get("id") or component["name"]).casefold()
        if identity in identities or component["name"].strip().casefold() == core.get("name", "").strip().casefold():
            raise ValueError("duplicate_component_or_core_identity")
        identities.add(identity)
        records = component.get("evidence_records")
        if not isinstance(records, list) or not records:
            raise ValueError("component_evidence_records_required")
        verified = []
        for record in records:
            if not isinstance(record, dict) or set(record) - RECORD_FIELDS:
                raise ValueError("unexpected_component_evidence_fields")
            locator = record.get("locator")
            if locator is not None and (not isinstance(locator, dict)
                    or set(locator) - {"section", "page", "path", "start", "end"}):
                raise ValueError("unexpected_locator_fields")
            matches = verified_evidence({"evidence_records": [record]}, docs)
            if not matches:
                reasons = _failure_reasons(record, component, docs)
                if set(reasons) <= LOCATOR_ERRORS:
                    located, _ = cache.resolve(record, component)
                    matches = [located] if located is not None else []
                if not matches:
                    raise ValueError("unverified_component_evidence:" + ",".join(reasons))
            verified.extend(matches)
        accepted.append({**component, "evidence_records": verified})
    core["components"] = [*existing, *accepted]
    return _replace(output, issue.entity_path, core)
