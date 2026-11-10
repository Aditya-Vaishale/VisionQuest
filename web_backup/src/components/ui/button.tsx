import * as React from "react"
import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

import { KbdShortcut } from "@/components/ui/kbd-shortcut"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

const buttonVariants = cva(
  // rounded-lg, an explicit transition list (a button that animates `all`
  // animates its own width as its label changes), and the one focus treatment:
  // a solid 2px outline in the accent, which reads ≥3:1 on every plane, where
  // the old ring-3 halo measured 1.98:1 on white. The dimming answers
  // aria-disabled as well as :disabled — focusableWhenDisabled keeps a button
  // in the tab order by trading the attribute for aria-disabled, and without
  // it that button looked as pressable as any. Pointer events stay on for it:
  // a button that is aria-disabled on purpose may still explain itself when
  // pressed.
  //
  // Every class group is set once per variant and size: the corner, the type
  // size and the icon size live with the sizes, the border colour with the
  // variants. What cva returns raw is then already what a merge would leave,
  // so a link wearing buttonVariants() draws exactly the Button — with a
  // stylesheet deciding between two border colours or two type sizes, an
  // outline link lost its hairline and a sm one its 13px register.
  "group/button inline-flex shrink-0 items-center justify-center border bg-clip-padding font-medium whitespace-nowrap transition-[background-color,border-color,color,box-shadow,translate] duration-(--duration-fast) ease-(--ease-standard) focus-ring select-none active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:opacity-50 aria-disabled:opacity-50 aria-invalid:border-destructive [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        // Role one of six: the accent is a filled button. The hover mixes ink
        // into the brand rather than fading it — an alpha hover on a solid fill
        // shows the page through the button — and the press adds an inset
        // shadow so the pixel it moves reads as a press rather than a jump.
        default:
          "border-transparent bg-brand text-brand-foreground hover:bg-[color-mix(in_oklch,var(--brand),var(--foreground)_10%)] active:shadow-[inset_0_1px_2px_oklch(0_0_0_/_10%)]",
        // The near-ink primary Vibra shipped before this look, kept as a
        // variant for the second button in a region that already spent its one
        // accent fill.
        ink: "border-transparent bg-foreground text-background hover:bg-[color-mix(in_oklch,var(--foreground),var(--background)_12%)] active:shadow-[inset_0_1px_2px_oklch(0_0_0_/_10%)]",
        // A hairline, not the field boundary: a button is not an input, and
        // the heavier line made every outline button read as a control to
        // type in.
        outline:
          "bg-card border-border hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-[color-mix(in_oklch,var(--secondary),var(--foreground)_5%)] aria-expanded:bg-secondary aria-expanded:text-secondary-foreground",
        ghost:
          "border-transparent hover:bg-muted hover:text-foreground aria-expanded:bg-muted aria-expanded:text-foreground",
        // The tone on its own opaque tint, which reads 4.98:1 light and 6.35
        // dark. Deepening the tint on hover would move the background towards
        // the text, so the hover moves the border — for which the base already
        // reserves room — and the fill holds.
        destructive: "border-transparent bg-danger-muted text-danger hover:border-danger",
        link: "border-transparent text-brand underline-offset-4 hover:underline",
      },
      size: {
        // The radius follows the height: the 32px sizes turn the lg corner
        // (10px), the smaller ones the md corner (8px), so a small button is
        // not a capsule. The tighter padding beside an icon is set on the
        // inline axis (ps/pe), so it follows the icon to the right-hand side
        // of a right-to-left page instead of staying on the left.
        default:
          "h-8 gap-1.5 rounded-lg px-2.5 text-sm has-data-[icon=inline-end]:pe-2 has-data-[icon=inline-start]:ps-2 [&_svg:not([class*='size-'])]:size-4",
        xs: "h-6 gap-1 rounded-md px-2 text-xs has-data-[icon=inline-end]:pe-1.5 has-data-[icon=inline-start]:ps-1.5 [&_svg:not([class*='size-'])]:size-3",
        // The label register, 13px — not the 12.8px a 0.8rem step lands on.
        sm: "h-7 gap-1 rounded-md px-2.5 text-label has-data-[icon=inline-end]:pe-1.5 has-data-[icon=inline-start]:ps-1.5 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-9 gap-1.5 rounded-lg px-2.5 text-sm has-data-[icon=inline-end]:pe-2 has-data-[icon=inline-start]:ps-2 [&_svg:not([class*='size-'])]:size-4",
        icon: "size-8 rounded-lg text-sm [&_svg:not([class*='size-'])]:size-4",
        "icon-xs": "size-6 rounded-md text-sm [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-7 rounded-md text-sm [&_svg:not([class*='size-'])]:size-4",
        "icon-lg": "size-9 rounded-lg text-sm [&_svg:not([class*='size-'])]:size-4",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

// aria-keyshortcuts takes the UI Events names of the keys — Meta, Control,
// Alt, Shift, Escape — with the modifiers first. The kit writes chords its own
// way ("mod+k"), and "mod" is two chords: Meta+K on a Mac, Control+K
// everywhere else. Both are listed, which the attribute allows, so nothing has
// to guess the platform on the server.
const ARIA_MODIFIERS: Record<string, string> = {
  cmd: "Meta",
  command: "Meta",
  meta: "Meta",
  ctrl: "Control",
  control: "Control",
  alt: "Alt",
  opt: "Alt",
  option: "Alt",
  shift: "Shift",
}

const ARIA_KEYS: Record<string, string> = {
  esc: "Escape",
  escape: "Escape",
  enter: "Enter",
  return: "Enter",
  tab: "Tab",
  space: "Space",
  backspace: "Backspace",
  delete: "Delete",
  del: "Delete",
  up: "ArrowUp",
  arrowup: "ArrowUp",
  down: "ArrowDown",
  arrowdown: "ArrowDown",
  left: "ArrowLeft",
  arrowleft: "ArrowLeft",
  right: "ArrowRight",
  arrowright: "ArrowRight",
  pageup: "PageUp",
  pagedown: "PageDown",
  home: "Home",
  end: "End",
}

function ariaKeyshortcuts(shortcut: string): string {
  const tokens = shortcut
    .split("+")
    .map((token) => token.trim())
    .filter(Boolean)
  const chord = (mod: string) => {
    const modifiers: string[] = []
    const keys: string[] = []
    for (const token of tokens) {
      const name = token.toLowerCase()
      if (name === "mod") modifiers.push(mod)
      else if (ARIA_MODIFIERS[name]) modifiers.push(ARIA_MODIFIERS[name])
      else keys.push(ARIA_KEYS[name] ?? token[0].toUpperCase() + token.slice(1))
    }
    return [...modifiers, ...keys].join("+")
  }
  return tokens.some((token) => token.toLowerCase() === "mod")
    ? `${chord("Meta")} ${chord("Control")}`
    : chord("Meta")
}

export type ButtonProps = ButtonPrimitive.Props &
  VariantProps<typeof buttonVariants> & {
    /**
     * What the button does, in a few words. An icon-only button needs one —
     * and its `aria-label` is still what a screen reader hears; the tooltip is
     * for the pointer.
     */
    tooltip?: React.ReactNode
    /**
     * The chord that fires it, e.g. "mod+k". Printed as keycaps in the tooltip
     * and announced through `aria-keyshortcuts`; binding the key itself stays
     * the caller's job.
     */
    shortcut?: string
  }

function Button({
  className,
  variant = "default",
  size = "default",
  tooltip,
  shortcut,
  ...props
}: ButtonProps) {
  const button = (
    <ButtonPrimitive
      data-slot="button"
      // Both axes, always, as CONVENTIONS asks of an enumerated one: a button
      // group reads data-variant to give an outline button a field's line.
      data-variant={variant}
      data-size={size}
      // The chord is announced whether or not a tooltip prints it, so a
      // keyboard user hears it without hovering.
      aria-keyshortcuts={shortcut ? ariaKeyshortcuts(shortcut) : undefined}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )

  if (!tooltip && !shortcut) return button

  return (
    <Tooltip>
      <TooltipTrigger render={button} />
      <TooltipContent className="flex items-center gap-2">
        {tooltip}
        {shortcut ? <KbdShortcut keys={shortcut} size="sm" className="opacity-80" /> : null}
      </TooltipContent>
    </Tooltip>
  )
}

export { Button, buttonVariants }
