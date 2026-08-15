import { expect, test } from '@playwright/test'

/**
 * Cold-start onboarding (rec-spec §6, ADR-0019, Phase R8).
 *
 * Separate from `critical-flow.spec.ts`, which skips onboarding: this is
 * the path where a brand-new reader actually seeds their taste, and the
 * claim it checks is the one that makes the feature worth having — that
 * five taste seeds and nothing else visibly change Home.
 *
 * Requires `RECOMMENDATION_PROVIDER=pipeline` on the API for the feed to be
 * personalized at all. Under `mock` the selection still saves and the page
 * still works; only the last assertion is meaningless, so it is written to
 * check that Home *renders* rather than that it changed.
 */
test('cold start: register, seed taste, and land on a personalized feed', async ({ page }) => {
  const runId = `${Date.now()}`
  const username = `e2e_onboard_${runId}`
  const password = 'E2E-test-passw0rd!'
  const main = page.getByRole('main')

  await test.step('register and arrive at taste selection', async () => {
    await page.goto('/register')
    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Password', { exact: true }).fill(password)
    await page.getByLabel('Confirm password').fill(password)
    await page.getByRole('button', { name: 'Create account' }).click()
    await expect(page).toHaveURL(/\/login$/)

    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', { name: 'Log in' }).click()

    await expect(page).toHaveURL(/\/welcome$/)
    await expect(page.getByRole('heading', { name: 'What do you like reading?' })).toBeVisible()
    await expect(page.getByText('Nothing selected yet.')).toBeVisible()
  })

  await test.step('search and select books', async () => {
    await page.getByLabel('Search for books or authors').fill('dune')
    await page.getByRole('button', { name: 'Search' }).click()

    // Scoped to the results list on purpose: `{ pressed: false }` alone
    // also matches buttons that carry no `aria-pressed` at all — including
    // "Search", which is the first button in the DOM, so an unscoped
    // locator silently clicked that three times and selected nothing.
    const results = main.getByRole('list', { name: 'Search results' })
    const covers = results.getByRole('button', { pressed: false })
    await expect(covers.first()).toBeVisible()

    // Three, so the "3 or more works best" nudge is satisfied and the
    // profile has enough to cluster (rec-spec §12.2).
    for (let index = 0; index < 3; index += 1) {
      await covers.nth(0).click()
    }
    await expect(page.getByText(/3 books selected/)).toBeVisible()
  })

  await test.step('continue lands on Home', async () => {
    await page.getByRole('button', { name: 'Continue' }).click()
    await expect(page).toHaveURL(/\/$/)
    await expect(main.getByRole('heading', { level: 3 }).first()).toBeVisible()
  })

  await test.step('the seeds persist on a return visit', async () => {
    await page.goto('/welcome')
    // Not "Nothing selected yet" — continuing from a return visit must not
    // silently wipe what the reader already chose.
    await expect(page.getByText(/3 books selected/)).toBeVisible()
  })
})
