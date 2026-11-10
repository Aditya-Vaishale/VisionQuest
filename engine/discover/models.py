"""
Fact sheet types for Stage 1 (Discover).

Facts only: what the data LOOKS like (blanks, patterns, parse rates, keys).
Never what it MEANS; that is the AI's job in the Reason stage.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

FACT_SHEET_VERSION = "discover-2"   # bump whenever facts change (cached plans depend on it)

class ValueCount(BaseModel):
    value: str
    count: int

class ShapeShare(BaseModel):
    """Value pattern: digits -> 9, letters -> A, repeats collapsed. "$1,234.50" -> "$9,9.9"."""
    shape: str
    share: float                       # share of non-blank rows
    example: str

class LengthStats(BaseModel):
    min: int
    mean: float
    max: int

class NumberReading(BaseModel):
    """One way of reading the text as numbers, and how well it fits."""
    reading: str                       # "as_is" | "symbols_us" | "symbols_eu"
    parse_rate: float                  # share of non-blank rows that become numbers
    failed_examples: list[ValueCount] = Field(default_factory=list)
    symbols_removed: list[str] = Field(default_factory=list)
    percent_sign_rate: float = 0.0
    parentheses_rate: float = 0.0      # "(1,200)" read as -1200
    ambiguous_rate: float = 0.0        # rows that mean different numbers in US vs EU style

class NumberStats(BaseModel):
    reading: str
    min: float
    p01: float
    p25: float
    median: float
    p75: float
    p99: float
    max: float
    mean: float
    std: float
    integer_rate: float
    negative_rate: float
    zero_rate: float
    leading_zero_rate: float = 0.0     # "00123"-style text; turning it into numbers would lose zeros
    rising_rate: float | None = None   # share of row-to-row steps (file order) that do not go down

class DateReading(BaseModel):
    """One way of reading the text as dates/times, and how well it fits."""
    reading: str                       # strftime pattern, "ISO8601", "unix_seconds", "unix_millis", "year_quarter"
    parse_rate: float
    min: str
    max: str
    distinct: int
    has_time: bool
    timezone_rate: float = 0.0
    median_gap: str | None = None      # between consecutive distinct values, e.g. "1d", "15m"
    common_gap: str | None = None
    common_gap_share: float | None = None
    failed_examples: list[ValueCount] = Field(default_factory=list)

class ColumnFacts(BaseModel):
    position: int                      # 1-based
    name: str
    storage: str                       # "text" | "integer" | "decimal" | "datetime" | "boolean"
    rows: int
    blank: int
    blank_rate: float
    distinct: int
    distinct_rate: float               # distinct / non-blank
    all_unique: bool                   # no blanks and every value different
    top_values: list[ValueCount] = Field(default_factory=list)
    samples: list[str] = Field(default_factory=list)
    shapes: list[ShapeShare] = Field(default_factory=list)
    length: LengthStats | None = None
    space_padded_rate: float = 0.0     # values with leading/trailing spaces
    number_readings: list[NumberReading] = Field(default_factory=list)
    number_stats: NumberStats | None = None
    date_readings: list[DateReading] = Field(default_factory=list)
    estimated: bool = False            # parse tests used a sample of the distinct values

    def kind(self) -> str:
        """What the values mostly read as: "number", "date", "number_or_date" (equally well),
        or the storage type when neither fits at least half the rows. A label, not a meaning."""
        number = max((r.parse_rate for r in self.number_readings), default=0.0)
        date = self.date_readings[0].parse_rate if self.date_readings else 0.0
        if max(number, date) < 0.5:
            return self.storage
        if number >= 0.5 and date == number:
            return "number_or_date"
        return "date" if date > number else "number"

class LoadInfo(BaseModel):
    file_name: str
    size_bytes: int
    encoding: str
    delimiter: str
    header_line: int | None            # 1-based line in the file; None = no header row
    preamble: list[str] = Field(default_factory=list)              # lines above the table
    ragged_rows: int = 0               # rows with missing or extra fields
    ragged_examples: list[int] = Field(default_factory=list)       # 1-based line numbers
    renamed_columns: dict[str, str] = Field(default_factory=dict)  # new name -> original header
    blank_rows_dropped: int = 0
    notes: list[str] = Field(default_factory=list)

class HeaderDates(BaseModel):
    """Column NAMES that read as dates: a sign that time runs across columns."""
    reading: str
    columns: list[str]

class KeyCandidate(BaseModel):
    """Columns whose values never repeat (together): what could identify one row."""
    columns: list[str]
    kinds: list[str]                   # kind of each column, so an ID can be told from an amount
    grid_fill: float | None = None     # pairs: rows / all possible combinations (1.0 = every combination present)
    luck_chance: float | None = None   # pairs: chance random values would be unique anyway (birthday maths)

class FactSheet(BaseModel):
    version: str = FACT_SHEET_VERSION
    load: LoadInfo | None = None       # None when profiling an in-memory table (e.g. the cleaned copy)
    rows: int
    column_count: int
    duplicate_rows: int
    candidate_keys: list[KeyCandidate] = Field(default_factory=list)
    header_dates: list[HeaderDates] = Field(default_factory=list)
    columns: list[ColumnFacts]
