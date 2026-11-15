import * as React from "react"

import { formatNumber } from "@/lib/format"
import type { ChartConfig } from "@/components/ui/chart"
import { isChartToken, type ChartToken } from "@/components/ui/percentage-bar"

/** One point of a chart: the index value plus one number per series key. */
export type ChartDatum = Record<string, string | number | null | undefined>

/** One plotted measure — which key to read, what to call it, what to paint it. */
export type ChartSeries = {
  key: string
  label: string
  /** A chart token, or any CSS colour for a brand hue. Defaults to the palette in order. */
  color?: ChartToken | string
  /**
   * The key holding the same measure over the period before this one. Drawn as
   * a dashed ghost behind the series and printed in its tooltip row as a delta.
   */
  compareKey?: string
  /**
   * The colour the ghost is drawn in: a chart token or any CSS colour. Left
   * out, the ghost wears the series' own colour; `var(--chart-neutral)` keeps
   * the period before out of the palette, grey under every preset — including
   * one whose first slot follows a coloured accent.
   */
  compareColor?: ChartToken | string
}

/** The props every cartesian chart in the set accepts. */
export type CommonChartProps = React.ComponentProps<"div"> & {
  data: ChartDatum[]
  /** The key holding each point's category — the month, the day, the source. */
  index: string
  series: ChartSeries[]
  /** Formats every number the chart prints: axis ticks, tooltips, and the text summary. */
  valueFormatter?: (n: number) => string
  /** Formats every index label, e.g. an ISO date into "Sep 4". */
  indexFormatter?: (v: string | number) => string
  /** Plot height in pixels, axis band included. */
  height?: number
  showLegend?: boolean
  showGrid?: boolean
  showXAxis?: boolean
  showYAxis?: boolean
  showTooltip?: boolean
  /** Where the series are named: beside their last point, under the plot, or nowhere. */
  legend?: ChartLegendPlacement
  /** Goal lines, event markers and bands drawn over the plot and read out as text. */
  annotations?: ChartAnnotation[]
  /** Draws each series' `compareKey` as a dashed ghost behind it, in the series' `compareColor` if it names one, its own colour if not. */
  compare?: boolean
  className?: string
}

// The palette wraps rather than inventing a ninth hue: past eight series the
// colours stop being distinguishable, so fold the tail into an "Other" series.
const PALETTE_SIZE = 8

/**
 * A series' colour: a chart token becomes its CSS variable, any other string is
 * taken as a raw CSS colour, and a series that names none takes the next slot in
 * the palette, wrapping past the eighth.
 */
export function seriesColor(series: ChartSeries, i: number): string {
  const color = series.color
  if (color === undefined) return `var(--chart-${(i % PALETTE_SIZE) + 1})`
  return isChartToken(color) ? `var(--${color})` : color
}

/**
 * The ChartConfig the chart primitive needs — it turns each entry into a
 * `--color-<key>` custom property that recharts marks reference.
 */
export function buildChartConfig(series: ChartSeries[]): ChartConfig {
  // fromEntries defines own properties, so a series keyed "__proto__" lands as
  // data instead of reassigning the config object's prototype.
  return Object.fromEntries(
    series.map((entry, i) => [entry.key, { label: entry.label, color: seriesColor(entry, i) }])
  )
}

/**
 * The shared starting point: a 280px plot with both axes, a grid, direct labels
 * at the end of each series, and a tooltip. The value axis is on — a chart
 * without a printed scale is a shape, not a measurement — and the charts turn it
 * off themselves when the plot is too small to carry one (`fitsYAxis`).
 */
export const chartDefaults = {
  height: 280,
  showLegend: true,
  showGrid: true,
  showXAxis: true,
  showYAxis: true,
  showTooltip: true,
  legend: "inline-end",
} as const

/**
 * A drawn line: 2px with round caps and joins reads as a stroke at any size
 * and holds its own on a white sheet, where 1.5px thinned to a hair on a
 * high-density screen.
 */
export const STROKE_WIDTH = 2

/**
 * The gridline: the grid token, dashed, so a rule under the data reads as a
 * guide rather than as a border. Every cartesian chart spreads this onto its
 * CartesianGrid.
 */
export const GRID_PROPS = { stroke: "var(--chart-grid)", strokeDasharray: "3 3" } as const

/**
 * The dot under the pointer: 3.5px of the series' own colour, ringed in the
 * surface it sits on so it stays legible where two lines cross.
 * --chart-surface falls back to the card a chart normally lives on; set it on
 * any ancestor when the chart sits on another plane.
 */
export const ACTIVE_DOT = { r: 3.5, strokeWidth: 2, stroke: "var(--chart-surface, var(--card))" } as const

/**
 * The corner a column turns, and the gap between two segments of one stack. A
 * stack is rounded as one shape — the top corners on the topmost segment, the
 * bottom corners on the lowest — so a bar reads as a printed block rather than
 * a pile of separately rounded tiles.
 */
export const BAR_RADIUS = 6
export const BAR_GAP = 1

/** Axis chrome: no rule and no tick marks, so only the labels carry the scale. */
export const axisProps = { tickLine: false, axisLine: false, tickMargin: 8, fontSize: 12 } as const

/**
 * The paint every axis label takes: --chart-axis, the token §3.8 names for the
 * printed scale. recharts writes fill="#666" onto its own
 * tick text, and the primitive's `.recharts-cartesian-axis-tick text` rule does
 * not reach it — recharts 3 nests labels under
 * `.recharts-cartesian-axis-tick-labels` instead — so #666 survived on the card
 * at 3.16:1 in dark. Passing the fill as a tick prop puts it on the element
 * itself, where nothing has to match a selector.
 */
export const AXIS_TICK = { fill: "var(--chart-axis)" } as const

/** Chart numbers fall back to thousands-separated values when no valueFormatter is given. */
export function defaultValueFormatter(value: number): string {
  return formatNumber(value)
}

/** Index labels print as they arrive unless the chart is given an indexFormatter. */
export function defaultIndexFormatter(value: string | number): string {
  return String(value)
}

/** What the text helpers need to turn a chart's data back into words. */
export type ChartTextOptions = {
  data: ChartDatum[]
  index: string
  series: ChartSeries[]
  valueFormatter?: (n: number) => string
  indexFormatter?: (v: string | number) => string
}

function readIndex(datum: ChartDatum, index: string, format: (v: string | number) => string) {
  const raw = datum[index]
  return typeof raw === "string" || typeof raw === "number" ? format(raw) : ""
}

function readValue(raw: ChartDatum[string], format: (n: number) => string) {
  return typeof raw === "number" && Number.isFinite(raw) ? format(raw) : "no data"
}

function joinLabels(labels: string[]): string {
  if (labels.length < 2) return labels.join("")
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`
}

/**
 * The plotted data as text, one row per point. Every chart renders this into a
 * visually hidden list, so the numbers are readable without pointing at a tooltip.
 */
export function chartRows(options: ChartTextOptions): { label: string; readings: string }[] {
  const {
    data,
    index,
    series,
    valueFormatter = defaultValueFormatter,
    indexFormatter = defaultIndexFormatter,
  } = options

  return data.map((datum) => ({
    label: readIndex(datum, index, indexFormatter),
    readings: series
      .map((entry) => `${entry.label} ${readValue(datum[entry.key], valueFormatter)}`)
      .join(", "),
  }))
}

/**
 * The heading for a tooltip: the point's own index value, read straight off the
 * datum. The primitive resolves its label through the config, which only works
 * when the index is a string — reading the datum keeps numeric indexes intact.
 */
export function tooltipIndexLabel(
  payload: ReadonlyArray<{ payload?: unknown }> | undefined,
  index: string,
  format: (v: string | number) => string = defaultIndexFormatter
): string {
  const datum = payload?.[0]?.payload
  const raw = datum && typeof datum === "object" ? (datum as ChartDatum)[index] : undefined
  return typeof raw === "string" || typeof raw === "number" ? format(raw) : ""
}

/** A one-sentence description of what a chart plots, used as its accessible name. */
export function chartSummary(kind: string, options: ChartTextOptions): string {
  const { data, index, series, indexFormatter = defaultIndexFormatter } = options
  if (series.length === 0) return `${kind} with no series.`

  const labels = joinLabels(series.map((entry) => entry.label))
  if (data.length === 0) return `${kind} of ${labels} by ${index}. No data.`

  const first = readIndex(data[0], index, indexFormatter)
  const last = readIndex(data[data.length - 1], index, indexFormatter)
  const count = `${data.length} point${data.length === 1 ? "" : "s"}`
  return `${kind} of ${labels} by ${index}, ${count} from ${first} to ${last}.`
}

/* -------------------------------------------------------------------------- */
/* Annotations                                                                 */
/* -------------------------------------------------------------------------- */

/** Where a chart names its series. */
export type ChartLegendPlacement = "inline-end" | "bottom" | "none"

/** The meanings an annotation can carry; each resolves to a token, never a literal. */
export type ChartAnnotationTone = "neutral" | "brand" | "positive" | "negative" | "warning" | "info"

export type ChartAnnotation =
  /** A threshold across the plot: a goal, a limit, an included allowance. */
  | { kind: "line"; axis?: "x" | "y"; value: number | string; label: string; tone?: ChartAnnotationTone }
  /** A moment on the index axis: a launch, a deploy, an incident. */
  | { kind: "event"; x: number | string; label: string; tone?: ChartAnnotationTone; href?: string }
  /**
   * A stretch of the index axis: a freeze, an outage, a campaign. The label
   * reads from the band's start; `align: "end"` hangs it from the band's end
   * instead, for a band that runs to the edge of the plot — a 59px word over
   * a 30px band at the right edge otherwise runs out of the plot.
   */
  | {
      kind: "band"
      from: number | string
      to: number | string
      label: string
      tone?: ChartAnnotationTone
      align?: "start" | "end"
    }

const ANNOTATION_PAINT: Record<ChartAnnotationTone, string> = {
  neutral: "var(--faint-foreground)",
  brand: "var(--brand)",
  positive: "var(--chart-positive)",
  negative: "var(--chart-negative)",
  warning: "var(--warning)",
  info: "var(--info)",
}

/**
 * The paint a *meaning* takes, as opposed to a category.
 *
 * A series that is coded by status — 200/429/500, up/down, paid/overdue — is
 * not one of eight interchangeable hues: it has to resolve to the semantic
 * tokens, or a reader learns the wrong colour for "failed" on one page and
 * carries it to the next. Categories keep the palette; meanings come from here.
 */
export const CHART_TONES = {
  positive: "var(--chart-positive)",
  negative: "var(--chart-negative)",
  neutral: "var(--chart-neutral)",
  warning: "var(--warning)",
  info: "var(--info)",
} as const

export type ChartTone = keyof typeof CHART_TONES

export function chartTone(tone: ChartTone): string {
  return CHART_TONES[tone]
}

/** The token an annotation's tone paints in. */
export function annotationPaint(tone: ChartAnnotationTone = "neutral"): string {
  return ANNOTATION_PAINT[tone] ?? ANNOTATION_PAINT.neutral
}

/** The numbers an annotation pins to the value axis, so the scale can hold them. */
export function annotationValues(annotation: ChartAnnotation): number[] {
  if (annotation.kind === "line" && annotation.axis !== "x" && typeof annotation.value === "number")
    return [annotation.value]
  return []
}

/**
 * Every annotation as a line of text, appended to a chart's visually hidden
 * rows: a goal line a sighted reader can see has to be readable too.
 */
export function annotationRows(
  annotations: ChartAnnotation[] = [],
  options: {
    valueFormatter?: (n: number) => string
    indexFormatter?: (v: string | number) => string
  } = {}
): string[] {
  const {
    valueFormatter = defaultValueFormatter,
    indexFormatter = defaultIndexFormatter,
  } = options
  const at = (value: number | string) =>
    typeof value === "number" ? valueFormatter(value) : indexFormatter(value)

  return annotations.map((annotation) => {
    if (annotation.kind === "line")
      return `${annotation.label}: ${
        annotation.axis === "x" ? indexFormatter(annotation.value) : at(annotation.value)
      }`
    if (annotation.kind === "event") return `${annotation.label} at ${indexFormatter(annotation.x)}`
    return `${annotation.label}: ${indexFormatter(annotation.from)} to ${indexFormatter(annotation.to)}`
  })
}
