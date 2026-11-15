"use client"

import * as React from "react"
import { LabelList } from "recharts"

import {
  type ChartAnnotation,
  type ChartLegendPlacement,
  type ChartSeries,
} from "@/components/ui/chart-core"

/* -------------------------------------------------------------------------- */
/* Direct labels                                                               */
/* -------------------------------------------------------------------------- */


// An 8px swatch and 12px text: the series colour carries the identity and the
// ink carries the reading, because slots 5–8 as 13px coloured text miss AA.
const SWATCH = 8
const LABEL_GAP = 6
const CHAR_WIDTH = 6.4

type DirectLabelProps = {
  x?: number
  y?: number
  index?: number
  last?: number
  text?: string
  paint?: string
}

function DirectLabelMark({ x = 0, y = 0, index, last, text = "", paint }: DirectLabelProps) {
  if (index !== last) return null

  return (
    <g transform={`translate(${x + LABEL_GAP}, ${y})`} data-slot="chart-direct-label">
      <rect y={-SWATCH / 2} width={SWATCH} height={SWATCH} rx={2} fill={paint} />
      <text
        x={SWATCH + 4}
        dy="0.32em"
        fill="var(--foreground)"
        fontSize={12}
        data-slot="chart-direct-label-text"
      >
        {text}
      </text>
    </g>
  )
}

/**
 * A series' name set beside its own last point, so a reader never has to match a
 * swatch in a legend to a line in a plot. Returns null unless the chart is
 * drawing its legend inline, which is what makes it safe to write into every mark.
 */
export function directLabel(
  entry: ChartSeries,
  options: { legend: ChartLegendPlacement; count: number }
): React.ReactElement | null {
  if (options.legend !== "inline-end" || options.count === 0) return null

  return (
    <LabelList
      key={`label-${entry.key}`}
      dataKey={entry.key}
      content={
        <DirectLabelMark
          last={options.count - 1}
          text={entry.label}
          paint={`var(--color-${entry.key})`}
        />
      }
    />
  )
}

/**
 * The headroom an annotation label needs. A marker on the index axis writes its
 * eyebrow above the plot, and 12px of margin clips the ascender off it.
 */
export function annotationHeadroom(annotations: ChartAnnotation[] = []): number {
  return annotations.some((a) => a.kind === "event" || (a.kind === "line" && a.axis === "x"))
    ? 24
    : 12
}

/** The right margin the inline labels need, so the longest one is not clipped. */
export function inlineLabelWidth(series: ChartSeries[], legend: ChartLegendPlacement): number {
  if (legend !== "inline-end") return 12
  const longest = series.reduce((most, entry) => Math.max(most, entry.label.length), 0)
  return Math.min(180, LABEL_GAP + SWATCH + 4 + Math.ceil(longest * CHAR_WIDTH) + 8)
}

/**
 * Where the legend goes once the box is known. Inline labels that would take
 * more than a quarter of the plot — a 390px phone gave billing-usage 84px of a
 * 318px one — go under it instead; before the first measurement the answer is
 * what was asked for, so the server render and the client's first one agree.
 */
export function legendPlacement(
  asked: ChartLegendPlacement,
  series: ChartSeries[],
  width: number
): ChartLegendPlacement {
  // A lone series has no legend to fall back to — the charts draw one for two
  // or more — so it keeps its label, which is the cheaper of the two anyway.
  if (asked !== "inline-end" || width === 0 || series.length < 2) return asked
  return inlineLabelWidth(series, asked) > width / 4 ? "bottom" : asked
}


export { DirectLabelMark }
