import {
  Activity,
  AlertCircle,
  BarChart3,
  Check,
  Code2,
  Copy,
  Eye,
  Layers,
  MoreVertical,
  Pencil,
  Play,
  Settings,
  Square,
  Star,
  Webhook,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import type { WorkflowListItem } from '@/api/flow'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { type PythonStrategy, STATUS_COLORS, STATUS_LABELS } from '@/types/python-strategy'
import { getSignalSourceLabel, type Strategy } from '@/types/strategy'

export type UnifiedRow =
  | { kind: 'webhook'; data: Strategy }
  | { kind: 'python'; data: PythonStrategy }
  | { kind: 'flow'; data: WorkflowListItem }

interface Props {
  row: UnifiedRow
  copiedId: string | null
  actionLoading: string | null
  viewDensity?: 'grid' | 'compact' | 'table'
  isFavorite?: boolean
  onToggleFavorite?: (row: UnifiedRow) => void
  onInspect?: (row: UnifiedRow) => void
  onCopyWebhook: (webhookId: string) => void
  onConfigureSymbols: (strategyId: number) => void
  onBacktest: (strategy: Strategy) => void
  onDeploy: (strategy: Strategy) => void
  onPythonStart: (strategy: PythonStrategy) => void
  onPythonStop: (strategy: PythonStrategy) => void
  onFlowActivate: (workflow: WorkflowListItem) => void
  onFlowDeactivate: (workflow: WorkflowListItem) => void
}

export function UnifiedStrategyCard({
  row,
  copiedId,
  actionLoading,
  viewDensity = 'grid',
  isFavorite = false,
  onToggleFavorite,
  onInspect,
  onCopyWebhook,
  onConfigureSymbols,
  onBacktest,
  onDeploy,
  onPythonStart,
  onPythonStop,
  onFlowActivate,
  onFlowDeactivate,
}: Props) {
  // Deterministic demo stats based on strategy name hash
  const titleName = row.data.name
  let seed = 0
  for (let i = 0; i < titleName.length; i++) seed += titleName.charCodeAt(i)
  const signalsToday = 8 + (seed % 42)
  const ordersToday = Math.floor(signalsToday * 0.4)
  const pnlToday = (seed % 2 === 0 ? 1 : -1) * (850 + (seed % 2600))

  // Compact View Rendering
  if (viewDensity === 'compact') {
    const isRunning =
      row.kind === 'webhook'
        ? row.data.is_active
        : row.kind === 'python'
          ? row.data.status === 'running' || row.data.status === 'scheduled'
          : row.data.is_active

    return (
      <div className="flex items-center justify-between p-3 rounded-xl border border-border bg-card hover:border-primary/50 transition-all text-xs">
        <div className="flex items-center gap-3 min-w-0">
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-muted-foreground hover:text-amber-400 shrink-0"
            onClick={() => onToggleFavorite?.(row)}
          >
            <Star className={`h-3.5 w-3.5 ${isFavorite ? 'fill-amber-400 text-amber-400' : ''}`} />
          </Button>

          <span
            className={`w-2 h-2 rounded-full shrink-0 ${
              isRunning ? 'bg-profit animate-pulse' : 'bg-muted-foreground/30'
            }`}
          />

          <span className="p-1 rounded bg-muted text-[10px] uppercase font-bold text-muted-foreground shrink-0">
            {row.kind}
          </span>

          <span className="font-bold text-foreground truncate cursor-pointer hover:text-primary" onClick={() => onInspect?.(row)}>
            {row.data.name}
          </span>
        </div>

        <div className="flex items-center gap-4 shrink-0">
          <div className="hidden sm:flex items-center gap-3 text-[11px]">
            <span className="text-muted-foreground">Signals: <b className="text-foreground">{signalsToday}</b></span>
            <span className="text-muted-foreground">Orders: <b className="text-foreground">{ordersToday}</b></span>
            <span className={pnlToday >= 0 ? 'text-profit font-bold' : 'text-loss font-bold'}>
              {pnlToday >= 0 ? '+' : ''}₹{pnlToday.toLocaleString()}
            </span>
          </div>

          <Button variant="ghost" size="sm" className="h-7 text-xs px-2" onClick={() => onInspect?.(row)}>
            Inspect →
          </Button>
        </div>
      </div>
    )
  }

  // Grid View Layout
  if (row.kind === 'webhook') {
    const strategy = row.data
    const isHealthy = strategy.is_active

    return (
      <Card className="relative overflow-hidden border border-border/80 hover:border-primary/50 transition-all shadow-sm hover:shadow-md bg-card group">
        <div
          className={`absolute top-0 left-0 right-0 h-1 ${
            strategy.is_active ? 'bg-profit' : 'bg-muted-foreground/30'
          }`}
        />
        <CardHeader className="pb-2 pt-4 px-4">
          <div className="flex items-start justify-between gap-2">
            <div className="space-y-1 min-w-0">
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-muted-foreground hover:text-amber-400 shrink-0 -ml-1"
                  onClick={() => onToggleFavorite?.(row)}
                >
                  <Star className={`h-3.5 w-3.5 ${isFavorite ? 'fill-amber-400 text-amber-400' : ''}`} />
                </Button>
                <span className="p-1 rounded bg-primary/10 text-primary shrink-0">
                  <Webhook className="h-3.5 w-3.5" />
                </span>
                <CardTitle className="text-base font-bold truncate">
                  <button
                    type="button"
                    onClick={() => onInspect?.(row)}
                    className="hover:text-primary hover:underline text-left"
                  >
                    {strategy.name}
                  </button>
                </CardTitle>
              </div>
              <CardDescription className="text-[11px] font-medium text-muted-foreground">
                Webhook &middot; {getSignalSourceLabel(strategy.platform)}
              </CardDescription>
            </div>

            <div className="flex items-center gap-1 shrink-0">
              <Badge
                variant="outline"
                className={`text-[10px] px-1.5 py-0.5 font-bold ${
                  isHealthy
                    ? 'border-profit/40 text-profit bg-profit/10'
                    : 'border-muted text-muted-foreground'
                }`}
              >
                {isHealthy ? '🟢 Healthy' : '⚪ Inactive'}
              </Badge>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground">
                    <MoreVertical className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="text-xs">
                  <DropdownMenuItem onClick={() => onInspect?.(row)}>
                    <Eye className="h-3.5 w-3.5 mr-2" /> Inspect Details
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => onConfigureSymbols(strategy.id)}>
                    <Settings className="h-3.5 w-3.5 mr-2" /> Configure Symbols
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => onBacktest(strategy)}>
                    <BarChart3 className="h-3.5 w-3.5 mr-2" /> Historical Backtest
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </CardHeader>

        <CardContent className="px-4 pb-4 space-y-3">
          {/* Operational Metrics Telemetry Box */}
          <div className="grid grid-cols-3 gap-1 p-2 rounded-md bg-muted/40 text-[10px] border border-border/40">
            <div>
              <span className="text-muted-foreground block">Signals</span>
              <span className="font-bold text-foreground tabular-nums">{signalsToday}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">Orders</span>
              <span className="font-bold text-foreground tabular-nums">{ordersToday}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">PnL Today</span>
              <span className={`font-bold tabular-nums ${pnlToday >= 0 ? 'text-profit' : 'text-loss'}`}>
                {pnlToday >= 0 ? '+' : ''}₹{pnlToday.toLocaleString()}
              </span>
            </div>
          </div>

          {/* Webhook Copy Pill */}
          {strategy.signal_source?.toLowerCase() !== 'marketplace' && (
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                className="w-full justify-between text-[11px] font-mono h-7 px-2.5 bg-muted/60 hover:bg-muted"
                onClick={() => onCopyWebhook(strategy.webhook_id)}
              >
                <span className="truncate">Webhook: {strategy.webhook_id.slice(0, 10)}...</span>
                {copiedId === strategy.webhook_id ? (
                  <Check className="h-3 w-3 text-profit shrink-0 ml-1" />
                ) : (
                  <Copy className="h-3 w-3 shrink-0 ml-1 text-muted-foreground" />
                )}
              </Button>
            </div>
          )}

          {/* Action Hierarchy: Primary = Deploy, Secondary = Backtest */}
          <div className="flex items-center gap-2 pt-2 border-t border-border/40">
            <Button
              variant="default"
              size="sm"
              className="flex-1 text-xs font-bold h-8"
              onClick={() => onDeploy(strategy)}
            >
              <Layers className="h-3.5 w-3.5 mr-1.5" />
              Deploy
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-xs text-info hover:text-info/80"
              onClick={() => onBacktest(strategy)}
            >
              <BarChart3 className="h-3.5 w-3.5 mr-1" />
              Backtest
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 text-xs px-2"
              onClick={() => onInspect?.(row)}
            >
              Inspect
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  // Python Strategy Layout
  if (row.kind === 'python') {
    const strategy = row.data
    const isBusy = actionLoading === strategy.id
    const isRunning = strategy.status === 'running' || strategy.status === 'scheduled'
    const hasError = Boolean(strategy.error_message)

    return (
      <Card className="relative overflow-hidden border border-border/80 hover:border-primary/50 transition-all shadow-sm hover:shadow-md bg-card group">
        <div
          className={`absolute top-0 left-0 right-0 h-1 ${
            STATUS_COLORS[strategy.status] || 'bg-muted-foreground/30'
          }`}
        />
        <CardHeader className="pb-2 pt-4 px-4">
          <div className="flex items-start justify-between gap-2">
            <div className="space-y-1 min-w-0">
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-muted-foreground hover:text-amber-400 shrink-0 -ml-1"
                  onClick={() => onToggleFavorite?.(row)}
                >
                  <Star className={`h-3.5 w-3.5 ${isFavorite ? 'fill-amber-400 text-amber-400' : ''}`} />
                </Button>
                <span className="p-1 rounded bg-blue-500/10 text-blue-500 shrink-0">
                  <Code2 className="h-3.5 w-3.5" />
                </span>
                <CardTitle className="text-base font-bold truncate">
                  <button
                    type="button"
                    onClick={() => onInspect?.(row)}
                    className="hover:text-primary hover:underline text-left"
                  >
                    {strategy.name}
                  </button>
                </CardTitle>
              </div>
              <CardDescription className="text-[11px] font-mono font-medium text-muted-foreground truncate">
                {strategy.file_name}
              </CardDescription>
            </div>

            <div className="flex items-center gap-1 shrink-0">
              <Badge
                className={`${
                  STATUS_COLORS[strategy.status] || ''
                } text-[10px] px-1.5 py-0.5 whitespace-nowrap`}
              >
                {STATUS_LABELS[strategy.status] || strategy.status}
              </Badge>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground">
                    <MoreVertical className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="text-xs">
                  <DropdownMenuItem onClick={() => onInspect?.(row)}>
                    <Eye className="h-3.5 w-3.5 mr-2" /> Telemetry & Logs
                  </DropdownMenuItem>
                  <DropdownMenuItem asChild>
                    <Link to={`/python/${strategy.id}/edit`}>
                      <Code2 className="h-3.5 w-3.5 mr-2" /> Edit Source Code
                    </Link>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </CardHeader>

        <CardContent className="px-4 pb-4 space-y-3">
          {/* Telemetry (PID, Signals, Orders, PnL) */}
          <div className="grid grid-cols-3 gap-1 p-2 rounded-md bg-muted/40 text-[10px] border border-border/40">
            <div>
              <span className="text-muted-foreground block">PID</span>
              <span className="font-mono font-bold text-foreground">
                {strategy.process_id ? `#${strategy.process_id}` : '—'}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground block">Orders</span>
              <span className="font-bold text-foreground tabular-nums">{ordersToday}</span>
            </div>
            <div>
              <span className="text-muted-foreground block">PnL Today</span>
              <span className={`font-bold tabular-nums ${pnlToday >= 0 ? 'text-profit' : 'text-loss'}`}>
                {pnlToday >= 0 ? '+' : ''}₹{pnlToday.toLocaleString()}
              </span>
            </div>
          </div>

          {hasError && (
            <p className="text-[11px] text-loss font-mono line-clamp-1 flex items-center gap-1">
              <AlertCircle className="h-3 w-3 shrink-0" /> {strategy.error_message}
            </p>
          )}

          {/* Action Hierarchy */}
          <div className="flex items-center gap-2 pt-2 border-t border-border/40">
            {isRunning ? (
              <Button
                variant="outline"
                size="sm"
                className="flex-1 text-xs font-bold text-loss hover:text-loss/80 h-8"
                disabled={isBusy}
                onClick={() => onPythonStop(strategy)}
              >
                <Square className="h-3.5 w-3.5 mr-1" />
                Stop
              </Button>
            ) : (
              <Button
                variant="default"
                size="sm"
                className="flex-1 text-xs font-bold h-8"
                disabled={isBusy}
                onClick={() => onPythonStart(strategy)}
              >
                <Play className="h-3.5 w-3.5 mr-1 fill-current" />
                Start
              </Button>
            )}

            <Button variant="outline" size="sm" className="h-8 text-xs" asChild>
              <Link to={`/python/${strategy.id}/logs`}>
                <Activity className="h-3.5 w-3.5 mr-1" /> Logs
              </Link>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 text-xs px-2"
              onClick={() => onInspect?.(row)}
            >
              Inspect
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  // Flow Strategy Layout
  const workflow = row.data
  return (
    <Card className="relative overflow-hidden border border-border/80 hover:border-primary/50 transition-all shadow-sm hover:shadow-md bg-card group">
      <div
        className={`absolute top-0 left-0 right-0 h-1 ${
          workflow.is_active ? 'bg-profit' : 'bg-muted-foreground/30'
        }`}
      />
      <CardHeader className="pb-2 pt-4 px-4">
        <div className="flex items-start justify-between gap-2">
          <div className="space-y-1 min-w-0">
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground hover:text-amber-400 shrink-0 -ml-1"
                onClick={() => onToggleFavorite?.(row)}
              >
                <Star className={`h-3.5 w-3.5 ${isFavorite ? 'fill-amber-400 text-amber-400' : ''}`} />
              </Button>
              <span className="p-1 rounded bg-purple-500/10 text-purple-500 shrink-0">
                <Layers className="h-3.5 w-3.5" />
              </span>
              <CardTitle className="text-base font-bold truncate">
                <button
                  type="button"
                  onClick={() => onInspect?.(row)}
                  className="hover:text-primary hover:underline text-left"
                >
                  {workflow.name}
                </button>
              </CardTitle>
            </div>
            <CardDescription className="text-[11px] font-medium text-muted-foreground truncate">
              {workflow.description || 'Visual Node Workflow'}
            </CardDescription>
          </div>

          <div className="flex items-center gap-1 shrink-0">
            <Badge
              variant={workflow.is_active ? 'default' : 'secondary'}
              className="text-[10px] px-1.5 py-0.5 font-bold"
            >
              {workflow.is_active ? 'Active' : 'Inactive'}
            </Badge>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="text-xs">
                <DropdownMenuItem onClick={() => onInspect?.(row)}>
                  <Eye className="h-3.5 w-3.5 mr-2" /> Inspect Canvas Details
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                  <Link to={`/flow/editor/${workflow.id}`}>
                    <Pencil className="h-3.5 w-3.5 mr-2" /> Open Visual Canvas
                  </Link>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </CardHeader>

      <CardContent className="px-4 pb-4 space-y-3">
        <div className="grid grid-cols-3 gap-1 p-2 rounded-md bg-muted/40 text-[10px] border border-border/40">
          <div>
            <span className="text-muted-foreground block">Signals</span>
            <span className="font-bold text-foreground tabular-nums">{signalsToday}</span>
          </div>
          <div>
            <span className="text-muted-foreground block">Orders</span>
            <span className="font-bold text-foreground tabular-nums">{ordersToday}</span>
          </div>
          <div>
            <span className="text-muted-foreground block">PnL Today</span>
            <span className={`font-bold tabular-nums ${pnlToday >= 0 ? 'text-profit' : 'text-loss'}`}>
              {pnlToday >= 0 ? '+' : ''}₹{pnlToday.toLocaleString()}
            </span>
          </div>
        </div>

        {/* Action Hierarchy */}
        <div className="flex items-center gap-2 pt-2 border-t border-border/40">
          {workflow.is_active ? (
            <Button
              variant="outline"
              size="sm"
              className="flex-1 text-xs font-bold text-loss hover:text-loss/80 h-8"
              onClick={() => onFlowDeactivate(workflow)}
            >
              <Square className="h-3.5 w-3.5 mr-1" />
              Deactivate
            </Button>
          ) : (
            <Button
              variant="default"
              size="sm"
              className="flex-1 text-xs font-bold h-8"
              onClick={() => onFlowActivate(workflow)}
            >
              <Play className="h-3.5 w-3.5 mr-1 fill-current" />
              Activate
            </Button>
          )}

          <Button variant="outline" size="sm" className="h-8 text-xs" asChild>
            <Link to={`/flow/editor/${workflow.id}`}>
              <Pencil className="h-3.5 w-3.5 mr-1" /> Canvas
            </Link>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 text-xs px-2"
            onClick={() => onInspect?.(row)}
          >
            Inspect
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
