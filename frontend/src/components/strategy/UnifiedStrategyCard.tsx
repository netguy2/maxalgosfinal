import {
  BarChart3,
  Code2,
  Layers,
  MoreHorizontal,
  Pencil,
  Settings,
  Webhook,
  Zap,
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
import type { PythonStrategy } from '@/types/python-strategy'
import type { Strategy } from '@/types/strategy'

export type UnifiedRow =
  | { kind: 'automated'; data: Strategy }
  | { kind: 'webhook'; data: Strategy }
  | { kind: 'python'; data: PythonStrategy }
  | { kind: 'flow'; data: WorkflowListItem }

interface Props {
  row: UnifiedRow
  /** Number of active (running/waiting) deployments for this strategy */
  activeDeploymentCount?: number
  onInspect: (row: UnifiedRow) => void
  onCopyWebhook: (webhookId: string) => void
  onConfigureSymbols: (strategyId: number) => void
  onBacktest: (strategy: Strategy) => void
  onDeploy: (strategy: Strategy) => void
}

export function UnifiedStrategyCard({
  row,
  activeDeploymentCount = 0,
  onInspect,
  onCopyWebhook,
  onConfigureSymbols,
  onBacktest,
  onDeploy,
}: Props) {
  // Engine label & icon
  const engineIcon =
    row.kind === 'automated' ? (
      <Zap className="h-3 w-3 text-warning" />
    ) : row.kind === 'webhook' ? (
      <Webhook className="h-3 w-3 text-cat-3" />
    ) : row.kind === 'python' ? (
      <Code2 className="h-3 w-3 text-profit" />
    ) : (
      <Layers className="h-3 w-3 text-cat-2" />
    )

  const engineLabel =
    row.kind === 'automated'
      ? 'Automated'
      : row.kind === 'webhook'
        ? 'Webhook'
        : row.kind === 'python'
          ? 'Python'
          : 'Flow'

  // Last modified
  const lastModified: string | null =
    row.kind === 'automated' || row.kind === 'webhook'
      ? (row.data as Strategy).updated_at ?? null
      : row.kind === 'python'
        ? (row.data as PythonStrategy).updated_at ?? null
        : (row.data as WorkflowListItem).updated_at ?? null

  const relativeTime = (iso: string | null): string => {
    if (!iso) return '—'
    const diff = Date.now() - new Date(iso).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'Just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    return `${Math.floor(hrs / 24)}d ago`
  }

  // Edit / open link
  const editHref =
    row.kind === 'automated'
      ? (row.data as Strategy).template_id
        ? `/strategy/configure?template=${(row.data as Strategy).template_id}`
        : `/strategy/${row.data.id}`
      : row.kind === 'webhook'
        ? `/strategy/${row.data.id}`
        : row.kind === 'python'
          ? `/python/${row.data.id}/edit`
          : `/flow/editor/${row.data.id}`

  const editLabel = row.kind === 'flow' ? 'Open canvas' : 'Edit'

  return (
    // h-full + flex column so every card in a grid row is the same height and
    // the action row pins to the bottom -- names wrap to two lines on some
    // cards and one on others, which otherwise left the buttons at different
    // heights across the row.
    <div
      className="interactive-surface group relative flex h-full cursor-pointer flex-col rounded-xl border border-border bg-card p-4"
      onClick={() => onInspect(row)}
    >
      {/* Top row: name + menu */}
      <div className="mb-4 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground truncate leading-tight">
            {row.data.name}
          </p>
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
              {engineIcon}
              {engineLabel}
            </span>
            <span className="text-muted-foreground/40 text-[11px]">·</span>
            <span className="text-[11px] text-muted-foreground">
              {relativeTime(lastModified)}
            </span>
            {activeDeploymentCount > 0 && (
              <>
                <span className="text-muted-foreground/40 text-[11px]">·</span>
                <span className="flex items-center gap-1 text-[11px] font-semibold text-profit">
                  <span className="w-1.5 h-1.5 rounded-full bg-profit animate-pulse inline-block" />
                  {activeDeploymentCount} active
                </span>
              </>
            )}
          </div>
        </div>

        {/* ··· overflow menu */}
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
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem onClick={() => onInspect(row)} className="text-xs">
                Inspect details
              </DropdownMenuItem>

              {(row.kind === 'automated' || row.kind === 'webhook') && (
                <>
                  <DropdownMenuItem
                    onClick={() => onBacktest(row.data as Strategy)}
                    className="text-xs"
                  >
                    <BarChart3 className="h-3.5 w-3.5 mr-2" />
                    Backtest
                  </DropdownMenuItem>
                  {row.kind === 'webhook' && (
                    <DropdownMenuItem
                      onClick={() => onCopyWebhook((row.data as Strategy).webhook_id)}
                      className="text-xs"
                    >
                      <Webhook className="h-3.5 w-3.5 mr-2" />
                      Copy webhook URL
                    </DropdownMenuItem>
                  )}
                  <DropdownMenuItem
                    onClick={() => onConfigureSymbols((row.data as Strategy).id)}
                    className="text-xs"
                  >
                    <Settings className="h-3.5 w-3.5 mr-2" />
                    Configure symbols
                  </DropdownMenuItem>
                </>
              )}

              <DropdownMenuItem asChild className="text-xs">
                <Link to={editHref} onClick={(e) => e.stopPropagation()}>
                  <Pencil className="h-3.5 w-3.5 mr-2" />
                  {editLabel}
                </Link>
              </DropdownMenuItem>

              {(row.kind === 'automated' || row.kind === 'webhook') && (
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

      {/* Bottom action row */}
      <div
        className="mt-auto flex items-center gap-2 border-t border-border/50 pt-3"
        onClick={(e) => e.stopPropagation()}
      >
        <Button variant="ghost" size="sm" className="h-7 text-xs" asChild>
          <Link to={editHref}>{editLabel}</Link>
        </Button>

        {(row.kind === 'automated' || row.kind === 'webhook') && (
          <Button
            size="sm"
            className="h-7 text-xs font-semibold ml-auto"
            onClick={() => onDeploy(row.data as Strategy)}
          >
            Deploy
          </Button>
        )}

        {row.kind === 'python' && (
          <Button size="sm" variant="outline" className="h-7 text-xs font-semibold ml-auto" asChild>
            <Link to={`/deployments`}>View in Deployments</Link>
          </Button>
        )}

        {row.kind === 'flow' && (
          <Button size="sm" variant="outline" className="h-7 text-xs font-semibold ml-auto" asChild>
            <Link to={`/deployments`}>View in Deployments</Link>
          </Button>
        )}
      </div>
    </div>
  )
}
