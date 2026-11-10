"""
Parse tests: how well does a column's text read as numbers, or as dates?

Facts only. Each "reading" reports the share of rows it fits and what failed.
Nothing here decides what a column means; the AI does that in the Reason stage.

Inputs are a column's DISTINCT stripped non-blank values (most common first), with:
  counts  - rows per value (shown in examples)
  weights - used for rates; equal to counts unless distinct values were sampled
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

from engine.discover.models import DateReading, NumberReading, ValueCount

CURRENCY_SYMBOLS = ("$", "€", "£", "¥", "₹", "₩", "₽", "¢", "₺", "₦", "₫", "₱", "₪", "฿")
_CURRENCY = "[" + re.escape("".join(CURRENCY_SYMBOLS)) + "]"
_GROUP_SPACE = r"(?<=\d)[ '\u00a0\u202f](?=\d{3}(?!\d))"     # "1 234" / "1'234" digit grouping
_US = r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"  # 1,234.56
_EU = r"[+-]?(?:(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?|,\d+)"   # 1.234,56
_HAS_TIMEZONE = r".*(?:Z|[+-]\d{2}:?\d{2})"
_QUARTERS = (
    re.compile(r"(?P<y>\d{4})\s*[-/ ]?\s*[Qq](?P<q>[1-4])"),  # 2024-Q1, 2024 Q1
    re.compile(r"[Qq](?P<q>[1-4])\s*[-/ ]?\s*(?P<y>\d{4})"),  # Q1 2024, Q1-2024
)
UNIX_WINDOW_S = (631_152_000, 4_102_444_800)   # numbers count as Unix time only for 1990..2100
ISO = "ISO8601"
_NAT = np.datetime64("NaT", "ms")

# A test kit, not rules: each format is tried and simply reports how many rows it fits.
DATE_FORMATS: tuple[str, ...] = (
    # year first
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d",
    "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y%m%d%H%M%S",
    "%Y-%m", "%Y/%m", "%Y",
    ISO,  # every other ISO 8601 form: "2024-03-05T14:30:00.123Z", "+05:30" offsets ...
    # day first
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d.%m.%y",
    "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S",
    # month first
    "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y",
    "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p",
    # month names
    "%d %b %Y", "%d-%b-%Y", "%d-%b-%y", "%d %B %Y", "%b %d %Y", "%b %d, %Y", "%B %d %Y", "%B %d, %Y",
    "%b %Y", "%B %Y", "%b-%Y", "%b-%y", "%b", "%B",
    # month/year and time only
    "%m/%Y", "%m-%Y",
    "%H:%M", "%H:%M:%S", "%I:%M %p",
)

def clip(value: str, limit: int) -> str:
    """Shorten long text for display."""
    return value if len(value) <= limit else value[: limit - 1] + "…"

def to_floats(values: pd.Series) -> np.ndarray:
    """Numbers exactly as written ("12.5", "-3", "1e5"); NaN where not a finite number."""
    try:
        arr = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float, na_value=np.nan, copy=True)
    except (OverflowError, TypeError, ValueError):
        arr = np.array([_float_or_nan(v) for v in values], dtype=float)
    arr[~np.isfinite(arr)] = np.nan
    return arr

def _float_or_nan(value: object) -> float:
    try:
        return float(str(value).replace("_", "x"))  # Python accepts "1_000"; pandas does not
    except (OverflowError, ValueError):
        return float("nan")

def _share(mask: np.ndarray, weights: np.ndarray) -> float:
    total = float(weights.sum())
    return float(weights[mask].sum()) / total if total > 0 else 0.0

def _failed(values: pd.Series, counts: np.ndarray, failed: np.ndarray, limit: int, clip_at: int) -> list[ValueCount]:
    """The most common values a reading could not read."""
    if limit <= 0:
        return []
    idx = np.flatnonzero(failed)
    top = idx[np.argsort(-counts[idx], kind="stable")[:limit]]
    return [ValueCount(value=clip(str(values.iat[i]), clip_at), count=int(counts[i])) for i in top]

# ----------------------------------------------------------------------------- numbers

@dataclass(frozen=True)
class NumberResult:
    readings: list[NumberReading]
    best: str | None             # the reading that fits the most rows
    parsed: np.ndarray | None    # numbers from the best reading (NaN where it fails)
    as_is: np.ndarray            # numbers read exactly as written (NaN where not a number)

def number_readings(
    values: pd.Series, counts: np.ndarray, weights: np.ndarray, *,
    min_rate: float = 0.05, failed_limit: int = 3, clip_at: int = 60,
) -> NumberResult:
    """Try reading the text as numbers: as written, and with symbols/separators removed."""
    as_is = to_floats(values)

    # Symbol-tolerant text: "(1,200)" -> "1,200" (negative), "45%" -> "45", "$ 1 200" -> "1200"
    parens = values.str.fullmatch(r"\(.*\)", na=False).to_numpy(dtype=bool)
    text = values.str.replace(r"^\((.*)\)$", r"\1", regex=True)
    percent = text.str.contains(r"%\s*$", regex=True, na=False).to_numpy(dtype=bool)
    text = text.str.replace(r"\s*%\s*$", "", regex=True)
    symbols = [s for s in CURRENCY_SYMBOLS if text.str.contains(s, regex=False, na=False).any()]
    text = text.str.replace(_CURRENCY, "", regex=True).str.strip()
    text = text.str.replace(r"^([+-])\s+", r"\1", regex=True)
    text = text.str.replace(_GROUP_SPACE, "", regex=True)

    sign = np.where(parens, -1.0, 1.0)
    us_ok = text.str.fullmatch(_US, na=False).to_numpy(dtype=bool)
    eu_ok = text.str.fullmatch(_EU, na=False).to_numpy(dtype=bool)
    us = np.where(us_ok, to_floats(text.str.replace(",", "", regex=False)), np.nan) * sign
    eu_text = text.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    eu = np.where(eu_ok, to_floats(eu_text), np.nan) * sign

    ambiguous = _share(np.isfinite(us) & np.isfinite(eu) & (us != eu), weights)
    removed = symbols + (["%"] if percent.any() else []) + (["( )"] if parens.any() else [])
    candidates = (("as_is", as_is), ("symbols_us", us), ("symbols_eu", eu))
    rates = {name: _share(np.isfinite(arr), weights) for name, arr in candidates}

    readings: list[NumberReading] = []
    arrays: dict[str, np.ndarray] = {}
    for name, arr in candidates:
        rate = rates[name]
        if rate == 0 or rate < min_rate:
            continue
        if name != "as_is":
            adds_rows = rate > rates["as_is"] + 1e-12
            other_meaning = name == "symbols_eu" and ambiguous > 0
            if not (adds_rows or other_meaning):
                continue
        arrays[name] = arr
        tolerant = name != "as_is"
        readings.append(NumberReading(
            reading=name,
            parse_rate=round(rate, 4),
            failed_examples=_failed(values, counts, ~np.isfinite(arr), failed_limit, clip_at) if rate < 1 else [],
            symbols_removed=removed if tolerant else [],
            percent_sign_rate=round(_share(percent, weights), 4) if tolerant else 0.0,
            parentheses_rate=round(_share(parens, weights), 4) if tolerant else 0.0,
            ambiguous_rate=round(ambiguous, 4) if tolerant else 0.0,
        ))
    if not readings:
        return NumberResult([], None, None, as_is)
    best = max(readings, key=lambda r: r.parse_rate)  # ties keep the first: as_is, then US, then EU
    return NumberResult(readings, best.reading, arrays[best.reading], as_is)

# ----------------------------------------------------------------------------- dates

def _parse_format(values: pd.Series, fmt: str) -> np.ndarray:
    """datetime64[ms] per value; NaT where the format does not fit."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            if fmt == ISO:
                parsed = pd.to_datetime(values, format="ISO8601", errors="coerce", utc=True).dt.tz_convert(None)
            else:
                parsed = pd.to_datetime(values, format=fmt, errors="coerce")
            return parsed.to_numpy(dtype="datetime64[ms]")
        except (ValueError, TypeError, OverflowError):
            return np.full(len(values), _NAT)

def _unix(numbers: np.ndarray, to_ms: float) -> np.ndarray:
    """Numbers as Unix time (to_ms=1000 for seconds, 1 for milliseconds), only inside UNIX_WINDOW_S."""
    out = np.full(len(numbers), _NAT)
    ms = numbers * to_ms
    lo, hi = UNIX_WINDOW_S
    ok = np.isfinite(ms) & (ms >= lo * 1000) & (ms <= hi * 1000)
    out[ok] = ms[ok].astype(np.int64).astype("datetime64[ms]")
    return out

def _quarters(values: pd.Series) -> np.ndarray:
    out = np.full(len(values), _NAT)
    for i, value in enumerate(values):
        for pattern in _QUARTERS:
            m = pattern.fullmatch(value)
            if m:
                month = (int(m["q"]) - 1) * 3 + 1
                out[i] = np.datetime64(f"{m['y']}-{month:02d}-01", "ms")
                break
    return out

def date_candidates(
    values: pd.Series, numbers: np.ndarray, *, rng: np.random.Generator, probe: int = 100,
) -> list[tuple[str, np.ndarray]]:
    """Every date reading that fits at least one value. Readings giving identical
    results are merged (the first, more specific name is kept)."""
    n = len(values)
    if n == 0:
        return []
    sample = None if n <= probe else values.iloc[np.sort(rng.choice(n, size=probe, replace=False))]
    found: list[tuple[str, np.ndarray]] = []
    for fmt in DATE_FORMATS:
        if sample is not None and np.isnat(_parse_format(sample, fmt)).all():
            continue  # cheap probe first: skip formats that fit none of the sample
        parsed = _parse_format(values, fmt)
        if not np.isnat(parsed).all():
            found.append((fmt, parsed))
    if np.isfinite(numbers).any():
        found += [("unix_seconds", _unix(numbers, 1000.0)), ("unix_millis", _unix(numbers, 1.0))]
    found.append(("year_quarter", _quarters(values)))

    unique: list[tuple[str, np.ndarray]] = []
    seen: set[bytes] = set()
    for name, parsed in found:
        if np.isnat(parsed).all():
            continue
        key = parsed.view(np.int64).tobytes()
        if key not in seen:
            seen.add(key)
            unique.append((name, parsed))
    return unique

def date_readings(
    values: pd.Series, counts: np.ndarray, weights: np.ndarray, numbers: np.ndarray, *,
    rng: np.random.Generator, min_rate: float = 0.05, max_readings: int = 4,
    failed_limit: int = 3, clip_at: int = 60,
) -> list[DateReading]:
    readings: list[DateReading] = []
    for name, parsed in date_candidates(values, numbers, rng=rng):
        ok = ~np.isnat(parsed)
        rate = _share(ok, weights)
        if rate < min_rate:
            continue
        readings.append(_describe_dates(name, parsed, ok, rate, values, counts, weights, failed_limit, clip_at))
    readings.sort(key=lambda r: -r.parse_rate)  # stable: equal rates keep format order
    return readings[:max_readings]

def _describe_dates(
    name: str, parsed: np.ndarray, ok: np.ndarray, rate: float, values: pd.Series,
    counts: np.ndarray, weights: np.ndarray, failed_limit: int, clip_at: int,
) -> DateReading:
    good = parsed[ok]
    has_time = bool((good.view(np.int64) % 86_400_000 != 0).any())
    distinct = np.unique(good)
    gaps_s = np.diff(distinct).astype(np.int64) / 1000.0
    median_gap = common_gap = common_share = None
    if gaps_s.size:
        median_gap = _duration(float(np.median(gaps_s)))
        gap_values, gap_counts = np.unique(gaps_s, return_counts=True)
        top = int(np.argmax(gap_counts))
        common_gap = _duration(float(gap_values[top]))
        common_share = round(float(gap_counts[top]) / gaps_s.size, 3)
    timezone_rate = 0.0
    if name == ISO and rate > 0:
        tz = values.str.fullmatch(_HAS_TIMEZONE, na=False).to_numpy(dtype=bool)
        timezone_rate = round(_share(tz & ok, weights) / rate, 4)
    return DateReading(
        reading=name,
        parse_rate=round(rate, 4),
        min=_timestamp(distinct[0], has_time),
        max=_timestamp(distinct[-1], has_time),
        distinct=int(distinct.size),
        has_time=has_time,
        timezone_rate=timezone_rate,
        median_gap=median_gap,
        common_gap=common_gap,
        common_gap_share=common_share,
        failed_examples=_failed(values, counts, ~ok, failed_limit, clip_at) if rate < 1 else [],
    )

def _timestamp(value: np.datetime64, has_time: bool) -> str:
    text = np.datetime_as_string(value, unit="s").replace("T", " ")
    return text if has_time else text[:10]

def _duration(seconds: float) -> str:
    """Readable gap: 86400 -> "1d", 900 -> "15m", 2.5 -> "2.5s"."""
    for unit, size in (("d", 86_400), ("h", 3_600), ("m", 60)):
        if seconds >= size:
            return f"{round(seconds / size, 2):g}{unit}"
    return f"{round(seconds, 3):g}s"
