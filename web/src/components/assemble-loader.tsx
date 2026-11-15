"use client"

import { useEffect, useRef } from "react"

type Point = { x: number; y: number; tx: number; ty: number; light: number }

const POINTS = 84
const SWITCH_FRAMES = 120   // about 2 seconds between scattering and forming the hexagon
const LINK_DISTANCE = 48

/** Silver points that scatter, then join up into a hexagon, again and again. Still when the reader prefers less motion. */
export default function AssembleLoader() {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const cv = ref.current
    const ctx = cv?.getContext("2d")
    if (!cv || !ctx || matchMedia("(prefers-reduced-motion: reduce)").matches) return

    const DPR = Math.min(devicePixelRatio || 1, 2)
    let w = 0, h = 0, raf = 0, timer = 0, scattered = false
    let pts: Point[] = []

    /** n points spread evenly along the six sides of a hexagon centred on (cx, cy). */
    const hexagon = (cx: number, cy: number, n: number) => Array.from({ length: n }, (_, i) => {
      const seg = (i / n) * 6, side = Math.floor(seg), f = seg - side, R = Math.min(w, h) * 0.28
      const a1 = (side / 6) * Math.PI * 2 - Math.PI / 2, a2 = ((side + 1) / 6) * Math.PI * 2 - Math.PI / 2
      const x1 = cx + Math.cos(a1) * R, y1 = cy + Math.sin(a1) * R
      const x2 = cx + Math.cos(a2) * R, y2 = cy + Math.sin(a2) * R
      return { x: x1 + (x2 - x1) * f, y: y1 + (y2 - y1) * f }
    })

    function resize() {
      const r = cv!.getBoundingClientRect()
      w = r.width
      h = r.height
      cv!.width = w * DPR
      cv!.height = h * DPR
      ctx!.setTransform(DPR, 0, 0, DPR, 0, 0)
      pts = hexagon(w / 2, h / 2, POINTS).map((t) => ({
        x: Math.random() * w, y: Math.random() * h, tx: t.x, ty: t.y, light: 78 + Math.random() * 22,
      }))
    }

    function frame() {
      if (++timer > SWITCH_FRAMES) {
        timer = 0
        scattered = !scattered
        if (scattered) {
          pts.forEach((p) => { p.tx = Math.random() * w; p.ty = Math.random() * h })
        } else {
          const targets = hexagon(w / 2, h / 2, pts.length)
          pts.forEach((p, i) => { p.tx = targets[i].x; p.ty = targets[i].y })
        }
      }
      ctx!.fillStyle = "rgba(5,5,7,.25)"                 // the page's own black, so trails fade into it
      ctx!.fillRect(0, 0, w, h)
      ctx!.globalCompositeOperation = "lighter"
      for (let i = 0; i < pts.length; i++) {
        const a = pts[i]
        a.x += (a.tx - a.x) * 0.08
        a.y += (a.ty - a.y) * 0.08
        for (let j = i + 1; j < pts.length; j++) {
          const b = pts[j], d = Math.hypot(a.x - b.x, a.y - b.y)
          if (d < LINK_DISTANCE) {
            ctx!.strokeStyle = `rgba(214,216,222,${(1 - d / LINK_DISTANCE) * 0.4})`
            ctx!.lineWidth = 1
            ctx!.beginPath()
            ctx!.moveTo(a.x, a.y)
            ctx!.lineTo(b.x, b.y)
            ctx!.stroke()
          }
        }
      }
      for (const p of pts) {
        const g = ctx!.createRadialGradient(p.x, p.y, 0, p.x, p.y, 6)
        g.addColorStop(0, `hsla(0,0%,${p.light}%,.9)`)
        g.addColorStop(1, `hsla(0,0%,${p.light}%,0)`)
        ctx!.fillStyle = g
        ctx!.beginPath()
        ctx!.arc(p.x, p.y, 6, 0, Math.PI * 2)
        ctx!.fill()
      }
      ctx!.globalCompositeOperation = "source-over"
      raf = requestAnimationFrame(frame)
    }

    resize()
    frame()
    addEventListener("resize", resize)
    return () => {
      cancelAnimationFrame(raf)
      removeEventListener("resize", resize)
    }
  }, [])

  return <canvas ref={ref} aria-hidden className="h-full w-full bg-[#050507]" />
}
