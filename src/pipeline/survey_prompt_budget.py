"""Bound structured Survey inputs without cutting serialized JSON."""

from collections.abc import Mapping
import json


def compact_value(value, text_limit=4000, list_limit=12, depth=0):
    if isinstance(value, str):
        return value if len(value) <= text_limit else value[:text_limit] + " [truncated; original retained in Survey artifacts]"
    if isinstance(value, Mapping):
        if depth >= 10:
            return {"_omitted_nested_fields": len(value)}
        return {str(key): compact_value(item, text_limit, list_limit, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        result = [compact_value(item, text_limit, list_limit, depth + 1) for item in value[:list_limit]]
        if len(value) > list_limit:
            result.append({"_omitted_items": len(value) - list_limit})
        return result
    return value


def project_fields(record, fields):
    return {key: record[key] for key in fields if key in record}


def serialize_prompt(prefix, payload):
    return prefix + json.dumps(payload, ensure_ascii=False)


def fit_payload(prefix, payload, measure, limit):
    result = payload
    text_limit, list_limit = 4000, 12
    while measure(serialize_prompt(prefix, result)) > limit and text_limit >= 32:
        result = compact_value(payload, text_limit, list_limit)
        if isinstance(payload, Mapping) and isinstance(payload.get("original_topic"), str):
            result["original_topic"] = payload["original_topic"]
        for key in ("papers", "candidates", "subhypotheses", "paper_results", "registered_objects", "evidence_ledger"):
            if isinstance(payload.get(key), list):
                result[key] = [compact_value(record, text_limit, list_limit) for record in payload[key]]
        text_limit //= 2
        list_limit = max(1, list_limit // 2)
    return result


def planning_batches(prefix, base, collections, measure, limit):
    base = fit_payload(prefix, base, measure, limit // 2)
    batch = dict(base, **{key: [] for key in collections})
    batches = []
    pending = {key: iter(values) for key, values in collections.items()}
    while pending:
        for key in list(pending):
            try:
                record = next(pending[key])
            except StopIteration:
                pending.pop(key)
                continue
            single = dict(base, **{field: [] for field in collections})
            single[key] = [record]
            if measure(serialize_prompt(prefix, single)) > limit:
                single = fit_payload(prefix, single, measure, limit)
                record = single[key][0]
            batch[key].append(record)
            if measure(serialize_prompt(prefix, batch)) > limit:
                batch[key].pop()
                if any(batch[field] for field in collections):
                    batches.append(batch)
                batch = single
    if not batches or any(batch[field] for field in collections):
        batches.append(batch)
    return batches
