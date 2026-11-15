"use client"

import * as React from "react"
import type { RowData } from "@tanstack/react-table"
import { SlidersHorizontalIcon, XIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  DataTableFacetedFilter,
  type DataTableFacet,
} from "@/components/ui/data-table/faceted-filter"
import type { DataTableInstance } from "@/components/ui/data-table/columns"
import { DataTableViewOptions } from "@/components/ui/data-table/view-options"
import { Input } from "@/components/ui/input"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"

export type DataTableToolbarProps<TData extends RowData> = {
  table: DataTableInstance<TData>
  /** Column id to search; the box disappears when it is unset. */
  searchKey?: string
  searchPlaceholder?: string
  facets?: DataTableFacet<TData>[]
  /** Extra controls, placed after the facets and before the View menu. */
  children?: React.ReactNode
  /**
   * Replaces the View menu at the end of the row — an export menu beside it, a
   * density switch, whatever the page needs there. Counts as content: a
   * toolbar that has one renders even with no search and no facets.
   */
  viewOptionsSlot?: React.ReactNode
  className?: string
}

/**
 * The row above the table: a search box, the facet filters, a reset, and the
 * View menu.
 *
 * It renders nothing at all when it has nothing to hold. The View menu on its
 * own is not content — a table with no search and no facets used to ship a bar
 * whose only occupant was a column picker nobody had asked for, and an empty
 * 32px strip above a table reads as a missing element.
 *
 * Below md the facets and the View menu move into one Filters sheet: six
 * controls wrapping onto three lines is most of a phone's first screen, and the
 * search box is the one of them worth keeping in view.
 */
function DataTableToolbar<TData extends RowData>({
  table,
  searchKey,
  searchPlaceholder = "Search...",
  facets,
  children,
  viewOptionsSlot,
  className,
}: DataTableToolbarProps<TData>) {
  const searchColumn = searchKey ? table.getColumn(searchKey) : undefined
  const filtered = table.state.columnFilters.length > 0
  const hasFacets = Boolean(facets?.length)

  if (!searchColumn && !hasFacets && !children && !viewOptionsSlot) return null

  const facetFilters = facets?.map((facet) => (
    <DataTableFacetedFilter
      key={facet.columnId}
      column={table.getColumn(facet.columnId)}
      title={facet.title}
      options={facet.options}
      // A server-filtered table holds one page of the result, so its own
      // per-value counts would be counts of that page.
      showCounts={!table.options.manualFiltering}
    />
  ))

  const reset = filtered ? (
    <Button
      type="button"
      data-slot="data-table-reset"
      variant="ghost"
      size="sm"
      onClick={() => table.resetColumnFilters()}
    >
      Reset
      <XIcon data-icon="inline-end" aria-hidden="true" />
    </Button>
  ) : null

  const viewOptions = viewOptionsSlot ?? <DataTableViewOptions table={table} />

  return (
    <div
      data-slot="data-table-toolbar"
      className={cn("flex flex-wrap items-center gap-2", className)}
    >
      {searchColumn ? (
        <Input
          value={(searchColumn.getFilterValue() as string | undefined) ?? ""}
          onChange={(event) => searchColumn.setFilterValue(event.target.value || undefined)}
          placeholder={searchPlaceholder}
          // The placeholder disappears the moment there is a value in the box.
          aria-label={searchPlaceholder}
          className="h-8 w-full max-w-56 text-sm"
        />
      ) : null}

      <div className="hidden flex-wrap items-center gap-2 md:flex">
        {facetFilters}
        {reset}
        {children}
        {viewOptions}
      </div>

      <Sheet>
        <SheetTrigger
          render={
            <Button
              type="button"
              data-slot="data-table-filters-trigger"
              variant="outline"
              size="sm"
              className="md:hidden"
            >
              <SlidersHorizontalIcon data-icon="inline-start" aria-hidden="true" />
              Filters
              {filtered ? (
                <span
                  data-slot="data-table-filters-count"
                  className="ms-1 rounded-full bg-brand-muted px-1.5 text-2xs font-medium text-brand"
                >
                  {table.state.columnFilters.length}
                </span>
              ) : null}
            </Button>
          }
        />
        <SheetContent side="bottom" className="max-h-[80svh] overflow-y-auto p-4">
          <SheetHeader className="p-0">
            <SheetTitle>Filters</SheetTitle>
            <SheetDescription>Narrow the rows, and choose what the table shows.</SheetDescription>
          </SheetHeader>
          <div
            data-slot="data-table-filters-panel"
            className="flex flex-col items-stretch gap-2 [&>*]:w-full [&_[data-slot=button]]:justify-start"
          >
            {facetFilters}
            {reset}
            {children}
            {viewOptions}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}

export { DataTableToolbar }
