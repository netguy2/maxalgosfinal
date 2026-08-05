import {
  AlertCircle,
  BarChart3,
  ChevronDown,
  Code2,
  Layers,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Webhook,
  Zap,
} from 'lucide-react'
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { fetchCSRFToken } from '@/api/client'
import {
  activateWorkflow,
  deactivateWorkflow,
  listWorkflows,
  type WorkflowListItem,
} from '@/api/flow'
import { pythonStrategyApi } from '@/api/python-strategy'
import { strategyApi } from '@/api/strategy'
import { CommandPalette } from '@/components/strategy/CommandPalette'
import { StrategyInspector } from '@/components/strategy/StrategyInspector'
import { type UnifiedRow, UnifiedStrategyCard } from '@/components/strategy/UnifiedStrategyCard'
import { DeployStrategyDrawer } from '@/components/strategy-builder/DeployStrategyDrawer'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { CATALOG } from '@/lib/marketplace-catalog'
import type { PythonStrategy } from '@/types/python-strategy'
import type { Strategy } from '@/types/strategy'
import { showToast } from '@/utils/toast'

const StrategyPortfolio = lazy(() => import('@/pages/StrategyPortfolio'))

void import('@/pages/strategy/StrategyWizard')

type StatusFilter = 'all' | 'running' | 'stopped' | 'error'
type CategoryFilter = 'all' | 'webhook' | 'python' | 'flow'

export default function StrategyIndex() {
  const navigate = useNavigate()

  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [pythonStrategies, setPythonStrategies] = useState<PythonStrategy[]>([])
  const [workflows, setWorkflows] = useState<WorkflowListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  // Inspector
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [inspectedRow, setInspectedRow] = useState<UnifiedRow | null>(null)

  // Filters — single combined filter bar
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('all')
  const [searchQuery, setSearchQuery] = useState('')

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

  const fetchAll = async () => {
    const [webhookRes, pythonRes, flowRes] = await Promise.allSettled([
      strategyApi.getStrategies(),
      pythonStrategyApi.getStrategies(),
      listWorkflows(),
    ])
    if (webhookRes.status === 'fulfilled') setStrategies(webhookRes.value)
    if (pythonRes.status === 'fulfilled') setPythonStrategies(pythonRes.value)
    if (flowRes.status === 'fulfilled') setWorkflows(flowRes.value)
    setLoading(false)
  }

  const [searchParams, setSearchParams] = useSearchParams()

  useEffect(() => {
    const fetchHostConfig = async () => {
      try {
        const response = await fetch('/api/config/host', { credentials: 'include' })
        const data = await response.json()
        setHostConfig(data)
      } catch {
        setHostConfig({
          host_server: window.location.origin,
          is_localhost:
            window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1',
        })
      }
    }
    fetchHostConfig()
    fetchAll()
    const pollInterval = setInterval(fetchAll, 6000)
    return () => clearInterval(pollInterval)
    // biome-ignore lint/correctness/useExhaustiveDependencies: fetchAll is stable
  }, [])

  // Ctrl+K command palette
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setCommandPaletteOpen((p) => !p)
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [])

  const installingRef = useRef(false)
  useEffect(() => {
    const templateId = searchParams.get('template')
    if (!templateId || installingRef.current) return
    installingRef.current = true
    const catalogItem = CATALOG.find((c) => c.id === templateId)
    searchParams.delete('template')
    setSearchParams(searchParams, { replace: true })
    if (catalogItem) {
      const run = async () => {
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
            showToast.success(`Installed: ${catalogItem.name}`, 'strategy')
            fetchAll()
          } else {
            showToast.error(resp.message || 'Failed to install template', 'strategy')
          }
        } catch {
          showToast.error(`Failed to install: ${catalogItem.name}`, 'strategy')
        } finally {
          installingRef.current = false
        }
      }
      run()
    } else {
      installingRef.current = false
    }
    // biome-ignore lint/correctness/useExhaustiveDependencies: fetchAll is stable
  }, [searchParams, setSearchParams])

  const getWebhookUrl = (webhookId: string) => {
    const base = hostConfig?.host_server || window.location.origin
    return `${base}/strategy/webhook/${webhookId}`
  }

  const copyWebhookUrl = async (webhookId: string) => {
    try {
      await navigator.clipboard.writeText(getWebhookUrl(webhookId))
      setCopiedId(webhookId)
      showToast.success('Webhook URL copied', 'clipboard')
      setTimeout(() => setCopiedId(null), 2000)
    } catch {
      showToast.error('Failed to copy URL', 'clipboard')
    }
  }

  const handlePythonStart = async (strategy: PythonStrategy) => {
    try {
      setActionLoading(strategy.id)
      const r = await pythonStrategyApi.startStrategy(strategy.id)
      if (r.status === 'success') {
        showToast.success(r.message || `${strategy.name} started`, 'strategy')
        fetchAll()
      } else {
        showToast.error(r.message || 'Failed to start', 'strategy')
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
      const r = await pythonStrategyApi.stopStrategy(strategy.id)
      if (r.status === 'success') {
        showToast.success(r.message || `${strategy.name} stopped`, 'strategy')
        fetchAll()
      } else {
        showToast.error(r.message || 'Failed to stop', 'strategy')
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
      const r = await activateWorkflow(workflow.id)
      if (r.status === 'success') {
        showToast.success(r.message || `${workflow.name} activated`, 'strategy')
        fetchAll()
      } else {
        showToast.error(r.message || 'Failed to activate', 'strategy')
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
      const r = await deactivateWorkflow(workflow.id)
      if (r.status === 'success') {
        showToast.success(r.message || `${workflow.name} deactivated`, 'strategy')
        fetchAll()
      } else {
        showToast.error(r.message || 'Failed to deactivate', 'strategy')
      }
    } catch {
      showToast.error('Failed to deactivate workflow', 'strategy')
    } finally {
      setActionLoading(null)
    }
  }

  const unifiedRows = useMemo((): UnifiedRow[] => {
    const webhookRows: UnifiedRow[] = strategies
      .filter((s) => s.lifecycle_state !== 'Archived' && s.signal_source !== 'MaxHook')
      .map((data) => ({ kind: 'webhook' as const, data }))
    const pythonRows: UnifiedRow[] = pythonStrategies.map((data) => ({
      kind: 'python' as const,
      data,
    }))
    const flowRows: UnifiedRow[] = workflows.map((data) => ({ kind: 'flow' as const, data }))
    return [...webhookRows, ...pythonRows, ...flowRows]
  }, [strategies, pythonStrategies, workflows])

  const isRowRunning = (row: UnifiedRow): boolean => {
    if (row.kind === 'webhook') return row.data.is_active
    if (row.kind === 'python')
      return row.data.status === 'running' || row.data.status === 'scheduled'
    if (row.kind === 'flow') return row.data.is_active
    return false
  }

  const isRowError = (row: UnifiedRow): boolean => {
    if (row.kind === 'python')
      return Boolean(row.data.error_message || row.data.status === 'error')
    return false
  }

  const getRowKey = (row: UnifiedRow) => `${row.kind}-${row.data.id}`

  const filteredRows = useMemo(() => {
    return unifiedRows.filter((row) => {
      const name = row.data.name
      if (searchQuery && !name.toLowerCase().includes(searchQuery.toLowerCase())) return false
      if (categoryFilter !== 'all' && row.kind !== categoryFilter) return false
      if (statusFilter === 'running' && !isRowRunning(row)) return false
      if (statusFilter === 'stopped' && (isRowRunning(row) || isRowError(row))) return false
      if (statusFilter === 'error' && !isRowError(row)) return false
      return true
    })
  }, [unifiedRows, searchQuery, categoryFilter, statusFilter])

  const runningRows = useMemo(() => filteredRows.filter(isRowRunning), [filteredRows])
  const errorRows = useMemo(
    () => filteredRows.filter((r) => isRowError(r) && !isRowRunning(r)),
    [filteredRows]
  )
  const stoppedRows = useMemo(
    () => filteredRows.filter((r) => !isRowRunning(r) && !isRowError(r)),
    [filteredRows]
  )

  const stats = useMemo(() => {
    const running = unifiedRows.filter(isRowRunning).length
    const errors = unifiedRows.filter(isRowError).length
    return { total: unifiedRows.length, running, stopped: unifiedRows.length - running, errors }
  }, [unifiedRows])

  const handleInspect = (row: UnifiedRow) => {
    setInspectedRow(row)
    setInspectorOpen(true)
  }

  const handleDeploy = async (strategy: Strategy) => {
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
      showToast.error('Failed to load symbol mappings', 'strategy')
    } finally {
      setDeployLegsLoading(false)
    }
  }

  // Pill filter list
  const filterPills: { id: string; label: string; type: 'status' | 'category' }[] = [
    { id: 'all', label: 'All', type: 'status' },
    { id: 'running', label: 'Running', type: 'status' },
    { id: 'stopped', label: 'Stopped', type: 'status' },
    { id: 'error', label: 'Errors', type: 'status' },
    { id: 'webhook', label: 'Webhook', type: 'category' },
    { id: 'python', label: 'Python', type: 'category' },
    { id: 'flow', label: 'Flow', type: 'category' },
  ]

  const isPillActive = (pill: (typeof filterPills)[0]) => {
    if (pill.type === 'status') return statusFilter === pill.id
    return categoryFilter === pill.id
  }

  const handlePillClick = (pill: (typeof filterPills)[0]) => {
    if (pill.type === 'status') {
      setStatusFilter(pill.id as StatusFilter)
      if (pill.id !== 'all') setCategoryFilter('all')
    } else {
      setCategoryFilter(pill.id as CategoryFilter)
      if (pill.id !== 'all') setStatusFilter('all')
    }
  }

  const cardProps = {
    copiedId,
    actionLoading,
    onInspect: handleInspect,
    onCopyWebhook: copyWebhookUrl,
    onConfigureSymbols: (id: number) => navigate(`/strategy/${id}/mappings`),
    onBacktest: (s: Strategy) => navigate(`/backtest?strategy=${s.id}`),
    onDeploy: handleDeploy,
    onPythonStart: handlePythonStart,
    onPythonStop: handlePythonStop,
    onFlowActivate: handleFlowActivate,
    onFlowDeactivate: handleFlowDeactivate,
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 py-8 space-y-6">

      {/* ── Header ── */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Strategies</h1>
          {/* Compact summary line */}
          {!loading && (
            <p className="text-sm text-muted-foreground mt-0.5">
              {stats.total} strategies
              <span className="mx-1.5 opacity-30">•</span>
              <span className="text-profit font-medium">{stats.running} running</span>
              <span className="mx-1.5 opacity-30">•</span>
              {stats.stopped} stopped
              {stats.errors > 0 && (
                <>
                  <span className="mx-1.5 opacity-30">•</span>
                  <span className="text-destructive font-medium">{stats.errors} errors</span>
                </>
              )}
            </p>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={fetchAll}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1.5"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>

          {/* New Strategy dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" className="gap-1.5">
                <Plus className="h-4 w-4" />
                New Strategy
                <ChevronDown className="h-3.5 w-3.5 opacity-70" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52">
              <DropdownMenuItem onClick={() => navigate('/strategy/new')}>
                <Webhook className="h-4 w-4 mr-2 text-muted-foreground" />
                Webhook Strategy
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate('/python/new')}>
                <Code2 className="h-4 w-4 mr-2 text-muted-foreground" />
                Python Script
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate('/flow/new')}>
                <Zap className="h-4 w-4 mr-2 text-muted-foreground" />
                Visual Flow
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => navigate('/marketplace')}>
                <Layers className="h-4 w-4 mr-2 text-muted-foreground" />
                Browse Templates
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate('/strategy/wizard')}>
                <Sparkles className="h-4 w-4 mr-2 text-muted-foreground" />
                AI Strategy Wizard
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate('/backtest')}>
                <BarChart3 className="h-4 w-4 mr-2 text-muted-foreground" />
                Backtest Engine
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* ── Single Filter Row ── */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-48 max-w-64">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search strategies..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8 h-8 text-sm"
          />
        </div>

        <div className="flex flex-wrap items-center gap-1">
          {filterPills.map((pill) => {
            const active = isPillActive(pill)
            return (
              <button
                key={`${pill.type}-${pill.id}`}
                type="button"
                onClick={() => handlePillClick(pill)}
                className={`h-7 px-3 text-xs rounded-full font-medium transition-colors ${
                  active
                    ? 'bg-foreground text-background'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                }`}
              >
                {pill.label}
              </button>
            )
          })}
        </div>

        {/* Ctrl+K hint */}
        <button
          type="button"
          onClick={() => setCommandPaletteOpen(true)}
          className="ml-auto text-[11px] text-muted-foreground/60 hover:text-muted-foreground transition-colors flex items-center gap-1"
          title="Open command palette"
        >
          <kbd className="font-mono bg-muted border border-border rounded px-1 py-0.5 text-[10px]">
            ⌘K
          </kbd>
        </button>
      </div>

      {/* ── Strategy Groups ── */}
      {loading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <Skeleton key={i} className="h-32 w-full rounded-xl" />
          ))}
        </div>
      ) : filteredRows.length === 0 ? (
        <div className="py-20 text-center text-muted-foreground text-sm">
          <p>No strategies found.</p>
          <Button
            variant="link"
            className="mt-2 text-sm"
            onClick={() => {
              setSearchQuery('')
              setStatusFilter('all')
              setCategoryFilter('all')
            }}
          >
            Clear filters
          </Button>
        </div>
      ) : (
        <div className="space-y-8">
          {/* Running */}
          {runningRows.length > 0 && (
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-profit animate-pulse" />
                <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Running ({runningRows.length})
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {runningRows.map((row) => (
                  <UnifiedStrategyCard key={getRowKey(row)} row={row} {...cardProps} />
                ))}
              </div>
            </section>
          )}

          {/* Errors */}
          {errorRows.length > 0 && (
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <AlertCircle className="h-3.5 w-3.5 text-destructive" />
                <span className="text-xs font-semibold uppercase tracking-wider text-destructive">
                  Errors ({errorRows.length})
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {errorRows.map((row) => (
                  <UnifiedStrategyCard key={getRowKey(row)} row={row} {...cardProps} />
                ))}
              </div>
            </section>
          )}

          {/* Stopped */}
          {stoppedRows.length > 0 && (
            <section className="space-y-3">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-muted-foreground/30" />
                <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Stopped ({stoppedRows.length})
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {stoppedRows.map((row) => (
                  <UnifiedStrategyCard key={getRowKey(row)} row={row} {...cardProps} />
                ))}
              </div>
            </section>
          )}
        </div>
      )}

      {/* Portfolio Presets — separate lazy section below all strategies */}
      <section className="pt-6 border-t border-border">
        <details>
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors list-none flex items-center gap-2">
            <Layers className="h-3.5 w-3.5" />
            Portfolio Presets
          </summary>
          <div className="mt-4">
            <Suspense fallback={<Skeleton className="h-48 w-full" />}>
              <StrategyPortfolio />
            </Suspense>
          </div>
        </details>
      </section>

      {/* Command Palette */}
      <CommandPalette
        open={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        rows={unifiedRows}
        onInspect={handleInspect}
        onDeploy={(r) => handleDeploy(r.data as Strategy)}
        onBacktest={(r) => navigate(`/backtest?strategy=${r.data.id}`)}
      />

      {/* Strategy Inspector */}
      <StrategyInspector
        open={inspectorOpen}
        onClose={() => setInspectorOpen(false)}
        row={inspectedRow}
        copiedId={copiedId}
        actionLoading={actionLoading}
        onCopyWebhook={copyWebhookUrl}
        onBacktest={(s) => navigate(`/backtest?strategy=${s.id}`)}
        onDeploy={async (s) => {
          setInspectorOpen(false)
          await handleDeploy(s)
        }}
        onPythonStart={handlePythonStart}
        onPythonStop={handlePythonStop}
        onFlowActivate={handleFlowActivate}
        onFlowDeactivate={handleFlowDeactivate}
        getWebhookUrl={getWebhookUrl}
      />

      {/* Deploy Drawer */}
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
              headers: { 'X-CSRFToken': csrfToken },
            })
            const data = await res.json()
            if (data.status === 'error') {
              showToast.error(data.message || 'Activation failed', 'strategy')
            } else {
              showToast.success('Strategy deployed!', 'strategy')
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
