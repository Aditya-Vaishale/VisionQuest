"""
Background jobs for the API: one analysis per upload, run through the Pipeline in its own thread.

When the AI asks a question the job pauses (status needs_answer) until the user answers through the
API. When the dashboard is ready the job keeps its locked SQL room, so filters can rerun the approved
recipes on a narrowed base table. No AI is involved in filtering.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from engine.agent import Question
from engine import timing
from engine.discover import load_csv_bytes, profile_table
from engine.llm import LLMClient, get_llm
from engine.pipeline import Pipeline, StageCache
from engine.sql import quote_ident
from engine.stages import build_dashboard
from engine.stages.calculate import BASE
from engine.stages.clean import CLEAN

STAGE_NAMES = ("discover", "clean", "reason", "calculate", "validate", "visualize", "dashboard")
ANSWER_TIMEOUT_S = 30 * 60      # an unanswered question falls back to its first option after this
MAX_RUNNING = 2                 # analyses at the same time (they share the AI rate limit)
MAX_FILTER_VALUES = 50
REUSED = "reused saved output"

class Busy(RuntimeError):
    """Too many analyses are running, or this one cannot be removed yet."""

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

@dataclass
class Job:
    id: str
    file_name: str
    data: bytes = field(repr=False)
    status: str = "queued"                                 # queued | running | needs_answer | done | failed
    stage: str = ""
    stages: dict[str, str] = field(default_factory=dict)   # stage -> running | done | reused | failed
    question: Question | None = None
    error: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    dashboard: dict[str, Any] | None = None
    pipe: Pipeline | None = None
    card: Any = None
    val: Any = None
    vis: Any = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _reply: str = ""
    _answered: threading.Event = field(default_factory=threading.Event, repr=False)

    def view(self) -> dict[str, Any]:
        return {"id": self.id, "file": self.file_name, "status": self.status, "stage": self.stage,
                "stages": [{"name": s, "state": self.stages.get(s, "waiting")} for s in STAGE_NAMES],
                "question": self.question.model_dump() if self.question else None,
                "error": self.error or None, "created_at": self.created_at, "updated_at": self.updated_at}

    def touch(self, **changes: Any) -> None:
        for name, value in changes.items():
            setattr(self, name, value)
        self.updated_at = _now()

    def mark(self, stage: str, state: str) -> None:
        self.stages[stage] = state
        self.touch(stage=stage if state == "running" else self.stage)

    def ask(self, q: Question) -> str:
        """Called in the job thread when the AI asks: wait for the user's answer (or time out)."""
        self._answered.clear()
        self.touch(status="needs_answer", question=q, _reply="")
        asked = time.perf_counter()
        answered = self._answered.wait(ANSWER_TIMEOUT_S)
        timing.waited_for_user(time.perf_counter() - asked, answered)
        reply = self._reply if answered and self._reply else (q.options[0] if q.options else "no preference")
        if self.status == "needs_answer":            # not if the analysis was stopped meanwhile
            self.touch(status="running", question=None)
        return reply

    def answer(self, text: str) -> None:
        if self.status != "needs_answer":
            raise ValueError("This analysis is not waiting for an answer.")
        self._reply = text.strip()
        self._answered.set()

    def cancel(self, reason: str) -> None:
        """Stop this analysis at its next AI call; a waiting question is released at once."""
        if self.status not in ("queued", "running", "needs_answer"):
            return
        timing.cancel(self.id)
        self.touch(status="failed", error=f"Stopped: {reason}", question=None)
        self._answered.set()

def _reused(outcome: Any) -> bool:
    run = getattr(outcome, "run", None) or (outcome.runs[0] if getattr(outcome, "runs", None) else None)
    return bool(run is not None and run.message == REUSED)

def _step(job: Job, stage: str, work: Callable[[], Any]) -> Any:
    job.mark(stage, "running")
    with timing.stage(stage, job.id):
        outcome = work()
    job.mark(stage, "reused" if _reused(outcome) else "done")
    return outcome

def _fail(job: Job, stage: str, message: str) -> None:
    job.stages[stage] = "failed"
    job.touch(status="failed", error=f"{stage}: {message or 'did not finish'}")

def run_job(job: Job, llm: LLMClient, reviewer: LLMClient, cache: StageCache | None) -> None:
    """Discover -> Clean -> Reason -> Calculate -> Validate -> Visualize -> dashboard, for one upload."""
    try:
        job.touch(status="running")
        raw = _step(job, "discover", lambda: load_csv_bytes(job.data, file_name=job.file_name))
        with timing.stage("prepare", job.id):
            facts = profile_table(raw.df, raw.load)
            pipe = Pipeline(llm, raw, facts, job.data, answer=job.ask, cache=cache)
        job.touch(pipe=pipe, data=b"")                 # the file now lives in the locked SQL room
        cleaned = _step(job, "clean", pipe.clean)
        if cleaned.result is None or cleaned.facts is None:
            return _fail(job, "clean", cleaned.run.message)
        reasoned = _step(job, "reason", lambda: pipe.reason(cleaned))
        if reasoned.card is None:
            return _fail(job, "reason", reasoned.run.message)
        calc = _step(job, "calculate", lambda: pipe.calculate(reasoned.card))
        if calc.result is None:
            return _fail(job, "calculate", calc.run.message)
        val = _step(job, "validate", lambda: pipe.validate(reasoned.card, calc, reviewer))
        if not val.approved:
            return _fail(job, "validate", "no metric passed validation")
        vis = _step(job, "visualize", lambda: pipe.visualize(reasoned.card, val))
        if vis.plan is None:
            return _fail(job, "visualize", vis.run.message)
        job.mark("dashboard", "running")
        with timing.stage("dashboard", job.id), job.lock:
            spec = build_dashboard(pipe.box, vis.plan, vis.charts, val)
        spec.update(filtered=False, filters_applied=[])
        job.touch(card=reasoned.card, val=val, vis=vis, dashboard=spec)
        job.mark("dashboard", "done")
        job.touch(status="done", stage="")
    except Exception as exc:  # a job thread must never die silently
        _fail(job, job.stage or "discover", f"{type(exc).__name__}: {str(exc)[:300]}")
    finally:
        timing.run_summary(job.status)

# ----------------------------------------------------------------------------- filters (no AI)

class FilterIn(BaseModel):
    column: str
    values: list[str] = Field(default_factory=list, description="category filter: keep only these values")
    start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="date_range: first day")
    end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="date_range: last day")

def _literal(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"

def apply_filters(job: Job, filters: list[FilterIn]) -> dict[str, Any]:
    """Rebuild base with the chosen filters and rerun every approved recipe. An empty list resets."""
    if job.status != "done" or job.pipe is None or job.vis is None or job.dashboard is None:
        raise ValueError("The dashboard is not ready yet.")
    allowed = {f.column: f for f in job.vis.plan.filters}
    conditions = [f"coalesce(({job.card.regular_rows}), false)"]
    applied: list[dict[str, Any]] = []
    for f in filters:
        spec = allowed.get(f.column)
        if spec is None:
            raise ValueError(f"{f.column!r} is not a filter of this dashboard.")
        col = quote_ident(f.column)
        if spec.kind == "category" and f.values:
            conditions.append(f"CAST({col} AS VARCHAR) IN ({', '.join(map(_literal, f.values[:MAX_FILTER_VALUES]))})")
        elif spec.kind == "date_range" and (f.start or f.end):
            if f.start:
                conditions.append(f"CAST({col} AS DATE) >= CAST({_literal(f.start)} AS DATE)")
            if f.end:
                conditions.append(f"CAST({col} AS DATE) <= CAST({_literal(f.end)} AS DATE)")
        else:
            continue
        applied.append(f.model_dump(exclude_none=True))
    with job.lock:
        box = job.pipe.box
        box.create_table(BASE, f"SELECT * FROM {CLEAN} WHERE {' AND '.join(conditions)}", purpose="dashboard filter")
        result = build_dashboard(box, job.vis.plan, job.vis.charts, job.val)
    result.update(filters=job.dashboard["filters"], filtered=bool(applied), filters_applied=applied)
    return result

# ----------------------------------------------------------------------------- the job store

class JobStore:
    """All analyses of this API process, in memory (single user, one process)."""

    def __init__(self, cache: StageCache | None = None) -> None:
        self.cache = cache or StageCache()
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._clients: tuple[LLMClient, LLMClient] | None = None

    def _llms(self) -> tuple[LLMClient, LLMClient]:
        if self._clients is None:
            llm = get_llm()                              # RuntimeError if the API key is missing
            reviewer = get_llm("reviewer") if os.getenv("REVIEWER_LLM_MODEL") else llm
            self._clients = (llm, reviewer)
        return self._clients

    def start(self, file_name: str, data: bytes) -> Job:
        with self._lock:
            for other in self._jobs.values():          # one at a time: a new upload stops any older run
                other.cancel("a new analysis was started")
            running = sum(j.status in ("queued", "running", "needs_answer") for j in self._jobs.values())
            if running >= MAX_RUNNING:
                raise Busy(f"{running} analyses are already running; wait for one to finish.")
            llm, reviewer = self._llms()
            job = Job(id=uuid.uuid4().hex, file_name=file_name, data=data)
            self._jobs[job.id] = job
        threading.Thread(target=run_job, args=(job, llm, reviewer, self.cache),
                         name=f"analysis-{job.id[:8]}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status in ("queued", "running", "needs_answer"):
                raise Busy("This analysis is still running; delete it when it is done or failed.")
            del self._jobs[job_id]
        if job.pipe is not None:
            job.pipe.box.close()
        return True

    def close_all(self) -> None:
        with self._lock:
            jobs, self._jobs = list(self._jobs.values()), {}
        for job in jobs:
            if job.pipe is not None and job.status in ("done", "failed"):
                job.pipe.box.close()
