"use client"

import type { RowData } from "@tanstack/react-table"
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronsLeftIcon,
  ChevronsRightIcon,
} from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import type { DataTableInstance } from "@/components/ui/data-table/columns"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

export type DataTablePaginationProps<TData extends RowData> = {
  table: DataTableInstance<TData>
  pageSizeOptions?: number[]
  /** Shows "3 of 128 row(s) selected." on the left. */
  showSelectedCount?: boolean
  className?: string
}

/**
 * How many rows are ticked, and out of how many.
 *
 * A table that pages itself can count both off its own row models. One handed a
 * page at a time cannot: the filtered model holds the rows that arrived, so it
 * would report "2 of 10" for a selection spanning a 250-row result. In that
 * mode the ticks themselves are the count — selection is keyed by `getRowId`
 * and survives a page turn — and the total is the `rowCount` the caller gave.
 */
function selectionCounts<TData extends RowData>(table: DataTableInstance<TData>) {
  const served = table.options.manualPagination || table.options.manualFiltering
  return {
    // getRowCount already prefers options.rowCount over the row model.
    total: table.getRowCount(),
    selected: served
      ? Object.values(table.state.rowSelection).filter(Boolean).length
      : table.getFilteredSelectedRowModel().rows.length,
  }
}

/** The row below the table: how much is selected, how many rows a page holds, and where you are. */
function DataTablePagination<TData extends RowData>({
  table,
  pageSizeOptions = [10, 20, 30, 50],
  showSelectedCount = true,
  className,
}: DataTablePaginationProps<TData>) {
  const { pageIndex, pageSize } = table.state.pagination
  const { selected, total } = selectionCounts(table)
  // An empty table still sits on a page; "Page 1 of 0" would just be wrong.
  const pageCount = Math.max(table.getPageCount(), 1)

  return (
    <div
      data-slot="data-table-pagination"
      className={cn("flex flex-wrap items-center justify-between gap-x-6 gap-y-2", className)}
    >
      <div className="flex-1 text-sm text-muted-foreground">
        {showSelectedCount ? (
          <span data-slot="data-table-selected-count">
            {selected} of {total} row(s) selected.
          </span>
        ) : null}
      </div>

      <div className="flex items-center gap-2">
        <span className="hidden text-sm text-muted-foreground sm:inline">Rows per page</span>
        <Select
          value={String(pageSize)}
          onValueChange={(value) => {
            if (value) table.setPageSize(Number(value))
          }}
        >
          <SelectTrigger size="sm" aria-label="Rows per page" className="w-[4.25rem]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {pageSizeOptions.map((option) => (
              <SelectItem key={option} value={String(option)}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex items-center gap-2">
        <span
          data-slot="data-table-page-status"
          // Moving between pages is a change worth hearing about.
          aria-live="polite"
          className="text-sm tabular-nums whitespace-nowrap text-muted-foreground"
        >
          Page {pageIndex + 1} of {pageCount}
        </span>

        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label="Go to first page"
            disabled={!table.getCanPreviousPage()}
            onClick={() => table.firstPage()}
          >
            <ChevronsLeftIcon aria-hidden="true" className="rtl:rotate-180" />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label="Go to previous page"
            disabled={!table.getCanPreviousPage()}
            onClick={() => table.previousPage()}
          >
            <ChevronLeftIcon aria-hidden="true" className="rtl:rotate-180" />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label="Go to next page"
            disabled={!table.getCanNextPage()}
            onClick={() => table.nextPage()}
          >
            <ChevronRightIcon aria-hidden="true" className="rtl:rotate-180" />
          </Button>
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label="Go to last page"
            disabled={!table.getCanNextPage()}
            onClick={() => table.lastPage()}
          >
            <ChevronsRightIcon aria-hidden="true" className="rtl:rotate-180" />
          </Button>
        </div>
      </div>
    </div>
  )
}

export { DataTablePagination }
