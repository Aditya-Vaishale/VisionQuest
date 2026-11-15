"use client"

import * as React from "react"
import { CircleAlertIcon, FileTextIcon, RotateCwIcon, XIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { formatBytes } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { FileDropzone, type FileDropzoneProps } from "@/components/ui/file-dropzone"
import { Progress } from "@/components/ui/progress"

export type FileUploadProps = Omit<React.ComponentProps<"div">, "children"> &
  Pick<
    FileDropzoneProps,
    "onFilesAccepted" | "onFilesRejected" | "accept" | "maxSize" | "maxFiles" | "multiple"
  > & {
    /** The field's name; it names the drop area and the file list. */
    label: React.ReactNode
    /** A line under the label, read with the drop area as its description. */
    description?: React.ReactNode
    /** The files held. They count towards maxFiles, so the cap spans more than one drop. */
    value?: File[]
    /** Adds a "Remove <name>" button to each file; without it the list is read-only. */
    onRemove?: (file: File) => void
    /**
     * Upload progress by file name, 0–100. A file with an entry shows a bar at
     * that percent; a file without one is done.
     */
    uploading?: Record<string, number>
    /**
     * Uploads that failed, by file name, with the reason in the reader's
     * words. A failed file says so in its row until it is retried (given an
     * uploading entry) or removed.
     */
    failed?: Record<string, string>
    /** Adds a "Retry <name>" button to each failed file. */
    onRetry?: (file: File) => void
    /**
     * A problem with the field as a whole — "Attach the receipt" — shown
     * under the drop area, announced, and read with the drop area after.
     */
    error?: React.ReactNode
    /** Disables the drop area and the remove buttons together. */
    disabled?: boolean
  }

/** Kept on the bar whatever the caller sends: a percent is never below 0 or past 100. */
function clampPercent(percent: number): number {
  return Math.min(100, Math.max(0, percent))
}

/**
 * A labelled upload field over FileDropzone: the dropzone takes and validates
 * the files and reports what it turned down; the field lists what is held,
 * each with its size, a progress bar while it uploads, and a remove button.
 */
function FileUpload({
  label,
  description,
  value = [],
  onRemove,
  uploading,
  failed,
  onRetry,
  error,
  onFilesAccepted,
  onFilesRejected,
  accept,
  maxSize,
  maxFiles,
  multiple,
  disabled = false,
  className,
  ...props
}: FileUploadProps) {
  const labelId = React.useId()
  const descriptionId = React.useId()
  const errorId = React.useId()
  const describedBy = [description ? descriptionId : null, error ? errorId : null].filter(Boolean).join(" ")
  // The dropzone retires its rejection list when a file leaves its own list.
  // This field draws that list instead, so a removal remounts the dropzone,
  // which clears what it last turned down in the same way.
  const [round, setRound] = React.useState(0)

  return (
    <div
      data-slot="file-upload"
      data-disabled={disabled || undefined}
      data-invalid={error ? true : undefined}
      className={cn("flex w-full flex-col gap-2", className)}
      {...props}
    >
      <div className="flex flex-col gap-1">
        <span id={labelId} data-slot="file-upload-label" className="text-sm font-medium">
          {label}
        </span>
        {description ? (
          <p id={descriptionId} data-slot="file-upload-description" className="text-sm text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>

      <FileDropzone
        key={round}
        aria-labelledby={labelId}
        aria-describedby={describedBy || undefined}
        // An error draws the drop area's edge in the danger tone too.
        className={error ? "[&_[data-slot=file-dropzone-panel]]:border-danger" : undefined}
        value={value}
        listFiles={false}
        onFilesAccepted={onFilesAccepted}
        onFilesRejected={onFilesRejected}
        accept={accept}
        maxSize={maxSize}
        maxFiles={maxFiles}
        multiple={multiple}
        disabled={disabled}
      />

      {error ? (
        <p id={errorId} role="alert" data-slot="file-upload-error" className="text-sm text-danger">
          {error}
        </p>
      ) : null}

      {value.length > 0 ? (
        <ul data-slot="file-upload-files" aria-labelledby={labelId} className="flex flex-col gap-1.5">
          {value.map((file) => {
            const progress = uploading?.[file.name]
            const percent = progress === undefined ? undefined : clampPercent(progress)
            // An upload under way wins: a retry shows its bar, not the old failure.
            const reason = percent === undefined ? failed?.[file.name] : undefined
            const state = percent !== undefined ? "uploading" : reason !== undefined ? "failed" : "done"
            return (
              <li
                key={`${file.name}-${file.size}-${file.lastModified}`}
                data-slot="file-upload-file"
                data-state={state}
                className="flex flex-col gap-2 rounded-lg bg-card px-2.5 py-2 ring-1 ring-border"
              >
                <div className="flex min-w-0 items-center gap-2">
                  {reason === undefined ? (
                    <FileTextIcon aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
                  ) : (
                    <CircleAlertIcon aria-hidden="true" className="size-4 shrink-0 text-danger" />
                  )}
                  <span className="min-w-0 flex-1 truncate text-sm">{file.name}</span>
                  <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                    {formatBytes(file.size)}
                  </span>
                  {reason !== undefined && onRetry ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      aria-label={`Retry ${file.name}`}
                      disabled={disabled}
                      onClick={() => onRetry(file)}
                    >
                      <RotateCwIcon aria-hidden="true" />
                    </Button>
                  ) : null}
                  {onRemove ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      aria-label={`Remove ${file.name}`}
                      disabled={disabled}
                      onClick={() => {
                        setRound((current) => current + 1)
                        onRemove(file)
                      }}
                    >
                      <XIcon aria-hidden="true" />
                    </Button>
                  ) : null}
                </div>
                {reason === undefined ? null : (
                  <p role="alert" className="text-xs text-danger">
                    Upload failed. {reason}
                  </p>
                )}
                {percent === undefined ? null : (
                  <div className="flex items-center gap-2">
                    <Progress value={percent} aria-label={`Uploading ${file.name}`} className="flex-1" />
                    <span
                      aria-hidden="true"
                      className="w-9 shrink-0 text-end text-xs text-muted-foreground tabular-nums"
                    >
                      {Math.round(percent)}%
                    </span>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      ) : null}
    </div>
  )
}

export { FileUpload }
