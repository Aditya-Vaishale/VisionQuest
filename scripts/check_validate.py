"""
Step 5 check: Validate, with a fire drill.

Clean, Reason and Calculate are reused from saved outputs when possible. Then one deliberately wrong
metric is slipped in among the real ones, and Validate must not approve it as it is.

  python -m scripts.check_validate                                # 02 bank, 03 sales, 05 survey
  python -m scripts.check_validate samples/03_sales_with_totals.csv
  python -m scripts.check_validate --fresh calculate              # re-run Calculate first

Validate itself uses about 10-40 AI calls per file. Optional: set REVIEWER_LLM_MODEL in .env to use
a different model as the independent reviewer.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from engine.agent import RunResult
from engine.discover import LoadError, discover_csv
from engine.llm import LLMClient, get_llm
from engine.pipeline import STAGES, Pipeline, StageCache
from engine.sql import quote_ident
from engine.sql.results import jsonable
from engine.stages import CalculateOutcome, CleanReport, Metric, ValidateOutcome, run_validate
from engine.stages.calculate import BASE
from engine.stages.validate import allowed_numbers, untraceable
from scripts.terminal import pick_answer

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
DEFAULT = ("02_bank_balances.csv", "03_sales_with_totals.csv", "05_survey.csv")

# One deliberately wrong metric per sample: name, meaning, SQL ({col} = the clean column), raw column, unit
TRAPS: dict[str, tuple[str, str, str, str, str]] = {
    "02_bank_balances.csv": ("total_balance", "Total balance held across all accounts.",
                             "SELECT sum({col}) AS total_balance FROM base", "closing_balance", "USD"),
    "03_sales_with_totals.csv": ("total_units", "Total units sold across all regions and products.",
                                 "SELECT sum({col}) * 2 AS total_units FROM base", "units", "units"),
    "05_survey.csv": ("avg_gender", "Average gender of respondents.",
                      "SELECT avg({col}) AS avg_gender FROM base", "gender", ""),
}


# ----------------------------------------------------------------------------- printing

def report(ok: bool, label: str, note: object) -> bool:
    print(f"   {'✓' if ok else '✗'} {label:<48} {' '.join(str(note).split())[:100]}")
    return ok


def summary(r: RunResult) -> str:
    u = r.usage
    return (f"{r.stage}: status={r.status} | steps={u.get('steps')} | {u.get('input_tokens')} in / "
            f"{u.get('output_tokens')} out tokens | {u.get('seconds')}s")


def one_line(text: object, limit: int = 120) -> str:
    return " ".join(str(text).split())[:limit]


def show(val: ValidateOutcome, ways: dict[str, list[dict]]) -> None:
    metrics = val.calculate.metrics if val.calculate else []
    print(f"     {'metric':<28} {'final verdict':<28} {'review':<8} {'2nd way':<9} reason")
    for m in metrics:
        v, r = val.verdicts.get(m.name), val.reviews.get(m.name)
        verdict = (v.verdict if v else "-") + (" (repaired)" if m.name in val.repaired else "")
        tried = ways.get(m.name, [])
        proof = "match" if any(w["matched"] for w in tried) else ("no match" if tried else "none")
        print(f"     {m.name[:28]:<28} {verdict:<28} {(r.status if r else '-'):<8} "
              f"{proof:<9} {one_line(v.reason if v else '', 60)}")
    gone = [n for n in val.verdicts if n not in {m.name for m in metrics}]
    for name in gone:
        print(f"     {name[:28]:<28} {'drop (removed)':<28} {'':<8} {'':<9} {one_line(val.verdicts[name].reason, 60)}")
    if val.repaired:
        print(f"   sent through the Check loop: {', '.join(val.repaired)}")
    for note in val.notes:
        print(f"   note: {one_line(note)}")



# ----------------------------------------------------------------------------- the fire drill

def clean_name(rep: CleanReport, raw_name: str) -> str:
    best = [c for c in rep.columns if c.sources == [raw_name]] or [c for c in rep.columns if raw_name in c.sources]
    return best[0].name if best else raw_name


def plant_trap(pipe: Pipeline, calc: CalculateOutcome, rep: CleanReport, file_name: str) -> Metric | None:
    """Slip one wrong metric in among the real ones, as if Calculate had made it."""
    if file_name not in TRAPS or calc.result is None:
        return None
    name, meaning, template, raw_col, unit = TRAPS[file_name]
    while name in pipe.agent.ws.recipes:
        name += "_all"                                   # never overwrite a real metric
    sql = template.format(col=quote_ident(clean_name(rep, raw_col)))
    result = pipe.box.run(sql, purpose="fire drill: plant a wrong metric", tables=(BASE,))
    trap = pipe.agent.ws.recipes.save(Metric(
        name=name, meaning=meaning, sql=result.sql, columns=result.columns,
        preview=[[jsonable(v) for v in row] for row in result.rows[:10]],
        question="Q1", shape="single_value", measures=list(result.columns), unit=unit, confidence=0.9))
    position = min(1, len(calc.metrics))
    calc.metrics.insert(position, trap)
    calc.result.metrics.insert(position, name)
    return trap


# ----------------------------------------------------------------------------- running

def check_file(path: Path, llm: LLMClient, reviewer: LLMClient, cache: StageCache | None,
               fresh_from: str | None) -> list[bool]:
    print(f"\n=== {path.name} ===")
    try:
        raw, facts = discover_csv(path)
    except LoadError as exc:
        return [report(False, "file loads", exc)]
    results: list[bool] = []
    with Pipeline(llm, raw, facts, path.read_bytes(), answer=pick_answer, cache=cache, fresh_from=fresh_from) as pipe:
        cleaned = pipe.clean()
        print("  ", summary(cleaned.run))
        results.append(report(cleaned.result is not None, "clean finished", cleaned.run.message or "ok"))
        if cleaned.result is None or cleaned.facts is None or cleaned.report is None:
            return results
        reasoned = pipe.reason(cleaned)
        print("  ", summary(reasoned.run))
        results.append(report(reasoned.card is not None, "reason finished", reasoned.run.message or "ok"))
        if reasoned.card is None:
            return results
        calc = pipe.calculate(reasoned.card)
        print("  ", summary(calc.run))
        results.append(report(calc.result is not None, "calculate finished", calc.run.message or "ok"))
        if calc.result is None:
            return results

        trap = plant_trap(pipe, calc, cleaned.report, path.name)
        if trap is not None:
            print(f"   fire drill: planted '{trap.name}' = {trap.sql} -> {trap.preview}")
        val = run_validate(pipe.agent, reviewer, reasoned.card, calc, answer=pick_answer)
        for run in val.runs:
            print("  ", summary(run))
        ways = pipe.agent.ws.artifacts.get("second_ways", {})
        show(val, ways)

        first = val.runs[0] if val.runs else None
        results.append(report(val.finished, "checker reached a verdict",
                              (first.message or "ok") if first else "no run"))
        if trap is not None:
            verdict = val.verdicts.get(trap.name)
            kept = next((m for m in val.approved if m.name == trap.name), None)
            caught = kept is None or kept.sql != trap.sql
            how = f"{verdict.verdict}: {verdict.reason}" if verdict else "no verdict"
            results.append(report(caught, "the planted wrong metric was not approved as is", how))
        real_total = len(val.calculate.metrics if val.calculate else []) - (1 if trap else 0)
        real = [m for m in val.approved if trap is None or m.name != trap.name]
        results.append(report(bool(real), "real metrics approved", f"{len(real)} of {real_total}"))
        unproven = [m.name for m in val.approved if not any(w["matched"] for w in ways.get(m.name, []))]
        results.append(report(not unproven, "every approved metric has a matching second way",
                              ", ".join(unproven) or "ok"))
        allowed = allowed_numbers([m.name for m in val.approved], val.facts)
        loose = [n for n in val.notes if untraceable(n, allowed)]
        results.append(report(not loose, "notes quote only approved results",
                              "; ".join(loose) or f"{len(val.notes)} notes, all traceable"))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 5: Validate check with a fire drill")
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--fresh", choices=STAGES, help="re-run this stage and the ones after it")
    parser.add_argument("--no-cache", action="store_true", help="neither reuse nor save stage outputs")
    args = parser.parse_args()
    files = args.files or [SAMPLES / name for name in DEFAULT]
    missing = [f.name for f in files if not f.is_file()]
    if missing:
        print(f"✗ Missing: {', '.join(missing)}. Run first: python -m scripts.make_test_csvs")
        return 1
    try:
        llm = get_llm()
        reviewer = get_llm("reviewer") if os.getenv("REVIEWER_LLM_MODEL") else llm
    except (RuntimeError, ValueError) as exc:
        print(f"✗ Settings problem: {exc}")
        return 1

    cache = None if args.no_cache else StageCache()
    results: list[bool] = []
    for path in files:
        results += check_file(path, llm, reviewer, cache, args.fresh)
    passed = sum(results)
    m = llm.meter.snapshot()
    print(f"\n{passed}/{len(results)} passed | AI calls: {m['calls']} | "
          f"{m['input_tokens']} in / {m['output_tokens']} out tokens | {m['seconds']}s")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
