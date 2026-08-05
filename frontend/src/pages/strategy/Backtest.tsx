import { BarChart3, History, Play, RefreshCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { strategyApi } from '@/api/strategy'
import { PageContainer } from '@/components/layout/PageContainer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { SYMBOL_OPTIONS } from '@/lib/symbol-options'
import type { Strategy } from '@/types/strategy'
import { showToast } from '@/utils/toast'

interface BacktestTradeItem {
  id: number
  symbol: string
  action: string
  quantity: number
  entry_price: number
  exit_price: number
  pnl: number
  entry_time: string
  exit_time: string
}

interface EquityPoint {
  time: string
  equity: number
}

interface BacktestResult {
  id: number
  strategy_id: number
  strategy_name?: string
  symbol: string
  timeframe: string
  status: string
  error_message?: string | null
  start_date: string
  end_date: string
  capital: number
  win_rate: number
  returns: number
  max_drawdown_pct?: number | null
  sharpe_ratio?: number | null
  total_return_pct?: number | null
  final_equity?: number | null
  total_trades?: number
  equity_curve?: EquityPoint[]
  created_at: string
  trades?: BacktestTradeItem[]
}

const IN_FLIGHT_STATUSES = new Set(['Pending', 'Running'])

export default function Backtest() {
  const [searchParams] = useSearchParams()
  const preselectedStrategyId = searchParams.get('strategy') || ''

  const [viewTab, setViewTab] = useState<'run' | 'history'>('run')

  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [loadingStrategies, setLoadingStrategies] = useState(true)

  const [selectedStrategyId, setSelectedStrategyId] = useState<string>('')
  const [availableSymbols, setAvailableSymbols] = useState<string[]>(
    SYMBOL_OPTIONS.map((s) => s.value)
  )

  const [params, setParams] = useState({
    symbol: 'NIFTY',
    timeframe: '15m',
    start_date: '2026-01-01',
    end_date: '2026-03-31',
    capital: '100000',
  })
  const [launching, setLaunching] = useState(false)

  // Strategy-specific & Global results
  const [results, setResults] = useState<BacktestResult[]>([])
  const [allHistory, setAllHistory] = useState<BacktestResult[]>([])
  const [loadingResults, setLoadingResults] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [selectedRun, setSelectedRun] = useState<BacktestResult | null>(null)

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchStrategies = async () => {
    try {
      setLoadingStrategies(true)
      const all = await strategyApi.getStrategies()
      setStrategies(all.filter((s) => s.lifecycle_state !== 'Archived'))
    } catch {
      showToast.error('Failed to load strategies', 'strategy')
    } finally {
      setLoadingStrategies(false)
    }
  }

  const fetchAllHistory = async () => {
    try {
      setLoadingHistory(true)
      const res = (await strategyApi.getAllBacktests()) as {
        status: string
        backtests?: BacktestResult[]
      }
      if (res.status === 'success' && res.backtests) {
        setAllHistory(res.backtests)
      }
    } catch {
      /* ignore */
    } finally {
      setLoadingHistory(false)
    }
  }

  useEffect(() => {
    fetchStrategies()
    fetchAllHistory()
  }, [fetchAllHistory, fetchStrategies])

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const fetchResultsFor = async (strategyId: number): Promise<BacktestResult[]> => {
    const data = (await strategyApi.getBacktests(strategyId)) as {
      status: string
      backtests?: BacktestResult[]
    }
    return data.status === 'success' && data.backtests ? data.backtests : []
  }

  const handleSelectStrategy = async (value: string) => {
    setSelectedStrategyId(value)
    setResults([])
    setSelectedRun(null)
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    if (!value) return

    const strategyId = Number(value)
    try {
      setLoadingResults(true)
      const [{ mappings }, existing] = await Promise.all([
        strategyApi.getStrategy(strategyId),
        fetchResultsFor(strategyId),
      ])
      setResults(existing)
      if (existing.length > 0) {
        setSelectedRun(existing[0])
      }

      // Filter invalid non-symbol strings like 'BUY', 'SELL', 'LONG', 'SHORT', 'BOTH'
      const invalidTokens = new Set(['BUY', 'SELL', 'LONG', 'SHORT', 'BOTH', 'ORDER', 'NONE'])
      const validFromMappings = (mappings || [])
        .map((m) => m.symbol?.toUpperCase())
        .filter((s): s is string => Boolean(s) && !invalidTokens.has(s))

      const defaultSymbolList = SYMBOL_OPTIONS.map((s) => s.value)
      const uniqueSymbols = Array.from(new Set([...validFromMappings, ...defaultSymbolList]))
      setAvailableSymbols(uniqueSymbols)

      const chosenSymbol = validFromMappings[0] || 'NIFTY'
      setParams((prev) => ({ ...prev, symbol: chosenSymbol }))
    } catch {
      showToast.error('Failed to load strategy details', 'strategy')
    } finally {
      setLoadingResults(false)
    }
  }

  useEffect(() => {
    if (
      !loadingStrategies &&
      preselectedStrategyId &&
      strategies.some((s) => String(s.id) === preselectedStrategyId)
    ) {
      handleSelectStrategy(preselectedStrategyId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadingStrategies, preselectedStrategyId, handleSelectStrategy, strategies.some])

  const pollForCompletion = (strategyId: number) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const latest = await fetchResultsFor(strategyId)
        setResults(latest)
        if (latest.length > 0) {
          setSelectedRun(latest[0])
        }
        fetchAllHistory()
        const stillRunning = latest.some((r) => IN_FLIGHT_STATUSES.has(r.status))
        if (!stillRunning && pollRef.current) {
          clearInterval(pollRef.current)
          pollRef.current = null
        }
      } catch {
        if (pollRef.current) {
          clearInterval(pollRef.current)
          pollRef.current = null
        }
      }
    }, 3000)
  }

  const handleRun = async () => {
    if (!selectedStrategyId) return
    const strategyId = Number(selectedStrategyId)
    try {
      setLaunching(true)
      const data = await strategyApi.runBacktest(strategyId, params)
      if (data.status === 'pending') {
        showToast.success(
          data.message || 'Backtest started -- results will appear below.',
          'strategy'
        )
        const updated = await fetchResultsFor(strategyId)
        setResults(updated)
        if (updated.length > 0) setSelectedRun(updated[0])
        pollForCompletion(strategyId)
      } else if (data.status === 'success') {
        showToast.success('Backtest completed.', 'strategy')
        const updated = await fetchResultsFor(strategyId)
        setResults(updated)
        if (updated.length > 0) setSelectedRun(updated[0])
      } else {
        showToast.error(data.message || 'Backtest failed to start', 'strategy')
      }
    } catch (err: any) {
      const serverMsg = err?.response?.data?.message || err?.message || 'Failed to launch backtest'
      showToast.error(serverMsg, 'strategy')
    } finally {
      setLaunching(false)
    }
  }

  const selectedStrategy = strategies.find((s) => s.id === Number(selectedStrategyId))

  // Render SVG Equity Curve Chart
  const renderEquityCurve = (run: BacktestResult) => {
    const points = run.equity_curve || []
    if (points.length < 2) {
      return (
        <div className="h-40 flex items-center justify-center text-xs text-muted-foreground border border-dashed rounded-lg">
          Not enough equity data to generate chart.
        </div>
      )
    }

    const values = points.map((p) => p.equity)
    const minVal = Math.min(...values)
    const maxVal = Math.max(...values)
    const range = maxVal - minVal || 1

    const width = 600
    const height = 160
    const padding = 20

    const svgPoints = points
      .map((p, i) => {
        const x = padding + (i / (points.length - 1)) * (width - 2 * padding)
        const y = height - padding - ((p.equity - minVal) / range) * (height - 2 * padding)
        return `${x},${y}`
      })
      .join(' ')

    const isPositive = (run.total_return_pct ?? run.returns) >= 0
    const strokeColor = isPositive ? '#10b981' : '#ef4444'

    const firstPt = points[0]
    const lastPt = points[points.length - 1]
    const closedArea = `${padding},${height - padding} ${svgPoints} ${width - padding},${height - padding}`

    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs text-muted-foreground px-1">
          <span>Start: ₹{firstPt.equity.toLocaleString()}</span>
          <span className={isPositive ? 'text-profit font-bold' : 'text-loss font-bold'}>
            Final Equity: ₹{lastPt.equity.toLocaleString()} (
            {run.total_return_pct != null
              ? `${run.total_return_pct > 0 ? '+' : ''}${run.total_return_pct}%`
              : `${run.returns > 0 ? '+' : ''}₹${run.returns}`}
            )
          </span>
        </div>
        <div className="w-full overflow-hidden rounded-lg bg-card/60 border border-border p-2">
          <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-40 overflow-visible">
            <defs>
              <linearGradient id={`grad-${run.id}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={strokeColor} stopOpacity="0.25" />
                <stop offset="100%" stopColor={strokeColor} stopOpacity="0.0" />
              </linearGradient>
            </defs>
            {/* Grid lines */}
            <line
              x1={padding}
              y1={padding}
              x2={width - padding}
              y2={padding}
              stroke="currentColor"
              className="text-border"
              strokeDasharray="4,4"
            />
            <line
              x1={padding}
              y1={height / 2}
              x2={width - padding}
              y2={height / 2}
              stroke="currentColor"
              className="text-border"
              strokeDasharray="4,4"
            />
            <line
              x1={padding}
              y1={height - padding}
              x2={width - padding}
              y2={height - padding}
              stroke="currentColor"
              className="text-border"
            />
            {/* Area Fill */}
            <polygon points={closedArea} fill={`url(#grad-${run.id})`} />
            {/* Line Path */}
            <polyline
              fill="none"
              stroke={strokeColor}
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              points={svgPoints}
            />
          </svg>
        </div>
      </div>
    )
  }

  // Render Detailed Run Dashboard
  const renderRunDashboard = (run: BacktestResult) => {
    const trades = run.trades || []
    const winTrades = trades.filter((t) => (t.pnl || 0) > 0)
    const lossTrades = trades.filter((t) => (t.pnl || 0) <= 0)
    const totalWinPnl = winTrades.reduce((acc, t) => acc + (t.pnl || 0), 0)
    const totalLossPnl = Math.abs(lossTrades.reduce((acc, t) => acc + (t.pnl || 0), 0))
    const profitFactor =
      totalLossPnl > 0 ? (totalWinPnl / totalLossPnl).toFixed(2) : totalWinPnl > 0 ? '∞' : '0.00'
    const avgWin = winTrades.length > 0 ? totalWinPnl / winTrades.length : 0
    const avgLoss = lossTrades.length > 0 ? totalLossPnl / lossTrades.length : 0

    return (
      <div className="space-y-6 pt-2">
        {/* Metric Cards Row */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="p-3 rounded-lg border border-border bg-card">
            <span className="text-[11px] font-semibold text-muted-foreground block mb-1">
              Net Returns
            </span>
            <span
              className={`text-lg font-bold tabular-nums ${
                run.returns >= 0 ? 'text-profit' : 'text-loss'
              }`}
            >
              {run.returns >= 0 ? '+' : ''}₹{run.returns.toLocaleString()}
            </span>
            {run.total_return_pct != null && (
              <span className="text-xs text-muted-foreground block mt-0.5 font-medium">
                {run.total_return_pct >= 0 ? '+' : ''}
                {run.total_return_pct}% return
              </span>
            )}
          </div>

          <div className="p-3 rounded-lg border border-border bg-card">
            <span className="text-[11px] font-semibold text-muted-foreground block mb-1">
              Win Rate
            </span>
            <span className="text-lg font-bold text-profit tabular-nums">{run.win_rate}%</span>
            <span className="text-xs text-muted-foreground block mt-0.5">
              {winTrades.length} win / {lossTrades.length} loss
            </span>
          </div>

          <div className="p-3 rounded-lg border border-border bg-card">
            <span className="text-[11px] font-semibold text-muted-foreground block mb-1">
              Max Drawdown
            </span>
            <span className="text-lg font-bold text-loss tabular-nums">
              {run.max_drawdown_pct != null ? `${run.max_drawdown_pct}%` : 'N/A'}
            </span>
            <span className="text-xs text-muted-foreground block mt-0.5">Peak-to-trough</span>
          </div>

          <div className="p-3 rounded-lg border border-border bg-card">
            <span className="text-[11px] font-semibold text-muted-foreground block mb-1">
              Sharpe Ratio / PF
            </span>
            <span className="text-lg font-bold tabular-nums text-foreground">
              {run.sharpe_ratio ?? 'N/A'}{' '}
              <span className="text-xs font-normal text-muted-foreground">(PF {profitFactor})</span>
            </span>
            <span className="text-xs text-muted-foreground block mt-0.5">
              Avg Win ₹{Math.round(avgWin)} / Loss ₹{Math.round(avgLoss)}
            </span>
          </div>
        </div>

        {/* Equity Curve Graph */}
        <Card className="border border-border">
          <CardHeader className="py-3 px-4 flex flex-row items-center justify-between">
            <CardTitle className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <BarChart3 className="h-4 w-4 text-primary" />
              Equity Curve (P&L Replay)
            </CardTitle>
            <Badge variant="outline" className="text-[10px]">
              {run.symbol} • {run.timeframe}
            </Badge>
          </CardHeader>
          <CardContent className="px-4 pb-4">{renderEquityCurve(run)}</CardContent>
        </Card>

        {/* Trades Log */}
        <Card className="border border-border">
          <CardHeader className="py-3 px-4 flex flex-row items-center justify-between">
            <CardTitle className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Trade Execution Log ({trades.length} trades)
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0 overflow-x-auto">
            {trades.length === 0 ? (
              <p className="p-4 text-xs text-muted-foreground text-center">
                No trades were triggered during this backtest window.
              </p>
            ) : (
              <table className="w-full text-xs text-left border-collapse">
                <thead className="bg-muted/40 border-b border-border text-muted-foreground font-semibold">
                  <tr>
                    <th className="p-3">Trade #</th>
                    <th className="p-3">Action</th>
                    <th className="p-3">Entry Time</th>
                    <th className="p-3">Entry Price</th>
                    <th className="p-3">Exit Time</th>
                    <th className="p-3">Exit Price</th>
                    <th className="p-3 text-right">P&L (₹)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {trades.map((t, idx) => {
                    const isWin = (t.pnl || 0) > 0
                    return (
                      <tr key={t.id || idx} className="hover:bg-muted/20">
                        <td className="p-3 font-semibold text-muted-foreground">#{idx + 1}</td>
                        <td className="p-3 font-bold text-primary">{t.action}</td>
                        <td className="p-3 text-muted-foreground">{t.entry_time}</td>
                        <td className="p-3 font-mono">₹{t.entry_price}</td>
                        <td className="p-3 text-muted-foreground">{t.exit_time}</td>
                        <td className="p-3 font-mono">₹{t.exit_price}</td>
                        <td
                          className={`p-3 text-right font-bold tabular-nums ${
                            isWin ? 'text-profit' : 'text-loss'
                          }`}
                        >
                          {isWin ? '+' : ''}₹{t.pnl.toLocaleString()}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <PageContainer>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-primary/10 text-primary border border-primary/20">
            <History className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Institutional Backtesting Engine</h1>
            <p className="text-muted-foreground text-xs sm:text-sm">
              Event-driven bar-by-bar historical replay over live condition trees.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant={viewTab === 'run' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setViewTab('run')}
          >
            Run New Backtest
          </Button>
          <Button
            variant={viewTab === 'history' ? 'default' : 'outline'}
            size="sm"
            onClick={() => {
              setViewTab('history')
              fetchAllHistory()
            }}
          >
            <History className="h-4 w-4 mr-1.5" />
            Backtest History ({allHistory.length})
          </Button>
        </div>
      </div>

      {viewTab === 'run' ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Choose a strategy to backtest</CardTitle>
              <CardDescription>
                Select any saved strategy. Entry conditions will be replayed event-driven across
                historical OHLCV data.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {loadingStrategies ? (
                <Skeleton className="h-10 w-full max-w-sm" />
              ) : strategies.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No strategies yet.{' '}
                  <Link to="/strategy/new" className="underline">
                    Create one
                  </Link>{' '}
                  to run a backtest.
                </p>
              ) : (
                <Select value={selectedStrategyId} onValueChange={handleSelectStrategy}>
                  <SelectTrigger className="max-w-md">
                    <SelectValue placeholder="Select a strategy..." />
                  </SelectTrigger>
                  <SelectContent>
                    {strategies.map((s) => (
                      <SelectItem key={s.id} value={String(s.id)}>
                        {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}

              {selectedStrategy && (
                <div className="space-y-4 border-t pt-4">
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label>Symbol</Label>
                      <Select
                        value={params.symbol}
                        onValueChange={(val) => setParams((p) => ({ ...p, symbol: val }))}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {availableSymbols.map((sym) => (
                            <SelectItem key={sym} value={sym}>
                              {sym}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label>Timeframe</Label>
                      <Select
                        value={params.timeframe}
                        onValueChange={(val) => setParams((p) => ({ ...p, timeframe: val }))}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="5m">5 Minutes (5m)</SelectItem>
                          <SelectItem value="15m">15 Minutes (15m)</SelectItem>
                          <SelectItem value="1h">1 Hour (1h)</SelectItem>
                          <SelectItem value="1d">1 Day (1d)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label>Start Date</Label>
                      <Input
                        type="date"
                        value={params.start_date}
                        onChange={(e) => setParams((p) => ({ ...p, start_date: e.target.value }))}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label>End Date</Label>
                      <Input
                        type="date"
                        value={params.end_date}
                        onChange={(e) => setParams((p) => ({ ...p, end_date: e.target.value }))}
                      />
                    </div>
                    <div className="space-y-1.5 sm:col-span-2">
                      <Label>Simulated Capital (₹)</Label>
                      <Input
                        type="number"
                        value={params.capital}
                        onChange={(e) => setParams((p) => ({ ...p, capital: e.target.value }))}
                      />
                    </div>
                  </div>

                  <Button onClick={handleRun} disabled={launching} className="font-semibold">
                    {launching ? (
                      <>
                        <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                        Running Replay Engine...
                      </>
                    ) : (
                      <>
                        <Play className="h-4 w-4 mr-2 fill-current" />
                        Run Event-Driven Backtest
                      </>
                    )}
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          {selectedStrategy && (
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-base">Results for "{selectedStrategy.name}"</CardTitle>
                  <CardDescription>
                    Select a previous run or launch a new run above.
                  </CardDescription>
                </div>
                {results.length > 1 && (
                  <Select
                    value={selectedRun ? String(selectedRun.id) : ''}
                    onValueChange={(val) => {
                      const run = results.find((r) => String(r.id) === val)
                      if (run) setSelectedRun(run)
                    }}
                  >
                    <SelectTrigger className="w-[180px] h-8 text-xs">
                      <SelectValue placeholder="Select run..." />
                    </SelectTrigger>
                    <SelectContent>
                      {results.map((r) => (
                        <SelectItem key={r.id} value={String(r.id)}>
                          Run #{r.id} ({r.symbol})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </CardHeader>
              <CardContent>
                {loadingResults ? (
                  <div className="space-y-2 animate-pulse py-8 text-center text-xs text-muted-foreground">
                    Loading backtest results...
                  </div>
                ) : results.length === 0 ? (
                  <div className="text-center py-12 text-muted-foreground text-sm border border-dashed rounded-xl">
                    No runs yet for this strategy. Configure parameters above and click "Run
                    Event-Driven Backtest".
                  </div>
                ) : (
                  <div>
                    {/* Runs Selector Chips if multiple */}
                    {results.length > 1 && (
                      <div className="flex flex-wrap gap-2 mb-4 pb-3 border-b border-border">
                        {results.map((r) => {
                          const active = selectedRun?.id === r.id
                          return (
                            <Button
                              key={r.id}
                              variant={active ? 'default' : 'outline'}
                              size="sm"
                              onClick={() => setSelectedRun(r)}
                              className="h-8 text-xs"
                            >
                              Run #{r.id} • {r.symbol} ({r.returns >= 0 ? '+' : ''}₹
                              {r.returns.toLocaleString()})
                            </Button>
                          )
                        })}
                      </div>
                    )}

                    {selectedRun && renderRunDashboard(selectedRun)}
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </>
      ) : (
        /* History Tab */
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-base">All Backtest History</CardTitle>
              <CardDescription>
                Historical backtest runs executed across all strategies.
              </CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={fetchAllHistory} disabled={loadingHistory}>
              <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${loadingHistory ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </CardHeader>
          <CardContent>
            {loadingHistory ? (
              <div className="py-12 text-center text-sm text-muted-foreground">
                Loading backtest history...
              </div>
            ) : allHistory.length === 0 ? (
              <div className="py-16 text-center border border-dashed rounded-xl">
                <p className="text-sm text-muted-foreground">No historical backtest runs found.</p>
                <Button
                  variant="link"
                  onClick={() => setViewTab('run')}
                  className="text-xs text-primary mt-1"
                >
                  Run your first backtest →
                </Button>
              </div>
            ) : (
              <div className="overflow-x-auto border border-border rounded-xl">
                <table className="w-full text-xs text-left border-collapse">
                  <thead className="bg-muted/40 text-muted-foreground uppercase font-bold border-b border-border">
                    <tr>
                      <th className="p-3">Run #</th>
                      <th className="p-3">Strategy</th>
                      <th className="p-3">Symbol</th>
                      <th className="p-3">Timeframe</th>
                      <th className="p-3">Period</th>
                      <th className="p-3 text-right">Capital</th>
                      <th className="p-3 text-right">Win Rate</th>
                      <th className="p-3 text-right">Returns</th>
                      <th className="p-3 text-center">Status</th>
                      <th className="p-3 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {allHistory.map((b) => (
                      <tr key={b.id} className="hover:bg-muted/20">
                        <td className="p-3 font-bold text-muted-foreground">#{b.id}</td>
                        <td className="p-3 font-bold text-foreground">
                          {b.strategy_name || `Strategy #${b.strategy_id}`}
                        </td>
                        <td className="p-3 font-semibold text-primary">{b.symbol}</td>
                        <td className="p-3">
                          <Badge variant="outline">{b.timeframe}</Badge>
                        </td>
                        <td className="p-3 text-muted-foreground">
                          {b.start_date} to {b.end_date}
                        </td>
                        <td className="p-3 text-right font-medium">
                          ₹{b.capital.toLocaleString()}
                        </td>
                        <td className="p-3 text-right font-bold text-profit">
                          {IN_FLIGHT_STATUSES.has(b.status) || b.status === 'Failed'
                            ? '—'
                            : `${b.win_rate}%`}
                        </td>
                        <td className="p-3 text-right font-bold">
                          {IN_FLIGHT_STATUSES.has(b.status) || b.status === 'Failed' ? (
                            '—'
                          ) : (
                            <span className={b.returns >= 0 ? 'text-profit' : 'text-loss'}>
                              {b.returns >= 0 ? '+' : ''}₹{b.returns.toLocaleString()}
                            </span>
                          )}
                        </td>
                        <td className="p-3 text-center">
                          <Badge
                            className={
                              b.status === 'Success'
                                ? 'bg-profit/10 text-profit border-none font-bold text-[10px]'
                                : b.status === 'Failed'
                                  ? 'bg-loss/10 text-loss border-none font-bold text-[10px]'
                                  : 'bg-info/10 text-info border-none font-bold text-[10px]'
                            }
                          >
                            {b.status}
                          </Badge>
                        </td>
                        <td className="p-3 text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setSelectedStrategyId(String(b.strategy_id))
                              setSelectedRun(b)
                              setViewTab('run')
                            }}
                            className="h-7 text-[11px] text-primary hover:underline px-2"
                          >
                            View Details →
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </PageContainer>
  )
}
