"""
The AI's tools: abilities, not answers. Look, Query, Save recipe, Ask you.
Stages can add their own (e.g. save_clean) with register(); "finish" is added per stage.

Every tool returns text for the AI. Errors come back as text too, so the AI
can fix its own mistake (the Fix loop) instead of the run crashing.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from engine.agent.recipes import Recipe, RecipeBook
from engine.discover import profile_column
from engine.discover.render import render_column
from engine.sql import QueryError, Sandbox
from engine.sql.results import jsonable

@dataclass
class Workspace:
    """What the tools work on: the locked SQL room, recipes, the user's answers, stage outputs."""
    sandbox: Sandbox
    recipes: RecipeBook = field(default_factory=RecipeBook)
    answers: list[dict[str, str]] = field(default_factory=list)   # [{"question": ..., "answer": ...}]
    artifacts: dict[str, Any] = field(default_factory=dict)       # stage outputs, e.g. the clean report
    tables: tuple[str, ...] | None = None                         # tables the current stage may read; None = all

    def can_read(self, table: str) -> bool:
        return self.tables is None or str(table).strip().lower() in {t.lower() for t in self.tables}

class Question(BaseModel):
    question: str = Field(description="One short question for the user")
    options: list[str] = Field(default_factory=list, description="2-5 likely answers, if they exist")
    why_it_matters: str = Field(default="", description="How the answer changes the result, with numbers if known")

@dataclass(frozen=True)
class ToolOutcome:
    content: str                    # what the AI reads
    ok: bool = True
    pause: Question | None = None   # set by ask_user: the run waits for the user

class LookArgs(BaseModel):
    table: str = Field(description="Table name, e.g. raw")
    column: str | None = Field(default=None, description="Column to profile in detail; omit to list the table's columns")

class QueryArgs(BaseModel):
    sql: str = Field(description="One read-only DuckDB SELECT (WITH ... SELECT is fine)")
    purpose: str = Field(default="", description="Why you run this query, in a few words")

class SaveRecipeArgs(BaseModel):
    name: str = Field(description="snake_case name, e.g. total_leave_days")
    meaning: str = Field(description="What the number means in plain words, including what is counted and excluded")
    sql: str = Field(description="One read-only SELECT that computes it")
    assumptions: list[str] = Field(default_factory=list, description="Assumptions behind this definition")

@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    handler: Callable[[Any, Workspace], ToolOutcome]

    def spec(self) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": json_schema(self.args)}}

# ----------------------------------------------------------------------------- handlers

def _look(args: LookArgs, ws: Workspace) -> ToolOutcome:
    if not ws.can_read(args.table):
        return failure("not_allowed", f"Table {args.table!r} is not available in this stage.",
                       f"Available tables: {', '.join(ws.tables or ())}.")
    if args.column is None or not args.column.strip():
        return ToolOutcome(json.dumps(ws.sandbox.describe(args.table), ensure_ascii=False))
    name, position, series = ws.sandbox.column_values(args.table, args.column)
    view = {"ok": True, "table": args.table, "rows": len(series),
            "column": render_column(profile_column(series, position, name=name))}
    return ToolOutcome(json.dumps(view, ensure_ascii=False, separators=(",", ":")))

def _query(args: QueryArgs, ws: Workspace) -> ToolOutcome:
    result = ws.sandbox.run(args.sql, purpose=args.purpose or "query", tables=ws.tables)
    return ToolOutcome(result.to_llm())

def _save_recipe(args: SaveRecipeArgs, ws: Workspace) -> ToolOutcome:
    name = args.name.strip()
    if not RecipeBook.valid_name(name):
        return failure("invalid_name", f"Invalid recipe name {name!r}.",
                       "Use snake_case: lowercase letters, digits and _ (max 60 characters).")
    if not args.meaning.strip():
        return failure("missing_meaning", "Describe what the number means.")
    result = ws.sandbox.run(args.sql, purpose=f"recipe {name}", max_rows=50, tables=ws.tables)  # proves the SQL works
    if not result.rows:
        return failure("empty_result", "The recipe's query returned no rows.",
                       "Check the filters; a metric should return at least one row.")
    replaced = name in ws.recipes
    saved = ws.recipes.save(Recipe(
        name=name,
        meaning=args.meaning.strip(),
        sql=result.sql,
        assumptions=[a.strip() for a in args.assumptions if a.strip()],
        columns=result.columns,
        preview=[[jsonable(v) for v in row] for row in result.rows[:10]],
    ))
    return ToolOutcome(json.dumps({
        "ok": True, "saved": saved.name, "version": saved.version, "replaced": replaced,
        "result_columns": saved.columns, "preview": saved.preview, "more_rows": result.truncated,
    }, ensure_ascii=False))

def _ask(args: Question, ws: Workspace) -> ToolOutcome:
    question = args.question.strip()
    if not question:
        return failure("missing_question", "The question is empty.")
    options = [o.strip() for o in args.options if o.strip()][:5]
    return ToolOutcome("Waiting for the user's answer.",
                       pause=Question(question=question, options=options, why_it_matters=args.why_it_matters.strip()))

TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool("look", "See a table's columns and types, or detailed facts about one column "
                 "(blanks, patterns, number and date readings).", LookArgs, _look),
    Tool("query", "Run one read-only DuckDB SELECT on the loaded tables and get the rows back (up to 200).",
         QueryArgs, _query),
    Tool("save_recipe", "Save a metric definition: name, meaning, SQL, assumptions. The SQL is run to prove it "
                        "works; values are always recomputed from it later.", SaveRecipeArgs, _save_recipe),
    Tool("ask_user", "Ask the user ONE short question, only when the meaning is unclear and the answer changes "
                     "results materially. The run pauses until they answer.", Question, _ask),
)}

def register(tool: Tool) -> Tool:
    """Add a stage-specific tool (e.g. save_clean) to the toolbox."""
    TOOLS[tool.name] = tool
    return tool

# ----------------------------------------------------------------------------- helpers

def call_tool(tool: Tool, raw_args: dict[str, Any], ws: Workspace) -> ToolOutcome:
    """Validate arguments, run the tool, and turn every failure into text the AI can act on."""
    try:
        args = tool.args.model_validate(raw_args)
    except ValidationError as exc:
        return failure("bad_arguments", f"Arguments for {tool.name} are invalid: {validation_text(exc)}",
                       "Send arguments that match the tool's schema.")
    try:
        return tool.handler(args, ws)
    except QueryError as err:
        return ToolOutcome(err.to_llm(), ok=False)
    except Exception as exc:  # a tool bug must not crash the run
        return failure("tool_failed", f"{tool.name} failed: {type(exc).__name__}: {str(exc)[:300]}")

def error_text(kind: str, message: str, hint: str = "") -> str:
    return QueryError(kind, message, hint).to_llm()

def failure(kind: str, message: str, hint: str = "") -> ToolOutcome:
    return ToolOutcome(error_text(kind, message, hint), ok=False)

def validation_text(exc: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}" for e in exc.errors()[:8]]
    return "; ".join(parts)

def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic model -> plain JSON schema with references inlined (simpler for the AI to follow)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, list):
            return [inline(v) for v in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = copy.deepcopy(defs[node["$ref"].rsplit("/", 1)[-1]])
            return inline({**target, **{k: v for k, v in node.items() if k != "$ref"}})
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "title":
                continue                                    # schema metadata, not needed
            if key == "properties" and isinstance(value, dict):
                out[key] = {name: inline(sub) for name, sub in value.items()}  # field names kept as-is
            else:
                out[key] = inline(value)
        return out

    return inline(schema)
