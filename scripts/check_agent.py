"""
Step 4a check: the loop engine with real AI calls (uses about 10-25 calls of your NVIDIA quota).

  1. Explore: look -> query -> save recipe -> finish   (does it avoid the subtotal trap?)
  2. Ask loop: the run pauses with a question, then resumes with a scripted answer
  3. Budget: a 2-step budget stops the run cleanly

Run from the project folder:  python -m scripts.check_agent
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field

from engine.agent import Agent, Budget, RunResult, Stage, Workspace
from engine.discover import load_csv
from engine.llm import get_llm
from engine.sql import Sandbox
from engine.agent.loop import FINISH_GRACE_STEPS

SALES = Path(__file__).resolve().parent.parent / "samples" / "03_sales_with_totals.csv"

class RevenueAnswer(BaseModel):
    total_revenue: float = Field(description="Total revenue, taken from a query result")
    recipe: str = Field(description="Name of the saved recipe that computes it")
    excluded_rows: str = Field(description="Which rows were left out and why, or 'none'")
    assumptions: list[str] = Field(default_factory=list)

class CurrencyAnswer(BaseModel):
    total_revenue: float = Field(description="Total revenue of product rows, from a query result")
    currency: str = Field(description="Currency, exactly as the user answered")

EXPLORE = Stage(
    name="explore",
    instructions=("Find the total revenue across all products in table raw. Check what the rows represent "
                  "before adding anything up. Save the calculation with save_recipe as total_revenue, then finish."),
    output=RevenueAnswer, tools=("look", "query", "save_recipe"), thinking=True, budget=Budget(max_steps=12),
)
ASK = Stage(
    name="ask_demo",
    instructions=("The revenue column has no currency. First ask the user which currency it is with ask_user "
                  "(offer USD, EUR, INR). Then compute total revenue for product rows only, and finish."),
    output=CurrencyAnswer, tools=("query", "ask_user"), thinking=False, budget=Budget(max_steps=8),
)
TINY = Stage(
    name="tiny_budget",
    instructions=("Compute units and revenue per region and per product, check them against the subtotal rows, "
                  "save each as a recipe, then finish."),
    output=RevenueAnswer, tools=("look", "query", "save_recipe"), thinking=False, budget=Budget(max_steps=2),
)

def report(ok: bool, label: str, note: str) -> bool:
    print(f"   {'✓' if ok else '✗'} {label:<38} {' '.join(str(note).split())[:110]}")
    return ok

def summary(r: RunResult) -> str:
    tools = [t.name for s in r.trace for t in s.tools]
    u = r.usage
    return (f"status={r.status} | steps={u.get('steps')} | tools: {', '.join(tools) or '-'} | "
            f"{u.get('input_tokens')} in / {u.get('output_tokens')} out tokens | {u.get('seconds')}s")

def first_number(rows: list[tuple]) -> float | None:
    for cell in rows[0] if rows else ():
        if isinstance(cell, (int, float, Decimal)) and not isinstance(cell, bool):
            return float(cell)
    return None

def main() -> int:
    if not SALES.is_file():
        print("✗ Sample files not found. Run first: python -m scripts.make_test_csvs")
        return 1
    try:
        llm = get_llm()
    except (RuntimeError, ValueError) as exc:
        print(f"✗ Settings problem: {exc}")
        return 1
    results: list[bool] = []

    with Sandbox.from_raw(load_csv(SALES)) as box:
        grand = first_number(box.run("SELECT TRY_CAST(replace(revenue, ',', '') AS DOUBLE) FROM raw "
                                     "WHERE region = 'Grand Total'").rows)
        ws = Workspace(sandbox=box)
        agent = Agent(llm, ws)

        print("1) Explore: look -> query -> save recipe -> finish")
        r1 = agent.run(EXPLORE, "Task: what is the total revenue?")
        print("  ", summary(r1))
        results.append(report(r1.status == "finished", "loop reached finish", r1.message or "ok"))
        recipe = ws.recipes.get("total_revenue")
        results.append(report(recipe is not None, "recipe saved", recipe.meaning if recipe else "missing"))
        value = first_number(box.run(recipe.sql).rows) if recipe else None
        results.append(report(value is not None and grand is not None and abs(value - grand) < 0.01,
                              "recipe gives the right total", f"{value} vs file's Grand Total {grand}"))
        claimed = getattr(r1.output, "total_revenue", None)
        results.append(report(claimed is not None and value is not None and abs(claimed - value) < 0.01,
                              "finish number matches the recipe", claimed))
        if r1.output:
            print("   output:", r1.output.model_dump_json())

        print("\n2) Ask loop: pause for the user, then resume")
        r2 = agent.run(ASK, "Task: total revenue with its currency.")
        print("  ", summary(r2))
        asked = r2.status == "needs_user" and r2.question is not None
        results.append(report(asked, "run paused with a question", r2.question.question if r2.question else r2.status))
        if asked:
            print("   options:", r2.question.options, "| answering: EUR")
            r2 = agent.resume(r2, "EUR")
            print("  ", summary(r2))
            currency = str(getattr(r2.output, "currency", "")).upper()
            results.append(report(r2.status == "finished" and "EUR" in currency, "resumed with the answer and finished",
                                  r2.output.model_dump_json() if r2.output else r2.message))
            total = getattr(r2.output, "total_revenue", None)
            results.append(report(total is not None and grand is not None and abs(total - grand) < 0.01,
                                  "total is right, not just the currency", f"{total} vs file's Grand Total {grand}"))

        print("\n3) Budget: 2 steps only")
        r3 = agent.run(TINY, "Task: full regional breakdown.")
        print("  ", summary(r3))
        steps = int(r3.usage.get("steps", 0))
        results.append(report(r3.status in {"finished", "budget_exceeded"} and steps <= 2 + FINISH_GRACE_STEPS,
                              "stopped cleanly within budget", f"{r3.status}, {steps} steps. {r3.message}"))

        print("\nAudit trail of run 1:")
        for s in r1.trace:
            tools = "; ".join(f"{t.name}({'ok' if t.ok else 'error'})" for t in s.tools) or "-"
            print(f"   step {s.step}: {s.seconds}s, {s.output_tokens} out tokens, "
                  f"{s.thinking_chars} thinking chars | {tools}")
        print(f"SQL audit log: {len(box.log)} queries")

    passed = sum(results)
    m = llm.meter.snapshot()
    print(f"\n{passed}/{len(results)} passed | AI calls: {m['calls']} | "
          f"{m['input_tokens']} in / {m['output_tokens']} out tokens | {m['seconds']}s")
    return 0 if passed == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
