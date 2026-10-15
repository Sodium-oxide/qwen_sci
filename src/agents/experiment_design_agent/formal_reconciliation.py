"""Apply LLM definition repairs and scoped notation changes before plan recovery."""

from collections.abc import Mapping
from copy import deepcopy
import json
import re

from .formal_dependency import COLLECTION_IDS


def _plan_steps(payload):
    derivation = payload.get("forward_derivation", {})
    if isinstance(derivation, Mapping):
        for step in derivation.get("steps", []) if isinstance(derivation.get("steps", []), list) else []:
            if isinstance(step, Mapping):
                yield f"forward_derivation/{step.get('step_id')}", step
    attempts = payload.get("proof_attempts", [])
    if not isinstance(attempts, list):
        return
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            continue
        steps = attempt.get("steps", [])
        if not isinstance(steps, list):
            continue
        for step in steps:
            if isinstance(step, Mapping):
                yield f"{attempt.get('attempt_id')}/{step.get('step_id')}", step


def _rewrite_symbols(value, renames):
    if isinstance(value, Mapping):
        return {key: (renames.get(item, item) if key == "symbol" and isinstance(item, str)
                      else _rewrite_symbols(item, renames)) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_symbols(item, renames) for item in value]
    return value


def _rewrite_record_symbols(record, renames, *, bound_symbols=()):
    from .formal_object_registry import rewrite_record_symbols
    return rewrite_record_symbols(record, renames, bound_symbols=bound_symbols)


def _step_bindings(payload):
    from .formal_dependency import bound_symbols
    targets = {record.get("proposition_id", record.get("lemma_id")): bound_symbols(record)
               for record in payload.get("propositions", []) + payload.get("lemmas", [])}
    bindings = {}
    envelopes = [("forward_derivation", payload.get("forward_derivation", {}))]
    envelopes.extend((attempt.get("attempt_id"), attempt) for attempt in payload.get("proof_attempts", [])
                     if isinstance(attempt, Mapping))
    for scope, envelope in envelopes:
        if not isinstance(envelope, Mapping):
            continue
        target_id = envelope.get("target_id", envelope.get("target_proposition_id"))
        local = set(targets.get(target_id, set())) if isinstance(target_id, str) else set()
        steps = envelope.get("steps", [])
        for step in steps if isinstance(steps, list) else []:
            if isinstance(step, Mapping):
                local.update(bound_symbols(step))
                bindings[f"{scope}/{step.get('step_id')}"] = set(local)
                bindings.setdefault(step.get("step_id"), set()).update(local)
    return bindings


class _ReconciliationOperationError(ValueError):
    def __init__(self, code, action, index, record_id=None, invalid_ids=(), detail=""):
        super().__init__(code + (f": {detail}" if detail else ""))
        self.action = action
        self.index = index
        self.record_id = record_id
        self.invalid_ids = list(invalid_ids)


def _string_references(record, field):
    values = record.get(field, [])
    return [value for value in values if isinstance(value, str)] if isinstance(values, list) else []


def apply_definition_reconciliation(payload, patch, evidence_bundle=None, *, logger=None, brief_id=""):
    if not isinstance(patch, Mapping):
        raise ValueError("definition_reconciliation_patch_not_object")
    operations = {}
    rejected = []

    def reject(action, index, operation, error):
        diagnostic = {
            "action": action, "operation_index": index,
            "record_id": getattr(error, "record_id", None),
            "invalid_ids": getattr(error, "invalid_ids", []),
            "error_code": str(error).split(":", 1)[0], "reason": str(error),
            "raw_json": json.dumps(operation, ensure_ascii=False, sort_keys=True),
        }
        rejected.append(diagnostic)
        if logger is not None:
            logger.event("formal_definition_resolver", "reconciliation_operation_warning",
                         level="WARNING", status="WARNING", brief_id=brief_id,
                         action=action, operation_index=index, record_id=diagnostic["record_id"],
                         invalid_ids=diagnostic["invalid_ids"], error_code=diagnostic["error_code"],
                         error_detail=diagnostic["reason"], disposition="ignored_and_archived")

    for action in ("repairs", "merges", "symbol_renames"):
        values = patch.get(action, [])
        operations[action] = []
        if not isinstance(values, list) or len(values) > 64:
            reject(action, None, values, ValueError(f"definition_reconciliation_invalid_{action}"))
            continue
        for index, operation in enumerate(values):
            if not isinstance(operation, Mapping):
                reject(action, index, operation, ValueError(f"definition_reconciliation_invalid_{action}_operation"))
            else:
                operations[action].append((index, operation))
    while True:
        active_patch = {action: [operation for _, operation in values] for action, values in operations.items()}
        try:
            result = _apply_definition_reconciliation(payload, active_patch, evidence_bundle)
            break
        except _ReconciliationOperationError as error:
            index, operation = operations[error.action].pop(error.index)
            reject(error.action, index, operation, error)
    if rejected:
        result.setdefault("reconciliation_audit", []).append({
            "rejected_operations": rejected,
            "accepted_operation_count": sum(len(values) for values in operations.values()),
        })
    return result


def _apply_definition_reconciliation(payload, patch, evidence_bundle=None):
    from .formal_definition_resolver import FormalDefinitionResolver, normalize_model_relation_formats
    from .reasoning_validation import _verified_markers

    if not isinstance(patch, Mapping):
        raise ValueError("definition_reconciliation_patch_not_object")
    if not isinstance(payload, Mapping):
        raise ValueError("definition_reconciliation_payload_not_object")
    result = deepcopy(payload)
    records = {}
    collections = {}
    for collection, identifier in COLLECTION_IDS.items():
        values = result.get(collection, [])
        if not isinstance(values, list):
            raise ValueError(f"definition_reconciliation_invalid_collection:{collection}")
        for index, record in enumerate(values):
            if not isinstance(record, Mapping):
                raise ValueError(f"definition_reconciliation_record_not_object:{collection}[{index}]")
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
    step_bindings = _step_bindings(result)
    operations = {}
    for field in ("repairs", "merges", "symbol_renames"):
        values = patch.get(field, [])
        if not isinstance(values, list) or len(values) > 64 or not all(isinstance(item, Mapping) for item in values):
            raise ValueError(f"definition_reconciliation_invalid_{field}")
        operations[field] = values
    touched = set()
    owners = {}
    field_owners = {}
    for index, repair in enumerate(operations["repairs"]):
        identifier = repair.get("record_id")
        fields = repair.get("fields")
        if not isinstance(identifier, str) or identifier not in records or not isinstance(fields, Mapping) or not fields:
            raise _ReconciliationOperationError("definition_reconciliation_invalid_repair", "repairs", index,
                                                identifier, [identifier])
        if set(fields) & {*COLLECTION_IDS.values(), "step_id", "attempt_id", "audit_refs"}:
            raise _ReconciliationOperationError("definition_reconciliation_protected_field", "repairs", index, identifier)
        records[identifier].update(deepcopy(fields))
        touched.add(identifier)
        owners[identifier] = ("repairs", index)
        for field in fields:
            field_owners[identifier, field] = ("repairs", index)
    redirects = {}
    merged_symbols = {}
    for index, merge in enumerate(operations["merges"]):
        retained_id = merge.get("retained_id")
        merged_ids = merge.get("merged_ids")
        if (not isinstance(retained_id, str) or retained_id not in records or collections[retained_id] != "definitions"
                or not isinstance(merged_ids, list) or not merged_ids
                or not all(isinstance(identifier, str) and identifier in records
                           and collections[identifier] == "definitions" and identifier != retained_id
                           for identifier in merged_ids)):
            raise _ReconciliationOperationError("definition_reconciliation_invalid_merge", "merges", index,
                                                retained_id, merged_ids if isinstance(merged_ids, list) else [])
        retained = records[retained_id]
        for identifier in merged_ids:
            if identifier in redirects or retained_id in redirects:
                raise _ReconciliationOperationError("definition_reconciliation_overlapping_merge", "merges", index,
                                                    retained_id, [identifier])
            alternative = records[identifier]
            redirects[identifier] = retained_id
            merged_symbols[identifier] = (alternative.get("symbol"), retained.get("symbol"))
            for field in ("source_refs", "variable_references"):
                if not isinstance(alternative.get(field, []), list) or not isinstance(retained.get(field, []), list):
                    raise _ReconciliationOperationError("definition_reconciliation_invalid_merge_references",
                                                        "merges", index, retained_id, [identifier], field)
                for item in alternative.get(field, []):
                    if item not in retained.setdefault(field, []):
                        retained[field].append(deepcopy(item))
        touched.add(retained_id)
        owners[retained_id] = ("merges", index)
    for identifier in redirects:
        target = redirects[identifier]
        while target in redirects:
            target = redirects[target]
        redirects[identifier] = target
    merged_symbols = {identifier: (symbols[0], records[redirects[identifier]].get("symbol"))
                      for identifier, symbols in merged_symbols.items()}
    for record_id, record in records.items():
        references = {reference for field in ("depends_on", "premises", "assumption_ids")
                      for reference in _string_references(record, field)}
        renames = {old: new for identifier, (old, new) in merged_symbols.items()
                   if identifier in references and isinstance(old, str) and isinstance(new, str)
                   and old and new and old != new}
        if renames:
            _rewrite_record_symbols(record, renames, bound_symbols=step_bindings.get(record_id, ()))
        for field in ("depends_on", "premises", "assumption_ids"):
            references = record.get(field)
            if isinstance(references, list) and all(isinstance(reference, str) for reference in references):
                redirected = next((reference for reference in references if reference in redirects), None)
                if redirected is None:
                    continue
                rewritten = list(dict.fromkeys(redirects.get(identifier, identifier) for identifier in references))
                if rewritten != record[field]:
                    touched.add(record_id)
                    owners.setdefault(record_id, owners[redirects[redirected]])
                record[field] = rewritten
    pending_renames = {}
    for index, rename in enumerate(operations["symbol_renames"]):
        identifier = rename.get("definition_id")
        symbol = rename.get("symbol")
        affected_ids = rename.get("affected_ids", [])
        if (not isinstance(identifier, str) or identifier not in records or identifier in redirects or collections[identifier] != "definitions"
                or not isinstance(symbol, str) or not symbol.strip()
                or not isinstance(affected_ids, list) or not all(isinstance(owner, str) and owner in records for owner in affected_ids)):
            invalid_ids = ([identifier] if not isinstance(identifier, str) or identifier not in records
                           or identifier in redirects or collections.get(identifier) != "definitions" else [])
            if isinstance(affected_ids, list):
                invalid_ids.extend(owner for owner in affected_ids if not isinstance(owner, str) or owner not in records)
            raise _ReconciliationOperationError("definition_reconciliation_invalid_symbol_rename", "symbol_renames",
                                                index, identifier, invalid_ids)
        old_symbol = records[identifier].get("symbol")
        if not isinstance(old_symbol, str) or not old_symbol:
            if affected_ids:
                raise _ReconciliationOperationError("definition_reconciliation_missing_original_symbol",
                                                    "symbol_renames", index, identifier, affected_ids)
            records[identifier]["symbol"] = symbol
            touched.add(identifier)
            owners[identifier] = ("symbol_renames", index)
            continue
        records[identifier]["symbol"] = symbol
        touched.add(identifier)
        owners[identifier] = ("symbol_renames", index)
        for owner in affected_ids:
            mapping = pending_renames.setdefault(owner, {})
            if old_symbol in mapping and mapping[old_symbol] != symbol:
                raise _ReconciliationOperationError("definition_reconciliation_ambiguous_symbol_scope",
                                                    "symbol_renames", index, identifier, [owner])
            mapping[old_symbol] = symbol
            touched.add(owner)
            owners[owner] = ("symbol_renames", index)
    for identifier, renames in pending_renames.items():
        _rewrite_record_symbols(records[identifier], renames, bound_symbols=step_bindings.get(identifier, ()))
    for identifier, instances in step_instances.items():
        if identifier not in touched or collections.get(identifier) != "steps":
            continue
        updated = deepcopy(records[identifier])
        for instance in instances:
            instance.clear()
            instance.update(deepcopy(updated))
    for collection, id_field in (("definitions", "definition_id"), ("model_relations", "relation_id")):
        result[collection] = [record for record in result.get(collection, []) if record[id_field] not in redirects]
    for definition in result.get("definitions", []):
        identifier = definition["definition_id"]
        if identifier not in owners or definition.get("symbol") == original[identifier].get("symbol"):
            continue
        collisions = [record["definition_id"] for record in result["definitions"]
                      if record["definition_id"] != identifier and record.get("symbol") == definition.get("symbol")]
        if collisions:
            action, index = owners[identifier]
            raise _ReconciliationOperationError("definition_reconciliation_symbol_collision", action, index,
                                                identifier, collisions)
    for identifier in touched:
        record = records[identifier]
        if record.get("verification_readiness") != "blocked":
            record.pop("dependency_health", None)
            record.pop("construction_status", None)
    known_ids = set(records) - set(redirects)
    encoding_diagnostics = []
    for identifier in touched:
        collection = collections[identifier]
        if collection == "model_relations" and not _verified_markers(records[identifier]):
            envelope = normalize_model_relation_formats({"model_relations": [records[identifier]], "unknown_items": []})
            records[identifier].clear()
            records[identifier].update(envelope["model_relations"][0])
            encoding_diagnostics.extend(envelope["unknown_items"])
        if collection in {"definitions", "model_relations"}:
            failures = []
            for record in (original[identifier], records[identifier]):
                trial = {"schema_version": "formal_definition_resolution_v1", "definitions": [],
                         "model_relations": [], "unknown_items": [], collection: [record]}
                try:
                    FormalDefinitionResolver._validate(trial, evidence_bundle or {})
                    failures.append(set())
                except (ValueError, TypeError, KeyError) as error:
                    failures.append(set(str(error).split("; ")))
            errors = failures[1] - failures[0]
        else:
            errors = set()
        errors.update(set(_verified_markers(records[identifier])) - set(_verified_markers(original[identifier])))
        references = records[identifier].get("depends_on", [])
        previous = original[identifier].get("depends_on", [])
        if isinstance(references, list) and isinstance(previous, list):
            missing = {reference for reference in references if isinstance(reference, str) and reference not in known_ids}
            missing -= {reference for reference in previous if isinstance(reference, str) and reference not in records}
        else:
            missing = set()
        if missing:
            errors.add(f"definition_reconciliation_unknown_dependency:{identifier}")
        if errors:
            action, index = owners[identifier]
            for (owner_id, field), operation in field_owners.items():
                if owner_id == identifier and any(re.search(r"(?:[:._])" + re.escape(field) + r"(?:[:._]|$)", error)
                                                  for error in errors):
                    action, index = operation
                    break
            raise _ReconciliationOperationError("definition_reconciliation_invalid_operation", action, index,
                                                identifier, sorted(missing), "; ".join(sorted(errors)))
    for item in result.get("unknown_items", []):
        if not isinstance(item, Mapping):
            continue
        owner = item.get("record_id") or next((part for part in str(item.get("field_path", "")).split(".") if part in touched), None)
        if owner in touched and records[owner] != original[owner] and records[owner].get("verification_readiness") != "blocked":
            item.update(resolved=True, status="resolved")
    for diagnostic in encoding_diagnostics:
        if diagnostic not in result.setdefault("unknown_items", []):
            result["unknown_items"].append(deepcopy(diagnostic))
    if touched or redirects:
        result.setdefault("reconciliation_audit", []).append({
            "patch": deepcopy(dict(patch)), "id_redirects": redirects,
            "changes": [{"record_id": identifier, "before": original[identifier],
                         "after": None if identifier in redirects else deepcopy(records[identifier])}
                        for identifier in sorted(touched | set(redirects))],
        })
    from .formal_object_registry import build_registry, rewrite_live_references
    result = rewrite_live_references(result, redirects)
    if result.get("object_registry") or redirects:
        result.setdefault("object_registry", {}).setdefault("aliases", {}).update(redirects)
        result["object_registry"] = build_registry(result)
    return result


def definition_conflicts(payload):
    seen_ids = set()
    seen_symbols = set()
    conflicts = []
    for record in payload.get("definitions", []) if isinstance(payload, Mapping) else []:
        if not isinstance(record, Mapping):
            continue
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


def normalize_duplicate_definitions(payload, *, disambiguate=True, logger=None, brief_id=""):
    from .formal_dependency import free_expression_symbols, bound_symbols, declared_dependencies
    from .formal_plan_recovery import _block_record

    result = deepcopy(payload)
    step_bindings = _step_bindings(result)
    redirects = {}
    changes = []
    fields = (
        "symbol", "statement", "object_kind", "expression_latex", "formal_expression",
        "domain", "codomain", "unit", "conditions", "condition_expressions", "depends_on",
        "definition_status", "verification_readiness", "scope",
    )

    def records():
        for collection, identifier_field in COLLECTION_IDS.items():
            for record in result.get(collection, []):
                if isinstance(record, dict):
                    yield record.get(identifier_field), record
        yield from _plan_steps(result)

    def redirect_references():
        for _, record in records():
            for field in ("depends_on", "premises", "assumption_ids"):
                values = record.get(field)
                if isinstance(values, list) and all(isinstance(value, str) for value in values):
                    record[field] = list(dict.fromkeys(redirects.get(value, value) for value in values))

    while True:
        retained = []
        merged = False
        for record in result.get("definitions", []):
            if not isinstance(record, Mapping):
                retained.append(record)
                continue
            variable_references = record.get("variable_references", [])
            if not isinstance(variable_references, list) or not all(isinstance(value, str) for value in variable_references):
                retained.append(record)
                continue
            variables = set(variable_references)
            equivalent = next((candidate for candidate in retained if isinstance(candidate, Mapping)
                               and record.get("definition_status") == "specified" and record.get("statement")
                               and isinstance(candidate.get("variable_references", []), list)
                               and all(isinstance(value, str) for value in candidate.get("variable_references", []))
                               and isinstance(candidate.get("source_refs", []), list)
                               and isinstance(record.get("source_refs", []), list)
                               and all(candidate.get(field) == record.get(field) for field in fields)
                               and (not variables or not candidate.get("variable_references")
                                    or variables == set(candidate["variable_references"]))), None)
            if equivalent is None:
                retained.append(record)
                continue
            identifier = record["definition_id"]
            canonical_id = equivalent["definition_id"]
            redirects[identifier] = canonical_id
            redirects = {source: redirects.get(target, target) for source, target in redirects.items()}
            for field in ("source_refs", "variable_references"):
                for reference in record.get(field, []):
                    if reference not in equivalent.setdefault(field, []):
                        equivalent[field].append(deepcopy(reference))
            changes.append({"record_id": identifier, "retained_id": canonical_id,
                            "before": deepcopy(record), "action": "merge_equivalent"})
            merged = True
        result["definitions"] = retained
        if not merged:
            break
        redirect_references()

    renames = {}
    ambiguous = set()
    if disambiguate:
        groups = {}
        used_symbols = {record.get("symbol") for record in result.get("definitions", [])
                        if isinstance(record, Mapping) and isinstance(record.get("symbol"), str)}
        for record in result.get("definitions", []):
            if isinstance(record, Mapping) and isinstance(record.get("symbol"), str) and record["symbol"]:
                groups.setdefault(record["symbol"], []).append(record)
        for symbol, definitions in groups.items():
            if len(definitions) < 2:
                continue
            definition_ids = {record["definition_id"] for record in definitions}
            for definition in definitions[1:]:
                identifier = definition["definition_id"]
                suffix = re.sub(r"[^A-Za-z0-9_]", "_", identifier)
                renamed = f"{symbol}__{suffix}"
                number = 2
                while renamed in used_symbols:
                    renamed = f"{symbol}__{suffix}_{number}"
                    number += 1
                used_symbols.add(renamed)
                renames[identifier] = renamed
                changes.append({"record_id": identifier, "before": deepcopy(definition),
                                "symbol": renamed, "action": "preserve_distinct_definition"})
            for identifier, record in records():
                references = declared_dependencies(record)
                owners = references & definition_ids
                if not owners and record.get("variable_references"):
                    owners = {definition["definition_id"] for definition in definitions
                              if set(_string_references(record, "variable_references"))
                              & set(_string_references(definition, "variable_references"))}
                if identifier in definition_ids:
                    owners = {identifier}
                expressions = {field: value for field, value in record.items()
                               if field in {"formal_expression", "predicate_expression", "domain_expression",
                                            "conclusion_expression", "condition_expressions", "derived_expression",
                                            "quantifiers", "backend_encodings"}}
                bindings = bound_symbols(record) | set(step_bindings.get(identifier, ()))
                uses_symbol = symbol in ((set(_string_references(record, "symbol_references"))
                                          | free_expression_symbols(expressions, bindings)) - bindings)
                if len(owners) == 1:
                    owner = next(iter(owners))
                    if owner in renames:
                        _rewrite_record_symbols(record, {symbol: renames[owner]},
                                                bound_symbols=step_bindings.get(identifier, ()))
                elif uses_symbol:
                    ambiguous.add(identifier)
                    previous_status = record.get("status")
                    _block_record(result, record, identifier, "symbol",
                                  f"Symbol {symbol!r} has distinct definitions {sorted(definition_ids)}; "
                                  "its ownership in this record needs resolution.",
                                  logger=logger, brief_id=brief_id)
                    if "step_id" in record and previous_status in {"proposed", "unverified"}:
                        record["status"] = previous_status
            for definition in definitions[1:]:
                definition["symbol"] = renames[definition["definition_id"]]
    if changes:
        result.setdefault("reconciliation_audit", []).append({
            "source": "duplicate_definition_normalization", "id_redirects": redirects,
            "symbol_renames": renames, "changes": changes, "ambiguous_record_ids": sorted(ambiguous),
        })
        if logger is not None:
            logger.event("formal_definition_resolver", "definition_duplicates_normalized", status="COMPLETED",
                         brief_id=brief_id, merged_definition_count=len(redirects),
                         renamed_definition_count=len(renames), ambiguous_record_ids=sorted(ambiguous),
                         id_redirects=redirects)
    from .formal_object_registry import build_registry, rewrite_live_references
    result = rewrite_live_references(result, redirects)
    if result.get("object_registry") or redirects:
        result.setdefault("object_registry", {}).setdefault("aliases", {}).update(redirects)
        result["object_registry"] = build_registry(result)
    return result


def repair_plan_symbol_conflicts(plan, variable_claim_model, *, llm_call, logger=None, brief_id=""):
    from .formal_definition_resolver import RECONCILIATION_REVIEW_PROMPT, _reconciliation_catalog
    from .llm_json import call_required_json_with_logging, json_prompt_payload
    from .formal_plan_recovery import construction_warning

    plan = normalize_duplicate_definitions(plan, disambiguate=False, logger=logger, brief_id=brief_id)
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
    if logger is not None:
        logger.event("formal_definition_resolver", "plan_symbol_repair_input_profiled", status="PROFILED",
                     brief_id=brief_id, prompt_chars=len(prompt),
                     conflict_definition_ids=scope["conflict_definition_ids"],
                     direct_consumer_ids=scope["direct_consumer_ids"])
    try:
        patch = call_required_json_with_logging(
            llm_call, prompt, stage="formal_definition_resolver", request_kind="repair_plan_symbol_conflicts",
            logger=logger, brief_id=brief_id,
        )
        repaired = apply_definition_reconciliation(candidates, patch, logger=logger, brief_id=brief_id)
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
