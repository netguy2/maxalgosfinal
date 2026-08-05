import { Search, Sparkles } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Input } from '@/components/ui/input'
import { EQUITY_TEMPLATES, type EquityTemplate } from '@/lib/equityTemplates'
import { cn } from '@/lib/utils'

export interface EquityTemplateGridProps {
  onPick: (tpl: EquityTemplate) => void
}

export function EquityTemplateGrid({ onPick }: EquityTemplateGridProps) {
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return EQUITY_TEMPLATES.filter((t) => !q || t.name.toLowerCase().includes(q))
  }, [query])

  return (
    <div className="space-y-4">
      {/* Section heading */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <div className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-cat-2/15 to-info/15 text-cat-2">
            <Sparkles className="h-3.5 w-3.5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold leading-none">Trade Templates</h3>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {filtered.length} {filtered.length === 1 ? 'template' : 'templates'} · click to
              pre-fill
            </p>
          </div>
        </div>

        {/* Search */}
        <div className="relative sm:max-w-[220px] sm:flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search templates..."
            className="h-8 pl-8 text-xs"
          />
        </div>
      </div>

      {/* Template gallery */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed bg-muted/10 px-6 py-10 text-center">
          <p className="text-xs font-medium">No templates match "{query}"</p>
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
          {filtered.map((tpl) => {
            const Icon = tpl.icon
            return (
              <button
                key={tpl.id}
                type="button"
                onClick={() => onPick(tpl)}
                title={tpl.description}
                className={cn(
                  'group relative flex flex-col gap-2.5 overflow-hidden rounded-xl border bg-card p-3 text-left transition-all',
                  'hover:-translate-y-[1px] hover:border-foreground/30 hover:shadow-md',
                  'focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2'
                )}
              >
                {/* Icon panel */}
                <div
                  className={cn(
                    'flex h-14 w-full items-center justify-center rounded-lg px-2 transition',
                    tpl.side === 'BUY'
                      ? 'bg-gradient-to-br from-profit/10 via-profit/5 to-transparent group-hover:from-profit/15'
                      : 'bg-gradient-to-br from-loss/10 via-loss/5 to-transparent group-hover:from-loss/15'
                  )}
                >
                  <Icon
                    className={cn('h-6 w-6', tpl.side === 'BUY' ? 'text-profit' : 'text-loss')}
                  />
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
                        tpl.side === 'BUY' ? 'bg-profit/10 text-profit' : 'bg-loss/10 text-loss'
                      )}
                    >
                      {tpl.side}
                    </span>
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
