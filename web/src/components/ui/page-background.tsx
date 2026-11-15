"use client"

import BoidsEcosystem from "@/components/boids-ecosystem"

/** Full-page Boids background. Content sits above it, so buttons stay clickable. */
export function PageBackground({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative min-h-screen">
      <div className="fixed inset-0">
        <BoidsEcosystem className="rounded-none" />
      </div>
      <div className="dark relative z-10 text-white">{children}</div>
    </div>
  )
}
