import {
  Activity,
  ChevronDown,
  ChevronUp,
  Clock,
  Code2,
  Copy,
  Cpu,
  Heart,
  Layers,
  Pause,
  Play,
  RefreshCw,
  Square,
  Trash2,
  TrendingUp,
  Webhook,
  Zap,
} from 'lucide-react'
import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchCSRFToken } from '@/api/client'
import {
  activateWorkflow,
  deactivateWorkflow,
  listWorkflows,
  type WorkflowListItem,
} from '@/api/flow'
import { pythonStrategyApi } from '@/api/python-strategy'
import { strategyApi } from '@/api/strategy'
import { PageHeader } from '@/components/layout/PageHeader'
import { cn } from '@/lib/utils'
import type { PythonStrategy } from '@/types/python-strategy'
import type { Strategy } from '@/types/strategy'
import { showToast } from '@/utils/toast'

interface DeploymentInstance {
  id: number
  name: string
  strategy_id: number
  version_id: number
  status: string
  broker: string
  brokers: string[]
  capital: number
  max_positions: number
  order_type: string
  product: string
  trigger_type: string
  conditions_tree: any
  risk_params: any
  pnl: number
  trades_count: number
  health_score: number
  metrics: {
    cpu?: number
    memory?: number
    latency?: number
    heartbeat?: number
    last_tick?: string
  }
  events_timeline: Array<{ time: string; event: string }>
}

const BROKER_DISPLAY_NAMES: Record<string, string> = {
  compositedge: 'CompositEdge',
  dhan: 'Dhan',
  deltaexchange: 'Delta Exchange',
  indmoney: 'IndMoney',
  dhan_sandbox: 'Dhan (Sandbox)',
  definedge: 'Definedge',
  firstock: 'Firstock',
  flattrade: 'Flattrade',
  motilal: 'Motilal Oswal',
  fyers: 'Fyers',
  ibulls: 'Ibulls',
  iifl: 'IIFL',
  iiflcapital: 'IIFL Capital',
  jainamxts: 'JainamXts',
  pocketful: 'Pocketful',
  rmoney: 'RMoney',
  shoonya: 'Shoonya',
  upstox: 'Upstox',
  wisdom: 'Wisdom Capital',
  zebu: 'Zebu',
  bnr: 'BNR Securities',
  zerodha: 'Zerodha',
  aliceblue: 'Alice Blue',
  angel: 'Angel One',
}

export default function Deployments() {
  const [deployments, setDeployments] = useState<DeploymentInstance[]>([])
  const [pythonStrategies, setPythonStrategies] = useState<PythonStrategy[]>([])
  const [workflows, setWorkflows] = useState<WorkflowListItem[]>([])
  // Webhook (MaxHook/TradingView/Chartink) strategies. These place real
  // orders whenever a signal arrives but appeared in NONE of this page's
  // sections, nor Python Studio, nor Flow -- so an armed one was invisible
  // everywhere, which is how auto-seeded strategies fired live orders
  // unnoticed. Read-only here; arm/disarm and edit live in Strategy Library.
  const [webhookStrategies, setWebhookStrategies] = useState<Strategy[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<string>('All')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [connectedBrokers, setConnectedBrokers] = useState<string[]>([])
  const [editingBrokerId, setEditingBrokerId] = useState<number | null>(null)
  const [editingBrokerDraft, setEditingBrokerDraft] = useState<string[]>([])
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const fetchDeployments = async () => {
    try {
      const response = await fetch('/api/v1/deployments')
      if (response.ok) {
        const data = await response.json()
        setDeployments(data)
      }
    } catch (e) {
      console.error(e)
    }
  }

  const fetchPythonStrategies = async () => {
    try {
      const strategies = await pythonStrategyApi.getStrategies()
      setPythonStrategies(strategies)
    } catch (e) {
      console.error(e)
    }
  }

  const fetchWorkflows = async () => {
    try {
      const flows = await listWorkflows()
      setWorkflows(flows)
    } catch (e) {
      console.error(e)
    }
  }

  const fetchWebhookStrategies = async () => {
    try {
      const all = await strategyApi.getStrategies()
      // Archived strategies are retired -- they can't fire, so listing them
      // here would only add noise to a page meant to answer "what can trade
      // right now?".
      setWebhookStrategies(all.filter((s) => s.lifecycle_state !== 'Archived'))
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => {
    const fetchAll = async () => {
      await Promise.allSettled([
        fetchDeployments(),
        fetchPythonStrategies(),
        fetchWorkflows(),
        fetchWebhookStrategies(),
      ])
      setLoading(false)
    }
    fetchAll()
    const interval = setInterval(() => {
      fetchDeployments()
      fetchPythonStrategies()
      fetchWorkflows()
      fetchWebhookStrategies()
    }, 5000)
    return () => clearInterval(interval)
  }, [fetchDeployments, fetchPythonStrategies, fetchWorkflows])

  useEffect(() => {
    fetch('/api/broker/connections', { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.status !== 'success') return
        setConnectedBrokers(
          (data.connections || [])
            .filter((c: { connected: boolean }) => c.connected)
            .map((c: { broker: string }) => c.broker)
        )
      })
      .catch(() => {})
  }, [])

  const handleChangeBrokers = async (id: number, brokers: string[]) => {
    if (brokers.length === 0) {
      showToast.error('Select at least one broker')
      return
    }
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/api/v1/deployments/${id}/broker`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({ brokers }),
      })
      const data = await response.json()
      if (response.ok && data.status === 'success') {
        const label = brokers.map((b) => BROKER_DISPLAY_NAMES[b] ?? b).join(', ')
        showToast.success(`Broker(s) changed to ${label}`)
        setEditingBrokerId(null)
        fetchDeployments()
      } else {
        showToast.error(data.message || 'Failed to change broker')
      }
    } catch {
      showToast.error('Failed to change broker')
    }
  }

  const handlePause = async (id: number) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/api/v1/deployments/${id}/pause`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
      })
      if (response.ok) {
        showToast.success('Deployment paused')
        fetchDeployments()
      }
    } catch {
      showToast.error('Failed to pause deployment')
    }
  }

  const handleResume = async (id: number) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/api/v1/deployments/${id}/resume`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
      })
      if (response.ok) {
        showToast.success('Deployment resumed')
        fetchDeployments()
      }
    } catch {
      showToast.error('Failed to resume deployment')
    }
  }

  const handleStop = async (id: number) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/api/v1/deployments/${id}/stop`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
      })
      if (response.ok) {
        showToast.success('Deployment stopped permanently')
        fetchDeployments()
      }
    } catch {
      showToast.error('Failed to stop deployment')
    }
  }

  const handleDelete = async (id: number, name: string) => {
    if (!window.confirm(`Delete "${name}" permanently? This cannot be undone.`)) return
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/api/v1/deployments/${id}`, {
        method: 'DELETE',
        headers: { 'X-CSRFToken': csrfToken },
      })
      const data = await response.json()
      if (response.ok) {
        showToast.success('Deployment deleted')
        fetchDeployments()
      } else {
        showToast.error(data.message || 'Failed to delete deployment')
      }
    } catch {
      showToast.error('Failed to delete deployment')
    }
  }

  const handleClone = async (id: number) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/api/v1/deployments/${id}/clone`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({}),
      })
      if (response.ok) {
        showToast.success('Deployment cloned successfully as Draft')
        fetchDeployments()
      }
    } catch {
      showToast.error('Failed to clone deployment')
    }
  }

  const handlePythonStart = async (strategy: PythonStrategy) => {
    try {
      setActionLoading(strategy.id)
      const r = await pythonStrategyApi.startStrategy(strategy.id)
      if (r.status === 'success') {
        showToast.success(r.message || `${strategy.name} started`, 'strategy')
        fetchPythonStrategies()
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
        fetchPythonStrategies()
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
        fetchWorkflows()
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
        fetchWorkflows()
      } else {
        showToast.error(r.message || 'Failed to deactivate', 'strategy')
      }
    } catch {
      showToast.error('Failed to deactivate workflow', 'strategy')
    } finally {
      setActionLoading(null)
    }
  }

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'running':
      case 'managing':
      case 'entering':
        return 'bg-profit/10 text-profit border border-profit/20'
      case 'waiting':
        return 'bg-warning/10 text-warning border border-warning/20'
      case 'paused':
        return 'bg-muted-foreground/10 text-muted-foreground border border-muted-foreground/20'
      case 'stopped':
      case 'cancelled':
        return 'bg-loss/10 text-loss border border-loss/20'
      case 'error':
        return 'bg-loss/10 text-loss border border-loss/20 shadow-[0_0_8px_rgba(239,68,68,0.2)]'
      default:
        return 'bg-info/10 text-info border border-info/20'
    }
  }

  const tabs = ['All', 'Running', 'Paused', 'Stopped', 'Error']

  const filteredDeployments = deployments.filter((d) => {
    if (activeTab === 'All') return true
    const s = d.status.toLowerCase()
    if (activeTab === 'Running')
      return s === 'running' || s === 'waiting' || s === 'entering' || s === 'managing'
    if (activeTab === 'Paused') return s === 'paused' || s === 'draft'
    if (activeTab === 'Stopped') return s === 'stopped' || s === 'cancelled'
    return s === activeTab.toLowerCase()
  })

  // Distinguish Automated (Condition-Based) vs Webhook (Alert Listener) Deployments
  const isConditionDep = (d: DeploymentInstance) =>
    d.trigger_type === 'On Conditions' ||
    Boolean(d.conditions_tree?.operator || d.conditions_tree?.children)

  const automatedDeployments = filteredDeployments.filter(isConditionDep)
  const webhookDeployments = filteredDeployments.filter((d) => !isConditionDep(d))

  // Python filtering by tab
  const filteredPython = pythonStrategies.filter((p) => {
    if (activeTab === 'All') return true
    const s = p.status?.toLowerCase() || ''
    if (activeTab === 'Running') return s === 'running' || s === 'scheduled'
    if (activeTab === 'Stopped') return s === 'stopped' || s === 'idle'
    if (activeTab === 'Error') return s === 'error'
    return false
  })

  // Flow filtering by tab
  const filteredFlows = workflows.filter((w) => {
    if (activeTab === 'All') return true
    if (activeTab === 'Running') return w.is_active
    if (activeTab === 'Stopped') return !w.is_active
    return false
  })

  // Webhook strategy filtering by tab. "Armed" means it will actually place
  // an order when a signal arrives, which requires BOTH flags: is_active
  // (the on/off switch) and a lifecycle_state that permits trading. They
  // are separate columns and can disagree -- a strategy showing Active
  // while stuck in Draft rejects every signal (see signal_engine's
  // lifecycle gate), so showing is_active alone here would repeat exactly
  // the misleading "looks armed but isn't" state this section exists to
  // expose.
  const isWebhookArmed = (s: Strategy) =>
    s.is_active && s.lifecycle_state !== 'Draft' && s.lifecycle_state !== 'Archived'

  const filteredWebhookStrategies = webhookStrategies.filter((s) => {
    if (activeTab === 'All') return true
    if (activeTab === 'Running') return isWebhookArmed(s)
    if (activeTab === 'Stopped') return !isWebhookArmed(s)
    return false
  })

  // Aggregate stats
  const totalPnL = deployments.reduce((acc, curr) => acc + (curr.pnl || 0), 0)
  const webhookRunning = deployments.filter((d) =>
    ['running', 'waiting', 'managing', 'entering'].includes(d.status.toLowerCase())
  ).length
  const pythonRunning = pythonStrategies.filter(
    (p) => p.status === 'running' || p.status === 'scheduled'
  ).length
  const flowRunning = workflows.filter((w) => w.is_active).length
  const webhookStrategiesArmed = webhookStrategies.filter(isWebhookArmed).length
  const activeCount = webhookRunning + pythonRunning + flowRunning + webhookStrategiesArmed

  const totalItems =
    filteredDeployments.length +
    filteredPython.length +
    filteredFlows.length +
    filteredWebhookStrategies.length

  const renderDeploymentTable = (
    list: DeploymentInstance[],
    sectionTitle: string,
    icon: React.ReactNode
  ) => (
    <section className="space-y-2">
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {sectionTitle} ({list.length})
        </span>
      </div>
      <div className="border border-border rounded-xl overflow-hidden bg-card">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse min-w-[40rem]">
            <thead>
              <tr className="border-b border-border bg-muted/20 text-xs font-bold text-muted-foreground uppercase">
                <th className="p-4">Deployment</th>
                <th className="p-4">Broker</th>
                <th className="p-4">Status</th>
                <th className="p-4">PnL</th>
                <th className="p-4">Capital</th>
                <th className="p-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {list.map((dep) => {
                const isExpanded = expandedId === dep.id
                return (
                  <React.Fragment key={dep.id}>
                    <tr
                      className="border-b border-border hover:bg-muted/10 transition group cursor-pointer"
                      onClick={() => setExpandedId(isExpanded ? null : dep.id)}
                    >
                      <td className="p-4 font-bold flex items-center gap-2">
                        <span>{dep.name}</span>
                        <span className="text-xs font-normal text-muted-foreground">
                          v{dep.version_id}
                        </span>
                      </td>
                      <td
                        className="p-4 text-sm font-semibold"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {editingBrokerId === dep.id ? (
                          <div className="flex flex-col gap-1.5 rounded-md border border-border bg-background p-2 shadow-sm">
                            <div className="flex flex-wrap gap-1">
                              {['Paper Trading', ...connectedBrokers].map((broker) => {
                                const active = editingBrokerDraft.includes(broker)
                                return (
                                  <button
                                    key={broker}
                                    type="button"
                                    onClick={() =>
                                      setEditingBrokerDraft((prev) =>
                                        prev.includes(broker)
                                          ? prev.filter((b) => b !== broker)
                                          : [...prev, broker]
                                      )
                                    }
                                    className={cn(
                                      'px-2 py-1 rounded-full text-[11px] font-semibold border transition',
                                      active
                                        ? 'bg-primary text-primary-foreground border-primary'
                                        : 'bg-background text-muted-foreground border-border hover:border-primary/50'
                                    )}
                                  >
                                    {active && '✓ '}
                                    {BROKER_DISPLAY_NAMES[broker] ?? broker}
                                  </button>
                                )
                              })}
                            </div>
                            <div className="flex justify-end gap-1.5">
                              <button
                                type="button"
                                onClick={() => setEditingBrokerId(null)}
                                className="text-[11px] font-semibold text-muted-foreground hover:underline"
                              >
                                Cancel
                              </button>
                              <button
                                type="button"
                                onClick={() => handleChangeBrokers(dep.id, editingBrokerDraft)}
                                className="text-[11px] font-semibold text-primary hover:underline"
                              >
                                Save
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button
                            type="button"
                            onClick={() => {
                              setEditingBrokerId(dep.id)
                              setEditingBrokerDraft(
                                dep.brokers?.length ? dep.brokers : [dep.broker]
                              )
                            }}
                            className="hover:underline decoration-dotted text-left"
                            title="Click to change broker(s)"
                          >
                            {(dep.brokers?.length ? dep.brokers : [dep.broker])
                              .map((b) => BROKER_DISPLAY_NAMES[b] ?? b)
                              .join(', ')}
                          </button>
                        )}
                      </td>
                      <td className="p-4">
                        <span
                          className={cn(
                            'px-2.5 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider',
                            getStatusColor(dep.status)
                          )}
                        >
                          {dep.status}
                        </span>
                      </td>
                      <td
                        className={cn('p-4 font-bold', dep.pnl >= 0 ? 'text-profit' : 'text-loss')}
                      >
                        {dep.pnl >= 0 ? '+' : ''}₹{dep.pnl.toLocaleString()}
                      </td>
                      <td className="p-4 text-sm font-semibold">₹{dep.capital.toLocaleString()}</td>
                      <td className="p-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {['paused', 'draft'].includes(dep.status.toLowerCase()) ? (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleResume(dep.id)
                              }}
                              className="p-1.5 rounded hover:bg-profit/10 text-profit border border-profit/20"
                              title="Resume"
                            >
                              <Play className="w-3.5 h-3.5 fill-current" />
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                handlePause(dep.id)
                              }}
                              className="p-1.5 rounded hover:bg-warning/10 text-warning border border-warning/20"
                              title="Pause"
                            >
                              <Pause className="w-3.5 h-3.5 fill-current" />
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              handleStop(dep.id)
                            }}
                            className="p-1.5 rounded hover:bg-loss/10 text-loss border border-loss/20"
                            title="Stop Permanently"
                          >
                            <Square className="w-3.5 h-3.5 fill-current" />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              handleClone(dep.id)
                            }}
                            className="p-1.5 rounded hover:bg-info/10 text-info border border-info/20"
                            title="Clone Deployment"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                          {!['managing', 'entering'].includes(dep.status.toLowerCase()) && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleDelete(dep.id, dep.name)
                              }}
                              className="p-1.5 rounded hover:bg-loss/10 text-loss border border-loss/20"
                              title="Delete Deployment"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              setExpandedId(isExpanded ? null : dep.id)
                            }}
                            className="p-1 text-muted-foreground hover:text-foreground"
                            title={isExpanded ? 'Collapse' : 'Expand'}
                          >
                            {isExpanded ? (
                              <ChevronUp className="w-4 h-4" />
                            ) : (
                              <ChevronDown className="w-4 h-4" />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="bg-muted/10 border-b border-border">
                        <td colSpan={6} className="p-4">
                          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
                            <div className="lg:col-span-3 border border-border rounded-lg bg-background overflow-hidden">
                              <div className="flex items-center gap-1.5 px-3 py-2 border-b border-border bg-muted/30">
                                <Clock className="w-3.5 h-3.5 text-muted-foreground" />
                                <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
                                  Trigger Timeline
                                </h4>
                              </div>
                              <div className="max-h-[180px] overflow-y-auto font-mono text-[11px] leading-relaxed">
                                {(dep.events_timeline || []).length > 0 ? (
                                  (dep.events_timeline || []).map((ev, i) => (
                                    <div
                                      key={i}
                                      className="flex gap-3 px-3 py-1 border-b border-border/40 last:border-0 hover:bg-muted/20"
                                    >
                                      <span className="text-muted-foreground shrink-0">
                                        {ev.time}
                                      </span>
                                      <span className="text-foreground truncate">{ev.event}</span>
                                    </div>
                                  ))
                                ) : (
                                  <span className="block px-3 py-3 text-xs text-muted-foreground italic">
                                    No events logged yet
                                  </span>
                                )}
                              </div>
                            </div>
                            <div className="lg:col-span-2 border border-border rounded-lg bg-background overflow-hidden flex flex-col">
                              <div className="flex items-center gap-1.5 px-3 py-2 border-b border-border bg-muted/30">
                                <Cpu className="w-3.5 h-3.5 text-muted-foreground" />
                                <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
                                  Telemetry & Metrics
                                </h4>
                              </div>
                              <div className="grid grid-cols-2 gap-3 px-3 py-3 text-xs flex-1">
                                <div>
                                  <span className="text-muted-foreground block mb-0.5">CPU</span>
                                  <span className="font-bold tabular-nums">
                                    {dep.metrics?.cpu ?? 0.0}%
                                  </span>
                                </div>
                                <div>
                                  <span className="text-muted-foreground block mb-0.5">Memory</span>
                                  <span className="font-bold tabular-nums">
                                    {dep.metrics?.memory ?? 0} MB
                                  </span>
                                </div>
                                <div>
                                  <span className="text-muted-foreground block mb-0.5">
                                    Latency
                                  </span>
                                  <span className="font-bold tabular-nums">
                                    {dep.metrics?.latency ?? 0}ms
                                  </span>
                                </div>
                                <div>
                                  <span className="text-muted-foreground block mb-0.5">Health</span>
                                  <span className="font-bold">{dep.health_score}%</span>
                                </div>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )

  return (
    <div className="flex-1 p-6 space-y-5 bg-background text-foreground overflow-y-auto select-none">
      {/* Header */}
      <PageHeader
        title="Live Deployments"
        description="Mission control for all running strategies."
        actions={
          <button
            type="button"
            onClick={() => {
              fetchDeployments()
              fetchPythonStrategies()
              fetchWorkflows()
            }}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-md border border-border hover:bg-accent transition"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </button>
        }
      />

      {/* Compact status strip */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border border-border bg-card px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Heart className="w-3.5 h-3.5 text-profit" />
          <span className="text-xs text-muted-foreground">Heartbeat</span>
          <span className="flex items-center gap-1.5 text-xs font-bold text-profit">
            <span className="w-1.5 h-1.5 rounded-full bg-profit animate-pulse" />
            Healthy
          </span>
        </div>
        <div className="h-4 w-px bg-border" />
        <div className="flex items-center gap-2">
          <Activity className="w-3.5 h-3.5 text-profit" />
          <span className="text-xs text-muted-foreground">Market</span>
          <span className="text-xs font-bold text-profit">Live</span>
        </div>
        <div className="h-4 w-px bg-border" />
        <div className="flex items-center gap-2">
          <Cpu className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs text-muted-foreground">Active Workers</span>
          <span className="text-xs font-bold tabular-nums text-foreground">{activeCount}</span>
        </div>
        <div className="h-4 w-px bg-border" />
        <div className="flex items-center gap-2">
          <TrendingUp className={cn('w-3.5 h-3.5', totalPnL >= 0 ? 'text-profit' : 'text-loss')} />
          <span className="text-xs text-muted-foreground">Total P&L</span>
          <span
            className={cn(
              'text-xs font-bold tabular-nums',
              totalPnL >= 0 ? 'text-profit' : 'text-loss'
            )}
          >
            {totalPnL >= 0 ? '+' : ''}₹{totalPnL.toLocaleString()}
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border gap-1 overflow-x-auto">
        {tabs.map((tab) => (
          <button
            type="button"
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'px-3.5 py-2 text-xs font-semibold border-b-2 -mb-[1px] transition whitespace-nowrap',
              activeTab === tab
                ? 'border-primary text-primary font-bold'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Content */}
      {loading ? (
        <div className="text-center py-12 text-sm text-muted-foreground">
          Loading deployments...
        </div>
      ) : totalItems === 0 ? (
        <div className="text-center py-16 border border-dashed border-border rounded-xl">
          <span className="text-sm text-muted-foreground block">
            No deployments found in this tab.
          </span>
          <span className="text-xs text-muted-foreground/70 block mt-1">
            Deploy a strategy from the{' '}
            <Link to="/strategy" className="text-primary hover:underline">
              Strategy Library
            </Link>
            .
          </span>
        </div>
      ) : (
        <div className="space-y-6">
          {/* ── Automated Condition Deployments Table ── */}
          {automatedDeployments.length > 0 &&
            renderDeploymentTable(
              automatedDeployments,
              'Automated Deployments',
              <Zap className="h-3.5 w-3.5 text-warning" />
            )}

          {/* ── Webhook Alerts Table ── */}
          {webhookDeployments.length > 0 &&
            renderDeploymentTable(
              webhookDeployments,
              'Webhook Alerts',
              <Webhook className="h-3.5 w-3.5 text-cat-3" />
            )}

          {/* ── Python Strategies Section ── */}
          {filteredPython.length > 0 && (
            <section className="space-y-2">
              <div className="flex items-center gap-2">
                <Code2 className="h-3.5 w-3.5 text-profit" />
                <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Python Scripts ({filteredPython.length})
                </span>
              </div>
              <div className="border border-border rounded-xl overflow-hidden bg-card">
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse min-w-[40rem]">
                    <thead>
                      <tr className="border-b border-border bg-muted/20 text-xs font-bold text-muted-foreground uppercase">
                        <th className="p-4">Script</th>
                        <th className="p-4">Status</th>
                        <th className="p-4">PID</th>
                        <th className="p-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredPython.map((py) => {
                        const isRunning = py.status === 'running' || py.status === 'scheduled'
                        const isBusy = actionLoading === py.id
                        return (
                          <tr
                            key={py.id}
                            className="border-b border-border last:border-0 hover:bg-muted/10 transition"
                          >
                            <td className="p-4 font-semibold">{py.name}</td>
                            <td className="p-4">
                              <span
                                className={cn(
                                  'px-2.5 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider',
                                  isRunning
                                    ? 'bg-profit/10 text-profit border border-profit/20'
                                    : py.status === 'error'
                                      ? 'bg-loss/10 text-loss border border-loss/20'
                                      : 'bg-muted text-muted-foreground border border-border'
                                )}
                              >
                                {py.status || 'idle'}
                              </span>
                            </td>
                            <td className="p-4 text-sm text-muted-foreground font-mono">
                              {py.process_id ? `PID ${py.process_id}` : '—'}
                            </td>
                            <td className="p-4 text-right">
                              <div className="flex items-center justify-end gap-2">
                                {isRunning ? (
                                  <button
                                    type="button"
                                    disabled={isBusy}
                                    onClick={() => handlePythonStop(py)}
                                    className="p-1.5 rounded hover:bg-loss/10 text-loss border border-loss/20 disabled:opacity-50"
                                    title="Stop Script"
                                  >
                                    <Square className="w-3.5 h-3.5 fill-current" />
                                  </button>
                                ) : (
                                  <button
                                    type="button"
                                    disabled={isBusy}
                                    onClick={() => handlePythonStart(py)}
                                    className="p-1.5 rounded hover:bg-profit/10 text-profit border border-profit/20 disabled:opacity-50"
                                    title="Start Script"
                                  >
                                    <Play className="w-3.5 h-3.5 fill-current" />
                                  </button>
                                )}
                                <Link
                                  to={`/python/${py.id}/logs`}
                                  className="p-1.5 rounded hover:bg-muted text-muted-foreground border border-border text-[11px] font-semibold px-2"
                                >
                                  Logs
                                </Link>
                                <Link
                                  to={`/python/${py.id}/edit`}
                                  className="p-1.5 rounded hover:bg-muted text-muted-foreground border border-border text-[11px] font-semibold px-2"
                                >
                                  Edit
                                </Link>
                              </div>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          {/* ── Flow Workflows Section ── */}
          {filteredFlows.length > 0 && (
            <section className="space-y-2">
              <div className="flex items-center gap-2">
                <Layers className="h-3.5 w-3.5 text-cat-2" />
                <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Automation Flows ({filteredFlows.length})
                </span>
              </div>
              <div className="border border-border rounded-xl overflow-hidden bg-card">
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse min-w-[40rem]">
                    <thead>
                      <tr className="border-b border-border bg-muted/20 text-xs font-bold text-muted-foreground uppercase">
                        <th className="p-4">Flow</th>
                        <th className="p-4">Status</th>
                        <th className="p-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredFlows.map((flow) => {
                        const isBusy = actionLoading === String(flow.id)
                        return (
                          <tr
                            key={flow.id}
                            className="border-b border-border last:border-0 hover:bg-muted/10 transition"
                          >
                            <td className="p-4 font-semibold">{flow.name}</td>
                            <td className="p-4">
                              <span
                                className={cn(
                                  'px-2.5 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider',
                                  flow.is_active
                                    ? 'bg-profit/10 text-profit border border-profit/20'
                                    : 'bg-muted text-muted-foreground border border-border'
                                )}
                              >
                                {flow.is_active ? 'Active' : 'Inactive'}
                              </span>
                            </td>
                            <td className="p-4 text-right">
                              <div className="flex items-center justify-end gap-2">
                                {flow.is_active ? (
                                  <button
                                    type="button"
                                    disabled={isBusy}
                                    onClick={() => handleFlowDeactivate(flow)}
                                    className="p-1.5 rounded hover:bg-loss/10 text-loss border border-loss/20 disabled:opacity-50"
                                    title="Deactivate"
                                  >
                                    <Square className="w-3.5 h-3.5 fill-current" />
                                  </button>
                                ) : (
                                  <button
                                    type="button"
                                    disabled={isBusy}
                                    onClick={() => handleFlowActivate(flow)}
                                    className="p-1.5 rounded hover:bg-profit/10 text-profit border border-profit/20 disabled:opacity-50"
                                    title="Activate"
                                  >
                                    <Play className="w-3.5 h-3.5 fill-current" />
                                  </button>
                                )}
                                <Link
                                  to={`/flow/editor/${flow.id}`}
                                  className="p-1.5 rounded hover:bg-muted text-muted-foreground border border-border text-[11px] font-semibold px-2"
                                >
                                  Canvas
                                </Link>
                              </div>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}

          {filteredWebhookStrategies.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <Webhook className="h-3.5 w-3.5 text-cat-4" />
                <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Webhook Strategies ({filteredWebhookStrategies.length})
                </span>
              </div>
              <div className="border border-border rounded-xl overflow-hidden bg-card">
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse min-w-[40rem]">
                    <thead>
                      <tr className="border-b border-border bg-muted/20 text-xs font-bold text-muted-foreground uppercase">
                        <th className="p-4">Strategy</th>
                        <th className="p-4">Source</th>
                        <th className="p-4">Status</th>
                        <th className="p-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredWebhookStrategies.map((s) => {
                        const armed = isWebhookArmed(s)
                        // Surface the exact "green badge but silently
                        // rejecting every signal" state that made a broken
                        // strategy indistinguishable from a healthy one.
                        const stuckInDraft = s.is_active && s.lifecycle_state === 'Draft'
                        return (
                          <tr
                            key={s.id}
                            className="border-b border-border last:border-0 hover:bg-muted/10 transition"
                          >
                            <td className="p-4 font-semibold">{s.name}</td>
                            <td className="p-4 text-xs text-muted-foreground">
                              {s.signal_source || s.platform || '--'}
                            </td>
                            <td className="p-4">
                              <div className="flex items-center gap-2">
                                <span
                                  className={cn(
                                    'px-2.5 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider',
                                    armed
                                      ? 'bg-profit/10 text-profit border border-profit/20'
                                      : 'bg-muted text-muted-foreground border border-border'
                                  )}
                                >
                                  {armed ? 'Armed' : 'Disarmed'}
                                </span>
                                {stuckInDraft && (
                                  <span
                                    className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase bg-warning/10 text-warning border border-warning/20"
                                    title="Active but still in Draft -- signals are rejected. Open it in Strategy Library and activate it to fix."
                                  >
                                    Draft
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="p-4 text-right">
                              <Link
                                to={`/strategy/${s.id}`}
                                className="p-1.5 rounded hover:bg-muted text-muted-foreground border border-border text-[11px] font-semibold px-2"
                              >
                                Manage
                              </Link>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
