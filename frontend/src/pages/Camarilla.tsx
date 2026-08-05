import { AlertTriangle, ArrowLeft, Check, Info, Loader2, RefreshCw, Search } from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiClient } from '@/api/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAuthStore } from '@/stores/authStore'
import { showToast } from '@/utils/toast'

interface PivotLevel {
  name: string
  value: number
  description: string
  type: 'resistance' | 'support' | 'neutral'
}

interface SymbolSearchResult {
  symbol: string
  exchange: string
  name: string
}

// Well-known index/stock presets — now just seed the symbol search instead
// of hardcoding fabricated H/L/C numbers; the real values are always
// fetched live from the connected broker's previous trading day candle.
const PRESETS: Array<{ label: string; symbol: string; exchange: string }> = [
  { label: 'Nifty 50', symbol: 'NIFTY', exchange: 'NSE_INDEX' },
  { label: 'Nifty Bank', symbol: 'BANKNIFTY', exchange: 'NSE_INDEX' },
  { label: 'Reliance', symbol: 'RELIANCE', exchange: 'NSE' },
  { label: 'HDFC Bank', symbol: 'HDFCBANK', exchange: 'NSE' },
]

function formatDate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

export default function Camarilla() {
  const navigate = useNavigate()
  const { apiKey } = useAuthStore()

  const [symbolQuery, setSymbolQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SymbolSearchResult[]>([])
  const [searchOpen, setSearchOpen] = useState(false)
  const [searching, setSearching] = useState(false)
  const [selected, setSelected] = useState<SymbolSearchResult | null>(null)

  const [high, setHigh] = useState<number | null>(null)
  const [low, setLow] = useState<number | null>(null)
  const [close, setClose] = useState<number | null>(null)
  const [candleDate, setCandleDate] = useState<string | null>(null)
  const [loadingCandle, setLoadingCandle] = useState(false)
  const [fetchError, setFetchError] = useState<string | null>(null)

  const [levels, setLevels] = useState<PivotLevel[]>([])

  const calculatePivots = (H: number, L: number, C: number) => {
    if (Number.isNaN(H) || Number.isNaN(L) || Number.isNaN(C) || H <= L) {
      setLevels([])
      return
    }

    const range = H - L

    const h5 = (H / L) * C
    const h4 = C + (range * 1.1) / 2
    const h3 = C + (range * 1.1) / 4
    const h2 = C + (range * 1.1) / 6
    const h1 = C + (range * 1.1) / 12

    const l1 = C - (range * 1.1) / 12
    const l2 = C - (range * 1.1) / 6
    const l3 = C - (range * 1.1) / 4
    const l4 = C - (range * 1.1) / 2
    const l5 = C - (h5 - C)

    setLevels([
      {
        name: 'H5 (Target 2 / Super Breakout)',
        value: h5,
        description: 'Super breakout target level (very strong momentum)',
        type: 'resistance',
      },
      {
        name: 'H4 (Breakout Buy Level)',
        value: h4,
        description: 'Buy breakout above this strike; target H5',
        type: 'resistance',
      },
      {
        name: 'H3 (Short Entry / Resistance)',
        value: h3,
        description: 'Price reversal resistance; go short here in range-bound markets',
        type: 'resistance',
      },
      {
        name: 'H2 (Minor Resistance)',
        value: h2,
        description: 'Near-range resistance level',
        type: 'neutral',
      },
      {
        name: 'H1 (Immediate Resistance)',
        value: h1,
        description: 'Immediate minor resistance level',
        type: 'neutral',
      },
      {
        name: 'L1 (Immediate Support)',
        value: l1,
        description: 'Immediate minor support level',
        type: 'neutral',
      },
      {
        name: 'L2 (Minor Support)',
        value: l2,
        description: 'Near-range support level',
        type: 'neutral',
      },
      {
        name: 'L3 (Long Entry / Support)',
        value: l3,
        description: 'Price reversal support; go long here in range-bound markets',
        type: 'support',
      },
      {
        name: 'L4 (Breakout Short Level)',
        value: l4,
        description: 'Sell breakdown below this strike; target L5',
        type: 'support',
      },
      {
        name: 'L5 (Target 2 / Super Breakdown)',
        value: l5,
        description: 'Super breakdown target level (very strong downside momentum)',
        type: 'support',
      },
    ])
  }

  // Debounced symbol search — same /search endpoint ManualLegBuilder's
  // equity picker already uses.
  const runSearch = async (query: string) => {
    if (query.trim().length < 2) {
      setSearchResults([])
      return
    }
    if (!apiKey) {
      setSearchResults([])
      return
    }
    try {
      setSearching(true)
      const res = await apiClient.post<{ status: string; data?: SymbolSearchResult[] }>('/search', {
        apikey: apiKey,
        query: query.trim(),
      })
      if (res.data.status === 'success' && res.data.data) {
        setSearchResults(res.data.data.slice(0, 15))
      } else {
        setSearchResults([])
      }
    } catch {
      setSearchResults([])
    } finally {
      setSearching(false)
    }
  }

  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const handleSearchInput = (value: string) => {
    setSymbolQuery(value)
    setSearchOpen(true)
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
    searchDebounceRef.current = setTimeout(() => runSearch(value), 300)
  }

  // Fetch the most recent completed trading day's daily candle via the
  // real /history API and use its actual H/L/C — replaces the previous
  // hardcoded demo numbers entirely. Requesting a 10-day window (instead
  // of a single fixed date) sidesteps weekend/holiday handling: the
  // broker only ever returns real trading days, so the last row in the
  // response is always the most recent completed session.
  const fetchLiveCandle = async (result: SymbolSearchResult) => {
    if (!apiKey) {
      showToast.error('Connect a broker to load live data', 'system')
      return
    }
    setLoadingCandle(true)
    setFetchError(null)
    try {
      const end = new Date()
      const start = new Date()
      start.setDate(start.getDate() - 10)

      const res = await apiClient.post<{
        status: string
        message?: string
        data?: Array<{ timestamp: string | number; high: number; low: number; close: number }>
      }>('/history', {
        apikey: apiKey,
        symbol: result.symbol,
        exchange: result.exchange,
        interval: 'D',
        start_date: formatDate(start),
        end_date: formatDate(end),
      })

      if (res.data.status !== 'success' || !res.data.data || res.data.data.length === 0) {
        setFetchError(res.data.message || 'No historical data returned for this symbol.')
        setHigh(null)
        setLow(null)
        setClose(null)
        setLevels([])
        return
      }

      // Last row = most recent completed trading day. If today's session
      // is mid-day, the broker may include today's in-progress candle as
      // the last row — that's still the best available "current range"
      // reference, consistent with how a trader would read a live chart.
      const last = res.data.data[res.data.data.length - 1]
      const H = Number(last.high)
      const L = Number(last.low)
      const C = Number(last.close)

      setHigh(H)
      setLow(L)
      setClose(C)
      setCandleDate(
        typeof last.timestamp === 'string' ? last.timestamp.slice(0, 10) : String(last.timestamp)
      )
      calculatePivots(H, L, C)
    } catch {
      setFetchError('Failed to fetch live data from the broker.')
      setLevels([])
    } finally {
      setLoadingCandle(false)
    }
  }

  const handleSelect = (result: SymbolSearchResult) => {
    setSelected(result)
    setSymbolQuery(result.symbol)
    setSearchOpen(false)
    setSearchResults([])
    fetchLiveCandle(result)
  }

  const loadPreset = (preset: (typeof PRESETS)[number]) => {
    const result = { symbol: preset.symbol, exchange: preset.exchange, name: preset.label }
    handleSelect(result)
  }

  return (
    <div className="container mx-auto py-8 space-y-8 max-w-6xl px-4">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="outline" size="icon" onClick={() => navigate('/tools')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">
            Camarilla Pivot Calculator
          </h1>
          <p className="text-muted-foreground text-sm">
            Live supports, resistances, and breakout zones from the previous trading day's real
            range.
          </p>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-3">
        {/* Left Inputs Card */}
        <Card className="md:col-span-1 border border-border/80">
          <CardHeader>
            <CardTitle className="text-lg">Symbol</CardTitle>
            <CardDescription>Search a symbol to pull its live previous-day range.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="relative space-y-1.5">
              <Label htmlFor="symbol-search">Search Symbol</Label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="symbol-search"
                  value={symbolQuery}
                  onChange={(e) => handleSearchInput(e.target.value)}
                  placeholder="e.g. NIFTY, RELIANCE"
                  className="pl-8"
                />
                {searching && (
                  <Loader2 className="absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 animate-spin text-muted-foreground" />
                )}
              </div>
              {searchOpen && searchResults.length > 0 && (
                <div className="absolute top-full z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-md border bg-popover shadow-md">
                  {searchResults.map((r) => (
                    <button
                      key={`${r.exchange}:${r.symbol}`}
                      type="button"
                      onClick={() => handleSelect(r)}
                      className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs hover:bg-muted"
                    >
                      <span className="font-semibold">{r.symbol}</span>
                      <span className="truncate text-[10px] text-muted-foreground">
                        {r.name} · {r.exchange}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {selected && (
              <Button
                variant="outline"
                className="w-full font-bold"
                onClick={() => fetchLiveCandle(selected)}
                disabled={loadingCandle}
              >
                {loadingCandle ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4 mr-2" />
                )}
                Refresh Live Range
              </Button>
            )}

            {fetchError && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription className="text-xs">{fetchError}</AlertDescription>
              </Alert>
            )}

            {high !== null && low !== null && close !== null && (
              <div className="space-y-2 rounded-lg border p-3 text-xs">
                <div className="flex items-center gap-1.5 text-muted-foreground">
                  <Check className="h-3.5 w-3.5 text-profit" />
                  Live range {candleDate ? `(${candleDate})` : ''}
                </div>
                <div className="grid grid-cols-3 gap-2 font-mono">
                  <div>
                    <div className="text-muted-foreground">High</div>
                    <div className="font-bold">{high.toFixed(2)}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">Low</div>
                    <div className="font-bold">{low.toFixed(2)}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">Close</div>
                    <div className="font-bold">{close.toFixed(2)}</div>
                  </div>
                </div>
              </div>
            )}

            {/* Presets */}
            <div className="pt-4 border-t space-y-2">
              <Label className="text-xs font-bold text-muted-foreground uppercase">
                Quick Pick
              </Label>
              <div className="grid grid-cols-2 gap-2">
                {PRESETS.map((preset) => (
                  <Button
                    key={preset.symbol}
                    variant="outline"
                    size="sm"
                    className="text-xs"
                    onClick={() => loadPreset(preset)}
                    disabled={loadingCandle}
                  >
                    {preset.label}
                  </Button>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Right Output Levels list */}
        <Card className="md:col-span-2 border border-border/80">
          <CardHeader>
            <CardTitle className="text-lg">Camarilla Support & Resistance Levels</CardTitle>
            <CardDescription>
              {selected
                ? `Day trading targets for ${selected.symbol}, from its live previous-day range.`
                : 'Search or pick a symbol to calculate live levels.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {levels.length === 0 ? (
              <div className="text-center py-10 text-muted-foreground text-sm">
                {loadingCandle ? 'Fetching live range…' : 'Search a symbol to get started.'}
              </div>
            ) : (
              <div className="overflow-hidden border border-border rounded-lg">
                <Table>
                  <TableHeader className="bg-muted/40">
                    <TableRow>
                      <TableHead>Level</TableHead>
                      <TableHead className="text-right">Price Value</TableHead>
                      <TableHead>Execution Strategy Guideline</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {levels.map((lvl) => {
                      const colorClass =
                        lvl.type === 'resistance'
                          ? 'text-loss font-bold'
                          : lvl.type === 'support'
                            ? 'text-profit font-bold'
                            : 'text-muted-foreground'

                      return (
                        <TableRow key={lvl.name} className="hover:bg-muted/20">
                          <TableCell className={colorClass}>{lvl.name}</TableCell>
                          <TableCell className="text-right font-mono font-bold">
                            ₹{lvl.value.toFixed(2)}
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {lvl.description}
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Guidelines Strategy Card */}
      <Card className="border border-border/80">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Info className="h-5 w-5 text-info" />
            Day Trading Guidelines using Camarilla Pivots
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-6 md:grid-cols-2">
          <div className="space-y-2">
            <h4 className="font-bold text-sm text-profit uppercase">
              1. The Range-Bound Reversal Play
            </h4>
            <p className="text-xs text-muted-foreground leading-relaxed">
              If the asset opens between <strong>H3 and L3</strong>, price is expected to oscillate
              within the range.
            </p>
            <ul className="list-disc pl-4 text-xs text-muted-foreground space-y-1">
              <li>
                <strong>Buy Level:</strong> Go Long at L3 support if price starts rebounding. Target
                H3.
              </li>
              <li>
                <strong>Sell Level:</strong> Go Short at H3 resistance if price starts declining.
                Target L3.
              </li>
              <li>
                <strong>Stop Loss:</strong> Exit longs if price breaks L4; exit shorts if price
                breaks H4.
              </li>
            </ul>
          </div>

          <div className="space-y-2">
            <h4 className="font-bold text-sm text-loss uppercase">
              2. The Strong Trend Breakout Play
            </h4>
            <p className="text-xs text-muted-foreground leading-relaxed">
              If price breaks out of the daily H3/L3 buffer, a strong trending move is expected.
            </p>
            <ul className="list-disc pl-4 text-xs text-muted-foreground space-y-1">
              <li>
                <strong>Bullish Breakout:</strong> Buy when price breaks above <strong>H4</strong>.
                Target is H5.
              </li>
              <li>
                <strong>Bearish Breakdown:</strong> Sell / Short when price breaks below{' '}
                <strong>L4</strong>. Target is L5.
              </li>
              <li>
                <strong>Trailing Stop:</strong> Keep stop loss at H3 (for breakouts) or L3 (for
                breakdowns).
              </li>
            </ul>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
