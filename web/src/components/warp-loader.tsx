"use client"

import { useEffect, useRef } from "react"

type Star = { x: number; y: number; z: number; pz: number }

const STARS = 320
const TOP_SPEED = 14

/** Stars rushing towards the viewer, in white and silver. Draws nothing when the reader prefers less motion. */
export default function WarpLoader() {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const cv = ref.current
    const ctx = cv?.getContext("2d")
    if (!cv || !ctx || matchMedia("(prefers-reduced-motion: reduce)").matches) return

    const DPR = Math.min(devicePixelRatio || 1, 2)
    let w = 0, h = 0, raf = 0, speed = 0
    let stars: Star[] = []

    function resize() {
      const r = cv!.getBoundingClientRect()
      w = r.width
      h = r.height
      cv!.width = w * DPR
      cv!.height = h * DPR
      ctx!.setTransform(DPR, 0, 0, DPR, 0, 0)
      stars = Array.from({ length: STARS }, () => ({
        x: (Math.random() - 0.5) * w, y: (Math.random() - 0.5) * h, z: Math.random() * w, pz: 0,
      }))
    }

    function frame() {
      speed += (TOP_SPEED - speed) * 0.02
      ctx!.fillStyle = "rgba(5,5,7,.35)"               // the page's own black, so trails fade into it
      ctx!.fillRect(0, 0, w, h)
      ctx!.save()
      ctx!.translate(w / 2, h / 2)
      for (const s of stars) {
        s.pz = s.z
        s.z -= speed
        if (s.z < 1) {
          s.z = w
          s.x = (Math.random() - 0.5) * w
          s.y = (Math.random() - 0.5) * h
          s.pz = s.z
        }
        const near = 1 - s.z / w                          // 0 = far away, 1 = close
        const k = 128 / s.z, pk = 128 / s.pz
        const light = 68 + near * 32                      // far stars silver, close stars white
        ctx!.strokeStyle = `hsla(0,0%,${light}%,${Math.min(1, near * 1.4)})`
        ctx!.lineWidth = near * 2.4
        ctx!.beginPath()
        ctx!.moveTo(s.x * pk, s.y * pk)
        ctx!.lineTo(s.x * k, s.y * k)
        ctx!.stroke()
      }
      ctx!.restore()
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
