import { Pause, Play, Plus, Search, Trash2, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { strategyApi } from '@/api/strategy'
import StrikeSelector from '@/components/strategy/StrikeSelector'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import type {
  ConditionLeaf,
  ConditionNode,
  ConditionOperator,
  ExpiryType,
  InstrumentType,
  Leg,
  LegEntrySignal,
  LegGroup,
  LegRequest,
  StrikeSelectionMode,
  SymbolSearchResult,
} from '@/types/strategy'
import {
  COMMON_CONDITION_INDICATORS,
  CONDITION_OPERATORS,
  CONDITION_TYPES,
  EXPIRY_TYPES,
  getProductTypes,
  INSTRUMENT_TYPES,
  LEG_ENTRY_SIGNALS,
  STRIKE_OFFSETS,
} from '@/types/strategy'
import { showToast } from '@/utils/toast'

const FNO_EXCHANGES = ['NFO', 'BFO', 'MCX', 'CDS'] as const

function expiryLabel(expiryType?: string): string {
  return EXPIRY_TYPES.find((e) => e.value === expiryType)?.label || expiryType || ''
}

function legInstrumentSummary(leg: Leg): string {
  if (leg.entry_signal === 'EXIT') return 'Closes the open leg, goes flat'
  if (leg.instrument_type === 'OPT') {
    return `${leg.underlying} · ${expiryLabel(leg.expiry_type)} · ${leg.strike_offset} ${leg.option_type}`
  }
  if (leg.instrument_type === 'FUT') {
    return `${leg.underlying} · ${expiryLabel(leg.expiry_type)} · FUT`
  }
  return leg.instrument || '—'
}

function leafSummary(leaf: ConditionLeaf): string {
  switch (leaf.type) {
    case 'indicator':
      return `${leaf.indicator} ${leaf.condition} ${leaf.value}`
    case 'market_open':
      return `Market Open${leaf.exchange ? ` (${leaf.exchange})` : ''}`
    case 'broker_connected':
      return `Broker Connected${leaf.broker ? ` (${leaf.broker})` : ''}`
    case 'signal_fresh':
      return `Signal Fresh ${leaf.condition} ${leaf.value_seconds}s`
  }
}

function conditionSummary(condition: ConditionNode | null): string | null {
  if (!condition) return null
  if ('operator' in condition) {
    return condition.children
      .map((child) => ('operator' in child ? conditionSummary(child) : leafSummary(child)))
      .join(` ${condition.operator} `)
  }
  return leafSummary(condition)
}

/** One row in the leg-level condition-rule-group editor -- all-string form
 * fields regardless of leaf `type`, only the fields relevant to the
 * selected type are read when serializing (see ruleToLeaf). */
interface ConditionRuleDraft {
  type: ConditionLeaf['type']
  indicator: string
  operator: ConditionOperator
  value: string
  exchange: string
  broker: string
  valueSeconds: string
}

function emptyConditionRule(): ConditionRuleDraft {
  return {
    type: 'indicator',
    indicator: '',
    operator: '>',
    value: '',
    exchange: '',
    broker: '',
    valueSeconds: '10',
  }
}

function ruleToLeaf(rule: ConditionRuleDraft): ConditionLeaf | null {
  switch (rule.type) {
    case 'indicator':
      if (!rule.indicator.trim() || !rule.value.trim()) return null
      return {
        type: 'indicator',
        indicator: rule.indicator.trim().toUpperCase(),
        condition: rule.operator,
        value: rule.value.trim(),
      }
    case 'market_open':
      return { type: 'market_open', ...(rule.exchange ? { exchange: rule.exchange } : {}) }
    case 'broker_connected':
      return {
        type: 'broker_connected',
        ...(rule.broker.trim() ? { broker: rule.broker.trim() } : {}),
      }
    case 'signal_fresh': {
      const valueSeconds = Number(rule.valueSeconds)
      if (!valueSeconds || valueSeconds <= 0) return null
      return { type: 'signal_fresh', condition: rule.operator, value_seconds: valueSeconds }
    }
  }
}

function rulesToCondition(
  operator: 'AND' | 'OR',
  rules: ConditionRuleDraft[]
): ConditionNode | null {
  const leaves = rules.map(ruleToLeaf).filter((l): l is ConditionLeaf => l !== null)
  if (leaves.length === 0) return null
  if (leaves.length === 1) return leaves[0]
  return { operator, children: leaves }
}

/** Draft shape for one row in the generic multi-leg builder -- mirrors
 * LegRequest plus the local search-UI state needed while editing. An EXIT
 * draft only uses `label`/`entrySignal` -- every other field is ignored. */
interface LegDraft {
  label: string
  entrySignal: LegEntrySignal
  orderSide: 'BUY' | 'SELL'
  instrumentType: InstrumentType
  exchange: string
  underlying: string
  expiryType: ExpiryType | ''
  optionType: 'CE' | 'PE'
  strikeOffset: string
  strikeSelectionMode: StrikeSelectionMode
  strikeTargetValue: string
  instrument: string
  quantity: string
  productType: string
  // Condition (optional) -- a group of rules joined by one AND/OR operator.
  // An empty rule list means "no condition attached."
  conditionEnabled: boolean
  conditionOperator: 'AND' | 'OR'
  conditionRules: ConditionRuleDraft[]
}

function emptyLegDraft(label: string, entrySignal: LegEntrySignal): LegDraft {
  return {
    label,
    entrySignal,
    orderSide: 'BUY',
    instrumentType: 'OPT',
    exchange: '',
    underlying: '',
    expiryType: '',
    optionType: label.toLowerCase().includes('put') ? 'PE' : 'CE',
    strikeOffset: 'ATM',
    strikeSelectionMode: 'offset',
    strikeTargetValue: '',
    instrument: '',
    quantity: '1',
    productType: '',
    conditionEnabled: false,
    conditionOperator: 'AND',
    conditionRules: [emptyConditionRule()],
  }
}

function draftToRequest(draft: LegDraft): LegRequest | null {
  if (!draft.label.trim()) return null

  if (draft.entrySignal === 'EXIT') {
    return { label: draft.label.trim(), entry_signal: 'EXIT' }
  }

  let condition: ConditionNode | null = null
  if (draft.conditionEnabled) {
    condition = rulesToCondition(draft.conditionOperator, draft.conditionRules)
    // A user who enabled the condition toggle but left every rule
    // incomplete gets a hard stop, not a silently-dropped condition.
    if (!condition) return null
  }

  if (!draft.exchange || !draft.quantity || !draft.productType) return null
  const quantity = Number(draft.quantity)
  if (!quantity || quantity < 1) return null

  if (draft.instrumentType === 'EQ') {
    if (!draft.instrument) return null
    return {
      label: draft.label.trim(),
      entry_signal: draft.entrySignal,
      order_side: draft.orderSide,
      instrument_type: 'EQ',
      exchange: draft.exchange,
      instrument: draft.instrument,
      quantity,
      product_type: draft.productType,
      condition,
    }
  }

  if (!draft.underlying || !draft.expiryType) return null
  if (draft.instrumentType === 'OPT') {
    if (!draft.optionType) return null
    if (draft.strikeSelectionMode === 'offset' && !draft.strikeOffset) return null
    if (draft.strikeSelectionMode !== 'offset' && !draft.strikeTargetValue.trim()) return null
  }

  return {
    label: draft.label.trim(),
    entry_signal: draft.entrySignal,
    order_side: draft.orderSide,
    instrument_type: draft.instrumentType,
    exchange: draft.exchange,
    underlying: draft.underlying,
    expiry_type: draft.expiryType,
    ...(draft.instrumentType === 'OPT'
      ? {
          option_type: draft.optionType,
          strike_selection_mode: draft.strikeSelectionMode,
          ...(draft.strikeSelectionMode === 'offset'
            ? { strike_offset: draft.strikeOffset }
            : { strike_target_value: Number(draft.strikeTargetValue) }),
        }
      : {}),
    quantity,
    product_type: draft.productType,
    condition,
  }
}

/** One leg row inside the generic multi-leg builder -- instrument-type-aware
 * fields matching ConfigureSymbols.tsx's single-symbol form, parameterized
 * per leg instead of one flat form. */
function LegEditorRow({
  draft,
  onChange,
  onRemove,
  removable,
}: {
  draft: LegDraft
  onChange: (next: LegDraft) => void
  onRemove: () => void
  removable: boolean
}) {
  const [underlyingSearchOpen, setUnderlyingSearchOpen] = useState(false)
  const [searchResults, setSearchResults] = useState<SymbolSearchResult[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [underlyingQuery, setUnderlyingQuery] = useState(draft.underlying)

  useEffect(() => {
    if (draft.instrumentType === 'EQ') return
    const timer = setTimeout(async () => {
      if (underlyingQuery.length < 2) {
        setSearchResults([])
        return
      }
      try {
        setSearchLoading(true)
        const results = await strategyApi.searchUnderlyingSymbols(
          underlyingQuery,
          draft.exchange || undefined
        )
        setSearchResults(results)
      } catch {
        // ignore -- search box just stays empty
      } finally {
        setSearchLoading(false)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [underlyingQuery, draft.instrumentType, draft.exchange])

  const underlyingToFnoExchange = (exchange: string): string => {
    const ex = exchange.toUpperCase()
    if (ex === 'NSE' || ex === 'NSE_INDEX') return 'NFO'
    if (ex === 'BSE' || ex === 'BSE_INDEX') return 'BFO'
    if (ex === 'MCX' || ex === 'CDS') return ex
    return 'NFO'
  }

  const handleUnderlyingSelect = (result: SymbolSearchResult) => {
    onChange({
      ...draft,
      underlying: result.symbol,
      exchange: underlyingToFnoExchange(result.exchange),
      productType: draft.productType || 'NRML',
    })
    setUnderlyingSearchOpen(false)
  }

  // Suggest Quantity as the underlying's real lot size as soon as
  // underlying+exchange are both picked -- mirrors ConfigureSymbols.tsx's
  // single-symbol form (getUnderlyingLotsize), which this builder was
  // missing: a bare "1" for an F&O leg silently means 1 unit, not 1 lot,
  // which is almost never what's intended.
  useEffect(() => {
    if (draft.instrumentType === 'EQ' || !draft.underlying || !draft.exchange) return
    if (draft.quantity !== '1') return
    let cancelled = false
    strategyApi
      .getUnderlyingLotsize(draft.underlying, draft.exchange)
      .then((lotsize) => {
        if (cancelled || !lotsize || lotsize <= 1) return
        onChange({ ...draft, quantity: String(lotsize) })
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft.instrumentType, draft.underlying, draft.exchange])

  const productTypes = draft.exchange
    ? draft.instrumentType === 'OPT'
      ? ['MIS', 'NRML']
      : getProductTypes(draft.exchange)
    : []

  return (
    <div className="rounded-lg border overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 bg-muted/40 border-b">
        <Input
          className="max-w-[220px] font-semibold bg-background"
          value={draft.label}
          onChange={(e) => onChange({ ...draft, label: e.target.value })}
          placeholder="Leg label (e.g. Call)"
        />
        {removable && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="text-loss hover:text-loss hover:bg-loss/10"
            onClick={onRemove}
            aria-label={`Remove leg ${draft.label}`}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
      </div>

      <div className="p-4 space-y-5">
        {/* When to trigger */}
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            When to trigger
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Entry Signal</Label>
              <Select
                value={draft.entrySignal}
                onValueChange={(value: LegEntrySignal) =>
                  onChange({ ...draft, entrySignal: value })
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LEG_ENTRY_SIGNALS.map((s) => (
                    <SelectItem key={s.value} value={s.value}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {draft.entrySignal === 'EXIT'
                  ? 'Closes whatever leg is open and goes flat -- no instrument needed.'
                  : 'Which incoming signal opens this leg.'}
              </p>
            </div>
            {draft.entrySignal !== 'EXIT' && (
              <div className="space-y-2">
                <Label>Order Side</Label>
                <Select
                  value={draft.orderSide}
                  onValueChange={(value: 'BUY' | 'SELL') =>
                    onChange({ ...draft, orderSide: value })
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="BUY">BUY</SelectItem>
                    <SelectItem value="SELL">SELL</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">The broker order placed on entry.</p>
              </div>
            )}
          </div>
        </div>

        {draft.entrySignal === 'EXIT' ? null : (
          <>
            {/* What to trade */}
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                What to trade
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Instrument Type</Label>
                  <Select
                    value={draft.instrumentType}
                    onValueChange={(value: InstrumentType) =>
                      onChange({
                        ...emptyLegDraft(draft.label, draft.entrySignal),
                        instrumentType: value,
                      })
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {INSTRUMENT_TYPES.map((it) => (
                        <SelectItem key={it.value} value={it.value}>
                          {it.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {draft.instrumentType === 'EQ' ? (
                  <div className="space-y-2">
                    <Label>Broker Instrument</Label>
                    <Input
                      value={draft.instrument}
                      onChange={(e) =>
                        onChange({ ...draft, instrument: e.target.value.toUpperCase() })
                      }
                      placeholder="e.g. RELIANCE"
                    />
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Label>Underlying</Label>
                    <Popover open={underlyingSearchOpen} onOpenChange={setUnderlyingSearchOpen}>
                      <PopoverTrigger asChild>
                        <Button
                          variant="outline"
                          role="combobox"
                          aria-expanded={underlyingSearchOpen}
                          className="w-full justify-between font-normal"
                        >
                          {draft.underlying || 'Search underlying...'}
                          <Search className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent className="w-[320px] p-2" align="start">
                        <div className="flex items-center gap-2 border-b pb-2 px-1">
                          <Search className="h-4 w-4 shrink-0 opacity-50" />
                          <input
                            className="flex h-8 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                            placeholder="e.g. NIFTY"
                            value={underlyingQuery}
                            onChange={(e) => setUnderlyingQuery(e.target.value.toUpperCase())}
                          />
                        </div>
                        <div className="max-h-[260px] overflow-y-auto pt-2 space-y-1">
                          {searchLoading ? (
                            <div className="py-4 text-center text-xs text-muted-foreground">
                              Searching...
                            </div>
                          ) : underlyingQuery.length < 2 ? (
                            <div className="py-4 text-center text-xs text-muted-foreground">
                              Type at least 2 characters...
                            </div>
                          ) : searchResults.length === 0 ? (
                            <div className="py-4 text-center text-xs text-muted-foreground">
                              No symbols found
                            </div>
                          ) : (
                            searchResults.map((result) => (
                              <button
                                key={`${result.symbol}-${result.exchange}`}
                                type="button"
                                onClick={() => handleUnderlyingSelect(result)}
                                className="w-full flex items-center justify-between px-2 py-1.5 text-left text-sm rounded hover:bg-accent hover:text-accent-foreground transition-colors"
                              >
                                <span className="font-medium truncate">{result.symbol}</span>
                                <Badge
                                  variant="outline"
                                  className="text-[10px] px-1 py-0 font-mono ml-2 shrink-0"
                                >
                                  {result.exchange}
                                </Badge>
                              </button>
                            ))
                          )}
                        </div>
                      </PopoverContent>
                    </Popover>
                  </div>
                )}

                {draft.instrumentType !== 'EQ' && (
                  <>
                    <div className="space-y-2">
                      <Label>Exchange</Label>
                      <Select
                        value={draft.exchange}
                        onValueChange={(value) => onChange({ ...draft, exchange: value })}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select exchange" />
                        </SelectTrigger>
                        <SelectContent>
                          {FNO_EXCHANGES.map((ex) => (
                            <SelectItem key={ex} value={ex}>
                              {ex}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-2">
                      <Label>Expiry</Label>
                      <Select
                        value={draft.expiryType}
                        onValueChange={(value: ExpiryType) =>
                          onChange({ ...draft, expiryType: value })
                        }
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select expiry" />
                        </SelectTrigger>
                        <SelectContent>
                          {EXPIRY_TYPES.map((et) => (
                            <SelectItem key={et.value} value={et.value}>
                              {et.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    {draft.instrumentType === 'OPT' && (
                      <>
                        <div className="space-y-2">
                          <Label>Option Type</Label>
                          <div className="flex gap-2">
                            <Button
                              type="button"
                              variant={draft.optionType === 'CE' ? 'default' : 'outline'}
                              className="flex-1"
                              onClick={() => onChange({ ...draft, optionType: 'CE' })}
                            >
                              CE
                            </Button>
                            <Button
                              type="button"
                              variant={draft.optionType === 'PE' ? 'default' : 'outline'}
                              className="flex-1"
                              onClick={() => onChange({ ...draft, optionType: 'PE' })}
                            >
                              PE
                            </Button>
                          </div>
                        </div>
                        <StrikeSelector
                          value={{
                            mode: draft.strikeSelectionMode,
                            offsetValue: draft.strikeOffset,
                            targetValue: draft.strikeTargetValue,
                          }}
                          onChange={(next) =>
                            onChange({
                              ...draft,
                              strikeSelectionMode: next.mode,
                              strikeOffset: next.offsetValue,
                              strikeTargetValue: next.targetValue,
                            })
                          }
                        />
                      </>
                    )}
                  </>
                )}
              </div>
            </div>

            {/* Sizing */}
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Sizing
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Quantity</Label>
                  <Input
                    type="number"
                    min="1"
                    value={draft.quantity}
                    onChange={(e) => onChange({ ...draft, quantity: e.target.value })}
                  />
                  {draft.instrumentType !== 'EQ' && (
                    <p className="text-xs text-muted-foreground">
                      Auto-filled with the lot size once an underlying is selected -- adjust if
                      trading multiple lots.
                    </p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label>Product Type</Label>
                  <Select
                    value={draft.productType}
                    onValueChange={(value) => onChange({ ...draft, productType: value })}
                    disabled={!draft.exchange}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select product" />
                    </SelectTrigger>
                    <SelectContent>
                      {productTypes.map((pt) => (
                        <SelectItem key={pt} value={pt}>
                          {pt}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </div>

            {/* Condition (optional) */}
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id={`condition-enabled-${draft.label}`}
                  className="h-4 w-4"
                  checked={draft.conditionEnabled}
                  onChange={(e) => onChange({ ...draft, conditionEnabled: e.target.checked })}
                />
                <label
                  htmlFor={`condition-enabled-${draft.label}`}
                  className="text-xs font-semibold uppercase tracking-wide text-muted-foreground cursor-pointer"
                >
                  Condition (optional) -- only trigger if this is also true
                </label>
              </div>
              {draft.conditionEnabled && (
                <ConditionGroupEditor
                  operator={draft.conditionOperator}
                  rules={draft.conditionRules}
                  onOperatorChange={(operator) =>
                    onChange({ ...draft, conditionOperator: operator })
                  }
                  onRulesChange={(rules) => onChange({ ...draft, conditionRules: rules })}
                />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/** One rule row inside a ConditionGroupEditor -- a Type picker that swaps
 * the fields below it (indicator/operator/value for Indicator Comparison;
 * an optional exchange for Market Open; an optional broker for Broker
 * Connected; operator/seconds for Signal Fresh). */
function ConditionRuleEditor({
  rule,
  onChange,
  onRemove,
  removable,
}: {
  rule: ConditionRuleDraft
  onChange: (next: ConditionRuleDraft) => void
  onRemove: () => void
  removable: boolean
}) {
  return (
    <div className="flex flex-col sm:flex-row items-start sm:items-end gap-2">
      <div className="space-y-2 w-full sm:w-48">
        <Label>Type</Label>
        <Select
          value={rule.type}
          onValueChange={(value: ConditionLeaf['type']) =>
            onChange({ ...emptyConditionRule(), type: value })
          }
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CONDITION_TYPES.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {rule.type === 'indicator' && (
        <>
          <div className="space-y-2 w-full sm:w-40">
            <Label>Indicator</Label>
            <Input
              list="condition-indicators"
              value={rule.indicator}
              onChange={(e) => onChange({ ...rule, indicator: e.target.value.toUpperCase() })}
              placeholder="e.g. RSI"
            />
            <datalist id="condition-indicators">
              {COMMON_CONDITION_INDICATORS.map((ind) => (
                <option key={ind} value={ind} />
              ))}
            </datalist>
          </div>
          <div className="space-y-2 w-full sm:w-36">
            <Label>Comparison</Label>
            <Select
              value={rule.operator}
              onValueChange={(value: ConditionOperator) => onChange({ ...rule, operator: value })}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CONDITION_OPERATORS.map((op) => (
                  <SelectItem key={op.value} value={op.value}>
                    {op.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2 w-full sm:w-32">
            <Label>Value</Label>
            <Input
              value={rule.value}
              onChange={(e) => onChange({ ...rule, value: e.target.value })}
              placeholder="e.g. 70"
            />
          </div>
        </>
      )}

      {rule.type === 'market_open' && (
        <div className="space-y-2 w-full sm:w-40">
          <Label>Exchange (optional)</Label>
          <Select
            value={rule.exchange || '__any__'}
            onValueChange={(value) =>
              onChange({ ...rule, exchange: value === '__any__' ? '' : value })
            }
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__any__">Any exchange</SelectItem>
              {FNO_EXCHANGES.map((ex) => (
                <SelectItem key={ex} value={ex}>
                  {ex}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {rule.type === 'broker_connected' && (
        <div className="space-y-2 w-full sm:w-40">
          <Label>Broker (optional)</Label>
          <Input
            value={rule.broker}
            onChange={(e) => onChange({ ...rule, broker: e.target.value })}
            placeholder="Any broker"
          />
        </div>
      )}

      {rule.type === 'signal_fresh' && (
        <>
          <div className="space-y-2 w-full sm:w-36">
            <Label>Age</Label>
            <Select
              value={rule.operator}
              onValueChange={(value: ConditionOperator) => onChange({ ...rule, operator: value })}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CONDITION_OPERATORS.map((op) => (
                  <SelectItem key={op.value} value={op.value}>
                    {op.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2 w-full sm:w-32">
            <Label>Seconds</Label>
            <Input
              type="number"
              min="1"
              value={rule.valueSeconds}
              onChange={(e) => onChange({ ...rule, valueSeconds: e.target.value })}
            />
          </div>
        </>
      )}

      {removable && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="text-loss hover:text-loss hover:bg-loss/10 shrink-0"
          onClick={onRemove}
          aria-label="Remove condition rule"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      )}
    </div>
  )
}

/** A leg's condition: a list of rules joined by one AND/OR operator (a
 * single flat group -- see conditionToRules/rulesToCondition for why
 * nested groups aren't exposed in this editor). */
function ConditionGroupEditor({
  operator,
  rules,
  onOperatorChange,
  onRulesChange,
}: {
  operator: 'AND' | 'OR'
  rules: ConditionRuleDraft[]
  onOperatorChange: (operator: 'AND' | 'OR') => void
  onRulesChange: (rules: ConditionRuleDraft[]) => void
}) {
  return (
    <div className="space-y-3">
      {rules.map((rule, i) => (
        <div key={i} className="flex items-start gap-2">
          {i > 0 && (
            <Select value={operator} onValueChange={(v: 'AND' | 'OR') => onOperatorChange(v)}>
              <SelectTrigger className="w-20 shrink-0 mt-6">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="AND">AND</SelectItem>
                <SelectItem value="OR">OR</SelectItem>
              </SelectContent>
            </Select>
          )}
          <div className="flex-1">
            <ConditionRuleEditor
              rule={rule}
              onChange={(next) => onRulesChange(rules.map((r, idx) => (idx === i ? next : r)))}
              onRemove={() => onRulesChange(rules.filter((_, idx) => idx !== i))}
              removable={rules.length > 1}
            />
          </div>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => onRulesChange([...rules, emptyConditionRule()])}
      >
        <Plus className="h-4 w-4 mr-2" />
        Add Rule
      </Button>
    </div>
  )
}

/** One leg-group card in the list -- shows its legs, current rotation
 * state ("Currently open: Call/Put/Flat"), and pause/edit/delete actions. */
function LegGroupCard({
  group,
  onToggle,
  onDelete,
  toggling,
}: {
  group: LegGroup
  onToggle: () => void
  onDelete: () => void
  toggling: boolean
}) {
  const currentLeg = group.legs.find((l) => l.id === group.current_leg_id)

  return (
    <div className={`rounded-lg border p-4 space-y-3 ${group.is_active ? '' : 'opacity-50'}`}>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold">{group.name}</span>
          {!group.is_active && (
            <Badge variant="secondary" className="text-[10px]">
              Paused
            </Badge>
          )}
          <Badge variant={currentLeg ? 'default' : 'outline'} className="text-[10px]">
            Currently open: {currentLeg ? currentLeg.label : 'Flat'}
          </Badge>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggle}
            disabled={toggling}
            title={group.is_active ? 'Pause' : 'Resume'}
            aria-label={group.is_active ? `Pause ${group.name}` : `Resume ${group.name}`}
          >
            {group.is_active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="text-loss hover:text-loss hover:bg-loss/10"
            onClick={onDelete}
            aria-label={`Delete ${group.name}`}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {group.legs.map((leg) => (
          <div
            key={leg.id}
            className={`rounded border px-3 py-2 text-sm ${leg.id === group.current_leg_id ? 'border-primary bg-primary/5' : ''}`}
          >
            <div className="flex items-center justify-between">
              <span className="font-medium">{leg.label}</span>
              <Badge variant="outline" className="text-[10px]">
                {leg.entry_signal === 'EXIT'
                  ? 'EXIT · flatten'
                  : `${leg.entry_signal} → ${leg.order_side}`}
              </Badge>
            </div>
            <div className="text-muted-foreground text-xs mt-1">{legInstrumentSummary(leg)}</div>
            {leg.entry_signal !== 'EXIT' && (
              <div className="text-muted-foreground text-xs">
                Qty {leg.quantity} · {leg.product_type}
              </div>
            )}
            {conditionSummary(leg.condition) && (
              <div className="text-muted-foreground text-xs">
                Only if: {conditionSummary(leg.condition)}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function LegGroupsPanel({ strategyId }: { strategyId: number }) {
  const [groups, setGroups] = useState<LegGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [togglingId, setTogglingId] = useState<number | null>(null)

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [groupToDelete, setGroupToDelete] = useState<number | null>(null)

  // CE/PE Reversal quick-start
  const [quickUnderlying, setQuickUnderlying] = useState('')
  const [quickExchange, setQuickExchange] = useState('NFO')
  const [quickExpiry, setQuickExpiry] = useState<ExpiryType | ''>('')
  const [quickStrike, setQuickStrike] = useState('ATM')
  const [quickQuantity, setQuickQuantity] = useState('1')
  const [quickProduct, setQuickProduct] = useState('NRML')
  const [quickSubmitting, setQuickSubmitting] = useState(false)

  // Generic multi-leg builder
  const [builderOpen, setBuilderOpen] = useState(false)
  const [groupName, setGroupName] = useState('')
  const [legDrafts, setLegDrafts] = useState<LegDraft[]>([
    emptyLegDraft('Call', 'BUY'),
    emptyLegDraft('Put', 'SELL'),
  ])
  const [builderSubmitting, setBuilderSubmitting] = useState(false)

  const fetchGroups = async () => {
    try {
      setLoading(true)
      const response = await strategyApi.getLegGroups(strategyId)
      if (response.status === 'success') {
        setGroups(response.data || [])
      }
    } catch {
      showToast.error('Failed to load leg groups', 'strategy')
    } finally {
      setLoading(false)
    }
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: one-time fetch on mount, re-run only if strategyId itself changes
  useEffect(() => {
    fetchGroups()
  }, [strategyId])

  const handleQuickCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!quickUnderlying) {
      showToast.error('Please select an underlying', 'strategy')
      return
    }
    if (!quickExpiry) {
      showToast.error('Please select an expiry', 'strategy')
      return
    }
    if (!quickQuantity || Number(quickQuantity) < 1) {
      showToast.error('Quantity must be at least 1', 'strategy')
      return
    }

    try {
      setQuickSubmitting(true)
      const response = await strategyApi.createCePeReversal(strategyId, {
        underlying: quickUnderlying,
        exchange: quickExchange,
        expiry_type: quickExpiry,
        strike_offset: quickStrike,
        quantity: Number(quickQuantity),
        product_type: quickProduct,
      })
      if (response.status === 'success') {
        showToast.success('CE/PE Reversal created', 'strategy')
        setQuickUnderlying('')
        setQuickExpiry('')
        fetchGroups()
      } else {
        showToast.error(response.message || 'Failed to create reversal', 'strategy')
      }
    } catch {
      showToast.error('Failed to create reversal', 'strategy')
    } finally {
      setQuickSubmitting(false)
    }
  }

  const handleBuilderSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!groupName.trim()) {
      showToast.error('Please name this leg group', 'strategy')
      return
    }

    // Each leg must react to a different signal (BUY/SELL/SHORT/EXIT) or
    // the target leg for a given signal is ambiguous (see
    // resolve_leg_rotation in database/strategy_db.py, which picks the
    // first match on a tie). At most one EXIT leg, since EXIT has no
    // instrument of its own -- two would both just mean "flatten."
    const signals = legDrafts.map((d) => d.entrySignal)
    if (new Set(signals).size !== signals.length) {
      showToast.error('Each leg must react to a different signal', 'strategy')
      return
    }
    if (signals.filter((s) => s === 'EXIT').length > 1) {
      showToast.error('Only one leg can be EXIT', 'strategy')
      return
    }

    const legs = legDrafts.map(draftToRequest)
    if (legs.some((l) => l === null)) {
      showToast.error("Please complete every leg's fields before saving", 'strategy')
      return
    }

    try {
      setBuilderSubmitting(true)
      const response = await strategyApi.createLegGroup(strategyId, {
        name: groupName.trim(),
        legs: legs as LegRequest[],
      })
      if (response.status === 'success') {
        showToast.success('Leg group created', 'strategy')
        setGroupName('')
        setLegDrafts([emptyLegDraft('Call', 'BUY'), emptyLegDraft('Put', 'SELL')])
        setBuilderOpen(false)
        fetchGroups()
      } else {
        showToast.error(response.message || 'Failed to create leg group', 'strategy')
      }
    } catch {
      showToast.error('Failed to create leg group', 'strategy')
    } finally {
      setBuilderSubmitting(false)
    }
  }

  const handleToggle = async (group: LegGroup) => {
    try {
      setTogglingId(group.id)
      const response = await strategyApi.toggleLegGroup(strategyId, group.id)
      if (response.status === 'success') {
        setGroups((prev) =>
          prev.map((g) =>
            g.id === group.id ? { ...g, is_active: response.data?.is_active ?? !g.is_active } : g
          )
        )
        showToast.success(
          response.data?.is_active ? 'Leg group resumed' : 'Leg group paused',
          'strategy'
        )
      } else {
        showToast.error(response.message || 'Failed to toggle leg group', 'strategy')
      }
    } catch {
      showToast.error('Failed to toggle leg group', 'strategy')
    } finally {
      setTogglingId(null)
    }
  }

  const handleDelete = async () => {
    if (groupToDelete === null) return
    try {
      const response = await strategyApi.deleteLegGroup(strategyId, groupToDelete)
      if (response.status === 'success') {
        setGroups((prev) => prev.filter((g) => g.id !== groupToDelete))
        showToast.success('Leg group removed', 'strategy')
      } else {
        showToast.error(response.message || 'Failed to remove leg group', 'strategy')
      }
    } catch {
      showToast.error('Failed to remove leg group', 'strategy')
    } finally {
      setDeleteDialogOpen(false)
      setGroupToDelete(null)
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-48" />
        <Skeleton className="h-64" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* CE/PE Reversal quick-start */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="h-5 w-5" />
            CE/PE Reversal Quick-Start
          </CardTitle>
          <CardDescription>
            One-click Call/Put flip: BUY signal opens a Call; the next SELL closes the Call and
            opens a Put; the next BUY closes the Put and opens the Call again. The system tracks
            which leg is currently open, so it always closes the right one before opening the other.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleQuickCreate} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
              <div className="space-y-2">
                <Label>Underlying</Label>
                <Input
                  value={quickUnderlying}
                  onChange={(e) => setQuickUnderlying(e.target.value.toUpperCase())}
                  placeholder="e.g. NIFTY"
                />
              </div>
              <div className="space-y-2">
                <Label>Exchange</Label>
                <Select value={quickExchange} onValueChange={setQuickExchange}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {FNO_EXCHANGES.map((ex) => (
                      <SelectItem key={ex} value={ex}>
                        {ex}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Expiry</Label>
                <Select value={quickExpiry} onValueChange={(v: ExpiryType) => setQuickExpiry(v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select expiry" />
                  </SelectTrigger>
                  <SelectContent>
                    {EXPIRY_TYPES.map((et) => (
                      <SelectItem key={et.value} value={et.value}>
                        {et.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Strike</Label>
                <Select value={quickStrike} onValueChange={setQuickStrike}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {STRIKE_OFFSETS.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Quantity</Label>
                <Input
                  type="number"
                  min="1"
                  value={quickQuantity}
                  onChange={(e) => setQuickQuantity(e.target.value)}
                />
              </div>
            </div>
            <div className="space-y-2 max-w-xs">
              <Label>Product Type</Label>
              <Select value={quickProduct} onValueChange={setQuickProduct}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="NRML">NRML</SelectItem>
                  <SelectItem value="MIS">MIS</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button type="submit" disabled={quickSubmitting}>
              {quickSubmitting ? 'Creating...' : 'Create Reversal'}
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Leg Groups list */}
      <Card>
        <CardHeader>
          <CardTitle>Leg Groups</CardTitle>
          <CardDescription>
            {groups.length} group{groups.length !== 1 ? 's' : ''} configured
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {groups.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <p>No leg groups configured yet.</p>
              <p className="text-sm">Use the quick-start above or add a custom group below.</p>
            </div>
          ) : (
            groups.map((group) => (
              <LegGroupCard
                key={group.id}
                group={group}
                toggling={togglingId === group.id}
                onToggle={() => handleToggle(group)}
                onDelete={() => {
                  setGroupToDelete(group.id)
                  setDeleteDialogOpen(true)
                }}
              />
            ))
          )}
        </CardContent>
      </Card>

      {/* Generic leg builder */}
      <Card>
        <CardHeader>
          <CardTitle>Custom Leg Group</CardTitle>
          <CardDescription>
            A leg group has 2 to 4 legs, each reacting to a different signal (BUY/SELL/SHORT/ EXIT)
            -- a webhook alert can only ever send one of those four. Only one leg is ever open at a
            time: a new signal closes whichever leg is open (if any) and opens the leg for that
            signal, unless the signal is EXIT (closes and opens nothing) or the target leg has a
            condition attached that isn't currently met. Need more than one rotation? Create
            additional leg groups below (e.g. one for NIFTY, another for BANKNIFTY) -- they all
            react to the same webhook independently.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!builderOpen ? (
            <Button variant="outline" onClick={() => setBuilderOpen(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Add Leg Group
            </Button>
          ) : (
            <form onSubmit={handleBuilderSubmit} className="space-y-4">
              <div className="space-y-2 max-w-sm">
                <Label>Group Name</Label>
                <Input
                  value={groupName}
                  onChange={(e) => setGroupName(e.target.value)}
                  placeholder="e.g. BANKNIFTY CE/PE Reversal"
                />
              </div>

              <div className="flex items-center justify-between">
                <p className="text-sm text-muted-foreground">
                  {legDrafts.length} leg{legDrafts.length !== 1 ? 's' : ''} (2-4 allowed)
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    setLegDrafts((prev) => [
                      ...prev,
                      emptyLegDraft(`Leg ${prev.length + 1}`, 'SHORT'),
                    ])
                  }
                  disabled={
                    legDrafts.length >= 4 || legDrafts.some((d) => d.entrySignal === 'EXIT')
                  }
                  title={
                    legDrafts.some((d) => d.entrySignal === 'EXIT')
                      ? 'Change the EXIT leg to another signal before adding more legs'
                      : undefined
                  }
                >
                  <Plus className="h-4 w-4 mr-2" />
                  Add Leg
                </Button>
              </div>

              <div className="space-y-3">
                {legDrafts.map((draft, i) => (
                  <LegEditorRow
                    key={i}
                    draft={draft}
                    onChange={(next) =>
                      setLegDrafts((prev) => prev.map((d, idx) => (idx === i ? next : d)))
                    }
                    onRemove={() => setLegDrafts((prev) => prev.filter((_, idx) => idx !== i))}
                    removable={legDrafts.length > 2}
                  />
                ))}
              </div>

              <div className="flex items-center gap-2">
                <Button type="submit" disabled={builderSubmitting}>
                  {builderSubmitting ? 'Saving...' : 'Save Leg Group'}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setBuilderOpen(false)
                    setGroupName('')
                    setLegDrafts([emptyLegDraft('Call', 'BUY'), emptyLegDraft('Put', 'SELL')])
                  }}
                >
                  Cancel
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove Leg Group</DialogTitle>
            <DialogDescription>
              Are you sure you want to remove this leg group? This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDelete}>
              Remove Leg Group
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
