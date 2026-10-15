"""Run-local limits charged only at OpenAlex query-search HTTP boundaries."""

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
import threading
import weakref


class RetrievalBudgetExceeded(RuntimeError):
    pass


_active_request = ContextVar("scientific_retrieval_request", default=None)
_active_model_request = ContextVar("survey_model_request", default=None)
_run_budgets = {}
_run_budget_lock = threading.Lock()


def bind_retrieval_budget(config, budget):
    def release(reference):
        with _run_budget_lock:
            record = _run_budgets.get(id(config))
            if record is not None and record[1] is reference:
                _run_budgets.pop(id(config), None)
    with _run_budget_lock:
        _run_budgets[id(config)] = (config, weakref.ref(budget, release))


def provider_retrieval_budget(provider):
    with _run_budget_lock:
        record = _run_budgets.get(id(provider.config))
        if record is not None and record[0] is provider.config:
            budget = record[1]()
            if budget is not None:
                return budget
    return getattr(provider, "retrieval_budget", None)


class RetrievalBudget:
    def __init__(self, total=120, stages=None, assessment_limit=160, assessment_stages=None):
        self.total = max(0, int(total))
        self.stages = dict(stages or {"discovery": 20, "screening": 30, "comparison": 50, "supplement": 20})
        self.assessment_limit = max(0, int(assessment_limit))
        self.assessment_stages = dict(assessment_stages or {"discovery": 60, "relevance": 20, "screening": 40, "comparison": 60, "supplement": 20})
        self.lock = threading.Lock()
        self.attempts = Counter()
        self.request_keys = set()
        self.counters = Counter()
        self.model_reserved = 0

    def model_remaining(self):
        with self.lock:
            return max(0, self.assessment_limit - self.counters["model_assessment_requests"] - self.model_reserved)

    def reserve_model_capacity(self, count):
        with self.lock:
            if count > self.assessment_limit - self.counters["model_assessment_requests"] - self.model_reserved:
                raise RetrievalBudgetExceeded("model_budget_exhausted")
            self.model_reserved += count
            return {"remaining": count, "closed": False}

    def charge_model_attempt(self, lease):
        with self.lock:
            if lease["closed"]:
                raise RetrievalBudgetExceeded("model_scope_closed")
            if lease["remaining"]:
                lease["remaining"] -= 1
                self.model_reserved -= 1
            elif self.counters["model_assessment_requests"] + self.model_reserved >= self.assessment_limit:
                raise RetrievalBudgetExceeded("model_budget_exhausted")
            self.counters["model_assessment_requests"] += 1

    def release_model_capacity(self, lease):
        with self.lock:
            if not lease["closed"]:
                self.model_reserved -= lease["remaining"]
                lease.update(remaining=0, closed=True)

    def remaining(self, stage):
        with self.lock:
            return max(0, min(self.total - sum(self.attempts.values()), self.stages.get(stage, 0) - self.attempts[stage]))

    def reserve_http(self, stage, request_key):
        with self.lock:
            if sum(self.attempts.values()) >= self.total or self.attempts[stage] >= self.stages.get(stage, 0):
                raise RetrievalBudgetExceeded("global_budget_exhausted" if sum(self.attempts.values()) >= self.total else "stage_budget_exhausted")
            self.attempts[stage] += 1
            self.request_keys.add(request_key)

    def reserve_assessment(self, stage="comparison"):
        with self.lock:
            if self.counters["model_assessment_requests"] >= self.assessment_limit or self.counters["assessment_" + stage] >= self.assessment_stages.get(stage, 0):
                return False
            self.counters["model_assessment_requests"] += 1
            self.counters["assessment_" + stage] += 1
            return True

    def note(self, key, count=1):
        with self.lock:
            self.counters[key] += count

    def snapshot(self):
        with self.lock:
            return {"http_attempts": sum(self.attempts.values()), "http_limit": self.total,
                    "http_budget_scope": "openalex_query_search_only",
                    "http_attempts_by_stage": dict(self.attempts), "stage_limits": dict(self.stages),
                    "distinct_external_requests": len(self.request_keys), "assessment_limit": self.assessment_limit,
                    "model_reserved": self.model_reserved,
                    **dict(self.counters)}


@contextmanager
def retrieval_request_scope(budget, stage, request_key):
    token = _active_request.set({"budget": budget, "stage": stage, "key": request_key, "attempt": 0})
    try:
        yield
    finally:
        _active_request.reset(token)


def reserve_retrieval_http_attempt(default_budget=None, request_key="query_search"):
    """Charge an OpenAlex query-search transport attempt, never metadata."""
    request = _active_request.get()
    if request is not None and request["budget"] is not None:
        stage = request["stage"] if request["attempt"] == 0 else ("retry_fallback" if "retry_fallback" in request["budget"].stages else "supplement")
        request["budget"].reserve_http(stage, request["key"])
        request["attempt"] += 1
    elif default_budget is not None:
        default_budget.reserve_http("primary" if "primary" in default_budget.stages else "supplement", request_key)


def has_retrieval_request_scope():
    return _active_request.get() is not None


@contextmanager
def model_request_scope(budget, lease):
    token = _active_model_request.set((budget, lease))
    try:
        yield
    finally:
        _active_model_request.reset(token)


def reserve_model_http_attempt():
    request = _active_model_request.get()
    if request is not None:
        request[0].charge_model_attempt(request[1])
