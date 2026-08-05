import { AlertTriangle, Check, ChevronsUpDown, RefreshCw } from 'lucide-react'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { oiProfileApi } from '@/api/oi-profile'
import { DocsLink } from '@/components/DocsLink'
import {
  BarSettingsDropdown,
  ColumnConfigDropdown,
  ColumnReorderPanel,
} from '@/components/option-chain'
import { PlaceOrderDialog } from '@/components/trading'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useOptionChainLive } from '@/hooks/useOptionChainLive'
import { useOptionChainPreferences } from '@/hooks/useOptionChainPreferences'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import type { BarDataSource, BarStyle, ColumnKey, OptionStrike } from '@/types/option-chain'
import { COLUMN_DEFINITIONS } from '@/types/option-chain'
import { showToast } from '@/utils/toast'

// FNO_EXCHANGES and DEFAULT_UNDERLYINGS are now provided by useSupportedExchanges() hook

const STRIKE_COUNTS = [
  { value: 5, label: '5 strikes' },
  { value: 10, label: '10 strikes' },
  { value: 15, label: '15 strikes' },
  { value: 20, label: '20 strikes' },
  { value: 25, label: '25 strikes' },
]

// Format number in lakhs (divide by 100000)
function formatInLakhs(num: number | undefined | null): string {
  if (num === undefined || num === null || num === 0) return '0'
  const lakhs = num / 100000
  if (lakhs >= 100) {
    return `${lakhs.toFixed(0)}L`
  } else if (lakhs >= 10) {
    return `${lakhs.toFixed(1)}L`
  } else if (lakhs >= 1) {
    return `${lakhs.toFixed(2)}L`
  } else {
    // Less than 1 lakh, show in thousands
    const thousands = num / 1000
    if (thousands >= 1) {
      return `${thousands.toFixed(1)}K`
    }
    return num.toLocaleString()
  }
}

function formatPrice(num: number | undefined | null): string {
  if (num === undefined || num === null) return '0.00'
  return num.toFixed(2)
}

function convertExpiryForAPI(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
}

function calculateMaxPain(chain: OptionStrike[]): number | null {
  if (chain.length === 0) return null
  let minPain = Infinity
  let maxPainStrike: number | null = null

  // For each candidate expiry strike, total option-writer payout if the
  // underlying settles there: every ITM call/put pays out (settle - strike)
  // * OI to whoever holds it, at the writer's expense. The strike with the
  // lowest aggregate payout is where option writers ("the house") have the
  // least pain -- computed directly off the already-loaded chain so this
  // needs no extra API call.
  chain.forEach((candidate) => {
    let pain = 0
    chain.forEach((strike) => {
      if (strike.ce?.oi) {
        pain += Math.max(0, candidate.strike - strike.strike) * strike.ce.oi
      }
      if (strike.pe?.oi) {
        pain += Math.max(0, strike.strike - candidate.strike) * strike.pe.oi
      }
    })
    if (pain < minPain) {
      minPain = pain
      maxPainStrike = candidate.strike
    }
  })

  return maxPainStrike
}

function calculatePCR(chain: OptionStrike[]): number {
  let totalCeOi = 0
  let totalPeOi = 0

  chain.forEach((strike) => {
    if (strike.ce?.oi) totalCeOi += strike.ce.oi
    if (strike.pe?.oi) totalPeOi += strike.pe?.oi ?? 0
  })

  if (totalCeOi === 0) return 0
  return totalPeOi / totalCeOi
}

function calculateTotals(chain: OptionStrike[]): {
  ceVolume: number
  peVolume: number
  ceOi: number
  peOi: number
} {
  let ceVolume = 0
  let peVolume = 0
  let ceOi = 0
  let peOi = 0

  chain.forEach((strike) => {
    if (strike.ce) {
      ceVolume += strike.ce.volume ?? 0
      ceOi += strike.ce.oi ?? 0
    }
    if (strike.pe) {
      peVolume += strike.pe.volume ?? 0
      peOi += strike.pe.oi ?? 0
    }
  })

  return { ceVolume, peVolume, ceOi, peOi }
}

function getMaxValue(chain: OptionStrike[], dataSource: BarDataSource): number {
  let maxVal = 0
  chain.forEach((strike) => {
    const ceVal = dataSource === 'oi' ? strike.ce?.oi : strike.ce?.volume
    const peVal = dataSource === 'oi' ? strike.pe?.oi : strike.pe?.volume
    if (ceVal && ceVal > maxVal) maxVal = ceVal
    if (peVal && peVal > maxVal) maxVal = peVal
  })
  return maxVal || 1
}

interface PlaceOrderParams {
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  lotSize: number
  tickSize: number
}

interface OptionChainRowProps {
  strike: OptionStrike
  previousStrike: OptionStrike | undefined
  maxBarValue: number
  visibleCeColumns: ColumnKey[]
  visiblePeColumns: ColumnKey[]
  barDataSource: BarDataSource
  barStyle: BarStyle
  optionExchange: string
  onPlaceOrder: (params: PlaceOrderParams) => void
}

// Memoized row component to prevent unnecessary re-renders
const OptionChainRow = React.memo(function OptionChainRow({
  strike,
  previousStrike,
  maxBarValue,
  visibleCeColumns,
  visiblePeColumns,
  barDataSource,
  barStyle,
  optionExchange,
  onPlaceOrder,
}: OptionChainRowProps) {
  const ce = strike.ce
  const pe = strike.pe
  const label = ce?.label ?? pe?.label ?? ''
  const isATM = label === 'ATM'

  // For CE: OTM means strike > ATM (label starts with OTM)
  // For PE: OTM means strike < ATM (which is ITM for CE)
  const isCeOTM = label.startsWith('OTM')
  const isPeOTM = label.startsWith('ITM')

  // Flash animation for LTP changes
  const ceLtpChanged = previousStrike?.ce?.ltp !== undefined && previousStrike.ce.ltp !== ce?.ltp
  const peLtpChanged = previousStrike?.pe?.ltp !== undefined && previousStrike.pe.ltp !== pe?.ltp

  const ceFlashClass = ceLtpChanged
    ? ce && previousStrike?.ce && ce.ltp > previousStrike.ce.ltp
      ? 'bg-profit/30'
      : 'bg-loss/30'
    : ''
  const peFlashClass = peLtpChanged
    ? pe && previousStrike?.pe && pe.ltp > previousStrike.pe.ltp
      ? 'bg-profit/30'
      : 'bg-loss/30'
    : ''

  const ceSpread = ce && ce.bid > 0 && ce.ask > 0 ? ce.ask - ce.bid : 0
  const peSpread = pe && pe.bid > 0 && pe.ask > 0 ? pe.ask - pe.bid : 0

  const ceSpreadClass = ceSpread <= 1 ? 'text-profit' : ceSpread <= 2 ? 'text-warning' : 'text-loss'
  const peSpreadClass = peSpread <= 1 ? 'text-profit' : peSpread <= 2 ? 'text-warning' : 'text-loss'

  // Bar values based on data source
  const ceBarValue = barDataSource === 'oi' ? ce?.oi : ce?.volume
  const peBarValue = barDataSource === 'oi' ? pe?.oi : pe?.volume
  const ceBarPercent = ceBarValue ? Math.min((ceBarValue / maxBarValue) * 100, 100) : 0
  const peBarPercent = peBarValue ? Math.min((peBarValue / maxBarValue) * 100, 100) : 0

  // Bar styles
  const ceBarClass =
    barStyle === 'gradient' ? 'bg-gradient-to-r from-profit/25 to-transparent' : 'bg-profit/20'
  const peBarClass =
    barStyle === 'gradient' ? 'bg-gradient-to-l from-loss/25 to-transparent' : 'bg-loss/20'

  // Use tabular-nums for consistent number widths to prevent layout shifts
  const numClass = 'font-mono tabular-nums text-xs'

  const getCeColumnValue = (key: ColumnKey) => {
    switch (key) {
      case 'ce_oi':
        return <span className={numClass}>{formatInLakhs(ce?.oi)}</span>
      case 'ce_volume':
        return <span className={numClass}>{formatInLakhs(ce?.volume)}</span>
      case 'ce_bid_qty':
        return <span className={numClass}>{ce?.bid_qty ?? 0}</span>
      case 'ce_bid':
        return <span className={cn(numClass, 'text-loss')}>{formatPrice(ce?.bid)}</span>
      case 'ce_ltp':
        return (
          <span className={cn(numClass, 'font-semibold', ceFlashClass)}>
            {formatPrice(ce?.ltp)}
          </span>
        )
      case 'ce_ask':
        return <span className={cn(numClass, 'text-profit')}>{formatPrice(ce?.ask)}</span>
      case 'ce_ask_qty':
        return <span className={numClass}>{ce?.ask_qty ?? 0}</span>
      case 'ce_spread':
        return <span className={cn(numClass, ceSpreadClass)}>{formatPrice(ceSpread)}</span>
      default:
        return null
    }
  }

  const getPeColumnValue = (key: ColumnKey) => {
    switch (key) {
      case 'pe_oi':
        return <span className={numClass}>{formatInLakhs(pe?.oi)}</span>
      case 'pe_volume':
        return <span className={numClass}>{formatInLakhs(pe?.volume)}</span>
      case 'pe_bid_qty':
        return <span className={numClass}>{pe?.bid_qty ?? 0}</span>
      case 'pe_bid':
        return <span className={cn(numClass, 'text-loss')}>{formatPrice(pe?.bid)}</span>
      case 'pe_ltp':
        return (
          <span className={cn(numClass, 'font-semibold', peFlashClass)}>
            {formatPrice(pe?.ltp)}
          </span>
        )
      case 'pe_ask':
        return <span className={cn(numClass, 'text-profit')}>{formatPrice(pe?.ask)}</span>
      case 'pe_ask_qty':
        return <span className={numClass}>{pe?.ask_qty ?? 0}</span>
      case 'pe_spread':
        return <span className={cn(numClass, peSpreadClass)}>{formatPrice(peSpread)}</span>
      default:
        return null
    }
  }

  return (
    <TableRow
      className={cn(
        'hover:bg-muted/50 relative group'
        // No background for ATM and ITM, only OTM gets background
        // CE OTM = strikes above ATM
        // PE OTM = strikes below ATM (which is CE ITM)
      )}
      data-strike={strike.strike}
      data-label={label}
    >
      {/* CE cells */}
      {visibleCeColumns.length > 0 && (
        <TableCell
          className={cn(
            'p-0 relative',
            // OTM Call options get background (strikes above ATM)
            isCeOTM && !isATM && 'bg-warning/5'
          )}
        >
          {/* CE bar - spans the entire CE section */}
          <div
            className={cn(
              'absolute left-0 top-0 bottom-0 pointer-events-none z-0 transition-all duration-300',
              ceBarClass
            )}
            style={{ width: `${ceBarPercent}%` }}
          />
          {/* CE Buy/Sell buttons - appear on hover (positioned near strike) */}
          {ce && (
            <div
              className={cn(
                'absolute right-1 top-1/2 -translate-y-1/2 z-20',
                'flex gap-0.5',
                'opacity-0 group-hover:opacity-100 transition-opacity'
              )}
            >
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onPlaceOrder({
                    symbol: ce.symbol,
                    exchange: optionExchange,
                    action: 'BUY',
                    lotSize: ce.lotsize ?? 1,
                    tickSize: ce.tick_size ?? 0.05,
                  })
                }}
                className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-profit text-white hover:bg-profit"
              >
                B
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onPlaceOrder({
                    symbol: ce.symbol,
                    exchange: optionExchange,
                    action: 'SELL',
                    lotSize: ce.lotsize ?? 1,
                    tickSize: ce.tick_size ?? 0.05,
                  })
                }}
                className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-warning text-white hover:bg-warning"
              >
                S
              </button>
            </div>
          )}
          <div className="relative z-10 flex">
            {visibleCeColumns.map((key) => {
              const colDef = COLUMN_DEFINITIONS.find((c) => c.key === key)
              return (
                <div
                  key={key}
                  className={cn(
                    'flex-1 px-2 py-1.5 min-w-0',
                    colDef?.align === 'right' && 'text-right',
                    colDef?.align === 'center' && 'text-center',
                    colDef?.align === 'left' && 'text-left'
                  )}
                >
                  {getCeColumnValue(key)}
                </div>
              )
            })}
          </div>
        </TableCell>
      )}

      {/* Strike cell - center column */}
      <TableCell
        className={cn(
          'text-center font-bold px-2 py-1.5 text-sm w-20 min-w-20',
          isATM ? 'bg-primary/15' : 'bg-muted/30'
        )}
      >
        {strike.strike}
      </TableCell>

      {/* PE cells */}
      {visiblePeColumns.length > 0 && (
        <TableCell
          className={cn(
            'p-0 relative',
            // OTM Put options get background (strikes below ATM, which is ITM for CE)
            isPeOTM && !isATM && 'bg-warning/5'
          )}
        >
          {/* PE bar - spans the entire PE section from right */}
          <div
            className={cn(
              'absolute right-0 top-0 bottom-0 pointer-events-none z-0 transition-all duration-300',
              peBarClass
            )}
            style={{ width: `${peBarPercent}%` }}
          />
          {/* PE Buy/Sell buttons - appear on hover (positioned near strike) */}
          {pe && (
            <div
              className={cn(
                'absolute left-1 top-1/2 -translate-y-1/2 z-20',
                'flex gap-0.5',
                'opacity-0 group-hover:opacity-100 transition-opacity'
              )}
            >
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onPlaceOrder({
                    symbol: pe.symbol,
                    exchange: optionExchange,
                    action: 'BUY',
                    lotSize: pe.lotsize ?? 1,
                    tickSize: pe.tick_size ?? 0.05,
                  })
                }}
                className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-profit text-white hover:bg-profit"
              >
                B
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onPlaceOrder({
                    symbol: pe.symbol,
                    exchange: optionExchange,
                    action: 'SELL',
                    lotSize: pe.lotsize ?? 1,
                    tickSize: pe.tick_size ?? 0.05,
                  })
                }}
                className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-warning text-white hover:bg-warning"
              >
                S
              </button>
            </div>
          )}
          <div className="relative z-10 flex">
            {visiblePeColumns.map((key) => {
              const colDef = COLUMN_DEFINITIONS.find((c) => c.key === key)
              return (
                <div
                  key={key}
                  className={cn(
                    'flex-1 px-2 py-1.5 min-w-0',
                    colDef?.align === 'right' && 'text-right',
                    colDef?.align === 'center' && 'text-center',
                    colDef?.align === 'left' && 'text-left'
                  )}
                >
                  {getPeColumnValue(key)}
                </div>
              )
            })}
          </div>
        </TableCell>
      )}
    </TableRow>
  )
})

export default function OptionChain() {
  const { apiKey } = useAuthStore()
  const {
    toolsFnoExchanges: fnoExchanges,
    defaultToolsFnoExchange: defaultFnoExchange,
    defaultUnderlyings,
  } = useSupportedExchanges()
  const {
    visibleColumns,
    columnOrder,
    strikeCount,
    selectedUnderlying,
    barDataSource,
    barStyle,
    toggleColumn,
    reorderColumns,
    setStrikeCount,
    setSelectedUnderlying,
    setBarDataSource,
    setBarStyle,
    resetToDefaults,
  } = useOptionChainPreferences()

  const [selectedExchange, setSelectedExchange] = useState(defaultFnoExchange)
  const [underlyings, setUnderlyings] = useState<string[]>(
    defaultUnderlyings[defaultFnoExchange] || []
  )
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [expiries, setExpiries] = useState<string[]>([])
  const [isExpiriesLoading, setIsExpiriesLoading] = useState(false)
  const navigate = useNavigate()
  // Use ref for previous data to avoid causing re-renders and enable proper flash animation
  const previousDataRef = useRef<Map<number, OptionStrike>>(new Map())
  const [orderDialog, setOrderDialog] = useState<{
    open: boolean
    symbol: string
    exchange: string
    action: 'BUY' | 'SELL'
    quantity: number
    lotSize: number
    tickSize: number
  } | null>(null)

  // Re-sync exchange when broker capabilities load asynchronously
  useEffect(() => {
    setSelectedExchange((prev) =>
      prev && fnoExchanges.some((ex) => ex.value === prev) ? prev : defaultFnoExchange
    )
  }, [defaultFnoExchange, fnoExchanges])

  const optionExchange = selectedExchange
  // Send NFO/BFO directly — backend resolves correct exchange for index vs stock
  const exchange = selectedExchange

  const {
    data,
    isStreaming,
    isConnecting,
    isPolling,
    isPaused,
    error,
    wsError,
    lastUpdate,
    refetch,
    isLoading,
    streamingSymbols,
  } = useOptionChainLive(
    apiKey,
    selectedUnderlying,
    exchange,
    optionExchange,
    convertExpiryForAPI(selectedExpiry),
    strikeCount,
    { enabled: !!selectedExpiry, oiRefreshInterval: 30000, pauseWhenHidden: true }
  )

  // Fetch underlyings when exchange changes
  useEffect(() => {
    const defaults = defaultUnderlyings[selectedExchange] || []
    setUnderlyings(defaults)
    setSelectedUnderlying(defaults[0] || '')
    setExpiries([])
    setSelectedExpiry('')

    let cancelled = false
    const fetchUnderlyings = async () => {
      try {
        const response = await oiProfileApi.getUnderlyings(selectedExchange)
        if (cancelled) return
        if (response.status === 'success' && response.underlyings.length > 0) {
          setUnderlyings(response.underlyings)
          if (!response.underlyings.includes(defaults[0])) {
            setSelectedUnderlying(response.underlyings[0])
          }
        }
      } catch {
        // Keep defaults
      }
    }
    fetchUnderlyings()
    return () => {
      cancelled = true
    }
  }, [selectedExchange, defaultUnderlyings[selectedExchange], setSelectedUnderlying])

  // Fetch expiries when underlying changes
  useEffect(() => {
    if (!selectedUnderlying) return
    setIsExpiriesLoading(true)
    setExpiries([])
    setSelectedExpiry('')

    let cancelled = false
    const fetchExpiries = async () => {
      try {
        const response = await oiProfileApi.getExpiries(selectedExchange, selectedUnderlying)
        if (cancelled) return
        if (response.status === 'success' && response.expiries.length > 0) {
          setExpiries(response.expiries)
          setSelectedExpiry(response.expiries[0])
        } else {
          setExpiries([])
          setSelectedExpiry('')
        }
      } catch {
        if (cancelled) return
        showToast.error('Failed to load expiry dates')
      } finally {
        if (!cancelled) {
          setIsExpiriesLoading(false)
        }
      }
    }
    fetchExpiries()
    return () => {
      cancelled = true
    }
  }, [selectedUnderlying, selectedExchange])

  // Update previous data ref after render (for flash animation)
  // Using useEffect to update AFTER the current data is rendered
  useEffect(() => {
    if (data?.chain) {
      // Schedule the ref update for after render so the current render uses old previous data
      const timeoutId = setTimeout(() => {
        const newMap = new Map<number, OptionStrike>()
        data.chain.forEach((strike) => {
          newMap.set(strike.strike, strike)
        })
        previousDataRef.current = newMap
      }, 100) // Short delay to allow flash animation to show
      return () => clearTimeout(timeoutId)
    }
  }, [data?.chain])

  const handleUnderlyingChange = (value: string) => {
    setSelectedUnderlying(value)
    setSelectedExpiry('')
    setExpiries([])
  }

  // Clear underlying / expiry / expiries in the SAME React event as the
  // exchange change, so the next render has expiry='' (which makes the
  // polling hook's enabled flag false) BEFORE useOptionChainPolling's
  // dependency-driven effect fires a fetch with the new exchange and the
  // previous exchange's underlying / expiry.
  const handleExchangeChange = (value: string) => {
    if (value === selectedExchange) return
    setSelectedExchange(value)
    setSelectedUnderlying('')
    setExpiries([])
    setSelectedExpiry('')
  }

  const handleRefresh = () => {
    refetch()
  }

  const handlePlaceOrder = useCallback((params: PlaceOrderParams) => {
    setOrderDialog({
      open: true,
      symbol: params.symbol,
      exchange: params.exchange,
      action: params.action,
      quantity: params.lotSize,
      lotSize: params.lotSize,
      tickSize: params.tickSize,
    })
  }, [])

  // Memoized callback for dialog close to prevent re-renders
  const handleOrderDialogClose = useCallback((open: boolean) => {
    if (!open) setOrderDialog(null)
  }, [])

  const pcr = useMemo(() => (data?.chain ? calculatePCR(data.chain) : 0), [data?.chain])
  const maxPainStrike = useMemo(
    () => (data?.chain ? calculateMaxPain(data.chain) : null),
    [data?.chain]
  )
  const totals = useMemo(
    () =>
      data?.chain ? calculateTotals(data.chain) : { ceVolume: 0, peVolume: 0, ceOi: 0, peOi: 0 },
    [data?.chain]
  )
  const maxBarValue = useMemo(
    () => (data?.chain ? getMaxValue(data.chain, barDataSource) : 1),
    [data?.chain, barDataSource]
  )

  // Get ordered visible columns for each side
  const visibleCeColumns = useMemo(() => {
    return columnOrder.filter((key) => {
      const col = COLUMN_DEFINITIONS.find((c) => c.key === key)
      return col?.side === 'ce' && visibleColumns.includes(key)
    })
  }, [columnOrder, visibleColumns])

  const visiblePeColumns = useMemo(() => {
    return columnOrder.filter((key) => {
      const col = COLUMN_DEFINITIONS.find((c) => c.key === key)
      return col?.side === 'pe' && visibleColumns.includes(key)
    })
  }, [columnOrder, visibleColumns])

  if (error) {
    return (
      <div className="flex items-center justify-center py-16">
        <Card className="max-w-md">
          <CardContent className="p-6">
            <div className="text-center text-loss">
              <h2 className="text-xl font-bold mb-2">Error Loading Option Chain</h2>
              <p>{error}</p>
              <Button onClick={handleRefresh} className="mt-4">
                <RefreshCw className="h-4 w-4 mr-2" />
                Retry
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="py-4 space-y-3">
      {/* Compact filter + live-status bar (replaces the old page title) */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <div className="flex flex-wrap gap-2 items-center">
          <Select value={selectedExchange} onValueChange={handleExchangeChange}>
            <SelectTrigger className="w-24">
              <SelectValue placeholder="Exchange" />
            </SelectTrigger>
            <SelectContent>
              {fnoExchanges.map((ex) => (
                <SelectItem key={ex.value} value={ex.value}>
                  {ex.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Popover open={underlyingOpen} onOpenChange={setUnderlyingOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                role="combobox"
                aria-expanded={underlyingOpen}
                className="w-36 justify-between"
              >
                {selectedUnderlying || 'Select Underlying'}
                <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-48 p-0" align="start">
              <Command>
                <CommandInput placeholder="Search underlying..." />
                <CommandList>
                  <CommandEmpty>No underlying found</CommandEmpty>
                  <CommandGroup>
                    {underlyings.map((u) => (
                      <CommandItem
                        key={u}
                        value={u}
                        onSelect={() => {
                          handleUnderlyingChange(u)
                          setUnderlyingOpen(false)
                        }}
                      >
                        <Check
                          className={`mr-2 h-4 w-4 ${selectedUnderlying === u ? 'opacity-100' : 'opacity-0'}`}
                        />
                        {u}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
          <Select
            value={selectedExpiry}
            onValueChange={setSelectedExpiry}
            disabled={expiries.length === 0}
          >
            <SelectTrigger className="w-36">
              <SelectValue placeholder="Select Expiry" />
            </SelectTrigger>
            <SelectContent>
              {expiries.map((exp) => (
                <SelectItem key={exp} value={exp}>
                  {exp}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={String(strikeCount)} onValueChange={(v) => setStrikeCount(Number(v))}>
            <SelectTrigger className="w-36">
              <SelectValue placeholder="Strike Count" />
            </SelectTrigger>
            <SelectContent>
              {STRIKE_COUNTS.map((sc) => (
                <SelectItem key={sc.value} value={String(sc.value)}>
                  {sc.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <BarSettingsDropdown
            barDataSource={barDataSource}
            barStyle={barStyle}
            onBarDataSourceChange={setBarDataSource}
            onBarStyleChange={setBarStyle}
          />
          <ColumnConfigDropdown
            visibleColumns={visibleColumns}
            onToggleColumn={toggleColumn}
            onResetToDefaults={resetToDefaults}
          />
          <ColumnReorderPanel
            columnOrder={columnOrder}
            visibleColumns={visibleColumns}
            onReorderColumns={reorderColumns}
          />
        </div>

        {/* Live status pill -- replaces the old standalone Refresh button.
            Data streams live over WebSocket; a big manual refresh control
            doesn't match that. Falls back to a small refresh affordance
            only when the feed genuinely isn't live (polling/degraded), so
            there's still a manual escape hatch when auto-refresh isn't
            actually happening. */}
        <div className="flex items-center gap-2">
          <DocsLink page="option-chain" iconOnly />
          {isStreaming ? (
            <Badge
              variant="default"
              className="gap-1.5 bg-profit/15 text-profit border-profit/30 hover:bg-profit/15"
            >
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-profit opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-profit" />
              </span>
              LIVE
              {lastUpdate && (
                <span className="text-muted-foreground font-normal">
                  · {lastUpdate.toLocaleTimeString()}
                </span>
              )}
            </Badge>
          ) : (
            <>
              <Badge
                variant={isConnecting || isPolling || isPaused ? 'secondary' : 'destructive'}
                className={cn(
                  isConnecting && 'bg-warning/10 text-warning border-warning/20 hover:bg-warning/20'
                )}
                title={isPolling && wsError ? wsError : undefined}
              >
                {isPaused
                  ? 'Paused'
                  : isConnecting
                    ? 'Reconnecting…'
                    : isPolling
                      ? 'Polling'
                      : 'Feed Degraded'}
              </Badge>
              <Button
                variant="outline"
                size="sm"
                onClick={handleRefresh}
                disabled={!selectedExpiry || isLoading}
              >
                <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`} />
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Missing Master Contract warning */}
      {!isExpiriesLoading && expiries.length === 0 && selectedUnderlying && (
        <div className="rounded-xl border border-amber-500/20 bg-gradient-to-br from-amber-500/10 via-amber-500/5 to-transparent p-4 shadow-sm backdrop-blur-sm animate-in fade-in slide-in-from-top-2 duration-300">
          <div className="flex gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-500 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <h4 className="text-sm font-semibold text-amber-500">F&O Master Contracts Missing</h4>
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
                  className="bg-amber-500 text-black hover:bg-amber-400 font-semibold"
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

      {data && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
            <Card>
              <CardContent className="p-2.5">
                <div className="text-[11px] text-muted-foreground leading-none">
                  {selectedUnderlying} Spot
                </div>
                <div className="text-lg font-bold text-primary leading-tight mt-1">
                  {formatPrice(data.underlying_ltp)}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-2.5">
                <div className="text-[11px] text-muted-foreground leading-none">ATM Strike</div>
                <div className="text-lg font-bold leading-tight mt-1">{data.atm_strike}</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-2.5">
                <div className="text-[11px] text-muted-foreground leading-none">Max Pain</div>
                <div className="text-lg font-bold leading-tight mt-1">{maxPainStrike ?? '—'}</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-2.5">
                <div className="text-[11px] text-muted-foreground leading-none">PCR</div>
                <div
                  className={cn(
                    'text-lg font-bold leading-tight mt-1',
                    pcr > 1 ? 'text-profit' : 'text-warning'
                  )}
                >
                  {pcr.toFixed(2)}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-2.5">
                <div className="text-[11px] text-muted-foreground leading-none">OI (CE / PE)</div>
                <div className="text-sm font-mono tabular-nums leading-tight mt-1">
                  <span className="text-profit">{formatInLakhs(totals.ceOi)}</span>
                  <span className="mx-1 text-muted-foreground">/</span>
                  <span className="text-loss">{formatInLakhs(totals.peOi)}</span>
                </div>
                <div className="h-1 bg-muted rounded-full overflow-hidden mt-1.5">
                  <div
                    className="h-full bg-gradient-to-r from-profit to-primary transition-all duration-500"
                    style={{
                      width:
                        totals.ceOi + totals.peOi > 0
                          ? `${(totals.ceOi / (totals.ceOi + totals.peOi)) * 100}%`
                          : '0%',
                    }}
                  />
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <Table className="w-full table-fixed">
                  <TableHeader>
                    {/* Section headers row */}
                    <TableRow className="bg-muted/30 border-b-0">
                      {visibleCeColumns.length > 0 && (
                        <TableHead className="text-center text-profit font-bold text-sm border-r border-border">
                          CALLS
                        </TableHead>
                      )}
                      <TableHead className="text-center w-20 min-w-20" />
                      {visiblePeColumns.length > 0 && (
                        <TableHead className="text-center text-loss font-bold text-sm border-l border-border">
                          PUTS
                        </TableHead>
                      )}
                    </TableRow>
                    {/* Column headers row */}
                    <TableRow className="bg-muted/50">
                      {visibleCeColumns.length > 0 && (
                        <TableHead className="p-0 border-r border-border">
                          <div className="flex">
                            {visibleCeColumns.map((key) => {
                              const colDef = COLUMN_DEFINITIONS.find((c) => c.key === key)
                              return (
                                <div
                                  key={key}
                                  className={cn(
                                    'flex-1 px-2 py-2 text-xs font-medium min-w-0',
                                    colDef?.align === 'right' && 'text-right',
                                    colDef?.align === 'center' && 'text-center',
                                    colDef?.align === 'left' && 'text-left'
                                  )}
                                >
                                  {colDef?.label}
                                </div>
                              )
                            })}
                          </div>
                        </TableHead>
                      )}
                      <TableHead className="text-center bg-muted/30 text-xs w-20 min-w-20">
                        Strike
                      </TableHead>
                      {visiblePeColumns.length > 0 && (
                        <TableHead className="p-0 border-l border-border">
                          <div className="flex">
                            {visiblePeColumns.map((key) => {
                              const colDef = COLUMN_DEFINITIONS.find((c) => c.key === key)
                              return (
                                <div
                                  key={key}
                                  className={cn(
                                    'flex-1 px-2 py-2 text-xs font-medium min-w-0',
                                    colDef?.align === 'right' && 'text-right',
                                    colDef?.align === 'center' && 'text-center',
                                    colDef?.align === 'left' && 'text-left'
                                  )}
                                >
                                  {colDef?.label}
                                </div>
                              )
                            })}
                          </div>
                        </TableHead>
                      )}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.chain.map((strike) => (
                      <OptionChainRow
                        key={strike.strike}
                        strike={strike}
                        previousStrike={previousDataRef.current.get(strike.strike)}
                        maxBarValue={maxBarValue}
                        visibleCeColumns={visibleCeColumns}
                        visiblePeColumns={visiblePeColumns}
                        barDataSource={barDataSource}
                        barStyle={barStyle}
                        optionExchange={optionExchange}
                        onPlaceOrder={handlePlaceOrder}
                      />
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>

          {/* Slim detail line -- the broker/feed connection status itself
              now lives in the top toolbar's live-status pill; this just
              keeps the extra detail (symbol count, bar mode) that doesn't
              need a full-width footer bar of its own. */}
          <div className="text-xs text-muted-foreground">
            {isStreaming && `Streaming ${streamingSymbols} symbols · `}
            Bar: {barDataSource === 'oi' ? 'OI' : 'Volume'} ({barStyle})
          </div>
        </>
      )}

      {!data && !error && expiries.length > 0 && (
        <div className="flex items-center justify-center py-16">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
        </div>
      )}

      {/* Place Order Dialog */}
      <PlaceOrderDialog
        open={orderDialog?.open ?? false}
        onOpenChange={handleOrderDialogClose}
        symbol={orderDialog?.symbol}
        exchange={orderDialog?.exchange}
        action={orderDialog?.action}
        quantity={orderDialog?.quantity}
        lotSize={orderDialog?.lotSize}
        tickSize={orderDialog?.tickSize}
        strategy="OptionChain"
      />
    </div>
  )
}
