"use client"

import * as React from "react"

/**
 * Keyboard rows: j and k (or the arrow keys) walk a table, x toggles the
 * selection on the row under the cursor, and Enter opens it.
 *
 * The pattern is the one a mail client uses, and the reason it is a hook rather
 * than a handler on each row is the tab order: a table of two hundred rows must
 * cost the reader one Tab press, not two hundred, so exactly one row is
 * focusable at a time and the cursor moves within it. The rows themselves stay
 * plain — they take `tabIndex` and an id from `rowProps`, and the container
 * carries the listener and `aria-activedescendant`, which is what tells a
 * screen reader that the focus inside the grid has moved.
 *
 * Nothing here reads the DOM: the cursor is an index into the ids it was given,
 * so a filtered or re-sorted table simply hands over a new list.
 */
export type UseRovingRowsOptions = {
  /** The row ids in the order they are rendered. */
  ids: string[]
  /** Fired by x — usually the row's own `toggleSelected`. */
  onToggle?: (id: string) => void
  /** Fired by Enter, and by a click that did not land on a control. */
  onActivate?: (id: string) => void
  /** Turns the whole thing off, for a table that is loading or empty. */
  enabled?: boolean
}

export type UseRovingRows = {
  /** The row the cursor is on, or undefined before the reader has used a key. */
  activeId: string | undefined
  setActiveId: (id: string | undefined) => void
  /** Spread onto the scroll container or the <tbody>. */
  containerProps: {
    onKeyDown: (event: React.KeyboardEvent) => void
    "aria-activedescendant": string | undefined
  }
  /** Spread onto each row, with the row's own id. */
  rowProps: (id: string) => {
    id: string
    tabIndex: number
    "data-active": true | undefined
    onFocus: () => void
  }
}

/** Prefixed so the id is unique on a page holding more than one table. */
function domId(scope: string, id: string) {
  return `${scope}-row-${id}`
}

export function useRovingRows({
  ids,
  onToggle,
  onActivate,
  enabled = true,
}: UseRovingRowsOptions): UseRovingRows {
  const scope = React.useId()
  const [activeId, setActiveId] = React.useState<string | undefined>(undefined)

  // A row that has gone — filtered out, or on the previous page — cannot keep
  // the cursor, and the reader should not have to press a key to get it back.
  const current = activeId !== undefined && ids.includes(activeId) ? activeId : undefined
  const cursor = current === undefined ? -1 : ids.indexOf(current)

  const focus = React.useCallback(
    (index: number) => {
      const id = ids[index]
      if (id === undefined) return
      setActiveId(id)
      document.getElementById(domId(scope, id))?.focus()
    },
    [ids, scope]
  )

  const onKeyDown = React.useCallback(
    (event: React.KeyboardEvent) => {
      if (!enabled || ids.length === 0) return
      // A key pressed inside a cell's own control — a checkbox, a menu, a
      // search box — belongs to that control.
      const target = event.target as HTMLElement | null
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return

      const key = event.key
      const next =
        key === "j" || key === "ArrowDown"
          ? Math.min(cursor + 1, ids.length - 1)
          : key === "k" || key === "ArrowUp"
            ? Math.max(cursor - 1, 0)
            : key === "Home"
              ? 0
              : key === "End"
                ? ids.length - 1
                : null

      if (next !== null) {
        event.preventDefault()
        focus(cursor === -1 && (key === "k" || key === "ArrowUp") ? ids.length - 1 : next)
        return
      }

      if (current === undefined) return
      if (key === "x") {
        event.preventDefault()
        onToggle?.(current)
      } else if (key === "Enter") {
        event.preventDefault()
        onActivate?.(current)
      }
    },
    [current, cursor, enabled, focus, ids, onActivate, onToggle]
  )

  const rowProps = React.useCallback(
    (id: string) => ({
      id: domId(scope, id),
      // Roving tabindex: the cursor's row, or the first one before the reader
      // has touched a key, so the table is one stop in the tab order.
      tabIndex: (current === undefined ? ids[0] === id : current === id) ? 0 : -1,
      "data-active": (current === id || undefined) as true | undefined,
      onFocus: () => setActiveId(id),
    }),
    [current, ids, scope]
  )

  return {
    activeId: current,
    setActiveId,
    containerProps: {
      onKeyDown,
      "aria-activedescendant": current === undefined ? undefined : domId(scope, current),
    },
    rowProps,
  }
}
