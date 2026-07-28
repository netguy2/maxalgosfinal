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
  // Which deployment's broker dropdown is currently open, if any.
  const [editingBrokerId, setEditingBrokerId] = useState<number | null>(null)

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

  const handleChangeBroker = async (id: number, broker: string) => {
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`/api/v1/deployments/${id}/broker`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({ broker }),
      })
      const data = await response.json()
      if (response.ok && data.status === 'success') {
        showToast.success(`Broker changed to ${BROKER_DISPLAY_NAMES[broker] ?? broker}`)
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
    <div className="flex-1 p-6 space-y-6 bg-background text-foreground overflow-y-auto select-none">
      {/* Top Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Deployments</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Kubernetes-style control plane for running algorithmic strategies.
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

      {/* Metric Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl border border-border bg-card flex items-center justify-between">
          <div>
            <span className="text-xs text-muted-foreground font-semibold uppercase tracking-wider block">
              Heartbeat Status
            </span>
            <span className="text-xl font-bold flex items-center gap-2 mt-1">
              <span className="w-2.5 h-2.5 rounded-full bg-profit animate-pulse" />
              Healthy
            </span>
          </div>
          <Heart className="w-8 h-8 text-profit/20" />
        </div>

        <div className="p-4 rounded-xl border border-border bg-card flex items-center justify-between">
          <div>
            <span className="text-xs text-muted-foreground font-semibold uppercase tracking-wider block">
              Market Connection
            </span>
            <span className="text-xl font-bold text-profit mt-1">Live</span>
          </div>
          <Activity className="w-8 h-8 text-profit/20" />
        </div>

        <div className="p-4 rounded-xl border border-border bg-card flex items-center justify-between">
          <div>
            <span className="text-xs text-muted-foreground font-semibold uppercase tracking-wider block">
              Active Workers
            </span>
            <span className="text-2xl font-black mt-1">{activeCount}</span>
          </div>
          <Cpu className="w-8 h-8 text-indigo-500/20" />
        </div>

        <div className="p-4 rounded-xl border border-border bg-card flex items-center justify-between">
          <div>
            <span className="text-xs text-muted-foreground font-semibold uppercase tracking-wider block">
              Total P&L
            </span>
            <span
              className={cn(
                'text-2xl font-black mt-1',
                totalPnL >= 0 ? 'text-profit' : 'text-loss'
              )}
            >
              {totalPnL >= 0 ? '+' : ''}₹{totalPnL.toLocaleString()}
            </span>
          </div>
          <TrendingUp className="w-8 h-8 text-profit/20" />
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border gap-2">
        {tabs.map((tab) => (
          <button
            type="button"
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'px-4 py-2 text-sm font-semibold border-b-2 -mb-[2px] transition',
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
                          <select
                            autoFocus
                            defaultValue={dep.broker}
                            onChange={(e) => handleChangeBroker(dep.id, e.target.value)}
                            onBlur={() => setEditingBrokerId(null)}
                            className="text-xs font-semibold border border-border rounded px-1.5 py-1 bg-background"
                          >
                            <option value="Paper Trading">Paper Trading (Simulated)</option>
                            {connectedBrokers.map((broker) => (
                              <option key={broker} value={broker}>
                                {BROKER_DISPLAY_NAMES[broker] ?? broker}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setEditingBrokerId(dep.id)}
                            className="hover:underline decoration-dotted"
                            title="Click to change broker"
                          >
                            {BROKER_DISPLAY_NAMES[dep.broker] ?? dep.broker}
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
                        <td colSpan={6} className="p-4 space-y-4">
                          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                            {/* Trigger Timeline */}
                            <div className="border border-border rounded-lg bg-card p-3 space-y-2">
                              <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                                <Clock className="w-3.5 h-3.5" />
                                Trigger Timeline
                              </h4>
                              <div className="space-y-1.5 max-h-[160px] overflow-y-auto pr-1">
                                {(dep.events_timeline || []).map((ev, i) => (
                                  <div key={i} className="flex gap-2 text-xs">
                                    <span className="text-muted-foreground font-mono">{ev.time}</span>
                                    <span className="text-foreground">{ev.event}</span>
                                  </div>
                                ))}
                                {(!dep.events_timeline || dep.events_timeline.length === 0) && (
                                  <span className="text-xs text-muted-foreground block italic">No events logged yet</span>
                                )}
                              </div>
                            </div>

                            {/* Telemetry Metrics */}
                            <div className="border border-border rounded-lg bg-card p-3 space-y-2 flex flex-col justify-between">
                              <div className="space-y-2">
                                <h4 className="text-xs font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                                  <Cpu className="w-3.5 h-3.5" />
                                  Telemetry & Metrics
                                </h4>
                                <div className="grid grid-cols-2 gap-2 text-xs">
                                  <div>
                                    <span className="text-muted-foreground block">CPU Usage</span>
                                    <span className="font-bold">{dep.metrics?.cpu ?? 0.0}%</span>
                                  </div>
                                  <div>
                                    <span className="text-muted-foreground block">Memory</span>
                                    <span className="font-bold">{dep.metrics?.memory ?? 0} MB</span>
                                  </div>
                                  <div>
                                    <span className="text-muted-foreground block">Latency</span>
                                    <span className="font-bold">{dep.metrics?.latency ?? 0}ms</span>
                                  </div>
                                  <div>
                                    <span className="text-muted-foreground block">Evaluation Rate</span>
                                    <span className="font-bold">Every tick</span>
                                  </div>
                                </div>
                              </div>
                              <div className="text-[10px] text-muted-foreground border-t border-border/50 pt-2 flex items-center justify-between">
                                <span>Health score: {dep.health_score}%</span>
                                <span>Last tick: {dep.metrics?.last_tick ?? 'N/A'}</span>
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
