"""
Step 4d check: Discover -> Clean -> Reason -> Calculate, with real AI calls (about 25-45 per file).

  python -m scripts.check_calculate                                # 02 bank, 03 sales, 05 survey
  python -m scripts.check_calculate --all                          # all 8 samples (long)
  python -m scripts.check_calculate samples/01_leave_requests.csv  # one file

If the AI asks a question, type a number or your own answer.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from engine.agent import RunResult
from engine.discover import LoadError, discover_csv
from engine.llm import LLMClient, get_llm
from engine.pipeline import STAGES, Pipeline, StageCache
from engine.sql import Sandbox, quote_ident
from engine.sql.results import jsonable
from engine.stages import CalculateOutcome, CleanReport, Metric, check_calculate
from scripts.terminal import pick_answer

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
DEFAULT = ("02_bank_balances.csv", "03_sales_with_totals.csv", "05_survey.csv")
Check = tuple[str, bool, str]

# ----------------------------------------------------------------------------- printing

def report(ok: bool, label: str, note: object) -> bool:
    print(f"   {'✓' if ok else '✗'} {label:<44} {' '.join(str(note).split())[:100]}")
    return ok

def summary(r: RunResult) -> str:
    u = r.usage
    return (f"status={r.status} | steps={u.get('steps')} | {u.get('input_tokens')} in / "
            f"{u.get('output_tokens')} out tokens | {u.get('seconds')}s")

def one_line(text: object, limit: int = 120) -> str:
    return " ".join(str(text).split())[:limit]

def show(calc: CalculateOutcome, questions: list[str]) -> None:
    for m in calc.metrics:
        first = m.preview[0] if m.preview else []
        rows = "10+ rows" if len(m.preview) >= 10 else f"{len(m.preview)} rows"
        print(f"     {m.name[:30]:<30} {m.shape:<21} {m.unit[:8]:<8} {rows:<9} e.g. {one_line(first, 60)}")
    for d in calc.result.dropped if calc.result else []:
        q = questions[d.question - 1] if 1 <= d.question <= len(questions) else "?"
        print(f"   dropped Q{d.question}: {one_line(q, 60)} -> {one_line(d.reason, 70)}")
    for note in calc.result.notes if calc.result else []:
        print(f"   note: {one_line(note)}")

# ----------------------------------------------------------------------------- helpers

def clean_name(rep: CleanReport, raw_name: str) -> str:
    best = [c for c in rep.columns if c.sources == [raw_name]] or [c for c in rep.columns if raw_name in c.sources]
    return best[0].name if best else raw_name

def rerun(box: Sandbox, m: Metric) -> list[list[Any]]:
    return [[jsonable(v) for v in row] for row in box.run(m.sql, purpose=f"recheck {m.name}", tables=("base",)).rows[:10]]

def same_rows(a: list[list[Any]], b: list[list[Any]]) -> bool:
    """Equal rows; numbers may differ by tiny float rounding only."""
    if len(a) != len(b) or any(len(x) != len(y) for x, y in zip(a, b)):
        return False
    for x, y in ((x, y) for ra, rb in zip(a, b) for x, y in zip(ra, rb)):
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool):
            if abs(x - y) > 1e-6 * max(1.0, abs(x), abs(y)):
                return False
        elif x != y:
            return False
    return True

def numbers(box: Sandbox, metrics: list[Metric]) -> list[float]:
    """Every number in every metric's result, recomputed by Python from the saved SQL."""
    out: list[float] = []
    for m in metrics:
        for row in box.run(m.sql, purpose=f"recheck {m.name}", tables=("base",)).rows:
            out += [float(v) for v in row if isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)]
    return out

def near(values: list[float], target: float, tol: float = 0.01) -> bool:
    return any(abs(v - target) <= tol for v in values)

def scalar(box: Sandbox, sql: str) -> float:
    return float(box.trusted_query(sql, 1)[0][0] or 0)

# ----------------------------------------------------------------------------- ground truth for the samples

def expect_bank(box: Sandbox, metrics: list[Metric], rep: CleanReport) -> list[Check]:
    bal, day = quote_ident(clean_name(rep, "closing_balance")), quote_ident(clean_name(rep, "date"))
    vals = numbers(box, metrics)
    wrong = scalar(box, f"SELECT sum({bal}) FROM clean")
    latest = [float(r[0]) for r in box.trusted_query(
        f"SELECT {bal} FROM clean WHERE {day} = (SELECT max({day}) FROM clean)", 50)]
    found = near(vals, sum(latest), 0.5) or all(near(vals, v) for v in latest)
    return [("balances never summed across days", not near(vals, wrong, 0.5), f"wrong total would be {wrong:,.2f}"),
            ("current balance found (latest day)", found, f"total {sum(latest):,.2f} over {len(latest)} accounts")]

def expect_sales(box: Sandbox, metrics: list[Metric], rep: CleanReport) -> list[Check]:
    grand = scalar(box, "SELECT TRY_CAST(replace(revenue, ',', '') AS DOUBLE) FROM raw WHERE region = 'Grand Total'")
    vals = numbers(box, metrics)
    return [("total revenue = file's Grand Total", near(vals, grand), f"{grand:,.2f}"),
            ("no double counting (2x or 3x total)", not (near(vals, 2 * grand) or near(vals, 3 * grand)),
             f"{2 * grand:,.2f} and {3 * grand:,.2f} must not appear")]

def expect_survey(box: Sandbox, metrics: list[Metric], rep: CleanReport) -> list[Check]:
    gender = clean_name(rep, "gender")
    averaged = [m.name for m in metrics
                if re.search(rf"\b(avg|mean)\s*\([^)]*\b{re.escape(gender)}\b", m.sql, re.IGNORECASE)]
    mean = scalar(box, f"SELECT avg({quote_ident(clean_name(rep, 'satisfaction'))}) FROM clean")
    return [("gender codes never averaged", not averaged, ", ".join(averaged) or "ok"),
            ("average satisfaction is correct", near(numbers(box, metrics), mean), f"{mean:.3f}")]

def expect_leave(box: Sandbox, metrics: list[Metric], rep: CleanReport) -> list[Check]:
    trends = [m.name for m in metrics if m.shape in ("by_time", "by_time_and_category")]
    return [("a trend over time exists", bool(trends), ", ".join(trends) or "none")]

EXPECT: dict[str, Callable[[Sandbox, list[Metric], CleanReport], list[Check]]] = {
    "01_leave_requests.csv": expect_leave,
    "02_bank_balances.csv": expect_bank,
    "03_sales_with_totals.csv": expect_sales,
    "05_survey.csv": expect_survey,
}

# ----------------------------------------------------------------------------- running

def check_file(path: Path, llm: LLMClient, cache: StageCache | None, fresh_from: str | None) -> list[bool]:
    print(f"\n=== {path.name} ===")
    try:
        raw, facts = discover_csv(path)
    except LoadError as exc:
        return [report(False, "file loads", exc)]
    results: list[bool] = []
    with Pipeline(llm, raw, facts, path.read_bytes(), answer=pick_answer, cache=cache, fresh_from=fresh_from) as pipe:
        box = pipe.box
        cleaned = pipe.clean()
        print("   clean:     ", summary(cleaned.run))
        results.append(report(cleaned.result is not None, "clean finished", cleaned.run.message or "ok"))
        if cleaned.result is None or cleaned.facts is None or cleaned.report is None:
            return results

        reasoned = pipe.reason(cleaned)
        print("   reason:    ", summary(reasoned.run))
        results.append(report(reasoned.card is not None, "reason finished", reasoned.run.message or "ok"))
        if reasoned.card is None:
            return results

        calc = pipe.calculate(reasoned.card)
        print("   calculate: ", summary(calc.run))
        results.append(report(calc.result is not None, "calculate finished", calc.run.message or "ok"))
        if calc.result is None:
            for step in calc.run.trace[-3:]:                # help diagnose an unfinished run
                for t in step.tools:
                    print(f"     step {step.step} {t.name} ({'ok' if t.ok else 'error'}): {t.result[:160]}")
            return results

        show(calc, reasoned.card.questions)
        problems = check_calculate(calc.result, pipe.agent.ws)
        results.append(report(not problems, "metrics pass Python's checks", "; ".join(problems) or "ok"))
        unstable = [m.name for m in calc.metrics if not same_rows(rerun(box, m), m.preview)]
        results.append(report(not unstable, "every metric re-runs to the same result", ", ".join(unstable) or "ok"))
        singles = [m.name for m in calc.metrics if m.shape == "single_value"]
        results.append(report(bool(singles), "at least one headline number", ", ".join(singles) or "none"))
        for label, ok, note in EXPECT.get(path.name, lambda *_: [])(box, calc.metrics, cleaned.report):
            results.append(report(ok, label, note))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 4d: Calculate stage check")
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true", help="every CSV in samples/")
    parser.add_argument("--fresh", choices=STAGES, help="re-run this stage and the ones after it")
    parser.add_argument("--no-cache", action="store_true", help="neither reuse nor save stage outputs")
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

    cache = None if args.no_cache else StageCache()
    results: list[bool] = []
    for path in files:
        results += check_file(path, llm, cache, args.fresh)
    passed = sum(results)
    m = llm.meter.snapshot()
    print(f"\n{passed}/{len(results)} passed | AI calls: {m['calls']} | "
          f"{m['input_tokens']} in / {m['output_tokens']} out tokens | {m['seconds']}s")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
