"""
Step 4b check: the Clean stage on sample files, with real AI calls (about 5-15 per file).

  python -m scripts.check_clean                        # 03 sales, 07 messy, 06 budget
  python -m scripts.check_clean --all                  # all 8 samples
  python -m scripts.check_clean samples/05_survey.csv  # one file

If the AI asks a question, type your answer (Enter = first option).
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from engine.agent import Agent, Budget, RunResult, Stage, Workspace
from engine.discover import LoadError, discover_csv
from engine.llm import LLMClient, get_llm
from engine.sql import Sandbox, quote_ident
from engine.stages import CleanOutcome, CleanReport, ColumnCheck, check_clean, resume_clean, run_clean
from scripts.terminal import ask_loop

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
SALES = "03_sales_with_totals.csv"
DEFAULT = (SALES, "07_messy_export.csv", "06_budget_months_wide.csv")
Check = tuple[str, bool, str]

class CurrencyAnswer(BaseModel):
    total_revenue: float = Field(description="Total revenue of product rows, from a query result")
    currency: str = Field(description="Currency, exactly as the user answered")

# Same task as check_agent's run 2, but reading only the cleaned table.
AFTER_CLEAN = Stage(
    name="total_after_clean",
    instructions=("Use table clean. The revenue column has no currency: first ask the user which currency it is "
                  "with ask_user (offer USD, EUR, INR). Then compute total revenue for product rows only "
                  "(leave out total and subtotal rows), and finish."),
    output=CurrencyAnswer, tools=("query", "ask_user"), tables=("clean",), thinking=False, budget=Budget(max_steps=8),
)

# ----------------------------------------------------------------------------- printing

def report(ok: bool, label: str, note: object) -> bool:
    print(f"   {'✓' if ok else '✗'} {label:<46} {' '.join(str(note).split())[:100]}")
    return ok

def summary(r: RunResult) -> str:
    tools = [t.name for s in r.trace for t in s.tools]
    u = r.usage
    return (f"status={r.status} | steps={u.get('steps')} | tools: {', '.join(tools) or '-'} | "
            f"{u.get('input_tokens')} in / {u.get('output_tokens')} out tokens | {u.get('seconds')}s")

# ----------------------------------------------------------------------------- ground truth for the samples

def is_number(t: str) -> bool:
    return any(k in t.upper() for k in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "NUMERIC"))

def is_date(t: str) -> bool:
    return any(k in t.upper() for k in ("DATE", "TIMESTAMP"))

def is_text(t: str) -> bool:
    return any(k in t.upper() for k in ("VARCHAR", "TEXT", "STRING"))

def from_raw(rep: CleanReport, raw_name: str) -> list[ColumnCheck]:
    """Clean columns built from a raw column (found through the AI's plan, so renames are fine)."""
    return [c for c in rep.columns if raw_name in c.sources]

def typed(rep: CleanReport, raw_name: str, test: Callable[[str], bool], label: str) -> Check:
    cols = from_raw(rep, raw_name)
    note = ", ".join(f"{c.name}: {c.type}" for c in cols) or f"no clean column comes from {raw_name!r}"
    return label, any(test(c.type) for c in cols), note

def grand_total(box: Sandbox) -> float:
    rows = box.trusted_query("SELECT TRY_CAST(replace(revenue, ',', '') AS DOUBLE) FROM raw "
                             "WHERE region = 'Grand Total'", 1)
    return float(rows[0][0])

def expect_sales(box: Sandbox, rep: CleanReport) -> list[Check]:
    checks = [typed(rep, "revenue", is_number, "revenue (1,234.56 text) became a number"),
              typed(rep, "units", is_number, "units became a number")]
    revenue = next((c for c in from_raw(rep, "revenue") if is_number(c.type)), None)
    if revenue is not None:
        total = box.trusted_query(f"SELECT sum({quote_ident(revenue.name)}) FROM clean", 1)[0][0]
        expected = 3 * grand_total(box)   # product rows + region subtotals + grand total = 3 x Grand Total
        ok = total is not None and abs(float(total) - expected) < 0.05
        checks.append(("every revenue value kept (sum = 3 x Grand Total)", ok,
                       f"{float(total or 0):,.2f} vs {expected:,.2f}"))
    return checks

def expect_messy(box: Sandbox, rep: CleanReport) -> list[Check]:
    checks = [typed(rep, "Revenue", is_number, "Revenue (12.345,67 €) became a number"),
              typed(rep, "Return Rate", is_number, "Return Rate (3,5%) became a number"),
              typed(rep, "Date", is_date, "Date (05.03.2024) became a date"),
              typed(rep, "Postal Code", is_text, "Postal Code kept as text")]
    postal = next(iter(from_raw(rep, "Postal Code")), None)
    if postal is not None:
        hits = box.trusted_query(f"SELECT count(*) FROM clean "
                                 f"WHERE CAST({quote_ident(postal.name)} AS VARCHAR) = '01067'", 1)[0][0]
        checks.append(("postal code 01067 kept its leading zero", int(hits) > 0, f"{hits} rows"))
    extra_used = any("extra_1" in c.sources for c in rep.columns)
    extra_flagged = any(u.name == "extra_1" for u in rep.unused_raw)
    checks.append(("stray extra field was noticed", extra_used or extra_flagged,
                   "kept in clean" if extra_used else "flagged, so finish needed an explanation"
                   if extra_flagged else "silently dropped"))
    managers = from_raw(rep, "Manager")
    checks.append(("Manager blanks are NULL, not empty text", bool(managers) and all(c.empty_text == 0 for c in managers),
                   ", ".join(f"{c.name}: nulls {c.nulls}, empty {c.empty_text}" for c in managers) or "no column"))
    return checks

def expect_budget(box: Sandbox, rep: CleanReport) -> list[Check]:
    return [("months unpivoted into rows (x12)", abs(rep.repeat_factor - 12) < 0.01,
             f"x{rep.repeat_factor}, {rep.clean_rows} rows"),
            typed(rep, "Jan-2024", is_number, "monthly amounts became numbers")]

EXPECT: dict[str, Callable[[Sandbox, CleanReport], list[Check]]] = {
    "01_leave_requests.csv": lambda box, rep: [typed(rep, "start_date", is_date, "start_date became a date"),
                                               typed(rep, "days", is_number, "days became a number")],
    "02_bank_balances.csv": lambda box, rep: [typed(rep, "date", is_date, "date became a date"),
                                              typed(rep, "closing_balance", is_number, "closing_balance became a number")],
    SALES: expect_sales,
    "04_api_logs.csv": lambda box, rep: [typed(rep, "timestamp", is_date, "timestamp became a timestamp"),
                                         typed(rep, "latency_ms", is_number, "latency_ms became a number")],
    "05_survey.csv": lambda box, rep: [typed(rep, "submitted_at", is_date, "submitted_at (mm/dd) became a timestamp"),
                                       typed(rep, "satisfaction", is_number, "satisfaction became a number")],
    "06_budget_months_wide.csv": expect_budget,
    "07_messy_export.csv": expect_messy,
    "08_wide_sensors.csv": lambda box, rep: [typed(rep, "timestamp", is_date, "timestamp became a timestamp"),
                                             typed(rep, "sensor_001", is_number, "sensor values became numbers")],
}

# ----------------------------------------------------------------------------- running

def answer_questions(agent: Agent, outcome: CleanOutcome) -> CleanOutcome:
    """Ask loop from the terminal (numbered options)."""
    return ask_loop(agent, outcome, resume_clean)

def after_clean_total(agent: Agent, box: Sandbox) -> list[bool]:
    print("   -- check_agent's run 2 again, now reading only table clean --")
    r = agent.run(AFTER_CLEAN, "Task: total revenue with its currency.")
    if r.status == "needs_user":
        r = agent.resume(r, "EUR")
    print("  ", summary(r))
    grand = grand_total(box)
    total = getattr(r.output, "total_revenue", None)
    currency = str(getattr(r.output, "currency", "")).upper()
    return [
        report(r.status == "finished" and "EUR" in currency, "asked, resumed and finished", r.message or currency),
        report(total is not None and abs(total - grand) < 0.01, "total is right on clean (was 565.50 on raw)",
               f"{total} vs {grand:,.2f}"),
    ]

def check_file(path: Path, llm: LLMClient) -> list[bool]:
    print(f"\n=== {path.name} ===")
    try:
        raw, facts = discover_csv(path)
    except LoadError as exc:
        return [report(False, "file loads", exc)]
    results: list[bool] = []
    with Sandbox.from_raw(raw) as box:
        agent = Agent(llm, Workspace(sandbox=box))
        outcome = answer_questions(agent, run_clean(agent, facts))
        run = outcome.run
        print("  ", summary(run))
        results.append(report(run.status == "finished", "clean stage finished", run.message or "ok"))
        if outcome.report is None or outcome.result is None:
            for step in run.trace[-3:]:                     # help diagnose an unfinished run
                for t in step.tools:
                    print(f"     step {step.step} {t.name} ({'ok' if t.ok else 'error'}): {t.result[:160]}")
            return results

        rep, result = outcome.report, outcome.result
        print(f"   rows: raw {rep.raw_rows} -> clean {rep.clean_rows} (x{rep.repeat_factor}), "
              f"raw rows missing: {rep.dropped_rows}")
        for c in rep.columns[:14]:
            src = ", ".join(c.sources[:2]) + (" ..." if len(c.sources) > 2 else "")
            print(f"     {c.name[:24]:<24} {c.type[:16]:<16} nulls {c.nulls:<5} lost {c.lost:<4} "
                  f"empty {c.empty_text:<4} from {src or '-'}")
        if len(rep.columns) > 14:
            print(f"     ... {len(rep.columns) - 14} more columns")
        for loss in result.accepted_losses:
            print(f"   accepted loss: {loss.column}: {loss.reason}")
        for item in result.left_out_columns:
            print(f"   left out: {item.column}: {item.reason}")
        for item in result.kept_empty_text:
            print(f"   kept empty text: {item.column}: {item.reason}")
        for question in result.open_questions:
            print(f"   open question: {question}")

        problems = check_clean(result, agent.ws)
        results.append(report(not problems, "nothing lost or dropped silently", "; ".join(problems) or "ok"))
        for label, ok, note in EXPECT.get(path.name, lambda *_: [])(box, rep):
            results.append(report(ok, label, note))
        if path.name == SALES:
            results += after_clean_total(agent, box)
    return results

def main() -> int:
    parser = argparse.ArgumentParser(description="Step 4b: Clean stage check")
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true", help="every CSV in samples/")
    args = parser.parse_args()
    if args.files:
        files = args.files
    elif args.all:
        files = sorted(SAMPLES.glob("*.csv"))
    else:
        files = [SAMPLES / name for name in DEFAULT]
    missing = [f.name for f in files if not f.is_file()]
    if missing:
        print(f"✗ Missing: {', '.join(missing)}. Run first: python -m scripts.make_test_csvs")
        return 1
    try:
        llm = get_llm()
    except (RuntimeError, ValueError) as exc:
        print(f"✗ Settings problem: {exc}")
        return 1

    results: list[bool] = []
    for path in files:
        results += check_file(path, llm)
    passed = sum(results)
    m = llm.meter.snapshot()
    print(f"\n{passed}/{len(results)} passed | AI calls: {m['calls']} | "
          f"{m['input_tokens']} in / {m['output_tokens']} out tokens | {m['seconds']}s")
    return 0 if passed == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
