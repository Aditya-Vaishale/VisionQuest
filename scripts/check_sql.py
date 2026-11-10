"""
Step 3 check: the SQL safety layer lets analysis through and stops everything else.

Run from the project folder:  python -m scripts.check_sql
Needs the sample files first:  python -m scripts.make_test_csvs
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

from engine.discover import load_csv
from engine.sql import QueryError, Sandbox, SandboxLimits

SALES = Path(__file__).resolve().parent.parent / "samples" / "03_sales_with_totals.csv"
STOPPED = {"blocked", "unknown_table", "unsupported"}

ALLOWED = [
    ("group by (subtotal rows show up)",
     "SELECT region, SUM(TRY_CAST(units AS INTEGER)) AS units FROM raw GROUP BY region ORDER BY units DESC"),
    ("CTE + window + QUALIFY",
     "WITH t AS (SELECT region, product, TRY_CAST(units AS INTEGER) AS u FROM raw WHERE product <> '') "
     "SELECT region, product, u, RANK() OVER (PARTITION BY region ORDER BY u DESC) AS rnk FROM t QUALIFY rnk = 1"),
    ("DuckDB extras (EXCLUDE, ILIKE)", "SELECT * EXCLUDE (product) FROM raw WHERE region ILIKE '%total%'"),
    ("trailing semicolon", "SELECT count(*) AS n FROM raw;"),
    ("comment that looks like an attack", "SELECT 1 AS x /* ; DROP TABLE raw */"),
    ("big result is cut to the row limit", "SELECT n FROM range(1000) AS t(n)"),
]

ATTACKS = [
    ("drop a table", "DROP TABLE raw", STOPPED),
    ("delete rows", "DELETE FROM raw", STOPPED),
    ("two statements", "SELECT 1; DROP TABLE raw", STOPPED),
    ("read a system file", "SELECT * FROM read_csv('/etc/hosts')", STOPPED),
    ("read the API key file", "SELECT * FROM read_text('.env')", STOPPED),
    ("file path used as a table", "SELECT * FROM '.env'", STOPPED),
    ("list files", "SELECT * FROM glob('*')", STOPPED),
    ("SQL hidden in a string", "SELECT * FROM query('DROP TABLE raw')", STOPPED),
    ("read an environment variable", "SELECT getenv('HOME') AS home", STOPPED),
    ("write a file", "COPY raw TO 'leak.csv'", STOPPED),
    ("attach another database", "ATTACH 'other.db' AS other", STOPPED),
    ("install an extension", "INSTALL httpfs", STOPPED),
    ("change a safety setting", "SET enable_external_access = true", STOPPED),
    ("unknown table", "SELECT * FROM salaries", {"unknown_table"}),
    ("read a Python variable", "SELECT * FROM secret_df", {"unknown_table"}),
    ("misspelled column (normal mistake)", "SELECT revenue_total FROM raw", {"unknown_name"}),
]

CLEAN_SQL = ("SELECT region, product, TRY_CAST(units AS INTEGER) AS units, "
             "TRY_CAST(replace(revenue, ',', '') AS DOUBLE) AS revenue "
             "FROM raw WHERE region NOT ILIKE '%total%'")
# Big enough to need the time limit, small enough to finish (~1 min) if the limit ever failed.
RUNAWAY_SQL = "SELECT count(*) AS n FROM range(200000) AS a(x), range(200000) AS b(y) WHERE (x * y) % 7 = 3"

def report(ok: bool, label: str, note: str) -> bool:
    print(f"  {'✓' if ok else '✗'} {label:<40} {note}")
    return ok

def one_line(text: str, limit: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"

def main() -> int:
    if not SALES.is_file():
        print("✗ Sample files not found. Run first: python -m scripts.make_test_csvs")
        return 1
    secret_df = pd.DataFrame({"password": ["hunter2"]})  # noqa: F841  SQL must not be able to read this
    raw = load_csv(SALES)
    results: list[bool] = []

    with Sandbox.from_raw(raw) as box:
        print("Engine lock")
        for setting, value in box.hardening.items():
            print(f"  {setting}: {value}")

        print("\nAllowed: should run")
        first = None
        for label, sql in ALLOWED:
            try:
                r = box.run(sql)
            except QueryError as err:
                results.append(report(False, label, f"{err.kind}: {one_line(err.message)}"))
                continue
            first = first or r
            ok = (r.truncated and len(r.rows) == box.limits.max_rows) if label.startswith("big") else True
            cut = " (cut to limit)" if r.truncated else ""
            results.append(report(ok, label, f"{len(r.rows)} rows{cut}, {r.seconds:.3f}s"))

        print("\nAttacks and mistakes: should be stopped")
        for label, sql, expected in ATTACKS:
            try:
                box.run(sql)
            except QueryError as err:
                results.append(report(err.kind in expected, label, f"{err.kind}: {one_line(err.message)}"))
            else:
                results.append(report(False, label, "RAN - should have been stopped"))

        print("\nSaved copy (the Clean stage will use this)")
        try:
            rows = box.create_table("clean", CLEAN_SQL)
            results.append(report(rows == 20, "save cleaned copy as 'clean'", f"{rows} rows (subtotals removed)"))
            total = box.run("SELECT round(sum(revenue), 2) AS total FROM clean").rows[0][0]
            grand = box.run("SELECT TRY_CAST(replace(revenue, ',', '') AS DOUBLE) AS grand "
                            "FROM raw WHERE region = 'Grand Total'").rows[0][0]
            results.append(report(abs(total - grand) < 0.01, "clean total matches file's Grand Total",
                                  f"{total:,.2f} vs {grand:,.2f}"))
        except QueryError as err:
            results.append(report(False, "save cleaned copy as 'clean'", f"{err.kind}: {one_line(err.message)}"))
        try:
            box.create_table("raw", "SELECT 1 AS x")
        except QueryError as err:
            results.append(report(err.kind == "blocked", "original 'raw' cannot be replaced", err.kind))
        else:
            results.append(report(False, "original 'raw' cannot be replaced", "REPLACED - should be blocked"))
        intact = box.run("SELECT count(*) AS n FROM raw").rows[0][0]
        results.append(report(intact == 25, "raw table untouched after all attacks", f"{intact} rows"))

        print("\nWhat the AI receives for the first allowed query:")
        print(" ", first.to_llm() if first else "-")
        outcomes: dict[str, int] = {}
        for entry in box.log:
            outcomes[entry.outcome] = outcomes.get(entry.outcome, 0) + 1
        summary = ", ".join(f"{kind} {count}" for kind, count in sorted(outcomes.items()))
        print(f"\nAudit log: {len(box.log)} queries recorded ({summary})")

    print("\nTime limit")
    with Sandbox.from_raw(raw, SandboxLimits(timeout_s=2)) as slow:
        started = time.perf_counter()
        try:
            slow.run(RUNAWAY_SQL)
        except QueryError as err:
            took = time.perf_counter() - started
            results.append(report(err.kind == "timeout" and took < 10, "runaway query is stopped",
                                  f"{err.kind} after {took:.1f}s"))
        else:
            results.append(report(False, "runaway query is stopped", "finished - time limit not enforced"))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1

if __name__ == "__main__":
    sys.exit(main())
