/**
 * Phase 11 acceptance: the Manager page.
 *
 * No install runs here — a real install mutates the environment the whole suite shares, and the
 * resolution step is where the contract with the user actually is. So: the Installed tab lists
 * the packs the server discovered, resolving a source shows the diff before anything happens, a
 * pack whose pins conflict with the app is blocked with the resolver's reason and no confirm
 * button, disabling a pack takes its nodes out of the library, and a snapshot can be taken.
 */
import { E2E_TOKEN, USE_WHEEL, expect, test } from './fixtures'

async function openManager(page: import('@playwright/test').Page) {
  await page.goto(`/manager?token=${E2E_TOKEN}`)
  await page.getByTestId('manager-page').waitFor()
  await expect(page.getByTestId('pack-core')).toBeVisible({ timeout: 20000 })
}

test.describe('pack manager', () => {
  test('lists the installed packs with their distributions and node counts', async ({ page }) => {
    await openManager(page)
    const core = page.getByTestId('pack-core')
    await expect(core).toContainText('astro-canvas-core')
    await expect(core).toContainText('astro_canvas_core:register')
    await expect(core).toContainText(/\d+ nodes/)
    await expect(core).toHaveAttribute('data-enabled', 'true')
    await expect(core).toHaveAttribute('data-error', 'false')
    await expect(page.getByTestId('pack-rbcodes')).toBeVisible()
  })

  test('the registry tab lists the first-party packs and marks them installed', async ({
    page,
  }) => {
    await openManager(page)
    await page.getByTestId('manager-tab-registry').click()
    await expect(page.getByTestId('registry-card-astro-canvas-core')).toBeVisible({
      timeout: 20000,
    })
    // Both are installed here, so the card offers no install button.
    await expect(page.getByTestId('registry-installed-astro-canvas-core')).toBeVisible()
    await expect(page.getByTestId('registry-install-astro-canvas-core')).toHaveCount(0)

    await page.getByTestId('registry-search').fill('absorption')
    await expect(page.getByTestId('registry-card-astro-canvas-rbcodes')).toBeVisible()
    await expect(page.getByTestId('registry-card-astro-canvas-core')).toHaveCount(0)
  })

  test('resolving shows the diff before anything is installed', async ({ page }) => {
    await openManager(page)
    // A pack that is already installed at this exact version: a plan with no changes at all.
    await page.getByTestId('manager-source').fill('astro-canvas-core')
    await page.getByTestId('manager-install').click()

    const dialog = page.getByTestId('plan-dialog')
    await expect(dialog).toBeVisible({ timeout: 60000 })
    await expect(dialog).toHaveAttribute('data-blocked', 'false')
    if (USE_WHEEL) {
      // Against the wheels the server runs in an ephemeral `uv run --with` overlay, and
      // `uv pip install --dry-run` inside one does not see the overlay's own packages as
      // installed -- so the plan is legitimately non-empty. What still has to hold is that a
      // plan is *shown*, before anything is touched.
      await expect(page.getByTestId('plan-summary')).toBeVisible()
    } else {
      // Nothing would change, so there is nothing to confirm.
      await expect(page.getByTestId('plan-empty')).toBeVisible()
      await expect(page.getByTestId('plan-confirm')).toHaveCount(0)
    }

    await page.getByTestId('plan-cancel').click()
    await expect(dialog).toHaveCount(0)
  })

  test('a pack whose pins conflict with the app is blocked with the reason', async ({ page }) => {
    await openManager(page)
    // numpy 1.19 cannot satisfy what Astro Canvas itself requires, so the resolver refuses.
    await page.getByTestId('manager-source').fill('numpy==1.19.5')
    await page.getByTestId('manager-install').click()

    const dialog = page.getByTestId('plan-dialog')
    await expect(dialog).toBeVisible({ timeout: 60000 })
    await expect(dialog).toHaveAttribute('data-blocked', 'true')
    await expect(page.getByTestId('plan-conflicts')).toContainText(/unsatisfiable/i)
    await expect(page.getByTestId('plan-conflicts')).toContainText('numpy')
    // Blocked means blocked: the dialog offers no way to go ahead.
    await expect(page.getByTestId('plan-confirm')).toHaveCount(0)
    await page.getByTestId('plan-cancel').click()
  })

  test('disabling a pack takes its nodes out of the library, and enabling brings them back', async ({
    page,
  }) => {
    await openManager(page)
    const pack = page.getByTestId('pack-rbcodes')
    await page.getByTestId('pack-toggle-rbcodes').click()
    await expect(pack).toHaveAttribute('data-enabled', 'false', { timeout: 20000 })

    await page.goto(`/?token=${E2E_TOKEN}`)
    await page.getByTestId('canvas').waitFor()
    await page.getByTestId('library-search').fill('equivalent width')
    await expect(page.getByTestId('library-no-results')).toBeVisible({ timeout: 20000 })

    await openManager(page)
    await page.getByTestId('pack-toggle-rbcodes').click()
    await expect(page.getByTestId('pack-rbcodes')).toHaveAttribute('data-enabled', 'true', {
      timeout: 20000,
    })
  })

  test('a snapshot records the environment and shows up in the list', async ({ page }) => {
    await openManager(page)
    await page.getByTestId('manager-tab-snapshots').click()
    const label = `e2e ${Date.now()}`
    await page.getByTestId('snapshot-label').fill(label)
    await page.getByTestId('snapshot-create').click()

    const row = page.locator('[data-testid^="snapshot-"]').filter({ hasText: label })
    await expect(row).toBeVisible({ timeout: 60000 })
    await expect(row).toContainText(/\d+ packages/)
  })

  test('settings show uv and persist the security level', async ({ page }) => {
    await openManager(page)
    await page.getByTestId('manager-tab-settings').click()
    await expect(page.getByTestId('manager-uv')).toContainText('uv')

    // Click the radio rather than `check()`: the input's checked state is driven by the store,
    // which only changes once the server has stored the choice.
    await page.getByTestId('security-permissive').locator('input').click()
    await expect(page.getByTestId('security-permissive').locator('input')).toBeChecked({
      timeout: 20000,
    })

    await page.reload()
    await page.getByTestId('manager-page').waitFor()
    await page.getByTestId('manager-tab-settings').click()
    await expect(page.getByTestId('security-permissive').locator('input')).toBeChecked({
      timeout: 20000,
    })

    // Leave the workspace as the rest of the suite expects to find it.
    await page.getByTestId('security-standard').locator('input').click()
    await expect(page.getByTestId('security-standard').locator('input')).toBeChecked({
      timeout: 20000,
    })
  })
})
