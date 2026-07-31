import {
  Activity,
  ArrowLeft,
  Check,
  ChevronsUpDown,
  Flame,
  Info,
  MinusCircle,
  PlayCircle,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Wand2,
  Zap,
} from 'lucide-react'
import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { showToast } from '@/utils/toast'
import { WIZARD_MATRIX, WIZARD_TO_TEMPLATE_ID } from './wizardMatrix'

import { useAuthStore } from '@/stores/authStore'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'
import { optionChainApi } from '@/api/option-chain'
import { oiProfileApi } from '@/api/oi-profile'
import { useMarketData } from '@/hooks/useMarketData'
import { STRATEGY_TEMPLATES } from '@/lib/strategyTemplates'
import { CATALOG } from '@/lib/marketplace-catalog'
import { ExecuteBasketDialog } from '@/components/trading/ExecuteBasketDialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { buildOptionSymbol, type StrategyLeg } from '@/lib/strategyMath'
import { cn } from '@/lib/utils'

type DirectionOutlook = 'Bullish' | 'Neutral' | 'Bearish'
type VolatilityOutlook = 'Rising' | 'Neutral' | 'Falling'

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

function convertExpiryForSymbol(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
}

export default function StrategyWizard() {
  const navigate = useNavigate()
  const [wizardOutlook, setWizardOutlook] = useState<DirectionOutlook>('Bullish')
  const [wizardVolatility, setWizardVolatility] = useState<VolatilityOutlook>('Neutral')

  const { apiKey } = useAuthStore()
  const {
    toolsFnoExchanges: fnoExchanges,
    defaultToolsFnoExchange: defaultFnoExchange,
    defaultUnderlyings,
  } = useSupportedExchanges()

  // Dynamic asset class / symbols config
  const [selectedExchange, setSelectedExchange] = useState(defaultFnoExchange)
  const [underlyings, setUnderlyings] = useState<string[]>([])
  const [selectedUnderlying, setSelectedUnderlying] = useState('')
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [expiries, setExpiries] = useState<string[]>([])
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [isChainLoading, setIsChainLoading] = useState(false)
  const [chainData, setChainData] = useState<any>(null)

  // Direct Execution Dialog State
  const [executeDialogOpen, setExecuteDialogOpen] = useState(false)
  const [executeLegs, setExecuteLegs] = useState<StrategyLeg[]>([])
  const [executingStrategyName, setExecutingStrategyName] = useState('')

  // Sync exchange fallback
  useEffect(() => {
    setSelectedExchange((prev) =>
      prev && fnoExchanges.some((ex) => ex.value === prev) ? prev : defaultFnoExchange
    )
  }, [defaultFnoExchange, fnoExchanges])

  // Populate underlyings.
  //
  // Guarded to only reset selectedUnderlying when selectedExchange has
  // ACTUALLY changed (via lastExchangeRef), not merely whenever this effect
  // re-runs. Previously this ran its reset-to-fallback logic on every
  // re-run regardless of cause -- defaultUnderlyings is only useMemo-stable
  // on `capabilities` (useSupportedExchanges.ts), and the hardcoded
  // UNDERLYINGS fallback list is index-only (NIFTY/BANKNIFTY/... for NFO,
  // no individual stocks). If this effect fired again after the user had
  // already picked a real stock (e.g. RELIANCE, valid and present in the
  // underlyings dropdown), both the synchronous fallback check (line below)
  // and the async fetch's own re-check silently reset the selection back to
  // NIFTY the moment `prev` didn't happen to be in whichever underlyings
  // list was being compared against at that instant.
  const lastExchangeRef = useRef<string | null>(null)
  useEffect(() => {
    const exchangeChanged = lastExchangeRef.current !== null && lastExchangeRef.current !== selectedExchange
    lastExchangeRef.current = selectedExchange

    const defaults = defaultUnderlyings[selectedExchange] || []
    setUnderlyings((prev) => (exchangeChanged || prev.length === 0 ? defaults : prev))
    if (exchangeChanged) {
      setSelectedUnderlying(defaults[0] || '')
    }

    let cancelled = false
    ;(async () => {
      try {
        const response = await oiProfileApi.getUnderlyings(selectedExchange)
        if (cancelled) return
        if (response.status === 'success' && response.underlyings.length > 0) {
          setUnderlyings(response.underlyings)
          setSelectedUnderlying((prev) =>
            // Keep the current selection if it's already valid (covers both
            // the initial load, where prev is the placeholder default, and
            // a symbol the user already picked that this fetch now confirms)
            // -- only fall back to the first underlying when prev truly
            // isn't in the real, fetched list.
            response.underlyings.includes(prev) ? prev : response.underlyings[0]
          )
        }
      } catch {
        // Keep defaults on failure
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedExchange, defaultUnderlyings])

  // Fetch expiries
  useEffect(() => {
    if (!apiKey || !selectedUnderlying) return
    setExpiries([])
    setSelectedExpiry('')
    setChainData(null)
    let cancelled = false
    ;(async () => {
      try {
        const optionExchange = selectedExchange === 'NSE_INDEX' || selectedExchange === 'NFO' ? 'NFO' : 'BFO'
        const optsRes = await optionChainApi.getExpiries(apiKey, selectedUnderlying, optionExchange, 'options')
        if (cancelled) return
        if (optsRes.status === 'success' && Array.isArray(optsRes.data) && optsRes.data.length > 0) {
          const normalised = Array.from(new Set(optsRes.data.filter(Boolean).map(convertExpiryForSymbol)))
          setExpiries(normalised)
          setSelectedExpiry((prev) => (normalised.includes(prev) ? prev : normalised[0]))
        }
      } catch {
        // non-fatal
      }
    })()
    return () => {
      cancelled = true
    }
  }, [apiKey, selectedUnderlying, selectedExchange])

  // Fetch Option Chain
  const loadOptionChain = useCallback(async () => {
    if (!apiKey || !selectedUnderlying || !selectedExpiry) return
    if (expiries.length > 0 && !expiries.includes(selectedExpiry)) return
    setIsChainLoading(true)
    try {
      const exchange = selectedUnderlying === 'SENSEX' || selectedUnderlying === 'BANKEX' ? 'BSE_INDEX' : 'NSE_INDEX'
      const data = await optionChainApi.getOptionChain(apiKey, selectedUnderlying, exchange, selectedExpiry, 20)
      if (data.status === 'success') {
        setChainData(data)
      } else {
        showToast.error(data.message || 'Failed to load option chain')
      }
    } catch {
      showToast.error('Failed to load option chain')
    } finally {
      setIsChainLoading(false)
    }
  }, [apiKey, selectedExchange, selectedUnderlying, selectedExpiry, expiries])

  useEffect(() => {
    loadOptionChain()
  }, [loadOptionChain])

  // Derive stats
  const spotPrice = chainData?.underlying_ltp ?? null
  const atmStrike = chainData?.atm_strike ?? null
  const lotSize = useMemo(() => {
    if (!chainData?.chain) return null
    const atmRow = chainData.chain.find((s: any) => s.strike === chainData.atm_strike)
    return atmRow?.ce?.lotsize ?? atmRow?.pe?.lotsize ?? null
  }, [chainData])

  const strikeStep = useMemo(() => {
    if (!chainData?.chain || chainData.chain.length < 2) return 50
    const sorted = [...chainData.chain].map((s: any) => s.strike).sort((a: number, b: number) => a - b)
    let minDiff = Infinity
    for (let i = 1; i < sorted.length; i++) {
      const d = sorted[i] - sorted[i - 1]
      if (d > 0 && d < minDiff) minDiff = d
    }
    return Number.isFinite(minDiff) ? minDiff : 50
  }, [chainData])

  const tickSizeBySymbol = useMemo(() => {
    if (!chainData?.chain) return {}
    const map: Record<string, number> = {}
    for (const row of chainData.chain) {
      if (row.ce?.symbol && row.ce.tick_size > 0) map[row.ce.symbol] = row.ce.tick_size
      if (row.pe?.symbol && row.pe.tick_size > 0) map[row.pe.symbol] = row.pe.tick_size
    }
    return map
  }, [chainData])

  // Live WebSocket Market Data
  const optionExchange = useMemo(() => selectedExchange === 'NSE_INDEX' || selectedExchange === 'NFO' ? 'NFO' : 'BFO', [selectedExchange])
  const wsSymbols = useMemo(() => {
    if (!selectedUnderlying) return []
    const underlyingExch = selectedUnderlying === 'SENSEX' || selectedUnderlying === 'BANKEX' ? 'BSE_INDEX' : 'NSE_INDEX'
    const symbols = [{ symbol: selectedUnderlying, exchange: underlyingExch }]
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

  // Merge WS Ticks
  useEffect(() => {
    if (!chainData || wsData.size === 0) return
    const underlyingExch = selectedUnderlying === 'SENSEX' || selectedUnderlying === 'BANKEX' ? 'BSE_INDEX' : 'NSE_INDEX'
    const underlyingWs = wsData.get(`${underlyingExch}:${selectedUnderlying}`)
    let changed = false

    const mergedChain = chainData.chain.map((strike: any) => {
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
  }, [wsData, chainData, selectedUnderlying, optionExchange])

  // Resolve template legs for card preview
  const resolveLegsPreview = useCallback((wizardName: string) => {
    // chainData can lag behind selectedUnderlying while an async
    // loadOptionChain() fetch for the newly-selected symbol is still in
    // flight (e.g. right after switching NIFTY -> SENSEX). Without this
    // check, a strike coincidentally present in both chains (e.g. 24200)
    // would resolve against the STALE chain's rows, silently building a
    // leg for the wrong underlying entirely.
    if (!chainData || atmStrike === null || chainData.underlying !== selectedUnderlying) return []
    const templateId = WIZARD_TO_TEMPLATE_ID[wizardName]
    if (!templateId) return []
    const catalogItem = CATALOG.find((c) => c.id === templateId)
    const optionsTemplateId = catalogItem?.optionsTemplateId
    if (!optionsTemplateId) return []
    const tpl = STRATEGY_TEMPLATES.find((s) => s.id === optionsTemplateId)
    if (!tpl) return []

    const strikes = chainData.chain.map((s: any) => s.strike)
    return tpl.legs.map((leg) => {
      const target = atmStrike + leg.strikeOffset * strikeStep
      const resolvedStrike = nearestStrike(target, strikes) ?? target
      return `${leg.side} 1x ${resolvedStrike} ${leg.optionType}`
    })
  }, [chainData, atmStrike, strikeStep, selectedUnderlying])

  // Handle Direct Execution trigger
  const handleDirectExecute = useCallback((wizardName: string, isUnlimited: boolean) => {
    if (!apiKey) {
      showToast.error('Please configure API Key first')
      return
    }
    if (!chainData || atmStrike === null || !lotSize) {
      showToast.error('Option chain not loaded yet. Please wait.')
      return
    }
    if (chainData.underlying !== selectedUnderlying) {
      // The option chain fetch for the currently selected underlying
      // (triggered by loadOptionChain's useEffect on symbol/exchange
      // change) hasn't resolved yet -- chainData still holds the PREVIOUS
      // symbol's rows. Building order legs from it here would silently
      // place an order for the wrong underlying (e.g. selecting SENSEX but
      // executing a leg resolved from a still-cached NIFTY chain, because a
      // strike value happened to exist in both).
      showToast.error(`Option chain still loading for ${selectedUnderlying}. Please wait a moment and try again.`)
      return
    }
    if (isUnlimited) {
      const confirmed = window.confirm(
        `WARNING: ${wizardName} is classified as an UNLIMITED RISK strategy.\n\nSEBI compliance requires pre-trade SPAN checks. Do you acknowledge the risk and want to proceed?`
      )
      if (!confirmed) return
    }

    const templateId = WIZARD_TO_TEMPLATE_ID[wizardName]
    if (!templateId) {
      showToast.error(`No template mapping found for ${wizardName}`)
      return
    }

    const catalogItem = CATALOG.find((c) => c.id === templateId)
    const optionsTemplateId = catalogItem?.optionsTemplateId
    if (!optionsTemplateId) {
      showToast.error(`No options template found for ${wizardName}`)
      return
    }

    const tpl = STRATEGY_TEMPLATES.find((s) => s.id === optionsTemplateId)
    if (!tpl) {
      showToast.error(`Template structure not found for ${wizardName}`)
      return
    }

    // Resolve template legs
    const baseIdx = Math.max(0, expiries.indexOf(selectedExpiry))
    const strikes = chainData.chain.map((s: any) => s.strike)

    const resolvedLegs: StrategyLeg[] = tpl.legs.map((leg) => {
      const target = atmStrike + leg.strikeOffset * strikeStep
      const resolvedStrike = nearestStrike(target, strikes) ?? target
      
      const offset = leg.expiryOffset ?? 0
      const targetIdx = Math.min(baseIdx + offset, expiries.length - 1)
      const resolvedExpiry = expiries[Math.max(0, targetIdx)] ?? selectedExpiry

      const canUseChain = resolvedExpiry === selectedExpiry
      const row = canUseChain ? chainData.chain.find((s: any) => s.strike === resolvedStrike) : undefined
      const side = leg.optionType === 'CE' ? row?.ce : row?.pe

      const legExpiry = convertExpiryForSymbol(resolvedExpiry)

      return {
        id: Math.random().toString(36).slice(2, 10),
        segment: 'OPTION',
        side: leg.side,
        lots: leg.lots ?? 1,
        lotSize,
        expiry: legExpiry,
        strike: resolvedStrike,
        optionType: leg.optionType,
        price: side?.ltp ?? 0,
        iv: 0,
        active: true,
        symbol: side?.symbol ?? buildOptionSymbol(selectedUnderlying, legExpiry, resolvedStrike, leg.optionType),
      }
    })

    setExecutingStrategyName(`${selectedUnderlying} ${tpl.name} (${selectedExpiry})`)
    setExecuteLegs(resolvedLegs)
    setExecuteDialogOpen(true)
  }, [apiKey, chainData, atmStrike, lotSize, strikeStep, selectedUnderlying, selectedExpiry, expiries])

  const suggestedStrategies = WIZARD_MATRIX[wizardVolatility]?.[wizardOutlook] || []

  return (
    <div className="container mx-auto pb-8 space-y-6 max-w-6xl px-4 sm:px-6">
      {/* Sticky Top Control Bar */}
      <div className="sticky top-0 z-30 -mx-4 sm:-mx-6 px-4 sm:px-6 py-3 bg-background/95 backdrop-blur-md border-b border-border/80 shadow-sm flex flex-col lg:flex-row lg:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground hover:text-foreground transition-colors group px-2 h-8 text-xs"
            asChild
          >
            <Link to="/strategy">
              <ArrowLeft className="h-3.5 w-3.5 mr-1 group-hover:-translate-x-1 transition-transform" />
              Back
            </Link>
          </Button>
          <div className="h-4 w-[1px] bg-border" />
          <h1 className="text-base font-extrabold tracking-tight text-foreground flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            AI Strategy Wizard
          </h1>
        </div>

        {/* Target Asset & Expiry Configuration */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Exchange Dropdown */}
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Exch</span>
            <Select value={selectedExchange} onValueChange={setSelectedExchange}>
              <SelectTrigger className="h-8 w-[95px] bg-background/80 text-xs font-semibold">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {fnoExchanges.map((e) => (
                  <SelectItem key={e.value} value={e.value}>
                    {e.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Underlying Dropdown */}
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Symbol</span>
            <Popover open={underlyingOpen} onOpenChange={setUnderlyingOpen}>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  role="combobox"
                  aria-expanded={underlyingOpen}
                  className="h-8 w-[130px] justify-between bg-background/80 text-xs font-bold px-2.5"
                >
                  {selectedUnderlying || 'Select'}
                  <ChevronsUpDown className="ml-1 h-3.5 w-3.5 shrink-0 opacity-50" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-52 p-0">
                <Command>
                  <CommandInput placeholder="Search symbol..." className="h-8 text-xs" />
                  <CommandList>
                    <CommandEmpty>No symbol found.</CommandEmpty>
                    <CommandGroup>
                      {underlyings.map((u) => (
                        <CommandItem
                          key={u}
                          value={u}
                          onSelect={() => {
                            setSelectedUnderlying(u)
                            setUnderlyingOpen(false)
                          }}
                          className="text-xs font-medium"
                        >
                          <Check
                            className={cn(
                              'mr-2 h-3.5 w-3.5',
                              selectedUnderlying === u ? 'opacity-100' : 'opacity-0'
                            )}
                          />
                          {u}
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>
          </div>

          {/* Expiry Dropdown */}
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Expiry</span>
            <Select value={selectedExpiry} onValueChange={setSelectedExpiry} disabled={expiries.length === 0}>
              <SelectTrigger className="h-8 w-[115px] bg-background/80 text-xs font-semibold">
                <SelectValue placeholder={isChainLoading ? "Loading..." : "Expiry"} />
              </SelectTrigger>
              <SelectContent>
                {expiries.map((ex) => (
                  <SelectItem key={ex} value={ex}>
                    {ex}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Live Market Info Badges */}
          <div className="flex items-center gap-3 border-l border-border/80 pl-3 text-xs">
            <div className="flex items-center gap-1">
              <span className="text-[10px] font-bold uppercase text-muted-foreground">Spot:</span>
              <span className="font-extrabold text-foreground tabular-nums">
                {spotPrice !== null ? spotPrice.toFixed(2) : '—'}
              </span>
            </div>
            <div className="flex items-center gap-1">
              <span className="text-[10px] font-bold uppercase text-muted-foreground">ATM:</span>
              <span className="font-bold text-foreground tabular-nums">
                {atmStrike !== null ? atmStrike : '—'}
              </span>
            </div>
            <div className="flex items-center gap-1">
              <span className="text-[10px] font-bold uppercase text-muted-foreground">Lot:</span>
              <span className="font-semibold text-muted-foreground">
                {lotSize !== null ? lotSize : '—'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Control Matrix Panel */}
      <div className="grid gap-6 md:grid-cols-2">
        {/* 1. Market Direction Selector */}
        <Card className="border border-border/80 bg-card/60 backdrop-blur-md shadow-xl">
          <CardHeader className="pb-4">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/20 text-[11px] text-primary">
                  1
                </span>
                Market Direction Outlook
              </CardTitle>
              <Badge variant="outline" className="text-[10px] font-mono">
                {wizardOutlook}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="grid grid-cols-3 gap-3">
            {(
              [
                {
                  id: 'Bullish',
                  label: 'Bullish',
                  sub: 'Upward Bias',
                  icon: TrendingUp,
                  activeColor:
                    'bg-emerald-500/15 border-emerald-500/50 text-emerald-400 shadow-emerald-500/10',
                },
                {
                  id: 'Neutral',
                  label: 'Neutral',
                  sub: 'Range-bound',
                  icon: MinusCircle,
                  activeColor:
                    'bg-amber-500/15 border-amber-500/50 text-amber-400 shadow-amber-500/10',
                },
                {
                  id: 'Bearish',
                  label: 'Bearish',
                  sub: 'Downward Bias',
                  icon: TrendingDown,
                  activeColor:
                    'bg-rose-500/15 border-rose-500/50 text-rose-400 shadow-rose-500/10',
                },
              ] as const
            ).map((item) => {
              const Icon = item.icon
              const isActive = wizardOutlook === item.id

              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setWizardOutlook(item.id)}
                  className={`relative p-3 rounded-xl border text-center transition-all duration-200 flex flex-col items-center justify-center gap-1.5 cursor-pointer hover:scale-[1.02] ${
                    isActive
                      ? `${item.activeColor} shadow-lg ring-1 ring-primary/30 font-bold`
                      : 'bg-muted/20 border-border/60 text-muted-foreground hover:bg-muted/40 hover:text-foreground'
                  }`}
                >
                  <Icon
                    className={`h-5 w-5 ${isActive ? 'scale-110' : 'opacity-70'} transition-transform`}
                  />
                  <span className="text-sm font-semibold">{item.label}</span>
                  <span className="text-[10px] opacity-75">{item.sub}</span>
                </button>
              )
            })}
          </CardContent>
        </Card>

        {/* 2. Volatility Selector */}
        <Card className="border border-border/80 bg-card/60 backdrop-blur-md shadow-xl">
          <CardHeader className="pb-4">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/20 text-[11px] text-primary">
                  2
                </span>
                Implied Volatility (IV) Outlook
              </CardTitle>
              <Badge variant="outline" className="text-[10px] font-mono">
                {wizardVolatility} IV
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="grid grid-cols-3 gap-3">
            {(
              [
                {
                  id: 'Rising',
                  label: 'Rising',
                  sub: 'High Volatility',
                  icon: Zap,
                  activeColor:
                    'bg-cyan-500/15 border-cyan-500/50 text-cyan-400 shadow-cyan-500/10',
                },
                {
                  id: 'Neutral',
                  label: 'Neutral',
                  sub: 'Stable / Range',
                  icon: Activity,
                  activeColor:
                    'bg-blue-500/15 border-blue-500/50 text-blue-400 shadow-blue-500/10',
                },
                {
                  id: 'Falling',
                  label: 'Falling',
                  sub: 'IV Crush',
                  icon: Flame,
                  activeColor:
                    'bg-purple-500/15 border-purple-500/50 text-purple-400 shadow-purple-500/10',
                },
              ] as const
            ).map((item) => {
              const Icon = item.icon
              const isActive = wizardVolatility === item.id

              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setWizardVolatility(item.id)}
                  className={`relative p-3 rounded-xl border text-center transition-all duration-200 flex flex-col items-center justify-center gap-1.5 cursor-pointer hover:scale-[1.02] ${
                    isActive
                      ? `${item.activeColor} shadow-lg ring-1 ring-primary/30 font-bold`
                      : 'bg-muted/20 border-border/60 text-muted-foreground hover:bg-muted/40 hover:text-foreground'
                  }`}
                >
                  <Icon
                    className={`h-5 w-5 ${isActive ? 'scale-110' : 'opacity-70'} transition-transform`}
                  />
                  <span className="text-sm font-semibold">{item.label}</span>
                  <span className="text-[10px] opacity-75">{item.sub}</span>
                </button>
              )
            })}
          </CardContent>
        </Card>
      </div>

      {/* 3. Recommended Strategies Section */}
      <div className="space-y-4 pt-2">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-3">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-bold uppercase tracking-wider text-foreground flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              Recommended Structures
            </h2>
            <Badge variant="secondary" className="font-mono text-xs px-2.5 py-0.5">
              {suggestedStrategies.length} Options Found
            </Badge>
          </div>
          <div className="text-xs text-muted-foreground flex items-center gap-1.5 font-mono">
            <span>Matrix:</span>
            <span className="font-bold text-foreground">{wizardOutlook}</span>
            <span>+</span>
            <span className="font-bold text-foreground">{wizardVolatility} IV</span>
          </div>
        </div>

        {suggestedStrategies.length === 0 ? (
          <Card className="border border-dashed p-8 text-center bg-muted/10">
            <Info className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
            <p className="text-sm text-muted-foreground">
              No matching strategy structures found for this combination.
            </p>
          </Card>
        ) : (
          <div className="grid gap-5 md:grid-cols-2">
            {suggestedStrategies.map((item) => {
              const isUnlimited = item.risk === 'Unlimited Risk'
              const typeColor =
                item.type === 'CE'
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                  : item.type === 'PE'
                    ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                    : item.type === 'FUT'
                      ? 'bg-blue-500/10 text-blue-400 border-blue-500/30'
                      : 'bg-purple-500/10 text-purple-400 border-purple-500/30'

              return (
                <Card
                  key={item.name}
                  className="group relative border border-border/80 bg-card/70 hover:bg-card hover:border-primary/50 transition-all duration-300 shadow-md hover:shadow-xl rounded-xl overflow-hidden flex flex-col justify-between"
                >
                  <div className="p-5 space-y-4">
                    {/* Title + Badges */}
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span
                            className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${typeColor}`}
                          >
                            {item.type}
                          </span>
                          <CardTitle className="text-lg font-bold text-foreground group-hover:text-primary transition-colors">
                            {item.name}
                          </CardTitle>
                        </div>
                      </div>

                      <div className="flex flex-col items-end gap-1.5">
                        <Badge
                          variant={isUnlimited ? 'destructive' : 'outline'}
                          className={`text-[10px] font-semibold py-0.5 px-2 flex items-center gap-1 ${
                            !isUnlimited
                              ? 'border-emerald-500/40 text-emerald-400 bg-emerald-500/10'
                              : 'bg-rose-500/15 border-rose-500/40 text-rose-400'
                          }`}
                        >
                          {isUnlimited ? (
                            <ShieldAlert className="h-3 w-3" />
                          ) : (
                            <ShieldCheck className="h-3 w-3" />
                          )}
                          {item.risk}
                        </Badge>
                        <Badge
                          variant="secondary"
                          className="text-[10px] font-mono py-0.5 px-2 bg-muted/60"
                        >
                          {item.return}
                        </Badge>
                      </div>
                    </div>

                    {/* Description */}
                    <CardDescription className="text-xs text-muted-foreground leading-relaxed">
                      {item.description}
                    </CardDescription>

                    {/* Legs Preview */}
                    {chainData && atmStrike !== null && (
                      <div className="mt-3 pt-3 border-t border-border/40 space-y-1 bg-muted/10 rounded-lg p-2.5">
                        <span className="text-[9px] font-bold uppercase tracking-wider text-muted-foreground block mb-1">
                          Preview Legs ({selectedUnderlying})
                        </span>
                        {resolveLegsPreview(item.name).map((legText, i) => (
                          <div key={i} className="flex items-center gap-1.5 text-[11px] font-mono font-medium text-foreground">
                            <div className={cn(
                              "w-1.5 h-1.5 rounded-full",
                              legText.startsWith('BUY') ? "bg-profit" : "bg-loss"
                            )} />
                            {legText}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Action Bar */}
                  <div className="p-5 pt-0 flex gap-3">
                    <Button
                      variant="outline"
                      size="sm"
                      className="flex-1 text-xs font-bold py-2.5 rounded-lg border-border hover:bg-muted/40 text-foreground transition-all group/btn flex items-center justify-center gap-1.5 cursor-pointer"
                      onClick={() => {
                        if (isUnlimited) {
                          const confirmed = window.confirm(
                            `WARNING: ${item.name} is classified as an UNLIMITED RISK strategy.\n\nSEBI compliance requires pre-trade SPAN checks. Do you acknowledge the risk and want to proceed?`
                          )
                          if (!confirmed) return
                        }
                        const templateId = WIZARD_TO_TEMPLATE_ID[item.name]
                        if (templateId) {
                          showToast.info(
                            `Opening Visual Builder with ${item.name} pre-filled...`,
                            'strategy'
                          )
                          navigate(
                            `/visual-builder?template=${encodeURIComponent(
                              templateId
                            )}&underlying=${encodeURIComponent(
                              selectedUnderlying
                            )}&expiry=${encodeURIComponent(
                              selectedExpiry
                            )}&exchange=${encodeURIComponent(
                              selectedExchange
                            )}`
                          )
                        } else {
                          showToast.info(
                            `Opening Visual Builder to construct ${item.name}...`,
                            'strategy'
                          )
                          navigate('/visual-builder')
                        }
                      }}
                    >
                      <Wand2 className="h-3.5 w-3.5 text-muted-foreground group-hover/btn:rotate-12 transition-transform" />
                      <span>Builder</span>
                    </Button>

                    <Button
                      variant="default"
                      size="sm"
                      className="flex-1 text-xs font-bold py-2.5 rounded-lg bg-primary hover:bg-primary/90 text-primary-foreground shadow-md transition-all group/btn flex items-center justify-center gap-1.5 cursor-pointer"
                      onClick={() => handleDirectExecute(item.name, isUnlimited)}
                      disabled={!chainData || atmStrike === null}
                    >
                      <PlayCircle className="h-3.5 w-3.5 text-primary-foreground" />
                      <span>Execute</span>
                    </Button>
                  </div>
                </Card>
              )
            })}
          </div>
        )}
      </div>

      <ExecuteBasketDialog
        open={executeDialogOpen}
        onOpenChange={setExecuteDialogOpen}
        legs={executeLegs}
        exchange={optionExchange}
        strategyName={executingStrategyName}
        tickSizeBySymbol={tickSizeBySymbol}
        apiKey={apiKey ?? ''}
      />
    </div>
  )
}
