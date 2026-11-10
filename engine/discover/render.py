"""
Compact fact-sheet view for the AI, sized to a character budget.

The most detailed view that fits wins. Wide tables may summarise similar
columns together (same name pattern + same kind); the AI can zoom into any
column later with the Look tool.
"""
from __future__ import annotations

import json
import re
from typing import Any

from engine.discover.models import ColumnFacts, DateReading, FactSheet, KeyCandidate, NumberReading, NumberStats

DEFAULT_CHAR_BUDGET = 24_000   # about 6k tokens
GROUP_THRESHOLD = 40           # grouping is allowed only above this many columns
MIN_GROUP_SIZE = 3
_DIGITS = re.compile(r"\d+")
_TRUNCATED_NOTE = "Not every column fits; ask to look at a column by name."
_LEVEL_NAMES = {0: "minimal", 1: "compact", 2: "full"}
# Per detail level: top values, samples, shapes, failed examples, date readings
_LIMITS = {2: (8, 5, 4, 3, 3), 1: (3, 2, 2, 0, 1)}

LEGEND = {
    "rates": "shares of non-blank rows, 0-1",
    "top_values": "[value, rows]",
    "shapes": "[pattern, share]: 9 = digits, A = letters, repeats collapsed",
    "length": "[min, mean, max] characters",
    "readings": "ways the text could be read as numbers or dates, and how many rows each fits",
    "group": "similar columns (same name pattern, # = digits, same kind) summarised; ranges are [min, max]",
    "missing fields": "zero, false or empty",
    "candidate_keys": "columns whose values never repeat (together); grid_fill = rows / possible combinations",
}

def render_for_llm(sheet: FactSheet, char_budget: int = DEFAULT_CHAR_BUDGET) -> str:
    """Compact JSON for the AI: the most detailed view that fits `char_budget` characters."""
    allow_groups = sheet.column_count > GROUP_THRESHOLD
    for level in (2, 1, 0):
        for grouped in ((False, True) if allow_groups else (False,)):
            text = _dump(_view(sheet, _items(sheet.columns, level, grouped), level))
            if len(text) <= char_budget:
                return text
    return _dump(_truncated(sheet, char_budget, allow_groups))

def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

def _view(sheet: FactSheet, items: list[dict[str, Any]], level: int, **extra: Any) -> dict[str, Any]:
    return {"detail": _LEVEL_NAMES[level], "legend": LEGEND, "table": _table(sheet), "columns": items, **extra}

def _truncated(sheet: FactSheet, budget: int, grouped: bool) -> dict[str, Any]:
    items = _items(sheet.columns, 0, grouped)
    used = len(_dump(_view(sheet, [], 0, omitted_columns=len(items), note=_TRUNCATED_NOTE)))
    kept: list[dict[str, Any]] = []
    for item in items:
        size = len(_dump(item)) + 1
        if used + size > budget:
            break
        kept.append(item)
        used += size
    return _view(sheet, kept, 0, omitted_columns=len(items) - len(kept), note=_TRUNCATED_NOTE)

def _items(columns: list[ColumnFacts], level: int, grouped: bool) -> list[dict[str, Any]]:
    if not grouped:
        return [_column(c, level) for c in columns]
    buckets: dict[tuple[str, str], list[ColumnFacts]] = {}
    for c in columns:
        buckets.setdefault(_group_key(c), []).append(c)
    items: list[dict[str, Any]] = []
    done: set[tuple[str, str]] = set()
    for c in columns:                              # keep the table's column order
        key = _group_key(c)
        members = buckets[key]
        if len(members) < MIN_GROUP_SIZE:
            items.append(_column(c, level))
        elif key not in done:
            done.add(key)
            items.append(_group(key, members, level))
    return items

def _group_key(c: ColumnFacts) -> tuple[str, str]:
    return _DIGITS.sub("#", c.name), c.kind()

def _kind(c: ColumnFacts) -> str:
    number = max((r.parse_rate for r in c.number_readings), default=0.0)
    date = c.date_readings[0].parse_rate if c.date_readings else 0.0
    if max(number, date) < 0.5:
        return c.storage
    return "date" if date >= number else "number"

def _group(key: tuple[str, str], members: list[ColumnFacts], level: int) -> dict[str, Any]:
    pattern, kind = key
    g: dict[str, Any] = {
        "group": pattern,
        "kind": kind,
        "column_count": len(members),
        "names": _preview([m.name for m in members]),
        "blank_rate": [min(m.blank_rate for m in members), max(m.blank_rate for m in members)],
        "distinct": [min(m.distinct for m in members), max(m.distinct for m in members)],
    }
    stats = [m.number_stats for m in members if m.number_stats]
    if stats:
        g["number_range"] = [_num(min(s.min for s in stats)), _num(max(s.max for s in stats))]
        g["mean_range"] = [_num(min(s.mean for s in stats)), _num(max(s.mean for s in stats))]
    g["example_column"] = _column(members[0], level)
    return g

def _table(sheet: FactSheet) -> dict[str, Any]:
    t: dict[str, Any] = {
        "fact_sheet_version": sheet.version,
        "rows": sheet.rows,
        "columns": sheet.column_count,
        "duplicate_rows": sheet.duplicate_rows,
    }
    if sheet.candidate_keys:
        t["candidate_keys"] = [_key(k) for k in sheet.candidate_keys]
    if sheet.header_dates:
        t["column_names_that_read_as_dates"] = [
            {"reading": h.reading, "count": len(h.columns), "columns": _preview(h.columns)}
            for h in sheet.header_dates
        ]
    if sheet.load:
        load = sheet.load
        f: dict[str, Any] = {
            "name": load.file_name, "encoding": load.encoding,
            "delimiter": load.delimiter, "header_line": load.header_line,
        }
        if load.preamble:
            f["lines_above_table"] = load.preamble[:5]
        if load.ragged_rows:
            f["ragged_rows"] = {"count": load.ragged_rows, "example_lines": load.ragged_examples}
        if load.renamed_columns:
            f["renamed_columns"] = dict(list(load.renamed_columns.items())[:20])
        if load.blank_rows_dropped:
            f["blank_rows_dropped"] = load.blank_rows_dropped
        if load.notes:
            f["notes"] = load.notes
        t["file"] = f
    return t

def _key(k: KeyCandidate) -> dict[str, Any]:
    v: dict[str, Any] = {"columns": k.columns, "kinds": k.kinds}
    if k.grid_fill is not None:
        v["grid_fill"] = k.grid_fill
    if k.luck_chance is not None:
        v["unique_by_luck_chance"] = k.luck_chance
    return v

def _column(c: ColumnFacts, level: int) -> dict[str, Any]:
    v: dict[str, Any] = {"name": c.name, "storage": c.storage}
    if c.blank:
        v["blank_rate"] = c.blank_rate
    v["distinct"] = c.distinct
    if c.all_unique:
        v["all_unique"] = True
    if c.space_padded_rate:
        v["space_padded_rate"] = c.space_padded_rate
    if c.estimated:
        v["estimated_from_sample"] = True
    if level == 0:
        reads = _reads_as(c)
        if reads:
            v["reads_as"] = reads
        return v

    tops, samples, shapes, fails, dates = _LIMITS[level]
    if c.top_values:
        v["top_values"] = [[t.value, t.count] for t in c.top_values[:tops]]
    if c.samples:
        v["samples"] = c.samples[:samples]
    if c.shapes:
        v["shapes"] = [[s.shape, s.share] for s in c.shapes[:shapes]]
    if c.length and level == 2:
        v["length"] = [c.length.min, c.length.mean, c.length.max]
    if c.number_readings:
        v["number_readings"] = [_number_reading(r, fails) for r in c.number_readings]
    if c.number_stats:
        v["number_stats"] = _stats(c.number_stats, level)
    if c.date_readings:
        v["date_readings"] = [_date_reading(d, fails) for d in c.date_readings[:dates]]
    return v

def _number_reading(r: NumberReading, fails: int) -> dict[str, Any]:
    v: dict[str, Any] = {"reading": r.reading, "parse_rate": r.parse_rate}
    if r.symbols_removed:
        v["symbols_removed"] = r.symbols_removed
    if r.percent_sign_rate:
        v["percent_sign_rate"] = r.percent_sign_rate
    if r.parentheses_rate:
        v["parentheses_rate"] = r.parentheses_rate
    if r.ambiguous_rate:
        v["us_vs_eu_ambiguous_rate"] = r.ambiguous_rate
    if fails and r.failed_examples:
        v["failed"] = [[f.value, f.count] for f in r.failed_examples[:fails]]
    return v

def _stats(s: NumberStats, level: int) -> dict[str, Any]:
    keys = ("min", "p01", "p25", "median", "p75", "p99", "max", "mean", "std") if level == 2 \
        else ("min", "median", "max", "mean")
    v: dict[str, Any] = {"reading": s.reading, **{k: _num(getattr(s, k)) for k in keys}}
    for k in ("integer_rate", "negative_rate", "zero_rate", "leading_zero_rate"):
        if getattr(s, k):
            v[k] = getattr(s, k)
    if level == 2 and s.rising_rate is not None:
        v["rising_rate_in_file_order"] = s.rising_rate
    return v

def _date_reading(d: DateReading, fails: int) -> dict[str, Any]:
    v: dict[str, Any] = {"reading": d.reading, "parse_rate": d.parse_rate, "min": d.min, "max": d.max,
                         "distinct": d.distinct}
    if d.has_time:
        v["has_time"] = True
    if d.timezone_rate:
        v["timezone_rate"] = d.timezone_rate
    if d.median_gap:
        v["median_gap"] = d.median_gap
    if d.common_gap:
        v["common_gap"] = [d.common_gap, d.common_gap_share]
    if fails and d.failed_examples:
        v["failed"] = [[f.value, f.count] for f in d.failed_examples[:fails]]
    return v

def _reads_as(c: ColumnFacts) -> str | None:
    parts = []
    if c.number_readings:
        best = max(c.number_readings, key=lambda r: r.parse_rate)
        parts.append(f"number {best.parse_rate:.0%} ({best.reading})")
    if c.date_readings:
        d = c.date_readings[0]
        parts.append(f"date {d.parse_rate:.0%} ({d.reading})")
    return "; ".join(parts) or None

def _preview(names: list[str], head: int = 3, tail: int = 2) -> list[str]:
    if len(names) <= head + tail + 1:
        return names
    return [*names[:head], f"… {len(names) - head - tail} more …", *names[-tail:]]

def _num(x: float) -> float | int:
    y = float(f"{x:.6g}")
    return int(y) if y.is_integer() and abs(y) < 1e15 else y

def render_column(c: ColumnFacts) -> dict[str, Any]:
    """Full-detail view of one column (the Look tool's zoom)."""
    return _column(c, 2)