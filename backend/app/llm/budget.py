"""One execution budget spanning provider attempts, streams, tools and JSON repair."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import monotonic
from threading import Lock


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class ExecutionBudget:
    max_calls: int
    duration: float
    started: float = field(default_factory=monotonic)
    calls: int = 0
    provider_ms: int = 0
    reported_tokens: int | None = None
    lock: Lock = field(default_factory=Lock, repr=False)

    def remaining(self) -> float:
        remaining = self.duration - (monotonic() - self.started)
        if remaining <= 0:
            raise BudgetExceeded("本次执行已达到时间预算，请缩小问题范围后重试")
        return remaining

    def claim_call(self) -> float:
        with self.lock:
            remaining = self.remaining()
            if self.calls >= self.max_calls:
                raise BudgetExceeded("本次执行已达到模型调用预算，请缩小问题范围后重试")
            self.calls += 1
            return remaining

    def record_tokens(self, response):
        tokens = getattr(getattr(response, "usage", None), "total_tokens", None)
        if isinstance(tokens, int):
            with self.lock:
                self.reported_tokens = (self.reported_tokens or 0) + tokens

    def snapshot(self):
        with self.lock:
            return {
                "model_call_limit": self.max_calls,
                "duration_limit_ms": int(self.duration * 1000),
                "model_calls": self.calls,
                "provider_ms": self.provider_ms,
                "reported_tokens": self.reported_tokens,
                "elapsed_ms": int((monotonic() - self.started) * 1000),
            }


current_budget = ContextVar("llm_execution_budget", default=None)


@contextmanager
def execution_budget(max_calls: int = 6, duration: float = 90):
    existing = current_budget.get()
    if existing is not None:
        yield existing
        return
    budget = ExecutionBudget(max_calls=max_calls, duration=duration)
    token = current_budget.set(budget)
    try:
        yield budget
    finally:
        current_budget.reset(token)


def remaining_timeout(default: float) -> float:
    budget = current_budget.get()
    return min(default, budget.remaining()) if budget else default
