"""
Runs the AI stages for one file and reuses saved stage outputs.

A saved output is reused only when nothing it depends on changed: same file bytes, same model,
same instructions, tools and answer form, same earlier stages. It is also replayed through today's
checks (SQL guard, loss report, shape checks, finish gates); if anything fails, the stage runs again.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from engine.agent import Agent, Question, RecipeBook, RunResult, Stage, Workspace
from engine.agent.loop import BASE_RULES
from engine.agent.tools import TOOLS
from engine.config import PROJECT_ROOT
from engine.discover import FactSheet, RawTable
from engine.llm import LLMClient
from engine.sql import QueryError, Sandbox
from engine.stages import (
    CALCULATE_STAGE, CLEAN_STAGE, REASON_STAGE, VALIDATE_STAGE, VISUALIZE_STAGE,
    CalculateOutcome, CalculateResult, ChartArgs, CleanOutcome, CleanResult, DashboardPlan, Metric,
    ReasonOutcome, Review, UnderstandingCard, ValidateOutcome, Verdict, VisualizeOutcome,
    build_base, check_calculate, check_clean, check_reason, check_visualize, measure,
    resume_calculate, resume_clean, resume_reason, run_calculate, run_clean, run_reason,
    run_validate, run_visualize,
)
from engine.stages.calculate import BASE, SaveMetricArgs, shape_problems
from engine.stages.clean import CLEAN, MAX_EXPANDED_SQL, build_report
from engine.stages.clean import _outcome as clean_outcome
from engine.stages.validate import APPROVED, REVIEWER_PROMPT, result_numbers
from engine.stages.visualize import chart_problems

CACHE_VERSION = "1"            # bump to invalidate every saved output after a big code change
STAGES = ("clean", "reason", "calculate", "validate", "visualize")
Answer = Callable[[Question], str]

def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]

def stage_version(stage: Stage) -> str:
    """Changes whenever the stage's instructions, base rules, tools or answer form change."""
    tools = json.dumps([TOOLS[t].spec() for t in stage.tools], sort_keys=True)
    form = json.dumps(stage.output.model_json_schema(), sort_keys=True)
    return _digest(CACHE_VERSION, BASE_RULES, stage.name, stage.instructions, tools, form)

class StageCache:
    """Saved stage outputs as JSON files. Local only: they hold SQL and small result previews."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or PROJECT_ROOT / ".cache" / "stages"

    def load(self, key: str) -> dict[str, Any] | None:
        try:
            data = json.loads((self.root / f"{key}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def save(self, key: str, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f"{key}.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(self.root / f"{key}.json")

class Pipeline:
    """Clean -> Reason -> Calculate -> Validate -> Visualize for one file, in one locked SQL room."""

    def __init__(self, llm: LLMClient, raw: RawTable, facts: FactSheet, data: bytes, *, answer: Answer,
                 cache: StageCache | None = None, fresh_from: str | None = None) -> None:
        if fresh_from is not None and fresh_from not in STAGES:
            raise ValueError(f"fresh_from must be one of {STAGES}")
        self.raw, self.facts, self.answer, self.cache = raw, facts, answer, cache
        self.fresh = STAGES.index(fresh_from) if fresh_from else len(STAGES)
        self.box = Sandbox.from_raw(raw)
        self.agent = Agent(llm, Workspace(sandbox=self.box))
        self._key = _digest("file", hashlib.sha256(data).hexdigest(), llm.settings.model)

    def __enter__(self) -> Pipeline:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.box.close()

    # ------------------------------------------------------------------ stages

    def clean(self) -> CleanOutcome:
        key, saved = self._lookup("clean", CLEAN_STAGE)
        if saved is not None and (outcome := self._replay_clean(saved)) is not None:
            self._chain(key, saved)
            return outcome
        start = len(self.agent.ws.answers)
        outcome = self._ask(run_clean(self.agent, self.facts), resume_clean)
        if outcome.result is not None:
            self._store(key, {"sql": self.agent.ws.artifacts.get("clean_sql"),
                              "result": outcome.result.model_dump(), "answers": self.agent.ws.answers[start:]})
        return outcome

    def reason(self, cleaned: CleanOutcome) -> ReasonOutcome:
        if cleaned.result is None or cleaned.facts is None:
            raise ValueError("Clean must finish before Reason.")
        key, saved = self._lookup("reason", REASON_STAGE)
        if saved is not None and (outcome := self._replay_reason(saved)) is not None:
            self._chain(key, saved)
            return outcome
        start = len(self.agent.ws.answers)
        outcome = self._ask(run_reason(self.agent, clean=cleaned.result, clean_facts=cleaned.facts,
                                       load=self.raw.load), resume_reason)
        if outcome.card is not None:
            self._store(key, {"card": outcome.card.model_dump(), "answers": self.agent.ws.answers[start:]})
        return outcome

    def calculate(self, card: UnderstandingCard) -> CalculateOutcome:
        key, saved = self._lookup("calculate", CALCULATE_STAGE)
        if saved is not None and (outcome := self._replay_calculate(card, saved)) is not None:
            self._chain(key, saved)
            return outcome
        self.agent.ws.recipes = RecipeBook()           # drop anything a failed replay left behind
        start = len(self.agent.ws.answers)
        outcome = self._ask(run_calculate(self.agent, card), resume_calculate)
        if outcome.result is not None:
            metrics = [r.model_dump() for r in self.agent.ws.recipes.all() if isinstance(r, Metric)]
            self._store(key, {"result": outcome.result.model_dump(), "metrics": metrics,
                              "answers": self.agent.ws.answers[start:]})
        return outcome

    def validate(self, card: UnderstandingCard, calc: CalculateOutcome,
                 reviewer: LLMClient | None = None) -> ValidateOutcome:
        reviewer = reviewer or self.agent.llm
        metrics_id = json.dumps([[m.name, m.sql] for m in calc.metrics], ensure_ascii=False)
        key, saved = self._lookup("validate", VALIDATE_STAGE, REVIEWER_PROMPT, reviewer.settings.model, metrics_id)
        if saved is not None and (outcome := self._replay_validate(saved)) is not None:
            self._chain(key, saved)
            return outcome
        outcome = run_validate(self.agent, reviewer, card, calc, answer=self.answer)
        if outcome.finished and outcome.calculate is not None and outcome.calculate.result is not None:
            ws = self.agent.ws
            self._store(key, {
                "calculate": outcome.calculate.result.model_dump(),
                "metrics": [r.model_dump() for r in ws.recipes.all() if isinstance(r, Metric)],
                "verdicts": {n: v.model_dump() for n, v in outcome.verdicts.items()},
                "reviews": {n: r.model_dump() for n, r in outcome.reviews.items()},
                "notes": outcome.notes, "repaired": outcome.repaired,
                "second_ways": ws.artifacts.get("second_ways", {}),
            })
        return outcome

    def visualize(self, card: UnderstandingCard, val: ValidateOutcome) -> VisualizeOutcome:
        metrics_id = json.dumps([[m.name, m.sql] for m in val.approved], ensure_ascii=False)
        key, saved = self._lookup("visualize", VISUALIZE_STAGE, metrics_id)
        if saved is not None and (outcome := self._replay_visualize(saved, val)) is not None:
            self._chain(key, saved)
            return outcome
        outcome = run_visualize(self.agent, card, val)
        if outcome.plan is not None:
            charts = self.agent.ws.artifacts.get("charts", {})
            self._store(key, {"plan": outcome.plan.model_dump(), "charts": [c.model_dump() for c in charts.values()]})
        return outcome

    # ------------------------------------------------------------------ replay saved outputs

    def _replay_clean(self, saved: dict[str, Any]) -> CleanOutcome | None:
        ws = self.agent.ws
        try:
            result = CleanResult.model_validate(saved["result"])
            self.box.create_table(CLEAN, saved["sql"], purpose="save_clean (saved output)",
                                  max_sql_chars=MAX_EXPANDED_SQL)
            ws.artifacts["clean_report"] = build_report(self.box, result.columns)
            ws.artifacts["clean_sql"] = saved["sql"]
        except (KeyError, TypeError, ValueError, QueryError):
            return None
        if check_clean(result, ws):
            return None
        ws.answers.extend(saved.get("answers", []))
        return clean_outcome(self.agent, self._saved_run("clean", result))

    def _replay_reason(self, saved: dict[str, Any]) -> ReasonOutcome | None:
        ws = self.agent.ws
        try:
            card = UnderstandingCard.model_validate(saved["card"])
        except (KeyError, TypeError, ValueError):
            return None
        if check_reason(card, ws):
            return None
        ws.answers.extend(saved.get("answers", []))
        ws.artifacts["understanding"] = card
        return ReasonOutcome(run=self._saved_run("reason", card), card=card)

    def _replay_calculate(self, card: UnderstandingCard, saved: dict[str, Any]) -> CalculateOutcome | None:
        ws = self.agent.ws
        ws.recipes = RecipeBook()
        try:
            ws.artifacts["understanding"] = card
            build_base(ws, card)
            result = CalculateResult.model_validate(saved["result"])
            for item in saved["metrics"]:
                metric = Metric.model_validate(item)
                args = SaveMetricArgs.model_validate({k: getattr(metric, k) for k in SaveMetricArgs.model_fields})
                rerun = self.box.run(metric.sql, purpose=f"metric {metric.name} (saved output)", tables=(BASE,))
                if shape_problems(args, rerun, metric.dimensions, metric.measures):
                    return None                        # today's shape rules reject it: run the stage again
                ws.recipes.save(metric)
        except (KeyError, TypeError, ValueError, QueryError):
            return None
        if check_calculate(result, ws):
            return None
        ws.answers.extend(saved.get("answers", []))
        ws.artifacts["calculate_result"] = result
        metrics = [m for name in result.metrics if isinstance(m := ws.recipes.get(name), Metric)]
        return CalculateOutcome(run=self._saved_run("calculate", result), result=result, metrics=metrics)

    def _replay_validate(self, saved: dict[str, Any]) -> ValidateOutcome | None:
        """Works on a copy of the recipe book, so a failed replay leaves no repaired versions behind."""
        ws = self.agent.ws
        original = ws.recipes
        ws.recipes = RecipeBook()
        for recipe in original.all():
            ws.recipes.save(recipe)
        outcome = self._rebuild_validate(saved)
        if outcome is None:
            ws.recipes = original
        return outcome

    def _rebuild_validate(self, saved: dict[str, Any]) -> ValidateOutcome | None:
        ws = self.agent.ws
        try:
            result = CalculateResult.model_validate(saved["calculate"])
            for item in saved["metrics"]:
                ws.recipes.save(Metric.model_validate(item))        # repaired versions included
            verdicts = {n: Verdict.model_validate(v) for n, v in saved["verdicts"].items()}
            reviews = {n: Review.model_validate(r) for n, r in saved["reviews"].items()}
        except (KeyError, TypeError, ValueError):
            return None
        metrics = [m for n in result.metrics if isinstance(m := ws.recipes.get(n), Metric)]
        approved = [m for m in metrics if m.name in verdicts and verdicts[m.name].verdict in APPROVED]
        facts = {m.name: measure(self.box, m) for m in approved}
        if any(f.error or not f.reruns_same for f in facts.values()):
            return None                                             # a number no longer re-runs the same
        ws.artifacts["second_ways"] = saved.get("second_ways", {})
        ws.artifacts["calculate_result"] = result
        calc = CalculateOutcome(run=self._saved_run("calculate", result), result=result, metrics=metrics)
        return ValidateOutcome(approved=approved, verdicts=verdicts, facts=facts, reviews=reviews,
                               notes=list(saved.get("notes", [])), repaired=list(saved.get("repaired", [])),
                               calculate=calc, runs=[self._saved_run("validate", None)], finished=True)

    def _replay_visualize(self, saved: dict[str, Any], val: ValidateOutcome) -> VisualizeOutcome | None:
        ws = self.agent.ws
        try:
            plan = DashboardPlan.model_validate(saved["plan"])
            charts = {c.chart: c for c in (ChartArgs.model_validate(x) for x in saved["charts"])}
        except (KeyError, TypeError, ValueError):
            return None
        metrics = {m.name: m for m in val.approved}
        ws.artifacts.update(visualize_metrics=list(val.approved), charts=charts,
                            visualize_numbers=[v for m in val.approved if m.name in val.facts
                                               for v in result_numbers(val.facts[m.name].result)])
        for chart in charts.values():
            metric = metrics.get(chart.metric)
            if metric is None:
                return None
            try:
                result = self.box.run(metric.sql, purpose=f"chart {chart.chart} (saved output)", tables=(BASE,))
            except QueryError:
                return None
            if chart_problems(chart, metric, result)[0]:
                return None                                         # today's chart checks reject it
        if check_visualize(plan, ws):
            return None
        ws.artifacts["dashboard_plan"] = plan
        listed = sorted((charts[c] for c in dict.fromkeys(plan.charts) if c in charts), key=lambda c: c.priority)
        return VisualizeOutcome(run=self._saved_run("visualize", plan), plan=plan, charts=listed)

    # ------------------------------------------------------------------ helpers

    def _lookup(self, name: str, stage: Stage, *extra: str) -> tuple[str, dict[str, Any] | None]:
        key = _digest(self._key, stage_version(stage), *extra)
        if self.cache is None or STAGES.index(name) >= self.fresh:
            return key, None
        return key, self.cache.load(key)

    def _store(self, key: str, data: dict[str, Any]) -> None:
        if self.cache is not None:
            self.cache.save(key, data)
        self._chain(key, data)

    def _chain(self, key: str, data: dict[str, Any]) -> None:
        """The next stage's key depends on this stage's actual output, so a changed output never
        reuses a later stage that was built on the old one."""
        self._key = _digest(key, json.dumps(data, sort_keys=True, ensure_ascii=False, default=str))

    def _ask(self, outcome: Any, resume: Callable[[Agent, RunResult, str], Any]) -> Any:
        while outcome.run.status == "needs_user" and outcome.run.question is not None:
            outcome = resume(self.agent, outcome.run, self.answer(outcome.run.question))
        return outcome

    @staticmethod
    def _saved_run(stage: str, output: Any) -> RunResult:
        return RunResult(status="finished", stage=stage, output=output, message="reused saved output",
                         usage={"steps": 0, "seconds": 0.0, "input_tokens": 0, "output_tokens": 0})
