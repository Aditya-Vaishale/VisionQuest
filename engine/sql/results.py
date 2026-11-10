"""What a query gives back: a result, or a plain-language error the AI can act on."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

MAX_CELL_CHARS = 200  # long text cells are clipped before the AI sees them

class QueryError(Exception):
    """Blocked or failed query. `kind` is stable for code; `message` and `hint` are for the AI."""

    def __init__(self, kind: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.hint = hint

    def to_llm(self) -> str:
        payload = {"ok": False, "error": self.kind, "message": self.message}
        if self.hint:
            payload["hint"] = self.hint
        return json.dumps(payload, ensure_ascii=False)

@dataclass(frozen=True)
class QueryResult:
    sql: str
    columns: list[str]
    types: list[str]
    rows: list[tuple[Any, ...]]   # Python values exactly as DuckDB returned them
    truncated: bool               # more rows existed than the row limit
    seconds: float

    def to_llm(self, max_chars: int = 12_000) -> str:
        """Compact JSON for the AI: as many rows as fit in max_chars."""
        shown: list[list[Any]] = []
        used = 200 + len(json.dumps(self.columns, ensure_ascii=False)) + len(json.dumps(self.types))
        for row in self.rows:
            item = [jsonable(v) for v in row]
            size = len(json.dumps(item, ensure_ascii=False)) + 1
            if shown and used + size > max_chars:
                break
            shown.append(item)
            used += size
        payload: dict[str, Any] = {"ok": True, "columns": self.columns, "types": self.types, "rows": shown}
        if self.truncated or len(shown) < len(self.rows):
            payload["note"] = (f"Showing the first {len(shown)} rows only; more exist. "
                               "Aggregate, filter, or ORDER BY ... LIMIT to see what matters.")
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

def jsonable(value: Any) -> Any:
    """Any DuckDB value -> something JSON can hold (dates as ISO text, NaN as text...)."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return value if len(value) <= MAX_CELL_CHARS else value[: MAX_CELL_CHARS - 1] + "…"
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    return str(value)  # UUIDs, intervals, anything else
