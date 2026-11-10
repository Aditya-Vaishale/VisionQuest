"""
Step 6a check: Visualize. Every stage, including Validate and Visualize, is reused when saved.
Writes the spec the website will draw to .cache/dashboards/<file>.json.

  python -m scripts.check_visualize                          # 02 bank, 03 sales
  python -m scripts.check_visualize samples/05_survey.csv
  python -m scripts.check_visualize --fresh visualize        # redo only the dashboard plan
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from engine.agent import RunResult
from engine.config import PROJECT_ROOT
from engine.discover import LoadError, discover_csv
from engine.llm import LLMClient, get_llm
from engine.pipeline import STAGES, Pipeline, StageCache
from engine.stages import build_dashboard, check_visualize
from scripts.terminal import pick_answer

SAMPLES = PROJECT_ROOT / "samples"
OUT = PROJECT_ROOT / ".cache" / "dashboards"
DEFAULT = ("02_bank_balances.csv", "03_sales_with_totals.csv")
TIME_KINDS = {"line", "area"}
EXPECT = {   # sample-specific: should the dashboard show a trend over time?
    "02_bank_balances.csv": ("a trend chart over time exists", True),
    "03_sales_with_totals.csv": ("no time chart (the data has no dates)", False),
}

def report(ok: bool, label: str, note: object) -> bool:
    print(f"   {'✓' if ok else '✗'} {label:<44} {' '.join(str(note).split())[:100]}")
    return ok

def summary(r: RunResult) -> str:
    u = r.usage
    return (f"{r.stage}: status={r.status} | steps={u.get('steps')} | {u.get('input_tokens')} in / "
            f"{u.get('output_tokens')} out tokens | {u.get('seconds')}s")

def one_line(text: object, limit: int = 60) -> str:
    return " ".join(str(text).split())[:limit]

def show(spec: dict) -> None:
    print(f"   title: {spec['title']} | {spec['subtitle']}")
    for f in spec["filters"]:
        print(f"   filter: {f['label']} ({f['kind']} on {f['column']})")
    for s in spec["sections"]:
        print(f"   [{s['name']}]")
        for c in s["components"]:
            caveat = f" | caveat: {one_line(c['caveat'], 40)}" if c["caveat"] else ""
            print(f"     {c['kind']:<12} {c['size']:<3} {one_line(c['title'], 50):<50} "
                  f"{c['data']['total_rows']} rows{caveat}")

def check_file(path: Path, llm: LLMClient, cache: StageCache | None, fresh_from: str | None) -> list[bool]:
    print(f"\n=== {path.name} ===")
    try:
        raw, facts = discover_csv(path)
    except LoadError as exc:
        return [report(False, "file loads", exc)]
    results: list[bool] = []
    with Pipeline(llm, raw, facts, path.read_bytes(), answer=pick_answer, cache=cache, fresh_from=fresh_from) as pipe:
        cleaned = pipe.clean()
        reasoned = pipe.reason(cleaned) if cleaned.result is not None and cleaned.facts is not None else None
        card = reasoned.card if reasoned is not None else None
        calc = pipe.calculate(card) if card is not None else None
        ok = calc is not None and calc.result is not None
        results.append(report(ok, "clean, reason, calculate finished", "reused or re-run"))
        if not ok:
            return results
        val = pipe.validate(card, calc, llm)
        for run in val.runs:
            print("  ", summary(run))
        results.append(report(bool(val.approved), "validate approved metrics", f"{len(val.approved)} approved"))
        if not val.approved:
            return results

        vis = pipe.visualize(card, val)
        print("  ", summary(vis.run))
        results.append(report(vis.plan is not None, "visualize finished", vis.run.message or "ok"))
        if vis.plan is None:
            for step in vis.run.trace[-3:]:
                for t in step.tools:
                    print(f"     step {step.step} {t.name} ({'ok' if t.ok else 'error'}): {t.result[:160]}")
            return results
        problems = check_visualize(vis.plan, pipe.agent.ws)
        results.append(report(not problems, "plan passes Python's checks", "; ".join(problems) or "ok"))

        spec = build_dashboard(pipe.box, vis.plan, vis.charts, val)
        OUT.mkdir(parents=True, exist_ok=True)
        target = OUT / f"{path.stem}.json"
        target.write_text(json.dumps(spec, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        show(spec)
        results.append(report(target.is_file(), "dashboard spec written", target))
        kinds = [c.kind for c in vis.charts]
        results.append(report("kpi" in kinds, "at least one KPI card", ", ".join(kinds)))
        if path.name in EXPECT:
            label, want = EXPECT[path.name]
            results.append(report(bool(TIME_KINDS & set(kinds)) == want, label, ", ".join(kinds)))
    return results

def main() -> int:
    parser = argparse.ArgumentParser(description="Step 6a: Visualize check")
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--no-cache", action="store_true", help="neither reuse nor save stage outputs")
    parser.add_argument("--fresh", choices=STAGES, help="re-run this stage and the ones after it")
    args = parser.parse_args()
    files = args.files or [SAMPLES / name for name in DEFAULT]
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
