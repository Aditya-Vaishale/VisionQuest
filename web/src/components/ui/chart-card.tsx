import * as React from "react"
import { ChartColumnIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { chartDefaults } from "@/components/ui/chart-core"
import { EmptyState } from "@/components/ui/empty-state"
import { ChartSkeleton } from "@/components/ui/loading-skeletons"
import { Reveal } from "@/components/ui/reveal"

// A ChartSkeleton is a legend, a plot, and a row of tick labels; the two text
// rows and their gaps take about this much, so subtracting them keeps the card
// the same height whether it is loading, empty, or plotting.
const SKELETON_CHROME = 56

// `title` is content here, not the HTML tooltip attribute, so it replaces it.
export type ChartCardProps = Omit<React.ComponentProps<"div">, "title"> & {
  title: React.ReactNode
  description?: React.ReactNode
  /** Sits at the top right — a time range, an export menu, a link out. */
  actions?: React.ReactNode
  footer?: React.ReactNode
  /** Swaps the chart for a skeleton of the same height and sets aria-busy. */
  loading?: boolean
  /** Swaps the chart for an empty state; loading wins if both are set. */
  empty?: boolean
  emptyMessage?: React.ReactNode
  /** Height of the chart area, so all three states reserve the same space. */
  height?: number
}

function ChartCard({
  className,
  title,
  description,
  actions,
  footer,
  loading = false,
  empty = false,
  emptyMessage = "No data for this range.",
  height = chartDefaults.height,
  children,
  ...props
}: ChartCardProps) {
  const state = loading ? "loading" : empty ? "empty" : "ready"

  return (
    <Card
      data-slot="chart-card"
      data-state={state}
      aria-busy={loading || undefined}
      // The card's padding is the density token, so a chart card and the
      // stat cards beside it stay on one rhythm. The literal is the
      // comfortable value, for an install without the theme stylesheet.
      className={cn("gap-4 [--card-spacing:var(--density-card,1rem)]", className)}
      {...props}
    >
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {/* A chart's subtitle is a caption, not body copy: 13px under a 15px
            title is one step, which is what the register table asks for. */}
        {description ? (
          <CardDescription className="text-label">{description}</CardDescription>
        ) : null}
        {actions ? (
          <CardAction className="flex items-center gap-2">{actions}</CardAction>
        ) : null}
      </CardHeader>

      <CardContent>
        {/* Empty is checked first only when the answer is known: while it is
            still loading, "nothing to plot" has not been established yet. */}
        {empty && !loading ? (
          <EmptyState
            size="sm"
            icon={<ChartColumnIcon />}
            title={emptyMessage}
            className="h-(--chart-card-height)"
            style={{ "--chart-card-height": `${height}px` } as React.CSSProperties}
          />
        ) : (
          // The skeleton dissolves off the plot rather than being swapped for
          // it, and the card morphs between the two heights — so a dashboard
          // full of charts settles instead of snapping.
          <Reveal
            ready={!loading}
            skeleton={<ChartSkeleton height={Math.max(80, height - SKELETON_CHROME)} />}
          >
            {children}
          </Reveal>
        )}
      </CardContent>

      {footer ? (
        <CardFooter className="text-xs text-muted-foreground">{footer}</CardFooter>
      ) : null}
    </Card>
  )
}

export { ChartCard }
