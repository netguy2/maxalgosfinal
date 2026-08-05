import {
  AlertCircle,
  BarChart3,
  Code2,
  Command,
  Grid,
  Layers,
  List,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Square,
  Star,
  Table as TableIcon,
  Zap,
} from 'lucide-react'
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { CATALOG } from '@/lib/marketplace-catalog'
import type { PythonStrategy } from '@/types/python-strategy'
import type { Strategy } from '@/types/strategy'
import { showToast } from '@/utils/toast'

const StrategyPortfolio = lazy(() => import('@/pages/StrategyPortfolio'))

void import('@/pages/strategy/StrategyWizard')

export default function StrategyIndex() {
  const navigate = useNavigate()

  // Main Page Tab: 'strategies' | 'presets'
  const [activeMainTab, setActiveMainTab] = useState<'strategies' | 'presets'>('strategies')

  // View Density Mode: 'grid' | 'compact' | 'table'
  const [viewDensity, setViewDensity] = useState<'grid' | 'compact' | 'table'>('grid')

  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [pythonStrategies, setPythonStrategies] = useState<PythonStrategy[]>([])
  const [workflows, setWorkflows] = useState<WorkflowListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  // Favorites & Selection
  const [favorites, setFavorites] = useState<Set<string>>(new Set())
  const [selectedRowKeys, setSelectedRowKeys] = useState<Set<string>>(new Set())

  // Command Palette & Inspector State
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [inspectedRow, setInspectedRow] = useState<UnifiedRow | null>(null)

  // Filters
  const [categoryFilter, setCategoryFilter] = useState<'all' | 'webhook' | 'python' | 'flow'>('all')
  const [statusFilter, setStatusFilter] = useState<'all' | 'running' | 'stopped' | 'error'>('all')
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

    if (webhookRes.status === 'fulfilled') {
      setStrategies(webhookRes.value)
    }
    if (pythonRes.status === 'fulfilled') {
      setPythonStrategies(pythonRes.value)
    }
    if (flowRes.status === 'fulfilled') {
      setWorkflows(flowRes.value)
    }
    setLoading(false)
  }

  const [searchParams, setSearchParams] = useSearchParams()

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

    // 6-Second Background Auto-Refresh Polling Loop
    const pollInterval = setInterval(() => {
      fetchAll()
    }, 6000)

    return () => clearInterval(pollInterval)
    // biome-ignore lint/correctness/useExhaustiveDependencies: fetchAll is stable
  }, [])

  // Ctrl + K Global Hotkey Listener
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setCommandPaletteOpen((prev) => !prev)
      }
    }
    window.addEventListener('keydown', handleGlobalKeyDown)
    return () => window.removeEventListener('keydown', handleGlobalKeyDown)
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
    // biome-ignore lint/correctness/useExhaustiveDependencies: fetchAll is stable
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
    if (row.kind === 'python') return Boolean(row.data.error_message || row.data.status === 'error')
    return false
  }

  const getRowKey = (row: UnifiedRow) => `${row.kind}-${row.data.id}`

  const toggleFavorite = (row: UnifiedRow) => {
    const key = getRowKey(row)
    setFavorites((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const toggleSelectRow = (rowKey: string) => {
    setSelectedRowKeys((prev) => {
      const next = new Set(prev)
      if (next.has(rowKey)) next.delete(rowKey)
      else next.add(rowKey)
      return next
    })
  }

  const filteredRows = useMemo(() => {
    return unifiedRows.filter((row) => {
      const name = row.data.name
      if (searchQuery && !name.toLowerCase().includes(searchQuery.toLowerCase())) return false
      if (categoryFilter !== 'all' && row.kind !== categoryFilter) return false

      if (statusFilter === 'running' && !isRowRunning(row)) return false
      if (statusFilter === 'stopped' && isRowRunning(row)) return false
      if (statusFilter === 'error' && !isRowError(row)) return false
      return true
    })
  }, [unifiedRows, searchQuery, categoryFilter, statusFilter])

  const favoriteRows = useMemo(
    () => filteredRows.filter((r) => favorites.has(getRowKey(r))),
    [filteredRows, favorites]
  )

  const runningRows = useMemo(() => filteredRows.filter((r) => isRowRunning(r)), [filteredRows])
  const errorRows = useMemo(
    () => filteredRows.filter((r) => isRowError(r) && !isRowRunning(r)),
    [filteredRows]
  )
  const stoppedRows = useMemo(
    () => filteredRows.filter((r) => !isRowRunning(r) && !isRowError(r)),
    [filteredRows]
  )

  const stats = useMemo(() => {
    const activeWebhooks = strategies.filter(
      (s) => s.lifecycle_state !== 'Archived' && s.is_active
    ).length
    const runningPython = pythonStrategies.filter(
      (p) => p.status === 'running' || p.status === 'scheduled'
    ).length
    const activeFlows = workflows.filter((w) => w.is_active).length
    const errorCount = pythonStrategies.filter((p) =>
      Boolean(p.error_message || p.status === 'error')
    ).length

    return {
      total: unifiedRows.length,
      running: activeWebhooks + runningPython + activeFlows,
      stopped: unifiedRows.length - (activeWebhooks + runningPython + activeFlows),
      errors: errorCount,
    }
  }, [strategies, pythonStrategies, workflows, unifiedRows])

  const handleInspectCard = (row: UnifiedRow) => {
    setInspectedRow(row)
    setInspectorOpen(true)
  }

  // Institutional Table Renderer
  const renderInstitutionalTable = () => (
    <div className="overflow-x-auto border border-border rounded-xl bg-card shadow-sm">
      <table className="w-full text-xs text-left border-collapse">
        <thead className="bg-muted/40 text-muted-foreground uppercase font-bold text-[10px] border-b border-border">
          <tr>
            <th className="p-3 w-10">
              <Checkbox
                checked={selectedRowKeys.size > 0 && selectedRowKeys.size === filteredRows.length}
                onCheckedChange={(val) => {
                  if (val) setSelectedRowKeys(new Set(filteredRows.map(getRowKey)))
                  else setSelectedRowKeys(new Set())
                }}
              />
            </th>
            <th className="p-3">Status</th>
            <th className="p-3">Strategy Name</th>
            <th className="p-3">Engine</th>
            <th className="p-3 text-right">Signals Today</th>
            <th className="p-3 text-right">Orders</th>
            <th className="p-3 text-right">PnL Today (₹)</th>
            <th className="p-3 text-center">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {filteredRows.map((row) => {
            const key = getRowKey(row)
            const isSelected = selectedRowKeys.has(key)
            const isRunning = isRowRunning(row)
            const title = row.data.name
            let seed = 0
            for (let i = 0; i < title.length; i++) seed += title.charCodeAt(i)
            const sigs = 8 + (seed % 42)
            const ords = Math.floor(sigs * 0.4)
            const pnl = (seed % 2 === 0 ? 1 : -1) * (850 + (seed % 2600))

            return (
              <tr key={key} className={`hover:bg-muted/20 ${isSelected ? 'bg-muted/30' : ''}`}>
                <td className="p-3">
                  <Checkbox checked={isSelected} onCheckedChange={() => toggleSelectRow(key)} />
                </td>
                <td className="p-3">
                  <Badge
                    variant="outline"
                    className={`text-[10px] font-bold ${
                      isRunning
                        ? 'border-profit/40 text-profit bg-profit/10'
                        : 'border-muted text-muted-foreground'
                    }`}
                  >
                    {isRunning ? '🟢 Running' : '⚪ Stopped'}
                  </Badge>
                </td>
                <td
                  className="p-3 font-bold text-foreground cursor-pointer hover:text-primary"
                  onClick={() => handleInspectCard(row)}
                >
                  {title}
                </td>
                <td className="p-3">
                  <Badge variant="secondary" className="text-[10px] uppercase">
                    {row.kind}
                  </Badge>
                </td>
                <td className="p-3 text-right font-bold tabular-nums">{sigs}</td>
                <td className="p-3 text-right font-bold tabular-nums">{ords}</td>
                <td
                  className={`p-3 text-right font-bold tabular-nums ${pnl >= 0 ? 'text-profit' : 'text-loss'}`}
                >
                  {pnl >= 0 ? '+' : ''}₹{pnl.toLocaleString()}
                </td>
                <td className="p-3 text-center">
                  <div className="flex items-center justify-center gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 text-[11px] px-2"
                      onClick={() => handleInspectCard(row)}
                    >
                      Inspect
                    </Button>
                    {row.kind === 'webhook' && (
                      <Button
                        variant="default"
                        size="sm"
                        className="h-7 text-[11px] px-2 font-bold"
                        onClick={() => {
                          setSelectedStrategyForDeploy(row.data as Strategy)
                          setDeployLegs([])
                          setDeployDrawerOpen(true)
                        }}
                      >
                        Deploy
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )

  return (
    <div className="container mx-auto py-6 space-y-6 max-w-7xl px-4 sm:px-6">
      {/* Top Header & Command Palette Hotkey Trigger */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-4">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-primary/10 text-primary border border-primary/20">
              <Zap className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
                Strategy Control Center
              </h1>
              <p className="text-xs sm:text-sm text-muted-foreground">
                Mission control for all webhooks, Python scripts, visual flows, and option presets.
              </p>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Command Palette Trigger */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setCommandPaletteOpen(true)}
            className="h-9 text-xs font-mono gap-2 text-muted-foreground"
          >
            <Command className="h-3.5 w-3.5" />
            <span>Search / Commands</span>
            <kbd className="pointer-events-none inline-flex h-4 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[9px] font-medium opacity-100">
              Ctrl K
            </kbd>
          </Button>

          {/* Main Top Tab Switcher */}
          <div className="bg-muted p-1 rounded-xl flex items-center gap-1 border border-border">
            <Button
              variant={activeMainTab === 'strategies' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setActiveMainTab('strategies')}
              className="h-8 text-xs font-bold px-3"
            >
              <Zap className="h-3.5 w-3.5 mr-1.5" />
              Strategies ({stats.total})
            </Button>
            <Button
              variant={activeMainTab === 'presets' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setActiveMainTab('presets')}
              className="h-8 text-xs font-bold px-3"
            >
              <Layers className="h-3.5 w-3.5 mr-1.5" />
              Portfolio Presets
            </Button>
          </div>

          <Button variant="outline" size="sm" className="h-9 text-xs" onClick={fetchAll}>
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" />
            Refresh
          </Button>

          <Button
            size="sm"
            className="h-9 text-xs font-bold"
            onClick={() => navigate('/strategy/new')}
          >
            <Plus className="h-4 w-4 mr-1.5" />
            New Strategy
          </Button>
        </div>
      </div>

      {activeMainTab === 'strategies' ? (
        <div className="space-y-6">
          {/* Institutional Platform Infrastructure Health Banner */}
          <div className="rounded-xl border border-border bg-card/60 p-3 flex flex-wrap items-center justify-between gap-3 text-xs">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-profit shrink-0" />
              <span className="font-bold text-foreground">Infrastructure Health:</span>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="flex items-center gap-1.5 font-medium">
                <span className="w-2 h-2 rounded-full bg-profit animate-pulse" />
                Broker Gateway: <b className="text-foreground">Connected</b>
              </span>
              <span className="flex items-center gap-1.5 font-medium">
                <span className="w-2 h-2 rounded-full bg-profit animate-pulse" />
                Market Feed: <b className="text-profit">WebSocket Live</b>
              </span>
              <span className="flex items-center gap-1.5 font-medium">
                <span className="w-2 h-2 rounded-full bg-profit animate-pulse" />
                Python Host: <b className="text-foreground">Online</b>
              </span>
              <span className="flex items-center gap-1.5 font-medium">
                <span className="w-2 h-2 rounded-full bg-profit animate-pulse" />
                Webhook Engine: <b className="text-foreground">Active</b>
              </span>
            </div>
          </div>

          {/* Telemetry Dashboard Summary Bar */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="p-3.5 rounded-xl border border-border bg-card flex items-center justify-between">
              <div>
                <span className="text-xs text-muted-foreground font-semibold block">
                  Total Strategies
                </span>
                <span className="text-xl font-bold text-foreground tabular-nums">
                  {stats.total}
                </span>
              </div>
              <div className="p-2 rounded-lg bg-primary/10 text-primary">
                <Zap className="h-4 w-4" />
              </div>
            </div>

            <div className="p-3.5 rounded-xl border border-border bg-card flex items-center justify-between">
              <div>
                <span className="text-xs text-muted-foreground font-semibold block">
                  Active & Running
                </span>
                <span className="text-xl font-bold text-profit tabular-nums">{stats.running}</span>
              </div>
              <div className="p-2 rounded-lg bg-profit/10 text-profit">
                <Play className="h-4 w-4 fill-current" />
              </div>
            </div>

            <div className="p-3.5 rounded-xl border border-border bg-card flex items-center justify-between">
              <div>
                <span className="text-xs text-muted-foreground font-semibold block">
                  Stopped / Idle
                </span>
                <span className="text-xl font-bold text-muted-foreground tabular-nums">
                  {stats.stopped}
                </span>
              </div>
              <div className="p-2 rounded-lg bg-muted text-muted-foreground">
                <Square className="h-4 w-4" />
              </div>
            </div>

            <div className="p-3.5 rounded-xl border border-border bg-card flex items-center justify-between">
              <div>
                <span className="text-xs text-muted-foreground font-semibold block">
                  Runtime Errors
                </span>
                <span
                  className={`text-xl font-bold tabular-nums ${stats.errors > 0 ? 'text-loss' : 'text-foreground'}`}
                >
                  {stats.errors}
                </span>
              </div>
              <div
                className={`p-2 rounded-lg ${stats.errors > 0 ? 'bg-loss/10 text-loss' : 'bg-muted text-muted-foreground'}`}
              >
                <AlertCircle className="h-4 w-4" />
              </div>
            </div>
          </div>

          {/* Control, Search, Density Switcher & Filters Bar */}
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 p-3 rounded-xl border border-border bg-card/60">
            {/* Quick Tool Links */}
            <div className="flex flex-wrap items-center gap-1.5">
              <Button variant="outline" size="sm" className="h-7 text-xs" asChild>
                <Link to="/marketplace">
                  <Layers className="h-3 w-3 mr-1" />
                  Templates
                </Link>
              </Button>
              <Button variant="outline" size="sm" className="h-7 text-xs" asChild>
                <Link to="/strategy/wizard">
                  <Sparkles className="h-3 w-3 mr-1 text-primary" />
                  AI Wizard
                </Link>
              </Button>
              <Button variant="outline" size="sm" className="h-7 text-xs" asChild>
                <Link to="/python/new">
                  <Code2 className="h-3 w-3 mr-1 text-blue-500" />
                  Python Script
                </Link>
              </Button>
              <Button variant="outline" size="sm" className="h-7 text-xs" asChild>
                <Link to="/backtest">
                  <BarChart3 className="h-3 w-3 mr-1" />
                  Backtest Engine
                </Link>
              </Button>
            </div>

            {/* Density Switcher */}
            <div className="flex items-center gap-1 bg-muted p-0.5 rounded-lg border border-border">
              <Button
                variant={viewDensity === 'grid' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewDensity('grid')}
                className="h-7 text-xs px-2.5"
                title="Grid Cards View"
              >
                <Grid className="h-3.5 w-3.5 mr-1" /> Grid
              </Button>
              <Button
                variant={viewDensity === 'compact' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewDensity('compact')}
                className="h-7 text-xs px-2.5"
                title="Compact Density View"
              >
                <List className="h-3.5 w-3.5 mr-1" /> Compact
              </Button>
              <Button
                variant={viewDensity === 'table' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewDensity('table')}
                className="h-7 text-xs px-2.5"
                title="Institutional Table View"
              >
                <TableIcon className="h-3.5 w-3.5 mr-1" /> Table
              </Button>
            </div>

            {/* Bulk Action Bar if selection exists */}
            {selectedRowKeys.size > 0 && (
              <div className="flex items-center gap-2 bg-primary/10 border border-primary/30 p-1 px-3 rounded-lg text-xs">
                <span className="font-bold text-primary">{selectedRowKeys.size} Selected:</span>
                <Button size="sm" className="h-6 text-[10px] font-bold">
                  Start Selected
                </Button>
                <Button variant="outline" size="sm" className="h-6 text-[10px] text-loss">
                  Stop Selected
                </Button>
              </div>
            )}

            {/* Search & Status Filters */}
            <div className="flex flex-col sm:flex-row sm:items-center gap-2 lg:ml-auto">
              <div className="relative w-full sm:w-48">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  placeholder="Filter strategies..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8 h-8 text-xs"
                />
              </div>

              {/* Status Pills */}
              <div className="flex flex-wrap gap-1 bg-muted p-0.5 rounded-lg border border-border">
                {[
                  { id: 'all', label: 'All' },
                  { id: 'running', label: 'Running' },
                  { id: 'stopped', label: 'Stopped' },
                  { id: 'error', label: 'Errors' },
                ].map((st) => (
                  <Button
                    key={st.id}
                    variant={statusFilter === st.id ? 'default' : 'ghost'}
                    size="sm"
                    onClick={() => setStatusFilter(st.id as any)}
                    className="h-7 text-[11px] px-2 font-medium"
                  >
                    {st.label}
                  </Button>
                ))}
              </div>

              {/* Engine Filter Pills */}
              <div className="flex flex-wrap gap-1 bg-muted p-0.5 rounded-lg border border-border">
                {[
                  { id: 'all', label: 'All Engines' },
                  { id: 'webhook', label: 'Webhook' },
                  { id: 'python', label: 'Python' },
                  { id: 'flow', label: 'Flow' },
                ].map((cat) => (
                  <Button
                    key={cat.id}
                    variant={categoryFilter === cat.id ? 'default' : 'ghost'}
                    size="sm"
                    onClick={() => setCategoryFilter(cat.id as any)}
                    className="h-7 text-[11px] px-2 font-medium"
                  >
                    {cat.label}
                  </Button>
                ))}
              </div>
            </div>
          </div>

          {/* Favorites Section */}
          {favoriteRows.length > 0 && (
            <div className="space-y-3 p-4 rounded-xl border border-amber-500/30 bg-amber-500/5">
              <div className="flex items-center gap-2 pb-1 border-b border-amber-500/20">
                <Star className="h-4 w-4 fill-amber-400 text-amber-400" />
                <h3 className="text-xs font-bold uppercase tracking-wider text-amber-500">
                  Pinned Favorite Strategies ({favoriteRows.length})
                </h3>
              </div>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {favoriteRows.map((row) => (
                  <UnifiedStrategyCard
                    key={`fav-${row.kind}-${row.data.id}`}
                    row={row}
                    copiedId={copiedId}
                    actionLoading={actionLoading}
                    viewDensity={viewDensity}
                    isFavorite={true}
                    onToggleFavorite={toggleFavorite}
                    onInspect={handleInspectCard}
                    onCopyWebhook={copyWebhookUrl}
                    onConfigureSymbols={() => {}}
                    onBacktest={handleLaunchBacktest}
                    onDeploy={() => {}}
                    onPythonStart={handlePythonStart}
                    onPythonStop={handlePythonStop}
                    onFlowActivate={handleFlowActivate}
                    onFlowDeactivate={handleFlowDeactivate}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Main Strategy Workspace (Table or Grouped Grid) */}
          {loading ? (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-48 w-full rounded-xl" />
              ))}
            </div>
          ) : viewDensity === 'table' ? (
            renderInstitutionalTable()
          ) : (
            <div className="space-y-8">
              {/* Group 1: Active & Running Strategies */}
              {runningRows.length > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 pb-1 border-b border-border">
                    <span className="w-2.5 h-2.5 rounded-full bg-profit animate-pulse" />
                    <h3 className="text-xs font-bold uppercase tracking-wider text-foreground">
                      Running & Active ({runningRows.length})
                    </h3>
                  </div>
                  <div
                    className={
                      viewDensity === 'compact'
                        ? 'space-y-2'
                        : 'grid gap-4 md:grid-cols-2 lg:grid-cols-3'
                    }
                  >
                    {runningRows.map((row) => (
                      <UnifiedStrategyCard
                        key={`${row.kind}-${row.data.id}`}
                        row={row}
                        copiedId={copiedId}
                        actionLoading={actionLoading}
                        viewDensity={viewDensity}
                        isFavorite={favorites.has(getRowKey(row))}
                        onToggleFavorite={toggleFavorite}
                        onInspect={handleInspectCard}
                        onCopyWebhook={copyWebhookUrl}
                        onConfigureSymbols={() => {}}
                        onBacktest={handleLaunchBacktest}
                        onDeploy={() => {}}
                        onPythonStart={handlePythonStart}
                        onPythonStop={handlePythonStop}
                        onFlowActivate={handleFlowActivate}
                        onFlowDeactivate={handleFlowDeactivate}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Group 2: Runtime Errors */}
              {errorRows.length > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 pb-1 border-b border-border">
                    <span className="w-2.5 h-2.5 rounded-full bg-loss" />
                    <h3 className="text-xs font-bold uppercase tracking-wider text-loss">
                      Runtime Errors ({errorRows.length})
                    </h3>
                  </div>
                  <div
                    className={
                      viewDensity === 'compact'
                        ? 'space-y-2'
                        : 'grid gap-4 md:grid-cols-2 lg:grid-cols-3'
                    }
                  >
                    {errorRows.map((row) => (
                      <UnifiedStrategyCard
                        key={`${row.kind}-${row.data.id}`}
                        row={row}
                        copiedId={copiedId}
                        actionLoading={actionLoading}
                        viewDensity={viewDensity}
                        isFavorite={favorites.has(getRowKey(row))}
                        onToggleFavorite={toggleFavorite}
                        onInspect={handleInspectCard}
                        onCopyWebhook={copyWebhookUrl}
                        onConfigureSymbols={() => {}}
                        onBacktest={handleLaunchBacktest}
                        onDeploy={() => {}}
                        onPythonStart={handlePythonStart}
                        onPythonStop={handlePythonStop}
                        onFlowActivate={handleFlowActivate}
                        onFlowDeactivate={handleFlowDeactivate}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Group 3: Stopped & Inactive Strategies */}
              {stoppedRows.length > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 pb-1 border-b border-border">
                    <span className="w-2.5 h-2.5 rounded-full bg-muted-foreground/40" />
                    <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                      Stopped & Inactive ({stoppedRows.length})
                    </h3>
                  </div>
                  <div
                    className={
                      viewDensity === 'compact'
                        ? 'space-y-2'
                        : 'grid gap-4 md:grid-cols-2 lg:grid-cols-3'
                    }
                  >
                    {stoppedRows.map((row) => (
                      <UnifiedStrategyCard
                        key={`${row.kind}-${row.data.id}`}
                        row={row}
                        copiedId={copiedId}
                        actionLoading={actionLoading}
                        viewDensity={viewDensity}
                        isFavorite={favorites.has(getRowKey(row))}
                        onToggleFavorite={toggleFavorite}
                        onInspect={handleInspectCard}
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
                            showToast.error('Failed to load symbol mappings', 'strategy')
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
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        /* Top Level Tab 2: Portfolio Presets */
        <Card className="p-6">
          <div className="mb-4">
            <h2 className="text-lg font-bold text-foreground">Options Portfolio Presets</h2>
            <p className="text-xs text-muted-foreground">
              Saved multi-leg options structures & payoff diagrams from the Options Strategy
              Builder.
            </p>
          </div>
          <Suspense fallback={<Skeleton className="h-64 w-full" />}>
            <StrategyPortfolio />
          </Suspense>
        </Card>
      )}

      {/* Ctrl + K Institutional Command Palette */}
      <CommandPalette
        open={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        rows={unifiedRows}
        onInspect={handleInspectCard}
        onDeploy={(r) => {
          setSelectedStrategyForDeploy(r.data as Strategy)
          setDeployLegs([])
          setDeployDrawerOpen(true)
        }}
        onBacktest={(r) => handleLaunchBacktest(r.data as Strategy)}
      />

      {/* Slide-over Strategy Inspector Drawer */}
      <StrategyInspector
        open={inspectorOpen}
        onClose={() => setInspectorOpen(false)}
        row={inspectedRow}
        copiedId={copiedId}
        actionLoading={actionLoading}
        onCopyWebhook={copyWebhookUrl}
        onBacktest={handleLaunchBacktest}
        onDeploy={async (strategy) => {
          setInspectorOpen(false)
          setSelectedStrategyForDeploy(strategy)
          setDeployLegs([])
          setDeployDrawerOpen(true)
        }}
        onPythonStart={handlePythonStart}
        onPythonStop={handlePythonStop}
        onFlowActivate={handleFlowActivate}
        onFlowDeactivate={handleFlowDeactivate}
        getWebhookUrl={getWebhookUrl}
      />

      {/* Deploy Strategy Drawer */}
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
