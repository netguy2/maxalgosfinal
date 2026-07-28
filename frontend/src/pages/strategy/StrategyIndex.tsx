import {
  BarChart3,
  Check,
  Clock,
  Code2,
  Copy,
  Layers,
  Play,
  Plug,
  Plus,
  RefreshCw,
  Search,
  Settings,
  Sparkles,
  Webhook,
  Zap,
} from 'lucide-react'
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { fetchCSRFToken } from '@/api/client'
import { strategyApi } from '@/api/strategy'
import { CATALOG } from '@/lib/marketplace-catalog'
import { StatCard } from '@/components/patterns/StatCard'
import { DeployStrategyDrawer } from '@/components/strategy-builder/DeployStrategyDrawer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
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
import { prefetchRoute } from '@/lib/route-prefetch'
import { getSignalSourceLabel, type Strategy } from '@/types/strategy'
import { showToast } from '@/utils/toast'

const StrategyPortfolio = lazy(() => import('@/pages/StrategyPortfolio'))

// Eagerly prefetch the co-located wizard chunk the instant the strategies
// page mounts — the user is very likely to click the AI Wizard button, and
// the wizard module is tiny so the cost is negligible.
void import('@/pages/strategy/StrategyWizard')

/**
 * Strategy registry ("My Strategies") — the single-responsibility home page
 * for strategy management. Templates, the AI Wizard, Backtest Logs, and the
 * Webhooks Guide each moved to their own routes (see the action row below)
 * so this page stays focused on "manage my strategies".
 */
export default function StrategyIndex() {
  const navigate = useNavigate()
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [loading, setLoading] = useState(true)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [categoryFilter, setCategoryFilter] = useState<
    'all' | 'webhook' | 'builder' | 'marketplace'
  >('all')
  const [searchQuery, setSearchQuery] = useState('')

  const [hostConfig, setHostConfig] = useState<{
    host_server: string
    is_localhost: boolean
  } | null>(null)

  // Deploy Drawer
  const [deployDrawerOpen, setDeployDrawerOpen] = useState(false)
  const [selectedStrategyForDeploy, setSelectedStrategyForDeploy] = useState<Strategy | null>(null)

  // Backtest Modal
  const [backtestModalOpen, setBacktestModalOpen] = useState(false)
  const [selectedStrategyForBacktest, setSelectedStrategyForBacktest] = useState<Strategy | null>(
    null
  )
  const [backtestParams, setBacktestParams] = useState({
    symbol: 'NIFTY',
    timeframe: '15m',
    start_date: '2026-01-01',
    end_date: '2026-03-31',
    capital: '100000',
  })
  const [runningBacktest, setRunningBacktest] = useState(false)

  const fetchStrategies = async () => {
    try {
      setLoading(true)
      const data = await strategyApi.getStrategies()
      setStrategies(data)
    } catch (_error) {
      showToast.error('Failed to load strategies', 'strategy')
    } finally {
      setLoading(false)
    }
  }

  const [searchParams, setSearchParams] = useSearchParams()

  // Fetch host config and strategies on mount
  useEffect(() => {
    const fetchHostConfig = async () => {
      try {
        const response = await fetch('/api/config/host', { credentials: 'include' })
        const data = await response.json()
        setHostConfig(data)
      } catch (_error) {
        setHostConfig({
          host_server: window.location.origin,
          is_localhost:
            window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1',
        })
      }
    }
    fetchHostConfig()
    fetchStrategies()
  }, [])

  const installingRef = useRef(false)

  // Auto-install strategy template if ?template= query parameter is present in URL
  useEffect(() => {
    const templateId = searchParams.get('template')
    if (!templateId || installingRef.current) return

    installingRef.current = true
    const catalogItem = CATALOG.find((c) => c.id === templateId)

    // Remove the template param immediately so re-renders won't re-trigger
    searchParams.delete('template')
    setSearchParams(searchParams, { replace: true })

    if (catalogItem) {
      const installTemplate = async () => {
        try {
          const sanitizedName = catalogItem.name
            .replace(/\//g, '-')
            .replace(/[^a-zA-Z0-9\s\-_()]/g, '')
            .trim()
            .slice(0, 35)

          const resp = await strategyApi.createStrategy({
            name: sanitizedName,
            platform: 'tradingview',
            strategy_type: 'intraday',
            trading_mode: 'BOTH',
            start_time: '09:15',
            end_time: '15:00',
            squareoff_time: '15:15',
          })
          if (resp.status === 'success') {
            showToast.success(`Installed template strategy: ${catalogItem.name}`, 'strategy')
            fetchStrategies()
          } else {
            showToast.error(resp.message || 'Failed to install template', 'strategy')
          }
        } catch (_err) {
          showToast.error(`Failed to install template: ${catalogItem.name}`, 'strategy')
        } finally {
          installingRef.current = false
        }
      }
      installTemplate()
    } else {
      installingRef.current = false
    }
  }, [searchParams, setSearchParams])

  const getWebhookUrl = (webhookId: string): string => {
    const baseUrl = hostConfig?.host_server || window.location.origin
    return `${baseUrl}/strategy/webhook/${webhookId}`
  }

  const copyWebhookUrl = async (webhookId: string) => {
    const url = getWebhookUrl(webhookId)
    try {
      await navigator.clipboard.writeText(url)
      setCopiedId(webhookId)
      showToast.success('Webhook URL copied to clipboard', 'clipboard')
      setTimeout(() => setCopiedId(null), 2000)
    } catch {
      showToast.error('Failed to copy URL', 'clipboard')
    }
  }

  const [configuredSymbolsForBacktest, setConfiguredSymbolsForBacktest] = useState<string[]>([
    'NIFTY',
    'BANKNIFTY',
    'RELIANCE',
  ])

  const handleLaunchBacktest = async (strategy: Strategy) => {
    setSelectedStrategyForBacktest(strategy)
    setBacktestModalOpen(true)

    try {
      const data = await strategyApi.getStrategy(strategy.id)
      if (data.mappings && data.mappings.length > 0) {
        const symbolList = data.mappings
          .map((m) => m.symbol?.toUpperCase())
          .filter((s) => s && s !== 'LONG' && s !== 'SHORT' && s !== 'BOTH')

        if (symbolList.length > 0) {
          const uniqueSymbols = Array.from(
            new Set([...symbolList, 'NIFTY', 'BANKNIFTY', 'RELIANCE'])
          )
          setConfiguredSymbolsForBacktest(uniqueSymbols)
          setBacktestParams((prev) => ({ ...prev, symbol: symbolList[0] }))
          return
        }
      }
    } catch (_err) {
      // Keep defaults on fetch error
    }
    setBacktestParams((prev) => ({ ...prev, symbol: 'NIFTY' }))
  }

  const handleRunBacktestSubmit = async () => {
    if (!selectedStrategyForBacktest) return
    try {
      setRunningBacktest(true)
      const data = await strategyApi.runBacktest(selectedStrategyForBacktest.id, backtestParams)
      if (data.status === 'success') {
        showToast.success('Backtest job completed successfully!', 'strategy')
        setBacktestModalOpen(false)
        fetchStrategies() // update lifecycle state badge
        navigate('/strategy/backtests')
      } else if ((data.status as string) === 'pending') {
        // Real backtest engine not yet available — honest message, no fake run
        showToast.info(data.message || 'Backtesting engine coming soon', 'strategy')
        setBacktestModalOpen(false)
      } else {
        showToast.error(data.message || 'Backtest failed', 'strategy')
      }
    } catch {
      showToast.error('Failed to execute backtest', 'strategy')
    } finally {
      setRunningBacktest(false)
    }
  }

  const filteredStrategies = strategies.filter((s) => {
    if (s.lifecycle_state === 'Archived') return false

    // Name search (scales the grid past a handful of strategies)
    if (searchQuery && !s.name.toLowerCase().includes(searchQuery.toLowerCase())) {
      return false
    }

    // Check filter tab
    const src = s.signal_source?.toLowerCase() || ''
    if (categoryFilter === 'webhook') {
      return src !== 'marketplace' && s.platform !== 'strategy_builder'
    }
    if (categoryFilter === 'builder') {
      return s.platform === 'strategy_builder'
    }
    if (categoryFilter === 'marketplace') {
      return src === 'marketplace'
    }
    return true
  })

  // Summary stats for the dashboard header — real fields only (is_active /
  // lifecycle_state). There is no "Running"/"Paused" strategy status in the
  // data model; that distinction only exists on Deployment.status.
  const stats = useMemo(() => {
    const live = strategies.filter((s) => s.lifecycle_state !== 'Archived')
    return {
      total: live.length,
      active: live.filter((s) => s.is_active).length,
      inactive: live.filter((s) => !s.is_active).length,
      marketplace: live.filter((s) => s.signal_source?.toLowerCase() === 'marketplace').length,
    }
  }, [strategies])

  return (
    <div className="container mx-auto py-6 space-y-6 max-w-7xl px-4 sm:px-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Strategies</h1>
          <p className="text-muted-foreground">Manage and deploy your webhook strategies.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchStrategies}>
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
          <Button onClick={() => navigate('/strategy/new')}>
            <Plus className="h-4 w-4 mr-2" />
            New Strategy
          </Button>
        </div>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="Total Strategies" value={stats.total} icon={Zap} />
        <StatCard label="Active" value={stats.active} icon={Play} />
        <StatCard label="Inactive" value={stats.inactive} icon={Webhook} />
        <StatCard label="Marketplace" value={stats.marketplace} icon={Sparkles} />
      </div>

      {/* Related tools — each is its own page now */}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" className="h-8 text-xs" asChild>
          <Link to="/marketplace">
            <Layers className="h-3.5 w-3.5 mr-1.5" />
            Templates
          </Link>
        </Button>
        <Button variant="outline" size="sm" className="h-8 text-xs" asChild>
          <Link
            to="/strategy/wizard"
            onMouseEnter={() => prefetchRoute('/strategy/wizard')}
            onFocus={() => prefetchRoute('/strategy/wizard')}
          >
            <Sparkles className="h-3.5 w-3.5 mr-1.5" />
            AI Wizard
          </Link>
        </Button>
        <Button variant="outline" size="sm" className="h-8 text-xs" asChild>
          <Link to="/strategy/backtests">
            <BarChart3 className="h-3.5 w-3.5 mr-1.5" />
            Backtest Logs
          </Link>
        </Button>
        <Button variant="outline" size="sm" className="h-8 text-xs" asChild>
          <Link to="/tools/webhooks">
            <Webhook className="h-3.5 w-3.5 mr-1.5" />
            Webhooks Guide
          </Link>
        </Button>
      </div>

      {/* Search + Category Filters */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 pb-2">
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search strategies..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8 h-8 text-sm"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant={categoryFilter === 'all' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setCategoryFilter('all')}
            className="text-xs"
          >
            All Assets
          </Button>
          <Button
            variant={categoryFilter === 'webhook' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setCategoryFilter('webhook')}
            className="text-xs"
          >
            Webhooks
          </Button>
          <Button
            variant={categoryFilter === 'builder' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setCategoryFilter('builder')}
            className="text-xs"
          >
            Visual Builder
          </Button>
          <Button
            variant={categoryFilter === 'marketplace' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setCategoryFilter('marketplace')}
            className="text-xs"
          >
            Marketplace
          </Button>
        </div>
      </div>

      {/* "Visual Builder" strategies live entirely in the Portfolio Presets
          section below (a separate saved-option-strategy store, not a
          webhook Strategy row) -- so this tab skips the webhook grid/empty
          state and points straight at Portfolio Presets instead of always
          showing "No Strategies Found" regardless of what's actually saved. */}
      {categoryFilter === 'builder' ? (
        <Card className="py-8">
          <CardContent className="flex flex-col items-center justify-center text-center">
            <Layers className="h-10 w-10 text-muted-foreground mb-3" />
            <h3 className="text-base font-semibold mb-1">Visual Builder Strategies</h3>
            <p className="text-muted-foreground text-sm mb-4 max-w-md">
              Strategies saved from Strategy Builder appear in Portfolio Presets below, under
              MyTrades or Simulation.
            </p>
            <Button variant="outline" onClick={() => navigate('/visual-builder')}>
              <Plus className="h-4 w-4 mr-2" />
              Open Strategy Builder
            </Button>
          </CardContent>
        </Card>
      ) : loading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-48 w-full" />
          ))}
        </div>
      ) : filteredStrategies.length === 0 ? (
        <Card className="py-12">
          <CardContent className="flex flex-col items-center justify-center text-center">
            <Zap className="h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="text-lg font-semibold mb-2">No Strategies Found</h3>
            <p className="text-muted-foreground mb-4">
              Create a new strategy or subscribe to one in the Marketplace to get started.
            </p>
            <Button onClick={() => navigate('/strategy/new')}>
              <Plus className="h-4 w-4 mr-2" />
              Create Strategy
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {filteredStrategies.map((strategy) => (
            <Card
              key={strategy.id}
              className="relative overflow-hidden border hover:border-primary/40 transition-colors shadow-sm"
            >
              {/* Status Indicator Bar */}
              <div
                className={`absolute top-0 left-0 right-0 h-1 ${
                  strategy.is_active ? 'bg-profit' : 'bg-muted-foreground/30'
                }`}
              />

              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div className="space-y-1">
                    <CardTitle className="text-lg">
                      <Link
                        to={`/strategy/${strategy.id}`}
                        className="hover:text-primary hover:underline underline-offset-4 transition-colors"
                      >
                        {strategy.name}
                      </Link>
                    </CardTitle>
                    <CardDescription className="text-xs font-semibold">
                      Source: {getSignalSourceLabel(strategy.platform)}
                    </CardDescription>
                  </div>
                  <div className="flex gap-1.5 items-center">
                    <Badge
                      variant="outline"
                      className="text-[10px] uppercase font-bold text-primary"
                    >
                      {strategy.lifecycle_state || 'Draft'}
                    </Badge>
                    <Badge variant={strategy.is_active ? 'default' : 'secondary'}>
                      {strategy.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="space-y-4">
                {/* Mode and Timing info */}
                <div className="flex items-center gap-2 text-sm">
                  <Badge variant="outline" className="font-normal">
                    {strategy.is_intraday ? 'Intraday' : 'Positional'}
                  </Badge>
                </div>

                {strategy.is_intraday && strategy.start_time && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Clock className="h-3.5 w-3.5" />
                    <span>
                      {strategy.start_time} - {strategy.end_time}
                      {strategy.squareoff_time && ` (SqOff: ${strategy.squareoff_time})`}
                    </span>
                  </div>
                )}

                {/* Configured broker(s) - empty means "auto: all connected
                    brokers" (see services/signal_engine.py's fallback),
                    not "no broker", so label that state distinctly. */}
                <div className="flex items-center gap-1.5 flex-wrap text-xs">
                  <Plug className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  {strategy.brokers ? (
                    strategy.brokers.split(',').map((broker) => (
                      <Badge key={broker} variant="secondary" className="font-normal text-[10px]">
                        {broker.trim()}
                      </Badge>
                    ))
                  ) : (
                    <span className="text-muted-foreground">Auto (all connected brokers)</span>
                  )}
                </div>

                {/* Copy Webhook Helper */}
                {strategy.signal_source?.toLowerCase() !== 'marketplace' && (
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      className="flex-1 justify-start text-xs font-mono truncate h-8"
                      onClick={() => copyWebhookUrl(strategy.webhook_id)}
                    >
                      {copiedId === strategy.webhook_id ? (
                        <Check className="h-3 w-3 mr-2 text-profit" />
                      ) : (
                        <Copy className="h-3 w-3 mr-2" />
                      )}
                      <span className="truncate">
                        Webhook: {strategy.webhook_id.slice(0, 8)}...
                      </span>
                    </Button>
                  </div>
                )}

                {/* Operations Actions Row */}
                <div className="flex flex-wrap gap-2 pt-2 border-t border-border/40">
                  <Button variant="outline" size="sm" className="flex-1 text-xs" asChild>
                    <Link to={`/strategy/${strategy.id}/configure`}>
                      <Settings className="h-3.5 w-3.5 mr-1" />
                      Symbols
                    </Link>
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1 text-xs text-info hover:text-info/80"
                    onClick={() => handleLaunchBacktest(strategy)}
                  >
                    <Play className="h-3.5 w-3.5 mr-1" />
                    Backtest
                  </Button>
                  <Button
                    variant="default"
                    size="sm"
                    className="flex-1 text-xs"
                    onClick={() => {
                      setSelectedStrategyForDeploy(strategy)
                      setDeployDrawerOpen(true)
                    }}
                  >
                    <Layers className="h-3.5 w-3.5 mr-1" />
                    Deploy
                  </Button>
                  {strategy.signal_source?.toLowerCase() === 'python' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="w-full text-xs text-muted-foreground hover:text-foreground h-7"
                      asChild
                    >
                      <Link to="/python">
                        <Code2 className="h-3.5 w-3.5 mr-1" />
                        Open Code in Python Studio
                      </Link>
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Portfolio Presets — relocated here from the old /strategy/templates
          page (deleted; Marketplace now owns all template browsing). This
          section is about organizing/using presets for strategies the user
          already owns, so it lives on the "My Strategies" page rather than
          Marketplace, which is for acquiring new ones. */}
      <div className="border-t border-border pt-6 [&>div]:py-0">
        <h3 className="text-sm font-bold text-muted-foreground uppercase tracking-wider mb-4">
          Portfolio Presets
        </h3>
        <Suspense fallback={<Skeleton className="h-48 w-full" />}>
          <StrategyPortfolio />
        </Suspense>
      </div>

      {/* Backtest Config Modal */}
      <Dialog open={backtestModalOpen} onOpenChange={setBacktestModalOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Configure Backtest</DialogTitle>
            <DialogDescription>
              Simulate historical execution for "{selectedStrategyForBacktest?.name}" over selected
              dates.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <Label>Backtest Symbol</Label>
                <Select
                  value={backtestParams.symbol}
                  onValueChange={(val) => setBacktestParams({ ...backtestParams, symbol: val })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {configuredSymbolsForBacktest.map((sym) => (
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
                  value={backtestParams.timeframe}
                  onValueChange={(val) => setBacktestParams({ ...backtestParams, timeframe: val })}
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
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <Label>Start Date</Label>
                <Input
                  type="date"
                  value={backtestParams.start_date}
                  onChange={(e) =>
                    setBacktestParams({ ...backtestParams, start_date: e.target.value })
                  }
                />
              </div>
              <div className="space-y-1">
                <Label>End Date</Label>
                <Input
                  type="date"
                  value={backtestParams.end_date}
                  onChange={(e) =>
                    setBacktestParams({ ...backtestParams, end_date: e.target.value })
                  }
                />
              </div>
            </div>
            <div className="space-y-1">
              <Label>Simulated Capital (₹)</Label>
              <Input
                type="number"
                value={backtestParams.capital}
                onChange={(e) => setBacktestParams({ ...backtestParams, capital: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setBacktestModalOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleRunBacktestSubmit} disabled={runningBacktest}>
              {runningBacktest ? 'Running Simulation...' : 'Execute Backtest'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Deployment Drawer — creates a real Draft deployment internally,
          runs a real dry-run against it, and this callback only activates
          the already-created row (see DeployStrategyDrawer's onActivate
          contract). */}
      <DeployStrategyDrawer
        open={deployDrawerOpen}
        onClose={() => setDeployDrawerOpen(false)}
        strategyName={selectedStrategyForDeploy?.name || ''}
        legs={[]} // mappings loaded by deploy target
        strategyId={selectedStrategyForDeploy?.id}
        onActivate={async (deploymentId) => {
          try {
            const csrfToken = await fetchCSRFToken()
            const res = await fetch(`/api/v1/deployments/${deploymentId}/resume`, {
              method: 'POST',
              headers: {
                'X-CSRFToken': csrfToken,
              },
            })
            const data = await res.json()
            if (data.status === 'error') {
              showToast.error(data.message || 'Activation failed', 'strategy')
            } else {
              showToast.success('Strategy deployed successfully!', 'strategy')
              setDeployDrawerOpen(false)
              navigate('/deployments')
            }
          } catch {
            showToast.error('Failed to activate deployment', 'strategy')
          }
        }}
      />
    </div>
  )
}
