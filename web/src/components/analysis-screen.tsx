"use client"

import * as React from "react"
import { useParams, useRouter } from "next/navigation"

import AssembleLoader from "@/components/assemble-loader"
import { DashboardView } from "@/components/dashboard-view"
import {
  answerQuestion, cancelAnalysis, errorMessage, getAnalysis, getDashboard,
  type Dashboard, type Job, type Question, type StageState,
} from "@/lib/api"

const POLL_MS = 2000
const LABELS: Record<string, string> = {
  discover: "Reading the file", clean: "Cleaning the data", reason: "Understanding what it means",
  calculate: "Calculating metrics", validate: "Checking every number", visualize: "Planning the dashboard",
  dashboard: "Building the dashboard",
}
const DOT: Record<StageState, string> = {
  waiting: "bg-white/20",
  running: "bg-white ring-4 ring-white/15 motion-safe:animate-pulse",
  done: "bg-white",
  reused: "bg-white",
  failed: "bg-red-500",
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="min-h-screen bg-[#050507] text-white">{children}</div>
}

/** Which step to name in the middle of the animation, and what to call it. */
function current(job: Job | null): { index: number; label: string } {
  if (!job) return { index: -1, label: "Connecting…" }
  const stages = job.stages
  const at = (state: StageState) => stages.findIndex((s) => s.state === state)
  if (job.status === "failed") {
    const i = Math.max(at("failed"), 0)
    return { index: i, label: `Stopped at: ${LABELS[stages[i]?.name] ?? "a step"}` }
  }
  if (job.status === "needs_answer") return { index: Math.max(at("running"), 0), label: "Waiting for your answer" }
  const running = at("running")
  if (running >= 0) return { index: running, label: LABELS[stages[running].name] ?? stages[running].name }
  const finished = stages.filter((s) => s.state === "done" || s.state === "reused").length
  return { index: Math.min(finished, stages.length - 1), label: finished ? "Almost there…" : "Starting…" }
}

function QuestionBox({ id, question, onAnswered }: { id: string; question: Question; onAnswered: (j: Job) => void }) {
  const [text, setText] = React.useState("")
  const [state, setState] = React.useState<"idle" | "sending" | "sent">("idle")
  const [error, setError] = React.useState("")

  async function send(answer: string) {
    if (!answer.trim() || state !== "idle") return
    setState("sending")
    setError("")
    try {
      onAnswered(await answerQuestion(id, answer.trim()))
      setState("sent")
    } catch (e) {
      setError(errorMessage(e))
      setState("idle")
    }
  }

  if (state === "sent") return <p className="text-center text-sm text-white/70">Answer sent. Continuing…</p>
  return (
    <div className="w-full rounded-xl border border-white/20 bg-white/[0.04] p-5 text-left">
      <p className="font-semibold">{question.question}</p>
      {question.why_it_matters && <p className="mt-1 text-sm text-white/60">{question.why_it_matters}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        {question.options.map((o) => (
          <button key={o} onClick={() => send(o)} disabled={state !== "idle"}
            className="rounded-md border border-white/20 px-3 py-1.5 text-sm hover:bg-white/10 disabled:opacity-40">
            {o}
          </button>
        ))}
      </div>
      <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); send(text) }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Or type your own answer"
          className="flex-1 rounded-md border border-white/15 bg-white/[0.04] px-3 py-1.5 text-sm outline-none focus:border-white/60" />
        <button disabled={!text.trim() || state !== "idle"}
          className="rounded-md bg-white px-3 py-1.5 text-sm font-semibold text-black disabled:bg-white/10 disabled:text-white/40">
          Send
        </button>
      </form>
      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
    </div>
  )
}

export function AnalysisScreen() {
  const { id } = useParams<{ id: string }>()
  const [job, setJob] = React.useState<Job | null>(null)
  const [dashboard, setDashboard] = React.useState<Dashboard | null>(null)
  const [error, setError] = React.useState("")
  const router = useRouter()
  const [confirming, setConfirming] = React.useState(false)
  const [stopping, setStopping] = React.useState(false)

  React.useEffect(() => {
    let stop = false
    let timer: number | undefined
    const tick = async () => {
      try {
        const next = await getAnalysis(id)
        if (stop) return
        setJob(next)
        setError("")
        if (next.status === "done") {
          const spec = await getDashboard(id)
          if (!stop) setDashboard(spec)
          return
        }
        if (next.status === "failed") return
      } catch (e) {
        if (!stop) setError(errorMessage(e))
      }
      if (!stop) timer = window.setTimeout(tick, POLL_MS)
    }
    tick()
    return () => {
      stop = true
      window.clearTimeout(timer)
    }
  }, [id])

  if (dashboard) {
    return <Shell><DashboardView id={id} dashboard={dashboard} onChange={setDashboard} /></Shell>
  }
  const failed = job?.status === "failed"
  const active = job?.status === "queued" || job?.status === "running" || job?.status === "needs_answer"

  /** A running analysis is stopped on the server first (after a confirm), so nothing keeps running behind. */
  async function startOver() {
    if (active && !confirming) return setConfirming(true)
    setStopping(true)
    try {
      if (active) await cancelAnalysis(id)
    } catch {
      // it may have finished or stopped already; start over anyway
    }
    router.push("/#upload")
  }

  const step = current(job)
  const stages = job?.stages ?? []
  return (
    <Shell>
      <div className="mx-auto flex min-h-screen w-full max-w-xl flex-col px-6 py-8">
        <div className="flex min-h-8 flex-wrap items-center gap-3 self-start text-sm">
          {confirming ? (
            <>
              <span className="text-white/70">Stop this analysis?</span>
              <button type="button" onClick={startOver} disabled={stopping}
                className="rounded-md bg-white px-3 py-1 font-semibold text-black disabled:opacity-40">
                {stopping ? "Stopping…" : "Stop and start over"}
              </button>
              <button type="button" onClick={() => setConfirming(false)} disabled={stopping}
                className="rounded-md border border-white/20 px-3 py-1 hover:bg-white/10 disabled:opacity-40">
                Keep running
              </button>
            </>
          ) : (
            <button type="button" onClick={startOver} className="text-white/60 hover:text-white">← New analysis</button>
          )}
        </div>
        <main className="flex flex-1 flex-col items-center justify-center gap-6 py-6 text-center">
          <h1 className="text-2xl font-bold tracking-tight">Vision Quest</h1>

          {/* The animation, with the current step written in the middle of the hexagon. */}
          <div className="relative size-[min(84vw,30rem)]">
            {!failed && <AssembleLoader />}
            <div aria-hidden className="pointer-events-none absolute inset-0"
              style={{ background: "radial-gradient(circle at center, #050507 0%, rgba(5,5,7,.9) 16%, rgba(5,5,7,0) 25%)" }} />
            <div className="absolute inset-0 flex flex-col items-center justify-center px-[26%]" aria-live="polite">
              {step.index >= 0 && stages.length > 0 && (
                <p className="text-[10px] font-medium uppercase tracking-[0.28em] text-white/45">
                  Step {step.index + 1} of {stages.length}
                </p>
              )}
              <p className={`mt-2 text-base font-semibold leading-snug sm:text-lg ${failed ? "text-red-300" : "text-white"}`}>
                {step.label}
              </p>
            </div>
          </div>

          {stages.length > 0 && (
            <ol className="flex items-center gap-3" aria-label="Steps">
              {stages.map((s) => (
                <li key={s.name} title={`${LABELS[s.name] ?? s.name}: ${s.state}`}
                  className={`size-2 rounded-full transition-colors ${DOT[s.state]}`}>
                  <span className="sr-only">{`${LABELS[s.name] ?? s.name}: ${s.state}`}</span>
                </li>
              ))}
            </ol>
          )}

          <p className="max-w-full truncate text-sm text-white/60">
            {job ? <>Analysing <span className="text-white/90">{job.file}</span></> : "Connecting to the analysis…"}
          </p>

          {job?.status === "needs_answer" && job.question && (
            <QuestionBox key={job.updated_at} id={id} question={job.question} onAnswered={setJob} />
          )}
          {failed && (
            <p className="w-full rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-left text-sm text-red-300">
              {job.error}
            </p>
          )}
          {error && <p className="text-sm text-red-400">{error}</p>}
          {job && !failed && (
            <p className="text-xs text-white/40">A new file usually takes 10–15 minutes. Files seen before are faster.</p>
          )}
        </main>
      </div>
    </Shell>
  )
}
