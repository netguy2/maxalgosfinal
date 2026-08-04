import { ArrowLeft, FileText, Plus, RefreshCw, Upload } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { extractErrorMessage } from '@/api/client'
import { strategyApi } from '@/api/strategy'
import { ExecutionFlow } from '@/components/strategy/ExecutionFlow'
import { MappingCard } from '@/components/strategy/MappingCard'
import { SetupStep } from '@/components/strategy/SetupStep'
import { SignalActionFields } from '@/components/strategy/SignalActionFields'
import { type SignalPreset, SignalPresets } from '@/components/strategy/SignalPresets'
import StrikeSelector from '@/components/strategy/StrikeSelector'
import { TestWebhookPanel } from '@/components/strategy/TestWebhookPanel'
import { UnderlyingSearch } from '@/components/strategy/UnderlyingSearch'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import type {
  ExpiryType,
  InstrumentType,
  MappingAction,
  OrderType,
  RiskValueType,
  SignalAction,
  Strategy,
  StrategySymbolMapping,
  StrikeSelectionMode,
  SymbolSearchResult,
} from '@/types/strategy'
import {
  EQUITY_EXCHANGES,
  EXCHANGES,
  EXPIRY_TYPES,
  getProductTypes,
  INSTRUMENT_TYPES,
  SIGNAL_ACTIONS,
  UNIFIED_ACTIONS,
} from '@/types/strategy'
import { showToast } from '@/utils/toast'
import LegGroupsPanel from './LegGroupsPanel'

// F&O exchanges -- where underlyings for Futures/Options mappings are
// searched/traded. Equity/Index exchange (NSE/BSE) is still what the user
// picks for the underlying's OWN listing when searching, but order routing
// for FUT/OPT always happens on one of these.
const FNO_EXCHANGES = ['NFO', 'BFO', 'MCX', 'CDS'] as const

function expiryLabel(expiryType?: string): string {
  return EXPIRY_TYPES.find((e) => e.value === expiryType)?.label || expiryType || ''
}

/** Human-readable one-line summary for a FUT/OPT mapping row, e.g.
 * "NIFTY · Weekly (Current) · ATM CE" -- used in place of the frozen
 * `instrument` string, which is meaningless for these rows since the
 * tradable contract is resolved live on every signal, not stored. */
function instrumentSummary(mapping: StrategySymbolMapping): string {
  if (mapping.instrument_type === 'OPT') {
    return `${mapping.underlying} · ${expiryLabel(mapping.expiry_type)} · ${mapping.strike_offset} ${mapping.option_type}`
  }
  if (mapping.instrument_type === 'FUT') {
    return `${mapping.underlying} · ${expiryLabel(mapping.expiry_type)} · FUT`
  }
  return mapping.instrument || mapping.symbol
}

interface InstrumentFormState {
  instrumentType: InstrumentType
  // EQ
  symbolSearch: string
  searchResults: SymbolSearchResult[]
  searchLoading: boolean
  searchOpen: boolean
  selectedSymbol: SymbolSearchResult | null
  // FUT / OPT
  underlying: string
  underlyingSearchOpen: boolean
  exchange: string
  expiryType: ExpiryType | ''
  optionType: 'CE' | 'PE'
  strikeOffset: string
  strikeSelectionMode: StrikeSelectionMode
  strikeTargetValue: string
  // shared
  quantity: string
  productType: string
  // unified execution model only
  orderSide: 'BUY' | 'SELL' | ''
  // --- Signal Actions -------------------------------------------------
  // What to do when the trigger signal arrives, how to place the order,
  // and the protective orders that follow a fill. All optional: left at
  // their defaults the payload omits them and the mapping behaves exactly
  // as one created before these fields existed.
  signalAction: SignalAction
  orderType: OrderType
  limitPrice: string
  triggerPrice: string
  stopLossValue: string
  stopLossType: RiskValueType
  targetValue: string
  targetType: RiskValueType
  trailingValue: string
  trailingType: RiskValueType
  // Size in lots (F&O). Blank => use raw `quantity`.
  lots: string
  // Legs sharing a basket name fire together on one signal.
  legBasket: string
  label: string
}

function emptyFormState(): InstrumentFormState {
  return {
    instrumentType: 'EQ',
    symbolSearch: '',
    searchResults: [],
    searchLoading: false,
    searchOpen: false,
    selectedSymbol: null,
    underlying: '',
    underlyingSearchOpen: false,
    exchange: '',
    expiryType: '',
    optionType: 'CE',
    strikeOffset: 'ATM',
    strikeSelectionMode: 'offset',
    strikeTargetValue: '',
    quantity: '1',
    productType: '',
    orderSide: '',
    signalAction: 'ENTER',
    orderType: 'MARKET',
    limitPrice: '',
    triggerPrice: '',
    stopLossValue: '',
    stopLossType: 'percent',
    targetValue: '',
    targetType: 'percent',
    trailingValue: '',
    trailingType: 'percent',
    lots: '',
    legBasket: '',
    label: '',
  }
}

/**
 * Build the Signal Actions half of an add/update payload.
 *
 * Only non-default values are included. That matters: the backend treats a
 * missing key as "leave this column NULL", and every read path interprets
 * NULL as "behave exactly as before this feature existed". So a user who
 * ignores the advanced section produces a mapping byte-identical to one
 * created by the old form.
 */
function signalActionPayload(form: InstrumentFormState) {
  const payload: Record<string, unknown> = {}

  if (form.signalAction && form.signalAction !== 'ENTER') {
    payload.signal_action = form.signalAction
  }
  if (form.orderType && form.orderType !== 'MARKET') {
    payload.order_type = form.orderType
    if (form.limitPrice.trim()) payload.limit_price = Number(form.limitPrice)
    if (form.triggerPrice.trim()) payload.trigger_price = Number(form.triggerPrice)
  }

  for (const [value, type, valueKey, typeKey] of [
    [form.stopLossValue, form.stopLossType, 'stop_loss_value', 'stop_loss_type'],
    [form.targetValue, form.targetType, 'target_value', 'target_type'],
    [form.trailingValue, form.trailingType, 'trailing_value', 'trailing_type'],
  ] as const) {
    if (value.trim()) {
      payload[valueKey] = Number(value)
      payload[typeKey] = type
    }
  }

  if (form.lots.trim()) payload.lots = Number(form.lots)
  if (form.legBasket.trim()) payload.leg_basket = form.legBasket.trim()
  if (form.label.trim()) payload.label = form.label.trim()

  return payload
}

export default function ConfigureSymbols() {
  const { strategyId } = useParams<{ strategyId: string }>()
  const [strategy, setStrategy] = useState<Strategy | null>(null)
  const [mappings, setMappings] = useState<StrategySymbolMapping[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [applyingPreset, setApplyingPreset] = useState(false)
  const [togglingId, setTogglingId] = useState<number | null>(null)
  // Step 1 (What are you trading?) must be confirmed before Quick Start /
  // Add Symbols appear -- a single confirm-then-configure flow instead of
  // every section visible and editable at once.
  const [setupConfirmed, setSetupConfirmed] = useState(false)

  const isStateful = strategy?.execution_model === 'stateful'
  // Every non-rotation strategy now exposes the full 4-action vocabulary.
  // New strategies are created as 'unified' server-side, and 'legacy' rows
  // still accept BUY/SELL identically -- so showing the richer editor is
  // safe for both and removes the old "which mode am I in?" question.
  const isUnified = !isStateful

  const [triggerSymbol, setTriggerSymbol] = useState<'BUY' | 'SELL' | 'BOTH'>('BOTH')
  const [unifiedAction, setUnifiedAction] = useState<MappingAction>('BUY')
  const [form, setForm] = useState<InstrumentFormState>(emptyFormState())

  // Bulk symbols form
  const [csvData, setCsvData] = useState('')

  // Delete confirmation
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [mappingToDelete, setMappingToDelete] = useState<number | null>(null)

  // Edit dialog
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [mappingToEdit, setMappingToEdit] = useState<StrategySymbolMapping | null>(null)
  const [editTrigger, setEditTrigger] = useState<'BUY' | 'SELL' | 'BOTH'>('BOTH')
  const [editUnifiedAction, setEditUnifiedAction] = useState<MappingAction>('BUY')
  const [editForm, setEditForm] = useState<InstrumentFormState>(emptyFormState())
  const [editSubmitting, setEditSubmitting] = useState(false)

  const openEditDialog = (mapping: StrategySymbolMapping) => {
    setMappingToEdit(mapping)
    setEditTrigger(mapping.symbol === 'SELL' ? 'SELL' : mapping.symbol === 'BUY' ? 'BUY' : 'BOTH')
    setEditUnifiedAction((mapping.action as MappingAction) || 'BUY')
    setEditForm({
      ...emptyFormState(),
      instrumentType: mapping.instrument_type || 'EQ',
      exchange: mapping.exchange,
      quantity: String(mapping.quantity),
      productType: mapping.product_type,
      underlying: mapping.underlying || '',
      expiryType: mapping.expiry_type || '',
      optionType: mapping.option_type || 'CE',
      strikeOffset: mapping.strike_offset || 'ATM',
      strikeSelectionMode: mapping.strike_selection_mode || 'offset',
      strikeTargetValue:
        mapping.strike_target_value != null ? String(mapping.strike_target_value) : '',
      orderSide: mapping.order_side || '',
      // Signal Actions. The server normalises signal_action NULL -> 'ENTER'
      // and order_type NULL -> 'MARKET', so these always have a concrete
      // value to seed the controls with.
      signalAction: mapping.signal_action || 'ENTER',
      orderType: mapping.order_type || 'MARKET',
      limitPrice: mapping.limit_price != null ? String(mapping.limit_price) : '',
      triggerPrice: mapping.trigger_price != null ? String(mapping.trigger_price) : '',
      stopLossValue: mapping.stop_loss_value != null ? String(mapping.stop_loss_value) : '',
      stopLossType: mapping.stop_loss_type || 'percent',
      targetValue: mapping.target_value != null ? String(mapping.target_value) : '',
      targetType: mapping.target_type || 'percent',
      trailingValue: mapping.trailing_value != null ? String(mapping.trailing_value) : '',
      trailingType: mapping.trailing_type || 'percent',
      lots: mapping.lots != null ? String(mapping.lots) : '',
      legBasket: mapping.leg_basket || '',
      label: mapping.label || '',
      selectedSymbol: mapping.instrument
        ? ({ symbol: mapping.instrument, exchange: mapping.exchange } as SymbolSearchResult)
        : null,
      symbolSearch: mapping.instrument || '',
    })
    setEditDialogOpen(true)
  }

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!mappingToEdit || !strategyId) return

    if (!editForm.quantity || Number(editForm.quantity) < 1) {
      showToast.error('Quantity must be at least 1', 'strategy')
      return
    }
    if (!editForm.productType) {
      showToast.error('Please select a product type', 'strategy')
      return
    }
    if (editForm.instrumentType !== 'EQ' && (!editForm.underlying || !editForm.expiryType)) {
      showToast.error('Please select an underlying and expiry', 'strategy')
      return
    }
    if (editForm.instrumentType === 'OPT') {
      if (!editForm.optionType) {
        showToast.error('Please select an option type', 'strategy')
        return
      }
      if (editForm.strikeSelectionMode === 'offset' && !editForm.strikeOffset) {
        showToast.error('Please select a strike', 'strategy')
        return
      }
      if (editForm.strikeSelectionMode !== 'offset' && !editForm.strikeTargetValue.trim()) {
        showToast.error('Please enter a target value for strike selection', 'strategy')
        return
      }
    }

    try {
      setEditSubmitting(true)
      const response = await strategyApi.updateSymbolMapping(Number(strategyId), mappingToEdit.id, {
        symbol: isUnified
          ? editUnifiedAction === 'SELL' || editUnifiedAction === 'EXIT'
            ? 'SELL'
            : 'BUY'
          : editTrigger,
        ...(isUnified
          ? { action: editUnifiedAction, order_side: editForm.orderSide || undefined }
          : {}),
        exchange: editForm.exchange,
        quantity: Number(editForm.quantity),
        product_type: editForm.productType,
        instrument_type: editForm.instrumentType,
        ...(editForm.instrumentType === 'EQ'
          ? { instrument: editForm.selectedSymbol?.symbol || editForm.symbolSearch }
          : {
              underlying: editForm.underlying,
              expiry_type: editForm.expiryType || undefined,
              ...(editForm.instrumentType === 'OPT'
                ? {
                    option_type: editForm.optionType,
                    strike_selection_mode: editForm.strikeSelectionMode,
                    ...(editForm.strikeSelectionMode === 'offset'
                      ? { strike_offset: editForm.strikeOffset }
                      : { strike_target_value: Number(editForm.strikeTargetValue) }),
                  }
                : {}),
            }),
        ...signalActionPayload(editForm),
      })

      if (response.status === 'success') {
        showToast.success('Symbol mapping updated', 'strategy')
        setEditDialogOpen(false)
        setMappingToEdit(null)
        fetchStrategy()
      } else {
        showToast.error(response.message || 'Failed to update symbol', 'strategy')
      }
    } catch (error) {
      showToast.error(extractErrorMessage(error, 'Failed to update symbol'), 'strategy')
    } finally {
      setEditSubmitting(false)
    }
  }

  const fetchStrategy = async () => {
    if (!strategyId) return
    try {
      setLoading(true)
      const data = await strategyApi.getStrategy(Number(strategyId))
      setStrategy(data.strategy)
      setMappings(data.mappings || [])
    } catch (error) {
      showToast.error(extractErrorMessage(error, 'Failed to load strategy'), 'strategy')
    } finally {
      setLoading(false)
    }
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: one-time fetch on mount; fetchStrategy should not re-run on every render
  useEffect(() => {
    fetchStrategy()
  }, [])

  // Debounced symbol/underlying search -- scoped by which mode is active:
  // EQ searches all exchanges (unchanged from before), FUT/OPT restricts
  // to underlying-only rows (EQ/INDEX, no dated F&O contracts) since the
  // user is picking a base symbol like "NIFTY", not a specific contract.
  const runSearch = useCallback(
    async (query: string, mode: InstrumentType, exchangeFilter: string) => {
      if (query.length < 2) return [] as SymbolSearchResult[]
      if (mode === 'EQ') {
        return strategyApi.searchSymbols(query, exchangeFilter || undefined)
      }
      return strategyApi.searchUnderlyingSymbols(query, exchangeFilter || undefined)
    },
    []
  )

  useEffect(() => {
    if (form.instrumentType !== 'EQ') return
    const timer = setTimeout(async () => {
      if (form.symbolSearch.length < 2) {
        setForm((f) => ({ ...f, searchResults: [] }))
        return
      }
      try {
        setForm((f) => ({ ...f, searchLoading: true }))
        const results = await runSearch(form.symbolSearch, 'EQ', form.exchange)
        setForm((f) => ({ ...f, searchResults: results }))
      } catch (_error) {
        // ignore -- search box just stays empty
      } finally {
        setForm((f) => ({ ...f, searchLoading: false }))
      }
    }, 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.symbolSearch, form.exchange, form.instrumentType])

  useEffect(() => {
    if (form.instrumentType === 'EQ') return
    const timer = setTimeout(async () => {
      if (form.underlying.length < 2) {
        setForm((f) => ({ ...f, searchResults: [] }))
        return
      }
      try {
        setForm((f) => ({ ...f, searchLoading: true }))
        const results = await runSearch(form.underlying, form.instrumentType, form.exchange)
        setForm((f) => ({ ...f, searchResults: results }))
      } catch (_error) {
        // ignore
      } finally {
        setForm((f) => ({ ...f, searchLoading: false }))
      }
    }, 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.underlying, form.exchange, form.instrumentType])

  // Suggest Quantity as the underlying's real lot size as soon as
  // underlying+exchange are both picked for a FUT/OPT mapping -- mirrors
  // the EQ search's lot-size default (handleSymbolSelect below), which
  // otherwise only applies to the EQ flow since FUT/OPT never resolves a
  // SymbolSearchResult with a lotsize on it.
  useEffect(() => {
    if (form.instrumentType === 'EQ' || !form.underlying || !form.exchange) return
    let cancelled = false
    strategyApi
      .getUnderlyingLotsize(form.underlying, form.exchange)
      .then((lotsize) => {
        if (cancelled || !lotsize || lotsize <= 1) return
        setForm((f) => (f.quantity === '1' ? { ...f, quantity: String(lotsize) } : f))
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [form.instrumentType, form.underlying, form.exchange])

  const handleSymbolSelect = (result: SymbolSearchResult) => {
    setForm((f) => {
      const products = getProductTypes(result.exchange)
      return {
        ...f,
        selectedSymbol: result,
        symbolSearch: result.symbol,
        exchange: result.exchange,
        searchOpen: false,
        productType: products[0],
        // Default Quantity to the instrument's real lot size (1 for
        // equity, e.g. 75 for a NIFTY option/future) instead of always
        // leaving it at "1" -- for F&O, "1" silently means 1 unit rather
        // than 1 lot, which is almost never what was intended.
        quantity: result.lotsize && result.lotsize > 1 ? String(result.lotsize) : f.quantity,
      }
    })
  }

  // Mirrors option_symbol_service.py's get_option_exchange(): the
  // underlying search returns the base symbol's own equity/index
  // exchange (NSE/NSE_INDEX/BSE/BSE_INDEX), but FUT/OPT orders route
  // through the derivatives exchange, not the underlying's listing
  // exchange.
  const underlyingToFnoExchange = (exchange: string): string => {
    const ex = exchange.toUpperCase()
    if (ex === 'NSE' || ex === 'NSE_INDEX') return 'NFO'
    if (ex === 'BSE' || ex === 'BSE_INDEX') return 'BFO'
    if (ex === 'MCX' || ex === 'CDS') return ex
    return 'NFO'
  }

  const handleUnderlyingSelect = (result: SymbolSearchResult) => {
    setForm((f) => ({
      ...f,
      underlying: result.symbol,
      exchange: underlyingToFnoExchange(result.exchange),
      underlyingSearchOpen: false,
      productType: f.productType || 'NRML',
    }))
  }

  const resetForm = () => {
    setForm(emptyFormState())
  }

  /** Duplicate a rule, so a second leg is a tweak rather than a re-entry
   * of every field. Opens the edit dialog pre-filled rather than saving
   * silently -- a clone almost always needs one thing changed. */
  const handleCloneMapping = (mapping: StrategySymbolMapping) => {
    openEditDialog({ ...mapping, id: 0 } as StrategySymbolMapping)
  }

  /**
   * Apply a Quick Start preset: create every leg it defines in one go.
   *
   * The preset supplies only what it actually decides (which signal, what
   * the leg does, CE/PE, strike offset, basket). Underlying, exchange,
   * expiry, quantity and product still come from the form above, so a
   * preset never silently overrides a choice the user already made.
   *
   * Legs are created sequentially rather than in parallel: they share a
   * basket, and the backend assigns ordering per row -- firing them
   * concurrently would make the resulting order non-deterministic.
   */
  const handleApplyPreset = async (preset: SignalPreset) => {
    if (!strategyId) return

    // Defence-in-depth only: the grid is disabled and replaced with an
    // explanation whenever this is non-null, so a user should never reach
    // here in a blocked state. Kept so a future caller can't bypass it.
    if (presetBlockedReason) {
      showToast.error(presetBlockedReason, 'strategy')
      return
    }

    setApplyingPreset(true)
    let created = 0
    try {
      for (const leg of preset.legs) {
        const response = await strategyApi.addSymbolMapping(Number(strategyId), {
          symbol: leg.action === 'SELL' || leg.action === 'EXIT' ? 'SELL' : 'BUY',
          action: leg.action,
          order_side: leg.orderSide,
          exchange: form.exchange,
          quantity: Number(form.quantity) || 1,
          product_type: form.productType,
          instrument_type: 'OPT',
          underlying: form.underlying,
          expiry_type: form.expiryType || undefined,
          option_type: leg.optionType,
          strike_selection_mode: 'offset',
          strike_offset: leg.strikeOffset,
          signal_action: leg.signalAction,
          leg_basket: leg.legBasket,
          label: leg.label,
        })
        if (response.status === 'success') {
          created += 1
        } else {
          showToast.error(response.message || `Failed to add "${leg.label}"`, 'strategy')
          break
        }
      }

      if (created > 0) {
        showToast.success(
          `${preset.name} added — ${created} leg${created > 1 ? 's' : ''} created`,
          'strategy'
        )
        fetchStrategy()
      }
    } catch (error) {
      // A leg failing validation (e.g. no broker API key, or that leg's
      // strike/expiry can't be resolved) makes the backend 400, which axios
      // throws rather than resolves -- so this is the actual path most
      // preset failures take, not the `response.status !== 'success'`
      // branch above. Show the real reason instead of a generic string.
      showToast.error(extractErrorMessage(error, 'Failed to apply preset'), 'strategy')
      if (created > 0) fetchStrategy()
    } finally {
      setApplyingPreset(false)
    }
  }

  const handleSingleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (form.instrumentType === 'EQ') {
      if (!form.selectedSymbol) {
        showToast.error('Please select a symbol', 'strategy')
        return
      }
      if (!form.exchange) {
        showToast.error('Please select an exchange', 'strategy')
        return
      }
    } else {
      if (!form.underlying) {
        showToast.error('Please select an underlying', 'strategy')
        return
      }
      if (!form.exchange) {
        showToast.error('Please select an exchange', 'strategy')
        return
      }
      if (!form.expiryType) {
        showToast.error('Please select an expiry', 'strategy')
        return
      }
      if (form.instrumentType === 'OPT') {
        if (!form.optionType) {
          showToast.error('Please select an option type', 'strategy')
          return
        }
        if (form.strikeSelectionMode === 'offset' && !form.strikeOffset) {
          showToast.error('Please select a strike', 'strategy')
          return
        }
        if (form.strikeSelectionMode !== 'offset' && !form.strikeTargetValue.trim()) {
          showToast.error('Please enter a target value for strike selection', 'strategy')
          return
        }
      }
    }
    if (!form.quantity || Number(form.quantity) < 1) {
      showToast.error('Quantity must be at least 1', 'strategy')
      return
    }
    if (!form.productType) {
      showToast.error('Please select a product type', 'strategy')
      return
    }

    try {
      setSubmitting(true)
      const response = await strategyApi.addSymbolMapping(Number(strategyId), {
        symbol: isUnified
          ? unifiedAction === 'SELL' || unifiedAction === 'EXIT'
            ? 'SELL'
            : 'BUY'
          : triggerSymbol,
        ...(isUnified ? { action: unifiedAction, order_side: form.orderSide || undefined } : {}),
        exchange: form.exchange,
        quantity: Number(form.quantity),
        product_type: form.productType,
        instrument_type: form.instrumentType,
        ...(form.instrumentType === 'EQ'
          ? { instrument: form.selectedSymbol?.symbol }
          : {
              underlying: form.underlying,
              expiry_type: form.expiryType || undefined,
              ...(form.instrumentType === 'OPT'
                ? {
                    option_type: form.optionType,
                    strike_selection_mode: form.strikeSelectionMode,
                    ...(form.strikeSelectionMode === 'offset'
                      ? { strike_offset: form.strikeOffset }
                      : { strike_target_value: Number(form.strikeTargetValue) }),
                  }
                : {}),
            }),
        ...signalActionPayload(form),
      })

      if (response.status === 'success') {
        showToast.success('Symbol added successfully', 'strategy')
        resetForm()
        fetchStrategy()
      } else {
        showToast.error(response.message || 'Failed to add symbol', 'strategy')
      }
    } catch (error) {
      showToast.error(extractErrorMessage(error, 'Failed to add symbol'), 'strategy')
    } finally {
      setSubmitting(false)
    }
  }

  const handleBulkSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!csvData.trim()) {
      showToast.error('Please enter CSV data', 'strategy')
      return
    }

    try {
      setSubmitting(true)
      const response = await strategyApi.addBulkSymbols(Number(strategyId), csvData)

      if (response.status === 'success') {
        const { added = 0, failed = 0 } = response.data || {}
        showToast.success(
          `Added ${added} symbols${failed > 0 ? `, ${failed} failed` : ''}`,
          'strategy'
        )
        setCsvData('')
        fetchStrategy()
      } else {
        showToast.error(response.message || 'Failed to add symbols', 'strategy')
      }
    } catch (error) {
      showToast.error(extractErrorMessage(error, 'Failed to add symbols'), 'strategy')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDeleteMapping = async () => {
    if (mappingToDelete === null || !strategyId) return

    try {
      const response = await strategyApi.deleteSymbolMapping(Number(strategyId), mappingToDelete)
      if (response.status === 'success') {
        setMappings(mappings.filter((m) => m.id !== mappingToDelete))
        showToast.success('Symbol removed', 'strategy')
      } else {
        showToast.error(response.message || 'Failed to remove symbol', 'strategy')
      }
    } catch (error) {
      showToast.error(extractErrorMessage(error, 'Failed to remove symbol'), 'strategy')
    } finally {
      setDeleteDialogOpen(false)
      setMappingToDelete(null)
    }
  }

  /**
   * The rule currently being typed, shaped like a saved mapping so the
   * Execution Flow can draw it before it is saved. This is what turns the
   * form from "fill 18 fields and hope" into "watch the automation build".
   */
  /** Presets build CE/PE leg shapes, so they need Options plus everything a
   * contract needs to resolve. Stated up front and used to DISABLE the
   * grid, rather than erroring after the user clicks. */
  const presetBlockedReason = useMemo(() => {
    if (form.instrumentType !== 'OPT') return 'Quick-start setups are for Options'
    if (!form.underlying) return 'Choose an underlying to unlock these setups'
    if (!form.expiryType) return 'Choose an expiry to unlock these setups'
    if (!form.productType) return 'Choose a product type to unlock these setups'
    return null
  }, [form.instrumentType, form.underlying, form.expiryType, form.productType])

  const setupReady = presetBlockedReason === null

  const draftMapping = useMemo((): Partial<StrategySymbolMapping> | null => {
    const hasInstrument =
      form.instrumentType === 'EQ' ? Boolean(form.selectedSymbol?.symbol) : Boolean(form.underlying)
    if (!hasInstrument) return null
    return {
      action: (isUnified ? unifiedAction : triggerSymbol) as MappingAction,
      symbol: form.selectedSymbol?.symbol || form.underlying,
      instrument: form.selectedSymbol?.symbol,
      instrument_type: form.instrumentType,
      underlying: form.underlying,
      exchange: form.exchange,
      option_type: form.optionType,
      strike_offset: form.strikeOffset,
      strike_selection_mode: form.strikeSelectionMode,
      quantity: Number(form.quantity) || 1,
      product_type: form.productType as StrategySymbolMapping['product_type'],
      order_side: form.orderSide || null,
      signal_action: form.signalAction,
      order_type: form.orderType,
      lots: form.lots ? Number(form.lots) : null,
      leg_basket: form.legBasket || null,
      label: form.label || null,
      stop_loss_value: form.stopLossValue ? Number(form.stopLossValue) : null,
      stop_loss_type: form.stopLossType,
      target_value: form.targetValue ? Number(form.targetValue) : null,
      target_type: form.targetType,
      trailing_value: form.trailingValue ? Number(form.trailingValue) : null,
      trailing_type: form.trailingType,
    }
  }, [form, isUnified, unifiedAction, triggerSymbol])

  const handleToggleMapping = async (mapping: StrategySymbolMapping) => {
    if (!strategyId) return
    try {
      setTogglingId(mapping.id)
      const response = await strategyApi.toggleSymbolMapping(Number(strategyId), mapping.id)
      if (response.status === 'success') {
        setMappings((prev) =>
          prev.map((m) =>
            m.id === mapping.id ? { ...m, is_active: response.data?.is_active ?? !m.is_active } : m
          )
        )
        showToast.success(response.data?.is_active ? 'Symbol resumed' : 'Symbol paused', 'strategy')
      } else {
        showToast.error(response.message || 'Failed to toggle symbol', 'strategy')
      }
    } catch (error) {
      showToast.error(extractErrorMessage(error, 'Failed to toggle symbol'), 'strategy')
    } finally {
      setTogglingId(null)
    }
  }

  const productTypes = form.exchange
    ? form.instrumentType === 'OPT'
      ? ['MIS', 'NRML']
      : getProductTypes(form.exchange)
    : []

  if (loading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-64" />
        <Skeleton className="h-48" />
      </div>
    )
  }

  if (!strategy) {
    return null
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Back Button */}
      <Button variant="ghost" asChild>
        <Link to={`/strategy/${strategyId}`}>
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to {strategy.name}
        </Link>
      </Button>

      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Configure Symbols</h1>
          <p className="text-muted-foreground">Add symbols to {strategy.name}</p>
        </div>
        <Button variant="outline" onClick={fetchStrategy}>
          <RefreshCw className="h-4 w-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* Signal flow overview. Replaces the old "Execution Mode" dropdown:
      the engine is now derived from what the strategy actually contains
      (see services/signal_engine.py::_resolve_execution_model), so the
      trader configures behaviour instead of picking an engine. */}
      <ExecutionFlow mappings={mappings} draft={draftMapping} isStateful={isStateful} />

      {isStateful && <LegGroupsPanel strategyId={Number(strategyId)} />}

      {/* Quick Start presets. The manual form below exposes ~18 controls,
      which is the right amount of power for an expert and far too many
      decisions for a first-time user with no guided path. A preset fills
      every field it implies in one click. Options-only: presets describe
      CE/PE leg shapes, which have no meaning for an equity mapping. */}
      {!isStateful && (
        <>
          <SetupStep
            instrumentType={form.instrumentType}
            onInstrumentType={(value, defaultExchange) => {
              setForm((f) => ({
                ...emptyFormState(),
                instrumentType: value,
                exchange: defaultExchange ?? '',
                quantity: f.quantity,
              }))
              setSetupConfirmed(false)
            }}
            underlying={
              form.instrumentType === 'EQ' ? form.selectedSymbol?.symbol || '' : form.underlying
            }
            underlyingControl={
              /* The REAL search control, not a link to it. An earlier
              version rendered a button that scrolled down to the form,
              which meant picking an underlying threw the user into a
              different section mid-task. */
              form.instrumentType === 'EQ' ? (
                <UnderlyingSearch
                  value={form.symbolSearch}
                  onValueChange={(value) =>
                    setForm((f) => ({ ...f, symbolSearch: value, selectedSymbol: null }))
                  }
                  open={form.searchOpen}
                  onOpenChange={(open) =>
                    setForm((f) => ({
                      ...f,
                      searchOpen: open,
                      searchResults: open ? [] : f.searchResults,
                    }))
                  }
                  results={form.searchResults}
                  loading={form.searchLoading}
                  onSelect={handleSymbolSelect}
                  placeholder="Search symbol..."
                  searchPlaceholder="Search symbol (e.g. SBIN, INFY)..."
                />
              ) : (
                <UnderlyingSearch
                  value={form.underlying}
                  onValueChange={(value) => setForm((f) => ({ ...f, underlying: value }))}
                  open={form.underlyingSearchOpen}
                  onOpenChange={(open) =>
                    setForm((f) => ({
                      ...f,
                      underlyingSearchOpen: open,
                      searchResults: open ? [] : f.searchResults,
                    }))
                  }
                  results={form.searchResults}
                  loading={form.searchLoading}
                  onSelect={handleUnderlyingSelect}
                />
              )
            }
            exchange={form.exchange}
            exchanges={form.instrumentType === 'EQ' ? EQUITY_EXCHANGES : FNO_EXCHANGES}
            onExchange={(value) => setForm((f) => ({ ...f, exchange: value }))}
            expiryType={form.expiryType}
            onExpiryType={(value) => setForm((f) => ({ ...f, expiryType: value }))}
            ready={setupReady}
            confirmed={setupConfirmed}
            onConfirm={() => setSetupConfirmed(true)}
            onEdit={() => setSetupConfirmed(false)}
          />

          {setupConfirmed && (
            <SignalPresets
              onApply={handleApplyPreset}
              disabled={applyingPreset || submitting}
              blockedReason={presetBlockedReason}
              contextLabel={
                setupReady ? `${form.underlying} · ${expiryLabel(form.expiryType)}` : undefined
              }
            />
          )}
        </>
      )}

      {!isStateful && (
        <>
          {/* Add Symbols -- waits for Step 1 to be confirmed, same as Quick
          Start above, so this isn't a second "what are you trading" prompt
          sitting open at the same time as the first. */}
          {setupConfirmed && (
            <Card id="add-symbols-card">
              <CardHeader>
                <CardTitle>Add Symbols</CardTitle>
                <CardDescription>Add individual symbols or bulk import from CSV</CardDescription>
              </CardHeader>
              <CardContent>
                <Tabs defaultValue="single">
                  <TabsList className="grid w-full grid-cols-2">
                    <TabsTrigger value="single">
                      <Plus className="h-4 w-4 mr-2" />
                      Single Symbol
                    </TabsTrigger>
                    <TabsTrigger value="bulk">
                      <Upload className="h-4 w-4 mr-2" />
                      Bulk Import
                    </TabsTrigger>
                  </TabsList>

                  {/* Single Symbol Tab */}
                  <TabsContent value="single">
                    <form onSubmit={handleSingleSubmit} className="space-y-4 mt-4">
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
                        {/* Trigger Signal — which incoming webhook signal this
                      mapping responds to, NOT a manual trade direction the
                      user is forcing. A BUY signal only fires mappings
                      with Trigger=BUY; a SELL signal only fires
                      Trigger=SELL mappings. This is how one connection can
                      trade different instruments (or the same instrument
                      differently) depending on which signal arrives. */}
                        {isUnified ? (
                          <>
                            <div className="space-y-2">
                              <Label>React to Signal</Label>
                              <Select
                                value={unifiedAction}
                                onValueChange={(value: MappingAction) => setUnifiedAction(value)}
                              >
                                <SelectTrigger>
                                  <SelectValue placeholder="React to Signal" />
                                </SelectTrigger>
                                <SelectContent>
                                  {UNIFIED_ACTIONS.map((a) => (
                                    <SelectItem key={a.value} value={a.value}>
                                      {a.label}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                              <p className="text-xs text-muted-foreground">
                                Which incoming signal triggers this instrument.
                              </p>
                            </div>
                            <div className="space-y-2">
                              <Label>On Signal, Do</Label>
                              <Select
                                value={form.signalAction}
                                onValueChange={(value: SignalAction) =>
                                  setForm((f) => ({ ...f, signalAction: value }))
                                }
                              >
                                <SelectTrigger aria-label="On signal, do">
                                  <SelectValue placeholder="On Signal, Do" />
                                </SelectTrigger>
                                <SelectContent>
                                  {SIGNAL_ACTIONS.map((a) => (
                                    <SelectItem key={a.value} value={a.value}>
                                      {a.label}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                              <p className="text-xs text-muted-foreground">
                                {
                                  SIGNAL_ACTIONS.find((a) => a.value === form.signalAction)
                                    ?.description
                                }
                              </p>
                            </div>
                          </>
                        ) : (
                          <div className="space-y-2">
                            <Label>React to Signal</Label>
                            <Select
                              value={triggerSymbol}
                              onValueChange={(value: 'BUY' | 'SELL' | 'BOTH') =>
                                setTriggerSymbol(value)
                              }
                            >
                              <SelectTrigger>
                                <SelectValue placeholder="React to Signal" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="BOTH">BOTH</SelectItem>
                                <SelectItem value="BUY">BUY</SelectItem>
                                <SelectItem value="SELL">SELL</SelectItem>
                              </SelectContent>
                            </Select>
                            <p className="text-xs text-muted-foreground">
                              Which incoming signal triggers this instrument. BOTH reacts to either
                              BUY or SELL; selecting BUY or SELL makes it ignore the other signal.
                            </p>
                          </div>
                        )}

                        {/* Symbol/Underlying + Exchange (+ Expiry for
                        derivatives) live in the setup card above -- one
                        control per value, chosen before anything that
                        depends on it. Repeating them here gave two controls
                        for one value. */}

                        {form.instrumentType === 'OPT' && (
                          <>
                            {/* Option Type -- CE/PE two-button group */}
                            <div className="space-y-2">
                              <Label>Option Type</Label>
                              <div className="flex gap-2">
                                <Button
                                  type="button"
                                  variant={form.optionType === 'CE' ? 'default' : 'outline'}
                                  className="flex-1"
                                  onClick={() => setForm((f) => ({ ...f, optionType: 'CE' }))}
                                >
                                  CE
                                </Button>
                                <Button
                                  type="button"
                                  variant={form.optionType === 'PE' ? 'default' : 'outline'}
                                  className="flex-1"
                                  onClick={() => setForm((f) => ({ ...f, optionType: 'PE' }))}
                                >
                                  PE
                                </Button>
                              </div>
                            </div>

                            {/* Strike Selection */}
                            <StrikeSelector
                              value={{
                                mode: form.strikeSelectionMode,
                                offsetValue: form.strikeOffset,
                                targetValue: form.strikeTargetValue,
                              }}
                              onChange={(next) =>
                                setForm((f) => ({
                                  ...f,
                                  strikeSelectionMode: next.mode,
                                  strikeOffset: next.offsetValue,
                                  strikeTargetValue: next.targetValue,
                                }))
                              }
                            />
                          </>
                        )}

                        {/* Quantity */}
                        <div className="space-y-2">
                          <Label>Quantity</Label>
                          <Input
                            type="number"
                            min="1"
                            value={form.quantity}
                            onChange={(e) => setForm((f) => ({ ...f, quantity: e.target.value }))}
                            placeholder="Enter quantity"
                          />
                          {form.instrumentType === 'EQ' &&
                            form.selectedSymbol &&
                            form.selectedSymbol.lotsize > 1 && (
                              <p className="text-xs text-muted-foreground">
                                Lot size: {form.selectedSymbol.lotsize}. Quantity must be a multiple
                                of the lot size.
                              </p>
                            )}
                        </div>

                        {/* Product Type */}
                        <div className="space-y-2">
                          <Label>Product Type</Label>
                          <Select
                            value={form.productType}
                            onValueChange={(value) =>
                              setForm((f) => ({ ...f, productType: value }))
                            }
                            disabled={!form.exchange}
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

                      {/* Advanced: what the signal DOES, how the order is
                    placed, protective orders, lot sizing and multi-leg
                    baskets. Collapsed by default so the simple "add a
                    symbol" flow is unchanged for users who don't need it. */}
                      <SignalActionFields
                        form={form}
                        setForm={setForm}
                        isOption={form.instrumentType === 'OPT'}
                        isDerivative={form.instrumentType !== 'EQ'}
                        hideSignalAction={isUnified}
                      />

                      <Button type="submit" disabled={submitting}>
                        {submitting ? 'Adding...' : 'Add Symbol'}
                      </Button>
                    </form>
                  </TabsContent>

                  {/* Bulk Import Tab */}
                  <TabsContent value="bulk">
                    <form onSubmit={handleBulkSubmit} className="space-y-4 mt-4">
                      <div className="space-y-2">
                        <Label>CSV Data</Label>
                        <Textarea
                          placeholder="Symbol,Exchange,Quantity,Product&#10;RELIANCE,NSE,100,CNC&#10;TATAMOTORS,NSE,50,MIS"
                          value={csvData}
                          onChange={(e) => setCsvData(e.target.value)}
                          rows={6}
                          maxLength={102400}
                          className="font-mono text-sm"
                        />
                        <p className="text-xs text-muted-foreground">
                          Format: Symbol,Exchange,Quantity,Product (one per line, no header row).
                          Max 100KB. Equity/Index only -- use the Single Symbol tab above for
                          Futures/Options.
                        </p>
                      </div>

                      <div className="flex items-center gap-4">
                        <Button type="submit" disabled={submitting}>
                          {submitting ? 'Importing...' : 'Import Symbols'}
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => setCsvData('')}
                          disabled={!csvData}
                        >
                          Clear
                        </Button>
                      </div>
                    </form>
                  </TabsContent>
                </Tabs>
              </CardContent>
            </Card>
          )}

          <TestWebhookPanel strategyId={Number(strategyId)} />

          {/* Current rules, as cards.

          Replaces a 9-column table where every cell carried identical
          visual weight and the actual behaviour had to be reconstructed by
          reading across a row. Each card leads with the signal and verb in
          colour and embeds the same execution chain drawn at the top of the
          page, so a rule reads identically everywhere it appears. */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <FileText className="h-4 w-4" />
                Current Rules
              </CardTitle>
              <CardDescription>
                {mappings.length} rule{mappings.length !== 1 ? 's' : ''} configured
              </CardDescription>
            </CardHeader>
            <CardContent>
              {mappings.length === 0 ? (
                <div className="rounded-lg border border-dashed py-10 text-center">
                  <p className="text-sm font-medium">Nothing configured yet</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Pick a Quick Start above, or build a rule manually.
                  </p>
                </div>
              ) : (
                <div className="space-y-2">
                  {mappings.map((mapping) => (
                    <MappingCard
                      key={mapping.id}
                      mapping={mapping}
                      toggling={togglingId === mapping.id}
                      onEdit={openEditDialog}
                      onClone={handleCloneMapping}
                      onToggle={handleToggleMapping}
                      onDelete={(id) => {
                        setMappingToDelete(id)
                        setDeleteDialogOpen(true)
                      }}
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Edit Dialog */}
          <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
            {/* Wider than the default sm:max-w-lg: this form carries ~12
            fields plus the whole Signal Action / Risk block, and at the
            narrow default every row wrapped. The form is the flex column so
            DialogBody can scroll between a fixed header and footer. */}
            <DialogContent className="sm:max-w-2xl">
              <DialogHeader>
                <DialogTitle>Edit Rule</DialogTitle>
                <DialogDescription>
                  {mappingToEdit ? instrumentSummary(mappingToEdit) : ''}
                </DialogDescription>
              </DialogHeader>
              <form onSubmit={handleEditSubmit} className="flex min-h-0 flex-1 flex-col gap-4">
                <DialogBody className="space-y-4 py-1">
                  <div className="space-y-2">
                    <Label>Instrument Type</Label>
                    <Select
                      value={editForm.instrumentType}
                      onValueChange={(value: InstrumentType) =>
                        setEditForm((f) => ({ ...f, instrumentType: value }))
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
                  {isUnified ? (
                    <>
                      <div className="space-y-2">
                        <Label>React to Signal</Label>
                        <Select
                          value={editUnifiedAction}
                          onValueChange={(value: MappingAction) => setEditUnifiedAction(value)}
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {UNIFIED_ACTIONS.map((a) => (
                              <SelectItem key={a.value} value={a.value}>
                                {a.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-2">
                        <Label>On Signal, Do</Label>
                        <Select
                          value={editForm.signalAction}
                          onValueChange={(value: SignalAction) =>
                            setEditForm((f) => ({ ...f, signalAction: value }))
                          }
                        >
                          <SelectTrigger aria-label="On signal, do">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {SIGNAL_ACTIONS.map((a) => (
                              <SelectItem key={a.value} value={a.value}>
                                {a.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <p className="text-[11px] leading-tight text-muted-foreground">
                          {
                            SIGNAL_ACTIONS.find((a) => a.value === editForm.signalAction)
                              ?.description
                          }
                        </p>
                      </div>
                    </>
                  ) : (
                    <div className="space-y-2">
                      <Label>React to Signal</Label>
                      <Select
                        value={editTrigger}
                        onValueChange={(value: 'BUY' | 'SELL' | 'BOTH') => setEditTrigger(value)}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="BOTH">BOTH</SelectItem>
                          <SelectItem value="BUY">BUY</SelectItem>
                          <SelectItem value="SELL">SELL</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  )}

                  {editForm.instrumentType === 'EQ' ? (
                    <div className="space-y-2">
                      <Label>Broker Instrument</Label>
                      <Input
                        value={editForm.symbolSearch}
                        onChange={(e) =>
                          setEditForm((f) => ({
                            ...f,
                            symbolSearch: e.target.value,
                            selectedSymbol: {
                              ...f.selectedSymbol,
                              symbol: e.target.value,
                            } as SymbolSearchResult,
                          }))
                        }
                        placeholder="e.g. RELIANCE"
                      />
                    </div>
                  ) : (
                    <>
                      <div className="space-y-2">
                        <Label>Underlying</Label>
                        <Input
                          value={editForm.underlying}
                          onChange={(e) =>
                            setEditForm((f) => ({ ...f, underlying: e.target.value.toUpperCase() }))
                          }
                          placeholder="e.g. NIFTY"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Expiry</Label>
                        <Select
                          value={editForm.expiryType}
                          onValueChange={(value: ExpiryType) =>
                            setEditForm((f) => ({ ...f, expiryType: value }))
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
                      {editForm.instrumentType === 'OPT' && (
                        <>
                          <div className="space-y-2">
                            <Label>Option Type</Label>
                            <div className="flex gap-2">
                              <Button
                                type="button"
                                variant={editForm.optionType === 'CE' ? 'default' : 'outline'}
                                className="flex-1"
                                onClick={() => setEditForm((f) => ({ ...f, optionType: 'CE' }))}
                              >
                                CE
                              </Button>
                              <Button
                                type="button"
                                variant={editForm.optionType === 'PE' ? 'default' : 'outline'}
                                className="flex-1"
                                onClick={() => setEditForm((f) => ({ ...f, optionType: 'PE' }))}
                              >
                                PE
                              </Button>
                            </div>
                          </div>
                          <StrikeSelector
                            value={{
                              mode: editForm.strikeSelectionMode,
                              offsetValue: editForm.strikeOffset,
                              targetValue: editForm.strikeTargetValue,
                            }}
                            onChange={(next) =>
                              setEditForm((f) => ({
                                ...f,
                                strikeSelectionMode: next.mode,
                                strikeOffset: next.offsetValue,
                                strikeTargetValue: next.targetValue,
                              }))
                            }
                          />
                        </>
                      )}
                    </>
                  )}

                  <div className="space-y-2">
                    <Label>Exchange</Label>
                    <Select
                      value={editForm.exchange}
                      onValueChange={(value) =>
                        setEditForm((f) => ({ ...f, exchange: value, productType: '' }))
                      }
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select exchange" />
                      </SelectTrigger>
                      <SelectContent>
                        {(editForm.instrumentType === 'EQ' ? EXCHANGES : FNO_EXCHANGES).map(
                          (ex) => (
                            <SelectItem key={ex} value={ex}>
                              {ex}
                            </SelectItem>
                          )
                        )}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Quantity</Label>
                    <Input
                      type="number"
                      min="1"
                      value={editForm.quantity}
                      onChange={(e) => setEditForm((f) => ({ ...f, quantity: e.target.value }))}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Product Type</Label>
                    <Select
                      value={editForm.productType}
                      onValueChange={(value) => setEditForm((f) => ({ ...f, productType: value }))}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select product" />
                      </SelectTrigger>
                      <SelectContent>
                        {(editForm.exchange
                          ? editForm.instrumentType === 'OPT'
                            ? ['MIS', 'NRML']
                            : getProductTypes(editForm.exchange)
                          : []
                        ).map((pt) => (
                          <SelectItem key={pt} value={pt}>
                            {pt}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <SignalActionFields
                    form={editForm}
                    setForm={setEditForm}
                    isOption={editForm.instrumentType === 'OPT'}
                    isDerivative={editForm.instrumentType !== 'EQ'}
                    hideSignalAction={isUnified}
                  />
                </DialogBody>

                <DialogFooter>
                  <Button type="button" variant="outline" onClick={() => setEditDialogOpen(false)}>
                    Cancel
                  </Button>
                  <Button type="submit" disabled={editSubmitting}>
                    {editSubmitting ? 'Saving...' : 'Save Changes'}
                  </Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>

          {/* Delete Confirmation Dialog */}
          <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Remove Symbol</DialogTitle>
                <DialogDescription>
                  Are you sure you want to remove this symbol from the strategy? This action cannot
                  be undone.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
                  Cancel
                </Button>
                <Button variant="destructive" onClick={handleDeleteMapping}>
                  Remove Symbol
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </>
      )}
    </div>
  )
}
