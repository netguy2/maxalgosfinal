import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Loader2,
  Send,
  ShieldCheck,
  XCircle,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import {
  type BasketOrderItem,
  type BasketOrderResult,
  type PlaceGttOrderPayload,
  tradingApi,
} from '@/api/trading'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { StrategyLeg } from '@/lib/strategyMath'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

/**
 * Basket execution dialog for the Strategy Builder.
 *
 * Minimal controls by design — per-leg rows show only Include / side /
 * symbol / qty / price. Product (NRML|MIS|CNC) and Pricetype (LIMIT|MKT) are
 * single global controls that stamp every leg. Strategy name is
 * read-only and framed by the parent. Exchange is whatever the parent
 * resolves — NFO, BFO, or any crypto code pass through unchanged.
 *
 * Symbol format and order constants follow docs/prompt/symbols.md and
 * docs/prompt/order-constants.md.
 *
 * Phase 2 — GTT bracket attach (equity only): after a single-broker entry
 * order is CONFIRMED FILLED (order_status === "complete" via /orderstatus
 * polling below — not merely accepted for routing), any included EQUITY
 * row whose source leg has equityTargetPrice/equitySlPrice set gets a
 * follow-up POST /placegttorder (OCO if both set, SINGLE if only one),
 * using the same quantity/broker that just filled. This never runs for
 * the multi-broker fan-out path (/basketordermulti) — GTT support is
 * Zerodha/Dhan-only and multi-broker bracket attach would be substantial
 * extra complexity for a capability that barely exists broker-wide, so
 * it's explicitly out of scope; the UI shows an inline notice instead.
 * Trailing SL is never sent here — no backend anywhere in this platform
 * implements it (see ManualLegBuilder.tsx's Trailing SL field, which is
 * disabled/"Soon").
 *
 * Phase 3 — fill confirmation (order-status polling): a `status: "success"`
 * from /basketorder or /basketordermulti only means the broker ACCEPTED the
 * order for routing to the exchange (a non-null order_id came back) — it
 * does NOT mean the exchange filled it. An order can still be REJECTED
 * (margin shortfall, market closed, etc.) after acceptance. After entry
 * placement, every row with a returned orderid is polled against
 * POST /orderstatus until it reaches a terminal state (order_status
 * "complete" or "rejected") or a timeout elapses. Only "complete" rows are
 * treated as a live position: only they get "filled" messaging, only they
 * feed bracket attach. "rejected" rows are reported with the broker's own
 * rejection reason and their draft leg is removed via onLegNotFilled so
 * the Positions panel never shows a phantom position for an order the
 * exchange rejected. Rows still "open" when the poll times out are reported
 * honestly as still-pending — never claimed as filled or failed.
 */

type PriceType = 'LIMIT' | 'MARKET'
// CNC is equity-only (delivery); NRML/MIS also apply to F&O legs. All three
// are offered here since a basket can include equity legs (see EQUITY in
// RowState.segment below) alongside option/future legs.
type ProductType = 'NRML' | 'MIS' | 'CNC'

const PRODUCT_TYPES: ProductType[] = ['NRML', 'MIS', 'CNC']

interface RowState {
  legId: string
  include: boolean
  symbol: string
  action: 'BUY' | 'SELL'
  segment: 'OPTION' | 'FUTURE' | 'EQUITY'
  optionType?: 'CE' | 'PE'
  /** Lots the user buys/sells. Contract quantity = lots × lotSize. */
  lots: number
  /** Broker lot size (from the symbol / option-chain service). */
  lotSize: number
  price: number
  tickSize: number
  /**
   * Exchange for THIS row specifically. Option/future legs use the shared
   * `exchange` prop (NFO/BFO/crypto); EQUITY legs carry their own cash
   * exchange (NSE/BSE) from the leg itself, since a basket can mix an
   * equity leg with option/future legs on a different exchange entirely.
   */
  exchange: string
}

export interface ExecuteBasketDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  legs: StrategyLeg[]
  /** Exchange attached to every leg (NFO / BFO / crypto code). */
  exchange: string
  /** Read-only strategy name — auto-framed by the parent. */
  strategyName: string
  /**
   * Per-leg tick size, keyed by the leg's Max Algos symbol. Sourced from
   * the option-chain response (SymToken.tick_size in the DB). Missing
   * symbols fall back to 0.05, which is the NSE F&O default.
   */
  tickSizeBySymbol?: Record<string, number>
  apiKey: string
  /**
   * Called for each leg whose entry order was confirmed NOT filled
   * (broker-rejected, or still pending when the status poll times out) so
   * the parent can drop the stale local draft leg — otherwise the
   * Positions panel keeps showing a leg that was never actually filled.
   */
  onLegNotFilled?: (legId: string) => void
}

/** Broker order_status values this dialog treats as terminal-filled / terminal-not-filled. */
type FillStatus = 'pending' | 'complete' | 'rejected' | 'unknown'

interface FillOutcome {
  legId: string
  symbol: string
  orderid: string
  fillStatus: FillStatus
  message?: string
}

const ORDER_STATUS_POLL_INTERVAL_MS = 1500
const ORDER_STATUS_POLL_TIMEOUT_MS = 15000

/**
 * Poll /orderstatus for one order until it reaches a terminal broker state
 * ("complete" or "rejected") or the timeout elapses. Placement acceptance
 * (a returned order_id) is not fill confirmation — only this poll's result
 * is trusted as the real outcome.
 */
async function pollOrderFillStatus(
  apiKey: string,
  strategy: string,
  orderid: string
): Promise<{ fillStatus: FillStatus; message?: string }> {
  const deadline = Date.now() + ORDER_STATUS_POLL_TIMEOUT_MS
  for (;;) {
    try {
      const resp = await tradingApi.getOrderStatus(apiKey, strategy, orderid)
      const status = resp.data?.order_status?.toLowerCase()
      if (status === 'complete') return { fillStatus: 'complete' }
      if (status === 'rejected') return { fillStatus: 'rejected', message: resp.message }
      // "open" or any other non-terminal value — keep polling until timeout.
    } catch {
      // Transient network error while polling — keep trying until timeout
      // rather than reporting a false rejection.
    }
    if (Date.now() >= deadline) return { fillStatus: 'unknown' }
    await new Promise((r) => setTimeout(r, ORDER_STATUS_POLL_INTERVAL_MS))
  }
}

/** Decimal places implied by a tick (0.05 → 2, 0.0001 → 4, 0.5 → 1, 1 → 0). */
function tickDecimals(tick: number): number {
  if (!Number.isFinite(tick) || tick <= 0) return 2
  if (tick >= 1) return 0
  const s = tick.toString()
  const dot = s.indexOf('.')
  return dot === -1 ? 0 : s.length - dot - 1
}

/** Snap `value` to the nearest multiple of `tick` and strip binary drift. */
function roundToTick(value: number, tick = 0.05): number {
  if (!Number.isFinite(value) || value <= 0) return 0
  if (!Number.isFinite(tick) || tick <= 0) return value
  const decimals = tickDecimals(tick)
  return Number((Math.round(value / tick) * tick).toFixed(decimals))
}

interface BrokerConnection {
  broker: string
  connected: boolean
  is_data_broker: boolean
}

interface GttResult {
  symbol: string
  status: 'success' | 'error' | 'skipped'
  message?: string
  trigger_id?: string
}

export function ExecuteBasketDialog({
  open,
  onOpenChange,
  legs,
  exchange,
  strategyName,
  tickSizeBySymbol,
  apiKey,
  onLegNotFilled,
}: ExecuteBasketDialogProps) {
  const activeLegs = useMemo(() => legs.filter((l) => l.active), [legs])
  const [rows, setRows] = useState<RowState[]>([])
  const [product, setProduct] = useState<ProductType>('NRML')
  const [pricetype, setPricetype] = useState<PriceType>('LIMIT')
  const [submitting, setSubmitting] = useState(false)
  const [results, setResults] = useState<BasketOrderResult[] | null>(null)
  const [connections, setConnections] = useState<BrokerConnection[]>([])
  const [selectedBrokers, setSelectedBrokers] = useState<string[]>([])
  const [gttSubmitting, setGttSubmitting] = useState(false)
  const [gttResults, setGttResults] = useState<GttResult[] | null>(null)
  const [confirmingFills, setConfirmingFills] = useState(false)
  const [fillOutcomes, setFillOutcomes] = useState<FillOutcome[] | null>(null)

  // Fetch connected brokers whenever the dialog opens, and default the
  // selection to whichever one is currently the data broker (matches
  // today's single-broker behavior when the user has only one connected).
  useEffect(() => {
    if (!open) return
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
        // Non-fatal — falls back to the single-broker /basketorder path
        // (no brokers selected disables Execute if connections is empty).
      }
    }
    loadConnections()
  }, [open])

  const toggleBroker = (broker: string) =>
    setSelectedBrokers((prev) =>
      prev.includes(broker) ? prev.filter((b) => b !== broker) : [...prev, broker]
    )

  // Seed rows whenever dialog opens or legs change.
  useEffect(() => {
    if (!open) return
    setResults(null)
    setGttResults(null)
    setGttSubmitting(false)
    setFillOutcomes(null)
    setConfirmingFills(false)
    setProduct('NRML')
    setPricetype('LIMIT')
    setRows(
      activeLegs.map((leg) => {
        const tick = tickSizeBySymbol?.[leg.symbol] ?? 0.05
        return {
          legId: leg.id,
          include: true,
          symbol: leg.symbol,
          action: leg.side,
          segment: leg.segment,
          optionType: leg.optionType,
          lots: Math.max(1, Math.floor(leg.lots || 1)),
          lotSize: Math.max(1, Math.floor(leg.lotSize || 1)),
          price: roundToTick(leg.price || 0, tick),
          tickSize: tick,
          exchange: leg.segment === 'EQUITY' ? (leg.equityExchange ?? 'NSE') : exchange,
        }
      })
    )
  }, [open, activeLegs, tickSizeBySymbol, exchange])

  const updateRow = (legId: string, patch: Partial<RowState>) =>
    setRows((prev) => prev.map((r) => (r.legId === legId ? { ...r, ...patch } : r)))

  const includedRows = rows.filter((r) => r.include)
  // Mirrors the LIMIT-needs-a-valid-price check in handleExecute below --
  // duplicated here (rather than only checked at submit time) so the
  // Execute button is actually disabled instead of being clickable and
  // silently no-op'ing with a toast when a row's price is 0 (e.g. right
  // after the option chain hadn't finished loading a real LTP for a leg).
  const hasInvalidLimitPrice =
    pricetype === 'LIMIT' && includedRows.some((r) => !r.price || r.price <= 0)
  const canSubmit =
    !submitting &&
    includedRows.length > 0 &&
    strategyName.trim().length > 0 &&
    !!apiKey &&
    selectedBrokers.length > 0 &&
    !hasInvalidLimitPrice

  // Rows that would get a GTT bracket attach after a successful single-
  // broker entry — an EQUITY row whose source leg carries Target and/or
  // SL. Used both to size the "N leg(s)" messaging up front and to gate
  // which rows the phase-2 logic actually attempts after execute.
  const bracketEligibleRows = useMemo(
    () =>
      includedRows.filter((r) => {
        if (r.segment !== 'EQUITY') return false
        const leg = legs.find((l) => l.id === r.legId)
        return !!leg && (leg.equityTargetPrice !== undefined || leg.equitySlPrice !== undefined)
      }),
    [includedRows, legs]
  )
  const showMultiBrokerGttNotice = selectedBrokers.length > 1 && bracketEligibleRows.length > 0

  /** Builds the OCO/SINGLE GTT payload for one filled equity leg's exit bracket. */
  const buildGttPayload = (
    row: RowState,
    leg: StrategyLeg,
    gttProduct: 'CNC' | 'NRML'
  ): PlaceGttOrderPayload => {
    const hasTarget = leg.equityTargetPrice !== undefined
    const hasSl = leg.equitySlPrice !== undefined
    const triggerType: 'OCO' | 'SINGLE' = hasTarget && hasSl ? 'OCO' : 'SINGLE'
    const slPrice = hasSl ? roundToTick(leg.equitySlPrice as number, row.tickSize) : undefined
    const targetPrice = hasTarget
      ? roundToTick(leg.equityTargetPrice as number, row.tickSize)
      : undefined
    // The bracket closes the position, so it trades the opposite side of entry.
    const exitAction: 'BUY' | 'SELL' = row.action === 'BUY' ? 'SELL' : 'BUY'
    // For SINGLE, `price` is the exit leg's own limit price (confirmed against
    // both broker/zerodha/api/gtt_api.py and broker/dhan/api/gtt_api.py — the
    // only two brokers that implement GTT). For OCO both mappers read
    // stoploss/target instead and ignore `price`, so any non-zero value is
    // fine — the schema just requires the field to be present.
    const price =
      triggerType === 'SINGLE'
        ? ((slPrice ?? targetPrice) as number)
        : (targetPrice ?? slPrice ?? row.price)

    return {
      apikey: apiKey,
      strategy: strategyName.trim(),
      trigger_type: triggerType,
      exchange: row.exchange,
      symbol: row.symbol,
      action: exitAction,
      product: gttProduct,
      quantity: row.lots * row.lotSize,
      pricetype: 'LIMIT',
      price,
      triggerprice_sl: slPrice,
      triggerprice_tg: targetPrice,
      stoploss: triggerType === 'OCO' ? slPrice : undefined,
      target: triggerType === 'OCO' ? targetPrice : undefined,
    }
  }

  const handleExecute = async () => {
    if (!canSubmit) return

    // Build payload per docs/prompt/services_documentation.md (BasketOrder).
    // Contract quantity = lots × lotSize — the broker API expects contracts.
    // Final tick-snap here in case the user hit Execute before blurring
    // a manually-edited price input.
    const orders: BasketOrderItem[] = includedRows.map((r) => ({
      symbol: r.symbol,
      exchange: r.exchange,
      action: r.action,
      quantity: Math.max(1, Math.floor(r.lots) * Math.max(1, r.lotSize)),
      pricetype,
      product,
      price: pricetype === 'LIMIT' ? roundToTick(r.price, r.tickSize) : 0,
      trigger_price: 0,
    }))

    if (pricetype === 'LIMIT') {
      const bad = orders.find((o) => !o.price || (o.price ?? 0) <= 0)
      if (bad) {
        showToast.error(`${bad.symbol}: LIMIT needs a valid price`)
        return
      }
    }

    setSubmitting(true)
    try {
      // If broker selection is specified (1 or more brokers), route through
      // placeBasketOrderMulti to ensure exact broker targeting for every selected broker.
      if (selectedBrokers.length > 0) {
        const resp = await tradingApi.placeBasketOrderMulti(
          apiKey,
          strategyName.trim(),
          orders,
          selectedBrokers
        )
        const resultList = resp.results ?? []
        // Collapse per-broker results down to the per-symbol shape the
        // row list already knows how to render (first result per symbol).
        setResults(resultList)
        const successCount = resultList.filter(
          (r) => r.status === 'success' && !r.rejection_reason
        ).length
        const failCount = resultList.length - successCount
        const brokerNames = selectedBrokers.join(', ')

        const rejectedLegs = resultList.filter(
          (r) => r.status === 'error' || r.status === 'rejected' || Boolean(r.rejection_reason)
        )

        if (failCount === 0 && rejectedLegs.length === 0) {
          showToast.success(
            `Basket sent to ${brokerNames}: ${successCount}/${resultList.length} orders placed — check Order Book for fill confirmation`
          )
          if (bracketEligibleRows.length > 0) {
            showToast.warning(
              `Target/SL not attached — GTT brackets only support a single broker. ${bracketEligibleRows.length} leg(s) have no protection: ${bracketEligibleRows.map((r) => r.symbol).join(', ')}`,
              undefined,
              { duration: 10000 }
            )
          }
          setTimeout(() => onOpenChange(false), 800)
        } else {
          const failedDetails = rejectedLegs
            .map(
              (r) =>
                `${r.symbol}${r.broker ? ` (${r.broker})` : ''}: ${
                  r.rejection_reason || r.message || 'Broker Rejected Order'
                }`
            )
            .join('; ')
          showToast.error(
            `Basket Order Errors (${brokerNames}): ${failedDetails || `${failCount} order(s) failed`}`,
            undefined,
            { duration: 10000 }
          )
        }
        return
      }

      const resp = await tradingApi.placeBasketOrder(apiKey, strategyName.trim(), orders)
      if (resp.status !== 'success') {
        showToast.error(resp.message || 'Basket order failed')
        setSubmitting(false)
        return
      }
      const resultList = resp.results ?? []
      setResults(resultList)
      const acceptedCount = resultList.filter((r) => r.status === 'success').length
      const notAcceptedCount = resultList.length - acceptedCount
      const brokerName = selectedBrokers[0] ?? ''

      // Placement acceptance (order_id returned) is NOT fill confirmation —
      // the exchange can still reject an accepted order (margin, market
      // closed, etc.). Sandbox orders fill synchronously and never need
      // this poll; the same is true for any row the broker already
      // rejected outright at placement (no orderid to poll).
      const acceptedRows = resultList.filter(
        (r): r is BasketOrderResult & { orderid: string } => r.status === 'success' && !!r.orderid
      )
      let outcomes: FillOutcome[] = []
      if (resp.mode !== 'analyze' && acceptedRows.length > 0) {
        setConfirmingFills(true)
        outcomes = await Promise.all(
          acceptedRows.map(async (r) => {
            const row = includedRows.find((ir) => ir.symbol === r.symbol)
            const { fillStatus, message } = await pollOrderFillStatus(
              apiKey,
              strategyName.trim(),
              r.orderid
            )
            return {
              legId: row?.legId ?? r.symbol,
              symbol: r.symbol,
              orderid: r.orderid,
              fillStatus,
              message,
            }
          })
        )
        setConfirmingFills(false)
        setFillOutcomes(outcomes)
      } else if (resp.mode === 'analyze') {
        // Sandbox fills are synchronous and authoritative as soon as
        // /basketorder returns — no exchange round-trip to wait for.
        outcomes = acceptedRows.map((r) => {
          const row = includedRows.find((ir) => ir.symbol === r.symbol)
          return {
            legId: row?.legId ?? r.symbol,
            symbol: r.symbol,
            orderid: r.orderid,
            fillStatus: 'complete' as const,
          }
        })
        setFillOutcomes(outcomes)
      }

      const rejectedOutcomes = outcomes.filter((o) => o.fillStatus === 'rejected')
      const pendingOutcomes = outcomes.filter((o) => o.fillStatus === 'unknown')

      // Drop the local draft leg for anything confirmed NOT filled — a
      // rejected or still-pending-after-timeout order must never keep
      // showing as a live position in the Positions panel.
      for (const o of [...rejectedOutcomes, ...pendingOutcomes]) {
        onLegNotFilled?.(o.legId)
      }

      if (notAcceptedCount > 0) {
        showToast.error(
          `Basket partial on ${brokerName}: ${acceptedCount} accepted, ${notAcceptedCount} rejected at placement`
        )
      }
      // Per-leg exchange-rejection and fill-confirmation toasts are
      // intentionally NOT shown here -- the backend's async_verify_order_fill
      // (services/order_verification_helper.py) independently polls each
      // order and pushes order_event/order_notification over SocketIO
      // regardless of how it was placed, which useSocket.ts already turns
      // into toasts. Showing them here too produced duplicate toasts for the
      // same outcome. rejectedOutcomes/pendingOutcomes/filledCount above
      // still drive real downstream logic (onLegNotFilled, GTT bracket
      // eligibility below) which the SocketIO push does not replace.
      if (pendingOutcomes.length > 0) {
        showToast.warning(
          `Still pending with the exchange: ${pendingOutcomes.map((o) => o.symbol).join(', ')}. Check the Order Book — not yet confirmed filled or rejected.`,
          undefined,
          { duration: 10000 }
        )
      }

      // Phase 2 — GTT bracket attach for equity legs with Target/SL, only
      // for rows CONFIRMED FILLED (order_status "complete") — placement
      // acceptance alone is not enough to attach a bracket to a position
      // that may not exist.
      const gttCandidates = bracketEligibleRows.filter((r) =>
        outcomes.some((o) => o.symbol === r.symbol && o.fillStatus === 'complete')
      )
      if (gttCandidates.length === 0) {
        if (
          notAcceptedCount === 0 &&
          rejectedOutcomes.length === 0 &&
          pendingOutcomes.length === 0
        ) {
          setTimeout(() => onOpenChange(false), 800)
        }
        return
      }

      if (resp.mode === 'analyze') {
        showToast.warning(
          `Entry placed in Sandbox — GTT bracket not available in Sandbox mode. ${gttCandidates.length} leg(s) have no Target/SL protection: ${gttCandidates.map((r) => r.symbol).join(', ')}`,
          undefined,
          { duration: 10000 }
        )
        setGttResults(
          gttCandidates.map((r) => ({
            symbol: r.symbol,
            status: 'skipped',
            message: 'Sandbox mode',
          }))
        )
        return
      }

      if (product === 'MIS') {
        // Should already be blocked at leg-add time (ManualLegBuilder), but
        // the dialog's global Product control can still be switched to MIS
        // after legs were added with Target/SL — cover that path too.
        showToast.warning(
          `Entry placed with MIS — GTT requires CNC/NRML. ${gttCandidates.length} leg(s) have no Target/SL protection: ${gttCandidates.map((r) => r.symbol).join(', ')}`,
          undefined,
          { duration: 10000 }
        )
        setGttResults(
          gttCandidates.map((r) => ({
            symbol: r.symbol,
            status: 'skipped',
            message: 'Product is MIS',
          }))
        )
        return
      }

      // product !== 'MIS' guaranteed by the early return above — GTT only
      // ever runs with CNC or NRML.
      const gttProduct = product as 'CNC' | 'NRML'
      setGttSubmitting(true)
      const gttOutcomes: GttResult[] = []
      for (const row of gttCandidates) {
        const leg = legs.find((l) => l.id === row.legId)
        if (!leg) continue
        try {
          const payload = buildGttPayload(row, leg, gttProduct)
          const gttResp = await tradingApi.placeGttOrder(payload)
          gttOutcomes.push(
            gttResp.status === 'success'
              ? { symbol: row.symbol, status: 'success', trigger_id: gttResp.trigger_id }
              : { symbol: row.symbol, status: 'error', message: gttResp.message || 'GTT failed' }
          )
        } catch (err) {
          const msg = err instanceof Error ? err.message : 'Network error'
          gttOutcomes.push({ symbol: row.symbol, status: 'error', message: msg })
        }
      }
      setGttSubmitting(false)
      setGttResults(gttOutcomes)

      const gttFailed = gttOutcomes.filter((g) => g.status !== 'success')
      if (gttFailed.length === 0) {
        showToast.success(`Bracket (Target/SL) attached for ${gttOutcomes.length} leg(s)`)
        setTimeout(() => onOpenChange(false), 800)
      } else {
        showToast.error(
          `Entry filled but bracket FAILED for: ${gttFailed.map((g) => g.symbol).join(', ')}. Position is live WITHOUT Target/SL protection — attach manually from GTT Orders.`,
          undefined,
          { duration: 10000 }
        )
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Network error'
      showToast.error(`Basket order error: ${msg}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Send className="h-4 w-4" /> Execute Basket Order
          </DialogTitle>
          <DialogDescription className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">Strategy</span>
            <span
              className="rounded-md border bg-muted/40 px-2 py-0.5 font-mono text-[11px] font-semibold text-foreground"
              title={strategyName}
            >
              {strategyName}
            </span>
            <span className="text-muted-foreground">·</span>
            <span className="text-muted-foreground">Exchange</span>
            <span className="rounded-md border bg-muted/40 px-2 py-0.5 font-mono text-[11px] font-semibold text-foreground">
              {new Set(rows.map((r) => r.exchange)).size > 1 ? 'Mixed' : exchange}
            </span>
          </DialogDescription>
        </DialogHeader>

        {/* Broker chip-select — defaults to the current data broker.
            Selecting more than one fans the basket out sequentially via
            /basketordermulti; a single selection keeps using the existing
            single-broker /basketorder path unchanged. */}
        <div className="space-y-1.5">
          <Label className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Execute on
          </Label>
          {connections.length === 0 ? (
            <p className="text-xs text-muted-foreground">
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
                    disabled={submitting || !!results}
                    className={cn(
                      'rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-colors',
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
          {showMultiBrokerGttNotice && (
            <p className="flex items-start gap-1.5 text-[11px] text-warning">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
              Target/SL (GTT) is only supported with a single broker selected — entry-only orders
              will be placed for {bracketEligibleRows.length} leg(s) with Target/SL.
            </p>
          )}
        </div>

        {/* Global controls — compact inline row */}
        <div className="flex items-end gap-4 rounded-lg border bg-muted/20 p-3">
          <div className="flex-1 space-y-1">
            <Label className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Product Type
            </Label>
            <div className="inline-flex h-9 w-full overflow-hidden rounded-md border bg-background">
              {PRODUCT_TYPES.map((p, idx) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setProduct(p)}
                  disabled={submitting || !!results}
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
          <div className="flex-1 space-y-1">
            <Label className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Price Type
            </Label>
            <div className="inline-flex h-9 w-full overflow-hidden rounded-md border bg-background">
              <button
                type="button"
                onClick={() => setPricetype('LIMIT')}
                disabled={submitting || !!results}
                className={cn(
                  'flex-1 text-xs font-semibold transition-colors',
                  pricetype === 'LIMIT'
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted'
                )}
              >
                LIMIT
              </button>
              <button
                type="button"
                onClick={() => setPricetype('MARKET')}
                disabled={submitting || !!results}
                className={cn(
                  'flex-1 border-l text-xs font-semibold transition-colors',
                  pricetype === 'MARKET'
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted'
                )}
              >
                MKT
              </button>
            </div>
          </div>
        </div>

        {/* Leg rows — compact rectangular grid. Symbol + side badges share
            one flex cell so the Max Algos symbol has the maximum possible
            width and wraps rather than truncates on narrow viewports. */}
        <div className="overflow-hidden rounded-lg border">
          {/* Header */}
          <div className="grid grid-cols-[32px_1fr_72px_104px] items-center gap-2 border-b bg-muted/30 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            <span className="text-center">Use</span>
            <span>Symbol</span>
            <span className="text-right">Lots</span>
            <span className="text-right">Price</span>
          </div>
          {/* Body */}
          <div className="max-h-[40vh] overflow-y-auto">
            {rows.length === 0 ? (
              <div className="p-6 text-center text-sm text-muted-foreground">
                No active legs in the strategy.
              </div>
            ) : (
              rows.map((r, idx) => {
                const result = results?.find((x) => x.symbol === r.symbol)
                const fillOutcome = fillOutcomes?.find((o) => o.symbol === r.symbol)
                return (
                  <div
                    key={r.legId}
                    className={cn(
                      'grid grid-cols-[32px_1fr_72px_104px] items-start gap-2 px-3 py-2 text-sm',
                      idx !== rows.length - 1 && 'border-b',
                      !r.include && 'opacity-50',
                      fillOutcome?.fillStatus === 'complete' && 'bg-profit/5',
                      (result?.status === 'error' || fillOutcome?.fillStatus === 'rejected') &&
                        'bg-loss/5',
                      fillOutcome?.fillStatus === 'unknown' && 'bg-warning/5'
                    )}
                  >
                    {/* Include */}
                    <div className="flex h-8 items-center justify-center">
                      <Checkbox
                        checked={r.include}
                        onCheckedChange={(v) => updateRow(r.legId, { include: v === true })}
                        disabled={submitting || !!results}
                      />
                    </div>

                    {/* Symbol cell — side/type badges inline, full Max Algos
                        symbol wraps onto a second line if needed (break-all)
                        instead of truncating. */}
                    <div className="min-w-0 flex-col">
                      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                        <span
                          className={cn(
                            'shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold text-white',
                            r.action === 'BUY' ? 'bg-profit' : 'bg-loss'
                          )}
                        >
                          {r.action === 'BUY' ? 'B' : 'S'}
                        </span>
                        {r.segment === 'OPTION' && r.optionType && (
                          <span
                            className={cn(
                              'shrink-0 rounded px-1 py-0.5 text-[10px] font-bold text-white',
                              r.optionType === 'CE' ? 'bg-profit' : 'bg-loss'
                            )}
                          >
                            {r.optionType}
                          </span>
                        )}
                        {r.segment === 'FUTURE' && (
                          <span className="shrink-0 rounded bg-sky-600 px-1 py-0.5 text-[10px] font-bold text-white">
                            FUT
                          </span>
                        )}
                        {r.segment === 'EQUITY' && (
                          <span className="shrink-0 rounded bg-violet-600 px-1 py-0.5 text-[10px] font-bold text-white">
                            EQ
                          </span>
                        )}
                        <span
                          className="break-all font-mono text-xs font-semibold leading-tight"
                          title={r.symbol}
                        >
                          {r.symbol}
                        </span>
                      </div>
                      <div className="mt-0.5 text-[10px] text-muted-foreground">
                        {r.exchange} · Lot size: {r.lotSize} · Qty: {r.lots * r.lotSize}
                      </div>
                      {result && (
                        <div className="mt-0.5 flex items-center gap-1 text-[10px]">
                          {result.status === 'error' ? (
                            <>
                              <XCircle className="h-3 w-3 text-loss" />
                              <span className="truncate text-loss" title={result.message}>
                                {result.message || 'Rejected at placement'}
                              </span>
                            </>
                          ) : !fillOutcome ? (
                            confirmingFills ? (
                              <>
                                <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
                                <span className="truncate text-muted-foreground">
                                  #{result.orderid} — confirming fill…
                                </span>
                              </>
                            ) : (
                              <>
                                <CheckCircle2 className="h-3 w-3 text-profit" />
                                <span className="truncate text-profit">#{result.orderid}</span>
                              </>
                            )
                          ) : fillOutcome.fillStatus === 'complete' ? (
                            <>
                              <CheckCircle2 className="h-3 w-3 text-profit" />
                              <span className="truncate text-profit">
                                Filled · #{result.orderid}
                              </span>
                            </>
                          ) : fillOutcome.fillStatus === 'rejected' ? (
                            <>
                              <XCircle className="h-3 w-3 text-loss" />
                              <span className="truncate text-loss" title={fillOutcome.message}>
                                Rejected by exchange
                                {fillOutcome.message ? ` — ${fillOutcome.message}` : ''}
                              </span>
                            </>
                          ) : (
                            <>
                              <Clock className="h-3 w-3 text-warning" />
                              <span className="truncate text-warning">
                                Still pending — check Order Book
                              </span>
                            </>
                          )}
                        </div>
                      )}
                      {(() => {
                        const isBracketRow =
                          fillOutcome?.fillStatus === 'complete' &&
                          bracketEligibleRows.some((br) => br.legId === r.legId)
                        if (!isBracketRow) return null
                        const gttResult = gttResults?.find((g) => g.symbol === r.symbol)
                        if (!gttResult) {
                          if (!gttSubmitting) return null
                          return (
                            <div className="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground">
                              <Loader2 className="h-3 w-3 animate-spin" />
                              Attaching bracket…
                            </div>
                          )
                        }
                        if (gttResult.status === 'success') {
                          return (
                            <div className="mt-0.5 flex items-center gap-1 text-[10px] text-profit">
                              <ShieldCheck className="h-3 w-3" />
                              Bracket attached
                            </div>
                          )
                        }
                        return (
                          <div className="mt-0.5 flex items-center gap-1 text-[10px] text-loss">
                            <AlertTriangle className="h-3 w-3 shrink-0" />
                            <span className="truncate" title={gttResult.message}>
                              Bracket FAILED — no Target/SL. {gttResult.message}
                            </span>
                          </div>
                        )
                      })()}
                    </div>

                    {/* Lots — user edits lots; contract qty = lots × lotSize
                        is computed at payload build time. */}
                    <Input
                      type="number"
                      min={1}
                      step={1}
                      value={r.lots}
                      onChange={(e) =>
                        updateRow(r.legId, {
                          lots: Math.max(1, Math.floor(Number(e.target.value) || 1)),
                        })
                      }
                      disabled={submitting || !!results || !r.include}
                      className="h-8 text-right font-mono text-xs"
                    />

                    {/* Price (disabled for MARKET) — snapped to the leg's
                        tick size on blur so users never see floating-point
                        drift like 185.85000000000002. */}
                    <Input
                      type="number"
                      min={0}
                      step={r.tickSize}
                      value={r.price}
                      onChange={(e) => updateRow(r.legId, { price: Number(e.target.value) || 0 })}
                      onBlur={(e) => {
                        const snapped = roundToTick(Number(e.target.value) || 0, r.tickSize)
                        updateRow(r.legId, { price: snapped })
                      }}
                      disabled={submitting || !!results || pricetype !== 'LIMIT' || !r.include}
                      placeholder={pricetype === 'MARKET' ? 'MKT' : '0.00'}
                      className="h-8 text-right font-mono text-xs"
                    />
                  </div>
                )
              })
            )}
          </div>
        </div>

        <DialogFooter className="flex-row items-center justify-between sm:justify-between">
          <div className="text-xs">
            {hasInvalidLimitPrice ? (
              <span className="text-destructive font-medium">
                Enter a price for every included leg (or switch to MKT) before executing
              </span>
            ) : (
              <span className="text-muted-foreground">
                {includedRows.length} of {rows.length} legs · {selectedBrokers.length} broker
                {selectedBrokers.length === 1 ? '' : 's'} selected
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
              {results ? 'Close' : 'Cancel'}
            </Button>
            <Button onClick={handleExecute} disabled={!canSubmit || !!results} className="gap-1.5">
              <Send className="h-3.5 w-3.5" />
              {gttSubmitting
                ? 'Attaching brackets…'
                : confirmingFills
                  ? 'Confirming fills…'
                  : submitting
                    ? 'Placing…'
                    : `Execute (${includedRows.length})`}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
