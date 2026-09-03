/** Shared Tailwind class strings for the compact AutoForm widgets. */

export const INPUT_CLASS =
  'h-6 w-full min-w-0 rounded-md border border-input bg-input/30 px-1.5 text-xs text-foreground ' +
  'outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring ' +
  'disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/40'

export const TEXTAREA_CLASS =
  'w-full min-w-0 resize-y rounded-md border border-input bg-input/30 px-1.5 py-1 font-mono text-xs ' +
  'leading-4 text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 ' +
  'focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive'

export const ICON_BUTTON_CLASS =
  'inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-input ' +
  'bg-background text-xs text-muted-foreground hover:bg-accent hover:text-foreground ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50'

export const UNIT_CLASS = 'shrink-0 select-none text-[11px] leading-none text-muted-foreground'
