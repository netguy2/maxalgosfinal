import { Link, useLocation } from 'react-router-dom'
import { cn } from '@/lib/utils'

/**
 * In-page switcher for the Options Tools suite.
 *
 * Rendered above every tool page (wired at the route level in App.tsx) so
 * users can hop between tools without going back to a hub page. Option Chain
 * is the suite's home — /tools redirects there.
 */
const OPTIONS_TOOLS = [
  { href: '/optionchain', label: 'Option Chain' },
  { href: '/ivchart', label: 'Greeks' },
  { href: '/oitracker', label: 'OI Tracker' },
  { href: '/maxpain', label: 'Max Pain' },
  { href: '/straddle', label: 'Straddle' },
  { href: '/straddlepnl', label: 'Straddle PnL' },
  { href: '/volsurface', label: 'Vol Surface' },
  { href: '/gex', label: 'GEX' },
  { href: '/ivsmile', label: 'IV Smile' },
  { href: '/oiprofile', label: 'OI Profile' },
  { href: '/camarilla', label: 'Camarilla' },
]

export function ToolsSwitcher() {
  const location = useLocation()

  return (
    <nav aria-label="Options tools" className="mb-4 -mx-1 overflow-x-auto scrollbar-thin">
      <div className="flex items-center gap-1 px-1 py-1 min-w-max border-b border-border">
        {OPTIONS_TOOLS.map((tool) => {
          const active =
            location.pathname === tool.href || location.pathname.startsWith(`${tool.href}/`)
          return (
            <Link
              key={tool.href}
              to={tool.href}
              className={cn(
                'whitespace-nowrap rounded-t-md px-3 py-1.5 text-xs font-semibold transition-colors border-b-2 -mb-px',
                active
                  ? 'border-primary text-primary bg-primary/5'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-accent'
              )}
            >
              {tool.label}
            </Link>
          )
        })}
      </div>
    </nav>
  )
}
