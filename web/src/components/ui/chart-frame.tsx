"use client"

import * as React from "react"

import { cn } from "@/lib/utils"
import { useReducedMotion } from "@/hooks/use-reduced-motion"
import { ChartContainer } from "@/components/ui/chart"
import { annotationRows, type ChartAnnotation } from "@/components/ui/chart-core"
import { fitsYAxis } from "@/components/ui/chart-scale"
import { ChartSkeleton } from "@/components/ui/loading-skeletons"

/* -------------------------------------------------------------------------- */
/* The frame: measure, then draw                                              */
/* -------------------------------------------------------------------------- */


// A ChartSkeleton is a legend, a plot and a row of tick labels; the two text
// rows and their gaps take about this much, so the skeleton reserves the same
// box the finished chart will fill.
const SKELETON_CHROME = 56

/** What a chart's body is told about the box it is being drawn into. */
export type ChartFrame = {
  /** The plot's own width in px, or 0 before it has been measured. */
  width: number
  /** False until one layout has happened — the skeleton holds the space until then. */
  measured: boolean
  reduced: boolean
  /** Whether the value axis both was asked for and fits in the box. */
  yAxis: (asked: boolean) => boolean
}

export type ChartPlotProps = Omit<React.ComponentProps<typeof ChartContainer>, "children"> & {
  height: number
  /** The recharts chart to draw, given what is known about the box. */
  children: (frame: ChartFrame) => React.ComponentProps<typeof ChartContainer>["children"]
}

/**
 * A chart's box: measured first, drawn second.
 *
 * Nothing can be measured on the server, so the skeleton holds the chart's
 * space until the first client layout, and the ChartContainer inside then
 * measures its own box and draws at that size — which is also what makes the
 * mount fade a fade of the finished chart rather than of a mis-sized one. The
 * width measured here is what decides whether a value axis fits, so that
 * decision is handed to the chart body rather than guessed at.
 */
function ChartPlot({ height, className, style, children, ...props }: ChartPlotProps) {
  const [width, setWidth] = React.useState(0)
  const [measured, setMeasured] = React.useState(false)
  const plot = React.useRef<HTMLDivElement | null>(null)
  // Asked of the plot itself, so a frame that asked for less motion on its own
  // wrapper is heard; the document root would not have carried it.
  const reduced = useReducedMotion(plot)

  const ref = React.useCallback((node: HTMLDivElement | null) => {
    plot.current = node
    if (!node) return
    const read = () => setWidth(Math.round(node.getBoundingClientRect().width))
    read()
    // One layout has now happened, whether or not it produced a number: an
    // environment with no layout engine reports 0 forever, and holding a
    // skeleton there would mean no chart is ever drawn at all.
    setMeasured(true)
    if (typeof ResizeObserver !== "function") return
    const observer = new ResizeObserver(read)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return (
    <div ref={ref} data-slot="chart-plot" className="w-full">
      {measured ? (
        <ChartContainer
          // The one piece of motion a chart has: it fades in when it first has a
          // size, and never again — a re-render on new data leaves the element
          // mounted, so the animation does not restart. Duration and easing are
          // the theme's tokens, which are zeroed under reduced motion.
          className={cn(
            !reduced && "animate-in fade-in-0 duration-(--duration-base) ease-(--ease-standard)",
            className
          )}
          style={{ height, ...style }}
          {...props}
        >
          {children({
            width,
            measured,
            reduced,
            yAxis: (asked: boolean) => asked && fitsYAxis(height, width),
          })}
        </ChartContainer>
      ) : (
        <ChartSkeleton height={Math.max(80, height - SKELETON_CHROME)} />
      )}
    </div>
  )
}

export type ChartRowsProps = {
  slot: string
  label: string
  rows: { label: string; readings: string }[]
  annotations?: ChartAnnotation[]
  valueFormatter?: (n: number) => string
  indexFormatter?: (v: string | number) => string
}

/**
 * A chart's numbers as text. Every plotted point, then every annotation drawn
 * over them — a goal line a sighted reader can see has to be readable too.
 */
function ChartRows({
  slot,
  label,
  rows,
  annotations,
  valueFormatter,
  indexFormatter,
}: ChartRowsProps) {
  const notes = annotationRows(annotations, { valueFormatter, indexFormatter })

  return (
    <ul data-slot={slot} aria-label={label} className="sr-only">
      {rows.map((row, i) => (
        <li key={`row-${i}`}>{`${row.label}: ${row.readings}`}</li>
      ))}
      {notes.map((note, i) => (
        <li key={`note-${i}`} data-slot="chart-annotation-row">
          {note}
        </li>
      ))}
    </ul>
  )
}


export { ChartPlot, ChartRows }
