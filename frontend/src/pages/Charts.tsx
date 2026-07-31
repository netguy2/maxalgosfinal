// pages/Charts.tsx
// Live charting page: candles for any equity/F&O symbol (fetched live from
// the broker via /historify/api/live-data — no pre-download step needed),
// indicator overlays with visual buy/sell signal markers, and a quick
// buy/sell order ticket. Full-width layout (no sidebar chrome), same
// pattern as pages/HistorifyCharts.tsx and pages/flow/FlowEditor.tsx — this
// is a new, separate page; neither of those files is touched.
//
// Symbol search uses /search/api/search (the same endpoint pages/Token.tsx
// and pages/Historify.tsx already use) rather than Historify's downloaded-
// only catalog, so any symbol the broker's master contract knows about is
// immediately chartable.

// Use html2canvas-pro which has native oklch color support — same choice
// as pages/PnLTracker.tsx's screenshot feature.
import html2canvas from 'html2canvas-pro'
import {
  Activity,
  BarChart3,
  BookOpen,
  Camera,
  ChevronDown,
  Eraser,
  Globe,
  Home,
  Loader2,
  LogOut,
  Maximize,
  Minimize,
  Minus,
  Moon,
  MoveHorizontal,
  PenLine,
  Percent,
  Plus,
  RefreshCw,
  Save,
  Search,
  Slash,
  Square,
  Star,
  Sun,
  Trash2,
  TrendingUp,
  X,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { authApi } from '@/api/auth'
import { chartDrawingsApi } from '@/api/chart-drawings'
import { type ChartWatchlist, chartWatchlistsApi } from '@/api/chart-watchlists'
import { type CustomIndicator, customIndicatorsApi } from '@/api/custom-indicators'
import { dashboardApi } from '@/api/dashboard'
import {
  historifyApi,
  type IndicatorRequest,
  type IndicatorSeriesPoint,
  type OHLCVBarDto,
} from '@/api/historify'
import { indicatorPresetsApi } from '@/api/indicator-presets'
import { LogoutConfirmDialog } from '@/components/auth/LogoutConfirmDialog'
import { AiInsightCard } from '@/components/charts/AiInsightCard'
import { CustomIndicatorBuilder } from '@/components/charts/CustomIndicatorBuilder'
import type { ChartDrawing } from '@/components/charts/chartDrawings'
import {
  aggregateTickIntoCandle,
  type ChartOverlay,
  type ChartSignal,
  LiveCandlestickChart,
  type SupportResistanceLevel,
} from '@/components/charts/LiveCandlestickChart'
import { QuickOrderTicket } from '@/components/charts/QuickOrderTicket'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useMarketData } from '@/hooks/useMarketData'
import { useProfileMenuItems } from '@/hooks/useProfileMenuItems'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'
import { useChartTheme } from '@/lib/chart-theme'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

const CHART_TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', 'D']

/** Converts a Historify interval string to seconds, for live-tick bucketing. */
function intervalToSeconds(interval: string): number {
  const match = interval.match(/^(\d*)([smhDWMQY])$/)
  if (!match) return 300
  const value = match[1] ? parseInt(match[1], 10) : 1
  const unit = match[2]
  switch (unit) {
    case 's':
      return value
    case 'm':
      return value * 60
    case 'h':
      return value * 3600
    case 'D':
      return value * 86400
    case 'W':
      return value * 7 * 86400
    default:
      return value * 30 * 86400 // M/Q/Y — coarse, only used for live-tick bucketing which doesn't apply at these scales
  }
}

interface IndicatorConfig {
  /** UI toggle key — stable regardless of period. */
  key: string
  /**
   * The exact key services/historify_service.py's get_indicator_overlays_from_bars
   * uses in its response `data` object: `f"{name}_{period}"` for
   * single-output indicators with a period (e.g. "EMA_20"), or just `name`
   * for period-less/multi-output indicators (VWAP, MACD, BOLLINGER). Must
   * be kept in sync with the params below — if the period changes, this
   * must change too.
   */
  dataKey: string
  request: IndicatorRequest
  label: string
  color: string
  /** Which chart pane this indicator belongs in — see ChartOverlay.paneHint. */
  paneHint?: 'price' | 'rsi' | 'macd' | 'atr' | 'stoch'
}

const INDICATOR_PALETTE = [
  '#f59e0b',
  '#8b5cf6',
  '#06b6d4',
  '#ec4899',
  '#22c55e',
  '#ef4444',
  '#3b82f6',
]

// Fixed swatch set for manual chart drawings (trendline/rectangle/
// fibonacci/horizontal ray) — a small curated set rather than a full color
// picker, matching the rest of this toolbar's "pick from a fixed set"
// convention (see INDICATOR_PALETTE above).
const DRAWING_COLOR_PALETTE = ['#3b82f6', '#ef4444', '#22c55e', '#f59e0b', '#a855f7', '#06b6d4']

const AVAILABLE_INDICATORS: IndicatorConfig[] = [
  {
    key: 'EMA',
    dataKey: 'EMA_20',
    request: { name: 'EMA', params: [20] },
    label: 'EMA 20',
    color: INDICATOR_PALETTE[0],
  },
  {
    key: 'SMA',
    dataKey: 'SMA_50',
    request: { name: 'SMA', params: [50] },
    label: 'SMA 50',
    color: INDICATOR_PALETTE[1],
  },
  {
    key: 'VWAP',
    dataKey: 'VWAP',
    request: { name: 'VWAP' },
    label: 'VWAP',
    color: INDICATOR_PALETTE[2],
  },
  {
    key: 'RSI',
    dataKey: 'RSI_14',
    request: { name: 'RSI', params: [14] },
    label: 'RSI 14',
    color: INDICATOR_PALETTE[3],
    paneHint: 'rsi',
  },
  {
    key: 'MACD',
    dataKey: 'MACD',
    request: { name: 'MACD' },
    label: 'MACD',
    color: INDICATOR_PALETTE[4],
    paneHint: 'macd',
  },
  {
    key: 'ATR',
    dataKey: 'ATR_14',
    request: { name: 'ATR', params: [14] },
    label: 'ATR 14',
    color: INDICATOR_PALETTE[5],
    paneHint: 'atr',
  },
  {
    key: 'BOLLINGER',
    dataKey: 'BOLLINGER',
    request: { name: 'BOLLINGER', params: [20, 2] },
    label: 'Bollinger 20/2',
    color: INDICATOR_PALETTE[6],
  },
  {
    key: 'STOCH',
    dataKey: 'STOCH',
    request: { name: 'STOCH', params: [14, 3, 3] },
    label: 'Stochastic 14/3/3',
    color: INDICATOR_PALETTE[0],
    paneHint: 'stoch',
  },
]

// Indicators the backend actually uses to derive crossover signals (EMA x
// SMA cross, RSI 30/70, price vs Bollinger bands — see
// services/historify_service.py's get_indicator_overlays_from_bars).
// Requested whenever "Buy/Sell Signals" is on, regardless of which of
// these the user has separately toggled on as a visible overlay line.
const SIGNAL_SOURCE_INDICATORS = AVAILABLE_INDICATORS.filter((ind) =>
  ['EMA', 'SMA', 'RSI', 'BOLLINGER'].includes(ind.key)
)

export default function Charts() {
  const navigate = useNavigate()
  const { mode, toggleMode, appMode, toggleAppMode, isTogglingMode } = useThemeStore()
  const { user, logout, apiKey } = useAuthStore()
  const profileMenuItems = useProfileMenuItems()
  const { allExchanges } = useSupportedExchanges()
  const chartTheme = useChartTheme()
  const [showLogoutDialog, setShowLogoutDialog] = useState(false)
  const { symbol: urlSymbol } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()

  // Available balance -- fetched once for AiInsightCard's client-side-only
  // position-size-pct -> quantity conversion (see that component's prop
  // doc: this value is never sent to the AI provider, only used locally
  // to turn the AI's suggested percentage into a real quantity).
  const [availableBalance, setAvailableBalance] = useState<number | undefined>(undefined)
  useEffect(() => {
    dashboardApi.getDashboardData().then((result) => {
      if (result.status === 'success' && result.data) {
        setAvailableBalance(parseFloat(result.data.availablecash) || undefined)
      }
    })
  }, [])

  const handleLogout = async () => {
    try {
      await authApi.logout()
      logout()
      navigate('/login')
      showToast.success('Logged out successfully', 'strategy')
    } catch {
      logout()
      navigate('/login')
    }
  }

  const handleModeToggle = async () => {
    const result = await toggleAppMode()
    if (result.success) {
      const newMode = useThemeStore.getState().appMode
      showToast.success(`Switched to ${newMode === 'live' ? 'Live' : 'Analyze'} mode`, 'strategy')
    } else {
      showToast.error(result.message || 'Failed to toggle mode', 'strategy')
    }
  }

  // Symbol selection — live search against /search/api/search (any symbol
  // the broker's master contract knows), not gated on Historify's
  // downloaded-only catalog.
  const [selectedSymbol, setSelectedSymbol] = useState(urlSymbol || '')
  const [selectedExchange, setSelectedExchange] = useState(searchParams.get('exchange') || 'NSE')
  const [selectedInterval, setSelectedInterval] = useState(searchParams.get('interval') || '5m')
  const [symbolSearchOpen, setSymbolSearchOpen] = useState(false)
  const [symbolSearch, setSymbolSearch] = useState('')
  const [symbolResults, setSymbolResults] = useState<
    Array<{ symbol: string; exchange: string; name?: string }>
  >([])
  const [isSearchingSymbols, setIsSearchingSymbols] = useState(false)
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Watchlists — named, multiple lists (e.g. "Nifty50", "My Positions"),
  // Charts-scoped (database/chart_watchlist_db.py — a separate table from
  // Historify's own single flat watchlist, which is untouched by this).
  const [watchlists, setWatchlists] = useState<ChartWatchlist[]>([])
  const [isLoadingWatchlists, setIsLoadingWatchlists] = useState(false)
  const [activeWatchlistId, setActiveWatchlistId] = useState<number | null>(null)
  const [watchlistMutating, setWatchlistMutating] = useState<string | null>(null)
  const [newListName, setNewListName] = useState('')
  const [creatingList, setCreatingList] = useState(false)

  const loadWatchlists = useCallback(async () => {
    setIsLoadingWatchlists(true)
    try {
      const resp = await chartWatchlistsApi.list()
      if (resp.status === 'success') {
        const lists = resp.data || []
        setWatchlists(lists)
        setActiveWatchlistId((prev) =>
          prev && lists.some((l) => l.id === prev) ? prev : (lists[0]?.id ?? null)
        )
      }
    } catch {
      // Non-fatal — watchlist panel just shows empty until retried.
    } finally {
      setIsLoadingWatchlists(false)
    }
  }, [])

  useEffect(() => {
    loadWatchlists()
  }, [loadWatchlists])

  const activeWatchlist = useMemo(
    () => watchlists.find((l) => l.id === activeWatchlistId) ?? null,
    [watchlists, activeWatchlistId]
  )

  const isInActiveWatchlist = useMemo(
    () =>
      !!selectedSymbol &&
      !!activeWatchlist &&
      activeWatchlist.items.some(
        (w) => w.symbol === selectedSymbol && w.exchange === selectedExchange
      ),
    [activeWatchlist, selectedSymbol, selectedExchange]
  )

  const handleCreateWatchlist = async () => {
    const name = newListName.trim()
    if (!name) return
    setCreatingList(true)
    try {
      const resp = await chartWatchlistsApi.create(name)
      if (resp.status === 'success') {
        setNewListName('')
        await loadWatchlists()
        if (resp.data) setActiveWatchlistId(resp.data.id)
      } else {
        showToast.error(resp.message || 'Failed to create watchlist', 'strategy')
      }
    } catch (err) {
      showToast.error(err instanceof Error ? err.message : 'Failed to create watchlist', 'strategy')
    } finally {
      setCreatingList(false)
    }
  }

  const handleDeleteWatchlistList = async (watchlistId: number) => {
    try {
      const resp = await chartWatchlistsApi.remove(watchlistId)
      if (resp.status === 'success') {
        await loadWatchlists()
      } else {
        showToast.error(resp.message || 'Failed to delete watchlist', 'strategy')
      }
    } catch (err) {
      showToast.error(err instanceof Error ? err.message : 'Failed to delete watchlist', 'strategy')
    }
  }

  const handleAddToWatchlist = async (symbol: string, exchange: string) => {
    if (!activeWatchlistId) {
      showToast.error('Create a watchlist first', 'strategy')
      return
    }
    const key = `${symbol}:${exchange}`
    setWatchlistMutating(key)
    try {
      const resp = await chartWatchlistsApi.addSymbol(activeWatchlistId, symbol, exchange)
      if (resp.status === 'success') {
        await loadWatchlists()
      } else {
        showToast.error(resp.message || 'Failed to add to watchlist', 'strategy')
      }
    } catch (err) {
      showToast.error(err instanceof Error ? err.message : 'Failed to add to watchlist', 'strategy')
    } finally {
      setWatchlistMutating(null)
    }
  }

  const handleRemoveFromWatchlist = async (
    watchlistId: number,
    symbol: string,
    exchange: string
  ) => {
    const key = `${symbol}:${exchange}`
    setWatchlistMutating(key)
    try {
      const resp = await chartWatchlistsApi.removeSymbol(watchlistId, symbol, exchange)
      if (resp.status === 'success') {
        setWatchlists((prev) =>
          prev.map((l) =>
            l.id === watchlistId
              ? {
                  ...l,
                  items: l.items.filter((w) => !(w.symbol === symbol && w.exchange === exchange)),
                }
              : l
          )
        )
      } else {
        showToast.error(resp.message || 'Failed to remove from watchlist', 'strategy')
      }
    } catch (err) {
      showToast.error(
        err instanceof Error ? err.message : 'Failed to remove from watchlist',
        'strategy'
      )
    } finally {
      setWatchlistMutating(null)
    }
  }

  const [bars, setBars] = useState<OHLCVBarDto[]>([])
  const [isLoadingChart, setIsLoadingChart] = useState(false)
  // Guards against a slow/rate-limited request for a symbol the user has
  // already switched away from resolving AFTER a newer request and
  // clobbering the chart with stale (or empty/error) data for a symbol
  // that's no longer even selected. Bumped at the start of every
  // loadChartData call; only the response matching the current value is
  // applied.
  const chartRequestIdRef = useRef(0)

  const [enabledIndicators, setEnabledIndicators] = useState<Set<string>>(new Set())
  const [indicatorsMenuOpen, setIndicatorsMenuOpen] = useState(false)
  const [presetScopeLoaded, setPresetScopeLoaded] = useState<'symbol' | 'global' | null>(null)
  const [isSavingPreset, setIsSavingPreset] = useState(false)
  const [signalsEnabled, setSignalsEnabled] = useState(false)
  const [srEnabled, setSrEnabled] = useState(false)
  const [srLevels, setSrLevels] = useState<SupportResistanceLevel[]>([])

  // Manual drawings (trendline/horizontal ray) — persisted per-user, per-
  // symbol/exchange/interval (database/chart_drawing_db.py). Reloaded
  // whenever the selected symbol/exchange/interval changes, same pattern
  // as loadWatchlists/loadCustomIndicators.
  const [activeDrawingTool, setActiveDrawingTool] = useState<
    'trendline' | 'horizontal_ray' | 'rectangle' | 'fibonacci' | null
  >(null)
  // Color used for the next drawing placed with the active tool (and its
  // live preview) — user-selectable via the swatch picker in the drawing
  // toolbar, defaulting to the theme's primary accent.
  const [drawingColor, setDrawingColor] = useState<string>(DRAWING_COLOR_PALETTE[0])

  // Fullscreen + screenshot -- both target chartAreaRef (the chart+sidebar
  // row below the toolbar), not the whole page, so the site header/nav
  // stays out of both. Uses the native Fullscreen API rather than a CSS
  // "fake fullscreen" so it actually takes over the OS-level display and
  // Escape works for free.
  const chartAreaRef = useRef<HTMLDivElement>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [isCapturingScreenshot, setIsCapturingScreenshot] = useState(false)

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(document.fullscreenElement === chartAreaRef.current)
    }
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange)
  }, [])

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen()
      } else if (chartAreaRef.current) {
        await chartAreaRef.current.requestFullscreen()
      }
    } catch {
      showToast.error('Fullscreen is not available in this browser', 'strategy')
    }
  }

  const takeChartScreenshot = async () => {
    if (!chartAreaRef.current) return
    setIsCapturingScreenshot(true)
    try {
      const canvas = await html2canvas(chartAreaRef.current, {
        backgroundColor: chartTheme.card,
        scale: 2,
        logging: false,
        useCORS: true,
      })
      canvas.toBlob(
        (blob) => {
          if (!blob) return
          const url = URL.createObjectURL(blob)
          const link = document.createElement('a')
          const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5)
          const symbolPart = selectedSymbol ? `${selectedSymbol}_${selectedInterval}_` : ''
          link.download = `Chart_${symbolPart}${timestamp}.png`
          link.href = url
          document.body.appendChild(link)
          link.click()
          document.body.removeChild(link)
          URL.revokeObjectURL(url)
          showToast.success('Screenshot saved', 'strategy')
        },
        'image/png',
        1.0
      )
    } catch {
      showToast.error('Failed to capture screenshot', 'strategy')
    } finally {
      setIsCapturingScreenshot(false)
    }
  }
  const [drawings, setDrawings] = useState<ChartDrawing[]>([])
  const [indicatorData, setIndicatorData] = useState<
    Record<string, IndicatorSeriesPoint[] | Record<string, IndicatorSeriesPoint[]>>
  >({})
  const [signalData, setSignalData] = useState<
    Record<string, { time: number; side: 'BUY' | 'SELL' }[]>
  >({})

  // Custom indicators — per-user, saved server-side (database/custom_indicator_db.py),
  // built from a fixed safe menu (blueprints/custom_indicators.py), never
  // arbitrary code. Loaded once and reused across symbol/interval changes;
  // only the ones toggled on get computed against the current bars.
  const [customIndicators, setCustomIndicators] = useState<CustomIndicator[]>([])
  const [enabledCustomIndicators, setEnabledCustomIndicators] = useState<Set<number>>(new Set())
  const [customIndicatorData, setCustomIndicatorData] = useState<
    Record<number, { series?: IndicatorSeriesPoint[]; signals?: ChartSignal[]; error?: string }>
  >({})
  const [builderOpen, setBuilderOpen] = useState(false)

  const loadCustomIndicators = useCallback(async () => {
    try {
      const resp = await customIndicatorsApi.list()
      if (resp.status === 'success') setCustomIndicators(resp.data || [])
    } catch {
      // Non-fatal — the custom-indicator chip row just shows empty until retried.
    }
  }, [])

  useEffect(() => {
    loadCustomIndicators()
  }, [loadCustomIndicators])

  const toggleCustomIndicator = (id: number) => {
    setEnabledCustomIndicators((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleDeleteCustomIndicator = async (id: number) => {
    try {
      const resp = await customIndicatorsApi.remove(id)
      if (resp.status === 'success') {
        setCustomIndicators((prev) => prev.filter((ci) => ci.id !== id))
        setEnabledCustomIndicators((prev) => {
          const next = new Set(prev)
          next.delete(id)
          return next
        })
      } else {
        showToast.error(resp.message || 'Failed to delete indicator', 'strategy')
      }
    } catch (err) {
      showToast.error(err instanceof Error ? err.message : 'Failed to delete indicator', 'strategy')
    }
  }

  const intervalSeconds = useMemo(() => intervalToSeconds(selectedInterval), [selectedInterval])

  // Debounced live symbol search, same 300ms pattern as pages/Historify.tsx.
  useEffect(() => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
    if (!symbolSearch.trim()) {
      setSymbolResults([])
      return
    }
    searchDebounceRef.current = setTimeout(async () => {
      setIsSearchingSymbols(true)
      try {
        const params = new URLSearchParams({ q: symbolSearch.trim() })
        // Without an explicit exchange list, /search/api/search treats the
        // request as "no exchange filter" and always falls through to the
        // plain equity-table search engine -- it never reaches the FNO
        // in-memory cache that NFO/BFO/MCX/CDS contracts are indexed in
        // (blueprints/search.py's api_search: is_fno_path only becomes true
        // when `exch` is a real, non-None FNO exchange). That's why an MCX
        // commodity like GOLDM never appeared in this search even though
        // its master-contract data is loaded and Options Chain/Strategy
        // Builder can find it fine. Passing every broker-supported exchange
        // (comma-separated -- the endpoint accepts and unions multiple)
        // makes each one route to its correct engine.
        if (allExchanges.length > 0) {
          params.set('exchange', allExchanges.map((e) => e.value).join(','))
        }
        const response = await fetch(`/search/api/search?${params}`, { credentials: 'include' })
        const data = await response.json()
        setSymbolResults((data.results || []).slice(0, 20))
      } catch {
        setSymbolResults([])
      } finally {
        setIsSearchingSymbols(false)
      }
    }, 300)
    return () => {
      if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
    }
  }, [symbolSearch, allExchanges])

  useEffect(() => {
    if (selectedSymbol && selectedExchange && selectedInterval) {
      setSearchParams({ exchange: selectedExchange, interval: selectedInterval })
    }
  }, [selectedSymbol, selectedExchange, selectedInterval, setSearchParams])

  const loadChartData = useCallback(async () => {
    if (!selectedSymbol || !selectedExchange) return
    const requestId = ++chartRequestIdRef.current
    setIsLoadingChart(true)
    try {
      const data = await historifyApi.getLiveChartData(
        selectedSymbol,
        selectedExchange,
        selectedInterval
      )
      // A newer request has since been issued (symbol/exchange/interval
      // changed again while this one was in flight) -- drop this result
      // instead of applying it out of order.
      if (requestId !== chartRequestIdRef.current) return
      if (data.status === 'success') {
        setBars(data.data || [])
        if ((data.count ?? 0) === 0) {
          showToast.info('No data returned for this symbol/interval.', 'strategy')
        }
      } else {
        showToast.error(data.message || 'Failed to load chart data', 'strategy')
        setBars([])
      }
    } catch (err) {
      if (requestId !== chartRequestIdRef.current) return
      showToast.error(err instanceof Error ? err.message : 'Failed to load chart data', 'strategy')
      setBars([])
    } finally {
      if (requestId === chartRequestIdRef.current) setIsLoadingChart(false)
    }
  }, [selectedSymbol, selectedExchange, selectedInterval])

  useEffect(() => {
    loadChartData()
  }, [loadChartData])

  // Load this symbol/exchange/interval's saved drawings whenever the
  // selection changes — drawings are scoped per symbol+interval, so
  // switching either means a fresh fetch, not a filter of what's loaded.
  useEffect(() => {
    if (!selectedSymbol || !selectedExchange || !selectedInterval) {
      setDrawings([])
      return
    }
    chartDrawingsApi
      .list(selectedSymbol, selectedExchange, selectedInterval)
      .then(setDrawings)
      .catch(() => setDrawings([]))
  }, [selectedSymbol, selectedExchange, selectedInterval])

  // Load this symbol's resolved indicator preset (symbol-specific, else
  // global default) whenever the selection changes, and apply it as the
  // initial indicator selection. Only runs on the symbol switch itself —
  // it does not re-run on every enabledIndicators change, so it never
  // clobbers a manual toggle made mid-session (same "don't overwrite user
  // intent" caution already applied to activeWatchlistId elsewhere on
  // this page).
  useEffect(() => {
    if (!selectedSymbol || !selectedExchange) {
      setPresetScopeLoaded(null)
      return
    }
    indicatorPresetsApi
      .get(selectedSymbol, selectedExchange)
      .then(({ scope, config }) => {
        setPresetScopeLoaded(scope)
        if (config) {
          setEnabledIndicators(new Set(config.indicators))
          setEnabledCustomIndicators(new Set(config.customIndicatorIds))
        }
      })
      .catch(() => setPresetScopeLoaded(null))
  }, [selectedSymbol, selectedExchange])

  const handleSavePreset = async (scope: 'symbol' | 'global') => {
    const config = {
      indicators: Array.from(enabledIndicators),
      customIndicatorIds: Array.from(enabledCustomIndicators),
    }
    setIsSavingPreset(true)
    try {
      const success =
        scope === 'symbol'
          ? selectedSymbol && selectedExchange
            ? await indicatorPresetsApi.saveForSymbol(selectedSymbol, selectedExchange, config)
            : false
          : await indicatorPresetsApi.saveGlobal(config)
      if (success) {
        setPresetScopeLoaded(scope)
        showToast.success(
          scope === 'symbol' ? 'Saved setup for this symbol' : 'Saved as default for all symbols',
          'strategy'
        )
      } else {
        showToast.error('Failed to save setup', 'strategy')
      }
    } catch (err) {
      showToast.error(err instanceof Error ? err.message : 'Failed to save setup', 'strategy')
    } finally {
      setIsSavingPreset(false)
    }
  }

  const handleDrawingCreated = async (drawing: ChartDrawing) => {
    // Optimistic: show it immediately using the client-generated id, then
    // reconcile with the server's real id once saved.
    setDrawings((prev) => [...prev, drawing])
    if (!selectedSymbol || !selectedExchange) return
    const saved = await chartDrawingsApi.create(
      selectedSymbol,
      selectedExchange,
      selectedInterval,
      drawing
    )
    if (saved) {
      setDrawings((prev) => prev.map((d) => (d.id === drawing.id ? saved : d)))
    } else {
      showToast.error('Failed to save drawing', 'strategy')
      setDrawings((prev) => prev.filter((d) => d.id !== drawing.id))
    }
  }

  const handleDrawingDeleted = async (id: string) => {
    setDrawings((prev) => prev.filter((d) => d.id !== id))
    // Only persisted drawings have a numeric server id — a drawing
    // deleted before its create-save round-trip finished has no backend
    // row to remove yet.
    if (!/^\d+$/.test(id)) return
    const success = await chartDrawingsApi.remove(id)
    if (!success) showToast.error('Failed to delete drawing', 'strategy')
  }

  const handleClearAllDrawings = () => {
    for (const d of drawings) {
      if (/^\d+$/.test(d.id)) chartDrawingsApi.remove(d.id).catch(() => {})
    }
    setDrawings([])
  }

  // Keep bars (and therefore indicators/signals, which recompute whenever
  // `bars` changes — see the effect below) reasonably current while a
  // symbol is open, not just on manual refresh/symbol change. Live ticks
  // already update the candle's visual price in real time via the
  // WebSocket path, but that path deliberately bypasses `bars` state (see
  // LiveCandlestickChart's liveTick effect) so it never triggers a signal
  // recompute on its own — this periodic refetch is what keeps signals
  // live. 30s balances staying current against the backend's ~3 req/sec
  // broker rate limit for history calls.
  useEffect(() => {
    if (!selectedSymbol || !selectedExchange) return
    const id = setInterval(loadChartData, 30_000)
    return () => clearInterval(id)
  }, [selectedSymbol, selectedExchange, loadChartData])

  // Compute indicator overlays (+ buy/sell signals) over the bars already
  // on screen whenever the enabled set, the signals toggle, or the bars
  // themselves change.
  //
  // Signals are decoupled from which lines are visually drawn: the backend
  // (services/historify_service.py's get_indicator_overlays_from_bars) only
  // derives crossover markers from specific indicator PAIRS being present
  // in the request (EMA x SMA cross, RSI 30/70, price vs Bollinger bands).
  // Toggling "Buy/Sell Signals" always requests that full signal-producing
  // set server-side regardless of which overlay chips the user has on, so
  // signals show up reliably rather than only when the right combination
  // of overlay chips happens to be enabled.
  useEffect(() => {
    const overlayRequests = AVAILABLE_INDICATORS.filter((ind) =>
      enabledIndicators.has(ind.key)
    ).map((ind) => ind.request)

    const requestedNames = new Set(overlayRequests.map((r) => r.name))
    const signalRequests = signalsEnabled
      ? SIGNAL_SOURCE_INDICATORS.filter((ind) => !requestedNames.has(ind.request.name)).map(
          (ind) => ind.request
        )
      : []

    const requests = [...overlayRequests, ...signalRequests]
    if (requests.length === 0 || bars.length === 0) {
      setIndicatorData({})
      setSignalData({})
      return
    }
    historifyApi
      .getIndicatorSeries(bars, requests)
      .then((resp) => {
        if (resp.status === 'success') {
          setIndicatorData(resp.data || {})
          setSignalData(signalsEnabled ? resp.signals || {} : {})
        } else {
          showToast.error(resp.message || 'Failed to load indicators', 'strategy')
        }
      })
      .catch((err) => {
        showToast.error(
          err instanceof Error ? err.message : 'Failed to load indicators',
          'strategy'
        )
      })
  }, [bars, enabledIndicators, signalsEnabled])

  // Detect support/resistance levels from the same bars whenever the
  // toggle is on — independent of the built-in/custom indicator fetches
  // above so a failure here never blocks them and vice versa.
  useEffect(() => {
    if (!srEnabled || bars.length === 0) {
      setSrLevels([])
      return
    }
    historifyApi
      .getSupportResistance(bars)
      .then((resp) => {
        if (resp.status === 'success' && resp.data) {
          const levels: SupportResistanceLevel[] = [
            ...resp.data.resistance.map((l) => ({
              price: l.price,
              side: 'resistance' as const,
              touches: l.touches,
            })),
            ...resp.data.support.map((l) => ({
              price: l.price,
              side: 'support' as const,
              touches: l.touches,
            })),
          ]
          setSrLevels(levels)
        } else {
          showToast.error(resp.message || 'Failed to compute support/resistance', 'strategy')
        }
      })
      .catch((err) => {
        showToast.error(
          err instanceof Error ? err.message : 'Failed to compute support/resistance',
          'strategy'
        )
      })
  }, [bars, srEnabled])

  // Compute enabled custom indicators over the same bars, independently of
  // the built-in fetch above — a separate endpoint
  // (/custom-indicators/api/compute), so a failure there never blocks
  // built-in indicators from rendering and vice versa.
  useEffect(() => {
    const enabledFormulas = customIndicators
      .filter((ci) => enabledCustomIndicators.has(ci.id))
      .map((ci) => ({ id: ci.id, formula: ci.formula }))

    if (enabledFormulas.length === 0 || bars.length === 0) {
      setCustomIndicatorData({})
      return
    }
    customIndicatorsApi
      .compute(bars, enabledFormulas)
      .then((resp) => {
        if (resp.status === 'success') {
          const byId: Record<
            number,
            { series?: IndicatorSeriesPoint[]; signals?: ChartSignal[]; error?: string }
          > = {}
          for (const [idStr, result] of Object.entries(resp.data || {})) {
            byId[Number(idStr)] = result
            if (result.error) {
              showToast.error(`Custom indicator error: ${result.error}`, 'strategy')
            }
          }
          setCustomIndicatorData(byId)
        } else {
          showToast.error(resp.message || 'Failed to compute custom indicators', 'strategy')
        }
      })
      .catch((err) => {
        showToast.error(
          err instanceof Error ? err.message : 'Failed to compute custom indicators',
          'strategy'
        )
      })
  }, [bars, customIndicators, enabledCustomIndicators])

  const totalEnabledIndicatorCount = enabledIndicators.size + enabledCustomIndicators.size

  const overlays: ChartOverlay[] = useMemo(() => {
    const result: ChartOverlay[] = []
    for (const ind of AVAILABLE_INDICATORS) {
      if (!enabledIndicators.has(ind.key)) continue
      const value = indicatorData[ind.dataKey]
      if (!value) continue
      if (Array.isArray(value)) {
        result.push({
          id: ind.key,
          label: ind.label,
          color: ind.color,
          data: value,
          paneHint: ind.paneHint,
        })
      } else {
        // Multi-output indicator (MACD/BOLLINGER) — one overlay line per
        // sub-series, all sharing the parent indicator's pane.
        let i = 0
        for (const [subKey, subSeries] of Object.entries(value)) {
          result.push({
            id: `${ind.key}_${subKey}`,
            label: `${ind.label} ${subKey}`,
            color:
              INDICATOR_PALETTE[
                (INDICATOR_PALETTE.indexOf(ind.color) + i + 1) % INDICATOR_PALETTE.length
              ],
            data: subSeries,
            paneHint: ind.paneHint,
          })
          i++
        }
      }
    }
    for (const ci of customIndicators) {
      if (!enabledCustomIndicators.has(ci.id)) continue
      const computed = customIndicatorData[ci.id]
      if (computed?.series) {
        result.push({
          id: `custom_${ci.id}`,
          label: ci.name,
          color: ci.color,
          data: computed.series,
          // Custom indicators are always price-unit combinations (see
          // CustomIndicatorBuilder — operands are EMA/SMA/VWAP/RSI/ATR/
          // BOLLINGER combined arithmetically or compared to a fixed
          // threshold); no dedicated oscillator pane for these in v1.
        })
      }
    }
    return result
  }, [
    enabledIndicators,
    indicatorData,
    customIndicators,
    enabledCustomIndicators,
    customIndicatorData,
  ])

  // Flatten every signal source into one list, then merge any that land
  // on the exact same (time, side) into a single marker carrying all the
  // sources that fired there — this is what fixes the overlapping/garbled
  // on-chart text (LiveCandlestickChart no longer renders permanent text
  // labels at all; the merged `sources` list is for a future signals log,
  // not on-canvas). Signals for timestamps not present in the currently
  // loaded bars are filtered again inside LiveCandlestickChart itself —
  // this memo doesn't need bars as a dependency, since that filter is the
  // chart component's job (it knows exactly what's in its own series).
  const signals: ChartSignal[] = useMemo(() => {
    const raw: ChartSignal[] = []
    for (const sigList of Object.values(signalData)) {
      raw.push(...sigList)
    }
    for (const ci of customIndicators) {
      if (!enabledCustomIndicators.has(ci.id)) continue
      const computed = customIndicatorData[ci.id]
      if (computed?.signals) raw.push(...computed.signals)
    }

    const merged = new Map<string, ChartSignal>()
    for (const sig of raw) {
      const key = `${sig.time}:${sig.side}`
      const existing = merged.get(key)
      if (existing) {
        existing.sources = [...(existing.sources ?? []), ...(sig.sources ?? ['signal'])]
      } else {
        merged.set(key, { ...sig, sources: sig.sources ?? ['signal'] })
      }
    }
    return Array.from(merged.values())
  }, [signalData, customIndicators, enabledCustomIndicators, customIndicatorData])

  const toggleIndicator = (key: string) => {
    setEnabledIndicators((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const handleClearAllIndicators = () => {
    setEnabledIndicators(new Set())
    setEnabledCustomIndicators(new Set())
  }

  // Live tick -> feed the chart's live-update prop. Ticks require a
  // connected+authenticated broker WS session; MarketDataManager falls
  // back to REST polling (multiquotes, ~5s) after 3 failed WS connection
  // attempts, and surfaces auth-level errors (invalid/expired broker
  // session) via `error` — both are worth showing so a silently-stale
  // chart doesn't look like a bug. It does NOT surface a broker adapter
  // rejecting one specific symbol (e.g. unsupported exchange for that
  // broker) — a known gap in the shared WS client, not something fixable
  // from this page alone.
  const {
    data: marketData,
    isConnected,
    isAuthenticated,
    isFallbackMode,
    error: marketDataError,
  } = useMarketData({
    symbols:
      selectedSymbol && selectedExchange
        ? [{ symbol: selectedSymbol, exchange: selectedExchange }]
        : [],
    mode: 'LTP',
    enabled: !!selectedSymbol && !!selectedExchange,
  })
  const liveSymbolData = marketData.get(`${selectedExchange}:${selectedSymbol}`)
  const liveTick = useMemo(() => {
    if (!liveSymbolData?.data.ltp) return null
    return {
      ltp: liveSymbolData.data.ltp,
      timestamp: liveSymbolData.lastUpdate
        ? Math.floor(liveSymbolData.lastUpdate / 1000)
        : Math.floor(Date.now() / 1000),
    }
  }, [liveSymbolData])

  const handleSymbolSelect = (symbol: string, exchange: string) => {
    setSelectedSymbol(symbol)
    setSelectedExchange(exchange)
    setSymbolSearchOpen(false)
    setSymbolSearch('')
  }

  const strategyName = `charts-${selectedSymbol || 'manual'}`

  // Escape disarms the active drawing tool, matching standard chart-tool UX.
  useEffect(() => {
    if (!activeDrawingTool) return
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setActiveDrawingTool(null)
    }
    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [activeDrawingTool])

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      {/* Top Header Bar */}
      <div className="h-12 border-b border-border flex items-center px-2 bg-card/50">
        <div className="flex items-center gap-2 px-2">
          <img
            src="/max-icon.png"
            alt="Max Algos"
            className="size-6 shrink-0 rounded-full object-cover ring-2 ring-brand/40"
          />
          <div className="flex flex-col leading-none">
            <span className="text-foreground text-xs font-extrabold tracking-wider">MAX</span>
            <span className="text-brand text-[7px] font-black tracking-[0.25em]">ALGOS</span>
          </div>
        </div>

        <div className="flex-1 flex flex-col items-center justify-center leading-tight">
          <span className="text-sm font-medium text-foreground">Charts</span>
          <span className="text-[10px] text-muted-foreground">
            Live candles, indicators &amp; trading
          </span>
        </div>

        <div className="flex items-center gap-2 px-2">
          <Badge
            variant={appMode === 'live' ? 'default' : 'secondary'}
            className={cnBadge(appMode)}
          >
            <span className="hidden sm:inline">
              {appMode === 'live' ? 'Live Mode' : 'Analyze Mode'}
            </span>
            <span className="sm:hidden">{appMode === 'live' ? 'Live' : 'Analyze'}</span>
          </Badge>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={handleModeToggle}
            disabled={isTogglingMode}
            title={`Switch to ${appMode === 'live' ? 'Analyze' : 'Live'} mode`}
            aria-label={`Switch to ${appMode === 'live' ? 'Analyze' : 'Live'} mode`}
          >
            {isTogglingMode ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            ) : appMode === 'live' ? (
              <Zap className="h-4 w-4" />
            ) : (
              <BarChart3 className="h-4 w-4" />
            )}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={toggleMode}
            disabled={appMode !== 'live'}
            title={mode === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
            aria-label={mode === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
          >
            {mode === 'light' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
          <Button variant="ghost" size="sm" className="h-7 text-xs" asChild>
            <Link to="/dashboard">
              <Home className="h-3.5 w-3.5 mr-1.5" />
              Dashboard
            </Link>
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-full bg-primary text-primary-foreground"
                aria-label="Open profile menu"
              >
                <span className="text-sm font-medium">
                  {user?.username?.[0]?.toUpperCase() || 'O'}
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              {profileMenuItems.map((item) => (
                <DropdownMenuItem
                  key={item.href}
                  onSelect={() => navigate(item.href)}
                  className="cursor-pointer"
                >
                  <item.icon className="h-4 w-4 mr-2" />
                  {item.label}
                </DropdownMenuItem>
              ))}
              <DropdownMenuItem asChild>
                <a
                  href="https://docs.maxalgos.in"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2"
                >
                  <BookOpen className="h-4 w-4" />
                  Docs
                </a>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => setShowLogoutDialog(true)}
                className="text-destructive focus:text-destructive"
              >
                <LogOut className="h-4 w-4 mr-2" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <LogoutConfirmDialog
        open={showLogoutDialog}
        onOpenChange={setShowLogoutDialog}
        onConfirm={handleLogout}
      />

      {/* Toolbar: symbol / interval / indicators / refresh */}
      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-card px-4 py-2">
        <Popover open={symbolSearchOpen} onOpenChange={setSymbolSearchOpen}>
          <PopoverTrigger asChild>
            <Button variant="outline" className="w-56 justify-between">
              {selectedSymbol ? (
                <span>
                  {selectedSymbol}:{selectedExchange}
                </span>
              ) : (
                <span className="text-muted-foreground">Select symbol...</span>
              )}
              <Search className="h-4 w-4 ml-2" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-64 p-0" align="start">
            <Command shouldFilter={false}>
              <CommandInput
                placeholder="Search any symbol..."
                value={symbolSearch}
                onValueChange={setSymbolSearch}
              />
              <CommandList>
                <CommandEmpty>
                  {isSearchingSymbols
                    ? 'Searching…'
                    : symbolSearch
                      ? 'No symbols found'
                      : 'Type to search'}
                </CommandEmpty>
                <CommandGroup>
                  {symbolResults.map((s) => (
                    <CommandItem
                      key={`${s.symbol}:${s.exchange}`}
                      value={`${s.symbol}:${s.exchange}`}
                      onSelect={() => handleSymbolSelect(s.symbol, s.exchange)}
                    >
                      <span className="font-medium">{s.symbol}</span>
                      <Badge variant="outline" className="ml-2 text-[10px]">
                        {s.exchange}
                      </Badge>
                      {s.name && (
                        <span className="text-xs text-muted-foreground ml-auto truncate max-w-[100px]">
                          {s.name}
                        </span>
                      )}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>

        {selectedSymbol && selectedExchange && (
          <Button
            variant="outline"
            size="icon"
            className="h-9 w-9"
            disabled={
              watchlistMutating === `${selectedSymbol}:${selectedExchange}` || !activeWatchlistId
            }
            onClick={() =>
              isInActiveWatchlist && activeWatchlistId
                ? handleRemoveFromWatchlist(activeWatchlistId, selectedSymbol, selectedExchange)
                : handleAddToWatchlist(selectedSymbol, selectedExchange)
            }
            title={
              !activeWatchlistId
                ? 'Create a watchlist first'
                : isInActiveWatchlist
                  ? `Remove from ${activeWatchlist?.name}`
                  : `Add to ${activeWatchlist?.name}`
            }
            aria-label={isInActiveWatchlist ? 'Remove from watchlist' : 'Add to watchlist'}
          >
            <Star className={cn('h-4 w-4', isInActiveWatchlist && 'fill-warning text-warning')} />
          </Button>
        )}

        <Select value={selectedInterval} onValueChange={setSelectedInterval}>
          <SelectTrigger className="w-24">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CHART_TIMEFRAMES.map((tf) => (
              <SelectItem key={tf} value={tf}>
                {tf}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button variant="outline" size="sm" onClick={loadChartData} disabled={isLoadingChart}>
          {isLoadingChart ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
        </Button>

        <div className="h-6 w-px bg-border" />

        <Popover open={indicatorsMenuOpen} onOpenChange={setIndicatorsMenuOpen}>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm" className="gap-1.5">
              <Activity className="h-3.5 w-3.5" />
              Indicators
              {totalEnabledIndicatorCount > 0 && (
                <Badge variant="secondary" className="h-4 px-1.5 text-[10px]">
                  {totalEnabledIndicatorCount}
                </Badge>
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-72 p-3" align="start">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Built-in
                </p>
                {totalEnabledIndicatorCount > 0 && (
                  <button
                    type="button"
                    onClick={handleClearAllIndicators}
                    className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-loss"
                  >
                    <Eraser className="h-3 w-3" />
                    Clear all
                  </button>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {AVAILABLE_INDICATORS.map((ind) => (
                  <label
                    key={ind.key}
                    className="flex cursor-pointer items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]"
                    style={
                      enabledIndicators.has(ind.key)
                        ? { borderColor: ind.color, color: ind.color }
                        : undefined
                    }
                  >
                    <Checkbox
                      checked={enabledIndicators.has(ind.key)}
                      onCheckedChange={() => toggleIndicator(ind.key)}
                      className="h-3 w-3"
                    />
                    {ind.label}
                  </label>
                ))}
              </div>
            </div>

            {customIndicators.length > 0 && (
              <div className="mt-3 space-y-1.5">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Custom
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {customIndicators.map((ci) => (
                    <div
                      key={ci.id}
                      className="group flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]"
                      style={
                        enabledCustomIndicators.has(ci.id)
                          ? { borderColor: ci.color, color: ci.color }
                          : undefined
                      }
                    >
                      <label className="flex cursor-pointer items-center gap-1">
                        <Checkbox
                          checked={enabledCustomIndicators.has(ci.id)}
                          onCheckedChange={() => toggleCustomIndicator(ci.id)}
                          className="h-3 w-3"
                        />
                        {ci.name}
                      </label>
                      <button
                        type="button"
                        onClick={() => handleDeleteCustomIndicator(ci.id)}
                        className="text-muted-foreground opacity-0 transition-opacity hover:text-loss group-hover:opacity-100"
                        aria-label={`Delete ${ci.name}`}
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="mt-3 space-y-1.5 border-t border-border pt-3">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Save setup
              </p>
              <div className="flex gap-1.5">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 flex-1 gap-1 text-[11px]"
                  disabled={isSavingPreset || !selectedSymbol || !selectedExchange}
                  onClick={() => handleSavePreset('symbol')}
                  title="Auto-load this selection only for the current symbol"
                >
                  <Save className="h-3 w-3" />
                  This symbol
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 flex-1 gap-1 text-[11px]"
                  disabled={isSavingPreset}
                  onClick={() => handleSavePreset('global')}
                  title="Set as the default for every symbol without its own saved setup"
                >
                  <Globe className="h-3 w-3" />
                  All symbols
                </Button>
              </div>
              {presetScopeLoaded && (
                <p className="text-[10px] text-muted-foreground">
                  Loaded from your {presetScopeLoaded === 'symbol' ? 'symbol' : 'default'} setup.
                </p>
              )}
            </div>

            <button
              type="button"
              onClick={() => {
                setIndicatorsMenuOpen(false)
                setBuilderOpen(true)
              }}
              className="mt-3 flex w-full items-center justify-center gap-1 rounded-md border border-dashed px-2 py-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-muted"
            >
              <Plus className="h-3.5 w-3.5" />
              Create custom indicator
            </button>
          </PopoverContent>
        </Popover>

        <button
          type="button"
          onClick={() => setSignalsEnabled((v) => !v)}
          className={cn(
            'flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors',
            signalsEnabled
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-border text-muted-foreground hover:bg-muted'
          )}
          title="Show BUY/SELL arrow markers where EMA/SMA cross, RSI hits 30/70, or price crosses the Bollinger bands"
        >
          <TrendingUp className="h-3.5 w-3.5" />
          Buy/Sell Signals
        </button>

        <button
          type="button"
          onClick={() => setSrEnabled((v) => !v)}
          className={cn(
            'flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors',
            srEnabled
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-border text-muted-foreground hover:bg-muted'
          )}
          title="Support/resistance levels clustered from real swing highs/lows — not a fixed formula, ranked by how many times price touched each zone"
        >
          <Minus className="h-3.5 w-3.5" />
          Support/Resistance
        </button>

        {selectedSymbol && selectedExchange && (
          <div className="ml-auto flex items-center gap-1.5 text-[11px]">
            {marketDataError ? (
              <span className="flex items-center gap-1 text-loss" title={marketDataError}>
                <span className="h-1.5 w-1.5 rounded-full bg-loss" />
                Live feed error — check broker connection
              </span>
            ) : isFallbackMode ? (
              <span
                className="flex items-center gap-1 text-warning"
                title="WebSocket unavailable — polling every ~5s instead"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-warning" />
                Live (polling)
              </span>
            ) : isConnected && isAuthenticated ? (
              <span className="flex items-center gap-1 text-profit">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-profit" />
                Live
              </span>
            ) : (
              <span className="flex items-center gap-1 text-muted-foreground">
                <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground" />
                Connecting…
              </span>
            )}
          </div>
        )}
      </div>

      {/* Main content: watchlists + chart + order ticket. Fullscreen and
          screenshot both target this ref so the site header/nav stays
          outside of both. */}
      <div ref={chartAreaRef} className="flex flex-1 overflow-hidden bg-background">
        <div className="w-56 shrink-0 overflow-y-auto border-r border-border">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Watchlists
            </span>
            {isLoadingWatchlists && (
              <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
            )}
          </div>

          {/* List selector — named lists as tabs, + New List input */}
          <div className="flex flex-wrap gap-1 border-b border-border p-2">
            {watchlists.map((wl) => (
              <div key={wl.id} className="group flex items-center">
                <button
                  type="button"
                  onClick={() => setActiveWatchlistId(wl.id)}
                  className={cn(
                    'rounded-l-full rounded-r-sm border px-2 py-0.5 text-[11px] font-medium transition-colors',
                    wl.id === activeWatchlistId
                      ? 'border-primary bg-primary text-primary-foreground'
                      : 'border-border text-muted-foreground hover:bg-muted'
                  )}
                >
                  {wl.name}
                </button>
                <button
                  type="button"
                  onClick={() => handleDeleteWatchlistList(wl.id)}
                  className="rounded-r-full border border-l-0 border-border px-1 py-0.5 text-muted-foreground opacity-0 transition-opacity hover:text-loss group-hover:opacity-100"
                  aria-label={`Delete ${wl.name}`}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-1 border-b border-border p-2">
            <Input
              value={newListName}
              onChange={(e) => setNewListName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreateWatchlist()}
              placeholder="New list name..."
              className="h-7 text-xs"
              disabled={creatingList}
            />
            <Button
              variant="outline"
              size="icon"
              className="h-7 w-7 shrink-0"
              onClick={handleCreateWatchlist}
              disabled={creatingList || !newListName.trim()}
              aria-label="Create watchlist"
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </div>

          {!activeWatchlist ? (
            <p className="p-3 text-[11px] text-muted-foreground">
              {watchlists.length === 0 ? 'No watchlists yet — create one above.' : 'Select a list.'}
            </p>
          ) : activeWatchlist.items.length === 0 ? (
            <p className="p-3 text-[11px] text-muted-foreground">
              No symbols in "{activeWatchlist.name}" yet. Search a symbol above and tap the star to
              add it.
            </p>
          ) : (
            <div>
              {activeWatchlist.items.map((w) => {
                const isActive = w.symbol === selectedSymbol && w.exchange === selectedExchange
                const key = `${w.symbol}:${w.exchange}`
                return (
                  <div
                    key={key}
                    className={cn(
                      'group flex items-center justify-between gap-1 border-b border-border px-3 py-2 text-xs cursor-pointer',
                      isActive ? 'bg-primary/10' : 'hover:bg-muted'
                    )}
                    onClick={() => handleSymbolSelect(w.symbol, w.exchange)}
                  >
                    <div className="min-w-0">
                      <div className="truncate font-medium">{w.symbol}</div>
                      <div className="text-[10px] text-muted-foreground">{w.exchange}</div>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleRemoveFromWatchlist(activeWatchlist.id, w.symbol, w.exchange)
                      }}
                      disabled={watchlistMutating === key}
                      className="shrink-0 text-muted-foreground opacity-0 transition-opacity hover:text-loss group-hover:opacity-100"
                      aria-label={`Remove ${w.symbol} from watchlist`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )
              })}
            </div>
          )}
        </div>
        <div className="relative flex-1 min-w-0">
          <div className="absolute left-2 top-2 z-10 flex items-center gap-1 rounded-md border border-border bg-card p-1 shadow-sm">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  className={cn(
                    'flex h-7 items-center gap-1 rounded px-1.5 transition-colors',
                    activeDrawingTool
                      ? 'bg-primary text-primary-foreground'
                      : 'text-muted-foreground hover:bg-muted'
                  )}
                  title="Drawing tools"
                  aria-label="Drawing tools menu"
                >
                  <PenLine className="h-4 w-4" />
                  <ChevronDown className="h-3 w-3" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56">
                <DropdownMenuItem
                  onClick={() =>
                    setActiveDrawingTool((t) => (t === 'trendline' ? null : 'trendline'))
                  }
                  className={cn(activeDrawingTool === 'trendline' && 'bg-accent')}
                >
                  <Slash className="h-4 w-4 mr-2" />
                  Trendline
                  <span className="ml-auto text-[10px] text-muted-foreground">2 clicks</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() =>
                    setActiveDrawingTool((t) => (t === 'horizontal_ray' ? null : 'horizontal_ray'))
                  }
                  className={cn(activeDrawingTool === 'horizontal_ray' && 'bg-accent')}
                >
                  <MoveHorizontal className="h-4 w-4 mr-2" />
                  Horizontal Ray
                  <span className="ml-auto text-[10px] text-muted-foreground">1 click</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() =>
                    setActiveDrawingTool((t) => (t === 'rectangle' ? null : 'rectangle'))
                  }
                  className={cn(activeDrawingTool === 'rectangle' && 'bg-accent')}
                >
                  <Square className="h-4 w-4 mr-2" />
                  Rectangle
                  <span className="ml-auto text-[10px] text-muted-foreground">2 clicks</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() =>
                    setActiveDrawingTool((t) => (t === 'fibonacci' ? null : 'fibonacci'))
                  }
                  className={cn(activeDrawingTool === 'fibonacci' && 'bg-accent')}
                >
                  <Percent className="h-4 w-4 mr-2" />
                  Fibonacci Retracement
                  <span className="ml-auto text-[10px] text-muted-foreground">2 clicks</span>
                </DropdownMenuItem>
                {drawings.length > 0 && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onClick={handleClearAllDrawings}
                      className="text-loss focus:text-loss"
                    >
                      <X className="h-4 w-4 mr-2" />
                      Clear all drawings
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Color swatch strip — only shown while a tool is armed, so
                repeated placements with the same tool don't need to reopen
                the dropdown to change color each time. */}
            {activeDrawingTool && (
              <div className="flex items-center gap-1 border-l border-border pl-1 ml-0.5">
                {DRAWING_COLOR_PALETTE.map((color) => (
                  <button
                    key={color}
                    type="button"
                    onClick={() => setDrawingColor(color)}
                    className={cn(
                      'h-4 w-4 shrink-0 rounded-full ring-offset-1 ring-offset-card transition-transform hover:scale-110',
                      drawingColor === color && 'ring-2 ring-foreground'
                    )}
                    style={{ backgroundColor: color }}
                    title={`Use ${color} for this drawing`}
                    aria-label={`Drawing color ${color}`}
                  />
                ))}
              </div>
            )}

            <div className="border-l border-border pl-1 ml-0.5 flex items-center gap-1">
              <button
                type="button"
                onClick={takeChartScreenshot}
                disabled={isCapturingScreenshot}
                className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
                title="Save chart screenshot"
                aria-label="Save chart screenshot"
              >
                {isCapturingScreenshot ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Camera className="h-4 w-4" />
                )}
              </button>
              <button
                type="button"
                onClick={toggleFullscreen}
                className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted"
                title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen chart'}
                aria-label={isFullscreen ? 'Exit fullscreen' : 'Fullscreen chart'}
              >
                {isFullscreen ? <Minimize className="h-4 w-4" /> : <Maximize className="h-4 w-4" />}
              </button>
            </div>
          </div>
          <LiveCandlestickChart
            bars={bars}
            intervalSeconds={intervalSeconds}
            overlays={overlays}
            signals={signals}
            supportResistanceLevels={srLevels}
            liveTick={liveTick}
            isLoading={isLoadingChart}
            drawingColor={drawingColor}
            activeDrawingTool={activeDrawingTool}
            drawings={drawings}
            onDrawingCreated={handleDrawingCreated}
            onDrawingDeleted={handleDrawingDeleted}
            onDrawingToolConsumed={() => setActiveDrawingTool(null)}
          />
        </div>
        <div className="w-96 shrink-0 overflow-y-auto border-l border-border p-3 space-y-3">
          {selectedSymbol && selectedExchange && (
            <AiInsightCard
              symbol={selectedSymbol}
              exchange={selectedExchange}
              interval={selectedInterval}
              livePrice={liveTick?.ltp}
              availableIndicators={AVAILABLE_INDICATORS.map((ind) => ({
                key: ind.key,
                label: ind.label,
              }))}
              chartEnabledIndicatorKeys={enabledIndicators}
              availableBalance={availableBalance}
            />
          )}
          {selectedSymbol && selectedExchange ? (
            <QuickOrderTicket
              symbol={selectedSymbol}
              exchange={selectedExchange}
              ltp={liveTick?.ltp}
              apiKey={apiKey ?? ''}
              strategyName={strategyName}
            />
          ) : (
            <p className="text-xs text-muted-foreground">Select a symbol to place an order.</p>
          )}
        </div>
      </div>

      <CustomIndicatorBuilder
        open={builderOpen}
        onOpenChange={setBuilderOpen}
        onCreated={loadCustomIndicators}
      />
    </div>
  )
}

function cnBadge(appMode: 'live' | 'analyzer'): string {
  return appMode === 'analyzer' ? 'text-xs bg-purple-500 hover:bg-purple-600 text-white' : 'text-xs'
}

// Re-exported so the pure tick-aggregation helper stays reachable from
// this page's own module graph for future unit tests without a second copy.
export { aggregateTickIntoCandle }
