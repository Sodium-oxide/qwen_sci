"""Complete only diagnosed fields while preserving the accepted formal skeleton."""

from collections.abc import Mapping
from copy import deepcopy

from .formal_contracts import PROPOSAL_STATUSES, TARGET_FIELDS, _valid_restricted_expression
from .formal_dependency import COLLECTION_IDS
from .formal_expression import EXPRESSION_CONTRACT, expression_diagnostics, normalize_expression, valid_declarations
from .formal_plan_recovery import archive_formal_record
from .llm_json import call_required_json_with_logging, json_prompt_payload


EXPRESSION_FIELDS = ("domain_expression", "conclusion_expression", "predicate_expression")
REFERENCE_FIELDS = ("premises", "depends_on", "assumption_ids", "required_obligation_ids")


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
    assumption = {
        "assumption_id": "A1", "statement": "The real scalar x is positive.", "predicate": "x > 0",
        "predicate_expression": {"op": "gt", "args": [{"symbol": "x"}, {"number": "0"}]},
        "quantifiers": [{"symbol": "x", "sort": "real", "quantifier": "forall"}],
        "scope": "Real scalars", "assumption_kind": "modeling_convention", "is_global": False,
        "depends_on": [], "symbol_references": ["x"], "variable_references": [],
        "status": "candidate_formalization",
    }
    obligation = {
        "obligation_id": "PO_L1_1", "target_id": "L1", "statement": "Check the order implication.",
        "depends_on": ["A1"], "status": "unresolved",
    }
    lemma["required_obligation_ids"] = [obligation["obligation_id"]]
    return {"required_target_fields": list(TARGET_FIELDS),
            "target_examples": {"assumption": assumption, "proposition": example, "lemma": lemma,
                                "proof_obligation": obligation},
            "reference_rules": {
                "required_obligation_ids": "Use only declared proof_obligation IDs with target_id equal to this target's ID.",
                "repair": "Replace or remove invalid references; retain valid dependencies and obligations. "
                          "Related association patches are validated together.",
                "completion": "Mathematical completion is allowed; accepted candidates continue to proof and verification. "
                              "Use null and an encoding-gap explanation when an expression cannot be encoded.",
            },
            "expression_language": deepcopy(EXPRESSION_CONTRACT)}


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


def _record_map(plan):
    return {(collection, record.get(id_field)): record for collection, id_field in COLLECTION_IDS.items()
            for record in plan.get(collection, []) if isinstance(record, Mapping)
            and isinstance(record.get(id_field), str)}


def _valid_reference(field, reference, owner_id, records):
    if not isinstance(reference, str):
        return False
    if field == "required_obligation_ids":
        return records.get(("proof_obligations", reference), {}).get("target_id") == owner_id
    if field == "assumption_ids":
        return ("assumptions", reference) in records
    return any(identifier == reference and collection != "proof_obligations" for collection, identifier in records)


def _reference_issue(field, reference, owner_id, records):
    matches = [(collection, record) for (collection, identifier), record in records.items() if identifier == reference]
    issue = {"field": field, "reference": reference}
    if not isinstance(reference, str):
        return dict(issue, error_code="reference_requires_string", reason="The reference must be a string ID.")
    if not matches:
        return dict(issue, error_code="missing_reference", reason="No declared formal record has this ID.")
    if field == "required_obligation_ids":
        obligation = records.get(("proof_obligations", reference))
        if obligation is not None:
            return dict(issue, error_code="obligation_target_mismatch", actual_target_id=obligation.get("target_id"),
                        expected_target_id=owner_id, reason="The obligation is associated with a different target.")
        return dict(issue, error_code="wrong_reference_type", actual_collection=matches[0][0],
                    reason="A required obligation must reference a proof_obligation record.")
    return dict(issue, error_code="wrong_reference_type", actual_collection=matches[0][0],
                reason="Use an assumption ID." if field == "assumption_ids" else "A proof obligation cannot serve as an established premise.")


def skeleton_repair_targets(plan):
    records = _record_map(plan)
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
                if not valid_declarations(quantifiers):
                    issues["quantifiers"] = "Quantifier format is unsupported."
                obligations = record.get("required_obligation_ids", [])
                if not isinstance(obligations, list) or not all(isinstance(item, str) for item in obligations):
                    issues["required_obligation_ids"] = "Obligation references must be an array of IDs."
                elif any(not _valid_reference("required_obligation_ids", item, record[id_field], records) for item in obligations):
                    issues["required_obligation_ids"] = "Obligation references are absent or associated with another target."
                elif any(identifier not in obligations for identifier, obligation in obligations_by_id.items()
                         if obligation.get("target_id") == record[id_field]):
                    issues["required_obligation_ids"] = "An obligation associated with this target is not registered in required_obligation_ids."
            for field in ("domain_expression", "conclusion_expression", "predicate_expression"):
                if record.get(field) is not None and not _valid_restricted_expression(record[field]):
                    issues[field] = "Expression must use formal_expression_v2 or null."
            for field in ("premises", "depends_on", "assumption_ids", "symbol_references", "variable_references"):
                references = record.get(field, [])
                if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
                    issues[field] = "References must be an array of IDs or symbol names."
                elif field in ("premises", "depends_on", "assumption_ids") and any(
                    not _valid_reference(field, item, record[id_field], records) for item in references
                ):
                    issues[field] = "References include an unknown or incorrectly typed formal record ID."
            if collection == "proof_obligations" and (not isinstance(record.get("target_id"), str) or record["target_id"] not in target_ids):
                issues["target_id"] = "Target association is absent or unknown."
            if record.get("status") is not None and (not isinstance(record["status"], str) or record["status"] not in PROPOSAL_STATUSES):
                issues["status"] = "Proposal status is unsupported."
            if issues:
                diagnostics = []
                for field, reason in issues.items():
                    if field in EXPRESSION_FIELDS and record.get(field) is not None:
                        diagnostics.extend(dict(item, field=field, reason=reason) for item in
                                           expression_diagnostics(record[field], reject_unknown=True))
                    else:
                        diagnostics.append({"field": field, "node_path": "$", "error_code": "invalid_record_field",
                                            "actual_type": type(record.get(field)).__name__, "expected": reason})
                invalid_references = [
                    _reference_issue(field, reference, record[id_field], records)
                    for field in REFERENCE_FIELDS
                    for reference in (record.get(field, []) if isinstance(record.get(field), list) else [])
                    if not _valid_reference(field, reference, record[id_field], records)
                ]
                targets.append({"collection": collection, "record_id": record[id_field], "fields": issues,
                                "field_diagnostics": diagnostics, "invalid_references": invalid_references,
                                "valid_obligation_ids": [identifier for identifier, obligation in obligations_by_id.items()
                                                         if obligation.get("target_id") == record[id_field]]})
    targets_by_key = {(item["collection"], item["record_id"]): item for item in targets}
    for collection in ("propositions", "lemmas"):
        for (record_collection, identifier), record in records.items():
            if record_collection != collection or not isinstance(record.get("required_obligation_ids"), list):
                continue
            for reference in record["required_obligation_ids"]:
                obligation = obligations_by_id.get(reference) if isinstance(reference, str) else None
                if obligation is None or obligation.get("target_id") == identifier:
                    continue
                key = ("proof_obligations", reference)
                target = targets_by_key.get(key)
                if target is None:
                    target = {"collection": key[0], "record_id": key[1], "fields": {}, "field_diagnostics": []}
                    targets.append(target)
                    targets_by_key[key] = target
                target["fields"]["target_id"] = "Association conflicts with a target's required_obligation_ids; repair the link or the association together."
                target["field_diagnostics"].append({"field": "target_id", "node_path": "$", "error_code": "obligation_target_mismatch",
                                                     "actual_type": type(obligation.get("target_id")).__name__,
                                                     "expected": target["fields"]["target_id"], "referenced_by": identifier})
    return targets


def _repair_batches(targets, plan, batch_size):
    records = _record_map(plan)
    pending = list(targets)
    components = []
    while pending:
        component = [pending.pop(0)]
        changed = True
        while changed:
            changed = False
            identifiers = {item["record_id"] for item in component}
            references = set()
            for item in component:
                record = records[(item["collection"], item["record_id"])]
                values = record.get("required_obligation_ids", [])
                if isinstance(values, list):
                    references.update(value for value in values if isinstance(value, str))
                if isinstance(record.get("target_id"), str):
                    references.add(record["target_id"])
            for item in list(pending):
                record = records[(item["collection"], item["record_id"])]
                obligations = record.get("required_obligation_ids", [])
                linked = (item["record_id"] in references
                          or isinstance(record.get("target_id"), str) and record["target_id"] in identifiers
                          or isinstance(obligations, list) and any(
                              isinstance(reference, str) and reference in identifiers for reference in obligations))
                if linked:
                    pending.remove(item)
                    component.append(item)
                    changed = True
        components.append(component)
    batches = []
    batch = []
    for component in components:
        if batch and len(batch) + len(component) > batch_size:
            batches.append(batch)
            batch = []
        batch.extend(component)
    if batch:
        batches.append(batch)
    return batches


def _repair_catalog(records, batch):
    identifiers = {item["record_id"] for item in batch}
    related = set(identifiers)
    for key, record in records.items():
        if key[1] in identifiers:
            for field in REFERENCE_FIELDS:
                values = record.get(field, [])
                if isinstance(values, list):
                    related.update(value for value in values if isinstance(value, str))
            if isinstance(record.get("target_id"), str):
                related.add(record["target_id"])
    return [{"collection": collection, "record_id": identifier,
             "statement": record.get("statement", record.get("target", "")),
             "premises": record.get("premises", []), "target_id": record.get("target_id"),
             "status": record.get("status"), "required_obligation_ids": record.get("required_obligation_ids", [])}
            for (collection, identifier), record in records.items()
            if identifier in related or collection == "proof_obligations" and isinstance(record.get("target_id"), str)
            and record["target_id"] in related]


def _normalize_skeleton_expressions(plan, *, logger, brief_id):
    for (collection, identifier), record in _record_map(plan).items():
        if collection not in ("assumptions", "propositions", "lemmas", "proof_obligations"):
            continue
        for field in EXPRESSION_FIELDS:
            if field not in record:
                continue
            original = record[field]
            normalized = normalize_expression(original)
            if normalized != original:
                archive_formal_record(plan, f"{collection}.{identifier}.{field}", original,
                                      "Original expression before numeric-leaf normalization.")
                record[field] = normalized
                if logger is not None:
                    logger.event("formal_reasoning_planner", "expression_shape_repaired", status="REPAIRED",
                                 brief_id=brief_id, record_id=identifier, fields=[field])


def _apply_skeleton_patches(plan, response, allowed, entry, *, logger, brief_id):
    records = _record_map(plan)
    proposals = {}
    for patch in response["patches"]:
        key = (patch.get("collection"), patch.get("record_id")) if isinstance(patch, Mapping) else (None, None)
        if not all(isinstance(item, str) for item in key) or key not in allowed or not isinstance(patch.get("fields"), Mapping):
            archive_formal_record(plan, "skeleton_repair.invalid_patch", patch, "Patch is outside requested records.")
            diagnostic = {"node_path": "$", "error_code": "invalid_patch_target",
                          "actual_type": type(patch).__name__, "expected": "A requested collection/record_id and fields object."}
            entry.setdefault("rejected_fields", []).append({"record_id": key[1], "field_diagnostics": [diagnostic]})
            if logger is not None:
                logger.event("formal_reasoning_planner", "skeleton_patch_warning", level="WARNING", status="WARNING",
                             brief_id=brief_id, record_id=key[1] if isinstance(key[1], str) else None,
                             fields=[], field_diagnostics=[diagnostic], disposition="ignored_invalid_patch", blocking=False)
            continue
        unrequested = [field for field in patch["fields"] if field not in allowed[key]]
        if unrequested:
            archive_formal_record(plan, f"skeleton_repair.{key[1]}", patch, "Accepted fields cannot be replaced.")
            diagnostics = [{"field": field, "node_path": f"$.fields.{field}", "error_code": "unrequested_patch_field",
                            "actual_type": type(patch["fields"][field]).__name__, "expected": "Only fields listed in repair_targets."}
                           for field in unrequested]
            entry.setdefault("rejected_fields", []).append({"record_id": key[1], "field_diagnostics": diagnostics})
            if logger is not None:
                logger.event("formal_reasoning_planner", "skeleton_patch_warning", level="WARNING", status="WARNING",
                             brief_id=brief_id, record_id=key[1], fields=unrequested, field_diagnostics=diagnostics,
                             disposition="kept_previous_fields", blocking=False)
        fields = proposals.setdefault(key, {})
        for field, value in patch["fields"].items():
            if field in allowed[key] and field not in fields:
                fields[field] = normalize_expression(deepcopy(value)) if field in EXPRESSION_FIELDS else deepcopy(value)
    rejected = {}
    while True:
        trial = deepcopy(plan)
        trial_records = _record_map(trial)
        for key, fields in proposals.items():
            trial_records[key].update(fields)
        issues = {(item["collection"], item["record_id"]): item for item in skeleton_repair_targets(trial)}
        newly_rejected = []
        for key, fields in proposals.items():
            remaining = issues.get(key, {})
            for field, value in fields.items():
                diagnostics = [item for item in remaining.get("field_diagnostics", []) if item["field"] == field]
                if field in remaining.get("fields", {}) and not diagnostics:
                    diagnostics = [{"field": field, "node_path": "$", "error_code": "invalid_record_field",
                                    "expected": remaining["fields"][field], "actual_type": type(value).__name__}]
                if field in REFERENCE_FIELDS and isinstance(records[key].get(field), list) and isinstance(value, list):
                    removed = [reference for reference in records[key][field] if reference not in value
                               and _valid_reference(field, reference, key[1], records)]
                    if removed:
                        diagnostics.append({"field": field, "node_path": "$", "error_code": "valid_reference_removed",
                                            "references": removed, "expected": "Retain valid dependencies and obligations."})
                if key[0] == "proof_obligations" and field == "target_id":
                    owners = [identifier for (collection, identifier), record in records.items()
                              if collection in ("propositions", "lemmas")
                              and isinstance(record.get("required_obligation_ids"), list)
                              and key[1] in record["required_obligation_ids"]
                              and _valid_reference("required_obligation_ids", key[1], identifier, records)]
                    if owners and value != records[key].get("target_id"):
                        diagnostics.append({"field": field, "node_path": "$", "error_code": "valid_obligation_association_changed",
                                            "references": owners, "expected": "Preserve the existing valid obligation ownership."})
                if diagnostics:
                    rejected.setdefault(key, []).extend(diagnostics)
                    newly_rejected.append((key, field))
        if not newly_rejected:
            break
        for key, field in newly_rejected:
            proposals[key].pop(field)
    for key, diagnostics in rejected.items():
        raw_patches = [patch for patch in response["patches"] if isinstance(patch, Mapping)
                       and (patch.get("collection"), patch.get("record_id")) == key]
        archive_formal_record(plan, f"skeleton_repair.{key[1]}", raw_patches,
                              "Invalid patch fields: " + "; ".join(item["error_code"] for item in diagnostics))
        entry.setdefault("rejected_fields", []).append({"record_id": key[1], "field_diagnostics": deepcopy(diagnostics)})
        if logger is not None:
            logger.event("formal_reasoning_planner", "skeleton_patch_warning", level="WARNING", status="WARNING",
                         brief_id=brief_id, record_id=key[1], fields=sorted({item["field"] for item in diagnostics}),
                         field_diagnostics=diagnostics, disposition="kept_previous_fields", blocking=False)
    for key, fields in proposals.items():
        record = records[key]
        fields = {field: value for field, value in fields.items() if field not in record or record[field] != value}
        if not fields:
            continue
        original = deepcopy(record)
        archive_formal_record(plan, f"skeleton_repair.{key[1]}", original, "Original draft before targeted field repair.")
        record.update(fields)
        if record.get("machine_encoding_issues"):
            record["machine_encoding_issues"] = [field for field in record["machine_encoding_issues"] if field not in fields]
            if not record["machine_encoding_issues"]:
                record.pop("machine_encoding_issues")
        record["candidate_completion_pending"] = False
        record["candidate_completion_fields"] = sorted(set([*record.get("candidate_completion_fields", []), *fields]))
        completions = []
        for field, value in fields.items():
            before = deepcopy(original.get(field))
            completion = {"collection": key[0], "record_id": key[1], "field": field,
                          "field_path": f"{key[0]}.{key[1]}.{field}", "original_present": field in original,
                          "original": before, "candidate": deepcopy(value), "before": before, "after": deepcopy(value),
                          "status": "unverified", "reason": "Accepted mathematical candidate; verification follows.",
                          "source": "skeleton_record_repair", "repair_round": entry["round"]}
            plan["candidate_completions"].append(completion)
            completions.append(completion)
        plan["unknown_items"][:] = [item for item in plan["unknown_items"] if not (
            isinstance(item, Mapping) and (item.get("diagnostic_origin") == "skeleton_record_repair"
                                          or item.get("category") == "record_encoding")
            and item.get("record_id") == key[1] and item.get("field") in fields
            and item.get("category") not in {"semantic_conflict", "needs_user_decision"})]
        unencoded = [field for field in fields if field in EXPRESSION_FIELDS and fields[field] is None]
        for field in unencoded:
            plan["unknown_items"].append({"record_id": key[1], "field": field,
                                          "field_path": f"{key[0]}.{key[1]}.{field}", "status": "encoding_pending",
                                          "reason": "Mathematical text retained; executable expression encoding is pending.",
                                          "category": "encoding_gap", "diagnostic_origin": "skeleton_record_repair"})
        entry["updated_fields"].append({"record_id": key[1], "fields": sorted(fields), "candidate_review_required": False})
        entry.setdefault("candidate_completions", []).extend(deepcopy(completions))
        entry["status"] = "REPAIRED"
        if logger is not None:
            logger.event("formal_reasoning_planner", "skeleton_candidate_completion", status="REPAIRED",
                         brief_id=brief_id, record_id=key[1], fields=sorted(fields), disposition="adopted", blocking=False)
            if unencoded:
                logger.event("formal_reasoning_planner", "skeleton_encoding_pending", status="ENCODING_PENDING",
                             brief_id=brief_id, record_id=key[1], fields=unencoded, disposition="kept_mathematical_draft", blocking=False)


def repair_skeleton_records(plan, context, *, settings, repair_prompt, llm_call, logger=None, brief_id=""):
    rounds = max(0, min(2, int(settings.get("max_skeleton_repairs", 1))))
    batch_size = max(1, min(8, int(settings.get("max_records_per_skeleton_repair", 4))))
    audit = plan.setdefault("skeleton_repair_audit", [])
    candidate_completions = plan.setdefault("candidate_completions", [])
    if not isinstance(candidate_completions, list):
        archive_formal_record(plan, "candidate_completions", candidate_completions, "Malformed candidate completion audit.")
        candidate_completions = plan["candidate_completions"] = []
    unknown_items = plan.setdefault("unknown_items", [])
    if not isinstance(unknown_items, list):
        archive_formal_record(plan, "unknown_items", unknown_items, "Malformed unknown-item collection.")
        unknown_items = plan["unknown_items"] = []
    if not isinstance(audit, list):
        archive_formal_record(plan, "skeleton_repair_audit", audit, "Malformed repair audit.")
        audit = plan["skeleton_repair_audit"] = []
    _normalize_skeleton_expressions(plan, logger=logger, brief_id=brief_id)
    for repair_round in range(1, rounds + 1):
        targets = skeleton_repair_targets(plan)
        if not targets:
            break
        progress = False
        for batch_number, batch in enumerate(_repair_batches(targets, plan, batch_size), 1):
            allowed = {(item["collection"], item["record_id"]): item["fields"] for item in batch}
            records = _record_map(plan)
            request = {**context, "output_contract": skeleton_output_contract(), "repair_targets": batch,
                       "records": [deepcopy(records[key]) for key in allowed],
                       "record_catalog": _repair_catalog(records, batch),
                       "atomic_association_repair": True}
            entry = {"round": repair_round, "record_ids": [item["record_id"] for item in batch], "updated_fields": [], "status": "NO_PROGRESS"}
            try:
                prompt = repair_prompt + json_prompt_payload(request)
                if logger is not None:
                    logger.event("formal_reasoning_planner", "input_profiled", status="PROFILED", brief_id=brief_id,
                                 phase="skeleton_repair", repair_round=repair_round, batch_number=batch_number,
                                 record_count=len(batch), catalog_count=len(request["record_catalog"]), prompt_chars=len(prompt))
                response = call_required_json_with_logging(llm_call, prompt,
                    stage="formal_reasoning_planner", request_kind=f"v2_skeleton_repair_round_{repair_round}_batch_{batch_number}",
                    logger=logger, brief_id=brief_id)
                if not isinstance(response, Mapping) or response.get("schema_version") != "skeleton_record_patch_v1" or not isinstance(response.get("patches"), list):
                    raise ValueError("invalid_skeleton_record_patch")
                _apply_skeleton_patches(plan, response, allowed, entry, logger=logger, brief_id=brief_id)
                progress = progress or bool(entry["updated_fields"])
                for item in response.get("unknown_items", []) if isinstance(response.get("unknown_items"), list) else []:
                    if isinstance(item, Mapping) and isinstance(item.get("record_id"), str) and item["record_id"] in entry["record_ids"]:
                        key = next(key for key in allowed if key[1] == item["record_id"])
                        if not isinstance(item.get("field"), str) or item["field"] not in allowed[key]:
                            continue
                        value = records[key].get(item["field"])
                        remaining = next((target["fields"] for target in skeleton_repair_targets(plan)
                                          if (target["collection"], target["record_id"]) == key), {})
                        explicit_review = item.get("category") in {"semantic_conflict", "needs_user_decision"} and bool(item.get("reason"))
                        if item["field"] not in remaining and value not in (None, "", []) and not explicit_review:
                            continue
                        encoding_gap = item["field"] in EXPRESSION_FIELDS and value is None and not explicit_review
                        diagnostic = dict(item, field_path=f"construction_records.{item['record_id']}.{item.get('field', 'content')}",
                                          status="needs_human_input" if explicit_review else "encoding_pending" if encoding_gap else "unresolved",
                                          category=item["category"] if explicit_review else "encoding_gap" if encoding_gap else "construction_warning",
                                          diagnostic_origin="skeleton_record_repair")
                        entry.setdefault("diagnostics", []).append(deepcopy(diagnostic))
                        if diagnostic not in unknown_items:
                            unknown_items.append(diagnostic)
                        if explicit_review:
                            plan["status"] = "requires_human_review"
                            if logger is not None:
                                logger.event("formal_reasoning_planner", "skeleton_semantic_warning", level="WARNING",
                                             status="REVIEW_REQUIRED", brief_id=brief_id, record_id=item["record_id"],
                                             field=item["field"], error_detail=item["reason"], blocking=False)
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
