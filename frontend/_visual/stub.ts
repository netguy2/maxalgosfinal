import type { Page } from '@playwright/test'

/**
 * Backend stub for the visual audit.
 *
 * The Flask app refuses to boot with the placeholder REDIRECT_URL in .env, so
 * the whole backend is faked here. Every response shape below is copied from
 * what the corresponding component actually reads -- a generic
 * `{status:'success'}` for everything is not enough, because AuthSync
 * inspects `logged_in`/`broker`/`api_key` and calls logout() (bouncing to
 * /login) on anything it doesn't recognise.
 *
 * Data is deliberately non-empty. Empty arrays render every page's EmptyState,
 * which hides exactly the layout being audited: table density, card grids,
 * stat rows and column alignment.
 */

const ok = (body: unknown) => ({
  status: 200,
  contentType: 'application/json',
  body: JSON.stringify(body),
})

const POSITIONS = [
  {
    symbol: 'RELIANCE',
    exchange: 'NSE',
    product: 'MIS',
    quantity: 50,
    average_price: 2891.4,
    ltp: 2934.85,
    pnl: 2172.5,
    pnlpercent: 1.5,
  },
  {
    symbol: 'BANKNIFTY24APR24FUT',
    exchange: 'NFO',
    product: 'NRML',
    quantity: -15,
    average_price: 48250,
    ltp: 48120.5,
    pnl: 1942.5,
    pnlpercent: 0.27,
  },
  {
    symbol: 'NIFTY28MAR2420800CE',
    exchange: 'NFO',
    product: 'NRML',
    quantity: 100,
    average_price: 142.35,
    ltp: 118.9,
    pnl: -2345,
    pnlpercent: -16.47,
  },
  {
    symbol: 'CRUDEOILM20MAY24FUT',
    exchange: 'MCX',
    product: 'NRML',
    quantity: 2,
    average_price: 6431,
    ltp: 6502.5,
    pnl: 715,
    pnlpercent: 1.11,
  },
]

const ORDERS = [
  {
    orderid: '25080500012345',
    symbol: 'RELIANCE',
    exchange: 'NSE',
    action: 'BUY',
    quantity: 50,
    price: 2891.4,
    pricetype: 'LIMIT',
    product: 'MIS',
    order_status: 'complete',
    timestamp: '2026-08-05 09:21:44',
  },
  {
    orderid: '25080500012346',
    symbol: 'BANKNIFTY24APR24FUT',
    exchange: 'NFO',
    action: 'SELL',
    quantity: 15,
    price: 48250,
    pricetype: 'MARKET',
    product: 'NRML',
    order_status: 'complete',
    timestamp: '2026-08-05 09:44:02',
  },
  {
    orderid: '25080500012347',
    symbol: 'TATAMOTORS',
    exchange: 'NSE',
    action: 'BUY',
    quantity: 200,
    price: 1042.8,
    pricetype: 'SL',
    product: 'CNC',
    order_status: 'open',
    timestamp: '2026-08-05 10:02:19',
  },
  {
    orderid: '25080500012348',
    symbol: 'INFY',
    exchange: 'NSE',
    action: 'SELL',
    quantity: 75,
    price: 1588.25,
    pricetype: 'LIMIT',
    product: 'CNC',
    order_status: 'rejected',
    timestamp: '2026-08-05 10:15:37',
  },
]

const HOLDINGS = [
  {
    symbol: 'INFY',
    exchange: 'NSE',
    quantity: 120,
    average_price: 1432.6,
    ltp: 1588.25,
    product: 'CNC',
    pnl: 18678,
    pnlpercent: 10.86,
  },
  {
    symbol: 'TATAMOTORS',
    exchange: 'NSE',
    quantity: 300,
    average_price: 988.15,
    ltp: 1042.8,
    product: 'CNC',
    pnl: 16395,
    pnlpercent: 5.53,
  },
  {
    symbol: 'SBIN',
    exchange: 'NSE',
    quantity: 500,
    average_price: 812.4,
    ltp: 794.55,
    product: 'CNC',
    pnl: -8925,
    pnlpercent: -2.2,
  },
]

/** Endpoint -> payload. First matching substring wins. */
const ROUTES: [string, unknown][] = [
  [
    '/auth/session-status',
    {
      status: 'success',
      logged_in: true,
      authenticated: true,
      user: 'audit',
      broker: 'zerodha',
      is_admin: true,
      api_key: 'audit-key',
      active_sessions: 1,
      subscription_required: false,
    },
  ],
  [
    'capabilities',
    {
      status: 'success',
      data: {
        broker: 'zerodha',
        broker_type: 'equity',
        exchanges: ['NSE', 'BSE', 'NFO', 'BFO', 'CDS', 'MCX', 'NSE_INDEX', 'BSE_INDEX'],
        features: {},
      },
    },
  ],
  [
    'positionbook',
    { status: 'success', data: POSITIONS, statistics: { totalpnl: 2485, totalpositions: 4 } },
  ],
  [
    'orderbook',
    {
      status: 'success',
      data: {
        orders: ORDERS,
        statistics: {
          total_buy_orders: 2,
          total_sell_orders: 2,
          total_completed_orders: 2,
          total_open_orders: 1,
          total_rejected_orders: 1,
        },
      },
    },
  ],
  [
    'tradebook',
    {
      status: 'success',
      data: ORDERS.filter((o) => o.order_status === 'complete').map((o) => ({
        ...o,
        average_price: o.price,
        trade_value: o.price * o.quantity,
      })),
    },
  ],
  [
    'holdings',
    {
      status: 'success',
      data: {
        holdings: HOLDINGS,
        statistics: {
          totalholdingvalue: 1041397,
          totalinvvalue: 1015249,
          totalprofitandloss: 26148,
          totalpnlpercentage: 2.58,
        },
      },
    },
  ],
  // Dashboard reads margin data from here, NOT from a /funds route.
  [
    '/auth/dashboard-data',
    {
      status: 'success',
      data: {
        availablecash: '482915.40',
        collateral: '125000.00',
        m2mrealized: '12480.00',
        m2munrealized: '2485.00',
        utiliseddebits: '317084.60',
      },
    },
  ],
  [
    'funds',
    {
      status: 'success',
      data: {
        availablecash: '482915.40',
        collateral: '125000.00',
        m2mrealized: '12480.00',
        m2munrealized: '2485.00',
        utiliseddebits: '317084.60',
      },
    },
  ],
  [
    'analytics_api/summary',
    {
      status: 'success',
      data: {
        total_pnl: 26148,
        today_realized_pnl: 12480,
        win_rate: 62,
        closed_trades: 34,
        sharpe: 1.42,
        max_drawdown: 8.4,
        avg_latency_ms: 118,
        trades_total: 34,
        used_margin: 317084.6,
      },
    },
  ],
  ['master-contract/status', { status: 'success', data: { status: 'success', message: 'Ready' } }],
  ['/settings/', { status: 'success', data: { mode: 'live' } }],
  // Returns a BARE ARRAY, no {status,data} envelope -- handing this one the
  // generic envelope makes ActiveStrategiesCard throw
  // "deployments.filter is not a function", which the ErrorBoundary catches
  // and replaces the entire Dashboard with. Endpoint shapes have to match.
  [
    '/api/v1/deployments',
    [
      {
        id: 1,
        strategy_name: 'EMA Crossover',
        status: 'running',
        symbol: 'RELIANCE',
        exchange: 'NSE',
      },
      {
        id: 2,
        strategy_name: 'Straddle Scalper',
        status: 'waiting',
        symbol: 'BANKNIFTY',
        exchange: 'NFO',
      },
    ],
  ],
  // Also a bare array (listWorkflows returns response.data directly).
  [
    '/flow/api/workflows',
    [
      {
        id: 1,
        name: 'Morning Breakout',
        is_active: true,
        last_run_status: 'completed',
        updated_at: '2026-08-05T04:10:00Z',
      },
      {
        id: 2,
        name: 'Expiry Hedge',
        is_active: false,
        last_run_status: 'pending',
        updated_at: '2026-08-04T11:30:00Z',
      },
    ],
  ],
  [
    '/sandbox/api/configs',
    {
      status: 'success',
      configs: {
        capital: {
          title: 'Capital & Margin',
          configs: {
            starting_capital: {
              value: '10000000',
              description: 'Starting sandbox capital',
              type: 'number',
            },
            reset_day: { value: 'Sunday', description: 'Weekly reset day', type: 'text' },
          },
        },
        leverage: {
          title: 'Leverage',
          configs: {
            equity_mis_leverage: { value: '5', description: 'Equity MIS leverage', type: 'number' },
            futures_leverage: { value: '10', description: 'Futures leverage', type: 'number' },
          },
        },
      },
    },
  ],
  // Nested under `data` -- Profile reads response.data.data.valid_brokers and
  // throws on .map() if the envelope is flat.
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

export async function installStub(page: Page) {
  await page.route('**/*', async (route, request) => {
    const type = request.resourceType()
    // Only XHR/fetch. Routing the document navigation returns JSON for the
    // page itself, and the browser renders that instead of the app.
    if (type !== 'xhr' && type !== 'fetch') return route.continue()

    const url = request.url()
    for (const [needle, body] of ROUTES) {
      if (url.includes(needle)) return route.fulfill(ok(body))
    }
    return route.fulfill(ok({ status: 'success', data: [], message: '' }))
  })
}
