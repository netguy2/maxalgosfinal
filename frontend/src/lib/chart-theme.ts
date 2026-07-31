import { useEffect, useState } from 'react'
import { useThemeStore } from '@/stores/themeStore'

/**
 * Chart theming utility — the single bridge between the CSS design tokens
 * (src/index.css) and JS charting libraries (Plotly, lightweight-charts).
 *
 * Charts cannot read Tailwind classes, so this module resolves the CSS custom
 * properties at call time and normalizes them to hex strings (Plotly does not
 * understand `oklch()` values). Pages must use these helpers instead of
 * hardcoding chart colors.
 */

export interface ChartTheme {
  background: string
  foreground: string
  card: string
  muted: string
  mutedForeground: string
  border: string
  primary: string
  profit: string
  loss: string
  buy: string
  sell: string
  brand: string
  /** Categorical series palette (chart-1..5). */
  colorway: string[]
}

// Canvas used to normalize any CSS color (incl. oklch) to a hex string.
let normalizeCtx: CanvasRenderingContext2D | null | undefined

function getNormalizeCtx(): CanvasRenderingContext2D | null {
  if (normalizeCtx !== undefined) return normalizeCtx
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 1
    canvas.height = 1
    normalizeCtx = canvas.getContext('2d', { willReadFrequently: true })
  } catch {
    normalizeCtx = null
  }
  return normalizeCtx
}

const colorCache = new Map<string, string>()

/**
 * Convert any CSS color string to #rrggbb (or #rrggbbaa) hex.
 * Falls back to the raw string in environments without canvas (jsdom).
 */
export function normalizeCssColor(color: string): string {
  const cached = colorCache.get(color)
  if (cached) return cached

  const ctx = getNormalizeCtx()
  if (!ctx) return color

  try {
    ctx.clearRect(0, 0, 1, 1)
    ctx.fillStyle = color
    ctx.fillRect(0, 0, 1, 1)
    const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data
    const hex =
      a === 255
        ? `#${[r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')}`
        : `#${[r, g, b, a].map((v) => v.toString(16).padStart(2, '0')).join('')}`
    colorCache.set(color, hex)
    return hex
  } catch {
    return color
  }
}

/** Resolve a CSS custom property from the document root and normalize to hex. */
export function resolveToken(name: string): string {
  if (typeof document === 'undefined') return '#000000'
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  if (!raw) return '#000000'
  return normalizeCssColor(raw)
}

/** Snapshot of the current theme's chart-relevant tokens, hex-normalized. */
export function getChartTheme(): ChartTheme {
  return {
    background: resolveToken('--background'),
    foreground: resolveToken('--foreground'),
    card: resolveToken('--card'),
    muted: resolveToken('--muted'),
    mutedForeground: resolveToken('--muted-foreground'),
    border: resolveToken('--border'),
    primary: resolveToken('--primary'),
    profit: resolveToken('--profit'),
    loss: resolveToken('--loss'),
    buy: resolveToken('--buy'),
    sell: resolveToken('--sell'),
    brand: resolveToken('--brand'),
    colorway: [
      resolveToken('--chart-1'),
      resolveToken('--chart-2'),
      resolveToken('--chart-3'),
      resolveToken('--chart-4'),
      resolveToken('--chart-5'),
    ],
  }
}

/**
 * Base Plotly layout following the active theme. Spread page-specific
 * settings over it: `{ ...plotlyLayout(theme), title: ... }`.
 */
export function plotlyLayout(theme: ChartTheme): Record<string, unknown> {
  return {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    colorway: theme.colorway,
    font: { color: theme.mutedForeground, size: 12 },
    xaxis: { gridcolor: theme.border, zerolinecolor: theme.border, linecolor: theme.border },
    yaxis: { gridcolor: theme.border, zerolinecolor: theme.border, linecolor: theme.border },
    margin: { t: 32, r: 16, b: 40, l: 56 },
    hoverlabel: {
      bgcolor: theme.card,
      bordercolor: theme.border,
      font: { color: theme.foreground, size: 12 },
    },
  }
}

/** Base options for lightweight-charts following the active theme. */
export function lightweightChartsOptions(theme: ChartTheme): Record<string, unknown> {
  return {
    layout: {
      background: { color: 'transparent' },
      textColor: theme.mutedForeground,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: theme.border },
      horzLines: { color: theme.border },
    },
    timeScale: { borderColor: theme.border },
    rightPriceScale: { borderColor: theme.border },
    crosshair: {
      vertLine: { labelBackgroundColor: theme.primary },
      horzLine: { labelBackgroundColor: theme.primary },
    },
  }
}

/** Candlestick series colors (lightweight-charts) from profit/loss tokens. */
export function candleSeriesOptions(theme: ChartTheme): Record<string, unknown> {
  return {
    upColor: theme.profit,
    downColor: theme.loss,
    borderUpColor: theme.profit,
    borderDownColor: theme.loss,
    wickUpColor: theme.profit,
    wickDownColor: theme.loss,
  }
}

/**
 * Reactive chart theme — re-resolves tokens whenever light/dark mode,
 * analyzer/live mode, or the accent color changes, so charts re-render
 * in the new palette.
 */
export function useChartTheme(): ChartTheme {
  const mode = useThemeStore((s) => s.mode)
  const appMode = useThemeStore((s) => s.appMode)
  const color = useThemeStore((s) => s.color)
  const [theme, setTheme] = useState<ChartTheme>(() => getChartTheme())

  // Single effect covers both "read tokens after the DOM class/attribute
  // change has been applied" (mount) and "re-run when any theme dimension
  // changes" (mode/appMode/color deps) -- these used to be two separate
  // effects that both fired on mount, producing two redundant re-resolved
  // theme object references (a third object beyond the useState
  // initializer's) on every single mount. Every one of the 17 chart pages
  // using this hook feeds `theme` into a useCallback/useEffect dependency
  // array (e.g. PnLTracker.tsx's initChart), so each spurious reference
  // change cascaded into a real, duplicate network fetch on page load --
  // not just a wasted render.
  // biome-ignore lint/correctness/useExhaustiveDependencies: mode/appMode/color are the DOM triggers
  useEffect(() => {
    const frame = requestAnimationFrame(() => setTheme(getChartTheme()))
    return () => cancelAnimationFrame(frame)
  }, [mode, appMode, color])

  return theme
}
