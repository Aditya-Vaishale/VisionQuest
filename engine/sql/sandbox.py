"""
The locked room where all SQL runs.

One in-memory DuckDB per dataset. Data is loaded first, then the engine is locked:
no files, no network, no extensions, memory/thread caps, settings frozen.
It then tries to break its own lock and refuses to start if it can (fail closed).
Every AI query (allowed, blocked or failed) is logged for auditing.
"""
from __future__ import annotations

import re
import tempfile
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from engine import timing
import duckdb
import pandas as pd

from engine.discover.loader import RawTable
from engine.sql.guard import MAX_SQL_CHARS, check_select, check_statement, quote_ident, short
from engine.sql.results import QueryError, QueryResult

ROW_ID = "_row"   # added to raw: 1-based data row number in the file, so every row stays traceable
_TABLE_NAME = re.compile(r"[a-z][a-z0-9_]{0,62}")
_MEMORY = re.compile(r"\d+(?:\.\d+)?\s*(?:KB|MB|GB|TB|KiB|MiB|GiB|TiB)", re.IGNORECASE)

def _exceptions(*names: str) -> tuple[type[BaseException], ...]:
    """DuckDB exception classes by name, skipping any this DuckDB version lacks."""
    found = (getattr(duckdb, n, None) for n in names)
    return tuple(c for c in found if isinstance(c, type) and issubclass(c, BaseException))

# Engine error -> (kind, hint for the AI). First match wins.
_ERRORS = (
    (_exceptions("InterruptException"), "timeout",
     "Filter or aggregate earlier, and avoid joins that multiply rows."),
    (_exceptions("OutOfMemoryException"), "too_big",
     "Aggregate, select fewer columns, or avoid joins that multiply rows."),
    (_exceptions("PermissionException"), "blocked", "Queries may only read the loaded tables."),
    (_exceptions("ParserException"), "syntax", "Fix the SQL syntax (DuckDB dialect)."),
    (_exceptions("BinderException", "CatalogException"), "unknown_name",
     'Check table and column names; wrap names with spaces or capitals in double quotes, e.g. "Store ID".'),
    (_exceptions("ConversionException"), "conversion",
     "Some values could not be converted; TRY_CAST turns bad values into NULL."),
    (_exceptions("InvalidInputException", "OutOfRangeException"), "invalid_input",
     "Check function arguments and value ranges."),
)

@dataclass(frozen=True)
class SandboxLimits:
    timeout_s: float = 15.0
    max_rows: int = 200         # rows returned per query
    memory_limit: str = "2GB"
    threads: int = 4

@dataclass(frozen=True)
class QueryLogEntry:
    at: str
    purpose: str
    sql: str
    outcome: str                # "ok" or the error kind
    seconds: float
    rows: int | None = None
    message: str | None = None

class SandboxError(RuntimeError):
    """The engine could not be locked safely, so nothing will run."""

class Sandbox:
    """One locked, in-memory DuckDB per dataset. All AI-written SQL runs here."""

    def __init__(self, tables: dict[str, pd.DataFrame], limits: SandboxLimits | None = None) -> None:
        self.limits = limits or SandboxLimits()
        if not _MEMORY.fullmatch(self.limits.memory_limit.strip()):
            raise SandboxError(f"memory_limit must look like '2GB', got {self.limits.memory_limit!r}")
        self.log: list[QueryLogEntry] = []
        self.hardening: dict[str, str] = {}
        self._tables: set[str] = set()     # every table queries may read
        self._sources: set[str] = set()    # original tables: never replaced
        self._lock = threading.RLock()
        self._con = duckdb.connect(":memory:")
        try:
            for name, frame in tables.items():
                self._load(name, frame)
            self._lock_engine()
            self._prove_lock()
        except BaseException:
            self._con.close()
            raise

    @classmethod
    def from_raw(cls, raw: RawTable, limits: SandboxLimits | None = None) -> Sandbox:
        """Sandbox holding the uploaded file as table `raw` (all text, as loaded), plus _row:
        the 1-based data row number, so every later row can be traced back to the file."""
        frame = raw.df.copy()
        frame.insert(0, ROW_ID, range(1, len(frame) + 1))
        return cls({"raw": frame}, limits)

    # ------------------------------------------------------------------ public API

    @property
    def tables(self) -> list[str]:
        return sorted(self._tables)

    def schema(self) -> dict[str, list[tuple[str, str]]]:
        """Table -> [(column, type)], read by our own code (not AI SQL)."""
        with self._lock:
            out: dict[str, list[tuple[str, str]]] = {}
            for name in self.tables:
                relation = self._con.table(name)
                out[name] = list(zip(relation.columns, (str(t) for t in relation.types)))
            return out

    def describe(self, table: str, max_columns: int = 80) -> dict[str, object]:
        """Columns, types and row count of one table (read by our own code, for the Look tool)."""
        with self._lock:
            key = self._known(table)
            columns = self.schema()[key]
            rows = int(self._con.execute(f"SELECT count(*) FROM {quote_ident(key)}").fetchone()[0])
        info: dict[str, object] = {
            "ok": True, "table": key, "rows": rows, "column_count": len(columns),
            "columns": [[c, t] for c, t in columns[:max_columns]],
        }
        if len(columns) > max_columns:
            info["note"] = f"{len(columns) - max_columns} more columns not listed; look at one by name."
        return info

    def column_values(self, table: str, column: str, max_rows: int = 1_000_000) -> tuple[str, int, pd.Series]:
        """One column as a pandas Series, read by our own code (for the Look tool).
        Returns (exact column name, 1-based position, values)."""
        with self._lock:
            key = self._known(table)
            names = [c for c, _ in self.schema()[key]]
            match = next((n for n in names if n == column), None) or \
                next((n for n in names if n.casefold() == str(column).casefold()), None)
            if match is None:
                raise QueryError("unknown_name", f"Column {column!r} not found in {key}.",
                                 "Use look on the table to list its columns.")
            frame = self._con.sql(f"SELECT {quote_ident(match)} FROM {quote_ident(key)} LIMIT {int(max_rows)}").df()
        return match, names.index(match) + 1, frame.iloc[:, 0]

    def table_frame(self, table: str, max_rows: int = 1_000_000) -> pd.DataFrame:
        """A whole table as pandas (our own code; e.g. to run Discover again on the cleaned copy)."""
        with self._lock:
            key = self._known(table)
            return self._con.sql(f"SELECT * FROM {quote_ident(key)} LIMIT {int(max_rows)}").df()

    def trusted_query(self, sql: str, max_rows: int = 10_000) -> list[tuple]:
        """ONLY for SQL built by our own code (reports, checks). Never pass AI-written SQL here:
        it skips the guard and the audit log (the engine lock and time limit still apply)."""
        with self._lock:
            _, _, rows = self._execute(sql, fetch=max_rows)
            return rows

    def run(self, sql: str, *, purpose: str = "query", max_rows: int | None = None,
            tables: Iterable[str] | None = None) -> QueryResult:
        """Run one read-only SELECT exactly as written and keep the first rows.
        `tables` limits which tables this query may read (None = all).
        Raises QueryError (blocked or failed) with an AI-readable reason."""
        limit = max(1, int(max_rows or self.limits.max_rows))
        allowed = self._tables if tables is None else self._tables & {str(t).lower() for t in tables}
        started = time.perf_counter()
        with self._lock:
            try:
                body = check_select(self._con, sql, allowed)
                columns, types, rows = self._execute(body, fetch=limit + 1)
            except QueryError as err:
                self._record(purpose, sql, err.kind, started, message=err.message)
                raise
        result = QueryResult(
            sql=body, columns=columns, types=types, rows=rows[:limit],
            truncated=len(rows) > limit, seconds=round(time.perf_counter() - started, 4),
        )
        self._record(purpose, sql, "ok", started, rows=len(result.rows))
        return result

    def create_table(self, name: str, sql: str, *, purpose: str = "save table",
                     max_sql_chars: int | None = None) -> int:
        """Save a SELECT's result as a new table (e.g. the cleaned copy). Returns its row count.
        Original tables are never replaced; a table cannot be built from itself.
        max_sql_chars: only for SQL our code expanded from the AI's shorter text."""
        started = time.perf_counter()
        label = f"[{name}] {sql}"
        with self._lock:
            try:
                key = _table_key(name)
                if key in self._sources:
                    raise QueryError("blocked", f"'{key}' is an original table and cannot be replaced.",
                                     "Save the result under a new name, e.g. clean.")
                body = check_select(self._con, sql, self._tables - {key}, max_chars=max_sql_chars or MAX_SQL_CHARS)
                wrapped = f"CREATE OR REPLACE TABLE {quote_ident(key)} AS\n{body}\n"
                check_statement(self._con, wrapped, duckdb.StatementType.CREATE, "Internal safety check failed.")
                self._execute(wrapped, fetch=None)
                rows = int(self._con.execute(f"SELECT count(*) FROM {quote_ident(key)}").fetchone()[0])
            except QueryError as err:
                self._record(purpose, label, err.kind, started, message=err.message)
                raise
            self._tables.add(key)
        self._record(purpose, label, "ok", started, rows=rows)
        return rows

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ setup

    def _load(self, name: str, frame: pd.DataFrame) -> None:
        key = _table_key(name)
        view = f"_load_{key}"
        self._con.register(view, frame)
        try:
            self._con.execute(f"CREATE TABLE {quote_ident(key)} AS SELECT * FROM {quote_ident(view)}")
        finally:
            self._con.unregister(view)
        self._tables.add(key)
        self._sources.add(key)

    def _lock_engine(self) -> None:
        settings = (
            ("enable_external_access", "false", True),         # no files, no network
            ("allow_community_extensions", "false", True),
            ("autoinstall_known_extensions", "false", True),
            ("autoload_known_extensions", "false", True),
            ("python_enable_replacements", "false", False),    # no reading Python variables by name
            ("memory_limit", f"'{self.limits.memory_limit.strip()}'", True),
            ("threads", str(max(1, int(self.limits.threads))), True),
            ("lock_configuration", "true", True),             # last: freezes everything above
        )
        for name, value, required in settings:
            try:
                self._con.execute(f"SET {name} = {value}")
            except duckdb.Error as exc:
                if required:
                    raise SandboxError(f"Could not apply safety setting {name}: {short(exc)}") from exc
                self.hardening[name] = "not available in this DuckDB version"
            else:
                self.hardening[name] = value.strip("'")

    def _prove_lock(self) -> None:
        """Fail closed: try forbidden things directly on the engine, skipping the guard."""
        with tempfile.TemporaryDirectory() as folder:
            probe = Path(folder) / "probe.csv"
            probe.write_text("a\n1\n", encoding="utf-8")
            path = str(probe).replace("'", "''")
            try:
                self._con.execute(f"SELECT * FROM read_csv('{path}')").fetchall()
            except duckdb.Error as exc:
                if not _is_permission_error(exc):
                    raise SandboxError(f"Could not confirm that file access is blocked: {short(exc)}") from exc
            else:
                raise SandboxError("Safety check failed: the engine could read a file.")
        self.hardening["file_access_probe"] = "blocked"
        try:
            self._con.execute("SET enable_external_access = true")
        except duckdb.Error:
            self.hardening["settings_change_probe"] = "blocked"
        else:
            raise SandboxError("Safety check failed: engine settings could be changed.")

    # ------------------------------------------------------------------ internals

    def _known(self, table: str) -> str:
        key = str(table).strip().lower()
        if key not in self._tables:
            raise QueryError("unknown_table", f"Unknown table {table!r}.", f"Available tables: {', '.join(self.tables)}.")
        return key

    def _execute(self, sql: str, *, fetch: int | None) -> tuple[list[str], list[str], list[tuple]]:
        """Run with a time limit. fetch=None: run only; fetch=n: return the first n rows."""
        timer = threading.Timer(self.limits.timeout_s, self._con.interrupt)
        timer.daemon = True
        started = time.perf_counter()
        timer.start()
        try:
            if fetch is None:
                self._con.execute(sql)
                return [], [], []
            relation = self._con.sql(sql)                   # binds only: column names and types
            columns = list(relation.columns)
            types = [str(t) for t in relation.types]
            rows = self._con.execute(sql).fetchmany(fetch)  # the query exactly as written
            return columns, types, rows
        except duckdb.Error as exc:
            raise _translate(exc, self.limits.timeout_s) from None
        except Exception as exc:  # e.g. a value Python cannot represent
            raise QueryError("error", f"{type(exc).__name__}: {short(exc)}") from None
        finally:
            timer.cancel()
            timing.sql(time.perf_counter() - started, sql)

    def _record(self, purpose: str, sql: object, outcome: str, started: float, *,
                rows: int | None = None, message: str | None = None) -> None:
        text = str(sql)
        self.log.append(QueryLogEntry(
            at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            purpose=purpose,
            sql=text if len(text) <= 4000 else text[:3999] + "…",
            outcome=outcome,
            seconds=round(time.perf_counter() - started, 4),
            rows=rows,
            message=message,
        ))

def _table_key(name: str) -> str:
    key = str(name).strip()
    if not _TABLE_NAME.fullmatch(key):
        raise QueryError("blocked", f"Invalid table name {name!r}.",
                         "Use lowercase letters, digits and _ (start with a letter), e.g. clean.")
    return key

def _is_permission_error(exc: BaseException) -> bool:
    permission = _exceptions("PermissionException")
    text = str(exc).lower()
    return (bool(permission) and isinstance(exc, permission)) or "permission" in text or "disabled by configuration" in text

def _translate(exc: BaseException, timeout_s: float) -> QueryError:
    for classes, kind, hint in _ERRORS:
        if classes and isinstance(exc, classes):
            message = f"The query ran longer than {timeout_s:g}s and was stopped." if kind == "timeout" else short(exc)
            return QueryError(kind, message, hint)
    return QueryError("error", short(exc))
