"""
Run Stage 1 (Discover) on CSV files and show the fact sheet.

  python -m scripts.discover_csv samples/07_messy_export.csv
  python -m scripts.discover_csv samples/08_wide_sensors.csv --ai   (also print what the AI receives)
  python -m scripts.discover_csv --all                              (every CSV in samples/)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from engine.discover import LoadError, discover_csv, render_for_llm
from engine.discover.models import ColumnFacts, FactSheet

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
MAX_COLUMN_LINES = 15

def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 1: Discover")
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true", help="every CSV in samples/")
    parser.add_argument("--ai", action="store_true", help="print the JSON the AI will receive")
    args = parser.parse_args()
    files = sorted(SAMPLES.glob("*.csv")) if args.all else args.files
    if not files:
        parser.error("give a CSV path, or --all (run python -m scripts.make_test_csvs first)")
    failed = sum(not show(path, args.ai) for path in files)
    return 1 if failed else 0

def show(path: Path, print_ai: bool) -> bool:
    print(f"\n=== {path.name} ===")
    started = time.perf_counter()
    try:
        _, sheet = discover_csv(path)
    except LoadError as exc:
        print(f"✗ {exc}")
        return False
    seconds = time.perf_counter() - started
    ai_view = render_for_llm(sheet)
    parsed_view = json.loads(ai_view)
    _print_table(sheet)
    _print_columns(sheet.columns)
    print(f"AI view: {len(ai_view):,} chars (~{len(ai_view) // 4:,} tokens), "
          f"detail={parsed_view['detail']} | took {seconds:.2f}s")
    if print_ai:
        print(json.dumps(parsed_view, indent=1, ensure_ascii=False))
    return True

def _print_table(sheet: FactSheet) -> None:
    load = sheet.load
    if load:
        print(f"File: {load.encoding}, delimiter {load.delimiter!r}, header on line {load.header_line}")
        for line in load.preamble:
            print(f"  above table: {line!r}")
        if load.ragged_rows:
            print(f"  ragged rows: {load.ragged_rows} (lines {load.ragged_examples})")
        if load.renamed_columns:
            print(f"  renamed: {load.renamed_columns}")
        if load.blank_rows_dropped:
            print(f"  blank rows dropped: {load.blank_rows_dropped}")
        for note in load.notes:
            print(f"  note: {note}")
    keys = ", ".join(_key_text(k) for k in sheet.candidate_keys) or "none"
    print(f"Table: {sheet.rows:,} rows x {sheet.column_count} columns | "
          f"duplicate rows: {sheet.duplicate_rows} | possible keys: {keys}")
    for h in sheet.header_dates:
        print(f"  column names read as dates ({h.reading}): {len(h.columns)}, e.g. {h.columns[:3]}")

def _key_text(k) -> str:
    text = " + ".join(f"{c} ({kind})" for c, kind in zip(k.columns, k.kinds))
    return text + (f" [fills {k.grid_fill:.0%} of grid]" if k.grid_fill is not None else "")

def _print_columns(columns: list[ColumnFacts]) -> None:
    print(f"{'#':>3}  {'column':<22} {'blank':>6} {'distinct':>8}  {'top shape':<14} reads as")
    for c in columns[:MAX_COLUMN_LINES]:
        shape = c.shapes[0].shape if c.shapes else "-"
        print(f"{c.position:>3}  {c.name[:22]:<22} {c.blank_rate:>6.1%} {c.distinct:>8,}  {shape[:14]:<14} {_reads(c)}")
    if len(columns) > MAX_COLUMN_LINES:
        print(f"     ... {len(columns) - MAX_COLUMN_LINES} more columns")

def _reads(c: ColumnFacts) -> str:
    parts = [f"number {r.parse_rate:.0%} ({r.reading}{', ambiguous' if r.ambiguous_rate else ''})"
             for r in c.number_readings]
    parts += [f"date {d.parse_rate:.0%} ({d.reading})" for d in c.date_readings[:2]]
    return "; ".join(parts) or "text"

if __name__ == "__main__":
    sys.exit(main())
