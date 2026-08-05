import { Pause, Radio } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

interface LiveStatusBadgeProps {
  /** Feed is connected and ticking. */
  isLive?: boolean
  /** Updates are deliberately suspended (takes precedence over isLive). */
  isPaused?: boolean
}

/**
 * Live / Paused indicator for the streaming feed, shown beside a page title.
 *
 * Positions, Holdings, OrderBook and TradeBook each carried a byte-identical
 * copy of this badge pair inline. One component keeps the wording, colours
 * and pulse animation in sync when any of them changes.
 *
 * Renders nothing when neither state applies, so callers can pass it
 * unconditionally as `titleAdornment`.
 */
export function LiveStatusBadge({ isLive, isPaused }: LiveStatusBadgeProps) {
  if (isPaused) {
    return (
      <Badge variant="outline" className="bg-warning/10 text-warning border-warning/30 gap-1">
        <Pause className="h-3 w-3" />
        Paused
      </Badge>
    )
  }
  if (isLive) {
    return (
      <Badge variant="outline" className="bg-profit/10 text-profit border-profit/30 gap-1">
        <Radio className="h-3 w-3 animate-pulse" />
        Live
      </Badge>
    )
  }
  return null
}
