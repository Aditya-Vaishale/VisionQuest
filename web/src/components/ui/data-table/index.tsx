"use client"

import * as React from "react"
import {
  useTable,
  type ColumnFiltersState,
  type OnChangeFn,
  type PaginationState,
  type RowData,
  type RowSelectionState,
  type SortingState,
  type ColumnVisibilityState,
} from "@tanstack/react-table"
import { type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"
import {
  columnIdOf,
  dataTableFeatures,
  dataTableRowVariants,
  type DataTableColumnDef,
  type DataTableInstance,
} from "@/components/ui/data-table/columns"
import type { DataTableFacet } from "@/components/ui/data-table/faceted-filter"
import { DataTablePagination } from "@/components/ui/data-table/pagination"
import { DataTableRows, dataTablePanelClass } from "@/components/ui/data-table/rows"
import { DataTableToolbar } from "@/components/ui/data-table/toolbar"
import { TableSkeleton } from "@/components/ui/loading-skeletons"

// A barrel, so building a table never needs more than one import from
// `@/components/ui/data-table`. The sibling modules export exactly their own
// component and its props type; `columns.tsx` also holds internals
// (`columnIdOf`, `fromControl`, `EMPTY_COPY`, `ariaSortOf`), so it is listed by
// name rather than starred.
export {
  dataTableCellVariants,
  dataTableFeatures,
  dataTableHeadVariants,
  dataTableRowVariants,
  selectionColumn,
  type DataTableColumn,
  type DataTableColumnDef,
  type DataTableColumnMeta,
  type DataTableFeatures,
  type DataTableInstance,
  type DataTableRow,
  type SelectionColumnOptions,
} from "@/components/ui/data-table/columns"
export * from "@/components/ui/data-table/column-header"
export * from "@/components/ui/data-table/faceted-filter"
export * from "@/components/ui/data-table/pagination"
export * from "@/components/ui/data-table/rows"
export * from "@/components/ui/data-table/row-actions"
export * from "@/components/ui/data-table/toolbar"
export * from "@/components/ui/data-table/view-options"

export type DataTableProps<TData extends RowData, TValue = unknown> = React.ComponentProps<"div"> & {
  columns: DataTableColumnDef<TData, TValue>[]
  data: TData[]
  /** Column id the search box filters on; without it there is no search box. */
  searchKey?: string
  searchPlaceholder?: string
  facets?: DataTableFacet<TData>[]
  /** Extra toolbar controls, placed after the facets. */
  toolbar?: (table: DataTableInstance<TData>) => React.ReactNode
  /** Replaces the toolbar's View menu — an export menu, a density switch. */
  viewOptionsSlot?: React.ReactNode
  /** j/k to walk the rows, x to select, Enter to open. On by default. */
  keyboard?: boolean
  pageSize?: number
  pageSizeOptions?: number[]
  enableRowSelection?: boolean
  initialSorting?: SortingState
  emptyMessage?: React.ReactNode
  loading?: boolean
  onRowClick?: (row: TData) => void
  /** Scrolls the rows under a pinned header instead of growing the page. */
  stickyHeader?: boolean
  /**
   * Names the table, as its `<caption>` — out of sight unless `captionVisible`.
   * `aria-label` and `aria-labelledby` name the table too, not the wrapper;
   * prefer `aria-labelledby` at the card's or the page's own heading.
   */
  caption?: React.ReactNode
  /** Draws the caption above the rows instead of keeping it for screen readers. */
  captionVisible?: boolean
  size?: NonNullable<VariantProps<typeof dataTableRowVariants>["size"]>
  /** Keeps selection attached to the row, not its index. Use it whenever rows can move. */
  getRowId?: (row: TData) => string
  /**
   * Slices of table state the caller owns. Pass one and it is controlled — the
   * table renders what you hand it and reports every change through the
   * matching `on*Change` — so a page fetched from a server can drive the same
   * frame the client-side table uses. Slices you leave out stay internal.
   */
  state?: Partial<{
    pagination: PaginationState
    sorting: SortingState
    columnFilters: ColumnFiltersState
    rowSelection: RowSelectionState
    columnVisibility: ColumnVisibilityState
  }>
  onPaginationChange?: OnChangeFn<PaginationState>
  onSortingChange?: OnChangeFn<SortingState>
  onColumnFiltersChange?: OnChangeFn<ColumnFiltersState>
  onRowSelectionChange?: OnChangeFn<RowSelectionState>
  onColumnVisibilityChange?: OnChangeFn<ColumnVisibilityState>
  /**
   * The rows are one page a server already paged, so the table renders them as
   * they came instead of slicing them again. `rowCount` is then the only way it
   * can know how many pages there are.
   */
  manualPagination?: boolean
  /** The rows arrive sorted; the header still reports what was clicked. */
  manualSorting?: boolean
  /** The rows arrive filtered; the toolbar still reports what was chosen. */
  manualFiltering?: boolean
  /** How many rows the query matched, not how many arrived. Pass it with `manualPagination`. */
  rowCount?: number
}

/** TanStack's default header, and an sr-only "Actions" for a row-menu column that names none. */
function defaultHeader({ header }: { header: { column: { id: string; columnDef: { accessorKey?: unknown; accessorFn?: unknown; meta?: { label?: string } } } } }): React.ReactNode {
  const { id, columnDef } = header.column
  if (typeof columnDef.accessorKey === "string") return columnDef.accessorKey
  if (columnDef.accessorFn) return id
  if (id === "actions") return <span className="sr-only">{columnDef.meta?.label ?? "Actions"}</span>
  return null
}

/**
 * What a column is before its own definition speaks. 0 reads as "size me from
 * my content"; a column that sets `size` gets it. The header a column gets when
 * it names none is TanStack's own — its accessor key, else nothing — except
 * the row menu's: an `id: "actions"` column draws no title, but its header cell
 * still says what it holds, to a screen reader walking the columns and to axe's
 * empty-table-header. A table built on `useTable` directly (a server-paged
 * one, a card grid) passes this too, so no header cell is ever empty.
 */
const dataTableDefaultColumn = { size: 0, header: defaultHeader }

/** A sortable, filterable, paginated table: toolbar above, rows in a panel with the pagination as its footer strip. */

function DataTable<TData extends RowData, TValue = unknown>({
  columns,
  data,
  searchKey,
  searchPlaceholder,
  facets,
  toolbar,
  viewOptionsSlot,
  keyboard = true,
  pageSize = 10,
  pageSizeOptions,
  enableRowSelection = true,
  initialSorting,
  emptyMessage,
  loading = false,
  onRowClick,
  stickyHeader = false,
  caption,
  captionVisible,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
  size = "default",
  className,
  getRowId,
  state,
  onPaginationChange,
  onSortingChange,
  onColumnFiltersChange,
  onRowSelectionChange,
  onColumnVisibilityChange,
  manualPagination = false,
  manualSorting = false,
  manualFiltering = false,
  rowCount,
  ...props
}: DataTableProps<TData, TValue>) {
  // Serialised rather than passed straight through, so an inline `facets`
  // literal does not rebuild every column on every render — and via JSON, so no
  // separator can collide with a column id.
  const facetKey = JSON.stringify((facets ?? []).map((facet) => facet.columnId))

  // The two filters this component drives get their filter function named
  // rather than left to `filterFn: "auto"`, whose choice depends on the value
  // type it samples: a facet writes an array of values, and the search box
  // writes a substring. A column that declares its own `filterFn` keeps it.
  const resolvedColumns = React.useMemo(() => {
    const facetIds = new Set<string>(JSON.parse(facetKey))
    return columns.map((column) => {
      if ("filterFn" in column && column.filterFn) return column
      const id = columnIdOf(column) ?? ""
      // arrHas keeps the rows whose own value is one of the chosen ones.
      if (facetIds.has(id)) return { ...column, filterFn: "arrHas" } as DataTableColumnDef<TData, TValue>
      // includesString stringifies the cell, so search works on any value type.
      if (id === searchKey) {
        return { ...column, filterFn: "includesString" } as DataTableColumnDef<TData, TValue>
      }
      return column
    })
  }, [columns, facetKey, searchKey])

  const controlled = {
    ...(state ? { state } : {}),
    ...(onPaginationChange ? { onPaginationChange } : {}),
    ...(onSortingChange ? { onSortingChange } : {}),
    ...(onColumnFiltersChange ? { onColumnFiltersChange } : {}),
    ...(onRowSelectionChange ? { onRowSelectionChange } : {}),
    ...(onColumnVisibilityChange ? { onColumnVisibilityChange } : {}),
  }

  const table = useTable({
    features: dataTableFeatures,
    // ColumnDef is invariant in its value type, so a columns array narrowed
    // to TValue is not a columns array of unknown, however fine each member is.
    columns: resolvedColumns as DataTableColumnDef<TData>[],
    data,
    defaultColumn: dataTableDefaultColumn,
    enableRowSelection,
    getRowId,
    manualPagination,
    manualSorting,
    manualFiltering,
    rowCount,
    // Every feature seeds its own slice with `{ ...defaults, ...initialState }`,
    // so a `sorting: undefined` key here would wipe the default empty array out
    // and the first sort would throw. Only pass the key when there is a value.
    initialState: {
      pagination: { pageIndex: 0, pageSize },
      ...(initialSorting ? { sorting: initialSorting } : {}),
    },
    // Same rule for the controlled half: each feature supplies its own
    // `on*Change` — the one that writes the internal state — and an explicit
    // `undefined` here would replace it, leaving the table unable to sort or
    // filter itself. So only the keys the caller actually passed are spread.
    ...controlled,
  })

  const columnCount = Math.max(table.getVisibleFlatColumns().length, 1)
  const hasSelectionColumn = resolvedColumns.some((column) => columnIdOf(column) === "select")

  return (
    <div
      data-slot="data-table"
      data-size={size}
      data-sticky-header={stickyHeader || undefined}
      className={cn(
        "flex w-full flex-col gap-3",
        // Declared on the root so a caller's className can override it —
        // on the panel it would shadow whatever they set from out here.
        stickyHeader && "[--data-table-max-h:32rem]",
        className
      )}
      {...props}
    >
      <DataTableToolbar
        table={table}
        searchKey={searchKey}
        searchPlaceholder={searchPlaceholder}
        facets={facets}
        viewOptionsSlot={viewOptionsSlot}
      >
        {toolbar?.(table)}
      </DataTableToolbar>

      {loading ? (
        <div
          data-slot="data-table-panel"
          role="status"
          aria-busy="true"
          className={dataTablePanelClass(stickyHeader)}
        >
          <span className="sr-only">Loading rows</span>
          {/* COUPLED TO registry/vibra/ui/loading-skeletons.tsx: TableSkeleton
              draws its own frame, and this panel already has one. */}
          <TableSkeleton rows={pageSize} columns={columnCount} className="rounded-none border-0" />
        </div>
      ) : (
        <DataTableRows
          table={table}
          size={size}
          stickyHeader={stickyHeader}
          caption={caption}
          captionVisible={captionVisible}
          aria-label={ariaLabel}
          aria-labelledby={ariaLabelledBy}
          emptyMessage={emptyMessage}
          onRowClick={onRowClick}
          keyboard={keyboard}
          footer={
            <DataTablePagination
              table={table}
              pageSizeOptions={pageSizeOptions}
              showSelectedCount={enableRowSelection && hasSelectionColumn}
            />
          }
        />
      )}
    </div>
  )
}

export { DataTable, dataTableDefaultColumn }
