"""Explicit, resumable supplementary extraction from the graph's full-text queue."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from threading import Event, Lock, RLock
import time
from typing import Any

from filelock import FileLock, Timeout
from omegaconf import OmegaConf

from src.paper_graph.ingest import (
    ingest_paper, normalize_extraction, object_value, paper_identity, source_documents,
)
from src.paper_graph.evidence_repair import (
    REPAIR_INSTRUCTIONS, EvidenceLocatorCache, apply_repair_response, evidence_issues, locator_repairs, repair_request,
)
from src.paper_graph.component_repair import (
    COMPONENT_INSTRUCTIONS, apply_component_response, component_issues, component_request,
)
from src.paper_graph.repository import PaperGraphRepository, digest
from src.paper_graph.settings import select

EXTRACTION_RECIPE = "grounded-queue-v1"


class ExtractionValidationError(ValueError):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


class ExtractionInterrupted(Exception):
    pass


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
    return [issue.message for issue in evidence_issues(payload, docs)]


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
        self._chat_agent_lock = Lock()
        self._write_lock = RLock()
        self._stop_requested = Event()

    def _make_chat_agent(self) -> Any:
        from src.agents.survey_agent.utils.api_call import ChatAgent
        survey = select(self.config, "survey")
        if survey is None:
            raise ValueError("paper-graph extract requires the Survey configuration (survey.APIInfo)")
        detached = OmegaConf.create(OmegaConf.to_container(survey, resolve=True) if OmegaConf.is_config(survey) else survey)
        return ChatAgent(detached, project_config=self.config)

    def _get_chat_agent(self) -> Any:
        with self._chat_agent_lock:
            if self._chat_agent is None:
                self._chat_agent = self.chat_agent_factory()
            return self._chat_agent

    def _write(self, operation: Callable, *args: Any, **kwargs: Any) -> Any:
        with self._write_lock:
            return operation(*args, **kwargs)

    def _log(self, event: str, paper_id: str, attempt_id: int, **fields: Any) -> None:
        record = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "event": event, "paper_id": paper_id, "attempt_id": attempt_id, **fields}
        try:
            with self._write_lock:
                sys.stderr.write(json.dumps(record, ensure_ascii=False) + "\n")
                sys.stderr.flush()
        except (OSError, ValueError):
            return

    def _check_interruption(self) -> None:
        if self._stop_requested.is_set():
            raise ExtractionInterrupted("Queue execution interrupted; saved output is available for resume")

    def run(self, *, paper_ids: list[str] | None = None, limit: int | None = None,
            retry_failed: bool = False, dry_run: bool = False, temperature: float = 0.05,
            max_retry: int = 3, max_output_tokens: int = 16000, max_evidence_repairs: int = 2,
            max_component_repairs: int = 2,
            workers: int = 10) -> dict[str, Any]:
        if limit is not None and limit < 1:
            raise ValueError("Extraction --limit must be positive")
        if max_retry < 1 or max_output_tokens < 1:
            raise ValueError("max_retry and max_output_tokens must be positive")
        if max_evidence_repairs < 0:
            raise ValueError("max_evidence_repairs must be nonnegative")
        if type(max_component_repairs) is not int or max_component_repairs < 0:
            raise ValueError("max_component_repairs must be a nonnegative integer")
        if type(workers) is not int or workers < 1:
            raise ValueError("workers must be a positive integer")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        options = {"temperature": temperature, "max_retry": max_retry, "max_output_tokens": max_output_tokens}
        # Repair policy deliberately stays outside the extraction fingerprint:
        # old paid outputs remain reusable when enabling/changing repair limits.
        if dry_run:
            return self._run(paper_ids, limit, retry_failed, True, options, max_evidence_repairs, workers, max_component_repairs)
        # An OS file lock is released on process death. Ordinary graph ingestion
        # remains available; a compare-and-swap protects its queue updates.
        if not self.repository.db_path.is_file():
            raise FileNotFoundError(f"Paper graph database not found: {self.repository.db_path}")
        try:
            with FileLock(str(self.repository.db_path) + ".extract.lock", timeout=0):
                return self._run(paper_ids, limit, retry_failed, False, options, max_evidence_repairs, workers, max_component_repairs)
        except Timeout as exc:
            raise RuntimeError("Another paper-graph extraction executor holds this queue lock") from exc

    def _run(self, paper_ids: list[str] | None, limit: int | None, retry_failed: bool,
             dry_run: bool, options: dict[str, Any], max_evidence_repairs: int, workers: int,
             max_component_repairs: int) -> dict[str, Any]:
        queued = self.repository.pending()
        requested = {paper_identity({"paper_id": p}) for p in paper_ids or []}
        selected = [q for q in queued if not requested or q["paper_id"] in requested]
        profile = _model_profile(self.config)
        papers_by_index = {}
        processed = 0
        selected_items = iter(enumerate(selected))
        self._stop_requested.clear()

        def next_work():
            nonlocal processed
            while limit is None or processed < limit:
                entry = next(selected_items, None)
                if entry is None:
                    break
                index, item = entry
                prepared = self._prepare_paper(item, profile, options, retry_failed, max_evidence_repairs, max_component_repairs)
                if prepared["plan"]["status"] == "skipped_failed":
                    papers_by_index[index] = prepared["plan"]
                    continue
                processed += 1
                return index, prepared
            return None

        if dry_run or workers == 1:
            while (work := next_work()) is not None:
                index, prepared = work
                papers_by_index[index] = prepared["plan"] if dry_run else self._process_paper(
                    prepared, options, max_evidence_repairs, max_component_repairs)
        else:
            pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="paper-graph")
            active = {}
            try:
                while True:
                    while len(active) < workers and (work := next_work()) is not None:
                        index, prepared = work
                        future = pool.submit(copy_context().run, self._process_paper, prepared, options,
                                             max_evidence_repairs, max_component_repairs)
                        active[future] = index
                    if not active:
                        break
                    completed, _ = wait(active, return_when=FIRST_COMPLETED)
                    for future in completed:
                        index = active.pop(future)
                        papers_by_index[index] = future.result()
            except BaseException:
                self._stop_requested.set()
                for future in active:
                    future.cancel()
                raise
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
        papers = [papers_by_index[index] for index in sorted(papers_by_index)]
        return {"ok": not any(p["status"] in {"partial", "failed", "skipped_failed", "interrupted"} or p.get("source_errors") for p in papers),
                "dry_run": dry_run, "workers": workers, "selected": len(selected), "processed": processed,
                "succeeded": sum(p["status"] == "succeeded" for p in papers),
                "partial": sum(p["status"] == "partial" for p in papers),
                "failed": sum(p["status"] == "failed" for p in papers),
                "interrupted": sum(p["status"] == "interrupted" for p in papers),
                "skipped_failed": sum(p["status"] == "skipped_failed" for p in papers),
                "not_pending": sorted(requested - {q["paper_id"] for q in queued}),
                "remaining": len(self.repository.pending()), "papers": papers}

    def _prepare_paper(self, item: dict[str, Any], profile: dict[str, Any], options: dict[str, Any],
                       retry_failed: bool, max_evidence_repairs: int, max_component_repairs: int) -> dict[str, Any]:
        paper_id, original = item["paper_id"], item["input"]
        docs, source_errors = _source_snapshot(original)
        input_hash = digest({"recipe": EXTRACTION_RECIPE, "input": original,
                             "sources": [{key: value for key, value in doc.items() if key != "text"} for doc in docs],
                             "source_errors": source_errors, "model_profile": profile, "options": options})
        previous = self.repository.latest_attempt(paper_id, input_hash)
        saved_issues = evidence_issues(previous["output"], docs) if (
            previous and previous["has_output"] and not source_errors) else []
        saved_components = []
        saved_ready = False
        if previous and previous["has_output"] and not source_errors:
            try:
                saved_payload = _merge_output(paper_id, original, previous["output"], docs)
                saved_components = component_issues(saved_payload, docs)
                saved_ready = not saved_issues and not normalize_extraction(saved_payload, docs)[-1]
            except (ValueError, TypeError):
                pass
        reusable = bool(previous and previous["has_output"] and (
            previous["status"] in {"running", "interrupted", "succeeded", "partial"} or previous["stage"] == "ingestion"
            or (retry_failed and previous["stage"] in {"evidence_verification", "evidence_repair", "component_repair"}
                and (saved_issues or saved_components or saved_ready))))
        main_state = self.repository.latest_main_state(previous["attempt_id"]) if (
            previous and not previous["has_output"] and not source_errors
            and (retry_failed or previous["status"] in {"running", "interrupted"})) else None
        info = {"paper_id": paper_id, "input_hash": input_hash}
        if previous and previous["status"] == "failed" and not reusable and not retry_failed:
            plan = {**info, "status": "skipped_failed", "attempt_id": previous["attempt_id"],
                    "stage": previous["stage"], "error": previous["error"]}
        else:
            action = ("repair_evidence" if saved_issues and max_evidence_repairs else
                      "repair_components" if saved_components and max_component_repairs else "resume_import") if reusable else (
                          "repair_main_json" if main_state else "extract")
            plan = {**info, "status": "planned", "action": action, "reused_output": reusable,
                    "max_evidence_repairs": max_evidence_repairs,
                    "max_component_repairs": max_component_repairs,
                    "component_issues": [issue.as_dict() for issue in saved_components],
                    "evidence_issues": [issue.as_dict() for issue in saved_issues] if reusable else [],
                    "source_count": len(docs), "fulltext_chars": sum(len(doc["text"]) for doc in docs),
                    "source_errors": source_errors}
        return {"info": info, "original": original, "docs": docs, "source_errors": source_errors,
                "previous": previous, "reusable": reusable, "main_state": main_state, "plan": plan}

    def _process_paper(self, prepared: dict[str, Any], options: dict[str, Any], max_evidence_repairs: int,
                       max_component_repairs: int) -> dict[str, Any]:
        info, original, docs = prepared["info"], prepared["original"], prepared["docs"]
        paper_id, input_hash = info["paper_id"], info["input_hash"]
        previous, reusable = prepared["previous"], prepared["reusable"]
        self._check_interruption()
        if previous and previous["status"] == "running":
            self._write(self.repository.checkpoint_attempt, previous["attempt_id"], status="interrupted", stage=previous["stage"],
                error={"type": "Interrupted", "message": "Execution resumed by a later queue run"})
        attempt_id = self._write(self.repository.start_attempt, paper_id, input_hash)
        stage = "source_validation"
        repair_errors: list[str] = []
        repair_count = 0
        component_count = 0
        component_errors: list[str] = []
        locator_stats = {"corrected": 0, "cache_hits": 0}
        output = None
        candidates = []
        self._log("paper_started", paper_id, attempt_id, reused_output=reusable)
        try:
            if prepared["source_errors"]:
                raise ExtractionValidationError(prepared["source_errors"])
            if reusable:
                output = previous["output"]
                self._write(self.repository.checkpoint_attempt, attempt_id, stage="evidence_verification", output=output)
            else:
                stage = "extraction"
                self._write(self.repository.checkpoint_attempt, attempt_id, stage=stage)
                agent = self._get_chat_agent()
                self._check_interruption()
                from src.agents.survey_agent.utils.step2v2_extractor import extract_paper_info_batch
                metadata = object_value(original.get("metadata"))
                request_ids = {}

                def observe_main(event):
                    nonlocal stage
                    identity = (event["paper_id"], event["round"])
                    if event["phase"] == "request":
                        self._check_interruption()
                        request_stage = "extraction_json_repair" if event["repair_state"] else "extraction"
                        stage = request_stage
                        request_ids[identity] = self._write(self.repository.start_extraction_request,
                            attempt_id, request_stage, event["round"], event)
                        self._log("main_request_started", paper_id, attempt_id, round=event["round"], stage=request_stage)
                    elif event["phase"] == "response":
                        self._write(self.repository.save_extraction_response, request_ids[identity], event["response"])
                    else:
                        self._write(self.repository.finish_extraction_request, request_ids[identity], attempt_id, event)
                        self._log("main_request_finished", paper_id, attempt_id, round=event["round"],
                                  status=event["status"], error=event.get("error"))

                outputs = extract_paper_info_batch({paper_id: _paper_text(docs)}, agent,
                    source_info={paper_id: {"source_venue": original.get("source_venue") or metadata.get("venue", ""),
                                            "pub_year": original.get("pub_year") or metadata.get("year", "")}},
                    include_baselines=False, preserve_components=True, strict_input_budget=True, repair_main_json=True,
                    main_request_observer=observe_main,
                    initial_main_states={paper_id: prepared["main_state"]} if prepared["main_state"] else None, **options)
                if len(outputs) != 1 or not isinstance(outputs[0], dict):
                    raise ExtractionValidationError([f"expected_one_extraction:{paper_id}: got {len(outputs)}"])
                output = outputs[0]
                self._write(self.repository.checkpoint_attempt, attempt_id, stage="evidence_verification", output=output)
            self._check_interruption()
            stage = "evidence_verification"
            payload = _merge_output(paper_id, original, output, docs)
            locator_cache = EvidenceLocatorCache(docs)
            locator_cache.seed(payload)
            output = self._correct_evidence_locators(
                paper_id, original, output, docs, attempt_id, locator_cache, locator_stats)
            payload = _merge_output(paper_id, original, output, docs)
            issues = evidence_issues(payload, docs)
            if issues and max_evidence_repairs:
                stage = "evidence_repair"
                self._write(self.repository.checkpoint_attempt, attempt_id, stage=stage, output=output)
                output, repair_errors, repair_count = self._repair_evidence(
                    paper_id, original, output, docs, attempt_id, options, max_evidence_repairs, locator_cache)
                payload = _merge_output(paper_id, original, output, docs)
            self._check_interruption()
            stage = "evidence_verification"
            if component_issues(payload, docs) and max_component_repairs:
                stage = "component_repair"
                self._write(self.repository.checkpoint_attempt, attempt_id, stage=stage, output=output)
                output, component_errors, component_count = self._repair_components(
                    paper_id, original, output, docs, attempt_id, options, max_component_repairs, locator_cache)
                payload = _merge_output(paper_id, original, output, docs)
            stage = "evidence_verification"
            _, verified_nodes, _, classified, reasons = normalize_extraction(payload)
            candidates = classified["candidate_verification"]
            if reasons and not any(node["node_type"] == "Core" for node in verified_nodes):
                raise ExtractionValidationError(reasons)
            partial_error = ({"type": "PartialExtraction", "message": "; ".join(reasons), "reasons": reasons,
                              "evidence_issues": [issue.as_dict() for issue in evidence_issues(payload, docs)],
                              "repair_errors": repair_errors, "component_repair_errors": component_errors} if reasons else None)
            self._check_interruption()
            stage = "ingestion"
            self._write(self.repository.checkpoint_attempt, attempt_id, stage=stage)
            result = self._write(ingest_paper, self.repository.db_path, payload, expected_queue_hash=digest(original),
                                 extraction_attempt_id=attempt_id, queue_input=original, extraction_error=partial_error)
            status = result["status"]
            self._log("paper_finished", paper_id, attempt_id, status=status, model_repairs=repair_count,
                      component_repairs=component_count, locator_corrections=locator_stats["corrected"],
                      locator_cache_hits=locator_stats["cache_hits"])
            return {**info, "attempt_id": attempt_id, "status": status, "result": result,
                    **({"error": partial_error} if partial_error else {}),
                    "reused_output": reusable, "evidence_repairs": repair_count,
                    "evidence_locator_corrections": locator_stats["corrected"],
                    "evidence_locator_cache_hits": locator_stats["cache_hits"], "component_repairs": component_count}
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
            if isinstance(exc, ExtractionValidationError):
                error["reasons"] = exc.reasons
            if candidates:
                error["candidates"] = candidates
            if output is not None and stage in {"evidence_verification", "evidence_repair", "component_repair"}:
                error["evidence_issues"] = [issue.as_dict() for issue in evidence_issues(output, docs)]
                error["repair_errors"] = repair_errors
                error["component_repair_errors"] = component_errors
            status = "interrupted" if isinstance(exc, ExtractionInterrupted) else "failed"
            self._write(self.repository.checkpoint_attempt, attempt_id, status=status, stage=stage, error=error)
            self._log("paper_finished", paper_id, attempt_id, status=status, stage=stage, error=error,
                      model_repairs=repair_count, locator_corrections=locator_stats["corrected"],
                      locator_cache_hits=locator_stats["cache_hits"])
            return {**info, "attempt_id": attempt_id, "status": status, "stage": stage, "error": error,
                    "reused_output": reusable, "evidence_repairs": repair_count,
                    "evidence_locator_corrections": locator_stats["corrected"],
                    "evidence_locator_cache_hits": locator_stats["cache_hits"], "component_repairs": component_count}

    def _repair_components(self, paper_id: str, original: dict[str, Any], output: dict[str, Any],
                            docs: list[dict[str, Any]], attempt_id: int, options: dict[str, Any],
                            max_rounds: int, cache: EvidenceLocatorCache) -> tuple[dict[str, Any], list[str], int]:
        from src.agents.survey_agent.utils.api_call import NonRetryableRequestError
        errors_by_target = {}
        blocked = set()
        request_count = 0
        for round_number in range(1, max_rounds + 1):
            issues = component_issues(_merge_output(paper_id, original, output, docs), docs)
            for issue in issues:
                if issue.target_id in blocked:
                    continue
                self._check_interruption()
                request = component_request(output, issue, docs, errors_by_target.get(issue.target_id, []))
                request["paper_id"] = paper_id
                request_id = self._write(self.repository.start_extraction_request,
                    attempt_id, "component_repair", round_number, request)
                request_count += 1
                self._log("component_repair_started", paper_id, attempt_id, entity=issue.name,
                          round=round_number, max_rounds=max_rounds, request_id=request_id)
                terminal_error = False
                errors = []
                try:
                    agent = self._get_chat_agent()
                    prompt = COMPONENT_INSTRUCTIONS + "\n\n" + json.dumps(request, ensure_ascii=False)
                    budget = int(agent.config.APIInfo.llm_max_context_length) - options["max_output_tokens"]
                    if budget <= 0 or agent.estimate_tokens(prompt) > budget:
                        blocked.add(issue.target_id)
                        raise ValueError(f"component_repair_input_budget_exceeded:{paper_id}")
                    responses = agent.batch_remote_chat([prompt],
                        desc=f"Component repair paper={paper_id} entity={issue.name} round={round_number}/{max_rounds}",
                        temperature=options["temperature"], strict_input_budget=True,
                        max_output_tokens=options["max_output_tokens"])
                    response = responses[0] if isinstance(responses, list) and len(responses) == 1 else None
                    self._write(self.repository.save_extraction_response, request_id, response)
                    output = apply_component_response(output, issue, response, docs, cache)
                except Exception as exc:
                    errors = [f"{type(exc).__name__}: {exc}"]
                    terminal_error = isinstance(exc, NonRetryableRequestError)
                errors_by_target[issue.target_id] = errors
                outcome = {"status": "failed" if errors else "applied", "target_id": issue.target_id,
                           "errors": errors}
                self._write(self.repository.finish_extraction_request, request_id, attempt_id, outcome, output=output)
                self._log("component_repair_finished", paper_id, attempt_id, entity=issue.name,
                          round=round_number, max_rounds=max_rounds, request_id=request_id, **outcome)
                if terminal_error:
                    return output, [error for values in errors_by_target.values() for error in values], request_count
        return output, [error for values in errors_by_target.values() for error in values], request_count

    def _correct_evidence_locators(self, paper_id: str, original: dict[str, Any], output: dict[str, Any],
                                   docs: list[dict[str, Any]], attempt_id: int, cache: EvidenceLocatorCache,
                                   stats: dict[str, int]) -> dict[str, Any]:
        issues = evidence_issues(_merge_output(paper_id, original, output, docs), docs)
        response, cache_hits = locator_repairs(output, issues, cache)
        targets = {patch["target_id"] for patch in response["repairs"]}
        if not targets:
            return output
        selected = [issue for issue in issues if issue.target_id in targets]
        request = {"task": "correct_evidence_locators", "method": "deterministic_locator", "paper_id": paper_id,
                   "failures": [issue.as_dict() for issue in selected], "cache_hits": cache_hits}
        repair_id = self._write(self.repository.start_evidence_repair, attempt_id, 0, request)
        self._write(self.repository.save_evidence_repair_response, repair_id, response)
        output, applied, errors = apply_repair_response(output, selected, response, docs)
        remaining = evidence_issues(_merge_output(paper_id, original, output, docs), docs)
        unresolved = [issue.as_dict() for issue in remaining if issue.target_id in targets]
        outcome = {"status": "partial" if applied and unresolved else "applied" if applied else "failed",
                   "method": "deterministic_locator", "applied_targets": applied, "errors": errors,
                   "remaining_issues": unresolved, "cache_hits": cache_hits}
        self._write(self.repository.finish_evidence_repair, repair_id, attempt_id, output, outcome)
        stats["corrected"] += len(applied)
        stats["cache_hits"] += cache_hits
        self._log("evidence_locator_corrected", paper_id, attempt_id, round=0, repair_id=repair_id,
                  entities=list(dict.fromkeys(issue.label for issue in selected)), corrected=len(applied),
                  cache_hits=cache_hits, errors=errors)
        return output

    def _repair_evidence(self, paper_id: str, original: dict[str, Any], output: dict[str, Any],
                         docs: list[dict[str, Any]], attempt_id: int, options: dict[str, Any],
                         max_rounds: int, locator_cache: EvidenceLocatorCache) -> tuple[dict[str, Any], list[str], int]:
        from src.agents.survey_agent.utils.api_call import NonRetryableRequestError
        errors_by_entity: dict[tuple, list[str]] = {}
        blocked_entities = set()
        repair_count = 0
        for round_number in range(1, max_rounds + 1):
            issues = evidence_issues(_merge_output(paper_id, original, output, docs), docs)
            paths = list(dict.fromkeys(i.entity_path for i in issues if i.entity_path not in blocked_entities))
            if not paths:
                break
            for path in paths:
                self._check_interruption()
                targets = [i for i in issues if i.entity_path == path]
                request = repair_request(output, targets, docs, errors_by_entity.get(path, []))
                request["paper_id"] = paper_id
                repair_id = self._write(self.repository.start_evidence_repair, attempt_id, round_number, request)
                repair_count += 1
                started = time.monotonic()
                self._log("evidence_repair_started", paper_id, attempt_id, entity=targets[0].label,
                          round=round_number, max_rounds=max_rounds, repair_id=repair_id,
                          targets=[issue.target_id for issue in targets], model_requests=repair_count,
                          location_candidates=len(request["location_candidates"]))
                applied = []
                terminal_provider_error = False
                try:
                    agent = self._get_chat_agent()
                    prompt = REPAIR_INSTRUCTIONS + "\n\n" + json.dumps(request, ensure_ascii=False)
                    context = int(agent.config.APIInfo.llm_max_context_length)
                    tokens = agent.estimate_tokens(prompt)
                    budget = context - options["max_output_tokens"]
                    if budget <= 0 or tokens > budget:
                        raise ValueError(f"repair_input_budget_exceeded:{paper_id}: {tokens} > {budget} tokens")
                    responses = agent.batch_remote_chat(
                        [prompt], desc=f"Evidence repair paper={paper_id} entity={targets[0].label} round={round_number}/{max_rounds}",
                        temperature=options["temperature"], strict_input_budget=True,
                        max_output_tokens=options["max_output_tokens"])
                    response = responses[0] if isinstance(responses, list) and len(responses) == 1 else None
                    # Save even malformed responses, before parsing or applying.
                    self._write(self.repository.save_evidence_repair_response, repair_id, response)
                    output, applied, errors = apply_repair_response(
                        output, targets, response, docs, locator_cache=locator_cache,
                        candidates=request["location_candidates"])
                except Exception as exc:
                    errors = [f"{type(exc).__name__}: {exc}"]
                    terminal_provider_error = isinstance(exc, NonRetryableRequestError)
                    if str(exc).startswith("repair_input_budget_exceeded:"):
                        blocked_entities.add(path)
                remaining = evidence_issues(_merge_output(paper_id, original, output, docs), docs)
                errors_by_entity[path] = errors
                unresolved = [i.as_dict() for i in remaining if i.entity_path == path]
                outcome = {"status": "partial" if applied and unresolved else "applied" if applied else "failed",
                           "applied_targets": applied, "errors": errors, "remaining_issues": unresolved}
                self._write(self.repository.finish_evidence_repair, repair_id, attempt_id, output, outcome)
                self._log("evidence_repair_finished", paper_id, attempt_id, entity=targets[0].label,
                          round=round_number, max_rounds=max_rounds, repair_id=repair_id, status=outcome["status"],
                          applied=len(applied), remaining=len(unresolved), errors=errors,
                          model_requests=repair_count, elapsed_seconds=round(time.monotonic() - started, 2))
                if terminal_provider_error:
                    return output, [error for values in errors_by_entity.values() for error in values], repair_count
                # Re-scan after patches that expand a list, so target indices in
                # the following round address the new, checkpointed output.
                issues = remaining
        return output, [error for values in errors_by_entity.values() for error in values], repair_count
