"""Explicit, resumable supplementary extraction from the graph's full-text queue."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout
from omegaconf import OmegaConf

from src.paper_graph.ingest import (
    ingest_paper, normalize_extraction, object_value, paper_identity, source_documents, verified_evidence,
)
from src.paper_graph.repository import PaperGraphRepository, digest
from src.paper_graph.settings import select

EXTRACTION_RECIPE = "grounded-queue-v1"


class ExtractionValidationError(ValueError):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def _source_snapshot(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Read actual files even when a queued checksum is stale, for safe resume keys."""
    candidates = list(payload.get("source_documents") or [])
    if payload.get("source_path") or payload.get("source_text"):
        candidates.append({"source_id": payload.get("source_id"), "path": payload.get("source_path"),
                           "text": payload.get("source_text")})
    docs: dict[str, dict[str, Any]] = {}
    errors = []
    for raw in candidates:
        if not isinstance(raw, Mapping):
            errors.append("invalid_source_document")
            continue
        if raw.get("reading_mode", "fulltext") != "fulltext":
            continue
        label = str(raw.get("path") or raw.get("source_id") or "inline")
        try:
            # The actual content hash participates in the checkpoint identity,
            # including when it disagrees with the original queued checksum.
            current = {k: v for k, v in raw.items() if k not in {"sha256", "source_sha256"}}
            loaded = source_documents({"source_documents": [current]})
            if not loaded:
                errors.append(f"missing_or_empty_fulltext:{label}")
                continue
            doc = loaded[0]
            expected = raw.get("sha256") or raw.get("source_sha256")
            if expected and expected != doc["sha256"]:
                errors.append(f"source_checksum_mismatch:{label}: expected {expected}, actual {doc['sha256']}")
            old = docs.get(doc["source_id"])
            if old and (old["sha256"], old["page"]) != (doc["sha256"], doc["page"]):
                errors.append(f"conflicting_source_identity:{doc['source_id']}")
            docs[doc["source_id"]] = doc
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            errors.append(f"source_read_failed:{label}: {type(exc).__name__}: {exc}")
    if not docs:
        errors.append("missing_fulltext")
    return [docs[k] for k in sorted(docs)], sorted(set(errors))


def _model_profile(config: Any) -> dict[str, Any]:
    def public(value: Any) -> Any:
        if OmegaConf.is_config(value):
            value = OmegaConf.to_container(value, resolve=True)
        if isinstance(value, Mapping):
            return {str(k): public(v) for k, v in value.items()
                    if not any(s in str(k).lower() for s in ("api_key", "password", "secret", "authorization"))
                    and str(k).lower() not in {"token", "credential", "credentials"}}
        if isinstance(value, (list, tuple)):
            return [public(v) for v in value]
        return value
    return public({"api": select(config, "survey.APIInfo", {}), "registry": select(config, "llm", {})})


def _paper_text(docs: list[dict[str, Any]]) -> str:
    if len(docs) == 1:
        return docs[0]["text"]
    # No chunk is cut off or summarized. Source labels are outside the original
    # passages and cannot pass the subsequent literal quote verification.
    return "\n\n".join(f"Source ID: {d['source_id']} (page: {d['page']})\n\n{d['text']}" for d in docs)


def _merge_output(paper_id: str, original: dict[str, Any], output: dict[str, Any],
                  docs: list[dict[str, Any]]) -> dict[str, Any]:
    if paper_identity(output) != paper_id:
        raise ExtractionValidationError([f"extracted_paper_id_mismatch:expected {paper_id}, got {paper_identity(output)}"])
    metadata = {k: v for k, v in object_value(original.get("metadata")).items() if k != "domain"}
    metadata.update(object_value(output.get("metadata")))
    merged = {**original, **output, "paper_id": paper_id, "metadata": metadata, "source_documents": docs}
    # Original bibliographic aliases must not override newly extracted metadata;
    # model-supplied file paths must never become provenance.
    for key in ("paper_title", "paper_domain", "source_id", "source_path", "source_text", "cores", "core_contributions", "components"):
        merged.pop(key, None)
    return merged


def _evidence_errors(payload: dict[str, Any], docs: list[dict[str, Any]]) -> list[str]:
    """Do not let one valid quote conceal another fabricated quote on the same entity."""
    resources = object_value(payload.get("ideation_resource")) or payload
    entities = []
    cores = resources.get("core_contributions", [])
    for i, raw in enumerate(cores if isinstance(cores, list) else []):
        core = object_value(raw)
        if not core:
            continue
        label = f"core[{i}]:{core.get('name', '')}"
        entities.append((label, core))
        components = core.get("components", [])
        for j, value in enumerate(components if isinstance(components, list) else []):
            component = object_value(value)
            if component:
                entities.append((f"{label}/component[{j}]:{component.get('name', '')}", component))
    components = resources.get("components", [])
    for i, value in enumerate(components if isinstance(components, list) else []):
        component = object_value(value)
        if component:
            entities.append((f"component[{i}]:{component.get('name', '')}", component))
    errors = []
    for label, entity in entities:
        evidence = []
        for field in ("evidence_records", "evidence"):
            entries = entity.get(field) or []
            if isinstance(entries, (str, Mapping)):
                entries = [entries]
            if not isinstance(entries, list):
                errors.append(f"invalid_evidence:{label}/{field}")
            else:
                evidence.extend(entries)
        for field in ("source_quote", "quote"):
            if entity.get(field):
                evidence.append({"quote": entity[field],
                    **{k: entity[k] for k in ("source_id", "source_section", "locator", "page") if k in entity}})
        for i, entry in enumerate(evidence):
            candidate = {"evidence_records": [entry], "source_section": entity.get("source_section"), "page": entity.get("page")}
            if not verified_evidence(candidate, docs):
                errors.append(f"unverified_evidence:{label}/evidence[{i}]: quote, source identity or locator does not match full text")
    return errors


class PaperGraphExtractionExecutor:
    def __init__(self, db_path: Path | str, *, config: Any = None,
                 chat_agent_factory: Callable[[], Any] | None = None) -> None:
        self.repository = PaperGraphRepository(db_path)
        if config is None:
            from src.config import load_config
            config = load_config()
        self.config = config
        self.chat_agent_factory = chat_agent_factory or self._make_chat_agent
        self._chat_agent = None

    def _make_chat_agent(self) -> Any:
        from src.agents.survey_agent.utils.api_call import ChatAgent
        survey = select(self.config, "survey")
        if survey is None:
            raise ValueError("paper-graph extract requires the Survey configuration (survey.APIInfo)")
        detached = OmegaConf.create(OmegaConf.to_container(survey, resolve=True) if OmegaConf.is_config(survey) else survey)
        return ChatAgent(detached, project_config=self.config)

    def run(self, *, paper_ids: list[str] | None = None, limit: int | None = None,
            retry_failed: bool = False, dry_run: bool = False, temperature: float = 0.05,
            max_retry: int = 3, max_output_tokens: int = 16000) -> dict[str, Any]:
        if limit is not None and limit < 1:
            raise ValueError("Extraction --limit must be positive")
        if max_retry < 1 or max_output_tokens < 1:
            raise ValueError("max_retry and max_output_tokens must be positive")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        options = {"temperature": temperature, "max_retry": max_retry, "max_output_tokens": max_output_tokens}
        if dry_run:
            return self._run(paper_ids, limit, retry_failed, True, options)
        # An OS file lock is released on process death. Ordinary graph ingestion
        # remains available; a compare-and-swap protects its queue updates.
        if not self.repository.db_path.is_file():
            raise FileNotFoundError(f"Paper graph database not found: {self.repository.db_path}")
        try:
            with FileLock(str(self.repository.db_path) + ".extract.lock", timeout=0):
                return self._run(paper_ids, limit, retry_failed, False, options)
        except Timeout as exc:
            raise RuntimeError("Another paper-graph extraction executor holds this queue lock") from exc

    def _run(self, paper_ids: list[str] | None, limit: int | None, retry_failed: bool,
             dry_run: bool, options: dict[str, Any]) -> dict[str, Any]:
        queued = self.repository.pending()
        requested = {paper_identity({"paper_id": p}) for p in paper_ids or []}
        selected = [q for q in queued if not requested or q["paper_id"] in requested]
        profile = _model_profile(self.config)
        papers = []
        processed = 0
        for item in selected:
            if limit is not None and processed >= limit:
                break
            paper_id, original = item["paper_id"], item["input"]
            docs, source_errors = _source_snapshot(original)
            input_hash = digest({"recipe": EXTRACTION_RECIPE, "input": original,
                                 "sources": [{k: v for k, v in d.items() if k != "text"} for d in docs],
                                 "source_errors": source_errors, "model_profile": profile, "options": options})
            previous = self.repository.latest_attempt(paper_id, input_hash)
            reusable = previous and previous["has_output"] and (
                previous["status"] in {"running", "interrupted", "succeeded"} or previous["stage"] == "ingestion")
            info = {"paper_id": paper_id, "input_hash": input_hash}
            if previous and previous["status"] == "failed" and not reusable and not retry_failed:
                papers.append({**info, "status": "skipped_failed", "attempt_id": previous["attempt_id"],
                               "stage": previous["stage"], "error": previous["error"]})
                continue
            processed += 1
            if dry_run:
                papers.append({**info, "status": "planned", "action": "resume_import" if reusable else "extract",
                               "source_count": len(docs), "fulltext_chars": sum(len(d["text"]) for d in docs),
                               "source_errors": source_errors})
                continue
            if previous and previous["status"] == "running":
                self.repository.checkpoint_attempt(previous["attempt_id"], status="interrupted", stage=previous["stage"],
                    error={"type": "Interrupted", "message": "Execution resumed by a later queue run"})
            attempt_id = self.repository.start_attempt(paper_id, input_hash)
            stage = "source_validation"
            try:
                if source_errors:
                    raise ExtractionValidationError(source_errors)
                if reusable:
                    output = previous["output"]
                    self.repository.checkpoint_attempt(attempt_id, stage="evidence_verification", output=output)
                else:
                    stage = "extraction"
                    self.repository.checkpoint_attempt(attempt_id, stage=stage)
                    if self._chat_agent is None:
                        self._chat_agent = self.chat_agent_factory()
                    from src.agents.survey_agent.utils.step2v2_extractor import extract_paper_info_batch
                    metadata = object_value(original.get("metadata"))
                    outputs = extract_paper_info_batch({paper_id: _paper_text(docs)}, self._chat_agent,
                        source_info={paper_id: {"source_venue": original.get("source_venue") or metadata.get("venue", ""),
                                                "pub_year": original.get("pub_year") or metadata.get("year", "")}},
                        include_baselines=False, preserve_components=True, strict_input_budget=True, **options)
                    if len(outputs) != 1 or not isinstance(outputs[0], dict):
                        raise ExtractionValidationError([f"expected_one_extraction:{paper_id}: got {len(outputs)}"])
                    output = outputs[0]
                    # Commit the paid model result before verification/graph writes.
                    self.repository.checkpoint_attempt(attempt_id, stage="evidence_verification", output=output)
                stage = "evidence_verification"
                payload = _merge_output(paper_id, original, output, docs)
                errors = _evidence_errors(payload, docs)
                if errors:
                    raise ExtractionValidationError(sorted(set(errors)))
                _, _, _, _, reasons = normalize_extraction(payload)
                if reasons:
                    raise ExtractionValidationError(reasons)
                stage = "ingestion"
                self.repository.checkpoint_attempt(attempt_id, stage=stage)
                result = ingest_paper(self.repository.db_path, payload, expected_queue_hash=digest(original),
                                      extraction_attempt_id=attempt_id)
                papers.append({**info, "attempt_id": attempt_id, "status": "succeeded", "result": result,
                               "reused_output": bool(reusable)})
            except Exception as exc:
                error = {"type": type(exc).__name__, "message": str(exc)}
                if isinstance(exc, ExtractionValidationError):
                    error["reasons"] = exc.reasons
                self.repository.checkpoint_attempt(attempt_id, status="failed", stage=stage, error=error)
                papers.append({**info, "attempt_id": attempt_id, "status": "failed", "stage": stage, "error": error})
        return {"ok": not any(p["status"] in {"failed", "skipped_failed"} or p.get("source_errors") for p in papers),
                "dry_run": dry_run, "selected": len(selected), "processed": processed,
                "succeeded": sum(p["status"] == "succeeded" for p in papers),
                "failed": sum(p["status"] == "failed" for p in papers),
                "skipped_failed": sum(p["status"] == "skipped_failed" for p in papers),
                "not_pending": sorted(requested - {q["paper_id"] for q in queued}),
                "remaining": len(self.repository.pending()), "papers": papers}
