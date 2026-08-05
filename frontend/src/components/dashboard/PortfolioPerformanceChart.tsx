// components/dashboard/PortfolioPerformanceChart.tsx
// P&L sparkline with a proper 3-way empty state instead of always showing
// a ₹0 chart: no broker connected / broker connected but genuinely zero
// balance (never funded/traded) / broker connected with a real balance
// but today's samples are still accumulating.

import { BarChart3, LineChart, Trophy, Wallet } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { MarginData, PnlSnapshotEntry } from '@/api/dashboard'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
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

function formatActivityTime(ts: string | null): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true })
}

interface PortfolioPerformanceChartProps {
  pnlHistory: PnlSnapshotEntry[]
  marginData: MarginData | null
  isBrokerConnected: boolean
}

export function PortfolioPerformanceChart({
  pnlHistory,
  marginData,
  isBrokerConnected,
}: PortfolioPerformanceChartProps) {
  const navigate = useNavigate()

  const latestPnl = pnlHistory.length > 0 ? pnlHistory[pnlHistory.length - 1] : null
  const totalPnl = latestPnl
    ? parseFloat(latestPnl.m2munrealized || '0') + parseFloat(latestPnl.m2mrealized || '0')
    : null
  const firstPnl =
    pnlHistory.length > 0
      ? parseFloat(pnlHistory[0].m2munrealized || '0') +
        parseFloat(pnlHistory[0].m2mrealized || '0')
      : 0
  const pnlPct =
    totalPnl !== null && firstPnl !== 0 ? ((totalPnl - firstPnl) / Math.abs(firstPnl)) * 100 : 0
  const winningCount = pnlHistory.filter((p) => parseFloat(p.m2mrealized || '0') > 0).length
  const losingCount = pnlHistory.filter((p) => parseFloat(p.m2mrealized || '0') < 0).length

  const pnlSparklinePath = (() => {
    if (pnlHistory.length < 2) return 'M 0 25 L 100 25'
    const values = pnlHistory.map(
      (p) => parseFloat(p.m2munrealized || '0') + parseFloat(p.m2mrealized || '0')
    )
    const min = Math.min(...values)
    const max = Math.max(...values)
    const range = max - min || 1
    const step = 100 / (values.length - 1)
    return values
      .map((v, i) => {
        const x = i * step
        const y = 35 - ((v - min) / range) * 30
        return `${i === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`
      })
      .join(' ')
  })()

  const hasBalance = marginData !== null && parseFloat(marginData.availablecash || '0') > 0

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-bold text-foreground tracking-wide">Portfolio Performance</h3>
        <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
          Today
        </span>
      </div>

      <PremiumCard className="p-5 min-h-[320px] justify-between">
        {!isBrokerConnected ? (
          <EmptyState
            icon={LineChart}
            title="Connect a broker to start tracking P&L"
            description="Once connected, your live portfolio performance will show up here."
            action={
              <Button size="sm" className="mt-3" onClick={() => navigate('/broker')}>
                Connect Broker
              </Button>
            }
          />
        ) : !hasBalance ? (
          <EmptyState
            icon={Wallet}
            title="No portfolio activity yet"
            description="Fund your account and place your first trade to see performance here."
          />
        ) : (
          <>
            <div>
              <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
                P&amp;L
              </span>
              <div className="flex items-baseline gap-2 mt-1">
                <span
                  className={cn(
                    'text-2xl font-black',
                    totalPnl === null
                      ? 'text-foreground'
                      : totalPnl > 0
                        ? 'text-profit'
                        : totalPnl < 0
                          ? 'text-loss'
                          : 'text-foreground'
                  )}
                >
                  ₹{totalPnl !== null ? formatIndianNumber(totalPnl) : '0.00'}
                </span>
                <span
                  className={cn(
                    'text-xs font-bold',
                    pnlPct > 0 ? 'text-profit' : pnlPct < 0 ? 'text-loss' : 'text-muted-foreground'
                  )}
                >
                  {pnlPct >= 0 ? '+' : ''}
                  {pnlPct.toFixed(2)}%
                </span>
              </div>
            </div>

            <div className="my-6 h-36 w-full text-brand/20 relative">
              {pnlHistory.length >= 2 ? (
                <svg className="w-full h-full" viewBox="0 0 100 40" preserveAspectRatio="none">
                  <defs>
                    <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--brand)" stopOpacity="0.15" />
                      <stop offset="100%" stopColor="var(--brand)" stopOpacity="0" />
                    </linearGradient>
                  </defs>
                  <line
                    x1="0"
                    y1="25"
                    x2="100"
                    y2="25"
                    stroke="var(--border)"
                    strokeWidth="0.5"
                    strokeDasharray="2,2"
                  />
                  <path d={`${pnlSparklinePath} L 100 40 L 0 40 Z`} fill="url(#chartGrad)" />
                  <path
                    d={pnlSparklinePath}
                    fill="none"
                    stroke="var(--brand)"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                  />
                </svg>
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <p className="text-xs text-muted-foreground font-medium">
                    Collecting today's P&amp;L samples…
                  </p>
                </div>
              )}
              {pnlHistory.length >= 2 && (
                <div className="flex justify-between text-[9px] text-muted-foreground font-semibold mt-2 select-none">
                  <span>{formatActivityTime(pnlHistory[0].timestamp)}</span>
                  <span>{formatActivityTime(pnlHistory[pnlHistory.length - 1].timestamp)}</span>
                </div>
              )}
            </div>

            <div className="grid grid-cols-3 gap-2 border-t border-border pt-4">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded bg-warning/10 text-warning">
                  <Trophy className="h-4 w-4" />
                </div>
                <div className="flex flex-col leading-tight">
                  <span className="text-[10px] text-muted-foreground font-medium">Winning</span>
                  <span className="text-xs font-extrabold text-foreground">{winningCount}</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded bg-loss/10 text-loss">
                  <BarChart3 className="h-4 w-4" />
                </div>
                <div className="flex flex-col leading-tight">
                  <span className="text-[10px] text-muted-foreground font-medium">Losing</span>
                  <span className="text-xs font-extrabold text-foreground">{losingCount}</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded bg-info/10 text-info">
                  <BarChart3 className="h-4 w-4" />
                </div>
                <div className="flex flex-col leading-tight">
                  <span className="text-[10px] text-muted-foreground font-medium">Total</span>
                  <span className="text-xs font-extrabold text-foreground">
                    {pnlHistory.length}
                  </span>
                </div>
              </div>
            </div>
          </>
        )}
      </PremiumCard>
    </div>
  )
}
