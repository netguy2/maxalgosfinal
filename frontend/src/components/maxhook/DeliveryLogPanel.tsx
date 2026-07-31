import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { type WebhookDelivery, webhookDeliveryApi } from '@/api/webhook-deliveries'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { DeliveryTimeline } from './DeliveryTimeline'

/**
 * Recent webhook deliveries for one connection, each expandable into a
 * step-by-step timeline.
 *
 * This is the support surface: when a client says "my alert didn't trade",
 * this page shows whether the signal arrived at all, and if so which stage
 * stopped it.
 */

const OUTCOME_DOT: Record<string, string> = {
  processed: 'bg-profit',
  accepted: 'bg-brand',
  received: 'bg-muted-foreground',
  duplicate: 'bg-amber-500',
  rejected: 'bg-loss',
  failed: 'bg-loss',
}

const FILTERS = [
  { value: '', label: 'All' },
  { value: 'processed', label: 'Processed' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'duplicate', label: 'Duplicates' },
  { value: 'failed', label: 'Failed' },
]

function summarize(d: WebhookDelivery): string {
  if (d.reason_detail) return d.reason_detail
  if (d.order_ids?.length) return `${d.order_ids.length} order(s) placed`
  return d.outcome
}

interface Props {
  strategyId?: number
  webhookId?: string
  className?: string
}

export function DeliveryLogPanel({ strategyId, webhookId, className }: Props) {
  const [outcome, setOutcome] = useState('')
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['webhook-deliveries', strategyId, webhookId, outcome],
    queryFn: () =>
      webhookDeliveryApi.list({
        strategyId,
        webhookId,
        outcome: outcome || undefined,
        limit: 50,
      }),
    // Deliveries arrive from an external system at unpredictable times, and a
    // signal that is still "accepted" flips to processed/failed asynchronously.
    refetchInterval: 15000,
  })

  const deliveries = data ?? []

  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1">
          {FILTERS.map((f) => (
            <Button
              key={f.value}
              size="sm"
              variant={outcome === f.value ? 'secondary' : 'ghost'}
              onClick={() => setOutcome(f.value)}
            >
              {f.label}
            </Button>
          ))}
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          {isFetching ? 'Refreshing…' : 'Refresh'}
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading deliveries…</p>}

      {error && (
        <div className="rounded-md border border-loss/30 bg-loss/10 px-3 py-2">
          <p className="text-sm text-loss">Could not load delivery log.</p>
        </div>
      )}

      {!isLoading && !error && deliveries.length === 0 && (
        <div className="rounded-md border border-dashed px-4 py-8 text-center">
          <p className="text-sm text-muted-foreground">
            {outcome
              ? `No ${outcome} deliveries yet.`
              : 'No signals received yet. Deliveries appear here as soon as your webhook is called.'}
          </p>
        </div>
      )}

      <div className="divide-y rounded-md border">
        {deliveries.map((d) => {
          const isOpen = expandedId === d.id
          return (
            <div key={d.id}>
              <button
                type="button"
                onClick={() => setExpandedId(isOpen ? null : d.id)}
                className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/50"
                aria-expanded={isOpen}
              >
                <span
                  aria-hidden
                  className={cn(
                    'h-2 w-2 shrink-0 rounded-full',
                    OUTCOME_DOT[d.outcome] ?? 'bg-muted-foreground'
                  )}
                />
                <span className="w-20 shrink-0 font-mono text-xs text-muted-foreground">
                  {d.received_at
                    ? new Date(d.received_at).toLocaleTimeString(undefined, {
                        hour12: false,
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })
                    : '—'}
                </span>
                <span className="w-24 shrink-0 truncate font-mono text-xs font-medium">
                  {d.signal ?? '—'}
                </span>
                <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                  {summarize(d)}
                </span>
                {d.duration_ms != null && (
                  <span className="hidden shrink-0 font-mono text-xs text-muted-foreground sm:inline">
                    {d.duration_ms}ms
                  </span>
                )}
                <Badge variant="outline" className="shrink-0 text-xs capitalize">
                  {d.outcome}
                </Badge>
              </button>
              {isOpen && (
                <div className="border-t bg-muted/30 px-4 py-4">
                  <DeliveryTimeline delivery={d} />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
