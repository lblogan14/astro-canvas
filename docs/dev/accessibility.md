# Accessibility: what is checked, and what it found

*Phase 13.* Design §10.3 asks for a canvas that works without a mouse, without colour vision, and
without motion. That is checked rather than asserted, by four suites:

| | Command | What it covers |
|---|---|---|
| axe-core | `pnpm -C frontend exec playwright test e2e/a11y.spec.ts` | WCAG 2.1 A/AA over the shell, library, inspector, drawer, palette, panels, gallery, all four app modes, an editor and the viewer |
| Keyboard | `… e2e/keyboard.spec.ts` | the absorption wizard start to finish with the keyboard alone, a focus indicator on every control the Tab order reaches |
| Motion | `… e2e/keyboard.spec.ts` | `prefers-reduced-motion` really stops the transitions |
| Colour vision | `pnpm -C frontend exec vitest run src/canvas/__tests__/portPalette.spec.ts` | the port palette under protanopia, deuteranopia and tritanopia |

They run as part of `task test:e2e` and `task test:fe`.

## The gate

**Zero serious or critical violations.** Moderate and minor findings are printed rather than
failed: what is left of them is landmark advice that does not map onto a canvas application, and a
gate that has to be argued with gets switched off. Two things are excluded from the axe pass and
both are written down in the spec:

- `.vue-flow__pane` and `.vue-flow__edges`, which are the canvas library's own markup. Everything
  around them — the chrome, the node bodies Astro Canvas renders into them, the on-canvas zoom
  controls — is audited.
- Nothing else. In particular *disabled controls are not exempted*, even though WCAG 1.4.3 would
  allow it; see below.

Every audit waits for finite animations and transitions to finish first. axe reads computed
styles, so a colour caught halfway through a 150 ms transition is reported as its own contrast
failure — a button going from enabled to disabled measured 2.5:1 in the middle and 5.5:1 at
either end.

## What the checks found

Nine fixes, in the order they turned up.

**`Tab` was bound to the quick-add palette**, globally, which meant a keyboard user could never
move focus off the canvas: the first `Tab` opened a dialog instead of reaching the toolbar. This
was the one finding that made the app unusable rather than awkward. Quick add is now `Ctrl+K` (or
`Shift+A`), and the shortcut handler returns early on `Tab` so the browser keeps it.

**`--muted-foreground` failed AA.** shadcn's `oklch(0.556)` (#737373) is 4.7:1 on white but only
4.3:1 on `--muted`, and most of the app's secondary text sits on exactly that ground. It is
`oklch(0.5)` now: 6.0:1 and 5.5:1, with margin left for the places where `bg-muted` composites
onto an already tinted surface.

**Tinted status text failed AA**, all of it the same shape — a 500-weight colour as text on a 10–20 %
tint of itself. `text-amber-600` on `bg-amber-500/10` was 3.0:1, `text-blue-600` on
`bg-blue-500/15` 4.4:1, `text-emerald-500` 3.4:1. They are all `-700` in light mode and `-400` in
dark now.

**The destructive button and badge failed AA**: `text-destructive` on `bg-destructive/10` was
4.0:1 and 3.3:1 on the `/20` hover. `--destructive` moved from `oklch(0.577)` to `oklch(0.45)`,
which is 5.7:1 and 4.7:1.

**Disabled buttons faded instead of muting.** `disabled:opacity-50` is 3.3:1 at best, and while
1.4.3 exempts inactive components, an unreadable disabled label is a real problem rather than a
technicality. Disabled buttons now drop to `--muted-foreground` on `--muted`, which is 5:1 and
still unmistakably inactive — and they no longer transition into that state, which is what made
the audit flake in the first place.

**The node library claimed `role="tree"`** with plain `<li>` children and no tree keyboard
behaviour. It is a list of disclosure sections, and it says so now. The *workspace* tree really is
one: its nested lists are `role="group"`, and `aria-level` moved off the list and onto the items,
where ARIA 1.2 allows it.

**The drawer's `role="tablist"` contained the Clear and Close buttons.** Only the tabs are inside
the tablist now, they carry `aria-controls` and a roving `tabindex`, `Left`/`Right`/`Home`/`End`
move between them, and the panel is labelled by the selected tab.

**The wizard's stepper `<ol>` held the layout buttons as direct children**, which an `<ol>` may
not. The list is the stepper; the buttons are its siblings.

**Vue Flow's zoom buttons had no accessible name** and the minimap had no label. The `Controls`
component's slots let us keep its styling and give each button a name.

**A dashboard tile's body scrolls but was not focusable**, so its content could not be read
without a mouse. It takes `tabindex="0"` and a focus ring.

**The workflow-name input had `focus:outline-none` and no ring** — the one control in the shell
that gave a keyboard user nothing to look at.

## Colour vision

Port colour is the Okabe–Ito set, chosen for red-green deficiency, and **every port type also
carries a glyph**, so colour is never the only channel. The unit test simulates protanopia,
deuteranopia and tritanopia (Viénot–Brettel–Mollon, in linear-light sRGB) and measures CIE76
distance between every pair of wire colours:

- normal vision, protanopia, deuteranopia: every pair ≥ 15 Lab units apart;
- tritanopia: orange/purple 11.5, sky blue/green 13.4, green/blue 10.6 — closer, and the reason
  the glyph exists. The threshold there is 10.

The other half of the test is that no two core types share a colour *and* a glyph. It found one:
`astro.LineList` and `astro.Transition` were both an orange triangle, and they meet on
`rbcodes.lines.find_transition`, which takes one and returns the other. A transition is a
wavelength on a spectrum, so it took the spectral glyph in the line family's colour: an orange
diamond.

## Reduced motion

A single `@media (prefers-reduced-motion: reduce)` block in
[`main.css`](https://github.com/lblogan14/astro-canvas/blob/main/frontend/src/assets/main.css)
collapses every animation and transition to 0.001 ms and turns off smooth scrolling. The app's
motion is decoration — a pulsing running badge, a sliding sheet, the canvas's easing — so there
is nothing to preserve. `!important` is deliberate: what it overrides are themselves utilities,
and a per-component opt-out would be one more thing to forget.

## Adding a page to the audit

One `test` and one `audit(page, label)` call:

```ts
test('the thing I just built', async ({ page, request }) => {
  const doc = await shell(page, request)
  await page.getByTestId('open-the-thing').click()
  await audit(page, 'the thing', '[data-testid="the-thing"]')
})
```

Pass the `include` selector when the surface is a panel or a dialog: the audit is then about your
markup and not about whatever else is on the page.

## What is not covered

- **Screen-reader narration of the graph itself.** A node's ports, its status and its wires are
  drawn as SVG inside Vue Flow, and reading them aloud sensibly needs a live region and a
  keyboard model for the canvas — a v0.2 item, not a phase 13 fix.
- **Keyboard editing of the graph.** Nodes can be added (`Ctrl+K`), run, and configured entirely
  from the keyboard, and every panel and mode is reachable; *wiring* two nodes together still
  needs a pointer.
- **Zoom to 200 %** (WCAG 1.4.4) is untested; the shell is responsive but the canvas is not
  reflowable by nature.
