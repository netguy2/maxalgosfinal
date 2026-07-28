// components/charts/QuickOrderTicket.tsx
// Simple buy/sell order ticket for the Charts page — qty, product, price
// type, broker chip-selector, buy/sell buttons.
//
// Broker selection follows the exact pattern from
// components/trading/ExecuteBasketDialog.tsx: fetch /api/broker/connections
// on mount, default to the connected data broker, chip-toggle for multi-
// select. One broker selected -> tradingApi.placeOrder (single-broker
// /placeorder). More than one -> tradingApi.placeOrderMulti (/placeordermulti,
// sequential fan-out — see services/multi_broker_order_service.py), which
// returns the same per-broker {broker, status, orderid?, message?}[] shape
// ExecuteBasketDialog.tsx already knows how to aggregate.
//
// Fill confirmation: after each broker's entry is accepted, polls
// tradingApi.getOrderStatus until a terminal state, the same
// poll-until-terminal-state approach already proven in
// ExecuteBasketDialog.tsx (pollOrderFillStatus) — placement acceptance
// (a returned order_id) is not fill confirmation, so this never reports
// "success" the instant an order is merely accepted for routing.

import { CheckCircle2, Clock, Loader2, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { tradingApi } from '@/api/trading'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

type ProductType = 'MIS' | 'NRML' | 'CNC'
type PriceType = 'MARKET' | 'LIMIT'
type FillStatus = 'pending' | 'complete' | 'rejected' | 'unknown'

const PRODUCT_TYPES: ProductType[] = ['MIS', 'NRML', 'CNC']
const POLL_INTERVAL_MS = 1500
const POLL_TIMEOUT_MS = 15000

interface BrokerConnection {
  broker: string
  connected: boolean
  is_data_broker: boolean
}

interface BrokerFillOutcome {
  broker: string
  orderid?: string
  fillStatus: FillStatus
  message?: string
}

async function pollOrderFillStatus(
  apiKey: string,
  strategy: string,
  orderid: string
): Promise<{ fillStatus: FillStatus; message?: string }> {
  const deadline = Date.now() + POLL_TIMEOUT_MS
  for (;;) {
    try {
      const resp = await tradingApi.getOrderStatus(apiKey, strategy, orderid)
      const status = resp.data?.order_status?.toLowerCase()
      if (status === 'complete') return { fillStatus: 'complete' }
      if (status === 'rejected') return { fillStatus: 'rejected', message: resp.message }
    } catch {
      // Transient network error — keep polling until timeout rather than
      // reporting a false rejection.
    }
    if (Date.now() >= deadline) return { fillStatus: 'unknown' }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
  }
}

interface QuickOrderTicketProps {
  symbol: string
  exchange: string
  ltp?: number
  apiKey: string
  /** Read-only strategy tag stamped on the order, same convention as ExecuteBasketDialog. */
  strategyName: string
}

export function QuickOrderTicket({
  symbol,
  exchange,
  ltp,
  apiKey,
  strategyName,
}: QuickOrderTicketProps) {
  const [quantity, setQuantity] = useState(1)
  const [product, setProduct] = useState<ProductType>('MIS')
  const [pricetype, setPricetype] = useState<PriceType>('MARKET')
  const [price, setPrice] = useState(ltp ?? 0)
  const [submitting, setSubmitting] = useState<'BUY' | 'SELL' | null>(null)
  const [lastResults, setLastResults] = useState<BrokerFillOutcome[] | null>(null)

  const [connections, setConnections] = useState<BrokerConnection[]>([])
  const [selectedBrokers, setSelectedBrokers] = useState<string[]>([])

  // Fetch connected brokers on mount, default to the current data broker —
  // same pattern as ExecuteBasketDialog.tsx.
  useEffect(() => {
    const loadConnections = async () => {
      try {
        const response = await fetch('/api/broker/connections', { credentials: 'include' })
        const data = await response.json()
        if (data.status === 'success') {
          const conns: BrokerConnection[] = data.connections || []
          setConnections(conns)
          const dataBroker = conns.find((c) => c.is_data_broker && c.connected)
          setSelectedBrokers(dataBroker ? [dataBroker.broker] : [])
        }
      } catch {
        // Non-fatal — falls back to no brokers selected, which disables Buy/Sell.
      }
    }
    loadConnections()
  }, [])

  const toggleBroker = (broker: string) =>
    setSelectedBrokers((prev) =>
      prev.includes(broker) ? prev.filter((b) => b !== broker) : [...prev, broker]
    )

  const canSubmit =
    !submitting && quantity > 0 && !!apiKey && !!symbol && !!exchange && selectedBrokers.length > 0

  const handleOrder = async (action: 'BUY' | 'SELL') => {
    if (!canSubmit) return
    if (pricetype === 'LIMIT' && (!price || price <= 0)) {
      showToast.error('Enter a valid LIMIT price')
      return
    }

    setSubmitting(action)
    setLastResults(null)
    try {
      const orderPayload = {
        exchange,
        symbol,
        action,
        quantity,
        pricetype,
        product,
        price: pricetype === 'LIMIT' ? price : 0,
        trigger_price: 0,
      }

      let acceptedByBroker: { broker: string; orderid: string }[] = []
      let rejectedAtPlacement: { broker: string; message?: string }[] = []

      if (selectedBrokers.length > 0) {
        const resp = await tradingApi.placeOrderMulti(
          { apikey: apiKey, strategy: strategyName, ...orderPayload },
          selectedBrokers
        )
        const results = resp.results ?? []
        acceptedByBroker = results
          .filter((r) => r.status === 'success' && !!r.orderid)
          .map((r) => ({ broker: r.broker, orderid: r.orderid as string }))
        rejectedAtPlacement = results
          .filter((r) => r.status !== 'success')
          .map((r) => ({ broker: r.broker, message: r.message }))
      } else {
        const resp = await tradingApi.placeOrder({
          apikey: apiKey,
          strategy: strategyName,
          ...orderPayload,
        })
        const broker = selectedBrokers[0]
        if (resp.status === 'success' && resp.data?.orderid) {
          acceptedByBroker = [{ broker, orderid: resp.data.orderid }]
        } else {
          rejectedAtPlacement = [{ broker, message: resp.message }]
        }
      }

      if (rejectedAtPlacement.length > 0) {
        showToast.error(
          `${action} rejected at placement on: ${rejectedAtPlacement.map((r) => `${r.broker}${r.message ? ` (${r.message})` : ''}`).join(', ')}`
        )
      }
      if (acceptedByBroker.length === 0) {
        setLastResults(
          rejectedAtPlacement.map((r) => ({
            broker: r.broker,
            fillStatus: 'rejected' as const,
            message: r.message,
          }))
        )
        return
      }

      showToast.info(
        `${action} order sent to ${acceptedByBroker.map((a) => a.broker).join(', ')} — confirming fill…`
      )
      const fillOutcomes = await Promise.all(
        acceptedByBroker.map(async ({ broker, orderid }) => {
          const { fillStatus, message } = await pollOrderFillStatus(apiKey, strategyName, orderid)
          return { broker, orderid, fillStatus, message }
        })
      )
      const allResults: BrokerFillOutcome[] = [
        ...fillOutcomes,
        ...rejectedAtPlacement.map((r) => ({
          broker: r.broker,
          fillStatus: 'rejected' as const,
          message: r.message,
        })),
      ]
      setLastResults(allResults)

      // Fill/rejection/pending toasts are intentionally NOT shown here --
      // the backend's async_verify_order_fill (services/order_verification_helper.py)
      // independently polls the same order and pushes order_event/
      // order_notification over SocketIO for every order regardless of how
      // it was placed, which useSocket.ts already turns into toasts. Showing
      // them here too produced duplicate toasts for the same outcome. The
      // fillOutcomes above still drive the inline per-broker status display
      // (setLastResults) in this component's own UI, which the SocketIO
      // push does not.
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Network error'
      showToast.error(`${action} order error: ${msg}`)
      setLastResults(
        selectedBrokers.map((broker) => ({ broker, fillStatus: 'rejected' as const, message: msg }))
      )
    } finally {
      setSubmitting(null)
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border bg-card p-3">
      <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Quick Order
      </div>

      <div className="space-y-1">
        <Label className="text-[11px] text-muted-foreground">Broker</Label>
        {connections.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">
            No connected brokers found. Connect one from Broker Management.
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {connections
              .filter((c) => c.connected)
              .map((c) => (
                <button
                  key={c.broker}
                  type="button"
                  onClick={() => toggleBroker(c.broker)}
                  disabled={!!submitting}
                  className={cn(
                    'rounded-full border px-2 py-0.5 text-[11px] font-semibold transition-colors',
                    selectedBrokers.includes(c.broker)
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-border bg-background text-muted-foreground hover:bg-muted'
                  )}
                >
                  {c.broker}
                  {c.is_data_broker && <span className="ml-1 opacity-70">(data)</span>}
                </button>
              ))}
          </div>
        )}
      </div>

      <div className="space-y-1">
        <Label className="text-[11px] text-muted-foreground">Quantity</Label>
        <Input
          type="number"
          min={1}
          step={1}
          value={quantity}
          onChange={(e) => setQuantity(Math.max(1, Math.floor(Number(e.target.value) || 1)))}
          disabled={!!submitting}
          className="h-8 font-mono text-xs"
        />
      </div>

      <div className="space-y-1">
        <Label className="text-[11px] text-muted-foreground">Product</Label>
        <div className="inline-flex h-8 w-full overflow-hidden rounded-md border bg-background">
          {PRODUCT_TYPES.map((p, idx) => (
            <button
              key={p}
              type="button"
              onClick={() => setProduct(p)}
              disabled={!!submitting}
              className={cn(
                'flex-1 text-xs font-semibold transition-colors',
                idx > 0 && 'border-l',
                product === p
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted'
              )}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-1">
        <Label className="text-[11px] text-muted-foreground">Price Type</Label>
        <div className="inline-flex h-8 w-full overflow-hidden rounded-md border bg-background">
          <button
            type="button"
            onClick={() => setPricetype('MARKET')}
            disabled={!!submitting}
            className={cn(
              'flex-1 text-xs font-semibold transition-colors',
              pricetype === 'MARKET'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-muted'
            )}
          >
            MKT
          </button>
          <button
            type="button"
            onClick={() => setPricetype('LIMIT')}
            disabled={!!submitting}
            className={cn(
              'flex-1 border-l text-xs font-semibold transition-colors',
              pricetype === 'LIMIT'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-muted'
            )}
          >
            LIMIT
          </button>
        </div>
      </div>

      {pricetype === 'LIMIT' && (
        <div className="space-y-1">
          <Label className="text-[11px] text-muted-foreground">Price</Label>
          <Input
            type="number"
            min={0}
            step={0.05}
            value={price}
            onChange={(e) => setPrice(Number(e.target.value) || 0)}
            disabled={!!submitting}
            className="h-8 font-mono text-xs"
          />
        </div>
      )}

      <div className="grid grid-cols-2 gap-2">
        <Button
          onClick={() => handleOrder('BUY')}
          disabled={!canSubmit}
          className="bg-profit text-white hover:bg-profit/90"
        >
          {submitting === 'BUY' ? <Loader2 className="h-4 w-4 animate-spin" /> : 'BUY'}
        </Button>
        <Button
          onClick={() => handleOrder('SELL')}
          disabled={!canSubmit}
          className="bg-loss text-white hover:bg-loss/90"
        >
          {submitting === 'SELL' ? <Loader2 className="h-4 w-4 animate-spin" /> : 'SELL'}
        </Button>
      </div>

      {lastResults && lastResults.length > 0 && (
        <div className="flex flex-col gap-1">
          {lastResults.map((r) => (
            <div
              key={r.broker}
              className="flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-[11px]"
            >
              {r.fillStatus === 'complete' ? (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-profit" />
                  <span className="text-profit">
                    {r.broker}: filled{r.orderid ? ` · #${r.orderid}` : ''}
                  </span>
                </>
              ) : r.fillStatus === 'rejected' ? (
                <>
                  <XCircle className="h-3.5 w-3.5 shrink-0 text-loss" />
                  <span className="truncate text-loss" title={r.message}>
                    {r.broker}: rejected{r.message ? ` — ${r.message}` : ''}
                  </span>
                </>
              ) : (
                <>
                  <Clock className="h-3.5 w-3.5 shrink-0 text-warning" />
                  <span className="text-warning">{r.broker}: still pending</span>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
