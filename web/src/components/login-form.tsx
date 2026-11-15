"use client"

import * as React from "react"

import { ApiError, errorMessage, login } from "@/lib/api"

/** Where to go after logging in: only a path on this site, never another website (no open redirect). */
function nextPath(): string {
  const raw = new URLSearchParams(window.location.search).get("next")
  return raw && raw.startsWith("/") && !raw.startsWith("//") && !raw.includes("\\") ? raw : "/"
}

export function LoginForm() {
  const [username, setUsername] = React.useState("")
  const [password, setPassword] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (busy || !username.trim() || !password) return
    setBusy(true)
    setError("")
    try {
      await login(username.trim(), password)
      window.location.replace(nextPath())
    } catch (err) {
      setPassword("")
      setError(err instanceof ApiError && err.status === 429
        ? "Too many failed attempts. Try again in a few minutes."
        : errorMessage(err))
      setBusy(false)
    }
  }

  const field = "w-full rounded-md border border-white/15 bg-white/[0.04] px-3 py-2 text-sm text-white outline-none " +
    "transition-colors placeholder:text-white/30 focus:border-white/60 focus:bg-white/[0.06]"
  return (
    <form onSubmit={submit}
      className="w-full space-y-6 rounded-2xl border border-white/[0.08] bg-white/[0.02] p-8 backdrop-blur-[2px]">
      <header className="text-center">
        <h1 className="text-4xl font-bold leading-none tracking-[-0.03em]">Vision Quest</h1>
        <p className="mt-3 text-sm text-white/60">Log in to continue</p>
      </header>
      <div className="space-y-4">
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-white/70">Username</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username"
            autoCapitalize="none" spellCheck={false} maxLength={128} required autoFocus className={field} />
        </label>
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-white/70">Password</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password" maxLength={256} required className={field} />
        </label>
      </div>
      <button type="submit" disabled={busy || !username.trim() || !password}
        className="w-full rounded-md bg-white px-4 py-2.5 text-sm font-semibold text-black transition-colors hover:bg-white/90 disabled:bg-white/10 disabled:text-white/40">
        {busy ? "Logging in…" : "Log in"}
      </button>
      {error && <p role="alert" className="text-center text-sm text-red-400">{error}</p>}
    </form>
  )
}
