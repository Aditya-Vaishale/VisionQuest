"""Stage 6a, Visualize: the AI turns approved metrics into a dashboard plan.

Per metric the AI picks the chart type, which columns go where, size, section and priority, plus the
page title and useful filters. Python checks every chart against the metric's real result and reports
chart facts back (too many bars, missing periods ...): the Chart loop. The output is a neutral
dashboard spec (JSON) for the website. It holds only numbers Python computed.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic import BaseModel, Field, field_validator
from engine.agent import Agent, Budget, RunResult, Stage, Workspace
from engine.agent.tools import Tool, ToolOutcome, failure, register
from engine.sql import QueryError, QueryResult, Sandbox, quote_ident
from engine.sql.results import jsonable
from engine.stages.calculate import BASE, Metric
from engine.stages.reason import UnderstandingCard
from engine.stages.validate import ValidateOutcome, result_numbers, untraceable
from engine.stages.validate import ValidateOutcome, context_numbers, result_numbers, sql_numbers, untraceable


ChartKind = Literal["kpi", "line", "area", "bar", "stacked_bar", "grouped_bar", "pie", "scatter", "table"]
Size = Literal["S", "M", "L", "XL"]       # quarter, half, three-quarter, full width
MAX_BARS = 25
MAX_SERIES = 8
MAX_PIE_SLICES = 6
MIN_LINE_POINTS = 3
_PERCENT_UNITS = {"%", "pct", "percent"}
MIN_SCATTER_POINTS = 5
MAX_KPI_VALUES = 4
CARD_BUDGET = 6_000        # characters of the card given to the AI
METRICS_BUDGET = 20_000    # characters of metric definitions and results given to the AI
_NUMERIC = ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "NUMERIC")
_TEMPORAL = ("DATE", "TIMESTAMP")

# ----------------------------------------------------------------------------- one chart order

class ChartArgs(BaseModel):
    chart: str = Field(description="Chart id, snake_case, e.g. revenue_by_region_bar")
    metric: str = Field(description="The approved metric this chart shows")
    kind: ChartKind = Field(description=(
        "kpi = big number card(s) for a 1-row result; line/area = a trend over a date column; "
        "bar = values per group; stacked_bar / grouped_bar = values per group split by a series column; "
        "pie = shares of one whole (max 6 slices, never negative); scatter = two measures against each other; "
        "table = when no chart fits or exact values matter"))
    x: str = Field(default="", description="Result column on the x axis (label or date); empty for kpi and table")
    y: list[str] = Field(default_factory=list, description="Measure column(s) to plot; for kpi, the values to show")
    series: str = Field(default="", description="Optional result column that splits lines or bars by colour")
    horizontal: bool = Field(default=False, description="Bars sideways: good for long labels or many groups")
    sort: Literal["x", "value_desc", "value_asc", "as_is"] = Field(
        default="as_is", description="Display order of rows; time charts are always ordered by date")
    top_n: int | None = Field(default=None, ge=1, description="Show only the first N rows after sorting")
    title: str = Field(description="Short title; no numbers that are not in the result")
    subtitle: str = Field(default="", description="One short line: what is counted, or the period")
    unit: str = Field(default="", description="e.g. EUR, %, days")
    decimals: int = Field(default=0, ge=0, le=4)
    size: Size = Field(description="S = quarter width (kpi), M = half, L = three quarters, XL = full width")
    section: str = Field(description="Section heading, e.g. Overview, Trends, Breakdowns")
    priority: int = Field(ge=1, le=100, description="1 = most important; shown first")
    @field_validator("x", "series", mode="before")
    @classmethod
    def _one_name(cls, value: Any) -> Any:
        """The AI sometimes sends a column as a list or as list text ('["age_group"]'); keep the one name."""
        if isinstance(value, str) and value.strip().startswith("["):
            try:
                value = json.loads(value)
            except ValueError:
                return value
        if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
            return value[0]
        return value

# ----------------------------------------------------------------------------- chart facts (Python)

def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

def _is_type(type_name: str, kinds: tuple[str, ...]) -> bool:
    return any(k in type_name for k in kinds)

def _as_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None

def missing_periods(values: list[Any]) -> str:
    """'3 months missing between ...' when a date series has holes; '' when complete or unclear."""
    days = sorted({d for d in map(_as_date, values) if d is not None})
    if len(days) < 3:
        return ""
    steps = sorted((b - a).days for a, b in zip(days, days[1:]))
    step = steps[len(steps) // 2]
    months = (days[-1].year - days[0].year) * 12 + days[-1].month - days[0].month
    if 28 <= step <= 31:
        expected, unit = months + 1, "months"
    elif 89 <= step <= 92:
        expected, unit = months // 3 + 1, "quarters"
    elif 365 <= step <= 366:
        expected, unit = days[-1].year - days[0].year + 1, "years"
    elif step >= 1:
        expected = (days[-1] - days[0]).days // step + 1
        unit = {1: "days", 7: "weeks"}.get(step, f"{step}-day periods")
    else:
        return ""
    missing = expected - len(days)
    return f"{missing} {unit} missing between {days[0]} and {days[-1]}" if missing > 0 else ""

def chart_problems(args: ChartArgs, metric: Metric, result: QueryResult) -> tuple[list[str], list[str]]:
    """Problems block the chart (the AI must change it). Facts are shown so the AI can judge."""
    types = {c: t.upper() for c, t in zip(result.columns, result.types)}
    rows, n = result.rows, len(result.rows)
    problems: list[str] = []
    facts = [f"{n} rows"]
    for c in [args.x, *args.y, args.series]:
        if c and c not in types:
            problems.append(f"{c!r} is not a result column of {metric.name} (columns: {result.columns}).")
    if problems:
        return problems, facts
    for m in args.y:
        if not _is_type(types[m], _NUMERIC):
            problems.append(f"y column {m!r} is {types[m]}, not a number.")
    unit = (args.unit or metric.unit).strip().lower()
    if not problems and unit in _PERCENT_UNITS:
        index = {c: i for i, c in enumerate(result.columns)}
        for m in args.y:
            values = [abs(r[index[m]]) for r in rows if _is_num(r[index[m]])]
            if values and max(values) > 100:
                problems.append(f"{m!r} reaches {max(values):g}, so it is not a percentage; set this "
                                f"chart's unit to the one that fits {m!r} instead of {unit!r}.")
    kind = args.kind
    if kind == "kpi":
        if n != 1:
            problems.append(f"kpi needs a 1-row result; {metric.name} has {n} rows (use a chart or table).")
        if not 1 <= len(args.y) <= MAX_KPI_VALUES:
            problems.append(f"kpi shows 1 to {MAX_KPI_VALUES} values; list them in y.")
        return problems, facts
    if kind == "table":
        return problems, facts
    if not args.x or not args.y:
        return problems + [f"{kind} needs an x column and at least one y column."], facts

    index = {c: i for i, c in enumerate(result.columns)}
    xs = [r[index[args.x]] for r in rows]
    distinct_x = len({str(v) for v in xs})
    x_is_time, x_is_num = _is_type(types[args.x], _TEMPORAL), _is_type(types[args.x], _NUMERIC)
    if args.series:
        series_count = len({str(r[index[args.series]]) for r in rows})
        facts.append(f"{series_count} series")
        if series_count > MAX_SERIES:
            problems.append(f"{series_count} series is too many colours; at most {MAX_SERIES}.")
    elif distinct_x < n and kind != "scatter":
        problems.append(f"{args.x!r} repeats ({n} rows, {distinct_x} distinct): add a series column or pick another x.")

    if kind in ("line", "area"):
        if not (x_is_time or x_is_num):
            problems.append(f"{kind} needs a date or number on x; {args.x!r} is {types[args.x]} (use bar).")
        if distinct_x < MIN_LINE_POINTS:
            problems.append(f"{kind} needs at least {MIN_LINE_POINTS} points; there are {distinct_x} (use bar or kpi).")
        if args.top_n:
            problems.append("time charts show every period; remove top_n.")
        if x_is_time and (gaps := missing_periods(xs)):
            facts.append(gaps)
    if kind in ("bar", "stacked_bar", "grouped_bar"):
        shown = min(distinct_x, args.top_n or distinct_x)
        if shown > MAX_BARS:
            problems.append(f"{shown} bars is too many to read; set top_n to {MAX_BARS} or less, or use a table.")
    if kind in ("stacked_bar", "grouped_bar") and not args.series and len(args.y) < 2:
        problems.append(f"{kind} needs a series column, or two or more y columns.")
    if kind == "stacked_bar" and any(_is_num(r[index[m]]) and r[index[m]] < 0 for r in rows for m in args.y):
        problems.append("stacked bars cannot show negative values; use grouped_bar or line.")
    if kind == "pie":
        if len(args.y) != 1 or args.series:
            problems.append("pie shows exactly one y column and no series.")
        elif any(not _is_num(r[index[args.y[0]]]) or r[index[args.y[0]]] < 0 for r in rows):
            problems.append("pie needs non-negative values in every slice.")
        if distinct_x > MAX_PIE_SLICES:
            problems.append(f"{distinct_x} slices is too many for a pie (max {MAX_PIE_SLICES}); use bar.")
        if args.top_n and args.top_n < distinct_x:
            problems.append("a pie must show the whole; top_n would hide part of it. Use bar.")
    if kind == "scatter":
        if not x_is_num:
            problems.append(f"scatter needs a number on x; {args.x!r} is {types[args.x]}.")
        if n < MIN_SCATTER_POINTS:
            problems.append(f"scatter needs at least {MIN_SCATTER_POINTS} points; there are {n}.")
    if args.top_n and args.top_n < n and kind not in ("line", "area"):
        facts.append(f"shows the first {args.top_n} of {n} rows")
    return problems, facts

# ----------------------------------------------------------------------------- the save_chart tool (Chart loop)

def _approved(ws: Workspace) -> dict[str, Metric]:
    return {m.name: m for m in ws.artifacts.get("visualize_metrics", [])}

def _save_chart(args: ChartArgs, ws: Workspace) -> ToolOutcome:
    metrics = _approved(ws)
    metric = metrics.get(args.metric.strip())
    if metric is None:
        return failure("unknown_metric", f"{args.metric!r} is not an approved metric.",
                       f"Approved metrics: {', '.join(metrics)}.")
    chart = args.chart.strip()
    if not (chart.isidentifier() and chart == chart.lower()):
        return failure("invalid_name", f"Invalid chart id {chart!r}.", "Use snake_case, e.g. revenue_by_region_bar.")
    result = ws.sandbox.run(metric.sql, purpose=f"chart {chart}", tables=(BASE,))
    problems, facts = chart_problems(args, metric, result)
    allowed = (result_numbers([[jsonable(v) for v in r] for r in result.rows]) + sql_numbers(metric.sql)
               + context_numbers(ws.sandbox) + ([float(args.top_n)] if args.top_n else []))
    made_up = untraceable(f"{args.title} {args.subtitle}", allowed)
    if made_up:
        problems.append(f"title or subtitle quotes numbers that are not in the result: {made_up}.")
    if problems:
        return failure("bad_chart", " | ".join(problems), "Change the chart (kind, columns, top_n, text) and save again.")
    ws.artifacts.setdefault("charts", {})[chart] = args.model_copy(update={"chart": chart, "metric": metric.name})
    return ToolOutcome(json.dumps({"ok": True, "saved": chart, "chart_facts": facts}, ensure_ascii=False))

SAVE_CHART = register(Tool(
    "save_chart",
    "Save one chart for an approved metric. Python checks it against the metric's real result and returns "
    "chart facts; a refused chart must be changed and saved again. Same id again replaces it.",
    ChartArgs, _save_chart,
))

# ----------------------------------------------------------------------------- the page plan and its gate

MAX_FILTERS = 4
MAX_CATEGORY_OPTIONS = 50

class ExcludedMetric(BaseModel):
    metric: str
    reason: str = Field(description="Why it is left out, e.g. 'repeats total_revenue_units'")

class FilterSpec(BaseModel):
    column: str = Field(description="Exact column name in base")
    kind: Literal["date_range", "category"]
    label: str = Field(description="Short label shown next to the filter")

class DashboardPlan(BaseModel):
    title: str = Field(description="Page title about the data; no numbers that are not in a result")
    subtitle: str = Field(default="", description="One short line about the data")
    charts: list[str] = Field(description="Saved chart ids to show")
    excluded: list[ExcludedMetric] = Field(default_factory=list, description="Approved metrics left out, with why")
    filters: list[FilterSpec] = Field(default_factory=list, description="0-4 useful filters")

def check_visualize(plan: DashboardPlan, ws: Workspace) -> list[str]:
    """Every approved metric is shown or excluded with a reason; filters and texts are sound."""
    metrics = _approved(ws)
    saved: dict[str, ChartArgs] = ws.artifacts.get("charts", {})
    problems: list[str] = []
    unknown = [c for c in plan.charts if c not in saved]
    if unknown:
        problems.append(f"Not saved with save_chart: {unknown}.")
    shown = {saved[c].metric for c in plan.charts if c in saved}
    if not shown:
        problems.append("Show at least one saved chart.")
    excluded = {e.metric.strip() for e in plan.excluded if e.reason.strip()}
    missing = [m for m in metrics if m not in shown and m not in excluded]
    if missing:
        problems.append(f"Show or exclude (with a reason) every approved metric; missing: {missing}.")
    if shown & excluded:
        problems.append(f"Shown and excluded at the same time: {sorted(shown & excluded)}.")
    if len(plan.filters) > MAX_FILTERS:
        problems.append(f"At most {MAX_FILTERS} filters.")
    types = {c: t.upper() for c, t in ws.sandbox.schema().get(BASE, [])}
    for f in plan.filters:
        t = types.get(f.column, "")
        if not t:
            problems.append(f"Filter column {f.column!r} is not in base (e.g. {', '.join(list(types)[:20])}).")
        elif f.kind == "date_range" and not _is_type(t, _TEMPORAL):
            problems.append(f"Filter {f.column!r} is {t}; date_range needs a date column.")
        elif f.kind == "category":
            count = ws.sandbox.trusted_query(f"SELECT count(DISTINCT {quote_ident(f.column)}) FROM {BASE}", 1)[0][0]
            if count > MAX_CATEGORY_OPTIONS:
                problems.append(f"Filter {f.column!r} has {count} values; at most {MAX_CATEGORY_OPTIONS} for a category filter.")
    known = ws.artifacts.get("visualize_numbers", []) + context_numbers(ws.sandbox)
    known += [v for m in metrics.values() for v in sql_numbers(m.sql)]
    made_up = untraceable(f"{plan.title} {plan.subtitle}", known)
    if made_up:
        problems.append(f"title or subtitle quotes numbers that are not in any result: {made_up}.")
    return problems[:15]

VISUALIZE_INSTRUCTIONS = """Goal: turn the approved metrics into a clear, visual-first dashboard plan.
Every metric below was approved by Validate. You decide how to show them; you never change their numbers.

Steps:
1. For each metric, pick the chart that fits its question and shape: kpi for 1-row headline numbers;
   line or area for trends over time; bar for comparing groups (horizontal for long labels); stacked or
   grouped bars to split groups by a second column; pie only for a few shares of one whole; scatter to
   relate two measures; table when exact values matter or nothing else fits.
2. Save each chart with save_chart. Python checks it against the real result and returns chart facts
   (row count, missing periods, rows hidden by top_n). If it is refused, change the chart and save again.
3. Layout: priority 1 = most important. Put a few kpi cards (size S) first, then the main trend or
   comparison (L or XL), then supporting charts (M). Group charts into a few short sections.
4. Leave out a metric only if it repeats another one; list it in excluded with the reason.
5. Filters: 0-4 columns of base a reader would want to narrow by (a date range, or a category with few
   values). Check them with look or query on base.
6. Title and subtitle: name what the data is about; no numbers that are not in a result.
7. You may call several tools in one reply. Then call finish with the title, subtitle, chart ids,
   excluded metrics and filters."""

VISUALIZE_STAGE = Stage(
    name="visualize",
    instructions=VISUALIZE_INSTRUCTIONS,
    output=DashboardPlan,
    tools=("look", "query", "save_chart"),
    tables=(BASE,),
    check=check_visualize,
    thinking=True,
    budget=Budget(max_steps=20, max_output_tokens=120_000),
)

# ----------------------------------------------------------------------------- running it, and the spec for the website

def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"

@dataclass
class VisualizeOutcome:
    run: RunResult
    plan: DashboardPlan | None = None
    charts: list[ChartArgs] = field(default_factory=list)     # the listed charts, most important first

def run_visualize(agent: Agent, card: UnderstandingCard, val: ValidateOutcome) -> VisualizeOutcome:
    ws = agent.ws
    ws.artifacts["visualize_metrics"] = list(val.approved)
    ws.artifacts["visualize_numbers"] = [v for m in val.approved if m.name in val.facts for v in result_numbers(val.facts[m.name].result)]
    ws.artifacts["charts"] = {}
    metrics_text = "[]"
    for rows in (12, 4, 1):
        views = []
        for m in val.approved:
            f, v = val.facts.get(m.name), val.verdicts.get(m.name)
            views.append({"name": m.name, "meaning": m.meaning, "shape": m.shape, "dimensions": m.dimensions,
                          "measures": m.measures, "unit": m.unit, "time_grain": m.time_grain,
                          "caveat": v.note if v and v.note else "", "rows": f.rows if f else len(m.preview),
                          "result": {"columns": m.columns, "rows": (f.result if f else m.preview)[:rows]}})
        metrics_text = json.dumps(views, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(metrics_text) <= METRICS_BUDGET:
            break
    about = card.model_dump(include={"dataset", "row_grain", "time", "columns"}, exclude_defaults=True)
    notes = "\n".join(f"- {n}" for n in val.notes) or "- none"
    task = (f"Plan the dashboard for these {len(val.approved)} approved metrics.\n\n"
            f"What the data is about:\n{_clip(json.dumps(about, ensure_ascii=False, default=str), CARD_BUDGET)}\n\n"
            f"Approved metrics (definition, caveat from Validate, first result rows):\n"
            f"{_clip(metrics_text, METRICS_BUDGET)}\n\nDashboard notes from Validate:\n{notes}")
    run = agent.run(VISUALIZE_STAGE, task)
    if run.status != "finished" or not isinstance(run.output, DashboardPlan):
        return VisualizeOutcome(run=run)
    saved: dict[str, ChartArgs] = ws.artifacts["charts"]
    charts = sorted((saved[c] for c in dict.fromkeys(run.output.charts) if c in saved), key=lambda c: c.priority)
    ws.artifacts["dashboard_plan"] = run.output
    return VisualizeOutcome(run=run, plan=run.output, charts=charts)

def _key(v: Any) -> tuple:
    if v is None:
        return (2, 0.0, "")
    return (0, float(v), "") if _is_num(v) else (1, 0.0, str(v))

def _display_rows(c: ChartArgs, result: QueryResult) -> list[list[Any]]:
    """Rows in display order; top_n only hides rows (no new numbers are made)."""
    rows = [[jsonable(v) for v in r] for r in result.rows]
    index = {col: i for i, col in enumerate(result.columns)}
    if c.kind in ("line", "area") and c.x in index:
        rows.sort(key=lambda r: _key(r[index[c.x]]))
    elif c.sort == "x" and c.x in index:
        rows.sort(key=lambda r: _key(r[index[c.x]]))
    elif c.sort in ("value_desc", "value_asc") and c.y and c.y[0] in index:
        rows.sort(key=lambda r: _key(r[index[c.y[0]]]), reverse=c.sort == "value_desc")
    if c.top_n and c.kind not in ("line", "area"):
        if c.series and c.x in index:
            keep = list(dict.fromkeys(str(r[index[c.x]]) for r in rows))[: c.top_n]
            rows = [r for r in rows if str(r[index[c.x]]) in keep]
        else:
            rows = rows[: c.top_n]
    return rows

def _filter_spec(box: Sandbox, f: FilterSpec) -> dict[str, Any]:
    col = quote_ident(f.column)          # the gate checked the column exists in base
    spec: dict[str, Any] = {"column": f.column, "kind": f.kind, "label": f.label}
    if f.kind == "date_range":
        low, high = box.trusted_query(f"SELECT CAST(min({col}) AS VARCHAR), CAST(max({col}) AS VARCHAR) FROM {BASE}", 1)[0]
        spec.update(min=low, max=high)
    else:
        spec["options"] = [r[0] for r in box.trusted_query(
            f"SELECT DISTINCT CAST({col} AS VARCHAR) AS v FROM {BASE} WHERE {col} IS NOT NULL ORDER BY v",
            MAX_CATEGORY_OPTIONS)]
    return spec

def build_dashboard(box: Sandbox, plan: DashboardPlan, charts: list[ChartArgs], val: ValidateOutcome) -> dict[str, Any]:
    """The spec the website draws. Every number comes from re-running an approved recipe right now."""
    metrics = {m.name: m for m in val.approved}
    sections: dict[str, list[dict[str, Any]]] = {}
    for c in charts:
        m = metrics.get(c.metric)
        if m is None:
            continue
        verdict = val.verdicts.get(m.name)
        caveat = verdict.note if verdict and verdict.note else ""
        try:
            result = box.run(m.sql, purpose=f"dashboard {c.chart}", tables=(BASE,))
            data = {"columns": result.columns, "rows": _display_rows(c, result), "total_rows": len(result.rows)}
        except QueryError as err:
            data = {"columns": [], "rows": [], "total_rows": 0}
            caveat = f"Could not be computed: {err.message}"
        sections.setdefault(c.section.strip() or "Overview", []).append({
            "id": c.chart, "kind": c.kind, "title": c.title, "subtitle": c.subtitle, "metric": m.name,
            "meaning": m.meaning, "x": c.x, "y": c.y, "series": c.series, "horizontal": c.horizontal,
             "unit": c.unit or (m.unit if len(m.measures) == 1 else ""),
            "assumptions": list(m.assumptions), "data": data}),
    return {"title": plan.title, "subtitle": plan.subtitle, "notes": list(val.notes),
            "filters": [_filter_spec(box, f) for f in plan.filters],
            "sections": [{"name": name, "components": comps} for name, comps in sections.items()]}
