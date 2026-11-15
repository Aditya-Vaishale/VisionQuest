"""
Where the time goes, so a slow run can be explained.

One line per AI call, one summary per stage and one for the whole run, written to the API terminal
and to logs/timing.log. Each analysis runs in its own thread, so totals are kept per thread.
Never logs prompts or replies; a slow SQL line shows only the first 120 characters of the query.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, fields

from engine.config import PROJECT_ROOT

SLOW_SQL_S = 1.0      # SQL slower than this gets its own line
SLOW_SLOT_S = 0.5     # rate-limit waits shorter than this are not shown per call

log = logging.getLogger("engine.timing")
_local = threading.local()
_tally_lock = threading.Lock() 
_setup_lock = threading.Lock()

@dataclass
class Tally:
    ai: float = 0.0        # waiting for the AI to reply (failed attempts included)
    slot: float = 0.0      # held back by our own requests-per-minute limit
    backoff: float = 0.0   # sleeping before a retry (429, timeout, 5xx)
    user: float = 0.0      # waiting for your answer to a question
    sql: float = 0.0       # DuckDB work
    calls: int = 0
    failed: int = 0
    queries: int = 0
    out_tokens: int = 0

    def add(self, other: Tally) -> None:
        for f in fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))

    def line(self, wall: float) -> str:
        python = max(0.0, wall - self.ai - self.slot - self.backoff - self.user - self.sql)
        return (f"{wall:7.1f}s | AI {self.ai:.1f}s ({self.calls} calls, {self.out_tokens:,} out tokens)"
                f" | limit wait {self.slot:.1f}s | retries {self.failed} (+{self.backoff:.1f}s)"
                f" | your answers {self.user:.1f}s | SQL {self.sql:.1f}s ({self.queries}) | python {python:.1f}s")

def _setup() -> None:
    with _setup_lock:
        if log.handlers:
            return
        folder = PROJECT_ROOT / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        style = logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S")
        for handler in (logging.StreamHandler(sys.stderr),
                        logging.FileHandler(folder / "timing.log", encoding="utf-8")):
            handler.setFormatter(style)
            log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False

def _where() -> str:
    return f"{getattr(_local, 'job', '-'):<8} {getattr(_local, 'stage', '-'):<9}"

def _tally() -> Tally | None:
    return getattr(_local, "tally", None)

@contextmanager
def stage(name: str, job: str = "") -> Iterator[None]:
    """Time one stage of one analysis; its summary is logged when it ends, even on an error."""
    _setup()
    if getattr(_local, "run", None) is None:
        _local.run, _local.run_started = Tally(), time.perf_counter()
    _local.job, _local.stage, _local.tally = job[:8] or "-", name, Tally()
    started = time.perf_counter()
    try:
        yield
    finally:
        tally = _local.tally
        log.info("%s %s", _where(), tally.line(time.perf_counter() - started))
        _local.run.add(tally)
        _local.stage, _local.tally = "-", None

def run_summary(status: str) -> None:
    """The whole analysis in one line. Call once, when the job ends."""
    run = getattr(_local, "run", None)
    if run is None:
        return
    wall = time.perf_counter() - _local.run_started
    log.info("%-8s %-9s %s [%s]", getattr(_local, "job", "-"), "TOTAL", run.line(wall), status)
    _local.run = None

def ai_call(slot_s: float, call_s: float, *, thinking: bool, in_tokens: int = 0, out_tokens: int = 0,
            tools: Sequence[str] = (), error: str = "", pause_s: float = 0.0) -> None:
    """One attempt to reach the AI: a reply (no error) or a failure, plus the pause before a retry."""
    t = _tally()
    number = ""
    if t is not None:
        with _tally_lock:
            t.ai += call_s
            t.slot += slot_s
            t.backoff += pause_s
            t.out_tokens += out_tokens
            if error:
                t.failed += 1
            else:
                t.calls += 1
            number = f"#{t.calls + t.failed}"
    wait = f" (limit wait {slot_s:.1f}s)" if slot_s >= SLOW_SLOT_S else ""
    if error:
        then = f"retry in {pause_s:.1f}s" if pause_s else "giving up"
        log.warning("%s AI %s FAILED %s after %.1fs%s, %s", _where(), number, error, call_s, wait, then)
    else:
        log.info("%s AI %s %.1fs%s | in %s out %s | thinking %s | -> %s", _where(), number, call_s, wait,
                 f"{in_tokens:,}", f"{out_tokens:,}", "on" if thinking else "off", ", ".join(tools) or "text")

def sql(seconds: float, text: str) -> None:
    """One DuckDB statement. Counted only inside a stage; slow ones get their own line."""
    t = _tally()
    if t is None:
        return
    with _tally_lock:
        t.sql += seconds
        t.queries += 1
    if seconds >= SLOW_SQL_S:
        log.warning("%s slow SQL %.1fs: %s", _where(), seconds, " ".join(text.split())[:120])

def waited_for_user(seconds: float, answered: bool) -> None:
    t = _tally()
    if t is not None:
        t.user += seconds
    note = "" if answered else " (no answer in time: used the first option)"
    log.info("%s waited %.0fs for your answer%s", _where(), seconds, note)

def event(text: str) -> None:
    """One short line about what happened, e.g. why a finish was refused."""
    _setup()
    log.info("%s %s", _where(), " ".join(str(text).split())[:200])

def capture() -> tuple[str, str, Tally | None]:
    """This thread's job, stage and totals, to hand to a helper thread (see attach)."""
    return getattr(_local, "job", "-"), getattr(_local, "stage", "-"), _tally()

@contextmanager
def attach(context: tuple[str, str, Tally | None]) -> Iterator[None]:
    """Count a helper thread's AI calls in the stage that started it."""
    _local.job, _local.stage, _local.tally = context
    try:
        yield
    finally:
        _local.job, _local.stage, _local.tally = "-", "-", None

class Cancelled(RuntimeError):
    """The analysis was stopped by the user; raised at its next AI call."""

_cancelled: set[str] = set()
_cancel_lock = threading.Lock()

def cancel(job: str) -> None:
    with _cancel_lock:
        _cancelled.add(job[:8])

def raise_if_cancelled() -> None:
    job = getattr(_local, "job", "-")
    with _cancel_lock:
        stopped = job in _cancelled
    if stopped:
        raise Cancelled("stopped by the user")