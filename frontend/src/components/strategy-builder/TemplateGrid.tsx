import { Search, Sparkles } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Input } from '@/components/ui/input'
import { type Direction, STRATEGY_TEMPLATES, type StrategyTemplate } from '@/lib/strategyTemplates'
import { cn } from '@/lib/utils'

export interface TemplateGridProps {
  direction: Direction
  onDirectionChange: (d: Direction) => void
  onPick: (tpl: StrategyTemplate) => void
}

const DIRECTION_FILTERS: Array<{
  value: Direction
  label: string
  dotClass: string
  activeClass: string
}> = [
  {
    value: 'BULLISH',
    label: 'Bullish',
    dotClass: 'bg-profit',
    activeClass: 'border-profit/50 bg-profit/10 text-profit',
  },
  {
    value: 'BEARISH',
    label: 'Bearish',
    dotClass: 'bg-loss',
    activeClass: 'border-loss/50 bg-loss/10 text-loss',
  },
  {
    value: 'NON_DIRECTIONAL',
    label: 'Neutral',
    dotClass: 'bg-warning',
    activeClass: 'border-warning/50 bg-warning/10 text-warning',
  },
]

function MiniPayoffIcon({ path, direction }: { path: string; direction: Direction }) {
  const strokeColor =
    direction === 'BULLISH'
      ? 'stroke-profit'
      : direction === 'BEARISH'
        ? 'stroke-loss'
        : 'stroke-warning'
  return (
    <svg
      viewBox="0 0 100 40"
      className="h-10 w-full"
      fill="none"
      strokeWidth={2.2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* zero line */}
      <line
        x1="0"
        y1="20"
        x2="100"
        y2="20"
        className="stroke-muted-foreground/30"
        strokeWidth="1"
        strokeDasharray="2 2"
      />
      <path d={path} className={strokeColor} />
    </svg>
  )
}

export function TemplateGrid({ direction, onDirectionChange, onPick }: TemplateGridProps) {
  const [query, setQuery] = useState('')

  const counts = useMemo(() => {
    const c: Record<Direction, number> = { BULLISH: 0, BEARISH: 0, NON_DIRECTIONAL: 0 }
    for (const t of STRATEGY_TEMPLATES) c[t.direction]++
    return c
  }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return STRATEGY_TEMPLATES.filter(
      (t) => t.direction === direction && (!q || t.name.toLowerCase().includes(q))
    )
  }, [direction, query])

  return (
    <div className="space-y-4">
      {/* Section heading */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <div className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-violet-500/15 to-blue-500/15 text-violet-600 dark:text-violet-400">
            <Sparkles className="h-3.5 w-3.5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold leading-none">Strategy Library</h3>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {filtered.length} {filtered.length === 1 ? 'template' : 'templates'} · click to
              configure
            </p>
          </div>
        </div>

        {/* Search */}
        <div className="relative sm:max-w-[220px] sm:flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search strategy..."
            className="h-8 pl-8 text-xs"
          />
        </div>
      </div>

      {/* Direction tabs with counts */}
      <div className="flex flex-wrap gap-1.5">
        {DIRECTION_FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => onDirectionChange(f.value)}
            className={cn(
              'group inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition',
              direction === f.value
                ? f.activeClass
                : 'border-border bg-background text-muted-foreground hover:bg-muted'
            )}
          >
            <span className={cn('h-1.5 w-1.5 rounded-full', f.dotClass)} />
            {f.label}
            <span
              className={cn(
                'rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums',
                direction === f.value ? 'bg-background/60' : 'bg-muted text-muted-foreground/80'
              )}
            >
              {counts[f.value]}
            </span>
          </button>
        ))}
      </div>

      {/* Template gallery */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed bg-muted/10 px-6 py-10 text-center">
          <p className="text-xs font-medium">No strategies match "{query}"</p>
          <button
            type="button"
            onClick={() => setQuery('')}
            className="text-[11px] text-primary hover:underline"
          >
            Clear search
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
          {filtered.map((tpl) => (
            <button
              key={tpl.id}
              type="button"
              onClick={() => onPick(tpl)}
              className={cn(
                'group relative flex flex-col gap-2.5 overflow-hidden rounded-xl border bg-card p-3 text-left transition-all',
                'hover:-translate-y-[1px] hover:border-foreground/30 hover:shadow-md',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2'
              )}
            >
              {/* Payoff preview panel */}
              <div
                className={cn(
                  'flex h-14 w-full items-center justify-center rounded-lg px-2 transition',
                  tpl.direction === 'BULLISH' &&
                    'bg-gradient-to-br from-profit/10 via-profit/5 to-transparent group-hover:from-profit/15',
                  tpl.direction === 'BEARISH' &&
                    'bg-gradient-to-br from-loss/10 via-loss/5 to-transparent group-hover:from-loss/15',
                  tpl.direction === 'NON_DIRECTIONAL' &&
                    'bg-gradient-to-br from-warning/10 via-warning/5 to-transparent group-hover:from-warning/15'
                )}
              >
                <MiniPayoffIcon path={tpl.payoffPath} direction={tpl.direction} />
              </div>

              {/* Name + meta */}
              <div className="space-y-1">
                <h4 className="line-clamp-1 text-xs font-semibold leading-tight text-foreground">
                  {tpl.name}
                </h4>
                <div className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      'inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide',
                      tpl.direction === 'BULLISH' &&
                        'bg-profit/10 text-profit',
                      tpl.direction === 'BEARISH' &&
                        'bg-loss/10 text-loss',
                      tpl.direction === 'NON_DIRECTIONAL' &&
                        'bg-warning/10 text-warning'
                    )}
                  >
                    {tpl.legs.length} {tpl.legs.length === 1 ? 'leg' : 'legs'}
                  </span>
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
