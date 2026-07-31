import type { WebhookDelivery } from '@/api/webhook-deliveries'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

/**
 * Step-by-step trace of one webhook delivery.
 *
 * Answers "why did this signal (not) trade?" without reading log files. The
 * stage entries come from the backend's `stages` column, which each processing
 * step appends to — so as modules are added the timeline grows automatically
 * with no change here.
 */

const OUTCOME_STYLES: Record<string, { label: string; className: string }> = {
  processed: { label: 'Processed', className: 'bg-profit/15 text-profit border-profit/30' },
  accepted: { label: 'Queued', className: 'bg-brand/15 text-brand border-brand/30' },
  received: { label: 'Received', className: 'bg-muted text-muted-foreground border-border' },
  duplicate: {
    label: 'Duplicate — suppressed',
    className: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30',
  },
  rejected: { label: 'Rejected', className: 'bg-loss/15 text-loss border-loss/30' },
  failed: { label: 'Failed', className: 'bg-loss/15 text-loss border-loss/30' },
}

/** Terminal states where no further stages will arrive. */
const TERMINAL = new Set(['processed', 'rejected', 'failed', 'duplicate'])

function OutcomeBadge({ outcome }: { outcome: string }) {
  const style = OUTCOME_STYLES[outcome] ?? {
    label: outcome,
    className: 'bg-muted text-muted-foreground border-border',
  }
  return (
    <Badge variant="outline" className={cn('font-medium', style.className)}>
      {style.label}
    </Badge>
  )
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString(undefined, {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

interface Props {
  delivery: WebhookDelivery
  className?: string
}

export function DeliveryTimeline({ delivery, className }: Props) {
  const isFailure = delivery.outcome === 'rejected' || delivery.outcome === 'failed'
  const stages = delivery.stages ?? []

  return (
    <div className={cn('space-y-4', className)}>
      {/* Summary */}
      <div className="flex flex-wrap items-center gap-2">
        <OutcomeBadge outcome={delivery.outcome} />
        {delivery.signal && (
          <span className="font-mono text-sm font-medium">{delivery.signal}</span>
        )}
        <span className="text-xs text-muted-foreground">
          {formatTime(delivery.received_at)}
          {delivery.duration_ms != null && ` · ${delivery.duration_ms}ms`}
        </span>
        {delivery.source_type && (
          <Badge variant="outline" className="text-xs">
            {delivery.source_type}
          </Badge>
        )}
      </div>

      {/* Why it stopped. The single most useful line when debugging. */}
      {isFailure && delivery.reason_detail && (
        <div className="rounded-md border border-loss/30 bg-loss/10 px-3 py-2">
          <p className="text-sm text-loss">{delivery.reason_detail}</p>
          {delivery.reason_code && (
            <p className="mt-1 font-mono text-xs text-loss/70">{delivery.reason_code}</p>
          )}
        </div>
      )}

      {delivery.outcome === 'duplicate' && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2">
          <p className="text-sm text-amber-700 dark:text-amber-400">
            {delivery.reason_detail ??
              'Identical signal already received — suppressed to prevent a duplicate order.'}
          </p>
        </div>
      )}

      {/* Stage trace */}
      {stages.length > 0 && (
        <ol className="relative space-y-0">
          {stages.map((stage, i) => (
            <li key={`${stage.stage}-${i}`} className="relative flex gap-3 pb-4 last:pb-0">
              {/* Connector rail */}
              {i < stages.length - 1 && (
                <span aria-hidden className="absolute left-[5px] top-3 h-full w-px bg-border" />
              )}
              <span
                aria-hidden
                className={cn(
                  'relative z-10 mt-1.5 h-[11px] w-[11px] shrink-0 rounded-full border-2 border-background',
                  stage.outcome === 'reject' || stage.outcome === 'fail' ? 'bg-loss' : 'bg-brand'
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-sm font-medium capitalize">{stage.stage}</span>
                  <span className="text-xs text-muted-foreground">{stage.outcome}</span>
                  {stage.ms != null && (
                    <span className="ml-auto font-mono text-xs text-muted-foreground">
                      {stage.ms}ms
                    </span>
                  )}
                </div>
                {stage.detail && (
                  <p className="mt-0.5 break-words text-xs text-muted-foreground">{stage.detail}</p>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}

      {stages.length === 0 && !isFailure && delivery.outcome !== 'duplicate' && (
        <p className="text-xs text-muted-foreground">No stage detail recorded for this delivery.</p>
      )}

      {/* Resulting orders */}
      {delivery.order_ids?.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted-foreground">Orders:</span>
          {delivery.order_ids.map((id) => (
            <Badge key={id} variant="outline" className="font-mono text-xs">
              {id}
            </Badge>
          ))}
        </div>
      )}

      {/* Non-terminal states will still change — say so rather than implying done. */}
      {!TERMINAL.has(delivery.outcome) && (
        <p className="text-xs text-muted-foreground">
          Still processing — this delivery has not reached a final state yet.
        </p>
      )}

      {/* Raw payload, collapsed by default. */}
      {delivery.payload && (
        <details className="group">
          <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
            Raw payload
          </summary>
          <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-muted p-3 font-mono text-xs">
            {delivery.payload}
          </pre>
        </details>
      )}
    </div>
  )
}
