import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"
import { Card, CardAction, CardContent, CardHeader } from "@/components/ui/card"
import { MetricDelta, type MetricDeltaProps } from "@/components/ui/metric-delta"
import { NumberRoll } from "@/components/ui/number-roll"
import { Skeleton } from "@/components/ui/skeleton"

const statCardVariants = cva("", {
  variants: {
    variant: {
      card: "",
      // No border, shadow, radius, or background of its own, so a StatCardGroup
      // can draw one frame around a whole row of them. COUPLED TO card.tsx:
      // each class cancels one of the frame's own (rounded-xl, bg-surface,
      // ring-1) and the descendant rule flattens the sheet; stat-card.test.tsx
      // fails if Card's chrome changes shape under it.
      flush:
        "rounded-none bg-transparent ring-0 [&_[data-slot=card-content]]:rounded-none [&_[data-slot=card-content]]:bg-transparent [&_[data-slot=card-content]]:ring-0",
    },
    size: {
      // Padding is the density token, and that lives on the Card root itself;
      // `sm` is the Card primitive's tighter spacing, which comes from
      // data-[size=sm] and needs nothing written here.
      default: "",
      sm: "",
    },
    // A tinted frame: the strip takes the tone's own muted plane while the
    // sheet stays white, so a row of four tiles can be four colours without a
    // single number changing its ink. The ring goes with it, at a third of
    // the tone, so the frame's edge is the same colour as its ground.
    tone: {
      neutral: "",
      info: "bg-info-muted ring-info/30",
      success: "bg-success-muted ring-success/30",
      warning: "bg-warning-muted ring-warning/30",
      danger: "bg-danger-muted ring-danger/30",
      brand: "bg-brand-muted ring-brand/30",
    },
  },
  defaultVariants: { variant: "card", size: "default", tone: "neutral" },
})

/**
 * Whether a `controls` value names a panel: a non-empty id. A tile is a tab
 * only of a panel it can point at, and StatCard and StatCardGroup ask this
 * one question, so a row can never be a tablist of tiles that are not tabs.
 */
function namesPanel(controls: string | undefined): controls is string {
  return typeof controls === "string" && controls.trim() !== ""
}

/** A number that rolls to its new value instead of cutting to it. */
export type StatCardRoll = {
  value: number
  /** Receives the animating value every frame, so round inside it. */
  format?: (value: number) => string
}

type StatCardOwnProps = {
  label: React.ReactNode
  /** Change since the previous period; rendered as a <MetricDelta>. */
  delta?: number
  deltaFormat?: MetricDeltaProps["format"]
  /** False for metrics where down is the win — churn, latency, cost. */
  positiveIsGood?: boolean
  /** Sits beside the delta — what it is measured against, e.g. "vs last month". */
  description?: React.ReactNode
  /** The strip's action slot — an icon, or a small control such as a link; sized to 4 unless it sets its own size. */
  icon?: React.ReactNode
  footer?: React.ReactNode
  size?: NonNullable<VariantProps<typeof statCardVariants>["size"]>
  variant?: NonNullable<VariantProps<typeof statCardVariants>["variant"]>
  /** Tints the frame — the strip and the ring — in a tone; the sheet and the number stay as they are. */
  tone?: NonNullable<VariantProps<typeof statCardVariants>["tone"]>
  /** Replaces the value and meta row with skeletons; the label and footer stay put. */
  loading?: boolean
  /**
   * Makes the tile choosable: its control answers Enter and Space, and the
   * frame takes the brand tint when it is the selected one. With `controls`
   * the control is a tab of that region (`aria-selected`); without, a toggle
   * button (`aria-pressed`). Usually set by <StatCardGroup selectable>, which
   * owns the tablist, the arrow keys and the roving tabindex.
   */
  selectable?: boolean
  selected?: boolean
  onSelect?: () => void
  /** The id of the region this tile drives, e.g. the chart card it re-binds; it makes the tile a tab. */
  controls?: string
}

/**
 * `value` and `roll` are the same slot filled two ways, so the type says so: a
 * card either renders what it was given or rolls a number to it, and a caller
 * that passes `roll` does not also have to hand over a `value` it would never
 * be shown.
 */
export type StatCardProps = React.ComponentProps<"div"> &
  StatCardOwnProps &
  (
    | { value: React.ReactNode; roll?: never }
    | { value?: React.ReactNode; roll: StatCardRoll }
  )

function StatCard({
  className,
  label,
  value,
  roll,
  delta,
  deltaFormat,
  positiveIsGood,
  description,
  icon,
  footer,
  size = "default",
  variant = "card",
  tone = "neutral",
  loading = false,
  selectable = false,
  selected = false,
  onSelect,
  controls,
  tabIndex,
  id,
  ...props
}: StatCardProps) {
  const labelId = React.useId()
  const valueId = React.useId()
  const metaId = React.useId()

  // Three cues, never colour alone: the tinted frame, the ink the unselected
  // values give up, and `aria-selected` (or `aria-pressed`) for anyone not
  // looking. A fill rather than an outline: a stroke around a box reads as
  // focus or as an error, and the kit's chosen things are all fills.
  //
  // The control is an element of its own spread under the whole tile, not the
  // tile itself: a tile holds a number's "Explain" button and a sparkline, and
  // a tab or a button may hold nothing focusable (axe nested-interactive, on
  // saas-overview's four tiles). It is named by the label and described by
  // the number; a click anywhere on the tile but on its own controls picks it.
  // A tab only with a panel: a tile that names no region it drives is a
  // toggle button instead, and names no id at all. The tile's id is the
  // control's, so a panel labelled by its tile is labelled by the tab — and a
  // string label names it directly, since a panel's aria-labelledby is not
  // followed a second time into the tab's own.
  const control = selectable ? (
    <span
      data-slot="stat-card-control"
      id={id}
      {...(namesPanel(controls)
        ? { role: "tab" as const, "aria-selected": selected, "aria-controls": controls }
        : { role: "button" as const, "aria-pressed": selected })}
      {...(typeof label === "string" ? { "aria-label": label } : { "aria-labelledby": labelId })}
      aria-describedby={loading ? undefined : description ? `${valueId} ${metaId}` : valueId}
      // Focusable on its own; a group hands in the roving tabindex.
      tabIndex={tabIndex ?? 0}
      onKeyDown={(event: React.KeyboardEvent<HTMLSpanElement>) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault()
          onSelect?.()
        }
      }}
      className="absolute inset-0 rounded-[inherit] outline-none"
    />
  ) : null
  // The content paints above the control, so its own buttons take their clicks.
  const layered = selectable ? "relative" : undefined
  const pick = selectable
    ? (event: React.MouseEvent<HTMLDivElement>) => {
        // Only a control inside the tile keeps the click: a focusable box the
        // tile sits in (a scroller made a tab stop while it overflows) is not one.
        const hit = (event.target as Element).closest("a[href], button, input, select, textarea, summary, [tabindex]")
        if (hit && event.currentTarget.contains(hit) && hit.getAttribute("data-slot") !== "stat-card-control") return
        onSelect?.()
      }
    : undefined

  // The delta is a pill on the strip, beside the label, the way a report
  // annotates a figure in its margin — so the sheet below carries the number
  // and its caption alone. While loading the pill goes with the number it
  // qualifies; the icon stays, because it is the tile's identity, not data.
  const action =
    icon || (delta !== undefined && !loading) ? (
      <CardAction className="flex items-center gap-2 text-muted-foreground [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4">
        {icon}
        {delta !== undefined && !loading ? (
          <MetricDelta
            value={delta}
            format={deltaFormat}
            positiveIsGood={positiveIsGood}
            variant="pill"
            size="sm"
          />
        ) : null}
      </CardAction>
    ) : null

  return (
    <Card
      data-slot="stat-card"
      data-variant={variant}
      data-tone={tone === "neutral" ? undefined : tone}
      data-selected={selectable ? String(selected) : undefined}
      size={size}
      aria-busy={loading || undefined}
      id={selectable ? undefined : id}
      tabIndex={selectable ? undefined : tabIndex}
      onClick={pick}
      className={cn(
        statCardVariants({ variant, size, tone }),
        selectable &&
          "relative cursor-pointer transition-[box-shadow,background-color] duration-(--duration-fast) ease-(--ease-standard) hover:bg-accent data-[selected=true]:bg-brand-muted data-[selected=true]:hover:bg-brand-muted has-[>[data-slot=stat-card-control]:focus-visible]:focus-outline",
        className
      )}
      {...props}
    >
      {control}
      <CardHeader className={layered}>
        <StatCardLabel id={labelId}>{label}</StatCardLabel>
        {action}
      </CardHeader>

      <CardContent className={cn("flex flex-col gap-1", layered)}>
        {loading ? (
          <div data-slot="stat-card-skeleton" className="flex flex-col gap-1.5">
            <Skeleton className="h-9 w-28 group-data-[size=sm]/card:h-7" />
            {description ? <Skeleton className="h-4 w-20" /> : null}
          </div>
        ) : (
          <>
            <StatCardValue id={valueId}>
              {roll ? <NumberRoll value={roll.value} format={roll.format} /> : value}
            </StatCardValue>
            {description ? (
              <div
                id={metaId}
                data-slot="stat-card-meta"
                // font-sans and tracking-normal, because this row sits under a
                // number set on the numeral register, and the caption must not
                // inherit whatever tracking a preset gives the figures.
                className="flex flex-wrap items-center gap-x-2 gap-y-1 font-sans tracking-normal"
              >
                <StatCardDescription>{description}</StatCardDescription>
              </div>
            ) : null}
          </>
        )}
        {footer ? <StatCardFooter>{footer}</StatCardFooter> : null}
      </CardContent>
    </Card>
  )
}

// The label is the card-title register — 14px at 600, in ink — because on a
// tile the label is the title: it names the figure the way a card head names
// a chart.
function StatCardLabel({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="stat-card-label"
      className={cn("type-label font-semibold text-foreground", className)}
      {...props}
    />
  )
}

// The numeral register, the signature of the look: 30px at 700, tabular, on
// the figures' own tracking, set here so the meta row cannot inherit it. It
// scales from the Card root's data-size, so it needs a `group/card` above it;
// in a selectable group the unselected tiles drop to --muted-foreground (6.76:1).
function StatCardValue({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="stat-card-value"
      className={cn(
        "type-numeral text-3xl group-data-[size=sm]/card:text-xl group-data-[selected=false]/card:text-muted-foreground",
        className
      )}
      {...props}
    />
  )
}

function StatCardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="stat-card-description"
      className={cn("text-xs text-muted-foreground", className)}
      {...props}
    />
  )
}

// Under the caption, so a sparkline runs the width of the number. Hidden on a
// phone, where a 2-up row has room for the number and its caption only; a kit
// chart in a hidden footer is not drawn at all (ChartContainer skips a box
// with no area), so recharts has no 0×0 box to warn about.
function StatCardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div data-slot="stat-card-footer" className={cn("hidden pt-2 sm:block", className)} {...props} />
  )
}

export {
  namesPanel,
  StatCard,
  StatCardDescription,
  StatCardFooter,
  StatCardLabel,
  StatCardValue,
  statCardVariants,
}
