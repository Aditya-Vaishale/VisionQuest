"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

import { FileUpload } from "@/components/ui/file-upload"
import { errorMessage, startAnalysis } from "@/lib/api"

const MAX_MB = 200

export function UploadPanel() {
  const router = useRouter()
  const [files, setFiles] = React.useState<File[]>([])
  const [uploading, setUploading] = React.useState<Record<string, number>>({})
  const [error, setError] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const file = files[0]

  async function analyse() {
    if (!file || busy) return
    setBusy(true)
    setError("")
    try {
      const job = await startAnalysis(file, (p) => setUploading({ [file.name]: Math.min(p, 99) }))
      setUploading({})
      router.push(`/analyses/${job.id}`)
    } catch (e) {
      setUploading({})
      setError(errorMessage(e))
      setBusy(false)
    }
  }

  return (
    <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-white/[0.03] p-8 shadow-[0_24px_80px_-20px_rgba(0,0,0,0.9)] backdrop-blur-xl">
      <h2 className="text-2xl font-semibold tracking-tight">Upload a CSV</h2>
      <p className="mt-2 text-sm leading-relaxed text-white/55">
        Any domain, any layout. The file stays on this computer; only summaries and small samples go to the AI.
      </p>
      <div className="mt-6">
        <FileUpload
          label="CSV file"
          accept={[".csv"]}
          maxSize={MAX_MB * 1024 * 1024}
          maxFiles={1}
          value={files}
          uploading={uploading}
          onFilesAccepted={(accepted) => {
            setFiles(accepted.slice(0, 1))
            setError("")
          }}
          onRemove={() => {
            if (!busy) setFiles([])
          }}
        />
      </div>
      {error && <p className="mt-3 text-sm text-red-400">{error}</p>}
      <button
        onClick={analyse}
        disabled={!file || busy}
        className="mt-6 h-11 w-full rounded-lg bg-white text-sm font-semibold text-black transition-colors hover:bg-white/90 disabled:cursor-not-allowed disabled:opacity-30"
      >
        {busy ? "Starting…" : "Analyse"}
      </button>
    </div>
  )
}
