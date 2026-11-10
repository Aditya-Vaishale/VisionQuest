"""
Budget: caps on steps, active time, tokens and cost for one run. It stops every loop.

Cost is counted from TOTAL output tokens: NVIDIA reports 0 thinking tokens
separately, so thinking is only visible inside the output total.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from engine.llm import UsageMeter

@dataclass(frozen=True)
class Budget:
    max_steps: int = 20                 # AI calls per run
    max_seconds: float = 600.0          # active time; waiting for the user is not counted
    max_input_tokens: int = 1_500_000
    max_output_tokens: int = 80_000     # includes thinking
    max_cost_usd: float | None = None   # only used when prices are set
    price_in_per_million: float = 0.0   # free tier: 0
    price_out_per_million: float = 0.0
    warn_at: float = 0.85               # share of any limit that triggers "wrap up now"

class BudgetTracker:
    def __init__(self, budget: Budget, meter: UsageMeter) -> None:
        self.budget = budget
        self._meter = meter
        start = meter.snapshot()
        self._in0 = int(start["input_tokens"])
        self._out0 = int(start["output_tokens"])
        self.steps = 0
        self._active = 0.0
        self._since: float | None = None

    def start(self) -> None:
        if self._since is None:
            self._since = time.perf_counter()

    def pause(self) -> None:
        if self._since is not None:
            self._active += time.perf_counter() - self._since
            self._since = None

    def used(self) -> dict[str, float | int]:
        now = self._meter.snapshot()
        running = time.perf_counter() - self._since if self._since is not None else 0.0
        tokens_in = int(now["input_tokens"]) - self._in0
        tokens_out = int(now["output_tokens"]) - self._out0
        b = self.budget
        cost = (tokens_in * b.price_in_per_million + tokens_out * b.price_out_per_million) / 1_000_000
        return {"steps": self.steps, "seconds": round(self._active + running, 1),
                "input_tokens": tokens_in, "output_tokens": tokens_out, "cost_usd": round(cost, 4)}

    def _shares(self) -> dict[str, float]:
        u, b = self.used(), self.budget
        shares = {
            "steps": u["steps"] / b.max_steps,
            "time": u["seconds"] / b.max_seconds,
            "input tokens": u["input_tokens"] / b.max_input_tokens,
            "output tokens": u["output_tokens"] / b.max_output_tokens,
        }
        if b.max_cost_usd:
            shares["cost"] = u["cost_usd"] / b.max_cost_usd
        return shares

    def exceeded(self) -> str | None:
        """Name of the first limit reached, or None."""
        return next((name for name, share in self._shares().items() if share >= 1.0), None)

    def nearly_out(self) -> bool:
        """True when the next step is the last one, or any limit is past warn_at."""
        if self.steps + 1 >= self.budget.max_steps:
            return True
        return any(share >= self.budget.warn_at for share in self._shares().values())
