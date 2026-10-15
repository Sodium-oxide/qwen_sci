"""Bound skeleton requests by mathematical dependency closure and recover per group."""

from collections.abc import Mapping
from copy import deepcopy

from .formal_dependency import COLLECTION_IDS, declared_dependencies, expression_variable_ids, related_context_ids


def record_index(formal_inputs):
    records = {}
    for collection, identifier in (("definitions", "definition_id"), ("model_relations", "relation_id")):
        for record in formal_inputs.get(collection, []):
            if isinstance(record, Mapping) and isinstance(record.get(identifier), str):
                records.setdefault(record[identifier], record)
    return records


def record_dependencies(record, records):
    return declared_dependencies(record)


def dependency_batch(formal_inputs, root_ids, *, max_definitions=24, max_relations=16):
    records = record_index(formal_inputs)
    registry_objects = formal_inputs.get("object_registry", {}).get("objects", {})
    known_records = {identifier: entry.get("record", {}) for identifier, entry in registry_objects.items()}
    known_records.update(records)
    selected = {}
    pending = list(dict.fromkeys(root_ids))
    omitted = set()
    counts = {"definitions": 0, "model_relations": 0}
    while pending:
        identifier = pending.pop(0)
        if identifier in selected or identifier in omitted:
            continue
        record = records.get(identifier)
        if record is None:
            omitted.add(identifier)
            continue
        collection = "definitions" if "definition_id" in record else "model_relations"
        limit = max_definitions if collection == "definitions" else max_relations
        if counts[collection] >= limit:
            omitted.add(identifier)
            continue
        selected[identifier] = record
        counts[collection] += 1
        pending.extend(sorted(record_dependencies(record, records) - set(selected)))
    variables = {
        reference for record in selected.values()
        for reference in record.get("variable_references", []) or [] if isinstance(reference, str)
    }
    variables.update(expression_variable_ids(list(selected.values())))
    return {
        "root_ids": list(root_ids),
        "definitions": [deepcopy(record) for record in selected.values() if "definition_id" in record],
        "model_relations": [deepcopy(record) for record in selected.values() if "relation_id" in record],
        "unknown_items": [deepcopy(item) for item in formal_inputs.get("unknown_items", [])
                          if isinstance(item, Mapping) and any(identifier in str(item.get("field_path", "")) for identifier in selected)][:12],
        "variable_ids": sorted(variables),
        "external_dependencies": [
            {"record_id": identifier, "symbol": known_records.get(identifier, {}).get("symbol"),
             "statement": str(known_records.get(identifier, {}).get("statement") or "")[:160],
             "status": "context_only" if identifier in known_records else "missing",
             "exists_in_registry": identifier in known_records}
            for identifier in sorted(omitted)
        ],
    }


def build_skeleton_batches(formal_inputs, *, max_definitions=24, max_relations=16):
    max_definitions = max(1, min(24, int(max_definitions)))
    max_relations = max(1, int(max_relations))
    records = record_index(formal_inputs)
    pending = list(records)
    batches = []
    while pending:
        roots = [pending.pop(0)]
        batch = dependency_batch(formal_inputs, roots, max_definitions=max_definitions, max_relations=max_relations)
        for identifier in list(pending):
            trial = dependency_batch(formal_inputs, roots + [identifier], max_definitions=max_definitions, max_relations=max_relations)
            trial_ids = {record.get("definition_id", record.get("relation_id"))
                         for collection in ("definitions", "model_relations") for record in trial[collection]}
            existing_ids = {record.get("definition_id", record.get("relation_id"))
                            for collection in ("definitions", "model_relations") for record in batch[collection]}
            if identifier in trial_ids and existing_ids <= trial_ids:
                roots.append(identifier)
                pending.remove(identifier)
                batch = trial
        batches.append(batch)
    return batches or [dependency_batch(formal_inputs, [])]


def compact_skeleton_payload(payload, *, aggressive=False):
    result = deepcopy(payload)
    omitted = result.setdefault("omitted_context", {})
    shortened = []

    def shorten(value, path):
        if isinstance(value, str) and len(value) > (400 if aggressive else 1600):
            shortened.append({"field_path": path, "original_chars": len(value)})
            return value[:400 if aggressive else 1600]
        if isinstance(value, Mapping):
            return {key: shorten(item, f"{path}.{key}") for key, item in value.items()}
        if isinstance(value, list):
            return [shorten(item, f"{path}[{index}]") for index, item in enumerate(value[:8 if aggressive else 16])]
        return value

    for field in ("research_brief", "reasoning_context", "variable_claim_model"):
        result[field] = shorten(result.get(field, {}), field)
    for collection in ("definitions", "model_relations"):
        for record in result["resolved_inputs"][collection]:
            for field in ("statement", "scope", "domain", "codomain"):
                if field in record:
                    record[field] = shorten(record[field], f"{collection}.{record.get('definition_id', record.get('relation_id'))}.{field}")
    evidence = result.get("evidence_bundle", {})
    cards = evidence.get("evidence_cards", []) if isinstance(evidence, Mapping) else []
    if aggressive:
        cards = [{key: card.get(key) for key in ("card_id", "source_id", "statement")}
                 for card in cards[:4] if isinstance(card, Mapping)]
    else:
        cards = [deepcopy(card) for card in cards if isinstance(card, Mapping)]
    catalog = [] if aggressive else deepcopy(evidence.get("evidence_catalog", [])) if isinstance(evidence, Mapping) else []
    result["evidence_bundle"] = shorten({
        "evidence_role": "reference", "evidence_cards": cards, "evidence_catalog": catalog,
    }, "evidence_bundle")
    if aggressive:
        omitted["encoding_deferred_ids"] = []
        for collection in ("definitions", "model_relations"):
            for record in result["resolved_inputs"][collection]:
                if record.get("formal_expression") is not None or record.get("condition_expressions"):
                    omitted["encoding_deferred_ids"].append(record.get("definition_id", record.get("relation_id")))
                    record["formal_expression"] = None
                    record["condition_expressions"] = []
        result["external_dependencies"] = result.get("external_dependencies", [])[:24]
    omitted["shortened_text_fields"] = shortened
    return result


def namespace_skeleton_response(response, group_id, existing_ids):
    result = deepcopy(response)
    redirects = {}
    for collection, field in COLLECTION_IDS.items():
        values = result.get(collection, [])
        if isinstance(values, Mapping):
            values = [dict(values)] if field in values else list(values.values())
            result[collection] = values
        if not isinstance(values, list):
            continue
        for record in values:
            if (isinstance(record, Mapping) and isinstance(record.get(field), str)
                    and record[field] not in existing_ids and not record[field].startswith(f"{group_id}_")):
                redirects[record[field]] = f"{group_id}_{record[field]}"

    from .formal_object_registry import rewrite_live_references
    return rewrite_live_references(result, redirects)
