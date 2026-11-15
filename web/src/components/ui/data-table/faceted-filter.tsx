"use client"

import * as React from "react"
import type { RowData } from "@tanstack/react-table"
import { PlusCircleIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command"
import type { DataTableColumn } from "@/components/ui/data-table/columns"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Separator } from "@/components/ui/separator"

export type DataTableFacetOption = {
  label: string
  value: string
  icon?: React.ComponentType<{ className?: string }>
  /** How many rows carry this value. Give it when the server counted them; otherwise the table counts the rows it holds. */
  count?: number
}

export type DataTableFacet<TData extends RowData> = {
  /** The column this filter drives: an accessor key, or an explicit column id. */
  columnId: Extract<keyof TData, string> | (string & {})
  title: string
  options: DataTableFacetOption[]
}

export type DataTableFacetedFilterProps<TData extends RowData, TValue> = {
  /** Undefined when no column matches the facet's columnId; the filter then renders nothing. */
  column?: DataTableColumn<TData, TValue>
  title: string
  options: DataTableFacetOption[]
  /**
   * Whether the table's own count of each value may stand in for an option that
   * gives none. False for a server-filtered table, where the rows in hand are
   * one page of the result and counting them would report "3" for a value that
   * matches three hundred.
   */
  showCounts?: boolean
  className?: string
}

/** A multi-select filter for one column, with the row count beside every option. */
function DataTableFacetedFilter<TData extends RowData, TValue>({
  column,
  title,
  options,
  showCounts = true,
  className,
}: DataTableFacetedFilterProps<TData, TValue>) {
  if (!column) return null

  const selected = new Set((column.getFilterValue() as string[] | undefined) ?? [])
  const counts = showCounts ? column.getFacetedUniqueValues() : undefined
  const chosen = options.filter((option) => selected.has(option.value))

  const toggle = (value: string) => {
    const next = new Set(selected)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    column.setFilterValue(next.size > 0 ? Array.from(next) : undefined)
  }

  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            type="button"
            data-slot="data-table-faceted-filter"
            data-active={selected.size > 0 || undefined}
            variant="outline"
            size="sm"
            className={cn("border-dashed data-[active]:border-solid", className)}
          >
            <PlusCircleIcon data-icon="inline-start" aria-hidden="true" />
            {title}
            {chosen.length > 0 ? (
              <>
                <Separator orientation="vertical" aria-hidden="true" className="mx-0.5 h-4" />
                {/* Two names fit on the button; past that the count says more in less. */}
                {chosen.length > 2 ? (
                  <Badge variant="secondary" className="rounded-sm px-1 font-normal">
                    {chosen.length} selected
                  </Badge>
                ) : (
                  chosen.map((option) => (
                    <Badge
                      key={option.value}
                      variant="secondary"
                      className="rounded-sm px-1 font-normal"
                    >
                      {option.label}
                    </Badge>
                  ))
                )}
              </>
            ) : null}
          </Button>
        }
      />
      {/* COUPLED TO registry/vibra/ui/popover.tsx: the popover ships a padded
          w-72 panel, and a command list draws its own padding at its own width. */}
      <PopoverContent align="start" className="w-56 p-0">
        <Command>
          <CommandInput placeholder={title} />
          {/* Options are checked independently, and cmdk does not say so on its
              own — see the aria-checked on each item below. */}
          <CommandList aria-multiselectable="true">
            <CommandEmpty>No options match.</CommandEmpty>
            <CommandGroup>
              {options.map((option) => {
                const isSelected = selected.has(option.value)
                // A count the caller worked out wins: only they can count rows
                // the table was never handed.
                const count = option.count ?? counts?.get(option.value)
                return (
                  <CommandItem
                    key={option.value}
                    // Filter on the label, so the row count beside it never
                    // becomes part of what the search box matches.
                    value={option.label}
                    onSelect={() => toggle(option.value)}
                    // cmdk owns aria-selected, which it puts on the *highlighted*
                    // option — a cursor, not a choice. Checked state is its own
                    // attribute, so the two never contradict each other.
                    aria-checked={isSelected}
                    data-checked={isSelected ? "true" : undefined}
                  >
                    {option.icon ? (
                      <option.icon className="size-4 text-muted-foreground" />
                    ) : null}
                    {option.label}
                    {count !== undefined ? (
                      <span className="ms-auto text-xs tabular-nums text-muted-foreground">
                        {count}
                      </span>
                    ) : null}
                  </CommandItem>
                )
              })}
            </CommandGroup>
            {selected.size > 0 ? (
              <>
                <CommandSeparator />
                <CommandGroup>
                  <CommandItem
                    onSelect={() => column.setFilterValue(undefined)}
                    className="justify-center text-muted-foreground"
                  >
                    Clear filter
                  </CommandItem>
                </CommandGroup>
              </>
            ) : null}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

export { DataTableFacetedFilter }
