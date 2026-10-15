"""Persistent reservations include failed and interrupted executions."""

import time
from datetime import datetime, timezone
from pathlib import Path

from src.pipeline.computational_state import load_state, state_lock
from src.pipeline.science_run import atomic_write_json


class BudgetExhausted(RuntimeError):
    pass


class BranchBudget:
    def __init__(self, root: Path, limits: dict):
        self.root, self.limits = root, limits
        self.started = time.monotonic()
        state = load_state(root)
        self.prior_seconds = float(state.get("used_wall_seconds", 0))
        if state.get("budget_session_started_at"):
            checkpoint = datetime.fromisoformat(state["budget_session_started_at"].replace("Z", "+00:00"))
            self.prior_seconds += max(0., (datetime.now(timezone.utc) - checkpoint).total_seconds())
        from src.pipeline.computational_state import update_state
        from src.pipeline.science_run import utc_now
        update_state(root, used_wall_seconds=self.prior_seconds, budget_session_started_at=utc_now())

    def remaining(self) -> float:
        return max(0., self.limits["max_wall_seconds"] - self.prior_seconds - (time.monotonic() - self.started))

    def reserve(self) -> tuple[int, float]:
        with state_lock(self.root):
            state = load_state(self.root)
            count = int(state.get("execution_count", 0))
            remaining = self.remaining()
            if count >= self.limits["max_total_executions"] or remaining <= 0 or self.limits["max_execution_seconds"] <= 0:
                raise BudgetExhausted("execution_or_wall_budget_exhausted")
            state.update(execution_count=count + 1, used_wall_seconds=self.limits["max_wall_seconds"] - remaining)
            from src.pipeline.science_run import utc_now
            state["budget_session_started_at"] = utc_now()
            atomic_write_json(self.root / "branch_state.json", state)
            return count + 1, min(remaining, self.limits["max_execution_seconds"])

    def checkpoint(self) -> None:
        from src.pipeline.computational_state import update_state
        from src.pipeline.science_run import utc_now
        update_state(self.root, used_wall_seconds=self.limits["max_wall_seconds"] - self.remaining(),
            budget_session_started_at=utc_now())
