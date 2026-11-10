"""
Step 4c check: Discover -> Clean -> Reason on sample files, with real AI calls (about 15-30 per file).

  python -m scripts.check_reason                          # 01 leave, 02 bank, 03 sales, 05 survey
  python -m scripts.check_reason --all                    # all 8 samples (long)
  python -m scripts.check_reason samples/04_api_logs.csv  # one file

If the AI asks a question, type your answer (Enter = first option).
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from engine.agent import Agent, RunResult, Workspace
from engine.discover import LoadError, discover_csv
from engine.llm import LLMClient, get_llm
from engine.sql import QueryError, Sandbox, quote_ident
from engine.stages import (
    CleanReport, UnderstandingCard, check_reason, resume_clean, resume_reason, run_clean, run_reason,
)
from scripts.terminal import ask_loop


SAMPLES = Path(__file__).resolve().parent.parent / "samples"
DEFAULT = ("01_leave_requests.csv", "02_bank_balances.csv", "03_sales_with_totals.csv", "05_survey.csv")
Check = tuple[str, bool, str]
AMOUNT = {"amount_or_count"}
ID_LIKE = {"identifier", "category", "code"}
CODE_LIKE = {"code", "category"}

# ----------------------------------------------------------------------------- printing

def report(ok: bool, label: str, note: object) -> bool:
    print(f"   {'✓' if ok else '✗'} {label:<46} {' '.join(str(note).split())[:100]}")
    return ok

def summary(r: RunResult) -> str:
    u = r.usage
    return (f"status={r.status} | steps={u.get('steps')} | {u.get('input_tokens')} in / "
            f"{u.get('output_tokens')} out tokens | {u.get('seconds')}s")

def one_line(text: object, limit: int = 150) -> str:
    return " ".join(str(text).split())[:limit]

def show_card(card: UnderstandingCard) -> None:
    print(f"   dataset:  {one_line(card.dataset)}")
    print(f"   one row = {one_line(card.row_grain)}")
    print(f"   evidence: {one_line(card.grain_evidence)}")
    print(f"   keys: {card.keys or '-'} | entities: {card.entities or '-'} | confidence {card.confidence:.0%}")
    print(f"   regular rows: WHERE {one_line(card.regular_rows, 80)}")
    if card.time:
        t = card.time
        print(f"   time: {t.column} = {one_line(t.meaning, 60)} | cadence {one_line(t.cadence, 30)} "
              f"| show by {one_line(t.display_grain, 50)}")
    for role in card.columns[:14]:
        print(f"     {role.column[:22]:<22} {role.kind:<22} {one_line(role.aggregation, 70)}")
    if len(card.columns) > 14:
        print(f"     ... {len(card.columns) - 14} more")
    for g in card.row_groups:
        print(f"   special rows: {g.name} ({g.rows}) -> {one_line(g.treatment, 60)} | WHERE {one_line(g.sql_filter, 60)}")
    for q in card.questions[:10]:
        print(f"   question: {one_line(q)}")
    for d in card.doubts:
        print(f"   doubt: {one_line(d.topic, 50)} -> {one_line(d.decision, 90)}")

# ----------------------------------------------------------------------------- ground truth for the samples

def is_number(t: str) -> bool:
    return any(k in t.upper() for k in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "REAL", "NUMERIC"))

def clean_name(rep: CleanReport, raw_name: str, numeric: bool | None = None) -> str | None:
    """The clean column made from a raw column (Clean may have renamed it)."""
    cols = [c for c in rep.columns if raw_name in c.sources]
    if numeric is not None:
        cols = [c for c in cols if is_number(c.type) == numeric]
    best = [c for c in cols if c.sources == [raw_name]] or cols
    return best[0].name if best else None

def kind_of(card: UnderstandingCard, column: str | None) -> str:
    if column is None:
        return "-"
    for role in card.columns:
        if fnmatch.fnmatchcase(column.casefold(), role.column.strip().casefold()):
            return role.kind
    return "-"

def kind_is(card: UnderstandingCard, rep: CleanReport, raw_name: str, allowed: set[str], label: str,
            numeric: bool | None = None) -> Check:
    column = clean_name(rep, raw_name, numeric)
    kind = kind_of(card, column)
    return label, kind in allowed, f"{column}: {kind}"

def keys_are(card: UnderstandingCard, rep: CleanReport, raw_names: list[str], label: str) -> Check:
    want = {(clean_name(rep, r) or r).casefold() for r in raw_names}
    have = {k.strip().casefold() for k in card.keys}
    return label, want == have, f"keys: {card.keys or '-'}"

def time_is_temporal(box: Sandbox, card: UnderstandingCard) -> Check:
    column = card.time.column if card.time else None
    types = {c.casefold(): t for c, t in box.schema()["clean"]}
    ctype = types.get(column.strip().casefold(), "") if column else ""
    ok = any(k in ctype.upper() for k in ("DATE", "TIMESTAMP"))
    return "time column found, and it is a date/time", ok, f"{column}: {ctype or '-'}"

def sales_rows(box: Sandbox, card: UnderstandingCard, rep: CleanReport) -> Check:
    label = "20 detail rows regular, 5 total rows special"
    region = clean_name(rep, "region")
    if region is None:
        return label, False, "no region column"
    special = " OR ".join(f"coalesce(({g.sql_filter}), false)" for g in card.row_groups) or "false"
    is_total = f"{quote_ident(region)} ILIKE '%total%'"
    sql = (f"SELECT count(*) FILTER (WHERE coalesce(({card.regular_rows}), false) AND NOT {is_total}) AS detail, "
           f"count(*) FILTER (WHERE ({special}) AND {is_total}) AS totals, "
           f"count(*) FILTER (WHERE ({special}) AND NOT {is_total}) AS wrong FROM clean")
    try:
        r = box.run(sql, purpose="check: sales rows", tables=("clean",))
    except QueryError as err:
        return label, False, err.message
    detail, totals, wrong = r.rows[0]
    return (label, detail == 20 and totals == 5 and wrong == 0,
            f"regular detail {detail}, special totals {totals}, detail rows marked special {wrong}")

EXPECT: dict[str, Callable[[Sandbox, UnderstandingCard, CleanReport], list[Check]]] = {
    "01_leave_requests.csv": lambda box, card, rep: [
        keys_are(card, rep, ["request_id"], "one row = one request (key request_id)"),
        kind_is(card, rep, "days", AMOUNT, "days can be summed"),
        kind_is(card, rep, "employee_id", ID_LIKE, "employee_id is an identifier, not a number")],

    "02_bank_balances.csv": lambda box, card, rep: [
        keys_are(card, rep, ["date", "account_id"], "one row = one account per day"),
        kind_is(card, rep, "closing_balance", {"level_or_snapshot", "running_total"}, "closing_balance is a snapshot"),
        kind_is(card, rep, "deposits", AMOUNT, "deposits can be summed")],

    "03_sales_with_totals.csv": lambda box, card, rep: [
        sales_rows(box, card, rep),
        kind_is(card, rep, "revenue", AMOUNT, "revenue can be summed")],

    "04_api_logs.csv": lambda box, card, rep: [
        time_is_temporal(box, card),
        kind_is(card, rep, "status_code", CODE_LIKE, "status_code is a code, not a number"),
        kind_is(card, rep, "latency_ms", {"measurement", "rate_ratio_or_average"}, "latency is averaged, not summed")],

    "05_survey.csv": lambda box, card, rep: [
        keys_are(card, rep, ["respondent_id"], "smallest key: respondent_id alone"),
        kind_is(card, rep, "gender", CODE_LIKE, "gender is a code (never averaged)"),
        kind_is(card, rep, "satisfaction", {"score_or_rating"}, "satisfaction is a score")],

    "06_budget_months_wide.csv": lambda box, card, rep: [
        time_is_temporal(box, card),
        kind_is(card, rep, "Jan-2024", AMOUNT, "monthly amounts can be summed", numeric=True)],

    "07_messy_export.csv": lambda box, card, rep: [
        kind_is(card, rep, "Revenue", AMOUNT, "revenue can be summed"),
        kind_is(card, rep, "Return Rate", {"rate_ratio_or_average"}, "return rate is a rate, not summed"),
        kind_is(card, rep, "Postal Code", ID_LIKE, "postal code is not a number")],

    "08_wide_sensors.csv": lambda box, card, rep: [
        time_is_temporal(box, card),
        kind_is(card, rep, "sensor_001", {"measurement", "level_or_snapshot"}, "sensor values are readings, not sums")],
}

# ----------------------------------------------------------------------------- running

def check_file(path: Path, llm: LLMClient) -> list[bool]:
    print(f"\n=== {path.name} ===")
    try:
        raw, facts = discover_csv(path)
    except LoadError as exc:
        return [report(False, "file loads", exc)]
    results: list[bool] = []
    with Sandbox.from_raw(raw) as box:
        agent = Agent(llm, Workspace(sandbox=box))
        cleaned = ask_loop(agent, run_clean(agent, facts), resume_clean)
        print("   clean: ", summary(cleaned.run))
        results.append(report(cleaned.result is not None, "clean finished", cleaned.run.message or "ok"))
        if cleaned.result is None or cleaned.facts is None or cleaned.report is None:
            return results

        reasoned = ask_loop(agent, run_reason(agent, clean=cleaned.result, clean_facts=cleaned.facts,
                                              load=raw.load), resume_reason)
        run = reasoned.run
        print("   reason:", summary(run))
        results.append(report(reasoned.card is not None, "reason finished", run.message or "ok"))
        if reasoned.card is None:
            for step in run.trace[-3:]:                     # help diagnose an unfinished run
                for t in step.tools:
                    print(f"     step {step.step} {t.name} ({'ok' if t.ok else 'error'}): {t.result[:160]}")
            return results

        card = reasoned.card
        show_card(card)
        problems = check_reason(card, agent.ws)
        results.append(report(not problems, "card passes Python's checks", "; ".join(problems) or "ok"))
        for label, ok, note in EXPECT.get(path.name, lambda *_: [])(box, card, cleaned.report):
            results.append(report(ok, label, note))
    return results

def main() -> int:
    parser = argparse.ArgumentParser(description="Step 4c: Reason stage check")
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
