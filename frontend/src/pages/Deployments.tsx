import React, { useState, useEffect } from 'react'
import {
  Play,
  Pause,
  Square,
  Copy,
  Trash2,
  ChevronDown,
  ChevronUp,
  Activity,
  Heart,
  TrendingUp,
  Cpu,
  Clock,
  RefreshCw,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'
import { fetchCSRFToken } from '@/api/client'

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
  compositedge: 'CompositEdge', dhan: 'Dhan', deltaexchange: 'Delta Exchange',
  indmoney: 'IndMoney', dhan_sandbox: 'Dhan (Sandbox)', definedge: 'Definedge',
  firstock: 'Firstock', flattrade: 'Flattrade', motilal: 'Motilal Oswal',
  fyers: 'Fyers', ibulls: 'Ibulls', iifl: 'IIFL', iiflcapital: 'IIFL Capital',
  jainamxts: 'JainamXts', pocketful: 'Pocketful', rmoney: 'RMoney',
  shoonya: 'Shoonya', upstox: 'Upstox', wisdom: 'Wisdom Capital', zebu: 'Zebu',
  bnr: 'BNR Securities', zerodha: 'Zerodha', aliceblue: 'Alice Blue', angel: 'Angel One',
}

export default function Deployments() {
  const [deployments, setDeployments] = useState<DeploymentInstance[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<string>('All')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [connectedBrokers, setConnectedBrokers] = useState<string[]>([])
  // Which deployment's broker chip-picker is currently open, if any, and
  // the in-progress selection while editing (chips let a deployment fan
  // orders out to multiple brokers at once).
  const [editingBrokerId, setEditingBrokerId] = useState<number | null>(null)
  const [editingBrokerDraft, setEditingBrokerDraft] = useState<string[]>([])

  const fetchDeployments = async () => {
    try {
      const response = await fetch('/api/v1/deployments')
      if (response.ok) {
        const data = await response.json()
        setDeployments(data)
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDeployments()
    // biome-ignore lint/correctness/useExhaustiveDependencies: fetchDeployments is stable across renders
    const interval = setInterval(fetchDeployments, 5000)
    return () => clearInterval(interval)
  }, [])

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
        headers: { 'X-CSRFToken': csrfToken }
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
        headers: { 'X-CSRFToken': csrfToken }
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
        headers: { 'X-CSRFToken': csrfToken }
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
    if (!window.confirm(`Delete "${name}" permanently? This cannot be undone.`)) {
      return
    }
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
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken
        },
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



  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'running':
      case 'managing':
        return 'bg-profit/10 text-profit border border-profit/20'
      case 'waiting':
        return 'bg-warning/10 text-warning border border-warning/20'
      case 'paused':
        return 'bg-gray-500/10 text-gray-400 border border-gray-500/20'
      case 'stopped':
      case 'cancelled':
        return 'bg-loss/10 text-loss border border-loss/20'
      case 'error':
        return 'bg-loss/10 text-loss border border-loss/20 shadow-[0_0_8px_rgba(239,68,68,0.2)]'
      default:
        return 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
    }
  }

  const tabs = ['All', 'Running', 'Waiting', 'Paused', 'Completed', 'Stopped', 'Error']

  const filteredDeployments = deployments.filter((d) => {
    if (activeTab === 'All') return true
    return d.status.toLowerCase() === activeTab.toLowerCase()
  })

  // Aggregate stats
  const totalPnL = deployments.reduce((acc, curr) => acc + (curr.pnl || 0), 0)
  const activeCount = deployments.filter((d) => ['running', 'waiting', 'managing'].includes(d.status.toLowerCase())).length

  return (
    <div className="flex-1 p-6 space-y-5 bg-background text-foreground overflow-y-auto select-none">
      {/* Top Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-lg font-bold tracking-tight text-foreground">Deployments</h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            Control plane for running algorithmic strategies.
          </p>
        </div>
        <button
          type="button"
          onClick={fetchDeployments}
          className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold rounded-md border border-border hover:bg-accent transition"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {/* Compact status strip — replaces 4 tall metric cards with one dense row */}
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

      {/* Deployments Table / List */}
      {loading ? (
        <div className="text-center py-12 text-sm text-muted-foreground">Loading deployments...</div>
      ) : filteredDeployments.length === 0 ? (
        <div className="text-center py-16 border border-dashed border-border rounded-xl">
          <span className="text-sm text-muted-foreground block">No deployments found in this tab.</span>
        </div>
      ) : (
        <div className="border border-border rounded-xl overflow-hidden bg-card">
          <table className="w-full text-left border-collapse">
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
              {filteredDeployments.map((dep) => {
                const isExpanded = expandedId === dep.id
                return (
                  <React.Fragment key={dep.id}>
                    <tr className="border-b border-border hover:bg-muted/10 transition group cursor-pointer" onClick={() => setExpandedId(isExpanded ? null : dep.id)}>
                      <td className="p-4 font-bold flex items-center gap-2">
                        <span>{dep.name}</span>
                        <span className="text-xs font-normal text-muted-foreground">v{dep.version_id}</span>
                      </td>
                      <td className="p-4 text-sm font-semibold" onClick={(e) => e.stopPropagation()}>
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
                              setEditingBrokerDraft(dep.brokers?.length ? dep.brokers : [dep.broker])
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
                        <span className={cn('px-2.5 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider', getStatusColor(dep.status))}>
                          {dep.status}
                        </span>
                      </td>
                      <td className={cn('p-4 font-bold', dep.pnl >= 0 ? 'text-profit' : 'text-loss')}>
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
                              title="Resume Strategy"
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
                              title="Pause Strategy"
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
                            className="p-1.5 rounded hover:bg-blue-500/10 text-blue-400 border border-blue-500/20"
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
                            title={isExpanded ? 'Collapse Details' : 'Expand Details'}
                          >
                            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                          </button>
                        </div>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="bg-muted/10 border-b border-border">
                        <td colSpan={6} className="p-4">
                          <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
                            {/* Trigger Timeline — styled as a real log console */}
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
                                      <span className="text-muted-foreground shrink-0">{ev.time}</span>
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

                            {/* Telemetry Metrics */}
                            <div className="lg:col-span-2 border border-border rounded-lg bg-background overflow-hidden flex flex-col">
                              <div className="flex items-center gap-1.5 px-3 py-2 border-b border-border bg-muted/30">
                                <Cpu className="w-3.5 h-3.5 text-muted-foreground" />
                                <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
                                  Telemetry & Metrics
                                </h4>
                              </div>
                              <div className="grid grid-cols-2 gap-3 px-3 py-3 text-xs flex-1">
                                <div>
                                  <span className="text-muted-foreground block mb-0.5">CPU Usage</span>
                                  <span className="font-bold tabular-nums">{dep.metrics?.cpu ?? 0.0}%</span>
                                </div>
                                <div>
                                  <span className="text-muted-foreground block mb-0.5">Memory</span>
                                  <span className="font-bold tabular-nums">{dep.metrics?.memory ?? 0} MB</span>
                                </div>
                                <div>
                                  <span className="text-muted-foreground block mb-0.5">Latency</span>
                                  <span className="font-bold tabular-nums">{dep.metrics?.latency ?? 0}ms</span>
                                </div>
                                <div>
                                  <span className="text-muted-foreground block mb-0.5">Evaluation Rate</span>
                                  <span className="font-bold">Every tick</span>
                                </div>
                              </div>
                              <div className="text-[11px] text-muted-foreground border-t border-border px-3 py-2 flex items-center justify-between bg-muted/10">
                                <span>Health: <span className="font-semibold text-foreground">{dep.health_score}%</span></span>
                                <span>Last tick: <span className="font-semibold text-foreground">{dep.metrics?.last_tick ?? 'N/A'}</span></span>
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
      )}
    </div>
  )
}
