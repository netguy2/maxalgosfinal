import { Target as TargetIcon } from 'lucide-react'
import type { StrategyLeg } from '@/lib/strategyMath'
import { cn } from '@/lib/utils'

export interface TradePreviewProps {
  /** The single active equity leg being previewed. Null when none added yet. */
  leg: StrategyLeg | null
  targetPrice?: number
  slPrice?: number
  /** Live price if available, else falls back to the leg's entry price. */
  currentPrice?: number
}

function formatCurrency(v: number | undefined): string {
  if (v === undefined || !Number.isFinite(v)) return '—'
  return `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

interface TileProps {
  label: string
  value: string
  tone?: 'profit' | 'loss' | 'neutral'
  emphasize?: boolean
}

function Tile({ label, value, tone = 'neutral', emphasize = false }: TileProps) {
  return (
    <div
      className={cn(
        'flex flex-col justify-center gap-1 px-3.5 py-2.5',
        emphasize && 'bg-gradient-to-br from-muted/40 to-transparent'
      )}
    >
      <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </dt>
      <dd
        className={cn(
          'font-semibold tabular-nums leading-tight',
          emphasize ? 'text-base' : 'text-sm',
          tone === 'profit' && 'text-profit',
          tone === 'loss' && 'text-loss'
        )}
      >
        {value}
      </dd>
    </div>
  )
}

export function TradePreview({ leg, targetPrice, slPrice, currentPrice }: TradePreviewProps) {
  if (!leg) {
    return (
      <div className="flex h-[300px] items-center justify-center rounded-xl border bg-card p-2 shadow-sm">
        <div className="flex flex-col items-center gap-2 text-center text-sm text-muted-foreground">
          <TargetIcon className="h-6 w-6 opacity-40" />
          Add an equity position to see the trade preview.
        </div>
      </div>
    )
  }

  const entry = leg.price
  const qty = leg.lots * leg.lotSize
  const isBuy = leg.side === 'BUY'
  const current = currentPrice ?? entry

  const riskPerShare = slPrice !== undefined ? Math.abs(entry - slPrice) : undefined
  const rewardPerShare = targetPrice !== undefined ? Math.abs(targetPrice - entry) : undefined
  const rrRatio =
    riskPerShare && riskPerShare > 0 && rewardPerShare !== undefined
      ? rewardPerShare / riskPerShare
      : undefined

  const positionSize = entry * qty
  const expectedPnlAtTarget =
    targetPrice !== undefined ? (isBuy ? 1 : -1) * (targetPrice - entry) * qty : undefined
  const expectedPnlAtSl =
    slPrice !== undefined ? (isBuy ? 1 : -1) * (slPrice - entry) * qty : undefined
  const currentPnl = (isBuy ? 1 : -1) * (current - entry) * qty

  // Bracket meter: position SL / Entry / Target along a horizontal track.
  // Falls back to a plain entry marker when Target/SL aren't set.
  const trackLow = Math.min(slPrice ?? entry, entry, targetPrice ?? entry)
  const trackHigh = Math.max(slPrice ?? entry, entry, targetPrice ?? entry)
  const trackSpan = trackHigh - trackLow || 1
  const pctOf = (v: number) => ((v - trackLow) / trackSpan) * 100

  return (
    <div className="space-y-3 rounded-xl border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold leading-none">{leg.symbol}</h3>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {leg.equityExchange} · {isBuy ? 'Buy' : 'Sell'} · {qty} qty
          </p>
        </div>
        {rrRatio !== undefined && (
          <span
            className={cn(
              'rounded-full px-2.5 py-1 text-[11px] font-bold tabular-nums',
              rrRatio >= 1.5 ? 'bg-profit/10 text-profit' : 'bg-warning/10 text-warning'
            )}
          >
            R:R 1:{rrRatio.toFixed(2)}
          </span>
        )}
      </div>

      {/* Bracket meter */}
      <div className="space-y-2 py-2">
        <div className="relative h-2 rounded-full bg-muted">
          <div
            className="absolute inset-y-0 rounded-full bg-gradient-to-r from-loss/40 via-muted-foreground/20 to-profit/40"
            style={{ left: '0%', right: '0%' }}
          />
          {slPrice !== undefined && (
            <div
              className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background bg-loss shadow"
              style={{ left: `${pctOf(slPrice)}%` }}
              title={`Stop Loss ₹${slPrice.toFixed(2)}`}
            />
          )}
          <div
            className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background bg-foreground shadow"
            style={{ left: `${pctOf(entry)}%` }}
            title={`Entry ₹${entry.toFixed(2)}`}
          />
          {targetPrice !== undefined && (
            <div
              className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background bg-profit shadow"
              style={{ left: `${pctOf(targetPrice)}%` }}
              title={`Target ₹${targetPrice.toFixed(2)}`}
            />
          )}
        </div>
        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span>{slPrice !== undefined ? `SL ₹${slPrice.toFixed(2)}` : 'No SL set'}</span>
          <span className="font-semibold text-foreground">Entry ₹{entry.toFixed(2)}</span>
          <span>
            {targetPrice !== undefined ? `Target ₹${targetPrice.toFixed(2)}` : 'No target set'}
          </span>
        </div>
      </div>

      <dl className="grid grid-cols-2 divide-x divide-y rounded-lg border sm:grid-cols-4 [&>*:nth-child(4n+1)]:sm:border-l-0">
        <Tile label="Entry" value={formatCurrency(entry)} emphasize />
        <Tile
          label="Current P&L"
          value={formatCurrency(currentPnl)}
          tone={currentPnl > 0 ? 'profit' : currentPnl < 0 ? 'loss' : 'neutral'}
          emphasize
        />
        <Tile label="Position Size" value={formatCurrency(positionSize)} />
        <Tile label="R:R" value={rrRatio !== undefined ? `1 : ${rrRatio.toFixed(2)}` : '—'} />
        <Tile
          label="Expected P&L @ Target"
          value={formatCurrency(expectedPnlAtTarget)}
          tone="profit"
        />
        <Tile label="Expected P&L @ SL" value={formatCurrency(expectedPnlAtSl)} tone="loss" />
      </dl>
    </div>
  )
}
