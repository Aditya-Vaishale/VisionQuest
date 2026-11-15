"use client"

import {
  columnFacetingFeature,
  columnFilteringFeature,
  columnSizingFeature,
  columnVisibilityFeature,
  createFacetedRowModel,
  createFacetedUniqueValues,
  createFilteredRowModel,
  createPaginatedRowModel,
  createSortedRowModel,
  filterFn_arrHas,
  filterFn_arrIncludes,
  filterFn_equals,
  filterFn_inDateRange,
  filterFn_includesString,
  filterFn_inNumberRange,
  filterFn_weakEquals,
  rowPaginationFeature,
  rowSelectionFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_basic,
  sortFn_datetime,
  sortFn_text,
  tableFeatures,
  type Column,
  type ColumnDef,
  type ReactTable,
  type Row,
  type RowData,
} from "@tanstack/react-table"
import { cva } from "class-variance-authority"

import { Checkbox } from "@/components/ui/checkbox"

export type DataTableColumnMeta = {
  /**
   * Where the header and the cells sit on the line. The names are the
   * left-to-right ones and the alignment is logical: "right" is the line's end,
   * the left of a right-to-left table, and "left" its start. Set "right" on
   * every numeric column.
   */
  align?: "left" | "center" | "right"
  /** The name shown in the View menu, when the column id is not a good one. */
  label?: string
  /** Extra classes for this column's header and cells. */
  className?: string
}

/**
 * The features every Vibra data table runs on. Exported so a column helper or a
 * hand-rolled useTable call can be typed against exactly the same set.
 *
 * The fn registries are named one by one rather than by spreading the exported
 * `filterFns`/`sortFns` objects, which are deprecated upstream and pull all
 * twenty-four built-ins (18 filter, 6 sort) into the bundle. What is registered is every name
 * `filterFn: "auto"` and `sortFn: "auto"` can resolve to — so a column of any
 * value type still filters and sorts correctly — plus `arrHas` for the faceted
 * filters. Add a name here before using it on a column def.
 */
export const dataTableFeatures = tableFeatures({
  columnFacetingFeature,
  columnFilteringFeature,
  columnSizingFeature,
  columnVisibilityFeature,
  rowPaginationFeature,
  rowSelectionFeature,
  rowSortingFeature,
  facetedRowModel: createFacetedRowModel(),
  facetedUniqueValues: createFacetedUniqueValues(),
  filteredRowModel: createFilteredRowModel(),
  paginatedRowModel: createPaginatedRowModel(),
  sortedRowModel: createSortedRowModel(),
  filterFns: {
    arrHas: filterFn_arrHas,
    arrIncludes: filterFn_arrIncludes,
    equals: filterFn_equals,
    inDateRange: filterFn_inDateRange,
    includesString: filterFn_includesString,
    inNumberRange: filterFn_inNumberRange,
    weakEquals: filterFn_weakEquals,
  },
  sortFns: {
    alphanumeric: sortFn_alphanumeric,
    basic: sortFn_basic,
    datetime: sortFn_datetime,
    text: sortFn_text,
  },
  columnMeta: {} as DataTableColumnMeta,
})

export type DataTableFeatures = typeof dataTableFeatures
export type DataTableColumnDef<TData extends RowData, TValue = unknown> = ColumnDef<DataTableFeatures, TData, TValue>
export type DataTableColumn<TData extends RowData, TValue = unknown> = Column<DataTableFeatures, TData, TValue>
export type DataTableRow<TData extends RowData> = Row<DataTableFeatures, TData>
export type DataTableInstance<TData extends RowData> = ReactTable<DataTableFeatures, TData>

/** Resolves a column id the way the table itself does, so facets can name a column by its accessor key. */
function columnIdOf(def: object): string | undefined {
  const column = def as { id?: string; accessorKey?: unknown; header?: unknown }
  if (column.id) return column.id
  if (column.accessorKey !== undefined) return String(column.accessorKey).replaceAll(".", "_")
  return typeof column.header === "string" ? column.header : undefined
}

// COUPLED TO registry/vibra/ui/table.tsx: TableHead ships h-10 and
// text-foreground. Column titles are labels, not data: the label register in
// ink, one step shorter than the rows they sit above.
const dataTableHeadVariants = cva("type-label bg-surface text-foreground", {
  variants: {
    // The header is a row too: a quarter step shorter than a body row at
    // either density, which is h-10 comfortable.
    size: {
      default: "h-[calc(var(--density-row,2.75rem)-0.25rem)] px-3",
      sm: "h-8 px-2.5",
    },
    // Logical, like TableHead's own text-start: a right-to-left table's titles
    // start at the right, and a numeric column's end at the left.
    align: { left: "text-start", center: "text-center", right: "text-end" },
    sticky: {
      // A border on a sticky <th> scrolls away with the row it belongs to; an
      // inset shadow is painted by the cell itself, so the hairline stays put.
      true: "sticky top-0 z-10 shadow-[inset_0_-1px_0_0_var(--rule)]",
      false: "",
    },
  },
  defaultVariants: { size: "default", align: "left", sticky: false },
})

const dataTableCellVariants = cva("", {
  variants: {
    // Only the default size follows the density token; `sm` is a caller
    // who has already chosen tight rows, and would overflow its own
    // h-9 if the cells grew underneath it.
    size: { default: "px-3 py-[var(--density-cell-y,0.75rem)]", sm: "px-2.5 py-2" },
    // "right" means numeric, set at the line's end, and a column of numerals
    // only lines up on tabular figures — the pairing simple-table.tsx makes.
    align: { left: "", center: "text-center", right: "text-end tabular-nums" },
  },
  defaultVariants: { size: "default", align: "left" },
})

// Selection is TableRow's own business now — the accent's fifth role, drawn as
// a brand-muted plane with a 2px rail and 500 weight, so it never reads as a
// pointer position and never reads by colour alone.
// Every plane a row can take is opaque, because the pinned first column below
// md takes its row's plane: the card at rest, and for a hover or an open menu
// TableRow's half-muted plane mixed into the card rather than laid over it —
// the same colour on the card, but solid, so a figure scrolling under the
// pinned cell never shows through it. Selected (brand-muted) and focused
// (muted) are solid already.
// Written out in full: Tailwind finds a class by reading the source, not by
// running it.
const dataTableRowVariants = cva(
  "bg-card hover:bg-[color-mix(in_srgb,var(--muted)_50%,var(--card))] has-aria-expanded:bg-[color-mix(in_srgb,var(--muted)_50%,var(--card))]",
  {
    variants: {
      size: { default: "h-[var(--density-row,2.75rem)]", sm: "h-9" },
      clickable: {
        true: "cursor-pointer focus-ring focus-visible:bg-muted",
        false: "",
      },
    },
    defaultVariants: { size: "default", clickable: false },
  }
)

// Nothing to show reads two ways: the data has not arrived yet, or the filters
// hid it. Only one of those is the reader's to fix.
const EMPTY_COPY = {
  filtered: {
    title: "No matching rows",
    description: "Clear the search or the filters to see everything again.",
  },
  unfiltered: { title: "No rows yet", description: undefined },
} as const

// A click on the checkbox or the ⋯ button is a click on that control, not on
// the row underneath it.
const INTERACTIVE =
  "a, button, input, select, textarea, label, [role='checkbox'], [role='menuitem'], [contenteditable='true']"

function fromControl(target: EventTarget | null) {
  return target instanceof Element && target.closest(INTERACTIVE) !== null
}

/** The <th>'s own sort state — omitted entirely on a column that cannot be sorted. */
function ariaSortOf<TData extends RowData>(column: DataTableColumn<TData>) {
  if (!column.getCanSort()) return undefined
  const sorted = column.getIsSorted()
  return sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"
}

export type SelectionColumnOptions<TData extends RowData> = {
  /** Names each checkbox after its own row — "Select row for Olivia Martin". */
  rowLabel?: (row: TData) => string
}

/** The leading checkbox column. Put it first in `columns`; `DataTable` never adds one for you. */
function selectionColumn<TData extends RowData>(
  options: SelectionColumnOptions<TData> = {}
): DataTableColumnDef<TData> {
  const { rowLabel } = options

  return {
    id: "select",
    size: 32,
    enableSorting: false,
    enableHiding: false,
    meta: { label: "Select" },
    header: ({ table }) => (
      <Checkbox
        checked={table.getIsAllPageRowsSelected()}
        indeterminate={table.getIsSomePageRowsSelected() && !table.getIsAllPageRowsSelected()}
        // Same reason as the per-row box below: nothing on this page can be
        // selected, so the control should not look like it can select it.
        disabled={!table.getRowModel().rows.some((row) => row.getCanSelect())}
        onCheckedChange={(checked) => table.toggleAllPageRowsSelected(checked)}
        aria-label="Select all rows on this page"
      />
    ),
    cell: ({ row }) => (
      <Checkbox
        checked={row.getIsSelected()}
        // enableRowSelection={false} makes the toggle a no-op; say so rather
        // than leaving a checkbox that looks live and does nothing.
        disabled={!row.getCanSelect()}
        onCheckedChange={(checked) => row.toggleSelected(checked)}
        aria-label={
          rowLabel ? `Select row for ${rowLabel(row.original)}` : `Select row ${row.index + 1}`
        }
      />
    ),
  }
}

export {
  ariaSortOf,
  columnIdOf,
  dataTableCellVariants,
  dataTableHeadVariants,
  dataTableRowVariants,
  EMPTY_COPY,
  fromControl,
  selectionColumn,
}
