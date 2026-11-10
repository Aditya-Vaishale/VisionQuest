"""
Stage 1 loader: read a CSV as plain text.

Every cell stays a string, so nothing is type-guessed wrongly this early.
Works out the encoding, the delimiter and where the table starts (title lines
above it are kept as "preamble"), and records every fix it makes.
"""
from __future__ import annotations

import codecs
import csv
import io
import itertools
import re
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from engine.discover.models import LoadInfo

MAX_FILE_MB = 200
DELIMITERS = (",", ";", "\t", "|")
SNIFF_RECORDS = 200
_NUMBER_LIKE = re.compile(r"[+-]?[\d.,\s]*\d[\d.,\s]*%?")

class LoadError(ValueError):
    """The file cannot be read as a table. The message is safe to show the user."""

@dataclass
class RawTable:
    df: pd.DataFrame       # every cell is a str ("" when empty); nothing type-guessed
    load: LoadInfo

def load_csv(path: str | Path, *, max_mb: float = MAX_FILE_MB) -> RawTable:
    path = Path(path)
    if not path.is_file():
        raise LoadError(f"File not found: {path}")
    if path.stat().st_size > max_mb * 1_048_576:
        raise LoadError(f"The file is larger than the {max_mb:g} MB limit.")
    return load_csv_bytes(path.read_bytes(), file_name=path.name, max_mb=max_mb)

def load_csv_bytes(data: bytes, *, file_name: str = "upload.csv", max_mb: float = MAX_FILE_MB) -> RawTable:
    """Same as load_csv, for bytes already in memory (e.g. a browser upload)."""
    if len(data) > max_mb * 1_048_576:
        raise LoadError(f"The file is larger than the {max_mb:g} MB limit.")
    text, encoding = _decode(data)
    if not text.strip():
        raise LoadError("The file is empty.")
    if "\x00" in text[:8192]:
        raise LoadError("This looks like a binary file (for example an Excel workbook), not a text CSV.")

    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))  # allow long text cells
    delimiter = _detect_delimiter(text)

    records: list[tuple[int, list[str]]] = []
    blank_rows = 0
    try:
        for line, record in _read_records(text, delimiter):
            if _filled(record):
                records.append((line, record))
            else:
                blank_rows += 1
    except csv.Error as exc:
        raise LoadError(f"The file could not be read as CSV: {exc}") from exc
    if not records:
        raise LoadError("No table was found in the file.")

    sniff = [record for _, record in records[:SNIFF_RECORDS]]
    width = Counter(len(r) for r in sniff).most_common(1)[0][0]
    start = _table_start(sniff, width)
    header_line, header = records[start]
    preamble = [_clip(delimiter.join(r).strip(" " + delimiter), 200) for _, r in records[:start]]

    notes: list[str] = []
    has_header = _looks_like_header(header)
    body = records[start + 1:] if has_header else records[start:]
    if not has_header:
        notes.append("The first row looks like data, not column names, so columns were named col_1, col_2, ...")
    if not body:
        raise LoadError("The file has column names but no data rows.")

    # Never drop a filled cell: rows with extra filled fields get extra columns.
    header_fill = max(_last_filled(header), 1) if has_header else width
    full_width = header_fill if has_header else 0
    ragged: list[int] = []
    extra_fields = False
    for line, record in body:
        last = _last_filled(record)
        full_width = max(full_width, last)
        if last > header_fill:
            extra_fields = True
            ragged.append(line)
        elif len(record) < header_fill:
            ragged.append(line)

    if has_header:
        raw_names = [_clean_name(c) for c in header[:full_width]]
        raw_names += [""] * (full_width - len(raw_names))
        names, renamed = _unique_names(raw_names, len(header))
        if extra_fields:
            notes.append("Some rows have more filled fields than there are column names; "
                         "extra columns were added so no data is lost.")
    else:
        names, renamed = [f"col_{i}" for i in range(1, full_width + 1)], {}

    if encoding in ("cp1252", "latin-1"):
        notes.append(f"The text was not valid UTF-8 and was read as {encoding}; check special characters.")

    rows = [r[:full_width] if len(r) >= full_width else r + [""] * (full_width - len(r)) for _, r in body]
    load = LoadInfo(
        file_name=file_name,
        size_bytes=len(data),
        encoding=encoding,
        delimiter=delimiter,
        header_line=header_line if has_header else None,
        preamble=preamble[:10],
        ragged_rows=len(ragged),
        ragged_examples=ragged[:5],
        renamed_columns=renamed,
        blank_rows_dropped=blank_rows,
        notes=notes,
    )
    return RawTable(df=pd.DataFrame(rows, columns=names, dtype=object), load=load)

def _decode(data: bytes) -> tuple[str, str]:
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return data.decode("utf-16"), "utf-16"
        except UnicodeDecodeError as exc:
            raise LoadError("The file is marked as UTF-16 but could not be decoded.") from exc
    if data.startswith(codecs.BOM_UTF8):
        return data[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace"), "utf-8 (with BOM)"
    for encoding in ("utf-8", "cp1252"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1"), "latin-1"  # never fails: every byte is a character

def _read_records(text: str, delimiter: str) -> Iterator[tuple[int, list[str]]]:
    """Yield (line number, fields) per CSV record; quoted fields may span lines."""
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, quotechar='"', strict=False)
    for record in reader:
        yield reader.line_num, record

def _detect_delimiter(text: str) -> str:
    """The delimiter that splits the most rows into the same number of fields."""
    head = text[:65_536]
    best, best_score = ",", (0.0, 0)
    for delimiter in DELIMITERS:
        try:
            filled = (r for _, r in _read_records(head, delimiter) if _filled(r))
            widths = [len(r) for r in itertools.islice(filled, SNIFF_RECORDS)]
        except csv.Error:
            continue
        if not widths:
            continue
        width, freq = Counter(widths).most_common(1)[0]
        if width < 2:
            continue
        score = (freq / len(widths), width)
        if score > best_score:
            best, best_score = delimiter, score
    return best

def _table_start(records: list[list[str]], width: int) -> int:
    """The header: first well-filled row followed by rows of the usual width.
    Rows above it (report titles, export notes) become the preamble."""
    def table_like(r: list[str]) -> bool:
        return abs(len(r) - width) <= 1

    need = max(2, (width + 1) // 2) if width > 1 else 1
    for i, record in enumerate(records):
        if not table_like(record) or _last_filled(record) < need:
            continue
        following = records[i + 1:i + 4]
        if sum(table_like(r) for r in following) >= min(2, len(following)):
            return i
    return 0

def _looks_like_header(record: list[str]) -> bool:
    filled = [c.strip() for c in record if c.strip()]
    return bool(filled) and not all(_NUMBER_LIKE.fullmatch(c) for c in filled)

def _filled(record: list[str]) -> bool:
    return any(c.strip() for c in record)

def _last_filled(record: list[str]) -> int:
    for i in range(len(record) - 1, -1, -1):
        if record[i].strip():
            return i + 1
    return 0

def _clean_name(name: str) -> str:
    return " ".join(name.replace("\ufeff", "").split())

def _unique_names(raw: list[str], header_len: int) -> tuple[list[str], dict[str, str]]:
    """Fill blank names and de-duplicate (case-insensitively, as SQL does)."""
    names: list[str] = []
    renamed: dict[str, str] = {}
    seen: set[str] = {"_row"}
    for i, original in enumerate(raw, start=1):
        base = original or (f"column_{i}" if i <= header_len else f"extra_{i - header_len}")
        name, k = base, 2
        while name.casefold() in seen:
            name, k = f"{base}_{k}", k + 1
        seen.add(name.casefold())
        names.append(name)
        if name != original:
            renamed[name] = original
    return names, renamed

def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
