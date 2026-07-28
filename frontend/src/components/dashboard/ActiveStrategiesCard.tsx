// components/dashboard/ActiveStrategiesCard.tsx
// Glanceable summary of running/waiting deployments with live P&L. Reuses
// GET /api/v1/deployments exactly as pages/Deployments.tsx already polls
// it (same 5s cadence) -- no new backend endpoint. Deliberately does not
// duplicate Deployments.tsx's pause/resume/stop controls; this is a
// summary card, full control lives on the Deployments page.

import { LayoutGrid } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { type DeploymentInstance, dashboardApi } from '@/api/dashboard'
import { CardContent, CardHeader } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { PremiumCard } from './PremiumCard'

function formatIndianNumber(value: number): string {
  if (Number.isNaN(value)) return '0.00'
  const isNegative = value < 0
  const absNum = Math.abs(value)
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

// Same status -> color mapping as pages/Deployments.tsx's getStatusColor,
// kept in sync deliberately so a deployment never looks different colored
// here vs. on its own page.
function getStatusColor(status: string) {
  switch (status.toLowerCase()) {
    case 'running':
    case 'managing':
      return 'bg-profit/10 text-profit border border-profit/20'
    case 'waiting':
      return 'bg-warning/10 text-warning border border-warning/20'
    case 'paused':
      return 'bg-gray-500/10 text-gray-400 border border-gray-500/20'
    case 'stopped':
    case 'cancelled':
      return 'bg-loss/10 text-loss border border-loss/20'
    case 'error':
      return 'bg-loss/10 text-loss border border-loss/20'
    default:
      return 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
  }
}

const ACTIVE_STATUSES = ['running', 'waiting', 'managing', 'entering']

export function ActiveStrategiesCard() {
  const navigate = useNavigate()
  const [deployments, setDeployments] = useState<DeploymentInstance[]>([])
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const fetchDeployments = async () => {
      const data = await dashboardApi.getDeployments()
      if (!cancelled) {
        setDeployments(data)
        setIsLoading(false)
      }
    }
    fetchDeployments()
    const interval = setInterval(fetchDeployments, 5000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  const active = deployments.filter((d) => ACTIVE_STATUSES.includes(d.status.toLowerCase()))

  return (
    <PremiumCard className="p-5 gap-3">
      <CardHeader className="p-0 flex-row items-center justify-between">
        <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
          Active Strategies
        </span>
        <button
          type="button"
          onClick={() => navigate('/deployments')}
          className="text-xs font-bold text-brand hover:underline"
        >
          View all
        </button>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading ? (
          <div className="space-y-3 py-1">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        ) : active.length === 0 ? (
          <EmptyState
            icon={LayoutGrid}
            title="No strategies running"
            description="Deploy a strategy to see it here with live status and P&L."
          />
        ) : (
          <div className="space-y-1">
            {active.map((d) => (
              <button
                type="button"
                key={d.id}
                onClick={() => navigate('/deployments')}
                className="w-full flex items-center justify-between py-2 border-b border-border/60 last:border-0 text-left hover:bg-muted/40 rounded px-1 -mx-1 transition-colors"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-sm font-bold text-foreground truncate">{d.name}</span>
                  <span
                    className={cn(
                      'inline-flex px-1.5 py-0.5 text-[9px] font-black uppercase tracking-wider rounded shrink-0',
                      getStatusColor(d.status)
                    )}
                  >
                    {d.status}
                  </span>
                </div>
                <span
                  className={cn(
                    'text-xs font-bold tabular-nums shrink-0',
                    d.pnl > 0 ? 'text-profit' : d.pnl < 0 ? 'text-loss' : 'text-muted-foreground'
                  )}
                >
                  {d.pnl >= 0 ? '+' : ''}₹{formatIndianNumber(d.pnl)}
                </span>
              </button>
            ))}
          </div>
        )}
      </CardContent>
    </PremiumCard>
  )
}
