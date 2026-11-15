"use client"

import type { RowData } from "@tanstack/react-table"
import { SlidersHorizontalIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import type { DataTableInstance } from "@/components/ui/data-table/columns"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

export type DataTableViewOptionsProps<TData extends RowData> = {
  table: DataTableInstance<TData>
  className?: string
}

/** The View menu: one checkbox per hideable column, labelled from its meta.label or its id. */
function DataTableViewOptions<TData extends RowData>({ table, className }: DataTableViewOptionsProps<TData>) {
  const columns = table.getAllColumns().filter((column) => column.getCanHide())
  if (columns.length === 0) return null

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            data-slot="data-table-view-options"
            variant="outline"
            size="sm"
            // "View" alone says nothing about what it views.
            aria-label="View columns"
            className={cn("ms-auto", className)}
          >
            <SlidersHorizontalIcon data-icon="inline-start" aria-hidden="true" />
            View
          </Button>
        }
      />
      <DropdownMenuContent align="end" className="w-auto min-w-40">
        {/* COUPLED TO registry/vibra/ui/dropdown-menu.tsx: the label is a
            Base UI group label and throws outside a group. */}
        <DropdownMenuGroup>
          <DropdownMenuLabel>Columns</DropdownMenuLabel>
          {columns.map((column) => (
            <DropdownMenuCheckboxItem
              key={column.id}
              checked={column.getIsVisible()}
              onCheckedChange={(checked) => column.toggleVisibility(checked)}
              closeOnClick={false}
            >
              <span className="capitalize">{column.columnDef.meta?.label ?? column.id}</span>
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export { DataTableViewOptions }
