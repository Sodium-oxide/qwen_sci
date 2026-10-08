"""Bound skeleton requests by mathematical dependency closure and recover per group."""

from collections.abc import Mapping
from copy import deepcopy

from .formal_dependency import COLLECTION_IDS, expression_symbols, expression_variable_ids


def record_index(formal_inputs):
    records = {}
    for collection, identifier in (("definitions", "definition_id"), ("model_relations", "relation_id")):
        for record in formal_inputs.get(collection, []):
            if isinstance(record, Mapping) and isinstance(record.get(identifier), str):
                records.setdefault(record[identifier], record)
    return records


def record_dependencies(record, records):
    dependencies = {
        reference for reference in record.get("depends_on", []) or []
        if isinstance(reference, str)
    }
    symbols = expression_symbols({key: record.get(key) for key in ("formal_expression", "condition_expressions")})
    symbols.update(reference for reference in record.get("symbol_references", []) or [] if isinstance(reference, str))
    variables = expression_variable_ids(record)
    stack = [record.get("formal_expression"), record.get("condition_expressions")]
    while stack:
        value = stack.pop()
        if isinstance(value, Mapping):
            if isinstance(value.get("ref"), str):
                dependencies.add(value["ref"])
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    dependencies.update(
        identifier for identifier, candidate in records.items()
        if "definition_id" in candidate
        and (candidate.get("symbol") in symbols
             or variables.intersection(candidate.get("variable_references", []) or []))
    )
    return dependencies - {record.get("definition_id"), record.get("relation_id")}


def dependency_batch(formal_inputs, root_ids, *, max_definitions=24, max_relations=16):
    records = record_index(formal_inputs)
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
            {"record_id": identifier, "symbol": records.get(identifier, {}).get("symbol"),
             "statement": str(records.get(identifier, {}).get("statement") or "")[:160],
             "status": "context_only"}
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
            if isinstance(record, Mapping) and isinstance(record.get(field), str) and record[field] not in existing_ids:
                redirects[record[field]] = f"{group_id}_{record[field]}"

    reference_fields = set(COLLECTION_IDS.values()) | {
        "premises", "depends_on", "assumption_ids", "global_assumption_ids", "required_obligation_ids",
        "target_id", "ref", "record_id", "target_proposition_id", "lemma_id",
    }

    def rewrite(value, field=""):
        if isinstance(value, Mapping):
            return {key: rewrite(item, key) for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item, field) for item in value]
        if isinstance(value, str) and field in reference_fields:
            return redirects.get(value, value)
        return value

    return rewrite(result)
