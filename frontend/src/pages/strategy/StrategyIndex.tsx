import {
  BarChart3,
  Code2,
  Layers,
  Play,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Wand2,
  Webhook,
  Zap,
} from 'lucide-react'
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { fetchCSRFToken } from '@/api/client'
import {
  activateWorkflow,
  createWorkflow,
  deactivateWorkflow,
  listWorkflows,
  type WorkflowListItem,
} from '@/api/flow'
import { pythonStrategyApi } from '@/api/python-strategy'
import { strategyApi } from '@/api/strategy'
import { type UnifiedRow, UnifiedStrategyCard } from '@/components/strategy/UnifiedStrategyCard'
import { DeployStrategyDrawer } from '@/components/strategy-builder/DeployStrategyDrawer'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { CATALOG } from '@/lib/marketplace-catalog'
import { prefetchRoute } from '@/lib/route-prefetch'
import type { PythonStrategy } from '@/types/python-strategy'
import type { Strategy } from '@/types/strategy'
import { showToast } from '@/utils/toast'

const StrategyPortfolio = lazy(() => import('@/pages/StrategyPortfolio'))

// Eagerly prefetch the co-located wizard chunk the instant the strategies
// page mounts — the user is very likely to click the AI Wizard button, and
// the wizard module is tiny so the cost is negligible.
void import('@/pages/strategy/StrategyWizard')

/**
 * Strategy registry ("My Strategies") — the single-responsibility home page
 * for strategy management.
 *
 * This is a genuine merge of THREE separate backend models, each with its
 * own real lifecycle -- webhook Strategy rows (database/strategy_db.py,
 * still the model for raw TradingView/ChartInk/generic webhooks and any
 * template with no Python-generator adapter), Python Strategy Host scripts
 * (STRATEGY_CONFIGS JSON blob, including marketplace templates ported to
 * real Python generation), and Flow workflows (database/flow_db.py). One
 * shared card chrome (UnifiedStrategyCard) with per-kind actions is the
 * honest representation of that -- a webhook row has no start/stop
 * process, a Flow workflow has no Backtest concept, so a single generic
 * action set would either lie about capabilities or hide real ones.
 */
export default function StrategyIndex() {
  const navigate = useNavigate()
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [pythonStrategies, setPythonStrategies] = useState<PythonStrategy[]>([])
  const [workflows, setWorkflows] = useState<WorkflowListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [categoryFilter, setCategoryFilter] = useState<'all' | 'webhook' | 'python' | 'flow'>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [creatingFlow, setCreatingFlow] = useState(false)

  const [hostConfig, setHostConfig] = useState<{
    host_server: string
    is_localhost: boolean
  } | null>(null)

  // Deploy Drawer
  const [deployDrawerOpen, setDeployDrawerOpen] = useState(false)
  const [selectedStrategyForDeploy, setSelectedStrategyForDeploy] = useState<Strategy | null>(null)
  const [deployLegs, setDeployLegs] = useState<
    { symbol: string; exchange: string; side?: string }[]
  >([])
  const [deployLegsLoading, setDeployLegsLoading] = useState(false)

  // Fetches all three sources in parallel. Promise.allSettled (not
  // Promise.all) so one source being down (e.g. Flow's DB unreachable)
  // shows a toast for that source instead of blanking the whole page --
  // the other two sources' strategies are still real and still running.
  const fetchAll = async () => {
    setLoading(true)
    const [webhookRes, pythonRes, flowRes] = await Promise.allSettled([
      strategyApi.getStrategies(),
      pythonStrategyApi.getStrategies(),
      listWorkflows(),
    ])

    if (webhookRes.status === 'fulfilled') {
      setStrategies(webhookRes.value)
    } else {
      showToast.error('Failed to load webhook strategies', 'strategy')
    }
    if (pythonRes.status === 'fulfilled') {
      setPythonStrategies(pythonRes.value)
    } else {
      showToast.error('Failed to load Python strategies', 'strategy')
    }
    if (flowRes.status === 'fulfilled') {
      setWorkflows(flowRes.value)
    } else {
      showToast.error('Failed to load Flow strategies', 'strategy')
    }
    setLoading(false)
  }

  const [searchParams, setSearchParams] = useSearchParams()

  // Fetch host config and all strategy sources on mount
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
    fetchAll()
    // biome-ignore lint/correctness/useExhaustiveDependencies: fetchAll is stable across renders, mount-only fetch
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
            fetchAll()
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
    // biome-ignore lint/correctness/useExhaustiveDependencies: fetchAll is stable across renders
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

  // Backtesting now lives entirely on its own page (/backtest) -- this just
  // hands off the chosen strategy via query param instead of opening a
  // modal here, so there's one real launch flow instead of two.
  const handleLaunchBacktest = (strategy: Strategy) => {
    navigate(`/backtest?strategy=${strategy.id}`)
  }

  const handlePythonStart = async (strategy: PythonStrategy) => {
    try {
      setActionLoading(strategy.id)
      const response = await pythonStrategyApi.startStrategy(strategy.id)
      if (response.status === 'success') {
        showToast.success(response.message || `Strategy ${strategy.name} started`, 'strategy')
        fetchAll()
      } else {
        showToast.error(response.message || 'Failed to start strategy', 'strategy')
      }
    } catch {
      showToast.error('Failed to start strategy', 'strategy')
    } finally {
      setActionLoading(null)
    }
  }

  const handlePythonStop = async (strategy: PythonStrategy) => {
    try {
      setActionLoading(strategy.id)
      const response = await pythonStrategyApi.stopStrategy(strategy.id)
      if (response.status === 'success') {
        showToast.success(response.message || `Strategy ${strategy.name} stopped`, 'strategy')
        fetchAll()
      } else {
        showToast.error(response.message || 'Failed to stop strategy', 'strategy')
      }
    } catch {
      showToast.error('Failed to stop strategy', 'strategy')
    } finally {
      setActionLoading(null)
    }
  }

  const handleFlowActivate = async (workflow: WorkflowListItem) => {
    try {
      setActionLoading(String(workflow.id))
      const res = await activateWorkflow(workflow.id)
      if (res.status === 'success') {
        showToast.success(res.message || `${workflow.name} activated`, 'strategy')
        fetchAll()
      } else {
        showToast.error(res.message || 'Failed to activate', 'strategy')
      }
    } catch {
      showToast.error('Failed to activate workflow', 'strategy')
    } finally {
      setActionLoading(null)
    }
  }

  const handleFlowDeactivate = async (workflow: WorkflowListItem) => {
    try {
      setActionLoading(String(workflow.id))
      const res = await deactivateWorkflow(workflow.id)
      if (res.status === 'success') {
        showToast.success(res.message || `${workflow.name} deactivated`, 'strategy')
        fetchAll()
      } else {
        showToast.error(res.message || 'Failed to deactivate', 'strategy')
      }
    } catch {
      showToast.error('Failed to deactivate workflow', 'strategy')
    } finally {
      setActionLoading(null)
    }
  }

  // "Create Your Own Strategy" -- reuses Flow/Automation Studio's own
  // create-and-open sequence (FlowIndex.tsx's "New Workflow" action) rather
  // than building a new canvas/node system. Skips Flow's own list screen
  // since the user arrives here with clear intent to start one new thing.
  const handleCreateOwnStrategy = async () => {
    setCreatingFlow(true)
    try {
      const wf = await createWorkflow({ name: 'My Strategy' })
      navigate(`/flow/editor/${wf.id}`)
    } catch {
      showToast.error('Failed to start a new strategy canvas', 'strategy')
    } finally {
      setCreatingFlow(false)
    }
  }

  const unifiedRows = useMemo((): UnifiedRow[] => {
    const webhookRows: UnifiedRow[] = strategies
      .filter(
        (s) =>
          s.lifecycle_state !== 'Archived' &&
          // MaxHook connections are ordinary Strategy rows tagged with this
          // signal_source at creation (NewMaxHookConnection.tsx) -- they
          // belong exclusively in /maxhook, not here, mirroring how
          // Chartink (a separate backend entirely) never appears here.
          s.signal_source !== 'MaxHook'
      )
      .map((data) => ({ kind: 'webhook' as const, data }))
    const pythonRows: UnifiedRow[] = pythonStrategies.map((data) => ({
      kind: 'python' as const,
      data,
    }))
    const flowRows: UnifiedRow[] = workflows.map((data) => ({ kind: 'flow' as const, data }))
    return [...webhookRows, ...pythonRows, ...flowRows]
  }, [strategies, pythonStrategies, workflows])

  const filteredRows = unifiedRows.filter((row) => {
    const name = row.data.name
    if (searchQuery && !name.toLowerCase().includes(searchQuery.toLowerCase())) return false
    if (categoryFilter !== 'all' && row.kind !== categoryFilter) return false
    return true
  })

  const stats = useMemo(() => {
    const activeWebhooks = strategies.filter(
      (s) => s.lifecycle_state !== 'Archived' && s.is_active
    ).length
    const runningPython = pythonStrategies.filter(
      (p) => p.status === 'running' || p.status === 'scheduled'
    ).length
    const activeFlows = workflows.filter((w) => w.is_active).length
    return {
      total: unifiedRows.length,
      active: activeWebhooks + runningPython + activeFlows,
      webhook: strategies.filter((s) => s.lifecycle_state !== 'Archived').length,
      python: pythonStrategies.length,
      flow: workflows.length,
    }
  }, [strategies, pythonStrategies, workflows, unifiedRows])

  return (
    <div className="container mx-auto py-5 space-y-4 max-w-7xl px-4 sm:px-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <div>
          <h1 className="text-lg font-bold tracking-tight text-foreground">Strategies</h1>
          <p className="text-sm text-muted-foreground">
            All your strategies -- webhooks, Python, and Flow -- in one place.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" className="h-8 text-xs" onClick={fetchAll}>
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
            Refresh
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs"
            onClick={handleCreateOwnStrategy}
            disabled={creatingFlow}
          >
            <Wand2 className="h-3.5 w-3.5 mr-1.5" />
            Create Your Own Strategy
          </Button>
          <Button size="sm" className="h-8 text-xs" onClick={() => navigate('/strategy/new')}>
            <Plus className="h-3.5 w-3.5 mr-1.5" />
            New Strategy
          </Button>
        </div>
      </div>

      {/* Summary stats — compact inline row instead of tall cards */}
      <div className="flex flex-wrap items-stretch gap-2 rounded-lg border border-border bg-card/50 px-3 py-2">
        {[
          { label: 'Total', value: stats.total, icon: Zap },
          { label: 'Active', value: stats.active, icon: Play },
          { label: 'Webhooks', value: stats.webhook, icon: Webhook },
          { label: 'Python', value: stats.python, icon: Code2 },
          { label: 'Flow', value: stats.flow, icon: Layers },
        ].map(({ label, value, icon: Icon }, i, arr) => (
          <div key={label} className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <Icon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              <span className="text-xs text-muted-foreground">{label}</span>
              <span className="text-sm font-bold tabular-nums text-foreground">{value}</span>
            </div>
            {i < arr.length - 1 && <div className="h-4 w-px bg-border" />}
          </div>
        ))}
      </div>

      {/* Related tools + search + filters — single compact row */}
      <div className="flex flex-col lg:flex-row lg:items-center gap-2 lg:gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <Button variant="outline" size="sm" className="h-7 text-xs" asChild>
            <Link to="/marketplace">
              <Layers className="h-3 w-3 mr-1" />
              Templates
            </Link>
          </Button>
          <Button variant="outline" size="sm" className="h-7 text-xs" asChild>
            <Link
              to="/strategy/wizard"
              onMouseEnter={() => prefetchRoute('/strategy/wizard')}
              onFocus={() => prefetchRoute('/strategy/wizard')}
            >
              <Sparkles className="h-3 w-3 mr-1" />
              AI Wizard
            </Link>
          </Button>
          <Button variant="outline" size="sm" className="h-7 text-xs" asChild>
            <Link to="/python/new">
              <Code2 className="h-3 w-3 mr-1" />
              Add Python
            </Link>
          </Button>
          <Button variant="outline" size="sm" className="h-7 text-xs" asChild>
            <Link to="/backtest">
              <BarChart3 className="h-3 w-3 mr-1" />
              Backtest
            </Link>
          </Button>
          <Button variant="outline" size="sm" className="h-7 text-xs" asChild>
            <Link to="/tools/webhooks">
              <Webhook className="h-3 w-3 mr-1" />
              Webhooks Guide
            </Link>
          </Button>
        </div>

        <div className="hidden lg:block h-5 w-px bg-border" />

        <div className="flex flex-col sm:flex-row sm:items-center gap-2 lg:ml-auto">
          <div className="relative w-full sm:w-56">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Search strategies..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 h-7 text-xs"
            />
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Button
              variant={categoryFilter === 'all' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setCategoryFilter('all')}
              className="h-7 text-xs"
            >
              All
            </Button>
            <Button
              variant={categoryFilter === 'webhook' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setCategoryFilter('webhook')}
              className="h-7 text-xs"
            >
              Webhooks
            </Button>
            <Button
              variant={categoryFilter === 'python' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setCategoryFilter('python')}
              className="h-7 text-xs"
            >
              Python
            </Button>
            <Button
              variant={categoryFilter === 'flow' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setCategoryFilter('flow')}
              className="h-7 text-xs"
            >
              Flow
            </Button>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-48 w-full" />
          ))}
        </div>
      ) : filteredRows.length === 0 ? (
        <Card className="py-12">
          <CardContent className="flex flex-col items-center justify-center text-center">
            <Zap className="h-12 w-12 text-muted-foreground mb-4" />
            <h3 className="text-lg font-semibold mb-2">No Strategies Found</h3>
            <p className="text-muted-foreground mb-4">
              Create a new strategy, deploy one from the Marketplace, or subscribe to a Premium
              strategy to get started.
            </p>
            <Button onClick={() => navigate('/strategy/new')}>
              <Plus className="h-4 w-4 mr-2" />
              Create Strategy
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {filteredRows.map((row) => (
            <UnifiedStrategyCard
              key={`${row.kind}-${row.data.id}`}
              row={row}
              copiedId={copiedId}
              actionLoading={actionLoading}
              onCopyWebhook={copyWebhookUrl}
              onConfigureSymbols={() => {}}
              onBacktest={handleLaunchBacktest}
              onDeploy={async (strategy) => {
                setSelectedStrategyForDeploy(strategy)
                setDeployLegs([])
                setDeployDrawerOpen(true)
                setDeployLegsLoading(true)
                try {
                  const { mappings } = await strategyApi.getStrategy(strategy.id)
                  setDeployLegs(
                    (mappings || []).map((m) => ({
                      symbol: m.symbol,
                      exchange: m.exchange,
                      side: m.order_side || m.action || 'BUY',
                    }))
                  )
                } catch {
                  showToast.error('Failed to load strategy symbol mappings', 'strategy')
                } finally {
                  setDeployLegsLoading(false)
                }
              }}
              onPythonStart={handlePythonStart}
              onPythonStop={handlePythonStop}
              onFlowActivate={handleFlowActivate}
              onFlowDeactivate={handleFlowDeactivate}
            />
          ))}
        </div>
      )}

      {/* Portfolio Presets — a genuinely different artifact type (saved
          option-leg/payoff structures from the Options Strategy Builder,
          not a running process). Given its own bordered section with a
          visible gap above so it doesn't read as a continuation of the
          strategy card grid. */}
      <div className="mt-8 pt-6 border-t-2 border-border">
        <div className="rounded-lg border border-border bg-card/50 p-4 [&>div]:py-0">
          <h3 className="text-sm font-bold text-muted-foreground uppercase tracking-wider mb-4">
            Portfolio Presets
          </h3>
          <Suspense fallback={<Skeleton className="h-48 w-full" />}>
            <StrategyPortfolio />
          </Suspense>
        </div>
      </div>

      {/* Deployment Drawer — creates a real Draft deployment internally,
          runs a real dry-run against it, and this callback only activates
          the already-created row (see DeployStrategyDrawer's onActivate
          contract). legs is fetched from the strategy's real symbol
          mappings (strategyApi.getStrategy) when Deploy is clicked above —
          an empty array here means the strategy genuinely has no symbol
          mappings configured yet, not that they weren't loaded. */}
      <DeployStrategyDrawer
        open={deployDrawerOpen}
        onClose={() => setDeployDrawerOpen(false)}
        strategyName={selectedStrategyForDeploy?.name || ''}
        legs={deployLegs}
        legsLoading={deployLegsLoading}
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
