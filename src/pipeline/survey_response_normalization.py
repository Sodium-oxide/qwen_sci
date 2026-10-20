"""Recover model response structures without inventing scientific judgments."""

from collections import Counter
from collections.abc import Mapping
import json
import math
import re

from .paper_identity import canonical_paper_id


GRAPH_ROLES = {"evidence_seed", "exploration_seed", "context_seed", "do_not_expand", "undetermined"}
PAPER_ID_FIELDS = ("paper_id", "paperId", "openalex_id", "id")
PAPER_ASSESSMENT_FIELDS = {"project_score", "project_relevance_score", "project_reason", "sh_assessments", "scientific_objects"}
PAPER_WRAPPERS = ("papers", "paper_assessments", "assessments", "results", "data", "result", "response", "output")

SCORE_ALIASES = {
    "project_score": ("project_relevance_score", "relevance_score"),
    "semantic_relevance_score": ("sh_score", "semantic_score", "relevance_score"),
    "sh_score": ("semantic_relevance_score", "sh_relevance_score"),
}


def score_fields_raw(record, field):
    return {key: record[key] for key in (field, *SCORE_ALIASES.get(field, ())) if key in record}


def _score_value(value):
    if isinstance(value, Mapping):
        if len(value) != 1 or next(iter(value)) not in {"score", "value"}:
            return None
        value = next(iter(value.values()))
    if isinstance(value, str):
        match = re.fullmatch(r"\s*([0-5](?:\.0+)?)\s*(?:/\s*5)?\s*", value)
        if not match:
            return None
        value = float(match.group(1))
    if type(value) is int:
        return value if 0 <= value <= 5 else None
    if type(value) is float and math.isfinite(value) and value.is_integer() and 0 <= value <= 5:
        return int(value)
    return None


def score_field(record, field, diagnostics):
    values = score_fields_raw(record, field)
    if not values:
        return None
    scores = [_score_value(value) for value in values.values()]
    if any(value is None for value in scores) or len(set(scores)) != 1:
        return None
    if field not in values:
        diagnostics.recovered(field, "score_field_alias")
    if any(type(value) is not int for value in values.values()):
        diagnostics.recovered(field, "explicit_score_to_integer")
    return scores[0]


def graph_role_fields(value, diagnostics=None, **context):
    normalized = value.strip().casefold().replace("-", "_").replace(" ", "_") if isinstance(value, str) else ""
    aliases = {"evidence": "evidence_seed", "exploration": "exploration_seed", "context": "context_seed",
        "no_expansion": "do_not_expand", "unknown": "undetermined"}
    role = aliases.get(normalized, normalized)
    valid = role in GRAPH_ROLES
    if diagnostics is not None:
        if not valid:
            diagnostics.unresolved("recommended_graph_role", "missing_or_unknown_graph_role", value, **context)
        elif role != value:
            diagnostics.recovered("recommended_graph_role", "normalize_graph_role")
    return {"recommended_graph_role": role if valid else "undetermined", "recommended_graph_role_raw": value,
        "graph_role_assessment_status": "assessed" if valid and role != "undetermined" else "undetermined"}


class FormatBatch:
    def __init__(self, stage, batch_id, **context):
        self.stage, self.batch_id = stage, batch_id
        self.context = context
        self.recoveries = Counter()
        self.issues = []
        self.suppressed_issues = []
        self.suppress_derived = False
        self.root_causes = {}
        self.response_audit = {}

    def recovered(self, field, action):
        self.recoveries[f"{field}:{action}"] += 1

    def unresolved(self, field, reason, raw=None, **context):
        details = {**self.context, **context, "field": field, "reason": reason, "raw": raw}
        if context.get("paper_id"):
            details.pop("paper_ids", None)
        paper_id = canonical_paper_id(context.get("paper_id"))
        root = self.root_causes.get((paper_id, None)) or self.root_causes.get((paper_id, context.get("sub_hypothesis_id")))
        if (self.suppress_derived and field != "response") or root is not None:
            root = root or next((issue for issue in self.issues if issue["field"] == "response"),
                {"field": "response", "reason": "response_unavailable"})
            details["derived_from"] = {key: root[key] for key in ("field", "reason", "paper_id", "sub_hypothesis_id") if key in root}
            self.suppressed_issues.append(details)
        else:
            self.issues.append(details)
        return details

    def root_cause(self, field, reason, raw=None, *, dependent_scopes=None, derived_issues=(), **context):
        """Report a cause once and retain its dependent failures only in the audit."""
        root = self.unresolved(field, reason, raw, **context)
        scopes = [context] if dependent_scopes is None else dependent_scopes
        for scope in scopes:
            if scope.get("paper_id"):
                self.root_causes[(canonical_paper_id(scope["paper_id"]), scope.get("sub_hypothesis_id"))] = root
        for issue in derived_issues:
            if any(issue is visible for visible in self.issues):
                self.issues = [visible for visible in self.issues if visible is not issue]
                issue["derived_from"] = {key: root[key] for key in ("field", "reason", "paper_id", "sub_hypothesis_id") if key in root}
                self.suppressed_issues.append(issue)
        return root

    def publish(self, logger):
        if self.recoveries:
            logger.info("Survey format recovery: stage=%s batch=%s recovered=%s actions=%s.",
                self.stage, self.batch_id, sum(self.recoveries.values()),
                json.dumps(dict(self.recoveries), ensure_ascii=False))
        if self.issues:
            samples = [{key: value for key, value in issue.items() if key != "raw"} for issue in self.issues[:8]]
            logger.warning("Survey format warning: stage=%s batch=%s unresolved=%s details=%s omitted_details=%s; full details saved in format_normalization_audit.",
                self.stage, self.batch_id, len(self.issues),
                json.dumps(samples, ensure_ascii=False), max(0, len(self.issues) - 8))
        if self.suppressed_issues:
            logger.info("Survey format aggregation: stage=%s batch=%s suppressed_derived=%s; full details saved in format_normalization_audit.",
                self.stage, self.batch_id, len(self.suppressed_issues))
        return {"stage": self.stage, "batch_id": self.batch_id,
                **self.context, "recoveries": dict(self.recoveries),
                "issues": [*self.issues, *self.suppressed_issues],
                "visible_issues": self.issues, "suppressed_issues": self.suppressed_issues}


def normalize_model_response(value, *, collection_field, diagnostics):
    """Normalize one model response while preserving an upstream failure boundary."""
    if collection_field == "papers":
        collections = _paper_collections(value)
        diagnostics.response_audit = {"parsed_response": value,
            "collection_paths": [path for path, _records in collections],
            "status": "normalized" if collections else "unavailable"}
        if collections:
            if len(collections) == 1 and collections[0][0] == "$.papers":
                return value
            action = ("paper_records_array_to_object" if isinstance(value, list)
                else "paper_record_object_to_collection" if _is_paper_record(value)
                else "paper_assessment_wrapper_to_object")
            diagnostics.recovered("response", action)
            if len(collections) == 1:
                return {"papers": collections[0][1]}
            records = [record for _path, content in collections
                for record in record_list(content, "papers", diagnostics)]
            return {"papers": records}
        diagnostics.unresolved("response", "assessment_records_unavailable" if isinstance(value, Mapping)
            else "expected_response_object", value)
        return {"_survey_response_unavailable": True}
    if isinstance(value, Mapping):
        return value
    diagnostics.unresolved("response", "expected_response_object", value)
    return {"_survey_response_unavailable": True}


def _is_paper_record(value):
    return isinstance(value, Mapping) and bool(set(value) & (set(PAPER_ID_FIELDS) | PAPER_ASSESSMENT_FIELDS))


def _is_keyed_papers(value):
    return (isinstance(value, Mapping) and bool(value) and not _is_paper_record(value)
        and any(_is_paper_record(item) or re.fullmatch(r"W\d+", canonical_paper_id(key))
            for key, item in value.items()))


def _paper_collections(value, path="$", depth=0):
    """Recognize explicit paper envelopes, without searching arbitrary JSON children."""
    if depth > 4:
        return []
    if isinstance(value, list):
        return [(path, value)] if not value or any(_is_paper_record(item) for item in value) else []
    if not isinstance(value, Mapping):
        return []
    nested_assessment = any(isinstance(value.get(key), Mapping) and PAPER_ASSESSMENT_FIELDS.intersection(value[key])
        for key in ("assessment", "evaluation", "result"))
    if PAPER_ASSESSMENT_FIELDS.intersection(value) or (_is_paper_record(value) and nested_assessment):
        return [(path, value)]
    collections = [collection for key in PAPER_WRAPPERS if key in value
        for collection in _paper_collections(value[key], f"{path}.{key}", depth + 1)]
    return collections or ([(path, value)] if _is_paper_record(value) or _is_keyed_papers(value) else [])


def record_list(value, field, diagnostics, *, record_audit=None, **context):
    if value is None:
        diagnostics.recovered(field, "null_to_empty")
        return []
    if isinstance(value, Mapping):
        identity_fields = {"papers": "paper_id", "sh_assessments": "sub_hypothesis_id",
            "candidates": "candidate_id", "assessments": "sub_hypothesis_id"}
        identity = identity_fields.get(field)
        keyed = (_is_keyed_papers(value) if field == "papers" else identity and identity not in value
            and value and all(isinstance(item, Mapping) for item in value.values()))
        if keyed:
            diagnostics.recovered(field, "keyed_objects_to_records")
            records = []
            for index, (identifier, item) in enumerate(value.items()):
                item_context = {**context, "paper_id": identifier} if field == "papers" else context
                entry = {"record_index": index, "keyed_paper_id": identifier, "raw_record": item, "status": "accepted"}
                if record_audit is not None:
                    record_audit.append(entry)
                if not isinstance(item, Mapping):
                    entry["status"] = "expected_record_object"
                    diagnostics.unresolved(field, "expected_record_object", item, **item_context)
                    continue
                identities = [item[key] for key in PAPER_ID_FIELDS if isinstance(item.get(key), str) and item[key].strip()] if field == "papers" else [item.get(identity, identifier)]
                if any((canonical_paper_id(raw) != canonical_paper_id(identifier) if field == "papers"
                        else raw != identifier) for raw in identities):
                    entry["status"] = "conflicting_identity"
                    diagnostics.unresolved(field, "conflicting_identity", item, **item_context)
                    continue
                records.append({**item, identity: item.get(identity) or identifier})
            return records
        if field == "evidence_spans" and "source" not in value:
            diagnostics.recovered(field, "sources_to_records")
            value = [{"source": source, "text": summary} for source, summary in value.items()]
        else:
            diagnostics.recovered(field, "object_to_list")
            value = [value]
    if not isinstance(value, list):
        diagnostics.unresolved(field, "expected_record_list", value, **context)
        return []
    records = []
    for index, item in enumerate(value):
        entry = {"record_index": index, "raw_record": item,
            "status": "accepted" if isinstance(item, Mapping) else "expected_record_object"}
        if record_audit is not None:
            record_audit.append(entry)
        if isinstance(item, Mapping):
            records.append(dict(item))
        else:
            diagnostics.unresolved(field, "expected_record_object", item, record_index=index, **context)
    return records


def align_paper_assessments(expected_ids, value, diagnostics):
    """Match only explicit, equivalent IDs; never guess from order or titles."""
    issue_start = len(diagnostics.issues)
    sources = []
    records = record_list(value, "papers", diagnostics, record_audit=sources)
    expected = {canonical_paper_id(identifier) for identifier in expected_ids}
    returned = []
    for entry in sources:
        if entry["status"] == "accepted":
            continue
        raw_ids = {key: entry["raw_record"][key] for key in PAPER_ID_FIELDS
            if isinstance(entry.get("raw_record"), Mapping) and key in entry["raw_record"]}
        identities = {canonical_paper_id(item) for item in [entry.get("keyed_paper_id"), *raw_ids.values()]
            if isinstance(item, str) and item.strip()}
        returned.append({**entry, "identity_fields_raw": raw_ids,
            "canonical_paper_id": canonical_paper_id(entry.get("keyed_paper_id")),
            "canonical_identity_options": sorted(identities)})
    groups = {}
    for source, source_entry in zip(records, (entry for entry in sources if entry["status"] == "accepted")):
        record = dict(source)
        failure = None
        if not PAPER_ASSESSMENT_FIELDS.intersection(record):
            wrappers = [key for key in ("assessment", "evaluation", "result")
                if isinstance(record.get(key), Mapping) and PAPER_ASSESSMENT_FIELDS.intersection(record[key])]
            if len(wrappers) == 1:
                wrapper = wrappers[0]
                identities = [canonical_paper_id(part[key]) for part in (record, record[wrapper])
                    for key in PAPER_ID_FIELDS if isinstance(part.get(key), str) and part[key].strip()]
                if len(set(identities)) > 1:
                    failure = "conflicting_paper_id_fields"
                else:
                    record = {**{key: item for key, item in record.items() if key != wrapper}, **record[wrapper]}
                    diagnostics.recovered("papers", "nested_assessment_to_record")
            elif wrappers:
                failure = "ambiguous_assessment_wrappers"
        raw_ids = {key: record[key] for key in PAPER_ID_FIELDS if key in record}
        identities = {canonical_paper_id(item) for item in raw_ids.values() if isinstance(item, str) and item.strip()}
        identity_options = set(identities)
        if failure == "conflicting_paper_id_fields":
            identity_options.update(canonical_paper_id(record[wrapper][key]) for key in PAPER_ID_FIELDS
                if isinstance(record[wrapper].get(key), str) and record[wrapper][key].strip())
        identifier = next(iter(identities)) if len(identities) == 1 else ""
        failure = failure or ("conflicting_paper_id_fields" if len(identities) > 1 else "missing_paper_id" if not identifier else None)
        entry = {**{key: item for key, item in source_entry.items() if key != "raw_record"}, "identity_fields_raw": raw_ids,
            "canonical_paper_id": identifier, "canonical_identity_options": sorted(identity_options),
            "status": failure or ("matched" if identifier in expected else "unexpected_paper_id")}
        returned.append(entry)
        if failure or identifier not in expected:
            continue
        if "paper_id" not in raw_ids or not isinstance(raw_ids["paper_id"], str) or not raw_ids["paper_id"].strip():
            diagnostics.recovered("paper_id", "identity_field_alias")
        groups.setdefault(identifier, []).append((record, entry))
    aligned = {}
    for identifier, matches in groups.items():
        judgments = {json.dumps({key: item for key, item in record.items() if key not in PAPER_ID_FIELDS},
            sort_keys=True, ensure_ascii=False) for record, _entry in matches}
        if len(judgments) > 1:
            for _record, entry in matches:
                entry["status"] = "conflicting_assessments"
            continue
        aligned[identifier] = matches[0][0]
        if len(matches) > 1:
            diagnostics.recovered("papers", "identical_assessments_collapsed")
            for _record, entry in matches[1:]:
                entry["status"] = "duplicate_identical"
    returned.sort(key=lambda entry: entry["record_index"])
    expected_records = []
    for index, raw_id in enumerate(expected_ids):
        identifier = canonical_paper_id(raw_id)
        related = [entry for entry in returned if identifier in entry["canonical_identity_options"]]
        indices = [entry["record_index"] for entry in related]
        status = ("matched" if identifier in aligned else "conflicting_assessments" if identifier in groups
            else "conflicting_identity" if any(entry["status"] in {"conflicting_identity", "conflicting_paper_id_fields"} for entry in related)
            else "missing_assessment")
        expected_records.append({"expected_index": index, "paper_id": raw_id,
            "canonical_paper_id": identifier, "returned_record_indices": indices, "status": status})
        if status == "matched" and groups[identifier][0][0].get("paper_id") != raw_id:
            diagnostics.recovered("paper_id", "canonical_identity_match")
    failed = [entry for entry in expected_records if entry["status"] != "matched"]
    unexpected = [entry for entry in returned if entry["status"] not in {"matched", "duplicate_identical"}]
    prior_issues = diagnostics.issues[issue_start:]
    audit = {"expected_records": expected_records, "returned_records": returned,
        "missing_paper_ids": [entry["paper_id"] for entry in failed if entry["status"] == "missing_assessment"],
        "conflicting_paper_ids": [entry["paper_id"] for entry in failed if entry["status"] in {"conflicting_assessments", "conflicting_identity"}],
        "unexpected_paper_ids": [entry["identity_fields_raw"] for entry in unexpected if entry["status"] == "unexpected_paper_id"]}
    if failed or unexpected or prior_issues:
        diagnostics.root_cause("papers", "assessment_alignment_incomplete", unexpected,
            dependent_scopes=[{"paper_id": entry["paper_id"]} for entry in failed], derived_issues=prior_issues,
            missing_paper_ids=audit["missing_paper_ids"], conflicting_paper_ids=audit["conflicting_paper_ids"],
            unexpected_paper_ids=audit["unexpected_paper_ids"], unmatched_records=len(unexpected))
        for entry in failed:
            diagnostics.unresolved("papers", entry["status"], paper_id=entry["paper_id"],
                returned_record_indices=entry["returned_record_indices"])
    return aligned, audit


def source_summaries(value, paper, diagnostics, **context):
    from .source_context import source_texts
    sources = source_texts(paper)
    summaries = record_list(value, "evidence_spans", diagnostics, **context)
    valid = []
    for summary in summaries:
        source, content = summary.get("source"), summary.get("text")
        if not isinstance(source, str) or source not in {"title", "abstract", "source_excerpt"}:
            diagnostics.unresolved("evidence_spans.source", "unknown_source_field", summary, **context)
        elif not isinstance(content, str) or not content.strip():
            diagnostics.unresolved("evidence_spans.text", "missing_source_summary", summary, **context)
        elif not sources.get(source):
            diagnostics.unresolved("evidence_spans.source", "source_content_unavailable", summary, **context)
        else:
            valid.append(summary)
    return valid


def slot_contributions(value, allowed_slots, diagnostics, **context):
    field = "candidate_slot_contributions"
    unresolved = []
    if value is None:
        diagnostics.recovered(field, "null_to_empty")
        return [], []
    if isinstance(value, Mapping):
        if "slot_name" in value or "slot" in value:
            diagnostics.recovered(field, "object_to_list")
            value = [value]
        else:
            diagnostics.recovered(field, "slots_to_records")
            records = []
            for slot, details in value.items():
                if isinstance(details, Mapping):
                    if details.get("slot_name", details.get("slot", slot)) != slot:
                        diagnostics.unresolved(field, "conflicting_slot_identity", details, slot_name=slot, **context)
                        unresolved.append({slot: details})
                        continue
                    records.append({**details, "slot_name": slot})
                else:
                    records.append({"slot_name": slot, "support_level": details})
            value = records
    if not isinstance(value, list):
        diagnostics.unresolved(field, "expected_slot_records", value, **context)
        return [], [value]
    valid = []
    for raw in value:
        if isinstance(raw, str):
            slot, separator, level = raw.rpartition(":")
            item = {"slot_name": slot.strip() if separator else raw.strip(),
                    "support_level": level.strip() if separator else None}
        elif isinstance(raw, Mapping):
            item = dict(raw)
        else:
            diagnostics.unresolved(field, "expected_slot_record", raw, **context)
            unresolved.append(raw)
            continue
        slot = item.get("slot_name", item.get("slot"))
        level = item.get("support_level", item.get("level"))
        reason = item.get("reason", item.get("explanation", ""))
        if "slot" in item or "level" in item or "explanation" in item:
            diagnostics.recovered(field, "field_aliases")
        if isinstance(level, str):
            normalized = level.strip().casefold()
            if normalized != level:
                diagnostics.recovered(field, "support_level_case")
            level = normalized
        missing = []
        if not isinstance(slot, str) or slot not in allowed_slots:
            missing.append("unknown_or_missing_slot_name")
        if not isinstance(level, str) or level not in {"direct", "partial", "indirect", "none"}:
            missing.append("unknown_or_missing_support_level")
        if not isinstance(reason, str):
            missing.append("invalid_reason")
        if missing:
            diagnostics.unresolved(field, ",".join(missing), raw, **context)
            unresolved.append(raw)
        else:
            if isinstance(raw, str):
                diagnostics.recovered(field, "string_to_slot_fields")
            valid.append({"slot_name": slot, "support_level": level, "reason": reason})
    return valid, unresolved
