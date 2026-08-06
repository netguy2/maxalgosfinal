import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

const PAGE_TITLES: Record<string, string> = {
  '/': 'Home',
  '/faq': 'FAQ',
  '/setup': 'Setup',
  '/login': 'Login',
  '/reset-password': 'Reset Password',
  '/broker': 'Select Broker',
  '/dashboard': 'Dashboard',
  '/positions': 'Positions',
  '/orderbook': 'Order Book',
  '/tradebook': 'Trade Book',
  '/holdings': 'Holdings',
  '/search': 'Search',
  '/search/token': 'Token Search',
  '/apikey': 'API Key',
  '/tradingview': 'TradingView',
  '/gocharting': 'GoCharting',
  '/pnl-tracker': 'P&L Tracker',
  '/sandbox': 'Sandbox',
  '/sandbox/mypnl': 'Sandbox P&L',
  '/analyzer': 'Analyzer',
  '/tools': 'Tools',
  '/strategybuilder': 'Strategy Builder',
  '/strategybuilder/portfolio': 'Strategy Portfolio',
  '/optionchain': 'Option Chain',
  '/ivchart': 'IV Chart',
  '/oitracker': 'OI Tracker',
  '/maxpain': 'Max Pain',
  '/straddle': 'Straddle Chart',
  '/straddlepnl': 'Straddle P&L',
  '/volsurface': 'Vol Surface',
  '/gex': 'GEX Dashboard',
  '/ivsmile': 'IV Smile',
  '/oiprofile': 'OI Profile',
  '/websocket/test': 'WebSocket Test',
  '/strategy': 'Strategies',
  '/strategy/new': 'New Strategy',
  '/python': 'Python Strategies',
  '/python/new': 'New Python Strategy',
  '/python/guide': 'Python Strategy Guide',
  '/maxhook': 'MaxHook',
  '/maxhook/new': 'New Connection',
  '/flow': 'Automation Studio',
  '/flow/shortcuts': 'Automation Studio Shortcuts',
  '/leverage': 'Leverage',
  '/admin': 'Admin',
  '/admin/freeze': 'Freeze Qty',
  '/admin/holidays': 'Holidays',
  '/admin/timings': 'Market Timings',
  '/admin/master-contract': 'Master Contract',
  '/logs': 'Logs',
  '/logs/live': 'Live Logs',
  '/logs/sandbox': 'Sandbox Logs',
  '/logs/security': 'Security',
  '/logs/traffic': 'Traffic',
  '/logs/latency': 'Latency',
  '/health': 'Health Monitor',
  '/profile': 'Profile',
  '/action-center': 'Control Center',
  '/playground': 'Playground',
  '/historify': 'Historify',
  '/historify/charts': 'Historify Charts',
}

/** Dynamic route patterns for parameterized routes */
const DYNAMIC_TITLES: Array<{ pattern: RegExp; title: string }> = [
  { pattern: /^\/strategy\/[^/]+\/configure$/, title: 'Configure Strategy' },
  { pattern: /^\/strategy\/[^/]+$/, title: 'View Strategy' },
  { pattern: /^\/python\/[^/]+\/edit$/, title: 'Edit Strategy' },
  { pattern: /^\/python\/[^/]+\/logs$/, title: 'Strategy Logs' },
  { pattern: /^\/python\/[^/]+\/schedule$/, title: 'Schedule Strategy' },
  { pattern: /^\/maxhook\/[^/]+\/configure$/, title: 'Configure Symbols' },
  { pattern: /^\/maxhook\/[^/]+$/, title: 'View Connection' },
  { pattern: /^\/flow\/editor\/[^/]+$/, title: 'Automation Studio' },
  { pattern: /^\/historify\/charts\/[^/]+$/, title: 'Historify Charts' },
  { pattern: /^\/websocket\/test\/\d+$/, title: 'WebSocket Test' },
]

function getPageTitle(pathname: string): string {
  if (PAGE_TITLES[pathname]) {
    return PAGE_TITLES[pathname]
  }

  for (const { pattern, title } of DYNAMIC_TITLES) {
    if (pattern.test(pathname)) {
      return title
    }
  }

  return 'Max Algos'
}

export function usePageTitle() {
  const { pathname } = useLocation()

  useEffect(() => {
    const title = getPageTitle(pathname)
    document.title = title === 'Max Algos' ? 'Max Algos' : `${title} | Max Algos`
  }, [pathname])
}
