import { Check, ChevronsUpDown, Loader2, RefreshCw, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { apiClient } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

interface EquitySearchResult {
  symbol: string
  exchange: string
  name: string
  lotsize: number
}

export interface SymbolHeaderProps {
  assetClass: string
  onAssetClassChange: (v: string) => void

  exchanges: Array<{ value: string; label: string }>
  selectedExchange: string
  onExchangeChange: (v: string) => void

  underlyings: string[]
  selectedUnderlying: string
  onUnderlyingChange: (u: string) => void
  underlyingOpen: boolean
  onUnderlyingOpenChange: (open: boolean) => void

  expiries: string[]
  selectedExpiry: string
  onExpiryChange: (e: string) => void

  spotPrice: number | null
  futuresPrice: number | null
  lotSize: number | null
  atmIv: number | null
  daysToExpiry: number | null

  onRefresh: () => void
  isRefreshing: boolean

  /** Equity mode only — cash-segment exchanges (NSE/BSE), distinct from the
   * F&O `exchanges` list above since equity doesn't trade on NFO/BFO. */
  equityExchanges: Array<{ value: string; label: string }>
  equityExchange: string
  equitySymbol: string
  onEquitySymbolChange: (symbol: string, exchange: string) => void
  /** Max Algos API key — needed for the equity symbol search lookup. */
  apiKey: string

  /** Equity mode only — OHLCV from the /quotes REST seed (StrategyBuilder.tsx). */
  equityOpen?: number | null
  equityHigh?: number | null
  equityLow?: number | null
  equityVolume?: number | null
}

interface MetricCellProps {
  label: string
  value: string
  sub?: string
  tone?: 'primary' | 'profit' | 'warn' | 'muted'
  accent?: boolean
}

function MetricCell({ label, value, sub, tone = 'muted', accent = false }: MetricCellProps) {
  return (
    <div
      className={cn(
        'relative flex flex-col justify-center gap-1 px-4 py-3 transition',
        accent && 'bg-gradient-to-b from-background to-muted/20'
      )}
    >
      <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </span>
      <span
        className={cn(
          'font-semibold tabular-nums leading-none',
          accent ? 'text-2xl tracking-tight' : 'text-base',
          tone === 'primary' && 'text-foreground',
          tone === 'profit' && 'text-profit',
          tone === 'warn' && 'text-warning',
          tone === 'muted' && 'text-foreground'
        )}
      >
        {value}
      </span>
      {sub && <span className="text-[10px] font-medium text-muted-foreground">{sub}</span>}
    </div>
  )
}

export function SymbolHeader({
  assetClass,
  onAssetClassChange,
  exchanges,
  selectedExchange,
  onExchangeChange,
  underlyings,
  selectedUnderlying,
  onUnderlyingChange,
  underlyingOpen,
  onUnderlyingOpenChange,
  expiries,
  selectedExpiry,
  onExpiryChange,
  spotPrice,
  futuresPrice,
  lotSize,
  atmIv,
  daysToExpiry,
  onRefresh,
  isRefreshing,
  equityExchanges,
  equityExchange,
  equitySymbol,
  onEquitySymbolChange,
  apiKey,
  equityOpen,
  equityHigh,
  equityLow,
  equityVolume,
}: SymbolHeaderProps) {
  const hasData = spotPrice !== null
  const isEquity = assetClass === 'Equity'

  // Equity symbol search — same /search endpoint ManualLegBuilder's EQUITY
  // leg-add already uses, kept local to this component since it's only
  // relevant while assetClass === 'Equity'.
  const [equityQuery, setEquityQuery] = useState(equitySymbol)
  const [equityResults, setEquityResults] = useState<EquitySearchResult[]>([])
  const [isEquitySearching, setIsEquitySearching] = useState(false)
  const [equitySearchOpen, setEquitySearchOpen] = useState(false)

  useEffect(() => {
    setEquityQuery(equitySymbol)
  }, [equitySymbol])

  useEffect(() => {
    if (!isEquity || !equityQuery.trim() || equityQuery.trim().length < 2 || !apiKey) {
      setEquityResults([])
      return
    }
    if (equityQuery === equitySymbol) {
      // Just re-selected the current symbol — don't re-search.
      setEquityResults([])
      return
    }
    let cancelled = false
    setIsEquitySearching(true)
    const handle = setTimeout(async () => {
      try {
        const res = await apiClient.post<{ status: string; data?: EquitySearchResult[] }>(
          '/search',
          { apikey: apiKey, query: equityQuery.trim(), exchange: equityExchange }
        )
        if (cancelled) return
        if (res.data.status === 'success' && res.data.data) {
          setEquityResults(res.data.data.slice(0, 15))
        } else {
          setEquityResults([])
        }
      } catch {
        if (!cancelled) setEquityResults([])
      } finally {
        if (!cancelled) setIsEquitySearching(false)
      }
    }, 300)
    return () => {
      cancelled = true
      clearTimeout(handle)
    }
  }, [equityQuery, equitySymbol, isEquity, apiKey, equityExchange])

  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
      {/* Top bar — breadcrumb-style selectors + live status */}
      <div className="flex flex-wrap items-center gap-3 border-b bg-gradient-to-r from-muted/40 via-background to-background px-4 py-2.5">
        <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          Analyzing
        </span>

        <div className="inline-flex items-stretch overflow-hidden rounded-lg border bg-background divide-x">
          {/* Asset Class */}
          <Select value={assetClass} onValueChange={onAssetClassChange}>
            <SelectTrigger className="h-9 w-[100px] rounded-none border-0 bg-transparent text-xs font-semibold focus:ring-0 focus:ring-offset-0">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="Equity">Equity</SelectItem>
              <SelectItem value="Futures">Futures</SelectItem>
              <SelectItem value="Options">Options</SelectItem>
            </SelectContent>
          </Select>

          {/* Exchange — Equity trades cash segment (NSE/BSE), not NFO/BFO */}
          <Select
            value={isEquity ? equityExchange : selectedExchange}
            onValueChange={(v) =>
              isEquity ? onEquitySymbolChange(equitySymbol, v) : onExchangeChange(v)
            }
          >
            <SelectTrigger className="h-9 w-[92px] rounded-none border-0 bg-transparent text-xs font-semibold focus:ring-0 focus:ring-offset-0">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(isEquity ? equityExchanges : exchanges).map((e) => (
                <SelectItem key={e.value} value={e.value}>
                  {e.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Underlying — Equity gets a live symbol search (thousands of
              stocks, can't be a static list); Options/Futures keep the
              small hard-coded underlyings dropdown. */}
          {isEquity ? (
            <Popover open={equitySearchOpen} onOpenChange={setEquitySearchOpen}>
              <PopoverTrigger asChild>
                <Button
                  variant="ghost"
                  role="combobox"
                  aria-expanded={equitySearchOpen}
                  className="h-9 w-[168px] justify-between rounded-none border-0 bg-transparent px-3 text-xs font-bold tracking-wide hover:bg-muted/40"
                >
                  <span className="flex items-center gap-1.5 truncate">
                    <Search className="h-3 w-3 shrink-0 opacity-50" />
                    {equitySymbol || 'Search stock...'}
                  </span>
                  <ChevronsUpDown className="ml-2 h-3.5 w-3.5 shrink-0 opacity-50" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-64 p-0">
                <div className="flex flex-col">
                  <div className="relative border-b p-1.5">
                    <Input
                      autoFocus
                      value={equityQuery}
                      onChange={(e) => setEquityQuery(e.target.value)}
                      placeholder="e.g. RELIANCE, INFY"
                      className="h-8 pr-7 text-xs font-medium"
                    />
                    {isEquitySearching && (
                      <Loader2 className="absolute right-4 top-1/2 h-3.5 w-3.5 -translate-y-1/2 animate-spin text-muted-foreground" />
                    )}
                  </div>
                  <div className="max-h-56 overflow-y-auto">
                    {equityResults.length === 0 && !isEquitySearching && (
                      <p className="px-3 py-4 text-center text-xs text-muted-foreground">
                        {equityQuery.trim().length < 2 ? 'Type to search' : 'No symbol found.'}
                      </p>
                    )}
                    {equityResults.map((r) => (
                      <button
                        key={`${r.exchange}:${r.symbol}`}
                        type="button"
                        onClick={() => {
                          onEquitySymbolChange(r.symbol, r.exchange)
                          setEquitySearchOpen(false)
                        }}
                        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs hover:bg-muted"
                      >
                        <span className="font-semibold">{r.symbol}</span>
                        <span className="truncate text-[10px] text-muted-foreground">{r.name}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </PopoverContent>
            </Popover>
          ) : (
            <Popover open={underlyingOpen} onOpenChange={onUnderlyingOpenChange}>
              <PopoverTrigger asChild>
                <Button
                  variant="ghost"
                  role="combobox"
                  aria-expanded={underlyingOpen}
                  className="h-9 w-[168px] justify-between rounded-none border-0 bg-transparent px-3 text-xs font-bold tracking-wide hover:bg-muted/40"
                >
                  {selectedUnderlying || 'Select'}
                  <ChevronsUpDown className="ml-2 h-3.5 w-3.5 opacity-50" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-56 p-0">
                <Command>
                  <CommandInput placeholder="Search symbol..." className="h-9 text-xs" />
                  <CommandList>
                    <CommandEmpty>No symbol found.</CommandEmpty>
                    <CommandGroup>
                      {underlyings.map((u) => (
                        <CommandItem
                          key={u}
                          value={u}
                          onSelect={() => {
                            onUnderlyingChange(u)
                            onUnderlyingOpenChange(false)
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
          )}

          {/* Expiry */}
          {assetClass !== 'Equity' && (
            <Select value={selectedExpiry} onValueChange={onExpiryChange}>
              <SelectTrigger className="h-9 w-[128px] rounded-none border-0 bg-transparent text-xs font-semibold focus:ring-0 focus:ring-offset-0">
                <SelectValue placeholder="Expiry" />
              </SelectTrigger>
              <SelectContent>
                {expiries.map((ex) => (
                  <SelectItem key={ex} value={ex}>
                    {ex}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        <div className="ml-auto flex items-center gap-3">
          {/* Live indicator */}
          <div className="hidden items-center gap-1.5 sm:flex">
            <span className="relative flex h-2 w-2">
              <span
                className={cn(
                  'absolute inline-flex h-full w-full rounded-full opacity-75',
                  hasData ? 'animate-ping bg-profit' : 'bg-muted-foreground/40'
                )}
              />
              <span
                className={cn(
                  'relative inline-flex h-2 w-2 rounded-full',
                  hasData ? 'bg-profit' : 'bg-muted-foreground/60'
                )}
              />
            </span>
            <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              {hasData ? 'Live' : 'Idle'}
            </span>
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={onRefresh}
            disabled={isRefreshing}
            className="h-8 gap-1.5 text-xs"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', isRefreshing && 'animate-spin')} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Metrics grid — hairline divisions, big primary numbers */}
      <div className="grid grid-cols-2 divide-x divide-y sm:grid-cols-3 sm:divide-y-0 lg:grid-cols-5 bg-card">
        <MetricCell
          label={isEquity ? 'LTP' : 'Spot'}
          value={spotPrice !== null ? spotPrice.toFixed(2) : '—'}
          sub={
            isEquity && spotPrice !== null && equityOpen != null
              ? `${spotPrice - equityOpen >= 0 ? '+' : ''}${(spotPrice - equityOpen).toFixed(2)} vs open`
              : undefined
          }
          tone="primary"
          accent
        />
        {isEquity ? (
          <MetricCell label="Open" value={equityOpen != null ? equityOpen.toFixed(2) : '—'} />
        ) : (
          <MetricCell
            label="Futures"
            value={futuresPrice !== null ? futuresPrice.toFixed(2) : '—'}
            sub={
              spotPrice !== null && futuresPrice !== null
                ? `${futuresPrice > spotPrice ? '+' : ''}${(futuresPrice - spotPrice).toFixed(2)}`
                : undefined
            }
            tone="profit"
            accent
          />
        )}
        {isEquity ? (
          <MetricCell
            label="High"
            value={equityHigh != null ? equityHigh.toFixed(2) : '—'}
            tone="profit"
          />
        ) : assetClass === 'Options' ? (
          <MetricCell
            label="ATM IV"
            value={atmIv !== null ? `${atmIv.toFixed(2)}%` : '—'}
            tone="warn"
          />
        ) : (
          <div className="hidden lg:block border-l border-border" />
        )}
        {isEquity ? (
          <MetricCell
            label="Low"
            value={equityLow != null ? equityLow.toFixed(2) : '—'}
            tone="warn"
          />
        ) : (
          <MetricCell
            label="DTE"
            value={daysToExpiry !== null ? `${daysToExpiry.toFixed(0)}` : '—'}
            sub={daysToExpiry !== null ? 'days to expiry' : undefined}
          />
        )}
        {isEquity ? (
          <MetricCell
            label="Volume"
            value={equityVolume != null ? equityVolume.toLocaleString('en-IN') : '—'}
          />
        ) : (
          <MetricCell label="Lot Size" value={lotSize !== null ? String(lotSize) : '—'} />
        )}
      </div>
    </div>
  )
}
