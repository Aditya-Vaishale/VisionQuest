import { Suspense } from "react"

import { AnalysisScreen } from "@/components/analysis-screen"
import { AuthGate } from "@/components/auth-gate"

/** The analysis id is only known per visit, so the client screen reads it inside Suspense
 *  (required in this Next.js version when cacheComponents is on). */
export default function AnalysisPage() {
  return (
    <AuthGate>
      <Suspense fallback={<div className="min-h-screen bg-[#050507]" />}>
        <AnalysisScreen />
      </Suspense>
    </AuthGate>
  )
}
