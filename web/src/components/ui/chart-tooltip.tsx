"use client"

import * as React from "react"

import { DASH } from "@/components/ui/chart-annotations"
import {
  defaultValueFormatter,
  seriesColor,
  type ChartDatum,
  type ChartSeries,
} from "@/components/ui/chart-core"
import { MetricDelta } from "@/components/ui/metric-delta"

/* -------------------------------------------------------------------------- */
/* Tooltip rows                                                                */
/* -------------------------------------------------------------------------- */


export type TooltipRowOptions = {
  valueFormatter?: (n: number) => string
  /** The chart's series, so a row can find its own compare key. */
  series?: ChartSeries[]
  compare?: boolean
}

/**
 * One tooltip row: swatch, series name, the value through the chart's own
 * formatter, and — when a compare period is drawn — how far it is from the same
 * point a period ago.
 */
export function tooltipRow(options: TooltipRowOptions = {}) {
  const { valueFormatter = defaultValueFormatter, series = [], compare = false } = options

  return function renderRow(value: unknown, name: unknown, item: unknown) {
    // recharts types the payload entry as widely as its own generics allow, so
    // the two fields this row reads are narrowed here rather than in the signature.
    const point = item as { color?: string; dataKey?: unknown; payload?: ChartDatum }
    const entry = series.find((candidate) => candidate.key === point.dataKey)
    const previous =
      compare && entry?.compareKey ? point.payload?.[entry.compareKey] : undefined
    const current = Number(value)
    const delta =
      typeof previous === "number" && previous !== 0 && Number.isFinite(current)
        ? current / previous - 1
        : undefined

    return (
      <>
        <span
          className="size-2.5 shrink-0 rounded-[2px]"
          style={{ backgroundColor: point.color }}
        />
        <div className="flex flex-1 items-center justify-between gap-3 leading-none">
          <span className="text-muted-foreground">{String(name)}</span>
          <span className="flex items-center gap-2">
            <span className="font-medium tabular-nums">{valueFormatter(current)}</span>
            {delta === undefined ? null : (
              <MetricDelta value={delta} size="sm" showIcon={false} className="text-2xs" />
            )}
          </span>
        </div>
      </>
    )
  }
}

/**
 * The ghost's stroke: dashed and dimmed, in the series' own colour — or in
 * its compareColor when it names one, as a page does to keep the period
 * before out of the palette with var(--chart-neutral). 0.75 is measured
 * rather than chosen — 0.65 of the default theme's first chart hue
 * composites to 2.73:1 on a white card and 2.96:1 on a dark one, both under
 * the 3:1 a line has to clear; 0.75 reads 3.24 light and 3.53 dark. The dash
 * is what carries the meaning anyway, so the opacity only has to stay out of
 * the way.
 */
export const COMPARE_STROKE = {
  strokeDasharray: DASH,
  strokeOpacity: 0.75,
  strokeWidth: 1.5,
  legendType: "none",
  tooltipType: "none",
  dot: false,
  activeDot: false,
  isAnimationActive: false,
} as const

/** The compare series a chart should draw behind its own: each in its series' compareColor, or the series' own colour when it names none. */
export function compareSeries(series: ChartSeries[], compare: boolean): ChartSeries[] {
  if (!compare) return []
  return series.flatMap((entry, i) =>
    entry.compareKey
      ? [{ key: entry.compareKey, label: `${entry.label} (prev)`, color: entry.compareColor ?? seriesColor(entry, i) }]
      : []
  )
}
