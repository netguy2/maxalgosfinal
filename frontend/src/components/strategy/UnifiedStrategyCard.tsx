import {
  AlertCircle,
  BarChart3,
  Code2,
  Layers,
  MoreHorizontal,
  Pencil,
  Play,
  Settings,
  Square,
  Webhook,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import type { WorkflowListItem } from '@/api/flow'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { type PythonStrategy, STATUS_LABELS } from '@/types/python-strategy'
import { type Strategy } from '@/types/strategy'

export type UnifiedRow =
  | { kind: 'webhook'; data: Strategy }
  | { kind: 'python'; data: PythonStrategy }
  | { kind: 'flow'; data: WorkflowListItem }

interface Props {
  row: UnifiedRow
  copiedId: string | null
  actionLoading: string | null
  onInspect: (row: UnifiedRow) => void
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
  actionLoading,
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
  const isRunning =
    row.kind === 'webhook'
      ? row.data.is_active
      : row.kind === 'python'
        ? row.data.status === 'running' || row.data.status === 'scheduled'
        : row.data.is_active

  const hasError =
    row.kind === 'python' && Boolean(row.data.error_message || row.data.status === 'error')

  const isBusy =
    actionLoading === (row.kind === 'python' ? row.data.id : String(row.data.id))

  // Engine label & icon
  const engineIcon =
    row.kind === 'webhook' ? (
      <Webhook className="h-3 w-3" />
    ) : row.kind === 'python' ? (
      <Code2 className="h-3 w-3" />
    ) : (
      <Layers className="h-3 w-3" />
    )

  const engineLabel =
    row.kind === 'webhook' ? 'Webhook' : row.kind === 'python' ? 'Python' : 'Flow'

  // Status text
  const statusLabel =
    row.kind === 'python'
      ? STATUS_LABELS[row.data.status] || row.data.status
      : isRunning
        ? 'Running'
        : 'Stopped'

  // Border accent
  const borderAccent = hasError
    ? 'border-l-destructive'
    : isRunning
      ? 'border-l-profit'
      : 'border-l-transparent'

  return (
    <div
      className={`group relative bg-card border border-border border-l-2 ${borderAccent} rounded-xl p-4 cursor-pointer hover:border-border/80 hover:shadow-sm transition-all`}
      onClick={() => onInspect(row)}
    >
      {/* Top row: status dot + name + menu */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2.5 min-w-0">
          {/* Status dot */}
          <div className="mt-1 shrink-0">
            {hasError ? (
              <AlertCircle className="h-3.5 w-3.5 text-destructive" />
            ) : isRunning ? (
              <span className="block w-2 h-2 rounded-full bg-profit animate-pulse mt-0.5" />
            ) : (
              <span className="block w-2 h-2 rounded-full bg-muted-foreground/30 mt-0.5" />
            )}
          </div>

          <div className="min-w-0">
            <p className="text-sm font-semibold text-foreground truncate leading-tight">
              {row.data.name}
            </p>
            <div className="flex items-center gap-1.5 mt-1">
              <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                {engineIcon}
                {engineLabel}
              </span>
              <span className="text-muted-foreground/40 text-[11px]">·</span>
              <span
                className={`text-[11px] font-medium ${
                  hasError
                    ? 'text-destructive'
                    : isRunning
                      ? 'text-profit'
                      : 'text-muted-foreground'
                }`}
              >
                {statusLabel}
              </span>
              {row.kind === 'python' && row.data.process_id && isRunning && (
                <>
                  <span className="text-muted-foreground/40 text-[11px]">·</span>
                  <span className="text-[11px] text-muted-foreground font-mono">
                    PID {row.data.process_id}
                  </span>
                </>
              )}
            </div>
          </div>
        </div>

        {/* ··· overflow menu — stop click from bubbling to card */}
        <div onClick={(e) => e.stopPropagation()}>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="opacity-0 group-hover:opacity-100 transition-opacity h-7 w-7 flex items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="text-xs w-44">
              <DropdownMenuItem
                onClick={() => onInspect(row)}
                className="text-xs"
              >
                Inspect details
              </DropdownMenuItem>

              {row.kind === 'webhook' && (
                <>
                  <DropdownMenuItem
                    onClick={() => onBacktest(row.data as Strategy)}
                    className="text-xs"
                  >
                    <BarChart3 className="h-3.5 w-3.5 mr-2" /> Backtest
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => onCopyWebhook((row.data as Strategy).webhook_id)}
                    className="text-xs"
                  >
                    <Webhook className="h-3.5 w-3.5 mr-2" /> Copy webhook URL
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => onConfigureSymbols((row.data as Strategy).id)}
                    className="text-xs"
                  >
                    <Settings className="h-3.5 w-3.5 mr-2" /> Configure symbols
                  </DropdownMenuItem>
                </>
              )}

              {row.kind === 'python' && (
                <DropdownMenuItem asChild className="text-xs">
                  <Link to={`/python/${row.data.id}/edit`}>
                    <Pencil className="h-3.5 w-3.5 mr-2" /> Edit script
                  </Link>
                </DropdownMenuItem>
              )}

              {row.kind === 'flow' && (
                <DropdownMenuItem asChild className="text-xs">
                  <Link to={`/flow/editor/${row.data.id}`}>
                    <Pencil className="h-3.5 w-3.5 mr-2" /> Open canvas
                  </Link>
                </DropdownMenuItem>
              )}

              {row.kind === 'webhook' && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => onDeploy(row.data as Strategy)}
                    className="text-xs font-semibold"
                  >
                    Deploy to broker
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Error message */}
      {hasError && (row.data as PythonStrategy).error_message && (
        <p className="mt-2 text-[11px] text-destructive font-mono line-clamp-1">
          {(row.data as PythonStrategy).error_message}
        </p>
      )}

      {/* Bottom action row — stop click from bubbling */}
      <div
        className="mt-4 pt-3 border-t border-border/50 flex items-center gap-2"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Primary action */}
        {row.kind === 'webhook' && (
          <Button
            size="sm"
            className="h-7 text-xs font-semibold flex-1"
            onClick={() => onDeploy(row.data as Strategy)}
          >
            Deploy
          </Button>
        )}

        {row.kind === 'python' && (
          <>
            {isRunning ? (
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs font-semibold flex-1 text-destructive hover:text-destructive border-destructive/30"
                disabled={isBusy}
                onClick={() => onPythonStop(row.data as PythonStrategy)}
              >
                <Square className="h-3 w-3 mr-1 fill-current" />
                Stop
              </Button>
            ) : (
              <Button
                size="sm"
                className="h-7 text-xs font-semibold flex-1"
                disabled={isBusy}
                onClick={() => onPythonStart(row.data as PythonStrategy)}
              >
                <Play className="h-3 w-3 mr-1 fill-current" />
                Start
              </Button>
            )}
            <Button variant="ghost" size="sm" className="h-7 text-xs" asChild>
              <Link to={`/python/${row.data.id}/logs`}>Logs</Link>
            </Button>
          </>
        )}

        {row.kind === 'flow' && (
          <>
            {isRunning ? (
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs font-semibold flex-1 text-destructive hover:text-destructive border-destructive/30"
                disabled={isBusy}
                onClick={() => onFlowDeactivate(row.data as WorkflowListItem)}
              >
                <Square className="h-3 w-3 mr-1 fill-current" />
                Deactivate
              </Button>
            ) : (
              <Button
                size="sm"
                className="h-7 text-xs font-semibold flex-1"
                disabled={isBusy}
                onClick={() => onFlowActivate(row.data as WorkflowListItem)}
              >
                <Play className="h-3 w-3 mr-1 fill-current" />
                Activate
              </Button>
            )}
            <Button variant="ghost" size="sm" className="h-7 text-xs" asChild>
              <Link to={`/flow/editor/${row.data.id}`}>Canvas</Link>
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
