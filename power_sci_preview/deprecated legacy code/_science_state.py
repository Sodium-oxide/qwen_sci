"""Single-writer science-project state semantics over the JSON store.

The JSON file remains the persistence format, but agents interact with one
versioned scientific world through :class:`ScienceStateManager`.  The manager
binds a loaded object to one canonical store, performs optimistic version
checks, versions major artifact families, and stamps gap foreign keys with
project/snapshot context.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Any, Callable
import copy
import json
import os
import re
import shutil
import time
import traceback
import uuid

try:
    from ._project_compaction import compact_project_for_persistence
    from ._fulltext_cache import (
        externalize_paper_fulltext,
        externalize_project_fulltexts,
        hydrate_paper_fulltext,
        hydrate_project_fulltexts,
    )
except ImportError:
    from _project_compaction import compact_project_for_persistence
    from _fulltext_cache import (
        externalize_paper_fulltext,
        externalize_project_fulltexts,
        hydrate_paper_fulltext,
        hydrate_project_fulltexts,
    )


class ScienceStateError(RuntimeError):
    pass


class ScienceStateStoreMismatch(ScienceStateError):
    pass


class StaleScienceStateError(ScienceStateError):
    pass


ARTIFACT_GROUPS: dict[str, tuple[str, ...]] = {
    "papers": ("papergraph", "evidence", "causal_evidence_graph"),
    "gaps": (
        "knowledge_gaps", "tanxi_gap_analysis", "socrates_mechanism_contracts", "socrates_reports",
        "research_evidence_graphs", "active_research_evidence_graph_ref",
        "research_task_graphs", "active_research_task_graph_ref",
        "research_packages", "socrates_type_reviews",
    ),
    "proposals": ("proposal_briefs", "research_proposals", "proposal_audits"),
    "hypotheses": ("hypotheses", "mingli_draft_ideas", "mingli_finalized_ideas", "mingli_hypothesis_evolution_runs"),
    "debates": ("socratic_debates", "hypothesis_revisions", "mingli_debate_iterations"),
    "verification": ("mechanism_reports", "verification_reports", "yanzhen_reports"),
    "project": ("title", "domain", "objective", "research_brief", "phase", "sub_hypotheses"),
}


NORMALIZED_PROJECT_LAYOUT_SCHEMA_VERSION = "science_project_layout_v1"
NORMALIZED_PROJECT_STORAGE_FORMAT = "normalized_artifact_store_v1"

# Only invariant directories belong here.  Alignment-contract, gap-contract,
# bundle-version, run, and transaction directories are created lazily when a
# later migration/write transaction has a real identifier for them.
NORMALIZED_PROJECT_STATIC_DIRECTORIES: dict[str, str] = {
    "papers": "papers",
    "fragments": "fragments",
    "assertions": "assertions",
    "source_span_registry_shards": "fragments/registry_shards/source_span",
    "assertion_registry_shards": "assertions/registry_shards/evidence_assertion",
    "evidence_graphs": "graphs/evidence",
    "gaps": "gaps",
    "bundles": "bundles",
    "contracts": "contracts",
    "reports": "reports",
    "runs": "runs",
    "project_fields": "project_fields",
    "audits": "audits",
    "fragment_candidate_audits": "audits/fragment_candidates",
    "socrates_query_audits": "audits/socrates_queries",
    "migration_audits": "audits/migration",
    "reference_integrity_audits": "audits/reference_integrity",
    "artifact_json_repairs": "audits/artifact_json_repairs",
    "transactions": "transactions",
}

NORMALIZED_PROJECT_DYNAMIC_PATH_TEMPLATES: dict[str, str] = {
    "manifest": "manifest.json",
    "paper": "papers/<paper_id>.json",
    "fragment_audit": "fragments/<alignment_contract_hash>/<paper_id>.jsonl",
    "fragment_index": "fragments/<alignment_contract_hash>/<paper_id>.index.json",
    "fragment_registry": "fragments/fragment_registry.json",
    "source_span_registry": "fragments/source_span_registry.json",
    "assertion_registry": "assertions/assertion_registry.json",
    "source_span_registry_root": "fragments/source_span_registry_root.json",
    "assertion_registry_root": "assertions/assertion_registry_root.json",
    "evidence_graph": "graphs/evidence/<graph_id>/v<version>.json",
    "gap": "gaps/<gap_id>.json",
    "bundle": "bundles/<gap_id>/v<version>.json",
    "contract": "contracts/<gap_id>/v<version>.json",
    "report": "reports/<run_id>.json",
    "run_detail": "runs/<run_id>.detail.json",
    "run_summary": "runs/<run_id>.summary.json",
    "project_field": "project_fields/<field_name>.json",
    "fragment_candidate_audit": "audits/fragment_candidates/<run_id>.jsonl",
    "socrates_query_audit": "audits/socrates_queries/<run_id>.jsonl",
    "migration_audit": "audits/migration/<migration_id>.json",
    "reference_integrity_audit": "audits/reference_integrity/<state_version>.json",
    "artifact_json_repair_audit": "audits/artifact_json_repairs/<repair_id>.json",
    "tanxi_detector_result": "runs/tanxi_detectors/<input_fingerprint>/<detector_id>/v<version>.json",
    "subhypothesis_contract": "sub_hypothesis_contracts/<sub_hypothesis_id>/<contract_revision>.json",
    "retrieval_execution": "retrieval_executions/<sub_hypothesis_id>/v<version>.json",
    "tanxi_input_manifest": "runs/tanxi_inputs/<input_fingerprint>/v<version>.json",
    "transaction_staging": "transactions/<transaction_id>/",
}


V3_RESEARCH_QUESTION_STATE_SCHEMA_VERSION = "v3_research_question_state_refs_v1"
V3_SUBHYPOTHESIS_CONTRACT_ARTIFACT_SCHEMA_VERSION = "v3_subhypothesis_contract_artifact_v1"
V3_RETRIEVAL_EXECUTION_ARTIFACT_SCHEMA_VERSION = "v3_retrieval_execution_artifact_v1"
TANXI_INPUT_MANIFEST_SCHEMA_VERSION = "tanxi_input_manifest_v3"


def _v3_subhypothesis_id(sub_hypothesis: dict[str, Any], index: int = 0) -> str:
    return str(
        sub_hypothesis.get("id")
        or sub_hypothesis.get("sub_hypothesis_id")
        or (f"SH{index + 1}" if index >= 0 else "")
    ).strip()


def _is_v3_subhypothesis(sub_hypothesis: Any) -> bool:
    if not isinstance(sub_hypothesis, dict):
        return False
    contract = sub_hypothesis.get("research_question_contract")
    return bool(
        sub_hypothesis.get("evidence_pipeline_schema") == "research_question_evidence_v3"
        or (
            isinstance(contract, dict)
            and str(contract.get("schema_version") or "")
            == "research_question_contract_v3"
        )
    )


_GAP_ALLOCATOR: ContextVar[dict[str, Any] | None] = ContextVar("science_gap_allocator", default=None)


def _safe_identifier(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip()).strip("_").lower()


_TANXI_REFERENCE_BODY_FIELDS = frozenset({
    "excerpt",
    "quote",
    "source_quote",
    "supporting_phrase",
    "document",
    "full_text",
    "fulltext",
})


def _tanxi_reference_only_value(value: Any) -> Any:
    """Remove source bodies from resumable TanXi artifacts.

    Runtime evidence views are intentionally narrow but may include quotes for
    an active semantic audit.  Checkpoints must retain only durable lookup
    keys, hashes, and offsets so a resumed GroupChat hydrates text afresh from
    the same immutable span record.
    """
    if isinstance(value, dict):
        return {
            str(key): _tanxi_reference_only_value(item)
            for key, item in value.items()
            if str(key) not in _TANXI_REFERENCE_BODY_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_tanxi_reference_only_value(item) for item in value]
    return copy.deepcopy(value)


def _gap_sequence_from_id(gap_id: str, project_id: str) -> int:
    prefix = f"gap_{_safe_identifier(project_id)}_"
    text = str(gap_id or "").lower()
    if not text.startswith(prefix):
        return 0
    suffix = text[len(prefix):]
    return int(suffix) if suffix.isdigit() else 0


def activate_project_gap_allocator(project: dict[str, Any]) -> None:
    project_id = str(project.get("project_id") or "")
    registry = project.get("gap_identity_registry") if isinstance(project.get("gap_identity_registry"), dict) else {}
    assignments = registry.get("assignments") if isinstance(registry.get("assignments"), dict) else {}
    ledger = project.get("gap_candidate_ledger") if isinstance(project.get("gap_candidate_ledger"), dict) else {}
    ledger_rows = ledger.get("candidates") if isinstance(ledger.get("candidates"), list) else []
    registry_ids = [
        str(entry.get("canonical_gap_id") or "")
        for entry in assignments.values()
        if isinstance(entry, dict)
    ]
    ledger_ids = [
        str(row.get("canonical_gap_id") or row.get("latest_gap_id") or "")
        for row in ledger_rows
        if isinstance(row, dict)
    ]
    maximum = max(
        [
            _gap_sequence_from_id(str(gap.get("gap_id") or ""), project_id)
            for gap in project.get("knowledge_gaps", [])
            if isinstance(gap, dict)
        ]
        + [_gap_sequence_from_id(value, project_id) for value in registry_ids + ledger_ids]
        or [0]
    )
    next_sequence = max(
        int(project.get("next_gap_sequence") or 1),
        int(registry.get("next_gap_sequence") or 1),
        maximum + 1,
    )
    _GAP_ALLOCATOR.set({"project_id": project_id, "next_sequence": next_sequence})


def new_science_gap_id(project_id: str = "") -> str:
    allocator = _GAP_ALLOCATOR.get()
    active_project = str(project_id or (allocator or {}).get("project_id") or "").strip()
    if active_project and allocator and str(allocator.get("project_id") or "") == active_project:
        sequence = max(1, int(allocator.get("next_sequence") or 1))
        allocator["next_sequence"] = sequence + 1
        return f"gap_{_safe_identifier(active_project)}_{sequence:04d}"
    if active_project:
        return f"gap_{_safe_identifier(active_project)}_{time.time_ns()}"
    return f"gap_unbound_{time.time_ns()}"


def _science_source_handoff_refs(values: Any) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in values if isinstance(values, list) else []:
        if not isinstance(item, dict):
            continue
        ref = {
            "source_text_handoff_id": str(item.get("source_text_handoff_id") or ""),
            "paper_id": str(item.get("paper_id") or ""),
            "source_unit_id": str(item.get("source_unit_id") or ""),
            "excerpt_hash": str(item.get("excerpt_hash") or ""),
            "source_origin": str(item.get("source_origin") or ""),
            "source_role": str(item.get("source_role") or ""),
            "package_slot": str(item.get("package_slot") or ""),
            "acceptance_status": str(item.get("acceptance_status") or ""),
        }
        key = (ref["source_text_handoff_id"], ref["source_unit_id"], ref["package_slot"])
        if not ref["source_unit_id"] or key in seen:
            continue
        seen.add(key)
        refs.append(ref)
    return refs


def science_gap_handoff_snapshot(gap: dict[str, Any]) -> dict[str, Any]:
    """Return the human-auditable core of one scientific gap.

    This intentionally preserves the original handoff fields so an older
    Socrates contract can be checked during the migration to gap-scoped
    revisions.  The stronger hash below additionally includes the causal and
    evidence-bundle fields that determine whether MingLi may safely reuse a
    contract.
    """
    return {
        "description": str(gap.get("description") or ""),
        "claim": str(gap.get("claim") or gap.get("description") or ""),
        "evidence_ids": [str(item) for item in (gap.get("supporting_references") or []) if str(item).strip()][:12],
        "mechanism": str(gap.get("proposed_mediator") or gap.get("mechanism_hint") or ""),
        "source_text_handoff_refs": _science_source_handoff_refs(gap.get("source_text_handoffs")),
        "evidence_lineage_refs": _science_source_handoff_refs(gap.get("evidence_lineage")),
        "source_evidence_unit_ids": [
            str(item.get("source_unit_id") or "")
            for item in (gap.get("source_evidence_units") or [])
            if isinstance(item, dict) and str(item.get("source_unit_id") or "")
        ][:24],
    }


def science_gap_state_fingerprint(gap: dict[str, Any]) -> dict[str, Any]:
    """Return the gap-local scientific state that a Socrates handoff binds.

    A global ``artifact_versions.gaps`` counter changes whenever *any* gap or
    contract changes.  It is useful for audit history but is too coarse to
    invalidate an otherwise unchanged gap.  This fingerprint makes the
    handoff specific to the causal object that Socrates actually inspected.
    """
    return {
        "core": science_gap_handoff_snapshot(gap),
        "gap_type": str(gap.get("gap_type") or gap.get("type") or ""),
        "sub_hypothesis_id": str(gap.get("sub_hypothesis_id") or ""),
        "comparison": str(gap.get("comparison") or ""),
        "mechanism_draft": copy.deepcopy(gap.get("mechanism_draft") or {}),
        "mechanism_evidence_bundle": copy.deepcopy(gap.get("mechanism_evidence_bundle") or {}),
        "source_evidence_units": copy.deepcopy(gap.get("source_evidence_units") or []),
        "source_text_handoffs": copy.deepcopy(gap.get("source_text_handoffs") or []),
        "evidence_lineage": copy.deepcopy(gap.get("evidence_lineage") or []),
        "alignment_qualification": copy.deepcopy(gap.get("alignment_qualification") or {}),
        "causal_mediation": copy.deepcopy(gap.get("causal_mediation") or {}),
    }


def science_gap_snapshot_hash(gap: dict[str, Any]) -> str:
    """Hash one canonical gap fingerprint with deterministic JSON encoding."""
    payload = json.dumps(
        science_gap_state_fingerprint(gap),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(payload.encode("utf-8")).hexdigest()


class ScienceStateManager:
    def __init__(
        self,
        project_path: Callable[[str], Path],
        reader: Callable[[Path, str], dict[str, Any]],
        writer: Callable[[Path, Any], None],
    ) -> None:
        self._project_path = project_path
        self._reader = reader
        self._writer = writer
        self._lock = RLock()

    @staticmethod
    def _manifest_api() -> dict[str, Any]:
        try:
            from ._science_manifest import (
                SCIENCE_PROJECT_MANIFEST_SCHEMA_VERSION,
                SCIENCE_TRANSACTION_AUDIT_SCHEMA_VERSION,
                NORMALIZED_ARTIFACT_STORAGE_FORMAT,
                canonical_json_bytes,
                content_hash,
                finalize_manifest,
                safe_relative_artifact_path,
                science_artifact_ref,
                validate_project_manifest,
                validate_science_artifact_ref,
                with_content_hash,
            )
        except ImportError:
            from _science_manifest import (
                SCIENCE_PROJECT_MANIFEST_SCHEMA_VERSION,
                SCIENCE_TRANSACTION_AUDIT_SCHEMA_VERSION,
                NORMALIZED_ARTIFACT_STORAGE_FORMAT,
                canonical_json_bytes,
                content_hash,
                finalize_manifest,
                safe_relative_artifact_path,
                science_artifact_ref,
                validate_project_manifest,
                validate_science_artifact_ref,
                with_content_hash,
            )
        return locals()

    def _normalized_project_root(self, project_id: str) -> Path:
        return Path(str(self.normalized_project_layout(project_id)["project_root"])).resolve()

    def _normalized_artifact_path(self, project_id: str, relative_path: str) -> Path:
        api = self._manifest_api()
        safe_path = api["safe_relative_artifact_path"](relative_path)
        root = self._normalized_project_root(project_id)
        target = (root / Path(*safe_path.split("/"))).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ScienceStateError(f"Normalized artifact escaped project root: {relative_path}") from exc
        return target

    @staticmethod
    def _is_temporary_transaction_artifact_path(relative_path: str) -> bool:
        """Return True when a manifest/ref path points at transaction scratch space.

        Normalized manifests must only reference durable artifact locations such
        as ``project_fields/...`` or ``papers/...``.  Transaction directories are
        intentionally ephemeral; in particular ``staged_artifacts`` is deleted
        after commit.  If a stale or partially-built ref leaks into a project
        field, reads should recover where possible and future commits should
        reject it before publishing a broken manifest.
        """

        normalized = str(relative_path or "").replace("\\", "/").strip().lower().strip("/")
        if not normalized:
            return False
        parts = [part for part in normalized.split("/") if part]
        return bool(parts and parts[0] == "transactions") or "staged_artifacts" in parts

    @staticmethod
    def _is_missing_or_temporary_artifact_error(exc: BaseException) -> bool:
        if isinstance(exc, FileNotFoundError):
            return True
        if not isinstance(exc, (ScienceStateError, ValueError)):
            return False
        text = str(exc).lower()
        return (
            "referenced science artifact does not exist" in text
            or "referenced artifact is missing" in text
            or "science project field artifact is missing" in text
            or "temporary transaction" in text
            or "staged_artifacts" in text
        )

    @staticmethod
    def _log_state_recovery(event: str, **data: Any) -> None:
        try:
            from .log import log_event
        except ImportError:
            try:
                from log import log_event
            except ImportError:
                return
        try:
            log_event("WARN", event, **data)
        except Exception:
            return

    @staticmethod
    def _transaction_stage_path(staging_root: Path, ordinal: int, safe_path: str) -> Path:
        """Use a short scratch filename for transaction staging.

        The durable artifact path can be long and descriptive, for example a
        versioned project-field name.  Mirroring that whole path under
        ``transactions/<txn>/staged_artifacts/...`` pushes Windows installs over
        MAX_PATH in real workspaces with non-ASCII contest directories.  Stage
        files are private scratch artifacts, so a compact ordinal name is both
        safer and easier to reason about; the write plan still records the
        durable normalized target separately.
        """

        suffix = Path(str(safe_path or "")).suffix.lower()
        if suffix not in {".json", ".jsonl"}:
            suffix = ".artifact"
        return staging_root / f"{max(0, int(ordinal)):06d}{suffix}"

    @contextmanager
    def _project_writer_lock(self, project_id: str, *, timeout_seconds: float = 5.0):
        """Serialize normalized writers across threads and Python processes."""
        root = self._normalized_project_root(project_id)
        root.mkdir(parents=True, exist_ok=True)
        lock_path = root / ".science-writer.lock"
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        descriptor: int | None = None
        with self._lock:
            while descriptor is None:
                try:
                    descriptor = os.open(
                        str(lock_path),
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    )
                    payload = json.dumps(
                        {"pid": os.getpid(), "created_at": time.time(), "project_id": project_id},
                        ensure_ascii=False,
                    ).encode("utf-8")
                    os.write(descriptor, payload)
                except FileExistsError:
                    try:
                        age = time.time() - lock_path.stat().st_mtime
                    except OSError:
                        age = 0.0
                    if age > 300.0:
                        try:
                            lock_path.unlink()
                            continue
                        except OSError:
                            pass
                    if time.monotonic() >= deadline:
                        raise ScienceStateError(
                            f"Timed out acquiring normalized project writer lock: {project_id}"
                        )
                    time.sleep(0.05)
            try:
                yield
            finally:
                if descriptor is not None:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                try:
                    lock_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _load_manifest_unlocked(self, project_id: str, *, required: bool = True) -> dict[str, Any] | None:
        manifest_path = Path(str(self.normalized_project_layout(project_id)["manifest_path"]))
        if not manifest_path.is_file():
            if required:
                raise ScienceStateError(
                    f"Normalized project manifest not found: {project_id}; initialize or migrate explicitly first."
                )
            return None
        manifest = self._reader(manifest_path, f"Normalized project manifest not found: {project_id}")
        api = self._manifest_api()
        api["validate_project_manifest"](manifest)
        if str(manifest.get("project_id") or "") != str(project_id):
            raise ScienceStateError("Normalized project manifest identity mismatch")
        if str(manifest.get("state_store_id") or "") != self.store_id(project_id):
            raise ScienceStateStoreMismatch(
                f"Normalized project {project_id} belongs to {manifest.get('state_store_id')}, "
                f"active store is {self.store_id(project_id)}."
            )
        return manifest

    def get_project_manifest(self, project_id: str) -> dict[str, Any]:
        """Load and validate the normalized commit point for one project."""
        manifest = self._load_manifest_unlocked(project_id, required=True)
        return copy.deepcopy(manifest or {})

    def repair_artifact_json_v2(
        self,
        project_id: str,
        target: str,
    ) -> dict[str, Any]:
        """Explicitly reserialize one JSON artifact after preserving its bytes.

        This maintenance action deliberately does not scan a project and never
        reconstructs evidence or downloads literature.  It is intended for
        artifacts written by a pre-atomic writer: a strictly parseable JSON
        document is rewritten through the current atomic writer, while an
        unreadable document is preserved and reported as unrecoverable.
        """

        normalized_project_id = str(project_id or "").strip()
        requested_target = str(target or "").strip()
        if not normalized_project_id:
            raise ScienceStateError("artifact_json_repair_v2 requires project_id")
        if not requested_target:
            raise ScienceStateError(
                "artifact_json_repair_v2 requires an explicit normalized path or legacy_snapshot target"
            )
        root = self._normalized_project_root(normalized_project_id)
        projects_root = Path(str(self.normalized_project_layout(normalized_project_id)["projects_root"])).resolve()
        if requested_target == "legacy_snapshot":
            artifact_path = self._project_path(normalized_project_id).resolve()
            try:
                artifact_path.relative_to(projects_root)
            except ValueError as exc:
                raise ScienceStateError("Legacy project snapshot escaped active project store") from exc
            target_kind = "legacy_snapshot"
            target_reference = "legacy_snapshot"
        else:
            safe_path = self._manifest_api()["safe_relative_artifact_path"](requested_target)
            if self._is_temporary_transaction_artifact_path(safe_path):
                raise ScienceStateError(
                    "artifact_json_repair_v2 refuses temporary transaction artifacts"
                )
            if Path(safe_path).suffix.lower() != ".json":
                raise ScienceStateError(
                    "artifact_json_repair_v2 only accepts one .json artifact; JSONL evidence remains immutable"
                )
            artifact_path = self._normalized_artifact_path(normalized_project_id, safe_path)
            target_kind = "normalized_artifact"
            target_reference = safe_path
        if not artifact_path.is_file():
            raise ScienceStateError(
                f"artifact_json_repair_v2 target does not exist: {target_reference}"
            )

        repair_id = f"repair_{time.time_ns()}_{uuid.uuid4().hex[:10]}"
        audit_root = root / "audits" / "artifact_json_repairs"
        backup_path = audit_root / f"{repair_id}.source.json"
        audit_path = audit_root / f"{repair_id}.json"

        def write_bytes_atomically(destination: Path, body: bytes) -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(
                f".{destination.name}.{os.getpid()}.{time.time_ns()}.tmp"
            )
            try:
                temporary.write_bytes(body)
                os.replace(temporary, destination)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

        with self._project_writer_lock(normalized_project_id):
            raw = artifact_path.read_bytes()
            write_bytes_atomically(backup_path, raw)
            audit = {
                "schema_version": "artifact_json_repair_v2",
                "repair_id": repair_id,
                "project_id": normalized_project_id,
                "state_store_id": self.store_id(normalized_project_id),
                "target_kind": target_kind,
                "target": target_reference,
                "backup_path": str(backup_path.relative_to(root)).replace("\\", "/"),
                "original_byte_count": len(raw),
                "original_sha256": "sha256:" + sha256(raw).hexdigest(),
                "requested_at": time.time(),
                "network_retrieval_performed": False,
            }
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                audit.update(
                    {
                        "status": "UNRECOVERABLE_ARTIFACT",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "completed_at": time.time(),
                    }
                )
                self._writer(audit_path, audit)
                return copy.deepcopy(audit)

            self._writer(artifact_path, parsed)
            audit.update(
                {
                    "status": "REPAIRED_VALID_JSON",
                    "resulting_sha256": "sha256:" + sha256(
                        artifact_path.read_bytes()
                    ).hexdigest(),
                    "completed_at": time.time(),
                }
            )
            self._writer(audit_path, audit)
            return copy.deepcopy(audit)

    def _next_artifact_path(
        self,
        base_path: str,
        *,
        artifact_version: int,
        previous_ref: dict[str, Any] | None = None,
    ) -> str:
        api = self._manifest_api()
        normalized = api["safe_relative_artifact_path"](base_path)
        if not previous_ref:
            return normalized
        path = Path(normalized)
        return str(
            path.with_name(f"{path.stem}.v{max(1, int(artifact_version)):04d}{path.suffix}")
        ).replace("\\", "/")

    def _payload_reference_hash(self, payload: Any) -> str:
        api = self._manifest_api()
        if isinstance(payload, dict) and str(payload.get("content_hash") or "").startswith("sha256:"):
            return str(payload["content_hash"])
        return api["content_hash"](payload)

    @staticmethod
    def _version_from_artifact_path(relative_path: str, *, fallback: int = 1) -> int:
        text = str(relative_path or "").replace("\\", "/")
        for pattern in (r"\.v(\d+)\.json$", r"/v(\d+)\.json$"):
            match = re.search(pattern, text)
            if match:
                try:
                    return max(1, int(match.group(1)))
                except (TypeError, ValueError):
                    break
        try:
            return max(1, int(fallback or 1))
        except (TypeError, ValueError):
            return 1

    def _read_valid_existing_artifact(
        self,
        project_id: str,
        relative_path: str,
    ) -> dict[str, Any] | None:
        """Read one durable JSON artifact if it exists and validates.

        This is intentionally a recovery helper, not a normal read path.  It is
        used only when a manifest has lost refs but immutable artifact files are
        still present on disk; invalid or partial files are ignored so the
        regular transaction guard can raise the original immutability error.
        """

        try:
            from ._science_artifacts import validate_normalized_artifact
        except ImportError:
            from _science_artifacts import validate_normalized_artifact
        try:
            safe_path = self._manifest_api()["safe_relative_artifact_path"](relative_path)
            path = self._normalized_artifact_path(project_id, safe_path)
        except Exception:
            return None
        if not path.is_file() or path.suffix.lower() != ".json":
            return None
        try:
            payload = self._reader(path, f"Recovered normalized artifact disappeared: {path}")
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        try:
            validate_normalized_artifact(payload)
        except Exception:
            return None
        return copy.deepcopy(payload)

    def _recover_orphan_gap_chain_refs(
        self,
        project_id: str,
        gap_id: str,
        *,
        state_store_id: str = "",
    ) -> dict[str, dict[str, Any]] | None:
        """Recover refs for a complete immutable gap/bundle/contract chain.

        A previous transaction can leave durable artifact files behind while a
        later compatibility/migration manifest no longer contains ``gap_refs``.
        Treating that state as a brand-new gap makes the next save target the
        original immutable path again (``gaps/<gap_id>.json``).  This helper
        rebinds only a fully self-consistent orphan chain so the caller can
        version from it instead of overwriting it.
        """

        normalized_gap_id = str(gap_id or "").strip()
        if not normalized_gap_id:
            return None
        api = self._manifest_api()
        active_store_id = str(state_store_id or self.store_id(project_id))
        safe_gap_id = _safe_identifier(normalized_gap_id)
        root = self._normalized_project_root(project_id)
        candidates: set[str] = {f"gaps/{safe_gap_id}.json"}
        try:
            gaps_dir = self._normalized_artifact_path(project_id, "gaps")
            if gaps_dir.is_dir():
                for path in gaps_dir.glob(f"{safe_gap_id}.v*.json"):
                    relative = str(path.resolve().relative_to(root)).replace("\\", "/")
                    candidates.add(relative)
        except Exception:
            pass

        recovered_options: list[tuple[int, dict[str, dict[str, Any]]]] = []
        for gap_path in sorted(candidates):
            gap = self._read_valid_existing_artifact(project_id, gap_path)
            if not isinstance(gap, dict):
                continue
            if str(gap.get("project_id") or "") != project_id or str(gap.get("gap_id") or "") != normalized_gap_id:
                continue
            bundle_path = str(gap.get("evidence_bundle_ref") or "")
            contract_path = str(gap.get("latest_contract_ref") or "")
            if not bundle_path or not contract_path:
                continue
            bundle = self._read_valid_existing_artifact(project_id, bundle_path)
            contract = self._read_valid_existing_artifact(project_id, contract_path)
            if not isinstance(bundle, dict) or not isinstance(contract, dict):
                continue
            if any(
                str(item.get("project_id") or "") != project_id
                or str(item.get("gap_id") or "") != normalized_gap_id
                for item in (bundle, contract)
            ):
                continue
            gap_hash = str(gap.get("content_hash") or "")
            bundle_hash = str(bundle.get("content_hash") or "")
            if (
                str(contract.get("gap_ref") or "") != gap_path
                or str(contract.get("gap_snapshot_hash") or "") != gap_hash
                or str(contract.get("evidence_bundle_ref") or "") != bundle_path
                or str(contract.get("evidence_bundle_hash") or "") != bundle_hash
            ):
                continue
            gap_version = self._version_from_artifact_path(
                gap_path,
                fallback=gap.get("gap_version") or 1,
            )
            bundle_version = self._version_from_artifact_path(
                bundle_path,
                fallback=bundle.get("bundle_version") or 1,
            )
            contract_version = self._version_from_artifact_path(
                contract_path,
                fallback=contract.get("contract_version") or 1,
            )
            recovered_options.append((gap_version, {
                "gap_ref": api["science_artifact_ref"](
                    state_store_id=active_store_id,
                    project_id=project_id,
                    artifact_type="gap",
                    artifact_id=normalized_gap_id,
                    artifact_version=gap_version,
                    path=gap_path,
                    artifact_hash=gap_hash,
                ),
                "bundle_ref": api["science_artifact_ref"](
                    state_store_id=active_store_id,
                    project_id=project_id,
                    artifact_type="bundle",
                    artifact_id=normalized_gap_id,
                    artifact_version=bundle_version,
                    path=bundle_path,
                    artifact_hash=bundle_hash,
                ),
                "contract_ref": api["science_artifact_ref"](
                    state_store_id=active_store_id,
                    project_id=project_id,
                    artifact_type="contract",
                    artifact_id=normalized_gap_id,
                    artifact_version=contract_version,
                    path=contract_path,
                    artifact_hash=str(contract.get("content_hash") or ""),
                ),
            }))
        if recovered_options:
            return copy.deepcopy(max(recovered_options, key=lambda item: item[0])[1])
        return None

    def _recover_orphan_project_field_ref(
        self,
        project_id: str,
        field_name: str,
        *,
        state_store_id: str = "",
    ) -> dict[str, Any] | None:
        """Recover a durable project-field generation absent from the manifest.

        A transaction may publish immutable ``project_fields`` artifacts and
        then fail before publishing the manifest.  Without this recovery the
        next save treats the field as version zero, targets the original
        static path, and fails forever when its derived content changed.  The
        recovery is intentionally narrow: it accepts only a schema-valid,
        hash-bearing field document with matching project and field identity.
        """
        normalized_field = str(field_name or "").strip()
        if not normalized_field or normalized_field.startswith("fragment_audit:"):
            return None
        api = self._manifest_api()
        active_store_id = str(state_store_id or self.store_id(project_id))
        safe_field = _safe_identifier(normalized_field)
        root = self._normalized_project_root(project_id)
        candidates: set[str] = {f"project_fields/{safe_field}.json"}
        try:
            fields_dir = self._normalized_artifact_path(project_id, "project_fields")
            if fields_dir.is_dir():
                for path in fields_dir.glob(f"{safe_field}.v*.json"):
                    candidates.add(str(path.resolve().relative_to(root)).replace("\\", "/"))
        except Exception:
            pass

        recovered: list[tuple[int, str, str]] = []
        for relative_path in sorted(candidates):
            if self._is_temporary_transaction_artifact_path(relative_path):
                continue
            try:
                path = self._normalized_artifact_path(project_id, relative_path)
            except Exception:
                continue
            if not path.is_file() or path.suffix.lower() != ".json":
                continue
            try:
                document = self._reader(path, f"Recovered project field disappeared: {path}")
            except Exception:
                continue
            if not isinstance(document, dict):
                continue
            if (
                document.get("schema_version") != "science_project_field_v1"
                or str(document.get("project_id") or "") != project_id
                or str(document.get("field_name") or "") != normalized_field
            ):
                continue
            artifact_hash = str(document.get("content_hash") or "")
            actual_hash = api["content_hash"](document, omit_content_hash=True)
            if not artifact_hash.startswith("sha256:") or artifact_hash != actual_hash:
                continue
            version = self._version_from_artifact_path(relative_path, fallback=1)
            recovered.append((version, relative_path, artifact_hash))
        if not recovered:
            return None
        version, relative_path, artifact_hash = max(recovered, key=lambda item: (item[0], item[1]))
        return api["science_artifact_ref"](
            state_store_id=active_store_id,
            project_id=project_id,
            artifact_type="project_field",
            artifact_id=normalized_field,
            artifact_version=version,
            path=relative_path,
            artifact_hash=artifact_hash,
        )

    def resolve_ref(self, ref: dict[str, Any]) -> Any:
        """Resolve and hash-check one store/project/version-bound reference."""
        api = self._manifest_api()
        validated = api["validate_science_artifact_ref"](ref)
        project_id = str(validated["project_id"])
        if str(validated["state_store_id"]) != self.store_id(project_id):
            raise ScienceStateStoreMismatch(
                f"Science artifact reference belongs to {validated['state_store_id']}, "
                f"active store is {self.store_id(project_id)}."
            )
        if self._is_temporary_transaction_artifact_path(str(validated["path"])):
            raise ScienceStateError(
                "Science artifact reference points to temporary transaction staging path: "
                f"{validated['path']}"
            )
        path = self._normalized_artifact_path(project_id, str(validated["path"]))
        if not path.is_file():
            raise ScienceStateError(f"Referenced science artifact does not exist: {validated['path']}")
        if path.suffix.lower() == ".json":
            payload: Any = self._reader(path, f"Referenced science artifact does not exist: {path}")
            actual_hash = self._payload_reference_hash(payload)
        else:
            payload = path.read_bytes()
            actual_hash = "sha256:" + sha256(payload).hexdigest()
        if actual_hash != str(validated["content_hash"]):
            raise ScienceStateError(f"Science artifact content hash mismatch: {validated['path']}")
        return copy.deepcopy(payload)

    def _manifest_after_ref_update(
        self,
        manifest: dict[str, Any],
        *,
        ref_field: str,
        ref_key: str,
        ref: dict[str, Any],
        artifact_group: str,
        id_field: str = "",
        artifact_id: str = "",
    ) -> dict[str, Any]:
        api = self._manifest_api()
        updated = copy.deepcopy(manifest)
        refs = updated.get(ref_field) if isinstance(updated.get(ref_field), dict) else {}
        refs = dict(refs)
        refs[str(ref_key)] = copy.deepcopy(ref)
        updated[ref_field] = refs
        if id_field and artifact_id:
            identifiers = [str(item) for item in updated.get(id_field, []) if str(item)]
            if artifact_id not in identifiers:
                identifiers.append(artifact_id)
            updated[id_field] = identifiers
            if id_field == "gap_ids":
                knowledge_ids = [str(item) for item in updated.get("knowledge_gap_ids", []) if str(item)]
                if artifact_id not in knowledge_ids:
                    knowledge_ids.append(artifact_id)
                updated["knowledge_gap_ids"] = knowledge_ids
        versions = updated.get("artifact_versions") if isinstance(updated.get("artifact_versions"), dict) else {}
        versions = {str(key): int(value or 0) for key, value in versions.items()}
        versions[artifact_group] = int(versions.get(artifact_group, 0)) + 1
        updated["artifact_versions"] = versions
        updated["state_version"] = int(manifest.get("state_version") or 0) + 1
        updated["updated_at"] = time.time()
        updated["last_committed_transaction_id"] = "PENDING_TRANSACTION_ID"
        return api["finalize_manifest"](updated)

    def _save_ref_artifact(
        self,
        project_id: str,
        *,
        payload: dict[str, Any],
        artifact_type: str,
        artifact_id: str,
        artifact_version: int,
        base_path: str,
        ref_field: str,
        ref_key: str,
        artifact_group: str,
        expected_version: int | None,
        id_field: str = "",
        latest_ref_field: str = "",
        latest_run_id: str = "",
    ) -> dict[str, Any]:
        manifest = self.get_project_manifest(project_id)
        current_version = int(manifest.get("state_version") or 0)
        if expected_version is not None and int(expected_version) != current_version:
            raise StaleScienceStateError(
                f"stale science state for project {project_id}: expected version "
                f"{expected_version}, current version {current_version}"
            )
        refs = manifest.get(ref_field) if isinstance(manifest.get(ref_field), dict) else {}
        previous_ref = refs.get(ref_key) if isinstance(refs.get(ref_key), dict) else None
        payload_hash = self._payload_reference_hash(payload)
        if previous_ref and str(previous_ref.get("content_hash") or "") == payload_hash:
            return {
                "status": "UNCHANGED",
                "state_version": current_version,
                "ref": copy.deepcopy(previous_ref),
            }
        previous_version = int((previous_ref or {}).get("artifact_version") or 0)
        resolved_version = max(int(artifact_version or 0), previous_version + 1, 1)
        relative_path = self._next_artifact_path(
            base_path,
            artifact_version=resolved_version,
            previous_ref=previous_ref,
        )
        api = self._manifest_api()
        ref = api["science_artifact_ref"](
            state_store_id=self.store_id(project_id),
            project_id=project_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            artifact_version=resolved_version,
            path=relative_path,
            artifact_hash=payload_hash,
        )
        updated = self._manifest_after_ref_update(
            manifest,
            ref_field=ref_field,
            ref_key=ref_key,
            ref=ref,
            artifact_group=artifact_group,
            id_field=id_field,
            artifact_id=artifact_id,
        )
        if latest_ref_field:
            updated[latest_ref_field] = copy.deepcopy(ref)
        if latest_run_id:
            updated["latest_run_id"] = str(latest_run_id)
        if latest_ref_field or latest_run_id:
            updated = api["finalize_manifest"](updated)
        result = self._commit_normalized_transaction(
            project_id,
            artifact_writes={relative_path: payload},
            manifest=updated,
            expected_version=current_version,
            operation=f"SAVE_{artifact_type.upper()}",
        )
        result.update({"status": "COMMITTED", "ref": ref})
        return result

    def get_paper(
        self,
        project_id: str,
        paper_id: str,
        *,
        hydrate_evidence: bool = False,
    ) -> dict[str, Any]:
        manifest = self.get_project_manifest(project_id)
        ref = (manifest.get("paper_refs") or {}).get(str(paper_id))
        if not isinstance(ref, dict):
            raise ScienceStateError(f"Unknown paper_id for project {project_id}: {paper_id}")
        payload = self.resolve_ref(ref)
        if not isinstance(payload, dict):
            raise ScienceStateError(f"Paper artifact is not an object: {paper_id}")
        paper = hydrate_paper_fulltext(payload)
        if hydrate_evidence:
            return self.get_paper_evidence(project_id, paper_id, paper=paper)
        return paper

    def _read_indexed_evidence_record(
        self,
        project_id: str,
        registry_root_ref: dict[str, Any],
        identifier: str,
    ) -> dict[str, Any]:
        records = self._read_indexed_evidence_records(
            project_id,
            registry_root_ref,
            [identifier],
        )
        return records[str(identifier)]

    def _read_indexed_evidence_records(
        self,
        project_id: str,
        registry_root_ref: dict[str, Any],
        identifiers: Iterable[str],
        *,
        tolerate_record_errors: bool = False,
        integrity_errors: list[dict[str, Any]] | None = None,
        record_kind: str = "evidence_record",
    ) -> dict[str, dict[str, Any]]:
        """Read indexed evidence in shard/file batches.

        Callers frequently need hundreds of admitted assertions and their
        referenced spans.  Resolving the manifest, root, shard, and JSONL file
        separately for every identifier turns that narrow read model back into
        thousands of tiny disk operations.  This method keeps the same strict
        reference validation while reading every shard and JSONL file once.
        """
        try:
            from ._evidence_storage import evidence_registry_shard_key
        except ImportError:
            from _evidence_storage import evidence_registry_shard_key
        normalized_ids = list(dict.fromkeys(
            str(identifier or "").strip()
            for identifier in identifiers
            if str(identifier or "").strip()
        ))
        if not normalized_ids:
            return {}
        root = self.resolve_ref(registry_root_ref)
        if (
            not isinstance(root, dict)
            or root.get("schema_version") != "evidence_record_registry_root_v3"
        ):
            raise ScienceStateError(
                "EVIDENCE_REGISTRY_V3_REQUIRED: evidence reads require "
                "a sharded registry root."
            )
        def record_error(
            identifier: str,
            error_code: str,
            detail: str,
        ) -> None:
            if not tolerate_record_errors:
                raise ScienceStateError(detail)
            if integrity_errors is not None:
                integrity_errors.append({
                    "schema_version": "artifact_integrity_error_v3",
                    "error_code": error_code,
                    "evidence_kind": str(record_kind or "evidence_record"),
                    "evidence_id": str(identifier or ""),
                    "detail": str(detail)[:500],
                    "excluded_from_evidence_graph": True,
                })

        ids_by_shard: dict[str, list[str]] = {}
        for identifier in normalized_ids:
            ids_by_shard.setdefault(evidence_registry_shard_key(identifier), []).append(identifier)
        locations_by_path: dict[Path, list[tuple[str, dict[str, Any]]]] = {}
        for shard_key, shard_ids in ids_by_shard.items():
            shard_ref = (root.get("shards") or {}).get(shard_key)
            if not isinstance(shard_ref, dict):
                for identifier in shard_ids:
                    record_error(
                        identifier,
                        "INDEXED_EVIDENCE_SHARD_MISSING",
                        f"Unknown indexed evidence id for project {project_id}: {identifier}",
                    )
                continue
            try:
                shard = self.resolve_ref(shard_ref)
            except (ScienceStateError, FileNotFoundError, ValueError) as exc:
                for identifier in shard_ids:
                    record_error(
                        identifier,
                        "INDEXED_EVIDENCE_SHARD_UNREADABLE",
                        f"Indexed evidence shard is unreadable for {identifier}: {exc}",
                    )
                continue
            if (
                not isinstance(shard, dict)
                or shard.get("schema_version") != "evidence_record_registry_shard_v3"
                or str(shard.get("shard_key") or "") != shard_key
            ):
                for identifier in shard_ids:
                    record_error(
                        identifier,
                        "INDEXED_EVIDENCE_SHARD_INVALID",
                        f"Invalid indexed evidence shard for {identifier}",
                    )
                continue
            entries = shard.get("entries") if isinstance(shard.get("entries"), dict) else {}
            for identifier in shard_ids:
                entry = entries.get(identifier)
                if not isinstance(entry, dict):
                    record_error(
                        identifier,
                        "INDEXED_EVIDENCE_ID_MISSING",
                        f"Unknown indexed evidence id for project {project_id}: {identifier}",
                    )
                    continue
                path = self._normalized_artifact_path(project_id, str(entry.get("file") or ""))
                locations_by_path.setdefault(path, []).append((identifier, entry))
        records: dict[str, dict[str, Any]] = {}
        for path, locations in locations_by_path.items():
            try:
                file_size = path.stat().st_size
                stream = path.open("rb")
            except OSError as exc:
                for identifier, _entry in locations:
                    record_error(
                        identifier,
                        "INDEXED_EVIDENCE_FILE_UNREADABLE",
                        f"Indexed evidence file is unreadable for {identifier}: {exc}",
                    )
                continue
            with stream:
                for identifier, entry in sorted(locations, key=lambda item: int(item[1].get("offset") or 0)):
                    offset = int(entry.get("offset") or 0)
                    length = int(entry.get("length") or 0)
                    if offset < 0 or length <= 0 or offset + length > file_size:
                        record_error(
                            identifier,
                            "INDEXED_EVIDENCE_LOCATION_INVALID",
                            f"Invalid indexed evidence location for {identifier}",
                        )
                        continue
                    try:
                        stream.seek(offset)
                        body = stream.read(length)
                    except OSError as exc:
                        record_error(
                            identifier,
                            "INDEXED_EVIDENCE_FILE_UNREADABLE",
                            f"Indexed evidence file read failed for {identifier}: {exc}",
                        )
                        continue
                    expected_hash = str(entry.get("content_hash") or "")
                    if expected_hash and "sha256:" + sha256(body).hexdigest() != expected_hash:
                        record_error(
                            identifier,
                            "INDEXED_EVIDENCE_CONTENT_HASH_MISMATCH",
                            f"Indexed evidence content hash mismatch: {identifier}",
                        )
                        continue
                    try:
                        payload = json.loads(body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        record_error(
                            identifier,
                            "INDEXED_EVIDENCE_PAYLOAD_INVALID",
                            f"Indexed evidence payload is invalid for {identifier}: {exc}",
                        )
                        continue
                    if not isinstance(payload, dict):
                        record_error(
                            identifier,
                            "INDEXED_EVIDENCE_PAYLOAD_INVALID",
                            f"Indexed evidence payload is not an object: {identifier}",
                        )
                        continue
                    records[identifier] = payload
        return records

    def get_source_span(self, project_id: str, source_span_id: str) -> dict[str, Any]:
        manifest = self.get_project_manifest(project_id)
        registry_ref = manifest.get("source_span_registry_root_ref")
        if not isinstance(registry_ref, dict):
            raise ScienceStateError(
                f"EVIDENCE_REGISTRY_V2_MIGRATION_REQUIRED: project has no source-span registry root: {project_id}"
            )
        return self._read_indexed_evidence_record(project_id, registry_ref, source_span_id)

    def get_evidence_assertion(self, project_id: str, assertion_id: str) -> dict[str, Any]:
        manifest = self.get_project_manifest(project_id)
        registry_ref = manifest.get("assertion_registry_root_ref")
        if not isinstance(registry_ref, dict):
            raise ScienceStateError(
                f"EVIDENCE_REGISTRY_V2_MIGRATION_REQUIRED: project has no assertion registry root: {project_id}"
            )
        return self._read_indexed_evidence_record(project_id, registry_ref, assertion_id)

    def get_paper_evidence(
        self,
        project_id: str,
        paper_id: str,
        *,
        paper: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Hydrate V4 evidence for one paper only, never a whole project.

        This is a read model.  It restores source-span relationships by id
        but intentionally does not re-embed the paper document into every
        span or copy span/quote content into assertions.  Callers needing a
        quote resolve the referenced span; persistence therefore remains
        reference-first even after a read-modify-write cycle.
        """
        resolved = copy.deepcopy(paper) if isinstance(paper, dict) else self.get_paper(project_id, paper_id)
        storage = resolved.get("evidence_storage_v4") if isinstance(resolved.get("evidence_storage_v4"), dict) else {}
        if storage and str(storage.get("schema_version") or "") != "paper_evidence_storage_ref_v4":
            raise ScienceStateError("EVIDENCE_STORAGE_V4_REQUIRED")
        document_versions = self._document_versions_from_storage_v4(
            storage,
            paper_id=str(resolved.get("paper_id") or paper_id),
        )
        current_document_version_hash = str(
            storage.get("current_document_version_hash") or ""
        )
        if storage and not current_document_version_hash:
            raise ScienceStateError("EVIDENCE_STORAGE_CURRENT_DOCUMENT_VERSION_V4_REQUIRED")
        document = copy.deepcopy(
            document_versions.get(current_document_version_hash) or {}
        )
        if storage and not document:
            raise ScienceStateError("EVIDENCE_STORAGE_CURRENT_DOCUMENT_ARTIFACT_MISSING")
        spans: list[dict[str, Any]] = []
        for span_id in storage.get("source_span_ids", []):
            span = self.get_source_span(project_id, str(span_id))
            spans.append(span)
        assertions: list[dict[str, Any]] = []
        for assertion_id in storage.get("assertion_ids", []):
            assertion = self.get_evidence_assertion(project_id, str(assertion_id))
            assertions.append(assertion)
        resolved["evidence_document_v4"] = document
        resolved["evidence_document_versions_v4"] = [
            copy.deepcopy(document_versions[version_hash])
            for version_hash in sorted(document_versions)
        ]
        resolved["source_spans_v6"] = spans
        resolved["evidence_assertions_v4"] = assertions
        return resolved

    @staticmethod
    def _document_versions_from_storage_v4(
        storage: dict[str, Any],
        *,
        paper_id: str,
    ) -> dict[str, dict[str, Any]]:
        """Return immutable V4 document versions keyed by their exact identifier.

        Runtime readers and writers accept only the explicit V4 collection.
        """
        source = storage if isinstance(storage, dict) else {}
        if not source:
            return {}
        if str(source.get("schema_version") or "") != "paper_evidence_storage_ref_v4":
            raise ScienceStateError("EVIDENCE_STORAGE_V4_REQUIRED")

        raw_versions = source.get("document_versions_v4")
        requires_declared_current = raw_versions is not None
        if not isinstance(raw_versions, dict):
            raise ScienceStateError("EVIDENCE_DOCUMENT_VERSION_COLLECTION_V4_REQUIRED")

        validated: dict[str, dict[str, Any]] = {}
        for version_hash, raw_document in raw_versions.items():
            normalized_hash = str(version_hash or "")
            if (
                not normalized_hash
                or not isinstance(raw_document, dict)
                or str(raw_document.get("schema_version") or "") != "document_version_v4"
                or str(raw_document.get("paper_id") or "") != str(paper_id or "")
                or str(raw_document.get("document_version_hash") or "") != normalized_hash
            ):
                raise ScienceStateError("EVIDENCE_DOCUMENT_VERSION_ARTIFACT_INVALID")
            validated[normalized_hash] = copy.deepcopy(raw_document)
        if requires_declared_current:
            current_document_version_hash = str(
                source.get("current_document_version_hash") or ""
            )
            if not current_document_version_hash:
                raise ScienceStateError(
                    "EVIDENCE_STORAGE_CURRENT_DOCUMENT_VERSION_V4_REQUIRED"
                )
            if current_document_version_hash not in validated:
                raise ScienceStateError(
                    "EVIDENCE_STORAGE_CURRENT_DOCUMENT_ARTIFACT_MISSING"
                )
        return {
            version_hash: validated[version_hash]
            for version_hash in sorted(validated)
        }

    def _project_field_value(
        self,
        project_id: str,
        manifest: dict[str, Any],
        field_name: str,
        *,
        required: bool = True,
    ) -> Any:
        ref = (manifest.get("project_field_refs") or {}).get(field_name)
        if not isinstance(ref, dict):
            if required:
                raise ScienceStateError(
                    f"Normalized project field is required for V2 operation: {field_name}"
                )
            return None
        document = self.resolve_ref(ref)
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != "science_project_field_v1"
            or str(document.get("project_id") or "") != project_id
            or str(document.get("field_name") or "") != field_name
        ):
            raise ScienceStateError(
                f"Invalid normalized project field artifact for {project_id}: {field_name}"
            )
        return copy.deepcopy(document.get("value"))

    @staticmethod
    def _compact_v3_retrieval_execution(execution: dict[str, Any]) -> dict[str, Any]:
        """Keep one SH ledger auditable without persisting discovery payloads.

        The authoritative retrieval result is the admitted assertion/span/paper
        reference set plus compact task and slot statistics.  Provider result
        bodies, broad-candidate diagnostics, query prose, and full-text data
        are deliberately excluded from this high-frequency artifact.
        """
        source = execution if isinstance(execution, dict) else {}
        task_fields = (
            "task_id", "query_branch", "query_fingerprint", "retrieval_purpose",
            "plan_revision", "status", "coverage_status", "query_mode", "evidence_slot",
            "candidate_count", "metadata_kept_count", "fulltext_available_count",
            "alignment_completed_count", "alignment_not_executed_count",
            "alignment_integrity_error_count", "direct_slot_admitted_count",
            "direct_slot_admitted_ids", "direct_slot_admitted_source_ids",
            "direct_slot_admitted_assertion_ids_by_slot",
            "direct_slot_admitted_source_ids_by_slot",
            "direct_slot_admitted_span_ids_by_slot",
            "new_direct_slot_admitted_source_count",
            "reused_direct_slot_admitted_source_count",
            "reused_direct_slot_admitted_assertion_count",
            "direct_slot_admitted_span_count", "coverage_bundle_id",
            "coverage_bundle_kind", "comparison_signature", "slot_policy_verdict",
            "provider_dispatch_status", "provider_dispatch_reason",
            "independent_confirmation_required", "foundation_context_count",
            "background_only_count", "contract_rejected_count", "raw_provider_result_count",
            "deferred_provider_count", "provider_error_count",
        )
        results = []
        for raw in source.get("results", []):
            if not isinstance(raw, dict):
                continue
            row = {
                key: copy.deepcopy(raw[key])
                for key in task_fields
                if key in raw
            }
            if row:
                results.append(row)
        top_level_fields = (
            "schema_version", "status", "retrieval_execution_status",
            "candidate_intake_status", "alignment_status", "candidate_count",
            "raw_provider_result_count", "deferred_provider_count", "provider_error_count",
            "v2_deferred_provider_continuation_attempts", "configured_providers",
            "dispatched_providers", "skipped_providers", "metadata_kept_count",
            "fulltext_available_count", "alignment_completed_count",
            "alignment_not_executed_count", "alignment_integrity_error_count",
            "admission_status", "evidence_coverage_status", "aggregate_evidence_ready",
            "required_direct_slot_ids", "covered_direct_slot_ids",
            "missing_direct_slot_ids", "direct_evidence_paper_count",
            "research_question_contract_id", "v2_query_variant_policy",
            "unexecuted_task_ids", "scientific_gap_verdict", "rule",
        )
        compacted = {
            key: copy.deepcopy(source[key])
            for key in top_level_fields
            if key in source
        }
        compacted["results"] = results
        compacted["slot_coverage_ledger"] = copy.deepcopy(
            source.get("slot_coverage_ledger")
            if isinstance(source.get("slot_coverage_ledger"), dict)
            else {}
        )
        return compacted

    @staticmethod
    def _v3_contract_subhypothesis_projection(sub_hypothesis: dict[str, Any]) -> dict[str, Any]:
        """Return the immutable scientific declaration for one V3 SH.

        A retrieval plan is a deterministic compiler output from the immutable
        contract, not part of that contract.  Execution ledgers, annotation
        summaries, and plan-supersession logs are operational state and must
        never change a declaration artifact's content hash.
        """
        contract = (
            sub_hypothesis.get("research_question_contract")
            if isinstance(sub_hypothesis.get("research_question_contract"), dict)
            else {}
        )
        immutable_fields = (
            "id",
            "sub_hypothesis_id",
            "focus",
            "research_question",
            "evidence_pipeline_schema",
            "research_role",
            "design_basis_ids",
            "shared_context_keys",
            "claim_target",
            "claim_types",
            "epistemic_profile",
            "evidence_contract",
            "scientific_scope",
            "objective_anchor",
            "candidate_id",
        )
        projection = {
            key: copy.deepcopy(sub_hypothesis[key])
            for key in immutable_fields
            if key in sub_hypothesis
        }
        projection["research_question_contract"] = copy.deepcopy(contract)
        return projection

    def _read_v3_subhypothesis_contract_ref(
        self,
        project_id: str,
        ref: dict[str, Any],
    ) -> dict[str, Any]:
        document = self.resolve_ref(ref)
        if (
            not isinstance(document, dict)
            or document.get("schema_version")
            != V3_SUBHYPOTHESIS_CONTRACT_ARTIFACT_SCHEMA_VERSION
            or str(document.get("project_id") or "") != project_id
            or not isinstance(document.get("sub_hypothesis"), dict)
            or not isinstance(document.get("research_question_contract"), dict)
        ):
            raise ScienceStateError("V3_SUBHYPOTHESIS_CONTRACT_ARTIFACT_INVALID")
        return copy.deepcopy(document)

    def _read_v3_retrieval_execution_ref(
        self,
        project_id: str,
        ref: dict[str, Any],
    ) -> dict[str, Any]:
        document = self.resolve_ref(ref)
        if (
            not isinstance(document, dict)
            or document.get("schema_version")
            != V3_RETRIEVAL_EXECUTION_ARTIFACT_SCHEMA_VERSION
            or str(document.get("project_id") or "") != project_id
            or not isinstance(document.get("execution"), dict)
        ):
            raise ScienceStateError("V3_RETRIEVAL_EXECUTION_ARTIFACT_INVALID")
        return copy.deepcopy(document)

    def _v3_research_question_state_refs(
        self,
        project_id: str,
        manifest: dict[str, Any],
        *,
        required: bool = True,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        contract_refs = {
            str(key): copy.deepcopy(value)
            for key, value in (manifest.get("subhypothesis_contract_refs") or {}).items()
            if isinstance(value, dict)
        }
        execution_refs = {
            str(key): copy.deepcopy(value)
            for key, value in (manifest.get("retrieval_execution_refs") or {}).items()
            if isinstance(value, dict)
        }
        if required and (
            str(manifest.get("v3_research_question_state_schema_version") or "")
            != V3_RESEARCH_QUESTION_STATE_SCHEMA_VERSION
            or not contract_refs
        ):
            raise ScienceStateError(
                "V3_SUBHYPOTHESIS_STATE_MIGRATION_REQUIRED: V3 contracts and retrieval "
                "executions must be externalized before reference-first execution."
            )
        return contract_refs, execution_refs

    def load_v3_subhypothesis_contracts(self, project_id: str) -> list[dict[str, Any]]:
        """Load immutable V3 SH declarations without materializing a project."""
        manifest = self.get_project_manifest(project_id)
        contract_refs, _ = self._v3_research_question_state_refs(project_id, manifest)
        contracts: list[dict[str, Any]] = []
        for sub_hypothesis_id, ref in sorted(contract_refs.items()):
            document = self._read_v3_subhypothesis_contract_ref(project_id, ref)
            if str(document.get("sub_hypothesis_id") or "") != sub_hypothesis_id:
                raise ScienceStateError("V3_SUBHYPOTHESIS_CONTRACT_REF_IDENTITY_MISMATCH")
            contracts.append(document)
        return contracts

    @staticmethod
    def _v3_runtime_subhypothesis(document: dict[str, Any]) -> dict[str, Any]:
        """Build the small in-memory SH view required by V3 orchestration.

        Retrieval plans are deterministically compiled from the externalized
        contract.  They are intentionally not restored from, or written into,
        a declaration artifact.
        """
        try:
            from ._research_question_contract import build_question_retrieval_plan
        except ImportError:
            from _research_question_contract import build_question_retrieval_plan
        source = document if isinstance(document, dict) else {}
        sub_hypothesis = copy.deepcopy(source.get("sub_hypothesis") or {})
        contract = source.get("research_question_contract")
        if not isinstance(contract, dict):
            raise ScienceStateError("V3_SUBHYPOTHESIS_CONTRACT_ARTIFACT_INVALID")
        sub_hypothesis["research_question_contract"] = copy.deepcopy(contract)
        sub_hypothesis["research_question_retrieval_plan"] = (
            build_question_retrieval_plan(contract)
        )
        sub_hypothesis["evidence_pipeline_schema"] = "research_question_evidence_v3"
        return sub_hypothesis

    def load_v3_retrieval_executions(
        self,
        project_id: str,
        *,
        sub_hypothesis_ids: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Load only requested V3 SH execution ledgers from detached artifacts."""
        manifest = self.get_project_manifest(project_id)
        _contract_refs, execution_refs = self._v3_research_question_state_refs(project_id, manifest)
        requested = {str(item) for item in (sub_hypothesis_ids or []) if str(item)}
        executions: dict[str, dict[str, Any]] = {}
        for sub_hypothesis_id, ref in sorted(execution_refs.items()):
            if requested and sub_hypothesis_id not in requested:
                continue
            document = self._read_v3_retrieval_execution_ref(project_id, ref)
            if str(document.get("sub_hypothesis_id") or "") != sub_hypothesis_id:
                raise ScienceStateError("V3_RETRIEVAL_EXECUTION_REF_IDENTITY_MISMATCH")
            executions[sub_hypothesis_id] = copy.deepcopy(document.get("execution") or {})
        return executions

    def load_v3_retrieval_execution(
        self,
        project_id: str,
        sub_hypothesis_id: str,
        *,
        required: bool = False,
    ) -> dict[str, Any] | None:
        executions = self.load_v3_retrieval_executions(
            project_id,
            sub_hypothesis_ids=[sub_hypothesis_id],
        )
        execution = executions.get(str(sub_hypothesis_id))
        if execution is None and required:
            raise ScienceStateError(
                f"V3_RETRIEVAL_EXECUTION_REQUIRED: {sub_hypothesis_id}"
            )
        return execution

    def _v3_contract_documents_from_subhypotheses(
        self,
        project_id: str,
        sub_hypotheses: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        try:
            from ._research_question_contract import validate_research_question_contract
        except ImportError:
            from _research_question_contract import validate_research_question_contract
        documents: dict[str, dict[str, Any]] = {}
        for index, sub_hypothesis in enumerate(sub_hypotheses):
            if not _is_v3_subhypothesis(sub_hypothesis):
                continue
            sub_hypothesis_id = _v3_subhypothesis_id(sub_hypothesis, index)
            if not sub_hypothesis_id:
                raise ScienceStateError("V3_SUBHYPOTHESIS_CONTRACT_ID_REQUIRED")
            contract = validate_research_question_contract(
                sub_hypothesis.get("research_question_contract")
            )
            document = self._manifest_api()["with_content_hash"]({
                "schema_version": V3_SUBHYPOTHESIS_CONTRACT_ARTIFACT_SCHEMA_VERSION,
                "project_id": project_id,
                "sub_hypothesis_id": sub_hypothesis_id,
                "research_question_contract_id": str(contract.get("contract_id") or ""),
                "contract_revision": str(
                    contract.get("contract_revision") or contract.get("declaration_hash") or ""
                ),
                "contract_hash": str(contract.get("declaration_hash") or ""),
                "research_question_contract": contract,
                "sub_hypothesis": self._v3_contract_subhypothesis_projection(sub_hypothesis),
            })
            documents[sub_hypothesis_id] = document
        return documents

    def _plan_v3_research_question_state_artifacts(
        self,
        project_id: str,
        *,
        sub_hypotheses: list[dict[str, Any]],
        executions: dict[str, Any],
        existing_contract_refs: dict[str, dict[str, Any]] | None = None,
        existing_execution_refs: dict[str, dict[str, Any]] | None = None,
        require_existing_contracts: bool = False,
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        """Create only changed immutable SH contract/execution artifacts."""
        api = self._manifest_api()
        writes: dict[str, Any] = {}
        contract_refs = {
            str(key): copy.deepcopy(value)
            for key, value in (existing_contract_refs or {}).items()
            if isinstance(value, dict)
        }
        execution_refs = {
            str(key): copy.deepcopy(value)
            for key, value in (existing_execution_refs or {}).items()
            if isinstance(value, dict)
        }
        documents = self._v3_contract_documents_from_subhypotheses(project_id, sub_hypotheses)
        if require_existing_contracts and set(documents) - set(contract_refs):
            raise ScienceStateError(
                "V3_SUBHYPOTHESIS_STATE_MIGRATION_REQUIRED: current V3 contract refs are absent."
            )
        for sub_hypothesis_id, document in sorted(documents.items()):
            previous_ref = contract_refs.get(sub_hypothesis_id)
            if isinstance(previous_ref, dict):
                previous = self._read_v3_subhypothesis_contract_ref(project_id, previous_ref)
                if str(previous.get("content_hash") or "") == str(document.get("content_hash") or ""):
                    continue
                if str(previous.get("contract_revision") or "") == str(document.get("contract_revision") or ""):
                    raise ScienceStateError(
                        "V3_SUBHYPOTHESIS_CONTRACT_IMMUTABILITY_VIOLATION: "
                        f"{sub_hypothesis_id} changed without a contract revision."
                    )
            version = int((previous_ref or {}).get("artifact_version") or 0) + 1
            revision = _safe_identifier(document.get("contract_revision")) or f"v{version:04d}"
            path = self._next_artifact_path(
                f"sub_hypothesis_contracts/{_safe_identifier(sub_hypothesis_id)}/{revision}.json",
                artifact_version=version,
                previous_ref=previous_ref,
            )
            writes[path] = document
            contract_refs[sub_hypothesis_id] = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id),
                project_id=project_id,
                artifact_type="v3_subhypothesis_contract",
                artifact_id=sub_hypothesis_id,
                artifact_version=version,
                path=path,
                artifact_hash=str(document["content_hash"]),
            )
        for sub_hypothesis_id, raw_execution in sorted(executions.items()):
            if sub_hypothesis_id not in documents or not isinstance(raw_execution, dict):
                continue
            contract_document = documents[sub_hypothesis_id]
            execution = self._compact_v3_retrieval_execution(raw_execution)
            contract_id = str(contract_document.get("research_question_contract_id") or "")
            if str(execution.get("research_question_contract_id") or contract_id) != contract_id:
                raise ScienceStateError("V3_RETRIEVAL_EXECUTION_CONTRACT_ID_MISMATCH")
            document = api["with_content_hash"]({
                "schema_version": V3_RETRIEVAL_EXECUTION_ARTIFACT_SCHEMA_VERSION,
                "project_id": project_id,
                "sub_hypothesis_id": sub_hypothesis_id,
                "research_question_contract_id": contract_id,
                "contract_revision": str(contract_document.get("contract_revision") or ""),
                "contract_hash": str(contract_document.get("contract_hash") or ""),
                "execution": execution,
            })
            previous_ref = execution_refs.get(sub_hypothesis_id)
            if isinstance(previous_ref, dict):
                previous = self._read_v3_retrieval_execution_ref(project_id, previous_ref)
                if str(previous.get("content_hash") or "") == str(document.get("content_hash") or ""):
                    continue
            version = int((previous_ref or {}).get("artifact_version") or 0) + 1
            path = self._next_artifact_path(
                f"retrieval_executions/{_safe_identifier(sub_hypothesis_id)}/execution.json",
                artifact_version=version,
                previous_ref=previous_ref,
            )
            writes[path] = document
            execution_refs[sub_hypothesis_id] = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id),
                project_id=project_id,
                artifact_type="v3_retrieval_execution",
                artifact_id=sub_hypothesis_id,
                artifact_version=version,
                path=path,
                artifact_hash=str(document["content_hash"]),
            )
        return writes, contract_refs, execution_refs

    def migrate_v3_research_question_state(
        self,
        project_id: str,
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Explicitly externalize V2 SH declarations and per-SH executions.

        This is a one-time normalized-storage migration.  The previous large
        project fields remain immutable historical artifacts but are removed
        from the active manifest; normal V2 execution never reads them.
        """
        manifest = self.get_project_manifest(project_id)
        current_version = int(manifest.get("state_version") or 0)
        if expected_version is not None and int(expected_version) != current_version:
            raise StaleScienceStateError(
                f"stale science state for project {project_id}: expected version "
                f"{expected_version}, current version {current_version}"
            )
        contract_refs, execution_refs = self._v3_research_question_state_refs(
            project_id,
            manifest,
            required=False,
        )
        if (
            str(manifest.get("v3_research_question_state_schema_version") or "")
            == V3_RESEARCH_QUESTION_STATE_SCHEMA_VERSION
            and contract_refs
        ):
            return {
                "status": "ALREADY_MIGRATED",
                "project_id": project_id,
                "state_version": current_version,
                "subhypothesis_contract_refs": contract_refs,
                "retrieval_execution_refs": execution_refs,
            }
        sub_hypotheses = self._project_field_value(
            project_id,
            manifest,
            "sub_hypotheses",
        )
        executions = self._project_field_value(
            project_id,
            manifest,
            "research_question_retrieval_executions_v3",
            required=False,
        )
        if not isinstance(sub_hypotheses, list) or not sub_hypotheses or not all(
            _is_v3_subhypothesis(item) for item in sub_hypotheses if isinstance(item, dict)
        ):
            raise ScienceStateError(
                "V3_SUBHYPOTHESIS_STATE_MIGRATION_REQUIRES_CURRENT_V3_CONTRACTS"
            )
        if not all(isinstance(item, dict) for item in sub_hypotheses):
            raise ScienceStateError(
                "V3_SUBHYPOTHESIS_STATE_MIGRATION_REQUIRES_VALID_SUBHYPOTHESES"
            )
        execution_values = executions if isinstance(executions, dict) else {}
        writes, next_contract_refs, next_execution_refs = (
            self._plan_v3_research_question_state_artifacts(
                project_id,
                sub_hypotheses=[dict(item) for item in sub_hypotheses],
                executions=execution_values,
                existing_contract_refs=contract_refs,
                existing_execution_refs=execution_refs,
            )
        )
        api = self._manifest_api()
        updated = copy.deepcopy(manifest)
        field_refs = {
            str(key): copy.deepcopy(value)
            for key, value in (manifest.get("project_field_refs") or {}).items()
            if isinstance(value, dict)
            and str(key) not in {
                "sub_hypotheses",
                "research_question_retrieval_executions_v3",
                "slot_coverage_ledger_v1",
            }
        }
        updated["project_field_refs"] = field_refs
        updated["subhypothesis_contract_refs"] = next_contract_refs
        updated["retrieval_execution_refs"] = next_execution_refs
        updated["v3_research_question_state_schema_version"] = (
            V3_RESEARCH_QUESTION_STATE_SCHEMA_VERSION
        )
        versions = {
            str(key): int(value or 0)
            for key, value in (manifest.get("artifact_versions") or {}).items()
        }
        versions["project"] = int(versions.get("project") or 0) + 1
        versions["retrieval"] = int(versions.get("retrieval") or 0) + 1
        updated["artifact_versions"] = versions
        updated["state_version"] = current_version + 1
        updated["updated_at"] = time.time()
        updated["last_committed_transaction_id"] = "PENDING_TRANSACTION_ID"
        updated = api["finalize_manifest"](updated)
        result = self._commit_normalized_transaction(
            project_id,
            artifact_writes=writes,
            manifest=updated,
            expected_version=current_version,
            operation="MIGRATE_V2_RESEARCH_QUESTION_STATE",
        )
        return {
            "status": "MIGRATED",
            "project_id": project_id,
            "state_version": int(result.get("state_version") or current_version + 1),
            "contract_count": len(next_contract_refs),
            "execution_count": len(next_execution_refs),
            "subhypothesis_contract_refs": next_contract_refs,
            "retrieval_execution_refs": next_execution_refs,
        }

    def persist_v3_retrieval_execution(
        self,
        project_id: str,
        *,
        sub_hypothesis_id: str,
        execution: dict[str, Any],
        field_updates: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Atomically write one SH retrieval ledger and compact control fields.

        No project materialization occurs here: the immutable contract ref is
        checked directly and only the affected execution artifact is versioned.
        """
        normalized_subhypothesis_id = str(sub_hypothesis_id or "").strip()
        if not normalized_subhypothesis_id or not isinstance(execution, dict):
            raise ScienceStateError("V3_RETRIEVAL_EXECUTION_ID_AND_PAYLOAD_REQUIRED")
        manifest = self.get_project_manifest(project_id)
        current_version = int(manifest.get("state_version") or 0)
        if expected_version is not None and int(expected_version) != current_version:
            raise StaleScienceStateError(
                f"stale science state for project {project_id}: expected version "
                f"{expected_version}, current version {current_version}"
            )
        contract_refs, execution_refs = self._v3_research_question_state_refs(
            project_id,
            manifest,
        )
        contract_ref = contract_refs.get(normalized_subhypothesis_id)
        if not isinstance(contract_ref, dict):
            raise ScienceStateError(
                f"V3_SUBHYPOTHESIS_CONTRACT_REQUIRED: {normalized_subhypothesis_id}"
            )
        contract_document = self._read_v3_subhypothesis_contract_ref(
            project_id,
            contract_ref,
        )
        contract_id = str(contract_document.get("research_question_contract_id") or "")
        if str(execution.get("research_question_contract_id") or contract_id) != contract_id:
            raise ScienceStateError("V3_RETRIEVAL_EXECUTION_CONTRACT_ID_MISMATCH")
        api = self._manifest_api()
        compacted_execution = self._compact_v3_retrieval_execution(execution)
        execution_document = api["with_content_hash"]({
            "schema_version": V3_RETRIEVAL_EXECUTION_ARTIFACT_SCHEMA_VERSION,
            "project_id": project_id,
            "sub_hypothesis_id": normalized_subhypothesis_id,
            "research_question_contract_id": contract_id,
            "contract_revision": str(contract_document.get("contract_revision") or ""),
            "contract_hash": str(contract_document.get("contract_hash") or ""),
            "execution": compacted_execution,
        })
        writes: dict[str, Any] = {}
        next_execution_refs = dict(execution_refs)
        previous_execution_ref = next_execution_refs.get(normalized_subhypothesis_id)
        if isinstance(previous_execution_ref, dict):
            previous_execution = self._read_v3_retrieval_execution_ref(
                project_id,
                previous_execution_ref,
            )
        else:
            previous_execution = {}
        if str(previous_execution.get("content_hash") or "") != str(
            execution_document.get("content_hash") or ""
        ):
            execution_version = int(
                (previous_execution_ref or {}).get("artifact_version") or 0
            ) + 1
            execution_path = self._next_artifact_path(
                f"retrieval_executions/{_safe_identifier(normalized_subhypothesis_id)}/execution.json",
                artifact_version=execution_version,
                previous_ref=previous_execution_ref,
            )
            writes[execution_path] = execution_document
            next_execution_refs[normalized_subhypothesis_id] = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id),
                project_id=project_id,
                artifact_type="v3_retrieval_execution",
                artifact_id=normalized_subhypothesis_id,
                artifact_version=execution_version,
                path=execution_path,
                artifact_hash=str(execution_document["content_hash"]),
            )

        next_field_refs = {
            str(key): copy.deepcopy(value)
            for key, value in (manifest.get("project_field_refs") or {}).items()
            if isinstance(value, dict)
        }
        protected = {
            "sub_hypotheses",
            "research_question_retrieval_executions_v3",
            "slot_coverage_ledger_v1",
        }
        for field_name, value in (field_updates or {}).items():
            name = str(field_name or "").strip()
            if not name or name in protected or name.startswith("fragment_audit:"):
                raise ScienceStateError("INVALID_NARROW_V3_RETRIEVAL_FIELD_UPDATE")
            document = api["with_content_hash"]({
                "schema_version": "science_project_field_v1",
                "project_id": project_id,
                "field_name": name,
                "value": copy.deepcopy(value),
            })
            previous_ref = next_field_refs.get(name)
            if isinstance(previous_ref, dict) and str(previous_ref.get("content_hash") or "") == str(document["content_hash"]):
                continue
            version = int((previous_ref or {}).get("artifact_version") or 0) + 1
            path = self._next_artifact_path(
                f"project_fields/{_safe_identifier(name)}.json",
                artifact_version=version,
                previous_ref=previous_ref,
            )
            writes[path] = document
            next_field_refs[name] = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id),
                project_id=project_id,
                artifact_type="project_field",
                artifact_id=name,
                artifact_version=version,
                path=path,
                artifact_hash=str(document["content_hash"]),
            )
        if not writes:
            return {
                "status": "UNCHANGED",
                "project_id": project_id,
                "state_version": current_version,
                "execution_ref": copy.deepcopy(next_execution_refs.get(normalized_subhypothesis_id)),
            }
        updated = copy.deepcopy(manifest)
        updated["retrieval_execution_refs"] = next_execution_refs
        updated["project_field_refs"] = next_field_refs
        updated["v3_research_question_state_schema_version"] = (
            V3_RESEARCH_QUESTION_STATE_SCHEMA_VERSION
        )
        versions = {
            str(key): int(value or 0)
            for key, value in (manifest.get("artifact_versions") or {}).items()
        }
        versions["retrieval"] = int(versions.get("retrieval") or 0) + 1
        if field_updates:
            versions["workflow"] = int(versions.get("workflow") or 0) + 1
        updated["artifact_versions"] = versions
        updated["state_version"] = current_version + 1
        updated["updated_at"] = time.time()
        updated["last_committed_transaction_id"] = "PENDING_TRANSACTION_ID"
        updated = api["finalize_manifest"](updated)
        result = self._commit_normalized_transaction(
            project_id,
            artifact_writes=writes,
            manifest=updated,
            expected_version=current_version,
            operation="PERSIST_V3_RETRIEVAL_EXECUTION",
        )
        return {
            "status": "COMMITTED",
            "project_id": project_id,
            "state_version": int(result.get("state_version") or current_version + 1),
            "execution_ref": copy.deepcopy(next_execution_refs.get(normalized_subhypothesis_id)),
        }

    def load_tanxi_evidence_view(
        self,
        project_id: str,
        *,
        contract_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Load only V4-admitted evidence required by TanXi.

        This read model never materializes PaperGraph, full text, broad
        candidates, or historical gap artifacts.  The retrieval execution
        ledger is the authority for which persisted assertions may enter the
        TanXi graph; every assertion and span is then randomly read through
        the sharded registry.
        """
        try:
            from ._research_question_contract import validate_research_question_contract
        except ImportError:
            from _research_question_contract import validate_research_question_contract
        manifest = self.get_project_manifest(project_id)
        source_span_registry_root_ref = manifest.get("source_span_registry_root_ref")
        assertion_registry_root_ref = manifest.get("assertion_registry_root_ref")
        has_sharded_registry_roots = isinstance(
            source_span_registry_root_ref, dict
        ) and isinstance(assertion_registry_root_ref, dict)
        has_partial_sharded_registry_roots = (
            isinstance(source_span_registry_root_ref, dict)
            != isinstance(assertion_registry_root_ref, dict)
        )
        has_legacy_registry_refs = isinstance(
            manifest.get("source_span_registry_ref"), dict
        ) or isinstance(manifest.get("assertion_registry_ref"), dict)
        has_legacy_inline_evidence = False
        if not has_sharded_registry_roots and not has_legacy_registry_refs:
            for paper_ref in (manifest.get("paper_refs") or {}).values():
                if not isinstance(paper_ref, dict):
                    continue
                try:
                    paper = self.resolve_ref(paper_ref)
                except ScienceStateError:
                    continue
                if isinstance(paper, dict) and any(
                    key in paper
                    for key in (
                        "evidence_document_v4",
                        "source_spans_v6",
                        "evidence_assertions_v4",
                    )
                ):
                    has_legacy_inline_evidence = True
                    break
        if has_partial_sharded_registry_roots:
            raise ScienceStateError(
                "EVIDENCE_REGISTRY_V4_INCOMPLETE: TanXi requires both source-span and "
                "assertion registry roots when either root has been persisted."
            )
        if not has_sharded_registry_roots and (
            has_legacy_registry_refs or has_legacy_inline_evidence
        ):
            raise ScienceStateError(
                "EVIDENCE_REGISTRY_V4_REQUIRED: TanXi requires sharded source-span "
                "and assertion registry roots for a project with historic embedded evidence."
            )
        contract_documents = self.load_v3_subhypothesis_contracts(project_id)
        executions = self.load_v3_retrieval_executions(project_id)
        selected_contract_ids = {str(item) for item in (contract_ids or []) if str(item)}
        contracts: list[dict[str, Any]] = []
        contract_by_sh: dict[str, dict[str, Any]] = {}
        contract_refs_by_id: dict[str, dict[str, Any]] = {}
        for document in contract_documents:
            raw_contract = document.get("research_question_contract")
            contract = validate_research_question_contract(raw_contract)
            contract_id = str(contract.get("contract_id") or "")
            if selected_contract_ids and contract_id not in selected_contract_ids:
                continue
            contracts.append(contract)
            sub_hypothesis_id = str(document.get("sub_hypothesis_id") or "")
            contract_by_sh[sub_hypothesis_id] = contract
            contract_refs_by_id[contract_id] = {
                key: copy.deepcopy(value)
                for key, value in document.items()
                if key in {
                    "sub_hypothesis_id", "research_question_contract_id",
                    "contract_revision", "contract_hash", "content_hash",
                }
            }
        if not contracts:
            raise ScienceStateError("TANXI_EVIDENCE_VIEW_CONTRACTS_EMPTY")

        admitted_by_contract: dict[str, dict[str, set[str]]] = {}
        execution_rows: list[dict[str, Any]] = []
        for sub_hypothesis_id, execution in executions.items():
            if not isinstance(execution, dict):
                continue
            contract = contract_by_sh.get(str(sub_hypothesis_id))
            if not isinstance(contract, dict):
                continue
            contract_id = str(contract.get("contract_id") or "")
            if str(execution.get("research_question_contract_id") or "") != contract_id:
                continue
            per_slot = admitted_by_contract.setdefault(contract_id, {})
            results = execution.get("results") if isinstance(execution.get("results"), list) else []
            for result in results:
                if not isinstance(result, dict):
                    continue
                admitted = result.get("direct_slot_admitted_assertion_ids_by_slot")
                if not isinstance(admitted, dict):
                    continue
                for slot_id, assertion_ids in admitted.items():
                    slot = str(slot_id or "")
                    if not slot or not isinstance(assertion_ids, list):
                        continue
                    per_slot.setdefault(slot, set()).update(
                        str(assertion_id) for assertion_id in assertion_ids if str(assertion_id)
                    )
            execution_rows.append({
                "sub_hypothesis_id": str(sub_hypothesis_id),
                "research_question_contract_id": contract_id,
                "retrieval_execution_status": str(execution.get("retrieval_execution_status") or execution.get("status") or ""),
                "required_direct_slot_ids": list(execution.get("required_direct_slot_ids") or []),
                "covered_direct_slot_ids": list(execution.get("covered_direct_slot_ids") or []),
                "missing_direct_slot_ids": list(execution.get("missing_direct_slot_ids") or []),
            })

        retrieval_execution_errors = [
            {
                "sub_hypothesis_id": str(sub_hypothesis_id),
                "task_id": str(result.get("task_id") or ""),
                "status": str(result.get("status") or ""),
                "failure_stage": str(result.get("failure_stage") or ""),
                "exception_type": str(result.get("exception_type") or ""),
                "exception_message": str(result.get("exception_message") or ""),
            }
            for sub_hypothesis_id, execution in executions.items()
            if isinstance(execution, dict)
            and isinstance(contract_by_sh.get(str(sub_hypothesis_id)), dict)
            and str(execution.get("research_question_contract_id") or "")
            == str(
                contract_by_sh[str(sub_hypothesis_id)].get("contract_id") or ""
            )
            for result in (execution.get("results") or [])
            if isinstance(result, dict)
            and str(result.get("status") or "") == "RETRIEVAL_EXECUTION_ERROR"
        ]
        if not has_sharded_registry_roots:
            payload = {
                "schema_version": "tanxi_evidence_view_v4",
                "project_id": project_id,
                "contracts": contracts,
                "contract_refs": [
                    contract_refs_by_id[str(contract.get("contract_id") or "")]
                    for contract in contracts
                    if str(contract.get("contract_id") or "") in contract_refs_by_id
                ],
                "retrieval_executions": execution_rows,
                "retrieval_execution_refs": [
                    {
                        "sub_hypothesis_id": sub_hypothesis_id,
                        "research_question_contract_id": str(
                            contract_by_sh[sub_hypothesis_id].get("contract_id") or ""
                        ),
                        "content_hash": str(ref.get("content_hash") or ""),
                        "artifact_version": int(ref.get("artifact_version") or 0),
                    }
                    for sub_hypothesis_id, ref in sorted(
                        (manifest.get("retrieval_execution_refs") or {}).items()
                    )
                    if sub_hypothesis_id in contract_by_sh and isinstance(ref, dict)
                ],
                "documents": [],
                "source_spans": [],
                "assertions": [],
                "artifact_integrity_errors_v4": [],
                "admission_policy": "retrieval_ledger_direct_slot_admitted_assertion_ids_by_slot",
                "corpus_status": "EMPTY_V4_CORPUS",
                "empty_corpus_diagnostic": {
                    "status": (
                        "RETRIEVAL_EXECUTION_FAILED_NO_CORPUS"
                        if retrieval_execution_errors
                        else "RETRIEVAL_COMPLETED_WITHOUT_ADMITTED_EVIDENCE"
                    ),
                    "reason_code": (
                        "V4_RETRIEVAL_EXECUTION_ERROR"
                        if retrieval_execution_errors
                        else "V4_NO_ADMITTED_EVIDENCE"
                    ),
                    "retrieval_execution_error_count": len(retrieval_execution_errors),
                    "retrieval_execution_errors": retrieval_execution_errors,
                    "registry_state": "NOT_CREATED_BECAUSE_NO_ADMITTED_SOURCE_EVIDENCE",
                },
            }
            payload["input_fingerprint"] = self._tanxi_input_fingerprint(payload)
            return payload

        assertion_ids = sorted({
            assertion_id
            for slot_map in admitted_by_contract.values()
            for assertion_group in slot_map.values()
            for assertion_id in assertion_group
        })
        assertions: list[dict[str, Any]] = []
        spans_by_id: dict[str, dict[str, Any]] = {}
        documents_by_version: dict[tuple[str, str], dict[str, Any]] = {}
        document_versions_by_paper: dict[str, dict[str, dict[str, Any]]] = {}
        integrity_errors: list[dict[str, Any]] = []
        assertions_by_id = self._read_indexed_evidence_records(
            project_id,
            assertion_registry_root_ref,
            assertion_ids,
            tolerate_record_errors=True,
            integrity_errors=integrity_errors,
            record_kind="evidence_assertion",
        )
        expected_by_assertion: dict[str, tuple[dict[str, Any], set[str], list[str]]] = {}
        for assertion_id in assertion_ids:
            assertion = assertions_by_id.get(assertion_id)
            if not isinstance(assertion, dict):
                continue
            if (
                str(assertion.get("schema_version") or "") != "evidence_assertion_v4"
                or str(assertion.get("textual_explicitness") or "") != "EXPLICIT"
                or str(assertion.get("assertion_origin") or "") != "SOURCE_EXPLICIT"
                or str(assertion.get("derivation_status") or "") not in {"", "NOT_DERIVED"}
            ):
                integrity_errors.append({
                    "schema_version": "artifact_integrity_error_v4",
                    "assertion_id": assertion_id,
                    "reason": "NONEXPLICIT_OR_DERIVED_ASSERTION_REJECTED",
                })
                continue
            contract_id = str(assertion.get("research_question_contract_id") or "")
            contract = next(
                (item for item in contracts if str(item.get("contract_id") or "") == contract_id),
                None,
            )
            if not isinstance(contract, dict):
                integrity_errors.append({
                    "assertion_id": assertion_id,
                    "reason": "ASSERTION_CURRENT_CONTRACT_NOT_FOUND",
                })
                continue
            if (
                str(assertion.get("research_question_contract_revision") or "")
                != str(contract.get("contract_revision") or contract.get("declaration_hash") or "")
                or str(assertion.get("research_question_contract_hash") or "")
                != str(contract.get("declaration_hash") or "")
            ):
                integrity_errors.append({
                    "assertion_id": assertion_id,
                    "reason": "ASSERTION_CONTRACT_REVISION_MISMATCH",
                })
                continue
            allowed_slots = admitted_by_contract.get(contract_id, {})
            supported_slots = {
                str(item.get("slot_id") or "")
                for item in assertion.get("slot_support", [])
                if isinstance(item, dict)
                and item.get("support_status") == "VERIFIED_NONCOUNTING"
                and str(item.get("slot_id") or "") in {
                    str(slot_id) for slot_id in assertion.get("admitted_slot_ids_v4") or []
                }
                and assertion_id in allowed_slots.get(str(item.get("slot_id") or ""), set())
            }
            if not supported_slots:
                integrity_errors.append({
                    "assertion_id": assertion_id,
                    "reason": "LEDGER_ASSERTION_SLOT_SUPPORT_MISMATCH",
                })
                continue
            span_ids = [str(item) for item in assertion.get("source_span_ids", []) if str(item)]
            if not span_ids or not str(assertion.get("document_version_hash") or ""):
                integrity_errors.append({
                    "assertion_id": assertion_id,
                    "reason": "ASSERTION_PROVENANCE_INCOMPLETE",
                })
                continue
            expected_by_assertion[assertion_id] = (assertion, supported_slots, span_ids)

        required_span_ids = sorted({
            span_id
            for _assertion, _slots, span_ids in expected_by_assertion.values()
            for span_id in span_ids
        })
        spans_loaded = self._read_indexed_evidence_records(
            project_id,
            source_span_registry_root_ref,
            required_span_ids,
            tolerate_record_errors=True,
            integrity_errors=integrity_errors,
            record_kind="source_span",
        )
        for assertion_id, (raw_assertion, supported_slots, span_ids) in expected_by_assertion.items():
            assertion = raw_assertion
            span_integrity_failed = False
            for span_id in span_ids:
                span = spans_loaded.get(span_id)
                if not isinstance(span, dict):
                    span_integrity_failed = True
                    continue
                if (
                    str(span.get("schema_version") or "") != "source_span_v6"
                    or str(span.get("source_type") or "") != "fulltext"
                    or str(span.get("span_kind") or "") in {"title", "abstract"}
                    or str(span.get("section_disposition") or "") != "INCLUDED"
                    or str(span.get("source_material_status") or "")
                    != "SOURCE_BOUND_FULLTEXT"
                    or str(span.get("binding_status") or "")
                    != "SOURCE_UNIT_VERIFIED"
                    or not str(span.get("source_locator") or "")
                ):
                    integrity_errors.append({
                        "schema_version": "artifact_integrity_error_v4",
                        "assertion_id": assertion_id,
                        "source_span_id": span_id,
                        "reason": "DIRECT_ADMISSION_REQUIRES_FULLTEXT_SOURCE_SPAN",
                    })
                    span_integrity_failed = True
                    continue
                if (
                    str(span.get("paper_id") or "") != str(assertion.get("paper_id") or "")
                    or str(span.get("document_version_hash") or "")
                    != str(assertion.get("document_version_hash") or "")
                ):
                    integrity_errors.append({
                        "assertion_id": assertion_id,
                        "source_span_id": span_id,
                        "reason": "ASSERTION_SPAN_DOCUMENT_MISMATCH",
                    })
                    span_integrity_failed = True
                    continue
                spans_by_id[span_id] = span
            if span_integrity_failed:
                continue
            paper_id = str(assertion.get("paper_id") or "")
            document_version_hash = str(assertion.get("document_version_hash") or "")
            document_key = (paper_id, document_version_hash)
            if document_key not in documents_by_version:
                if paper_id not in document_versions_by_paper:
                    paper_ref = (manifest.get("paper_refs") or {}).get(paper_id)
                    if not isinstance(paper_ref, dict):
                        integrity_errors.append({
                            "assertion_id": assertion_id,
                            "reason": "ASSERTION_PAPER_ARTIFACT_MISSING",
                        })
                        continue
                    paper = self.resolve_ref(paper_ref)
                    storage = paper.get("evidence_storage_v4") if isinstance(paper, dict) and isinstance(paper.get("evidence_storage_v4"), dict) else {}
                    try:
                        document_versions_by_paper[paper_id] = (
                            self._document_versions_from_storage_v4(
                                storage,
                                paper_id=paper_id,
                            )
                        )
                    except ScienceStateError as exc:
                        integrity_errors.append({
                            "assertion_id": assertion_id,
                            "reason": "ASSERTION_DOCUMENT_ARTIFACT_MISSING",
                            "diagnostic_code": str(exc),
                        })
                        continue
                document = document_versions_by_paper[paper_id].get(
                    document_version_hash
                )
                if not isinstance(document, dict):
                    integrity_errors.append({
                        "assertion_id": assertion_id,
                        "reason": "ASSERTION_DOCUMENT_ARTIFACT_MISSING",
                    })
                    continue
                documents_by_version[document_key] = copy.deepcopy(document)
            assertion = copy.deepcopy(assertion)
            assertion["admitted_slot_ids_v4"] = sorted(supported_slots)
            assertions.append(assertion)

        payload = {
            "schema_version": "tanxi_evidence_view_v4",
            "project_id": project_id,
            "contracts": contracts,
            "contract_refs": [
                contract_refs_by_id[str(contract.get("contract_id") or "")]
                for contract in contracts
                if str(contract.get("contract_id") or "") in contract_refs_by_id
            ],
            "retrieval_executions": execution_rows,
            "retrieval_execution_refs": [
                {
                    "sub_hypothesis_id": sub_hypothesis_id,
                    "research_question_contract_id": str(
                        contract_by_sh[sub_hypothesis_id].get("contract_id") or ""
                    ),
                    "content_hash": str(ref.get("content_hash") or ""),
                    "artifact_version": int(ref.get("artifact_version") or 0),
                }
                for sub_hypothesis_id, ref in sorted(
                    (manifest.get("retrieval_execution_refs") or {}).items()
                )
                if sub_hypothesis_id in contract_by_sh and isinstance(ref, dict)
            ],
            "documents": [
                documents_by_version[key]
                for key in sorted(documents_by_version)
            ],
            "source_spans": [spans_by_id[key] for key in sorted(spans_by_id)],
            "assertions": sorted(assertions, key=lambda item: str(item.get("assertion_id") or "")),
            "artifact_integrity_errors_v4": integrity_errors,
            "admission_policy": "retrieval_ledger_direct_slot_admitted_assertion_ids_by_slot",
            "corpus_status": "V4_ADMITTED_EVIDENCE_AVAILABLE",
        }
        payload["input_fingerprint"] = self._tanxi_input_fingerprint(payload)
        return payload

    @staticmethod
    def _tanxi_input_fingerprint(evidence_view: dict[str, Any]) -> str:
        """Fingerprint immutable TanXi references, never quote/full-text payloads."""
        source = evidence_view if isinstance(evidence_view, dict) else {}
        contract_refs = [
            {
                "sub_hypothesis_id": str(item.get("sub_hypothesis_id") or ""),
                "research_question_contract_id": str(
                    item.get("research_question_contract_id") or ""
                ),
                "contract_revision": str(item.get("contract_revision") or ""),
                "contract_hash": str(item.get("contract_hash") or ""),
                "content_hash": str(item.get("content_hash") or ""),
            }
            for item in source.get("contract_refs", [])
            if isinstance(item, dict)
        ]
        execution_refs = [
            {
                "sub_hypothesis_id": str(item.get("sub_hypothesis_id") or ""),
                "research_question_contract_id": str(
                    item.get("research_question_contract_id") or ""
                ),
                "artifact_version": int(item.get("artifact_version") or 0),
                "content_hash": str(item.get("content_hash") or ""),
            }
            for item in source.get("retrieval_execution_refs", [])
            if isinstance(item, dict)
        ]
        assertions = [
            {
                "assertion_id": str(item.get("assertion_id") or ""),
                "paper_id": str(item.get("paper_id") or ""),
                "document_version_hash": str(item.get("document_version_hash") or ""),
                "source_span_ids": sorted(
                    str(value) for value in item.get("source_span_ids", []) if str(value)
                ),
                "admitted_slot_ids_v4": sorted(
                    str(value) for value in item.get("admitted_slot_ids_v4", []) if str(value)
                ),
                "quote_hash": str(item.get("quote_hash") or ""),
            }
            for item in source.get("assertions", [])
            if isinstance(item, dict)
        ]
        spans = [
            {
                "source_span_id": str(
                    item.get("source_span_id") or item.get("source_unit_id") or ""
                ),
                "paper_id": str(item.get("paper_id") or ""),
                "document_version_hash": str(item.get("document_version_hash") or ""),
                "quote_hash": str(item.get("quote_hash") or ""),
                "source_locator": str(item.get("source_locator") or ""),
                "char_start": item.get("char_start"),
                "char_end": item.get("char_end"),
                "page_number": item.get("page_number"),
            }
            for item in source.get("source_spans", [])
            if isinstance(item, dict)
        ]
        documents = [
            {
                "paper_id": str(item.get("paper_id") or ""),
                "document_version_hash": str(item.get("document_version_hash") or ""),
            }
            for item in source.get("documents", [])
            if isinstance(item, dict)
        ]
        projection = {
            "schema_version": TANXI_INPUT_MANIFEST_SCHEMA_VERSION,
            "project_id": str(source.get("project_id") or ""),
            "contract_refs": sorted(contract_refs, key=lambda item: (
                item["sub_hypothesis_id"], item["research_question_contract_id"]
            )),
            "retrieval_execution_refs": sorted(execution_refs, key=lambda item: (
                item["sub_hypothesis_id"], item["artifact_version"]
            )),
            "admitted_assertions": sorted(assertions, key=lambda item: item["assertion_id"]),
            "source_spans": sorted(spans, key=lambda item: item["source_span_id"]),
            "paper_document_versions": sorted(documents, key=lambda item: (
                item["paper_id"], item["document_version_hash"]
            )),
            "normalization_policy_revision": str(
                source.get("normalization_policy_revision") or
                "research_evidence_graph_v4_reference_first_view"
            ),
            "detector_admission_projection_policy_revision": str(
                source.get("detector_admission_projection_policy_revision") or
                "direct_slot_admission_projection_v1"
            ),
        }
        return "sha256:" + sha256(
            json.dumps(
                projection,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()

    def persist_tanxi_input_manifest(
        self,
        project_id: str,
        *,
        evidence_view: dict[str, Any],
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Persist the immutable reference list consumed by one TanXi run."""
        if str(evidence_view.get("schema_version") or "") != "tanxi_evidence_view_v4":
            raise ScienceStateError(
                "TANXI_EVIDENCE_VIEW_V3_REQUIRED: historic evidence views are not adapted"
            )
        if str(evidence_view.get("project_id") or "") != project_id:
            raise ScienceStateError("TANXI_INPUT_MANIFEST_PROJECT_MISMATCH")
        input_fingerprint = self._tanxi_input_fingerprint(evidence_view)
        if str(evidence_view.get("input_fingerprint") or "") != input_fingerprint:
            raise ScienceStateError("TANXI_INPUT_FINGERPRINT_MISMATCH")
        manifest = self.get_project_manifest(project_id)
        current_version = int(manifest.get("state_version") or 0)
        if expected_version is not None and int(expected_version) != current_version:
            raise StaleScienceStateError(
                f"stale science state for project {project_id}: expected version "
                f"{expected_version}, current version {current_version}"
            )
        active_ref = manifest.get("active_tanxi_input_manifest_ref")
        if isinstance(active_ref, dict):
            prior = self.resolve_ref(active_ref)
            if (
                isinstance(prior, dict)
                and str(prior.get("input_fingerprint") or "") == input_fingerprint
            ):
                return {
                    "status": "CACHE_HIT",
                    "project_id": project_id,
                    "state_version": current_version,
                    "input_fingerprint": input_fingerprint,
                    "input_manifest": prior,
                    "artifact_ref": copy.deepcopy(active_ref),
                }
        manifest_payload = self._tanxi_input_manifest_payload(evidence_view)
        api = self._manifest_api()
        document = api["with_content_hash"](manifest_payload)
        historical_refs = {
            str(key): copy.deepcopy(value)
            for key, value in (manifest.get("tanxi_input_manifest_refs") or {}).items()
            if isinstance(value, dict)
        }
        prior_ref = historical_refs.get(input_fingerprint)
        if isinstance(prior_ref, dict):
            prior = self.resolve_ref(prior_ref)
            if (
                isinstance(prior, dict)
                and str(prior.get("input_fingerprint") or "") == input_fingerprint
            ):
                updated = copy.deepcopy(manifest)
                updated["active_tanxi_input_manifest_ref"] = copy.deepcopy(prior_ref)
                versions = {
                    str(key): int(value or 0)
                    for key, value in (manifest.get("artifact_versions") or {}).items()
                }
                versions["workflow"] = int(versions.get("workflow") or 0) + 1
                updated["artifact_versions"] = versions
                updated["state_version"] = current_version + 1
                updated["updated_at"] = time.time()
                updated["last_committed_transaction_id"] = "PENDING_TRANSACTION_ID"
                updated = api["finalize_manifest"](updated)
                result = self._commit_normalized_transaction(
                    project_id,
                    artifact_writes={},
                    manifest=updated,
                    expected_version=current_version,
                    operation="REACTIVATE_TANXI_INPUT_MANIFEST",
                )
                return {
                    "status": "REACTIVATED_HISTORICAL_INPUT",
                    "project_id": project_id,
                    "state_version": int(result.get("state_version") or current_version + 1),
                    "input_fingerprint": input_fingerprint,
                    "input_manifest": prior,
                    "artifact_ref": copy.deepcopy(prior_ref),
                }
        version = int((prior_ref or {}).get("artifact_version") or 0) + 1
        path = f"runs/tanxi_inputs/{_safe_identifier(input_fingerprint)}/v{version:04d}.json"
        ref = api["science_artifact_ref"](
            state_store_id=self.store_id(project_id),
            project_id=project_id,
            artifact_type="tanxi_input_manifest",
            artifact_id=_safe_identifier(input_fingerprint),
            artifact_version=version,
            path=path,
            artifact_hash=str(document["content_hash"]),
        )
        updated = copy.deepcopy(manifest)
        historical_refs[input_fingerprint] = ref
        updated["tanxi_input_manifest_refs"] = historical_refs
        updated["active_tanxi_input_manifest_ref"] = ref
        versions = {
            str(key): int(value or 0)
            for key, value in (manifest.get("artifact_versions") or {}).items()
        }
        versions["workflow"] = int(versions.get("workflow") or 0) + 1
        updated["artifact_versions"] = versions
        updated["state_version"] = current_version + 1
        updated["updated_at"] = time.time()
        updated["last_committed_transaction_id"] = "PENDING_TRANSACTION_ID"
        updated = api["finalize_manifest"](updated)
        result = self._commit_normalized_transaction(
            project_id,
            artifact_writes={path: document},
            manifest=updated,
            expected_version=current_version,
            operation="PERSIST_TANXI_INPUT_MANIFEST",
        )
        return {
            "status": "COMMITTED",
            "project_id": project_id,
            "state_version": int(result.get("state_version") or current_version + 1),
            "input_fingerprint": input_fingerprint,
            "input_manifest": document,
            "artifact_ref": ref,
        }

    def _tanxi_input_manifest_payload(self, evidence_view: dict[str, Any]) -> dict[str, Any]:
        """Return a compact, quote-free immutable TanXi input manifest."""
        source = evidence_view if isinstance(evidence_view, dict) else {}
        return {
            "schema_version": TANXI_INPUT_MANIFEST_SCHEMA_VERSION,
            "project_id": str(source.get("project_id") or ""),
            "input_fingerprint": str(source.get("input_fingerprint") or ""),
            "contract_refs": [
                copy.deepcopy(item)
                for item in source.get("contract_refs", [])
                if isinstance(item, dict)
            ],
            "retrieval_execution_refs": [
                copy.deepcopy(item)
                for item in source.get("retrieval_execution_refs", [])
                if isinstance(item, dict)
            ],
            "admitted_assertions": sorted(
                [
                    {
                        "assertion_id": str(item.get("assertion_id") or ""),
                        "paper_id": str(item.get("paper_id") or ""),
                        "document_version_hash": str(item.get("document_version_hash") or ""),
                        "source_span_ids": sorted(
                            str(value) for value in item.get("source_span_ids", []) if str(value)
                        ),
                        "slot_ids": sorted(
                            str(value) for value in item.get("admitted_slot_ids_v4", []) if str(value)
                        ),
                        "quote_hash": str(item.get("quote_hash") or ""),
                    }
                    for item in source.get("assertions", [])
                    if isinstance(item, dict) and str(item.get("assertion_id") or "")
                ],
                key=lambda item: item["assertion_id"],
            ),
            "admitted_source_spans": sorted(
                [
                    {
                        "source_span_id": str(item.get("source_span_id") or item.get("source_unit_id") or ""),
                        "paper_id": str(item.get("paper_id") or ""),
                        "document_version_hash": str(item.get("document_version_hash") or ""),
                        "quote_hash": str(item.get("quote_hash") or item.get("excerpt_hash") or ""),
                        "source_locator": str(item.get("source_locator") or ""),
                        "char_start": item.get("char_start"),
                        "char_end": item.get("char_end"),
                        "page_number": item.get("page_number"),
                    }
                    for item in source.get("source_spans", [])
                    if isinstance(item, dict)
                    and str(item.get("source_span_id") or item.get("source_unit_id") or "")
                ],
                key=lambda item: item["source_span_id"],
            ),
            "paper_document_versions": sorted(
                [
                    {
                        "paper_id": str(item.get("paper_id") or ""),
                        "document_version_hash": str(item.get("document_version_hash") or ""),
                    }
                    for item in source.get("documents", [])
                    if isinstance(item, dict)
                ],
                key=lambda item: (item["paper_id"], item["document_version_hash"]),
            ),
            "counts": {
                "paper_count": len(source.get("documents") or []),
                "source_span_count": len(source.get("source_spans") or []),
                "assertion_count": len(source.get("assertions") or []),
            },
            "normalization_policy_revision": "research_evidence_graph_v4_reference_first_view",
            "detector_admission_projection_policy_revision": "direct_slot_admission_projection_v1",
        }

    def load_tanxi_project_context(self, project_id: str) -> dict[str, Any]:
        """Load only the project fields used by the V3 TanXi workflow.

        This deliberately excludes PaperGraph, all full text, historical graph
        snapshots, and unrelated proposal artifacts.  The returned object has
        the normal project surface required by typed detectors and workflow
        routing, but its evidence comes exclusively from ``load_tanxi_evidence_view``.
        """
        manifest = self.get_project_manifest(project_id)
        fields = {
            "research_workflow_control",
            "workflow_mode",
            "title",
            "domain",
            "declared_domain",
            "objective",
            "strategic_need",
            "research_brief",
            "evidence_normalization_policy_revision",
            "assertion_review_revision",
            "gap_identity_registry",
        "tanxi_run_checkpoint_v3",
        }
        project: dict[str, Any] = {
            "project_id": project_id,
            "state_version": int(manifest.get("state_version") or 0),
            "state_store_id": str(manifest.get("state_store_id") or ""),
            "artifact_versions": copy.deepcopy(manifest.get("artifact_versions") or {}),
            "papergraph": [],
            "knowledge_gaps": [],
            "research_evidence_graphs": [],
        }
        metadata = manifest.get("project_metadata") if isinstance(manifest.get("project_metadata"), dict) else {}
        for name in ("title", "domain", "objective", "phase"):
            if name in metadata:
                project[name] = copy.deepcopy(metadata[name])
        for field_name in fields:
            value = self._project_field_value(
                project_id,
                manifest,
                field_name,
                required=False,
            )
            if value is not None:
                project[field_name] = value
        contract_documents = self.load_v3_subhypothesis_contracts(project_id)
        executions = self.load_v3_retrieval_executions(project_id)
        project["sub_hypotheses"] = [
            self._v3_runtime_subhypothesis(document)
            for document in contract_documents
        ]
        project["research_question_retrieval_executions_v3"] = executions
        project["v3_research_question_state_schema_version"] = (
            V3_RESEARCH_QUESTION_STATE_SCHEMA_VERSION
        )
        graph_ref = manifest.get("active_research_evidence_graph_ref")
        if isinstance(graph_ref, dict):
            project["active_research_evidence_graph_ref"] = {
                key: copy.deepcopy(value)
                for key, value in graph_ref.items()
                if key != "path"
            }
        return project

    def load_tanxi_transition_context(self, project_id: str) -> dict[str, Any]:
        """Read the ZhiZhi→TanXi handoff without PaperGraph or full text."""
        manifest = self.get_project_manifest(project_id)
        contracts = self.load_v3_subhypothesis_contracts(project_id)
        executions = self.load_v3_retrieval_executions(project_id)
        execution_order = self._project_field_value(
            project_id,
            manifest,
            "subhypothesis_retrieval_execution_order",
            required=False,
        )
        statuses: dict[str, dict[str, Any]] = {}
        for document in contracts:
            sub_hypothesis_id = str(document.get("sub_hypothesis_id") or "")
            contract = document.get("research_question_contract") or {}
            execution = executions.get(sub_hypothesis_id) or {}
            statuses[sub_hypothesis_id] = {
                "research_question_contract_id": str(contract.get("contract_id") or ""),
                "contract_revision": str(
                    contract.get("contract_revision") or contract.get("declaration_hash") or ""
                ),
                "retrieval_execution_status": str(
                    execution.get("retrieval_execution_status") or execution.get("status") or "NOT_EXECUTED"
                ),
                "evidence_coverage_status": str(
                    execution.get("evidence_coverage_status") or "EMPTY"
                ),
                "aggregate_evidence_ready": bool(execution.get("aggregate_evidence_ready")),
                "required_direct_slot_ids": list(execution.get("required_direct_slot_ids") or []),
                "covered_direct_slot_ids": list(execution.get("covered_direct_slot_ids") or []),
                "missing_direct_slot_ids": list(execution.get("missing_direct_slot_ids") or []),
                "direct_evidence_paper_count": int(
                    execution.get("direct_evidence_paper_count") or 0
                ),
            }
        return {
            "schema_version": "tanxi_transition_context_v3",
            "project_id": project_id,
            "state_version": int(manifest.get("state_version") or 0),
            "subhypothesis_retrieval_execution_order": (
                copy.deepcopy(execution_order) if isinstance(execution_order, dict) else {}
            ),
            "retrieval_execution_status_by_sh": statuses,
            "subhypothesis_contract_count": len(contracts),
            "retrieval_execution_count": len(executions),
            "active_tanxi_input_manifest_ref": copy.deepcopy(
                manifest.get("active_tanxi_input_manifest_ref")
                if isinstance(manifest.get("active_tanxi_input_manifest_ref"), dict)
                else {}
            ),
        }

    def commit_v3_project_patch(
        self,
        project_id: str,
        *,
        field_updates: dict[str, Any],
        artifact_groups: tuple[str, ...] = ("gaps",),
        expected_version: int | None = None,
        operation: str = "COMMIT_V3_PROJECT_PATCH",
    ) -> dict[str, Any]:
        """Atomically update selected V3 project fields without full hydration."""
        if not field_updates:
            raise ScienceStateError("V3 project patch requires at least one field update")
        manifest = self.get_project_manifest(project_id)
        current_version = int(manifest.get("state_version") or 0)
        if expected_version is not None and int(expected_version) != current_version:
            raise StaleScienceStateError(
                f"stale science state for project {project_id}: expected version "
                f"{expected_version}, current version {current_version}"
            )
        api = self._manifest_api()
        writes: dict[str, Any] = {}
        updated = copy.deepcopy(manifest)
        field_refs = {
            str(key): copy.deepcopy(value)
            for key, value in (manifest.get("project_field_refs") or {}).items()
            if isinstance(value, dict)
        }
        for field_name, value in field_updates.items():
            name = str(field_name or "").strip()
            if not name or name.startswith("fragment_audit:"):
                raise ScienceStateError("Invalid V3 project patch field name")
            document = api["with_content_hash"]({
                "schema_version": "science_project_field_v1",
                "project_id": project_id,
                "field_name": name,
                "value": copy.deepcopy(value),
            })
            previous_ref = field_refs.get(name)
            if isinstance(previous_ref, dict) and str(previous_ref.get("content_hash") or "") == str(document["content_hash"]):
                continue
            version = int((previous_ref or {}).get("artifact_version") or 0) + 1
            path = self._next_artifact_path(
                f"project_fields/{_safe_identifier(name)}.json",
                artifact_version=version,
                previous_ref=previous_ref,
            )
            writes[path] = document
            field_refs[name] = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id),
                project_id=project_id,
                artifact_type="project_field",
                artifact_id=name,
                artifact_version=version,
                path=path,
                artifact_hash=str(document["content_hash"]),
            )
        if not writes:
            return {"status": "UNCHANGED", "project_id": project_id, "state_version": current_version}
        versions = {
            str(key): int(value or 0)
            for key, value in (manifest.get("artifact_versions") or {}).items()
        }
        for group in dict.fromkeys(artifact_groups):
            versions[str(group)] = int(versions.get(str(group)) or 0) + 1
        updated["project_field_refs"] = field_refs
        updated["artifact_versions"] = versions
        updated["state_version"] = current_version + 1
        updated["updated_at"] = time.time()
        updated["last_committed_transaction_id"] = "PENDING_TRANSACTION_ID"
        updated = api["finalize_manifest"](updated)
        result = self._commit_normalized_transaction(
            project_id,
            artifact_writes=writes,
            manifest=updated,
            expected_version=current_version,
            operation=operation,
        )
        return {
            "status": "COMMITTED",
            "project_id": project_id,
            "state_version": int(result.get("state_version") or current_version + 1),
            "updated_fields": sorted(field_updates),
        }

    def persist_tanxi_detector_result(
        self,
        project_id: str,
        *,
        input_fingerprint: str,
        detector_id: str,
        detector_result: dict[str, Any],
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Persist one completed detector as a V4 reference-only artifact."""
        normalized_detector_id = _safe_identifier(detector_id)
        if not normalized_detector_id or not str(input_fingerprint or ""):
            raise ScienceStateError(
                "TanXi detector result requires an input fingerprint and detector id"
            )
        try:
            try:
                from ._gap_detectors import compact_detector_result_for_persistence_v4
            except ImportError:
                from _gap_detectors import compact_detector_result_for_persistence_v4
            result = compact_detector_result_for_persistence_v4(
                detector_result if isinstance(detector_result, dict) else {}
            )
        except ValueError as exc:
            raise ScienceStateError(
                "TanXi detector persistence accepts only current "
                "gap_detector_result_v3 inputs"
            ) from exc
        result = _tanxi_reference_only_value(result)
        document = {
            "schema_version": "tanxi_detector_result_v4",
            "project_id": project_id,
            "input_fingerprint": str(input_fingerprint),
            "detector_id": str(detector_id),
            "result": copy.deepcopy(result),
        }
        api = self._manifest_api()
        document = api["with_content_hash"](document)
        manifest = self.get_project_manifest(project_id)
        current_version = int(manifest.get("state_version") or 0)
        if expected_version is not None and int(expected_version) != current_version:
            raise StaleScienceStateError(
                f"stale science state for project {project_id}: expected version "
                f"{expected_version}, current version {current_version}"
            )
        reference_key = f"{str(input_fingerprint)}:{str(detector_id)}"
        existing_refs = (
            manifest.get("tanxi_detector_result_refs")
            if isinstance(manifest.get("tanxi_detector_result_refs"), dict)
            else {}
        )
        # A detector checkpoint is resumable only for the exact evidence-view
        # fingerprint that produced it. Retaining every historical graph's
        # refs makes the manifest grow without enabling a valid V3 resume.
        # Detached artifacts remain immutable on disk for auditability.
        reference_prefix = f"{str(input_fingerprint)}:"
        refs = {
            str(key): copy.deepcopy(value)
            for key, value in existing_refs.items()
            if isinstance(value, dict) and str(key).startswith(reference_prefix)
        }
        previous_ref = refs.get(reference_key)
        if (
            isinstance(previous_ref, dict)
            and str(previous_ref.get("content_hash") or "")
            == str(document.get("content_hash") or "")
        ):
            if len(refs) == len(existing_refs):
                return {
                    "status": "UNCHANGED",
                    "project_id": project_id,
                    "state_version": current_version,
                    "artifact_ref": copy.deepcopy(previous_ref),
                }
            updated = copy.deepcopy(manifest)
            updated["tanxi_detector_result_refs"] = refs
            versions = {
                str(key): int(value or 0)
                for key, value in (manifest.get("artifact_versions") or {}).items()
            }
            versions["workflow"] = int(versions.get("workflow") or 0) + 1
            updated["artifact_versions"] = versions
            updated["state_version"] = current_version + 1
            updated["updated_at"] = time.time()
            updated["last_committed_transaction_id"] = "PENDING_TRANSACTION_ID"
            updated = api["finalize_manifest"](updated)
            transaction = self._commit_normalized_transaction(
                project_id,
                artifact_writes={},
                manifest=updated,
                expected_version=current_version,
                operation="PRUNE_STALE_TANXI_V3_DETECTOR_REFS",
            )
            return {
                "status": "PRUNED_STALE_REFS",
                "project_id": project_id,
                "state_version": int(transaction.get("state_version") or current_version + 1),
                "artifact_ref": copy.deepcopy(previous_ref),
            }
        version = int((previous_ref or {}).get("artifact_version") or 0) + 1
        fingerprint_key = _safe_identifier(str(input_fingerprint).removeprefix("sha256:"))
        path = (
            f"runs/tanxi_detectors/{fingerprint_key}/"
            f"{normalized_detector_id}/v{version:04d}.json"
        )
        ref = api["science_artifact_ref"](
            state_store_id=self.store_id(project_id),
            project_id=project_id,
            artifact_type="tanxi_detector_result",
            artifact_id=f"{fingerprint_key}:{normalized_detector_id}",
            artifact_version=version,
            path=path,
            artifact_hash=str(document["content_hash"]),
        )
        updated = copy.deepcopy(manifest)
        refs[reference_key] = ref
        updated["tanxi_detector_result_refs"] = refs
        versions = {
            str(key): int(value or 0)
            for key, value in (manifest.get("artifact_versions") or {}).items()
        }
        versions["workflow"] = int(versions.get("workflow") or 0) + 1
        updated["artifact_versions"] = versions
        updated["state_version"] = current_version + 1
        updated["updated_at"] = time.time()
        updated["last_committed_transaction_id"] = "PENDING_TRANSACTION_ID"
        updated = api["finalize_manifest"](updated)
        transaction = self._commit_normalized_transaction(
            project_id,
            artifact_writes={path: document},
            manifest=updated,
            expected_version=current_version,
            operation="PERSIST_TANXI_V3_DETECTOR_RESULT",
        )
        return {
            "status": "COMMITTED",
            "project_id": project_id,
            "state_version": int(transaction.get("state_version") or current_version + 1),
            "artifact_ref": ref,
        }

    def get_tanxi_detector_result(
        self,
        project_id: str,
        detector_result_ref: dict[str, Any],
        *,
        input_fingerprint: str,
        detector_id: str,
    ) -> dict[str, Any]:
        """Resolve one V4 reference detector artifact with identity checks."""
        document = self.resolve_ref(detector_result_ref)
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != "tanxi_detector_result_v4"
            or str(document.get("project_id") or "") != project_id
            or str(document.get("input_fingerprint") or "") != str(input_fingerprint)
            or str(document.get("detector_id") or "") != str(detector_id)
            or not isinstance(document.get("result"), dict)
            or document["result"].get("schema_version")
            != "gap_detector_result_reference_artifact_v4"
        ):
            raise ScienceStateError(
                "TanXi V4 detector checkpoint artifact identity or payload is invalid"
            )
        return copy.deepcopy(document["result"])

    def get_active_research_evidence_graph(
        self,
        project_id: str,
    ) -> dict[str, Any] | None:
        """Resolve the current detached evidence graph without loading a project."""
        return self.get_research_evidence_graph(project_id)

    def get_research_evidence_graph(
        self,
        project_id: str,
        graph_snapshot_ref: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Resolve one immutable detached graph by its V3 snapshot identity."""
        manifest = self.get_project_manifest(project_id)
        requested = graph_snapshot_ref if isinstance(graph_snapshot_ref, dict) else {}
        refs = [
            ref
            for ref in (manifest.get("research_evidence_graph_refs") or {}).values()
            if isinstance(ref, dict)
        ]
        active_ref = manifest.get("active_research_evidence_graph_ref")
        if isinstance(active_ref, dict):
            refs.append(active_ref)
        ref = next(
            (
                item
                for item in refs
                if (
                    not requested
                    or (
                        str(item.get("artifact_id") or "") == str(requested.get("graph_id") or "")
                        and int(item.get("artifact_version") or 0) == int(requested.get("graph_version") or 0)
                    )
                )
            ),
            None,
        )
        if not isinstance(ref, dict):
            return None
        snapshot = self.resolve_ref(ref)
        if not isinstance(snapshot, dict) or str(snapshot.get("project_id") or "") != project_id:
            raise ScienceStateError(
                f"Invalid detached research evidence graph artifact for {project_id}"
            )
        if requested and (
            str(snapshot.get("graph_id") or "") != str(requested.get("graph_id") or "")
            or int(snapshot.get("graph_version") or 0) != int(requested.get("graph_version") or 0)
            or (
                str(requested.get("input_fingerprint") or "")
                and str(snapshot.get("input_fingerprint") or "")
                != str(requested.get("input_fingerprint") or "")
            )
        ):
            raise ScienceStateError(
                f"Detached research evidence graph does not match requested V3 snapshot for {project_id}"
            )
        return snapshot

    def persist_tanxi_evidence_graph(
        self,
        project_id: str,
        *,
        evidence_view: dict[str, Any],
        expected_version: int | None = None,
        per_bucket_pair_limit: int = 64,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        """Build/cache one detached V3 graph from the narrow V2 evidence view.

        The active graph reference is manifest-level state.  The full snapshot
        is an immutable graph artifact and never becomes a giant project field.
        """
        try:
            from ._research_graph import (
                build_research_evidence_graph_from_tanxi_view,
                graph_snapshot_ref,
                tanxi_evidence_graph_input_fingerprint,
            )
        except ImportError:
            from _research_graph import (
                build_research_evidence_graph_from_tanxi_view,
                graph_snapshot_ref,
                tanxi_evidence_graph_input_fingerprint,
            )
        manifest = self.get_project_manifest(project_id)
        current_version = int(manifest.get("state_version") or 0)
        if expected_version is not None and int(expected_version) != current_version:
            raise StaleScienceStateError(
                f"stale science state for project {project_id}: expected version "
                f"{expected_version}, current version {current_version}"
            )
        graph_input_fingerprint = tanxi_evidence_graph_input_fingerprint(evidence_view)
        prior_ref = manifest.get("active_research_evidence_graph_ref")
        if (
            isinstance(prior_ref, dict)
            and str(prior_ref.get("input_fingerprint") or "") == graph_input_fingerprint
        ):
            prior_snapshot = self.resolve_ref(prior_ref)
            if (
                isinstance(prior_snapshot, dict)
                and str(prior_snapshot.get("schema_version") or "")
                == "research_evidence_graph_v4"
                and str(prior_snapshot.get("input_fingerprint") or "")
                == graph_input_fingerprint
            ):
                return {
                    "status": "CACHE_HIT",
                    "project_id": project_id,
                    "state_version": current_version,
                    "snapshot": prior_snapshot,
                    "graph_snapshot_ref": graph_snapshot_ref(prior_snapshot),
                    "artifact_ref": copy.deepcopy(prior_ref),
                }
        prior_snapshot = self.resolve_ref(prior_ref) if isinstance(prior_ref, dict) else None
        if (
            not isinstance(prior_snapshot, dict)
            or str(prior_snapshot.get("schema_version") or "") != "research_evidence_graph_v4"
        ):
            prior_snapshot = None
        snapshot = build_research_evidence_graph_from_tanxi_view(
            evidence_view,
            prior_snapshot=prior_snapshot,
            per_bucket_pair_limit=per_bucket_pair_limit,
            progress_callback=progress_callback,
        )
        api = self._manifest_api()
        graph_id = _safe_identifier(snapshot.get("graph_id"))
        graph_version = max(1, int(snapshot.get("graph_version") or 1))
        path = f"graphs/evidence/{graph_id}/v{graph_version:04d}.json"
        payload_hash = self._payload_reference_hash(snapshot)
        ref = api["science_artifact_ref"](
            state_store_id=self.store_id(project_id),
            project_id=project_id,
            artifact_type="research_evidence_graph",
            artifact_id=str(snapshot.get("graph_id") or ""),
            artifact_version=graph_version,
            path=path,
            artifact_hash=payload_hash,
        )
        ref["input_fingerprint"] = str(snapshot.get("input_fingerprint") or "")
        updated = copy.deepcopy(manifest)
        versions = {
            str(key): int(value or 0)
            for key, value in (manifest.get("artifact_versions") or {}).items()
        }
        versions["graphs"] = int(versions.get("graphs") or 0) + 1
        updated["artifact_versions"] = versions
        updated["active_research_evidence_graph_ref"] = ref
        graph_refs = {
            str(key): copy.deepcopy(value)
            for key, value in (manifest.get("research_evidence_graph_refs") or {}).items()
            if isinstance(value, dict)
        }
        graph_refs[f"{snapshot.get('graph_id')}:v{graph_version:04d}"] = ref
        updated["research_evidence_graph_refs"] = graph_refs
        updated["state_version"] = current_version + 1
        updated["updated_at"] = time.time()
        updated["last_committed_transaction_id"] = "PENDING_TRANSACTION_ID"
        updated = api["finalize_manifest"](updated)
        result = self._commit_normalized_transaction(
            project_id,
            artifact_writes={path: snapshot},
            manifest=updated,
            expected_version=current_version,
            operation="PERSIST_TANXI_EVIDENCE_GRAPH",
        )
        return {
            "status": "COMMITTED",
            "project_id": project_id,
            "state_version": int(result.get("state_version") or current_version + 1),
            "snapshot": snapshot,
            "graph_snapshot_ref": graph_snapshot_ref(snapshot),
            "artifact_ref": ref,
        }

    def save_paper(
        self,
        project_id: str,
        paper: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        paper_id = str(paper.get("paper_id") or paper.get("id") or "").strip()
        if not paper_id:
            raise ScienceStateError("Paper artifact requires paper_id")
        payload = externalize_paper_fulltext(copy.deepcopy(paper))
        return self._save_ref_artifact(
            project_id,
            payload=payload,
            artifact_type="paper",
            artifact_id=paper_id,
            artifact_version=0,
            base_path=f"papers/{_safe_identifier(paper_id)}.json",
            ref_field="paper_refs",
            ref_key=paper_id,
            artifact_group="papers",
            expected_version=expected_version,
            id_field="paper_ids",
        )

    def commit_prepared_candidate(
        self,
        project_id: str,
        *,
        paper: dict[str, Any],
        evidence_record: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Commit one prepared paper and its immutable evidence artifacts.

        This transaction never materializes the project or reads unrelated
        paper artifacts. Only the compact evidence-summary project field is
        updated alongside the current paper and affected registry shards.
        """

        manifest = self.get_project_manifest(project_id)
        current_version = int(manifest.get("state_version") or 0)
        if expected_version is not None and int(expected_version) != current_version:
            raise StaleScienceStateError(
                f"stale science state for project {project_id}: expected version "
                f"{expected_version}, current version {current_version}"
            )
        paper_id = str(paper.get("paper_id") or paper.get("id") or "").strip()
        if not paper_id:
            raise ScienceStateError("Prepared candidate transaction requires paper_id")

        started_at = time.perf_counter()
        copy_started_at = time.perf_counter()
        wrapper = {
            "papergraph": [copy.deepcopy(paper)],
            "evidence": [copy.deepcopy(evidence_record)] if isinstance(evidence_record, dict) else [],
        }
        deepcopy_ms = round((time.perf_counter() - copy_started_at) * 1000, 2)
        compact_project_for_persistence(wrapper)
        paper_payload = wrapper["papergraph"][0]
        paper_payload.setdefault("paper_id", paper_id)
        externalize_paper_fulltext(paper_payload)
        compact_evidence = (
            wrapper["evidence"][0]
            if wrapper.get("evidence") and isinstance(wrapper["evidence"][0], dict)
            else None
        )

        new_version = current_version + 1
        evidence_started_at = time.perf_counter()
        evidence_writes, evidence_refs, evidence_stats = self._externalize_v4_evidence_records(
            project_id,
            [paper_payload],
            state_version=new_version,
            existing_span_registry_ref=(
                manifest.get("source_span_registry_root_ref")
                if isinstance(manifest.get("source_span_registry_root_ref"), dict)
                else None
            ),
            existing_assertion_registry_ref=(
                manifest.get("assertion_registry_root_ref")
                if isinstance(manifest.get("assertion_registry_root_ref"), dict)
                else None
            ),
        )
        evidence_externalization_ms = round(
            (time.perf_counter() - evidence_started_at) * 1000,
            2,
        )

        api = self._manifest_api()
        writes: dict[str, Any] = dict(evidence_writes)
        updated = copy.deepcopy(manifest)
        paper_refs = {
            str(key): copy.deepcopy(value)
            for key, value in (manifest.get("paper_refs") or {}).items()
            if isinstance(value, dict)
        }
        old_paper_ref = paper_refs.get(paper_id)
        hash_started_at = time.perf_counter()
        paper_hash = self._payload_reference_hash(paper_payload)
        paper_hash_scan_ms = round((time.perf_counter() - hash_started_at) * 1000, 2)
        if not old_paper_ref or str(old_paper_ref.get("content_hash") or "") != paper_hash:
            paper_version = int((old_paper_ref or {}).get("artifact_version") or 0) + 1
            paper_path = self._next_artifact_path(
                f"papers/{_safe_identifier(paper_id)}.json",
                artifact_version=paper_version,
                previous_ref=old_paper_ref,
            )
            writes[paper_path] = paper_payload
            paper_refs[paper_id] = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id),
                project_id=project_id,
                artifact_type="paper",
                artifact_id=paper_id,
                artifact_version=paper_version,
                path=paper_path,
                artifact_hash=paper_hash,
            )

        project_field_refs = {
            str(key): copy.deepcopy(value)
            for key, value in (manifest.get("project_field_refs") or {}).items()
            if isinstance(value, dict)
        }
        evidence_field_changed = False
        if compact_evidence is not None:
            evidence_values = self._project_field_value(
                project_id,
                manifest,
                "evidence",
                required=False,
            )
            evidence_values = [
                dict(item) for item in evidence_values if isinstance(item, dict)
            ] if isinstance(evidence_values, list) else []
            replaced = False
            for index, item in enumerate(evidence_values):
                if str(item.get("paper_id") or "") == paper_id:
                    evidence_values[index] = compact_evidence
                    replaced = True
                    break
            if not replaced:
                evidence_values.append(compact_evidence)
            evidence_document = api["with_content_hash"]({
                "schema_version": "science_project_field_v1",
                "project_id": project_id,
                "field_name": "evidence",
                "value": evidence_values,
            })
            old_evidence_ref = project_field_refs.get("evidence")
            if (
                not old_evidence_ref
                or str(old_evidence_ref.get("content_hash") or "")
                != str(evidence_document.get("content_hash") or "")
            ):
                evidence_field_version = int(
                    (old_evidence_ref or {}).get("artifact_version") or 0
                ) + 1
                evidence_path = self._next_artifact_path(
                    "project_fields/evidence.json",
                    artifact_version=evidence_field_version,
                    previous_ref=old_evidence_ref,
                )
                writes[evidence_path] = evidence_document
                evidence_field_changed = True
                project_field_refs["evidence"] = api["science_artifact_ref"](
                    state_store_id=self.store_id(project_id),
                    project_id=project_id,
                    artifact_type="project_field",
                    artifact_id="evidence",
                    artifact_version=evidence_field_version,
                    path=evidence_path,
                    artifact_hash=str(evidence_document["content_hash"]),
                )

        if not writes:
            return {
                "status": "UNCHANGED",
                "project_id": project_id,
                "state_version": current_version,
                "paper_ref": copy.deepcopy(old_paper_ref or {}),
                "artifact_refs": {
                    "document_artifact_refs": copy.deepcopy(
                        paper_payload.get("document_artifact_refs") or {}
                    ),
                },
                "paper": paper_payload,
                "evidence_record": compact_evidence,
                "metrics": {
                    "project_materialization_ms": 0.0,
                    "project_deepcopy_ms": deepcopy_ms,
                    "paper_hash_scan_ms": paper_hash_scan_ms,
                    "transaction_encode_ms": 0.0,
                    "transaction_write_ms": 0.0,
                    "refresh_materialization_ms": 0.0,
                },
            }

        updated["paper_refs"] = paper_refs
        paper_ids = [str(item) for item in manifest.get("paper_ids", []) if str(item)]
        if paper_id not in paper_ids:
            paper_ids.append(paper_id)
        updated["paper_ids"] = paper_ids
        updated["project_field_refs"] = project_field_refs
        updated.update(evidence_refs)
        prior_storage = (
            dict(manifest.get("evidence_storage") or {})
            if isinstance(manifest.get("evidence_storage"), dict)
            else {}
        )
        updated["evidence_storage"] = {
            **prior_storage,
            "schema_version": "research_question_evidence_storage_v4",
            "last_transaction_new_source_spans": int(
                evidence_stats.get("new_source_spans") or 0
            ),
            "last_transaction_new_assertions": int(
                evidence_stats.get("new_assertions") or 0
            ),
            "registry_schema_version": str(
                evidence_stats.get("registry_schema_version") or ""
            ),
            "materialization_policy": (
                "incremental_paper_delta; source spans and assertions random-read through registries"
            ),
        }
        versions = {
            str(key): int(value or 0)
            for key, value in (manifest.get("artifact_versions") or {}).items()
        }
        if paper_refs.get(paper_id) != old_paper_ref:
            versions["papers"] = int(versions.get("papers") or 0) + 1
        if evidence_writes:
            versions["evidence"] = int(versions.get("evidence") or 0) + 1
        if evidence_field_changed:
            versions["project"] = int(versions.get("project") or 0) + 1
        updated["artifact_versions"] = versions
        updated["state_version"] = new_version
        updated["updated_at"] = time.time()
        updated["last_committed_transaction_id"] = "PENDING_TRANSACTION_ID"
        encode_started_at = time.perf_counter()
        updated = api["finalize_manifest"](updated)
        transaction_encode_ms = round(
            (time.perf_counter() - encode_started_at) * 1000,
            2,
        )
        write_started_at = time.perf_counter()
        result = self._commit_normalized_transaction(
            project_id,
            artifact_writes=writes,
            manifest=updated,
            expected_version=current_version,
            operation="COMMIT_PREPARED_LITERATURE_CANDIDATE",
        )
        transaction_write_ms = round(
            (time.perf_counter() - write_started_at) * 1000,
            2,
        )
        return {
            "status": "COMMITTED",
            "project_id": project_id,
            "state_version": int(result.get("state_version") or new_version),
            "paper_ref": copy.deepcopy(paper_refs.get(paper_id) or {}),
            "artifact_refs": {
                **{key: copy.deepcopy(value) for key, value in evidence_refs.items()},
                "document_artifact_refs": copy.deepcopy(
                    paper_payload.get("document_artifact_refs") or {}
                ),
            },
            "paper": paper_payload,
            "evidence_record": compact_evidence,
            "metrics": {
                "project_materialization_ms": 0.0,
                "project_deepcopy_ms": deepcopy_ms,
                "paper_hash_scan_ms": paper_hash_scan_ms,
                "evidence_externalization_ms": evidence_externalization_ms,
                "transaction_encode_ms": transaction_encode_ms,
                "transaction_write_ms": transaction_write_ms,
                "refresh_materialization_ms": 0.0,
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
            },
        }

    def get_gap(self, project_id: str, gap_id: str) -> dict[str, Any]:
        manifest = self.get_project_manifest(project_id)
        ref = (manifest.get("gap_refs") or {}).get(str(gap_id))
        if not isinstance(ref, dict):
            raise ScienceStateError(f"Unknown gap_id for project {project_id}: {gap_id}")
        payload = self.resolve_ref(ref)
        if not isinstance(payload, dict):
            raise ScienceStateError(f"Gap artifact is not an object: {gap_id}")
        return payload

    def _commit_existing_gap_chain(
        self,
        project_id: str,
        gap_id: str,
        *,
        gap_override: dict[str, Any] | None = None,
        bundle_override: dict[str, Any] | None = None,
        contract_override: dict[str, Any] | None = None,
        expected_version: int | None = None,
        operation: str,
    ) -> dict[str, Any]:
        try:
            from ._science_artifacts import artifact_content_hash, validate_normalized_artifact
        except ImportError:
            from _science_artifacts import artifact_content_hash, validate_normalized_artifact
        manifest = self.get_project_manifest(project_id)
        current_version = int(manifest.get("state_version") or 0)
        if expected_version is not None and int(expected_version) != current_version:
            raise StaleScienceStateError(
                f"stale science state for project {project_id}: expected version "
                f"{expected_version}, current version {current_version}"
            )
        old_gap_ref = (manifest.get("gap_refs") or {}).get(gap_id)
        old_bundle_ref = (manifest.get("bundle_refs") or {}).get(gap_id)
        old_contract_ref = (manifest.get("contract_refs") or {}).get(gap_id)
        old_report_ref = (manifest.get("report_refs") or {}).get(gap_id)
        if not all(isinstance(item, dict) for item in (old_gap_ref, old_bundle_ref, old_contract_ref)):
            raise ScienceStateError(
                f"Gap chain is incomplete for {gap_id}; create gap/bundle/contract as one artifact set."
            )
        gap = copy.deepcopy(gap_override or self.resolve_ref(old_gap_ref))
        bundle = copy.deepcopy(bundle_override or self.resolve_ref(old_bundle_ref))
        contract = copy.deepcopy(contract_override or self.resolve_ref(old_contract_ref))
        if any(str(item.get("project_id") or "") != project_id for item in (gap, bundle, contract)):
            raise ScienceStateError("Gap chain project identity mismatch")
        if any(str(item.get("gap_id") or "") != gap_id for item in (gap, bundle, contract)):
            raise ScienceStateError("Gap chain gap identity mismatch")

        api = self._manifest_api()
        writes: dict[str, Any] = {}
        bundle_hash_before = self._payload_reference_hash(bundle)
        bundle_changed = bundle_hash_before != str(old_bundle_ref.get("content_hash") or "")
        if bundle_changed:
            bundle_version = int(old_bundle_ref.get("artifact_version") or 0) + 1
            bundle["bundle_version"] = bundle_version
            bundle["content_hash"] = artifact_content_hash(bundle)
            bundle_path = f"bundles/{_safe_identifier(gap_id)}/v{bundle_version:04d}.json"
            writes[bundle_path] = bundle
            bundle_ref = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id), project_id=project_id,
                artifact_type="bundle", artifact_id=gap_id,
                artifact_version=bundle_version, path=bundle_path,
                artifact_hash=str(bundle["content_hash"]),
            )
        else:
            bundle_ref = copy.deepcopy(old_bundle_ref)
            bundle_path = str(bundle_ref["path"])

        gap_version = int(old_gap_ref.get("artifact_version") or 0) + 1
        contract_version = int(old_contract_ref.get("artifact_version") or 0) + 1
        gap_path = self._next_artifact_path(
            f"gaps/{_safe_identifier(gap_id)}.json",
            artifact_version=gap_version,
            previous_ref=old_gap_ref,
        )
        contract_path = f"contracts/{_safe_identifier(gap_id)}/v{contract_version:04d}.json"
        gap["gap_version"] = gap_version
        gap["evidence_bundle_ref"] = bundle_path
        gap["latest_contract_ref"] = contract_path
        gap["content_hash"] = artifact_content_hash(gap)
        contract["contract_version"] = contract_version
        contract["gap_ref"] = gap_path
        contract["gap_snapshot_hash"] = str(gap["content_hash"])
        contract["evidence_bundle_ref"] = bundle_path
        contract["evidence_bundle_hash"] = str(bundle_ref["content_hash"])
        contract["content_hash"] = artifact_content_hash(contract)
        validate_normalized_artifact(gap)
        validate_normalized_artifact(bundle)
        validate_normalized_artifact(contract)
        writes[gap_path] = gap
        writes[contract_path] = contract
        gap_ref = api["science_artifact_ref"](
            state_store_id=self.store_id(project_id), project_id=project_id,
            artifact_type="gap", artifact_id=gap_id,
            artifact_version=gap_version, path=gap_path,
            artifact_hash=str(gap["content_hash"]),
        )
        contract_ref = api["science_artifact_ref"](
            state_store_id=self.store_id(project_id), project_id=project_id,
            artifact_type="contract", artifact_id=gap_id,
            artifact_version=contract_version, path=contract_path,
            artifact_hash=str(contract["content_hash"]),
        )

        report_ref = copy.deepcopy(old_report_ref) if isinstance(old_report_ref, dict) else None
        if isinstance(old_report_ref, dict):
            report = self.resolve_ref(old_report_ref)
            report_version = int(old_report_ref.get("artifact_version") or 0) + 1
            run_id = str(report.get("run_id") or f"state_{current_version + 1:04d}")
            report_path = (
                f"reports/{_safe_identifier(run_id)}_{_safe_identifier(gap_id)}"
                f".v{report_version:04d}.json"
            )
            report["contract_ref"] = contract_path
            report["content_hash"] = artifact_content_hash(report)
            validate_normalized_artifact(report)
            writes[report_path] = report
            report_ref = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id), project_id=project_id,
                artifact_type="report", artifact_id=f"{run_id}:{gap_id}",
                artifact_version=report_version, path=report_path,
                artifact_hash=str(report["content_hash"]),
            )

        updated = copy.deepcopy(manifest)
        updated.setdefault("gap_refs", {})[gap_id] = gap_ref
        updated.setdefault("bundle_refs", {})[gap_id] = bundle_ref
        updated.setdefault("contract_refs", {})[gap_id] = contract_ref
        if isinstance(report_ref, dict):
            updated.setdefault("report_refs", {})[gap_id] = report_ref
            if (
                isinstance(updated.get("latest_report_ref"), dict)
                and updated["latest_report_ref"].get("artifact_id") == old_report_ref.get("artifact_id")
            ):
                updated["latest_report_ref"] = copy.deepcopy(report_ref)
        versions = dict(updated.get("artifact_versions") or {})
        version_groups = ["gaps", "contracts"]
        if bundle_changed:
            version_groups.append("bundles")
        for group in version_groups:
            versions[group] = int(versions.get(group, 0)) + 1
        if isinstance(report_ref, dict):
            versions["reports"] = int(versions.get("reports", 0)) + 1
        updated["artifact_versions"] = versions
        updated["state_version"] = current_version + 1
        updated["updated_at"] = time.time()
        updated["last_committed_transaction_id"] = "PENDING_TRANSACTION_ID"
        updated = api["finalize_manifest"](updated)
        result = self._commit_normalized_transaction(
            project_id,
            artifact_writes=writes,
            manifest=updated,
            expected_version=current_version,
            operation=operation,
        )
        result.update({
            "status": "COMMITTED",
            "gap_ref": gap_ref,
            "bundle_ref": bundle_ref,
            "contract_ref": contract_ref,
            "report_ref": report_ref,
        })
        return result

    def save_gap(
        self,
        project_id: str,
        gap: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        try:
            from ._science_artifacts import validate_normalized_artifact
        except ImportError:
            from _science_artifacts import validate_normalized_artifact
        validate_normalized_artifact(gap)
        gap_id = str(gap.get("gap_id") or "")
        if str(gap.get("project_id") or "") != str(project_id):
            raise ScienceStateError("Gap artifact project mismatch")
        return self._commit_existing_gap_chain(
            project_id,
            gap_id,
            gap_override=copy.deepcopy(gap),
            expected_version=expected_version,
            operation="SAVE_GAP_CHAIN",
        )

    def _get_latest_ref_artifact(
        self,
        project_id: str,
        ref_field: str,
        ref_key: str,
        label: str,
    ) -> dict[str, Any]:
        manifest = self.get_project_manifest(project_id)
        ref = (manifest.get(ref_field) or {}).get(str(ref_key))
        if not isinstance(ref, dict):
            raise ScienceStateError(f"Unknown {label} for project {project_id}: {ref_key}")
        payload = self.resolve_ref(ref)
        if not isinstance(payload, dict):
            raise ScienceStateError(f"{label} artifact is not an object: {ref_key}")
        return payload

    def _get_historical_versioned_artifact(
        self,
        project_id: str,
        *,
        directory: str,
        identity_key: str,
        identity_value: str,
        version_key: str,
        version: int,
        label: str,
    ) -> dict[str, Any]:
        root = self._normalized_artifact_path(project_id, directory)
        matches: list[dict[str, Any]] = []
        if root.is_dir():
            for path in sorted(root.glob("*.json")):
                payload = self._reader(path, f"Historical {label} artifact disappeared: {path}")
                if (
                    str(payload.get(identity_key) or "") == str(identity_value)
                    and int(payload.get(version_key) or 0) == int(version)
                ):
                    matches.append(payload)
        unique = {
            self._payload_reference_hash(item): item for item in matches
        }
        if not unique:
            raise ScienceStateError(
                f"Unknown {label} version for project {project_id}: {identity_value}@{version}"
            )
        if len(unique) > 1:
            raise ScienceStateError(
                f"Ambiguous {label} version for project {project_id}: {identity_value}@{version}"
            )
        return copy.deepcopy(next(iter(unique.values())))

    def get_bundle(self, project_id: str, gap_id: str, version: int | None = None) -> dict[str, Any]:
        bundle = self._get_latest_ref_artifact(project_id, "bundle_refs", gap_id, "bundle")
        if version is None or int(bundle.get("bundle_version") or 0) == int(version):
            return bundle
        return self._get_historical_versioned_artifact(
            project_id,
            directory=f"bundles/{_safe_identifier(gap_id)}",
            identity_key="gap_id",
            identity_value=gap_id,
            version_key="bundle_version",
            version=int(version),
            label="bundle",
        )

    def save_bundle(
        self,
        project_id: str,
        gap_id: str,
        bundle: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        try:
            from ._science_artifacts import validate_normalized_artifact
        except ImportError:
            from _science_artifacts import validate_normalized_artifact
        validate_normalized_artifact(bundle)
        if str(bundle.get("project_id") or "") != project_id or str(bundle.get("gap_id") or "") != gap_id:
            raise ScienceStateError("Evidence bundle identity mismatch")
        return self._commit_existing_gap_chain(
            project_id,
            gap_id,
            bundle_override=copy.deepcopy(bundle),
            expected_version=expected_version,
            operation="SAVE_BUNDLE_CHAIN",
        )

    def get_contract(self, project_id: str, gap_id: str, version: int | None = None) -> dict[str, Any]:
        contract = self._get_latest_ref_artifact(project_id, "contract_refs", gap_id, "contract")
        if version is None or int(contract.get("contract_version") or 0) == int(version):
            return contract
        return self._get_historical_versioned_artifact(
            project_id,
            directory=f"contracts/{_safe_identifier(gap_id)}",
            identity_key="gap_id",
            identity_value=gap_id,
            version_key="contract_version",
            version=int(version),
            label="contract",
        )

    def save_contract(
        self,
        project_id: str,
        gap_id: str,
        contract: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        try:
            from ._science_artifacts import validate_normalized_artifact
        except ImportError:
            from _science_artifacts import validate_normalized_artifact
        validate_normalized_artifact(contract)
        if str(contract.get("project_id") or "") != project_id or str(contract.get("gap_id") or "") != gap_id:
            raise ScienceStateError("Socrates contract identity mismatch")
        return self._commit_existing_gap_chain(
            project_id,
            gap_id,
            contract_override=copy.deepcopy(contract),
            expected_version=expected_version,
            operation="SAVE_CONTRACT_CHAIN",
        )

    def save_run_summary(
        self,
        project_id: str,
        run_id: str,
        summary: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        return self._save_ref_artifact(
            project_id,
            payload=copy.deepcopy(summary),
            artifact_type="run_summary",
            artifact_id=run_id,
            artifact_version=0,
            base_path=f"runs/{_safe_identifier(run_id)}.summary.json",
            ref_field="run_summary_refs",
            ref_key=run_id,
            artifact_group="runs",
            expected_version=expected_version,
            latest_ref_field="latest_run_summary_ref",
            latest_run_id=run_id,
        )

    def save_report(
        self,
        project_id: str,
        run_id: str,
        report: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        result = self._save_ref_artifact(
            project_id,
            payload=copy.deepcopy(report),
            artifact_type="report",
            artifact_id=run_id,
            artifact_version=0,
            base_path=f"reports/{_safe_identifier(run_id)}.json",
            ref_field="report_refs",
            ref_key=run_id,
            artifact_group="reports",
            expected_version=expected_version,
            latest_ref_field="latest_report_ref",
            latest_run_id=run_id,
        )
        return result

    def save_fragments(
        self,
        project_id: str,
        fragments: list[dict[str, Any]],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Persist canonical fragments as indexed immutable JSONL generations."""
        try:
            from ._science_artifacts import validate_normalized_artifact
            from ._science_manifest import (
                encode_indexed_jsonl,
                fragment_index_document,
                fragment_registry_document,
            )
        except ImportError:
            from _science_artifacts import validate_normalized_artifact
            from _science_manifest import (
                encode_indexed_jsonl,
                fragment_index_document,
                fragment_registry_document,
            )
        manifest = self.get_project_manifest(project_id)
        current_version = int(manifest.get("state_version") or 0)
        if expected_version is not None and int(expected_version) != current_version:
            raise StaleScienceStateError(
                f"stale science state for project {project_id}: expected version "
                f"{expected_version}, current version {current_version}"
            )
        registry_ref = manifest.get("fragment_registry_ref")
        if isinstance(registry_ref, dict):
            registry = self.resolve_ref(registry_ref)
        else:
            try:
                from ._science_manifest import fragment_registry_document
            except ImportError:
                from _science_manifest import fragment_registry_document
            registry = fragment_registry_document({})
        entries = dict(registry.get("entries") or {})
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        unchanged: list[str] = []
        for fragment in fragments:
            validate_normalized_artifact(fragment)
            fragment_id = str(fragment.get("fragment_id") or "")
            if fragment_id in entries:
                existing = entries[fragment_id]
                if str(existing.get("content_hash") or "") != str(fragment.get("content_hash") or ""):
                    raise ScienceStateError(
                        f"Canonical fragment ID collision with different content: {fragment_id}"
                    )
                unchanged.append(fragment_id)
                continue
            key = (
                _safe_identifier(fragment.get("alignment_contract_hash")),
                _safe_identifier(fragment.get("paper_id")),
            )
            if not all(key):
                raise ScienceStateError("Canonical fragment requires alignment contract and paper identity")
            grouped.setdefault(key, []).append(copy.deepcopy(fragment))
        if not grouped:
            return {
                "status": "UNCHANGED",
                "state_version": current_version,
                "fragment_ids": unchanged,
                "new_fragment_count": 0,
            }

        writes: dict[str, Any] = {}
        generation = current_version + 1
        for (alignment_hash, paper_id), records in grouped.items():
            has_prior_group = any(
                str(item.get("alignment_contract_hash") or "") == alignment_hash
                and _safe_identifier(item.get("paper_id")) == paper_id
                for item in entries.values()
                if isinstance(item, dict)
            )
            suffix = f".v{generation:04d}" if has_prior_group else ""
            jsonl_path = f"fragments/{alignment_hash}/{paper_id}{suffix}.jsonl"
            index_path = f"fragments/{alignment_hash}/{paper_id}{suffix}.index.json"
            jsonl_bytes, local_index = encode_indexed_jsonl(records)
            index_document = fragment_index_document(
                alignment_contract_hash=alignment_hash,
                paper_id=str(records[0].get("paper_id") or paper_id),
                jsonl_path=jsonl_path,
                entries=local_index,
            )
            writes[jsonl_path] = jsonl_bytes
            writes[index_path] = index_document
            file_hash = "sha256:" + sha256(jsonl_bytes).hexdigest()
            for fragment in records:
                fragment_id = str(fragment["fragment_id"])
                location = local_index[fragment_id]
                entries[fragment_id] = {
                    "alignment_contract_hash": alignment_hash,
                    "paper_id": str(fragment.get("paper_id") or ""),
                    "file": jsonl_path,
                    "index_file": index_path,
                    "offset": int(location["offset"]),
                    "length": int(location["length"]),
                    "file_hash": file_hash,
                    "content_hash": str(fragment.get("content_hash") or ""),
                }

        new_registry = fragment_registry_document(entries)
        prior_registry_ref = registry_ref if isinstance(registry_ref, dict) else None
        registry_version = int((prior_registry_ref or {}).get("artifact_version") or 0) + 1
        registry_path = self._next_artifact_path(
            "fragments/fragment_registry.json",
            artifact_version=registry_version,
            previous_ref=prior_registry_ref,
        )
        writes[registry_path] = new_registry
        api = self._manifest_api()
        new_registry_ref = api["science_artifact_ref"](
            state_store_id=self.store_id(project_id),
            project_id=project_id,
            artifact_type="fragment_registry",
            artifact_id="fragment_registry",
            artifact_version=registry_version,
            path=registry_path,
            artifact_hash=str(new_registry["content_hash"]),
        )
        updated = copy.deepcopy(manifest)
        updated["fragment_registry_ref"] = new_registry_ref
        versions = dict(updated.get("artifact_versions") or {})
        versions["fragments"] = int(versions.get("fragments", 0)) + 1
        updated["artifact_versions"] = versions
        updated["state_version"] = current_version + 1
        updated["updated_at"] = time.time()
        updated["last_committed_transaction_id"] = "PENDING_TRANSACTION_ID"
        updated = api["finalize_manifest"](updated)
        result = self._commit_normalized_transaction(
            project_id,
            artifact_writes=writes,
            manifest=updated,
            expected_version=current_version,
            operation="SAVE_CANONICAL_FRAGMENTS",
        )
        result.update({
            "status": "COMMITTED",
            "fragment_ids": [str(item["fragment_id"]) for values in grouped.values() for item in values],
            "unchanged_fragment_ids": unchanged,
            "new_fragment_count": sum(len(values) for values in grouped.values()),
            "fragment_registry_ref": new_registry_ref,
        })
        return result

    def get_fragment(self, project_id: str, fragment_id: str) -> dict[str, Any]:
        """Random-read one fragment through the registry without scanning JSONL."""
        manifest = self.get_project_manifest(project_id)
        registry_ref = manifest.get("fragment_registry_ref")
        if not isinstance(registry_ref, dict):
            raise ScienceStateError(f"Project has no fragment registry: {project_id}")
        registry = self.resolve_ref(registry_ref)
        entry = (registry.get("entries") or {}).get(str(fragment_id))
        if not isinstance(entry, dict):
            raise ScienceStateError(f"Unknown fragment_id for project {project_id}: {fragment_id}")
        jsonl_path = self._normalized_artifact_path(project_id, str(entry.get("file") or ""))
        offset = int(entry.get("offset") or 0)
        length = int(entry.get("length") or 0)
        file_size = jsonl_path.stat().st_size
        if offset < 0 or length <= 0 or offset + length > file_size:
            raise ScienceStateError(f"Invalid fragment byte index for {fragment_id}")
        with jsonl_path.open("rb") as stream:
            stream.seek(offset)
            encoded_fragment = stream.read(length)
        if len(encoded_fragment) != length:
            raise ScienceStateError(f"Short fragment read for {fragment_id}")
        fragment = json.loads(encoded_fragment.decode("utf-8"))
        if str(fragment.get("fragment_id") or "") != str(fragment_id):
            raise ScienceStateError(f"Fragment registry points to a different record: {fragment_id}")
        if self._payload_reference_hash(fragment) != str(entry.get("content_hash") or ""):
            raise ScienceStateError(f"Canonical fragment content hash mismatch: {fragment_id}")
        return fragment

    def append_fragment_audit(
        self,
        project_id: str,
        run_id: str,
        fragments: list[dict[str, Any]],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Append audit records by committing a new immutable JSONL generation."""
        manifest = self.get_project_manifest(project_id)
        current_version = int(manifest.get("state_version") or 0)
        if expected_version is not None and int(expected_version) != current_version:
            raise StaleScienceStateError(
                f"stale science state for project {project_id}: expected version "
                f"{expected_version}, current version {current_version}"
            )
        ref_key = f"fragment_audit:{run_id}"
        previous_ref = (manifest.get("project_field_refs") or {}).get(ref_key)
        previous_records: list[dict[str, Any]] = []
        if isinstance(previous_ref, dict):
            prior_bytes = self.resolve_ref(previous_ref)
            if not isinstance(prior_bytes, bytes):
                raise ScienceStateError("Fragment audit reference does not resolve to JSONL bytes")
            previous_records = [
                json.loads(line.decode("utf-8"))
                for line in prior_bytes.splitlines()
                if line.strip()
            ]
        combined = [*previous_records, *(copy.deepcopy(item) for item in fragments if isinstance(item, dict))]
        body = b"".join(
            self._manifest_api()["canonical_json_bytes"](item) + b"\n"
            for item in combined
        )
        artifact_hash = "sha256:" + sha256(body).hexdigest()
        if isinstance(previous_ref, dict) and previous_ref.get("content_hash") == artifact_hash:
            return {"status": "UNCHANGED", "state_version": current_version, "ref": previous_ref}
        version = int((previous_ref or {}).get("artifact_version") or 0) + 1
        path = self._next_artifact_path(
            f"audits/fragment_candidates/{_safe_identifier(run_id)}.jsonl",
            artifact_version=version,
            previous_ref=previous_ref if isinstance(previous_ref, dict) else None,
        )
        api = self._manifest_api()
        ref = api["science_artifact_ref"](
            state_store_id=self.store_id(project_id),
            project_id=project_id,
            artifact_type="fragment_candidate_audit",
            artifact_id=run_id,
            artifact_version=version,
            path=path,
            artifact_hash=artifact_hash,
        )
        updated = self._manifest_after_ref_update(
            manifest,
            ref_field="project_field_refs",
            ref_key=ref_key,
            ref=ref,
            artifact_group="fragments",
        )
        result = self._commit_normalized_transaction(
            project_id,
            artifact_writes={path: body},
            manifest=updated,
            expected_version=current_version,
            operation="APPEND_FRAGMENT_AUDIT",
        )
        result.update({"status": "COMMITTED", "ref": ref, "record_count": len(combined)})
        return result

    def _iter_manifest_reference_objects(self, manifest: dict[str, Any]):
        for field in (
            "paper_refs", "gap_refs", "bundle_refs", "contract_refs",
            "report_refs", "run_summary_refs", "project_field_refs",
            "research_evidence_graph_refs", "tanxi_detector_result_refs",
        ):
            values = manifest.get(field)
            if isinstance(values, dict):
                for ref in values.values():
                    if isinstance(ref, dict):
                        yield ref
        for field in (
            "latest_report_ref", "latest_run_summary_ref", "fragment_registry_ref",
            "paper_index_ref", "source_span_registry_ref", "assertion_registry_ref",
            "source_span_registry_root_ref", "assertion_registry_root_ref",
            "active_research_evidence_graph_ref",
        ):
            ref = manifest.get(field)
            if isinstance(ref, dict):
                yield ref

    def _verify_manifest_references_unlocked(self, project_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        api = self._manifest_api()
        checked = 0
        errors: list[str] = []
        for ref in self._iter_manifest_reference_objects(manifest):
            try:
                api["validate_science_artifact_ref"](
                    ref,
                    state_store_id=self.store_id(project_id),
                    project_id=project_id,
                )
                if self._is_temporary_transaction_artifact_path(str(ref.get("path") or "")):
                    raise ScienceStateError(
                        "Manifest reference points to temporary transaction staging path: "
                        f"{ref.get('path')}"
                    )
                path = self._normalized_artifact_path(project_id, str(ref["path"]))
                if not path.is_file():
                    raise ScienceStateError(f"Referenced artifact is missing: {ref['path']}")
                if path.suffix.lower() == ".json":
                    payload = self._reader(path, f"Referenced artifact is missing: {ref['path']}")
                    actual_hash = self._payload_reference_hash(payload)
                else:
                    actual_hash = "sha256:" + sha256(path.read_bytes()).hexdigest()
                if actual_hash != str(ref.get("content_hash") or ""):
                    raise ScienceStateError(
                        f"Referenced artifact hash mismatch: {ref['path']}"
                    )
                checked += 1
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise ScienceStateError(
                "Normalized reference integrity failed: " + " | ".join(errors[:8])
            )
        registry_entries: dict[str, Any] = {}
        registry_ref = manifest.get("fragment_registry_ref")
        if isinstance(registry_ref, dict):
            registry = self._reader(
                self._normalized_artifact_path(project_id, str(registry_ref["path"])),
                "Fragment registry is missing",
            )
            registry_entries = (
                registry.get("entries") if isinstance(registry.get("entries"), dict) else {}
            )
            verified_fragment_files: set[str] = set()
            verified_indexes: dict[str, dict[str, Any]] = {}
            for fragment_id, entry in registry_entries.items():
                if not isinstance(entry, dict):
                    errors.append(f"Fragment registry entry is invalid: {fragment_id}")
                    continue
                file_name = str(entry.get("file") or "")
                if not file_name:
                    continue
                if file_name not in verified_fragment_files:
                    file_path = self._normalized_artifact_path(project_id, file_name)
                    if not file_path.is_file():
                        errors.append(f"Fragment JSONL is missing: {file_name}")
                        continue
                    actual_file_hash = "sha256:" + sha256(file_path.read_bytes()).hexdigest()
                    if actual_file_hash != str(entry.get("file_hash") or ""):
                        errors.append(f"Fragment JSONL hash mismatch: {file_name}")
                    verified_fragment_files.add(file_name)
                index_name = str(entry.get("index_file") or "")
                if index_name and index_name not in verified_indexes:
                    index_path = self._normalized_artifact_path(project_id, index_name)
                    if not index_path.is_file():
                        errors.append(f"Fragment index is missing: {index_name}")
                    else:
                        verified_indexes[index_name] = self._reader(
                            index_path, f"Fragment index is missing: {index_name}"
                        )
                index_document = verified_indexes.get(index_name, {})
                indexed_location = (index_document.get("entries") or {}).get(fragment_id)
                if indexed_location != {
                    "offset": int(entry.get("offset") or 0),
                    "length": int(entry.get("length") or 0),
                }:
                    errors.append(f"Fragment registry/index disagreement: {fragment_id}")

        def iter_fragment_refs(value: Any):
            if isinstance(value, dict):
                for key, nested in value.items():
                    if key.endswith("fragment_refs") and isinstance(nested, list):
                        for item in nested:
                            yield str(item)
                    else:
                        yield from iter_fragment_refs(nested)
            elif isinstance(value, list):
                for nested in value:
                    yield from iter_fragment_refs(nested)

        gap_refs = manifest.get("gap_refs") or {}
        bundle_refs = manifest.get("bundle_refs") or {}
        contract_refs = manifest.get("contract_refs") or {}
        report_refs = manifest.get("report_refs") or {}
        for gap_id, gap_ref in gap_refs.items():
            gap = self._reader(
                self._normalized_artifact_path(project_id, str(gap_ref["path"])),
                f"Gap artifact is missing: {gap_id}",
            )
            bundle_ref = bundle_refs.get(gap_id)
            contract_ref = contract_refs.get(gap_id)
            if not isinstance(bundle_ref, dict) or gap.get("evidence_bundle_ref") != bundle_ref.get("path"):
                errors.append(f"Gap {gap_id} does not bind the manifest-selected evidence bundle")
            if not isinstance(contract_ref, dict) or gap.get("latest_contract_ref") != contract_ref.get("path"):
                errors.append(f"Gap {gap_id} does not bind the manifest-selected Socrates contract")
            missing = sorted(set(iter_fragment_refs(gap)) - set(registry_entries))
            if missing:
                errors.append(f"Gap {gap_id} has unknown fragments: {missing[:3]}")
            bundle: dict[str, Any] = {}
            if isinstance(bundle_ref, dict):
                bundle = self._reader(
                    self._normalized_artifact_path(project_id, str(bundle_ref["path"])),
                    f"Evidence bundle is missing: {gap_id}",
                )
                missing = sorted(set(iter_fragment_refs(bundle)) - set(registry_entries))
                if missing:
                    errors.append(f"Bundle {gap_id} has unknown fragments: {missing[:3]}")
            if isinstance(contract_ref, dict):
                contract = self._reader(
                    self._normalized_artifact_path(project_id, str(contract_ref["path"])),
                    f"Socrates contract is missing: {gap_id}",
                )
                if contract.get("gap_ref") != gap_ref.get("path"):
                    errors.append(f"Contract {gap_id} points to a non-current gap")
                if contract.get("gap_snapshot_hash") != gap_ref.get("content_hash"):
                    errors.append(f"Contract {gap_id} gap hash mismatch")
                if isinstance(bundle_ref, dict) and (
                    contract.get("evidence_bundle_ref") != bundle_ref.get("path")
                    or contract.get("evidence_bundle_hash") != bundle_ref.get("content_hash")
                ):
                    errors.append(f"Contract {gap_id} evidence bundle binding mismatch")
            report_ref = report_refs.get(gap_id)
            if isinstance(report_ref, dict) and isinstance(contract_ref, dict):
                report = self._reader(
                    self._normalized_artifact_path(project_id, str(report_ref["path"])),
                    f"Socrates report is missing: {gap_id}",
                )
                if report.get("contract_ref") != contract_ref.get("path"):
                    errors.append(f"Socrates report {gap_id} points to a non-current contract")
                query_audit = str(report.get("query_audit_ref") or "")
                if query_audit and not self._normalized_artifact_path(project_id, query_audit).is_file():
                    errors.append(f"Socrates report {gap_id} query audit is missing")
        if errors:
            raise ScienceStateError(
                "Normalized cross-artifact integrity failed: " + " | ".join(errors[:8])
            )
        return {
            "valid": True,
            "references_checked": checked,
            "fragment_registry_entries": len(registry_entries),
            "gap_bindings_checked": len(gap_refs),
        }

    def _commit_normalized_transaction(
        self,
        project_id: str,
        *,
        artifact_writes: dict[str, Any],
        manifest: dict[str, Any],
        expected_version: int,
        operation: str,
    ) -> dict[str, Any]:
        """Stage immutable artifacts and replace the manifest last.

        Existing artifact paths may be reused only when their bytes are
        identical.  Updates therefore need a new version/generation path;
        this keeps the old manifest valid if a process dies before commit.
        """
        api = self._manifest_api()
        transaction_id = f"txn_{time.time_ns()}_{uuid.uuid4().hex[:10]}"
        root = self._normalized_project_root(project_id)
        transaction_root = root / "transactions" / transaction_id
        staging_root = transaction_root / "staged_artifacts"
        manifest_path = root / "manifest.json"
        with self._project_writer_lock(project_id):
            current = self._load_manifest_unlocked(project_id, required=False)
            # During explicit legacy migration there is no manifest yet; the
            # caller has already checked the legacy snapshot version and that
            # version becomes the transaction base.  Later commits always use
            # the manifest as the authority.
            current_version = (
                int(current.get("state_version") or 0)
                if isinstance(current, dict)
                else int(expected_version)
            )
            if int(expected_version) != current_version:
                raise StaleScienceStateError(
                    f"stale science state for project {project_id}: "
                    f"expected version {expected_version}, current version {current_version}"
                )
            if int(manifest.get("state_version") or -1) != current_version + 1:
                raise ScienceStateError(
                    "Normalized manifest transaction must advance state_version exactly once"
                )
            if str(manifest.get("last_committed_transaction_id") or "") != transaction_id:
                manifest = copy.deepcopy(manifest)
                manifest["last_committed_transaction_id"] = transaction_id
                manifest = api["finalize_manifest"](manifest)
            else:
                api["validate_project_manifest"](manifest)
            # Preserve one audit record even when artifact staging itself
            # fails.  The current context is updated before every side effect
            # so a repair can distinguish a bad write plan from a failed move.
            transaction_root.mkdir(parents=True, exist_ok=False)
            committed_paths: list[str] = []
            deduplicated_targets: list[dict[str, Any]] = []
            write_plan: list[dict[str, Any]] = []
            active_artifact: dict[str, str] = {
                "phase": "initialize_write_plan",
                "relative_path": "",
                "stage_path": "",
                "final_path": "",
                "artifact_hash": "",
            }
            try:
                # Different raw path spellings can normalize to one Windows
                # path (for example a slash/backslash variant).  Never stage
                # that target twice: coalesce byte-identical writes and reject
                # divergent content before anything is published.
                planned_by_target: dict[str, dict[str, Any]] = {}
                for relative_path, value in artifact_writes.items():
                    active_artifact = {
                        "phase": "normalize_target_path",
                        "relative_path": str(relative_path),
                        "stage_path": "",
                        "final_path": "",
                        "artifact_hash": "",
                    }
                    safe_path = api["safe_relative_artifact_path"](relative_path)
                    body = value if isinstance(value, bytes) else api["canonical_json_bytes"](value, pretty=True)
                    final_path = self._normalized_artifact_path(project_id, safe_path)
                    artifact_hash = "sha256:" + sha256(body).hexdigest()
                    stage_path = self._transaction_stage_path(
                        staging_root,
                        len(planned_by_target),
                        safe_path,
                    )
                    active_artifact = {
                        "phase": "plan_normalized_target",
                        "relative_path": str(relative_path),
                        "stage_path": str(stage_path),
                        "final_path": str(final_path),
                        "artifact_hash": artifact_hash,
                    }
                    existing = planned_by_target.get(safe_path)
                    if existing is not None:
                        if existing["body"] != body:
                            raise ScienceStateError(
                                "Duplicate normalized artifact target has divergent content: "
                                f"{safe_path} from {existing['relative_paths']!r} and {relative_path!r}"
                            )
                        existing["relative_paths"].append(str(relative_path))
                        deduplicated_targets.append({
                            "normalized_path": safe_path,
                            "artifact_hash": artifact_hash,
                            "duplicate_relative_path": str(relative_path),
                            "canonical_relative_path": existing["relative_paths"][0],
                        })
                        continue
                    planned_by_target[safe_path] = {
                        "safe_path": safe_path,
                        "relative_paths": [str(relative_path)],
                        "stage_path": stage_path,
                        "final_path": final_path,
                        "body": body,
                        "artifact_hash": artifact_hash,
                    }

                # The staged list is built only after all normalized targets
                # are unique, so a later os.replace can never consume another
                # item's stage file.
                staged: list[dict[str, Any]] = []
                for entry in planned_by_target.values():
                    active_artifact = {
                        "phase": "stage_artifact",
                        "relative_path": entry["relative_paths"][0],
                        "stage_path": str(entry["stage_path"]),
                        "final_path": str(entry["final_path"]),
                        "artifact_hash": entry["artifact_hash"],
                    }
                    entry["stage_path"].parent.mkdir(parents=True, exist_ok=True)
                    entry["stage_path"].write_bytes(entry["body"])
                    staged.append(entry)
                    write_plan.append({
                        "normalized_path": entry["safe_path"],
                        "relative_paths": list(entry["relative_paths"]),
                        "stage_path": str(entry["stage_path"]),
                        "final_path": str(entry["final_path"]),
                        "artifact_hash": entry["artifact_hash"],
                    })

                for entry in staged:
                    stage_path = entry["stage_path"]
                    final_path = entry["final_path"]
                    body = entry["body"]
                    active_artifact = {
                        "phase": "publish_artifact",
                        "relative_path": entry["relative_paths"][0],
                        "stage_path": str(stage_path),
                        "final_path": str(final_path),
                        "artifact_hash": entry["artifact_hash"],
                    }
                    if final_path.exists():
                        if final_path.read_bytes() != body:
                            raise ScienceStateError(
                                f"Normalized artifact path is immutable and already differs: {final_path}"
                            )
                        continue
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(stage_path, final_path)
                    committed_paths.append(str(final_path.relative_to(root)).replace("\\", "/"))

                active_artifact = {
                    "phase": "verify_manifest_references",
                    "relative_path": "",
                    "stage_path": "",
                    "final_path": str(manifest_path),
                    "artifact_hash": str(manifest.get("content_hash") or ""),
                }
                integrity = self._verify_manifest_references_unlocked(project_id, manifest)
                integrity_audit = {
                    "schema_version": "science_reference_integrity_audit_v1",
                    "project_id": project_id,
                    "state_store_id": self.store_id(project_id),
                    "state_version": int(manifest["state_version"]),
                    "transaction_id": transaction_id,
                    "status": "PASS",
                    **integrity,
                    "checked_at": time.time(),
                }
                active_artifact["phase"] = "write_reference_integrity_audit"
                self._writer(
                    root / "audits" / "reference_integrity" / f"{int(manifest['state_version']):04d}.json",
                    integrity_audit,
                )
                active_artifact["phase"] = "publish_manifest"
                self._writer(manifest_path, manifest)
                audit = {
                    "schema_version": api["SCIENCE_TRANSACTION_AUDIT_SCHEMA_VERSION"],
                    "transaction_id": transaction_id,
                    "project_id": project_id,
                    "state_store_id": self.store_id(project_id),
                    "operation": str(operation),
                    "from_version": current_version,
                    "to_version": int(manifest["state_version"]),
                    "artifact_paths": committed_paths,
                    "manifest_hash": str(manifest.get("content_hash") or ""),
                    "write_plan": write_plan,
                    "deduplicated_normalized_targets": deduplicated_targets,
                    "status": "COMMITTED",
                    "committed_at": time.time(),
                }
                self._writer(transaction_root / "transaction.json", audit)
                shutil.rmtree(staging_root, ignore_errors=True)
                return {
                    "transaction_id": transaction_id,
                    "state_version": int(manifest["state_version"]),
                    "manifest": copy.deepcopy(manifest),
                    "artifact_paths": committed_paths,
                }
            except Exception as exc:
                failure = {
                    "schema_version": api["SCIENCE_TRANSACTION_AUDIT_SCHEMA_VERSION"],
                    "transaction_id": transaction_id,
                    "project_id": project_id,
                    "operation": str(operation),
                    "from_version": current_version,
                    "status": "ABORTED_BEFORE_MANIFEST_COMMIT",
                    "orphan_artifact_paths": committed_paths,
                    "phase": active_artifact["phase"],
                    "relative_path": active_artifact["relative_path"],
                    "stage_path": active_artifact["stage_path"],
                    "final_path": active_artifact["final_path"],
                    "artifact_hash": active_artifact["artifact_hash"],
                    "exception_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
                    "exception_message": str(exc),
                    "exception_repr": repr(exc),
                    "exception_traceback": traceback.format_exc(),
                    "write_plan": write_plan,
                    "deduplicated_normalized_targets": deduplicated_targets,
                    "failed_at": time.time(),
                }
                try:
                    self._writer(transaction_root / "transaction.json", failure)
                except Exception:
                    pass
                raise

    def store_id(self, project_id: str) -> str:
        root = str(self._project_path(project_id).parent.resolve()).lower()
        return "science-store-" + sha256(root.encode("utf-8")).hexdigest()[:16]

    def normalized_project_layout(self, project_id: str) -> dict[str, Any]:
        """Describe the normalized artifact tree without touching the disk.

        The legacy project file and the future artifact directory are siblings:

        ``projects/<project_id>.json`` and ``projects/<project_id>/``.

        The parent ``projects`` directory already belongs to exactly one
        ScienceStateManager store, so no second store root or workspace-local
        path is invented here.
        """
        normalized_id = str(project_id or "").strip()
        if not normalized_id:
            raise ScienceStateError("Normalized science-project layout requires project_id")
        legacy_path = self._project_path(normalized_id).resolve()
        projects_root = legacy_path.parent.resolve()
        project_root = (projects_root / legacy_path.stem).resolve()
        try:
            project_root.relative_to(projects_root)
        except ValueError as exc:
            raise ScienceStateError(
                f"Normalized project root escaped the active science store: {project_root}"
            ) from exc
        if project_root == projects_root:
            raise ScienceStateError("Normalized project root cannot equal the projects directory")
        directories = {
            name: str((project_root / relative_path).resolve())
            for name, relative_path in NORMALIZED_PROJECT_STATIC_DIRECTORIES.items()
        }
        return {
            "schema_version": NORMALIZED_PROJECT_LAYOUT_SCHEMA_VERSION,
            "storage_format": NORMALIZED_PROJECT_STORAGE_FORMAT,
            "project_id": normalized_id,
            "state_store_id": self.store_id(normalized_id),
            "projects_root": str(projects_root),
            "legacy_project_path": str(legacy_path),
            "project_root": str(project_root),
            "manifest_path": str(project_root / "manifest.json"),
            "directories": directories,
            "dynamic_path_templates": dict(NORMALIZED_PROJECT_DYNAMIC_PATH_TEMPLATES),
            "active_storage_format": "legacy_monolithic_json",
            "manifest_exists": (project_root / "manifest.json").is_file(),
        }

    def prepare_normalized_project_layout(self, project_id: str) -> dict[str, Any]:
        """Create only the normalized directory skeleton for one legacy project.

        This is deliberately not a migration or activation operation: it does
        not write ``manifest.json``, copy artifacts, change ``state_version``,
        or redirect reads/writes away from the legacy JSON.  Requiring the
        canonical legacy project to load successfully prevents orphan layout
        trees and cross-store preparation.
        """
        project = self.get_project(project_id)
        layout = self.normalized_project_layout(project_id)
        if str(project.get("state_store_id") or "") != str(layout["state_store_id"]):
            raise ScienceStateStoreMismatch(
                f"Science project {project_id} is not bound to layout store {layout['state_store_id']}."
            )
        project_root = Path(str(layout["project_root"])).resolve()
        projects_root = Path(str(layout["projects_root"])).resolve()
        try:
            project_root.relative_to(projects_root)
        except ValueError as exc:
            raise ScienceStateError(
                f"Refusing to create normalized layout outside active projects root: {project_root}"
            ) from exc

        created: list[str] = []
        existing: list[str] = []
        with self._lock:
            for directory in [project_root, *(Path(path) for path in layout["directories"].values())]:
                if directory.exists() and not directory.is_dir():
                    raise ScienceStateError(
                        f"Normalized science-project layout path is not a directory: {directory}"
                    )
                if directory.is_dir():
                    existing.append(str(directory))
                    continue
                directory.mkdir(parents=True, exist_ok=False)
                created.append(str(directory))

        prepared = dict(layout)
        prepared.update({
            "created_directories": created,
            "existing_directories": existing,
            "manifest_written": False,
            "storage_activated": False,
            "state_version": int(project.get("state_version") or 0),
        })
        return prepared

    @staticmethod
    def _ids_from_gap_values(values: Any) -> list[str]:
        return list(dict.fromkeys(
            str(item.get("gap_id") or "")
            for item in (values if isinstance(values, list) else [])
            if isinstance(item, dict) and str(item.get("gap_id") or "")
        ))

    def _normalized_compatibility_fields(self, project: dict[str, Any]) -> dict[str, Any]:
        """Split the materialized view while preserving V3 provenance state.

        Research Evidence Graph V3 snapshots live in immutable graph artifacts
        referenced by the manifest.  A materialized project may expose their
        small references but must never write the graph bodies back into project
        fields, where they would duplicate every span and assertion.
        """
        excluded = {
            "papergraph", "primary_scientific_gaps", "secondary_scientific_gaps",
            "state_version", "state_store_id", "state_context", "artifact_versions",
            "artifacts", "research_evidence_graphs", "active_research_evidence_graph_ref",
        }
        fields: dict[str, Any] = {}
        bundle_extensions: dict[str, dict[str, Any]] = {}
        sub_hypotheses = [
            item for item in project.get("sub_hypotheses", []) if isinstance(item, dict)
        ]
        externalize_v3_research_question_state = bool(sub_hypotheses) and all(
            _is_v3_subhypothesis(item) for item in sub_hypotheses
        )
        v3_dynamic_fields = {
            "sub_hypotheses",
            "research_question_retrieval_executions_v3",
            "slot_coverage_ledger_v1",
        }
        for key, value in project.items():
            if key in excluded:
                continue
            if externalize_v3_research_question_state and key in v3_dynamic_fields:
                continue
            payload = copy.deepcopy(value)
            if key == "tanxi_gap_analysis" and isinstance(payload, dict):
                ranked = payload.pop("ranked_gaps", [])
                payload["ranked_gap_ids"] = self._ids_from_gap_values(ranked)
            elif key == "knowledge_gaps" and isinstance(payload, list):
                for gap in payload:
                    if not isinstance(gap, dict):
                        continue
                    gap_id = str(gap.get("gap_id") or "")
                    bundle = gap.pop("mechanism_evidence_bundle", None)
                    if not gap_id or not isinstance(bundle, dict):
                        continue
                    extension = copy.deepcopy(bundle)
                    extension.pop("evidence_fragment_alignments", None)
                    extension.pop("gap_anchor_fragment_alignments", None)
                    design = extension.get("research_design_evidence")
                    if isinstance(design, dict):
                        design.pop("fragment_alignments", None)
                    bundle_extensions[gap_id] = extension
            elif key == "socrates_mechanism_contracts" and isinstance(payload, dict):
                for contract in payload.values():
                    if isinstance(contract, dict):
                        contract.pop("mechanism_evidence_bundle", None)
            elif key == "socrates_reports" and isinstance(payload, list):
                for report in payload:
                    if isinstance(report, dict):
                        report.pop("mechanism_contract", None)
            fields[key] = payload
        if bundle_extensions:
            fields["_normalized_bundle_extensions"] = bundle_extensions
        return fields

    def _externalize_v4_evidence_records(
        self,
        project_id: str,
        papers: list[dict[str, Any]],
        *,
        state_version: int,
        existing_span_registry_ref: dict[str, Any] | None = None,
        existing_assertion_registry_ref: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Write canonical V4 spans/assertions through sharded registries.

        Paper artifacts receive compact references and counts only.  The
        registry root holds shard refs, while a new evidence record touches
        only the shard selected by its content id.  Normal saves therefore do
        not deserialize, copy, or rewrite a project-wide registry snapshot.
        """
        try:
            from ._evidence_storage import (
                assertion_source_span_ids,
                compact_record_v4_evidence,
                encode_indexed_evidence_jsonl,
                evidence_contract_partition_v4,
                evidence_registry_root_document,
                evidence_registry_shard_document,
                evidence_registry_shard_key,
                indexed_evidence_document,
            )
        except ImportError:
            from _evidence_storage import (
                assertion_source_span_ids,
                compact_record_v4_evidence,
                encode_indexed_evidence_jsonl,
                evidence_contract_partition_v4,
                evidence_registry_root_document,
                evidence_registry_shard_document,
                evidence_registry_shard_key,
                indexed_evidence_document,
            )
        api = self._manifest_api()
        root_schema = "evidence_record_registry_root_v3"

        def registry_root(
            ref: dict[str, Any] | None,
            *,
            record_kind: str,
        ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
            if not isinstance(ref, dict):
                return {}, {}
            root = self.resolve_ref(ref)
            if (
                not isinstance(root, dict)
                or root.get("schema_version") != root_schema
                or str(root.get("record_kind") or "") != record_kind
            ):
                raise ScienceStateError(
                    "EVIDENCE_REGISTRY_V3_REQUIRED: normal V3 persistence "
                    f"requires a {record_kind} sharded registry root."
                )
            shards = {
                str(key): copy.deepcopy(value)
                for key, value in (root.get("shards") or {}).items()
                if isinstance(value, dict)
            }
            return root, shards

        prior_span_root, span_shard_refs = registry_root(
            existing_span_registry_ref,
            record_kind="source_span",
        )
        prior_assertion_root, assertion_shard_refs = registry_root(
            existing_assertion_registry_ref,
            record_kind="evidence_assertion",
        )
        del prior_span_root, prior_assertion_root
        span_entries_by_shard: dict[str, dict[str, dict[str, Any]]] = {}
        assertion_entries_by_shard: dict[str, dict[str, dict[str, Any]]] = {}
        dirty_span_shards: set[str] = set()
        dirty_assertion_shards: set[str] = set()

        def shard_entries(
            *,
            identifier: str,
            record_kind: str,
            refs: dict[str, dict[str, Any]],
            cache: dict[str, dict[str, dict[str, Any]]],
        ) -> tuple[str, dict[str, dict[str, Any]]]:
            shard_key = evidence_registry_shard_key(identifier)
            if shard_key in cache:
                return shard_key, cache[shard_key]
            ref = refs.get(shard_key)
            if not isinstance(ref, dict):
                cache[shard_key] = {}
                return shard_key, cache[shard_key]
            shard = self.resolve_ref(ref)
            if (
                not isinstance(shard, dict)
                or shard.get("schema_version") != "evidence_record_registry_shard_v3"
                or str(shard.get("record_kind") or "") != record_kind
                or str(shard.get("shard_key") or "") != shard_key
            ):
                raise ScienceStateError(
                    "EVIDENCE_REGISTRY_SHARD_INTEGRITY_ERROR: registry root references "
                    f"an invalid {record_kind} shard {shard_key}."
                )
            cache[shard_key] = {
                str(key): copy.deepcopy(value)
                for key, value in (shard.get("entries") or {}).items()
                if isinstance(value, dict)
            }
            return shard_key, cache[shard_key]

        writes: dict[str, Any] = {}
        pending_spans: dict[tuple[str, str], list[dict[str, Any]]] = {}
        pending_assertions: dict[tuple[str, str], list[dict[str, Any]]] = {}

        for paper in papers:
            if not isinstance(paper, dict):
                continue
            compact_record_v4_evidence(paper)
            paper_id = str(paper.get("paper_id") or "").strip()
            if not paper_id:
                continue
            has_inline_evidence = any(
                key in paper for key in (
                    "evidence_document_v4",
                    "source_spans_v6",
                    "evidence_assertions_v4",
                )
            )
            if not has_inline_evidence:
                continue
            partition = evidence_contract_partition_v4(paper)
            existing_storage = (
                paper.get("evidence_storage_v4")
                if isinstance(paper.get("evidence_storage_v4"), dict)
                else {}
            )
            document_versions = self._document_versions_from_storage_v4(
                existing_storage,
                paper_id=paper_id,
            )
            current_document = paper.get("evidence_document_v4")
            if (
                not isinstance(current_document, dict)
                or str(current_document.get("schema_version") or "") != "document_version_v4"
                or str(current_document.get("paper_id") or "") != paper_id
                or not str(current_document.get("document_version_hash") or "")
            ):
                raise ScienceStateError("EVIDENCE_DOCUMENT_VERSION_ARTIFACT_INVALID")
            current_document_version_hash = str(
                current_document.get("document_version_hash") or ""
            )
            document_versions[current_document_version_hash] = copy.deepcopy(
                current_document
            )
            document_versions = {
                version_hash: document_versions[version_hash]
                for version_hash in sorted(document_versions)
            }
            spans = [item for item in paper.get("source_spans_v6", []) if isinstance(item, dict)]
            assertions = [item for item in paper.get("evidence_assertions_v4", []) if isinstance(item, dict)]
            for span in spans:
                span_id = str(span.get("source_span_id") or span.get("source_unit_id") or "")
                _, span_entries = shard_entries(
                    identifier=span_id,
                    record_kind="source_span",
                    refs=span_shard_refs,
                    cache=span_entries_by_shard,
                ) if span_id else ("", {})
                if span_id and span_id not in span_entries:
                    span_entries[span_id] = {"_pending": True}
                    dirty_span_shards.add(evidence_registry_shard_key(span_id))
                    pending_spans.setdefault((partition, paper_id), []).append(copy.deepcopy(span))
            for assertion in assertions:
                assertion_id = str(assertion.get("assertion_id") or "")
                _, assertion_entries = shard_entries(
                    identifier=assertion_id,
                    record_kind="evidence_assertion",
                    refs=assertion_shard_refs,
                    cache=assertion_entries_by_shard,
                ) if assertion_id else ("", {})
                if assertion_id and assertion_id not in assertion_entries:
                    assertion_entries[assertion_id] = {"_pending": True}
                    dirty_assertion_shards.add(evidence_registry_shard_key(assertion_id))
                    pending_assertions.setdefault((partition, paper_id), []).append(copy.deepcopy(assertion))
            paper["evidence_storage_v4"] = {
                "schema_version": "paper_evidence_storage_ref_v4",
                "current_document_version_hash": current_document_version_hash,
                "document_versions_v4": document_versions,
                "source_span_ids": [
                    str(item.get("source_span_id") or item.get("source_unit_id") or "")
                    for item in spans
                    if str(item.get("source_span_id") or item.get("source_unit_id") or "")
                ],
                "assertion_ids": [
                    str(item.get("assertion_id") or "") for item in assertions if str(item.get("assertion_id") or "")
                ],
                "assertion_source_span_ids": assertion_source_span_ids(assertions),
                "source_span_count": len(spans),
                "assertion_count": len(assertions),
            }
            paper.pop("evidence_document_v4", None)
            paper.pop("source_spans_v6", None)
            paper.pop("evidence_assertions_v4", None)

        def persist_group(
            groups: dict[tuple[str, str], list[dict[str, Any]]],
            *,
            record_kind: str,
            identifier_field: str,
            directory: str,
        ) -> None:
            for (partition, paper_id), records in groups.items():
                body, offsets = encode_indexed_evidence_jsonl(records, identifier_field=identifier_field)
                if not offsets:
                    continue
                jsonl_path = f"{directory}/{partition}/{_safe_identifier(paper_id)}.v{state_version:04d}.jsonl"
                index_path = f"{directory}/{partition}/{_safe_identifier(paper_id)}.v{state_version:04d}.index.json"
                writes[jsonl_path] = body
                index_document = indexed_evidence_document(
                    record_kind=record_kind,
                    paper_id=paper_id,
                    partition=partition,
                    jsonl_path=jsonl_path,
                    identifier_field=identifier_field,
                    entries=offsets,
                )
                writes[index_path] = index_document
                body_hash = "sha256:" + sha256(body).hexdigest()
                records_by_identifier = {
                    str(record.get(identifier_field) or ""): record
                    for record in records
                    if str(record.get(identifier_field) or "")
                }
                for identifier, location in offsets.items():
                    record = records_by_identifier[identifier]
                    record_body = json.dumps(
                        record,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                    shard_key, shard_entry_map = shard_entries(
                        identifier=identifier,
                        record_kind=record_kind,
                        refs=(span_shard_refs if record_kind == "source_span" else assertion_shard_refs),
                        cache=(span_entries_by_shard if record_kind == "source_span" else assertion_entries_by_shard),
                    )
                    shard_entry_map[identifier] = {
                        "paper_id": paper_id,
                        "partition": partition,
                        "file": jsonl_path,
                        "index_file": index_path,
                        "offset": int(location["offset"]),
                        "length": int(location["length"]),
                        "file_hash": body_hash,
                        "content_hash": "sha256:" + sha256(record_body).hexdigest(),
                    }

        persist_group(
            pending_spans,
            record_kind="source_span",
            identifier_field="source_span_id",
            directory="fragments",
        )
        persist_group(
            pending_assertions,
            record_kind="evidence_assertion",
            identifier_field="assertion_id",
            directory="assertions",
        )

        refs: dict[str, Any] = {}
        def persist_registry(
            *,
            record_kind: str,
            root_ref: dict[str, Any] | None,
            shard_refs: dict[str, dict[str, Any]],
            entries_by_shard: dict[str, dict[str, dict[str, Any]]],
            dirty_shards: set[str],
            directory: str,
            root_base_path: str,
            artifact_prefix: str,
        ) -> dict[str, Any] | None:
            if not dirty_shards:
                return copy.deepcopy(root_ref) if isinstance(root_ref, dict) else None
            next_shards = dict(shard_refs)
            for shard_key in sorted(dirty_shards):
                entries = entries_by_shard.get(shard_key) or {}
                if any(item.get("_pending") is True for item in entries.values() if isinstance(item, dict)):
                    raise ScienceStateError(
                        f"Unmaterialized {record_kind} registry entry in shard {shard_key}"
                    )
                previous_ref = shard_refs.get(shard_key)
                shard_document = evidence_registry_shard_document(
                    record_kind=record_kind,
                    shard_key=shard_key,
                    entries=entries,
                )
                shard_version = int((previous_ref or {}).get("artifact_version") or 0) + 1
                shard_path = self._next_artifact_path(
                    f"{directory}/{shard_key}.json",
                    artifact_version=shard_version,
                    previous_ref=previous_ref,
                )
                writes[shard_path] = shard_document
                next_shards[shard_key] = api["science_artifact_ref"](
                    state_store_id=self.store_id(project_id),
                    project_id=project_id,
                    artifact_type=f"{artifact_prefix}_shard",
                    artifact_id=shard_key,
                    artifact_version=shard_version,
                    path=shard_path,
                    artifact_hash=str(shard_document["content_hash"]),
                )
            registry_root = evidence_registry_root_document(
                record_kind=record_kind,
                shards=next_shards,
            )
            root_version = int((root_ref or {}).get("artifact_version") or 0) + 1
            path = self._next_artifact_path(
                root_base_path,
                artifact_version=root_version,
                previous_ref=root_ref,
            )
            writes[path] = registry_root
            return api["science_artifact_ref"](
                state_store_id=self.store_id(project_id),
                project_id=project_id,
                artifact_type=f"{artifact_prefix}_root",
                artifact_id=f"{artifact_prefix}_root",
                artifact_version=root_version,
                path=path,
                artifact_hash=str(registry_root["content_hash"]),
            )

        span_root_ref = persist_registry(
            record_kind="source_span",
            root_ref=existing_span_registry_ref,
            shard_refs=span_shard_refs,
            entries_by_shard=span_entries_by_shard,
            dirty_shards=dirty_span_shards,
            directory="fragments/registry_shards/source_span",
            root_base_path="fragments/source_span_registry_root.json",
            artifact_prefix="source_span_registry",
        )
        assertion_root_ref = persist_registry(
            record_kind="evidence_assertion",
            root_ref=existing_assertion_registry_ref,
            shard_refs=assertion_shard_refs,
            entries_by_shard=assertion_entries_by_shard,
            dirty_shards=dirty_assertion_shards,
            directory="assertions/registry_shards/evidence_assertion",
            root_base_path="assertions/assertion_registry_root.json",
            artifact_prefix="assertion_registry",
        )
        if isinstance(span_root_ref, dict):
            refs["source_span_registry_root_ref"] = span_root_ref
        if isinstance(assertion_root_ref, dict):
            refs["assertion_registry_root_ref"] = assertion_root_ref
        return writes, refs, {
            "new_source_spans": sum(len(items) for items in pending_spans.values()),
            "new_assertions": sum(len(items) for items in pending_assertions.values()),
            "registry_schema_version": "evidence_record_registry_root_v3",
        }

    def migrate_v2_evidence_registries(
        self,
        project_id: str,
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Explicitly convert legacy full registries into V2 root/shard indexes.

        This maintenance operation is intentionally outside normal project
        loading, saving, retrieval, and TanXi execution.  Once committed, the
        V2 read/write path accepts only the sharded registry roots; the old
        full registries remain historical artifacts but cannot be selected as
        a runtime fallback.
        """
        try:
            from ._evidence_storage import (
                evidence_registry_root_document,
                evidence_registry_shard_document,
                evidence_registry_shard_key,
            )
        except ImportError:
            from _evidence_storage import (
                evidence_registry_root_document,
                evidence_registry_shard_document,
                evidence_registry_shard_key,
            )
        manifest = self.get_project_manifest(project_id)
        current_version = int(manifest.get("state_version") or 0)
        if expected_version is not None and int(expected_version) != current_version:
            raise StaleScienceStateError(
                f"stale science state for project {project_id}: expected version "
                f"{expected_version}, current version {current_version}"
            )
        existing_span_root = manifest.get("source_span_registry_root_ref")
        existing_assertion_root = manifest.get("assertion_registry_root_ref")
        if isinstance(existing_span_root, dict) and isinstance(existing_assertion_root, dict):
            return {
                "status": "ALREADY_MIGRATED",
                "project_id": project_id,
                "state_version": current_version,
                "source_span_registry_root_ref": copy.deepcopy(existing_span_root),
                "assertion_registry_root_ref": copy.deepcopy(existing_assertion_root),
            }
        legacy_span_ref = manifest.get("source_span_registry_ref")
        legacy_assertion_ref = manifest.get("assertion_registry_ref")
        if not isinstance(legacy_span_ref, dict) or not isinstance(legacy_assertion_ref, dict):
            raise ScienceStateError(
                "EVIDENCE_REGISTRY_V2_MIGRATION_SOURCE_MISSING: both legacy registry refs are required"
            )
        legacy_span = self.resolve_ref(legacy_span_ref)
        legacy_assertions = self.resolve_ref(legacy_assertion_ref)
        if (
            not isinstance(legacy_span, dict)
            or legacy_span.get("schema_version") != "evidence_record_registry_v1"
            or str(legacy_span.get("record_kind") or "") != "source_span"
            or not isinstance(legacy_assertions, dict)
            or legacy_assertions.get("schema_version") != "evidence_record_registry_v1"
            or str(legacy_assertions.get("record_kind") or "") != "evidence_assertion"
        ):
            raise ScienceStateError(
                "EVIDENCE_REGISTRY_V2_MIGRATION_SOURCE_INVALID: expected immutable registry_v1 artifacts"
            )
        api = self._manifest_api()
        writes: dict[str, Any] = {}

        def migrate_kind(
            *,
            record_kind: str,
            entries: dict[str, Any],
            shard_directory: str,
            root_base_path: str,
            artifact_prefix: str,
        ) -> tuple[dict[str, Any], int]:
            grouped: dict[str, dict[str, dict[str, Any]]] = {}
            for identifier, entry in entries.items():
                normalized_identifier = str(identifier or "").strip()
                if not normalized_identifier or not isinstance(entry, dict):
                    continue
                shard_key = evidence_registry_shard_key(normalized_identifier)
                grouped.setdefault(shard_key, {})[normalized_identifier] = copy.deepcopy(entry)
            shard_refs: dict[str, dict[str, Any]] = {}
            for shard_key, shard_entries in sorted(grouped.items()):
                document = evidence_registry_shard_document(
                    record_kind=record_kind,
                    shard_key=shard_key,
                    entries=shard_entries,
                )
                path = f"{shard_directory}/{shard_key}.json"
                writes[path] = document
                shard_refs[shard_key] = api["science_artifact_ref"](
                    state_store_id=self.store_id(project_id),
                    project_id=project_id,
                    artifact_type=f"{artifact_prefix}_shard",
                    artifact_id=shard_key,
                    artifact_version=1,
                    path=path,
                    artifact_hash=str(document["content_hash"]),
                )
            root = evidence_registry_root_document(
                record_kind=record_kind,
                shards=shard_refs,
            )
            root_path = root_base_path
            writes[root_path] = root
            root_ref = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id),
                project_id=project_id,
                artifact_type=f"{artifact_prefix}_root",
                artifact_id=f"{artifact_prefix}_root",
                artifact_version=1,
                path=root_path,
                artifact_hash=str(root["content_hash"]),
            )
            return root_ref, len(grouped)

        span_root_ref, span_shard_count = migrate_kind(
            record_kind="source_span",
            entries=legacy_span.get("entries") or {},
            shard_directory="fragments/registry_shards/source_span",
            root_base_path="fragments/source_span_registry_root.json",
            artifact_prefix="source_span_registry",
        )
        assertion_root_ref, assertion_shard_count = migrate_kind(
            record_kind="evidence_assertion",
            entries=legacy_assertions.get("entries") or {},
            shard_directory="assertions/registry_shards/evidence_assertion",
            root_base_path="assertions/assertion_registry_root.json",
            artifact_prefix="assertion_registry",
        )
        updated = copy.deepcopy(manifest)
        updated["source_span_registry_root_ref"] = span_root_ref
        updated["assertion_registry_root_ref"] = assertion_root_ref
        updated["evidence_storage"] = {
            **dict(manifest.get("evidence_storage") or {}),
            "schema_version": "research_question_evidence_storage_v3",
            "registry_schema_version": "evidence_record_registry_root_v2",
            "legacy_registry_policy": "historical_audit_only_not_runtime_readable",
        }
        versions = {
            str(key): int(value or 0)
            for key, value in (manifest.get("artifact_versions") or {}).items()
        }
        versions["evidence"] = int(versions.get("evidence") or 0) + 1
        updated["artifact_versions"] = versions
        updated["state_version"] = current_version + 1
        updated["updated_at"] = time.time()
        updated["last_committed_transaction_id"] = "PENDING_TRANSACTION_ID"
        updated = api["finalize_manifest"](updated)
        result = self._commit_normalized_transaction(
            project_id,
            artifact_writes=writes,
            manifest=updated,
            expected_version=current_version,
            operation="MIGRATE_V2_EVIDENCE_REGISTRIES",
        )
        return {
            "status": "MIGRATED",
            "project_id": project_id,
            "state_version": int(result.get("state_version") or current_version + 1),
            "source_span_count": len(legacy_span.get("entries") or {}),
            "assertion_count": len(legacy_assertions.get("entries") or {}),
            "source_span_shard_count": span_shard_count,
            "assertion_shard_count": assertion_shard_count,
            "source_span_registry_root_ref": span_root_ref,
            "assertion_registry_root_ref": assertion_root_ref,
        }

    def activate_normalized_project_storage(
        self,
        project_id: str,
        *,
        expected_version: int | None = None,
        run_id: str = "",
    ) -> dict[str, Any]:
        """Explicitly migrate one canonical legacy snapshot in one transaction.

        This operation is never triggered by directory creation.  The legacy
        JSON remains as a rollback source, but after the manifest commit all
        manager reads and saves use normalized artifacts.
        """
        layout = self.normalized_project_layout(project_id)
        if bool(layout.get("manifest_exists")):
            manifest = self.get_project_manifest(project_id)
            return {
                "status": "ALREADY_ACTIVE",
                "project_id": project_id,
                "state_version": int(manifest.get("state_version") or 0),
                "manifest": manifest,
            }
        legacy_path = self._project_path(project_id)
        project = self._reader(legacy_path, f"Science project not found: {project_id}")
        self._validate_project_identity(project, project_id)
        self._hydrate_state_metadata(project, self.store_id(project_id))
        hydrate_project_fulltexts(project)
        project = compact_project_for_persistence(project)
        legacy_version = int(project.get("state_version") or 0)
        if expected_version is not None and int(expected_version) != legacy_version:
            raise StaleScienceStateError(
                f"stale science state for project {project_id}: expected version "
                f"{expected_version}, current version {legacy_version}"
            )
        self.prepare_normalized_project_layout(project_id)
        migration_run_id = str(run_id or f"migration_{legacy_version:04d}")
        api = self._manifest_api()
        try:
            from ._science_artifacts import (
                artifact_content_hash,
                build_normalized_gap_artifact_set,
                validate_normalized_artifact,
            )
            from ._science_manifest import (
                encode_indexed_jsonl,
                fragment_index_document,
                fragment_registry_document,
                with_content_hash,
            )
        except ImportError:
            from _science_artifacts import (
                artifact_content_hash,
                build_normalized_gap_artifact_set,
                validate_normalized_artifact,
            )
            from _science_manifest import (
                encode_indexed_jsonl,
                fragment_index_document,
                fragment_registry_document,
                with_content_hash,
            )

        writes: dict[str, Any] = {}
        project_field_refs: dict[str, dict[str, Any]] = {}
        for field_name, value in self._normalized_compatibility_fields(project).items():
            document = with_content_hash({
                "schema_version": "science_project_field_v1",
                "project_id": project_id,
                "field_name": field_name,
                "value": value,
            })
            path = f"project_fields/{_safe_identifier(field_name)}.json"
            writes[path] = document
            project_field_refs[field_name] = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id),
                project_id=project_id,
                artifact_type="project_field",
                artifact_id=field_name,
                artifact_version=1,
                path=path,
                artifact_hash=str(document["content_hash"]),
            )

        v3_sub_hypotheses = [
            dict(item)
            for item in project.get("sub_hypotheses", [])
            if isinstance(item, dict)
        ]
        v3_executions = (
            project.get("research_question_retrieval_executions_v3")
            if isinstance(project.get("research_question_retrieval_executions_v3"), dict)
            else {}
        )
        v3_contract_refs: dict[str, dict[str, Any]] = {}
        v3_execution_refs: dict[str, dict[str, Any]] = {}
        v3_state_active = bool(v3_sub_hypotheses) and all(
            _is_v3_subhypothesis(item) for item in v3_sub_hypotheses
        )
        if v3_state_active:
            v3_writes, v3_contract_refs, v3_execution_refs = (
                self._plan_v3_research_question_state_artifacts(
                    project_id,
                    sub_hypotheses=v3_sub_hypotheses,
                    executions=v3_executions,
                )
            )
            writes.update(v3_writes)
            for field_name in (
                "sub_hypotheses",
                "research_question_retrieval_executions_v3",
                "slot_coverage_ledger_v1",
            ):
                project_field_refs.pop(field_name, None)

        evidence_writes, evidence_refs, evidence_stats = self._externalize_v4_evidence_records(
            project_id,
            project.get("papergraph", []) if isinstance(project.get("papergraph"), list) else [],
            state_version=legacy_version + 1,
        )
        writes.update(evidence_writes)
        paper_refs: dict[str, dict[str, Any]] = {}
        paper_ids: list[str] = []
        for index, paper in enumerate(project.get("papergraph", [])):
            if not isinstance(paper, dict):
                continue
            paper_id = str(paper.get("paper_id") or paper.get("id") or "").strip()
            if not paper_id:
                paper_id = "paper_" + sha256(
                    json.dumps(paper, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()[:20]
            payload = copy.deepcopy(paper)
            payload.setdefault("paper_id", paper_id)
            externalize_paper_fulltext(payload)
            path = f"papers/{_safe_identifier(paper_id)}.json"
            writes[path] = payload
            paper_refs[paper_id] = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id),
                project_id=project_id,
                artifact_type="paper",
                artifact_id=paper_id,
                artifact_version=1,
                path=path,
                artifact_hash=self._payload_reference_hash(payload),
            )
            paper_ids.append(paper_id)

        gap_refs: dict[str, dict[str, Any]] = {}
        bundle_refs: dict[str, dict[str, Any]] = {}
        contract_refs: dict[str, dict[str, Any]] = {}
        report_refs: dict[str, dict[str, Any]] = {}
        fragment_by_id: dict[str, dict[str, Any]] = {}
        fragment_audits: list[dict[str, Any]] = []
        gap_ids: list[str] = []
        for gap in project.get("knowledge_gaps", []):
            if not isinstance(gap, dict) or not str(gap.get("gap_id") or ""):
                continue
            artifact_set = build_normalized_gap_artifact_set(
                project,
                gap,
                run_id=migration_run_id,
            )
            gap_artifact = artifact_set["gap"]
            bundle = artifact_set["bundle"]
            contract = artifact_set["contract"]
            report = artifact_set["report"]
            gap_id = str(gap_artifact["gap_id"])
            gap_ids.append(gap_id)
            gap_path = f"gaps/{_safe_identifier(gap_id)}.json"
            bundle_path = f"bundles/{_safe_identifier(gap_id)}/v{int(bundle['bundle_version']):04d}.json"
            contract_path = f"contracts/{_safe_identifier(gap_id)}/v{int(contract['contract_version']):04d}.json"
            report_path = f"reports/{_safe_identifier(migration_run_id)}_{_safe_identifier(gap_id)}.json"
            writes.update({
                gap_path: gap_artifact,
                bundle_path: bundle,
                contract_path: contract,
                report_path: report,
            })
            gap_refs[gap_id] = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id), project_id=project_id,
                artifact_type="gap", artifact_id=gap_id,
                artifact_version=int(gap_artifact["gap_version"]), path=gap_path,
                artifact_hash=str(gap_artifact["content_hash"]),
            )
            bundle_refs[gap_id] = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id), project_id=project_id,
                artifact_type="bundle", artifact_id=gap_id,
                artifact_version=int(bundle["bundle_version"]), path=bundle_path,
                artifact_hash=str(bundle["content_hash"]),
            )
            contract_refs[gap_id] = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id), project_id=project_id,
                artifact_type="contract", artifact_id=gap_id,
                artifact_version=int(contract["contract_version"]), path=contract_path,
                artifact_hash=str(contract["content_hash"]),
            )
            report_refs[gap_id] = api["science_artifact_ref"](
                state_store_id=self.store_id(project_id), project_id=project_id,
                artifact_type="socrates_report", artifact_id=f"{migration_run_id}:{gap_id}",
                artifact_version=1, path=report_path,
                artifact_hash=str(report["content_hash"]),
            )
            for fragment in artifact_set.get("canonical_fragments", []):
                if isinstance(fragment, dict):
                    fragment_by_id[str(fragment.get("fragment_id") or "")] = fragment
            fragment_audits.extend(
                item for item in artifact_set.get("fragment_candidate_audit_records", [])
                if isinstance(item, dict)
            )

        registry_entries: dict[str, dict[str, Any]] = {}
        grouped_fragments: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for fragment in fragment_by_id.values():
            key = (
                _safe_identifier(fragment.get("alignment_contract_hash")),
                _safe_identifier(fragment.get("paper_id")),
            )
            if all(key):
                grouped_fragments.setdefault(key, []).append(fragment)
        for (alignment_hash, paper_id), records in grouped_fragments.items():
            jsonl_path = f"fragments/{alignment_hash}/{paper_id}.jsonl"
            index_path = f"fragments/{alignment_hash}/{paper_id}.index.json"
            jsonl_bytes, local_index = encode_indexed_jsonl(records)
            index_document = fragment_index_document(
                alignment_contract_hash=alignment_hash,
                paper_id=str(records[0].get("paper_id") or paper_id),
                jsonl_path=jsonl_path,
                entries=local_index,
            )
            writes[jsonl_path] = jsonl_bytes
            writes[index_path] = index_document
            file_hash = "sha256:" + sha256(jsonl_bytes).hexdigest()
            for fragment in records:
                fragment_id = str(fragment["fragment_id"])
                location = local_index[fragment_id]
                registry_entries[fragment_id] = {
                    "alignment_contract_hash": alignment_hash,
                    "paper_id": str(fragment.get("paper_id") or ""),
                    "file": jsonl_path,
                    "index_file": index_path,
                    "offset": int(location["offset"]),
                    "length": int(location["length"]),
                    "file_hash": file_hash,
                    "content_hash": str(fragment.get("content_hash") or ""),
                }
        registry = fragment_registry_document(registry_entries)
        registry_path = "fragments/fragment_registry.json"
        writes[registry_path] = registry
        registry_ref = api["science_artifact_ref"](
            state_store_id=self.store_id(project_id), project_id=project_id,
            artifact_type="fragment_registry", artifact_id="fragment_registry",
            artifact_version=1, path=registry_path,
            artifact_hash=str(registry["content_hash"]),
        )
        if fragment_audits:
            audit_path = f"audits/fragment_candidates/{_safe_identifier(migration_run_id)}.jsonl"
            writes[audit_path] = b"".join(
                api["canonical_json_bytes"](item) + b"\n" for item in fragment_audits
            )
        writes.setdefault(
            f"audits/socrates_queries/{_safe_identifier(migration_run_id)}.jsonl",
            b"",
        )

        ranked_ids = self._ids_from_gap_values(
            (project.get("tanxi_gap_analysis") or {}).get("ranked_gaps", [])
            if isinstance(project.get("tanxi_gap_analysis"), dict) else []
        )
        primary_ids = self._ids_from_gap_values(project.get("primary_scientific_gaps", []))
        secondary_ids = self._ids_from_gap_values(project.get("secondary_scientific_gaps", []))
        artifact_versions = {
            **{str(key): int(value or 0) for key, value in self._artifact_versions(project).items()},
            "fragments": max(1, int((project.get("artifact_versions") or {}).get("fragments", 0))),
            "bundles": max(1, int((project.get("artifact_versions") or {}).get("bundles", 0))),
            "contracts": max(1, int((project.get("artifact_versions") or {}).get("contracts", 0))),
            "reports": max(1, int((project.get("artifact_versions") or {}).get("reports", 0))),
            "runs": int((project.get("artifact_versions") or {}).get("runs", 0)),
        }
        manifest = {
            "schema_version": api["SCIENCE_PROJECT_MANIFEST_SCHEMA_VERSION"],
            "storage_format": api["NORMALIZED_ARTIFACT_STORAGE_FORMAT"],
            "project_id": project_id,
            "state_version": legacy_version + 1,
            "state_store_id": self.store_id(project_id),
            "artifact_versions": artifact_versions,
            "project_metadata": {
                "title": str(project.get("title") or ""),
                "domain": str(project.get("domain") or ""),
                "objective": str(project.get("objective") or ""),
                "phase": str(project.get("phase") or ""),
            },
            "paper_ids": list(dict.fromkeys(paper_ids)),
            "paper_refs": paper_refs,
            "gap_ids": list(dict.fromkeys(gap_ids)),
            "gap_refs": gap_refs,
            "knowledge_gap_ids": list(dict.fromkeys(gap_ids)),
            "ranked_gap_ids": ranked_ids,
            "primary_gap_ids": primary_ids,
            "secondary_gap_ids": secondary_ids,
            "bundle_refs": bundle_refs,
            "contract_refs": contract_refs,
            "report_refs": report_refs,
            "run_summary_refs": {},
            "project_field_refs": project_field_refs,
            "v3_research_question_state_schema_version": (
                V3_RESEARCH_QUESTION_STATE_SCHEMA_VERSION if v3_state_active else ""
            ),
            "subhypothesis_contract_refs": v3_contract_refs,
            "retrieval_execution_refs": v3_execution_refs,
            "fragment_registry_ref": registry_ref,
            **evidence_refs,
            "evidence_storage": {
                "schema_version": "research_question_evidence_storage_v4",
                **evidence_stats,
                "materialization_policy": "paper_metadata_only; source spans and assertions random-read through registries",
            },
            "latest_report_ref": next(reversed(report_refs.values()), None) if report_refs else None,
            "latest_run_id": migration_run_id,
            "latest_run_summary_ref": None,
            "last_committed_transaction_id": "PENDING_TRANSACTION_ID",
            "updated_at": time.time(),
        }
        manifest = api["finalize_manifest"](manifest)
        result = self._commit_normalized_transaction(
            project_id,
            artifact_writes=writes,
            manifest=manifest,
            expected_version=legacy_version,
            operation="ACTIVATE_NORMALIZED_PROJECT_STORAGE",
        )
        result.update({
            "status": "ACTIVATED",
            "legacy_project_path": str(legacy_path),
            "legacy_project_preserved": True,
            "paper_count": len(paper_refs),
            "gap_count": len(gap_refs),
            "fragment_count": len(registry_entries),
        })
        return result

    def _save_normalized_materialized_project(
        self,
        project: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> None:
        project_id = str(project.get("project_id") or "")
        manifest = self.get_project_manifest(project_id)
        current = self._materialize_normalized_project(project_id)
        current_version = int(manifest.get("state_version") or 0)
        context = project.get("state_context") if isinstance(project.get("state_context"), dict) else {}
        loaded_version = expected_version
        if loaded_version is None and context:
            loaded_version = int(context.get("loaded_version") or 0)
        if loaded_version is not None and int(loaded_version) != current_version:
            raise StaleScienceStateError(
                f"stale science state for project {project_id}: expected version "
                f"{loaded_version}, current version {current_version}"
            )
        active_store_id = self.store_id(project_id)
        payload = compact_project_for_persistence(copy.deepcopy(project))
        new_version = current_version + 1
        changed_groups = self._changed_artifacts(current, payload)
        artifact_versions = {
            str(key): int(value or 0) for key, value in (manifest.get("artifact_versions") or {}).items()
        }
        for group in changed_groups:
            artifact_versions[group] = int(artifact_versions.get(group, 0)) + 1
        payload["state_version"] = new_version
        payload["state_store_id"] = active_store_id
        payload["artifact_versions"] = artifact_versions
        payload["artifacts"] = {
            key: {"version": value} for key, value in artifact_versions.items()
        }
        payload["state_context"] = {"store_id": active_store_id, "loaded_version": new_version}
        payload["updatedAt"] = time.time()
        changed_contract_ids = self._changed_contract_ids(current, payload)
        self._stamp_gap_context(
            payload,
            current,
            new_version,
            int(artifact_versions.get("gaps", 0)),
            changed_contract_ids,
        )
        history = [
            item for item in current.get("state_transactions", []) if isinstance(item, dict)
        ][-49:]
        history.append({
            "from_version": current_version,
            "to_version": new_version,
            "changed_artifacts": changed_groups,
            "savedAt": payload["updatedAt"],
            "store_id": active_store_id,
            "operation": "NORMALIZED_MANIFEST_LAST_SAVE",
        })
        payload["state_transactions"] = history

        api = self._manifest_api()
        try:
            from ._science_artifacts import (
                artifact_content_hash,
                build_normalized_gap_artifact_set,
                validate_normalized_artifact,
            )
            from ._science_manifest import (
                encode_indexed_jsonl,
                fragment_index_document,
                fragment_registry_document,
                with_content_hash,
            )
        except ImportError:
            from _science_artifacts import (
                artifact_content_hash,
                build_normalized_gap_artifact_set,
                validate_normalized_artifact,
            )
            from _science_manifest import (
                encode_indexed_jsonl,
                fragment_index_document,
                fragment_registry_document,
                with_content_hash,
            )

        writes: dict[str, Any] = {}
        updated = copy.deepcopy(manifest)
        changed_storage_groups: set[str] = set()

        v3_sub_hypotheses = [
            dict(item)
            for item in payload.get("sub_hypotheses", [])
            if isinstance(item, dict)
        ]
        v3_state_active = bool(v3_sub_hypotheses) and all(
            _is_v3_subhypothesis(item) for item in v3_sub_hypotheses
        )
        if v3_state_active:
            v3_execution_values = (
                payload.get("research_question_retrieval_executions_v3")
                if isinstance(payload.get("research_question_retrieval_executions_v3"), dict)
                else {}
            )
            v3_writes, v3_contract_refs, v3_execution_refs = (
                self._plan_v3_research_question_state_artifacts(
                    project_id,
                    sub_hypotheses=v3_sub_hypotheses,
                    executions=v3_execution_values,
                    existing_contract_refs=(
                        manifest.get("subhypothesis_contract_refs")
                        if isinstance(manifest.get("subhypothesis_contract_refs"), dict)
                        else {}
                    ),
                    existing_execution_refs=(
                        manifest.get("retrieval_execution_refs")
                        if isinstance(manifest.get("retrieval_execution_refs"), dict)
                        else {}
                    ),
                )
            )
            writes.update(v3_writes)
            updated["subhypothesis_contract_refs"] = v3_contract_refs
            updated["retrieval_execution_refs"] = v3_execution_refs
            updated["v3_research_question_state_schema_version"] = (
                V3_RESEARCH_QUESTION_STATE_SCHEMA_VERSION
            )
            if v3_writes:
                changed_storage_groups.add("retrieval")

        has_inline_evidence = any(
            isinstance(paper, dict)
            and any(
                key in paper
                for key in (
                    "evidence_document_v4",
                    "source_spans_v6",
                    "evidence_assertions_v4",
                )
            )
            for paper in (payload.get("papergraph") or [])
        )
        legacy_registry_present = isinstance(manifest.get("source_span_registry_ref"), dict) or isinstance(
            manifest.get("assertion_registry_ref"), dict
        )
        sharded_registry_complete = isinstance(manifest.get("source_span_registry_root_ref"), dict) and isinstance(
            manifest.get("assertion_registry_root_ref"), dict
        )
        if has_inline_evidence and legacy_registry_present and not sharded_registry_complete:
            raise ScienceStateError(
                "EVIDENCE_REGISTRY_V2_MIGRATION_REQUIRED: migrate immutable evidence registries "
                "before saving new V2 evidence."
            )

        evidence_writes, evidence_refs, evidence_stats = self._externalize_v4_evidence_records(
            project_id,
            payload.get("papergraph", []) if isinstance(payload.get("papergraph"), list) else [],
            state_version=new_version,
            existing_span_registry_ref=(
                manifest.get("source_span_registry_root_ref")
                if isinstance(manifest.get("source_span_registry_root_ref"), dict)
                else None
            ),
            existing_assertion_registry_ref=(
                manifest.get("assertion_registry_root_ref")
                if isinstance(manifest.get("assertion_registry_root_ref"), dict)
                else None
            ),
        )
        writes.update(evidence_writes)
        updated.update(evidence_refs)
        updated["evidence_storage"] = {
            "schema_version": "research_question_evidence_storage_v4",
            **evidence_stats,
            "materialization_policy": "paper_metadata_only; source spans and assertions random-read through registries",
        }
        if evidence_writes:
            changed_storage_groups.add("evidence")

        old_field_refs = manifest.get("project_field_refs") if isinstance(manifest.get("project_field_refs"), dict) else {}
        audit_refs = {
            key: ref for key, ref in old_field_refs.items()
            if str(key).startswith("fragment_audit:") and isinstance(ref, dict)
        }
        new_field_refs: dict[str, dict[str, Any]] = dict(audit_refs)
        for field_name, value in self._normalized_compatibility_fields(payload).items():
            document = with_content_hash({
                "schema_version": "science_project_field_v1",
                "project_id": project_id,
                "field_name": field_name,
                "value": value,
            })
            old_ref = old_field_refs.get(field_name) if isinstance(old_field_refs.get(field_name), dict) else None
            old_ref_path = str((old_ref or {}).get("path") or "")
            old_ref_reusable = bool(old_ref) and not self._is_temporary_transaction_artifact_path(old_ref_path)
            if old_ref_reusable:
                try:
                    old_ref_reusable = self._normalized_artifact_path(project_id, old_ref_path).is_file()
                except Exception:
                    old_ref_reusable = False
            if not old_ref_reusable:
                recovered_ref = self._recover_orphan_project_field_ref(
                    project_id,
                    field_name,
                    state_store_id=active_store_id,
                )
                if isinstance(recovered_ref, dict):
                    old_ref = recovered_ref
                    old_ref_path = str(recovered_ref.get("path") or "")
                    old_ref_reusable = True
                    self._log_state_recovery(
                        "normalized_orphan_project_field_rebound",
                        project_id=project_id,
                        field_name=field_name,
                        field_ref_path=old_ref_path,
                        artifact_version=int(recovered_ref.get("artifact_version") or 1),
                        action="use_orphan_project_field_as_previous_ref_before_versioning",
                    )
            if (
                old_ref
                and old_ref_reusable
                and str(old_ref.get("content_hash") or "") == str(document["content_hash"])
            ):
                new_field_refs[field_name] = copy.deepcopy(old_ref)
                continue
            ref_version = int((old_ref or {}).get("artifact_version") or 0) + 1
            previous_ref_for_path = old_ref if old_ref_reusable else (
                {"path": f"project_fields/{_safe_identifier(field_name)}.json"}
                if ref_version > 1
                else None
            )
            path = self._next_artifact_path(
                f"project_fields/{_safe_identifier(field_name)}.json",
                artifact_version=ref_version,
                previous_ref=previous_ref_for_path,
            )
            writes[path] = document
            new_field_refs[field_name] = api["science_artifact_ref"](
                state_store_id=active_store_id, project_id=project_id,
                artifact_type="project_field", artifact_id=field_name,
                artifact_version=ref_version, path=path,
                artifact_hash=str(document["content_hash"]),
            )
            changed_storage_groups.add("project")
        if v3_state_active:
            for field_name in (
                "sub_hypotheses",
                "research_question_retrieval_executions_v3",
                "slot_coverage_ledger_v1",
            ):
                new_field_refs.pop(field_name, None)
        updated["project_field_refs"] = new_field_refs

        old_paper_refs = manifest.get("paper_refs") if isinstance(manifest.get("paper_refs"), dict) else {}
        paper_refs: dict[str, dict[str, Any]] = {}
        paper_ids: list[str] = []
        for paper in payload.get("papergraph", []):
            if not isinstance(paper, dict):
                continue
            paper_id = str(paper.get("paper_id") or paper.get("id") or "").strip()
            if not paper_id:
                paper_id = "paper_" + sha256(
                    json.dumps(paper, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()[:20]
            paper_payload = copy.deepcopy(paper)
            paper_payload.setdefault("paper_id", paper_id)
            externalize_paper_fulltext(paper_payload)
            paper_hash = self._payload_reference_hash(paper_payload)
            old_ref = old_paper_refs.get(paper_id) if isinstance(old_paper_refs.get(paper_id), dict) else None
            if old_ref and old_ref.get("content_hash") == paper_hash:
                paper_refs[paper_id] = copy.deepcopy(old_ref)
            else:
                ref_version = int((old_ref or {}).get("artifact_version") or 0) + 1
                path = self._next_artifact_path(
                    f"papers/{_safe_identifier(paper_id)}.json",
                    artifact_version=ref_version,
                    previous_ref=old_ref,
                )
                writes[path] = paper_payload
                paper_refs[paper_id] = api["science_artifact_ref"](
                    state_store_id=active_store_id, project_id=project_id,
                    artifact_type="paper", artifact_id=paper_id,
                    artifact_version=ref_version, path=path, artifact_hash=paper_hash,
                )
                changed_storage_groups.add("papers")
            paper_ids.append(paper_id)
        updated["paper_ids"] = list(dict.fromkeys(paper_ids))
        updated["paper_refs"] = paper_refs

        old_gap_refs = manifest.get("gap_refs") if isinstance(manifest.get("gap_refs"), dict) else {}
        old_bundle_refs = manifest.get("bundle_refs") if isinstance(manifest.get("bundle_refs"), dict) else {}
        old_contract_refs = manifest.get("contract_refs") if isinstance(manifest.get("contract_refs"), dict) else {}
        old_report_refs = manifest.get("report_refs") if isinstance(manifest.get("report_refs"), dict) else {}
        gap_refs: dict[str, dict[str, Any]] = {}
        bundle_refs: dict[str, dict[str, Any]] = {}
        contract_refs: dict[str, dict[str, Any]] = {}
        report_refs: dict[str, dict[str, Any]] = {}
        fragment_candidates: dict[str, dict[str, Any]] = {}
        transaction_run_id = f"state_{new_version:04d}"

        gap_ids: list[str] = []
        for gap in payload.get("knowledge_gaps", []):
            if not isinstance(gap, dict) or not str(gap.get("gap_id") or ""):
                continue
            gap_id = str(gap.get("gap_id") or "")
            gap_ids.append(gap_id)
            old_gap_ref = old_gap_refs.get(gap_id) if isinstance(old_gap_refs.get(gap_id), dict) else None
            old_bundle_ref = old_bundle_refs.get(gap_id) if isinstance(old_bundle_refs.get(gap_id), dict) else None
            old_contract_ref = old_contract_refs.get(gap_id) if isinstance(old_contract_refs.get(gap_id), dict) else None
            old_report_ref = old_report_refs.get(gap_id) if isinstance(old_report_refs.get(gap_id), dict) else None
            if not all(isinstance(item, dict) for item in (old_gap_ref, old_bundle_ref, old_contract_ref)):
                recovered_chain = self._recover_orphan_gap_chain_refs(
                    project_id,
                    gap_id,
                    state_store_id=active_store_id,
                )
                if isinstance(recovered_chain, dict):
                    old_gap_ref = copy.deepcopy(recovered_chain["gap_ref"])
                    old_bundle_ref = copy.deepcopy(recovered_chain["bundle_ref"])
                    old_contract_ref = copy.deepcopy(recovered_chain["contract_ref"])
                    self._log_state_recovery(
                        "normalized_orphan_gap_chain_rebound",
                        project_id=project_id,
                        gap_id=gap_id,
                        gap_ref_path=str(old_gap_ref.get("path") or ""),
                        bundle_ref_path=str(old_bundle_ref.get("path") or ""),
                        contract_ref_path=str(old_contract_ref.get("path") or ""),
                        action="use_orphan_chain_as_previous_ref_before_versioning",
                    )
            if (
                "gaps" not in changed_groups
                and isinstance(old_gap_ref, dict)
                and isinstance(old_bundle_ref, dict)
                and isinstance(old_contract_ref, dict)
            ):
                gap_refs[gap_id] = copy.deepcopy(old_gap_ref)
                bundle_refs[gap_id] = copy.deepcopy(old_bundle_ref)
                contract_refs[gap_id] = copy.deepcopy(old_contract_ref)
                if isinstance(old_report_ref, dict):
                    report_refs[gap_id] = copy.deepcopy(old_report_ref)
                continue
            artifact_set = build_normalized_gap_artifact_set(
                payload,
                gap,
                run_id=transaction_run_id,
            )
            gap_artifact = copy.deepcopy(artifact_set["gap"])
            bundle = copy.deepcopy(artifact_set["bundle"])
            contract = copy.deepcopy(artifact_set["contract"])
            report = copy.deepcopy(artifact_set["report"])
            gap_version = int((old_gap_ref or {}).get("artifact_version") or 0) + 1
            bundle_version = int((old_bundle_ref or {}).get("artifact_version") or 0) + 1
            contract_version = int((old_contract_ref or {}).get("artifact_version") or 0) + 1
            report_version = int((old_report_ref or {}).get("artifact_version") or 0) + 1
            gap_path = self._next_artifact_path(
                f"gaps/{_safe_identifier(gap_id)}.json",
                artifact_version=gap_version,
                previous_ref=old_gap_ref,
            )
            bundle_path = f"bundles/{_safe_identifier(gap_id)}/v{bundle_version:04d}.json"
            contract_path = f"contracts/{_safe_identifier(gap_id)}/v{contract_version:04d}.json"
            report_path = f"reports/{_safe_identifier(transaction_run_id)}_{_safe_identifier(gap_id)}.json"

            bundle["bundle_version"] = bundle_version
            bundle["content_hash"] = artifact_content_hash(bundle)
            gap_artifact["gap_version"] = gap_version
            gap_artifact["evidence_bundle_ref"] = bundle_path
            gap_artifact["latest_contract_ref"] = contract_path
            gap_artifact["content_hash"] = artifact_content_hash(gap_artifact)
            contract["contract_version"] = contract_version
            contract["gap_ref"] = gap_path
            contract["gap_snapshot_hash"] = str(gap_artifact["content_hash"])
            contract["evidence_bundle_ref"] = bundle_path
            contract["evidence_bundle_hash"] = str(bundle["content_hash"])
            contract["content_hash"] = artifact_content_hash(contract)
            report["run_id"] = transaction_run_id
            report["contract_ref"] = contract_path
            report["query_audit_ref"] = f"audits/socrates_queries/{transaction_run_id}.jsonl"
            report["content_hash"] = artifact_content_hash(report)
            for artifact in (gap_artifact, bundle, contract, report):
                validate_normalized_artifact(artifact)
            writes.update({
                gap_path: gap_artifact,
                bundle_path: bundle,
                contract_path: contract,
                report_path: report,
            })
            writes.setdefault(report["query_audit_ref"], b"")
            gap_refs[gap_id] = api["science_artifact_ref"](
                state_store_id=active_store_id, project_id=project_id,
                artifact_type="gap", artifact_id=gap_id,
                artifact_version=gap_version, path=gap_path,
                artifact_hash=str(gap_artifact["content_hash"]),
            )
            bundle_refs[gap_id] = api["science_artifact_ref"](
                state_store_id=active_store_id, project_id=project_id,
                artifact_type="bundle", artifact_id=gap_id,
                artifact_version=bundle_version, path=bundle_path,
                artifact_hash=str(bundle["content_hash"]),
            )
            contract_refs[gap_id] = api["science_artifact_ref"](
                state_store_id=active_store_id, project_id=project_id,
                artifact_type="contract", artifact_id=gap_id,
                artifact_version=contract_version, path=contract_path,
                artifact_hash=str(contract["content_hash"]),
            )
            report_refs[gap_id] = api["science_artifact_ref"](
                state_store_id=active_store_id, project_id=project_id,
                artifact_type="report", artifact_id=f"{transaction_run_id}:{gap_id}",
                artifact_version=report_version, path=report_path,
                artifact_hash=str(report["content_hash"]),
            )
            changed_storage_groups.update({"gaps", "bundles", "contracts", "reports"})
            for fragment in artifact_set.get("canonical_fragments", []):
                if isinstance(fragment, dict) and str(fragment.get("fragment_id") or ""):
                    fragment_candidates[str(fragment["fragment_id"])] = fragment
        updated["gap_ids"] = list(dict.fromkeys(gap_ids))
        updated["knowledge_gap_ids"] = list(dict.fromkeys(gap_ids))
        updated["gap_refs"] = gap_refs
        updated["bundle_refs"] = bundle_refs
        updated["contract_refs"] = contract_refs
        updated["report_refs"] = report_refs

        registry_ref = manifest.get("fragment_registry_ref")
        registry = self.resolve_ref(registry_ref) if isinstance(registry_ref, dict) else fragment_registry_document({})
        registry_entries = dict(registry.get("entries") or {})
        grouped_new: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for fragment_id, fragment in fragment_candidates.items():
            if fragment_id in registry_entries:
                if registry_entries[fragment_id].get("content_hash") != fragment.get("content_hash"):
                    raise ScienceStateError(f"Canonical fragment collision: {fragment_id}")
                continue
            key = (
                _safe_identifier(fragment.get("alignment_contract_hash")),
                _safe_identifier(fragment.get("paper_id")),
            )
            if all(key):
                grouped_new.setdefault(key, []).append(fragment)
        for (alignment_hash, paper_id), records in grouped_new.items():
            jsonl_path = f"fragments/{alignment_hash}/{paper_id}.v{new_version:04d}.jsonl"
            index_path = f"fragments/{alignment_hash}/{paper_id}.v{new_version:04d}.index.json"
            jsonl_bytes, local_index = encode_indexed_jsonl(records)
            writes[jsonl_path] = jsonl_bytes
            writes[index_path] = fragment_index_document(
                alignment_contract_hash=alignment_hash,
                paper_id=str(records[0].get("paper_id") or paper_id),
                jsonl_path=jsonl_path,
                entries=local_index,
            )
            file_hash = "sha256:" + sha256(jsonl_bytes).hexdigest()
            for fragment in records:
                fragment_id = str(fragment["fragment_id"])
                location = local_index[fragment_id]
                registry_entries[fragment_id] = {
                    "alignment_contract_hash": alignment_hash,
                    "paper_id": str(fragment.get("paper_id") or ""),
                    "file": jsonl_path,
                    "index_file": index_path,
                    "offset": int(location["offset"]),
                    "length": int(location["length"]),
                    "file_hash": file_hash,
                    "content_hash": str(fragment.get("content_hash") or ""),
                }
        if grouped_new:
            registry_document = fragment_registry_document(registry_entries)
            registry_version = int((registry_ref or {}).get("artifact_version") or 0) + 1
            registry_path = self._next_artifact_path(
                "fragments/fragment_registry.json",
                artifact_version=registry_version,
                previous_ref=registry_ref if isinstance(registry_ref, dict) else None,
            )
            writes[registry_path] = registry_document
            updated["fragment_registry_ref"] = api["science_artifact_ref"](
                state_store_id=active_store_id, project_id=project_id,
                artifact_type="fragment_registry", artifact_id="fragment_registry",
                artifact_version=registry_version, path=registry_path,
                artifact_hash=str(registry_document["content_hash"]),
            )
            changed_storage_groups.add("fragments")

        updated["ranked_gap_ids"] = self._ids_from_gap_values(
            (payload.get("tanxi_gap_analysis") or {}).get("ranked_gaps", [])
            if isinstance(payload.get("tanxi_gap_analysis"), dict) else []
        )
        updated["primary_gap_ids"] = self._ids_from_gap_values(payload.get("primary_scientific_gaps", []))
        updated["secondary_gap_ids"] = self._ids_from_gap_values(payload.get("secondary_scientific_gaps", []))
        updated["project_metadata"] = {
            "title": str(payload.get("title") or ""),
            "domain": str(payload.get("domain") or ""),
            "objective": str(payload.get("objective") or ""),
            "phase": str(payload.get("phase") or ""),
        }
        updated["state_version"] = new_version
        updated["artifact_versions"] = artifact_versions
        for group in changed_storage_groups:
            if group not in changed_groups:
                updated["artifact_versions"][group] = int(
                    (manifest.get("artifact_versions") or {}).get(group, 0)
                ) + 1
        updated["latest_run_id"] = transaction_run_id
        updated["latest_report_ref"] = next(reversed(report_refs.values()), None) if report_refs else None
        updated["updated_at"] = time.time()
        updated["last_committed_transaction_id"] = "PENDING_TRANSACTION_ID"
        updated = api["finalize_manifest"](updated)
        self._commit_normalized_transaction(
            project_id,
            artifact_writes=writes,
            manifest=updated,
            expected_version=current_version,
            operation="SAVE_MATERIALIZED_PROJECT",
        )
        refreshed = self._materialize_normalized_project(project_id)
        project.clear()
        project.update(refreshed)

    def preview_normalized_gap_artifacts(
        self,
        project_id: str,
        gap_id: str,
        *,
        run_id: str,
    ) -> dict[str, Any]:
        """Build and validate one normalized gap artifact set without writes.

        Only the canonical ``knowledge_gaps`` collection may supply the gap;
        ranked/primary/secondary copies are intentionally ignored so a stale
        duplicate cannot become the migration source.  Physical persistence
        waits for the manifest transaction layer.
        """
        normalized_gap_id = str(gap_id or "").strip()
        normalized_run_id = str(run_id or "").strip()
        if not normalized_gap_id or not normalized_run_id:
            raise ScienceStateError("Normalized gap artifact preview requires gap_id and run_id")
        project = self.get_project(project_id)
        gap = next((
            item for item in project.get("knowledge_gaps", [])
            if isinstance(item, dict) and str(item.get("gap_id") or "") == normalized_gap_id
        ), None)
        if not isinstance(gap, dict):
            raise ScienceStateError(
                f"Canonical knowledge gap not found for normalized artifact preview: {normalized_gap_id}"
            )
        try:
            from ._science_artifacts import build_normalized_gap_artifact_set
        except ImportError:
            from _science_artifacts import build_normalized_gap_artifact_set
        artifact_set = build_normalized_gap_artifact_set(
            project,
            gap,
            run_id=normalized_run_id,
        )
        layout = self.normalized_project_layout(project_id)
        root = Path(str(layout["project_root"]))
        bundle_version = int(artifact_set["bundle"].get("bundle_version") or 1)
        contract_version = int(artifact_set["contract"].get("contract_version") or 1)
        fragment_targets: dict[str, dict[str, str]] = {}
        for fragment in artifact_set.get("canonical_fragments", []):
            if not isinstance(fragment, dict):
                continue
            contract_hash = _safe_identifier(fragment.get("alignment_contract_hash"))
            paper_id = _safe_identifier(fragment.get("paper_id"))
            key = f"{contract_hash}:{paper_id}"
            fragment_targets[key] = {
                "jsonl": str(root / "fragments" / contract_hash / f"{paper_id}.jsonl"),
                "index": str(root / "fragments" / contract_hash / f"{paper_id}.index.json"),
            }
        preview = copy.deepcopy(artifact_set)
        preview.update({
            "persistence_mode": "DRY_RUN",
            "storage_activated": False,
            "source_project_state_version": int(project.get("state_version") or 0),
            "source_state_store_id": str(project.get("state_store_id") or ""),
            "planned_paths": {
                "gap": str(root / "gaps" / f"{_safe_identifier(normalized_gap_id)}.json"),
                "bundle": str(root / "bundles" / _safe_identifier(normalized_gap_id) / f"v{bundle_version:04d}.json"),
                "contract": str(root / "contracts" / _safe_identifier(normalized_gap_id) / f"v{contract_version:04d}.json"),
                "report": str(root / "reports" / f"{_safe_identifier(normalized_run_id)}.json"),
                "fragment_candidate_audit": str(root / "audits" / "fragment_candidates" / f"{_safe_identifier(normalized_run_id)}.jsonl"),
                "socrates_query_audit": str(root / "audits" / "socrates_queries" / f"{_safe_identifier(normalized_run_id)}.jsonl"),
                "canonical_fragment_files": fragment_targets,
            },
        })
        return preview

    def _materialize_normalized_project(self, project_id: str) -> dict[str, Any]:
        manifest = self.get_project_manifest(project_id)
        project: dict[str, Any] = {}
        missing_project_field_refs: list[dict[str, Any]] = []
        for field_name, ref in (manifest.get("project_field_refs") or {}).items():
            if not isinstance(ref, dict) or str(field_name).startswith("fragment_audit:"):
                continue
            try:
                document = self.resolve_ref(ref)
            except (ScienceStateError, FileNotFoundError, ValueError) as exc:
                if not self._is_missing_or_temporary_artifact_error(exc):
                    raise
                ref_path = str(ref.get("path") or "")
                audit_entry = {
                    "field_name": str(field_name),
                    "ref_path": ref_path,
                    "artifact_type": str(ref.get("artifact_type") or ""),
                    "artifact_version": int(ref.get("artifact_version") or 0),
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                    "temporary_transaction_path": self._is_temporary_transaction_artifact_path(ref_path),
                    "recovery_action": "skip_project_field_ref_and_rebuild_if_derivable",
                }
                missing_project_field_refs.append(audit_entry)
                self._log_state_recovery(
                    "normalized_project_field_ref_missing",
                    project_id=project_id,
                    field_name=str(field_name),
                    ref_path=ref_path,
                    artifact_version=audit_entry["artifact_version"],
                    temporary_transaction_path=audit_entry["temporary_transaction_path"],
                    action=audit_entry["recovery_action"],
                    error_type=type(exc).__name__,
                    error=str(exc)[:240],
                )
                continue
            if (
                isinstance(document, dict)
                and document.get("schema_version") == "science_project_field_v1"
                and str(document.get("field_name") or "") == str(field_name)
            ):
                project[str(field_name)] = copy.deepcopy(document.get("value"))
        if str(manifest.get("v3_research_question_state_schema_version") or "") == (
            V3_RESEARCH_QUESTION_STATE_SCHEMA_VERSION
        ):
            contract_documents = self.load_v3_subhypothesis_contracts(project_id)
            executions = self.load_v3_retrieval_executions(project_id)
            project["sub_hypotheses"] = [
                self._v3_runtime_subhypothesis(document)
                for document in contract_documents
            ]
            project["research_question_retrieval_executions_v3"] = executions
            project["v3_research_question_state_schema_version"] = (
                V3_RESEARCH_QUESTION_STATE_SCHEMA_VERSION
            )
            for index, sub_hypothesis in enumerate(project["sub_hypotheses"]):
                sub_hypothesis_id = _v3_subhypothesis_id(sub_hypothesis, index)
                execution = executions.get(sub_hypothesis_id)
                if isinstance(execution, dict):
                    sub_hypothesis["research_question_retrieval_execution"] = (
                        copy.deepcopy(execution)
                    )
        if missing_project_field_refs:
            metadata = manifest.get("project_metadata") if isinstance(manifest.get("project_metadata"), dict) else {}
            for metadata_field in ("title", "domain", "objective", "phase"):
                if metadata_field not in project and metadata_field in metadata:
                    project[metadata_field] = copy.deepcopy(metadata.get(metadata_field))
            missing_field_names = {
                str(item.get("field_name") or "") for item in missing_project_field_refs
            }
            if (
                "subhypothesis_scientific_operationality_preflight" in missing_field_names
                and "subhypothesis_scientific_operationality_preflight" not in project
            ):
                try:
                    from ._project import apply_subhypothesis_scientific_operationality_preflight
                except ImportError:
                    try:
                        from _project import apply_subhypothesis_scientific_operationality_preflight
                    except ImportError:
                        apply_subhypothesis_scientific_operationality_preflight = None
                if apply_subhypothesis_scientific_operationality_preflight is not None:
                    apply_subhypothesis_scientific_operationality_preflight(project)
                    self._log_state_recovery(
                        "normalized_project_field_rebuilt",
                        project_id=project_id,
                        field_name="subhypothesis_scientific_operationality_preflight",
                        source="sub_hypotheses",
                        reason="missing_project_field_ref_recovery",
                    )
            recovery = project.get("normalized_storage_recovery")
            recovery = copy.deepcopy(recovery) if isinstance(recovery, dict) else {}
            existing_missing = [
                item for item in recovery.get("missing_project_field_refs", [])
                if isinstance(item, dict)
            ]
            existing_missing.extend(missing_project_field_refs)
            recovery["missing_project_field_refs"] = existing_missing[-50:]
            rebuilt = [
                name for name in (
                    "sub_hypotheses",
                    "subhypothesis_scientific_operationality_preflight",
                )
                if name in project
                and any(str(item.get("field_name") or "") == name for item in missing_project_field_refs)
            ]
            if rebuilt:
                recovery["rebuilt_project_fields"] = list(dict.fromkeys(
                    [*(str(item) for item in recovery.get("rebuilt_project_fields", []) if str(item)), *rebuilt]
                ))[-50:]
            recovery["last_recovered_at"] = time.time()
            project["normalized_storage_recovery"] = recovery
        bundle_extensions = project.pop("_normalized_bundle_extensions", {})
        if not isinstance(bundle_extensions, dict):
            bundle_extensions = {}
        project["project_id"] = project_id
        project.pop("research_evidence_graphs", None)
        project["research_evidence_graphs"] = []
        graph_ref = manifest.get("active_research_evidence_graph_ref")
        if isinstance(graph_ref, dict):
            project["active_research_evidence_graph_ref"] = copy.deepcopy(graph_ref)
        project["papergraph"] = [
            self.get_paper(project_id, paper_id)
            for paper_id in manifest.get("paper_ids", [])
            if str(paper_id) in (manifest.get("paper_refs") or {})
        ]
        gaps = project.get("knowledge_gaps")
        if not isinstance(gaps, list):
            gaps = [
                self.get_gap(project_id, gap_id)
                for gap_id in manifest.get("knowledge_gap_ids", [])
                if str(gap_id) in (manifest.get("gap_refs") or {})
            ]
            project["knowledge_gaps"] = gaps
        else:
            legacy_gap_by_id = {
                str(item.get("gap_id") or ""): item
                for item in gaps if isinstance(item, dict)
            }
            for gap_id in manifest.get("knowledge_gap_ids", []):
                if str(gap_id) not in (manifest.get("gap_refs") or {}):
                    continue
                normalized_gap = self.get_gap(project_id, str(gap_id))
                target = legacy_gap_by_id.get(str(gap_id))
                if target is None:
                    gaps.append(normalized_gap)
                    legacy_gap_by_id[str(gap_id)] = gaps[-1]
                    target = gaps[-1]
                else:
                    target.update(copy.deepcopy(normalized_gap))
                if str(gap_id) in (manifest.get("bundle_refs") or {}):
                    normalized_bundle = self.get_bundle(project_id, str(gap_id))
                    legacy_bundle = copy.deepcopy(bundle_extensions.get(str(gap_id)) or {})
                    legacy_bundle.update(copy.deepcopy(normalized_bundle))
                    refs: list[str] = []
                    for role in ("input", "mediator", "outcome"):
                        role_value = normalized_bundle.get(role)
                        if isinstance(role_value, dict):
                            refs.extend(str(item) for item in role_value.get("fragment_refs", []))
                    refs.extend(
                        str(item) for item in normalized_bundle.get("competing_fragment_refs", [])
                    )
                    refs.extend(
                        str(item) for item in normalized_bundle.get("rejected_audit_fragment_refs", [])
                    )
                    materialized_fragments = [
                        self.get_fragment(project_id, fragment_id)
                        for fragment_id in dict.fromkeys(refs)
                    ]
                    legacy_bundle["evidence_fragment_alignments"] = materialized_fragments
                    design = legacy_bundle.get("research_design_evidence")
                    if isinstance(design, dict):
                        design["fragment_alignments"] = copy.deepcopy(materialized_fragments)
                    target["mechanism_evidence_bundle"] = legacy_bundle
        gap_by_id = {
            str(item.get("gap_id") or ""): item
            for item in gaps
            if isinstance(item, dict) and str(item.get("gap_id") or "")
        }
        project["primary_scientific_gaps"] = [
            copy.deepcopy(gap_by_id[gap_id])
            for gap_id in manifest.get("primary_gap_ids", [])
            if gap_id in gap_by_id
        ]
        project["secondary_scientific_gaps"] = [
            copy.deepcopy(gap_by_id[gap_id])
            for gap_id in manifest.get("secondary_gap_ids", [])
            if gap_id in gap_by_id
        ]
        tanxi = project.get("tanxi_gap_analysis")
        if isinstance(tanxi, dict):
            ranked_ids = [
                str(item) for item in tanxi.pop("ranked_gap_ids", manifest.get("ranked_gap_ids", []))
            ]
            tanxi["ranked_gaps"] = [
                copy.deepcopy(gap_by_id[gap_id]) for gap_id in ranked_ids if gap_id in gap_by_id
            ]
        contracts = project.get("socrates_mechanism_contracts")
        if not isinstance(contracts, dict):
            contracts = {}
        for gap_id in manifest.get("contract_refs", {}):
            normalized_contract = self.get_contract(project_id, gap_id)
            if gap_id not in contracts:
                contracts[gap_id] = normalized_contract
            elif isinstance(contracts.get(gap_id), dict):
                for key, value in normalized_contract.items():
                    contracts[gap_id][key] = copy.deepcopy(value)
            if isinstance(contracts.get(gap_id), dict) and not isinstance(
                contracts[gap_id].get("mechanism_evidence_bundle"), dict
            ):
                gap_bundle = (gap_by_id.get(gap_id) or {}).get("mechanism_evidence_bundle")
                if isinstance(gap_bundle, dict):
                    contracts[gap_id]["mechanism_evidence_bundle"] = copy.deepcopy(gap_bundle)
        project["socrates_mechanism_contracts"] = contracts
        reports = project.get("socrates_reports")
        if not isinstance(reports, list):
            reports = []
        for report in reports:
            if not isinstance(report, dict) or isinstance(report.get("mechanism_contract"), dict):
                continue
            contract = contracts.get(str(report.get("gap_id") or ""))
            if isinstance(contract, dict):
                report["mechanism_contract"] = copy.deepcopy(contract)
        project["socrates_reports"] = reports
        project["state_version"] = int(manifest.get("state_version") or 0)
        project["state_store_id"] = str(manifest.get("state_store_id") or "")
        project["artifact_versions"] = {
            str(key): int(value or 0)
            for key, value in (manifest.get("artifact_versions") or {}).items()
        }
        project["artifacts"] = {
            key: {"version": value} for key, value in project["artifact_versions"].items()
        }
        project["state_context"] = {
            "store_id": project["state_store_id"],
            "loaded_version": project["state_version"],
        }
        activate_project_gap_allocator(project)
        return project

    def get_project(
        self,
        project_id: str,
        materialize_legacy_view: bool = True,
    ) -> dict[str, Any]:
        manifest_path = Path(str(self.normalized_project_layout(project_id)["manifest_path"]))
        if manifest_path.is_file():
            if not materialize_legacy_view:
                return self.get_project_manifest(project_id)
            return self._materialize_normalized_project(project_id)
        path = self._project_path(project_id)
        project = self._reader(path, f"Science project not found: {project_id}")
        self._validate_project_identity(project, project_id)
        self._hydrate_state_metadata(project, self.store_id(project_id))
        hydrate_project_fulltexts(project)
        activate_project_gap_allocator(project)
        return project

    def adopt_project_copy(self, project_id: str, source_store_id: str) -> dict[str, Any]:
        """Explicitly rebind a copied project snapshot to the active store.

        A versioned project copied between ``.science`` roots is deliberately
        rejected by :meth:`get_project`.  Migration code must call this method
        once, naming the source store recorded in the snapshot, so migration
        cannot be confused with an agent accidentally loading a second copy.
        """
        path = self._project_path(project_id)
        active_store_id = self.store_id(project_id)
        with self._lock:
            project = self._reader(path, f"Science project not found: {project_id}")
            self._validate_project_identity(project, project_id)
            recorded_source = str(project.get("state_store_id") or "")
            declared_source = str(source_store_id or "").strip()
            if not declared_source:
                raise ScienceStateStoreMismatch(
                    f"Migration of science project {project_id} requires source_store_id."
                )
            if recorded_source and recorded_source != declared_source:
                raise ScienceStateStoreMismatch(
                    f"Science project {project_id} records source store {recorded_source}, "
                    f"not declared source {declared_source}."
                )
            if declared_source == active_store_id:
                raise ScienceStateStoreMismatch(
                    f"Science project {project_id} is already bound to active store {active_store_id}."
                )

            payload = compact_project_for_persistence(copy.deepcopy(project))
            externalize_project_fulltexts(payload)
            prior_version = int(payload.get("state_version") or 0)
            migrated_at = time.time()
            payload["state_version"] = prior_version + 1
            payload["state_store_id"] = active_store_id
            payload["state_context"] = {
                "store_id": active_store_id,
                "loaded_version": payload["state_version"],
            }
            payload["updatedAt"] = migrated_at
            migrations = [
                item for item in payload.get("state_migrations", []) if isinstance(item, dict)
            ][-49:]
            migrations.append(
                {
                    "source_store_id": declared_source,
                    "target_store_id": active_store_id,
                    "from_version": prior_version,
                    "to_version": payload["state_version"],
                    "migratedAt": migrated_at,
                }
            )
            payload["state_migrations"] = migrations
            transactions = [
                item for item in payload.get("state_transactions", []) if isinstance(item, dict)
            ][-49:]
            transactions.append(
                {
                    "from_version": prior_version,
                    "to_version": payload["state_version"],
                    "changed_artifacts": [],
                    "savedAt": migrated_at,
                    "store_id": active_store_id,
                    "operation": "ADOPT_MIGRATED_PROJECT_COPY",
                }
            )
            payload["state_transactions"] = transactions
            self._writer(path, payload)
        return self.get_project(project_id)

    def save_project(self, project: dict[str, Any], expected_version: int | None = None) -> None:
        project_id = str(project.get("project_id") or "").strip()
        if not project_id:
            raise ScienceStateError("Science project must contain project_id before save")
        manifest_path = Path(str(self.normalized_project_layout(project_id)["manifest_path"]))
        if manifest_path.is_file():
            self._save_normalized_materialized_project(
                project,
                expected_version=expected_version,
            )
            return
        path = self._project_path(project_id)
        active_store_id = self.store_id(project_id)
        context = project.get("state_context") if isinstance(project.get("state_context"), dict) else {}
        bound_store_id = str(context.get("store_id") or project.get("state_store_id") or "")
        if bound_store_id and bound_store_id != active_store_id:
            raise ScienceStateStoreMismatch(
                f"Science project {project_id} was loaded from {bound_store_id} but save targets {active_store_id}."
            )
        with self._lock:
            current: dict[str, Any] = {}
            if path.exists():
                current = self._reader(path, f"Science project not found: {project_id}")
                self._validate_project_identity(current, project_id)
                persisted_store_id = str(current.get("state_store_id") or "")
                if persisted_store_id and persisted_store_id != active_store_id:
                    raise ScienceStateStoreMismatch(
                        f"Science project {project_id} belongs to {persisted_store_id}, "
                        f"active store is {active_store_id}; use explicit migration adoption."
                    )
            current_version = int(current.get("state_version") or 0)
            loaded_version = expected_version
            if loaded_version is None and context:
                loaded_version = int(context.get("loaded_version") or 0)
            if loaded_version is not None and current and int(loaded_version) != current_version:
                raise StaleScienceStateError(
                    f"stale science state for project {project_id}: expected version {loaded_version}, current version {current_version}"
                )

            payload = compact_project_for_persistence(copy.deepcopy(project))
            externalize_project_fulltexts(payload)
            new_version = current_version + 1
            changed = self._changed_artifacts(current, payload)
            artifact_versions = self._artifact_versions(current)
            for name in changed:
                artifact_versions[name] = int(artifact_versions.get(name, 0)) + 1
            payload["state_version"] = new_version
            payload["state_store_id"] = active_store_id
            payload["artifact_versions"] = artifact_versions
            payload["artifacts"] = {
                name: {"version": int(version)} for name, version in artifact_versions.items()
            }
            payload["state_context"] = {
                "store_id": active_store_id,
                "loaded_version": new_version,
            }
            payload["updatedAt"] = time.time()
            changed_contract_ids = self._changed_contract_ids(current, payload)
            self._stamp_gap_context(
                payload,
                current,
                new_version,
                artifact_versions.get("gaps", 0),
                changed_contract_ids,
            )
            history = [item for item in current.get("state_transactions", []) if isinstance(item, dict)][-49:]
            history.append(
                {
                    "from_version": current_version,
                    "to_version": new_version,
                    "changed_artifacts": changed,
                    "savedAt": payload["updatedAt"],
                    "store_id": active_store_id,
                }
            )
            payload["state_transactions"] = history
            self._writer(path, payload)
            # V2 source evidence is intentionally not retained in a growing
            # monolithic project snapshot.  Once this first legacy write has a
            # durable version, atomically switch it to the normalized manifest
            # store; later saves take the incremental normalized path above.
            self.activate_normalized_project_storage(
                project_id,
                expected_version=new_version,
                run_id=f"automatic_v2_evidence_cutover_{new_version:04d}",
            )
            project.clear()
            project.update(self.get_project(project_id))

    def _validate_project_identity(self, project: dict[str, Any], requested_project_id: str) -> None:
        actual = str(project.get("project_id") or "")
        if actual != str(requested_project_id):
            raise ScienceStateError(
                f"Project identity mismatch: requested {requested_project_id}, loaded {actual or '<missing>'}."
            )

    def _hydrate_state_metadata(self, project: dict[str, Any], store_id: str) -> None:
        version = int(project.get("state_version") or 0)
        persisted_store = str(project.get("state_store_id") or "")
        if persisted_store and persisted_store != store_id:
            raise ScienceStateStoreMismatch(
                f"Science project {project.get('project_id')} belongs to {persisted_store}, active store is {store_id}."
            )
        project["state_version"] = version
        project["state_store_id"] = store_id
        project["artifact_versions"] = self._artifact_versions(project)
        project["artifacts"] = {
            name: {"version": value} for name, value in project["artifact_versions"].items()
        }
        project["state_context"] = {"store_id": store_id, "loaded_version": version}

    def _artifact_versions(self, project: dict[str, Any]) -> dict[str, int]:
        stored = project.get("artifact_versions") if isinstance(project.get("artifact_versions"), dict) else {}
        nested = project.get("artifacts") if isinstance(project.get("artifacts"), dict) else {}
        return {
            name: int(stored.get(name) or ((nested.get(name) or {}).get("version") if isinstance(nested.get(name), dict) else 0) or 0)
            for name in ARTIFACT_GROUPS
        }

    def _changed_artifacts(self, current: dict[str, Any], incoming: dict[str, Any]) -> list[str]:
        if not current:
            return list(ARTIFACT_GROUPS)
        changed: list[str] = []
        for name, keys in ARTIFACT_GROUPS.items():
            before = {key: current.get(key) for key in keys}
            after = {key: incoming.get(key) for key in keys}
            if json.dumps(before, ensure_ascii=False, sort_keys=True, default=str) != json.dumps(
                after, ensure_ascii=False, sort_keys=True, default=str
            ):
                changed.append(name)
        return changed

    def _changed_contract_ids(self, current: dict[str, Any], incoming: dict[str, Any]) -> set[str]:
        before = current.get("socrates_mechanism_contracts") if isinstance(current.get("socrates_mechanism_contracts"), dict) else {}
        after = incoming.get("socrates_mechanism_contracts") if isinstance(incoming.get("socrates_mechanism_contracts"), dict) else {}

        def scientific_body(contract: Any) -> Any:
            if not isinstance(contract, dict):
                return contract
            return {
                key: value
                for key, value in contract.items()
                if key not in {
                    "project_id", "project_version", "gap_id", "gap_artifact_version",
                    "gap_snapshot", "gap_handoff",
                }
            }

        return {
            str(gap_id)
            for gap_id, contract in after.items()
            if gap_id not in before
            or scientific_body(before.get(gap_id)) != scientific_body(contract)
            or not isinstance(contract, dict)
            or not isinstance(contract.get("gap_handoff"), dict)
        }

    def _stamp_gap_context(
        self,
        project: dict[str, Any],
        current: dict[str, Any],
        state_version: int,
        gap_version: int,
        changed_contract_ids: set[str],
    ) -> None:
        project_id = str(project.get("project_id") or "")
        current_gaps = {
            str(item.get("gap_id") or ""): item
            for item in current.get("knowledge_gaps", [])
            if isinstance(item, dict) and str(item.get("gap_id") or "")
        }
        gap_by_id: dict[str, dict[str, Any]] = {}
        maximum = 0
        for gap in project.get("knowledge_gaps", []):
            if not isinstance(gap, dict):
                continue
            gap_id = str(gap.get("gap_id") or "")
            if not gap_id:
                gap_id = new_science_gap_id(project_id)
                gap["gap_id"] = gap_id
            gap["project_id"] = project_id
            gap.setdefault("created_state_version", state_version)
            previous = current_gaps.get(gap_id, {})
            previous_hash = str(previous.get("gap_snapshot_hash") or "")
            if not previous_hash and previous:
                previous_hash = science_gap_snapshot_hash(previous)
            current_hash = science_gap_snapshot_hash(gap)
            previous_revision = int(previous.get("gap_revision") or 1) if previous else 0
            if not previous:
                gap_revision = 1
            elif previous_hash == current_hash:
                gap_revision = max(1, previous_revision)
            else:
                gap_revision = max(1, previous_revision) + 1
            # ``gap_artifact_version`` remains an audit-level collection
            # version for backward compatibility.  MingLi handoff validity is
            # determined by the gap-local revision/hash below, so unrelated
            # Socrates writes cannot stale an otherwise unchanged contract.
            gap["gap_artifact_version"] = int(gap_version)
            gap["gap_revision"] = gap_revision
            gap["gap_snapshot_hash"] = current_hash
            gap_by_id[gap_id] = gap
            maximum = max(maximum, _gap_sequence_from_id(gap_id, project_id))
        project["next_gap_sequence"] = max(int(project.get("next_gap_sequence") or 1), maximum + 1)
        contracts = project.get("socrates_mechanism_contracts")
        stamped_contracts: dict[str, dict[str, Any]] = {}
        if isinstance(contracts, dict):
            for gap_id, contract in contracts.items():
                if not isinstance(contract, dict):
                    continue
                if str(gap_id) not in changed_contract_ids:
                    continue
                gap = gap_by_id.get(str(gap_id), {})
                contract["project_id"] = project_id
                contract["project_version"] = state_version
                contract["gap_id"] = str(gap_id)
                contract["gap_artifact_version"] = int(gap_version)
                contract["gap_revision"] = int(gap.get("gap_revision") or 1)
                contract["gap_snapshot_hash"] = str(gap.get("gap_snapshot_hash") or science_gap_snapshot_hash(gap))
                contract["gap_snapshot"] = science_gap_handoff_snapshot(gap)
                contract["gap_handoff"] = {
                    "schema_version": "gap_snapshot_handoff_v2",
                    "project_id": project_id,
                    "state_store_id": str(project.get("state_store_id") or ""),
                    "project_version": state_version,
                    "gap_artifact_version": int(gap_version),
                    "gap_revision": int(gap.get("gap_revision") or 1),
                    "gap_snapshot_hash": str(gap.get("gap_snapshot_hash") or science_gap_snapshot_hash(gap)),
                    "gap_id": str(gap_id),
                    "gap_snapshot": copy.deepcopy(contract["gap_snapshot"]),
                }
                stamped_contracts[str(gap_id)] = contract
        reports = project.get("socrates_reports")
        if isinstance(reports, list) and stamped_contracts:
            pending_report_gap_ids = set(stamped_contracts)
            for report in reversed(reports):
                if not isinstance(report, dict):
                    continue
                gap_id = str(report.get("gap_id") or "")
                if gap_id not in pending_report_gap_ids:
                    continue
                if isinstance(report.get("science_state_handoff"), dict):
                    continue
                contract = stamped_contracts.get(gap_id)
                if not contract:
                    continue
                report["project_id"] = project_id
                report["project_version"] = state_version
                report["gap_artifact_version"] = int(gap_version)
                report["gap_revision"] = int(gap.get("gap_revision") or 1)
                report["gap_snapshot_hash"] = str(gap.get("gap_snapshot_hash") or science_gap_snapshot_hash(gap))
                report["science_state_handoff"] = copy.deepcopy(contract["gap_handoff"])
                report["mechanism_contract"] = copy.deepcopy(contract)
                pending_report_gap_ids.remove(gap_id)
