"use client"

import * as React from "react"
import { InfoIcon } from "lucide-react"

import { AreaChart } from "@/components/ui/area-chart"
import { Badge } from "@/components/ui/badge"
import { BarChart } from "@/components/ui/bar-chart"
import { ChartCard } from "@/components/ui/chart-card"
import type { ChartSeries } from "@/components/ui/chart-core"
import { DashboardGrid, DashboardGridItem, type ColSpanValue } from "@/components/ui/dashboard-grid"
import { DataTable, DataTableColumnHeader, type DataTableColumnDef } from "@/components/ui/data-table"
import { DonutChart } from "@/components/ui/donut-chart"
import { LineChart } from "@/components/ui/line-chart"
import { StatCard } from "@/components/ui/stat-card"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { applyFilters, errorMessage, type ChartComponent, type Dashboard, type FilterIn } from "@/lib/api"
import {
  cartesianData, chartNumber, columnFormat, humanize, INDEX_KEY, kpiItems, numberText, pieSlices,
} from "@/lib/chart-data"

type Size = ChartComponent["size"]
interface ViewProps { id: string; dashboard: Dashboard; onChange: (d: Dashboard) => void }

// Full width on a phone; at lg, S = quarter, M = half, L = three quarters, XL = full.
const SPAN: Record<Size, ColSpanValue> = {
  S: { base: 12, sm: 6, lg: 3 }, M: { base: 12, lg: 6 }, L: { base: 12, lg: 9 }, XL: 12,
}
const HEIGHT: Record<Size, number> = { S: 220, M: 280, L: 300, XL: 320 }
// Distinct hues for visuals with several series; the theme's grey ramp repeats past five.
const PALETTE = [
  "oklch(0.72 0.14 250)", "oklch(0.80 0.14 80)", "oklch(0.72 0.14 160)", "oklch(0.68 0.18 25)",
  "oklch(0.72 0.14 300)", "oklch(0.80 0.10 200)", "oklch(0.76 0.13 130)", "oklch(0.70 0.13 350)",
]
const DOTS_UP_TO = 20
// Past this many points a smoothed curve invents bends between them; draw straight segments instead.
const CURVE_UP_TO = 30
const CARTESIAN = new Set<ChartComponent["kind"]>(["line", "area", "bar", "grouped_bar", "stacked_bar"])

const measureOf = (c: ChartComponent) => ({ decimals: c.decimals, unit: c.unit })
const paint = (i: number) => PALETTE[i % PALETTE.length]
const colored = (series: ChartSeries[]) =>
  series.length > 1 ? series.map((s, i) => ({ ...s, color: paint(i) })) : series
const hasAbout = (c: ChartComponent) => Boolean(c.meaning) || c.assumptions.length > 0

/** The ⓘ: what the number means and what it assumes. */
function About({ c }: { c: ChartComponent }) {
  return (
    <Tooltip>
      <TooltipTrigger aria-label="What this shows"
        className="rounded-sm text-muted-foreground hover:text-foreground focus-ring">
        <InfoIcon className="size-4" />
      </TooltipTrigger>
      <TooltipContent side="bottom" className="flex-col items-start gap-1 text-start">
        {c.meaning && <p>{c.meaning}</p>}
        {c.assumptions.length > 0 && (
          <ul className="list-disc space-y-0.5 ps-4">{c.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
        )}
      </TooltipContent>
    </Tooltip>
  )
}

/** Caveat, rows hidden by top_n, and any honest note about how the visual is drawn. */
function footerOf(c: ChartComponent): React.ReactNode {
  const { rows, total_rows } = c.data
  const notes = [
    c.kind === "stacked_bar" && "Bars are shown side by side, not stacked.",
    c.kind === "scatter" && "Shown as a table; scatter charts are not available yet.",
    total_rows > rows.length && `Showing ${rows.length} of ${total_rows} rows.`,
  ].filter(Boolean) as string[]
  if (!c.caveat && notes.length === 0) return undefined
  return (
    <div className="flex flex-col gap-1">
      {c.caveat && <p className="text-warning">{c.caveat}</p>}
      {notes.map((n) => <p key={n}>{n}</p>)}
    </div>
  )
}

/** Any result as a sortable, paged table. Columns are read by position, so any column name works. */
function TableView({ c }: { c: ChartComponent }) {
  const columns = React.useMemo<DataTableColumnDef<unknown[]>[]>(() =>
    c.data.columns.map((name, i) => {
      const values = c.data.rows.map((r) => r[i])
      const format = columnFormat(values, c.y.includes(name) ? measureOf(c) : null)
      const title = humanize(name)
      return {
        id: `c${i}`,
        accessorFn: (row: unknown[]) => row[i],
        header: ({ column }) => <DataTableColumnHeader column={column} title={title} />,
        cell: ({ row }) => format(row.original[i]),
        meta: { align: values.some((v) => typeof v === "number") ? "right" : "left", label: title },
      } satisfies DataTableColumnDef<unknown[]>
    }), [c])
  return (
    <DataTable columns={columns} data={c.data.rows} enableRowSelection={false} keyboard={false}
      pageSize={10} aria-label={c.title} />
  )
}

/** Picks the Vibra visual for the spec's kind; anything that cannot be drawn falls back to a table. */
function Plot({ c }: { c: ChartComponent }) {
  const height = HEIGHT[c.size]
  const valueFormatter = chartNumber(measureOf(c))

  if (c.kind === "pie") {
    const slices = pieSlices(c)
    if (slices && slices.length > 0) {
      return (
        <DonutChart data={slices.map((s, i) => ({ ...s, color: paint(i) }))} valueFormatter={valueFormatter}
          height={height} centerValue={null} />
      )
    }
  }

  if (CARTESIAN.has(c.kind)) {
    const chart = cartesianData(c)
    if (chart && chart.data.length > 0) {
      const series = colored(chart.series)
      const common = {
        data: chart.data, index: INDEX_KEY, series, valueFormatter, indexFormatter: chart.formatIndex,
        height, showLegend: series.length > 1,
      }
      const curve = chart.data.length <= CURVE_UP_TO ? "monotone" : "linear"
      if (c.kind === "line") {
        return <LineChart {...common} baseline="auto" curve={curve} dots={chart.data.length <= DOTS_UP_TO} />
      }
      if (c.kind === "area") return <AreaChart {...common} curve={curve} />
      return <BarChart {...common} />
    }
  }

  return <TableView c={c} />
}

/** One Vibra stat card per KPI value; numbers roll to their new value when filters change. */
function KpiCards({ c }: { c: ChartComponent }) {
  const items = kpiItems(c)
  const measure = measureOf(c)
  const description = c.subtitle || c.caveat ? (
    <>
      {c.subtitle && <span className="block">{c.subtitle}</span>}
      {c.caveat && <span className="block text-warning">{c.caveat}</span>}
    </>
  ) : undefined
  const icon = hasAbout(c) ? <About c={c} /> : undefined

  if (items.length === 0) {
    return <StatCard className="h-full" label={c.title} value="—" description="No data to show." icon={icon} />
  }
  return (
    <div className="grid h-full grid-cols-[repeat(auto-fit,minmax(11rem,1fr))] gap-[var(--density-gap,1rem)]">
      {items.map((item) => {
        const shared = {
          className: "h-full",
          label: items.length > 1 ? `${c.title} · ${humanize(item.name)}` : c.title,
          description, icon,
        }
        return item.number === null
          ? <StatCard key={item.name} {...shared} value={item.text} />
          : <StatCard key={item.name} {...shared}
              roll={{ value: item.number, format: (n) => numberText(n, measure) }} />
      })}
    </div>
  )
}

function ComponentCard({ c }: { c: ChartComponent }) {
  if (c.kind === "kpi") return <KpiCards c={c} />
  return (
    <ChartCard className="h-full" title={c.title} description={c.subtitle || undefined}
      actions={hasAbout(c) ? <About c={c} /> : undefined} footer={footerOf(c)}
      empty={c.data.rows.length === 0} emptyMessage="No data to show." height={HEIGHT[c.size]}>
      <Plot c={c} />
    </ChartCard>
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
    <TooltipProvider>
      <div className="mx-auto max-w-7xl space-y-8 px-6 py-10">
        <header>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-bold">{dashboard.title}</h1>
            {dashboard.filtered && (
              <Badge variant="outline" title="Numbers written in titles describe the unfiltered data">
                Filtered
              </Badge>
            )}
          </div>
          {dashboard.subtitle && <p className="mt-1 text-muted-foreground">{dashboard.subtitle}</p>}
        </header>
        <FiltersBar id={id} dashboard={dashboard} onChange={onChange} />
        {dashboard.notes.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            {dashboard.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        )}
        {dashboard.sections.map((s) => (
          <section key={s.name} className="space-y-3">
            <h2 className="text-lg font-semibold">{s.name}</h2>
            <DashboardGrid>
              {s.components.map((c) => (
                <DashboardGridItem key={c.id} colSpan={SPAN[c.size]}>
                  <ComponentCard c={c} />
                </DashboardGridItem>
              ))}
            </DashboardGrid>
          </section>
        ))}
      </div>
    </TooltipProvider>
  )
}
