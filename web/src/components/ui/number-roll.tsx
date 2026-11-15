"use client"

import * as React from "react"

import { cn } from "@/lib/utils"
import { formatNumber } from "@/lib/format"

/** Rounds to whole units — the roll passes fractional values through every frame. */
function formatWhole(value: number) {
  return formatNumber(value, { maximumFractionDigits: 0 })
}

function easeOutCubic(t: number) {
  return 1 - (1 - t) ** 3
}

/** The theme's own slow duration, in milliseconds; the literal is the fallback for an install without the theme. */
const FALLBACK_DURATION = 320

/**
 * `--duration-slow`, resolved at the moment the value changes rather than read
 * once: the token is zeroed both by `prefers-reduced-motion` and by
 * `[data-motion="reduced"]`, so asking the document for it is what makes this
 * component honour either without a second code path.
 */
function tokenDuration(): number {
  if (typeof window === "undefined") return FALLBACK_DURATION
  const raw = window
    .getComputedStyle(document.documentElement)
    .getPropertyValue("--duration-slow")
    .trim()
  const seconds = raw.endsWith("ms") ? 0.001 : raw.endsWith("s") ? 1 : 0
  const parsed = Number.parseFloat(raw)
  if (!seconds || !Number.isFinite(parsed)) return FALLBACK_DURATION
  return parsed * seconds * 1000
}

/** The OS-level setting, for a project that installed the item without the theme's tokens. */
function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches
}

// `children` is what this renders, so a caller passing any would be ignored.
export type NumberRollProps = Omit<React.ComponentProps<"span">, "children"> & {
  value: number
  /** Receives the animating value every frame, so round inside it. */
  format?: (value: number) => string
  /** Milliseconds. Defaults to --duration-slow, which is 0ms under reduced motion. */
  duration?: number
}

/**
 * A number that rolls to its new value when it changes.
 *
 * The formatted final value is what renders on the server and on the first
 * client render — nothing animates on mount, so a page does not spend its
 * first frames showing numbers that are not yet true. Only a change animates,
 * from wherever the roll had got to, so a value that moves again mid-roll
 * continues rather than jumping back.
 */
function NumberRoll({
  className,
  value,
  format = formatWhole,
  duration,
  ...props
}: NumberRollProps) {
  // Only a roll in flight has state of its own; the rest of the time the
  // number shown is the number given, which is what makes the first render —
  // on the server and in the browser — the final value with nothing to correct.
  const [rolling, setRolling] = React.useState<number | null>(null)
  // Where the roll actually is, which is not `value` while one is running.
  const at = React.useRef(value)
  const display = rolling ?? value

  React.useEffect(() => {
    const from = at.current
    if (from === value) return

    const ms = duration ?? tokenDuration()
    if (ms <= 0 || prefersReducedMotion()) {
      at.current = value
      // Nothing to animate, and `display` already reads `value`. The frame
      // exists only to drop a roll that was in flight when the reader turned
      // motion off; with none in flight it changes nothing.
      const clear = requestAnimationFrame(() => setRolling(null))
      return () => cancelAnimationFrame(clear)
    }

    let frame = 0
    const start = performance.now()
    const step = (now: number) => {
      const progress = Math.min(1, (now - start) / ms)
      if (progress === 1) {
        at.current = value
        setRolling(null)
        return
      }
      const next = from + (value - from) * easeOutCubic(progress)
      at.current = next
      setRolling(next)
      frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [value, duration])

  return (
    <span
      data-slot="number-roll"
      data-rolling={display !== value || undefined}
      className={cn("tabular-nums", className)}
      {...props}
    >
      {/* A number in motion is decoration: read aloud it would be a stream of
          wrong values. The one that is true sits beside it, always. */}
      <span aria-hidden="true">{format(display)}</span>
      <span className="sr-only">{format(value)}</span>
    </span>
  )
}

export { NumberRoll }
