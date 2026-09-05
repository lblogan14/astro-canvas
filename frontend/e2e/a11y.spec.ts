/**
 * Accessibility (phase 13, scope item 3): axe-core over the surfaces a user cannot avoid.
 *
 * The gate is **zero serious or critical violations** against WCAG 2.1 A and AA. Moderate and
 * minor findings are printed rather than failed — most of what is left is landmark advice that
 * does not map onto a canvas application, and a gate that has to be argued with gets disabled.
 *
 * One deliberate exclusion:
 *
 * - `.vue-flow__pane` and `.vue-flow__edges` are Vue Flow's own markup. The chrome around them,
 *   the nodes Astro Canvas renders into them and the on-canvas controls are all audited.
 * Disabled controls are *not* exempted, even though WCAG 1.4.3 would allow it: the button
 * variants drop to `--muted-foreground` on `--muted` when disabled rather than fading to 50 %
 * opacity, so an inactive label stays readable and the audit stays honest.
 */
import AxeBuilder from '@axe-core/playwright'
import type { APIRequestContext, Page } from '@playwright/test'
import { expect, test } from './fixtures'

import {
  type WorkflowDocLike,
  createWorkflow,
  deleteWorkflow,
  mathChain,
  openWorkflow,
  uniqueId,
} from './helpers'

const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']
const ABSORPTION = 'rbcodes.absorption-line-measurement'

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
 * as its own contrast failure — a button going from enabled to disabled measured 2.5:1 in the
 * middle and 5.5:1 at both ends. Infinite animations (the running badge's pulse) are skipped,
 * because waiting for those never returns.
 */
async function settle(page: Page): Promise<void> {
  // Three rounds: waiting for the animations in flight can let a late render start new ones
  // (a preview arriving, a chip re-rendering), and those are the ones axe would catch halfway.
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
async function audit(page: Page, label: string, include?: string): Promise<void> {
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

/** Open a fresh math chain and wait until the shell is live. */
async function shell(page: Page, request: APIRequestContext): Promise<WorkflowDocLike> {
  const doc = mathChain()
  await createWorkflow(request, doc)
  await openWorkflow(page, doc.id)
  await expect(page.getByTestId('run')).toBeEnabled()
  return doc
}

async function instantiate(request: APIRequestContext, template: string): Promise<string> {
  const response = await request.post(
    `/api/templates/${encodeURIComponent(template)}/instantiate`,
    { data: { name: `a11y ${uniqueId('t')}` } },
  )
  expect(response.status()).toBe(201)
  return ((await response.json()) as { doc: { id: string } }).doc.id
}

test.describe('accessibility', () => {
  test('the canvas shell', async ({ page, request }) => {
    const doc = await shell(page, request)
    try {
      await audit(page, 'canvas shell')
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('the node library, searched', async ({ page, request }) => {
    const doc = await shell(page, request)
    try {
      // The library is the sidebar's default panel; clicking its toolbar button would close it.
      await expect(page.getByTestId('node-library')).toBeVisible()
      await page.getByTestId('library-search').fill('spec')
      await expect(page.locator('[data-node-type]').first()).toBeVisible()
      await audit(page, 'node library', '[data-testid="node-library"]')
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('the inspector on a selected node, where AutoForm renders the widgets', async ({
    page,
    request,
  }) => {
    const doc = await shell(page, request)
    try {
      await page.getByTestId('node-sum').click()
      await expect(page.getByTestId('inspector')).toBeVisible()
      await audit(page, 'inspector', '[data-testid="inspector"]')
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('the command palette and the bottom drawer', async ({ page, request }) => {
    const doc = await shell(page, request)
    try {
      await page.getByTestId('toggle-drawer').click()
      await expect(page.getByTestId('drawer')).toBeVisible()
      await audit(page, 'bottom drawer', '[data-testid="drawer"]')

      await page.getByTestId('canvas').click({ position: { x: 30, y: 30 } })
      await page.keyboard.press('Control+K')
      await expect(page.getByTestId('palette')).toBeVisible()
      await audit(page, 'command palette', '[data-testid="palette"]')
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('the workspace and workflows panels', async ({ page, request }) => {
    const doc = await shell(page, request)
    try {
      await page.getByTestId('toggle-workspace').click()
      await expect(page.getByTestId('workspace-panel')).toBeVisible()
      await expect(page.getByTestId('workspace-root')).not.toBeEmpty()
      await audit(page, 'workspace panel', '[data-testid="workspace-panel"]')

      await page.getByTestId('toggle-workflows').click()
      await expect(page.getByTestId('workflows-panel')).toBeVisible()
      await audit(page, 'workflows panel', '[data-testid="workflows-panel"]')
    } finally {
      await deleteWorkflow(request, doc.id)
    }
  })

  test('the templates gallery', async ({ page }) => {
    await page.goto('/templates')
    await expect(page.getByTestId('gallery-list')).toBeVisible()
    await audit(page, 'templates gallery')
  })

  test('the four app-mode layouts of a real template', async ({ page, request }) => {
    test.slow()
    const id = await instantiate(request, ABSORPTION)
    try {
      for (const mode of ['app', 'wizard', 'dashboard', 'batch'] as const) {
        await page.goto(`/w/${encodeURIComponent(id)}/${mode}`)
        await expect(page.getByTestId(`${mode}-mode`)).toBeVisible({ timeout: 60000 })
        await audit(page, `${mode} mode`)
      }
    } finally {
      await deleteWorkflow(request, id)
    }
  })

  test('an expandable editor and the viewer sheet', async ({ page, request }) => {
    test.slow()
    const id = await instantiate(request, ABSORPTION)
    try {
      await openWorkflow(page, id)
      const continuum = page.locator('[data-testid="node-continuum"]')
      await expect(continuum.getByTestId('status-badge')).toHaveText(/done/i, { timeout: 90000 })

      await continuum.getByTestId('node-editor').click()
      const editor = page.getByTestId('editor')
      await expect(editor).toBeVisible()
      await audit(page, 'continuum editor', '[data-testid="editor"]')
      await page.getByTestId('editor-close').click()
      await expect(editor).toHaveCount(0)

      await page.locator('[data-testid="node-slice"]').getByTestId('preview-expand').click()
      await expect(page.getByTestId('viewer')).toBeVisible()
      await audit(page, 'viewer sheet', '[data-testid="viewer"]')
    } finally {
      await deleteWorkflow(request, id)
    }
  })
})
