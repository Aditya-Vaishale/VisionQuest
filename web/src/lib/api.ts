export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "")
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

/** An error from the API, with its HTTP status (0 = the API could not be reached). */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = "ApiError"
  }
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

/** The session ended or never started: go to the login page and come back here afterwards. */
export function goToLogin(): void {
  if (typeof window === "undefined" || window.location.pathname === "/login") return
  const here = window.location.pathname + window.location.search + window.location.hash
  window.location.replace(`/login?next=${encodeURIComponent(here)}`)
}

type Options = { method?: "GET" | "POST" | "DELETE"; body?: unknown; toLoginOn401?: boolean }

/** Every call sends the session cookie; a 401 sends the reader to the login page unless told otherwise. */
async function request<T>(path: string, { method, body, toLoginOn401 = true }: Options = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: method ?? (body === undefined ? "GET" : "POST"),
      credentials: "include",
      cache: "no-store",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(UNREACHABLE, 0)
  }
  const data: unknown = await res.json().catch(() => null)
  if (res.status === 401 && toLoginOn401) goToLogin()
  if (!res.ok) throw new ApiError(errorText(data, res.status), res.status)
  return data as T
}

const route = (id: string, rest = "") => `/analyses/${encodeURIComponent(id)}${rest}`
export const getAnalysis = (id: string) => request<Job>(route(id))
export const answerQuestion = (id: string, answer: string) => request<Job>(route(id, "/answer"), { body: { answer } })
export const getDashboard = (id: string) => request<Dashboard>(route(id, "/dashboard"))
export const applyFilters = (id: string, filters: FilterIn[]) =>
  request<Dashboard>(route(id, "/filters"), { body: { filters } })

export const cancelAnalysis = (id: string) => request<Job>(route(id, "/cancel"), { method: "POST" })

export const getMe = () => request<{ user: string }>("/auth/me", { toLoginOn401: false })
export const login = (username: string, password: string) =>
  request<{ user: string }>("/auth/login", { body: { username, password }, toLoginOn401: false })
export const logout = () => request<{ ok: boolean }>("/auth/logout", { method: "POST", toLoginOn401: false })

/** Upload with progress (fetch cannot report upload progress, so this uses XMLHttpRequest). */
export function startAnalysis(file: File, onProgress: (percent: number) => void): Promise<Job> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open("POST", `${API_URL}/analyses`)
    xhr.withCredentials = true
    xhr.responseType = "json"
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve(xhr.response as Job)
      if (xhr.status === 401) goToLogin()
      reject(new ApiError(errorText(xhr.response, xhr.status), xhr.status))
    }
    xhr.onerror = () => reject(new ApiError(UNREACHABLE, 0))
    const form = new FormData()
    form.append("file", file)
    xhr.send(form)
  })
}
