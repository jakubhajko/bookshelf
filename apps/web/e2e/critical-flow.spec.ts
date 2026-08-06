import { AxeBuilder } from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

/**
 * Spec §13.5's critical flow, end to end against a real Chromium browser and
 * a real API + PostgreSQL — the first place in this project anything runs
 * in an actual browser rather than jsdom or curl. One long sequential story
 * (`test.step` per numbered spec step) rather than 13 independent tests:
 * each step depends on state the previous one left behind (the account, the
 * rating, the shelves), so splitting them would mean re-deriving that state
 * per test for no real isolation benefit.
 *
 * Two axe-core scans are folded in at natural checkpoints (Home after
 * login, the book-detail dialog) rather than run as a separate test —
 * spec §18 Phase 9 asks for an accessibility pass, and scanning real,
 * populated, interactive states this flow already reaches is more useful
 * than scanning empty pages in isolation. Only "critical"/"serious" impact
 * violations fail the test; "moderate"/"minor" are logged, not enforced —
 * this is the first automated a11y check this project has ever run, and a
 * hard zero-tolerance gate on every impact level on day one would be more
 * likely to make the check get disabled than to fix a moderate issue.
 *
 * Runs against whatever `E2E_BASE_URL`/API is already up (see
 * playwright.config.ts) — a fresh username is generated per run so this is
 * safe to run repeatedly against a persistent dev database, not just a
 * throwaway CI one.
 */

const ENFORCED_IMPACTS = new Set(['critical', 'serious'])

async function assertNoSeriousViolations(page: Page, scopeSelector?: string) {
  const builder = new AxeBuilder({ page })
  if (scopeSelector) builder.include(scopeSelector)
  const results = await builder.analyze()

  const enforced = results.violations.filter((v) => ENFORCED_IMPACTS.has(v.impact ?? ''))
  const other = results.violations.filter((v) => !ENFORCED_IMPACTS.has(v.impact ?? ''))

  if (other.length > 0) {
    console.log(
      `axe: ${other.length} non-blocking (moderate/minor) violation(s) — ` +
        other.map((v) => `${v.id} (${v.impact})`).join(', '),
    )
  }

  expect(enforced, JSON.stringify(enforced, null, 2)).toEqual([])
}

test('critical flow: register, rate, shelve, reject, and persist across a session', async ({
  page,
}) => {
  const runId = `${Date.now()}`
  const username = `e2e_${runId}`
  const password = 'E2E-test-passw0rd!'
  const shelfNameA = `To Read ${runId}`
  const shelfNameB = `Favorites ${runId}`

  const main = page.getByRole('main')
  let ratedBookId = ''
  let ratedBookTitle = ''
  let rejectedBookId = ''

  await test.step('1. register', async () => {
    await page.goto('/register')
    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Password', { exact: true }).fill(password)
    await page.getByLabel('Confirm password').fill(password)
    await page.getByRole('button', { name: 'Create account' }).click()
    await expect(page).toHaveURL(/\/login$/)
    await expect(page.getByText('Account created. Log in to continue.')).toBeVisible()
  })

  await test.step('2. login', async () => {
    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', { name: 'Log in' }).click()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByRole('button', { name: `Account menu for ${username}` })).toBeVisible()
  })

  await test.step('3. browse', async () => {
    await expect(main.getByRole('heading', { level: 3 }).first()).toBeVisible()
    await assertNoSeriousViolations(page)
  })

  await test.step('4. open', async () => {
    ratedBookTitle = (await main.getByRole('heading', { level: 3 }).first().textContent())?.trim() ?? ''
    expect(ratedBookTitle).not.toBe('')
    await main.getByRole('heading', { level: 3 }).first().click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('radiogroup', { name: 'Your rating' })).toBeVisible()
    await expect(dialog.getByRole('heading', { level: 1 })).toHaveText(ratedBookTitle)

    ratedBookId = new URL(page.url()).pathname.split('/').pop() ?? ''
    expect(ratedBookId).toMatch(/^\d+$/)

    await assertNoSeriousViolations(page, '[role="dialog"]')
  })

  await test.step('5. rate', async () => {
    const dialog = page.getByRole('dialog')
    // RatingStars' radio inputs are deliberately `sr-only` — the visible,
    // clickable surface is the <label> that wraps each one (real users and
    // screen readers both go through it; a sighted mouse click never lands
    // on the input's own, invisible geometry), so click the label itself
    // rather than fighting Playwright's actionability checks on a hidden
    // node. Plain `.click()` (not `.check()`) skips its own immediate
    // post-click checked-state verification, which raced React's render on
    // a slower run; the "Remove rating" assertion below already re-polls
    // until the mutation's optimistic update actually lands.
    await dialog.locator('label').filter({ hasText: '4 stars' }).click()
    await expect(dialog.getByRole('button', { name: 'Remove rating' })).toBeVisible()
    await dialog.getByRole('button', { name: 'Close' }).click()
    await expect(dialog).toBeHidden()
  })

  await test.step('6. verify Rated', async () => {
    await page.getByRole('link', { name: 'Rated' }).click()
    await expect(page).toHaveURL(/\/rated$/)
    await expect(page.getByRole('heading', { name: 'Rated books' })).toBeVisible()
    await expect(
      main.getByRole('heading', { level: 3, name: ratedBookTitle, exact: true }),
    ).toBeVisible()
  })

  await test.step('7. create shelf', async () => {
    await page.getByRole('link', { name: 'Shelves' }).click()
    await expect(page).toHaveURL(/\/shelves$/)

    await page.getByLabel('New shelf').fill(shelfNameA)
    await page.getByRole('button', { name: 'Create' }).click()
    await expect(page.getByRole('heading', { level: 2, name: shelfNameA, exact: true })).toBeVisible()

    await page.getByLabel('New shelf').fill(shelfNameB)
    await page.getByRole('button', { name: 'Create' }).click()
    await expect(page.getByRole('heading', { level: 2, name: shelfNameB, exact: true })).toBeVisible()
  })

  await test.step('8. save to multiple shelves', async () => {
    // Direct navigation to the specific book rather than picking Home's
    // "first card" again — rating it in step 5 made it recommendation-
    // ineligible (spec §5.5), so it may no longer be Home's first item.
    await page.goto(`/books/${ratedBookId}`)
    await expect(main.getByRole('heading', { level: 1 })).toHaveText(ratedBookTitle)

    await main.getByRole('button', { name: 'Add to shelf' }).click()
    await page.getByRole('checkbox', { name: shelfNameA, exact: true }).check()
    await page.getByRole('checkbox', { name: shelfNameB, exact: true }).check()
    await page.keyboard.press('Escape')
  })

  await test.step('9. open shelf Discover', async () => {
    await page.getByRole('link', { name: 'Shelves' }).click()
    await page.getByRole('heading', { level: 2, name: shelfNameA, exact: true }).click()
    await expect(page).toHaveURL(/\/shelves\/[^/]+\/books$/)

    await page.getByRole('link', { name: 'Discover' }).click()
    await expect(page).toHaveURL(/\/shelves\/[^/]+\/discover$/)
  })

  await test.step('10. reject another book', async () => {
    await expect(main.getByRole('heading', { level: 3 }).first()).toBeVisible()
    await main.getByRole('heading', { level: 3 }).first().click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    rejectedBookId = new URL(page.url()).pathname.split('/').pop() ?? ''
    expect(rejectedBookId).toMatch(/^\d+$/)
    expect(rejectedBookId).not.toBe(ratedBookId)

    await dialog.getByRole('button', { name: 'Not interested' }).click()
    await expect(dialog.getByRole('button', { name: 'Not interested' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    await dialog.getByRole('button', { name: 'Close' }).click()
    await expect(dialog).toBeHidden()
  })

  await test.step('11. logout', async () => {
    await page.getByRole('button', { name: `Account menu for ${username}` }).click()
    await page.getByRole('menuitem', { name: 'Log out' }).click()
    await expect(page).toHaveURL(/\/login$/)
  })

  await test.step('12. login', async () => {
    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', { name: 'Log in' }).click()
    await expect(page).toHaveURL(/\/$/)
  })

  await test.step('13. verify persistence', async () => {
    await page.getByRole('link', { name: 'Rated' }).click()
    await expect(
      main.getByRole('heading', { level: 3, name: ratedBookTitle, exact: true }),
    ).toBeVisible()

    await page.getByRole('link', { name: 'Shelves' }).click()
    await expect(page.getByRole('heading', { level: 2, name: shelfNameA, exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { level: 2, name: shelfNameB, exact: true })).toBeVisible()

    await page.getByRole('heading', { level: 2, name: shelfNameB, exact: true }).click()
    await expect(
      main.getByRole('heading', { level: 3, name: ratedBookTitle, exact: true }),
    ).toBeVisible()

    await page.goto(`/books/${rejectedBookId}`)
    await expect(main.getByRole('button', { name: 'Not interested' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })
})
