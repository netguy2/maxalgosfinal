import {
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
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { fetchCSRFToken } from '@/api/client'
import { listWorkflows, type WorkflowListItem } from '@/api/flow'
import { pythonStrategyApi } from '@/api/python-strategy'
import { strategyApi } from '@/api/strategy'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
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

void import('@/pages/strategy/StrategyWizard')

type CategoryFilter = 'all' | 'automated' | 'webhook' | 'python' | 'flow'

function isConditionStrategy(s: Strategy): boolean {
  return Boolean(
    s.template_id ||
      s.platform === 'Custom' ||
      s.platform === 'wizard' ||
      s.signal_source === 'ConditionEngine' ||
      s.signal_source === 'Custom'
  )
}

export default function StrategyIndex() {
  const navigate = useNavigate()

  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [pythonStrategies, setPythonStrategies] = useState<PythonStrategy[]>([])
  const [workflows, setWorkflows] = useState<WorkflowListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  // Deployment counts for each strategy (client-side join)
  const [deploymentCounts, setDeploymentCounts] = useState<Record<number, number>>({})

  // Inspector
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [inspectedRow, setInspectedRow] = useState<UnifiedRow | null>(null)

  // Filter — category only (no status)
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

  // Fetch active deployment counts
  const fetchDeploymentCounts = async () => {
    try {
      const res = await fetch('/api/v1/deployments')
      if (!res.ok) return
      const data: Array<{ strategy_id: number; status: string }> = await res.json()
      const counts: Record<number, number> = {}
      for (const d of data) {
        const s = d.status?.toLowerCase()
        if (s === 'running' || s === 'waiting' || s === 'managing' || s === 'entering') {
          counts[d.strategy_id] = (counts[d.strategy_id] || 0) + 1
        }
      }
      setDeploymentCounts(counts)
    } catch {
      // non-critical
    }
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
    fetchDeploymentCounts()
    const pollInterval = setInterval(fetchAll, 8000)
    return () => clearInterval(pollInterval)
    // biome-ignore lint/correctness/useExhaustiveDependencies: fetchAll is stable
  }, [fetchAll, fetchDeploymentCounts])

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
            template_id: catalogItem.id,
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
  }, [searchParams, setSearchParams, fetchAll])

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

  const handleInspect = (row: UnifiedRow) => {
    setInspectedRow(row)
    setInspectorOpen(true)
  }

  const unifiedRows = useMemo((): UnifiedRow[] => {
    const stratRows: UnifiedRow[] = strategies
      .filter((s) => s.lifecycle_state !== 'Archived' && s.signal_source !== 'MaxHook')
      .map((data) => ({
        kind: isConditionStrategy(data) ? ('automated' as const) : ('webhook' as const),
        data,
      }))
    const pythonRows: UnifiedRow[] = pythonStrategies.map((data) => ({
      kind: 'python' as const,
      data,
    }))
    const flowRows: UnifiedRow[] = workflows.map((data) => ({ kind: 'flow' as const, data }))
    return [...stratRows, ...pythonRows, ...flowRows]
  }, [strategies, pythonStrategies, workflows])

  const filteredRows = useMemo(() => {
    return unifiedRows.filter((row) => {
      if (searchQuery && !row.data.name.toLowerCase().includes(searchQuery.toLowerCase()))
        return false
      if (categoryFilter !== 'all' && row.kind !== categoryFilter) return false
      return true
    })
  }, [unifiedRows, searchQuery, categoryFilter])

  const stats = useMemo(() => {
    const validStrats = strategies.filter(
      (s) => s.lifecycle_state !== 'Archived' && s.signal_source !== 'MaxHook'
    )
    const automated = validStrats.filter(isConditionStrategy).length
    const webhook = validStrats.length - automated
    const python = pythonStrategies.length
    const flow = workflows.length
    return { total: automated + webhook + python + flow, automated, webhook, python, flow }
  }, [strategies, pythonStrategies, workflows])

  const getRowKey = (row: UnifiedRow) => `${row.kind}-${row.data.id}`

  const getActiveDeploymentCount = (row: UnifiedRow): number => {
    if (row.kind !== 'automated' && row.kind !== 'webhook') return 0
    return deploymentCounts[(row.data as Strategy).id] || 0
  }

  type FilterPill = { id: CategoryFilter; label: string }
  const filterPills: FilterPill[] = [
    { id: 'all', label: 'All' },
    { id: 'automated', label: 'Automated' },
    { id: 'webhook', label: 'Webhook' },
    { id: 'python', label: 'Python' },
    { id: 'flow', label: 'Flow' },
  ]

  // void copiedId
  void copiedId

  const handleRefresh = () => {
    fetchAll()
    fetchDeploymentCounts()
  }

  return (
    <PageContainer>
      {/* ── Header ── */}
      <PageHeader
        title="Strategy Library"
        description={
          !loading && (
            <>
              {stats.total} strategies
              {stats.automated > 0 && (
                <>
                  {' '}
                  <span className="opacity-30 mx-1">·</span> {stats.automated} automated
                </>
              )}
              {stats.webhook > 0 && (
                <>
                  {' '}
                  <span className="opacity-30 mx-1">·</span> {stats.webhook} webhook
                </>
              )}
              {stats.python > 0 && (
                <>
                  {' '}
                  <span className="opacity-30 mx-1">·</span> {stats.python} python
                </>
              )}
              {stats.flow > 0 && (
                <>
                  {' '}
                  <span className="opacity-30 mx-1">·</span> {stats.flow} flow
                </>
              )}
            </>
          )
        }
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleRefresh}
              className="text-sm text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1.5"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </button>

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
        }
      />

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

        <div className="flex items-center gap-1">
          {filterPills.map((pill) => {
            const active = categoryFilter === pill.id
            return (
              <button
                key={pill.id}
                type="button"
                onClick={() => setCategoryFilter(pill.id)}
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

        <button
          type="button"
          onClick={() => setCommandPaletteOpen(true)}
          className="ml-auto text-[11px] text-muted-foreground/60 hover:text-muted-foreground transition-colors flex items-center gap-1"
          title="Open command palette (⌘K)"
        >
          <kbd className="font-mono bg-muted border border-border rounded px-1 py-0.5 text-[10px]">
            ⌘K
          </kbd>
        </button>
      </div>

      {/* ── Strategy Grid ── */}
      {loading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <Skeleton key={i} className="h-28 w-full rounded-xl" />
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
              setCategoryFilter('all')
            }}
          >
            Clear filters
          </Button>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filteredRows.map((row) => (
            <UnifiedStrategyCard
              key={getRowKey(row)}
              row={row}
              activeDeploymentCount={getActiveDeploymentCount(row)}
              onInspect={handleInspect}
              onCopyWebhook={copyWebhookUrl}
              onConfigureSymbols={(id) => navigate(`/strategy/${id}/mappings`)}
              onBacktest={(s) => navigate(`/backtest?strategy=${s.id}`)}
              onDeploy={handleDeploy}
            />
          ))}
        </div>
      )}

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
        actionLoading={null}
        onCopyWebhook={copyWebhookUrl}
        onBacktest={(s) => navigate(`/backtest?strategy=${s.id}`)}
        onDeploy={async (s) => {
          setInspectorOpen(false)
          await handleDeploy(s)
        }}
        onPythonStart={async () => {}}
        onPythonStop={async () => {}}
        onFlowActivate={async () => {}}
        onFlowDeactivate={async () => {}}
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
              showToast.success('Strategy deployed! Manage it in Live Deployments.', 'strategy')
              setDeployDrawerOpen(false)
              navigate('/deployments')
            }
          } catch {
            showToast.error('Failed to activate deployment', 'strategy')
          }
        }}
      />
    </PageContainer>
  )
}
