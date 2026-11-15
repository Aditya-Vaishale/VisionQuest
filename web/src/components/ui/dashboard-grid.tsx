import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

export type ColSpan = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12

/** How wide a cell is, either at every size or one width per breakpoint. */
export type ColSpanValue =
  | ColSpan
  | { base?: ColSpan; sm?: ColSpan; md?: ColSpan; lg?: ColSpan; xl?: ColSpan }

// Tailwind only emits the classes it can read in the source, so every
// breakpoint × span pair is spelled out here as a literal. Building the name
// by interpolating the number into a template string type-checks and then
// renders an unstyled cell, because no such class was ever generated.
// dashboard-grid.test.tsx asserts all 60 literals are present, so deleting one
// fails rather than silently dropping a column.
const COL_SPAN: Record<ColSpan, string> = {
  1: "col-span-1", 2: "col-span-2", 3: "col-span-3", 4: "col-span-4",
  5: "col-span-5", 6: "col-span-6", 7: "col-span-7", 8: "col-span-8",
  9: "col-span-9", 10: "col-span-10", 11: "col-span-11", 12: "col-span-12",
}

const COL_SPAN_SM: Record<ColSpan, string> = {
  1: "sm:col-span-1", 2: "sm:col-span-2", 3: "sm:col-span-3", 4: "sm:col-span-4",
  5: "sm:col-span-5", 6: "sm:col-span-6", 7: "sm:col-span-7", 8: "sm:col-span-8",
  9: "sm:col-span-9", 10: "sm:col-span-10", 11: "sm:col-span-11", 12: "sm:col-span-12",
}

const COL_SPAN_MD: Record<ColSpan, string> = {
  1: "md:col-span-1", 2: "md:col-span-2", 3: "md:col-span-3", 4: "md:col-span-4",
  5: "md:col-span-5", 6: "md:col-span-6", 7: "md:col-span-7", 8: "md:col-span-8",
  9: "md:col-span-9", 10: "md:col-span-10", 11: "md:col-span-11", 12: "md:col-span-12",
}

const COL_SPAN_LG: Record<ColSpan, string> = {
  1: "lg:col-span-1", 2: "lg:col-span-2", 3: "lg:col-span-3", 4: "lg:col-span-4",
  5: "lg:col-span-5", 6: "lg:col-span-6", 7: "lg:col-span-7", 8: "lg:col-span-8",
  9: "lg:col-span-9", 10: "lg:col-span-10", 11: "lg:col-span-11", 12: "lg:col-span-12",
}

const COL_SPAN_XL: Record<ColSpan, string> = {
  1: "xl:col-span-1", 2: "xl:col-span-2", 3: "xl:col-span-3", 4: "xl:col-span-4",
  5: "xl:col-span-5", 6: "xl:col-span-6", 7: "xl:col-span-7", 8: "xl:col-span-8",
  9: "xl:col-span-9", 10: "xl:col-span-10", 11: "xl:col-span-11", 12: "xl:col-span-12",
}

const ROW_SPAN = { 1: "row-span-1", 2: "row-span-2", 3: "row-span-3" } as const

// A span computed at runtime — from an API, from a cast, from untyped JS —
// can land outside 1..12 and miss the table, which would hand back undefined
// from a function that promises a string. Clamp to the nearest real column.
function lookup(table: Record<ColSpan, string>, span: ColSpan): string {
  return table[Math.min(12, Math.max(1, Math.round(span))) as ColSpan]
}

/** The `col-span` classes for a span, smallest breakpoint first; an empty string for no span. */
export function colSpanClass(span?: ColSpanValue): string {
  if (span === undefined) return ""
  if (typeof span === "number") return lookup(COL_SPAN, span)
  const { base, sm, md, lg, xl } = span
  return [
    base && lookup(COL_SPAN, base),
    sm && lookup(COL_SPAN_SM, sm),
    md && lookup(COL_SPAN_MD, md),
    lg && lookup(COL_SPAN_LG, lg),
    xl && lookup(COL_SPAN_XL, xl),
  ]
    .filter(Boolean)
    .join(" ")
}

const dashboardGridVariants = cva("grid", {
  variants: {
    // The track count holds at every breakpoint, so a cell's span means the
    // same thing everywhere; use a responsive colSpan to stack on small screens.
    columns: {
      2: "grid-cols-2",
      3: "grid-cols-3",
      4: "grid-cols-4",
      6: "grid-cols-6",
      12: "grid-cols-12",
    },
    // The default gap is the density token, so retightening a dashboard
    // moves the grid with the tables and the cards. The literal is the
    // comfortable value, for an install without the theme stylesheet; `sm`
    // is a choice the caller made, so it stays put.
    gap: { default: "gap-[var(--density-gap,1rem)]", sm: "gap-3" },
  },
  defaultVariants: { columns: 12, gap: "default" },
})

export type DashboardGridProps = React.ComponentProps<"div"> & {
  columns?: NonNullable<VariantProps<typeof dashboardGridVariants>["columns"]>
  gap?: NonNullable<VariantProps<typeof dashboardGridVariants>["gap"]>
}

/** The grid a dashboard page lays its widgets out on. */
function DashboardGrid({ className, columns = 12, gap = "default", ...props }: DashboardGridProps) {
  return (
    <div
      data-slot="dashboard-grid"
      data-columns={columns}
      data-gap={gap}
      className={cn(dashboardGridVariants({ columns, gap }), className)}
      {...props}
    />
  )
}

export type DashboardGridItemProps = React.ComponentProps<"div"> & {
  colSpan?: ColSpanValue
  rowSpan?: 1 | 2 | 3
}

/** One cell of a DashboardGrid; it spans the whole width until you narrow it. */
function DashboardGridItem({ className, colSpan, rowSpan, ...props }: DashboardGridItemProps) {
  const span = colSpanClass(colSpan)

  return (
    <div
      data-slot="dashboard-grid-item"
      data-col-span={
        colSpan === undefined ? "full" : typeof colSpan === "number" ? colSpan : "responsive"
      }
      data-row-span={rowSpan ?? 1}
      className={cn("min-w-0", span || "col-span-full", rowSpan && ROW_SPAN[rowSpan], className)}
      {...props}
    />
  )
}

export { DashboardGrid, DashboardGridItem, dashboardGridVariants }
