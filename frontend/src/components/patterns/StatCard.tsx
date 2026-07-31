import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'

interface StatCardProps {
  label: string
  value: ReactNode
  /** Signed delta — rendered in profit/loss color automatically. */
  delta?: number
  /** Preformatted delta text; defaults to the signed number. */
  deltaLabel?: string
  icon?: LucideIcon
  /** Optional slot below the value (sparkline, sub-text). */
  footer?: ReactNode
  className?: string
}

/**
 * Dense stat tile used across dashboard / tools pages.
 * Numbers render with tabular figures; deltas use semantic P&L tokens.
 */
export function StatCard({
  label,
  value,
  delta,
  deltaLabel,
  icon: Icon,
  footer,
  className,
}: StatCardProps) {
  const showDelta = typeof delta === 'number' && !Number.isNaN(delta)
  return (
    <Card className={cn('py-4', className)}>
      <CardContent className="px-4">
        <div className="flex items-start justify-between gap-2">
          <p className="text-xs font-medium text-muted-foreground truncate">{label}</p>
          {Icon && <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />}
        </div>
        <div className="mt-1.5 flex items-baseline gap-2">
          <span className="text-xl font-bold tabular-nums text-foreground">{value}</span>
          {showDelta && (
            <span
              className={cn(
                'text-xs font-semibold tabular-nums',
                delta > 0 ? 'text-profit' : delta < 0 ? 'text-loss' : 'text-muted-foreground'
              )}
            >
              {deltaLabel ?? `${delta > 0 ? '+' : ''}${delta}`}
            </span>
          )}
        </div>
        {footer && <div className="mt-2">{footer}</div>}
      </CardContent>
    </Card>
  )
}
