/**
 * Visual audit of the layout refactor.
 *
 * The Flask backend will not boot with the placeholder REDIRECT_URL in .env,
 * so every /api and blueprint call is fulfilled from a stub here. That is
 * enough for what this checks: layout, spacing, header/container consistency
 * and mobile overflow are all client-side concerns. Nothing here asserts on
 * real market data.
 *
 * Two kinds of check:
 *  1. Automated assertions that catch the bug classes this refactor targeted
 *     -- horizontal page scroll, off-screen dialog close buttons, headers
 *     that disagree on title size, content columns that jump between routes.
 *  2. Screenshots, so the result can actually be looked at.
 */
import { expect, type Page, test } from '@playwright/test'
import { installStub } from './stub'

const DESKTOP = { width: 1440, height: 900 }
const PHONE = { width: 390, height: 844 } // iPhone 14

/** Pages that render inside the app shell and were touched by the refactor. */
const ROUTES = [
  ['dashboard', '/dashboard'],
  ['positions', '/positions'],
  ['orderbook', '/orderbook'],
  ['tradebook', '/tradebook'],
  ['holdings', '/holdings'],
  ['strategies', '/strategy'],
  ['marketplace', '/marketplace'],
  ['analytics', '/analytics'],
  ['logs', '/logs'],
  // /apikey is omitted: the Vite DEV server 404s that path instead of serving
  // the SPA shell (its history-fallback treats it as a file request), so the
  // app never mounts there under `npm run dev`. Pre-existing and dev-only --
  // in production Flask serves index.html for it. Verified untouched by this
  // refactor: `git diff <base>..HEAD -- vite.config.ts` is empty.
  ['profile', '/profile'],
  ['sandbox', '/sandbox'],
] as const

async function seed(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem(
      'maxalgos-auth',
      JSON.stringify({
        state: {
          user: {
            username: 'audit',
            broker: 'zerodha',
            isLoggedIn: true,
            loginTime: new Date().toISOString(),
          },
          apiKey: 'audit-key',
          isAuthenticated: true,
          isAdmin: true,
          brokerSessionValid: true,
        },
        version: 0,
      })
    )
  })
  await installStub(page)
}

/** Console errors that indicate a real client-side fault. */
function watchConsole(page: Page, sink: string[]) {
  page.on('console', (m) => {
    if (m.type() !== 'error') return
    const t = m.text()
    // Network noise from the stubbed backend is expected and not a UI bug.
    if (/Failed to load resource|net::ERR|WebSocket|401|403|404/i.test(t)) return
    sink.push(t)
  })
  page.on('pageerror', (e) => sink.push(`pageerror: ${e.message}`))
}

test.describe('layout audit', () => {
  for (const [name, path] of ROUTES) {
    test(`${name} — desktop`, async ({ page }, testInfo) => {
      const errors: string[] = []
      watchConsole(page, errors)
      await seed(page)
      await page.setViewportSize(DESKTOP)
      await page.goto(path, { waitUntil: 'domcontentloaded' })
      // Guard: without this the whole suite passes vacuously on a blank page.
      // The app shell renders <main>; if it never appears, the page did not
      // mount and every downstream assertion is meaningless.
      await expect(page.locator('main').first()).toBeVisible({ timeout: 15000 })
      await page.waitForTimeout(1200)

      await page.screenshot({
        path: testInfo.outputPath(`${name}-desktop.png`),
        fullPage: true,
      })

      // The body-level `overflow-x: clip` should mean the document never
      // scrolls sideways. If this trips, something escaped its container.
      const overflow = await page.evaluate(() => ({
        docWidth: document.documentElement.scrollWidth,
        viewWidth: document.documentElement.clientWidth,
      }))
      expect(
        overflow.docWidth,
        `${name}: page scrolls horizontally (${overflow.docWidth} > ${overflow.viewWidth})`
      ).toBeLessThanOrEqual(overflow.viewWidth + 1)

      expect(errors, `${name}: console errors`).toEqual([])
    })

    test(`${name} — phone`, async ({ page }, testInfo) => {
      await seed(page)
      await page.setViewportSize(PHONE)
      await page.goto(path, { waitUntil: 'domcontentloaded' })
      await expect(page.locator('main').first()).toBeVisible({ timeout: 15000 })
      await page.waitForTimeout(1200)

      await page.screenshot({
        path: testInfo.outputPath(`${name}-phone.png`),
        fullPage: true,
      })

      const overflow = await page.evaluate(() => ({
        docWidth: document.documentElement.scrollWidth,
        viewWidth: document.documentElement.clientWidth,
        // Name the widest offender so a failure is actionable.
        culprit: (() => {
          const vw = document.documentElement.clientWidth
          let worst = { sel: '', w: 0 }
          for (const el of Array.from(document.querySelectorAll<HTMLElement>('body *'))) {
            const r = el.getBoundingClientRect()
            if (r.width > vw + 1 && r.width > worst.w) {
              worst = {
                sel: `${el.tagName.toLowerCase()}.${(el.className || '').toString().slice(0, 80)}`,
                w: Math.round(r.width),
              }
            }
          }
          return worst.sel ? `${worst.sel} (${worst.w}px)` : ''
        })(),
      }))
      expect(
        overflow.docWidth,
        `${name}: h-scroll on phone (${overflow.docWidth} > ${overflow.viewWidth}) widest: ${overflow.culprit}`
      ).toBeLessThanOrEqual(overflow.viewWidth + 1)
    })
  }
})

test('page headings agree on size across routes', async ({ page }) => {
  await seed(page)
  await page.setViewportSize(DESKTOP)
  const seen: Record<string, string[]> = {}

  for (const [name, path] of ROUTES) {
    await page.goto(path, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(900)
    const h1 = page.locator('h1').first()
    if ((await h1.count()) === 0) continue
    const size = await h1.evaluate((el) => getComputedStyle(el).fontSize)
    ;(seen[size] ??= []).push(name)
  }

  // The whole point of PageHeader: one font-size for every in-app page title.
  expect(
    Object.keys(seen).length,
    `page titles render at ${Object.keys(seen).length} different sizes: ${JSON.stringify(seen)}`
  ).toBeLessThanOrEqual(1)
})

test('content column is the same width across routes', async ({ page }) => {
  await seed(page)
  await page.setViewportSize(DESKTOP)
  const widths: Record<string, number[]> = {}

  for (const [name, path] of ROUTES) {
    await page.goto(path, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(900)
    const main = page.locator('main').first()
    if ((await main.count()) === 0) continue
    const w = await main.evaluate((el) => {
      const kid = el.firstElementChild as HTMLElement | null
      return kid ? Math.round(kid.getBoundingClientRect().width) : 0
    })
    ;(widths[String(w)] ??= []).push(name)
  }
  // Narrow pages (Profile, ApiKey) legitimately differ, so allow a small
  // number of distinct widths -- but not one per page, which is what the
  // ~40 hand-rolled root wrappers produced.
  expect(
    Object.keys(widths).length,
    `content column widths: ${JSON.stringify(widths)}`
  ).toBeLessThanOrEqual(3)
})
