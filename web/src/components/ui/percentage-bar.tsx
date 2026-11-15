import * as React from "react"

import { cn } from "@/lib/utils"
import { percentOf } from "@/lib/format"

export type ChartToken =
  | "chart-1"
  | "chart-2"
  | "chart-3"
  | "chart-4"
  | "chart-5"
  | "chart-6"
  | "chart-7"
  | "chart-8"

/** The palette in order. Segments that name no colour are painted from it, wrapping past the eighth. */
export const CHART_TOKENS: readonly ChartToken[] = [
  "chart-1",
  "chart-2",
  "chart-3",
  "chart-4",
  "chart-5",
  "chart-6",
  "chart-7",
  "chart-8",
]

// Spelled out rather than built from `bg-${token}`, because Tailwind scans for
// whole class names in the source and would find nothing to generate otherwise.
// rank-list imports this map so the two components share one palette.
export const CHART_BG: Record<ChartToken, string> = {
  "chart-1": "bg-chart-1",
  "chart-2": "bg-chart-2",
  "chart-3": "bg-chart-3",
  "chart-4": "bg-chart-4",
  "chart-5": "bg-chart-5",
  "chart-6": "bg-chart-6",
  "chart-7": "bg-chart-7",
  "chart-8": "bg-chart-8",
}

/**
 * Each segment's whole-number share of the total, by largest remainder: every
 * share is floored, then the points left over are handed out one at a time to
 * the largest fractional remainders, ties going to the later segment — so on a
 * perfect tie the last segment absorbs the rounding, where a spare point sits
 * at the end of the bar instead of shifting every boundary after it.
 *
 * That gives three guarantees at once — the shares sum to exactly 100, so the
 * bar never leaves a sliver of track showing; no share is ever negative; and
 * none is off its true value by more than a point.
 *
 * The guarantee that needs the flooring is the second one. Rounding each share
 * and handing the whole gap to the last segment reaches the same total but can
 * overshoot on the way: two halves that both round up (99 and 101 of 200, say)
 * already sum to 101 between them, leaving the last segment at −1, and a
 * negative width is invalid CSS that a browser drops on the floor. Flooring
 * first means there is only ever a surplus to give away, never a debt.
 *
 * Negative values count as zero, a zero-value segment always stays at zero,
 * and every share is zero when there is nothing to split.
 */
export function segmentPercentages(segments: { value: number }[]): number[] {
  const values = segments.map((segment) => Math.max(0, segment.value))
  const total = values.reduce((sum, value) => sum + value, 0)
  if (total <= 0) return values.map(() => 0)

  const exact = values.map((value) => percentOf(value, total))
  const shares = exact.map((percent) => Math.floor(percent))
  const leftover = 100 - shares.reduce((sum, share) => sum + share, 0)

  const byRemainder = exact
    .map((percent, index) => ({ index, remainder: percent - Math.floor(percent) }))
    .sort((a, b) => b.remainder - a.remainder || b.index - a.index)

  // leftover is the sum of the discarded fractions, so it is always smaller
  // than the segment count; the modulo is a belt-and-braces guard against
  // float drift rather than a case that arises.
  for (let i = 0; i < leftover; i++) shares[byRemainder[i % byRemainder.length].index] += 1

  return shares
}

/**
 * Whether a colour names one of the palette tokens. Checked against the token
 * list rather than with `color in CHART_BG`, which also answers true for
 * anything on Object's prototype — "toString" would have taken the palette
 * branch and come back with no colour at all.
 */
export function isChartToken(color: string): color is ChartToken {
  return (CHART_TOKENS as readonly string[]).includes(color)
}

/** A chart token paints from the palette; any other string is taken as a raw CSS colour. */
function segmentPaint(color: PercentageBarSegment["color"], index: number) {
  if (color === undefined) {
    return { className: CHART_BG[CHART_TOKENS[index % CHART_TOKENS.length]], style: undefined }
  }
  if (isChartToken(color)) {
    return { className: CHART_BG[color], style: undefined }
  }
  return { className: undefined, style: { backgroundColor: color } as React.CSSProperties }
}

const DEFAULT_FORMAT = (_value: number, percent: number) => `${percent}%`

export type PercentageBarSegment = {
  label: string
  value: number
  /** A chart token, or any CSS colour for a brand hue. Defaults to the palette in order. */
  color?: ChartToken | string
}

export type PercentageBarProps = React.ComponentProps<"div"> & {
  segments: PercentageBarSegment[]
  showLegend?: boolean
  /** Shows each segment's number in the legend. */
  showValues?: boolean
  /** Receives the raw value and its rounded share, e.g. (4820, 52) => "4,820 (52%)". */
  format?: (value: number, percent: number) => string
  height?: "sm" | "default"
}

function PercentageBar({
  className,
  segments,
  showLegend = true,
  showValues = true,
  format = DEFAULT_FORMAT,
  height = "default",
  ...props
}: PercentageBarProps) {
  const percents = segmentPercentages(segments)
  // The split is carried by colour alone inside the bar, so the whole reading
  // goes on the track as its accessible name — the legend may be turned off.
  const reading = segments.map((segment, i) => `${segment.label} ${percents[i]}%`).join(", ")

  return (
    <div
      data-slot="percentage-bar"
      data-height={height}
      className={cn("flex w-full flex-col gap-3", className)}
      {...props}
    >
      <div
        data-slot="percentage-bar-track"
        role="img"
        aria-label={reading}
        className={cn(
          "flex w-full overflow-hidden rounded-full bg-muted",
          height === "sm" ? "h-1.5" : "h-2"
        )}
      >
        {segments.map((segment, index) => {
          const paint = segmentPaint(segment.color, index)
          return (
            <div
              key={`${segment.label}-${index}`}
              data-slot="percentage-bar-segment"
              className={cn("h-full", paint.className)}
              style={{ width: `${percents[index]}%`, ...paint.style }}
            />
          )
        })}
      </div>

      {showLegend ? (
        <ul
          data-slot="percentage-bar-legend"
          className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs"
        >
          {segments.map((segment, index) => {
            const paint = segmentPaint(segment.color, index)
            return (
              <li
                key={`${segment.label}-${index}`}
                data-slot="percentage-bar-legend-item"
                className="flex items-center gap-1.5"
              >
                <span
                  data-slot="percentage-bar-swatch"
                  aria-hidden="true"
                  className={cn("size-2 shrink-0 rounded-full", paint.className)}
                  style={paint.style}
                />
                <span className="text-muted-foreground">{segment.label}</span>
                {showValues ? (
                  <span className="font-medium tabular-nums">
                    {format(segment.value, percents[index])}
                  </span>
                ) : null}
              </li>
            )
          })}
        </ul>
      ) : null}
    </div>
  )
}

export { PercentageBar }
