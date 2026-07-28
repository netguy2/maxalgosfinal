/**
 * Route chunk prefetching.
 *
 * All pages are lazy-loaded; navigating to a cold route shows the full-page
 * loader while its chunk downloads. Hovering a nav item is a strong signal of
 * intent, so we start the dynamic import then — Vite resolves these to the
 * same chunks as the lazy() calls in App.tsx, and the browser caches them.
 */

const prefetchers: Record<string, () => Promise<unknown>> = {
  '/dashboard': () => import('@/pages/Dashboard'),
  '/orderbook': () => import('@/pages/OrderBook'),
  '/tradebook': () => import('@/pages/TradeBook'),
  '/positions': () => import('@/pages/Positions'),
  '/action-center': () => import('@/pages/ActionCenter'),
  '/strategy': () => import('@/pages/strategy/StrategyIndex'),
  '/strategy/wizard': () => import('@/pages/strategy/StrategyWizard'),
  '/strategy/backtests': () => import('@/pages/strategy/BacktestLogs'),
  '/tools/webhooks': () => import('@/pages/tools/WebhooksGuide'),
  '/visual-builder': () => import('@/pages/StrategyBuilder'),
  '/marketplace': () => import('@/pages/Marketplace'),
  '/deployments': () => import('@/pages/Deployments'),
  '/analytics': () => import('@/pages/Analytics'),
  '/python': () => import('@/pages/python-strategy/PythonStrategyIndex'),
  '/flow': () => import('@/pages/flow/FlowIndex'),
  '/maxhook': () => import('@/pages/maxhook/MaxHookIndex'),
  '/tools': () => import('@/pages/OptionChain'),
  '/optionchain': () => import('@/pages/OptionChain'),
  '/pnl-tracker': () => import('@/pages/PnLTracker'),
  '/historify': () => import('@/pages/Historify'),
  '/sandbox': () => import('@/pages/Sandbox'),
  '/broker/manage': () => import('@/pages/BrokerManage'),
  '/logs': () => import('@/pages/LogsIndex'),
  '/profile': () => import('@/pages/Profile'),
}

const prefetched = new Set<string>()

/** Kick off the chunk download for a route. Safe to call repeatedly. */
export function prefetchRoute(href: string): void {
  if (prefetched.has(href)) return
  const loader = prefetchers[href]
  if (!loader) return
  prefetched.add(href)
  // Fire and forget — a failed prefetch just falls back to load-on-navigate.
  loader().catch(() => {
    prefetched.delete(href)
  })
}
