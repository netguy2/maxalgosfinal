import {
  Activity,
  AlertTriangle,
  BarChart3,
  Briefcase,
  Layers,
  LineChart,
  Loader2,
  Sparkles,
  TrendingUp,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { apiClient } from '@/api/client'
import { oiProfileApi } from '@/api/oi-profile'
import { optionChainApi } from '@/api/option-chain'
import { type PortfolioEntry, strategyPortfolioApi, type Watchlist } from '@/api/strategy-portfolio'
import { tradingApi } from '@/api/trading'
import { DocsLink } from '@/components/DocsLink'
import { EditLegDialog } from '@/components/strategy-builder/EditLegDialog'
import { EquityTemplateGrid } from '@/components/strategy-builder/EquityTemplateGrid'
import { GreeksTab, type LegGreeks } from '@/components/strategy-builder/GreeksTab'
import {
  type EquityOrderType,
  type LegDraft,
  type LegDraftSide,
  ManualLegBuilder,
} from '@/components/strategy-builder/ManualLegBuilder'
import MultiStrikeOITab from '@/components/strategy-builder/MultiStrikeOITab'
import { PayoffChart } from '@/components/strategy-builder/PayoffChart'
import { PnLTab } from '@/components/strategy-builder/PnLTab'
import { PositionsPanel } from '@/components/strategy-builder/PositionsPanel'
import { SaveStrategyDialog } from '@/components/strategy-builder/SaveStrategyDialog'
import { Simulators } from '@/components/strategy-builder/Simulators'
import StrategyChartTab from '@/components/strategy-builder/StrategyChartTab'
import { SymbolHeader } from '@/components/strategy-builder/SymbolHeader'
import {
  type ResolvedTemplateLeg,
  TemplateDialog,
} from '@/components/strategy-builder/TemplateDialog'
import { TemplateGrid } from '@/components/strategy-builder/TemplateGrid'
import { TradePreview } from '@/components/strategy-builder/TradePreview'
import { ExecuteBasketDialog } from '@/components/trading/ExecuteBasketDialog'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useMarketData } from '@/hooks/useMarketData'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'
import type { EquityTemplate } from '@/lib/equityTemplates'
import { CATALOG } from '@/lib/marketplace-catalog'
import {
  buildFutureSymbol,
  buildOptionSymbol,
  computePayoff,
  daysToExpiry,
  daysToYears,
  nearestLegDays,
  netCredit,
  probabilityOfProfit,
  type StrategyLeg,
  totalPnlAt,
  totalPremium,
} from '@/lib/strategyMath'
import type { Direction, StrategyTemplate } from '@/lib/strategyTemplates'
import { STRATEGY_TEMPLATES } from '@/lib/strategyTemplates'
import { useAuthStore } from '@/stores/authStore'
import type { OptionChainResponse } from '@/types/option-chain'
import { showToast } from '@/utils/toast'

// Convert DD-MMM-YYYY (API-returned expiry) to DDMMMYY (Max Algos symbol format).
function convertExpiryForSymbol(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
}

function optionExchangeFor(exchange: string): string {
  if (exchange === 'NFO' || exchange === 'NSE_INDEX') return 'NFO'
  if (exchange === 'BFO' || exchange === 'BSE_INDEX') return 'BFO'
  return exchange
}

function underlyingExchangeFor(exchange: string, symbol: string): string {
  const INDEXES_NSE = new Set(['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50'])
  const INDEXES_BSE = new Set(['SENSEX', 'BANKEX', 'SENSEX50'])
  if (INDEXES_NSE.has(symbol)) return 'NSE_INDEX'
  if (INDEXES_BSE.has(symbol)) return 'BSE_INDEX'
  return exchange
}

function uid(): string {
  return Math.random().toString(36).slice(2, 10)
}

function nearestStrike(target: number, strikes: number[]): number | null {
  if (strikes.length === 0) return null
  let best = strikes[0]
  let bestDist = Math.abs(strikes[0] - target)
  for (const s of strikes) {
    const d = Math.abs(s - target)
    if (d < bestDist) {
      bestDist = d
      best = s
    }
  }
  return best
}

/**
 * Serialize broker-backed API calls this page issues, across a small fixed
 * number of independent lanes.
 *
 * The Strategy Builder fires roughly five requests on mount (two `/expiry`
 * calls, `/optionchain`, `/syntheticfuture`, and the ATM `/optiongreeks`
 * seed) plus more on leg edits. The backend's shared HTTP/2 httpx client
 * occasionally races on stream reads when ~3+ requests multiplex
 * simultaneously, surfacing as ``[Errno 35] Resource temporarily
 * unavailable``.
 *
 * This used to be ONE module-level promise chain (strict 1-at-a-time),
 * which is safely below the ~3-request race threshold but paid for that
 * margin with real wall-clock time on every symbol switch: 5 calls at
 * ~150-250ms broker latency each, serialized end to end, made a cold
 * switch take 1.5-2+ seconds even though most of those calls don't
 * actually depend on each other -- only /optionchain depends on the
 * expiries resolving first; /syntheticfuture and the ATM /optiongreeks
 * seed are independent of it and of each other.
 *
 * LANE_COUNT independent chains (still the exact same proven
 * one-promise-per-lane pattern, just N of them) keeps a full lane of
 * margin under the documented "~3+" race point while letting genuinely
 * independent calls overlap -- which is what actually cuts the visible
 * "select a symbol -> chain appears" latency, without touching the
 * backend constraint this exists to work around. Callers are assigned a
 * lane round-robin; which lane a given call lands on doesn't matter since
 * every lane obeys the same global rate floor below.
 */
const LANE_COUNT = 2
const callChains: Promise<unknown>[] = Array.from({ length: LANE_COUNT }, () => Promise.resolve())
let nextLane = 0

/**
 * Minimum gap between two calls STARTING, enforced globally across all
 * lanes (not per-lane) -- this bounds total request RATE regardless of how
 * many lanes exist.
 *
 * Serializing alone does NOT bound request RATE — a render->fetch loop just
 * queues calls back-to-back and still saturates the server. That is exactly
 * what happened when the ATM-IV effect depended on `chainData`: one
 * /optiongreeks per WS tick, thousands of 429s, and (on single-worker
 * gunicorn) a starved healthcheck that made nginx return 504 for every
 * other route.
 *
 * The dependency bug is fixed at its source below, but this floor is
 * defence-in-depth: any FUTURE loop on this page degrades to a bounded
 * rate instead of taking the instance down. 120ms is well under the
 * latency of the broker fetches these calls wrap (~150-250ms), so correct
 * code rarely actually waits on it.
 */
const MIN_CALL_INTERVAL_MS = 120
let lastCallStartedAt = 0

function queuedFetch<T>(fn: () => Promise<T>): Promise<T> {
  const throttled = async (): Promise<T> => {
    const sinceLast = Date.now() - lastCallStartedAt
    if (sinceLast < MIN_CALL_INTERVAL_MS) {
      await new Promise((resolve) => setTimeout(resolve, MIN_CALL_INTERVAL_MS - sinceLast))
    }
    lastCallStartedAt = Date.now()
    return fn()
  }
  const lane = nextLane
  nextLane = (nextLane + 1) % LANE_COUNT
  const next = callChains[lane].then(throttled, throttled)
  // Swallow errors on this lane's chain so one failure doesn't break the
  // next caller on the SAME lane — each caller still sees its own
  // rejection via the returned promise.
  callChains[lane] = next.catch(() => undefined)
  return next
}

export default function StrategyBuilder() {
  const { apiKey } = useAuthStore()
  const {
    toolsFnoExchanges: fnoExchanges,
    defaultToolsFnoExchange: defaultFnoExchange,
    defaultUnderlyings,
    tradingExchanges,
  } = useSupportedExchanges()
  // Equity trades the cash segment only — filter the broker's full trading
  // exchange list down to NSE/BSE (excludes CDS/MCX/CRYPTO/etc., which
  // tradingExchanges otherwise includes).
  const equityExchanges = useMemo(
    () => tradingExchanges.filter((e) => e.value === 'NSE' || e.value === 'BSE'),
    [tradingExchanges]
  )
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [assetClass, setAssetClass] = useState('Options')

  const [selectedExchange, setSelectedExchange] = useState(defaultFnoExchange)
  const [underlyings, setUnderlyings] = useState<string[]>(
    defaultUnderlyings[defaultFnoExchange] || []
  )
  const [selectedUnderlying, setSelectedUnderlying] = useState(
    defaultUnderlyings[defaultFnoExchange]?.[0] || ''
  )
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [expiries, setExpiries] = useState<string[]>([])
  const [futureExpiries, setFutureExpiries] = useState<string[]>([])
  const [selectedExpiry, setSelectedExpiry] = useState('')

  const [chainData, setChainData] = useState<OptionChainResponse | null>(null)
  const [atmIv, setAtmIv] = useState<number | null>(null)
  const [futuresPrice, setFuturesPrice] = useState<number | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isExpiriesLoading, setIsExpiriesLoading] = useState(false)
  const [legs, setLegs] = useState<StrategyLeg[]>([])
  const [direction, setDirection] = useState<Direction>('BULLISH')

  const [activeTemplate, setActiveTemplate] = useState<StrategyTemplate | null>(null)
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false)
  const [equityTemplatePrefill, setEquityTemplatePrefill] = useState<{
    side: LegDraftSide
    orderType: EquityOrderType
    suggestedSlPct?: number
    suggestedTargetPct?: number
  } | null>(null)
  const handleEquityTemplatePick = useCallback((tpl: EquityTemplate) => {
    // New object reference each pick so ManualLegBuilder's effect re-fires
    // even if the same template is clicked twice in a row.
    setEquityTemplatePrefill({
      side: tpl.side,
      orderType: tpl.defaultOrderType,
      suggestedSlPct: tpl.suggestedSlPct,
      suggestedTargetPct: tpl.suggestedTargetPct,
    })
    showToast.success(`Applied template: ${tpl.name}`)
  }, [])

  const [spotShiftPct, setSpotShiftPct] = useState(0)
  const [ivShiftPct, setIvShiftPct] = useState(0)
  const [daysElapsed, setDaysElapsed] = useState(0)

  const [greeksByLeg, setGreeksByLeg] = useState<Record<string, LegGreeks>>({})

  const [editLegId, setEditLegId] = useState<string | null>(null)
  const [marginRequired, setMarginRequired] = useState<number | null>(null)
  const [isMarginLoading, setIsMarginLoading] = useState(false)
  // null = unknown yet; true/false once we've probed the broker.
  const [marginSupported, setMarginSupported] = useState<boolean | null>(null)

  // Portfolio persistence state
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [loadedEntry, setLoadedEntry] = useState<PortfolioEntry | null>(null)

  // Basket execution dialog
  const [executeDialogOpen, setExecuteDialogOpen] = useState(false)

  // Max Algos-symbol → tick size map, built from the live option chain.
  // Powers per-leg price snapping in the Execute Basket dialog so options
  // priced in 0.05 ticks never leak floating-point drift into the order,
  // and crypto legs with 0.0001 / 0.5 ticks are respected too.
  const tickSizeBySymbol = useMemo(() => {
    if (!chainData?.chain) return {}
    const map: Record<string, number> = {}
    for (const row of chainData.chain) {
      if (row.ce?.symbol && row.ce.tick_size > 0) map[row.ce.symbol] = row.ce.tick_size
      if (row.pe?.symbol && row.pe.tick_size > 0) map[row.pe.symbol] = row.pe.tick_size
    }
    return map
  }, [chainData])

  // Dynamic, read-only strategy name sent to /basketorder. Prefers the
  // saved portfolio entry name; otherwise synthesises from current state.
  const computedStrategyName = useMemo(() => {
    if (loadedEntry?.name) return loadedEntry.name
    const activeCount = legs.filter((l) => l.active).length
    const template = activeTemplate?.name
    const parts = [selectedUnderlying || 'Strategy']
    if (template) parts.push(template)
    if (selectedExpiry) parts.push(selectedExpiry)
    if (activeCount > 0) parts.push(`(${activeCount}L)`)
    return parts.join(' ')
  }, [loadedEntry, legs, activeTemplate, selectedUnderlying, selectedExpiry])

  const requestIdRef = useRef(0)

  // Reset every module-level queuedFetch lane on every mount.
  // This module singleton survives SPA navigation — if the user navigated
  // away mid-fetch on a previous visit, a lane may still be waiting on a
  // promise that will never resolve. Every new mount gets fresh queues so
  // the expiry fetch and chain fetch fire immediately without blocking.
  // biome-ignore lint/correctness/useExhaustiveDependencies: intentional mount-only reset
  useEffect(() => {
    for (let i = 0; i < callChains.length; i++) callChains[i] = Promise.resolve()
    nextLane = 0
  }, [])

  // Reset all expiry- / chain-derived state in the same event handler as the
  // underlying or exchange change so React batches them into a single render.
  // Without this, dependent effects (`/optionchain`, `/syntheticfuture`, ...)
  // get one frame where `selectedUnderlying` is new but `selectedExpiry` is
  // still the previous underlying's, and fire an invalid pair at the broker.
  // OptionChain uses the same pattern.
  const resetExpiryAndChainState = useCallback(() => {
    setExpiries([])
    setFutureExpiries([])
    setSelectedExpiry('')
    setChainData(null)
    setAtmIv(null)
    setFuturesPrice(null)
  }, [])

  const handleUnderlyingChange = useCallback(
    (next: string) => {
      if (next === selectedUnderlying) return
      setSelectedUnderlying(next)
      resetExpiryAndChainState()
    },
    [selectedUnderlying, resetExpiryAndChainState]
  )

  const handleExchangeChange = useCallback(
    (next: string) => {
      if (next === selectedExchange) return
      setSelectedExchange(next)
      resetExpiryAndChainState()
    },
    [selectedExchange, resetExpiryAndChainState]
  )

  // Re-sync exchange when broker capabilities load async
  useEffect(() => {
    setSelectedExchange((prev) =>
      prev && fnoExchanges.some((ex) => ex.value === prev) ? prev : defaultFnoExchange
    )
  }, [defaultFnoExchange, fnoExchanges])

  // Populate the underlyings dropdown. The hard-coded `defaultUnderlyings`
  // map only covers the major indices (NIFTY / BANKNIFTY / ...), so we mirror
  // the Option Chain page and fetch the full F&O list from
  // /search/api/underlyings — which includes every F&O stock (RELIANCE,
  // TCS, HDFCBANK, etc.) in addition to indices. Defaults are shown
  // immediately for fast paint, then replaced when the API resolves.
  useEffect(() => {
    const defaults = defaultUnderlyings[selectedExchange] || []
    setUnderlyings(defaults)
    setSelectedUnderlying((prev) => (defaults.includes(prev) ? prev : defaults[0] || ''))

    let cancelled = false
    ;(async () => {
      try {
        const response = await oiProfileApi.getUnderlyings(selectedExchange)
        if (cancelled) return
        if (response.status === 'success' && response.underlyings.length > 0) {
          setUnderlyings(response.underlyings)
          setSelectedUnderlying((prev) =>
            response.underlyings.includes(prev) ? prev : response.underlyings[0]
          )
        }
      } catch {
        // Keep defaults on failure.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedExchange, defaultUnderlyings])

  // Sync page state with search params (underlying, exchange, expiry) when arriving with ?template=
  useEffect(() => {
    const templateId = searchParams.get('template')
    if (!templateId) return

    const urlUnderlying = searchParams.get('underlying')
    const urlExchange = searchParams.get('exchange')
    const urlExpiry = searchParams.get('expiry')

    if (urlExchange) {
      setSelectedExchange(urlExchange)
    }
    if (urlUnderlying) {
      setSelectedUnderlying(urlUnderlying)
    }
    if (urlExpiry) {
      setSelectedExpiry(urlExpiry)
    }
  }, [searchParams])

  // Load expiries (options + futures — different calendars on MCX/CDS especially).
  // Expiries are normalised to the Max Algos DDMMMYY format at the source so that
  // every downstream component (header, dialogs, symbol builders) sees a single
  // consistent string — otherwise the Edit dialog can't match leg.expiry
  // ("21APR26") against the raw API value ("21-APR-2026") and the field blanks.
  useEffect(() => {
    if (!apiKey || !selectedUnderlying) return
    setIsExpiriesLoading(true)
    // IMPORTANT: clear expiries + selectedExpiry + chainData synchronously
    // BEFORE the fetch starts. Otherwise downstream effects (/optionchain,
    // /syntheticfuture, /optiongreeks) see the previous underlying's
    // selectedExpiry (e.g. NIFTY's 21APR26) alongside the new
    // selectedUnderlying (BANKNIFTY) and fire an invalid (underlying,
    // expiry) request into the broker, which logs "No strikes found" until
    // the fresh expiries finally arrive.
    setExpiries([])
    setFutureExpiries([])
    const hasTemplate = searchParams.get('template')
    if (!hasTemplate) {
      setSelectedExpiry('')
    }
    setChainData(null)
    setAtmIv(null)
    setFuturesPrice(null)
    let cancelled = false
    ;(async () => {
      try {
        const optionExchange = optionExchangeFor(selectedExchange)
        // Serialize the two `/expiry` calls through the page queue so they
        // don't multiplex with each other or with the other mount-time
        // fetches below.
        const optsRes = await queuedFetch(() =>
          optionChainApi.getExpiries(apiKey, selectedUnderlying, optionExchange, 'options')
        )
        const futsRes = await queuedFetch(() =>
          optionChainApi
            .getExpiries(apiKey, selectedUnderlying, optionExchange, 'futures')
            .catch(() => ({ status: 'error' as const, data: [] as string[] }))
        )
        if (cancelled) return
        const normaliseList = (list: string[]) =>
          // Preserve order but drop empties and de-dupe after normalisation.
          Array.from(new Set(list.filter(Boolean).map(convertExpiryForSymbol)))
        if (
          optsRes.status === 'success' &&
          Array.isArray(optsRes.data) &&
          optsRes.data.length > 0
        ) {
          const normalised = normaliseList(optsRes.data)
          setExpiries(normalised)
          setSelectedExpiry((prev) => (normalised.includes(prev) ? prev : normalised[0]))
        } else {
          setExpiries([])
          setSelectedExpiry('')
        }
        if (futsRes.status === 'success' && Array.isArray(futsRes.data)) {
          setFutureExpiries(normaliseList(futsRes.data))
        } else {
          setFutureExpiries([])
        }
      } catch (_err) {
        if (!cancelled) {
          showToast.error('Failed to fetch expiries')
        }
      } finally {
        if (!cancelled) {
          setIsExpiriesLoading(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [apiKey, selectedUnderlying, selectedExchange, searchParams.get])

  // Load option chain
  const loadOptionChain = useCallback(async () => {
    if (!apiKey || !selectedUnderlying || !selectedExpiry) return
    // Skip while the expiries list is (re)loading for the current
    // underlying/exchange -- e.g. right after arriving via a
    // ?template=...&expiry=... URL, selectedExpiry is set directly from
    // the URL param BEFORE the real options-expiry list has even been
    // fetched (see the search-params-sync effect above). If that URL
    // param happened to be a FUTURES expiry rather than an options one
    // (MCX/CDS have separate options/futures expiry calendars), this
    // guard alone wasn't enough: expiries.length was still 0 during that
    // window, so the check below was skipped entirely and a request fired
    // with a futures-only expiry, producing exactly the wrong-symbol
    // "No strikes found" error this comment now prevents. Once the
    // expiries fetch resolves, its own effect already self-corrects
    // selectedExpiry if it's not in the real list -- this additional
    // isExpiriesLoading gate just closes the race window before that
    // correction lands.
    if (isExpiriesLoading) return
    // Skip while the expiries list hasn't refreshed for the current
    // underlying yet — e.g. after switching NIFTY → BANKNIFTY, the
    // previous expiry (21APR26) isn't valid for BANKNIFTY.
    if (expiries.length > 0 && !expiries.includes(selectedExpiry)) return
    const reqId = ++requestIdRef.current
    setIsRefreshing(true)
    try {
      const exchange = underlyingExchangeFor(selectedExchange, selectedUnderlying)
      const expiryCode = convertExpiryForSymbol(selectedExpiry)
      const data = await queuedFetch(() =>
        optionChainApi.getOptionChain(apiKey, selectedUnderlying, exchange, expiryCode, 20)
      )
      if (reqId !== requestIdRef.current) return
      if (data.status === 'success') {
        setChainData(data)
        // ATM IV: mid of CE/PE IV at ATM strike — we'll use the smile service later;
        // for now compute via greeks of ATM CE once legs are known.
      } else {
        showToast.error(data.message || 'Failed to load option chain')
      }
    } catch (_err) {
      showToast.error('Failed to load option chain')
    } finally {
      if (reqId === requestIdRef.current) setIsRefreshing(false)
    }
  }, [apiKey, selectedExchange, selectedUnderlying, selectedExpiry, expiries, isExpiriesLoading])

  useEffect(() => {
    loadOptionChain()
  }, [loadOptionChain])

  // Live tick-by-tick prices for the underlying + every visible strike's
  // CE/PE, layered on top of the REST-fetched chain above (same hybrid
  // pattern as OptionChain.tsx's useOptionChainLive: REST gives structure/
  // OI/greeks once per chain load, WS keeps LTP current between loads).
  // Without this, Spot/Futures/leg premiums here only ever reflected
  // whatever was true at the moment the chain was fetched.
  const optionExchange = useMemo(() => optionExchangeFor(selectedExchange), [selectedExchange])
  const wsSymbols = useMemo(() => {
    if (!selectedUnderlying) return []
    const symbols: Array<{ symbol: string; exchange: string }> = [
      {
        symbol: selectedUnderlying,
        exchange: underlyingExchangeFor(selectedExchange, selectedUnderlying),
      },
    ]
    if (chainData?.chain) {
      for (const strike of chainData.chain) {
        if (strike.ce?.symbol) symbols.push({ symbol: strike.ce.symbol, exchange: optionExchange })
        if (strike.pe?.symbol) symbols.push({ symbol: strike.pe.symbol, exchange: optionExchange })
      }
    }
    return symbols
  }, [selectedUnderlying, selectedExchange, optionExchange, chainData?.chain])

  const { data: wsData } = useMarketData({
    symbols: wsSymbols,
    mode: 'LTP',
    enabled: wsSymbols.length > 0,
  })

  // Merge WS LTP updates into chainData (underlying spot + per-strike CE/PE)
  // without touching OI/greeks/other REST-only fields.
  useEffect(() => {
    if (!chainData || wsData.size === 0) return
    const underlyingExch = underlyingExchangeFor(selectedExchange, selectedUnderlying)
    const underlyingWs = wsData.get(`${underlyingExch}:${selectedUnderlying}`)
    let changed = false

    const mergedChain = chainData.chain.map((strike) => {
      let newStrike = strike
      const { ce, pe } = strike
      if (ce?.symbol) {
        const wsCe = wsData.get(`${optionExchange}:${ce.symbol}`)
        if (wsCe?.data?.ltp !== undefined && wsCe.data.ltp !== ce.ltp) {
          newStrike = { ...newStrike, ce: { ...ce, ltp: wsCe.data.ltp } }
          changed = true
        }
      }
      if (pe?.symbol) {
        const wsPe = wsData.get(`${optionExchange}:${pe.symbol}`)
        if (wsPe?.data?.ltp !== undefined && wsPe.data.ltp !== pe.ltp) {
          newStrike = { ...newStrike, pe: { ...pe, ltp: wsPe.data.ltp } }
          changed = true
        }
      }
      return newStrike
    })

    const newUnderlyingLtp = underlyingWs?.data?.ltp
    if (newUnderlyingLtp !== undefined && newUnderlyingLtp !== chainData.underlying_ltp) {
      changed = true
    }

    if (changed) {
      setChainData({
        ...chainData,
        chain: mergedChain,
        underlying_ltp: newUnderlyingLtp ?? chainData.underlying_ltp,
      })
    }
  }, [wsData, chainData, selectedExchange, selectedUnderlying, optionExchange])

  // Seed ATM IV directly from the ATM CE as soon as the chain loads.
  // (The leg-Greeks fetch is gated on having at least one leg, so without this
  // the ATM IV badge would stay blank until the user adds a position.)
  //
  // Keyed on the ATM CE SYMBOL, never on `chainData` itself. The WS-merge
  // effect above calls setChainData() on every live LTP tick, so a
  // `chainData` dependency here made this re-run per tick and fire one
  // /optiongreeks request each time -- a self-sustaining render->fetch loop
  // that flooded the endpoint until the rate limiter returned 429 and
  // saturated the server's request pool (dashboard 504s, container marked
  // unhealthy). The ATM symbol only changes when the chain or ATM strike
  // genuinely changes, which is exactly when the IV needs refetching.
  //
  // NOTE: `chainData.chain` is a brand-new array on every tick (the merge
  // above rebuilds it with .map()), so this memo does recompute each tick.
  // That is fine and deliberate: it returns a plain STRING, so the effect
  // below — which compares its deps by value — sees no change and does not
  // refire. Depending on the array directly is what has to be avoided;
  // recomputing a cheap .find() does not cost a request.
  const atmCeSymbol = useMemo(() => {
    if (!chainData?.atm_strike) return null
    return chainData.chain.find((s) => s.strike === chainData.atm_strike)?.ce?.symbol ?? null
  }, [chainData?.atm_strike, chainData?.chain])

  useEffect(() => {
    if (!apiKey || !atmCeSymbol) return
    const atmSymbol = atmCeSymbol
    let cancelled = false
    ;(async () => {
      try {
        const exchange = optionExchangeFor(selectedExchange)
        const underlyingExchange = underlyingExchangeFor(selectedExchange, selectedUnderlying)
        const res = await queuedFetch(() =>
          apiClient.post<{
            status: string
            implied_volatility?: number
          }>('/optiongreeks', {
            apikey: apiKey,
            symbol: atmSymbol,
            exchange,
            underlying_symbol: selectedUnderlying,
            underlying_exchange: underlyingExchange,
          })
        )
        if (cancelled) return
        if (
          res.data.status === 'success' &&
          typeof res.data.implied_volatility === 'number' &&
          res.data.implied_volatility > 0
        ) {
          setAtmIv(res.data.implied_volatility)
        }
      } catch {
        /* non-fatal */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [apiKey, atmCeSymbol, selectedExchange, selectedUnderlying])

  // Load synthetic future for the selected expiry
  useEffect(() => {
    if (!apiKey || !selectedUnderlying || !selectedExpiry) return
    // Double-check selectedExpiry is actually valid for the current
    // underlying — the expiries-load effect clears selectedExpiry to ''
    // at the start of an underlying switch, but if for any reason this
    // effect runs before that clear propagates we skip rather than fire
    // an invalid (underlying, expiry) pair at the broker.
    if (expiries.length > 0 && !expiries.includes(selectedExpiry)) return
    let cancelled = false
    ;(async () => {
      try {
        const exchange = underlyingExchangeFor(selectedExchange, selectedUnderlying)
        const expiryCode = convertExpiryForSymbol(selectedExpiry)
        const res = await queuedFetch(() =>
          apiClient.post<{
            status: string
            synthetic_future_price?: number
          }>('/syntheticfuture', {
            apikey: apiKey,
            underlying: selectedUnderlying,
            exchange,
            expiry_date: expiryCode,
          })
        )
        if (cancelled) return
        if (res.data.status === 'success' && res.data.synthetic_future_price) {
          setFuturesPrice(res.data.synthetic_future_price)
        } else {
          setFuturesPrice(null)
        }
      } catch {
        if (!cancelled) setFuturesPrice(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [apiKey, selectedExchange, selectedUnderlying, selectedExpiry, expiries])

  // ── Equity mode ──
  // A separate, self-contained data path from the option-chain state above.
  // Equity trades on the cash segment (NSE/BSE), has no expiry/strike/chain,
  // and its universe (thousands of listed stocks) doesn't fit the small
  // hard-coded F&O underlyings list — so Equity gets its own exchange
  // choice, its own symbol search (same /search endpoint ManualLegBuilder's
  // EQUITY leg-add already uses), and its own live price, entirely
  // independent of chainData/selectedExpiry so switching into/out of Equity
  // never disturbs Options/Futures state.
  const [equityExchange, setEquityExchange] = useState('NSE')
  const [equitySymbol, setEquitySymbol] = useState('')
  const [equityQuoteLtp, setEquityQuoteLtp] = useState<number | null>(null)
  // Rest of the quote snapshot (O/H/L/Volume) for the Equity stats bar. Kept
  // separate from equityQuoteLtp since the WS tick (below) only ever updates
  // LTP — these fields are REST-only and don't need live streaming.
  const [equityQuoteRest, setEquityQuoteRest] = useState<{
    open: number | null
    high: number | null
    low: number | null
    volume: number | null
  }>({ open: null, high: null, low: null, volume: null })

  // Seed the full equity quote once via REST as soon as a symbol is picked,
  // so the stats bar isn't blank while the WebSocket subscription (below)
  // connects/authenticates.
  useEffect(() => {
    if (assetClass !== 'Equity' || !apiKey || !equitySymbol) {
      setEquityQuoteLtp(null)
      setEquityQuoteRest({ open: null, high: null, low: null, volume: null })
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const res = await tradingApi.getQuotes(apiKey, equitySymbol, equityExchange)
        if (cancelled) return
        if (res.status === 'success' && res.data) {
          if (res.data.ltp) setEquityQuoteLtp(res.data.ltp)
          setEquityQuoteRest({
            open: res.data.open ?? null,
            high: res.data.high ?? null,
            low: res.data.low ?? null,
            volume: res.data.volume ?? null,
          })
        }
      } catch {
        /* non-fatal — live WS subscription below will populate LTP */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [assetClass, apiKey, equitySymbol, equityExchange])

  // Live tick-by-tick equity price via the same shared WebSocket manager
  // used above for Options/Futures.
  const equityWsSymbols = useMemo(
    () =>
      assetClass === 'Equity' && equitySymbol
        ? [{ symbol: equitySymbol, exchange: equityExchange }]
        : [],
    [assetClass, equitySymbol, equityExchange]
  )
  const { data: equityWsData } = useMarketData({
    symbols: equityWsSymbols,
    mode: 'LTP',
    enabled: equityWsSymbols.length > 0,
  })
  const equityLivePrice = useMemo(() => {
    if (!equitySymbol) return null
    const tick = equityWsData.get(`${equityExchange}:${equitySymbol}`)
    return tick?.data?.ltp ?? equityQuoteLtp
  }, [equityWsData, equitySymbol, equityExchange, equityQuoteLtp])

  const handleEquitySymbolChange = useCallback((symbol: string, exchange: string) => {
    setEquitySymbol(symbol)
    setEquityExchange(exchange)
    setEquityQuoteLtp(null)
  }, [])

  // Derived: ATM strike, lot size, spot
  const optionsOrFuturesSpotPrice = chainData?.underlying_ltp ?? null
  const spotPrice = assetClass === 'Equity' ? equityLivePrice : optionsOrFuturesSpotPrice
  const atmStrike = chainData?.atm_strike ?? null
  const lotSize = useMemo(() => {
    if (!chainData?.chain) return null
    const atmRow = chainData.chain.find((s) => s.strike === chainData.atm_strike)
    return atmRow?.ce?.lotsize ?? atmRow?.pe?.lotsize ?? null
  }, [chainData])

  // Common strike step — try to detect from chain spacing
  const strikeStep = useMemo(() => {
    if (!chainData?.chain || chainData.chain.length < 2) return 50
    const sorted = [...chainData.chain].map((s) => s.strike).sort((a, b) => a - b)
    let minDiff = Infinity
    for (let i = 1; i < sorted.length; i++) {
      const d = sorted[i] - sorted[i - 1]
      if (d > 0 && d < minDiff) minDiff = d
    }
    return Number.isFinite(minDiff) ? minDiff : 50
  }, [chainData])

  // DTE of the header-selected expiry (for the metadata badge only).
  const rawDays = useMemo(() => {
    if (!selectedExpiry) return null
    const expiryCode = convertExpiryForSymbol(selectedExpiry)
    return daysToExpiry(expiryCode)
  }, [selectedExpiry])

  // For the payoff curve: "At Expiry" uses the NEAREST leg's days-to-expiry
  // so calendar / diagonal spreads render correctly (the far leg retains
  // remaining time value). Falls back to the header expiry when no legs yet.
  const nearestDays = useMemo(() => {
    if (legs.length === 0) return rawDays ?? 0
    return nearestLegDays(legs)
  }, [legs, rawDays])

  // Simulator caps "days forward" to the nearest expiry so the T+0 slider
  // can't go past the first leg's expiration.
  const maxSimulatorDays = Math.max(0, Math.floor(nearestDays))
  const clampedDaysElapsed = Math.min(daysElapsed, maxSimulatorDays)

  // Remaining "simulated" years to the near expiry — for σ bands / PoP.
  const simulatedYearsToNearExpiry = daysToYears(Math.max(nearestDays - clampedDaysElapsed, 0))

  // Shifted spot for the payoff calculations
  const simulatedSpot = spotPrice !== null ? spotPrice * (1 + spotShiftPct / 100) : 0

  // Batch load Greeks for all legs (also used to fill ATM IV for the header)
  // We intentionally key this fetch on `legs.length` (plus exchange/underlying/atm)
  // rather than the full `legs` array: the latest `legs` snapshot is read inside
  // the async body, and depending on the whole array would refire this
  // un-debounced /multioptiongreeks network call on every leg-object edit.
  // biome-ignore lint/correctness/useExhaustiveDependencies: key on legs.length to avoid refiring the un-debounced Greeks fetch on every leg edit; the closure reads the latest legs at call time
  useEffect(() => {
    if (!apiKey || legs.length === 0) {
      setGreeksByLeg({})
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const exchange = optionExchangeFor(selectedExchange)
        const underlyingExchange = underlyingExchangeFor(selectedExchange, selectedUnderlying)
        const symbols = legs
          .filter((l) => l.segment === 'OPTION' && l.symbol)
          .map((l) => ({
            symbol: l.symbol,
            exchange,
            underlying_symbol: selectedUnderlying,
            underlying_exchange: underlyingExchange,
          }))
        if (symbols.length === 0) return
        const res = await queuedFetch(() =>
          apiClient.post<{
            status: string
            data?: Array<{
              symbol: string
              implied_volatility?: number
              greeks?: { delta?: number; gamma?: number; theta?: number; vega?: number }
            }>
          }>('/multioptiongreeks', {
            apikey: apiKey,
            symbols,
          })
        )
        if (cancelled) return
        if ((res.data.status === 'success' || res.data.status === 'partial') && res.data.data) {
          const map: Record<string, LegGreeks> = {}
          for (const leg of legs) {
            const hit = res.data.data.find((r) => r.symbol === leg.symbol)
            map[leg.id] = {
              legId: leg.id,
              iv: hit?.implied_volatility ?? null,
              delta: hit?.greeks?.delta ?? null,
              gamma: hit?.greeks?.gamma ?? null,
              theta: hit?.greeks?.theta ?? null,
              vega: hit?.greeks?.vega ?? null,
            }
          }
          setGreeksByLeg(map)

          // Fill ATM IV for header — use the leg at ATM if we find one, else avg of all IVs
          const atmLegIv = legs
            .map((l) => {
              const grk = map[l.id]
              if (grk?.iv !== null && grk?.iv !== undefined && l.strike === atmStrike) {
                return grk.iv
              }
              return null
            })
            .find((v) => v !== null)

          if (atmLegIv !== null && atmLegIv !== undefined) {
            setAtmIv(atmLegIv)
          } else {
            const ivs = Object.values(map)
              .map((g) => g.iv)
              .filter((v): v is number => v !== null && v !== undefined)
            if (ivs.length > 0) {
              setAtmIv(ivs.reduce((a, b) => a + b, 0) / ivs.length)
            }
          }

          // Backfill IV into legs for simulator pricing if missing
          setLegs((prev) =>
            prev.map((l) => {
              if (l.iv > 0) return l
              const iv = map[l.id]?.iv
              return iv ? { ...l, iv } : l
            })
          )
        }
      } catch {
        /* non-fatal */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [apiKey, legs.length, selectedExchange, selectedUnderlying, atmStrike])

  // Margin fetch — whenever legs change, call the broker margin service.
  // Debounced so rapid edits don't hammer the endpoint.
  useEffect(() => {
    if (!apiKey) return
    const openLegs = legs.filter((l) => l.active && !(l.exitPrice !== undefined && l.exitPrice > 0))
    if (openLegs.length === 0) {
      setMarginRequired(null)
      return
    }
    // If we've already determined the broker doesn't support margin,
    // don't keep probing — just skip.
    if (marginSupported === false) return

    const handle = setTimeout(async () => {
      setIsMarginLoading(true)
      try {
        const exchange = optionExchangeFor(selectedExchange)
        // NOTE: MarginPositionSchema declares `quantity` and `price` as
        // Str fields — sending them as numbers fails Marshmallow validation
        // with a 400 (no descriptive message), which earlier silently
        // suppressed the Margin row. Keep these as strings.
        const positions = openLegs.map((l) => ({
          exchange,
          symbol: l.symbol,
          action: l.side,
          quantity: String(l.lots * l.lotSize),
          product: 'NRML',
          pricetype: l.price > 0 ? 'LIMIT' : 'MARKET',
          price: l.price > 0 ? String(l.price) : '0',
        }))
        const res = await queuedFetch(() =>
          apiClient.post<{
            status: string
            data?: {
              total_margin_required?: number
              total_margin?: number
              margin_required?: number
            }
            message?: string
          }>(
            '/margin',
            { apikey: apiKey, positions },
            // Let 4xx/5xx responses resolve instead of throw so we can inspect them.
            { validateStatus: () => true }
          )
        )
        // Response key varies slightly across brokers — accept any of the
        // three field names the service has been observed to return.
        const total =
          res.data?.data?.total_margin_required ??
          res.data?.data?.total_margin ??
          res.data?.data?.margin_required ??
          null
        if (res.status === 200 && res.data.status === 'success' && typeof total === 'number') {
          setMarginRequired(total)
          setMarginSupported(true)
        } else {
          // Any non-success response (404/501/error message about unsupported
          // broker) means this broker doesn't expose margin — hide the metric.
          const msg = (res.data?.message || '').toLowerCase()
          const unsupported =
            res.status === 404 ||
            res.status === 501 ||
            msg.includes('not support') ||
            msg.includes('unsupported') ||
            msg.includes('not implemented')
          if (unsupported) {
            setMarginSupported(false)
          }
          setMarginRequired(null)
          // Surface the failure in the dev console so future schema
          // mismatches or broker quirks are easier to diagnose.
          console.warn('Margin calculation failed', {
            status: res.status,
            body: res.data,
          })
        }
      } catch {
        // Network failures shouldn't permanently disable — just clear for now.
        setMarginRequired(null)
      } finally {
        setIsMarginLoading(false)
      }
    }, 400)
    return () => clearTimeout(handle)
  }, [apiKey, legs, selectedExchange, marginSupported])

  // Backfill price for legs that were added without one (typically the far-
  // expiry leg of a calendar/diagonal — the loaded chain only covers the
  // near expiry, so those legs start at price=0 and we need /multiquotes
  // to supply the LTP). Runs only for legs whose price is still 0 and
  // haven't been edited closed.
  useEffect(() => {
    if (!apiKey) return
    const needs = legs.filter(
      (l) => l.price === 0 && !(l.exitPrice !== undefined && l.exitPrice > 0) && l.symbol
    )
    if (needs.length === 0) return
    const exchange = optionExchangeFor(selectedExchange)
    let cancelled = false
    ;(async () => {
      try {
        const res = await queuedFetch(() =>
          apiClient.post<{
            status: string
            results?: Array<{ symbol: string; exchange: string; data?: { ltp?: number } }>
          }>('/multiquotes', {
            apikey: apiKey,
            symbols: needs.map((l) => ({ symbol: l.symbol, exchange })),
          })
        )
        if (cancelled) return
        if (res.data.status === 'success' && res.data.results) {
          const priceBySymbol: Record<string, number> = {}
          for (const r of res.data.results) {
            if (r.data?.ltp !== undefined && r.data.ltp > 0) {
              priceBySymbol[r.symbol] = r.data.ltp
            }
          }
          if (Object.keys(priceBySymbol).length === 0) return
          setLegs((prev) =>
            prev.map((l) => {
              if (l.price > 0) return l
              const p = priceBySymbol[l.symbol]
              return p !== undefined ? { ...l, price: p } : l
            })
          )
        }
      } catch {
        /* non-fatal */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [apiKey, legs, selectedExchange])

  // F&O exchange for all leg symbols (used for WebSocket subscription).
  const fnoExchange = useMemo(() => optionExchangeFor(selectedExchange), [selectedExchange])

  // Chain-derived fallback prices (used until the first WS tick arrives).
  // PnLTab itself handles real-time streaming internally to scope tick-
  // driven re-renders (so ticks don't cascade into PayoffChart/Greeks/etc).
  const fallbackPricesByLeg = useMemo(() => {
    const map: Record<string, number> = {}
    if (!chainData) return map
    for (const leg of legs) {
      if (leg.segment !== 'OPTION' || leg.strike === undefined || !leg.optionType) continue
      const row = chainData.chain.find((s) => s.strike === leg.strike)
      const side = leg.optionType === 'CE' ? row?.ce : row?.pe
      if (side?.ltp !== undefined) map[leg.id] = side.ltp
    }
    return map
  }, [chainData, legs])

  // Add legs from a template
  const handleTemplatePick = useCallback(
    (tpl: StrategyTemplate) => {
      if (!chainData || atmStrike === null) {
        showToast.error('Option chain not loaded yet')
        return
      }
      setActiveTemplate(tpl)
      setTemplateDialogOpen(true)
    },
    [chainData, atmStrike]
  )

  const handleTemplateConfirm = useCallback(
    (resolved: ResolvedTemplateLeg[], totalLots: number) => {
      if (!lotSize) {
        showToast.error('Lot size not detected — load the chain first')
        return
      }
      const newLegs: StrategyLeg[] = resolved.map((r) => {
        // Each leg keeps its own expiry — calendars / diagonals span two.
        const legExpiry = convertExpiryForSymbol(r.resolvedExpiry)
        // Preserve the template's per-leg ratio (e.g. butterfly body = 2 lots,
        // wings = 1 lot) and scale it by the user's chosen lot multiplier.
        // Without this, all legs come in at `totalLots` and ratio spreads /
        // butterflies / condors collapse into wrong shapes.
        const legLots = Math.max(1, (r.lots ?? 1) * totalLots)
        return {
          id: uid(),
          segment: 'OPTION',
          side: r.side,
          lots: legLots,
          lotSize,
          expiry: legExpiry,
          strike: r.resolvedStrike,
          optionType: r.optionType,
          price: r.price,
          iv: 0,
          active: true,
          symbol:
            r.symbol ??
            buildOptionSymbol(selectedUnderlying, legExpiry, r.resolvedStrike, r.optionType),
        }
      })
      setLegs((prev) => [...prev, ...newLegs])
      setTemplateDialogOpen(false)
      setActiveTemplate(null)
    },
    [lotSize, selectedUnderlying]
  )

  // Marketplace template clone: arriving with ?template=<catalog-id> maps to a
  // real option structure in strategyTemplates.ts and auto-opens the same
  // picker dialog used by the "Templates" grid — the legs are the genuine
  // template legs, not a blank builder. Waits for the option chain to load
  // (handleTemplatePick/auto-confirm requires it) before firing, and removes the param so
  // it can't re-fire if legs are cleared and the chain effect re-runs.
  // biome-ignore lint/correctness/useExhaustiveDependencies: must only re-fire when the chain becomes ready or relevant params change
  useEffect(() => {
    const catalogTemplateId = searchParams.get('template')
    if (!catalogTemplateId || !chainData || atmStrike === null) return
    const catalogItem = CATALOG.find((c) => c.id === catalogTemplateId)
    const optionsTemplateId = catalogItem?.optionsTemplateId

    // Check if we arrived from Wizard with pre-selected options
    const urlUnderlying = searchParams.get('underlying')
    const urlExpiry = searchParams.get('expiry')

    searchParams.delete('template')
    searchParams.delete('underlying')
    searchParams.delete('expiry')
    searchParams.delete('exchange')
    setSearchParams(searchParams, { replace: true })

    if (!optionsTemplateId) return
    const tpl = STRATEGY_TEMPLATES.find((s) => s.id === optionsTemplateId)
    if (!tpl) return

    if (urlUnderlying && urlExpiry && lotSize) {
      // Auto-confirm the legs!
      const strikes = chainData.chain.map((s: any) => s.strike)
      const baseIdx = Math.max(0, expiries.indexOf(selectedExpiry))

      const resolvedLegs = tpl.legs.map((leg) => {
        const target = atmStrike + leg.strikeOffset * strikeStep
        const resolvedStrike = nearestStrike(target, strikes) ?? target
        const offset = leg.expiryOffset ?? 0
        const targetIdx = Math.min(baseIdx + offset, expiries.length - 1)
        const resolvedExpiry = expiries[Math.max(0, targetIdx)] ?? selectedExpiry
        const canUseChain = resolvedExpiry === selectedExpiry
        const row = canUseChain
          ? chainData.chain.find((s: any) => s.strike === resolvedStrike)
          : undefined
        const side = leg.optionType === 'CE' ? row?.ce : row?.pe
        return {
          ...leg,
          resolvedStrike,
          resolvedExpiry,
          price: side?.ltp ?? 0,
          symbol: side?.symbol ?? null,
        }
      })

      const newLegs: StrategyLeg[] = resolvedLegs.map((r) => {
        const legExpiry = convertExpiryForSymbol(r.resolvedExpiry)
        return {
          id: uid(),
          segment: 'OPTION',
          side: r.side,
          lots: 1,
          lotSize,
          expiry: legExpiry,
          strike: r.resolvedStrike,
          optionType: r.optionType,
          price: r.price,
          iv: 0,
          active: true,
          symbol:
            r.symbol ??
            buildOptionSymbol(selectedUnderlying, legExpiry, r.resolvedStrike, r.optionType),
        }
      })

      setLegs(newLegs)
      showToast.success(`Loaded template: ${tpl.name}`)
    } else {
      handleTemplatePick(tpl)
      showToast.success(`Loaded template: ${tpl.name}`)
    }
  }, [chainData, atmStrike, expiries, selectedExpiry, selectedUnderlying, lotSize, strikeStep])

  // Manual leg add
  const handleAddManualLeg = useCallback(
    (draft: LegDraft) => {
      // Equity legs are fully self-contained in the draft (symbol, exchange,
      // lot size all came from the equity search picker) and are entirely
      // independent of this page's underlying/expiry/option-chain state —
      // never routed through the option/future symbol-building logic below.
      if (draft.segment === 'EQUITY') {
        if (!draft.symbol || !draft.equityExchange) {
          showToast.error('Select a symbol first')
          return
        }
        const newLeg: StrategyLeg = {
          id: uid(),
          segment: 'EQUITY',
          side: draft.side,
          lots: draft.lots,
          lotSize: draft.lotSize ?? 1,
          expiry: '',
          price: draft.price,
          iv: 0,
          active: true,
          symbol: draft.symbol,
          equityExchange: draft.equityExchange,
          equityProduct: draft.equityProduct,
          equityOrderType: draft.equityOrderType,
          equityTargetPrice: draft.equityTargetPrice,
          equitySlPrice: draft.equitySlPrice,
          equityTrailingSlPct: draft.equityTrailingSlPct,
        }
        setLegs((prev) => [...prev, newLeg])
        return
      }

      if (!lotSize && draft.segment === 'OPTION') {
        showToast.error('Lot size not detected')
        return
      }
      const expiryCode = convertExpiryForSymbol(draft.expiry)

      // Prefer the broker-provided symbol from the live chain whenever
      // possible — some brokers (notably crypto exchanges like Delta) don't
      // follow the standard BASE[DDMMMYY][STRIKE][CE|PE] concatenation, so
      // constructing it locally would produce an invalid symbol.
      let symbol: string
      if (draft.segment === 'OPTION' && draft.strike !== undefined && draft.optionType) {
        const row = chainData?.chain.find((s) => s.strike === draft.strike)
        const side = draft.optionType === 'CE' ? row?.ce : row?.pe
        symbol =
          side?.symbol ??
          buildOptionSymbol(selectedUnderlying, expiryCode, draft.strike, draft.optionType)
      } else {
        symbol = buildFutureSymbol(selectedUnderlying, expiryCode)
      }

      // For futures, fall back to the synthetic-future price when the draft
      // didn't carry one — otherwise the payoff calc treats entry as 0 and
      // returns a runaway positive P&L.
      let entryPrice = draft.price
      if (draft.segment === 'FUTURE' && entryPrice <= 0 && futuresPrice !== null) {
        entryPrice = futuresPrice
      }

      const newLeg: StrategyLeg = {
        id: uid(),
        segment: draft.segment,
        side: draft.side,
        lots: draft.lots,
        lotSize: lotSize ?? 1,
        expiry: expiryCode,
        strike: draft.strike,
        optionType: draft.optionType,
        price: entryPrice,
        iv: 0,
        active: true,
        symbol,
      }
      setLegs((prev) => [...prev, newLeg])
    },
    [lotSize, selectedUnderlying, futuresPrice, chainData?.chain]
  )

  // Payoff
  const payoff = useMemo(() => {
    if (!spotPrice) {
      return {
        samples: [],
        maxProfit: 0,
        maxLoss: 0,
        breakevens: [],
        zeroCrossings: [],
      }
    }
    // ±10% band around spot — tight enough to focus on the strategy's
    // action zone and wide enough to contain the ±2σ shading for typical
    // NIFTY/BANKNIFTY IV on weekly/monthly expiries. For very high-IV
    // names or long-dated expiries the σ bands may extend beyond — the
    // range can be widened later if needed.
    const range: [number, number] = [spotPrice * 0.9, spotPrice * 1.1]
    // "At Expiry" curve → advance calendar time to the nearest leg's expiry;
    // far-dated legs (calendar / diagonal) keep their remaining time value.
    // "T+0" curve → advance by the simulator's days-forward value.
    return computePayoff(
      legs,
      spotPrice,
      nearestDays,
      clampedDaysElapsed,
      range,
      240,
      ivShiftPct,
      atmIv ?? 0
    )
  }, [legs, spotPrice, nearestDays, clampedDaysElapsed, ivShiftPct, atmIv])

  const pop = useMemo(() => {
    if (!spotPrice || atmIv === null || simulatedYearsToNearExpiry <= 0) return 0
    return probabilityOfProfit(payoff.samples, spotPrice, atmIv, simulatedYearsToNearExpiry)
  }, [payoff.samples, spotPrice, atmIv, simulatedYearsToNearExpiry])

  // legPnlAt (used by totalPnlAt below) always returns 0 for EQUITY legs —
  // it's an option-chain spot-sweep function and equity legs track a
  // different underlying (see strategyMath.ts's legPnlAt doc comment). For
  // Equity mode, compute live P&L directly against the page's own equity
  // price feed instead, using the same sign*(current-entry)*qty formula
  // PnLTab already uses.
  const equityTotalPnlNow = useMemo(() => {
    if (assetClass !== 'Equity' || equityLivePrice === null) return 0
    let total = 0
    for (const leg of legs) {
      if (!leg.active || leg.segment !== 'EQUITY') continue
      if (leg.exitPrice !== undefined && leg.exitPrice > 0) {
        total +=
          (leg.side === 'BUY' ? 1 : -1) * (leg.exitPrice - leg.price) * leg.lots * leg.lotSize
        continue
      }
      total +=
        (leg.side === 'BUY' ? 1 : -1) * (equityLivePrice - leg.price) * leg.lots * leg.lotSize
    }
    return total
  }, [assetClass, legs, equityLivePrice])

  const optionsTotalPnlNow = useMemo(() => {
    if (!spotPrice) return 0
    return totalPnlAt(legs, simulatedSpot, clampedDaysElapsed, ivShiftPct, atmIv ?? 0)
  }, [legs, simulatedSpot, clampedDaysElapsed, ivShiftPct, spotPrice, atmIv])

  const totalPnlNow = assetClass === 'Equity' ? equityTotalPnlNow : optionsTotalPnlNow

  const credit = useMemo(() => netCredit(legs), [legs])
  const premium = useMemo(() => totalPremium(legs), [legs])

  // Handlers
  const toggleLeg = useCallback((id: string) => {
    setLegs((prev) => prev.map((l) => (l.id === id ? { ...l, active: !l.active } : l)))
  }, [])
  const toggleLegSide = useCallback((id: string) => {
    setLegs((prev) =>
      prev.map((l) => (l.id === id ? { ...l, side: l.side === 'BUY' ? 'SELL' : 'BUY' } : l))
    )
  }, [])
  const removeLeg = useCallback((id: string) => {
    setLegs((prev) => prev.filter((l) => l.id !== id))
  }, [])
  const saveEditedLeg = useCallback(
    (updated: StrategyLeg) => {
      // Normalise expiry to the Max Algos DDMMMYY format — the dropdown may
      // have supplied an API-format value like "21-APR-26" which would wreck
      // symbol construction and leg-row rendering otherwise.
      const normalisedExpiry = convertExpiryForSymbol(updated.expiry)

      // Prefer the live chain's symbol whenever available so crypto / non-
      // standard option symbols stay correct across edits.
      let rebuiltSymbol: string
      if (updated.segment === 'OPTION' && updated.strike !== undefined && updated.optionType) {
        const row = chainData?.chain.find((s) => s.strike === updated.strike)
        const side = updated.optionType === 'CE' ? row?.ce : row?.pe
        rebuiltSymbol =
          side?.symbol ??
          buildOptionSymbol(
            selectedUnderlying,
            normalisedExpiry,
            updated.strike,
            updated.optionType
          )
      } else {
        rebuiltSymbol = buildFutureSymbol(selectedUnderlying, normalisedExpiry)
      }

      setLegs((prev) =>
        prev.map((l) =>
          l.id === updated.id ? { ...updated, expiry: normalisedExpiry, symbol: rebuiltSymbol } : l
        )
      )
      setEditLegId(null)
    },
    [selectedUnderlying, chainData]
  )
  const toggleAll = useCallback((active: boolean) => {
    setLegs((prev) => prev.map((l) => ({ ...l, active })))
  }, [])
  const resetLegs = useCallback(() => {
    setLegs([])
    setSpotShiftPct(0)
    setIvShiftPct(0)
    setDaysElapsed(0)
  }, [])
  const resetSimulators = useCallback(() => {
    setSpotShiftPct(0)
    setIvShiftPct(0)
    setDaysElapsed(0)
  }, [])

  // Load a saved strategy when arriving with ?load=<id>. We restore symbol,
  // exchange, expiry, and legs; greeks / synthetic-future will refetch
  // automatically once the chain effect hooks pick up the change.
  useEffect(() => {
    const loadId = searchParams.get('load')
    if (!loadId) return
    const id = Number(loadId)
    if (!Number.isFinite(id)) return
    let cancelled = false
    ;(async () => {
      try {
        const entry = await strategyPortfolioApi.get(id)
        if (cancelled) return
        // Hydrate primary selectors. They'll trigger their own fetches.
        setSelectedExchange(entry.exchange)
        setSelectedUnderlying(entry.underlying)
        if (entry.expiry) setSelectedExpiry(entry.expiry)
        // Hydrate legs. Mark them loaded so we don't overwrite user IV later.
        const restored: StrategyLeg[] = entry.legs.map((l) => ({
          id: l.id ?? uid(),
          segment: l.segment,
          side: l.side,
          lots: l.lots,
          lotSize: l.lotSize,
          expiry: l.expiry,
          strike: l.strike,
          optionType: l.optionType,
          price: l.price,
          iv: l.iv ?? 0,
          active: l.active ?? true,
          symbol: l.symbol,
          equityExchange: l.equityExchange,
          exitPrice: l.exitPrice,
        }))
        setLegs(restored)
        setLoadedEntry(entry)
        showToast.success(`Loaded "${entry.name}"`)
        // ?execute=1 alongside ?load=<id> (set by the "Execute Now" button
        // on the Portfolio Presets list) opens the basket-order dialog
        // immediately once the legs have hydrated, instead of requiring a
        // second manual click on the canvas's own Execute button.
        const shouldAutoExecute = searchParams.get('execute') === '1'
        // Remove the ?load/?execute params so subsequent state changes don't re-fire.
        searchParams.delete('load')
        searchParams.delete('execute')
        setSearchParams(searchParams, { replace: true })
        if (shouldAutoExecute) {
          setExecuteDialogOpen(true)
        }
      } catch (err) {
        showToast.error(err instanceof Error ? err.message : 'Failed to load strategy')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [searchParams, setSearchParams])

  const saveOrUpdateStrategy = useCallback(
    async (name: string, watchlist: Watchlist) => {
      if (legs.length === 0) {
        showToast.error('Add at least one leg before saving')
        return
      }
      setIsSaving(true)
      try {
        // Strip volatile runtime-only fields we don't need to persist.
        const legPayload = legs.map((l) => ({
          id: l.id,
          segment: l.segment,
          side: l.side,
          lots: l.lots,
          lotSize: l.lotSize,
          expiry: l.expiry,
          strike: l.strike,
          optionType: l.optionType,
          price: l.price,
          iv: l.iv,
          active: l.active,
          symbol: l.symbol,
          equityExchange: l.equityExchange,
          exitPrice: l.exitPrice,
        }))
        const payload = {
          name,
          watchlist,
          underlying: selectedUnderlying,
          exchange: selectedExchange,
          expiry: selectedExpiry || null,
          legs: legPayload,
        }
        const saved = loadedEntry
          ? await strategyPortfolioApi.update(loadedEntry.id, payload)
          : await strategyPortfolioApi.create(payload)
        setLoadedEntry(saved)
        setSaveDialogOpen(false)
        showToast.success(loadedEntry ? 'Strategy updated' : 'Strategy saved')
      } finally {
        setIsSaving(false)
      }
    },
    [legs, selectedExchange, selectedUnderlying, selectedExpiry, loadedEntry]
  )

  return (
    <div className="space-y-3 py-2">
      {/* Page header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-bold tracking-tight text-foreground">Strategy Builder</h1>
          {loadedEntry && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-cat-2/30 bg-cat-2/10 px-2.5 py-0.5 text-[11px] font-semibold text-cat-2">
              <span className="h-1.5 w-1.5 rounded-full bg-cat-2" />
              {loadedEntry.name}
            </span>
          )}
        </div>
        <DocsLink page="strategy-builder" iconOnly />
      </div>

      {/* Symbol header */}
      <SymbolHeader
        assetClass={assetClass}
        onAssetClassChange={setAssetClass}
        exchanges={fnoExchanges}
        selectedExchange={selectedExchange}
        onExchangeChange={handleExchangeChange}
        underlyings={underlyings}
        selectedUnderlying={selectedUnderlying}
        onUnderlyingChange={handleUnderlyingChange}
        underlyingOpen={underlyingOpen}
        onUnderlyingOpenChange={setUnderlyingOpen}
        expiries={expiries}
        selectedExpiry={selectedExpiry}
        onExpiryChange={setSelectedExpiry}
        spotPrice={spotPrice}
        futuresPrice={futuresPrice}
        lotSize={lotSize}
        atmIv={atmIv}
        daysToExpiry={rawDays}
        onRefresh={loadOptionChain}
        isRefreshing={isRefreshing}
        equityExchanges={equityExchanges}
        equityExchange={equityExchange}
        equitySymbol={equitySymbol}
        onEquitySymbolChange={handleEquitySymbolChange}
        apiKey={apiKey ?? ''}
        equityOpen={equityQuoteRest.open}
        equityHigh={equityQuoteRest.high}
        equityLow={equityQuoteRest.low}
        equityVolume={equityQuoteRest.volume}
      />

      {/* Missing Master Contract warning */}
      {!isExpiriesLoading && expiries.length === 0 && apiKey && selectedUnderlying && (
        <div className="rounded-xl border border-warning/20 bg-gradient-to-br from-warning/10 via-warning/5 to-transparent p-4 shadow-sm backdrop-blur-sm animate-in fade-in slide-in-from-top-2 duration-300">
          <div className="flex gap-3">
            <AlertTriangle className="h-5 w-5 text-warning shrink-0 mt-0.5" />
            <div className="space-y-1">
              <h4 className="text-sm font-semibold text-warning">F&O Master Contracts Missing</h4>
              <p className="text-xs text-muted-foreground leading-relaxed max-w-2xl">
                We couldn't find any active options or futures contracts for{' '}
                <span className="font-semibold text-foreground">{selectedUnderlying}</span> on
                exchange <span className="font-semibold text-foreground">{selectedExchange}</span>.
                This usually means the broker's symbol database has not been downloaded yet.
              </p>
              <div className="pt-2 flex items-center gap-3">
                <Button
                  onClick={() => navigate('/master-contract')}
                  size="sm"
                  className="bg-warning text-black hover:bg-warning font-semibold"
                >
                  Go to Master Contract
                </Button>
                <button
                  type="button"
                  onClick={() => {
                    const current = selectedUnderlying
                    setSelectedUnderlying('')
                    setTimeout(() => setSelectedUnderlying(current), 50)
                  }}
                  className="text-xs font-medium text-muted-foreground hover:text-foreground underline underline-offset-4"
                >
                  Retry Fetch
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Template-loading banner — shown while chain is still fetching when
          we arrived here via the AI Wizard with a ?template= param. Clears
          automatically once the template effect fires and removes the param. */}
      {searchParams.get('template') && (
        <div className="flex items-center gap-3 rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 shadow-sm">
          <Loader2 className="h-4 w-4 animate-spin text-primary shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-foreground">Loading strategy template…</p>
            <p className="text-xs text-muted-foreground">
              Fetching live option chain. Your strategy legs will be pre-filled automatically once
              the data is ready.
            </p>
          </div>
        </div>
      )}

      {/* Template grid — Options keeps the existing strike/expiry-shaped
          library; Equity gets simple trade templates; Futures has no
          template concept yet. */}
      <div className="overflow-hidden rounded-xl border bg-card p-5 shadow-sm">
        {assetClass === 'Options' && (
          <TemplateGrid
            direction={direction}
            onDirectionChange={setDirection}
            onPick={handleTemplatePick}
          />
        )}
        {assetClass === 'Equity' && <EquityTemplateGrid onPick={handleEquityTemplatePick} />}
        {assetClass === 'Futures' && (
          <div className="flex flex-col items-center justify-center gap-1 py-10 text-center">
            <p className="text-sm font-medium text-muted-foreground">
              Futures templates coming soon
            </p>
            <p className="text-xs text-muted-foreground/80">
              Add a futures position manually below in the meantime.
            </p>
          </div>
        )}
      </div>

      {/* Manual leg adder */}
      <ManualLegBuilder
        assetClass={assetClass as 'Equity' | 'Futures' | 'Options'}
        expiries={expiries}
        futureExpiries={futureExpiries}
        chain={chainData?.chain ?? null}
        selectedExpiry={selectedExpiry}
        atmStrike={atmStrike}
        strikeStep={strikeStep}
        apiKey={apiKey ?? ''}
        equitySymbol={equitySymbol}
        equityExchange={equityExchange}
        equityLivePrice={equityLivePrice}
        equityPrefill={equityTemplatePrefill}
        onAdd={handleAddManualLeg}
      />

      {/* Main working area — only revealed once the user has at least one leg.
          This avoids an empty-looking Strategy Positions panel and a flat
          payoff chart on first load, which looked like a broken state. */}
      {legs.length === 0 ? (
        <div className="relative overflow-hidden rounded-xl border border-dashed bg-gradient-to-br from-muted/30 via-background to-muted/20 px-6 py-14 shadow-sm">
          {/* Decorative floating icons */}
          <div className="pointer-events-none absolute -left-4 top-6 h-16 w-16 rounded-full bg-profit/5 blur-2xl" />
          <div className="pointer-events-none absolute right-12 top-10 h-20 w-20 rounded-full bg-cat-2/10 blur-3xl" />
          <div className="pointer-events-none absolute bottom-4 left-1/2 h-20 w-40 -translate-x-1/2 rounded-full bg-info/5 blur-3xl" />

          <div className="relative mx-auto max-w-xl space-y-4 text-center">
            <div className="mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl border bg-background shadow-sm">
              <div className="relative">
                <BarChart3 className="h-7 w-7 text-cat-2/60" />
                <span className="absolute -right-1 -top-1 inline-flex h-3 w-3 items-center justify-center rounded-full bg-profit ring-2 ring-background">
                  <TrendingUp className="h-2 w-2 text-white" />
                </span>
              </div>
            </div>

            <div className="space-y-1.5">
              <h3 className="text-base font-semibold">Your canvas awaits</h3>
              <p className="mx-auto max-w-md text-[13px] text-muted-foreground">
                {assetClass === 'Equity'
                  ? 'Pick a trade template above, or add a position manually. Trade preview and live P&L will materialize here.'
                  : 'Pick a pre-built strategy above, or add a position manually. Payoff chart, Greeks and live P&L will materialize here.'}
              </p>
            </div>

            <div className="flex flex-wrap items-center justify-center gap-2 pt-2">
              {assetClass === 'Equity' ? (
                <>
                  <span className="inline-flex items-center gap-1 rounded-full border bg-background/80 px-2.5 py-1 text-[10px] font-medium text-muted-foreground">
                    <TrendingUp className="h-3 w-3" /> Trade preview
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full border bg-background/80 px-2.5 py-1 text-[10px] font-medium text-muted-foreground">
                    <LineChart className="h-3 w-3" /> Live P&amp;L
                  </span>
                </>
              ) : (
                <>
                  <span className="inline-flex items-center gap-1 rounded-full border bg-background/80 px-2.5 py-1 text-[10px] font-medium text-muted-foreground">
                    <LineChart className="h-3 w-3" /> Payoff diagrams
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full border bg-background/80 px-2.5 py-1 text-[10px] font-medium text-muted-foreground">
                    <Sparkles className="h-3 w-3" /> Greeks &amp; IV
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full border bg-background/80 px-2.5 py-1 text-[10px] font-medium text-muted-foreground">
                    <TrendingUp className="h-3 w-3" /> What-if sims
                  </span>
                </>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[360px_minmax(0,1fr)]">
          {/* Left column: positions */}
          <div className="min-w-0">
            <PositionsPanel
              assetClass={assetClass as 'Equity' | 'Futures' | 'Options'}
              legs={legs}
              onToggleLeg={toggleLeg}
              onToggleSide={toggleLegSide}
              onEditLeg={setEditLegId}
              onRemoveLeg={removeLeg}
              onToggleAll={toggleAll}
              onReset={resetLegs}
              probOfProfit={pop}
              maxProfit={payoff.maxProfit}
              maxLoss={payoff.maxLoss}
              breakevens={payoff.breakevens}
              totalPnl={totalPnlNow}
              netCredit={credit}
              estPremium={premium}
              marginRequired={marginRequired}
              isMarginLoading={isMarginLoading}
              marginSupported={marginSupported}
              atmStrike={atmStrike}
              strikeStep={strikeStep}
              onSaveStrategy={() => setSaveDialogOpen(true)}
              onExecute={() => setExecuteDialogOpen(true)}
              isUpdating={loadedEntry !== null}
              executeDisabled={!apiKey}
            />
          </div>

          {/* Right column: tabs + simulators */}
          <div className="min-w-0 space-y-5">
            {/* key=assetClass forces a remount when switching asset class —
                Tabs is uncontrolled (defaultValue), and Equity/Options render
                a different set of TabsTrigger values, so a stale internal
                selection (e.g. "greeks" surviving into Equity mode where
                that trigger no longer exists) would otherwise show a blank
                pane until the user manually clicks a visible tab. */}
            <Tabs
              key={assetClass}
              defaultValue={assetClass === 'Equity' ? 'tradepreview' : 'payoff'}
              className="w-full"
            >
              {/* Tabs on the left, Save/Portfolio actions aligned to the right
                  so they're always visible directly above the Payoff graph —
                  no scrolling back to the page header. */}
              <div className="flex flex-wrap items-center justify-between gap-3">
                <TabsList className="inline-flex h-10 gap-1 rounded-xl border bg-card p-1 shadow-sm">
                  {assetClass === 'Equity' ? (
                    <>
                      <TabsTrigger
                        value="tradepreview"
                        className="rounded-lg px-4 text-xs font-semibold data-[state=active]:bg-gradient-to-br data-[state=active]:from-background data-[state=active]:to-muted/60 data-[state=active]:shadow-sm"
                      >
                        <LineChart className="mr-1.5 h-3.5 w-3.5" />
                        Trade Preview
                      </TabsTrigger>
                      <TabsTrigger
                        value="pnl"
                        className="rounded-lg px-4 text-xs font-semibold data-[state=active]:bg-gradient-to-br data-[state=active]:from-background data-[state=active]:to-muted/60 data-[state=active]:shadow-sm"
                      >
                        <TrendingUp className="mr-1.5 h-3.5 w-3.5" />
                        P&amp;L
                      </TabsTrigger>
                    </>
                  ) : (
                    <>
                      <TabsTrigger
                        value="payoff"
                        className="rounded-lg px-4 text-xs font-semibold data-[state=active]:bg-gradient-to-br data-[state=active]:from-background data-[state=active]:to-muted/60 data-[state=active]:shadow-sm"
                      >
                        <LineChart className="mr-1.5 h-3.5 w-3.5" />
                        Payoff
                      </TabsTrigger>
                      <TabsTrigger
                        value="greeks"
                        className="rounded-lg px-4 text-xs font-semibold data-[state=active]:bg-gradient-to-br data-[state=active]:from-background data-[state=active]:to-muted/60 data-[state=active]:shadow-sm"
                      >
                        <Sparkles className="mr-1.5 h-3.5 w-3.5" />
                        Greeks
                      </TabsTrigger>
                      <TabsTrigger
                        value="pnl"
                        className="rounded-lg px-4 text-xs font-semibold data-[state=active]:bg-gradient-to-br data-[state=active]:from-background data-[state=active]:to-muted/60 data-[state=active]:shadow-sm"
                      >
                        <TrendingUp className="mr-1.5 h-3.5 w-3.5" />
                        P&amp;L
                      </TabsTrigger>
                      <TabsTrigger
                        value="strategychart"
                        className="rounded-lg px-4 text-xs font-semibold data-[state=active]:bg-gradient-to-br data-[state=active]:from-background data-[state=active]:to-muted/60 data-[state=active]:shadow-sm"
                      >
                        <Activity className="mr-1.5 h-3.5 w-3.5" />
                        Strategy Chart
                      </TabsTrigger>
                      <TabsTrigger
                        value="multistrikeoi"
                        className="rounded-lg px-4 text-xs font-semibold data-[state=active]:bg-gradient-to-br data-[state=active]:from-background data-[state=active]:to-muted/60 data-[state=active]:shadow-sm"
                      >
                        <Layers className="mr-1.5 h-3.5 w-3.5" />
                        Multi Strike OI
                      </TabsTrigger>
                    </>
                  )}
                </TabsList>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => navigate('/visual-builder/portfolio')}
                    className="h-10 gap-1.5 px-4 text-xs font-semibold"
                  >
                    <Briefcase className="h-3.5 w-3.5" />
                    Portfolio
                  </Button>
                </div>
              </div>
              {assetClass === 'Equity' ? (
                <>
                  <TabsContent value="tradepreview" className="pt-4">
                    <TradePreview
                      leg={legs.find((l) => l.active && l.segment === 'EQUITY') ?? null}
                      targetPrice={
                        legs.find((l) => l.active && l.segment === 'EQUITY')?.equityTargetPrice
                      }
                      slPrice={legs.find((l) => l.active && l.segment === 'EQUITY')?.equitySlPrice}
                      currentPrice={equityLivePrice ?? undefined}
                    />
                  </TabsContent>
                  <TabsContent value="pnl" className="pt-4">
                    <PnLTab
                      legs={legs}
                      fnoExchange={fnoExchange}
                      fallbackPrices={fallbackPricesByLeg}
                    />
                  </TabsContent>
                </>
              ) : (
                <>
                  <TabsContent value="payoff" className="pt-4">
                    <div className="overflow-hidden rounded-xl border bg-card p-2 shadow-sm">
                      {spotPrice ? (
                        <PayoffChart
                          title={`${selectedUnderlying} — ${selectedExpiry || '—'}`}
                          spot={spotPrice}
                          atmIv={atmIv ?? 0}
                          tYears={simulatedYearsToNearExpiry}
                          payoff={payoff}
                        />
                      ) : (
                        <div className="flex h-[440px] items-center justify-center text-sm text-muted-foreground">
                          Load an option chain to see the payoff chart.
                        </div>
                      )}
                    </div>
                  </TabsContent>
                  <TabsContent value="greeks" className="pt-4">
                    <GreeksTab legs={legs} greeksByLeg={greeksByLeg} />
                  </TabsContent>
                  <TabsContent value="pnl" className="pt-4">
                    <PnLTab
                      legs={legs}
                      fnoExchange={fnoExchange}
                      fallbackPrices={fallbackPricesByLeg}
                    />
                  </TabsContent>
                  <TabsContent value="strategychart" className="pt-4">
                    <StrategyChartTab
                      underlying={selectedUnderlying}
                      exchange={selectedExchange}
                      legs={legs}
                      optionExchange={fnoExchange}
                    />
                  </TabsContent>
                  <TabsContent value="multistrikeoi" className="pt-4">
                    <MultiStrikeOITab
                      underlying={selectedUnderlying}
                      exchange={selectedExchange}
                      legs={legs}
                      optionExchange={fnoExchange}
                    />
                  </TabsContent>
                </>
              )}
            </Tabs>

            {assetClass !== 'Equity' && (
              <Simulators
                spotShiftPct={spotShiftPct}
                ivShiftPct={ivShiftPct}
                daysElapsed={daysElapsed}
                maxDays={maxSimulatorDays}
                onSpotShiftChange={setSpotShiftPct}
                onIvShiftChange={setIvShiftPct}
                onDaysElapsedChange={setDaysElapsed}
                onReset={resetSimulators}
              />
            )}
          </div>
        </div>
      )}

      <TemplateDialog
        open={templateDialogOpen}
        onOpenChange={setTemplateDialogOpen}
        template={activeTemplate}
        expiry={selectedExpiry}
        expiries={expiries}
        onExpiryChange={setSelectedExpiry}
        chain={chainData?.chain ?? null}
        atmStrike={atmStrike}
        strikeStep={strikeStep}
        onConfirm={handleTemplateConfirm}
      />

      <EditLegDialog
        open={editLegId !== null}
        onOpenChange={(open) => {
          if (!open) setEditLegId(null)
        }}
        leg={legs.find((l) => l.id === editLegId) ?? null}
        optionExpiries={expiries}
        futureExpiries={futureExpiries}
        chain={chainData?.chain ?? null}
        chainExpiry={selectedExpiry}
        underlying={selectedUnderlying}
        optionExchange={optionExchangeFor(selectedExchange)}
        apiKey={apiKey ?? ''}
        atmStrike={atmStrike}
        strikeStep={strikeStep}
        onSave={saveEditedLeg}
        onDelete={removeLeg}
      />

      <SaveStrategyDialog
        open={saveDialogOpen}
        onOpenChange={setSaveDialogOpen}
        onSave={saveOrUpdateStrategy}
        defaultName={loadedEntry?.name ?? ''}
        defaultWatchlist={loadedEntry?.watchlist ?? 'mytrades'}
        isUpdate={loadedEntry !== null}
        busy={isSaving}
      />

      <ExecuteBasketDialog
        open={executeDialogOpen}
        onOpenChange={setExecuteDialogOpen}
        legs={legs}
        exchange={optionExchangeFor(selectedExchange)}
        strategyName={computedStrategyName}
        tickSizeBySymbol={tickSizeBySymbol}
        apiKey={apiKey ?? ''}
        onLegNotFilled={removeLeg}
      />
    </div>
  )
}
