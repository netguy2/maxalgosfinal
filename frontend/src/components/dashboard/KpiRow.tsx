// components/dashboard/KpiRow.tsx
// 4 primary KPI cards (Balance, Today's P&L, Margin Used, Broker Status),
// with an Expand affordance revealing secondary values (Collateral,
// Unrealized P&L, Realized P&L, Master Contract sync status) that used to
// each get their own always-visible card.

import { ChevronDown, Info } from 'lucide-react'
import { useState } from 'react'
import type { MarginData, MasterContractStatus } from '@/api/dashboard'
import { CardContent, CardHeader } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { PremiumCard } from './PremiumCard'

function formatIndianNumber(value: string | number): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (Number.isNaN(num)) return '0.00'
  const isNegative = num < 0
  const absNum = Math.abs(num)
  let formatted: string
  if (absNum >= 10000000) {
    formatted = `${(absNum / 10000000).toFixed(2)}Cr`
  } else if (absNum >= 100000) {
    formatted = `${(absNum / 100000).toFixed(2)}L`
  } else {
    formatted = absNum.toLocaleString('en-IN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  }
  return isNegative ? `-${formatted}` : formatted
}

interface KpiRowProps {
  marginData: MarginData | null
  isLoading: boolean
  isBrokerConnected: boolean
  brokerName: string | null
  brokerSessionValid: boolean
  masterContract: MasterContractStatus
}

export function KpiRow({
  marginData,
  isLoading,
  isBrokerConnected,
  brokerName,
  brokerSessionValid,
  masterContract,
}: KpiRowProps) {
  const [expanded, setExpanded] = useState(false)

  const todaysPnl =
    marginData !== null
      ? parseFloat(marginData.m2munrealized || '0') + parseFloat(marginData.m2mrealized || '0')
      : null

  const marginPct =
    isLoading || !marginData
      ? null
      : (parseFloat(marginData.utiliseddebits) / (parseFloat(marginData.availablecash) || 1)) * 100

  const brokerStatusLabel = !isBrokerConnected
    ? 'Not connected'
    : brokerSessionValid
      ? 'Connected'
      : 'Session expired'

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Available Balance */}
        <PremiumCard className="p-5 gap-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold text-muted-foreground tracking-wider uppercase">
              Balance
            </span>
            <Info className="h-4 w-4 text-muted-foreground/80" />
          </div>
          <p className="text-2xl font-extrabold text-foreground tracking-tight">
            ₹
            {isLoading ? '...' : marginData ? formatIndianNumber(marginData.availablecash) : '0.00'}
          </p>
        </PremiumCard>

        {/* Today's P&L */}
        <PremiumCard className="p-5 gap-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold text-muted-foreground tracking-wider uppercase">
              Today's P&amp;L
            </span>
            <Info className="h-4 w-4 text-muted-foreground/80" />
          </div>
          <p
            className={cn(
              'text-2xl font-extrabold tracking-tight',
              todaysPnl === null
                ? 'text-foreground'
                : todaysPnl > 0
                  ? 'text-profit'
                  : todaysPnl < 0
                    ? 'text-loss'
                    : 'text-foreground'
            )}
          >
            ₹{isLoading ? '...' : todaysPnl !== null ? formatIndianNumber(todaysPnl) : '0.00'}
          </p>
        </PremiumCard>

        {/* Margin Used */}
        <PremiumCard className="p-5 gap-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold text-muted-foreground tracking-wider uppercase">
              Margin Used
            </span>
            <Info className="h-4 w-4 text-muted-foreground/80" />
          </div>
          <p className="text-2xl font-extrabold text-brand tracking-tight">
            ₹
            {isLoading
              ? '...'
              : marginData
                ? formatIndianNumber(marginData.utiliseddebits)
                : '0.00'}
          </p>
          <span className="text-[10px] font-bold text-muted-foreground">
            {marginPct !== null ? `${marginPct.toFixed(2)}% of available` : '—'}
          </span>
        </PremiumCard>

        {/* Broker Status */}
        <PremiumCard className="p-5 gap-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold text-muted-foreground tracking-wider uppercase">
              Broker
            </span>
            <span
              className={cn(
                'h-2 w-2 rounded-full',
                isBrokerConnected && brokerSessionValid
                  ? 'bg-profit'
                  : isBrokerConnected
                    ? 'bg-warning animate-pulse'
                    : 'bg-muted-foreground/40'
              )}
            />
          </div>
          <p className="text-lg font-extrabold text-foreground tracking-tight truncate">
            {brokerName ? brokerName.toUpperCase() : '—'}
          </p>
          <span className="text-[10px] font-bold text-muted-foreground">{brokerStatusLabel}</span>
        </PremiumCard>
      </div>

      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1 text-xs font-semibold text-muted-foreground hover:text-foreground transition-colors"
      >
        <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', expanded && 'rotate-180')} />
        {expanded ? 'Hide details' : 'Show more'}
      </button>

      {expanded && (
        <PremiumCard>
          <CardHeader>
            <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
              Additional details
            </span>
          </CardHeader>
          <CardContent className="grid grid-cols-2 lg:grid-cols-4 gap-4 pb-2">
            <div className="space-y-1">
              <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
                Collateral
              </span>
              <p className="text-lg font-bold text-foreground">
                ₹
                {isLoading
                  ? '...'
                  : marginData
                    ? formatIndianNumber(marginData.collateral)
                    : '0.00'}
              </p>
            </div>
            <div className="space-y-1">
              <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
                Unrealized P&amp;L
              </span>
              <p
                className={cn(
                  'text-lg font-bold',
                  marginData && parseFloat(marginData.m2munrealized) > 0
                    ? 'text-profit'
                    : marginData && parseFloat(marginData.m2munrealized) < 0
                      ? 'text-loss'
                      : 'text-foreground'
                )}
              >
                ₹
                {isLoading
                  ? '...'
                  : marginData
                    ? formatIndianNumber(marginData.m2munrealized)
                    : '0.00'}
              </p>
            </div>
            <div className="space-y-1">
              <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
                Realized P&amp;L (Booked)
              </span>
              <p
                className={cn(
                  'text-lg font-bold',
                  marginData && parseFloat(marginData.m2mrealized) > 0
                    ? 'text-profit'
                    : marginData && parseFloat(marginData.m2mrealized) < 0
                      ? 'text-loss'
                      : 'text-foreground'
                )}
              >
                ₹
                {isLoading
                  ? '...'
                  : marginData
                    ? formatIndianNumber(marginData.m2mrealized)
                    : '0.00'}
              </p>
            </div>
            <div className="space-y-1">
              <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
                Master Contract
              </span>
              <div className="flex items-center gap-1.5">
                <span
                  className={cn(
                    'h-1.5 w-1.5 rounded-full',
                    masterContract.status === 'success' ? 'bg-profit' : 'bg-warning animate-pulse'
                  )}
                />
                <p className="text-sm font-bold text-foreground">
                  {masterContract.status === 'success'
                    ? masterContract.total_symbols
                      ? `Synced (${masterContract.total_symbols})`
                      : 'Synced'
                    : 'Syncing…'}
                </p>
              </div>
            </div>
          </CardContent>
        </PremiumCard>
      )}
    </div>
  )
}
