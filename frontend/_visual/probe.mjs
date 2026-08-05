/**
 * Walk every audited route and report what actually rendered.
 *
 * Fast feedback loop for building the stub: a page whose data shape is wrong
 * throws into the ErrorBoundary, and the audit spec then just times out
 * waiting for <main> without saying why. This prints the crash text and any
 * pageerror per route so the offending endpoint is obvious.
 */
import { chromium } from 'playwright'

const ROUTES = [
  '/dashboard',
  '/positions',
  '/orderbook',
  '/tradebook',
  '/holdings',
  '/strategy',
  '/marketplace',
  '/analytics',
  '/logs',
  '/apikey',
  '/profile',
  '/sandbox',
]

const SESSION = {
  status: 'success',
  logged_in: true,
  authenticated: true,
  user: 'audit',
  broker: 'zerodha',
  is_admin: true,
  api_key: 'audit-key',
  active_sessions: 1,
  subscription_required: false,
}

// Endpoints whose shape the generic envelope gets wrong. Mirrors stub.ts --
// keep the two in sync when adding a route.
const EXTRA = [
  ['/api/v1/deployments', []],
  ['/flow/api/workflows', []],
  [
    'capabilities',
    { status: 'success', data: { broker: 'zerodha', broker_type: 'equity', exchanges: ['NSE', 'NFO'], features: {} } },
  ],
  ['/sandbox/api/configs', { status: 'success', configs: {} }],
  ['/api/broker/credentials', {
      status: 'success',
      data: {
        valid_brokers: ['zerodha', 'dhan', 'angel', 'upstox', 'fyers'],
        current_broker: 'zerodha',
        redirect_url: 'http://127.0.0.1:5000/zerodha/callback',
        host_server: 'http://127.0.0.1:5000',
        websocket_url: 'ws://127.0.0.1:8785',
        ngrok_allow: false,
        credentials: [],
      },
    }],
]

const browser = await chromium.launch()
const results = []

for (const route of ROUTES) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message.slice(0, 160)))
  page.on('console', (m) => {
    if (m.type() !== 'error') return
    const t = m.text()
    if (!/Failed to load resource|net::ERR|WebSocket|DevTools/i.test(t)) errors.push(t.slice(0, 160))
  })

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

  await page.route('**/*', async (r, q) => {
    const t = q.resourceType()
    if (t !== 'xhr' && t !== 'fetch') return r.continue()
    const u = q.url()
    const J = (o) =>
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(o) })
    if (u.includes('/auth/session-status')) return J(SESSION)
    for (const [needle, body] of EXTRA) if (u.includes(needle)) return J(body)
    return J({ status: 'success', data: [], message: '' })
  })

  await page.goto(`http://localhost:5173${route}`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3000)

  const state = await page.evaluate(() => ({
    url: location.pathname,
    hasMain: !!document.querySelector('main'),
    crashed: document.body.innerText.includes('Something went wrong'),
    text: document.body.innerText.slice(0, 130).replace(/\n+/g, ' | '),
  }))

  results.push({ route, ...state, errors: [...new Set(errors)].slice(0, 2) })
  await page.close()
}

await browser.close()

console.log('\nroute             status   landed          detail')
console.log('-'.repeat(104))
for (const r of results) {
  const flag = r.crashed ? 'CRASH ' : r.hasMain ? ' ok   ' : ' NOMAIN'
  console.log(
    `${r.route.padEnd(17)} ${flag}  ${r.url.padEnd(15)} ${r.crashed || !r.hasMain ? r.text : ''}`
  )
  for (const e of r.errors) console.log(`${' '.repeat(19)}! ${e}`)
}
