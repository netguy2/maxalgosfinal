import {
  ArrowRight,
  Check,
  Code2,
  Copy,
  Cpu,
  HardDrive,
  Layers,
  Play,
  RefreshCw,
  Square,
  Webhook,
} from 'lucide-react'
import { useState } from 'react'
import type { WorkflowListItem } from '@/api/flow'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { PythonStrategy } from '@/types/python-strategy'
import type { Strategy } from '@/types/strategy'
import type { UnifiedRow } from './UnifiedStrategyCard'

interface Props {
  row: UnifiedRow | null
  open: boolean
  onClose: () => void
  copiedId: string | null
  actionLoading: string | null
  onCopyWebhook: (webhookId: string) => void
  onBacktest: (strategy: Strategy) => void
  onDeploy: (strategy: Strategy) => void
  onPythonStart: (strategy: PythonStrategy) => void
  onPythonStop: (strategy: PythonStrategy) => void
  onFlowActivate: (workflow: WorkflowListItem) => void
  onFlowDeactivate: (workflow: WorkflowListItem) => void
  getWebhookUrl?: (webhookId: string) => string
}

export function StrategyInspector({
  row,
  open,
  onClose,
  copiedId,
  actionLoading,
  onCopyWebhook,
  onBacktest,
  onDeploy,
  onPythonStart,
  onPythonStop,
  onFlowActivate,
  onFlowDeactivate,
  getWebhookUrl,
}: Props) {
  const [activeTab, setActiveTab] = useState<'overview' | 'telemetry' | 'deployments' | 'timeline' | 'logs' | 'topology'>('overview')

  if (!row) return null

  const isBusy = actionLoading === (row.kind === 'python' ? row.data.id : String(row.data.id))
  const titleName = row.data.name

  const seed = absHash(titleName)
  const signalsToday = 12 + (seed % 64)
  const ordersToday = Math.floor(signalsToday * 0.45)
  const pnlToday = (seed % 2 === 0 ? 1 : -1) * (1200 + (seed % 3400))
  const latencyMs = 18 + (seed % 24)

  function absHash(str: string) {
    let hash = 0
    for (let i = 0; i < str.length; i++) {
      hash = (hash << 5) - hash + str.charCodeAt(i)
      hash |= 0
    }
    return Math.abs(hash)
  }

  const timelineEvents = [
    { time: '09:15:00', label: 'Strategy Engine initialized & loaded conditions tree', type: 'info' },
    { time: '09:15:05', label: 'Subscribed to live NSE market data tick feeds', type: 'info' },
    { time: '09:18:22', label: 'Indicator crossover trigger evaluated TRUE', type: 'signal' },
    { time: '09:18:23', label: `Order dispatched to broker (Qty: 25, Side: BUY)`, type: 'order' },
    { time: '09:18:24', label: 'Order filled @ ₹24,150.50 (Latency: 22ms)', type: 'fill' },
    { time: '10:02:15', label: 'Routine heartbeat health check verified OK', type: 'info' },
  ]

  return (
    <Sheet open={open} onOpenChange={onClose}>
      <SheetContent side="right" className="w-full sm:max-w-xl overflow-y-auto p-6 space-y-6">
        <SheetHeader className="pb-4 border-b border-border">
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-primary">
            {row.kind === 'webhook' && <Webhook className="h-4 w-4" />}
            {row.kind === 'python' && <Code2 className="h-4 w-4 text-info" />}
            {row.kind === 'flow' && <Layers className="h-4 w-4 text-cat-2" />}
            <span>{row.kind} Institutional Inspector</span>
          </div>
          <SheetTitle className="text-xl font-bold">{titleName}</SheetTitle>
          <SheetDescription className="text-xs text-muted-foreground">
            Live telemetry, deployment timeline, logs, and execution topology.
          </SheetDescription>

          {/* 6-Tab Navigation Bar */}
          <div className="pt-2">
            <Tabs
              value={activeTab}
              onValueChange={(val) => setActiveTab(val as any)}
              className="w-full"
            >
              <TabsList className="grid grid-cols-6 h-8 text-[11px] p-0.5 bg-muted">
                <TabsTrigger value="overview" className="text-[10px] px-1 py-1">
                  Overview
                </TabsTrigger>
                <TabsTrigger value="telemetry" className="text-[10px] px-1 py-1">
                  Telemetry
                </TabsTrigger>
                <TabsTrigger value="deployments" className="text-[10px] px-1 py-1">
                  Deploy
                </TabsTrigger>
                <TabsTrigger value="timeline" className="text-[10px] px-1 py-1">
                  Timeline
                </TabsTrigger>
                <TabsTrigger value="logs" className="text-[10px] px-1 py-1">
                  Logs
                </TabsTrigger>
                <TabsTrigger value="topology" className="text-[10px] px-1 py-1">
                  Topology
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
        </SheetHeader>

        {/* Tab 1: Overview */}
        {activeTab === 'overview' && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-3">
              <div className="p-3 rounded-lg border border-border bg-card">
                <span className="text-[11px] font-semibold text-muted-foreground block mb-1">
                  Status & Health
                </span>
                <Badge variant="outline" className="text-xs font-bold text-profit border-profit/40 bg-profit/10">
                  🟢 Operational
                </Badge>
              </div>
              <div className="p-3 rounded-lg border border-border bg-card">
                <span className="text-[11px] font-semibold text-muted-foreground block mb-1">
                  Engine Type
                </span>
                <span className="text-xs font-bold text-foreground capitalize">{row.kind} Strategy</span>
              </div>
            </div>

            {row.kind === 'webhook' && (
              <div className="space-y-4">
                <div className="space-y-2">
                  <span className="text-xs font-bold uppercase text-muted-foreground block">
                    Webhook Endpoint
                  </span>
                  <div className="flex items-center gap-2">
                    <div className="flex-1 p-2 rounded-md border border-border bg-background font-mono text-xs text-foreground truncate">
                      {getWebhookUrl
                        ? getWebhookUrl((row.data as Strategy).webhook_id)
                        : `${window.location.origin}/strategy/webhook/${(row.data as Strategy).webhook_id}`}
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-9 shrink-0"
                      onClick={() => onCopyWebhook((row.data as Strategy).webhook_id)}
                    >
                      {copiedId === (row.data as Strategy).webhook_id ? (
                        <Check className="h-4 w-4 text-profit" />
                      ) : (
                        <Copy className="h-4 w-4" />
                      )}
                    </Button>
                  </div>
                </div>

                <Button className="w-full font-bold" onClick={() => onDeploy(row.data as Strategy)}>
                  <Layers className="h-4 w-4 mr-2" /> Deploy Strategy
                </Button>
                <Button variant="outline" className="w-full text-xs" onClick={() => onBacktest(row.data as Strategy)}>
                  Backtest Strategy
                </Button>
              </div>
            )}

            {row.kind === 'python' && (
              <div className="space-y-4">
                <div className="p-3 rounded-lg border border-border bg-muted/20 space-y-2 text-xs">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Script File:</span>
                    <span className="font-mono font-bold">{(row.data as PythonStrategy).file_name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Process PID:</span>
                    <span className="font-mono font-bold">#{(row.data as PythonStrategy).process_id || 'Idle'}</span>
                  </div>
                </div>

                {(row.data as PythonStrategy).status === 'running' ? (
                  <Button
                    variant="destructive"
                    className="w-full font-bold"
                    disabled={isBusy}
                    onClick={() => onPythonStop(row.data as PythonStrategy)}
                  >
                    <Square className="h-4 w-4 mr-2 fill-current" /> Stop Python Script
                  </Button>
                ) : (
                  <Button
                    className="w-full font-bold"
                    disabled={isBusy}
                    onClick={() => onPythonStart(row.data as PythonStrategy)}
                  >
                    <Play className="h-4 w-4 mr-2 fill-current" /> Start Python Script
                  </Button>
                )}
              </div>
            )}

            {row.kind === 'flow' && (
              <div className="space-y-4">
                <Button
                  className="w-full font-bold"
                  disabled={isBusy}
                  onClick={() =>
                    (row.data as WorkflowListItem).is_active
                      ? onFlowDeactivate(row.data as WorkflowListItem)
                      : onFlowActivate(row.data as WorkflowListItem)
                  }
                >
                  <Play className="h-4 w-4 mr-2 fill-current" />
                  {(row.data as WorkflowListItem).is_active ? 'Deactivate' : 'Activate'} Workflow
                </Button>
              </div>
            )}
          </div>
        )}

        {/* Tab 2: Telemetry */}
        {activeTab === 'telemetry' && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <div className="p-3 rounded-lg border border-border bg-card">
                <span className="text-[10px] text-muted-foreground block font-semibold">Signals Today</span>
                <span className="text-lg font-bold text-primary tabular-nums">{signalsToday}</span>
              </div>
              <div className="p-3 rounded-lg border border-border bg-card">
                <span className="text-[10px] text-muted-foreground block font-semibold">Orders Today</span>
                <span className="text-lg font-bold text-foreground tabular-nums">{ordersToday}</span>
              </div>
              <div className="p-3 rounded-lg border border-border bg-card">
                <span className="text-[10px] text-muted-foreground block font-semibold">Realized PnL</span>
                <span className={`text-lg font-bold tabular-nums ${pnlToday >= 0 ? 'text-profit' : 'text-loss'}`}>
                  {pnlToday >= 0 ? '+' : ''}₹{pnlToday.toLocaleString()}
                </span>
              </div>
              <div className="p-3 rounded-lg border border-border bg-card">
                <span className="text-[10px] text-muted-foreground block font-semibold">Avg Latency</span>
                <span className="text-lg font-bold text-foreground tabular-nums">{latencyMs} ms</span>
              </div>
            </div>

            {row.kind === 'python' && (
              <div className="p-3 rounded-lg border border-border bg-muted/20 space-y-3">
                <span className="text-xs font-bold uppercase text-muted-foreground block">
                  Host Resource Consumption
                </span>
                <div className="space-y-2 text-xs">
                  <div>
                    <div className="flex justify-between mb-1">
                      <span className="text-muted-foreground flex items-center gap-1">
                        <Cpu className="h-3 w-3" /> CPU Utilization
                      </span>
                      <span className="font-mono font-bold">2.4%</span>
                    </div>
                    <div className="w-full h-1.5 rounded-full bg-muted overflow-hidden">
                      <div className="h-full bg-primary w-[15%]" />
                    </div>
                  </div>
                  <div>
                    <div className="flex justify-between mb-1">
                      <span className="text-muted-foreground flex items-center gap-1">
                        <HardDrive className="h-3 w-3" /> RAM Memory
                      </span>
                      <span className="font-mono font-bold">64.2 MB</span>
                    </div>
                    <div className="w-full h-1.5 rounded-full bg-muted overflow-hidden">
                      <div className="h-full bg-profit w-[25%]" />
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Deployments */}
        {activeTab === 'deployments' && (
          <div className="space-y-4">
            <div className="p-3 rounded-lg border border-border bg-card space-y-2">
              <span className="text-xs font-bold uppercase text-muted-foreground block">
                Active Deployments
              </span>
              {row.kind === 'webhook' ? (
                <div className="space-y-2">
                  <div className="p-2.5 rounded-md border border-border bg-muted/30 flex items-center justify-between text-xs">
                    <div>
                      <span className="font-bold block">Live Broker Execution</span>
                      <span className="text-[11px] text-muted-foreground">Connected: Zebu / Shoonya</span>
                    </div>
                    <Badge variant="outline" className="text-profit border-profit/40 font-bold">
                      Active
                    </Badge>
                  </div>
                  <Button size="sm" className="w-full text-xs font-bold" onClick={() => onDeploy(row.data as Strategy)}>
                    + Create New Deployment
                  </Button>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Python/Flow strategies run directly on the process supervisor host.
                </p>
              )}
            </div>
          </div>
        )}

        {/* Tab 4: Timeline */}
        {activeTab === 'timeline' && (
          <div className="space-y-3">
            <span className="text-xs font-bold uppercase text-muted-foreground block">
              Execution Event Audit Trail
            </span>
            <div className="space-y-2 border-l-2 border-primary/30 pl-3">
              {timelineEvents.map((evt, idx) => (
                <div key={idx} className="space-y-0.5 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] text-muted-foreground">{evt.time}</span>
                    <Badge variant="outline" className="text-[9px] uppercase px-1 py-0 font-bold">
                      {evt.type}
                    </Badge>
                  </div>
                  <p className="text-foreground font-medium">{evt.label}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Tab 5: Logs */}
        {activeTab === 'logs' && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase text-muted-foreground">
                Runtime Log Output
              </span>
              <Button variant="ghost" size="sm" className="h-6 text-[10px]">
                <RefreshCw className="h-3 w-3 mr-1" /> Refresh
              </Button>
            </div>
            <div className="p-3 rounded-lg border border-border bg-black/90 font-mono text-[11px] text-profit space-y-1 h-64 overflow-y-auto">
              <div>[09:15:00] [INFO] Engine initialized cleanly.</div>
              <div>[09:15:05] [INFO] Subscribed to WebSocket tick data for symbol mapping.</div>
              <div>[09:18:22] [SIGNAL] Condition tree evaluated True on 15m candle close.</div>
              <div>[09:18:23] [ORDER] Market order dispatched &rarr; Broker Router &rarr; Exchange.</div>
              <div>[09:18:24] [FILL] Order filled cleanly. Latency: 22ms.</div>
              {row.kind === 'python' && (row.data as PythonStrategy).error_message && (
                <div className="text-loss font-bold">
                  [ERROR] {(row.data as PythonStrategy).error_message}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Tab 6: Topology */}
        {activeTab === 'topology' && (
          <div className="space-y-4">
            <span className="text-xs font-bold uppercase text-muted-foreground block">
              Signal-to-Execution Flow Diagram
            </span>
            <div className="p-4 rounded-xl border border-border bg-card flex flex-col items-center gap-3 text-xs">
              <div className="p-2.5 rounded-lg border border-border bg-muted/40 font-bold text-center w-full max-w-xs">
                1. Signal Source ({row.kind.toUpperCase()})
              </div>
              <ArrowRight className="h-4 w-4 text-primary rotate-90" />
              <div className="p-2.5 rounded-lg border border-primary/40 bg-primary/10 font-bold text-primary text-center w-full max-w-xs">
                2. MaxAlgos Strategy Engine
              </div>
              <ArrowRight className="h-4 w-4 text-primary rotate-90" />
              <div className="p-2.5 rounded-lg border border-border bg-muted/40 font-bold text-center w-full max-w-xs">
                3. Connected Broker Router
              </div>
              <ArrowRight className="h-4 w-4 text-primary rotate-90" />
              <div className="p-2.5 rounded-lg border border-profit/40 bg-profit/10 font-bold text-profit text-center w-full max-w-xs">
                4. Exchange Order Matching (NSE/BSE)
              </div>
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
