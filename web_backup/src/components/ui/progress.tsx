"use client"

import { Progress as ProgressPrimitive } from "@base-ui/react/progress"
import { cn } from "@/lib/utils"

function Progress({
  className,
  children,
  value,
  ...props
}: ProgressPrimitive.Root.Props) {
  return (
    <ProgressPrimitive.Root
      value={value}
      data-slot="progress"
      className={cn("flex flex-wrap gap-3", className)}
      {...props}
    >
      {children}
      <ProgressTrack>
        <ProgressIndicator />
      </ProgressTrack>
    </ProgressPrimitive.Root>
  )
}

function ProgressTrack({ className, ...props }: ProgressPrimitive.Track.Props) {
  return (
    <ProgressPrimitive.Track
      className={cn(
        "relative flex h-1 w-full items-center overflow-x-hidden rounded-full bg-muted",
        className
      )}
      data-slot="progress-track"
      {...props}
    />
  )
}

/**
 * The slide a bar with no value makes: a segment two-fifths of the track wide,
 * centred, travels from wholly before the track's start to wholly past its end.
 * The keyframes come with the component — React hoists the sheet into the head
 * once, however many bars there are — so nothing is added to your CSS.
 */
const INDETERMINATE_KEYFRAMES =
  "@keyframes progress-indeterminate{from{translate:-175% 0}to{translate:175% 0}}"

function ProgressIndicator({
  className,
  ...props
}: ProgressPrimitive.Indicator.Props) {
  return (
    <>
      <style href="vibra-progress-keyframes" precedence="default">
        {INDETERMINATE_KEYFRAMES}
      </style>
      <ProgressPrimitive.Indicator
        data-slot="progress-indicator"
        className={(state) =>
          cn(
            "h-full bg-primary transition-[width] duration-(--duration-base) ease-(--ease-standard)",
            // No value (`value={null}`): a segment rather than a fill. It rests
            // in the middle of the track, where it cannot be read as an amount
            // — an amount always starts at the inline start — and slides the
            // reading way only while the reader has not asked for less motion,
            // by the OS setting or a [data-motion="reduced"] above. A loop
            // takes no duration token, so it has to not run instead.
            state.status === "indeterminate" &&
              "mx-auto w-2/5 motion-safe:not-in-data-[motion=reduced]:animate-[progress-indeterminate_1.5s_ease-in-out_infinite] rtl:[animation-direction:reverse]",
            typeof className === "function" ? className(state) : className
          )
        }
        {...props}
      />
    </>
  )
}

function ProgressLabel({ className, ...props }: ProgressPrimitive.Label.Props) {
  return (
    <ProgressPrimitive.Label
      className={cn("text-sm font-medium", className)}
      data-slot="progress-label"
      {...props}
    />
  )
}

// Pushed to the end of the row on the inline axis, so a right-to-left bar
// prints its value at the far (left) end rather than against the label.
function ProgressValue({ className, ...props }: ProgressPrimitive.Value.Props) {
  return (
    <ProgressPrimitive.Value
      className={cn(
        "ms-auto text-sm text-muted-foreground tabular-nums",
        className
      )}
      data-slot="progress-value"
      {...props}
    />
  )
}

export {
  Progress,
  ProgressTrack,
  ProgressIndicator,
  ProgressLabel,
  ProgressValue,
}
