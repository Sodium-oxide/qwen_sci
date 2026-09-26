"""Preserve formal construction drafts while isolating invalid computational records."""

from collections.abc import Mapping
from copy import deepcopy
import json

from .formal_contracts import FORMAL_PLAN_V2, PROPOSAL_STATUSES, validate_formal_plan_v2
from .formal_dependency import COLLECTION_IDS, dependency_ids, expression_symbols, formal_records


def unwrap_formal_plan(payload):
    current = deepcopy(dict(payload))
    wrappers = []
    for _depth in range(3):
        if any(key in current for key in ("propositions", "lemmas", "assumptions")):
            break
        candidates = [(key, value) for key, value in current.items() if isinstance(value, Mapping)
                      and (value.get("schema_version") == FORMAL_PLAN_V2
                           or any(key in value for key in ("propositions", "lemmas", "assumptions")))]
        if len(candidates) != 1:
            break
        wrapper, candidate = candidates[0]
        wrappers.append(wrapper)
        current = deepcopy(dict(candidate))
    return current, wrappers


def archive_formal_record(plan, path, record, reason):
    entry = {"field_path": path, "reason": reason,
             "raw_json": json.dumps(record, ensure_ascii=False, sort_keys=True)}
    archive = plan.setdefault("construction_archive", [])
    if entry not in archive:
        archive.append(entry)


def construction_warning(plan, identifier, field, reason, *, logger=None, brief_id=""):
    diagnostic = {"record_id": identifier, "field": field, "field_path": f"construction_records.{identifier}.{field}",
                  "reason": reason, "status": "needs_human_input", "category": "construction_warning"}
    if diagnostic not in plan["unknown_items"]:
        plan["unknown_items"].append(diagnostic)
        if logger is not None:
            logger.event("formal_reasoning_planner", "record_warning", level="WARNING", status="WARNING",
                         brief_id=brief_id, record_id=identifier, field=field, error_detail=reason,
                         disposition="kept_draft", requires_human_review=True)
    plan["status"] = "requires_human_review"


def _block_record(plan, record, identifier, field, reason, *, logger=None, brief_id=""):
    if record.get("construction_status") != "blocked":
        archive_formal_record(plan, f"records.{identifier}", record, reason)
    record["construction_status"] = "blocked"
    if "definition_id" in record:
        record.update(definition_status="unresolved", verification_readiness="blocked")
    else:
        record["status"] = "unresolved"
    construction_warning(plan, identifier, field, reason, logger=logger, brief_id=brief_id)


def normalize_variable_dependencies(plan, variable_claim_model=None, *, logger=None, brief_id=""):
    definitions = [record for record in plan.get("definitions", []) if isinstance(record, Mapping)]
    variables = [record for record in (variable_claim_model or {}).get("variables", [])
                 if isinstance(record, Mapping) and isinstance(record.get("variable_id"), str)]
    primary_ids = {record.get("variable_id"): f"D{position}" for position, record in enumerate(variables, 1)
                   if isinstance(record, Mapping)}
    aliases = {}
    for variable in variables:
        variable_id = variable.get("variable_id")
        matches = [record for record in definitions if variable_id in record.get("variable_references", [])]
        primary = [record for record in matches if record.get("definition_id") == primary_ids.get(variable_id)]
        selected = primary or matches
        if len(selected) == 1:
            aliases[variable_id] = selected[0]["definition_id"]
    identifiers = {record[id_field] for collection, id_field in COLLECTION_IDS.items()
                   for record in plan.get(collection, []) if isinstance(record, Mapping)
                   and isinstance(record.get(id_field), str)}
    for collection, id_field in COLLECTION_IDS.items():
        for record in plan.get(collection, []):
            if not isinstance(record, Mapping):
                continue
            for field in ("depends_on", "premises", "assumption_ids"):
                references = record.get(field)
                if not isinstance(references, list):
                    continue
                converted = [aliases.get(reference, reference) if isinstance(reference, str)
                             and reference not in identifiers else reference for reference in references]
                if converted != references:
                    repair = {"record_id": record[id_field], "field": field,
                              "original": deepcopy(references), "normalized": converted}
                    if repair not in plan.setdefault("dependency_repairs", []):
                        plan["dependency_repairs"].append(repair)
                    record[field] = converted
                    if logger is not None:
                        logger.event("formal_reasoning_planner", "dependency_reference_repaired", status="REPAIRED",
                                     brief_id=brief_id, record_id=record[id_field], field=field,
                                     original_references=references, normalized_references=converted)
    return plan


def recover_counterexample_analysis(payload, plan, *, logger=None, brief_id=""):
    from .counterexample_analyzer import no_target_counterexample_analysis, unavailable_counterexample_analysis
    from .formal_dependency import build_counterexample_target
    from .reasoning_validation import _verified_markers, validate_counterexample_analysis

    targets = {record.get("proposition_id", record.get("lemma_id")): record
               for record in plan["propositions"] + plan["lemmas"]}
    if not targets:
        return no_target_counterexample_analysis()
    candidates = payload.get("target_analyses", [payload]) if isinstance(payload, Mapping) else []
    candidates = candidates if isinstance(candidates, list) else []
    retained = []
    for target_id, target in targets.items():
        candidate = next((deepcopy(dict(item)) for item in candidates if isinstance(item, Mapping)
                          and item.get("target_claim_id") == target_id), None)
        errors = ["Missing target analysis."]
        if candidate is not None:
            candidate.pop("target_analyses", None)
            try:
                errors = validate_counterexample_analysis(candidate, formal_reasoning_plan=plan) + _verified_markers(candidate)
            except (TypeError, ValueError, KeyError) as error:
                errors = [f"{type(error).__name__}: {error}"]
        if errors:
            reason = "; ".join(errors)
            archived = candidate
            candidate = unavailable_counterexample_analysis(reason=reason)
            candidate.update(target_claim_id=target_id, target_specification=build_counterexample_target(plan, target_id),
                             negated_conclusion=f"NOT ({target.get('conclusion', '')})", search_domain=str(target.get("scope") or ""))
            if archived is not None:
                archive_formal_record(candidate, f"target_analyses.{target_id}", archived, reason)
            if logger is not None:
                logger.event("reasoning_validation", "target_warning", level="WARNING", status="WARNING",
                             brief_id=brief_id, target_id=target_id, error_detail=reason, disposition="kept_other_targets")
        retained.append(candidate)
    primary = deepcopy(retained[0])
    if len(retained) > 1:
        primary["target_analyses"] = retained
    return primary


def recover_formal_plan(payload, variable_claim_model=None, *, logger=None, brief_id=""):
    from .formal_definition_resolver import normalize_definition_conditions, normalize_definition_references
    from .formal_definition_resolver import normalize_record_completeness, FormalDefinitionResolver
    from .reasoning_validation import _verified_markers

    plan, wrappers = unwrap_formal_plan(payload)
    plan.update(schema_version=FORMAL_PLAN_V2, applicability="formal_theory")
    if type(plan.get("revision")) is not int or plan["revision"] < 1:
        plan["revision"] = 1
    if plan.get("status") not in ("unverified", "requires_human_review", "not_applicable"):
        plan["status"] = "unverified"
    for field in ("unknown_items", "semantic_diagnostics", "global_assumption_ids", "construction_archive", "dependency_repairs"):
        if not isinstance(plan.get(field), list):
            plan[field] = []
    for field in ("unknown_items", "semantic_diagnostics"):
        retained = []
        for index, item in enumerate(plan[field]):
            if not isinstance(item, Mapping) or _verified_markers(item) or (
                field == "semantic_diagnostics" and item.get("target_id") is not None
                and not isinstance(item["target_id"], str)
            ):
                archive_formal_record(plan, f"{field}[{index}]", item, "Malformed diagnostic retained in archive.")
                continue
            retained.append(deepcopy(dict(item)))
        plan[field] = retained
    derivation = plan.get("forward_derivation")
    if derivation is not None and not isinstance(derivation, Mapping):
        archive_formal_record(plan, "forward_derivation", derivation, "Malformed derivation envelope.")
    plan["forward_derivation"] = deepcopy(dict(derivation)) if isinstance(derivation, Mapping) else {}
    steps = plan["forward_derivation"].get("steps", [])
    if not isinstance(steps, list):
        archive_formal_record(plan, "forward_derivation.steps", steps, "Malformed derivation collection.")
        steps = []
    plan["forward_derivation"]["steps"] = []
    if wrappers and logger is not None:
        logger.event("formal_reasoning_planner", "response_unwrapped", status="REPAIRED", brief_id=brief_id,
                     wrapper_fields=wrappers)
    used_ids = set()
    accepted_records = {}
    for collection, id_field in COLLECTION_IDS.items():
        records = plan.get(collection, [])
        if isinstance(records, Mapping):
            records = [records] if id_field in records else list(records.values())
        if not isinstance(records, list):
            archive_formal_record(plan, collection, records, "Record collection cannot be interpreted.")
            records = []
        retained = []
        for index, original in enumerate(records):
            if not isinstance(original, Mapping):
                archive_formal_record(plan, f"{collection}[{index}]", original, "Expected a record object.")
                construction_warning(plan, f"{collection}[{index}]", "record", "Malformed record retained in archive.", logger=logger, brief_id=brief_id)
                continue
            record = deepcopy(dict(original))
            identifier = record.get(id_field, record.get("id"))
            if not isinstance(identifier, str) or not identifier.strip():
                identifier = f"RECOVERED_{collection}_{index + 1}"
                construction_warning(plan, identifier, id_field, "Missing identifier assigned for draft tracking.", logger=logger, brief_id=brief_id)
            if identifier in used_ids:
                if record == accepted_records[identifier]:
                    continue
                archive_formal_record(plan, f"{collection}.{identifier}", record, "Duplicate identifier candidate.")
                _block_record(plan, accepted_records[identifier], identifier, id_field, "Conflicting identifier candidates require review.", logger=logger, brief_id=brief_id)
                construction_warning(plan, identifier, id_field, "Duplicate candidate retained in archive.", logger=logger, brief_id=brief_id)
                continue
            used_ids.add(identifier)
            record[id_field] = identifier
            accepted_records[identifier] = record
            if _verified_markers(record):
                archive_formal_record(plan, f"{collection}.{identifier}", record, "Untrusted verification claims.")
                for field in list(record):
                    if _verified_markers({field: record[field]}):
                        record.pop(field)
                construction_warning(plan, identifier, "status", "Untrusted verification claims removed; mathematical content remains a draft.", logger=logger, brief_id=brief_id)
            for field in ("premises", "depends_on", "assumption_ids", "symbol_references", "variable_references"):
                if field not in record:
                    continue
                references = record[field]
                if isinstance(references, str):
                    references = [references]
                if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
                    _block_record(plan, record, identifier, field, "Unparseable references retained in archive.", logger=logger, brief_id=brief_id)
                    references = []
                record[field] = references
            if collection != "definitions" and (not isinstance(record.get("status"), str)
                                                  or record["status"] not in PROPOSAL_STATUSES):
                record["status"] = "unresolved" if collection == "proof_obligations" else "candidate_formalization"
            if collection in ("propositions", "lemmas"):
                defaults = {"statement": "", "scope": "", "conclusion": "", "premises": [], "quantifiers": [],
                            "domain_expression": None, "conclusion_expression": None, "required_obligation_ids": []}
                for field, default in defaults.items():
                    if field not in record:
                        _block_record(plan, record, identifier, field, "Missing target content remains unresolved.", logger=logger, brief_id=brief_id)
                        record[field] = deepcopy(default)
                quantifiers = record["quantifiers"]
                if not isinstance(quantifiers, list) or any(not isinstance(item, Mapping)
                        or not isinstance(item.get("symbol"), str) or item.get("sort") not in ("real", "integer", "boolean")
                        or item.get("quantifier") != "forall" for item in quantifiers):
                    _block_record(plan, record, identifier, "quantifiers", "Unsupported quantifiers retained in archive.", logger=logger, brief_id=brief_id)
                    record["quantifiers"] = []
                if not isinstance(record["required_obligation_ids"], list) or not all(isinstance(item, str) for item in record["required_obligation_ids"]):
                    _block_record(plan, record, identifier, "required_obligation_ids", "Malformed obligation references.", logger=logger, brief_id=brief_id)
                    record["required_obligation_ids"] = []
                if not isinstance(record.get("lemma_instantiations", []), list):
                    _block_record(plan, record, identifier, "lemma_instantiations", "Malformed lemma instantiations.", logger=logger, brief_id=brief_id)
                    record["lemma_instantiations"] = []
            retained.append(record)
        plan[collection] = retained
    retained_steps = []
    for index, original in enumerate(steps):
        identifier = original.get("step_id") if isinstance(original, Mapping) else None
        if not isinstance(identifier, str) or not identifier or identifier in used_ids:
            archive_formal_record(plan, f"forward_derivation.steps[{index}]", original, "Invalid or duplicate step identifier.")
            continue
        record = deepcopy(dict(original))
        used_ids.add(identifier)
        for field in ("premises", "depends_on", "assumption_ids", "symbol_references", "variable_references"):
            references = record.get(field, [])
            if isinstance(references, str):
                references = [references]
            if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
                _block_record(plan, record, identifier, field, "Malformed derivation references.", logger=logger, brief_id=brief_id)
                references = []
            record[field] = references
        record["status"] = "proposed" if record.get("status") in ("proposed", "unverified") else "unresolved"
        retained_steps.append(record)
    plan["forward_derivation"]["steps"] = retained_steps
    envelope = {"schema_version": "formal_definition_resolution_v1", "definitions": plan["definitions"],
                "model_relations": plan["model_relations"], "unknown_items": []}
    envelope, _condition_repairs = normalize_definition_conditions(envelope)
    envelope, _reference_repairs = normalize_definition_references(envelope)
    envelope = normalize_record_completeness(envelope, {})
    original_envelope = deepcopy(envelope)
    envelope, _discarded = FormalDefinitionResolver._quarantine_invalid_records(envelope, {})
    for collection, id_field in (("definitions", "definition_id"), ("model_relations", "relation_id")):
        retained_ids = {record[id_field] for record in envelope[collection]}
        for record in original_envelope[collection]:
            if record[id_field] not in retained_ids:
                archive_formal_record(plan, f"{collection}.{record[id_field]}", record, "Invalid formal input retained in archive.")
                construction_warning(plan, record[id_field], "record", "Invalid formal input retained in archive.", logger=logger, brief_id=brief_id)
    symbols = set()
    symbol_records = {}
    for collection in ("definitions", "model_relations"):
        retained = []
        for record in envelope[collection]:
            if collection == "definitions":
                symbol = record.get("symbol")
                if not isinstance(symbol, str) or not symbol or symbol in symbols:
                    archive_formal_record(plan, f"definitions.{record['definition_id']}", record, "Missing or duplicate declared symbol.")
                    construction_warning(plan, record["definition_id"], "symbol", "Symbol candidate retained in archive.", logger=logger, brief_id=brief_id)
                    if isinstance(symbol, str) and symbol in symbol_records:
                        previous = symbol_records[symbol]
                        _block_record(plan, previous, previous["definition_id"], "symbol", "Conflicting symbol declarations require review.", logger=logger, brief_id=brief_id)
                    continue
                symbols.add(symbol)
                symbol_records[symbol] = record
            retained.append(record)
        plan[collection] = retained
    for item in envelope["unknown_items"]:
        if item not in plan["unknown_items"]:
            plan["unknown_items"].append(item)
    normalize_variable_dependencies(plan, variable_claim_model, logger=logger, brief_id=brief_id)
    records = formal_records(plan)
    variable_ids = {record.get("variable_id") for record in (variable_claim_model or {}).get("variables", [])
                    if isinstance(record, Mapping) and isinstance(record.get("variable_id"), str)}
    for identifier, record in records.items():
        for field in ("premises", "depends_on", "assumption_ids"):
            references = record.get(field, [])
            missing = [reference for reference in references if reference not in records or "obligation_id" in records[reference]]
            if missing:
                _block_record(plan, record, identifier, field, f"Unresolved references: {missing}", logger=logger, brief_id=brief_id)
                record[field] = [reference for reference in references if reference not in missing]
        if variable_claim_model is not None:
            missing = [reference for reference in record.get("variable_references", []) if reference not in variable_ids]
            if missing:
                _block_record(plan, record, identifier, "variable_references", f"Unknown variables: {missing}", logger=logger, brief_id=brief_id)
                record["variable_references"] = [reference for reference in record["variable_references"] if reference not in missing]
        missing_symbols = (set(record.get("symbol_references", [])) | expression_symbols(record)) - symbols
        if missing_symbols and ("definition_id" not in record or record.get("definition_status") == "specified"):
            _block_record(plan, record, identifier, "symbol_references", f"Undeclared symbols: {sorted(missing_symbols)}", logger=logger, brief_id=brief_id)
            record["symbol_references"] = [symbol for symbol in record.get("symbol_references", []) if symbol in symbols]
            for field in ("formal_expression", "predicate_expression", "domain_expression", "conclusion_expression"):
                if field in record:
                    record[field] = None
            record["condition_expressions"] = []
            if "quantifiers" in record:
                record["quantifiers"] = []
    invalid_globals = [identifier for identifier in plan["global_assumption_ids"]
                       if not isinstance(identifier, str) or identifier not in records or "assumption_id" not in records[identifier]]
    plan["global_assumption_ids"] = [identifier for identifier in plan["global_assumption_ids"] if identifier not in invalid_globals]
    targets = {record.get("proposition_id", record.get("lemma_id")): record
               for record in plan["propositions"] + plan["lemmas"]}
    for target in targets.values():
        identifier = target.get("proposition_id", target.get("lemma_id"))
        if invalid_globals:
            _block_record(plan, target, identifier, "global_assumption_ids", "A global premise cannot be resolved.", logger=logger, brief_id=brief_id)
        missing = [reference for reference in target["required_obligation_ids"]
                   if reference not in records or records[reference].get("target_id") != identifier]
        if missing:
            _block_record(plan, target, identifier, "required_obligation_ids", f"Unresolved obligations: {missing}", logger=logger, brief_id=brief_id)
            target["required_obligation_ids"] = [reference for reference in target["required_obligation_ids"] if reference not in missing]
    obligations = []
    for record in plan["proof_obligations"]:
        parent = targets.get(record.get("target_id")) if isinstance(record.get("target_id"), str) else None
        if parent is None:
            archive_formal_record(plan, f"proof_obligations.{record['obligation_id']}", record, "Unknown target association.")
            construction_warning(plan, record["obligation_id"], "target_id", "Unknown target association.", logger=logger, brief_id=brief_id)
            continue
        if record["obligation_id"] not in parent["required_obligation_ids"]:
            parent["required_obligation_ids"].append(record["obligation_id"])
        obligations.append(record)
    plan["proof_obligations"] = obligations
    attempts = plan.get("proof_attempts", [])
    if not isinstance(attempts, list):
        archive_formal_record(plan, "proof_attempts", attempts, "Malformed proof attempts.")
        attempts = []
    plan["proof_attempts"] = []
    for target_id, target in targets.items():
        instances = target.get("lemma_instantiations", [])
        malformed = any(not isinstance(instance, Mapping) or not isinstance(instance.get("lemma_id"), str)
                        for instance in instances)
        if malformed:
            _block_record(plan, target, target_id, "lemma_instantiations", "Malformed lemma application retained in archive.", logger=logger, brief_id=brief_id)
            target["lemma_instantiations"] = []
    records = formal_records(plan)
    active = set()
    visited = set()

    def visit(identifier, path):
        if identifier in active:
            for member in path[path.index(identifier):]:
                _block_record(plan, records[member], member, "depends_on", "Cyclic construction dependency.", logger=logger, brief_id=brief_id)
                for field in ("premises", "depends_on", "assumption_ids", "symbol_references", "condition_expressions"):
                    records[member][field] = []
                for field in ("formal_expression", "predicate_expression", "conclusion_expression", "domain_expression"):
                    if field in records[member]:
                        records[member][field] = None
            return
        if identifier in visited:
            return
        active.add(identifier)
        for dependency in dependency_ids(records[identifier], plan):
            if dependency in records:
                visit(dependency, path + [identifier])
        active.remove(identifier)
        visited.add(identifier)

    for identifier in records:
        visit(identifier, [])
    errors = validate_formal_plan_v2(plan, variable_claim_model)
    for identifier, target in targets.items():
        instance_errors = [error for error in errors if error.startswith(f"{identifier}_") and "lemma_" in error]
        if instance_errors:
            _block_record(plan, target, identifier, "lemma_instantiations", "; ".join(instance_errors), logger=logger, brief_id=brief_id)
            target["lemma_instantiations"] = []
    errors = validate_formal_plan_v2(plan, variable_claim_model)
    if errors:
        affected = {identifier for identifier in records if any(error.startswith(f"{identifier}_") for error in errors)}
        if not affected:
            raise ValueError("formal_recovery_unhandled: " + "; ".join(errors))
        for collection, id_field in COLLECTION_IDS.items():
            for record in plan[collection]:
                if record[id_field] in affected:
                    archive_formal_record(plan, f"{collection}.{record[id_field]}", record, "; ".join(errors))
                    construction_warning(plan, record[id_field], "record", "Invalid record retained in archive.", logger=logger, brief_id=brief_id)
            plan[collection] = [record for record in plan[collection] if record[id_field] not in affected]
        plan["proof_attempts"] = attempts
        return recover_formal_plan(plan, variable_claim_model, logger=logger, brief_id=brief_id)
    changed = True
    while changed:
        changed = False
        for identifier, record in records.items():
            if record.get("construction_status") == "blocked":
                continue
            dependencies = dependency_ids(record, plan)
            if identifier in targets:
                dependencies.update(plan["global_assumption_ids"])
                dependencies.update(item["assumption_id"] for item in plan["assumptions"] if item.get("is_global") is True)
            if any(records[dependency].get("construction_status") == "blocked" for dependency in dependencies if dependency in records):
                _block_record(plan, record, identifier, "premises", "A prerequisite construction remains blocked.", logger=logger, brief_id=brief_id)
                changed = True
    for field, id_field in (("target_proposition_id", "proposition_id"), ("final_conclusion_step", "step_id")):
        identifier = plan["forward_derivation"].get(field)
        if identifier and (not isinstance(identifier, str) or identifier not in records or id_field not in records[identifier]):
            archive_formal_record(plan, f"forward_derivation.{field}", identifier, "Unresolved derivation endpoint.")
            plan["forward_derivation"][field] = ""
            plan["forward_derivation"]["status"] = "unresolved"
    for index, attempt in enumerate(attempts):
        target_id = attempt.get("target_id") if isinstance(attempt, Mapping) else None
        trial = deepcopy(plan)
        trial["proof_attempts"] = [*plan["proof_attempts"], attempt]
        try:
            errors = validate_formal_plan_v2(trial, variable_claim_model) + _verified_markers(attempt)
        except (TypeError, ValueError, KeyError) as error:
            errors = [f"{type(error).__name__}: {error}"]
        if not isinstance(target_id, str) or target_id not in targets or targets[target_id].get("construction_status") == "blocked" or errors:
            archive_formal_record(plan, f"proof_attempts[{index}]", attempt, "; ".join(errors) or "Target construction is blocked.")
            construction_warning(plan, target_id if isinstance(target_id, str) else f"proof_attempts[{index}]", "proof_attempts", "; ".join(errors) or "Target construction is blocked.", logger=logger, brief_id=brief_id)
        else:
            plan["proof_attempts"].append(deepcopy(attempt))
    return plan
