"use client"

import { ArrowDownIcon, ArrowUpIcon, ChevronsUpDownIcon, EyeOffIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import type { DataTableColumn } from "@/components/ui/data-table/columns"
import type { RowData } from "@tanstack/react-table"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

// Read out after the column name, so the direction never depends on the arrow
// glyph alone. The <th> also carries aria-sort; this is what a button user hears.
const SORT_LABELS = {
  asc: "sorted ascending",
  desc: "sorted descending",
  none: "not sorted",
} as const

const SORT_ICONS = {
  asc: ArrowUpIcon,
  desc: ArrowDownIcon,
  none: ChevronsUpDownIcon,
} as const

export type DataTableColumnHeaderProps<TData extends RowData, TValue> = {
  column: DataTableColumn<TData, TValue>
  title: string
  className?: string
}

/** A sortable column title: a real button that opens Asc / Desc / Hide and says which way it is sorted. */
function DataTableColumnHeader<TData extends RowData, TValue>({
  column,
  title,
  className,
}: DataTableColumnHeaderProps<TData, TValue>) {
  const align = column.columnDef.meta?.align ?? "left"

  if (!column.getCanSort()) {
    return (
      <span data-slot="data-table-column-header" className={cn("block truncate", className)}>
        {title}
      </span>
    )
  }

  const sorted = column.getIsSorted()
  const state = sorted === "asc" ? "asc" : sorted === "desc" ? "desc" : "none"
  const SortIcon = SORT_ICONS[state]

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            data-slot="data-table-column-header"
            data-sorted={state}
            variant="ghost"
            size="sm"
            // The visible title stays inside the name, so speech control still
            // reaches this button by saying what is printed on it.
            aria-label={`${title}, ${SORT_LABELS[state]}`}
            className={cn(
              // The label register in ink, like a title that cannot sort; the
              // arrow, not the colour, says which column is ordering the rows.
              "-mx-2.5 h-7 text-sm font-medium text-foreground",
              align === "right" && "ms-auto",
              className
            )}
          >
            {title}
            <SortIcon aria-hidden="true" className="size-3.5" />
          </Button>
        }
      />
      {/* COUPLED TO registry/vibra/ui/dropdown-menu.tsx: the menu popup is sized
          to its anchor, and this anchor is a short title button. */}
      <DropdownMenuContent align={align === "right" ? "end" : "start"} className="w-auto min-w-32">
        <DropdownMenuItem onClick={() => column.toggleSorting(false)}>
          <ArrowUpIcon className="text-muted-foreground" />
          Asc
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => column.toggleSorting(true)}>
          <ArrowDownIcon className="text-muted-foreground" />
          Desc
        </DropdownMenuItem>
        {column.getCanHide() ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => column.toggleVisibility(false)}>
              <EyeOffIcon className="text-muted-foreground" />
              Hide
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export { DataTableColumnHeader }
