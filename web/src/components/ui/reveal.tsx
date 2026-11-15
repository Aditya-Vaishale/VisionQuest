"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

/** The theme's own base duration, in milliseconds; the literal is the fallback for an install without the theme. */
const FALLBACK_DURATION = 200

/**
 * `--duration-base`, read from the document rather than hard-coded: the token
 * is zeroed both by `prefers-reduced-motion` and by `[data-motion="reduced"]`,
 * so the JavaScript half of the reveal — how long the skeleton stays mounted —
 * agrees with the CSS half without a second code path.
 */
function tokenDuration(): number {
  if (typeof window === "undefined") return FALLBACK_DURATION
  const raw = window
    .getComputedStyle(document.documentElement)
    .getPropertyValue("--duration-base")
    .trim()
  const scale = raw.endsWith("ms") ? 1 : raw.endsWith("s") ? 1000 : 0
  const parsed = Number.parseFloat(raw)
  if (!scale || !Number.isFinite(parsed)) return FALLBACK_DURATION
  return parsed * scale
}

type Phase = "pending" | "revealing" | "ready"

// `children` is the content half of the pair, so it is named rather than spread.
export type RevealProps = Omit<React.ComponentProps<"div">, "children"> & {
  /** False shows the skeleton; true dissolves it into the content. */
  ready: boolean
  skeleton: React.ReactNode
  children: React.ReactNode
}

/**
 * Swaps a skeleton for the content it stood in for, without the jolt.
 *
 * The two share one grid cell with the skeleton on top, so revealing is the
 * skeleton dissolving rather than two things fading at once — which is what
 * makes it work on the very frame the content mounts, with no first-frame
 * opacity trick. The box morphs between the two heights at the same time, so a
 * card does not snap taller under the reader's cursor.
 *
 * Under reduced motion `--duration-base` is 0ms: the skeleton is dropped on the
 * next tick and nothing moves.
 */
function Reveal({ className, ready, skeleton, children, ...props }: RevealProps) {
  // Whether the dissolve has finished. Reset while rendering rather than in an
  // effect — the React way to adjust state a prop invalidates — so mounting
  // already-ready never plays a reveal for content that was never hidden.
  const [settled, setSettled] = React.useState(ready)
  const [lastReady, setLastReady] = React.useState(ready)
  if (ready !== lastReady) {
    setLastReady(ready)
    setSettled(false)
  }
  const phase: Phase = !ready ? "pending" : settled ? "ready" : "revealing"

  const rootRef = React.useRef<HTMLDivElement>(null)
  const skeletonRef = React.useRef<HTMLDivElement>(null)
  const contentRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    if (phase !== "revealing") return
    const timer = window.setTimeout(() => setSettled(true), tokenDuration())
    return () => window.clearTimeout(timer)
  }, [phase])

  // Heights are measured, never guessed: the box can only animate between two
  // numbers, and the second one exists only once the content is in the DOM.
  // Written straight onto the node rather than held in state — the height is a
  // fact about layout, and re-rendering to carry it would put React a frame
  // behind the measurement. A measurement of 0 (no layout engine, nothing
  // rendered yet) leaves the box `auto`, so nothing is ever clipped.
  React.useLayoutEffect(() => {
    const root = rootRef.current
    if (!root) return
    const target = phase === "pending" ? skeletonRef.current : contentRef.current
    const measured = phase === "ready" ? 0 : (target?.offsetHeight ?? 0)
    if (measured <= 0) {
      root.style.height = ""
      return
    }
    if (phase === "pending") {
      root.style.height = `${measured}px`
      return
    }
    // One frame later, so the box starts from the skeleton's height it is
    // already sitting at rather than jumping straight to the content's.
    const frame = requestAnimationFrame(() => {
      root.style.height = `${measured}px`
    })
    return () => cancelAnimationFrame(frame)
    // `phase` alone: `children` and `skeleton` are fresh elements on every
    // parent render, and depending on them would force a synchronous
    // offsetHeight read — a reflow — each time an ancestor re-rendered, for a
    // number that only changes when the phase does.
  }, [phase])

  return (
    <div
      ref={rootRef}
      data-slot="reveal"
      data-state={phase}
      aria-busy={!ready || undefined}
      className={cn(
        "grid transition-[height] duration-[var(--duration-base,200ms)] ease-[var(--ease-standard)]",
        // The clip is what keeps the taller of the two layers inside the box
        // while the height animates between them. Once it has settled the box
        // is `auto` and there is nothing to clip, so it goes — a chart card's
        // tooltip should not be living inside a permanent clipping context.
        phase !== "ready" && "overflow-hidden",
        className
      )}
      {...props}
    >
      {phase === "pending" ? null : (
        // min-w-0: a grid item is as wide as what it holds unless told it may
        // be narrower, and then a heatmap's scroller inside a ChartCard never
        // scrolled — the card's sheet clipped the hours past its edge.
        <div ref={contentRef} data-slot="reveal-content" className="col-start-1 row-start-1 min-w-0">
          {children}
        </div>
      )}

      {phase === "ready" ? null : (
        <div
          ref={skeletonRef}
          data-slot="reveal-skeleton"
          // Hidden from assistive tech only once the real content is beneath
          // it: while it is the only thing there, it is what the page is.
          aria-hidden={phase === "revealing" || undefined}
          className={cn(
            "col-start-1 row-start-1 min-w-0 transition-opacity duration-[var(--duration-base,200ms)] ease-[var(--ease-standard)]",
            phase === "revealing" && "pointer-events-none opacity-0"
          )}
        >
          {skeleton}
        </div>
      )}
    </div>
  )
}

export { Reveal }
