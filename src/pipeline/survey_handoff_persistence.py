"""Atomic publication and verification for one completed Survey run."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from .survey_evidence_plan import SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION
from .survey_gap_ledger import build_deterministic_gap_ledger
from .survey_gap_candidates import (
    build_gap_candidate_ledger_payload,
    extract_gap_candidates,
)
from .survey_gap_adjudication import build_gap_coverage_artifact
from .survey_handoff_projection import build_survey_idea_handoff_projection
from .survey_idea_handoff import (
    ArtifactManifestEntry,
    SurveyManifest,
    build_manifest_payload,
    validate_manifest_payload,
)


SURVEY_MANIFEST_FILENAME = "survey_manifest.json"
_ARTIFACT_FILENAMES = {
    "survey_markdown": "survey.md",
    "survey_json": "survey.json",
    "survey_outline": "survey_outline.json",
    "project_context": "project_context.json",
    "evidence_plan": "survey_evidence_plan.json",
    "claim_traceability": "survey_claim_traceability.json",
    "gap_ledger": "survey_gap_ledger.json",
    "gap_candidates": "survey_gap_candidates.json",
    "gap_coverage": "survey_gap_coverage.json",
    "gap_triage": "survey_gap_triage.json",
    "idea_handoff": "survey_idea_handoff.json",
}


class SurveyArtifactPublicationError(RuntimeError):
    """Raised when a Survey run cannot be published as a completed manifest."""


def _text(value: Any, *, limit: int | None = None) -> str:
    text = str(value or "").strip()
    return text if limit is None else text[:limit]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    """Replace one artifact atomically after forcing its staged bytes to disk."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _project_id(project_context: Mapping[str, Any], evidence_plan: Mapping[str, Any], survey_run_id: str) -> str:
    project_id = _text(evidence_plan.get("project_id")) or _text(project_context.get("project_id"))
    if project_id:
        return project_id
    stable_run_id = re.sub(r"[^A-Za-z0-9_]+", "_", survey_run_id).strip("_")
    return f"sci_{stable_run_id or 'survey'}"


def _context_fingerprint(project_context: Mapping[str, Any], evidence_plan: Mapping[str, Any]) -> str:
    nested = _mapping(project_context.get("research_context"))
    return (
        _text(evidence_plan.get("project_context_fingerprint"))
        or _text(project_context.get("project_context_fingerprint"))
        or _text(project_context.get("input_fingerprint"))
        or _text(nested.get("input_fingerprint"))
    )


def build_project_context_artifact(
    project_context: Mapping[str, Any] | None,
    *,
    project_id: str,
) -> dict[str, Any]:
    """Normalize raw research context to the persisted Survey context artifact."""

    context = _mapping(project_context)
    if context.get("schema_version") == "survey_project_context_artifact_v1":
        artifact = dict(context)
        artifact.setdefault("project_id", project_id)
        return artifact
    return {
        "schema_version": "survey_project_context_artifact_v1",
        "event": "project_created",
        "project_id": project_id,
        "declared_domain": context.get("declared_domain", ""),
        "domain": context.get("domain", ""),
        "research_domains": context.get("research_domains", []),
        "domain_resolution_source": context.get("domain_resolution_source", ""),
        "requires_human_confirmation": bool(context.get("requires_human_confirmation")),
        "research_context": context,
    }


def _valid_evidence_plan(plan: Mapping[str, Any], fingerprint: str) -> bool:
    return bool(
        plan.get("schema_version") == SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION
        and _text(plan.get("project_id"))
        and _text(plan.get("project_context_fingerprint"))
        and _text(plan.get("project_context_fingerprint")) == fingerprint
        and isinstance(plan.get("subhypotheses"), list)
    )


def _claim_traceability_artifact(
    value: Mapping[str, Any] | None,
    *,
    project_id: str,
    fingerprint: str,
) -> dict[str, Any]:
    artifact = _mapping(value)
    if artifact.get("schema_version") == "survey_claim_traceability_v1":
        return artifact
    return {
        "schema_version": "survey_claim_traceability_v1",
        "project_id": project_id,
        "project_context_fingerprint": fingerprint,
        "evidence_plan_schema_version": SURVEY_EVIDENCE_PLAN_SCHEMA_VERSION,
        "validation_enabled": False,
        "claims": [],
    }


def _manifest_payload(
    *,
    survey_run_id: str,
    project_id: str,
    topic: str,
    base_dir: Path,
    fingerprint: str,
    status: str,
    artifacts: Mapping[str, bytes],
    created_at: str,
    completed_at: str = "",
) -> dict[str, Any]:
    entries = {
        name: ArtifactManifestEntry(
            path=_ARTIFACT_FILENAMES[name],
            sha256=_sha256_bytes(content),
            required=name in {
                "survey_markdown",
                "survey_json",
                "project_context",
                "evidence_plan",
                "claim_traceability",
                "gap_ledger",
                "idea_handoff",
            },
        )
        for name, content in artifacts.items()
    }
    return build_manifest_payload(
        SurveyManifest(
            survey_run_id=survey_run_id,
            project_id=project_id,
            topic=topic,
            project_context_fingerprint=fingerprint,
            base_dir=str(base_dir),
            status=status,
            created_at=created_at,
            completed_at=completed_at,
            artifacts=entries,
        )
    )


def _safe_artifact_path(base_dir: Path, relative_path: Any) -> Path | None:
    raw = Path(_text(relative_path))
    if not raw or raw.is_absolute():
        return None
    candidate = (base_dir / raw).resolve()
    try:
        candidate.relative_to(base_dir)
    except ValueError:
        return None
    return candidate


def verify_survey_manifest_artifacts(
    manifest: Mapping[str, Any] | str | Path,
    *,
    base_dir: str | Path | None = None,
    require_completed: bool = True,
) -> list[str]:
    """Validate manifest contract, completion status, paths, and SHA-256 digests."""

    if isinstance(manifest, Mapping):
        payload = dict(manifest)
    else:
        path = Path(manifest)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"unable to read manifest: {exc}"]
        payload = _mapping(value)
    errors = validate_manifest_payload(payload, verify_fingerprint=True)
    status = _text(payload.get("status"))
    if require_completed and status != "completed":
        errors.append(f"manifest is not completed: {status or 'missing'}")
    root = Path(base_dir or payload.get("base_dir") or "").resolve()
    if not root.exists():
        errors.append(f"manifest base_dir does not exist: {root}")
        return errors
    for name, entry in _mapping(payload.get("artifacts")).items():
        item = _mapping(entry)
        artifact_path = _safe_artifact_path(root, item.get("path"))
        if artifact_path is None:
            errors.append(f"artifact {name!r} has an unsafe path")
            continue
        if not artifact_path.is_file():
            errors.append(f"artifact {name!r} is missing: {artifact_path.name}")
            continue
        actual = sha256_file(artifact_path)
        if actual != _text(item.get("sha256")).lower():
            errors.append(f"artifact {name!r} sha256 mismatch")
    return errors


def publish_survey_run_artifacts(
    *,
    base_dir: str | Path,
    topic: str,
    survey_run_id: str,
    final_survey: str,
    survey_payload: Mapping[str, Any],
    survey_outline: Mapping[str, Any] | None = None,
    project_context: Mapping[str, Any] | None = None,
    evidence_plan: Mapping[str, Any] | None = None,
    claim_traceability: Mapping[str, Any] | None = None,
    gap_llm_call: Any | None = None,
    gap_papers: list[Mapping[str, Any]] | None = None,
    created_at: str = "",
) -> dict[str, Any]:
    """Publish a Survey run with a manifest that cannot claim partial output is complete."""

    root = Path(base_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_id = _text(survey_run_id) or root.name
    plan = _mapping(evidence_plan)
    raw_context = _mapping(project_context)
    project_id = _project_id(raw_context, plan, run_id)
    fingerprint = _context_fingerprint(raw_context, plan)
    context_artifact = build_project_context_artifact(raw_context, project_id=project_id)
    claim_artifact = _claim_traceability_artifact(
        claim_traceability,
        project_id=project_id,
        fingerprint=fingerprint,
    )
    normalized_survey = dict(survey_payload)
    normalized_survey["topic"] = _text(normalized_survey.get("topic")) or _text(topic)
    normalized_survey["research_run_id"] = _text(normalized_survey.get("research_run_id")) or run_id
    normalized_survey.setdefault("research_context", _mapping(context_artifact.get("research_context")))
    normalized_survey.setdefault("survey_evidence_plan", plan)
    normalized_survey.setdefault("claim_traceability", claim_artifact)
    artifacts: dict[str, bytes] = {
        "survey_markdown": str(final_survey or "").encode("utf-8"),
        "survey_json": _json_bytes(normalized_survey),
        "survey_outline": _json_bytes(_mapping(survey_outline)),
        "project_context": _json_bytes(context_artifact),
    }
    complete_contract = _valid_evidence_plan(plan, fingerprint)
    if complete_contract:
        ledger = build_deterministic_gap_ledger(
            evidence_plan=plan,
            claim_traceability=claim_artifact,
            project_context=context_artifact,
            survey_json=normalized_survey,
            source_artifacts={"publication": "survey_manifest.json"},
            created_at=created_at,
        )
        gap_candidates = []
        gap_coverage = None
        if callable(gap_llm_call):
            try:
                gap_candidates = extract_gap_candidates(
                    llm_call=gap_llm_call,
                    survey_markdown=final_survey,
                    survey_json=normalized_survey,
                    deterministic_ledger=ledger,
                    profile_resolution=_mapping(ledger.get("profile_resolution")),
                    papers=gap_papers,
                    extract_paper_limitations=bool(gap_papers),
                )
                gap_coverage = build_gap_coverage_artifact(
                    gap_ledger=ledger,
                    candidates=gap_candidates,
                    evidence_plan=plan,
                    papers=gap_papers,
                    llm_call=gap_llm_call,
                )
            except Exception:
                # Survey publication must remain available from the
                # deterministic ledger when optional LLM enrichment fails.
                gap_candidates = []
                gap_coverage = None
            candidate_ledger = build_gap_candidate_ledger_payload(
                gap_candidates,
                project_id=project_id,
                survey_run_id=run_id,
                project_context_fingerprint=fingerprint,
                source_artifacts={"survey_markdown": "survey.md", "survey_json": "survey.json"},
                created_at=created_at,
            )
            artifacts.update(
                {
                    "gap_candidates": _json_bytes(candidate_ledger),
                    "gap_coverage": _json_bytes(gap_coverage),
                }
            )
        handoff = build_survey_idea_handoff_projection(
            gap_ledger=ledger,
            adjudication=gap_coverage,
            evidence_plan=plan,
            project_context=context_artifact,
            survey_json=normalized_survey,
            source_artifacts={"manifest": "survey_manifest.json"},
            created_at=created_at,
            triage_llm_call=gap_llm_call if callable(gap_llm_call) else None,
        )
        artifacts.update(
            {
                "evidence_plan": _json_bytes(plan),
                "claim_traceability": _json_bytes(claim_artifact),
                "gap_ledger": _json_bytes(ledger),
                "gap_triage": _json_bytes(_mapping(handoff.get("gap_triage"))),
                "idea_handoff": _json_bytes(handoff),
            }
        )
    now = _text(created_at) or _utc_now()
    manifest_path = root / SURVEY_MANIFEST_FILENAME
    in_progress = _manifest_payload(
        survey_run_id=run_id,
        project_id=project_id,
        topic=_text(topic) or _text(normalized_survey.get("topic")),
        base_dir=root,
        fingerprint=fingerprint,
        status="in_progress",
        artifacts=artifacts,
        created_at=now,
    )
    _atomic_write_bytes(manifest_path, _json_bytes(in_progress))
    written: dict[str, bytes] = {}
    try:
        for name, content in artifacts.items():
            _atomic_write_bytes(root / _ARTIFACT_FILENAMES[name], content)
            if sha256_file(root / _ARTIFACT_FILENAMES[name]) != _sha256_bytes(content):
                raise SurveyArtifactPublicationError(f"hash verification failed for {name}")
            written[name] = content
        completed = _manifest_payload(
            survey_run_id=run_id,
            project_id=project_id,
            topic=_text(topic) or _text(normalized_survey.get("topic")),
            base_dir=root,
            fingerprint=fingerprint,
            status="completed" if complete_contract else "partial",
            artifacts=written,
            created_at=now,
            completed_at=_utc_now() if complete_contract else "",
        )
        _atomic_write_bytes(manifest_path, _json_bytes(completed))
        errors = verify_survey_manifest_artifacts(
            completed,
            base_dir=root,
            require_completed=complete_contract,
        )
        if errors:
            raise SurveyArtifactPublicationError("published manifest verification failed: " + "; ".join(errors))
    except Exception as exc:
        failed = _manifest_payload(
            survey_run_id=run_id,
            project_id=project_id,
            topic=_text(topic) or _text(normalized_survey.get("topic")),
            base_dir=root,
            fingerprint=fingerprint,
            status="failed",
            artifacts=written,
            created_at=now,
        )
        try:
            _atomic_write_bytes(manifest_path, _json_bytes(failed))
        except Exception:
            pass
        raise SurveyArtifactPublicationError(
            f"Survey artifact publication did not complete: {type(exc).__name__}: {exc}"
        ) from exc
    return {
        "status": "completed" if complete_contract else "partial",
        "manifest_path": str(manifest_path),
        "artifacts": {name: str(root / _ARTIFACT_FILENAMES[name]) for name in written},
        "gap_ledger_path": str(root / _ARTIFACT_FILENAMES["gap_ledger"]) if "gap_ledger" in written else "",
        "gap_candidates_path": str(root / _ARTIFACT_FILENAMES["gap_candidates"]) if "gap_candidates" in written else "",
        "gap_coverage_path": str(root / _ARTIFACT_FILENAMES["gap_coverage"]) if "gap_coverage" in written else "",
        "gap_triage_path": str(root / _ARTIFACT_FILENAMES["gap_triage"]) if "gap_triage" in written else "",
        "idea_handoff_path": str(root / _ARTIFACT_FILENAMES["idea_handoff"]) if "idea_handoff" in written else "",
    }


__all__ = [
    "SURVEY_MANIFEST_FILENAME",
    "SurveyArtifactPublicationError",
    "build_project_context_artifact",
    "publish_survey_run_artifacts",
    "sha256_file",
    "verify_survey_manifest_artifacts",
]
