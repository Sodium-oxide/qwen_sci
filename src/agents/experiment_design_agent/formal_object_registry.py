"""Canonical mathematical identities shared by definition and proof groups."""

from collections.abc import Mapping
from copy import deepcopy
import re

from .formal_dependency import (
    COLLECTION_IDS, bound_symbols, declared_dependencies, free_expression_symbols, partition_relation_premises,
)


REGISTRY_VERSION = "formal_object_registry_v1"
REFERENCE_FIELDS = frozenset({
    "depends_on", "premises", "assumption_ids", "global_assumption_ids",
    "required_obligation_ids", "target_id", "target_proposition_id", "ref",
    "record_id", "object_id", "canonical_id", "definition_id", "relation_id",
    "assumption_id", "proposition_id", "lemma_id", "obligation_id", "definition_ref",
    "lemma_ref", "assumption_ref", "premise_ref",
    "reused_object_ids", "alias_id", "retained_id", "merged_ids",
})
HISTORY_FIELDS = frozenset({
    "source_refs", "audit_refs", "unknown_items", "semantic_diagnostics",
    "object_registry", "object_registry_audit", "object_registry_diagnostics",
    "object_registry_raw_diagnostics",
    "premise_normalization",
    "original_record", "format_originals", "raw_json", "raw_excerpt",
})
MATHEMATICAL_FIELDS = (
    "statement", "object_kind", "expression_latex", "formal_expression", "domain",
    "codomain", "unit", "conditions", "condition_expressions", "scope",
    "depends_on", "premises", "predicate", "predicate_expression", "conclusion",
    "conclusion_expression", "domain_expression", "quantifiers", "assumption_kind",
    "is_global", "target", "target_id", "object_bindings",
)
OBJECT_PROMPT = """Use mathematical_object_context as the shared mathematical registry.
Reuse canonical IDs; owner_group identifies who primarily completes an object.
Return proposed updates for objects owned elsewhere. New mathematics, assumptions
and supporting lemmas remain welcome. Return normal collections or object_delta:
reused_object_ids, updated_objects/new_objects [{collection, record}],
proposed_aliases [{alias_id, canonical_id, reason}], dependency_updates
[{record_id, depends_on, premises, assumption_ids}].
Objects omitted from full_records still exist. Missing references and unresolved
cycles remain research drafts. Do not use unresolved circular definitions as
established premises. Keep units, conditions and scope when reusing an object.
Quantified and step-local symbols are not global aliases. Use object_bindings
{symbol: canonical_id} for global symbols where their identity is known.
Distinguish a mathematical object from a statement about that object. A definition
declares a quantity, constant, function, set or other mathematical object. Positivity,
finiteness, inequality, regularity and applicability statements about an existing
object are properties or conditions, not new definitions of that object.
For an existing primitive constant, reuse its canonical definition ID. Represent
its value domain and intrinsic conditions in domain, codomain, conditions and
condition_expressions. A primitive constant does not require a defining formula
merely to be usable in mathematical reasoning; encode needed conditions explicitly.
If a property needs its own referenceable record, use an assumption for an explicitly
assumed property, a model_relation for a modeling constraint, or a lemma/proposition
for a property to be derived. The property may depend on the object; the object must
not depend on the property merely because the property describes it.
Do not create a second primitive definition solely to express a property. Do not
alias a property record to the object it describes. Alias IDs only when both records
denote the same mathematical object. When completing a definition, preserve its
identity and defining meaning; add compatible conditions without replacing the
object with a Boolean predicate. Do not introduce dependencies that resolve after
alias normalization to the definition's own canonical ID.
Example: G14_c_light declares the speed-of-light constant c. The condition c > 0
belongs in its conditions or in a separate assumption/lemma referencing G14_c_light.
Do not create a primitive TP2_c_light_pos for c > 0 and alias it to G14_c_light.
Evidence is optional reference material, not a restriction on mathematical reasoning.
"""
PAIR_REVIEW_PROMPT = """Compare only these mathematical objects and direct consumers.
Return JSON {decision: merge|distinct|revise, reason: nonempty text, patch: optional
{repairs: [{record_id, fields}], merges: [{retained_id, merged_ids}],
symbol_renames: [{definition_id, symbol, affected_ids}]}}.
Merge only equal meanings with compatible scope, units and conditions. A shared
symbol or variable alone does not establish equality. Before deciding, identify
whether each record declares an object or states a property about an object.
Choose merge only when both records denote the same mathematical object or express
the same mathematical statement with compatible meaning and scope. A constant and
a predicate about that constant are not interchangeable. A shared subject or
physical quantity does not justify merging them.
For an object and a property about it, choose distinct when the property is a separate
assumption, relation, lemma or proposition. Choose revise when the property can be
added to the existing object's conditions through supported patch fields, preserving
its identity and defining meaning. Do not choose merge merely because both refer to
the same object. If the property is wrongly stored as a definition, explain the
needed record-type correction; do not alias it to the object to conceal that mismatch.
Before proposing an alias or merge, inspect dependencies under the proposed ID
redirection. Do not merge a dependent property into its prerequisite object if
this would create a self-dependency. Patch only supplied objects
and consumers. Preserve drafts; never claim verification. INPUT_JSON:
"""
CYCLE_REVIEW_PROMPT = """Review this circular mathematical construction and its direct
consumers. Return JSON {repairs: [{record_id, fields}], new_objects:
[{collection, record}], reason: text}. You may introduce primitive objects,
distinguish constraints from definitions, or retain an implicit definition draft.
Preserve genuine unresolved cycles; do not turn them into established proof
premises. Repair only the supplied records, with no claimed verification.
INPUT_JSON:
"""


def _records(payload):
    for collection, field in COLLECTION_IDS.items():
        values = payload.get(collection, [])
        if isinstance(values, list):
            for record in values:
                if isinstance(record, Mapping) and isinstance(record.get(field), str):
                    yield collection, field, record


def _references(record, field):
    values = record.get(field, [])
    return [value for value in values if isinstance(value, str)] if isinstance(values, list) else []


def _history(field):
    return field in HISTORY_FIELDS or field.endswith(("_audit", "_archive"))


def _text_rename(value, renames):
    if not isinstance(value, str) or not renames:
        return value
    pattern = "|".join(re.escape(symbol) for symbol in sorted(renames, key=len, reverse=True))
    return re.sub(r"(?<![\w])(?:" + pattern + r")(?![\w])",
                  lambda match: renames[match.group()], value)


def rewrite_record_symbols(record, renames, *, bound_symbols_override=(), bound_symbols=()):
    from .formal_dependency import bound_symbols as bindings
    blocked = set(bound_symbols_override) | set(bound_symbols) | bindings(record)
    safe = {old: new for old, new in renames.items()
            if isinstance(old, str) and old and isinstance(new, str) and old != new}

    def rewrite(value, field="", bound=frozenset()):
        if isinstance(value, Mapping):
            local = set(bound) | bindings(value)
            if value.get("op") in {"forall", "exists", "lambda"}:
                local.update(_references(value, "symbols"))
                if isinstance(value.get("symbol"), str):
                    local.add(value["symbol"])
            return {key: deepcopy(item) if _history(key) else rewrite(item, key, local)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item, field, bound) for item in value]
        if isinstance(value, str):
            active = {old: new for old, new in safe.items() if old not in bound and new not in bound}
            if field in {"symbol", "symbol_references"}:
                return active.get(value, value)
            if field in {"statement", "expression_latex", "predicate", "conclusion", "conditions",
                         "derived_statement", "final_conclusion"}:
                return _text_rename(value, active)
        return value

    for field in tuple(record):
        if not _history(field) and field not in {"quantifiers", "local_bindings"}:
            record[field] = rewrite(record[field], field, blocked)
    bindings_map = record.get("object_bindings")
    if isinstance(bindings_map, dict):
        record["object_bindings"] = {
            safe.get(symbol, symbol) if symbol not in blocked and safe.get(symbol) not in blocked else symbol: identifier
            for symbol, identifier in bindings_map.items()
        }
    return record


def resolve_reference(registry, identifier, *, group_id=""):
    if not isinstance(identifier, str):
        return identifier
    aliases = registry.get("aliases", {})
    identifier = registry.get("group_aliases", {}).get(group_id, {}).get(identifier, identifier)
    visited = set()
    while identifier in aliases and identifier not in visited:
        visited.add(identifier)
        identifier = aliases[identifier]
    return identifier


def rewrite_live_references(payload, redirects, *, symbol_renames=None):
    def rewrite(value, field=""):
        if isinstance(value, Mapping):
            if field == "object_bindings":
                return {key: rewrite(item, "object_id") for key, item in value.items()}
            return {key: deepcopy(item) if _history(key) else rewrite(item, key)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item, field) for item in value]
        if isinstance(value, str) and field in REFERENCE_FIELDS:
            visited = set()
            while value in redirects and value not in visited:
                visited.add(value)
                value = redirects[value]
        return value

    result = rewrite(payload)
    targets = {}
    for collection, field, record in _records(result):
        if collection in {"propositions", "lemmas"}:
            targets[record[field]] = bound_symbols(record)
        rewrite_record_symbols(record, (symbol_renames or {}).get(record[field], {}))
    def proof_steps(envelope, parent=""):
        if not isinstance(envelope, dict):
            return
        parent = envelope.get("target_id", envelope.get("target_proposition_id", parent))
        if not isinstance(parent, str):
            parent = ""
        local = (set(targets.get(parent, ())) if isinstance(parent, str) else set()) | bound_symbols(envelope)
        steps = envelope.get("steps", envelope.get("derivation_steps", []))
        for step in steps if isinstance(steps, list) else []:
            if isinstance(step, dict):
                rewrite_record_symbols(step, (symbol_renames or {}).get(step.get("step_id"), {})
                                       or (symbol_renames or {}).get(parent, {}), bound_symbols=local)
                local.update(bound_symbols(step))
        for attempt in envelope.get("proof_attempts", []):
            proof_steps(attempt, parent)
        for nested in envelope.get("target_results", []):
            proof_steps(nested, parent)
    proof_steps(result)
    proof_steps(result.get("forward_derivation", {}))
    return result


def rewrite_object_symbols(payload, object_renames):
    result = deepcopy(payload)
    maps = {identifier: dict(renames) for identifier, renames in object_renames.items()}
    records = list(_records(result))
    for _round in range(len(records) + 1):
        changed = False
        for _, field, record in records:
            mapping = maps.setdefault(record[field], {})
            before = dict(mapping)
            for dependency in declared_dependencies(record):
                for old, new in maps.get(dependency, {}).items():
                    mapping[old] = new if old not in mapping or mapping[old] == new else old
            changed |= mapping != before
        if not changed:
            break
    targets = {record[field]: bound_symbols(record) for collection, field, record in records
               if collection in {"propositions", "lemmas"}}
    for _, field, record in records:
        rewrite_record_symbols(record, maps.get(record[field], {}))
    def steps(envelope, parent=""):
        if not isinstance(envelope, dict):
            return
        parent = envelope.get("target_id", envelope.get("target_proposition_id", parent))
        local = set(targets.get(parent, ())) if isinstance(parent, str) else set()
        local.update(bound_symbols(envelope))
        values = envelope.get("steps", envelope.get("derivation_steps", []))
        for step in values if isinstance(values, list) else []:
            if not isinstance(step, dict):
                continue
            mapping = {}
            for dependency in declared_dependencies(step):
                for old, new in maps.get(dependency, {}).items():
                    mapping[old] = new if old not in mapping or mapping[old] == new else old
            rewrite_record_symbols(step, mapping, bound_symbols=local)
            local.update(bound_symbols(step))
        for key in ("proof_attempts", "target_results"):
            values = envelope.get(key, [])
            for nested in values if isinstance(values, list) else []:
                steps(nested, parent)
    steps(result)
    steps(result.get("forward_derivation", {}))
    return result


def _semantic_record(record):
    result = {field: deepcopy(record[field]) for field in MATHEMATICAL_FIELDS if record.get(field) is not None}
    for field in ("conditions", "condition_expressions", "depends_on", "premises", "quantifiers"):
        result.setdefault(field, [])
    symbol = record.get("symbol")
    if isinstance(symbol, str) and symbol:
        rewrite_record_symbols(result, {symbol: "__defined_object__"})
        if "statement" in record:
            result["statement"] = record["statement"]
    return result


def _equivalent(first, second):
    if _incomplete(first) != _incomplete(second):
        return False
    first_variables = set(_references(first, "variable_references"))
    second_variables = set(_references(second, "variable_references"))
    return (bool(first.get("statement")) and _semantic_record(first) == _semantic_record(second)
            and (not first_variables or not second_variables or first_variables == second_variables))


def build_registry(payload, *, variables=(), assigned=None, owners=None):
    previous = payload.get("object_registry", {})
    registry = {"schema_version": REGISTRY_VERSION, "objects": {},
                "global_assumption_ids": _references(payload, "global_assumption_ids"),
                "aliases": deepcopy(previous.get("aliases", {})),
                "group_aliases": deepcopy(previous.get("group_aliases", {}))}
    for identifier, entry in previous.get("objects", {}).items():
        if entry.get("reserved"):
            registry["objects"][identifier] = deepcopy(entry)
    for collection, field, record in _records(payload):
        identifier = record[field]
        old = previous.get("objects", {}).get(identifier, {})
        content = {key: deepcopy(value) for key, value in record.items() if not _history(key) or key == "source_refs"}
        revision = old.get("revision", 0) + (content != old.get("record"))
        registry["objects"][identifier] = {
            "canonical_id": identifier, "collection": collection, "record": content,
            "object_kind": collection, "symbol": record.get("symbol"),
            "variable_ids": _references(record, "variable_references"),
            "owner_group": record.get("owner_group", old.get("owner_group", "")),
            "revision": max(1, revision), "reserved": False,
            "symbol_aliases": list(dict.fromkeys([*old.get("symbol_aliases", []),
                *([old["symbol"]] if old.get("symbol") and old["symbol"] != record.get("symbol") else [])])),
            "id_aliases": list(old.get("id_aliases", [])),
        }
    for variable in variables:
        identifier = (assigned or {}).get(variable.get("variable_id"))
        if not identifier or identifier in registry["objects"]:
            continue
        registry["objects"][identifier] = {
            "canonical_id": identifier, "collection": "definitions", "object_kind": "definitions",
            "symbol": variable.get("symbol"), "variable_ids": [variable["variable_id"]],
            "owner_group": (owners or {}).get(variable["variable_id"], ""),
            "revision": 0, "reserved": True, "symbol_aliases": [], "id_aliases": [],
            "record": {"definition_id": identifier, "symbol": variable.get("symbol"),
                       "statement": variable.get("description", variable.get("name", "")),
                       "unit": variable.get("unit"), "scope": variable.get("scope"),
                       "variable_references": [variable["variable_id"]], "definition_status": "unresolved"},
        }
    for aliases in [registry["aliases"], *registry["group_aliases"].values()]:
        for alias, target in aliases.items():
            entry = registry["objects"].get(resolve_reference(registry, target))
            if entry and alias not in entry["id_aliases"]:
                entry["id_aliases"].append(alias)
    return registry


def project_group_context(registry, root_ids, *, group_id="", catalog_ids=None):
    required = {resolve_reference(registry, identifier, group_id=group_id)
                for identifier in root_ids if isinstance(identifier, str)}
    pending = sorted(required)
    while pending:
        identifier = pending.pop()
        entry = registry["objects"].get(identifier)
        if entry is None:
            continue
        dependencies = {resolve_reference(registry, reference, group_id=group_id)
                        for reference in declared_dependencies(entry["record"])}
        if entry["collection"] in {"propositions", "lemmas", "proof_obligations"}:
            dependencies.update(registry.get("global_assumption_ids", []))
            dependencies.update(identifier for identifier, candidate in registry["objects"].items()
                                if candidate["collection"] == "assumptions" and candidate["record"].get("is_global") is True)
        pending.extend(sorted(dependencies - required))
        required.update(dependencies)
    catalog = []
    for identifier, entry in sorted(registry["objects"].items()):
        if catalog_ids is not None and identifier not in required and identifier not in catalog_ids:
            continue
        record = entry["record"]
        catalog.append({"canonical_id": identifier, "object_kind": entry["collection"],
                        "symbol": entry.get("symbol"), "statement": str(record.get("statement") or "")[:200],
                        "unit": record.get("unit"), "scope": str(record.get("scope", record.get("domain")) or "")[:200],
                        "conditions": [str(condition)[:160] for condition in record.get("conditions", [])[:4]]
                                      if isinstance(record.get("conditions"), list) else [],
                        "owner_group": entry.get("owner_group", ""),
                        "status": record.get("definition_status", record.get("status", "unresolved")),
                        "reserved": entry.get("reserved", False)})
    return {"schema_version": REGISTRY_VERSION, "group_id": group_id, "catalog": catalog,
            "full_records": [deepcopy(registry["objects"][identifier]["record"])
                             for identifier in sorted(required) if identifier in registry["objects"]],
            "read_versions": {identifier: registry["objects"][identifier]["revision"]
                              for identifier in sorted(required) if identifier in registry["objects"]},
            "missing_references": sorted(required - set(registry["objects"])),
            "aliases": {alias: target for alias, target in registry.get("aliases", {}).items() if target in required}}


def registry_cache_context(context):
    return {key: deepcopy(context.get(key)) for key in
            ("schema_version", "group_id", "full_records", "read_versions", "missing_references", "aliases")}


def adapt_group_delta(response):
    delta = deepcopy(dict(response))
    if delta.get("object_delta_expanded") is True:
        return delta
    envelope = delta.pop("object_delta", {})
    if isinstance(envelope, Mapping):
        for key, value in envelope.items():
            if key in COLLECTION_IDS:
                delta.setdefault(key, [])
                if isinstance(delta[key], list) and isinstance(value, list):
                    delta[key].extend(deepcopy(value))
            else:
                delta[key] = deepcopy(value)
    if not isinstance(delta.get("unknown_items", []), list):
        delta["unknown_items"] = [{"field_path": "unknown_items", "reason": "unknown_items_not_array",
                                  "status": "needs_human_input", "original_record": deepcopy(delta["unknown_items"])}]
    for collection, field in COLLECTION_IDS.items():
        values = delta.get(collection)
        if isinstance(values, Mapping):
            delta[collection] = [dict(values)] if field in values else list(values.values())
            delta.setdefault("unknown_items", []).append({"field_path": collection,
                "reason": f"{collection}_not_array: converted record mapping to array.",
                "status": "needs_human_input", "original_record": deepcopy(values)})
        elif collection in delta and not isinstance(values, list):
            delta[collection] = []
            delta.setdefault("unknown_items", []).append({"field_path": collection,
                "reason": f"{collection}_not_array: object collection must be an array or record mapping.",
                "status": "needs_human_input", "original_record": deepcopy(values)})
    for action in ("new_objects", "updated_objects"):
        for index, operation in enumerate(delta.get(action, []) if isinstance(delta.get(action), list) else []):
            collection = operation.get("collection") if isinstance(operation, Mapping) else None
            record = operation.get("record") if isinstance(operation, Mapping) else None
            if (isinstance(collection, str) and collection in COLLECTION_IDS and isinstance(record, Mapping)
                    and isinstance(record.get(COLLECTION_IDS[collection]), str)):
                if not isinstance(delta.get(collection, []), list):
                    delta[collection] = []
                delta.setdefault(collection, []).append(deepcopy(dict(record)))
            else:
                delta.setdefault("unknown_items", []).append({"field_path": f"{action}[{index}]",
                    "reason": "Malformed object operation; other operations are retained.", "status": "needs_human_input",
                    "original_record": deepcopy(operation)})
    delta["object_delta_expanded"] = True
    return delta


def _unique_id(identifier, group_id, used):
    prefix = f"{group_id}_" if group_id else ""
    candidate = identifier if not prefix or identifier.startswith(prefix) else prefix + identifier
    number, base = 2, candidate
    while candidate in used:
        candidate = f"{base}_{number}"
        number += 1
    return candidate


def _incomplete(record):
    return (record.get("definition_status") == "unresolved"
            or bool(record.get("machine_encoding_issues"))
            or record.get("verification_readiness") in {"blocked", "requires_encoding"}
            or record.get("status") in {"unresolved", "needs_human_input"})


def _consumers(payload, identifiers):
    return [record for _, _, record in _records(payload)
            if declared_dependencies(record) & set(identifiers)][:8]


def _related(first, second):
    return (first.get("symbol") and first.get("symbol") == second.get("symbol")
            or first.get("statement") and first.get("statement") == second.get("statement")
            or set(_references(first, "variable_references")) & set(_references(second, "variable_references")))


def _pair_review(existing, incoming, payload, *, llm_call, logger, brief_id, checkpoint=None, cache_identity=None):
    if llm_call is None:
        return None
    from .llm_json import call_required_json_with_logging, json_prompt_payload
    from .cache import ExperimentDesignCache
    consumers = _consumers(payload, [existing.get("definition_id"), existing.get("relation_id")])
    fields = {*MATHEMATICAL_FIELDS, *COLLECTION_IDS.values(), "symbol", "variable_references",
              "definition_status", "verification_readiness", "status", "machine_encoding_issues"}
    def project(record):
        return {field: deepcopy(value) for field, value in record.items() if field in fields}
    pair = {"objects": [project(existing), project(incoming)], "consumers": [project(record) for record in consumers]}
    prompt = PAIR_REVIEW_PROMPT + json_prompt_payload(pair)
    cache = ExperimentDesignCache(checkpoint or {"enabled": False})
    identity = {"version": 1, "prompt": prompt, "llm": cache_identity or {}}
    decision = cache.read("object_pair_reviews", identity)
    if decision is None:
        if cache.offline:
            raise ValueError("object_pair_review_checkpoint_miss")
        decision = call_required_json_with_logging(
            llm_call, prompt, stage="formal_object_registry", request_kind="review_object_pair",
            logger=logger, brief_id=brief_id, request_options={"max_retries": 0},
        )
        try:
            cache.write("object_pair_reviews", identity, decision)
        except (OSError, TypeError, ValueError):
            if logger is not None:
                logger.event("formal_object_registry", "checkpoint_warning", level="WARNING", status="WARNING", brief_id=brief_id)
    return decision


def commit_group_delta(payload, response, *, group_id="", registry=None, logger=None,
                       brief_id="", llm_call=None, collections=None, namespace_new_ids=True,
                       checkpoint=None, cache_identity=None):
    result = deepcopy(payload)
    result.setdefault("unknown_items", [])
    registry = deepcopy(registry or build_registry(result))
    delta = adapt_group_delta(response)
    selected = set(collections or COLLECTION_IDS)
    raw_snapshots = delta.get("object_registry_raw_diagnostics", [])
    raw_snapshots = [deepcopy(item) for item in raw_snapshots if isinstance(item, Mapping)] if isinstance(raw_snapshots, list) else []
    if not raw_snapshots:
        raw_snapshots = [inspect_dependency_graph(delta, known_ids=set(registry["objects"]))]
    raw = raw_snapshots[-1]
    local_map = dict(registry.get("aliases", {}))
    local_map.update(registry.get("group_aliases", {}).get(group_id, {}))
    local_aliases = delta.get("local_object_aliases", {})
    if isinstance(local_aliases, Mapping):
        local_map.update({alias: identifier for alias, identifier in local_aliases.items()
                          if isinstance(alias, str) and isinstance(identifier, str)})
    used = set(registry["objects"])
    changes, writes, symbol_redirects = [], [], {}
    global_redirects = {}
    global_symbol_updates = {}
    updates = delta.get("updated_objects", [])
    explicit_updates = {(operation["collection"], operation["record"].get(COLLECTION_IDS[operation["collection"]]))
                        for operation in updates if isinstance(operation, Mapping)
                        and isinstance(operation.get("collection"), str) and operation["collection"] in COLLECTION_IDS
                        and isinstance(operation.get("record"), Mapping)
                        and isinstance(operation["record"].get(COLLECTION_IDS[operation["collection"]]), str)} if isinstance(updates, list) else set()
    for collection, field, incoming in list(_records(delta)):
        if collection not in selected:
            continue
        record = rewrite_live_references({collection: [incoming]}, local_map)[collection][0]
        local_id = incoming[field]
        identifier = record.get("canonical_id") or resolve_reference(registry, local_id, group_id=group_id)
        existing = next((candidate for candidate in result.get(collection, [])
                         if isinstance(candidate, Mapping) and candidate.get(field) == identifier), None)
        record[field] = identifier
        if existing is None and collection in {"definitions", "model_relations"}:
            existing = next((candidate for candidate in result.get(collection, [])
                             if isinstance(candidate, Mapping) and _equivalent(candidate, record)), None)
        if (existing is None and collection in {"definitions", "model_relations"}
                and not registry["objects"].get(identifier, {}).get("reserved")):
            related = [candidate for candidate in result.get(collection, [])
                       if isinstance(candidate, Mapping) and _related(candidate, record)]
            if len(related) == 1:
                existing = related[0]
        replace = False
        if existing is not None and (not _equivalent(existing, record)
                                     or _incomplete(existing) and not _incomplete(record)
                                     or (collection, local_id) in explicit_updates):
            owner = registry["objects"].get(existing[field], {}).get("owner_group", "")
            replace = (identifier == existing[field]
                       and (_incomplete(existing) or (collection, local_id) in explicit_updates)
                       and (not owner or not group_id or owner == group_id or _incomplete(existing) and group_id.startswith("TP")))
            if not replace:
                temporary = deepcopy(record)
                temporary[field] = _unique_id(local_id, group_id or "candidate", used)
                try:
                    decision = (_pair_review(existing, temporary, result, llm_call=llm_call,
                                             logger=logger, brief_id=brief_id,
                                             checkpoint=checkpoint, cache_identity=cache_identity)
                                if not owner or owner != group_id else None)
                    if isinstance(decision, Mapping) and decision.get("reason") and decision.get("decision") == "revise":
                        from .formal_reconciliation import apply_definition_reconciliation
                        review_payload = deepcopy(result)
                        review_payload.setdefault(collection, []).append(temporary)
                        allowed = {existing[field], temporary[field]} | {
                            item.get(COLLECTION_IDS[name]) for name, _, item in _records(result)
                            if name in selected and item in _consumers(result, [existing[field]])
                        }
                        patch = decision.get("patch", {})
                        scoped = {
                            "repairs": [item for item in patch.get("repairs", [])
                                        if isinstance(item, Mapping) and item.get("record_id") in allowed],
                            "merges": [item for item in patch.get("merges", [])
                                       if isinstance(item, Mapping) and item.get("retained_id") in allowed
                                       and isinstance(item.get("merged_ids"), list) and set(item["merged_ids"]) <= allowed],
                            "symbol_renames": [item for item in patch.get("symbol_renames", [])
                                              if isinstance(item, Mapping) and item.get("definition_id") in allowed
                                              and isinstance(item.get("affected_ids"), list) and set(item["affected_ids"]) <= allowed],
                        } if isinstance(patch, Mapping) else {}
                        revised = apply_definition_reconciliation(review_payload, scoped, logger=logger, brief_id=brief_id)
                        revised_records = {item[COLLECTION_IDS[name]]: item for name, _, item in _records(revised)}
                        if temporary[field] not in revised_records and existing[field] in revised_records:
                            result = revised
                            existing = revised_records[existing[field]]
                            decision = {"decision": "merge", "reason": decision["reason"]}
                        elif temporary[field] in revised_records:
                            candidate_id = temporary[field]
                            record = deepcopy(revised_records[candidate_id])
                            result = revised
                            result[collection] = [item for item in result[collection] if item[field] != candidate_id]
                            record[field] = identifier
                            existing = revised_records.get(existing[field])
                            decision = {"decision": "merge" if existing and _equivalent(existing, record) else "distinct",
                                        "reason": decision["reason"]}
                    if not (isinstance(decision, Mapping) and decision.get("decision") == "merge" and decision.get("reason")):
                        existing = None
                    else:
                        changes.append({"action": "semantic_merge", "record_id": existing[field], "reason": decision["reason"]})
                except Exception as error:
                    changes.append({"action": "pair_review_failed", "record_id": identifier,
                                    "reason": f"{type(error).__name__}: {error}"})
                    existing = None
        if existing is None:
            if collection in {"definitions", "model_relations"}:
                existing = next((candidate for candidate in result.get(collection, [])
                                 if isinstance(candidate, Mapping) and _equivalent(candidate, record)), None)
        if existing is None:
            reserved = registry["objects"].get(identifier, {})
            if identifier in used and not reserved.get("reserved"):
                identifier = _unique_id(local_id, group_id or "candidate", used)
            elif identifier not in used and group_id and namespace_new_ids:
                identifier = _unique_id(local_id, group_id, used)
            record[field] = identifier
            registry["objects"].setdefault(identifier, {})["owner_group"] = reserved.get("owner_group") or group_id
            result.setdefault(collection, []).append(record)
            existing = record
            writes.append((collection, field, existing))
            used.add(identifier)
            changes.append({"action": "add", "record_id": identifier, "local_id": local_id})
        elif replace:
            before = deepcopy(existing)
            record[field] = existing[field]
            existing.update(record)
            for reference_field in ("source_refs", "variable_references", "audit_refs"):
                values = before.get(reference_field, [])
                for value in values if isinstance(values, list) else []:
                    if isinstance(existing.get(reference_field, []), list) and value not in existing.setdefault(reference_field, []):
                        existing[reference_field].append(deepcopy(value))
            if isinstance(before.get("symbol"), str) and isinstance(existing.get("symbol"), str) and before["symbol"] != existing["symbol"]:
                global_symbol_updates[existing[field]] = {before["symbol"]: existing["symbol"]}
            writes.append((collection, field, existing))
            changes.append({"action": "complete", "record_id": existing[field], "before": before})
        canonical = existing[field]
        if local_id != canonical:
            local_map[local_id] = canonical
            registry.setdefault("group_aliases", {}).setdefault(group_id, {})[local_id] = canonical
            if local_id not in registry["objects"]:
                prior = registry.setdefault("aliases", {}).get(local_id)
                if prior is None or prior == canonical:
                    registry["aliases"][local_id] = canonical
                    global_redirects[local_id] = canonical
                else:
                    registry["aliases"].pop(local_id, None)
            changes.append({"action": "alias", "local_id": local_id, "record_id": canonical})
        old_symbol, symbol = incoming.get("symbol"), existing.get("symbol")
        if isinstance(old_symbol, str) and isinstance(symbol, str) and old_symbol != symbol:
            symbol_redirects[local_id] = (old_symbol, symbol)
        for source_field in ("source_refs", "variable_references", "audit_refs"):
            values = record.get(source_field, [])
            for value in values if isinstance(values, list) else []:
                if isinstance(existing.get(source_field, []), list) and value not in existing.setdefault(source_field, []):
                    existing[source_field].append(deepcopy(value))
    for index, proposal in enumerate(delta.get("proposed_aliases", []) if isinstance(delta.get("proposed_aliases"), list) else []):
        if not isinstance(proposal, Mapping):
            continue
        alias = proposal.get("alias_id")
        proposed = proposal.get("canonical_id")
        if not isinstance(alias, str) or not isinstance(proposed, str):
            result["unknown_items"].append({"field_path": f"proposed_aliases[{index}]",
                "reason": "Alias IDs must be strings; other alias proposals are retained.",
                "status": "needs_human_input", "original_record": deepcopy(proposal)})
            continue
        canonical = local_map.get(proposed, proposed)
        if isinstance(alias, str) and isinstance(canonical, str) and alias != canonical and alias in used:
            objects = {record[field]: (collection, field, record) for collection, field, record in _records(result)}
            alternative, retained = objects.get(alias), objects.get(canonical)
            if alternative and alternative[0] not in selected:
                continue
            if alternative and retained and alternative[0] == retained[0]:
                merge = bool(proposal.get("reason")) and _equivalent(alternative[2], retained[2])
                if not merge:
                    try:
                        decision = _pair_review(retained[2], alternative[2], result, llm_call=llm_call,
                                                logger=logger, brief_id=brief_id,
                                                checkpoint=checkpoint, cache_identity=cache_identity)
                        merge = isinstance(decision, Mapping) and decision.get("decision") == "merge" and bool(decision.get("reason"))
                    except Exception as error:
                        changes.append({"action": "alias_review_failed", "record_id": alias,
                                        "reason": f"{type(error).__name__}: {error}"})
                if merge:
                    original = deepcopy(alternative[2])
                    for field in ("source_refs", "variable_references", "audit_refs"):
                        values = alternative[2].get(field, [])
                        for value in values if isinstance(values, list) else []:
                            if isinstance(retained[2].get(field, []), list) and value not in retained[2].setdefault(field, []):
                                retained[2][field].append(deepcopy(value))
                    old_symbol, new_symbol = alternative[2].get("symbol"), retained[2].get("symbol")
                    if isinstance(old_symbol, str) and isinstance(new_symbol, str) and old_symbol != new_symbol:
                        result = rewrite_object_symbols(result, {alias: {old_symbol: new_symbol}})
                    result[alternative[0]] = [record for record in result[alternative[0]] if record[alternative[1]] != alias]
                    used.discard(alias)
                    registry["objects"].pop(alias, None)
                    changes.append({"action": "merge_proposed_alias", "record_id": alias,
                                    "retained_id": canonical, "reason": proposal.get("reason", ""), "before": original})
        if isinstance(alias, str) and isinstance(canonical, str) and canonical in used and alias not in used:
            local_map[alias] = canonical
            registry.setdefault("group_aliases", {}).setdefault(group_id, {})[alias] = canonical
            if not any(alias in mapping and mapping[alias] != canonical for mapping in registry["group_aliases"].values()):
                registry.setdefault("aliases", {})[alias] = canonical
                global_redirects[alias] = canonical
    for collection in selected:
        values = delta.get(collection, [])
        if isinstance(values, list):
            for record in values:
                if not isinstance(record, Mapping) or not isinstance(record.get(COLLECTION_IDS[collection]), str):
                    result.setdefault(collection, []).append(deepcopy(record))
    object_symbols = {identifier: {old: new} for identifier, (old, new) in symbol_redirects.items()}
    delta_records = list(_records(delta))
    for _round in range(len(delta_records) + 1):
        changed = False
        for _, field, record in delta_records:
            mapping = object_symbols.setdefault(record[field], {})
            before = dict(mapping)
            for dependency in declared_dependencies(record):
                for old, new in object_symbols.get(dependency, {}).items():
                    mapping[old] = new if old not in mapping or mapping[old] == new else old
            changed |= before != mapping
        if not changed:
            break
    renames = {}
    for _, field, record in _records(delta):
        renames[local_map.get(record[field], record[field])] = object_symbols.get(record[field], {})
    targets = {record[field]: bound_symbols(record) for collection, field, record in _records(result)
               if collection in {"propositions", "lemmas"}}
    def prepare_steps(envelope, parent=""):
        if not isinstance(envelope, dict):
            return
        parent = envelope.get("target_id", envelope.get("target_proposition_id", parent))
        local = set(targets.get(parent, ())) if isinstance(parent, str) else set()
        local.update(bound_symbols(envelope))
        steps = envelope.get("steps", envelope.get("derivation_steps", []))
        for step in steps if isinstance(steps, list) else []:
            if not isinstance(step, dict):
                continue
            mapping = {}
            for dependency in declared_dependencies(step):
                for old, new in object_symbols.get(dependency, {}).items():
                    mapping[old] = new if old not in mapping or mapping[old] == new else old
            rewrite_record_symbols(step, mapping, bound_symbols=local)
            local.update(bound_symbols(step))
        for attempt in envelope.get("proof_attempts", []):
            prepare_steps(attempt, parent)
        for nested in envelope.get("target_results", []):
            prepare_steps(nested, parent)
    prepare_steps(delta)
    prepare_steps(delta.get("forward_derivation", {}))
    rewritten = rewrite_live_references(delta, local_map, symbol_renames=renames)
    for collection, field, record in writes:
        actual = next((item for item in result.get(collection, []) if isinstance(item, dict) and item.get(field) == record[field]), None)
        if actual is not None:
            transformed = rewrite_live_references({collection: [actual]}, local_map, symbol_renames=renames)[collection][0]
            actual.clear()
            actual.update(transformed)
    result = rewrite_live_references(result, global_redirects)
    result = rewrite_object_symbols(result, global_symbol_updates)
    for operation in rewritten.get("dependency_updates", []) if isinstance(rewritten.get("dependency_updates"), list) else []:
        if not isinstance(operation, Mapping):
            continue
        for collection, field, record in _records(result):
            if collection in selected and record[field] == operation.get("record_id"):
                for reference_field in ("depends_on", "premises", "assumption_ids"):
                    if isinstance(operation.get(reference_field), list):
                        record[reference_field] = _references(operation, reference_field)
    for field in ("unknown_items", "semantic_diagnostics", "global_assumption_ids"):
        if isinstance(rewritten.get(field), list):
            for value in rewritten[field]:
                if value not in result.setdefault(field, []):
                    result[field].append(deepcopy(value))
    for alias in local_aliases if isinstance(local_aliases, Mapping) else []:
        canonical = resolve_reference({"aliases": local_map}, alias)
        if isinstance(alias, str) and canonical in used:
            registry.setdefault("group_aliases", {}).setdefault(group_id, {})[alias] = canonical
            if alias not in used:
                if any(mapping.get(alias, canonical) != canonical for mapping in registry["group_aliases"].values()):
                    registry.setdefault("aliases", {}).pop(alias, None)
                else:
                    registry.setdefault("aliases", {})[alias] = canonical
    result["object_registry"] = registry
    result["object_registry"] = build_registry(result)
    unified = inspect_dependency_graph(result)
    result["object_registry_diagnostics"] = unified
    result.setdefault("object_registry_audit", []).append({
        "group_id": group_id, "changes": changes, "id_redirects": local_map,
        "raw_diagnostics": raw, "raw_group_diagnostics": raw_snapshots, "unified_diagnostics": unified,
    })
    if logger is not None:
        for phase, diagnostics in [("raw_group_output", item) for item in raw_snapshots] + [("identity_unified", unified)]:
            logger.event("formal_object_registry", "graph_profiled", status="PROFILED", brief_id=brief_id,
                         group_id=group_id, phase=phase, **diagnostics)
    return result, rewritten, local_map


def inspect_dependency_graph(payload, *, known_ids=()):
    records, counts, target_by_step, inherited_bindings = {}, {}, {}, {}
    for _, field, record in _records(payload):
        records[record[field]] = record
        counts[record[field]] = counts.get(record[field], 0) + 1
    forward = payload.get("forward_derivation", {})
    envelopes = [("forward", forward)] if isinstance(forward, Mapping) else []
    for attempt in payload.get("proof_attempts", []) if isinstance(payload.get("proof_attempts"), list) else []:
        if isinstance(attempt, Mapping):
            envelopes.append((str(attempt.get("attempt_id", "attempt")), attempt))
    scoped_steps = {}
    for scope, envelope in envelopes:
        parent = envelope.get("target_id", envelope.get("target_proposition_id"))
        local_bindings = bound_symbols(records.get(parent, {})) | bound_symbols(envelope)
        steps = envelope.get("steps", [])
        if not isinstance(steps, list):
            steps = []
        local_ids = {step["step_id"]: f"{scope}::{step['step_id']}" for step in steps
                     if isinstance(step, Mapping) and isinstance(step.get("step_id"), str)}
        for step in steps:
            if isinstance(step, Mapping) and isinstance(step.get("step_id"), str):
                scoped = local_ids[step["step_id"]]
                records[scoped] = step
                scoped_steps[scoped] = local_ids
                target_by_step[scoped] = parent or step.get("target_id")
                inherited_bindings[scoped] = set(local_bindings)
                local_bindings.update(bound_symbols(step))
    aliases = payload.get("object_registry", {}).get("aliases", {})
    known = set(known_ids)
    missing_definitions, missing_premises, edges = [], [], {}
    textual_premise_count = 0
    uninterpreted_premise_count = 0
    for identifier, record in records.items():
        edges[identifier] = set()
        definitions = set(_references(record, "depends_on"))
        if "relation_id" in record:
            _, conditions, uninterpreted = partition_relation_premises(record.get("premises"), known_ids=set(records) | known)
            audit = record.get("premise_normalization", {})
            audit = audit if isinstance(audit, Mapping) else {}
            text_count, invalid_count = audit.get("text_condition_count", 0), audit.get("uninterpreted_count", 0)
            textual_premise_count += len(conditions) + (text_count if isinstance(text_count, int) and text_count >= 0 else 0)
            uninterpreted_premise_count += len(uninterpreted) + (invalid_count if isinstance(invalid_count, int) and invalid_count >= 0 else 0)
        references = declared_dependencies(record, known_ids=set(records) | known) | set(_references(record, "required_obligation_ids"))
        if "proposition_id" in record or "lemma_id" in record:
            references.update(_references(payload, "global_assumption_ids"))
            references.update(identifier for identifier, candidate in records.items()
                              if "assumption_id" in candidate and candidate.get("is_global") is True)
        for reference in sorted(references):
            canonical = resolve_reference({"aliases": aliases}, reference)
            canonical = scoped_steps.get(identifier, {}).get(canonical, canonical)
            if canonical in records:
                edges[identifier].add(canonical)
            elif canonical not in known:
                item = {"record_id": identifier, "missing_id": canonical,
                        "field": "depends_on" if reference in definitions else "premises"}
                (missing_definitions if reference in definitions else missing_premises).append(item)
        parent = record.get("target_id")
        if isinstance(parent, str) and parent not in records and parent not in known and identifier not in scoped_steps:
            missing_premises.append({"record_id": identifier, "missing_id": parent, "field": "target_id"})
    indices, lowlinks, active, stack, components = {}, {}, set(), [], []
    def visit(identifier):
        indices[identifier] = lowlinks[identifier] = len(indices)
        stack.append(identifier)
        active.add(identifier)
        for dependency in sorted(edges[identifier]):
            if dependency not in indices:
                visit(dependency)
                lowlinks[identifier] = min(lowlinks[identifier], lowlinks[dependency])
            elif dependency in active:
                lowlinks[identifier] = min(lowlinks[identifier], indices[dependency])
        if lowlinks[identifier] == indices[identifier]:
            component = []
            while True:
                member = stack.pop()
                active.remove(member)
                component.append(member)
                if member == identifier:
                    break
            if len(component) > 1 or identifier in edges[identifier]:
                components.append(sorted(component))
    for identifier in sorted(records):
        if identifier not in indices:
            visit(identifier)
    paths = []
    for component in components:
        start, members = component[0], set(component)
        def path_from(identifier, path):
            for dependency in sorted(edges[identifier] & members):
                if dependency == start:
                    return path + [start]
                if dependency not in path:
                    found = path_from(dependency, path + [dependency])
                    if found:
                        return found
            return None
        paths.append(path_from(start, [start]))
    unhealthy = {item["record_id"] for item in missing_definitions + missing_premises}
    unhealthy.update(identifier for component in components for identifier in component)
    symbols = {}
    for collection, _, definition in _records(payload):
        if collection == "definitions" and isinstance(definition.get("symbol"), str):
            symbols.setdefault(definition["symbol"], set()).add(definition["definition_id"])
    ambiguous = []
    for identifier, record in records.items():
        bindings = bound_symbols(record) | inherited_bindings.get(identifier, set())
        free = (set(_references(record, "symbol_references")) | free_expression_symbols(record, bindings)) - bindings
        declared = declared_dependencies(record)
        for symbol in sorted(free):
            owners = symbols.get(symbol, set())
            if len(owners) > 1 and len(owners & declared) != 1 and identifier not in owners:
                ambiguous.append({"record_id": identifier, "symbol": symbol, "candidate_ids": sorted(owners)})
                unhealthy.add(identifier)
    while True:
        affected = {identifier for identifier, dependencies in edges.items() if dependencies & unhealthy}
        affected.update(parent for identifier, parent in target_by_step.items() if identifier in unhealthy and parent in records)
        if affected <= unhealthy:
            break
        unhealthy.update(affected)
    targets = {identifier for identifier, record in records.items() if "proposition_id" in record or "lemma_id" in record}
    return {"active_object_count": len(records),
            "duplicate_ids": sorted(identifier for identifier, count in counts.items() if count > 1),
            "missing_definition_references": missing_definitions, "missing_premise_references": missing_premises,
            "missing_definition_reference_count": len(missing_definitions),
            "missing_premise_reference_count": len(missing_premises),
            "textual_premise_count": textual_premise_count,
            "uninterpreted_premise_count": uninterpreted_premise_count,
            "ambiguous_symbol_bindings": ambiguous, "ambiguous_symbol_binding_count": len(ambiguous),
            "cycle_paths": paths, "cyclic_components": components, "cyclic_component_count": len(components),
            "affected_target_ids": sorted(targets & unhealthy), "affected_target_count": len(targets & unhealthy)}


def repair_dependency_cycles(payload, *, llm_call, logger=None, brief_id="", max_components=3,
                             checkpoint=None, cache_identity=None):
    from .llm_json import call_required_json_with_logging, json_prompt_payload
    from .cache import ExperimentDesignCache
    cache = ExperimentDesignCache(checkpoint or {"enabled": False})
    result = deepcopy(payload)
    diagnostics = inspect_dependency_graph(result)
    for component in diagnostics["cyclic_components"][:max_components]:
        objects = {record[field]: record for _, field, record in _records(result)}
        review_ids = set(component) | {
            record[field] for _, field, record in _records(result)
            if declared_dependencies(record) & set(component)
        }
        review_ids = set(component) | set(sorted(review_ids - set(component))[:8])
        context = {"records": [{field: deepcopy(value) for field, value in objects[identifier].items()
                                if field in {*MATHEMATICAL_FIELDS, *COLLECTION_IDS.values(), "symbol", "variable_references"}}
                               for identifier in sorted(review_ids) if identifier in objects][:24],
                   "cycle_paths": [path for path in diagnostics["cycle_paths"] if path and set(path) & set(component)]}
        supplied_ids = {record[COLLECTION_IDS[collection]] for collection in COLLECTION_IDS
                        for record in context["records"] if COLLECTION_IDS[collection] in record}
        try:
            prompt = CYCLE_REVIEW_PROMPT + json_prompt_payload(context)
            identity = {"version": 1, "prompt": prompt, "llm": cache_identity or {}}
            response = cache.read("object_cycle_reviews", identity)
            if response is None:
                if cache.offline:
                    raise ValueError("object_cycle_review_checkpoint_miss")
                response = call_required_json_with_logging(
                    llm_call, prompt, stage="formal_object_registry", request_kind="repair_dependency_cycle",
                    logger=logger, brief_id=brief_id, request_options={"max_retries": 0},
                )
                try:
                    cache.write("object_cycle_reviews", identity, response)
                except (OSError, TypeError, ValueError):
                    if logger is not None:
                        logger.event("formal_object_registry", "checkpoint_warning", level="WARNING", status="WARNING", brief_id=brief_id)
            for repair in response.get("repairs", []):
                if isinstance(repair, Mapping) and repair.get("record_id") in supplied_ids and isinstance(repair.get("fields"), Mapping):
                    record = objects[repair["record_id"]]
                    record.update({field: deepcopy(value) for field, value in repair["fields"].items()
                                   if field in MATHEMATICAL_FIELDS})
            result, _, _ = commit_group_delta(result, {"new_objects": response.get("new_objects", [])},
                                              group_id="cycle", logger=logger, brief_id=brief_id)
        except Exception as error:
            result.setdefault("unknown_items", []).append({
                "field_path": "object_registry.cycles", "record_ids": component,
                "reason": f"{type(error).__name__}: {error}", "status": "needs_human_input",
            })
    result["object_registry"] = build_registry(result)
    result["object_registry_diagnostics"] = inspect_dependency_graph(result)
    return result
