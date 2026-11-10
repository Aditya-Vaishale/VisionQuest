"""
Stage 1, Discover: turn a table into a fact sheet.

Facts only (blanks, patterns, parse rates, keys); it never decides what a
column means. Works on the raw all-text table and, later, on the cleaned copy:
typed columns are profiled through their text form, so both get the same facts.
"""
from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.api import types as ptypes

from engine.discover.loader import RawTable, load_csv
from engine.discover.models import (
    ColumnFacts, FactSheet, HeaderDates, KeyCandidate, LengthStats, LoadInfo, NumberStats, ShapeShare,
    ValueCount,
)
from engine.discover.readings import clip, date_candidates, date_readings, number_readings, to_floats

_DIGIT = re.compile(r"\d")
_LETTER = re.compile(r"[^\W\d_]")
_SPACE = re.compile(r"\s+")
_REPEAT = re.compile(r"(.)\1+")
_LEADING_ZERO = r"[+-]?0\d"

@dataclass(frozen=True)
class DiscoverOptions:
    top_values: int = 8
    samples: int = 5
    shapes: int = 5
    max_value_chars: int = 60          # longer values are clipped in the fact sheet
    max_parse_values: int = 20_000     # above this many distinct values, parse tests use a sample
    min_report_rate: float = 0.05      # readings fitting fewer rows than this are left out as noise
    date_bar_on_numbers: float = 0.95  # if numbers fit this share, a date reading must fit it too
    max_key_pairs: int = 30            # two-column key checks per table
    key_pair_row_limit: int = 500_000  # skip two-column key checks on bigger tables
    max_key_luck: float = 0.05         # drop pairs this likely to be unique by pure chance
    seed: int = 0                      # same file -> same fact sheet (needed for caching later)

def discover_csv(path: str | Path, options: DiscoverOptions | None = None) -> tuple[RawTable, FactSheet]:
    raw = load_csv(path)
    return raw, profile_table(raw.df, raw.load, options)

def profile_table(df: pd.DataFrame, load: LoadInfo | None = None, options: DiscoverOptions | None = None) -> FactSheet:
    opts = options or DiscoverOptions()
    columns = [profile_column(df.iloc[:, i], i + 1, opts, name=str(df.columns[i])) for i in range(df.shape[1])]
    return FactSheet(
        load=load,
        rows=len(df),
        column_count=df.shape[1],
        duplicate_rows=int(df.duplicated().sum()) if len(df) else 0,
        candidate_keys=_candidate_keys(df, columns, opts),
        header_dates=_header_dates([c.name for c in columns], opts),
        columns=columns,
    )

def profile_column(
    series: pd.Series, position: int, options: DiscoverOptions | None = None, *, name: str | None = None,
) -> ColumnFacts:
    """Facts for one column. The Look tool will reuse this to zoom into a column."""
    opts = options or DiscoverOptions()
    rng = np.random.default_rng([opts.seed, position])
    rows = len(series)

    present = series[series.notna()]
    if isinstance(present.dtype, pd.DatetimeTZDtype):
        present = present.dt.tz_convert(None)
    text = present.astype(str)
    stripped = text.str.strip()
    filled = stripped.ne("").to_numpy(dtype=bool)
    in_order = stripped[filled]                     # non-blank values, in file order
    non_blank = len(in_order)
    base = {
        "position": position,
        "name": name if name is not None else str(series.name),
        "storage": _storage(series.dtype),
        "rows": rows,
        "blank": rows - non_blank,
        "blank_rate": _ratio(rows - non_blank, rows),
    }
    if non_blank == 0:
        return ColumnFacts(**base, distinct=0, distinct_rate=0.0, all_unique=False)

    # Most common first; ties in a fixed order so the same file always gives the same sheet.
    vc = in_order.value_counts(sort=False).sort_index(kind="stable").sort_values(ascending=False, kind="stable")
    values, counts, weights, estimated = _parse_sample(vc, opts.max_parse_values, rng)

    every_value_once = int(vc.iloc[0]) == 1
    top = [] if every_value_once else [
        ValueCount(value=clip(str(v), opts.max_value_chars), count=int(c))
        for v, c in vc.iloc[: opts.top_values].items()
    ]
    rest = vc.index[len(top):]
    picks = np.sort(rng.choice(len(rest), size=min(opts.samples, len(rest)), replace=False)) if len(rest) else []
    samples = [clip(str(rest[int(i)]), opts.max_value_chars) for i in picks]

    lengths = values.str.len().to_numpy(dtype=float)
    numbers = number_readings(values, counts, weights, min_rate=opts.min_report_rate, clip_at=opts.max_value_chars)
    stats = _number_stats(numbers.best, numbers.parsed, weights, values, in_order) if numbers.best else None
    dates = date_readings(
        values, counts, weights, numbers.as_is, rng=rng,
        min_rate=opts.min_report_rate, clip_at=opts.max_value_chars,
    )
    number_fit = max((r.parse_rate for r in numbers.readings), default=0.0)
    if number_fit >= opts.date_bar_on_numbers:
        dates = [d for d in dates if d.parse_rate >= opts.date_bar_on_numbers]

    return ColumnFacts(
        **base,
        distinct=len(vc),
        distinct_rate=_ratio(len(vc), non_blank),
        all_unique=base["blank"] == 0 and len(vc) == rows,
        top_values=top,
        samples=samples,
        shapes=_shapes(values, weights, opts.shapes, opts.max_value_chars),
        length=LengthStats(
            min=int(lengths.min()),
            mean=round(float(np.average(lengths, weights=weights)), 1),
            max=int(lengths.max()),
        ),
        space_padded_rate=_ratio(int((text[filled] != in_order).sum()), non_blank),
        number_readings=numbers.readings,
        number_stats=stats,
        date_readings=dates,
        estimated=estimated,
    )

def _parse_sample(vc: pd.Series, limit: int, rng: np.random.Generator) -> tuple[pd.Series, np.ndarray, np.ndarray, bool]:
    """Distinct values used for parse tests. Above `limit`, keep the most common half plus a
    random sample of the rest, re-weighted so rates still estimate shares of ALL rows."""
    uniq = vc.index.to_numpy(dtype=object)
    counts = vc.to_numpy(dtype=np.int64)
    weights = counts.astype(float)
    if len(uniq) <= limit:
        return pd.Series(uniq, dtype=object), counts, weights, False
    head = limit // 2
    picked = np.sort(rng.choice(np.arange(head, len(uniq)), size=limit - head, replace=False))
    keep = np.concatenate([np.arange(head), picked])
    weights = weights[keep]
    weights[head:] *= counts[head:].sum() / counts[picked].sum()
    return pd.Series(uniq[keep], dtype=object), counts[keep], weights, True

def _number_stats(
    reading: str, parsed: np.ndarray, weights: np.ndarray, values: pd.Series, in_order: pd.Series,
) -> NumberStats | None:
    ok = np.isfinite(parsed)
    if not ok.any():
        return None
    x, w = parsed[ok], weights[ok]
    q = _weighted_quantiles(x, w, (0.0, 0.01, 0.25, 0.5, 0.75, 0.99, 1.0))
    mean = float(np.average(x, weights=w))
    std = float(np.sqrt(np.average((x - mean) ** 2, weights=w)))
    kept = values[ok]
    leading = kept.str.match(_LEADING_ZERO, na=False).to_numpy(dtype=bool)

    # File order: map each row's text to its number, then look at row-to-row steps.
    sequence = in_order.map(dict(zip(kept, x))).to_numpy(dtype=float, na_value=np.nan)
    steps = np.diff(sequence[np.isfinite(sequence)])
    return NumberStats(
        reading=reading,
        min=q[0], p01=q[1], p25=q[2], median=q[3], p75=q[4], p99=q[5], max=q[6],
        mean=mean,
        std=std,
        integer_rate=_wshare(x == np.round(x), w),
        negative_rate=_wshare(x < 0, w),
        zero_rate=_wshare(x == 0, w),
        leading_zero_rate=_wshare(leading, w),
        rising_rate=round(float((steps >= 0).mean()), 4) if steps.size else None,
    )

def _weighted_quantiles(x: np.ndarray, w: np.ndarray, qs: tuple[float, ...]) -> list[float]:
    order = np.argsort(x, kind="stable")
    x, cumulative = x[order], np.cumsum(w[order])
    total, last = cumulative[-1], len(x) - 1
    return [float(x[min(int(np.searchsorted(cumulative, q * total, side="left")), last)]) for q in qs]

def _wshare(mask: np.ndarray, w: np.ndarray) -> float:
    total = float(w.sum())
    return round(float(w[mask].sum()) / total, 4) if total else 0.0

def _shape(value: str, limit: int = 24) -> str:
    s = _SPACE.sub(" ", _LETTER.sub("A", _DIGIT.sub("9", value)))
    s = _REPEAT.sub(r"\1", s)
    return s if len(s) <= limit else s[: limit - 1] + "…"

def _shapes(values: pd.Series, weights: np.ndarray, limit: int, clip_at: int) -> list[ShapeShare]:
    totals: dict[str, list] = {}
    for value, weight in zip(values, weights):
        key = _shape(value)
        if key in totals:
            totals[key][0] += weight
        else:
            totals[key] = [weight, value]          # first seen = most common example
    grand = float(weights.sum())
    ranked = sorted(totals.items(), key=lambda kv: -kv[1][0])[:limit]
    return [ShapeShare(shape=k, share=round(t / grand, 4), example=clip(ex, clip_at)) for k, (t, ex) in ranked]

def _storage(dtype: object) -> str:
    if ptypes.is_bool_dtype(dtype):
        return "boolean"
    if ptypes.is_integer_dtype(dtype):
        return "integer"
    if ptypes.is_float_dtype(dtype):
        return "decimal"
    if ptypes.is_datetime64_any_dtype(dtype):
        return "datetime"
    return "text"

def _ratio(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0

def _candidate_keys(df: pd.DataFrame, columns: list[ColumnFacts], opts: DiscoverOptions) -> list[KeyCandidate]:
    """What could identify one row.

    Single columns whose values never repeat come first. Pairs are tried only when no single
    column works. A pair is kept only if being unique by pure luck is unlikely (birthday maths),
    and pairs are sorted by how much of the possible grid they fill: date x account filling 100%
    means one row for every account on every date."""
    singles = [KeyCandidate(columns=[c.name], kinds=[c.kind()]) for c in columns if c.all_unique]
    rows = len(df)
    if singles or rows < 2 or rows > opts.key_pair_row_limit:
        return singles[:5]

    pool = sorted((c for c in columns if c.blank == 0 and c.distinct > 1), key=lambda c: -c.distinct)[:12]
    pairs: list[KeyCandidate] = []
    checked = 0
    for a, b in itertools.combinations(pool, 2):
        if checked >= opts.max_key_pairs:
            break
        combos = a.distinct * b.distinct
        if combos < rows:
            continue                               # too few combinations to be unique
        luck = math.exp(-rows * (rows - 1) / (2 * combos))
        if luck > opts.max_key_luck:
            continue                               # would likely be unique by chance: proves nothing
        checked += 1
        if df.duplicated(subset=[df.columns[a.position - 1], df.columns[b.position - 1]]).any():
            continue
        first, second = sorted((a, b), key=lambda c: c.position)
        pairs.append(KeyCandidate(
            columns=[first.name, second.name],
            kinds=[first.kind(), second.kind()],
            grid_fill=round(rows / combos, 4),
            luck_chance=round(luck, 4),
        ))
    pairs.sort(key=lambda k: -(k.grid_fill or 0.0))
    return pairs[:5]

def _header_dates(names: list[str], opts: DiscoverOptions) -> list[HeaderDates]:
    """Date readings that fit 3+ column NAMES (e.g. Jan-2024 ... Dec-2024)."""
    values = pd.Series(names, dtype=object)
    rng = np.random.default_rng([opts.seed, 0])
    found: list[HeaderDates] = []
    for reading, parsed in date_candidates(values, to_floats(values), rng=rng):
        hits = [n for n, ok in zip(names, ~np.isnat(parsed)) if ok]
        if len(hits) >= 3:
            found.append(HeaderDates(reading=reading, columns=hits))
    found.sort(key=lambda h: -len(h.columns))
    return found[:2]
