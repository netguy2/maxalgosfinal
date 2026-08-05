import type { ReactNode } from 'react'
import { Card, CardContent, CardDescription, CardHeader } from '@/components/ui/card'
import { cn } from '@/lib/utils'

/**
 * Semantic tone for the value. Keeps P&L colouring consistent instead of each
 * call site reaching for `text-profit`/`text-loss` directly (and occasionally
 * disagreeing about which shade).
 */
type StatTone = 'default' | 'profit' | 'loss' | 'primary' | 'muted'

const TONE_CLASS: Record<StatTone, string> = {
  default: 'text-foreground',
  profit: 'text-profit',
  loss: 'text-loss',
  primary: 'text-primary',
  muted: 'text-muted-foreground',
}

interface StatCardProps {
  /** Short label above the value, e.g. "Open Positions". */
  label: ReactNode
  /** The figure itself. */
  value: ReactNode
  /** Icon rendered before the value; sized by the card. */
  icon?: ReactNode
  tone?: StatTone
  /** Supporting line under the value (context, comparison, progress). */
  footer?: ReactNode
  className?: string
}

/**
 * A single figure in a stats row (Open Positions, Buy Orders, Win Rate...).
 *
 * Positions, OrderBook, TradeBook, Holdings and Analytics each rebuilt this
 * from Card + CardHeader + CardDescription + a `text-2xl` CardTitle. They
 * drifted: some labels were plain, others uppercase-bold; values were
 * text-2xl in some places and text-2xl font-black elsewhere; only some used
 * tabular figures, so digits jittered as live numbers ticked.
 *
 * `tabular-nums` is not cosmetic here -- these values update on every tick,
 * and proportional digits make the whole row shift width as they change.
 */
export function StatCard({
  label,
  value,
  icon,
  tone = 'default',
  footer,
  className,
}: StatCardProps) {
  return (
    <Card className={cn('gap-0 py-4', className)}>
      <CardHeader className="gap-1 px-4">
        <CardDescription className="flex items-center gap-1.5 text-xs font-medium">
          {label}
        </CardDescription>
        <div
          className={cn(
            'flex items-center gap-2 text-2xl leading-tight font-bold tabular-nums',
            TONE_CLASS[tone]
          )}
        >
          {icon && <span className="[&>svg]:size-5 shrink-0">{icon}</span>}
          {value}
        </div>
      </CardHeader>
      {footer && (
        <CardContent className="px-4 pt-2">
          <div className="text-muted-foreground text-xs">{footer}</div>
        </CardContent>
      )}
    </Card>
  )
}
