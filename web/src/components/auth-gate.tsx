"use client"

import * as React from "react"

import { ApiError, errorMessage, getMe, goToLogin, logout } from "@/lib/api"

type State = { kind: "checking" } | { kind: "in"; user: string } | { kind: "error"; message: string }

/**
 * Shows the page only to a logged-in reader. This is for the reader's convenience: the API itself
 * refuses every request without a valid session, so hiding the page is not what keeps data safe.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<State>({ kind: "checking" })
  const [attempt, setAttempt] = React.useState(0)
  const [leaving, setLeaving] = React.useState(false)

  React.useEffect(() => {
    let live = true
    getMe()
      .then((me) => { if (live) setState({ kind: "in", user: me.user }) })
      .catch((e: unknown) => {
        if (!live) return
        if (e instanceof ApiError && e.status === 401) return goToLogin()
        setState({ kind: "error", message: errorMessage(e) })
      })
    return () => { live = false }
  }, [attempt])

  async function signOut() {
    setLeaving(true)
    try {
      await logout()
    } catch {
      // the session may already be gone; leave anyway
    }
    window.location.replace("/login")
  }

  if (state.kind === "checking") return <div className="min-h-screen bg-[#050507]" />
  if (state.kind === "error") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[#050507] px-6 text-center text-white">
        <p className="text-sm text-white/70">{state.message}</p>
        <button type="button" onClick={() => { setState({ kind: "checking" }); setAttempt((n) => n + 1) }}
          className="rounded-md border border-white/20 px-4 py-1.5 text-sm hover:bg-white/10">
          Try again
        </button>
      </div>
    )
  }
  return (
    <>
      {children}
      <button type="button" onClick={signOut} disabled={leaving} title={`Logged in as ${state.user}`}
        className="fixed right-4 top-4 z-50 rounded-full border border-white/15 bg-[#050507]/85 px-3 py-1.5 text-xs text-white/70 hover:bg-white/10 hover:text-white disabled:opacity-40">
        {leaving ? "Logging out…" : "Log out"}
      </button>
    </>
  )
}
