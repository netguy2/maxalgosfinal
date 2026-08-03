import { History, Play, RefreshCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { strategyApi } from '@/api/strategy'
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
import type { Strategy } from '@/types/strategy'
import { showToast } from '@/utils/toast'

interface BacktestResult {
  id: number
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
  created_at: string
}

const DEFAULT_SYMBOLS = ['NIFTY', 'BANKNIFTY', 'RELIANCE']

// A run is still in flight until it leaves these two states -- see
// services/backtest_engine.py::run_backtest's status transitions
// (Pending -> Running -> Completed/Failed).
const IN_FLIGHT_STATUSES = new Set(['Pending', 'Running'])

/**
 * Standalone Backtest page -- pick any existing strategy, configure a
 * historical run, launch it, and watch it land here (polling, since
 * services/backtest_engine.py runs the replay on a background thread and
 * a multi-year replay can take real wall-clock time -- see
 * run_backtest_async's docstring). Previously this flow only existed as a
 * modal buried behind a button on each My Strategies card; this page is
 * the same real engine, just given its own place to live.
 */
export default function Backtest() {
  const [searchParams] = useSearchParams()
  const preselectedStrategyId = searchParams.get('strategy') || ''

  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [loadingStrategies, setLoadingStrategies] = useState(true)

  const [selectedStrategyId, setSelectedStrategyId] = useState<string>('')
  const [availableSymbols, setAvailableSymbols] = useState<string[]>(DEFAULT_SYMBOLS)
  const [params, setParams] = useState({
    symbol: 'NIFTY',
    timeframe: '15m',
    start_date: '2026-01-01',
    end_date: '2026-03-31',
    capital: '100000',
  })
  const [launching, setLaunching] = useState(false)

  const [results, setResults] = useState<BacktestResult[]>([])
  const [loadingResults, setLoadingResults] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchStrategies = async () => {
    try {
      setLoadingStrategies(true)
      const all = await strategyApi.getStrategies()
      // Backtest is a webhook-Strategy concept (real conditions_tree
      // replay) -- Python Strategy Host scripts and Flow workflows have no
      // conditions_tree to replay, and MaxHook connections are just
      // webhook Strategy rows tagged for a different UI, so they stay
      // eligible here same as any other webhook strategy.
      setStrategies(all.filter((s) => s.lifecycle_state !== 'Archived'))
    } catch {
      showToast.error('Failed to load strategies', 'strategy')
    } finally {
      setLoadingStrategies(false)
    }
  }

  useEffect(() => {
    fetchStrategies()
  }, [])

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

      const symbolList = (mappings || [])
        .map((m) => m.symbol?.toUpperCase())
        .filter((s): s is string => Boolean(s) && !['LONG', 'SHORT', 'BOTH'].includes(s))
      const uniqueSymbols = Array.from(new Set([...symbolList, ...DEFAULT_SYMBOLS]))
      setAvailableSymbols(uniqueSymbols)
      setParams((prev) => ({ ...prev, symbol: symbolList[0] || 'NIFTY' }))
    } catch {
      showToast.error('Failed to load strategy details', 'strategy')
    } finally {
      setLoadingResults(false)
    }
  }

  // Deep-link support: My Strategies' card "Backtest" action navigates here
  // as /backtest?strategy=<id> instead of opening its own modal, so this
  // page is the one real place a backtest gets launched from.
  useEffect(() => {
    if (!loadingStrategies && preselectedStrategyId && strategies.some((s) => String(s.id) === preselectedStrategyId)) {
      handleSelectStrategy(preselectedStrategyId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadingStrategies, preselectedStrategyId])

  // Poll until the just-launched run leaves Pending/Running -- the POST
  // only enqueues the job (services/backtest_engine.py::run_backtest_async
  // returns immediately), so the real outcome has to be fetched after.
  const pollForCompletion = (strategyId: number) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const latest = await fetchResultsFor(strategyId)
        setResults(latest)
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
    }, 4000)
  }

  const handleRun = async () => {
    if (!selectedStrategyId) return
    const strategyId = Number(selectedStrategyId)
    try {
      setLaunching(true)
      const data = await strategyApi.runBacktest(strategyId, params)
      if (data.status === 'pending') {
        showToast.success(data.message || 'Backtest started -- results will appear below.', 'strategy')
        setResults(await fetchResultsFor(strategyId))
        pollForCompletion(strategyId)
      } else if (data.status === 'success') {
        showToast.success('Backtest completed.', 'strategy')
        setResults(await fetchResultsFor(strategyId))
      } else {
        showToast.error(data.message || 'Backtest failed to start', 'strategy')
      }
    } catch {
      showToast.error('Failed to launch backtest', 'strategy')
    } finally {
      setLaunching(false)
    }
  }

  const selectedStrategy = strategies.find((s) => s.id === Number(selectedStrategyId))

  return (
    <div className="container mx-auto py-6 space-y-6 max-w-5xl px-4 sm:px-6">
      <div className="flex items-center gap-3">
        <History className="h-6 w-6 text-brand" />
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Backtest</h1>
          <p className="text-muted-foreground">
            Pick a saved strategy and replay it against historical data.
          </p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Choose a strategy</CardTitle>
          <CardDescription>
            Only strategies with saved entry conditions can be replayed. Create one first from{' '}
            <Link to="/strategy/new" className="underline">
              My Strategies
            </Link>{' '}
            if the list below is empty.
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
              <SelectTrigger className="max-w-sm">
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
                <div className="space-y-1">
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
                <div className="space-y-1">
                  <Label>Timeframe</Label>
                  <Select
                    value={params.timeframe}
                    onValueChange={(val) => setParams((p) => ({ ...p, timeframe: val }))}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="5m">5m</SelectItem>
                      <SelectItem value="15m">15m</SelectItem>
                      <SelectItem value="1h">1h</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label>Start Date</Label>
                  <Input
                    type="date"
                    value={params.start_date}
                    onChange={(e) => setParams((p) => ({ ...p, start_date: e.target.value }))}
                  />
                </div>
                <div className="space-y-1">
                  <Label>End Date</Label>
                  <Input
                    type="date"
                    value={params.end_date}
                    onChange={(e) => setParams((p) => ({ ...p, end_date: e.target.value }))}
                  />
                </div>
                <div className="space-y-1 sm:col-span-2">
                  <Label>Simulated Capital (₹)</Label>
                  <Input
                    type="number"
                    value={params.capital}
                    onChange={(e) => setParams((p) => ({ ...p, capital: e.target.value }))}
                  />
                </div>
              </div>

              <Button onClick={handleRun} disabled={launching}>
                {launching ? (
                  <>
                    <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                    Starting...
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4 mr-2" />
                    Run Backtest
                  </>
                )}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {selectedStrategy && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Results for "{selectedStrategy.name}"</CardTitle>
            <CardDescription>
              Runs update automatically while a backtest is in progress.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {loadingResults ? (
              <div className="space-y-2 animate-pulse">
                {[1, 2].map((i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : results.length === 0 ? (
              <div className="text-center py-10 text-muted-foreground text-sm">
                No runs yet for this strategy. Configure the form above and run one.
              </div>
            ) : (
              <div className="overflow-x-auto border border-border rounded-lg">
                <table className="w-full text-sm text-left">
                  <thead className="bg-muted text-muted-foreground text-xs uppercase font-bold border-b">
                    <tr>
                      <th className="p-3">Run</th>
                      <th className="p-3">Symbol</th>
                      <th className="p-3">Timeframe</th>
                      <th className="p-3">Period</th>
                      <th className="p-3 text-right">Capital</th>
                      <th className="p-3 text-right">Win Rate</th>
                      <th className="p-3 text-right">Returns</th>
                      <th className="p-3 text-center">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {results.map((b) => (
                      <tr key={b.id} className="hover:bg-muted/30">
                        <td className="p-3 font-semibold">#{b.id}</td>
                        <td className="p-3 font-semibold text-primary">{b.symbol}</td>
                        <td className="p-3">
                          <Badge variant="outline">{b.timeframe}</Badge>
                        </td>
                        <td className="p-3 text-xs text-muted-foreground">
                          {b.start_date} to {b.end_date}
                        </td>
                        <td className="p-3 text-right font-medium">
                          ₹{b.capital.toLocaleString()}
                        </td>
                        <td className="p-3 text-right font-bold text-profit">
                          {IN_FLIGHT_STATUSES.has(b.status) ? '—' : `${b.win_rate}%`}
                        </td>
                        <td className="p-3 text-right font-black text-info">
                          {IN_FLIGHT_STATUSES.has(b.status)
                            ? '—'
                            : `${b.returns > 0 ? '+' : ''}₹${b.returns.toLocaleString()}`}
                        </td>
                        <td className="p-3 text-center">
                          <Badge
                            className={
                              b.status === 'Completed'
                                ? 'bg-profit/10 text-profit border-none font-bold text-[10px]'
                                : b.status === 'Failed'
                                  ? 'bg-loss/10 text-loss border-none font-bold text-[10px]'
                                  : 'bg-info/10 text-info border-none font-bold text-[10px]'
                            }
                            title={b.status === 'Failed' ? b.error_message || undefined : undefined}
                          >
                            {b.status}
                          </Badge>
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
    </div>
  )
}
