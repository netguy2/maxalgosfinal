import { AlertTriangle, CheckCircle2, FlaskConical, History, XCircle } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { apiClient } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { MappingAction } from '@/types/strategy'
import { toneForSignal } from './signal-language'

interface DryRunLeg {
  id: number
  label?: string | null
  reacts_to?: string
  does?: string
  symbol?: string
  exchange?: string
  side?: string
  quantity?: number
  order_type?: string
  product?: string
  basket?: string | null
  error?: string
  notes?: string[]
  risk?: Record<string, { display: string }>
}

interface DryRunReport {
  signal: string
  matched: number
  legs: DryRunLeg[]
  warnings: string[]
}

interface Delivery {
  id: number
  signal?: string | null
  outcome?: string
  reason_detail?: string | null
  received_at?: string | null
  duration_ms?: number | null
}

const SIGNALS: MappingAction[] = ['BUY', 'SELL', 'SHORT', 'EXIT']

const OUTCOME_TONE: Record<string, string> = {
  processed: 'bg-profit/10 text-profit border-profit/30',
  rejected: 'bg-loss/10 text-loss border-loss/30',
  failed: 'bg-loss/10 text-loss border-loss/30',
  duplicate: 'bg-muted text-muted-foreground border-border',
  received: 'bg-brand/10 text-brand border-brand/30',
}

/**
 * "Will this actually work?" — answered before going live.
 *
 * Test resolves the real contract, side, quantity and risk orders for a
 * chosen signal WITHOUT placing anything, using the same helpers the live
 * engine uses. Previously the only way to find out was to arm the strategy
 * during market hours and watch, which is an expensive way to discover a
 * stale expiry.
 *
 * History surfaces the webhook delivery audit that was already being
 * recorded but only visible on a separate page.
 */
export function TestWebhookPanel({ strategyId }: { strategyId: number }) {
  const [signal, setSignal] = useState<MappingAction>('BUY')
  const [report, setReport] = useState<DryRunReport | null>(null)
  const [running, setRunning] = useState(false)
  const [log, setLog] = useState<Delivery[]>([])
  const [logLoading, setLogLoading] = useState(false)

  const runTest = async (sig: MappingAction) => {
    setSignal(sig)
    setRunning(true)
    setReport(null)
    try {
      const res = await apiClient.post<{ status: string; data: DryRunReport; message?: string }>(
        `/strategy/api/strategy/${strategyId}/dry-run`,
        { signal: sig }
      )
      if (res.data.status === 'success') setReport(res.data.data)
    } catch {
      /* surfaced via the empty state below */
    } finally {
      setRunning(false)
    }
  }

  const loadLog = useCallback(async () => {
    setLogLoading(true)
    try {
      const res = await apiClient.get<{ status: string; data: Delivery[] }>(
        `/strategy/api/strategy/${strategyId}/signal-log?limit=15`
      )
      if (res.data.status === 'success') setLog(res.data.data || [])
    } catch {
      /* non-fatal */
    } finally {
      setLogLoading(false)
    }
  }, [strategyId])

  useEffect(() => {
    loadLog()
  }, [loadLog])

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <FlaskConical className="h-4 w-4" />
          Test &amp; History
        </CardTitle>
        <CardDescription>
          Check what a signal would do before it happens for real — nothing is sent to your broker.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="test">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="test">
              <FlaskConical className="mr-2 h-3.5 w-3.5" />
              Test Signal
            </TabsTrigger>
            <TabsTrigger value="history" onClick={loadLog}>
              <History className="mr-2 h-3.5 w-3.5" />
              Recent Signals
            </TabsTrigger>
          </TabsList>

          <TabsContent value="test" className="mt-4 space-y-3">
            <div className="flex flex-wrap gap-2">
              {SIGNALS.map((s) => (
                <Button
                  key={s}
                  type="button"
                  size="sm"
                  variant={signal === s ? 'default' : 'outline'}
                  disabled={running}
                  onClick={() => runTest(s)}
                >
                  Test {s}
                </Button>
              ))}
            </div>

            {running && <p className="text-sm text-muted-foreground">Resolving…</p>}

            {report && !running && (
              <div className="space-y-3">
                <p className="text-sm">
                  <span className="font-semibold">{report.matched}</span> rule
                  {report.matched === 1 ? '' : 's'} would fire on{' '}
                  <Badge variant="outline" className={toneForSignal(report.signal).chip}>
                    {report.signal}
                  </Badge>
                </p>

                {report.warnings.map((w) => (
                  <div
                    key={w}
                    className="flex gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-xs"
                  >
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-500" />
                    <span>{w}</span>
                  </div>
                ))}

                {report.legs.map((leg) => (
                  <div key={leg.id} className="rounded-md border p-2.5 text-xs">
                    {leg.error ? (
                      <div className="flex gap-2">
                        <XCircle className="h-3.5 w-3.5 shrink-0 text-loss" />
                        <div>
                          <p className="font-medium">{leg.label || `Rule ${leg.id}`}</p>
                          <p className="text-muted-foreground">{leg.error}</p>
                        </div>
                      </div>
                    ) : (
                      <div className="flex gap-2">
                        <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-profit" />
                        <div className="min-w-0 space-y-1">
                          <p className="font-semibold">
                            {leg.side} {leg.symbol}{' '}
                            <span className="font-normal text-muted-foreground">
                              × {leg.quantity} · {leg.order_type} · {leg.product} · {leg.exchange}
                            </span>
                          </p>
                          {leg.risk && Object.keys(leg.risk).length > 0 && (
                            <p className="text-muted-foreground">
                              {Object.entries(leg.risk)
                                .map(([k, v]) => `${k.replace('_', ' ')} ${v.display}`)
                                .join(' · ')}
                            </p>
                          )}
                          {leg.basket && (
                            <Badge variant="outline" className="text-[10px]">
                              basket: {leg.basket}
                            </Badge>
                          )}
                          {leg.notes?.map((n) => (
                            <p key={n} className="text-amber-500">
                              {n}
                            </p>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {!report && !running && (
              <p className="text-xs text-muted-foreground">
                Pick a signal above to see the exact orders it would place.
              </p>
            )}
          </TabsContent>

          <TabsContent value="history" className="mt-4">
            {logLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
            {!logLoading && log.length === 0 && (
              <p className="text-xs text-muted-foreground">
                No signals received yet. Once your alert fires, every delivery appears here.
              </p>
            )}
            <div className="space-y-1.5">
              {log.map((d) => (
                <div
                  key={d.id}
                  className="flex flex-wrap items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs"
                >
                  <span className="font-mono text-muted-foreground">
                    {d.received_at ? new Date(d.received_at).toLocaleTimeString() : '—'}
                  </span>
                  <Badge variant="outline" className={toneForSignal(d.signal).chip}>
                    {d.signal || '—'}
                  </Badge>
                  <Badge
                    variant="outline"
                    className={OUTCOME_TONE[d.outcome || ''] ?? OUTCOME_TONE.received}
                  >
                    {d.outcome}
                  </Badge>
                  {d.duration_ms != null && (
                    <span className="text-muted-foreground">{d.duration_ms}ms</span>
                  )}
                  {d.reason_detail && (
                    <span className="min-w-0 flex-1 truncate text-muted-foreground">
                      {d.reason_detail}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}
