import { ListPlus, Minus, Plus, PlusCircle } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { apiClient } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { strikeMoneyness } from '@/lib/strategyMath'
import { cn } from '@/lib/utils'
import type { OptionStrike } from '@/types/option-chain'

export type LegDraftSegment = 'OPTION' | 'FUTURE' | 'EQUITY'
export type LegDraftSide = 'BUY' | 'SELL'
export type LegDraftType = 'CE' | 'PE'
export type EquityProduct = 'CNC' | 'MIS'
export type EquityOrderType = 'MARKET' | 'LIMIT'

export interface LegDraft {
  segment: LegDraftSegment
  side: LegDraftSide
  expiry: string
  strike?: number
  optionType?: LegDraftType
  lots: number
  price: number
  iv: number
  /** EQUITY only. */
  symbol?: string
  equityExchange?: string
  lotSize?: number
  /**
   * EQUITY only. Target/SL feed the Trade Preview's R:R math AND, once the
   * entry order fills, ExecuteBasketDialog attaches them as a real GTT
   * bracket (OCO if both set, SINGLE if only one) — see that file's
   * phase-2 GTT logic. GTT requires product CNC/NRML (MIS is rejected
   * server-side), so Target/SL are blocked at add-time when product=MIS
   * (see handleAdd below). Trailing SL % has no backend support anywhere
   * in this platform (no broker or scheduler implements it) — the field
   * is disabled in the UI and never sent to the GTT payload.
   */
  equityProduct?: EquityProduct
  equityOrderType?: EquityOrderType
  equityTargetPrice?: number
  equitySlPrice?: number
  equityTrailingSlPct?: number
}

interface EquitySearchResult {
  symbol: string
  exchange: string
  name: string
  lotsize: number
}

export interface ManualLegBuilderProps {
  /** Drives which segment's fields render — the page's asset-class toggle is
   * the single source of truth now; this component no longer has its own
   * independent Option/Future/Equity selector. */
  assetClass: 'Equity' | 'Futures' | 'Options'
  expiries: string[]
  futureExpiries: string[]
  chain: OptionStrike[] | null
  selectedExpiry: string
  atmStrike: number | null
  /** Common strike increment (e.g. 50 for NIFTY) — drives moneyness step labels. */
  strikeStep?: number
  /** Max Algos API key — used for the equity lot-size lookup. */
  apiKey: string
  /**
   * EQUITY only — the symbol/exchange/live-price the page's top "Analyzing"
   * selector already resolved. This card no longer runs its own
   * independent search: showing "RELIANCE" at the top while this card's
   * own Symbol field sat empty was a real bug (two disconnected pieces of
   * state both claiming to answer "what am I trading"). Pick once at the
   * top, every card downstream reads the same value.
   */
  equitySymbol?: string
  equityExchange?: string
  equityLivePrice?: number | null
  /**
   * Set (to a new object reference) when the user picks a card from
   * EquityTemplateGrid — pre-fills Side/Order Type and suggested Target/SL
   * without a resolution dialog (unlike options templates, there's no
   * strike/expiry to resolve against a live chain).
   */
  equityPrefill?: {
    side: LegDraftSide
    orderType: EquityOrderType
    suggestedSlPct?: number
    suggestedTargetPct?: number
  } | null
  onAdd: (draft: LegDraft) => void
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
      {children}
    </span>
  )
}

export function ManualLegBuilder({
  assetClass,
  expiries,
  futureExpiries,
  chain,
  selectedExpiry,
  atmStrike,
  strikeStep = 0,
  apiKey,
  equitySymbol = '',
  equityExchange = 'NSE',
  equityLivePrice = null,
  equityPrefill,
  onAdd,
}: ManualLegBuilderProps) {
  // Segment is dictated by the page's asset-class toggle, not an
  // independent selector here — Options asset-class maps to the OPTION
  // segment (Futures-within-Options leg-building isn't exposed by the page
  // toggle; this mirrors the prior default).
  const segment: LegDraftSegment =
    assetClass === 'Equity' ? 'EQUITY' : assetClass === 'Futures' ? 'FUTURE' : 'OPTION'
  const [side, setSide] = useState<LegDraftSide>('BUY')
  const [expiry, setExpiry] = useState<string>(selectedExpiry)
  const [optionType, setOptionType] = useState<LegDraftType>('CE')
  const [strike, setStrike] = useState<number | undefined>(undefined)
  const [lots, setLots] = useState(1)

  // Equity symbol/exchange/LTP now come from the page's shared top-level
  // selection (equitySymbol/equityExchange/equityLivePrice props) — this
  // card no longer has its own search box. Lot size still needs a lookup
  // (the quotes endpoint doesn't carry it), fired whenever the shared
  // symbol changes rather than on every keystroke of a local search.
  const [equityLotSize, setEquityLotSize] = useState(1)
  const [isEquityLotSizeLoading, setIsEquityLotSizeLoading] = useState(false)
  const [equityProduct, setEquityProduct] = useState<EquityProduct>('CNC')
  const [equityOrderType, setEquityOrderType] = useState<EquityOrderType>('MARKET')
  const [equityLimitPrice, setEquityLimitPrice] = useState<number | undefined>(undefined)
  const [equityTargetPrice, setEquityTargetPrice] = useState<number | undefined>(undefined)
  const [equitySlPrice, setEquitySlPrice] = useState<number | undefined>(undefined)
  const [equityTrailingSlPct, setEquityTrailingSlPct] = useState<number | undefined>(undefined)

  // Apply a template pick — side + order type immediately; suggested
  // Target/SL percentages resolve to concrete prices once a symbol with a
  // live LTP is selected (see the effect below).
  useEffect(() => {
    if (!equityPrefill) return
    setSide(equityPrefill.side)
    setEquityOrderType(equityPrefill.orderType)
  }, [equityPrefill])

  useEffect(() => {
    if (!equityPrefill || equityLivePrice === null) return
    const sign = equityPrefill.side === 'BUY' ? 1 : -1
    if (equityPrefill.suggestedTargetPct !== undefined) {
      setEquityTargetPrice(
        Number((equityLivePrice * (1 + (sign * equityPrefill.suggestedTargetPct) / 100)).toFixed(2))
      )
    }
    if (equityPrefill.suggestedSlPct !== undefined) {
      setEquitySlPrice(
        Number((equityLivePrice * (1 - (sign * equityPrefill.suggestedSlPct) / 100)).toFixed(2))
      )
    }
  }, [equityPrefill, equityLivePrice])

  // Lot size for the shared equity symbol — the quotes endpoint doesn't
  // carry it, so a single lookup fires whenever the top-level symbol
  // changes (not on every keystroke — there's no local search box anymore).
  useEffect(() => {
    if (segment !== 'EQUITY' || !equitySymbol || !apiKey) {
      setEquityLotSize(1)
      return
    }
    let cancelled = false
    setIsEquityLotSizeLoading(true)
    ;(async () => {
      try {
        const res = await apiClient.post<{
          status: string
          data?: EquitySearchResult[]
        }>('/search', { apikey: apiKey, query: equitySymbol, exchange: equityExchange })
        if (cancelled) return
        const match = res.data.data?.find(
          (r) => r.symbol === equitySymbol && r.exchange === equityExchange
        )
        setEquityLotSize(Math.max(1, match?.lotsize || 1))
      } catch {
        if (!cancelled) setEquityLotSize(1)
      } finally {
        if (!cancelled) setIsEquityLotSizeLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [segment, equitySymbol, equityExchange, apiKey])

  useEffect(() => {
    if (atmStrike === null || !chain) return
    const strikeInChain = strike !== undefined && chain.some((s) => s.strike === strike)
    if (!strikeInChain) setStrike(atmStrike)
  }, [atmStrike, chain, strike])

  const availableExpiries =
    segment === 'FUTURE' ? futureExpiries : segment === 'EQUITY' ? [] : expiries

  useEffect(() => {
    if (availableExpiries.length === 0) {
      setExpiry('')
      return
    }
    if (!availableExpiries.includes(expiry)) {
      setExpiry(availableExpiries[0])
    }
  }, [availableExpiries, expiry])

  const strikeOptions = useMemo(() => {
    if (!chain) return []
    return chain.map((s) => s.strike)
  }, [chain])

  const liveLeg = useMemo(() => {
    if (segment !== 'OPTION' || !chain || strike === undefined) return null
    const row = chain.find((s) => s.strike === strike)
    if (!row) return null
    const rowSide = optionType === 'CE' ? row.ce : row.pe
    if (!rowSide) return null
    return { price: rowSide.ltp, symbol: rowSide.symbol }
  }, [chain, strike, optionType, segment])

  // GTT (the real order-placement path for Target/SL, wired in
  // ExecuteBasketDialog) only accepts product CNC/NRML — MIS is rejected
  // server-side. Block the mismatch here, at add-time, rather than letting
  // the user discover it only after the entry order has already filled.
  const misBracketConflict =
    segment === 'EQUITY' &&
    equityProduct === 'MIS' &&
    (equityTargetPrice !== undefined || equitySlPrice !== undefined)

  const canAdd =
    segment === 'EQUITY'
      ? !!equitySymbol &&
        lots > 0 &&
        (equityOrderType !== 'LIMIT' || !!equityLimitPrice) &&
        !misBracketConflict
      : segment === 'FUTURE'
        ? expiry && lots > 0
        : expiry && optionType && strike !== undefined && lots > 0

  const handleAdd = () => {
    if (!canAdd) return
    if (segment === 'EQUITY') {
      if (!equitySymbol) return
      onAdd({
        segment,
        side,
        expiry: '',
        lots,
        price:
          equityOrderType === 'LIMIT'
            ? (equityLimitPrice ?? equityLivePrice ?? 0)
            : (equityLivePrice ?? 0),
        iv: 0,
        symbol: equitySymbol,
        equityExchange: equityExchange,
        lotSize: equityLotSize,
        equityProduct,
        equityOrderType,
        equityTargetPrice,
        equitySlPrice,
        equityTrailingSlPct,
      })
      setEquityLimitPrice(undefined)
      setEquityTargetPrice(undefined)
      setEquitySlPrice(undefined)
      setEquityTrailingSlPct(undefined)
      return
    }
    onAdd({
      segment,
      side,
      expiry,
      strike: segment === 'OPTION' ? strike : undefined,
      optionType: segment === 'OPTION' ? optionType : undefined,
      lots,
      price: liveLeg?.price ?? 0,
      iv: 0,
    })
  }

  const currentMoneyness = strikeMoneyness(strike, atmStrike, strikeStep, optionType)

  return (
    // No overflow-hidden here: it would clip the absolutely-positioned
    // equity symbol search dropdown below (which needs to float above
    // the sibling "Add a Position" panel and payoff card underneath it),
    // regardless of that dropdown's own z-index - overflow-hidden on an
    // ancestor always clips absolutely-positioned descendants.
    <div className="rounded-xl border bg-card shadow-sm">
      {/* Header — icon + title only. Buy/Sell moved down next to Add. */}
      <div className="flex items-center justify-between border-b bg-gradient-to-r from-muted/30 to-transparent px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-profit/15 to-info/15 text-profit">
            <ListPlus className="h-3.5 w-3.5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold leading-none">Add a Position</h3>
            <p className="mt-1 text-[10px] text-muted-foreground">
              Build legs manually with custom strike, expiry and side
            </p>
          </div>
        </div>
        {liveLeg && (
          <div className="hidden items-center gap-2 text-[11px] sm:flex">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-profit" />
              LTP
              <span className="font-bold tabular-nums text-foreground">
                ₹{liveLeg.price.toFixed(2)}
              </span>
            </span>
          </div>
        )}
      </div>

      {/* Action row — everything inline so mouse travel is minimal. */}
      <div className="flex flex-wrap items-end gap-3 px-4 py-4">
        {/* Exchange + Symbol (equity only) — READ-ONLY, mirrors the page's
            top "Analyzing" selector. That selector is the single place
            exchange/symbol are actually chosen; showing a second,
            independent search box here let the two disagree (top said
            "RELIANCE", this card's own field sat empty) — pick once at the
            top, every downstream card reads the same value. */}
        {segment === 'EQUITY' && (
          <div className="flex min-w-[220px] flex-col gap-1.5">
            <FieldLabel>Symbol</FieldLabel>
            {equitySymbol ? (
              <div className="flex h-9 items-center gap-2 rounded-md border bg-muted/30 px-3">
                <span className="text-xs font-semibold">{equitySymbol}</span>
                <span className="text-[10px] text-muted-foreground">{equityExchange}</span>
                <span className="ml-auto text-[11px] text-muted-foreground">
                  {isEquityLotSizeLoading ? (
                    '…'
                  ) : equityLivePrice !== null ? (
                    <>
                      LTP{' '}
                      <span className="font-semibold text-foreground">
                        ₹{equityLivePrice.toFixed(2)}
                      </span>
                    </>
                  ) : (
                    '—'
                  )}
                </span>
              </div>
            ) : (
              <div className="flex h-9 items-center rounded-md border border-dashed px-3 text-[11px] text-muted-foreground">
                Pick a symbol above in "Analyzing" first
              </div>
            )}
          </div>
        )}

        {/* Product (equity only) */}
        {segment === 'EQUITY' && (
          <div className="flex min-w-[90px] flex-col gap-1.5">
            <FieldLabel>Product</FieldLabel>
            <Select
              value={equityProduct}
              onValueChange={(v) => setEquityProduct(v as EquityProduct)}
            >
              <SelectTrigger className="h-9 text-xs font-medium">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="CNC">CNC</SelectItem>
                <SelectItem value="MIS">MIS</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}

        {/* Order Type + conditional Price (equity only) */}
        {segment === 'EQUITY' && (
          <div className="flex min-w-[110px] flex-col gap-1.5">
            <FieldLabel>Order Type</FieldLabel>
            <Select
              value={equityOrderType}
              onValueChange={(v) => setEquityOrderType(v as EquityOrderType)}
            >
              <SelectTrigger className="h-9 text-xs font-medium">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="MARKET">Market</SelectItem>
                <SelectItem value="LIMIT">Limit</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}
        {segment === 'EQUITY' && equityOrderType === 'LIMIT' && (
          <div className="flex min-w-[100px] flex-col gap-1.5">
            <FieldLabel>Price</FieldLabel>
            <Input
              type="number"
              min={0}
              step="0.05"
              value={equityLimitPrice ?? ''}
              onChange={(e) =>
                setEquityLimitPrice(e.target.value ? Number(e.target.value) : undefined)
              }
              placeholder={equityLivePrice ? equityLivePrice.toFixed(2) : '0.00'}
              className="h-9 text-xs font-medium tabular-nums"
            />
          </div>
        )}

        {/* Expiry (options/futures only) */}
        {segment !== 'EQUITY' && (
          <div className="flex min-w-[140px] flex-col gap-1.5">
            <FieldLabel>Expiry</FieldLabel>
            <Select value={expiry} onValueChange={setExpiry}>
              <SelectTrigger className="h-9 text-xs font-medium">
                <SelectValue placeholder={availableExpiries.length === 0 ? 'None' : 'Select'} />
              </SelectTrigger>
              <SelectContent>
                {availableExpiries.map((ex) => (
                  <SelectItem key={ex} value={ex}>
                    {ex}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {segment === 'OPTION' && (
          <>
            {/* Strike + inline moneyness */}
            <div className="flex min-w-[140px] flex-col gap-1.5">
              <FieldLabel>
                <span className="inline-flex items-center gap-1.5">
                  Strike
                  {currentMoneyness && (
                    <span
                      className={cn(
                        'rounded px-1 py-px text-[9px] font-bold uppercase tracking-wider normal-case',
                        currentMoneyness.kind === 'ATM' && 'bg-warning/15 text-warning',
                        currentMoneyness.kind === 'ITM' &&
                          'bg-info/15 text-info',
                        currentMoneyness.kind === 'OTM' && 'bg-muted text-muted-foreground'
                      )}
                    >
                      {currentMoneyness.label}
                    </span>
                  )}
                </span>
              </FieldLabel>
              <Select
                value={strike !== undefined ? String(strike) : ''}
                onValueChange={(v) => setStrike(Number(v))}
              >
                <SelectTrigger className="h-9 text-xs font-medium tabular-nums">
                  <SelectValue placeholder="Select" />
                </SelectTrigger>
                <SelectContent>
                  {strikeOptions.map((s) => {
                    const m = strikeMoneyness(s, atmStrike, strikeStep, optionType)
                    return (
                      <SelectItem key={s} value={String(s)}>
                        <span className="tabular-nums">{s}</span>
                        {m && (
                          <span
                            className={cn(
                              'ml-2 text-[9px] font-semibold uppercase tracking-wider',
                              m.kind === 'ATM' && 'text-warning',
                              m.kind === 'ITM' && 'text-info',
                              m.kind === 'OTM' && 'text-muted-foreground'
                            )}
                          >
                            {m.label}
                          </span>
                        )}
                      </SelectItem>
                    )
                  })}
                </SelectContent>
              </Select>
            </div>

            {/* CE / PE */}
            <div className="flex flex-col gap-1.5">
              <FieldLabel>Type</FieldLabel>
              <div className="inline-flex h-9 overflow-hidden rounded-md border bg-background p-0.5">
                <button
                  type="button"
                  onClick={() => setOptionType('CE')}
                  className={cn(
                    'rounded-sm px-3 text-[11px] font-bold transition',
                    optionType === 'CE'
                      ? 'bg-foreground text-background'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  CE
                </button>
                <button
                  type="button"
                  onClick={() => setOptionType('PE')}
                  className={cn(
                    'rounded-sm px-3 text-[11px] font-bold transition',
                    optionType === 'PE'
                      ? 'bg-foreground text-background'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  PE
                </button>
              </div>
            </div>
          </>
        )}

        {/* Buy / Sell — now inline, right where mouse already is. */}
        <div className="flex flex-col gap-1.5">
          <FieldLabel>Side</FieldLabel>
          <div className="inline-flex h-9 overflow-hidden rounded-md border bg-background p-0.5">
            <button
              type="button"
              onClick={() => setSide('BUY')}
              className={cn(
                'inline-flex items-center gap-1 rounded-sm px-3 text-[11px] font-bold uppercase tracking-wider transition',
                side === 'BUY'
                  ? 'bg-profit text-white shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              Buy
            </button>
            <button
              type="button"
              onClick={() => setSide('SELL')}
              className={cn(
                'inline-flex items-center gap-1 rounded-sm px-3 text-[11px] font-bold uppercase tracking-wider transition',
                side === 'SELL'
                  ? 'bg-loss text-white shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              Sell
            </button>
          </div>
        </div>

        {/* Lot Qty (raw share qty for equity) */}
        <div className="flex flex-col gap-1.5">
          <FieldLabel>{segment === 'EQUITY' ? 'Qty' : 'Lot Qty'}</FieldLabel>
          <div className="inline-flex h-9 w-[120px] items-center overflow-hidden rounded-md border bg-background">
            <button
              type="button"
              onClick={() => setLots(Math.max(1, lots - 1))}
              className="flex h-full w-9 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Decrease lots"
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
            <input
              type="number"
              min={1}
              value={lots}
              onChange={(e) => setLots(Math.max(1, Number(e.target.value) || 1))}
              className="h-full w-full border-x bg-transparent text-center text-xs font-bold tabular-nums outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
            />
            <button
              type="button"
              onClick={() => setLots(lots + 1)}
              className="flex h-full w-9 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Increase lots"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Target / Stop Loss (equity only) — once the entry order fills,
            ExecuteBasketDialog attaches these as a real GTT bracket (OCO if
            both set, SINGLE if only one). GTT requires product CNC/NRML,
            so this is blocked at add-time when product=MIS (see
            misBracketConflict below). Trailing SL % has no backend support
            anywhere in this platform and is disabled below. */}
        {segment === 'EQUITY' && (
          <>
            <div className="flex min-w-[100px] flex-col gap-1.5">
              <FieldLabel>Target</FieldLabel>
              <Input
                type="number"
                min={0}
                step="0.05"
                value={equityTargetPrice ?? ''}
                onChange={(e) =>
                  setEquityTargetPrice(e.target.value ? Number(e.target.value) : undefined)
                }
                placeholder="0.00"
                className="h-9 text-xs font-medium tabular-nums"
              />
            </div>
            <div className="flex min-w-[100px] flex-col gap-1.5">
              <FieldLabel>Stop Loss</FieldLabel>
              <Input
                type="number"
                min={0}
                step="0.05"
                value={equitySlPrice ?? ''}
                onChange={(e) =>
                  setEquitySlPrice(e.target.value ? Number(e.target.value) : undefined)
                }
                placeholder="0.00"
                className="h-9 text-xs font-medium tabular-nums"
              />
            </div>
            <div className="flex min-w-[110px] flex-col gap-1.5">
              <FieldLabel>
                <span className="inline-flex items-center gap-1">
                  Trailing SL %
                  <span className="rounded bg-muted px-1 py-px text-[9px] font-bold uppercase tracking-wider text-muted-foreground">
                    Soon
                  </span>
                </span>
              </FieldLabel>
              <Input
                type="number"
                min={0}
                step="0.1"
                value={equityTrailingSlPct ?? ''}
                onChange={(e) =>
                  setEquityTrailingSlPct(e.target.value ? Number(e.target.value) : undefined)
                }
                disabled
                placeholder="Not yet active"
                title="Trailing stop-loss isn't wired to a live order yet — no broker or backend service tracks price to ratchet the stop."
                className="h-9 text-xs font-medium tabular-nums opacity-60"
              />
            </div>
          </>
        )}

        {/* Context-aware Add button — color + label mirror the selected side,
            so the visual intent matches what will be added. */}
        <div className="ml-auto flex flex-col gap-1.5">
          <FieldLabel>&nbsp;</FieldLabel>
          <Button
            size="sm"
            onClick={handleAdd}
            disabled={!canAdd}
            className={cn(
              'h-9 gap-1.5 px-4 text-xs font-bold uppercase tracking-wider transition',
              side === 'BUY'
                ? 'bg-profit text-white hover:bg-profit'
                : 'bg-loss text-white hover:bg-loss'
            )}
          >
            <PlusCircle className="h-3.5 w-3.5" />
            {side === 'BUY' ? 'Add Buy' : 'Add Sell'}{' '}
            <span className="rounded bg-white/20 px-1.5 py-px text-[10px] font-bold tabular-nums">
              {side === 'BUY' ? '+' : '-'}
              {lots}x
            </span>
          </Button>
        </div>

        {misBracketConflict && (
          <p className="w-full text-[11px] font-medium text-loss">
            Target/SL requires CNC product — GTT does not support MIS/intraday. Switch Product to
            CNC, or clear Target/SL to add an MIS order.
          </p>
        )}
      </div>

      {/* Live symbol footer (LTP was moved to header; keep symbol here). */}
      {liveLeg && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-muted/20 px-4 py-2">
          <span className="text-[10px] text-muted-foreground sm:hidden">
            LTP
            <span className="ml-1 font-bold tabular-nums text-foreground">
              ₹{liveLeg.price.toFixed(2)}
            </span>
          </span>
          <span className="font-mono text-[10px] text-muted-foreground">{liveLeg.symbol}</span>
        </div>
      )}
    </div>
  )
}
