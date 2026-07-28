import { ArrowLeft, Clock, Filter, HardDrive, RefreshCw, ScrollText } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { pythonStrategyApi } from '@/api/python-strategy'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { LogViewer } from '@/components/ui/log-viewer'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import type { AllStrategiesLogFile, CombinedLogEntry } from '@/types/python-strategy'
import { showToast } from '@/utils/toast'

const ALL_STRATEGIES = '__all__'

export default function AllPythonStrategyLogs() {
  const [logFiles, setLogFiles] = useState<AllStrategiesLogFile[]>([])
  const [entries, setEntries] = useState<CombinedLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [strategyFilter, setStrategyFilter] = useState<string>(ALL_STRATEGIES)

  const fetchData = async (showLoading = true) => {
    try {
      if (showLoading) setLoading(true)
      const [files, combined] = await Promise.all([
        pythonStrategyApi.getAllLogFiles(),
        pythonStrategyApi.getCombinedLogs(500),
      ])
      setLogFiles(files)
      setEntries(combined.entries)
    } catch (_error) {
      if (showLoading) showToast.error('Failed to load logs', 'pythonStrategy')
    } finally {
      if (showLoading) setLoading(false)
    }
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: one-time initial load on mount
  useEffect(() => {
    fetchData()
  }, [])

  // Auto-refresh every 5s -- there's no per-strategy "running" gate here
  // like the single-strategy log page has (this view spans strategies in
  // every state), so it just polls on a fixed interval when enabled.
  useEffect(() => {
    if (!autoRefresh) return
    const interval = setInterval(() => fetchData(false), 5000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh])

  const handleRefresh = async () => {
    setRefreshing(true)
    await fetchData(false)
    setRefreshing(false)
  }

  // Distinct strategies present in the combined feed, for the filter dropdown
  const strategyOptions = useMemo(() => {
    const seen = new Map<string, string>()
    for (const e of entries) {
      if (!seen.has(e.strategy_id)) seen.set(e.strategy_id, e.strategy_name)
    }
    return Array.from(seen.entries()).map(([id, name]) => ({ id, name }))
  }, [entries])

  const filteredEntries = useMemo(() => {
    if (strategyFilter === ALL_STRATEGIES) return entries
    return entries.filter((e) => e.strategy_id === strategyFilter)
  }, [entries, strategyFilter])

  const combinedText = useMemo(
    () => filteredEntries.map((e) => `[${e.strategy_name}] ${e.line}`).join('\n'),
    [filteredEntries]
  )

  if (loading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <Skeleton className="h-8 w-32" />
        <div className="grid grid-cols-4 gap-6">
          <Skeleton className="h-[600px]" />
          <Skeleton className="h-[600px] col-span-3" />
        </div>
      </div>
    )
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Back Button */}
      <Button variant="ghost" asChild>
        <Link to="/python">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Python Strategies
        </Link>
      </Button>

      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">All Strategy Logs</h1>
          <p className="text-muted-foreground">
            Combined feed across every Python strategy -- no need to open each one individually
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center space-x-2">
            <Checkbox
              id="auto-refresh"
              checked={autoRefresh}
              onCheckedChange={(checked) => setAutoRefresh(checked as boolean)}
            />
            <Label htmlFor="auto-refresh" className="text-sm">
              Auto-refresh
            </Label>
          </div>
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing}>
            <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Strategy summary sidebar */}
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <Filter className="h-4 w-4" />
              Strategies
            </CardTitle>
            <CardDescription>{logFiles.length} log file(s)</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Select value={strategyFilter} onValueChange={setStrategyFilter}>
              <SelectTrigger>
                <SelectValue placeholder="Filter by strategy" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_STRATEGIES}>All strategies</SelectItem>
                {strategyOptions.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <div className="space-y-2">
              {logFiles.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-8">
                  No strategy logs found
                </p>
              ) : (
                logFiles.map((log) => (
                  <button
                    type="button"
                    key={`${log.strategy_id}-${log.name}`}
                    onClick={() =>
                      setStrategyFilter(
                        strategyFilter === log.strategy_id ? ALL_STRATEGIES : log.strategy_id
                      )
                    }
                    className={`w-full text-left p-3 rounded-lg transition-colors ${
                      strategyFilter === log.strategy_id
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted hover:bg-muted/80'
                    }`}
                  >
                    <div className="font-medium text-sm truncate">{log.strategy_name}</div>
                    <div className="flex items-center gap-2 mt-1 text-xs opacity-80">
                      <Clock className="h-3 w-3" />
                      {new Date(log.last_modified).toLocaleString('en-IN', {
                        day: '2-digit',
                        month: 'short',
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </div>
                    <div className="flex items-center gap-2 mt-1 text-xs opacity-80">
                      <HardDrive className="h-3 w-3" />
                      {log.size_kb.toFixed(2)} KB
                    </div>
                  </button>
                ))
              )}
            </div>
          </CardContent>
        </Card>

        {/* Combined log content */}
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle className="text-sm flex items-center justify-between">
              <span className="flex items-center gap-2">
                <ScrollText className="h-4 w-4" />
                Combined Log
              </span>
              {strategyFilter !== ALL_STRATEGIES && (
                <Badge variant="secondary">
                  {strategyOptions.find((s) => s.id === strategyFilter)?.name}
                </Badge>
              )}
            </CardTitle>
            <CardDescription>
              {filteredEntries.length} line(s) across {strategyOptions.length} strategy
              {strategyOptions.length === 1 ? '' : 'ies'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {filteredEntries.length === 0 ? (
              <div className="flex items-center justify-center h-[500px] text-muted-foreground">
                No log content available yet
              </div>
            ) : (
              <LogViewer value={combinedText} height="500px" followTail={autoRefresh} />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
