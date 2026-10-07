"""Apply LLM definition repairs and scoped notation changes before plan recovery."""

from collections.abc import Mapping
from copy import deepcopy
import re

from .formal_dependency import COLLECTION_IDS


def _plan_steps(payload):
    for step in payload.get("forward_derivation", {}).get("steps", []):
        yield f"forward_derivation/{step.get('step_id')}", step
    for attempt in payload.get("proof_attempts", []):
        for step in attempt.get("steps", []):
            yield f"{attempt.get('attempt_id')}/{step.get('step_id')}", step


def _rewrite_symbols(value, renames):
    if isinstance(value, Mapping):
        return {key: (renames.get(item, item) if key == "symbol" and isinstance(item, str)
                      else _rewrite_symbols(item, renames)) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_symbols(item, renames) for item in value]
    return value


def _rewrite_record_symbols(record, renames):
    for field in ("formal_expression", "condition_expressions", "predicate_expression",
                  "domain_expression", "conclusion_expression", "derived_expression",
                  "quantifiers", "calculation_steps", "variable_bindings"):
        if field in record:
            record[field] = _rewrite_symbols(record[field], renames)
    record["symbol_references"] = list(dict.fromkeys(
        renames.get(reference, reference) for reference in record.get("symbol_references", [])
    ))
    for field in ("expression_latex", "statement", "derived_statement", "predicate", "conclusion", "conditions"):
        if field not in record:
            continue
        pattern = "|".join(re.escape(symbol) for symbol in sorted(renames, key=len, reverse=True))
        if not pattern:
            continue
        def rewrite(text):
            return re.sub(r"(?<![\w])(?:" + pattern + r")(?![\w])",
                          lambda match: renames[match.group()], text) if isinstance(text, str) else text
        record[field] = [rewrite(item) for item in record[field]] if isinstance(record[field], list) else rewrite(record[field])


def apply_definition_reconciliation(payload, patch, evidence_bundle=None):
    from .formal_definition_resolver import FormalDefinitionResolver
    from .reasoning_validation import _verified_markers

    if not isinstance(patch, Mapping):
        raise ValueError("definition_reconciliation_patch_not_object")
    result = deepcopy(payload)
    records = {}
    collections = {}
    for collection, identifier in COLLECTION_IDS.items():
        for record in result.get(collection, []):
            record_id = record.get(identifier)
            if record_id in records:
                raise ValueError(f"definition_reconciliation_duplicate_id:{record_id}")
            records[record_id] = record
            collections[record_id] = collection
    step_instances = {}
    for scoped_id, step in _plan_steps(result):
        identifier = step.get("step_id")
        if not isinstance(identifier, str):
            continue
        if scoped_id in records:
            raise ValueError(f"definition_reconciliation_duplicate_step_scope:{scoped_id}")
        records[scoped_id] = step
        collections[scoped_id] = "steps"
        step_instances.setdefault(identifier, []).append(step)
    for identifier, instances in step_instances.items():
        if identifier not in records and all(instance == instances[0] for instance in instances):
            records[identifier] = instances[0]
            collections[identifier] = "steps"
    original = deepcopy(records)
    operations = {}
    for field in ("repairs", "merges", "symbol_renames"):
        values = patch.get(field, [])
        if not isinstance(values, list) or len(values) > 64 or not all(isinstance(item, Mapping) for item in values):
            raise ValueError(f"definition_reconciliation_invalid_{field}")
        operations[field] = values
    touched = set()
    for repair in operations["repairs"]:
        identifier = repair.get("record_id")
        fields = repair.get("fields")
        if identifier not in records or not isinstance(fields, Mapping) or not fields:
            raise ValueError("definition_reconciliation_invalid_repair")
        if set(fields) & {"definition_id", "relation_id", "source_refs", "audit_refs"}:
            raise ValueError("definition_reconciliation_protected_field")
        records[identifier].update(deepcopy(fields))
        touched.add(identifier)
    redirects = {}
    merged_symbols = {}
    for merge in operations["merges"]:
        retained_id = merge.get("retained_id")
        merged_ids = merge.get("merged_ids")
        if (retained_id not in records or collections[retained_id] != "definitions"
                or not isinstance(merged_ids, list) or not merged_ids
                or not all(isinstance(identifier, str) and identifier in records
                           and collections[identifier] == "definitions" and identifier != retained_id
                           for identifier in merged_ids)):
            raise ValueError("definition_reconciliation_invalid_merge")
        retained = records[retained_id]
        for identifier in merged_ids:
            if identifier in redirects or retained_id in redirects:
                raise ValueError("definition_reconciliation_overlapping_merge")
            alternative = records[identifier]
            redirects[identifier] = retained_id
            merged_symbols[identifier] = (alternative.get("symbol"), retained.get("symbol"))
            for field in ("source_refs", "variable_references"):
                for item in alternative.get(field, []):
                    if item not in retained.setdefault(field, []):
                        retained[field].append(deepcopy(item))
        touched.add(retained_id)
    for record_id, record in records.items():
        renames = {old: new for identifier, (old, new) in merged_symbols.items()
                   if identifier in record.get("depends_on", []) and old and new and old != new}
        if renames:
            _rewrite_record_symbols(record, renames)
        for field in ("depends_on", "premises", "assumption_ids"):
            if field in record:
                rewritten = list(dict.fromkeys(redirects.get(identifier, identifier) for identifier in record[field]))
                if rewritten != record[field]:
                    touched.add(record_id)
                record[field] = rewritten
    pending_renames = {}
    for rename in operations["symbol_renames"]:
        identifier = rename.get("definition_id")
        symbol = rename.get("symbol")
        affected_ids = rename.get("affected_ids", [])
        if (identifier not in records or identifier in redirects or collections[identifier] != "definitions"
                or not isinstance(symbol, str) or not symbol.strip()
                or not isinstance(affected_ids, list) or not all(isinstance(owner, str) and owner in records for owner in affected_ids)):
            raise ValueError("definition_reconciliation_invalid_symbol_rename")
        old_symbol = records[identifier].get("symbol")
        if not isinstance(old_symbol, str) or not old_symbol:
            if affected_ids:
                raise ValueError("definition_reconciliation_missing_original_symbol")
            records[identifier]["symbol"] = symbol
            touched.add(identifier)
            continue
        records[identifier]["symbol"] = symbol
        touched.add(identifier)
        for owner in affected_ids:
            mapping = pending_renames.setdefault(owner, {})
            if old_symbol in mapping and mapping[old_symbol] != symbol:
                raise ValueError("definition_reconciliation_ambiguous_symbol_scope")
            mapping[old_symbol] = symbol
            touched.add(owner)
    for identifier, renames in pending_renames.items():
        _rewrite_record_symbols(records[identifier], renames)
    for identifier, instances in step_instances.items():
        if identifier not in touched or collections.get(identifier) != "steps":
            continue
        updated = deepcopy(records[identifier])
        for instance in instances:
            instance.clear()
            instance.update(deepcopy(updated))
    for collection, id_field in (("definitions", "definition_id"), ("model_relations", "relation_id")):
        result[collection] = [record for record in result.get(collection, []) if record[id_field] not in redirects]
    for identifier in touched:
        record = records[identifier]
        if record.get("verification_readiness") != "blocked":
            record.pop("dependency_health", None)
            record.pop("construction_status", None)
    validation_payload = {
        "schema_version": "formal_definition_resolution_v1",
        "definitions": result.get("definitions", []),
        "model_relations": result.get("model_relations", []),
        "unknown_items": result.get("unknown_items", []),
    }
    FormalDefinitionResolver._validate(validation_payload, evidence_bundle or {})
    errors = _verified_markers(result)
    if errors:
        raise ValueError("; ".join(errors))
    known_ids = set(records) - set(redirects)
    for identifier in touched:
        if set(records[identifier].get("depends_on", [])) - known_ids:
            raise ValueError(f"definition_reconciliation_unknown_dependency:{identifier}")
    for item in result.get("unknown_items", []):
        owner = item.get("record_id") or next((part for part in str(item.get("field_path", "")).split(".") if part in touched), None)
        if owner in touched and records[owner] != original[owner] and records[owner].get("verification_readiness") != "blocked":
            item.update(resolved=True, status="resolved")
    if touched or redirects:
        result.setdefault("reconciliation_audit", []).append({
            "patch": deepcopy(dict(patch)), "id_redirects": redirects,
            "changes": [{"record_id": identifier, "before": original[identifier],
                         "after": None if identifier in redirects else deepcopy(records[identifier])}
                        for identifier in sorted(touched | set(redirects))],
        })
    return result


def definition_conflicts(payload):
    seen_ids = set()
    seen_symbols = set()
    conflicts = []
    for record in payload.get("definitions", []):
        identifier = record.get("definition_id")
        symbol = record.get("symbol")
        if identifier in seen_ids or symbol in seen_symbols:
            conflicts.append(identifier)
        seen_ids.add(identifier)
        seen_symbols.add(symbol)
    return conflicts


def reconciliation_record_scope(payload):
    """Select conflict records and their direct consumers for LLM review."""

    definitions = [record for record in payload.get("definitions", []) if isinstance(record, Mapping)]
    by_symbol = {}
    for record in definitions:
        symbol = record.get("symbol")
        if isinstance(symbol, str) and symbol:
            by_symbol.setdefault(symbol, []).append(record)
    duplicate_symbols = {symbol for symbol, records in by_symbol.items() if len(records) > 1}
    conflict_ids = {
        record.get("definition_id")
        for record in definitions
        if record.get("symbol") in duplicate_symbols
    }
    conflict_ids.update(identifier for identifier in definition_conflicts(payload) if isinstance(identifier, str))
    if not conflict_ids:
        return {
            "payload": deepcopy(payload),
            "conflict_definition_ids": [],
            "conflict_symbols": [],
            "direct_consumer_ids": [],
            "omitted_definition_count": 0,
        }

    def record_symbols(record):
        symbols = set(record.get("symbol_references", []) or [])
        for field in ("formal_expression", "condition_expressions", "predicate_expression", "conclusion_expression", "derived_expression"):
            value = record.get(field)
            stack = [value]
            while stack:
                item = stack.pop()
                if isinstance(item, Mapping):
                    if isinstance(item.get("symbol"), str):
                        symbols.add(item["symbol"])
                    stack.extend(item.values())
                elif isinstance(item, list):
                    stack.extend(item)
        return symbols

    conflict_symbols = set(duplicate_symbols)
    consumer_ids = set()
    scoped_records = {}
    for collection, identifier_field in COLLECTION_IDS.items():
        for record in payload.get(collection, []):
            if not isinstance(record, Mapping):
                continue
            identifier = record.get(identifier_field)
            references = {
                str(reference)
                for field in ("depends_on", "premises", "assumption_ids")
                for reference in (record.get(field, []) or [])
                if isinstance(reference, str)
            }
            is_consumer = bool(references & conflict_ids or record_symbols(record) & conflict_symbols)
            if identifier in conflict_ids or is_consumer:
                if isinstance(identifier, str):
                    consumer_ids.add(identifier)
                    scoped_records.setdefault(collection, []).append(deepcopy(record))

    for scoped_id, step in _plan_steps(payload):
        references = {
            str(reference)
            for field in ("depends_on", "premises", "assumption_ids")
            for reference in (step.get(field, []) or [])
            if isinstance(reference, str)
        }
        if references & conflict_ids or record_symbols(step) & conflict_symbols:
            consumer_ids.add(scoped_id)

    scoped = deepcopy(payload)
    for collection, identifier_field in COLLECTION_IDS.items():
        keep_ids = {
            record.get(identifier_field)
            for record in scoped_records.get(collection, [])
            if isinstance(record, Mapping)
        }
        scoped[collection] = [
            deepcopy(record) for record in payload.get(collection, [])
            if isinstance(record, Mapping) and record.get(identifier_field) in keep_ids
        ]
    scoped["unknown_items"] = [
        deepcopy(item) for item in payload.get("unknown_items", [])
        if not isinstance(item, Mapping)
        or any(identifier in str(item.get("field_path", "")) for identifier in consumer_ids)
    ]
    return {
        "payload": scoped,
        "conflict_definition_ids": sorted(identifier for identifier in conflict_ids if isinstance(identifier, str)),
        "conflict_symbols": sorted(conflict_symbols),
        "direct_consumer_ids": sorted(consumer_ids - conflict_ids),
        "omitted_definition_count": max(0, len(definitions) - len(scoped.get("definitions", []))),
    }


def reconciliation_dependent_records(payload, scope):
    """Return bounded summaries for non-definition records affected by conflicts."""

    direct_ids = set(scope.get("direct_consumer_ids", []))
    summaries = []
    fields = (
        "statement", "target", "scope", "conclusion", "status", "depends_on", "premises",
        "assumption_ids", "symbol_references", "variable_references", "formal_expression",
        "condition_expressions", "required_obligation_ids", "target_id",
    )
    for collection, identifier_field in COLLECTION_IDS.items():
        if collection in ("definitions", "model_relations"):
            continue
        for record in payload.get(collection, []):
            if not isinstance(record, Mapping) or record.get(identifier_field) not in direct_ids:
                continue
            summary = {"record_id": record.get(identifier_field), "collection": collection}
            summary.update({field: deepcopy(record[field]) for field in fields if field in record})
            summaries.append(summary)
    for scoped_id, step in _plan_steps(payload):
        if scoped_id not in direct_ids:
            continue
        summary = {"record_id": scoped_id, "collection": "steps"}
        summary.update({field: deepcopy(step[field]) for field in fields if field in step})
        summaries.append(summary)
    return summaries


def reconciliation_variable_ids(payload, scope):
    variable_ids = set()
    scoped = scope.get("payload", {}) if isinstance(scope, Mapping) else {}
    for collection in COLLECTION_IDS:
        for record in scoped.get(collection, []):
            if isinstance(record, Mapping):
                variable_ids.update(reference for reference in record.get("variable_references", []) or []
                                    if isinstance(reference, str))
    for record in reconciliation_dependent_records(payload, scope):
        variable_ids.update(reference for reference in record.get("variable_references", []) or []
                            if isinstance(reference, str))
    return variable_ids


def prepare_definition_candidates(payload):
    result = deepcopy(payload)
    retained = []
    seen = {}
    for record in result.get("definitions", []):
        identifier = record.get("definition_id")
        if identifier in seen:
            if record == seen[identifier]:
                continue
            candidate_number = 1
            identifiers = {item.get("definition_id") for item in result["definitions"]} | set(seen)
            candidate_id = f"{identifier}__candidate_{candidate_number}"
            while candidate_id in identifiers:
                candidate_number += 1
                candidate_id = f"{identifier}__candidate_{candidate_number}"
            record["definition_id"] = candidate_id
            identifier = candidate_id
        seen[identifier] = record
        retained.append(record)
    result["definitions"] = retained
    return result


def repair_plan_symbol_conflicts(plan, variable_claim_model, *, llm_call, logger=None, brief_id=""):
    from .formal_definition_resolver import RECONCILIATION_REVIEW_PROMPT, _reconciliation_catalog
    from .llm_json import call_required_json_with_logging, json_prompt_payload
    from .formal_plan_recovery import construction_warning

    if not definition_conflicts(plan):
        return plan
    candidates = prepare_definition_candidates(plan)
    scope = reconciliation_record_scope(candidates)
    scoped_candidates = scope["payload"]
    consumers = reconciliation_dependent_records(candidates, scope)
    relevant_variable_ids = reconciliation_variable_ids(candidates, scope)
    prompt = RECONCILIATION_REVIEW_PROMPT + json_prompt_payload({
        "candidate_catalog": _reconciliation_catalog(scoped_candidates),
        "dependent_records": consumers,
        "variable_registry": [
            variable for variable in (variable_claim_model or {}).get("variables", [])
            if isinstance(variable, Mapping)
            and (not relevant_variable_ids or variable.get("variable_id") in relevant_variable_ids)
        ],
        "scope": {key: value for key, value in scope.items() if key != "payload"},
    })
    try:
        patch = call_required_json_with_logging(
            llm_call, prompt, stage="formal_definition_resolver", request_kind="repair_plan_symbol_conflicts",
            logger=logger, brief_id=brief_id,
        )
        repaired = apply_definition_reconciliation(candidates, patch)
        remaining = definition_conflicts(repaired)
        if remaining:
            construction_warning(
                repaired, "definitions", "symbol",
                f"LLM notation repair left unresolved conflicts: {', '.join(map(str, remaining))}. "
                "The conflicting candidates remain available for subsequent revision.",
                logger=logger, brief_id=brief_id,
            )
        if logger is not None:
            logger.event("formal_definition_resolver", "plan_symbols_reconciled", status="COMPLETED",
                         brief_id=brief_id, remaining_conflict_count=len(definition_conflicts(repaired)))
        return repaired
    except Exception as error:
        construction_warning(
            candidates, "definitions", "symbol",
            f"LLM notation repair failed: {type(error).__name__}: {error}",
            logger=logger, brief_id=brief_id,
        )
        if logger is not None:
            logger.event("formal_definition_resolver", "plan_symbol_repair_warning", level="WARNING",
                         status="WARNING", brief_id=brief_id, error_detail=f"{type(error).__name__}: {error}")
        return candidates
