"""
Stage 4, Calculate: the AI turns the understanding card into the dashboard's metrics.

Each metric is a saved, re-runnable SQL recipe on table base (the regular rows of clean), plus
its shape: single value, trend, breakdown ... Python runs every recipe and checks the result
matches the declared shape. Values are always recomputed from the SQL, never typed in.
A dashboard filter later only rebuilds base; every recipe reruns unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

import sqlglot
from sqlglot import exp
from pydantic import BaseModel, Field, model_validator
from sqlglot.errors import SqlglotError

from engine.agent import Agent, Budget, RunResult, Stage, Workspace
from engine.agent.recipes import Recipe, RecipeBook
from engine.agent.tools import Tool, ToolOutcome, failure, register
from engine.sql import QueryResult
from engine.sql.results import jsonable
from engine.stages.clean import CLEAN
from engine.stages.reason import UnderstandingCard

BASE = "base"
CARD_BUDGET = 12_000       # characters of the understanding card given to the AI
MAX_METRICS = 15
MAX_TIME_PERIODS = 60
MIN_TIME_FILL = 0.5
_NUMERIC = ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "NUMERIC")
_TEMPORAL = ("DATE", "TIMESTAMP")

Shape = Literal["single_value", "by_time", "by_category", "by_time_and_category", "distribution", "table"]

# ----------------------------------------------------------------------------- what is saved

class Metric(Recipe):
    """A recipe plus what Validate and Visualize need to know about it."""
    question: str = ""
    shape: str = "table"
    dimensions: list[str] = Field(default_factory=list)
    measures: list[str] = Field(default_factory=list)
    unit: str = ""
    numerator: str = ""
    denominator: str = ""
    time_grain: str = ""
    confidence: float = 0.0

class SaveMetricArgs(BaseModel):
    name: str = Field(description="snake_case, e.g. approved_leave_days")
    meaning: str = Field(description="What the number means: what is counted and what is left out")
    question: str = Field(description="The card question it answers, e.g. Q3")
    sql: str = Field(description="One read-only SELECT on base, with a final ORDER BY if it returns several rows")
    shape: Shape = Field(description="single_value = 1 row, no dimensions; by_time = a series over a date column; "
                                     "by_category = values per group; by_time_and_category; "
                                     "distribution = counts per value or bin; table = anything else")
    dimensions: list[str] = Field(default_factory=list, description="Result columns that are labels (dates, groups)")
    measures: list[str] = Field(description="Result columns that are numbers")
    unit: str = Field(default="", description="e.g. EUR, days, %, ms")
    numerator: str = Field(default="", description="For rates: what is counted on top")
    denominator: str = Field(default="", description="For rates: what it is divided by")
    time_grain: str = Field(default="", description="For time shapes: day, week, month ...")
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)

# ----------------------------------------------------------------------------- the tool

def shape_problems(args: SaveMetricArgs, result: QueryResult, dims: list[str], measures: list[str]) -> list[str]:
    """Does the result really have the shape the AI declared?"""
    types = {c: t.upper() for c, t in zip(result.columns, result.types)}
    problems: list[str] = []
    for col in [*dims, *measures]:
        if col not in types:
            problems.append(f"{col!r} is not a result column (result columns: {result.columns}).")
    unlisted = [c for c in result.columns if c not in dims and c not in measures]
    if unlisted:
        problems.append(f"Name every result column as a dimension or a measure; not named: {unlisted}.")
    if not measures:
        problems.append("Give at least one measure.")
    for m in measures:
        if m in types and not any(k in types[m] for k in _NUMERIC):
            problems.append(f"Measure {m!r} is {types[m]}, not a number.")
    rows = result.rows
    if not rows:
        problems.append("The query returned no rows.")
    if result.truncated:
        problems.append("More than 200 rows: aggregate further, or keep the top N plus 'Other'.")
    if args.shape == "single_value" and (len(rows) != 1 or dims):
        problems.append("single_value needs exactly 1 row and no dimensions.")
    if args.shape in ("by_time", "by_time_and_category") and not any(
            any(k in types.get(d, "") for k in _TEMPORAL) for d in dims):
        problems.append(f"{args.shape} needs a DATE or TIMESTAMP dimension (use date_trunc).")
    time_dims = [d for d in dims if any(k in types.get(d, "") for k in _TEMPORAL)]
    if args.shape in ("by_time", "by_time_and_category") and time_dims and rows:
        at = {c: i for i, c in enumerate(result.columns)}
        periods = len({str(r[at[time_dims[0]]]) for r in rows})
        if periods > MAX_TIME_PERIODS:
            problems.append(f"{periods} periods is too many to read as a trend; use a coarser date_trunc "
                            f"(at most {MAX_TIME_PERIODS} periods, e.g. week or month).")
        others = [d for d in dims if d != time_dims[0] and d in at]
        groups = len({tuple(str(r[at[d]]) for d in others) for r in rows}) if others else 1
        if groups > 1 and len(rows) < MIN_TIME_FILL * periods * groups:
            problems.append(f"Most groups have no value in most periods ({len(rows)} of {periods * groups} "
                            "period-group pairs); use a coarser date_trunc so each group appears in each period.")
    if args.shape in ("by_category", "by_time_and_category", "distribution") and not dims:
        problems.append(f"{args.shape} needs at least one dimension.")
    if len(rows) > 1:
        ordered = _order_names(result.sql, result.columns)
        if ordered is not None and not ordered:
            problems.append("Add a final ORDER BY, so the rows come back in the same order every time.")
        elif ordered:
            loose = [d for d in dims if d.casefold() not in ordered]
            if loose:
                problems.append(f"End the ORDER BY with every dimension as a tie-break ({', '.join(loose)}), "
                                "so equal values always come back in the same order.")
    return problems

def _order_names(sql: str, columns: list[str]) -> set[str] | None:
    """Result columns used by the final ORDER BY (by name, alias or position). None = cannot tell."""
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except SqlglotError:
        return None
    order = tree.args.get("order") if tree is not None else None
    if order is None:
        return set()
    names: set[str] = set()
    for item in order.expressions:
        node = item.this
        if isinstance(node, exp.Literal) and not node.is_string:
            try:
                position = int(node.name)
            except ValueError:
                continue
            if 1 <= position <= len(columns):
                names.add(columns[position - 1].casefold())
        else:
            names.update(c.name.casefold() for c in node.find_all(exp.Column))
    return names

def _add_tie_breaks(sql: str, columns: list[str], dims: list[str]) -> str:
    """Add any dimension missing from the final ORDER BY. Only the order of tied rows changes, never a value."""
    ordered = _order_names(sql, columns)
    missing = [d for d in dims if ordered is not None and d.casefold() not in ordered and d in columns]
    if not missing:
        return sql
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
        for d in missing:
            tree = tree.order_by(exp.column(d, quoted=True), append=True, copy=False)
        return tree.sql(dialect="duckdb")
    except Exception:  # cannot rewrite it: the normal ORDER BY check will explain the problem
        return sql

def _save_metric(args: SaveMetricArgs, ws: Workspace) -> ToolOutcome:
    name = args.name.strip()
    if not RecipeBook.valid_name(name):
        return failure("invalid_name", f"Invalid metric name {name!r}.", "Use snake_case (max 60 characters).")
    saved_metrics = sum(isinstance(r, Metric) for r in ws.recipes.all())
    if name not in ws.recipes and saved_metrics >= MAX_METRICS:
        return failure("too_many", f"At most {MAX_METRICS} metrics.", "Replace a weaker one (same name), or finish.")
    result = ws.sandbox.run(args.sql, purpose=f"metric {name}", tables=(BASE,))
    actual = {c.casefold(): c for c in result.columns}
    dims = [actual.get(d.strip().casefold(), d.strip()) for d in args.dimensions]
    measures = [actual.get(m.strip().casefold(), m.strip()) for m in args.measures]
    fixed = _add_tie_breaks(result.sql, result.columns, dims)
    if fixed != result.sql:
        result = ws.sandbox.run(fixed, purpose=f"metric {name} (tie-break added)", tables=(BASE,))
    problems = shape_problems(args, result, dims, measures)
    if problems:
        return failure("bad_metric", " | ".join(problems), "Fix the SQL or the shape fields, then save again.")
    from engine.stages.validate import context_numbers, result_numbers, sql_numbers, untraceable
    rows = [[jsonable(v) for v in row] for row in result.rows]
    known = result_numbers(rows) + sql_numbers(result.sql) + context_numbers(ws.sandbox)
    loose = untraceable(" ".join([args.meaning, *args.assumptions]), known)
    if loose:
        return failure("numbers_in_text", "The meaning or assumptions quote numbers that are not in the result "
                       f"or the SQL: {', '.join(loose)}.",
                       "Describe the metric in words (e.g. 'revenue on event days compared with normal days'); "
                       "the dashboard shows the numbers from the result.")
    saved = ws.recipes.save(Metric(
        name=name, meaning=args.meaning.strip(), sql=result.sql,
        assumptions=[a.strip() for a in args.assumptions if a.strip()],
        columns=result.columns, preview=[[jsonable(v) for v in row] for row in result.rows[:10]],
        question=args.question.strip(), shape=args.shape, dimensions=dims, measures=measures,
        unit=args.unit.strip(), numerator=args.numerator.strip(), denominator=args.denominator.strip(),
        time_grain=args.time_grain.strip(), confidence=args.confidence,
    ))
    index = {c: i for i, c in enumerate(result.columns)}
    nulls = {m: n for m in measures if (n := sum(row[index[m]] is None for row in result.rows))}
    view = {"ok": True, "saved": name, "version": saved.version, "rows": len(result.rows), "preview": saved.preview}
    if nulls:
        view["null_values"] = nulls
    return ToolOutcome(json.dumps(view, ensure_ascii=False, default=str))

SAVE_METRIC = register(Tool(
    "save_metric",
    "Save one dashboard metric: SQL on base plus its shape. Python runs it, checks the result matches the "
    "shape, and returns a preview. Saving the same name again replaces it.",
    SaveMetricArgs, _save_metric,
))

# ----------------------------------------------------------------------------- finish and its gate

class AnsweredQuestion(BaseModel):
    question: int = Field(description="Question number from the card, e.g. 3")
    metrics: list[str] = Field(description="Saved metric names that answer it")

class DroppedQuestion(BaseModel):
    question: int = Field(description="Question number from the card")
    reason: str = Field(description="Why base cannot answer it, e.g. 'no allowance column'")

class CalculateResult(BaseModel):
    metrics: list[str] = Field(description="Saved metric names, most important first")
    answered: list[AnsweredQuestion] = Field(default_factory=list)
    dropped: list[DroppedQuestion] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list, description="Caveats for the dashboard, e.g. partial last month")

    @model_validator(mode="after")
    def _merge_repeats(self) -> CalculateResult:
        """A question listed twice is merged, not refused (its metrics or reasons are combined)."""
        self.metrics = list(dict.fromkeys(self.metrics))
        merged: dict[int, list[str]] = {}
        for a in self.answered:
            names = merged.setdefault(a.question, [])
            for m in a.metrics:
                if m not in names:
                    names.append(m)
        reasons: dict[int, list[str]] = {}
        for d in self.dropped:
            reasons.setdefault(d.question, []).append(d.reason)
        self.answered = [AnsweredQuestion(question=q, metrics=ms) for q, ms in merged.items()]
        self.dropped = [DroppedQuestion(question=q, reason="; ".join(dict.fromkeys(rs))) for q, rs in reasons.items()]
        return self

def check_calculate(result: CalculateResult, ws: Workspace) -> list[str]:
    """Every listed metric is saved, and every card question is answered or dropped (repeats are merged)."""
    saved = {r.name for r in ws.recipes.all() if isinstance(r, Metric)}
    card = ws.artifacts.get("understanding")
    n = len(card.questions) if isinstance(card, UnderstandingCard) else 0
    problems: list[str] = []
    if not result.metrics:
        problems.append("Save and list at least one metric.")
    unknown = [m for m in result.metrics if m not in saved]
    if unknown:
        problems.append(f"Not saved with save_metric: {unknown}.")
    for a in result.answered:
        bad = [m for m in a.metrics if m not in saved]
        if not a.metrics or bad:
            problems.append(f"Question {a.question}: answer it with saved metrics (unknown: {bad or 'none given'}).")
    answered = {a.question for a in result.answered}
    dropped = {d.question for d in result.dropped}
    seen = answered | dropped
    missing = [i for i in range(1, n + 1) if i not in seen]
    both = sorted(answered & dropped)
    outside = sorted(i for i in seen if not 1 <= i <= n)
    if missing:
        problems.append(f"Questions neither answered nor dropped: {missing}.")
    if both:
        problems.append(f"Questions both answered and dropped: {both}. Keep only one.")
    if outside:
        problems.append(f"There are only {n} questions; unknown numbers: {outside}.")
    return problems[:15]


# ----------------------------------------------------------------------------- the stage

CALCULATE_INSTRUCTIONS = """Goal: turn the understanding card into the dashboard's metrics: saved, re-runnable
SQL recipes. Read only table base = the regular rows of clean (special rows such as totals are already
left out). Never type a number yourself: every value shown later comes from a saved recipe.

Steps:
1. Go through the numbered questions. Drop any that base cannot answer (a needed column is missing,
   too few rows, or outside data is needed), with the reason.
2. Design metrics for the rest. Follow each column's kind and aggregation in the card, e.g.:
   never sum a level_or_snapshot over time (take the latest per entity, or average at one point in time);
   never average codes, identifiers or categories (count them or show shares);
   compute rates as sum(numerator) / sum(denominator), never as an average of rates, and name both;
   count distinct entities when rows repeat per entity.
3. Time: if the card has a time column, build the main trend with date_trunc at a grain a reader can
   follow: at most 60 periods, with every group present in most periods (e.g. month for half a year of
   daily rows, week for a quarter). For a rate per period use sum(numerator) / sum(denominator) inside
   the period. Split a trend by a category only when it has a few groups; otherwise show each group's
   total as a breakdown. State in assumptions if the first or last period is partial.
4. Breakdowns with many groups: keep the top N and put the rest in 'Other'. End multi-row results with
   an ORDER BY that includes every dimension as a tie-break (e.g. ORDER BY total DESC, region), so equal
   values always come back in the same order.
5. Save each metric with save_metric; it runs the SQL and checks the result's shape. Write meaning and
   assumptions in words: a number in them must appear in the result or the SQL (Python refuses others).
   Test with query first if unsure.
6. Save the 6-12 metrics that matter most: a few headline single values, the main trend if time exists,
   and the most useful breakdowns. Then call finish: metric names in priority order, which metrics
   answer which question, dropped questions with reasons, and caveats in notes."""

CALCULATE_STAGE = Stage(
    name="calculate",
    instructions=CALCULATE_INSTRUCTIONS,
    output=CalculateResult,
    tools=("look", "query", "save_metric", "ask_user"),
    tables=(BASE,),
    check=check_calculate,
    thinking=True,
    budget=Budget(max_steps=30, max_output_tokens=150_000),
)

@dataclass
class CalculateOutcome:
    run: RunResult
    result: CalculateResult | None = None
    metrics: list[Metric] = field(default_factory=list)   # in priority order

def build_base(ws: Workspace, card: UnderstandingCard) -> int:
    """Table base = the regular rows of clean. Every metric reads only base, so a dashboard
    filter only has to rebuild base; the recipes rerun unchanged. Returns base's row count."""
    sql = f"SELECT * FROM {CLEAN} WHERE coalesce(({card.regular_rows}), false)"
    rows = ws.sandbox.create_table(BASE, sql, purpose="base: regular rows")
    ws.artifacts["base_sql"] = sql
    return rows

def run_calculate(agent: Agent, card: UnderstandingCard) -> CalculateOutcome:
    agent.ws.artifacts["understanding"] = card
    rows = build_base(agent.ws, card)
    questions = "\n".join(f"Q{i}. {q}" for i, q in enumerate(card.questions, 1))
    about = json.dumps(card.model_dump(exclude={"questions"}, exclude_defaults=True), ensure_ascii=False)
    task = (f"Build the dashboard's metrics from table base ({rows} regular rows of clean).\n\n"
            f"Questions from the understanding card:\n{questions}\n\n"
            f"Understanding card (meaning and kind of each column, special rows, time, doubts):\n"
            f"{_clip(about, CARD_BUDGET)}")
    return _outcome(agent, agent.run(CALCULATE_STAGE, task))

def resume_calculate(agent: Agent, paused: RunResult, answer: str) -> CalculateOutcome:
    return _outcome(agent, agent.resume(paused, answer))

def _outcome(agent: Agent, run: RunResult) -> CalculateOutcome:
    if run.status != "finished" or not isinstance(run.output, CalculateResult):
        return CalculateOutcome(run=run)
    metrics = [m for name in run.output.metrics if isinstance(m := agent.ws.recipes.get(name), Metric)]
    agent.ws.artifacts["calculate_result"] = run.output
    return CalculateOutcome(run=run, result=run.output, metrics=metrics)

def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
