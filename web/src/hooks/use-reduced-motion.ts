"use client"

import * as React from "react"

const QUERY = "(prefers-reduced-motion: reduce)"

/**
 * Whether the document is currently asking for less motion.
 *
 * Two signals, one answer: the reader's OS setting, and `[data-motion="reduced"]`
 * on an ancestor — the switch a preview frame or a page flips to ask for the
 * same thing. The second is read the way the theme states it, off
 * `--duration-base`: the token is zeroed by both, so JavaScript that has to
 * decide (recharts' `isAnimationActive` is a prop, not a stylesheet) agrees with
 * the CSS half without a second code path or a second convention.
 */
export function prefersReducedMotion(element?: Element | null): boolean {
  if (typeof window === "undefined") return false
  if (window.matchMedia?.(QUERY).matches) return true

  const target = element ?? document.documentElement
  const raw = window.getComputedStyle(target).getPropertyValue("--duration-base").trim()
  // An install without the theme resolves the token to "", which is not a
  // request for less motion — only an explicit zero is.
  if (raw === "") return false
  return Number.parseFloat(raw) === 0
}

/**
 * Tracks {@link prefersReducedMotion}, re-reading when the OS setting changes
 * and when a `data-motion` attribute is added or removed anywhere above.
 *
 * Pass a ref to the node that should answer: the token is inherited, so reading
 * it there sees a `data-motion` set anywhere between that node and the root.
 * Without one the document root answers, which is right for a whole page and
 * wrong inside a frame that asked for less motion on its own wrapper.
 *
 * False on the server and on the first client render, so the markup React
 * hydrates is the markup it rendered; the first effect settles it before paint.
 */
export function useReducedMotion(element?: React.RefObject<Element | null>): boolean {
  const [reduced, setReduced] = React.useState(false)

  React.useEffect(() => {
    // Read from the caller's own node when it has one. The token is inherited,
    // so any element inside the subtree carries the answer — and reading the
    // document root instead missed `[data-motion="reduced"]` set on anything
    // below it, which is exactly where a preview frame sets it.
    const read = () => setReduced(prefersReducedMotion(element?.current))
    read()

    const mql = window.matchMedia?.(QUERY)
    mql?.addEventListener("change", read)

    // `data-motion` may be set on the html element, on a preview frame, or on a
    // wrapper in between, so the whole subtree is watched for the attribute
    // rather than one known node.
    const observer =
      typeof MutationObserver === "function"
        ? new MutationObserver(read)
        : undefined
    observer?.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-motion"],
      subtree: true,
    })

    return () => {
      mql?.removeEventListener("change", read)
      observer?.disconnect()
    }
  }, [element])

  return reduced
}
