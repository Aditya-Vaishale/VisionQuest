import type { ChartDatum, ChartSeries } from "@/components/ui/chart-core"
import type { DonutChartSlice } from "@/components/ui/donut-chart"
import type { ChartComponent } from "@/lib/api"

/** How a measure is printed: the decimals and unit the dashboard spec gives it. */
export type Measure = { decimals: number; unit: string }
export type Format = (value: unknown) => string

const LOCALE = "en-US"
/** The datum key every chart reads its x value from; series keys are s0, s1, ... */
export const INDEX_KEY = "__x"

/* -------------------------------------------------------------------------- */
/* Dates                                                                       */
/* -------------------------------------------------------------------------- */

// ISO text as the API writes it: "2024-03-01", "2024-03-01T13:45:00", optional fraction and offset.
const ISO = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?(?:Z|[+-]\d{2}:?\d{2})?$/

type DateParts = { y: number; mo: number; d: number; h: number; mi: number; s: number }
type Grain = "year" | "month" | "day" | "time"

function dateParts(value: unknown): DateParts | null {
  if (typeof value !== "string") return null
  const m = ISO.exec(value)
  if (!m) return null
  const n = (i: number) => Number(m[i] ?? 0)
  return { y: n(1), mo: n(2), d: n(3), h: n(4), mi: n(5), s: n(6) }
}

/** The coarsest calendar step every value sits on, so monthly data reads "Mar 2024", not "Mar 1, 2024". */
function grainOf(values: unknown[]): Grain | null {
  const present = values.filter((v) => v !== null && v !== undefined && v !== "")
  if (present.length === 0) return null
  const parts: DateParts[] = []
  for (const v of present) {
    const p = dateParts(v)
    if (!p) return null
    parts.push(p)
  }
  if (parts.some((p) => p.h || p.mi || p.s)) return "time"
  if (parts.length > 1 && parts.every((p) => p.mo === 1 && p.d === 1)) return "year"
  if (parts.length > 1 && parts.every((p) => p.d === 1)) return "month"
  return "day"
}

// Read as written (UTC), so a date never shifts a day in the reader's time zone.
const DATE_OPTIONS: Record<Grain, Intl.DateTimeFormatOptions> = {
  year: { year: "numeric", timeZone: "UTC" },
  month: { month: "short", year: "numeric", timeZone: "UTC" },
  day: { dateStyle: "medium", timeZone: "UTC" },
  time: { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" },
}
const dateFormats = new Map<Grain, Intl.DateTimeFormat>()

function dateText(p: DateParts, grain: Grain): string {
  let f = dateFormats.get(grain)
  if (!f) {
    f = new Intl.DateTimeFormat(LOCALE, DATE_OPTIONS[grain])
    dateFormats.set(grain, f)
  }
  return f.format(Date.UTC(p.y, p.mo - 1, p.d, p.h, p.mi, p.s))
}

/* -------------------------------------------------------------------------- */
/* Numbers                                                                     */
/* -------------------------------------------------------------------------- */

const CURRENCIES = new Set<string>(typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("currency") : [])
const CURRENCY_SYMBOL = new RegExp("^\\p{Sc}$", "u")
const numberFormats = new Map<string, Intl.NumberFormat>()

function numberFormat(options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = JSON.stringify(options)
  let f = numberFormats.get(key)
  if (!f) {
    f = new Intl.NumberFormat(LOCALE, options)
    numberFormats.set(key, f)
  }
  return f
}

export function toNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

/**
 * A measure with its unit: "EUR" (a currency code) → "€1,234.50", "$" → "$1,234.50",
 * "%" → "12.5%", anything else is written after the number → "3.2 days".
 * `fixed` pads to the spec's decimals (cards, tables); charts drop trailing zeros.
 */
export function numberText(n: number, measure: Measure, fixed = true): string {
  const decimals = Math.max(0, Math.min(measure.decimals, 6))
  const digits = { minimumFractionDigits: fixed ? decimals : 0, maximumFractionDigits: decimals }
  const unit = measure.unit.trim()
  if (CURRENCIES.has(unit)) return numberFormat({ style: "currency", currency: unit, ...digits }).format(n)
  if (CURRENCY_SYMBOL.test(unit)) return `${n < 0 ? "-" : ""}${unit}${numberFormat(digits).format(Math.abs(n))}`
  const text = numberFormat(digits).format(n)
  if (!unit) return text
  return unit === "%" ? `${text}%` : `${text} ${unit}`
}

/** Axis ticks and tooltips: at least two decimals, so a 0–1 axis never prints "0, 0, 1". */
export function chartNumber(measure: Measure): (n: number) => string {
  const wide = { ...measure, decimals: Math.max(measure.decimals, 2) }
  return (n) => numberText(n, wide, false)
}

/** A number that is a label, not a measure (an id, a year, a bucket): no unit, no grouping below 10,000. */
function plainNumber(n: number): string {
  return numberFormat({ maximumFractionDigits: 4, useGrouping: Math.abs(n) >= 10_000 }).format(n)
}

/* -------------------------------------------------------------------------- */
/* Cells and labels                                                            */
/* -------------------------------------------------------------------------- */

export function humanize(name: string): string {
  const text = name.replace(/_+/g, " ").trim()
  return text ? text[0].toUpperCase() + text.slice(1) : name
}

/** Prints any cell of one column: dates at the column's own grain, measures with their unit, the rest as text. */
export function columnFormat(values: unknown[], measure: Measure | null): Format {
  const grain = grainOf(values)
  return (value) => {
    if (value === null || value === undefined || value === "") return measure ? "—" : "(blank)"
    if (typeof value === "number") return measure ? numberText(value, measure) : plainNumber(value)
    if (typeof value === "boolean") return value ? "Yes" : "No"
    if (typeof value === "object") return JSON.stringify(value)
    const parts = grain ? dateParts(value) : null
    return parts && grain ? dateText(parts, grain) : String(value)
  }
}

function keyOf(value: unknown): string {
  if (value === null || value === undefined) return ""
  return typeof value === "object" ? JSON.stringify(value) : String(value)
}

/* -------------------------------------------------------------------------- */
/* Shaping the API's rows for each kind of visual                              */
/* -------------------------------------------------------------------------- */

export type CartesianData = {
  data: ChartDatum[]
  series: ChartSeries[]
  formatIndex: (v: string | number) => string
}

/**
 * Rows → one datum per x value. With a `series` column the long rows are pivoted
 * (one coloured line or bar per series value); without one, every y column is a
 * series. Keys are s0, s1, ... because they become CSS variable names.
 * Returns null when the columns the spec names are not in the result.
 */
export function cartesianData(c: ChartComponent): CartesianData | null {
  const { columns, rows } = c.data
  const xi = columns.indexOf(c.x)
  const si = c.series ? columns.indexOf(c.series) : -1
  const ys = c.y
    .map((name) => ({ name, i: columns.indexOf(name) }))
    .filter((y) => y.i >= 0 && y.i !== xi && y.i !== si)
  if (xi < 0 || ys.length === 0 || (c.series && si < 0)) return null

  const xFormat = columnFormat(rows.map((r) => r[xi]), null)
  const groupFormat = si >= 0 ? columnFormat(rows.map((r) => r[si]), null) : null
  const points = new Map<string, ChartDatum>()
  const labels = new Map<string, string>()
  const series = new Map<string, ChartSeries>()

  for (const row of rows) {
    const x = keyOf(row[xi])
    let point = points.get(x)
    if (!point) {
      point = { [INDEX_KEY]: x }
      points.set(x, point)
      labels.set(x, xFormat(row[xi]))
    }
    for (const y of ys) {
      const id = groupFormat ? JSON.stringify([keyOf(row[si]), y.name]) : y.name
      let entry = series.get(id)
      if (!entry) {
        const group = groupFormat ? groupFormat(row[si]) : ""
        const label = !groupFormat ? humanize(y.name) : ys.length > 1 ? `${group} · ${humanize(y.name)}` : group
        entry = { key: `s${series.size}`, label }
        series.set(id, entry)
      }
      point[entry.key] = toNumber(row[y.i])
    }
  }
  return {
    data: [...points.values()],
    series: [...series.values()],
    formatIndex: (v) => labels.get(String(v)) ?? String(v),
  }
}

/** Rows → donut slices (x is the name, the first y is the size). Null when the columns are missing. */
export function pieSlices(c: ChartComponent): DonutChartSlice[] | null {
  const { columns, rows } = c.data
  const xi = columns.indexOf(c.x)
  const yi = columns.indexOf(c.y[0] ?? "")
  if (xi < 0 || yi < 0) return null
  const name = columnFormat(rows.map((r) => r[xi]), null)
  return rows.flatMap((r) => {
    const value = toNumber(r[yi])
    return value === null ? [] : [{ name: name(r[xi]), value }]
  })
}

export type KpiItem = { name: string; text: string; number: number | null }

/** One card per y column, read from the first row. */
export function kpiItems(c: ChartComponent): KpiItem[] {
  const { columns, rows } = c.data
  const measure = { decimals: c.decimals, unit: c.unit }
  return (c.y.length ? c.y : columns).flatMap((name) => {
    const i = columns.indexOf(name)
    if (i < 0) return []
    const value = rows[0]?.[i]
    return [{ name, text: columnFormat(rows.map((r) => r[i]), measure)(value), number: toNumber(value) }]
  })
}
