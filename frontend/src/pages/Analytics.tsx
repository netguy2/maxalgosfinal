import { useQuery } from '@tanstack/react-query'
import { Activity, Award, RefreshCw, ShieldCheck, TrendingUp, Zap } from 'lucide-react'
import { webClient } from '@/api/client'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { StatCard } from '@/components/ui/stat-card'

interface AnalyticsSummary {
  source: string
  total_pnl: number
  realized_pnl: number
  unrealized_pnl: number
  today_realized_pnl: number
  win_rate: number | null
  sharpe: number | null
  max_drawdown: number | null
  trades_total: number
  trades_today: number
  closed_trades: number
  used_margin: number
  active_deployments: number
  order_latency_ms: number | null
  ws_latency_ms: number | null
  has_data: boolean
}

const inr = (n: number) => `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
const dash = (v: number | null | undefined) => (v == null ? '—' : v)

export default function Analytics() {
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['analytics-summary'],
    queryFn: async () => {
      const res = await webClient.get<{ status: string; data: AnalyticsSummary }>(
        '/analytics_api/summary'
      )
      return res.data.data
    },
    staleTime: 10_000,
  })

  const header = (
    <PageHeader
      title="Performance Analytics"
      description="Real P&L, risk and execution metrics from your Sandbox / Analyzer activity."
      actions={
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw className={`h-4 w-4 mr-2 ${isFetching ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      }
    />
  )

  if (isLoading) {
    return (
      <PageContainer>
        {header}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      </PageContainer>
    )
  }

  if (isError || !data) {
    return (
      <PageContainer>
        {header}
        <EmptyState
          icon={Activity}
          title="Analytics unavailable"
          description="Could not load performance analytics. Please try again."
        />
      </PageContainer>
    )
  }

  if (!data.has_data) {
    return (
      <PageContainer>
        {header}
        <EmptyState
          icon={TrendingUp}
          title="No analytics yet"
          description="Run strategies in Sandbox / Analyzer mode to build up performance history. Metrics like win rate, Sharpe and drawdown appear here once there are trades and daily P&L snapshots."
        />
      </PageContainer>
    )
  }

  const pnlPositive = data.total_pnl >= 0

  return (
    <PageContainer>
      {header}

      <Badge variant="outline" className="text-[10px] uppercase font-bold text-muted-foreground">
        Source: Sandbox / Analyzer
      </Badge>

      {/* Primary KPIs */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={
            <>
              <TrendingUp className={pnlPositive ? 'text-profit' : 'text-loss'} />
              Total P&L
            </>
          }
          value={inr(data.total_pnl)}
          tone={pnlPositive ? 'profit' : 'loss'}
          footer={`${inr(data.today_realized_pnl)} realized today`}
        />

        <StatCard
          label={
            <>
              <Award className="text-warning" />
              Win Rate
            </>
          }
          value={data.win_rate == null ? '—' : `${data.win_rate}%`}
          footer={
            <div className="space-y-2">
              <Progress value={data.win_rate ?? 0} className="h-2" />
              <p>
                Across {data.closed_trades} closed position{data.closed_trades === 1 ? '' : 's'}
              </p>
            </div>
          }
        />

        <StatCard
          label={
            <>
              <ShieldCheck className="text-info" />
              Sharpe Ratio
            </>
          }
          value={dash(data.sharpe)}
          footer={
            data.sharpe == null
              ? 'Needs ≥ 2 days of daily P&L history'
              : 'Annualized, from daily returns'
          }
        />

        <StatCard
          label={
            <>
              <Activity className="text-loss" />
              Max Drawdown
            </>
          }
          value={data.max_drawdown == null ? '—' : `-${data.max_drawdown}%`}
          tone="loss"
          footer={
            <div className="space-y-2">
              <Progress
                value={data.max_drawdown == null ? 0 : 100 - data.max_drawdown}
                className="h-2"
              />
              <p>Peak-to-trough on portfolio value</p>
            </div>
          }
        />
      </div>
      {/* Execution + allocation */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg font-bold flex items-center gap-2">
              <Zap className="h-5 w-5 text-warning" />
              Execution Latency
            </CardTitle>
            <CardDescription>Real order-routing metrics from the latency monitor</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-2">
              <span className="text-sm font-semibold">Avg Order Route Latency</span>
              <span className="font-bold tabular-nums">
                {data.order_latency_ms == null ? '—' : `${data.order_latency_ms} ms`}
              </span>
            </div>
            <div className="flex items-center justify-between pb-2">
              <span className="text-sm font-semibold">Trades Today</span>
              <span className="font-bold tabular-nums">{data.trades_today}</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg font-bold flex items-center gap-2">
              <Activity className="h-5 w-5 text-primary" />
              Portfolio
            </CardTitle>
            <CardDescription>Capital & deployment status</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-2">
              <span className="text-sm font-semibold">Active Deployments</span>
              <span className="font-bold tabular-nums">{data.active_deployments}</span>
            </div>
            <div className="flex items-center justify-between border-b border-border pb-2">
              <span className="text-sm font-semibold">Margin Used</span>
              <span className="font-bold tabular-nums">{inr(data.used_margin)}</span>
            </div>
            <div className="flex items-center justify-between pb-2">
              <span className="text-sm font-semibold">Total Trades</span>
              <span className="font-bold tabular-nums">{data.trades_total}</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  )
}
