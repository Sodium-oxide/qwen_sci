"""Shared resumable search/reading loop for Survey and Idea."""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import time
import threading

from .anysearch import identity_keys, merge_papers, text, write_json_atomic
from .search_planner import ScientificSearchPlanner, request_key, scientific_input
from .source_retry import source_retry_allowed, source_route_fingerprint


_active_acquisition = ContextVar("adaptive_source_acquisition", default=None)


class SearchBudgetExceeded(RuntimeError):
    pass


def charge_acquisition_http():
    scope = _active_acquisition.get()
    if scope is not None and not scope("http"):
        raise SearchBudgetExceeded("Shared search HTTP/time budget exhausted")


def acquisition_scope_active():
    return _active_acquisition.get() is not None


@contextmanager
def acquisition_scope(reserve):
    token = _active_acquisition.set(reserve)
    try:
        yield
    finally:
        _active_acquisition.reset(token)


def load_history(path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def history_states(history):
    if not isinstance(history, Mapping):
        return []
    if "queries" in history or "reads" in history:
        return [history]
    return [s for s in history.get("sessions", []) if isinstance(s, Mapping)]


def history_projection(histories) -> dict:
    sessions = []
    for history in histories:
        for state in history_states(history):
            sessions.append({key: state[key] for key in ("schema_version", "phase", "plan", "queries", "reads", "budget", "adjustments", "issues", "status", "summary") if key in state})
    return {"schema_version": 2, "sessions": sessions}


class AdaptiveSearch:
    def __init__(self, *, path, client, reader, llm=None, openalex_search=None,
                 settings=None, inherited=(), logger=None):
        self.path, self.client, self.reader = Path(path), client, reader
        self.llm, self.openalex_search, self.logger = llm, openalex_search, logger
        self.settings = dict(settings or {})
        self.inherited = [state for history in inherited for state in history_states(history)]
        self.state = load_history(self.path)
        self.started = time.monotonic()
        self.lock = threading.RLock()
        self.limits = {"queries": self.setting("max_requests", 12, 0, 100),
                       "http": self.setting("max_http_requests", 80, 0, 500),
                       "model": self.setting("max_model_calls", 12, 0, 40),
                       "acquisitions": self.setting("max_acquisition_attempts", 20, 0, 100),
                       "successful_reads": self.setting("read_limit", 8, 0, 40),
                       "seconds": self.setting("max_seconds", 900, 1, 7200)}

    def setting(self, key, default, low, high):
        try:
            return min(high, max(low, int(self.settings.get(key, default))))
        except (ValueError, TypeError):
            return default

    def save(self):
        with self.lock:
            elapsed = time.monotonic() - self.started
            self.state.setdefault("budget", {})["elapsed_seconds"] = self._prior_elapsed + elapsed
            self.state["budget"]["limits"] = self.limits
            write_json_atomic(self.path, self.state)

    def reserve(self, kind):
        with self.lock:
            budget = self.state.setdefault("budget", {})
            if self._prior_elapsed + time.monotonic() - self.started >= self.limits["seconds"]:
                return False
            if budget.get(kind, 0) >= self.limits[kind]:
                return False
            budget[kind] = budget.get(kind, 0) + 1
            self.save()
            return True

    def _raw(self, label, raw):
        directory = self.path.parent / (self.path.stem + "_model")
        directory.mkdir(parents=True, exist_ok=True)
        index = self.state.get("budget", {}).get("model", 0)
        (directory / f"{index:03d}-{label}.txt").write_text(str(raw), encoding="utf-8")

    def _catalog(self):
        try:
            # Capability loading is bounded independently and cached across
            # stages. A simple provider double need not implement discovery.
            method = getattr(self.client, "capabilities", None)
            if callable(method):
                catalog = method()
                if isinstance(catalog, Mapping) and isinstance(catalog.get("channels"), Mapping):
                    return dict(catalog)
        except Exception as exc:
            self.state.setdefault("issues", []).append({"step": "capabilities", "error_type": type(exc).__name__})
        from .search_capabilities import _fallback
        return _fallback()

    def run(self, *, phase, task, topic="", project_context=None, candidates=(), known_references=()):
        self._prior_elapsed = float(self.state.get("budget", {}).get("elapsed_seconds", 0))
        self.state.setdefault("schema_version", 2)
        self.state.setdefault("phase", phase)
        for key, default in (("queries", []), ("reads", {}), ("papers", {}), ("issues", []), ("adjustments", []), ("budget", {})):
            self.state.setdefault(key, default)
        self.save()
        catalog = self.state.get("capabilities") or self._catalog()
        self.state["capabilities"] = catalog
        planner = ScientificSearchPlanner(catalog, llm=self.llm,
                    max_needs=self.setting("max_needs", 5, 1, 8), repair_attempts=self.setting("plan_repair_attempts", 1, 0, 2),
                    budget=self.reserve, save_raw=self._raw)
        if not self.state.get("plan"):
            inputs = scientific_input(task, topic=topic, project_context=project_context,
                                      candidates=candidates, known_references=known_references)
            # Search history is observations, never evaluator instructions.
            inputs["previous_searches"] = [
                {"purpose": q.get("purpose"), "query": q.get("query"), "tag": q.get("tag"),
                 "status": q.get("status"), "metrics": q.get("metrics", {})}
                for state in self.inherited for q in state.get("queries", [])][-40:]
            self.state["plan"] = planner.plan(inputs, phase=phase)
            if self.state["queries"]:
                # Migrate completed pre-planner checkpoints without repeating
                # requests or discarding their source-reading records.
                need_id = self.state["plan"]["needs"][0]["id"] if self.state["plan"]["needs"] else "N1"
                for q in self.state["queries"]:
                    q.setdefault("need_id", need_id)
                    q.setdefault("provider", "anysearch")
                    q.setdefault("tag", getattr(self.client, "tag", "academic.search"))
                    q.setdefault("params", {})
                    q.setdefault("round", 0)
            self.save()
        needs = self.state["plan"]["needs"]
        known = set().union(*(identity_keys(ref) for ref in known_references if isinstance(ref, Mapping))) if known_references else set()
        self.known = known
        for inherited in self.inherited:
            for pid, read in inherited.get("reads", {}).items():
                if read.get("status") != "completed" or not isinstance(read.get("reference"), Mapping):
                    continue
                ref = read["reference"]
                if identity_keys(ref) & known:
                    continue
                # Preserve source provenance. Already-read scientific sources
                # are made available to this phase without spending a new slot.
                self.state["reads"].setdefault(pid, {**read, "reused": True})
        max_rounds = self.setting("max_rounds", 3, 1, 6)
        for need in needs:
            if any(q.get("need_id") == need["id"] for q in self.state["queries"]):
                continue
            for route in need["routes"][:2]:
                self._append_query(need, route, 0)
        self.save()
        # One probe for each need before expanding higher-yield needs. All
        # reservations are durable before work starts, including interrupted IO.
        if self._success_count() < self.limits["successful_reads"]:
            for query in self.state["queries"]:
                if (query.get("round", 0) == 0 and query.get("status") not in {"success", "valid_empty", "reused"}
                        and query.get("attempts", 0) < self.setting("checkpoint_attempts", 2, 1, 3)):
                    self._execute(query)
        for round_index in range(max_rounds):
            ordered = sorted(needs, key=lambda n: (-self._priority(n), n["id"])) if round_index else needs
            for need in ordered:
                if self._success_count() >= self.limits["successful_reads"]:
                    break
                queries = [q for q in self.state["queries"] if q.get("need_id") == need["id"]]
                for query in queries:
                    if round_index == 0 and query.get("round", 0) == 0:
                        continue  # Already probed above; retries wait for another round/resume.
                    if query.get("round", 0) > round_index or query.get("status") in {"success", "valid_empty", "reused"}:
                        continue
                    if query.get("attempts", 0) >= self.setting("checkpoint_attempts", 2, 1, 3):
                        continue
                    self._execute(query)
                self._read_candidates(need, planner,
                    probe_limit=1 if round_index == 0 and max_rounds > 1 and len(needs) > 1 else None)
                metrics = self._metrics(need)
                self.state.setdefault("summary", {})[need["id"]] = metrics
                for q in queries:
                    q["metrics"] = metrics
                self.save()
                need_queries = [q for q in self.state["queries"] if q.get("need_id") == need["id"]]
                if (round_index + 1 >= max_rounds or metrics["read_successes"] >= need["budget"]["successful_reads"]
                        and not metrics["uncovered_terms"] or self._success_count() >= self.limits["successful_reads"]
                        or len(need_queries) >= need["budget"]["requests"]):
                    continue
                if any(q.get("round", 0) > round_index for q in need_queries):
                    continue
                if any(a.get("need_id") == need["id"] and a.get("round") == round_index + 1 for a in self.state["adjustments"]):
                    continue
                # Do not spend model calls on adjustments after request budget
                # is exhausted, or after a permanent unavailable provider.
                if self.state["budget"].get("queries", 0) >= self.limits["queries"]:
                    continue
                route, reason = planner.adjust(need, metrics, need_queries, round_index=round_index + 1)
                adjustment = {"need_id": need["id"], "round": round_index + 1, "reason": reason,
                              "metrics": metrics, "route": route}
                self.state["adjustments"].append(adjustment)
                if route:
                    self._append_query(need, route, round_index + 1)
                self.save()
        self.state["issues"] = [*self.state["issues"], *planner.issues]
        exhausted = [key for key in ("queries", "http", "model", "acquisitions") if self.state["budget"].get(key, 0) >= self.limits[key]]
        if self._prior_elapsed + time.monotonic() - self.started >= self.limits["seconds"]:
            exhausted.append("seconds")
        self.state["status"] = "budget_exhausted" if exhausted else "completed" if self._success_count() >= self.limits["successful_reads"] else "partial"
        self.state["budget"]["exhausted"] = exhausted
        self.save()
        refs = [read["reference"] for read in self.state["reads"].values() if read.get("status") == "completed"
                and not identity_keys(read.get("reference", {})) & known]
        searches = [{key: q.get(key) for key in ("provider", "tag", "params", "phase", "need_id", "purpose", "target_subproblem", "query", "status", "attempts", "metrics")}
                    | {"paper_count": len(q.get("papers", [])), "checkpoint": str(self.path)} for q in self.state["queries"]]
        if self.logger:
            self.logger.info("Adaptive search phase=%s needs=%s queries=%s readable=%s acquisition_attempts=%s status=%s", phase, len(needs), len(searches), len(refs), self.state["budget"].get("acquisitions", 0), self.state["status"])
        return {"references": refs, "papers": list(self.state["papers"].values()), "searches": searches,
                "history": history_projection([self.state]), "checkpoint": str(self.path)}

    def _append_query(self, need, route, round_index):
        if sum(q.get("need_id") == need["id"] for q in self.state["queries"]) >= need["budget"]["requests"]:
            return
        route = {**route, "result_limit": self.setting("result_limit", 5, 1, 10)}
        key = request_key(route)
        if any(q.get("key") == key and q.get("need_id") == need["id"] for q in self.state["queries"]):
            return
        self.state["queries"].append({**route, "key": key, "phase": self.state["phase"], "need_id": need["id"],
                    "purpose": need["purpose"], "expected_source_types": need["expected_source_types"],
                    "target_subproblem": need["target_subproblem"], "round": round_index, "attempts": 0, "status": "pending"})

    def _execute(self, query):
        key = query.get("key") or request_key(query)
        previous = next((q for s in [*self.inherited, self.state] for q in s.get("queries", [])
                         if q is not query and (q.get("key") or request_key(q)) == key and q.get("status") in {"success", "valid_empty", "reused"}), None)
        if previous:
            query.update(status="reused", papers=previous.get("papers", []), reused_from=previous.get("phase"))
            self.save()
            return
        if not self.reserve("queries"):
            query["deferred_reason"] = "request_or_time_budget"
            return
        query.update(attempts=query.get("attempts", 0) + 1, status="in_progress")
        self.save()
        try:
            if query.get("provider") == "openalex":
                if not callable(self.openalex_search):
                    query.update(status="unavailable", papers=[])
                else:
                    with acquisition_scope(self.reserve):
                        papers = self.openalex_search(query["query"], query.get("result_limit", 5))
                    query.update(papers=papers, status="success" if papers else "valid_empty")
            else:
                # Every client retry is charged at the actual transport
                # boundary. Cache hits consume no HTTP budget.
                with acquisition_scope(self.reserve):
                    kwargs = {"limit": query.get("result_limit", 5)}
                    if query.get("tag") or query.get("params"):
                        kwargs.update(tag=query.get("tag", "academic.search"), params=query.get("params", {}))
                    result = self.client.search(query["query"], **kwargs)
                query.update(status=result.status, papers=result.papers, cached=result.cached, request_attempts=result.attempts)
        except Exception as exc:
            query.update(status="provider_failure", error_type=type(exc).__name__)
        self.save()

    def _success_count(self):
        return sum(r.get("status") == "completed" and not r.get("reused") for r in self.state["reads"].values())

    def _read_candidates(self, need, planner, *, probe_limit=None):
        papers = merge_papers([p for q in self.state["queries"] if q.get("need_id") == need["id"] and q.get("status") in {"success", "reused"}
                               for p in q.get("papers", []) if isinstance(p, dict) and p.get("paperId")])
        assessments = self.state.setdefault("assessments", {}).setdefault(need["id"], {})
        unassessed = [p for p in papers if p["paperId"] not in assessments and not identity_keys(p) & self.known]
        if unassessed:
            assessments.update(planner.assess(need, unassessed))
            self.save()
        seen = set(self.known)
        for read in self.state["reads"].values():
            if read.get("status") == "completed":
                seen.update(identity_keys(read.get("reference", {})))
        for paper in papers:
            pid = paper["paperId"]
            assessment = assessments.get(pid, {})
            if identity_keys(paper) & seen or not assessment.get("relevant"):
                continue
            if assessment.get("source_type") not in need["expected_source_types"]:
                continue
            paper["source_type"] = assessment["source_type"]
            existing = self.state["reads"].get(pid)
            if existing is None:
                existing = next((read for history in [self.state, *self.inherited] for read in history.get("reads", {}).values()
                                 if read.get("status") != "completed" and identity_keys(paper) &
                                 (identity_keys(read.get("paper", {})) | identity_keys(read.get("reference", {})))), None)
            if existing and existing.get("status") == "completed":
                continue
            fingerprint = source_route_fingerprint(paper)
            access_context = str(self.settings.get("access_context_generation", "anonymous-v1"))
            if existing and not source_retry_allowed(paper, existing.get("reference", {}), access_context):
                self.state["reads"][pid] = {**existing, "paper": paper, "deferred_reason": "unchanged_source_routes"}
                if self.logger:
                    self.logger.info("Source acquisition deferred paper=%s reason=unchanged_source_routes", pid)
                self.save()
                continue
            old_fingerprint = (existing or {}).get("attempt_fingerprint")
            if existing and not old_fingerprint:
                old_fingerprint = source_route_fingerprint(existing.get("paper", {}))
            previous_retry = (existing or {}).get("reference", {}).get("retry", {})
            old_context = (existing or {}).get("access_context_generation", previous_retry.get("access_context_generation", access_context))
            changed = bool(old_fingerprint and old_fingerprint != fingerprint or old_context != access_context)
            route_attempts = 0 if changed else (existing or {}).get("route_attempts", (existing or {}).get("attempts", 0))
            if route_attempts >= self.setting("checkpoint_attempts", 2, 1, 3):
                continue
            target = min(need["budget"]["successful_reads"], probe_limit) if probe_limit is not None else need["budget"]["successful_reads"]
            if self._success_count() >= self.limits["successful_reads"] or self._metrics(need)["read_successes"] >= target:
                break
            if not self.reserve("acquisitions"):
                break
            read = dict(existing or {"attempts": 0})
            read.pop("deferred_reason", None)
            read.update(paper=paper, need_id=need["id"], attempts=read["attempts"] + 1, status="in_progress",
                        route_attempts=route_attempts + 1, attempt_fingerprint=fingerprint, access_context_generation=access_context)
            self.state["reads"][pid] = read
            self.state["papers"][pid] = paper
            self.save()
            try:
                with acquisition_scope(self.reserve):
                    reference = self.reader(paper)
                reference = {**reference, "retrieval_provenance": [*paper.get("retrieval_provenance", []),
                    *[{"provider": q["provider"], "query": q["query"], "tag": q.get("tag", ""), "params": q.get("params", {}),
                       "phase": self.state["phase"], "need_id": need["id"]} for q in self.state["queries"] if q.get("need_id") == need["id"] and any(identity_keys(p) & identity_keys(paper) for p in q.get("papers", []))]],
                    "search_checkpoint": str(self.path), "reading_checkpoint": str(self.path)}
                if reference.get("reading_status") == "completed" and text(reference.get("keynote")):
                    read.update(status="completed", reference=reference)
                    seen.update(identity_keys(reference))
                else:
                    read.update(status="unavailable", reference=reference)
            except Exception as exc:
                read.update(status="failed", error_type=type(exc).__name__)
            self.save()

    def _metrics(self, need):
        queries = [q for q in self.state["queries"] if q.get("need_id") == need["id"]]
        raw = [p for q in queries for p in q.get("papers", [])]
        unique = merge_papers(raw)
        known_duplicates = sum(bool(identity_keys(p) & self.known) for p in unique)
        assessments = self.state.get("assessments", {}).get(need["id"], {})
        relevant = [p for p in unique if assessments.get(p.get("paperId"), {}).get("relevant") and assessments.get(p.get("paperId"), {}).get("source_type") in need["expected_source_types"] and not identity_keys(p) & self.known]
        reads = [r for r in self.state["reads"].values() if r.get("need_id") == need["id"] and not r.get("reused")]
        successes = [r for r in reads if r.get("status") == "completed"]
        attempts = sum(r.get("attempts", 0) for r in reads)
        actual_content = " ".join(text(r.get("reference", {}).get("keynote")) for r in successes).casefold()
        terms = need.get("coverage_terms", [])
        covered = [t for t in terms if t.casefold() in actual_content]
        return {"returned": len(raw), "unique": len(unique), "duplicates": len(raw) - len(unique) + known_duplicates,
                "new_relevant": len(relevant), "read_attempts": attempts,
                "read_successes": len(successes), "reading_success_rate": len(successes) / attempts if attempts else 0,
                "covered_terms": covered, "uncovered_terms": [t for t in terms if t not in covered],
                "coverage_basis": "actual_read_content", "themes": [p.get("title", "") for p in relevant[:5]]}

    def _priority(self, need):
        m = self._metrics(need)
        return (m["new_relevant"] + 2 * m["read_successes"]) * (1 + m["reading_success_rate"]) / (1 + m["read_attempts"]) + bool(m["uncovered_terms"])
