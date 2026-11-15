import {
  annotationValues,
  type ChartAnnotation,
  type ChartDatum,
  type ChartSeries,
} from "@/components/ui/chart-core"

// A printed scale lands on steps a reader can add up in their head. Anything
// else — recharts' own 0/650/1.3K/2K/2.6K — makes the reader do arithmetic to
// place a point between two gridlines.
const NICE_STEPS = [1, 2, 2.5, 5, 10] as const

/** Rounds a rough interval up to the next 1, 2, 2.5 or 5 × 10ⁿ. */
export function niceStep(rough: number): number {
  if (!Number.isFinite(rough) || rough <= 0) return 1
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const scaled = rough / magnitude
  const step = NICE_STEPS.find((candidate) => scaled <= candidate * (1 + 1e-9)) ?? 10
  return step * magnitude
}

// Summing a float step accumulates error, so each tick is computed from the
// index and then snapped back to the precision the step itself carries.
const snap = (value: number): number => Number(value.toPrecision(12))

/**
 * Where a value axis starts. `zero` — the default everywhere — always takes
 * zero in, because a count, a sum or a share is read against nothing, and a
 * bar that does not start there lies about its length. `auto` fits the axis
 * to the data's own range, on the same nice steps, for a level whose
 * movement is the reading — a rate, a price, a temperature — and which a
 * zero floor would flatten into a line along the top of the plot.
 */
export type ChartBaseline = "zero" | "auto"

/** Ticks from `bottom` to `top` on `step`, both ends included. */
function ticksBetween(bottom: number, top: number, step: number): number[] {
  const ticks: number[] = []
  for (let i = 0; bottom + i * step <= top + step / 2; i += 1) ticks.push(snap(bottom + i * step))
  return ticks
}

/** The ticks and the domain for a range, on nice steps, both ends included. */
export function niceDomain(
  min: number,
  max: number,
  count = 4,
  options: { baseline?: ChartBaseline } = {}
): { domain: [number, number]; ticks: number[] } {
  if (options.baseline === "auto") return fittedDomain(min, max, count)

  const low = Math.min(0, Number.isFinite(min) ? min : 0)
  const high = Math.max(Number.isFinite(max) ? max : 0, low)
  // A flat series at zero still needs two gridlines, or the plot has no scale.
  if (high === low) return { domain: [low, low + 1], ticks: [low, low + 1] }

  const step = niceStep((high - low) / Math.max(1, count))
  const bottom = Math.floor(low / step + 1e-9) * step
  const top = Math.ceil(high / step - 1e-9) * step
  return { domain: [snap(bottom), snap(top)], ticks: ticksBetween(bottom, top, step) }
}

/**
 * The `auto` baseline: the data's own range, widened out to the nice steps
 * either side of it, so 1.05–1.11 prints 1.04 / 1.06 / … / 1.12 rather than
 * 0 / 0.5 / 1 / 1.5. A flat level still gets a scale — a step either side of
 * it — and nothing to plot falls back to the zero baseline's 0 / 1.
 *
 * A peak drawn on the frame's edge reads as clipped, so an extreme within a
 * quarter of a step of the edge gets one step more: 1.05–1.12 prints up to
 * 1.14. That air never takes the axis across zero, which a level that does
 * not cross it has no business reaching past.
 */
function fittedDomain(min: number, max: number, count: number): { domain: [number, number]; ticks: number[] } {
  const lowest = Number.isFinite(min) ? min : 0
  const highest = Number.isFinite(max) ? Math.max(max, lowest) : lowest
  let low = lowest
  let high = highest
  if (high === low) {
    if (low === 0) return niceDomain(0, 0, count)
    const pad = niceStep(Math.abs(low) / 10)
    low -= pad
    high += pad
  }

  const step = niceStep((high - low) / Math.max(1, count))
  let bottom = Math.floor(low / step + 1e-9) * step
  let top = Math.ceil(high / step - 1e-9) * step
  if (lowest - bottom < step / 4) bottom = lowest >= 0 ? Math.max(0, bottom - step) : bottom - step
  if (top - highest < step / 4) top = highest <= 0 ? Math.min(0, top + step) : top + step
  return { domain: [snap(bottom), snap(top)], ticks: ticksBetween(bottom, top, step) }
}

/** The printed scale from 0 to `max`: `niceTicks(2_900, 4)` is 0, 1000, 2000, 3000. */
export function niceTicks(max: number, count = 4): number[] {
  return niceDomain(0, max, count).ticks
}

/**
 * The lowest and highest number a set of series reaches, stacked or laid over
 * one another. On the zero baseline the extent always takes zero in, so a
 * hole in the data or a series of nothing reads as 0 / 0; on `auto` it is the
 * data's own range, and ±Infinity when there is nothing to read.
 */
export function chartExtent(
  data: ChartDatum[],
  series: ChartSeries[],
  options: { stacked?: boolean; compare?: boolean; baseline?: ChartBaseline } = {}
): { min: number; max: number } {
  const keys = series.flatMap((entry) =>
    options.compare && entry.compareKey ? [entry.key, entry.compareKey] : [entry.key]
  )
  const fitted = options.baseline === "auto"
  let min = fitted ? Infinity : 0
  let max = fitted ? -Infinity : 0
  for (const datum of data) {
    let stack = 0
    // A row of holes is no stack at all — not a stack of zero, which a
    // fitted axis would otherwise have to reach down to.
    let stacked = false
    for (const key of keys) {
      const raw = datum[key]
      if (typeof raw !== "number" || !Number.isFinite(raw)) continue
      if (options.stacked) {
        stack += raw
        stacked = true
      } else {
        if (raw < min) min = raw
        if (raw > max) max = raw
      }
    }
    if (stacked) {
      if (stack < min) min = stack
      if (stack > max) max = stack
    }
  }
  return { min, max }
}

/** A y axis' explicit domain and ticks for the data it has to hold. */
export function yAxisScale(
  data: ChartDatum[],
  series: ChartSeries[],
  options: {
    stacked?: boolean
    compare?: boolean
    count?: number
    annotations?: ChartAnnotation[]
    /** Where the axis starts; zero unless the chart asks to fit its data. */
    baseline?: ChartBaseline
  } = {}
): { domain: [number, number]; ticks: number[] } {
  const { min, max } = chartExtent(data, series, options)
  // A goal line above every plotted point still has to fit inside the plot.
  let low = min
  let high = max
  for (const annotation of options.annotations ?? []) {
    for (const value of annotationValues(annotation)) {
      if (value < low) low = value
      if (value > high) high = value
    }
  }
  return niceDomain(low, high, options.count ?? 4, { baseline: options.baseline })
}

// Below these the axis band costs more than the scale it prints: the labels
// crowd the plot at 120px tall and eat a third of the width at 240px wide.
const MIN_AXIS_HEIGHT = 120
const MIN_AXIS_WIDTH = 240

/**
 * Whether a y axis fits. Width 0 means "not measured yet" — on the server, and
 * in a test with no layout — and is never taken as "too narrow".
 */
export function fitsYAxis(height: number, width = 0): boolean {
  if (height < MIN_AXIS_HEIGHT) return false
  return width === 0 || width >= MIN_AXIS_WIDTH
}
