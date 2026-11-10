"""
Checks one piece of AI-written SQL before it runs.

  Layer 1  DuckDB's own parser: exactly one statement, of the expected type (SELECT).
  Layer 2  sqlglot: reads only the loaded tables; no functions that reach files,
           the network or secrets, or that run SQL hidden inside a string.
  Layer 3  the locked engine itself (sandbox.py).

Everything else is allowed, so the AI keeps the full analytic SQL language:
CTEs, joins, window functions, QUALIFY, PIVOT/UNPIVOT, lists, regex, date maths ...
"""
from __future__ import annotations

from typing import Any

import duckdb
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from engine.sql.results import QueryError

MAX_SQL_CHARS = 20_000
ONLY_LOADED_TABLES = "Queries may only read the loaded tables."

# These could reach outside the loaded tables. The engine lock blocks them too; checking
# here as well gives the AI a clear reason instead of a low-level engine error.
BLOCKED_FUNCTIONS = frozenset({
    "query", "query_table",                                   # run SQL hidden inside a string
    "glob", "sniff_csv",                                      # list or inspect files
    "getenv", "duckdb_secrets", "which_secret", "load_aws_credentials",
})
BLOCKED_PREFIXES = ("read_", "parquet_", "iceberg_", "delta_", "sqlite_", "postgres_", "mysql_", "st_read", "http")

def quote_ident(name: str) -> str:
    """Safe SQL name: Store ID -> "Store ID"."""
    return '"' + name.replace('"', '""') + '"'

def short(exc: BaseException, limit: int = 600) -> str:
    text = str(exc).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"

def strip_sql(sql: str) -> str:
    body = sql.strip()
    while body.endswith(";"):
        body = body[:-1].rstrip()
    return body

def check_select(con: duckdb.DuckDBPyConnection, sql: Any, tables: set[str], max_chars: int = MAX_SQL_CHARS) -> str:
    """Return the cleaned SQL if it is one safe SELECT over `tables`; otherwise raise QueryError.
    max_chars is raised only for SQL our code expanded from the AI's shorter text (repeat blocks)."""
    if not isinstance(sql, str) or not sql.strip():
        raise QueryError("blocked", "The query is empty.")
    if len(sql) > max_chars:
        raise QueryError("blocked", f"The query is longer than {max_chars:,} characters.",
                         "Split the work into smaller queries.")
    body = strip_sql(sql)
    check_statement(con, body, duckdb.StatementType.SELECT,
                    "Only read-only SELECT queries are allowed (WITH ... SELECT is fine).")
    _check_tree(body, {t.lower() for t in tables})
    return body

def check_statement(con: duckdb.DuckDBPyConnection, sql: str, expected: Any, message: str) -> None:
    """Layer 1: DuckDB's own parser decides how many statements there are and of what kind."""
    try:
        statements = con.extract_statements(sql)
    except duckdb.Error as exc:
        raise QueryError("syntax", short(exc), "Fix the SQL syntax (DuckDB dialect).") from None
    if len(statements) != 1:
        raise QueryError("blocked", f"Send exactly one query at a time (found {len(statements)}).",
                         "If you used PIVOT without an IN (...) list, list the values explicitly.")
    try:
        kind = statements[0].type
    except Exception:  # statement kinds this client cannot name (e.g. ATTACH)
        kind = None
    if kind != expected:
        raise QueryError("blocked", message, ONLY_LOADED_TABLES)

def _check_tree(body: str, tables: set[str]) -> None:
    """Layer 2: walk the query tree for tables and functions."""
    try:
        trees = [t for t in sqlglot.parse(body, read="duckdb") if t is not None]
    except SqlglotError as exc:
        raise QueryError("unsupported", f"The safety checker could not read this query: {short(exc, 300)}",
                         "Rewrite it with standard SELECT syntax (WITH, JOIN, GROUP BY, window functions).") from None
    if len(trees) != 1 or isinstance(trees[0], exp.Command):
        raise QueryError("blocked", "Only a single SELECT query is allowed.", ONLY_LOADED_TABLES)
    tree = trees[0]

    for func in tree.find_all(exp.Func):
        name = _function_name(func)
        if name in BLOCKED_FUNCTIONS or name.startswith(BLOCKED_PREFIXES):
            raise QueryError("blocked", f"The function {name}() is not allowed.", ONLY_LOADED_TABLES)

    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    unknown: set[str] = set()
    for table in tree.find_all(exp.Table):
        source = table.this
        if source is None or isinstance(source, exp.Func):
            continue                                  # table functions like range(): checked above
        if not isinstance(source, exp.Identifier):
            raise QueryError("blocked", "Reading from files or text paths is not allowed.", ONLY_LOADED_TABLES)
        if table.name.lower() not in tables and table.name.lower() not in ctes:
            unknown.add(table.name)
    if unknown:
        raise QueryError("unknown_table", f"Unknown table(s): {', '.join(sorted(unknown))}.",
                         f"Available tables: {', '.join(sorted(tables))}.")

def _function_name(func: exp.Func) -> str:
    if isinstance(func, exp.Anonymous):
        return str(func.name).lower()
    return func.sql_name().lower()
