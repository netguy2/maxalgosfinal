// components/charts/LiveCandlestickChart.tsx
// Reusable live-updating candlestick chart with indicator overlays and
// buy/sell signal markers. Extracted from the proven chart-init pattern in
// pages/HistorifyCharts.tsx (createChart/CandlestickSeries/HistogramSeries,
// IST-aware time formatting, ResizeObserver) — that page is left untouched;
// this is a new, separate component for the Charts page.
//
// Purely presentational: does not fetch data or subscribe to anything
// itself. The parent owns fetching historical candles, indicator series,
// and the live WebSocket tick, and passes them down as props.

import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  LineSeries,
  type MouseEventParams,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  type ChartDrawing,
  createPrimitiveForDrawing,
  type FibonacciDrawing,
  type HorizontalRayDrawing,
  type RectangleDrawing,
  type TrendlineDrawing,
} from '@/components/charts/chartDrawings'
import { useChartTheme } from '@/lib/chart-theme'

export interface OHLCVBar {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface ChartOverlay {
  id: string
  label: string
  color: string
  data: Array<{ time: number; value: number }>
  lineWidth?: 1 | 2 | 3 | 4
  /**
   * Which pane this series belongs to. Omitted/'price' plots on the main
   * candle pane (correct for EMA/SMA/VWAP/Bollinger — already in price
   * units). Oscillators (RSI, MACD, ATR) are in entirely different value
   * ranges (RSI is 0-100, MACD/ATR are small deltas) and are invisible if
   * plotted on the same axis as a ~1000+ price — those get routed to
   * their own sub-pane below the price chart.
   */
  paneHint?: 'price' | 'rsi' | 'macd' | 'atr' | 'stoch'
}

export interface ChartSignal {
  time: number
  side: 'BUY' | 'SELL'
  /** Which signal source(s) fired here, e.g. ['EMA_SMA_CROSS', 'RSI_OVERSOLD'] — shown in the signals log, not on-canvas. */
  sources?: string[]
}

export interface LiveTick {
  ltp: number
  /** Epoch seconds of the tick. */
  timestamp: number
}

export interface SupportResistanceLevel {
  price: number
  side: 'support' | 'resistance'
  /** Touch count — used to scale line thickness/opacity so stronger levels stand out. */
  touches: number
}

interface LiveCandlestickChartProps {
  bars: OHLCVBar[]
  /** Interval in seconds, used both for IST formatting decisions and live
   * tick bucketing (e.g. 300 for "5m", 86400 for "D"). */
  intervalSeconds: number
  overlays?: ChartOverlay[]
  signals?: ChartSignal[]
  supportResistanceLevels?: SupportResistanceLevel[]
  liveTick?: LiveTick | null
  isLoading?: boolean
  /** Which drawing tool is armed for click-to-place, or null/undefined when not drawing. */
  activeDrawingTool?: 'trendline' | 'horizontal_ray' | 'rectangle' | 'fibonacci' | null
  /** Color for the next drawing placed with the active tool (and its live preview). */
  drawingColor?: string
  drawings?: ChartDrawing[]
  onDrawingCreated?: (drawing: ChartDrawing) => void
  onDrawingDeleted?: (id: string) => void
  /** Called once a click-to-place drawing completes, so the page can clear activeDrawingTool. */
  onDrawingToolConsumed?: () => void
}

/**
 * Pure helper: given the current last bar and an incoming live tick,
 * returns the bar that should now be the last bar on the chart — either
 * the same bar updated in place (tick falls within its bucket) or a new
 * bar (tick starts a new bucket). Isolated from the component so it's
 * independently testable and has no DOM/chart-library dependency.
 */
export function aggregateTickIntoCandle(
  lastBar: OHLCVBar | undefined,
  tick: LiveTick,
  intervalSeconds: number
): OHLCVBar {
  const bucketStart = Math.floor(tick.timestamp / intervalSeconds) * intervalSeconds
  if (lastBar && lastBar.timestamp === bucketStart) {
    return {
      timestamp: lastBar.timestamp,
      open: lastBar.open,
      high: Math.max(lastBar.high, tick.ltp),
      low: Math.min(lastBar.low, tick.ltp),
      close: tick.ltp,
      volume: lastBar.volume,
    }
  }
  return {
    timestamp: bucketStart,
    open: tick.ltp,
    high: tick.ltp,
    low: tick.ltp,
    close: tick.ltp,
    volume: 0,
  }
}

function formatTimeIST(time: number, intraday: boolean): string {
  const date = new Date(time * 1000)
  const istOffset = 5.5 * 60 * 60 * 1000
  const istDate = new Date(date.getTime() + istOffset)
  const day = istDate.getUTCDate().toString().padStart(2, '0')
  const month = (istDate.getUTCMonth() + 1).toString().padStart(2, '0')
  const year = istDate.getUTCFullYear().toString().slice(-2)
  if (!intraday) return `${day}/${month}/${year}`
  const hours = istDate.getUTCHours().toString().padStart(2, '0')
  const minutes = istDate.getUTCMinutes().toString().padStart(2, '0')
  return `${day}/${month}/${year} ${hours}:${minutes}`
}

export function LiveCandlestickChart({
  bars,
  intervalSeconds,
  overlays = [],
  signals = [],
  supportResistanceLevels = [],
  liveTick,
  isLoading,
  activeDrawingTool,
  drawingColor,
  drawings = [],
  onDrawingCreated,
  onDrawingDeleted,
  onDrawingToolConsumed,
}: LiveCandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  // Bumped every time the chart is actually (re)created (e.g. after a
  // theme change tears down and rebuilds it — see the init effect below).
  // The bars/signals, overlays, and support/resistance effects depend on
  // this INSTEAD OF depending on chartTheme directly: they used to fire in
  // the same render pass as the teardown, before the 100ms-deferred
  // createChart() call had run, so chartRef.current/candleSeriesRef.current
  // were still null/stale — each effect's `if (!chart) return` guard made
  // it silently no-op and never re-fire once the new chart existed,
  // wiping every marker/overlay/S-R line on every theme toggle. Depending
  // on this counter instead means those effects only run again once the
  // new chart instance genuinely exists.
  const [_chartInstanceId, setChartInstanceId] = useState(0)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const overlaySeriesRef = useRef<Map<string, ISeriesApi<'Line'>>>(new Map())
  const markersPluginRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const lastBarRef = useRef<OHLCVBar | undefined>(undefined)
  const drawingPrimitivesRef = useRef<Map<string, ReturnType<typeof createPrimitiveForDrawing>>>(
    new Map()
  )
  // Shared staging point for every click-click (two-point) drawing tool —
  // trendline, rectangle, and fibonacci all follow the identical
  // first-click-stores/second-click-completes pattern, so one ref covers
  // all three; only horizontal_ray is single-click.
  const pendingTwoPointRef = useRef<{ time: number; price: number } | null>(null)
  // The in-progress drawing's live preview — recomputed on every crosshair
  // move once a first point is staged, so the user sees the rectangle/fib/
  // trendline forming in real time instead of only on the second click
  // (TradingView-style drag preview). Rendered via the exact same
  // createPrimitiveForDrawing() primitives as a real drawing, just held in
  // a separate ref/effect so it never gets confused with persisted drawings.
  const previewPrimitiveRef = useRef<ReturnType<typeof createPrimitiveForDrawing> | null>(null)
  const [previewDrawing, setPreviewDrawing] = useState<ChartDrawing | null>(null)
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null)
  // Timestamp of the first bar in the last dataset we auto-fit the view
  // to. Only re-running fitContent() when this changes (a genuinely new
  // dataset — symbol/interval switch, or first load) instead of on every
  // bars update keeps the user's manual zoom/pan intact across the 30s
  // background refresh and across signals/overlay toggles (which also
  // flow through this same effect but don't change what candles exist).
  const fittedFirstBarTimeRef = useRef<number | null>(null)
  // Support/resistance are rendered as horizontal price lines attached to
  // the candle series (createPriceLine), not a separate line series —
  // they're static horizontal levels, not a time-series. Tracked here so
  // they can all be removed and redrawn when the level set changes.
  const srPriceLinesRef = useRef<ReturnType<ISeriesApi<'Candlestick'>['createPriceLine']>[]>([])
  // paneHint ('rsi' | 'macd' | 'atr') -> the pane index lightweight-charts
  // assigned it. Populated lazily the first time a series with that hint
  // is added; panes auto-collapse when their last series is removed
  // (lightweight-charts' default preserveEmptyPane: false), so this map
  // is cleared whenever we detect a hint no longer has any live series.
  const oscillatorPaneIndexRef = useRef<Map<string, number>>(new Map())
  const rsiReferenceLinesRef = useRef<ReturnType<ISeriesApi<'Line'>['createPriceLine']>[]>([])

  const chartTheme = useChartTheme()
  const isIntraday = intervalSeconds < 86400

  // Init chart once per theme/interval-shape change (same lifecycle as
  // HistorifyCharts.tsx's chart-init effect). bars is intentionally read
  // only for the initial seed here — subsequent bar updates go through
  // the effect below instead of tearing down and recreating the chart.
  // biome-ignore lint/correctness/useExhaustiveDependencies: only re-init on theme/interval-shape change; bars/overlays/signals update the existing chart via the effects below
  useEffect(() => {
    if (!containerRef.current) return

    const initTimer = setTimeout(() => {
      if (!containerRef.current) return
      // Preserve the user's zoom/pan across a theme-triggered rebuild —
      // capture the outgoing chart's visible logical range before tearing
      // it down, then restore it on the new chart below instead of always
      // calling fitContent() (which would reset to "fit all data" on every
      // theme toggle, even mid-analysis with a deliberately zoomed view).
      let preservedRange: { from: number; to: number } | null = null
      if (chartRef.current) {
        try {
          const range = chartRef.current.timeScale().getVisibleLogicalRange()
          if (range) preservedRange = { from: range.from, to: range.to }
        } catch {
          // Chart already in a bad state (e.g. container unmounted) -- fall
          // through to fitContent() below rather than blocking teardown.
        }
        chartRef.current.remove()
        chartRef.current = null
      }

      const container = containerRef.current
      const chart = createChart(container, {
        width: container.offsetWidth || 800,
        height: Math.max(container.offsetHeight || 600, 500),
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: chartTheme.mutedForeground,
        },
        grid: {
          vertLines: { color: chartTheme.border },
          horzLines: { color: chartTheme.border },
        },
        localization: {
          timeFormatter: (time: number) => formatTimeIST(time, isIntraday),
        },
        rightPriceScale: {
          borderColor: chartTheme.border,
          scaleMargins: { top: 0.1, bottom: 0.25 },
        },
        timeScale: {
          borderColor: chartTheme.border,
          timeVisible: isIntraday,
          secondsVisible: false,
          tickMarkFormatter: (time: number) => {
            const date = new Date(time * 1000)
            const istDate = new Date(date.getTime() + 5.5 * 60 * 60 * 1000)
            if (isIntraday) {
              const hours = istDate.getUTCHours().toString().padStart(2, '0')
              const minutes = istDate.getUTCMinutes().toString().padStart(2, '0')
              return `${hours}:${minutes}`
            }
            return istDate.getUTCDate().toString()
          },
        },
        crosshair: {
          mode: CrosshairMode.Normal,
          vertLine: {
            width: 1,
            color: `${chartTheme.mutedForeground}80`,
            style: 2,
            labelVisible: true,
            labelBackgroundColor: chartTheme.primary,
          },
          horzLine: {
            width: 1,
            color: `${chartTheme.mutedForeground}80`,
            style: 2,
            labelBackgroundColor: chartTheme.primary,
          },
        },
      })

      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: chartTheme.profit,
        downColor: chartTheme.loss,
        borderVisible: false,
        wickUpColor: chartTheme.profit,
        wickDownColor: chartTheme.loss,
      })

      const volumeSeries = chart.addSeries(HistogramSeries, {
        color: `${chartTheme.profit}99`,
        priceFormat: { type: 'volume' },
        priceScaleId: '',
      })
      volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })

      chartRef.current = chart
      candleSeriesRef.current = candleSeries
      volumeSeriesRef.current = volumeSeries
      overlaySeriesRef.current = new Map()
      markersPluginRef.current = createSeriesMarkers(candleSeries, [])

      if (bars.length > 0) {
        candleSeries.setData(
          bars.map((b) => ({
            time: b.timestamp as UTCTimestamp,
            open: b.open,
            high: b.high,
            low: b.low,
            close: b.close,
          }))
        )
        volumeSeries.setData(
          bars.map((b) => ({
            time: b.timestamp as UTCTimestamp,
            value: b.volume,
            color: b.close >= b.open ? 'rgba(34, 197, 94, 0.5)' : 'rgba(239, 68, 68, 0.5)',
          }))
        )
        lastBarRef.current = bars[bars.length - 1]
        fittedFirstBarTimeRef.current = bars[0].timestamp
        if (preservedRange) {
          chart.timeScale().setVisibleLogicalRange(preservedRange)
        } else {
          chart.timeScale().fitContent()
        }
      }

      // Signal to the bars/signals, overlays, and support/resistance
      // effects that a fresh chart instance now exists so they can
      // (re)draw against it -- see chartInstanceId's declaration above.
      setChartInstanceId((id) => id + 1)
    }, 100)

    const handleResize = () => {
      if (chartRef.current && containerRef.current) {
        const width = containerRef.current.offsetWidth
        const height = containerRef.current.offsetHeight
        if (width > 0 && height > 0) chartRef.current.applyOptions({ width, height })
      }
    }
    const resizeObserver = new ResizeObserver(handleResize)
    if (containerRef.current) resizeObserver.observe(containerRef.current)
    window.addEventListener('resize', handleResize)

    return () => {
      clearTimeout(initTimer)
      resizeObserver.disconnect()
      window.removeEventListener('resize', handleResize)
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
      }
    }
  }, [chartTheme, isIntraday])

  // Push new historical bars into the existing chart without re-creating
  // it, and sync signal markers in the SAME effect (not a separately
  // racing one) — markers are filtered to timestamps actually present in
  // `bars` right here, where `bars` is guaranteed to be the exact dataset
  // just applied via setData. This is what fixes markers silently
  // failing to render (and appearing to "disappear on zoom") when they'd
  // otherwise be computed against a slightly stale bars snapshot from an
  // independent async fetch in the parent.
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current) return

    // Explicitly clear stale candles/volume when bars goes empty (symbol
    // switch in flight, an error response, or a genuinely empty dataset)
    // instead of silently no-op'ing — without this, the previous symbol's
    // candles (and its price scale) stayed on screen looking like the new
    // symbol's chart, since setData() was simply never called again.
    if (bars.length === 0) {
      candleSeriesRef.current.setData([])
      volumeSeriesRef.current.setData([])
      lastBarRef.current = undefined
      fittedFirstBarTimeRef.current = null
      markersPluginRef.current?.setMarkers([])
      return
    }

    candleSeriesRef.current.setData(
      bars.map((b) => ({
        time: b.timestamp as UTCTimestamp,
        open: b.open,
        high: b.high,
        low: b.low,
        close: b.close,
      }))
    )
    volumeSeriesRef.current.setData(
      bars.map((b) => ({
        time: b.timestamp as UTCTimestamp,
        value: b.volume,
        color: b.close >= b.open ? 'rgba(34, 197, 94, 0.5)' : 'rgba(239, 68, 68, 0.5)',
      }))
    )
    lastBarRef.current = bars[bars.length - 1]

    // Only auto-fit the visible range when the dataset's start actually
    // changed (new symbol/interval, or the very first load) — not on
    // every re-render this effect runs for (new candles from the 30s
    // background refresh, or a signals/overlay toggle that leaves the
    // candle data itself unchanged). Without this guard, toggling
    // Buy/Sell Signals or Support/Resistance — or simply waiting for the
    // periodic refresh — would silently reset the user's zoom/pan.
    const firstBarTime = bars[0].timestamp
    if (fittedFirstBarTimeRef.current !== firstBarTime) {
      fittedFirstBarTimeRef.current = firstBarTime
      chartRef.current?.timeScale().fitContent()
    }

    if (markersPluginRef.current) {
      const barTimes = new Set(bars.map((b) => b.timestamp))
      markersPluginRef.current.setMarkers(
        signals
          .filter((s) => barTimes.has(s.time))
          .map((s) => ({
            time: s.time as UTCTimestamp,
            position: s.side === 'BUY' ? 'belowBar' : 'aboveBar',
            shape: s.side === 'BUY' ? 'arrowUp' : 'arrowDown',
            color: s.side === 'BUY' ? chartTheme.profit : chartTheme.loss,
          }))
      )
    }
  }, [bars, signals, chartTheme])

  // Sync overlay line series to the `overlays` prop — add/update/remove as
  // the indicator selection changes. Oscillators (paneHint 'rsi' | 'macd' |
  // 'atr') get routed to their own sub-pane via addSeries' paneIndex
  // param — lightweight-charts auto-creates a pane for a paneIndex that
  // doesn't exist yet, and auto-collapses a pane once its last series is
  // removed, so no manual addPane()/removePane() bookkeeping is needed.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const existing = overlaySeriesRef.current
    const paneIndexByHint = oscillatorPaneIndexRef.current

    const activeHints = new Set(
      overlays
        .map((o) => o.paneHint)
        .filter((h): h is 'rsi' | 'macd' | 'atr' => !!h && h !== 'price')
    )
    // A hint whose pane was previously assigned but has no overlays this
    // render will have its series removed below, collapsing that pane —
    // drop the stale index so a later re-enable gets a fresh pane rather
    // than reusing a now-wrong index.
    for (const hint of paneIndexByHint.keys()) {
      if (!activeHints.has(hint as 'rsi' | 'macd' | 'atr')) paneIndexByHint.delete(hint)
    }

    let nextPaneIndex = chart.panes().length
    for (const hint of activeHints) {
      if (!paneIndexByHint.has(hint)) {
        paneIndexByHint.set(hint, nextPaneIndex)
        nextPaneIndex++
      }
    }

    for (const overlay of overlays) {
      let series = existing.get(overlay.id)
      const paneIndex =
        overlay.paneHint && overlay.paneHint !== 'price'
          ? paneIndexByHint.get(overlay.paneHint)
          : undefined
      if (!series) {
        series = chart.addSeries(
          LineSeries,
          { color: overlay.color, lineWidth: overlay.lineWidth ?? 2, title: overlay.label },
          paneIndex
        )
        existing.set(overlay.id, series)
      }
      series.setData(overlay.data.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })))
    }

    for (const [id, series] of existing) {
      if (!overlays.some((o) => o.id === id)) {
        chart.removeSeries(series)
        existing.delete(id)
      }
    }

    // Keep the RSI pane's 30/70 reference lines attached to whichever RSI
    // series is currently live. Price lines are owned by the series they
    // were created on, so if that series was just removed above, its
    // lines are already gone with it — just reset our tracking ref.
    rsiReferenceLinesRef.current = []
    const rsiOverlay = overlays.find((o) => o.paneHint === 'rsi')
    if (rsiOverlay) {
      const rsiSeries = existing.get(rsiOverlay.id)
      if (rsiSeries) {
        rsiReferenceLinesRef.current = [
          rsiSeries.createPriceLine({
            price: 70,
            color: chartTheme.loss,
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
            title: 'Overbought',
          }),
          rsiSeries.createPriceLine({
            price: 30,
            color: chartTheme.profit,
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
            title: 'Oversold',
          }),
        ]
      }
    }
  }, [overlays, chartTheme])

  // Sync support/resistance horizontal levels — static price lines on the
  // candle series, redrawn whenever the level set changes. Line
  // thickness/opacity scales with touch count so stronger (more-tested)
  // levels visually stand out from weaker ones.
  useEffect(() => {
    const candleSeries = candleSeriesRef.current
    if (!candleSeries) return

    for (const line of srPriceLinesRef.current) {
      candleSeries.removePriceLine(line)
    }
    srPriceLinesRef.current = []

    if (supportResistanceLevels.length === 0) return
    const maxTouches = Math.max(...supportResistanceLevels.map((l) => l.touches), 1)

    srPriceLinesRef.current = supportResistanceLevels.map((level) => {
      const strength = level.touches / maxTouches
      const color = level.side === 'resistance' ? chartTheme.loss : chartTheme.profit
      return candleSeries.createPriceLine({
        price: level.price,
        color: `${color}${Math.round((0.4 + 0.5 * strength) * 255)
          .toString(16)
          .padStart(2, '0')}`,
        lineWidth: strength > 0.66 ? 2 : 1,
        lineStyle: 3,
        axisLabelVisible: true,
        title: `${level.side === 'resistance' ? 'R' : 'S'} (${level.touches}x)`,
      })
    })
  }, [supportResistanceLevels, chartTheme])

  // Sync manually-placed drawings (trendlines/horizontal rays) to attached
  // primitives — add/update/remove to match the `drawings` array, same
  // add/remove bookkeeping shape already used for overlaySeriesRef above.
  // Re-creating the primitive on every content change (rather than
  // mutating it in place) keeps this simple; drawings are small in number
  // compared to indicator series, so the cost is negligible.
  useEffect(() => {
    const series = candleSeriesRef.current
    if (!series) return
    const existing = drawingPrimitivesRef.current

    for (const drawing of drawings) {
      const current = existing.get(drawing.id)
      if (current) series.detachPrimitive(current)
      const primitive = createPrimitiveForDrawing(drawing)
      primitive.selected = drawing.id === selectedDrawingId
      series.attachPrimitive(primitive)
      existing.set(drawing.id, primitive)
    }

    for (const [id, primitive] of existing) {
      if (!drawings.some((d) => d.id === id)) {
        series.detachPrimitive(primitive)
        existing.delete(id)
      }
    }
  }, [drawings, selectedDrawingId])

  // Sync the in-progress drawing's live preview (see previewDrawing state
  // above) to its own primitive, kept entirely separate from
  // drawingPrimitivesRef so it's never mistaken for a persisted drawing and
  // never round-trips through onDrawingCreated/the drawings prop.
  useEffect(() => {
    const series = candleSeriesRef.current
    if (!series) return

    if (previewPrimitiveRef.current) {
      series.detachPrimitive(previewPrimitiveRef.current)
      previewPrimitiveRef.current = null
    }
    if (previewDrawing) {
      const primitive = createPrimitiveForDrawing(previewDrawing)
      series.attachPrimitive(primitive)
      previewPrimitiveRef.current = primitive
    }

    return () => {
      if (previewPrimitiveRef.current) {
        series.detachPrimitive(previewPrimitiveRef.current)
        previewPrimitiveRef.current = null
      }
    }
  }, [previewDrawing])

  // Click-to-place interaction for the active drawing tool, and click-to-
  // select an existing drawing (via hitTest -> hoveredObjectId) when no
  // tool is armed. lightweight-charts provides hitTest for cursor styling
  // and hover/click object identification only — actual point placement
  // and the two-click trendline workflow are entirely app-wired here via
  // subscribeClick, reading MouseEventParams.time/point and converting
  // through the series/time-scale coordinate APIs.
  useEffect(() => {
    const chart = chartRef.current
    const series = candleSeriesRef.current
    if (!chart || !series) return

    const buildDrawing = (
      pointA: { time: number; price: number },
      pointB: { time: number; price: number },
      id: string
    ): TrendlineDrawing | RectangleDrawing | FibonacciDrawing | null => {
      const color = drawingColor ?? chartTheme.primary
      if (activeDrawingTool === 'rectangle') {
        return { id, type: 'rectangle', pointA, pointB, color }
      }
      if (activeDrawingTool === 'fibonacci') {
        return { id, type: 'fibonacci', pointA, pointB, color }
      }
      if (activeDrawingTool === 'trendline') {
        return { id, type: 'trendline', pointA, pointB, color }
      }
      return null
    }

    const handleClick = (param: MouseEventParams<Time>) => {
      if (!activeDrawingTool) {
        // No tool armed — clicking a drawing selects it, clicking empty space deselects.
        const hoveredId = param.hoveredObjectId as string | undefined
        setSelectedDrawingId(hoveredId ?? null)
        return
      }
      if (param.time === undefined || !param.point) return
      const price = series.coordinateToPrice(param.point.y)
      if (price === null) return
      const time = param.time as unknown as number

      if (activeDrawingTool === 'horizontal_ray') {
        const drawing: HorizontalRayDrawing = {
          id: `local_${Date.now()}`,
          type: 'horizontal_ray',
          point: { time, price },
          color: drawingColor ?? chartTheme.primary,
        }
        onDrawingCreated?.(drawing)
        onDrawingToolConsumed?.()
        return
      }

      // trendline/rectangle/fibonacci — first click stores point A (and
      // arms the live preview via the crosshair-move handler below),
      // second click completes it.
      if (!pendingTwoPointRef.current) {
        pendingTwoPointRef.current = { time, price }
        return
      }
      const pointA = pendingTwoPointRef.current
      const pointB = { time, price }
      pendingTwoPointRef.current = null
      setPreviewDrawing(null)

      const drawing = buildDrawing(pointA, pointB, `local_${Date.now()}`)
      if (!drawing) return
      onDrawingCreated?.(drawing)
      onDrawingToolConsumed?.()
    }

    // Live preview: once point A is staged, redraw the in-progress shape on
    // every crosshair move so the user sees it forming before the second
    // click — mirrors the drag-to-preview feel of TradingView-style tools
    // without needing actual mouse-drag plumbing (lightweight-charts only
    // exposes click + crosshair-move, no native drag events on the pane).
    const handleCrosshairMove = (param: MouseEventParams<Time>) => {
      if (!activeDrawingTool || activeDrawingTool === 'horizontal_ray') return
      if (!pendingTwoPointRef.current) return
      if (param.time === undefined || !param.point) return
      const price = series.coordinateToPrice(param.point.y)
      if (price === null) return
      const time = param.time as unknown as number

      const preview = buildDrawing(pendingTwoPointRef.current, { time, price }, '__preview__')
      setPreviewDrawing(preview)
    }

    chart.subscribeClick(handleClick)
    chart.subscribeCrosshairMove(handleCrosshairMove)
    return () => {
      chart.unsubscribeCrosshairMove(handleCrosshairMove)
      chart.unsubscribeClick(handleClick)
    }
  }, [activeDrawingTool, drawingColor, chartTheme, onDrawingCreated, onDrawingToolConsumed])

  // Clear any in-progress trendline/rectangle/fibonacci placement (and its
  // live preview) when the tool is disarmed — e.g. user pressed Escape or
  // switched tools — rather than leaving a stale first point that would
  // silently attach to the next click.
  useEffect(() => {
    if (!activeDrawingTool) {
      pendingTwoPointRef.current = null
      setPreviewDrawing(null)
    }
  }, [activeDrawingTool])

  // Delete the selected drawing with Delete/Backspace, same convention as
  // the rest of the Charts page (keyboard delete for selected items).
  useEffect(() => {
    if (!selectedDrawingId) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Delete' && e.key !== 'Backspace') return
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return
      onDrawingDeleted?.(selectedDrawingId)
      setSelectedDrawingId(null)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedDrawingId, onDrawingDeleted])

  // Live tick -> update or append the forming candle in place.
  const lastTickKey = useMemo(
    () => (liveTick ? `${liveTick.timestamp}:${liveTick.ltp}` : null),
    [liveTick]
  )
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-run only when the tick actually changes (lastTickKey captures liveTick's identity), not on every render
  useEffect(() => {
    if (!liveTick || !candleSeriesRef.current) return
    const updated = aggregateTickIntoCandle(lastBarRef.current, liveTick, intervalSeconds)
    // liveTick.timestamp is the browser's local receive time (Date.now()),
    // not an exchange timestamp -- see Charts.tsx's liveTick useMemo. Clock
    // skew between the browser and the broker's history feed (or simply a
    // tick landing right at a bucket boundary before the REST history's
    // last bar has "closed") can produce a bucket time at or before
    // lastBarRef.current's. lightweight-charts' series.update() throws
    // "Cannot update oldest data" for any time <= what's already the last
    // point, so never call it with a regressed timestamp -- fold the tick
    // into the existing last bar instead of dropping/crashing on it.
    if (lastBarRef.current && updated.timestamp < lastBarRef.current.timestamp) {
      const merged: OHLCVBar = {
        ...lastBarRef.current,
        high: Math.max(lastBarRef.current.high, liveTick.ltp),
        low: Math.min(lastBarRef.current.low, liveTick.ltp),
        close: liveTick.ltp,
      }
      lastBarRef.current = merged
      candleSeriesRef.current.update({
        time: merged.timestamp as UTCTimestamp,
        open: merged.open,
        high: merged.high,
        low: merged.low,
        close: merged.close,
      })
      return
    }
    lastBarRef.current = updated
    candleSeriesRef.current.update({
      time: updated.timestamp as UTCTimestamp,
      open: updated.open,
      high: updated.high,
      low: updated.low,
      close: updated.close,
    })
  }, [lastTickKey, intervalSeconds])

  return (
    <div className="relative h-full w-full">
      <div
        ref={containerRef}
        className={activeDrawingTool ? 'h-full w-full cursor-crosshair' : 'h-full w-full'}
      />
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/60">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      )}
      {!isLoading && bars.length === 0 && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <p className="text-sm text-muted-foreground">No chart data available</p>
        </div>
      )}
    </div>
  )
}
