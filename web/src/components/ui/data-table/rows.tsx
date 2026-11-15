"use client"

import * as React from "react"
import type { RowData } from "@tanstack/react-table"
import { SearchXIcon } from "lucide-react"
import { type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"
import { useRovingRows } from "@/hooks/use-roving-rows"
import {
  ariaSortOf,
  dataTableCellVariants,
  dataTableHeadVariants,
  dataTableRowVariants,
  EMPTY_COPY,
  fromControl,
  type DataTableInstance,
  type DataTableRow,
} from "@/components/ui/data-table/columns"
import { EmptyState } from "@/components/ui/empty-state"
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

/**
 * Below md the first column is pinned, so a wide table scrolls its figures past
 * a name that stays put. The cell takes the row's own background rather than a
 * fixed one, so a hovered or selected row keeps its plane under the pinned cell
 * instead of showing a card-coloured hole — which is why every plane
 * dataTableRowVariants gives a row is opaque: a translucent hover showed the
 * figures scrolling underneath straight through the pinned cell.
 */
const STICKY_FIRST_COLUMN =
  "max-md:[&_[data-slot=table-cell]:first-child]:sticky max-md:[&_[data-slot=table-cell]:first-child]:start-0 max-md:[&_[data-slot=table-cell]:first-child]:z-10 max-md:[&_[data-slot=table-cell]:first-child]:bg-inherit max-md:[&_[data-slot=table-head]:first-child]:sticky max-md:[&_[data-slot=table-head]:first-child]:start-0 max-md:[&_[data-slot=table-head]:first-child]:z-20"

/**
 * A table wider than its panel scrolls in Table's own box, which is then a tab
 * stop with a ring drawn inside its edge — where the pinned first column and a
 * sticky header, painted above it, would cover it. So the panel draws the ring
 * instead, around its frame where nothing lies over it, and the box's own is
 * turned off.
 */
const FOCUSED_SCROLL_BOX =
  "has-[>[data-slot=table-container]:focus-visible]:focus-outline [&>[data-slot=table-container]:focus-visible]:outline-none"

/** The panel's frame, shared by the rows and by the skeleton that stands in for them. */
export function dataTablePanelClass(stickyHeader?: boolean, className?: string) {
  return cn(
    "overflow-hidden panel",
    STICKY_FIRST_COLUMN,
    FOCUSED_SCROLL_BOX,
    // The header sticks to the table's own scroll container, so that container
    // needs a height to scroll within.
    stickyHeader && "[&_[data-slot=table-container]]:max-h-(--data-table-max-h)",
    className
  )
}

export type DataTableRowsProps<TData extends RowData> = {
  table: DataTableInstance<TData>
  size?: NonNullable<VariantProps<typeof dataTableRowVariants>["size"]>
  /** Pins the header and scrolls the body inside the panel. */
  stickyHeader?: boolean
  /**
   * Dims the rows while the next page is on its way. For a table whose rows
   * come from a server: the frame keeps its border and its height, so a slow
   * page never collapses the layout under the reader's cursor.
   */
  busy?: boolean
  /**
   * Replaces the built-in empty state, which distinguishes filtered from empty.
   * Words are set as one muted line; an element — an EmptyState with the next
   * step in it — is seated as it is.
   */
  emptyMessage?: React.ReactNode
  onRowClick?: (row: TData) => void
  /**
   * j/k to walk the rows, x to select the one under the cursor, Enter to open
   * it, and one tab stop for the whole table. Off for a table nobody reads with
   * the keyboard, or one nested inside another widget's own key handling.
   */
  keyboard?: boolean
  /**
   * A strip under the rows, inside the panel — the pagination, usually — so
   * the count and the page controls sit on the sheet the rows do, under one
   * rule, rather than floating beneath the frame.
   */
  footer?: React.ReactNode
  /**
   * Names the table, as its `<caption>`: read out when a screen reader enters
   * it or lists the page's tables, and kept out of sight unless
   * `captionVisible`. Prefer `aria-labelledby` at a heading already on show.
   */
  caption?: React.ReactNode
  /** Draws the caption above the rows instead of keeping it for screen readers. */
  captionVisible?: boolean
  /** Names the table when nothing on show does. */
  "aria-label"?: string
  /** Names the table by a heading on show — the card's title, the page's h1. */
  "aria-labelledby"?: string
  className?: string
}

/**
 * The rows themselves, in their panel: the header, the body, what stands in
 * for them when there are none, and a footer strip when there is one.
 *
 * Split out of `DataTable` because a table whose rows arrive one page at a time
 * needs the frame without the toolbar or the pagination — it draws those itself,
 * around a `useTable` instance it owns, so that the query behind them is the
 * page it fetched. `DataTable` renders this too, so both read the same.
 */
export function DataTableRows<TData extends RowData>({
  table,
  size = "default",
  stickyHeader = false,
  busy = false,
  emptyMessage,
  onRowClick,
  keyboard = true,
  footer,
  caption,
  captionVisible = false,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
  className,
}: DataTableRowsProps<TData>) {
  const rows = table.getRowModel().rows
  const columnCount = Math.max(table.getVisibleFlatColumns().length, 1)
  const emptyState = table.state.columnFilters.length > 0 ? "filtered" : "unfiltered"

  const byId = React.useMemo(() => new Map(rows.map((row) => [row.id, row])), [rows])
  const roving = useRovingRows({
    ids: React.useMemo(() => rows.map((row) => row.id), [rows]),
    enabled: keyboard && rows.length > 0,
    onToggle: (id) => {
      const row = byId.get(id)
      if (row?.getCanSelect()) row.toggleSelected()
    },
    onActivate: (id) => {
      const row = byId.get(id)
      if (row) onRowClick?.(row.original)
    },
  })

  // Built once rather than inline per row, and only when there is somewhere to
  // click through to.
  const rowInteraction = (row: DataTableRow<TData>) =>
    onRowClick
      ? {
          // The roving grid hands out the tab stops when it is on. With it off
          // the rows carried a key handler nothing could ever focus, so a
          // clickable table was reachable by mouse only.
          ...(keyboard ? null : { tabIndex: 0 }),
          onClick: (event: React.MouseEvent) => {
            if (!fromControl(event.target)) onRowClick(row.original)
          },
          onKeyDown: (event: React.KeyboardEvent) => {
            if (event.target !== event.currentTarget) return
            if (event.key !== "Enter" && event.key !== " ") return
            event.preventDefault()
            onRowClick(row.original)
          },
        }
      : undefined

  return (
    <div
      data-slot="data-table-panel"
      data-busy={busy || undefined}
      className={dataTablePanelClass(stickyHeader, className)}
      {...(keyboard ? roving.containerProps : null)}
    >
      <Table
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        aria-busy={busy || undefined}
        className={cn("transition-opacity", busy && "opacity-60")}
      >
        {caption ? (
          <TableCaption
            data-visible={captionVisible || undefined}
            className={
              captionVisible
                ? "mt-0 caption-top px-3 pt-3 pb-2 text-start text-sm text-muted-foreground"
                : "sr-only"
            }
          >
            {caption}
          </TableCaption>
        ) : null}
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id} className="hover:bg-transparent">
              {headerGroup.headers.map((header) => {
                const meta = header.column.columnDef.meta
                const width = header.column.columnDef.size
                return (
                  <TableHead
                    key={header.id}
                    colSpan={header.colSpan}
                    data-align={meta?.align ?? "left"}
                    aria-sort={ariaSortOf(header.column)}
                    style={width ? { width } : undefined}
                    className={cn(
                      dataTableHeadVariants({ size, align: meta?.align, sticky: stickyHeader }),
                      meta?.className
                    )}
                  >
                    {header.isPlaceholder ? null : <table.FlexRender header={header} />}
                  </TableHead>
                )
              })}
            </TableRow>
          ))}
        </TableHeader>

        <TableBody>
          {rows.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={columnCount} className="p-0">
                <div
                  data-slot="data-table-empty"
                  role="status"
                  className="flex items-center justify-center"
                >
                  {emptyMessage === undefined ? (
                    <EmptyState size="sm" icon={<SearchXIcon />} {...EMPTY_COPY[emptyState]} />
                  ) : typeof emptyMessage === "string" || typeof emptyMessage === "number" ? (
                    <span className="py-6 text-sm text-muted-foreground">{emptyMessage}</span>
                  ) : (
                    // An element — an EmptyState with its own way out — is seated
                    // as it is: inside the muted line it lost its title's ink and
                    // sat a block inside an inline span.
                    emptyMessage
                  )}
                </div>
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row) => (
              <TableRow
                key={row.id}
                data-state={row.getIsSelected() ? "selected" : undefined}
                {...(keyboard ? roving.rowProps(row.id) : null)}
                {...rowInteraction(row)}
                className={dataTableRowVariants({ size, clickable: Boolean(onRowClick) })}
              >
                {row.getVisibleCells().map((cell) => {
                  const meta = cell.column.columnDef.meta
                  return (
                    <TableCell
                      key={cell.id}
                      data-align={meta?.align ?? "left"}
                      className={cn(
                        dataTableCellVariants({ size, align: meta?.align }),
                        meta?.className
                      )}
                    >
                      <table.FlexRender cell={cell} />
                    </TableCell>
                  )
                })}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      {footer ? (
        <div data-slot="data-table-footer" className="border-t border-rule px-3 py-2.5">
          {footer}
        </div>
      ) : null}
    </div>
  )
}
