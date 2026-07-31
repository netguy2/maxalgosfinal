// components/dashboard/TopMoversLists.tsx
// Two vertical ranked lists (Gainers, Losers) replacing the old single
// horizontal-scroll strip of interleaved mover cards.

import { TrendingDown, TrendingUp } from 'lucide-react'
import type { MarketMover } from '@/api/dashboard'
import { CardContent, CardHeader } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { PremiumCard } from './PremiumCard'

function MoverRow({ mover }: { mover: MarketMover }) {
  const isUp = mover.change_percent >= 0
  return (
    <div className="flex items-center justify-between py-2 border-b border-border/60 last:border-0">
      <span className="text-sm font-bold text-foreground">{mover.symbol}</span>
      <div className="flex items-center gap-3">
        <span className="text-xs font-semibold text-muted-foreground tabular-nums">
          {mover.ltp.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
        </span>
        <span
          className={cn(
            'flex items-center gap-1 text-xs font-bold tabular-nums',
            isUp ? 'text-profit' : 'text-loss'
          )}
        >
          {isUp ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
          {isUp ? '+' : ''}
          {mover.change_percent.toFixed(2)}%
        </span>
      </div>
    </div>
  )
}

function MoverListSkeleton() {
  return (
    <div className="space-y-3 py-1">
      {Array.from({ length: 5 }).map((_, i) => (
        <Skeleton key={i} className="h-5 w-full" />
      ))}
    </div>
  )
}

interface TopMoversListsProps {
  gainers: MarketMover[]
  losers: MarketMover[]
  isLoading: boolean
}

export function TopMoversLists({ gainers, losers, isLoading }: TopMoversListsProps) {
  return (
    <div className="space-y-4">
      <PremiumCard className="p-5 gap-3">
        <CardHeader className="p-0">
          <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
            Top Gainers
          </span>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <MoverListSkeleton />
          ) : gainers.length === 0 ? (
            <p className="text-xs text-muted-foreground py-3">No movers right now</p>
          ) : (
            gainers.map((m) => <MoverRow key={`${m.exchange}:${m.symbol}`} mover={m} />)
          )}
        </CardContent>
      </PremiumCard>

      <PremiumCard className="p-5 gap-3">
        <CardHeader className="p-0">
          <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
            Top Losers
          </span>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <MoverListSkeleton />
          ) : losers.length === 0 ? (
            <p className="text-xs text-muted-foreground py-3">No movers right now</p>
          ) : (
            losers.map((m) => <MoverRow key={`${m.exchange}:${m.symbol}`} mover={m} />)
          )}
        </CardContent>
      </PremiumCard>
    </div>
  )
}
