import { expect, test } from './fixtures'

test('shell loads and shows the backend version from /api/health', async ({ page, request }) => {
  const health = await request.get('/api/health')
  expect(health.ok()).toBe(true)
  const { version } = (await health.json()) as { version: string }

  await page.goto('/')
  await expect(page).toHaveTitle(/Astro Canvas/)
  await expect(page.getByRole('heading', { name: 'Astro Canvas' })).toBeVisible()

  const status = page.getByTestId('backend-status')
  await expect(status).toHaveAttribute('data-status', 'online')
  await expect(status).toContainText(`v${version}`)
})

test('unknown client routes still render the shell', async ({ page }) => {
  await page.goto('/some/future/route')
  await expect(page.getByRole('heading', { name: 'Astro Canvas' })).toBeVisible()
})
