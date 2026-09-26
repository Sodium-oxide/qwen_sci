"""Complete only diagnosed fields while preserving the accepted formal skeleton."""

from collections.abc import Mapping
from copy import deepcopy

from .formal_contracts import PROPOSAL_STATUSES, TARGET_FIELDS, _valid_restricted_expression
from .formal_dependency import COLLECTION_IDS
from .formal_plan_recovery import archive_formal_record
from .llm_json import call_required_json_with_logging, json_prompt_payload


def skeleton_output_contract():
    example = {
        "proposition_id": "P1", "statement": "A positive real is nonnegative.",
        "scope": "Real scalar x under assumption A1: x > 0", "premises": ["A1"],
        "conclusion": "x >= 0", "quantifiers": [{"symbol": "x", "sort": "real", "quantifier": "forall"}],
        "domain_expression": {"bool": True},
        "conclusion_expression": {"op": "ge", "args": [{"symbol": "x"}, {"number": "0"}]},
        "required_obligation_ids": [], "symbol_references": ["x"], "variable_references": [],
        "status": "candidate_formalization",
    }
    lemma = deepcopy(example)
    lemma["lemma_id"] = "L1"
    lemma.pop("proposition_id")
    return {"required_target_fields": list(TARGET_FIELDS), "target_examples": {"proposition": example, "lemma": lemma},
            "expression_language": {
                "leaves": [{"symbol": "name"}, {"number": "rational_string"}, {"bool": True}],
                "operation": {"op": "operator", "args": ["AST", "AST"]},
                "operators": ["add", "sub", "mul", "div", "pow", "eq", "ne", "lt", "le", "gt", "ge", "and", "or", "not"],
                "unsupported_expression": None,
            }}


def normalize_skeleton_target_fields(plan, *, logger=None, brief_id=""):
    aliases = {"premises": "premise_ids", "conclusion": "conclusion_text", "scope": "applicability_scope",
               "domain_expression": "domain_ast", "conclusion_expression": "conclusion_ast",
               "quantifiers": "quantified_variables"}
    for collection in ("propositions", "lemmas"):
        for record in plan.get(collection, []):
            if not isinstance(record, dict):
                continue
            copied = []
            for field, alias in aliases.items():
                if field not in record and alias in record:
                    record[field] = deepcopy(record[alias])
                    copied.append(field)
            if copied and logger is not None:
                logger.event("formal_reasoning_planner", "target_shape_repaired", status="REPAIRED",
                             brief_id=brief_id, record_id=record.get("proposition_id", record.get("lemma_id")), fields=copied)


def skeleton_repair_targets(plan):
    identifiers = {record.get(id_field) for collection, id_field in COLLECTION_IDS.items()
                   for record in plan.get(collection, []) if isinstance(record, Mapping)
                   and isinstance(record.get(id_field), str)}
    obligations_by_id = {record.get("obligation_id"): record for record in plan.get("proof_obligations", [])
                         if isinstance(record, Mapping) and isinstance(record.get("obligation_id"), str)}
    target_ids = {record.get(COLLECTION_IDS[collection]) for collection in ("propositions", "lemmas")
                  for record in plan.get(collection, []) if isinstance(record, Mapping)
                  and isinstance(record.get(COLLECTION_IDS[collection]), str)}
    targets = []
    for collection in ("assumptions", "propositions", "lemmas", "proof_obligations"):
        id_field = COLLECTION_IDS[collection]
        for record in plan.get(collection, []):
            if not isinstance(record, Mapping) or not isinstance(record.get(id_field), str):
                continue
            issues = {}
            if collection in ("propositions", "lemmas"):
                for field in TARGET_FIELDS:
                    if field not in record:
                        issues[field] = "Required target field is absent."
                for field in ("statement", "scope", "conclusion"):
                    if field in record and (not isinstance(record[field], str) or not record[field].strip()):
                        issues[field] = "Scientific text is missing or malformed."
                quantifiers = record.get("quantifiers", [])
                if not isinstance(quantifiers, list) or any(not isinstance(item, Mapping)
                    or not isinstance(item.get("symbol"), str) or item.get("sort") not in ("real", "integer", "boolean")
                    or item.get("quantifier") != "forall" for item in quantifiers):
                    issues["quantifiers"] = "Quantifier format is unsupported."
                obligations = record.get("required_obligation_ids", [])
                if not isinstance(obligations, list) or not all(isinstance(item, str) for item in obligations):
                    issues["required_obligation_ids"] = "Obligation references must be an array of IDs."
                elif any(item not in obligations_by_id or obligations_by_id[item].get("target_id") != record[id_field]
                         for item in obligations):
                    issues["required_obligation_ids"] = "Obligation references are absent or associated with another target."
            for field in ("domain_expression", "conclusion_expression", "predicate_expression"):
                if record.get(field) is not None and not _valid_restricted_expression(record[field]):
                    issues[field] = "Expression must use the restricted AST or null."
            for field in ("premises", "depends_on", "assumption_ids", "symbol_references", "variable_references"):
                references = record.get(field, [])
                if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
                    issues[field] = "References must be an array of IDs or symbol names."
                elif field in ("premises", "depends_on", "assumption_ids") and any(item not in identifiers for item in references):
                    issues[field] = "References include an unknown formal record ID."
            if collection == "proof_obligations" and (not isinstance(record.get("target_id"), str) or record["target_id"] not in target_ids):
                issues["target_id"] = "Target association is absent or unknown."
            if record.get("status") is not None and (not isinstance(record["status"], str) or record["status"] not in PROPOSAL_STATUSES):
                issues["status"] = "Proposal status is unsupported."
            if issues:
                targets.append({"collection": collection, "record_id": record[id_field], "fields": issues})
    return targets


def repair_skeleton_records(plan, context, *, settings, repair_prompt, llm_call, logger=None, brief_id=""):
    rounds = max(0, min(2, int(settings.get("max_skeleton_repairs", 1))))
    batch_size = max(1, min(8, int(settings.get("max_records_per_skeleton_repair", 4))))
    audit = plan.setdefault("skeleton_repair_audit", [])
    if not isinstance(audit, list):
        archive_formal_record(plan, "skeleton_repair_audit", audit, "Malformed repair audit.")
        audit = plan["skeleton_repair_audit"] = []
    for repair_round in range(1, rounds + 1):
        targets = skeleton_repair_targets(plan)
        if not targets:
            break
        progress = False
        for offset in range(0, len(targets), batch_size):
            batch = targets[offset:offset + batch_size]
            allowed = {(item["collection"], item["record_id"]): item["fields"] for item in batch}
            records = {(collection, record.get(COLLECTION_IDS[collection])): record for collection in COLLECTION_IDS
                       for record in plan.get(collection, []) if isinstance(record, dict)
                       and isinstance(record.get(COLLECTION_IDS[collection]), str)}
            request = {**context, "output_contract": skeleton_output_contract(), "repair_targets": batch,
                       "records": [deepcopy(records[key]) for key in allowed],
                       "record_catalog": [{"collection": collection, "record_id": identifier,
                                           "statement": record.get("statement", record.get("target", "")),
                                           "premises": record.get("premises", [])}
                                          for (collection, identifier), record in records.items()
                                          if collection not in ("definitions", "model_relations")]}
            entry = {"round": repair_round, "record_ids": [item["record_id"] for item in batch], "updated_fields": [], "status": "NO_PROGRESS"}
            try:
                response = call_required_json_with_logging(llm_call, repair_prompt + json_prompt_payload(request),
                    stage="formal_reasoning_planner", request_kind=f"v2_skeleton_repair_round_{repair_round}_batch_{offset // batch_size + 1}",
                    logger=logger, brief_id=brief_id)
                if not isinstance(response, Mapping) or response.get("schema_version") != "skeleton_record_patch_v1" or not isinstance(response.get("patches"), list):
                    raise ValueError("invalid_skeleton_record_patch")
                for patch in response["patches"]:
                    key = (patch.get("collection"), patch.get("record_id")) if isinstance(patch, Mapping) else (None, None)
                    if not all(isinstance(item, str) for item in key) or key not in allowed or not isinstance(patch.get("fields"), Mapping):
                        archive_formal_record(plan, "skeleton_repair.invalid_patch", patch, "Patch is outside requested records.")
                        continue
                    record = records[key]
                    fields = {field: deepcopy(value) for field, value in patch["fields"].items() if field in allowed[key]}
                    if any(field not in allowed[key] for field in patch["fields"]):
                        archive_formal_record(plan, f"skeleton_repair.{key[1]}", patch, "Accepted fields cannot be replaced.")
                    current_issues = next((item["fields"] for item in skeleton_repair_targets(plan)
                                           if (item["collection"], item["record_id"]) == key), {})
                    fields = {field: value for field, value in fields.items() if field in current_issues}
                    trial = deepcopy(plan)
                    trial_record = next(item for item in trial[key[0]] if isinstance(item, Mapping)
                                        and item.get(COLLECTION_IDS[key[0]]) == key[1])
                    trial_record.update(fields)
                    remaining = next((item["fields"] for item in skeleton_repair_targets(trial)
                                      if (item["collection"], item["record_id"]) == key), {})
                    rejected = {field for field in fields if field in remaining}
                    for field in ("premises", "depends_on", "assumption_ids", "required_obligation_ids"):
                        original = record.get(field)
                        if field in fields and isinstance(original, list) and isinstance(fields[field], list):
                            if len(fields[field]) < len(original) or any(
                                reference not in fields[field] for reference in original
                                if isinstance(reference, str) and any(identifier == reference for _, identifier in records)
                            ):
                                rejected.add(field)
                    if rejected:
                        archive_formal_record(plan, f"skeleton_repair.{key[1]}", patch,
                                              f"Invalid or weakened patch fields: {', '.join(sorted(rejected))}.")
                        if logger is not None:
                            logger.event("formal_reasoning_planner", "skeleton_patch_warning", level="WARNING", status="WARNING",
                                         brief_id=brief_id, record_id=key[1], fields=sorted(rejected),
                                         disposition="kept_previous_fields", blocking=False)
                    fields = {field: value for field, value in fields.items() if field not in rejected}
                    if fields and any(record.get(field) != value or field not in record for field, value in fields.items()):
                        archive_formal_record(plan, f"skeleton_repair.{key[1]}", record, "Original draft before targeted field repair.")
                        record.update(fields)
                        resolved_fields = {field for field, value in fields.items() if value not in (None, "", [])}
                        plan["unknown_items"] = [item for item in plan["unknown_items"] if not (
                            isinstance(item, Mapping) and item.get("diagnostic_origin") == "skeleton_record_repair"
                            and item.get("record_id") == key[1] and item.get("field") in resolved_fields)]
                        entry["updated_fields"].append({"record_id": key[1], "fields": sorted(fields)})
                        progress = True
                        entry["status"] = "REPAIRED"
                for item in response.get("unknown_items", []) if isinstance(response.get("unknown_items"), list) else []:
                    if isinstance(item, Mapping) and isinstance(item.get("record_id"), str) and item["record_id"] in entry["record_ids"]:
                        key = next(key for key in allowed if key[1] == item["record_id"])
                        if not isinstance(item.get("field"), str) or item["field"] not in allowed[key]:
                            continue
                        value = records[key].get(item["field"])
                        remaining = next((target["fields"] for target in skeleton_repair_targets(plan)
                                          if (target["collection"], target["record_id"]) == key), {})
                        if item["field"] not in remaining and value not in (None, "", []):
                            continue
                        diagnostic = dict(item, field_path=f"construction_records.{item['record_id']}.{item.get('field', 'content')}",
                                          status="needs_human_input", category="construction_warning",
                                          diagnostic_origin="skeleton_record_repair")
                        entry.setdefault("diagnostics", []).append(deepcopy(diagnostic))
                        if diagnostic not in plan["unknown_items"]:
                            plan["unknown_items"].append(diagnostic)
            except Exception as error:
                entry.update(status="WARNING", reason=f"{type(error).__name__}: {error}")
                if logger is not None:
                    logger.event("formal_reasoning_planner", "skeleton_repair_warning", level="WARNING", status="WARNING",
                                 brief_id=brief_id, record_ids=entry["record_ids"], repair_round=repair_round,
                                 error_detail=entry["reason"], disposition="kept_previous_drafts")
            audit.append(entry)
            if logger is not None:
                logger.event("formal_reasoning_planner", "skeleton_repair_completed", status=entry["status"], brief_id=brief_id,
                             record_ids=entry["record_ids"], repair_round=repair_round, updated_fields=entry["updated_fields"])
        if not progress:
            break
    return plan
