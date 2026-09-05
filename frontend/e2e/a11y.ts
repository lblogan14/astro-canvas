/**
 * The axe pass, shared by `a11y.spec.ts` (the token tier) and `users-auth.spec.ts` (the login
 * page, which only exists on a `--auth users` server and so lives in the other project).
 *
 * The gate is **zero serious or critical violations** against WCAG 2.1 A and AA. Moderate and
 * minor findings are printed rather than failed — most of what is left is landmark advice that
 * does not map onto a canvas application, and a gate that has to be argued with gets disabled.
 *
 * One deliberate exclusion: `.vue-flow__pane` and `.vue-flow__edges` are the canvas library's own
 * markup. The chrome around them, the nodes Astro Canvas renders into them and the on-canvas
 * controls are all audited. Disabled controls are *not* exempted, even though WCAG 1.4.3 would
 * allow it: the button variants mute when disabled rather than fading to 50 % opacity, so an
 * inactive label stays readable and the audit stays honest.
 */
import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'
import { expect } from './fixtures'

/** WCAG 2.1 A and AA, which is what "no serious violations" is measured against. */
export const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

interface Violation {
  id: string
  impact?: string | null
  help: string
  nodes: { target: unknown[]; failureSummary?: string }[]
}

/** One line per offending element, with axe's own explanation of what to change. */
function explain(violation: Violation): string {
  const where = violation.nodes
    .slice(0, 3)
    .map((n) => `${JSON.stringify(n.target)} ${n.failureSummary?.replace(/\s+/g, ' ') ?? ''}`)
    .join(' | ')
  return `${violation.id} [${violation.impact}] ${violation.help} :: ${where}`
}

/**
 * Wait for every finite animation and transition to finish.
 *
 * axe reads computed styles, so a colour caught halfway through a 150 ms transition is reported
 * as its own contrast failure. Three rounds, because waiting out the animations in flight can let
 * a late render start new ones. Infinite animations (a running badge's pulse) are skipped.
 */
export async function settle(page: Page): Promise<void> {
  for (let round = 0; round < 3; round += 1) {
    const running = await page.evaluate(async () => {
      const finite = document.getAnimations().filter((animation) => {
        const timing = animation.effect?.getComputedTiming()
        return timing !== undefined && timing.iterations !== Infinity
      })
      await Promise.all(finite.map((animation) => animation.finished.catch(() => undefined)))
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      return finite.length
    })
    if (running === 0) return
  }
}

/** Run axe over `page` (or the `include` subtree), fail on serious/critical, report the rest. */
export async function audit(page: Page, label: string, include?: string): Promise<void> {
  await settle(page)
  let builder = new AxeBuilder({ page }).withTags(TAGS)
  builder = builder.exclude('.vue-flow__pane').exclude('.vue-flow__edges')
  if (include) builder = builder.include(include)
  const results = await builder.analyze()
  const violations = results.violations as unknown as Violation[]
  const blocking = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  const rest = violations.filter((v) => !blocking.includes(v))
  if (rest.length)
    console.log(
      `a11y ${label}: ${rest.length} moderate/minor - ` +
        rest.map((v) => `${v.id} (${v.nodes.length})`).join(', '),
    )
  expect(blocking.map(explain), `serious or critical violations on ${label}`).toEqual([])
}
