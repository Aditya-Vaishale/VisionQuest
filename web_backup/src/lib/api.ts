export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "")
const UNREACHABLE = "Cannot reach the API. Is it running on port 8000?"

export type JobStatus = "queued" | "running" | "needs_answer" | "done" | "failed"
export type StageState = "waiting" | "running" | "done" | "reused" | "failed"
export interface Question { question: string; options: string[]; why_it_matters: string }
export interface Job {
  id: string; file: string; status: JobStatus; stage: string
  stages: { name: string; state: StageState }[]
  question: Question | null; error: string | null; created_at: string; updated_at: string
}
export type ChartKind = "kpi" | "line" | "area" | "bar" | "stacked_bar" | "grouped_bar" | "pie" | "scatter" | "table"
export interface ChartComponent {
  id: string; kind: ChartKind; title: string; subtitle: string; metric: string; meaning: string
  x: string; y: string[]; series: string; horizontal: boolean; unit: string; decimals: number
  size: "S" | "M" | "L" | "XL"; caveat: string; assumptions: string[]
  data: { columns: string[]; rows: unknown[][]; total_rows: number }
}
export interface FilterSpec {
  column: string; kind: "date_range" | "category"; label: string; min?: string; max?: string; options?: string[]
}
export interface FilterIn { column: string; values?: string[]; start?: string; end?: string }
export interface Dashboard {
  title: string; subtitle: string; notes: string[]; filters: FilterSpec[]
  sections: { name: string; components: ChartComponent[] }[]
  filtered: boolean; filters_applied: FilterIn[]
}

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

function errorText(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) return detail.map((d) => (d as { msg?: string })?.msg ?? String(d)).join("; ")
  return `The API returned an error (${status}).`
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, body === undefined
      ? { cache: "no-store" }
      : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
  } catch {
    throw new Error(UNREACHABLE)
  }
  const data: unknown = await res.json().catch(() => null)
  if (!res.ok) throw new Error(errorText(data, res.status))
  return data as T
}

const route = (id: string, rest = "") => `/analyses/${encodeURIComponent(id)}${rest}`
export const getAnalysis = (id: string) => request<Job>(route(id))
export const answerQuestion = (id: string, answer: string) => request<Job>(route(id, "/answer"), { answer })
export const getDashboard = (id: string) => request<Dashboard>(route(id, "/dashboard"))
export const applyFilters = (id: string, filters: FilterIn[]) =>
  request<Dashboard>(route(id, "/filters"), { filters })

/** Upload with progress (fetch cannot report upload progress, so this uses XMLHttpRequest). */
export function startAnalysis(file: File, onProgress: (percent: number) => void): Promise<Job> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open("POST", `${API_URL}/analyses`)
    xhr.responseType = "json"
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve(xhr.response as Job)
        : reject(new Error(errorText(xhr.response, xhr.status)))
    xhr.onerror = () => reject(new Error(UNREACHABLE))
    const form = new FormData()
    form.append("file", file)
    xhr.send(form)
  })
}
