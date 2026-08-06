import {
  BarChart3,
  Bell,
  BookOpen,
  Bot,
  ClipboardList,
  Code2,
  FileBarChart,
  FileText,
  FlaskConical,
  Gauge,
  History,
  Layers,
  LayoutDashboard,
  LineChart,
  type LucideIcon,
  Monitor,
  Plug,
  Search,
  Settings,
  Store,
  TrendingUp,
  User,
  Webhook,
  Workflow,
  Wrench,
} from 'lucide-react'

export interface NavItem {
  href: string
  label: string
  icon: LucideIcon
  /** When true, only shown to platform admins. Nav surfaces filter these
   * out for non-admins via filterNavItemsByRole(); the backend still
   * enforces admin access with 403s regardless. */
  adminOnly?: boolean
}

export interface NavSection {
  label: string
  items: NavItem[]
}

/**
 * Single source of truth for app navigation.
 *
 * The desktop sidebar renders navSections directly; every other nav surface
 * (mobile bottom bar, mobile sheet, profile dropdown) derives from the same
 * item objects so links can never drift out of sync again.
 */
export const navSections: NavSection[] = [
  {
    label: 'Trading',
    items: [
      { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
      { href: '/orderbook', label: 'Orderbook', icon: ClipboardList },
      { href: '/tradebook', label: 'Tradebook', icon: FileText },
      { href: '/positions', label: 'Positions', icon: TrendingUp },
      { href: '/action-center', label: 'Control Center', icon: Bell },
    ],
  },
  {
    label: 'Strategies',
    items: [
      { href: '/strategy', label: 'Strategy Library', icon: Code2 },
      { href: '/marketplace', label: 'Marketplace', icon: Store },
      { href: '/deployments', label: 'Live Deployments', icon: Layers },
      { href: '/backtest', label: 'Backtest', icon: History },
      { href: '/analytics', label: 'Analytics', icon: BarChart3 },
    ],
  },
  {
    label: 'Creation & Studio',
    items: [
      { href: '/visual-builder', label: 'Strategy Builder', icon: LineChart },
      { href: '/python', label: 'Python Studio', icon: Code2 },
      { href: '/flow', label: 'Automation Studio', icon: Workflow },
      { href: '/maxhook', label: 'MaxHook', icon: Webhook },
    ],
  },
  {
    label: 'Tools & Data',
    items: [
      { href: '/optionchain', label: 'Options Tools', icon: Wrench },
      { href: '/charts', label: 'Charts', icon: TrendingUp },
      { href: '/pnl-tracker', label: 'PnL Tracker', icon: LineChart },
      { href: '/sandbox', label: 'Sandbox', icon: FlaskConical },
    ],
  },
  {
    label: 'System',
    items: [
      { href: '/broker/manage', label: 'Broker Management', icon: Plug },
      { href: '/logs', label: 'Logs', icon: FileBarChart },
      { href: '/profile', label: 'Settings', icon: Settings },
    ],
  },
]

/** Flat list of every sidebar item (derived — do not hand-edit). */
export const navItems: NavItem[] = navSections.flatMap((section) => section.items)

// Items shown in mobile bottom navigation
export const bottomNavItems: NavItem[] = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/strategy', label: 'Library', icon: Code2 },
  { href: '/marketplace', label: 'Marketplace', icon: Store },
  { href: '/deployments', label: 'Deployments', icon: Layers },
  { href: '/positions', label: 'Positions', icon: TrendingUp },
]

// Paths in bottom nav (for filtering mobile sheet items)
const bottomNavPaths = bottomNavItems.map((item) => item.href)

// Secondary items for mobile sheet (items not in bottom nav)
export const mobileSheetItems = navItems.filter((item) => !bottomNavPaths.includes(item.href))

// Profile dropdown menu items
export const profileMenuItems: NavItem[] = [
  { href: '/profile', label: 'Profile', icon: User },
  { href: '/active-sessions', label: 'Active Sessions', icon: Monitor },
  { href: '/ai-settings', label: 'AI Insight', icon: Bot },
  { href: '/holdings', label: 'Holdings', icon: ClipboardList },
  { href: '/flow', label: 'Automation Studio', icon: Workflow },
  { href: '/python', label: 'Python Strategies', icon: Code2 },
  { href: '/pnl-tracker', label: 'PnL Tracker', icon: BarChart3 },
  { href: '/search/token', label: 'Search', icon: Search },
  { href: '/sandbox', label: 'Sandbox', icon: FlaskConical },
  { href: '/leverage', label: 'Leverage', icon: Gauge },
  { href: '/admin', label: 'Admin', icon: Settings, adminOnly: true },
]

/**
 * Filter a nav item list by the current user's admin role. Non-admins never
 * see items flagged adminOnly. Every nav surface (sidebar, profile dropdown,
 * mobile sheet) should run its items through this so the admin panel link is
 * hidden from regular users.
 */
export function filterNavItemsByRole(items: NavItem[], isAdmin: boolean): NavItem[] {
  return items.filter((item) => !item.adminOnly || isAdmin)
}

// External links
export const externalLinks = {
  docs: { href: 'https://docs.maxalgos.in', label: 'Docs', icon: BookOpen },
}

/**
 * Per-page documentation links, keyed by a stable page id (passed to the
 * shared <DocsLink> component, components/DocsLink.tsx).
 *
 * Every entry here intentionally points at the bare docs.maxalgos.in root,
 * NOT a deep-linked path (e.g. NOT "docs.maxalgos.in/trading-platform/
 * tradingview"). Several pages previously guessed deep-link anchors that
 * have no confirmed match anywhere in this repo's docs/ mirror or any
 * other source -- an unverified guess risks landing users on a 404, which
 * is worse than the root page. Only widen an entry to a deep link once
 * that exact path has been confirmed to resolve on the live site.
 *
 * docs/userguide/README.md (this repo's local content mirror) documents
 * which numbered module covers each topic -- useful for a human to look
 * up the right page manually, but not proof of the live URL scheme, so it
 * is not used to construct hrefs here.
 */
export const DOC_LINKS: Record<string, string> = {
  sandbox: externalLinks.docs.href,
  analyzer: externalLinks.docs.href,
  tradingview: externalLinks.docs.href,
  gocharting: externalLinks.docs.href,
  'python-strategy': externalLinks.docs.href,
  'flow-builder': externalLinks.docs.href,
  'strategy-builder': externalLinks.docs.href,
  'option-chain': externalLinks.docs.href,
  'iv-smile': externalLinks.docs.href,
  'max-pain': externalLinks.docs.href,
  'vol-surface': externalLinks.docs.href,
  gex: externalLinks.docs.href,
  'oi-tracker': externalLinks.docs.href,
  'straddle-chart': externalLinks.docs.href,
  'custom-straddle': externalLinks.docs.href,
  'remote-mcp': externalLinks.docs.href,
}

/**
 * Shared active-route check used by every nav surface.
 *
 * An item is active on an exact match or when the current path is nested
 * under it at a segment boundary (`/strategy/new` activates `/strategy`,
 * but `/strategybuilder` does not).
 */
export function isActiveRoute(pathname: string, href: string): boolean {
  if (href === '/') {
    return pathname === '/'
  }
  return pathname === href || pathname.startsWith(`${href}/`)
}
