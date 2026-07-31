import {
  Check,
  Clock,
  Code2,
  Copy,
  Layers,
  Pencil,
  Play,
  Plug,
  Settings,
  Square,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import type { WorkflowListItem } from '@/api/flow'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { CATALOG } from '@/lib/marketplace-catalog'
import { type PythonStrategy, STATUS_COLORS, STATUS_LABELS } from '@/types/python-strategy'
import { getSignalSourceLabel, type Strategy } from '@/types/strategy'

/**
 * My Strategies shows up to three genuinely different backend models --
 * webhook Strategy rows, Python Strategy Host scripts, and Flow workflows
 * -- with three different real lifecycles (a webhook row has no
 * start/stop process; a Flow workflow has no Backtest concept). One
 * shared card CHROME (status bar, title, badge, action row) with actions
 * branching per `kind` is the honest representation of that, instead of
 * pretending they're one unified model with a lowest-common-denominator
 * action set.
 */
export type UnifiedRow =
  | { kind: 'webhook'; data: Strategy }
  | { kind: 'python'; data: PythonStrategy }
  | { kind: 'flow'; data: WorkflowListItem }

interface Props {
  row: UnifiedRow
  copiedId: string | null
  actionLoading: string | null
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
  onCopyWebhook,
  onConfigureSymbols,
  onBacktest,
  onDeploy,
  onPythonStart,
  onPythonStop,
  onFlowActivate,
  onFlowDeactivate,
}: Props) {
  if (row.kind === 'webhook') {
    const strategy = row.data
    return (
      <Card className="relative overflow-hidden border hover:border-primary/40 transition-colors shadow-sm">
        <div
          className={`absolute top-0 left-0 right-0 h-1 ${
            strategy.is_active ? 'bg-profit' : 'bg-muted-foreground/30'
          }`}
        />
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between">
            <div className="space-y-1">
              <CardTitle className="text-lg">
                <Link
                  to={`/strategy/${strategy.id}`}
                  className="hover:text-primary hover:underline underline-offset-4 transition-colors"
                >
                  {strategy.name}
                </Link>
              </CardTitle>
              <CardDescription className="text-xs font-semibold">
                Webhook &middot; {getSignalSourceLabel(strategy.platform)}
              </CardDescription>
            </div>
            <div className="flex gap-1.5 items-center">
              <Badge variant="outline" className="text-[10px] uppercase font-bold text-primary">
                {strategy.lifecycle_state || 'Draft'}
              </Badge>
              <Badge variant={strategy.is_active ? 'default' : 'secondary'}>
                {strategy.is_active ? 'Active' : 'Inactive'}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-2 text-sm">
            <Badge variant="outline" className="font-normal">
              {strategy.is_intraday ? 'Intraday' : 'Positional'}
            </Badge>
          </div>
          {strategy.is_intraday && strategy.start_time && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              <span>
                {strategy.start_time} - {strategy.end_time}
                {strategy.squareoff_time && ` (SqOff: ${strategy.squareoff_time})`}
              </span>
            </div>
          )}
          <div className="flex items-center gap-1.5 flex-wrap text-xs">
            <Plug className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            {strategy.brokers ? (
              strategy.brokers.split(',').map((broker) => (
                <Badge key={broker} variant="secondary" className="font-normal text-[10px]">
                  {broker.trim()}
                </Badge>
              ))
            ) : (
              <span className="text-muted-foreground">Auto (all connected brokers)</span>
            )}
          </div>
          {strategy.signal_source?.toLowerCase() !== 'marketplace' && (
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className="flex-1 justify-start text-xs font-mono truncate h-8"
                onClick={() => onCopyWebhook(strategy.webhook_id)}
              >
                {copiedId === strategy.webhook_id ? (
                  <Check className="h-3 w-3 mr-2 text-profit" />
                ) : (
                  <Copy className="h-3 w-3 mr-2" />
                )}
                <span className="truncate">Webhook: {strategy.webhook_id.slice(0, 8)}...</span>
              </Button>
            </div>
          )}
          <div className="flex flex-wrap gap-2 pt-2 border-t border-border/40">
            <Button variant="outline" size="sm" className="flex-1 text-xs" asChild>
              <Link
                to={`/strategy/${strategy.id}/configure`}
                onClick={() => onConfigureSymbols(strategy.id)}
              >
                <Settings className="h-3.5 w-3.5 mr-1" />
                Symbols
              </Link>
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="flex-1 text-xs text-info hover:text-info/80"
              onClick={() => onBacktest(strategy)}
            >
              <Play className="h-3.5 w-3.5 mr-1" />
              Backtest
            </Button>
            <Button
              variant="default"
              size="sm"
              className="flex-1 text-xs"
              onClick={() => onDeploy(strategy)}
            >
              <Layers className="h-3.5 w-3.5 mr-1" />
              Deploy
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (row.kind === 'python') {
    const strategy = row.data
    const template = strategy.source_template_id
      ? CATALOG.find((c) => c.id === strategy.source_template_id)
      : undefined
    const isBusy = actionLoading === strategy.id

    return (
      <Card className="relative overflow-hidden border hover:border-primary/40 transition-colors shadow-sm">
        <div
          className={`absolute top-0 left-0 right-0 h-1 ${STATUS_COLORS[strategy.status] || ''}`}
        />
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between">
            <div className="space-y-1">
              <CardTitle className="text-lg">{strategy.name}</CardTitle>
              <CardDescription className="text-xs font-semibold">
                Python &middot; {strategy.file_name}
              </CardDescription>
              {template && (
                <p className="text-[11px] text-muted-foreground">from {template.name} template</p>
              )}
            </div>
            <Badge className={`${STATUS_COLORS[strategy.status] || ''} whitespace-nowrap`}>
              {STATUS_LABELS[strategy.status] || strategy.status}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Clock className="h-3.5 w-3.5" />
            <span>
              {strategy.schedule_start_time} - {strategy.schedule_stop_time} &middot;{' '}
              {strategy.exchange}
            </span>
          </div>
          {strategy.error_message && (
            <p className="text-xs text-loss line-clamp-2">{strategy.error_message}</p>
          )}
          <div className="flex flex-wrap gap-2 pt-2 border-t border-border/40">
            {strategy.status === 'running' || strategy.status === 'scheduled' ? (
              <Button
                variant="outline"
                size="sm"
                className="flex-1 text-xs text-loss hover:text-loss/80"
                disabled={isBusy}
                onClick={() => onPythonStop(strategy)}
              >
                <Square className="h-3.5 w-3.5 mr-1" />
                {strategy.status === 'scheduled' ? 'Cancel' : 'Stop'}
              </Button>
            ) : (
              <Button
                variant="default"
                size="sm"
                className="flex-1 text-xs"
                disabled={isBusy}
                onClick={() => onPythonStart(strategy)}
              >
                <Play className="h-3.5 w-3.5 mr-1" />
                Start
              </Button>
            )}
            <Button variant="outline" size="sm" className="flex-1 text-xs" asChild>
              <Link to={`/python/${strategy.id}/logs`}>Logs</Link>
            </Button>
            <Button variant="outline" size="sm" className="flex-1 text-xs" asChild>
              <Link to={`/python/${strategy.id}/edit`}>
                <Code2 className="h-3.5 w-3.5 mr-1" />
                Edit
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  // kind === 'flow'
  const workflow = row.data
  return (
    <Card className="relative overflow-hidden border hover:border-primary/40 transition-colors shadow-sm">
      <div
        className={`absolute top-0 left-0 right-0 h-1 ${
          workflow.is_active ? 'bg-profit' : 'bg-muted-foreground/30'
        }`}
      />
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <CardTitle className="text-lg">
              <Link
                to={`/flow/editor/${workflow.id}`}
                className="hover:text-primary hover:underline underline-offset-4 transition-colors"
              >
                {workflow.name}
              </Link>
            </CardTitle>
            <CardDescription className="text-xs font-semibold">
              Flow &middot; {workflow.description || 'Visual strategy'}
            </CardDescription>
          </div>
          <Badge variant={workflow.is_active ? 'default' : 'secondary'}>
            {workflow.is_active ? 'Active' : 'Inactive'}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {workflow.last_execution_status && (
          <div className="text-xs text-muted-foreground">
            Last run: {workflow.last_execution_status}
          </div>
        )}
        <div className="flex flex-wrap gap-2 pt-2 border-t border-border/40">
          <Button variant="outline" size="sm" className="flex-1 text-xs" asChild>
            <Link to={`/flow/editor/${workflow.id}`}>
              <Pencil className="h-3.5 w-3.5 mr-1" />
              Open Editor
            </Link>
          </Button>
          {workflow.is_active ? (
            <Button
              variant="outline"
              size="sm"
              className="flex-1 text-xs text-loss hover:text-loss/80"
              onClick={() => onFlowDeactivate(workflow)}
            >
              <Square className="h-3.5 w-3.5 mr-1" />
              Deactivate
            </Button>
          ) : (
            <Button
              variant="default"
              size="sm"
              className="flex-1 text-xs"
              onClick={() => onFlowActivate(workflow)}
            >
              <Play className="h-3.5 w-3.5 mr-1" />
              Activate
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
