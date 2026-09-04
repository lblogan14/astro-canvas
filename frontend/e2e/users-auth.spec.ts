import type { Page } from '@playwright/test'
import { expect, test } from '@playwright/test'

import { ADMIN_EMAIL } from '../playwright.config'

/**
 * The `--auth users` tier (design §12), against a second backend started with login accounts.
 *
 * Runs in its own Playwright project so the token-authenticated suite is untouched. Each test
 * uses a fresh address, because this backend keeps its identity database between runs and a
 * shared account would make the tests order-dependent. The admin address is the exception: it
 * is the one `ASTRO_CANVAS_ADMIN_EMAILS` promotes, so a repeat registration is expected to be
 * refused and the sign-in is what matters.
 */

const PASSWORD = 'a good long phrase'

function freshEmail(): string {
  return `student-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}@lab.example`
}

/** Create the account through the API (tolerating "already exists"), then sign in through the UI. */
async function account(page: Page, email: string, displayName = ''): Promise<void> {
  const created = await page.request.post('/api/auth/register', {
    data: { email, password: PASSWORD, display_name: displayName },
    failOnStatusCode: false,
  })
  expect([201, 400]).toContain(created.status())
  await signIn(page, email)
}

async function signIn(page: Page, email: string): Promise<void> {
  await page.context().clearCookies()
  await page.goto('/login')
  await page.getByTestId('login-email').fill(email)
  await page.getByTestId('login-password').fill(PASSWORD)
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('account')).toBeVisible()
  await expect(page).not.toHaveURL(/\/login/)
}

test('the canvas is behind a login, and remembers where you were going', async ({ page }) => {
  await page.context().clearCookies()
  await page.goto('/templates')
  await expect(page).toHaveURL('/login?redirect=/templates')
  await expect(page.getByTestId('login-form')).toBeVisible()
  await expect(page.getByTestId('canvas')).toHaveCount(0)
})

test('a wrong password is reported and keeps you on the page', async ({ page }) => {
  await page.context().clearCookies()
  await page.goto('/login')
  await page.getByTestId('login-email').fill('nobody@lab.example')
  await page.getByTestId('login-password').fill('not the password')
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('login-error')).toBeVisible()
  await expect(page).toHaveURL(/\/login$/)
})

test('signing up through the form lands on the canvas and names the account', async ({ page }) => {
  const email = freshEmail()
  await page.context().clearCookies()
  await page.goto('/login')
  await page.getByTestId('login-toggle').click()
  await page.getByTestId('login-email').fill(email)
  await page.getByTestId('login-password').fill(PASSWORD)
  await page.getByTestId('login-display-name').fill('A Student')
  await page.getByTestId('login-submit').click()

  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByTestId('account')).toHaveText(/A Student/)
  await expect(page.getByTestId('account')).toHaveAttribute('data-admin', 'false')
  await expect(page.getByTestId('ws-status')).toHaveAttribute('data-status', 'open')
})

test('a member cannot reach the pack manager', async ({ page }) => {
  await account(page, freshEmail())
  await page.getByTestId('share-menu').click()
  await expect(page.getByTestId('share-manager')).toHaveCount(0)
  await page.keyboard.press('Escape')

  // Typing the URL is not a way around it either.
  await page.goto('/manager')
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByTestId('manager-page')).toHaveCount(0)
})

test('an admin sees the pack manager', async ({ page }) => {
  await account(page, ADMIN_EMAIL, 'PI')
  await expect(page.getByTestId('account')).toHaveAttribute('data-admin', 'true')

  await page.getByTestId('share-menu').click()
  await page.getByTestId('share-manager').click()
  await expect(page.getByTestId('manager-page')).toBeVisible()
  await expect(page.getByTestId('pack-core')).toBeVisible()
})

test('each account gets its own workspace, and cannot change it', async ({ page }) => {
  const first = freshEmail()
  const second = freshEmail()

  await account(page, first)
  const one = await (await page.request.get('/api/workspace')).json()
  expect(one.can_select).toBe(false)

  await account(page, second)
  const two = await (await page.request.get('/api/workspace')).json()
  expect(two.root).not.toBe(one.root)

  const refused = await page.request.post('/api/workspace/select', {
    data: { path: one.root, create: false },
    failOnStatusCode: false,
  })
  expect(refused.status()).toBe(403)
})

test('signing out puts the login back', async ({ page }) => {
  await account(page, freshEmail())
  await page.getByTestId('sign-out').click()
  await expect(page).toHaveURL(/\/login/)
  await page.goto('/')
  await expect(page.getByTestId('login-form')).toBeVisible()
  await expect(page.getByTestId('canvas')).toHaveCount(0)
})
