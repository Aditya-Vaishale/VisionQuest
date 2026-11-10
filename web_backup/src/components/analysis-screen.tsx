"use client"

import * as React from "react"
import Link from "next/link"
import { useParams } from "next/navigation"

import { DashboardView } from "@/components/dashboard-view"
import {
  answerQuestion, errorMessage, getAnalysis, getDashboard, type Dashboard, type Job, type Question,
} from "@/lib/api"

const POLL_MS = 2000
const LABELS: Record<string, string> = {
  discover: "Reading the file", clean: "Cleaning the data", reason: "Understanding what it means",
  calculate: "Calculating metrics", validate: "Checking every number", visualize: "Planning the dashboard",
  dashboard: "Building the dashboard",
}
const ICONS: Record<string, string> = { waiting: "○", running: "◐", done: "●", reused: "●", failed: "✕" }

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="min-h-screen bg-[#050507] text-white">{children}</div>
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

  if (state === "sent") return <p className="mt-6 text-sm text-white/70">Answer sent. Continuing…</p>
  return (
    <div className="mt-6 rounded-xl border border-white/15 bg-white/5 p-4">
      <p className="font-semibold">{question.question}</p>
      {question.why_it_matters && <p className="mt-1 text-sm text-white/60">{question.why_it_matters}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        {question.options.map((o) => (
          <button key={o} onClick={() => send(o)} disabled={state !== "idle"}
            className="rounded-md border border-white/20 px-3 py-1.5 text-sm hover:bg-white/10">
            {o}
          </button>
        ))}
      </div>
      <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); send(text) }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Or type your own answer"
          className="flex-1 rounded-md border border-white/20 bg-transparent px-3 py-1.5 text-sm" />
        <button disabled={!text.trim() || state !== "idle"}
          className="rounded-md bg-white px-3 py-1.5 text-sm font-semibold text-black disabled:opacity-40">
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
  return (
    <Shell>
      <div className="mx-auto max-w-xl px-6 py-16">
        <Link href="/#upload" className="text-sm text-white/60 hover:text-white">← New analysis</Link>
        <h1 className="mt-4 text-3xl font-bold">Vision Quest</h1>
        <p className="mt-1 text-white/60">{job ? `Analysing ${job.file}` : "Connecting…"}</p>
        <ol className="mt-8 space-y-3">
          {(job?.stages ?? []).map((s) => (
            <li key={s.name} className={`flex items-center gap-3 ${s.state === "waiting" ? "text-white/40" : ""}`}>
              <span className={s.state === "running" ? "animate-pulse" : ""}>{ICONS[s.state]}</span>
              <span>{LABELS[s.name] ?? s.name}</span>
              {s.state === "reused" && <span className="text-xs text-white/50">(reused)</span>}
              {s.state === "failed" && <span className="text-xs text-red-400">failed</span>}
            </li>
          ))}
        </ol>
        {job?.status === "needs_answer" && job.question && (
          <QuestionBox key={job.updated_at} id={id} question={job.question} onAnswered={setJob} />
        )}
        {job?.status === "failed" && (
          <p className="mt-6 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{job.error}</p>
        )}
        {error && <p className="mt-6 text-sm text-red-400">{error}</p>}
        {job && job.status !== "failed" && (
          <p className="mt-8 text-xs text-white/40">A new file can take 15–20 minutes; files seen before are faster.</p>
        )}
      </div>
    </Shell>
  )
}
