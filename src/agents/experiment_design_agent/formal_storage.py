"""Shared verification data and lossless, separately stored audit payloads."""

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
from pathlib import Path


REPORT_VERSION = "formal_verification_report_v2"
SUMMARY_VERSION = "formal_verification_summary_v1"
TABLES = ("snapshots", "records", "diagnostics")
RAW_FIELDS = frozenset({"raw_json", "raw_excerpt", "raw_patch_json", "construction_archive"})


def content_id(value):
    digest = hashlib.sha256()
    for chunk in json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).iterencode(value):
        digest.update(chunk.encode("utf-8"))
    return digest.hexdigest()


def semantic_content(value):
    if isinstance(value, Mapping):
        return {key: semantic_content(item) for key, item in value.items()
                if key not in RAW_FIELDS and key not in {"audit_refs", "raw_excerpt_truncated"}}
    if isinstance(value, list):
        return [semantic_content(item) for item in value]
    return value


def diagnostic_applies(item, identifiers, known_ids):
    if item.get("scope") == "global" or item.get("is_global") is True:
        return True
    owners = {item[key] for key in ("record_id", "target_id") if isinstance(item.get(key), str)}
    for field in ("needed_for", "target_ids", "affected_ids"):
        if isinstance(item.get(field), list):
            owners.update(value for value in item[field] if isinstance(value, str))
    if owners:
        return bool(owners & identifiers)
    path = str(item.get("field_path") or item.get("path") or "")
    owners.update(part for part in path.split(".") if part in known_ids)
    parts = path.split(".")
    if len(parts) > 1 and parts[0] in {"variables", "definitions", "propositions", "lemmas", "proof_obligations", "model_relations", "assumptions"}:
        owners.add(parts[1])
    return bool(owners & identifiers)


def normalize_snapshot(snapshot):
    cleaned = semantic_content(snapshot)
    identifiers = {key for key in cleaned if not key.startswith("$")}
    identifiers.update(reference for record in cleaned.values() if isinstance(record, Mapping)
                       for reference in record.get("variable_references", []) if isinstance(reference, str))
    parent = cleaned.get("$parent", {})
    identifiers.update(parent[key] for key in ("proposition_id", "lemma_id") if isinstance(parent.get(key), str))
    known_ids = identifiers | set(cleaned.get("$definition_bindings", {}).values())
    for field in ("$unknown_items", "$diagnostics"):
        cleaned[field] = [item for item in cleaned.get(field, []) if diagnostic_applies(item, identifiers, known_ids)]
    return cleaned


def execution_snapshot(snapshot):
    return {key: value for key, value in normalize_snapshot(snapshot).items()
            if key not in {"$unknown_items", "$diagnostics"}}


class VerificationStore:
    def __init__(self, tables=None):
        self.tables = {name: dict((tables or {}).get(name, {})) for name in TABLES}
        self._keys = {name: {json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False): identifier
                            for identifier, value in self.tables[name].items()} for name in TABLES}

    def intern(self, table, value):
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        identifier = self._keys[table].get(encoded)
        if identifier is None:
            identifier = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            self._keys[table][encoded] = identifier
            self.tables[table].setdefault(identifier, deepcopy(value))
        return identifier

    def snapshot(self, value):
        snapshot = normalize_snapshot(value)
        record_refs = {key: self.intern("records", record) for key, record in snapshot.items()
                       if not key.startswith("$") or key in {"$parent", "$backend_encoding"}}
        diagnostic_refs = {key: [self.intern("diagnostics", item) for item in snapshot.get(key, [])]
                           for key in ("$unknown_items", "$diagnostics")}
        shared = {"record_refs": record_refs, "diagnostic_refs": diagnostic_refs,
                  "definition_bindings_ref": self.intern("records", snapshot.get("$definition_bindings", {}))}
        return self.intern("snapshots", shared)


def expand_report(report):
    if report.get("schema_version") == "formal_verification_report_v1":
        return {**report, "results": [{**result, "input_snapshot": normalize_snapshot(result["input_snapshot"])}
                                      for result in report.get("results", [])]}
    if report.get("schema_version") != REPORT_VERSION:
        raise ValueError("invalid_formal_verification_report")
    expanded = []
    try:
        for result in report["results"]:
            shared = report["snapshots"][result["snapshot_ref"]]
            snapshot = {key: report["records"][reference] for key, reference in shared["record_refs"].items()}
            snapshot.update({key: [report["diagnostics"][reference] for reference in references]
                             for key, references in shared["diagnostic_refs"].items()})
            snapshot["$definition_bindings"] = report["records"][shared["definition_bindings_ref"]]
            expanded.append({**result, "input_snapshot": snapshot})
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"verification_reference_missing_or_invalid: {error}") from error
    return {**report, "results": expanded}


def compact_report(report, store=None):
    if not report:
        return report
    store = store if store is not None else VerificationStore()
    expanded = expand_report(report) if report.get("schema_version") == REPORT_VERSION else report
    results = []
    for result in expanded["results"]:
        packed = {key: deepcopy(value) for key, value in result.items() if key not in {"input_snapshot", "snapshot_ref"}}
        packed["snapshot_ref"] = store.snapshot(result["input_snapshot"])
        results.append(packed)
    return {**{key: deepcopy(value) for key, value in report.items() if key not in {*TABLES, "results"}},
            "schema_version": REPORT_VERSION, "snapshot_semantics": report.get("snapshot_semantics", "legacy_v1"),
            "results": results, **store.tables}


def report_summary(report):
    excluded = {"input_snapshot", "snapshot_ref", "constraints", "conclusion_expression", "quantifiers",
                "candidate_points", "candidate_ids", "certificate_source", "proof_script", "lean_imports"}
    return {"schema_version": SUMMARY_VERSION,
            **{key: deepcopy(report.get(key, {} if key != "target_summaries" else []))
               for key in ("policy", "target_summaries", "task_summary")},
            "results": [{key: deepcopy(value) for key, value in result.items() if key not in excluded}
                        for result in report.get("results", [])]}


def archive_report(archive, report):
    store = VerificationStore(archive)
    cleaned = externalize_raw(report, archive)
    ledger_refs = []
    if report.get("schema_version") == "formal_verification_report_v1":
        for result in cleaned.get("results", []):
            snapshot = result.get("input_snapshot", {})
            ledger = {field: [store.intern("diagnostics", semantic_content(item)) for item in snapshot.get(field, [])]
                      for field in ("$unknown_items", "$diagnostics")}
            identifier = content_id(ledger)
            archive.setdefault("diagnostic_ledgers", {}).setdefault(identifier, ledger)
            if identifier not in ledger_refs:
                ledger_refs.append(identifier)
    packed = compact_report(cleaned, store)
    header = {key: value for key, value in packed.items() if key not in TABLES}
    if ledger_refs:
        header["original_diagnostic_ledger_refs"] = ledger_refs
    identifier = content_id(header)
    archive.setdefault("reports", {}).setdefault(identifier, header)
    archive.update(store.tables)
    return identifier


def archived_report(archive, identifier):
    try:
        return {**archive["reports"][identifier], **{table: archive[table] for table in TABLES}}
    except (KeyError, TypeError) as error:
        raise ValueError(f"verification_report_reference_missing: {identifier}") from error


def externalize_raw(value, archive):
    if isinstance(value, Mapping):
        cleaned = {}
        references = dict(value.get("audit_refs", {}))
        for key, item in value.items():
            if key in RAW_FIELDS:
                identifier = content_id(item)
                archive.setdefault("raw_payloads", {}).setdefault(identifier, deepcopy(item))
                references[key] = identifier
            elif key != "audit_refs":
                cleaned[key] = externalize_raw(item, archive)
        if references:
            cleaned["audit_refs"] = references
            links = archive.setdefault("raw_links", {}).setdefault(content_id(semantic_content(cleaned)), {})
            for field, reference in references.items():
                if reference not in links.setdefault(field, []):
                    links[field].append(reference)
        return cleaned
    if isinstance(value, list):
        return [externalize_raw(item, archive) for item in value]
    return value


def compact_revision_audit(audit, archive):
    for table in (*TABLES, "reports", "raw_payloads", "raw_links", "diagnostic_ledgers"):
        archive.setdefault(table, {}).update(audit.get(table, {}))
    iterations = []
    for original in audit.get("iterations", []):
        entry = {key: value for key, value in original.items() if key != "previous_verification_report"}
        if "previous_verification_report" in original:
            entry["previous_report_ref"] = archive_report(archive, original["previous_verification_report"])
        iterations.append(externalize_raw(entry, archive))
    return {"schema_version": "formal_revision_audit_v2", "iterations": iterations, "budget": audit.get("budget", 0)}


def revision_summary(audit):
    if audit.get("schema_version") == "formal_revision_summary_v1":
        return deepcopy(audit)
    return {"schema_version": "formal_revision_summary_v1", "budget": audit.get("budget", 0),
            "iterations": [{key: deepcopy(value) for key, value in item.items()
                            if key not in {"changes", "rejected_operations", "raw_patch_json", "audit_refs"}}
                           | {"changed_record_ids": [change["record_id"] for change in item.get("changes", [])],
                              "rejected_operation_count": len(item.get("rejected_operations", []))}
                           for item in audit.get("iterations", [])]}


def resolve_archive_reference(reference, *, base_dir=None):
    try:
        path = Path(reference["path"])
        if base_dir is not None:
            root = Path(base_dir).resolve()
            path = (root / path).resolve()
            path.relative_to(root)
        elif not path.is_absolute():
            raise ValueError("verification_archive_requires_base_directory")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
            raise ValueError("verification_archive_fingerprint_mismatch")
        return json.loads(raw)
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"verification_archive_unavailable: {error}") from error


def resolve_report_reference(summary, *, base_dir=None):
    if summary.get("schema_version") != SUMMARY_VERSION:
        return summary
    reference = summary.get("archive_ref", {})
    archive = resolve_archive_reference(reference, base_dir=base_dir)
    report = archived_report(archive, reference.get("report_id"))
    if report_summary(report) != {key: value for key, value in summary.items() if key != "archive_ref"}:
        raise ValueError("verification_summary_mismatch")
    return report
