import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { ArrowDownIcon, ArrowUpIcon, MinusIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { formatDelta } from "@/lib/format"

const metricDeltaVariants = cva(
  "inline-flex w-fit items-center gap-1 font-medium whitespace-nowrap tabular-nums [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
  {
    variants: {
      // Tone is derived from `trend` and `positiveIsGood`, never passed in: a
      // drop in churn is good, a drop in revenue is not.
      tone: {
        good: "text-success",
        bad: "text-danger",
        neutral: "text-muted-foreground",
      },
      variant: {
        text: "",
        badge: "rounded-md px-1.5 py-0.5",
        // The annotation on a card strip: a tinted capsule with a hairline of
        // its own tone, one line tall.
        pill: "h-5 rounded-full px-2 ring-1 ring-inset",
      },
      size: {
        default: "text-sm",
        sm: "text-xs [&_svg:not([class*='size-'])]:size-3",
      },
    },
    compoundVariants: [
      { variant: "badge", tone: "good", className: "bg-success-muted" },
      { variant: "badge", tone: "bad", className: "bg-danger-muted" },
      { variant: "badge", tone: "neutral", className: "bg-muted" },
      { variant: "pill", tone: "good", className: "bg-success-muted ring-success/20" },
      { variant: "pill", tone: "bad", className: "bg-danger-muted ring-danger/20" },
      { variant: "pill", tone: "neutral", className: "bg-muted ring-border" },
    ],
    defaultVariants: { tone: "neutral", variant: "text", size: "default" },
  }
)

/** The arrow each trend draws. Exported so anything else rendering a delta chip draws the same one. */
export const TREND_ICONS = { up: ArrowUpIcon, down: ArrowDownIcon, neutral: MinusIcon } as const

// Read out before the number so the direction never depends on color alone —
// "up +12.0%", "down −3", "no change 0%".
/** The word a screen reader hears before the number. Exported alongside TREND_ICONS. */
export const TREND_LABELS = { up: "up", down: "down", neutral: "no change" } as const

export type MetricDeltaTrend = keyof typeof TREND_ICONS

export type MetricDeltaProps = React.ComponentProps<"span"> & {
  /** The change itself: a ratio for "percent" (0.12 → "+12.0%"), a raw amount otherwise. */
  value: number
  format?: "percent" | "number" | "compact"
  /** Defaults to the sign of `value`. Set it to describe a change the number alone doesn't. */
  trend?: "up" | "down" | "neutral"
  /** False for metrics where down is the win — churn, latency, cost. */
  positiveIsGood?: boolean
  showIcon?: boolean
  variant?: NonNullable<VariantProps<typeof metricDeltaVariants>["variant"]>
  size?: NonNullable<VariantProps<typeof metricDeltaVariants>["size"]>
}

function MetricDelta({
  className,
  value,
  format = "percent",
  trend,
  positiveIsGood = true,
  showIcon = true,
  variant = "text",
  size = "default",
  ...props
}: MetricDeltaProps) {
  const resolvedTrend = trend ?? (value > 0 ? "up" : value < 0 ? "down" : "neutral")
  const isGood = resolvedTrend === "up" ? positiveIsGood : !positiveIsGood
  const tone = resolvedTrend === "neutral" ? "neutral" : isGood ? "good" : "bad"
  const TrendIcon = TREND_ICONS[resolvedTrend]

  return (
    <span
      data-slot="metric-delta"
      data-trend={resolvedTrend}
      data-tone={tone}
      className={cn(metricDeltaVariants({ tone, variant, size }), className)}
      {...props}
    >
      {showIcon ? <TrendIcon aria-hidden="true" /> : null}
      <span className="sr-only">{`${TREND_LABELS[resolvedTrend]} `}</span>
      {formatDelta(value, { style: format })}
    </span>
  )
}

export { MetricDelta, metricDeltaVariants }
