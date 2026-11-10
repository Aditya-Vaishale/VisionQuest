"""
Create 8 tricky test CSVs in samples/. Same files on every run (fixed seeds).
Each hides a trap the product must handle without fixed rules.

Run from the project folder:  python -m scripts.make_test_csvs
"""
from __future__ import annotations

import csv
import math
import random
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "samples"

def _write(name: str, header: Sequence, rows: Sequence[Sequence], *, delimiter: str = ",",
           encoding: str = "utf-8", preamble: Sequence[str] = ()) -> Path:
    path = OUT / name
    with path.open("w", newline="", encoding=encoding) as f:
        for line in preamble:
            f.write(line + "\n")
        writer = csv.writer(f, delimiter=delimiter, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path

def _eu(x: float) -> str:
    """12345.6 -> '12.345,60' (European style)."""
    return f"{x:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")

def leave_requests(rng: random.Random) -> Path:
    departments = ["Engineering", "Sales", "Finance", "HR", "Support"]
    staff = {f"EMP{i:03d}": rng.choice(departments) for i in range(1, 41)}
    reasons = {
        "Annual": ["Family trip", "Vacation", ""], "Sick": ["Fever", "Medical appointment", ""],
        "Casual": ["Personal work", ""], "Parental": ["Childcare"], "Unpaid": ["Extended travel", ""],
    }
    rows = []
    for i in range(1, 301):
        emp = rng.choice(sorted(staff))
        kind = rng.choices(list(reasons), weights=[40, 30, 20, 4, 6])[0]
        if kind == "Parental":
            days = rng.randint(20, 60)
        elif kind == "Annual":
            days = rng.randint(1, 10)
        else:
            days = rng.randint(1, 3)
        start = date(2024, 1, 1) + timedelta(days=rng.randrange(366))
        end = start + timedelta(days=days - 1)
        status = rng.choices(["Approved", "Pending", "Rejected", "Cancelled"], weights=[75, 8, 9, 8])[0]
        applied = start - timedelta(days=rng.randint(0, 30))
        rows.append([f"LR{i:04d}", emp, staff[emp], kind, start.isoformat(), end.isoformat(),
                     days, status, rng.choice(reasons[kind]), applied.isoformat()])
    header = ["request_id", "employee_id", "department", "leave_type", "start_date", "end_date",
              "days", "status", "reason", "applied_on"]
    return _write("01_leave_requests.csv", header, rows)

def bank_balances(rng: random.Random) -> Path:
    accounts = {"ACC-1001": ("Savings", 12_000.0), "ACC-1002": ("Checking", 3_500.0),
                "ACC-1003": ("Savings", 48_000.0), "ACC-1004": ("Business", 91_000.0),
                "ACC-1005": ("Checking", 800.0)}
    balance = {acc: opening for acc, (_, opening) in accounts.items()}
    rows = []
    for day in range(120):
        d = (date(2024, 1, 1) + timedelta(days=day)).isoformat()
        for acc, (kind, _) in accounts.items():
            deposit = round(rng.uniform(50, 2_500), 2) if rng.random() < 0.3 else 0.0
            withdrawal = round(rng.uniform(20, 900), 2) if rng.random() < 0.4 else 0.0
            withdrawal = min(withdrawal, round(balance[acc] + deposit, 2))
            balance[acc] = round(balance[acc] + deposit - withdrawal, 2)
            rows.append([d, acc, kind, f"{balance[acc]:.2f}", f"{deposit:.2f}", f"{withdrawal:.2f}"])
    header = ["date", "account_id", "account_type", "closing_balance", "deposits", "withdrawals"]
    return _write("02_bank_balances.csv", header, rows)

def sales_with_totals(rng: random.Random) -> Path:
    prices = {"Widget A": 19.99, "Widget B": 24.50, "Gadget C": 89.00, "Gadget D": 129.99, "Tool E": 9.75}
    rows, grand_units, grand_revenue = [], 0, 0.0
    for region in ["North", "South", "East", "West"]:
        units_total, revenue_total = 0, 0.0
        for product, price in prices.items():
            units = rng.randint(20, 400)
            revenue = round(units * price, 2)
            units_total += units
            revenue_total += revenue
            rows.append([region, product, units, f"{revenue:,.2f}"])
        rows.append([f"{region} Total", "", units_total, f"{revenue_total:,.2f}"])
        grand_units += units_total
        grand_revenue += revenue_total
    rows.append(["Grand Total", "", grand_units, f"{grand_revenue:,.2f}"])
    return _write("03_sales_with_totals.csv", ["region", "product", "units", "revenue"], rows)

def api_logs(rng: random.Random) -> Path:
    endpoints = [("/api/orders", "GET", 120), ("/api/orders", "POST", 260), ("/api/users", "GET", 80),
                 ("/api/search", "GET", 340), ("/api/payments", "POST", 520)]
    start = datetime(2024, 6, 3)
    events = []
    for hour in range(72):
        h = hour % 24
        if h < 6:
            volume = 4
        elif h < 22:
            volume = int(20 + 60 * math.sin(math.pi * (h - 6) / 16))
        else:
            volume = 8
        for _ in range(volume):
            ts = start + timedelta(hours=hour, seconds=rng.uniform(0, 3600))
            endpoint, method, typical_ms = rng.choice(endpoints)
            if method == "POST":
                status = rng.choices([200, 201, 400, 404, 500, 503], weights=[85, 6, 3, 2, 3, 1])[0]
            else:
                status = rng.choices([200, 304, 404, 500], weights=[90, 4, 3, 3])[0]
            latency = rng.lognormvariate(math.log(typical_ms), 0.45) * (3 if status >= 500 else 1)
            events.append((ts, endpoint, method, status, round(latency, 1), f"u{rng.randint(1, 300):04d}"))
    events.sort(key=lambda e: e[0])
    rows = [[f"{ts:%Y-%m-%dT%H:%M:%S}.{ts.microsecond // 1000:03d}Z", *rest] for ts, *rest in events]
    header = ["timestamp", "endpoint", "method", "status_code", "latency_ms", "user_id"]
    return _write("04_api_logs.csv", header, rows)

def survey(rng: random.Random) -> Path:
    comments = ["Great service, will come back!", 'Staff said "please wait", took 20 mins',
                "App crashes on login; please fix", "Okay overall", "Too expensive, but good quality",
                "Delivery was late\nbut support helped", "", "", ""]
    rows = []
    for i in range(1, 251):
        submitted = datetime(2024, 3, 1, 8, 0) + timedelta(minutes=rng.randint(0, 60 * 24 * 30))
        channels = ";".join(sorted(rng.sample(["Email", "Phone", "Chat", "Store"], rng.randint(1, 3))))
        recommend = rng.randint(0, 10) if rng.random() > 0.05 else ""
        rows.append([
            f"R{i:04d}", f"{submitted:%m/%d/%Y %H:%M}",
            rng.choice(["18-24", "25-34", "35-44", "45-54", "55+"]),
            rng.choices([1, 2, 3], weights=[48, 48, 4])[0],                # gender as a code, not a score
            rng.choices([1, 2, 3, 4, 5], weights=[5, 10, 20, 40, 25])[0],  # satisfaction score
            recommend, channels, rng.choice(comments),
        ])
    header = ["respondent_id", "submitted_at", "age_group", "gender", "satisfaction",
              "recommend_0_10", "channels_used", "comment"]
    return _write("05_survey.csv", header, rows)

def budget_wide(rng: random.Random) -> Path:
    months = [f"{date(2024, m, 1):%b-%Y}" for m in range(1, 13)]
    typical = {"Salaries": 90_000, "Software": 12_000, "Travel": 6_000}
    rows = []
    for dept in ["Engineering", "Sales", "Marketing", "Finance", "HR", "Support", "Legal", "Operations"]:
        for cost_type, amount in typical.items():
            base = amount * rng.uniform(0.5, 1.8)
            rows.append([dept, cost_type, *(round(base * rng.uniform(0.85, 1.15)) for _ in months)])
    return _write("06_budget_months_wide.csv", ["department", "cost_type", *months], rows)

def messy_export(rng: random.Random) -> Path:
    stores = [("S-01", "Berlin Mitte", "01067"), ("S-02", "Köln Süd", "50667"),
              ("S-03", "München Ost", "81667"), ("S-04", "Dresden Neustadt", "01097"),
              ("S-05", "Hamburg Hafen", "20457")]
    rows: list[list[str]] = []
    for week in range(30):
        day = date(2024, 1, 1) + timedelta(weeks=week)
        for store_id, name, postal in stores:
            revenue = "N/A" if rng.random() < 0.04 else f"{_eu(rng.uniform(800, 25_000))} €"
            rows.append([
                store_id, f" {name} ", postal, f"{day:%d.%m.%Y}", revenue, str(rng.randint(20, 900)),
                f"{rng.uniform(0.5, 8):.1f}".replace(".", ",") + "%",
                rng.choice(["A. Weber", "J. Fischer", "M. Schulz", "-", ""]),
                rng.choice(["", "", "Inventur", "Umbau"]), "",
            ])
    rows.insert(17, [])                                  # blank line inside the data
    rows.insert(40, ["S-03", " München Ost ", "81667"])  # short (ragged) row
    rows.insert(60, rows[59] + ["unexpected extra"])     # row with an extra field
    header = ["Store ID", "Store", "Postal Code", "Date", "Revenue", "Items Sold", "Return Rate",
              "Manager", "Notes", "Notes"]
    preamble = ["Quarterly Store Export", "Generated: 05.08.2024 08:00 by ERP system", ""]
    return _write("07_messy_export.csv", header, rows, delimiter=";", encoding="cp1252", preamble=preamble)

def wide_sensors(rng: random.Random) -> Path:
    sensors = [f"sensor_{i:03d}" for i in range(1, 401)]
    level = [rng.uniform(20, 80) for _ in sensors]
    rows = []
    for step in range(200):
        stamp = datetime(2024, 6, 1) + timedelta(minutes=10 * step)
        values = []
        for j in range(len(sensors)):
            level[j] = min(100.0, max(0.0, level[j] + rng.gauss(0, 1.5)))
            values.append("" if rng.random() < 0.01 else f"{level[j]:.2f}")
        rows.append([f"{stamp:%Y-%m-%d %H:%M:%S}", "Line-1" if step % 2 == 0 else "Line-2", *values])
    return _write("08_wide_sensors.csv", ["timestamp", "line", *sensors], rows)

BUILDERS: list[tuple[Callable[[random.Random], Path], str]] = [
    (leave_requests, "rows are requests, not days; some are cancelled or rejected"),
    (bank_balances, "balances are daily snapshots per account: adding them up is wrong"),
    (sales_with_totals, "subtotal and grand-total rows mixed in: easy to double count"),
    (api_logs, "error rate needs the right denominator; quiet night hours"),
    (survey, "gender is a code (averaging it is wrong); multi-answer cells; free text"),
    (budget_wide, "months are columns, not a date column"),
    (messy_export, "title lines, ';' delimiter, EU numbers, Windows encoding, placeholders, ragged rows"),
    (wide_sensors, "402 columns: too many to describe one by one"),
]

def main() -> None:
    OUT.mkdir(exist_ok=True)
    for build, trap in BUILDERS:
        path = build(random.Random(f"adapt-{build.__name__}"))
        print(f"✓ {path.name:<28} trap: {trap}")
    print(f"\nWrote {len(BUILDERS)} files to {OUT}")

if __name__ == "__main__":
    main()
