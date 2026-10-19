"""Shared, durable limits and local evidence for survey review."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Mapping
from pathlib import Path

import requests

from utils.api_call import DEFAULT_CHAT_MAX_OUTPUT_TOKENS


AUDIT_VERSION = "survey_claim_support_v2"
TERMINAL_STATES = {"exhausted", "needs_evidence", "permission_conflict", "no_change", "budget_exhausted"}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class ReviewStopped(RuntimeError):
    def __init__(self, reason, status="budget_exhausted"):
        super().__init__(reason)
        self.status = status


class SurveyReviewRuntime:
    def __init__(self, generator):
        self.generator = generator
        if not hasattr(generator, "survey_integrity_artifact"):
            generator.survey_integrity_artifact = {"issues": [], "claim_support": []}
        settings = generator.config.ModuleInfo.SurveyGenerator

        def limit(name, default):
            try:
                value = float(getattr(settings, name, default))
                return max(0, value) if math.isfinite(value) else default
            except (TypeError, ValueError):
                return default

        self.max_calls = int(limit("review_max_calls", 48))
        self.max_tokens = int(limit("review_max_tokens", 200000))
        self.max_seconds = limit("review_max_seconds", 600)
        self.network_attempts = min(2, max(1, int(limit("review_network_attempts", 2))))
        self.state = getattr(generator, "survey_review_state", None)
        if not isinstance(self.state, dict):
            self.state = {"schema_version": "survey_review_v1", "calls": 0, "tokens_reserved": 0,
                          "elapsed_seconds": 0, "accepted_modifications": 0, "issues": {},
                          "audit_cache": {}, "evidence": {}}
            generator.survey_review_state = self.state
        pending = self.state.pop("in_flight", None)
        if pending:
            self.state["elapsed_seconds"] += min(
                pending["timeout"], max(0, time.time() - pending["started_at"])
            )
        self.started = time.monotonic()
        self.prior_elapsed = self.state["elapsed_seconds"]
        self.stage = "review"
        self.section = 0
        self.issue_id = "-"
        self.frozen_papers = set()

    def persist(self):
        self.state["elapsed_seconds"] = self.prior_elapsed + time.monotonic() - self.started
        artifact = getattr(self.generator, "survey_integrity_artifact", None)
        if isinstance(artifact, dict):
            artifact["review_progress"] = {
                key: self.state[key] for key in (
                    "calls", "tokens_reserved", "elapsed_seconds", "accepted_modifications"
                )
            }
            artifact["review_issues"] = self.state["issues"]
        checkpoint = getattr(self.generator, "_survey_checkpoint", None)
        if checkpoint is not None:
            checkpoint.capture_generator()
            checkpoint.persist()

    def progress(self, reason):
        self.persist()
        self.generator.logger.info(
            "Survey review stage=%s section=%s issue=%s calls=%s/%s tokens_reserved=%s/%s "
            "elapsed_seconds=%.1f accepted=%s reason=%s",
            self.stage, self.section, self.issue_id[:12], self.state["calls"], self.max_calls,
            self.state["tokens_reserved"], self.max_tokens, self.state["elapsed_seconds"],
            self.state["accepted_modifications"], str(reason)[:400],
        )

    def remaining_seconds(self):
        return self.max_seconds - self.prior_elapsed - (time.monotonic() - self.started)

    def issue_key(self, text):
        return fingerprint({"text": text, "evidence": self.evidence_version(), "audit": AUDIT_VERSION})

    def evidence_version(self):
        return fingerprint({"evidence": self.state["evidence"],
                            "plan": getattr(self.generator, "survey_evidence_plan", {})})

    def terminal(self, text):
        return self.state["issues"].get(self.issue_key(text), {}).get("status") in TERMINAL_STATES

    def finish(self, texts, status, reason):
        for text in texts:
            self.state["issues"][self.issue_key(text)] = {
                "status": status, "reason": reason, "stage": self.stage,
                "section": self.section, "text": text,
            }
        self.progress(reason)

    def call(self, prompt, **kwargs):
        chat = self.generator.chat_agent
        estimator = getattr(chat, "estimate_tokens", None)
        input_tokens = (int(estimator(prompt)) if callable(estimator) else len(prompt.encode("utf-8"))) + 128
        requested_output_tokens = kwargs.get("max_output_tokens", DEFAULT_CHAT_MAX_OUTPUT_TOKENS)
        for attempt in range(self.network_attempts):
            remaining_tokens = self.max_tokens - self.state["tokens_reserved"] - input_tokens
            if self.state["calls"] >= self.max_calls:
                raise ReviewStopped("Shared review call budget exhausted.")
            if remaining_tokens <= 0 or requested_output_tokens <= 0:
                raise ReviewStopped("Shared review token budget exhausted.")
            timeout = self.remaining_seconds()
            if timeout <= 0:
                raise ReviewStopped("Shared review time budget exhausted.")
            output_tokens = min(requested_output_tokens, remaining_tokens)
            self.state["calls"] += 1
            self.state["tokens_reserved"] += input_tokens + output_tokens
            request_started = time.monotonic()
            self.state["in_flight"] = {"started_at": time.time(), "timeout": timeout}
            self.persist()
            self.progress("request_started")
            try:
                options = {**kwargs, "max_output_tokens": output_tokens, "request_timeout": timeout,
                           "strict_input_budget": True}
                method = chat.remote_chat
                undecorated = getattr(method, "__wrapped__", None)
                if undecorated is not None and hasattr(method, "retry"):
                    result = undecorated(chat, prompt, request_deadline=time.monotonic() + timeout, **options)
                else:
                    result = method(prompt, **options)
                if self.remaining_seconds() <= 0:
                    raise ReviewStopped("Shared review time budget exhausted during request.")
                if time.monotonic() - request_started > timeout:
                    raise ReviewStopped("Review request exceeded its deadline.", "exhausted")
                return result
            except requests.RequestException as exc:
                response = getattr(exc, "response", None)
                status = getattr(response, "status_code", None)
                if status is not None and status not in {408, 429} and status < 500:
                    raise ReviewStopped(str(exc), "exhausted") from exc
                if attempt + 1 >= self.network_attempts:
                    raise ReviewStopped(f"Review network attempts exhausted: {exc}", "exhausted") from exc
                self.progress("transient_network_retry")
            except ReviewStopped:
                raise
            except Exception as exc:
                raise ReviewStopped(f"Review request failed: {exc}", "exhausted") from exc
            finally:
                self.state.pop("in_flight", None)
                self.persist()


def review_runtime(generator):
    runtime = getattr(generator, "_review_runtime", None)
    if runtime is None:
        runtime = SurveyReviewRuntime(generator)
        generator._review_runtime = runtime
    return runtime


def freeze_paper_evidence(generator, paper_id):
    runtime = review_runtime(generator)
    if paper_id in runtime.frozen_papers:
        return runtime.state["evidence"][paper_id]
    analyzer = getattr(generator, "work_analyzer", None)
    collector = getattr(analyzer, "work_collector", None)
    manager = getattr(collector, "data_manager", None)
    previous = runtime.state["evidence"].get(paper_id, {})
    keynote = getattr(analyzer, "paper_keynote_cache", {}).get(hashlib.md5(paper_id.encode()).hexdigest(), {})
    confirmed = keynote.get("evidence_fragments", []) if isinstance(keynote, Mapping) else []
    fragments = [dict(item) for item in confirmed if isinstance(item, Mapping) and item.get("text")
                 and item.get("source") == "confirmed_fulltext" and item.get("source_version")]
    if not fragments:
        fragments = [dict(item) for item in previous.get("fragments", []) if item["source"] == "confirmed_fulltext"]
    cache_path = getattr(manager, "cache_path", None)
    if cache_path and re.fullmatch(r"[A-Za-z0-9_.-]+", paper_id) and paper_id not in {".", ".."}:
        path = Path(cache_path) / "parsed_papers" / paper_id / "auto" / f"{paper_id}.md"
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
                for match in re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", text):
                    fragments.append({"text": match.group().strip(), "source": "fulltext",
                                      "location": f"{path.resolve()}:{text.count(chr(10), 0, match.start()) + 1}"})
            except (OSError, UnicodeError) as exc:
                generator.logger.warning("Local review evidence unavailable paper=%s reason=%s", paper_id, exc)
    if not any(item["source"] == "fulltext" for item in fragments):
        fragments.extend(dict(item) for item in previous.get("fragments", []) if item["source"] == "fulltext")
    saved = getattr(collector, "_survey_resume_abstracts", {}).get(paper_id)
    metadata = getattr(collector, "paper_abstract_cache", {}).get(hashlib.md5(paper_id.encode()).hexdigest(), {})
    if not saved and isinstance(metadata, Mapping):
        saved = [metadata.get("title", ""), metadata.get("abstract", "")]
    if not saved or not any(saved):
        graph = getattr(collector, "reference_graph", None)
        if graph is not None and paper_id in graph:
            node = graph.nodes[paper_id]
            saved = [node.get("title", ""), node.get("abstract", "")]
    if saved and len(saved) >= 2 and saved[1]:
        fragments.append({"text": str(saved[1]), "source": "abstract", "location": "cached_abstract"})
    else:
        fragments.extend(dict(item) for item in previous.get("fragments", []) if item["source"] == "abstract")
    packet = {"paper_id": paper_id, "status": "fulltext" if any(
        item["source"] in {"fulltext", "confirmed_fulltext"} for item in fragments
    ) else "abstract_only" if fragments else "unavailable", "fragments": fragments}
    packet["version"] = fingerprint(packet)
    runtime.state["evidence"][paper_id] = packet
    runtime.frozen_papers.add(paper_id)
    runtime.persist()
    return packet


def select_evidence(packet, claim, max_characters=16000):
    words = set(re.findall(r"\w{3,}", claim.casefold()))
    ranked = sorted(enumerate(packet["fragments"]), key=lambda pair: (
        pair[1]["source"] != "confirmed_fulltext",
        -len(words & set(re.findall(r"\w{3,}", pair[1]["text"].casefold()))), pair[0]
    ))
    selected = []
    used = 0
    for _, fragment in ranked:
        if used + len(fragment["text"]) <= max_characters:
            selected.append(fragment)
            used += len(fragment["text"])
        if len(selected) >= 4:
            break
    return selected


def confirmed_packet_evidence(section_responses, packets):
    fragments = []
    for packet_index, note in section_responses.items():
        packet = packets[packet_index]
        for claim in note.get("claims", []):
            quote = claim.get("evidence", "")
            if quote and quote in packet.markdown:
                fragments.append({"text": quote, "source": "confirmed_fulltext",
                                  "location": f"packet:{packet_index};section:{claim['source_section']}",
                                  "source_version": fingerprint(packet.markdown)})
    return fragments
