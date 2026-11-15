"use client"

import { useEffect, useRef, type CSSProperties, type ReactNode } from "react"

import BoidsEcosystem from "@/components/boids-ecosystem"

const BACKGROUND = "#050507"
const PALETTE = ["#ffffff", "#e4e4e7", "#a1a1aa", "#71717a"]   // quiet monochrome flock

/** Eased 0..1, so the change starts and ends gently. */
function ease(t: number): number {
  const x = Math.min(1, Math.max(0, t))
  return x * x * (3 - 2 * x)
}

/**
 * Boids behind the page. As the visitor scrolls from the hero to the upload section, a progress
 * value --p goes from 0 to 1: the flock blurs and fades while the page turns black.
 * --p is written straight to the DOM on each animation frame, so scrolling never re-renders React.
 */
export function ScrollScene({ children }: { children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let frame = 0
    const update = () => {
      frame = 0
      root.current?.style.setProperty("--p", ease(window.scrollY / (window.innerHeight * 0.85)).toFixed(4))
    }
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update)
    }
    update()
    window.addEventListener("scroll", onScroll, { passive: true })
    window.addEventListener("resize", onScroll)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener("scroll", onScroll)
      window.removeEventListener("resize", onScroll)
    }
  }, [])

  return (
    <div ref={root} className="relative" style={{ "--p": 0 } as CSSProperties}>
      <div aria-hidden className="pointer-events-none fixed inset-0">
        <div
          className="absolute inset-0 will-change-[filter,opacity,transform]"
          style={{
            filter: "blur(calc(var(--p) * 18px))",
            opacity: "calc(1 - var(--p) * 0.9)",
            transform: "scale(calc(1 + var(--p) * 0.06))",
          }}
        >
          <BoidsEcosystem className="rounded-none" background={BACKGROUND} palette={PALETTE} count={650} />
        </div>
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_35%,rgba(0,0,0,0.65)_100%)]" />
        <div className="absolute inset-0 bg-black" style={{ opacity: "var(--p)" }} />
      </div>
      <div className="relative z-10">{children}</div>
    </div>
  )
}
