"use client"

import * as React from "react"
import { Cell, Pie, PieChart } from "recharts"

import { cn } from "@/lib/utils"
import { formatPercent } from "@/lib/format"
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { chartDefaults, defaultValueFormatter, seriesColor } from "@/components/ui/chart-core"
import type { ChartToken } from "@/components/ui/percentage-bar"

// The plot's radius is half its shortest side and the ring stops just inside
// it, so the hole is measured against the same radius rather than in raw pixels.
const OUTER_PERCENT = 90
const MIN_RING_PERCENT = 12

/**
 * Both radii as a share of the plot's own radius. innerRadius arrives in pixels,
 * which stops meaning anything once the box is smaller than it — as a share it
 * shrinks with the box, and the clamp always leaves a ring to draw.
 */
export function donutRadii(height: number, innerRadius: number): { inner: string; outer: string } {
  const available = Math.max(height, 1) / 2
  const inner = Math.round((Math.max(0, innerRadius) / available) * 100)
  return {
    inner: `${Math.min(inner, OUTER_PERCENT - MIN_RING_PERCENT)}%`,
    outer: `${OUTER_PERCENT}%`,
  }
}

// The centre sits inside the hole, so its value steps down with the ring
// rather than overflowing it. Its label stays on the 12px meta register at
// every size: the small ring's 10px arbitrary size was under the floor.
const CENTER_VALUE_SIZE = { sm: "text-base", md: "text-xl", lg: "text-2xl" } as const

export type DonutChartSlice = {
  name: string
  value: number
  /** A chart token, or any CSS colour. Defaults to the palette in order. */
  color?: ChartToken | string
}

export type DonutChartProps = React.ComponentProps<"div"> & {
  data: DonutChartSlice[]
  valueFormatter?: (n: number) => string
  height?: number
  /** Radius of the hole in pixels at the given height; it becomes a share of
   * the plot radius, clamped so the ring never closes up. */
  innerRadius?: number
  /** Sits under the centre value, e.g. "Total sessions". */
  centerLabel?: React.ReactNode
  /** Defaults to the formatted total; pass null for a plain ring. */
  centerValue?: React.ReactNode
  showLegend?: boolean
}

function DonutChart({
  className,
  data,
  valueFormatter = defaultValueFormatter,
  height = chartDefaults.height,
  innerRadius = 60,
  centerLabel,
  centerValue,
  showLegend = chartDefaults.showLegend,
  ...props
}: DonutChartProps) {
  const total = data.reduce((sum, slice) => sum + slice.value, 0)
  // Colour is assigned by position, never by name: two slices may legitimately
  // carry the same name ("Other", an unnamed bucket), and keying by it would
  // give them one colour and one React key between them. The resolved colour
  // rides on each datum as `fill`, which is where the tooltip reads it back.
  const slices = React.useMemo(
    () =>
      data.map((slice, i) => ({
        ...slice,
        fill: seriesColor({ key: slice.name, label: slice.name, color: slice.color }, i),
      })),
    [data]
  )
  // Labels only — the slices are painted per Cell, so there is no --color-<key>
  // to emit, and a name with a space in it never becomes an invalid custom property.
  const config = React.useMemo<ChartConfig>(
    () => Object.fromEntries(data.map((slice) => [slice.name, { label: slice.name }])),
    [data]
  )
  const share = (value: number) => (total > 0 ? formatPercent(value / total) : formatPercent(0))
  const radii = donutRadii(height, innerRadius)
  const centerSize = height < 160 ? "sm" : height < 240 ? "md" : "lg"
  // With nothing to plot, a centred "0" reads as a real total; the name on the
  // ring already says there is no data.
  const hasCenter = centerValue !== null && (data.length > 0 || centerValue !== undefined)

  return (
    <div
      data-slot="donut-chart"
      className={cn("flex w-full flex-col items-center gap-4", className)}
      {...props}
    >
      <div className="relative w-full" style={{ height }}>
        <ChartContainer
          config={config}
          role="img"
          aria-label={
            data.length === 0
              ? "Donut chart with no data."
              : `Donut chart of ${data.length} parts totalling ${valueFormatter(total)}.`
          }
          className="absolute inset-0 aspect-auto size-full"
        >
          <PieChart
            // Named once, by the container's role="img" and its summary; recharts'
            // keyboard layer would add an unnamed role="application" tab stop inside it.
            accessibilityLayer={false}
            margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
            <ChartTooltip
              content={
                <ChartTooltipContent
                  hideLabel
                  // The primitive prints raw numbers; the row is rebuilt here so
                  // the share sits beside the value the caller formatted.
                  formatter={(value, name, _item, _index, payload) => (
                    <>
                      <span
                        className="size-2.5 shrink-0 rounded-[2px]"
                        // The hovered datum itself, so a repeated name still
                        // shows the colour of the slice under the pointer.
                        style={{ backgroundColor: (payload as { fill?: string })?.fill }}
                      />
                      <div className="flex flex-1 items-center justify-between gap-3 leading-none">
                        <span className="text-muted-foreground">{name}</span>
                        <span className="font-medium tabular-nums">
                          {`${valueFormatter(Number(value))} · ${share(Number(value))}`}
                        </span>
                      </div>
                    </>
                  )}
                />
              }
            />
            <Pie
              data={slices}
              dataKey="value"
              nameKey="name"
              innerRadius={radii.inner}
              outerRadius={radii.outer}
              // A 2px stroke in the surface colour is the gap between slices —
              // white space, not a border drawn around a mark.
              stroke="var(--chart-surface, var(--card))"
              strokeWidth={2}
              // No draw-in (CONVENTIONS §6), in any mode: recharts' own default
              // answers only the OS setting, so under [data-motion="reduced"]
              // the ring still swept round for a second and a half.
              isAnimationActive={false}
            >
              {slices.map((slice, i) => (
                <Cell key={i} fill={slice.fill} />
              ))}
            </Pie>
          </PieChart>
        </ChartContainer>

        {hasCenter ? (
          <div
            data-slot="donut-chart-center"
            data-size={centerSize}
            className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-0.5 text-center"
          >
            <span
              className={cn(
                "font-semibold tracking-tight tabular-nums",
                CENTER_VALUE_SIZE[centerSize]
              )}
            >
              {centerValue ?? valueFormatter(total)}
            </span>
            {centerLabel ? (
              <span className="text-xs text-muted-foreground">
                {centerLabel}
              </span>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* Always rendered when there are parts: with the legend off it becomes
          the only place the slice values are readable as text. */}
      <ul
        data-slot="donut-chart-legend"
        aria-label="Donut chart parts"
        hidden={data.length === 0}
        className={cn(
          showLegend ? "flex flex-wrap justify-center gap-x-4 gap-y-1.5 text-xs" : "sr-only"
        )}
      >
        {slices.map((slice, i) => (
          <li key={i} className="flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="size-2 shrink-0 rounded-[2px]"
              style={{ backgroundColor: slice.fill }}
            />
            <span className="text-muted-foreground">{slice.name}</span>
            <span className="font-medium tabular-nums">{valueFormatter(slice.value)}</span>
            <span className="text-muted-foreground tabular-nums">{share(slice.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export { DonutChart }
