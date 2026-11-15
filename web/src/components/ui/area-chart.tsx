"use client"

import * as React from "react"
import { Area, CartesianGrid, AreaChart as RechartsAreaChart, XAxis, YAxis } from "recharts"

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

export type AreaChartProps = CommonChartProps & {
  /** Bands summing to a total instead of curves laid over one another. */
  stacked?: boolean
  /**
   * Where the value axis starts. `zero` takes zero in, as every chart does by
   * default; `auto` fits the axis to the data's own range, for a level — a
   * rate, a price — whose movement a zero floor would flatten. For a level,
   * prefer `LineChart`: on `auto` an area's fill runs down to the plot's
   * floor, not to zero, so its size is no magnitude. Ignored when `stacked`:
   * a stack is read from zero.
   */
  baseline?: ChartBaseline
  curve?: "monotone" | "linear" | "step"
  /** Fades each fill toward the baseline. Off by default: the look prints flat washes. */
  gradient?: boolean
}

// A wash, not a block: an overlaid area is a tenth of its stroke's colour, so
// the curve behind it still reads. A stacked band is the mark itself, so it
// carries enough paint to be told from its neighbour.
const FILL_OPACITY = { stacked: 0.65, overlaid: 0.1 } as const
const GRADIENT_STOPS = {
  stacked: { top: 0.85, bottom: 0.45 },
  overlaid: { top: 0.3, bottom: 0.02 },
} as const

function AreaChart({
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
  stacked = false,
  baseline = "zero",
  curve = "monotone",
  gradient = false,
  ...props
}: AreaChartProps) {
  const ghosts = React.useMemo(() => compareSeries(series, compare), [series, compare])
  const config = React.useMemo(
    () => buildChartConfig([...series, ...ghosts]),
    [series, ghosts]
  )
  // useId's colons are not valid in a url(#...) reference.
  const uid = React.useId().replace(/:/g, "")
  const stops = stacked ? GRADIENT_STOPS.stacked : GRADIENT_STOPS.overlaid
  const rows = chartRows({ data, index, series, valueFormatter, indexFormatter })
  // A stack is read from zero: fitted to its totals, every band below the
  // smallest total would be drawn with no scale beneath it.
  const floor: ChartBaseline = stacked ? "zero" : baseline
  const scale = yAxisScale(data, series, { stacked, compare, annotations, baseline: floor })
  const summary = chartSummary("Area chart", { data, index, series, indexFormatter })
  const inline = showLegend ? legend : "none"

  return (
    <div
      data-slot="area-chart"
      data-baseline={floor}
      data-curve={curve}
      data-stacked={stacked || undefined}
      data-gradient={gradient || undefined}
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
          <RechartsAreaChart
            // Named once, by the container's role="img" and its summary; recharts'
            // keyboard layer would add an unnamed role="application" tab stop inside it.
            accessibilityLayer={false}
            data={data}
            margin={{ top: annotationHeadroom(annotations), right: inlineLabelWidth(series, placement), bottom: 0, left: 12 }}
          >
            {gradient ? (
              <defs>
                {series.map((entry) => (
                  <linearGradient
                    key={entry.key}
                    id={`${uid}-${entry.key}`}
                    x1="0"
                    y1="0"
                    x2="0"
                    y2="1"
                  >
                    <stop offset="0%" stopColor={`var(--color-${entry.key})`} stopOpacity={stops.top} />
                    <stop
                      offset="100%"
                      stopColor={`var(--color-${entry.key})`}
                      stopOpacity={stops.bottom}
                    />
                  </linearGradient>
                ))}
              </defs>
            ) : null}

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
            ) : floor === "auto" ? (
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
              <Area
                key={entry.key}
                dataKey={entry.key}
                name={entry.label}
                type={curve}
                stroke={`var(--color-${entry.key})`}
                fill="none"
                {...COMPARE_STROKE}
              />
            ))}

            {series.map((entry) => (
              <Area
                key={entry.key}
                dataKey={entry.key}
                name={entry.label}
                type={curve}
                stackId={stacked ? "total" : undefined}
                stroke={`var(--color-${entry.key})`}
                strokeWidth={STROKE_WIDTH}
                strokeLinecap="round"
                strokeLinejoin="round"
                fill={gradient ? `url(#${uid}-${entry.key})` : `var(--color-${entry.key})`}
                fillOpacity={gradient ? 1 : FILL_OPACITY[stacked ? "stacked" : "overlaid"]}
                dot={false}
                activeDot={ACTIVE_DOT}
                isAnimationActive={false}
              >
                {directLabel(entry, { legend: placement, count: data.length })}
              </Area>
            ))}

            {renderAnnotations(annotations)}

            {showLegend && placement === "bottom" && series.length > 1 ? (
              <ChartLegend content={<ChartLegendContent />} />
            ) : null}
          </RechartsAreaChart>
          )
        }}
      </ChartPlot>

      <ChartRows
        slot="area-chart-data"
        label="Area chart data"
        rows={rows}
        annotations={annotations}
        valueFormatter={valueFormatter}
        indexFormatter={indexFormatter}
      />
    </div>
  )
}

export { AreaChart }
