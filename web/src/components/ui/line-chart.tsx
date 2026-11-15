"use client"

import * as React from "react"
import { CartesianGrid, Line, LineChart as RechartsLineChart, XAxis, YAxis } from "recharts"

import { cn } from "@/lib/utils"
import {
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart"
import {
  ACTIVE_DOT,
  AXIS_TICK,
  axisProps,
  buildChartConfig,
  chartDefaults,
  chartRows,
  chartSummary,
  type CommonChartProps,
  defaultIndexFormatter,
  defaultValueFormatter,
  GRID_PROPS,
  STROKE_WIDTH,
  tooltipIndexLabel,
} from "@/components/ui/chart-core"
import { renderAnnotations } from "@/components/ui/chart-annotations"
import { ChartPlot, ChartRows } from "@/components/ui/chart-frame"
import {
  annotationHeadroom,
  directLabel,
  inlineLabelWidth,
  legendPlacement,
} from "@/components/ui/chart-labels"
import { COMPARE_STROKE, compareSeries, tooltipRow } from "@/components/ui/chart-tooltip"
import { type ChartBaseline, yAxisScale } from "@/components/ui/chart-scale"

export type LineChartProps = CommonChartProps & {
  /**
   * Where the value axis starts. `zero` takes zero in, as every chart does by
   * default; `auto` fits the axis to the data's own range, for a level — a
   * rate, a price — whose movement a zero floor would flatten.
   */
  baseline?: ChartBaseline
  curve?: "monotone" | "linear" | "step"
  /** Marks every point, not just the one under the pointer. Best under ~20 points. */
  dots?: boolean
  strokeWidth?: number
}

function LineChart({
  className,
  data,
  index,
  series,
  valueFormatter = defaultValueFormatter,
  indexFormatter = defaultIndexFormatter,
  height = chartDefaults.height,
  showLegend = chartDefaults.showLegend,
  showGrid = chartDefaults.showGrid,
  showXAxis = chartDefaults.showXAxis,
  showYAxis = chartDefaults.showYAxis,
  showTooltip = chartDefaults.showTooltip,
  legend = chartDefaults.legend,
  annotations,
  compare = false,
  baseline = "zero",
  curve = "monotone",
  dots = false,
  strokeWidth = STROKE_WIDTH,
  ...props
}: LineChartProps) {
  const ghosts = React.useMemo(() => compareSeries(series, compare), [series, compare])
  const config = React.useMemo(() => buildChartConfig([...series, ...ghosts]), [series, ghosts])
  const rows = chartRows({ data, index, series, valueFormatter, indexFormatter })
  const scale = yAxisScale(data, series, { compare, annotations, baseline })
  const summary = chartSummary("Line chart", { data, index, series, indexFormatter })
  const inline = showLegend ? legend : "none"

  return (
    <div
      data-slot="line-chart"
      data-baseline={baseline}
      data-curve={curve}
      data-dots={dots || undefined}
      className={cn("w-full", className)}
      {...props}
    >
      <ChartPlot
        height={height}
        config={config}
        role="img"
        aria-label={summary}
        className="aspect-auto w-full"
      >
        {(frame) => {
          const placement = legendPlacement(inline, series, frame.width)
          return (
          <RechartsLineChart
            // Named once, by the container's role="img" and its summary; recharts'
            // keyboard layer would add an unnamed role="application" tab stop inside it.
            accessibilityLayer={false}
            data={data}
            margin={{ top: annotationHeadroom(annotations), right: inlineLabelWidth(series, placement), bottom: 0, left: 12 }}
          >
            {showGrid ? <CartesianGrid vertical={false} {...GRID_PROPS} /> : null}

            {showXAxis ? (
              <XAxis
                tick={AXIS_TICK}
                dataKey={index}
                {...axisProps}
                minTickGap={16}
                tickFormatter={(value) => indexFormatter(value)}
              />
            ) : null}

            {frame.yAxis(showYAxis) ? (
              <YAxis
                tick={AXIS_TICK}
                {...axisProps}
                width="auto"
                domain={scale.domain}
                ticks={scale.ticks}
                tickFormatter={(value) => valueFormatter(Number(value))}
              />
            ) : baseline === "auto" ? (
              // No printed scale in a box this small, but a fitted plot still
              // has to span the data's range rather than recharts' own 0-up one.
              <YAxis hide domain={scale.domain} />
            ) : null}

            {showTooltip ? (
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    labelFormatter={(_, payload) => tooltipIndexLabel(payload, index, indexFormatter)}
                    formatter={tooltipRow({ valueFormatter, series, compare })}
                  />
                }
              />
            ) : null}

            {/* The period before this one, behind its own series and dimmed. */}
            {ghosts.map((entry) => (
              <Line
                key={entry.key}
                dataKey={entry.key}
                name={entry.label}
                type={curve}
                stroke={`var(--color-${entry.key})`}
                {...COMPARE_STROKE}
              />
            ))}

            {series.map((entry) => (
              <Line
                key={entry.key}
                dataKey={entry.key}
                name={entry.label}
                type={curve}
                stroke={`var(--color-${entry.key})`}
                strokeWidth={strokeWidth}
                strokeLinecap="round"
                strokeLinejoin="round"
                // A hollow dot: the series' own ring around the surface the
                // chart sits on (--chart-surface, falling back to the card), so
                // a marker reads as a point on the line rather than a bead.
                dot={dots ? { r: 4, strokeWidth: 2, fill: "var(--chart-surface, var(--card))" } : false}
                activeDot={ACTIVE_DOT}
                isAnimationActive={false}
              >
                {directLabel(entry, { legend: placement, count: data.length })}
              </Line>
            ))}

            {renderAnnotations(annotations)}

            {showLegend && placement === "bottom" && series.length > 1 ? (
              <ChartLegend content={<ChartLegendContent />} />
            ) : null}
          </RechartsLineChart>
          )
        }}
      </ChartPlot>

      <ChartRows
        slot="line-chart-data"
        label="Line chart data"
        rows={rows}
        annotations={annotations}
        valueFormatter={valueFormatter}
        indexFormatter={indexFormatter}
      />
    </div>
  )
}

export { LineChart }
