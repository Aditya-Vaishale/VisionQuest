"use client"

import * as React from "react"
import { EllipsisIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

export type DataTableRowAction = {
  label: React.ReactNode
  onSelect: () => void
  icon?: React.ReactNode
  /** Renders in the danger tone and sits behind its own separator. */
  destructive?: boolean
  /** Displayed right-aligned, e.g. "⌘C". Purely a hint; wire the key up yourself. */
  shortcut?: string
  separatorBefore?: boolean
}

export type DataTableRowActionsProps = {
  actions: DataTableRowAction[]
  /** Name the row here — "Open menu for Olivia Martin" — so 30 identical buttons stop sounding identical. */
  label?: string
  className?: string
}

/** The trailing ⋯ button on a row, and the menu of things you can do to that row. */
function DataTableRowActions({
  actions,
  label = "Open row menu",
  className,
}: DataTableRowActionsProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            data-slot="data-table-row-actions"
            variant="ghost"
            size="icon-sm"
            aria-label={label}
            className={cn("ms-auto text-muted-foreground", className)}
          >
            <EllipsisIcon aria-hidden="true" />
          </Button>
        }
      />
      {/* COUPLED TO registry/vibra/ui/dropdown-menu.tsx: the popup is sized to
          its anchor, and this anchor is a 28px icon button. */}
      <DropdownMenuContent align="end" className="w-auto min-w-40">
        {actions.map((action, index) => (
          <React.Fragment key={index}>
            {action.separatorBefore && index > 0 ? <DropdownMenuSeparator /> : null}
            <DropdownMenuItem
              data-slot="data-table-row-action"
              variant={action.destructive ? "destructive" : "default"}
              onClick={action.onSelect}
            >
              {action.icon ? (
                <span className="flex items-center [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4">
                  {action.icon}
                </span>
              ) : null}
              {action.label}
              {action.shortcut ? (
                <DropdownMenuShortcut>{action.shortcut}</DropdownMenuShortcut>
              ) : null}
            </DropdownMenuItem>
          </React.Fragment>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export { DataTableRowActions }
