"use client"

import * as React from "react"
import { Bar, CartesianGrid, BarChart as RechartsBarChart, XAxis, YAxis } from "recharts"

import { cn } from "@/lib/utils"
import {
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart"
import {
  AXIS_TICK,
  axisProps,
  BAR_RADIUS,
  buildChartConfig,
  chartDefaults,
  chartRows,
  chartSummary,
  type CommonChartProps,
  defaultIndexFormatter,
  defaultValueFormatter,
  GRID_PROPS,
  tooltipIndexLabel,
} from "@/components/ui/chart-core"
import { renderAnnotations } from "@/components/ui/chart-annotations"
import { ChartPlot, ChartRows } from "@/components/ui/chart-frame"
import { annotationHeadroom } from "@/components/ui/chart-labels"
import { tooltipRow } from "@/components/ui/chart-tooltip"
import { yAxisScale } from "@/components/ui/chart-scale"

// A bar wider than this reads as a block of colour rather than a measurement,
// so the band's leftover space stays as air.
const MAX_BAR_SIZE = 24

export type BarChartProps = CommonChartProps & {
  /** Corner radius on the top of each bar; the baseline end stays square. */
  radius?: number
  /** Fixes the bar width in pixels instead of letting it fill the band, capped at 24. */
  barSize?: number
}

function BarChart({
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
  // Columns have no last point to write a name beside, so a bar chart that
  // needs a key puts it under the plot.
  legend = "bottom",
  annotations,
  radius = BAR_RADIUS,
  barSize,
  ...props
}: BarChartProps) {
  const config = React.useMemo(() => buildChartConfig(series), [series])
  const rows = chartRows({ data, index, series, valueFormatter, indexFormatter })
  const scale = yAxisScale(data, series, { annotations })
  const summary = chartSummary("Bar chart", { data, index, series, indexFormatter })

  return (
    <div data-slot="bar-chart" className={cn("w-full", className)} {...props}>
      <ChartPlot
        height={height}
        config={config}
        role="img"
        aria-label={summary}
        className="aspect-auto w-full"
      >
        {(frame) => (
          // barGap is the 2px of surface that separates bars inside a group.
          <RechartsBarChart
            // Named once, by the container's role="img" and its summary; recharts'
            // keyboard layer would add an unnamed role="application" tab stop inside it.
            accessibilityLayer={false}
            data={data}
            barGap={2}
            margin={{ top: annotationHeadroom(annotations), right: 12, bottom: 0, left: 12 }}
          >
            {showGrid ? <CartesianGrid vertical={false} {...GRID_PROPS} /> : null}

            {showXAxis ? (
              <XAxis
                tick={AXIS_TICK}
                dataKey={index}
                {...axisProps}
                minTickGap={8}
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
            ) : null}

            {showTooltip ? (
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    labelFormatter={(_, payload) => tooltipIndexLabel(payload, index, indexFormatter)}
                    formatter={tooltipRow({ valueFormatter, series })}
                  />
                }
              />
            ) : null}

            {series.map((entry) => (
              <Bar
                key={entry.key}
                dataKey={entry.key}
                name={entry.label}
                fill={`var(--color-${entry.key})`}
                radius={[radius, radius, 0, 0]}
                barSize={barSize}
                maxBarSize={barSize ?? MAX_BAR_SIZE}
                isAnimationActive={false}
              />
            ))}

            {renderAnnotations(annotations)}

            {showLegend && legend !== "none" && series.length > 1 ? (
              <ChartLegend content={<ChartLegendContent />} />
            ) : null}
          </RechartsBarChart>
        )}
      </ChartPlot>

      <ChartRows
        slot="bar-chart-data"
        label="Bar chart data"
        rows={rows}
        annotations={annotations}
        valueFormatter={valueFormatter}
        indexFormatter={indexFormatter}
      />
    </div>
  )
}

export { BarChart }
