"use client"

import * as React from "react"
import { ReferenceArea, ReferenceLine } from "recharts"

import { annotationPaint, type ChartAnnotation } from "@/components/ui/chart-core"

/* -------------------------------------------------------------------------- */
/* Annotations                                                                 */
/* -------------------------------------------------------------------------- */


// The eyebrow register, drawn in SVG: 11px, 600, the tone's own ink.
const EYEBROW = {
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: "0.06em",
} as const

/** The one dash on a chart: reference lines and the compare ghost share it. */
export const DASH = "4 4"

/**
 * A halo round a label in the plane the chart sits on: the stroke is painted
 * under the fill, so the words stay legible where they cross a column, a
 * line or the wash under an area. --chart-surface falls back to the card, as
 * the active dot's ring does.
 */
export const LABEL_HALO = {
  stroke: "var(--chart-surface, var(--card))",
  strokeWidth: 4,
  strokeLinejoin: "round",
  paintOrder: "stroke",
} as const

function annotationLabel(
  text: string,
  paint: string,
  position: "insideTopLeft" | "insideTopRight" | "top"
) {
  return {
    value: text.toUpperCase(),
    position,
    fill: paint,
    offset: 6,
    ...EYEBROW,
    ...LABEL_HALO,
  }
}

/**
 * Goal lines, event markers and bands as recharts elements.
 *
 * An array rather than a fragment: recharts reads its children by type, and
 * `React.Children` flattens an array into that list while a fragment arrives as
 * one opaque child it does not look inside.
 */
export function renderAnnotations(
  annotations: ChartAnnotation[] = [],
  options: { yAxisId?: string } = {}
): React.ReactElement[] {
  const { yAxisId } = options

  return annotations.map((annotation, i) => {
    const paint = annotationPaint(annotation.tone)

    if (annotation.kind === "band") {
      return (
        <ReferenceArea
          key={`band-${i}`}
          yAxisId={yAxisId}
          x1={annotation.from}
          x2={annotation.to}
          fill={paint}
          fillOpacity={0.1}
          stroke="none"
          aria-label={annotation.label}
          label={annotationLabel(
            annotation.label,
            paint,
            annotation.align === "end" ? "insideTopRight" : "insideTopLeft"
          )}
        />
      )
    }

    if (annotation.kind === "event") {
      return (
        <ReferenceLine
          key={`event-${i}`}
          yAxisId={yAxisId}
          x={annotation.x}
          stroke={paint}
          strokeWidth={1}
          strokeDasharray={DASH}
          label={annotationLabel(annotation.label, paint, "top")}
        />
      )
    }

    const onX = annotation.axis === "x"
    return (
      <ReferenceLine
        key={`line-${i}`}
        yAxisId={yAxisId}
        x={onX ? annotation.value : undefined}
        y={onX ? undefined : annotation.value}
        stroke={paint}
        strokeWidth={1}
        strokeDasharray={DASH}
        label={annotationLabel(annotation.label, paint, onX ? "top" : "insideTopLeft")}
      />
    )
  })
}

