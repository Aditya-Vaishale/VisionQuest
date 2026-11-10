"""
Stage 2, Clean: the AI turns raw text into a typed, tidy table called `clean`.

The AI writes the SQL (types, trimming, reshaping); Python checks the result.
After every save Python reports what was LOST: raw values that became NULL,
raw columns with data that no clean column uses, empty text that should be NULL,
raw rows that went missing, rows that multiplied. `finish` is refused until
every loss is fixed or explained, so nothing disappears silently.
"""
from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from engine.agent import Agent, Budget, RunResult, Stage, Workspace
from engine.agent.tools import Tool, ToolOutcome, failure, register
from engine.discover import FactSheet, profile_table, render_for_llm
from engine.sql import ROW_ID, Sandbox, quote_ident
from engine.sql.results import jsonable

RAW = "raw"
CLEAN = "clean"
REPORT_COLUMNS = 40        # columns listed in the report (columns with problems are always listed)
FACTS_BUDGET = 16_000      # characters of Discover facts given to the AI up front
_WILDCARD = set("*?[")
_NUMERIC = ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "NUMERIC")
_TEMPORAL = ("DATE", "TIME")
MAX_AI_SQL = 20_000          # what the AI itself may write (SQL + repeat templates)
MAX_EXPANDED_SQL = 400_000   # after Python fills in the repeat blocks
_PLACEHOLDER = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")
_BLOCK_NAME = re.compile(r"[a-z][a-z0-9_]{0,40}")

# ----------------------------------------------------------------------------- what the AI sends

class CleanColumn(BaseModel):
    name: str = Field(description="Column in clean; * wildcard allowed for many alike columns, e.g. sensor_*")
    sources: list[str] = Field(default_factory=list, description="raw column(s) it comes from; wildcards allowed")
    type: str = Field(description="Intended type: number, integer, date, timestamp, boolean, text ...")
    how: str = Field(description="How it was made, e.g. 'removed € and thousand dots, comma decimal -> DOUBLE'")

class AcceptedLoss(BaseModel):
    column: str = Field(description="Column name; wildcards allowed, e.g. sensor_*")
    reason: str = Field(description="Why this is right, e.g. 'N/A and - mean unknown'")

class RepeatBlock(BaseModel):
    name: str = Field(description="Placeholder name, lowercase; write {{name}} in sql where the list goes")
    columns: str = Field(description="raw columns to repeat over; wildcards allowed, e.g. sensor_*")
    template: str = Field(description="SQL for ONE column. {col} = its quoted name, {text} = its name as a SQL "
                                      "string. E.g. TRY_CAST(NULLIF(trim({col}), '') AS DOUBLE) AS {col}")
    separator: str = Field(default=", ", description="Text placed between the repeated items")

class SaveCleanArgs(BaseModel):
    sql: str = Field(description="ONE SELECT over raw that builds the clean table. Keep _row unchanged. "
                                 "May contain {{name}} placeholders that repeat blocks fill in.")
    columns: list[CleanColumn] = Field(description="Every output column except _row (wildcards allowed)")
    repeat: list[RepeatBlock] = Field(default_factory=list,
                                      description="Optional: one SQL template applied to many alike columns")

class CleanResult(BaseModel):
    summary: str = Field(description="What was cleaned, in 1-3 sentences")
    columns: list[CleanColumn] = Field(description="Final description of every clean column except _row")
    accepted_losses: list[AcceptedLoss] = Field(default_factory=list,
                                                description="clean columns where raw values rightly became NULL")
    left_out_columns: list[AcceptedLoss] = Field(default_factory=list,
                                                 description="raw columns WITH data that are not used in clean")
    kept_empty_text: list[AcceptedLoss] = Field(default_factory=list,
                                                description="clean text columns where empty text is kept on purpose")
    dropped_rows_reason: str = Field(default="", description="Only if raw rows were left out on purpose")
    reshaped: str = Field(default="", description="Only if rows were multiplied, e.g. months unpivoted")
    open_questions: list[str] = Field(default_factory=list, description="Questions about meaning for the next stage")

# ----------------------------------------------------------------------------- what Python reports

@dataclass
class ColumnCheck:
    name: str
    type: str
    sources: list[str]
    nulls: int
    distinct: int                      # approximate; -1 when not measurable (lists, structs)
    min: Any = None
    max: Any = None
    lost: int = 0                      # raw values (non-blank) that became NULL
    lost_examples: list[list[Any]] = field(default_factory=list)   # [raw value, rows]
    method: str = "none"               # exact (one source) | estimate (several sources) | none
    empty_text: int = 0                # text values that are empty or only spaces (blanks should be NULL)

    @property
    def has_problem(self) -> bool:
        return bool(self.lost or self.empty_text)

@dataclass
class UnusedColumn:
    """A raw column that holds data but feeds no clean column."""
    name: str
    filled: int                        # non-blank cells
    examples: list[list[Any]] = field(default_factory=list)        # [raw value, rows]

@dataclass
class CleanReport:
    raw_rows: int
    clean_rows: int
    clean_row_ids: int                 # distinct _row values in clean
    dropped_rows: int                  # raw rows with no clean row
    dropped_examples: list[int]
    columns: list[ColumnCheck]
    plan_problems: list[str]
    unused_raw: list[UnusedColumn] = field(default_factory=list)

    @property
    def repeat_factor(self) -> float:
        return round(self.clean_rows / self.clean_row_ids, 3) if self.clean_row_ids else 0.0

    def problems(self) -> list[str]:
        out = list(self.plan_problems)
        if self.dropped_rows:
            out.append(f"{self.dropped_rows} raw rows are missing from clean (e.g. _row {self.dropped_examples}).")
        for u in self.unused_raw[:10]:
            examples = ", ".join(f"{v!r} x{n}" for v, n in u.examples)
            out.append(f"raw column {u.name!r} has {u.filled} filled cells but no clean column uses it"
                       + (f" (e.g. {examples})" if examples else ""))
        if len(self.unused_raw) > 10:
            out.append(f"... and {len(self.unused_raw) - 10} more raw columns with data are unused.")
        for c in self.columns:
            if c.lost:
                examples = ", ".join(f"{v!r} x{n}" for v, n in c.lost_examples)
                about = "about " if c.method == "estimate" else ""
                out.append(f"{c.name}: {about}{c.lost} raw values became NULL" + (f" (e.g. {examples})" if examples else ""))
            if c.empty_text:
                out.append(f"{c.name}: {c.empty_text} values are empty text instead of NULL")
        return out

    def to_llm(self) -> str:
        flagged = [c for c in self.columns if c.has_problem]
        rest = [c for c in self.columns if not c.has_problem]
        listed = flagged + rest[: max(0, REPORT_COLUMNS - len(flagged))]
        view: dict[str, Any] = {
            "ok": True, "saved": CLEAN,
            "rows": {"raw": self.raw_rows, "clean": self.clean_rows,
                     "repeat_factor": self.repeat_factor, "raw_rows_missing": self.dropped_rows},
            "problems": self.problems() or ["none: nothing was lost"],
            "columns": [_column_view(c) for c in listed],
        }
        hidden = len(self.columns) - len(listed)
        if hidden:
            view["note"] = f"{hidden} more columns had no problems; use look to inspect any of them."
        return json.dumps(view, ensure_ascii=False, separators=(",", ":"), default=str)

def build_report(box: Sandbox, plan: list[CleanColumn]) -> CleanReport:
    schema = box.schema()
    raw_cols = [c for c, _ in schema[RAW]]
    clean_schema = schema[CLEAN]
    mapping, plan_problems = expand_plan(plan, [c for c, _ in clean_schema], raw_cols)
    row = quote_ident(ROW_ID)
    missing = f"FROM {RAW} AS r WHERE NOT EXISTS (SELECT 1 FROM {CLEAN} AS c WHERE c.{row} = r.{row})"
    stats = _column_stats(box, clean_schema)

    checks: list[ColumnCheck] = []
    for name, ctype in clean_schema:
        if name.casefold() == ROW_ID:
            continue
        sources = mapping.get(name, [])
        nulls, distinct, low, high, empty = stats[name]
        check = ColumnCheck(name=name, type=ctype, sources=sources, nulls=nulls, distinct=distinct,
                            min=low, max=high, empty_text=empty)
        if len(sources) == 1:
            check.method = "exact"
            check.lost, check.lost_examples = _lost_exact(box, name, sources[0])
        elif len(sources) > 1 and nulls:
            check.method = "estimate"
            check.lost = _lost_estimate(box, nulls, sources)
        checks.append(check)

    used = {s for sources in mapping.values() for s in sources}
    unused = [c for c in raw_cols if c.casefold() != ROW_ID and c not in used]
    return CleanReport(
        raw_rows=_scalar(box, f"SELECT count(*) FROM {RAW}"),
        clean_rows=_scalar(box, f"SELECT count(*) FROM {CLEAN}"),
        clean_row_ids=_scalar(box, f"SELECT count(DISTINCT {row}) FROM {CLEAN}"),
        dropped_rows=_scalar(box, f"SELECT count(*) {missing}"),
        dropped_examples=[int(r[0]) for r in box.trusted_query(f"SELECT r.{row} {missing} ORDER BY 1 LIMIT 5")],
        columns=checks,
        plan_problems=plan_problems,
        unused_raw=_unused_raw(box, unused),
    )

def expand_plan(plan: list[CleanColumn], clean_cols: list[str], raw_cols: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Plan entries (wildcards allowed) -> {clean column: [raw sources]}, plus plan problems.
    sensor_* -> sensor_* pairs each column with the raw column of the same name."""
    clean_by_key = {c.casefold(): c for c in clean_cols if c.casefold() != ROW_ID}
    raw_by_key = {c.casefold(): c for c in raw_cols if c.casefold() != ROW_ID}
    mapping: dict[str, list[str]] = {}
    problems: list[str] = []
    for entry in plan:
        targets = _match(entry.name, clean_by_key)
        if not targets:
            problems.append(f"Plan column {entry.name!r} is not in clean.")
            continue
        for target in targets:
            sources: list[str] = []
            for pattern in entry.sources:
                found = _match(pattern, raw_by_key)
                same_name = raw_by_key.get(target.casefold())
                if not found:
                    problems.append(f"Source {pattern!r} is not a raw column.")
                elif _is_pattern(pattern) and same_name in found:
                    sources.append(same_name)
                else:
                    sources.extend(found)
            mapping[target] = list(dict.fromkeys(sources))
    undescribed = [c for c in clean_by_key.values() if c not in mapping]
    if undescribed:
        more = " ..." if len(undescribed) > 10 else ""
        problems.append(f"Describe every clean column in columns; missing: {', '.join(undescribed[:10])}{more}")
    return mapping, list(dict.fromkeys(problems))[:20]

def _match(pattern: str, by_key: dict[str, str]) -> list[str]:
    key = pattern.strip().casefold()
    if _is_pattern(key):
        return [original for k, original in by_key.items() if fnmatch.fnmatchcase(k, key)]
    return [by_key[key]] if key in by_key else []

def _is_pattern(text: str) -> bool:
    return any(ch in _WILDCARD for ch in text)

def _name_matches(pattern: str, name: str) -> bool:
    return fnmatch.fnmatchcase(name.casefold(), pattern.strip().casefold())

def _column_stats(box: Sandbox, schema: list[tuple[str, str]]) -> dict[str, tuple[int, int, Any, Any, int]]:
    """NULLs, approximate distinct, min/max and empty text per clean column, in one query."""
    total = _scalar(box, f"SELECT count(*) FROM {CLEAN}")
    parts: list[str] = []
    layout: list[tuple[str, bool, bool, bool]] = []
    for name, ctype in schema:
        q = quote_ident(name)
        nested, ordered, text = _nested(ctype), _orderable(ctype), _is_text(ctype)
        parts.append(f"count({q})")
        if not nested:
            parts.append(f"approx_count_distinct({q})")
        if ordered:
            parts += [f"CAST(min({q}) AS VARCHAR)", f"CAST(max({q}) AS VARCHAR)"]
        if text:
            parts.append(f"count(*) FILTER (WHERE trim({q}) = '')")
        layout.append((name, nested, ordered, text))
    row = box.trusted_query(f"SELECT {', '.join(parts)} FROM {CLEAN}", max_rows=1)[0]
    out: dict[str, tuple[int, int, Any, Any, int]] = {}
    i = 0
    for name, nested, ordered, text in layout:
        non_null = int(row[i] or 0)
        i += 1
        distinct = -1
        if not nested:
            distinct = int(row[i] or 0)
            i += 1
        low = high = None
        if ordered:
            low, high = row[i], row[i + 1]
            i += 2
        empty = 0
        if text:
            empty = int(row[i] or 0)
            i += 1
        out[name] = (total - non_null, distinct, low, high, empty)
    return out

def _lost_exact(box: Sandbox, column: str, source: str) -> tuple[int, list[list[Any]]]:
    """One source: clean rows whose raw value had text but whose clean value is NULL."""
    c, s, row = quote_ident(column), quote_ident(source), quote_ident(ROW_ID)
    rows = box.trusted_query(
        f"WITH lost AS (SELECT CAST(raw_t.{s} AS VARCHAR) AS v "
        f"FROM {CLEAN} AS clean_t JOIN {RAW} AS raw_t ON clean_t.{row} = raw_t.{row} "
        f"WHERE coalesce(trim(CAST(raw_t.{s} AS VARCHAR)), '') <> '' AND clean_t.{c} IS NULL) "
        f"SELECT v, count(*) AS n, sum(count(*)) OVER () AS total FROM lost GROUP BY v ORDER BY n DESC, v LIMIT 5",
        max_rows=5,
    )
    if not rows:
        return 0, []
    return int(rows[0][2]), [[jsonable(v), int(n)] for v, n, _ in rows]

def _lost_estimate(box: Sandbox, nulls: int, sources: list[str]) -> int:
    """Several sources (unpivot, combine): NULLs beyond the blank raw cells they came from."""
    row = quote_ident(ROW_ID)
    blanks = " + ".join(
        f"(coalesce(trim(CAST(r.{quote_ident(s)} AS VARCHAR)), '') = '')::INTEGER" for s in sources)
    blank_cells = _scalar(box, f"SELECT coalesce(sum({blanks}), 0) FROM {RAW} AS r "
                               f"WHERE EXISTS (SELECT 1 FROM {CLEAN} AS c WHERE c.{row} = r.{row})")
    return max(0, nulls - blank_cells)

def _scalar(box: Sandbox, sql: str) -> int:
    rows = box.trusted_query(sql, max_rows=1)
    return int(rows[0][0] or 0) if rows else 0

def _unused_raw(box: Sandbox, candidates: list[str]) -> list[UnusedColumn]:
    """Raw columns that feed no clean column but still hold data: nothing may vanish silently."""
    if not candidates:
        return []
    filled_sql = ", ".join(
        f"count(*) FILTER (WHERE coalesce(trim(CAST({quote_ident(c)} AS VARCHAR)), '') <> '')" for c in candidates)
    counts = box.trusted_query(f"SELECT {filled_sql} FROM {RAW}", max_rows=1)[0]
    unused: list[UnusedColumn] = []
    for name, filled in zip(candidates, counts):
        if not filled:
            continue                                   # fully blank: leaving it out loses nothing
        examples: list[list[Any]] = []
        if len(unused) < 10:
            q = quote_ident(name)
            rows = box.trusted_query(
                f"SELECT CAST({q} AS VARCHAR) AS v, count(*) AS n FROM {RAW} "
                f"WHERE coalesce(trim(CAST({q} AS VARCHAR)), '') <> '' GROUP BY v ORDER BY n DESC, v LIMIT 3",
                max_rows=3)
            examples = [[jsonable(v), int(n)] for v, n in rows]
        unused.append(UnusedColumn(name=name, filled=int(filled), examples=examples))
    return unused

def _nested(ctype: str) -> bool:
    t = ctype.upper()
    return t.endswith("]") or t.startswith(("STRUCT", "MAP", "UNION"))

def _orderable(ctype: str) -> bool:
    t = ctype.upper()
    return not _nested(ctype) and any(k in t for k in (*_NUMERIC, *_TEMPORAL))

def _is_text(ctype: str) -> bool:
    return not _nested(ctype) and ctype.upper().startswith(("VARCHAR", "TEXT", "STRING"))

def _column_view(c: ColumnCheck) -> dict[str, Any]:
    v: dict[str, Any] = {"name": c.name, "type": c.type, "nulls": c.nulls}
    if c.distinct >= 0:
        v["distinct"] = c.distinct
    if c.min is not None:
        v["range"] = [jsonable(c.min), jsonable(c.max)]
    if c.sources:
        v["from"] = c.sources if len(c.sources) <= 3 else [*c.sources[:3], f"... {len(c.sources) - 3} more"]
    if c.lost:
        v["lost"] = c.lost if c.method == "exact" else f"about {c.lost}"
        if c.lost_examples:
            v["lost_examples"] = c.lost_examples
    if c.empty_text:
        v["empty_text"] = c.empty_text
    return v

# ----------------------------------------------------------------------------- the tool

def expand_repeats(sql: str, blocks: list[RepeatBlock], raw_cols: list[str]) -> tuple[str, dict[str, int]]:
    """Fill each {{name}} with the block's template once per matching raw column. ValueError = reason for the AI."""
    used = set(_PLACEHOLDER.findall(sql))
    if not blocks and not used:
        return sql, {}
    by_key = {c.casefold(): c for c in raw_cols if c.casefold() != ROW_ID}
    names = [b.name.strip() for b in blocks]
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        raise ValueError(f"Repeat block names must be unique: {', '.join(repeated)}.")
    filled: dict[str, str] = {}
    counts: dict[str, int] = {}
    for block, name in zip(blocks, names):
        if not _BLOCK_NAME.fullmatch(name):
            raise ValueError(f"Repeat block name {name!r} must be lowercase letters, digits and _.")
        if name not in used:
            raise ValueError(f"Repeat block {name!r} is not used; write {{{{{name}}}}} in sql.")
        if "{col}" not in block.template and "{text}" not in block.template:
            raise ValueError(f"Repeat block {name!r}: the template must use {{col}} or {{text}}.")
        targets = _match(block.columns, by_key)
        if not targets:
            raise ValueError(f"Repeat block {name!r}: no raw column matches {block.columns!r}.")
        items = [block.template.replace("{text}", "'" + c.replace("'", "''") + "'").replace("{col}", quote_ident(c))
                 for c in targets]
        filled[name] = block.separator.join(items)
        counts[name] = len(targets)
    unknown = sorted(used - set(filled))
    if unknown:
        raise ValueError(f"No repeat block for placeholder(s): {', '.join(unknown)}.")
    return _PLACEHOLDER.sub(lambda m: filled[m.group(1)], sql), counts

def _save_clean(args: SaveCleanArgs, ws: Workspace) -> ToolOutcome:
    box = ws.sandbox
    ws.artifacts.pop("clean_report", None)          # a new table makes the old report invalid
    written = len(args.sql) + sum(len(b.template) for b in args.repeat)
    if written > MAX_AI_SQL:
        return failure("too_long", f"The SQL you wrote is {written:,} characters (limit {MAX_AI_SQL:,}).",
                       "For many alike columns, write the expression once in a repeat block.")
    try:
        sql, expanded = expand_repeats(args.sql, args.repeat, [c for c, _ in box.schema()[RAW]])
    except ValueError as exc:
        return failure("bad_repeat", str(exc),
                       "Each block needs a name, a columns pattern and a template with {col}; "
                       "put {{name}} in sql where the list goes.")
    box.create_table(CLEAN, sql, purpose="save_clean", max_sql_chars=MAX_EXPANDED_SQL)
    if ROW_ID not in {c.casefold() for c, _ in box.schema()[CLEAN]}:
        return failure("missing_row_id", "The clean table has no _row column.",
                       "Select raw._row unchanged, so every clean row links back to its row in the file.")
    report = build_report(box, args.columns)
    ws.artifacts["clean_report"] = report
    ws.artifacts["clean_sql"] = sql                 # exact SQL that built clean (audit, re-runs)
    view = json.loads(report.to_llm())
    if expanded:
        view["repeat_expanded"] = expanded          # e.g. {"sensors": 400}
    return ToolOutcome(json.dumps(view, ensure_ascii=False, separators=(",", ":"), default=str))


SAVE_CLEAN = register(Tool(
    "save_clean",
    "Build (or rebuild) table clean from raw with ONE SELECT that keeps _row, and get Python's report of what "
    "was lost: raw values that became NULL, raw columns with data left unused, empty text, raw rows missing, "
    "rows multiplied.",
    SaveCleanArgs, _save_clean,
))

# ----------------------------------------------------------------------------- the finish gate

def check_clean(result: CleanResult, ws: Workspace) -> list[str]:
    """Refuse finish unless every loss, unused raw column and empty-text column is fixed or explained."""
    report = ws.artifacts.get("clean_report")
    if not isinstance(report, CleanReport):
        return ["Build the clean table with save_clean first (it must keep _row)."]
    schema = ws.sandbox.schema()
    _, problems = expand_plan(result.columns, [c for c, _ in schema[CLEAN]], [c for c, _ in schema[RAW]])

    def explained(items: list[AcceptedLoss], name: str) -> bool:
        return any(item.reason.strip() and _name_matches(item.column, name) for item in items)

    for u in report.unused_raw:
        if not explained(result.left_out_columns, u.name):
            problems.append(f"raw column {u.name!r} has {u.filled} filled cells but is not in clean. "
                            "Use it, or explain it in left_out_columns.")
    for c in report.columns:
        if c.lost and not explained(result.accepted_losses, c.name):
            problems.append(f"{c.name}: {c.lost} raw values became NULL. Fix the SQL, or explain it in accepted_losses.")
        if c.empty_text and not explained(result.kept_empty_text, c.name):
            problems.append(f"{c.name}: {c.empty_text} values are empty text. Use NULLIF(trim(...), '') so blanks "
                            "are NULL, or explain it in kept_empty_text.")
    if report.dropped_rows and not result.dropped_rows_reason.strip():
        problems.append(f"{report.dropped_rows} raw rows are missing from clean. Keep them, or explain in dropped_rows_reason.")
    if report.repeat_factor > 1 and not result.reshaped.strip():
        problems.append(f"Rows were multiplied (repeat factor {report.repeat_factor}). Explain it in reshaped.")
    return problems[:15]

# ----------------------------------------------------------------------------- the stage

CLEAN_INSTRUCTIONS = """Goal: build table clean from raw: the same information, correct types, tidy shape.
Do not decide what the data means yet; make it machine-readable without losing anything.

Steps:
1. Inspect raw. The fact sheet below shows, per column, how many rows each number or date reading fits,
   what failed, patterns, blanks and leading zeros. Use look for more detail on any column.
2. Write ONE SELECT over raw and save it with save_clean. Always keep _row unchanged.
   Give each column the type its values support:
   - numbers: strip currency symbols, %, spaces and thousand separators; respect US vs EU decimal style
     (the readings show which fits); TRY_CAST to DOUBLE, or BIGINT for whole numbers.
   - dates/times: try_strptime with the format the readings show. If day/month order is ambiguous and
     it changes values, ask the user.
   - text: trim padding, and turn empty text into NULL with NULLIF(trim(x), '') so blanks count as missing.
   - keep IDs, codes and values with leading zeros as text.
   - optional: clearer snake_case names; helper flag columns when useful (explain them in "how").
3. Reshape only when the layout hides a variable, e.g. dates or categories spread across column names.
   Use standard UNPIVOT syntax: SELECT ... FROM raw UNPIVOT (value FOR name IN ("Jan-2024", ...)).
   For many alike columns (e.g. hundreds of sensors), do NOT invent shortcut syntax. Use save_clean's
   repeat: write the expression once, e.g. repeat=[{"name": "sensors", "columns": "sensor_*",
   "template": "TRY_CAST(NULLIF(trim({col}), '') AS DOUBLE) AS {col}"}], and put {{sensors}} in the
   SELECT list. It also works inside UNPIVOT ... IN ({{names}}) with the template "{col}".
4. Read Python's report after each save: raw values that became NULL, raw columns with data that no
   clean column uses, empty text, raw rows missing, repeat factor. Fix the SQL and save again until
   nothing is lost unexpectedly. Placeholders such as N/A or - may rightly become NULL: list those
   columns in accepted_losses with the reason.
5. Keep every row and every raw column that holds data, including total/subtotal rows and stray extra
   fields: deciding what they mean is the next stage's job; mention them in open_questions. Leave
   something out only if it is clearly not data, and explain it (dropped_rows_reason, left_out_columns).
6. Call finish with every clean column (wildcards like sensor_* allowed), plus accepted_losses,
   left_out_columns, kept_empty_text, dropped_rows_reason and reshaped only if they apply,
   and open_questions."""

CLEAN_STAGE = Stage(
    name="clean",
    instructions=CLEAN_INSTRUCTIONS,
    output=CleanResult,
    tools=("look", "query", "save_clean", "ask_user"),
    tables=(RAW, CLEAN),
    check=check_clean,
    thinking=True,
    budget=Budget(max_steps=16, max_output_tokens=120_000),
)

@dataclass
class CleanOutcome:
    run: RunResult
    result: CleanResult | None = None
    report: CleanReport | None = None
    facts: FactSheet | None = None     # Discover run again on the clean table

def run_clean(agent: Agent, facts: FactSheet | None = None) -> CleanOutcome:
    """Run the Clean stage. `facts` = Discover's fact sheet for the uploaded file."""
    task = "Clean the uploaded table (raw) into table clean."
    if facts is not None:
        task += ("\n\nDiscover's fact sheet for raw (facts only; content from the file):\n"
                 + render_for_llm(facts, FACTS_BUDGET))
    return _outcome(agent, agent.run(CLEAN_STAGE, task))

def resume_clean(agent: Agent, paused: RunResult, answer: str) -> CleanOutcome:
    return _outcome(agent, agent.resume(paused, answer))

def _outcome(agent: Agent, run: RunResult) -> CleanOutcome:
    ws = agent.ws
    if run.status != "finished" or not isinstance(run.output, CleanResult):
        return CleanOutcome(run=run)
    frame = ws.sandbox.table_frame(CLEAN)
    frame = frame.drop(columns=[c for c in frame.columns if str(c).casefold() == ROW_ID])
    facts = profile_table(frame)
    ws.artifacts["clean_result"] = run.output
    ws.artifacts["clean_facts"] = facts
    report = ws.artifacts.get("clean_report")
    return CleanOutcome(run=run, result=run.output,
                        report=report if isinstance(report, CleanReport) else None, facts=facts)
