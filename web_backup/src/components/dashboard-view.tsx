"use client"

import * as React from "react"

import { applyFilters, errorMessage, type ChartComponent, type Dashboard, type FilterIn } from "@/lib/api"

const SPAN = { S: "lg:col-span-1", M: "lg:col-span-2", L: "lg:col-span-3", XL: "lg:col-span-4" } as const
const PREVIEW_ROWS = 12

interface ViewProps { id: string; dashboard: Dashboard; onChange: (d: Dashboard) => void }

function fmt(v: unknown, decimals: number, unit = ""): string {
  if (typeof v === "number") {
    const s = v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    return unit === "%" ? `${s}%` : unit ? `${s} ${unit}` : s
  }
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T00:00:00/.test(v)) return v.slice(0, 10)
  return v == null ? "—" : String(v)
}

function Kpi({ c }: { c: ChartComponent }) {
  const row = c.data.rows[0] ?? []
  return (
    <div className="mt-4 flex flex-wrap gap-6">
      {c.y.map((col) => (
        <div key={col}>
          <div className="text-3xl font-bold">{fmt(row[c.data.columns.indexOf(col)], c.decimals, c.unit)}</div>
          <div className="text-xs text-white/60">{col.replaceAll("_", " ")}</div>
        </div>
      ))}
    </div>
  )
}

function Preview({ c }: { c: ChartComponent }) {
  const { columns, rows, total_rows } = c.data
  const shown = rows.slice(0, PREVIEW_ROWS)
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-white/60">
          <tr>{columns.map((col) => <th key={col} className="pb-2 pr-4 font-medium">{col}</th>)}</tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i} className="border-t border-white/5">
              {r.map((v, j) => <td key={j} className="py-1.5 pr-4">{fmt(v, c.decimals)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {total_rows > shown.length && (
        <p className="mt-2 text-xs text-white/50">Showing {shown.length} of {total_rows} rows</p>
      )}
    </div>
  )
}

function Card({ c }: { c: ChartComponent }) {
  return (
    <div className={`rounded-xl border border-white/10 bg-white/5 p-4 ${SPAN[c.size]}`}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold">{c.title}</h3>
          {c.subtitle && <p className="text-sm text-white/60">{c.subtitle}</p>}
        </div>
        <span title={[c.meaning, ...c.assumptions].join("\n")}
          className="shrink-0 rounded bg-white/10 px-2 py-0.5 text-xs text-white/70">
          {c.kind} ⓘ
        </span>
      </div>
      {c.kind === "kpi" ? <Kpi c={c} /> : <Preview c={c} />}
      {c.caveat && <p className="mt-3 text-xs text-amber-300/90">{c.caveat}</p>}
    </div>
  )
}

function FiltersBar({ id, dashboard, onChange }: ViewProps) {
  const [picked, setPicked] = React.useState<Record<string, FilterIn>>(
    () => Object.fromEntries(dashboard.filters_applied.map((f) => [f.column, f])))
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
  if (dashboard.filters.length === 0) return null

  const update = (column: string, change: Partial<FilterIn>) =>
    setPicked((p) => ({ ...p, [column]: { ...(p[column] ?? { column }), ...change, column } }))
  const toggle = (column: string, value: string) => {
    const values = picked[column]?.values ?? []
    update(column, { values: values.includes(value) ? values.filter((v) => v !== value) : [...values, value] })
  }
  const apply = async (list: FilterIn[]) => {
    setBusy(true)
    setError("")
    try {
      onChange(await applyFilters(id, list))
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-6 rounded-xl border border-white/10 bg-white/5 p-4">
      {dashboard.filters.map((f) => (
        <div key={f.column} className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-white/60">{f.label}</p>
          {f.kind === "category" ? (
            <div className="flex max-w-md flex-wrap gap-1.5">
              {(f.options ?? []).map((o) => {
                const on = picked[f.column]?.values?.includes(o) ?? false
                return (
                  <button key={o} type="button" onClick={() => toggle(f.column, o)}
                    className={`rounded-full border px-2.5 py-1 text-xs ${on
                      ? "border-white bg-white text-black" : "border-white/20 text-white/80 hover:bg-white/10"}`}>
                    {o}
                  </button>
                )
              })}
            </div>
          ) : (
            <div className="flex gap-2">
              {(["start", "end"] as const).map((k) => (
                <input key={k} type="date" value={picked[f.column]?.[k] ?? ""}
                  min={f.min?.slice(0, 10)} max={f.max?.slice(0, 10)}
                  onChange={(e) => update(f.column, k === "start"
                    ? { start: e.target.value || undefined } : { end: e.target.value || undefined })}
                  className="rounded-md border border-white/20 bg-transparent px-2 py-1 text-sm [color-scheme:dark]" />
              ))}
            </div>
          )}
        </div>
      ))}
      <div className="flex gap-2">
        <button disabled={busy} onClick={() => apply(Object.values(picked))}
          className="rounded-md bg-white px-4 py-1.5 text-sm font-semibold text-black disabled:opacity-40">
          {busy ? "Applying…" : "Apply"}
        </button>
        <button disabled={busy} onClick={() => { setPicked({}); apply([]) }}
          className="rounded-md border border-white/20 px-4 py-1.5 text-sm hover:bg-white/10 disabled:opacity-40">
          Reset
        </button>
      </div>
      {error && <p className="w-full text-sm text-red-400">{error}</p>}
    </div>
  )
}

export function DashboardView({ id, dashboard, onChange }: ViewProps) {
  return (
    <div className="mx-auto max-w-7xl space-y-8 px-6 py-10">
      <header>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-bold">{dashboard.title}</h1>
          {dashboard.filtered && (
            <span title="Numbers written in titles describe the unfiltered data"
              className="rounded-full bg-amber-400/20 px-3 py-1 text-xs text-amber-300">Filtered</span>
          )}
        </div>
        {dashboard.subtitle && <p className="mt-1 text-white/60">{dashboard.subtitle}</p>}
      </header>
      <FiltersBar id={id} dashboard={dashboard} onChange={onChange} />
      {dashboard.notes.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm text-white/70">
          {dashboard.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
      {dashboard.sections.map((s) => (
        <section key={s.name}>
          <h2 className="mb-3 text-lg font-semibold text-white/90">{s.name}</h2>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
            {s.components.map((c) => <Card key={c.id} c={c} />)}
          </div>
        </section>
      ))}
    </div>
  )
}
