// api/historify.ts
// Thin wrappers around Historify's session-authenticated REST endpoints
// (blueprints/historify.py). Uses raw fetch with credentials: 'include',
// matching the pattern already used inline in pages/HistorifyCharts.tsx —
// these routes are session/CSRF-cookie authenticated, not apikey-based
// like the /api/v1/ Unified Broker API surface tradingApi.ts wraps.

export interface CatalogItem {
  symbol: string
  exchange: string
  interval: string
  first_timestamp: number
  last_timestamp: number
  record_count: number
  first_date?: string
  last_date?: string
}

export interface OHLCVBarDto {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface LiveChartDataResponse {
  status: 'success' | 'error'
  message?: string
  symbol?: string
  exchange?: string
  interval?: string
  data?: OHLCVBarDto[]
  count?: number
}

export interface WatchlistItem {
  id: number
  symbol: string
  exchange: string
  display_name?: string
  added_at: string
}

export interface IndicatorSeriesPoint {
  time: number
  value: number
}

export interface IndicatorSignal {
  time: number
  side: 'BUY' | 'SELL'
}

export interface IndicatorOverlayResponse {
  status: 'success' | 'error'
  message?: string
  /**
   * Keyed by display name — a single-output indicator like "EMA_20" maps
   * to an array of points; a multi-output indicator like "MACD" or
   * "BOLLINGER" maps to an object of named sub-series
   * (e.g. { macd: [...], signal: [...], histogram: [...] }).
   */
  data?: Record<string, IndicatorSeriesPoint[] | Record<string, IndicatorSeriesPoint[]>>
  /** Keyed by signal name, e.g. "EMA_SMA_CROSS", "RSI_OVERSOLD". */
  signals?: Record<string, IndicatorSignal[]>
}

/** One requested overlay — e.g. { name: 'EMA', params: [20] } or { name: 'BOLLINGER', params: [20, 2] }. */
export interface IndicatorRequest {
  name: 'EMA' | 'SMA' | 'VWAP' | 'RSI' | 'MACD' | 'ATR' | 'BOLLINGER' | 'STOCH'
  params?: (number | string)[]
}

export interface SupportResistanceLevel {
  price: number
  /** How many swing highs/lows clustered into this level — higher = stronger. */
  touches: number
}

export interface SupportResistanceResponse {
  status: 'success' | 'error'
  message?: string
  data?: {
    resistance: SupportResistanceLevel[]
    support: SupportResistanceLevel[]
  }
}

function serializeIndicators(indicators: IndicatorRequest[]): string {
  return indicators
    .map((ind) =>
      ind.params && ind.params.length > 0 ? `${ind.name}:${ind.params.join(':')}` : ind.name
    )
    .join(',')
}

// historify_bp is session/cookie-authenticated and NOT exempted from
// Flask-WTF's global CSRFProtect (app.py) — unlike apiKey-authenticated
// /api/v1/ routes, which are exempt. Every state-changing (POST/PUT/DELETE)
// call here must attach X-CSRFToken or the request 400s with "Security
// token expired or invalid" before the route handler even runs. Same
// pattern as lib/MarketDataManager.ts's fetchCSRFToken and api/client.ts's
// webClient interceptor.
async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', { credentials: 'include' })
  const data = await response.json()
  return data.csrf_token
}

export const historifyApi = {
  /** Get catalog of symbol/exchange/interval combos with data already downloaded. */
  getCatalog: async (): Promise<{ status: string; data?: CatalogItem[] }> => {
    const response = await fetch('/historify/api/catalog', { credentials: 'include' })
    return response.json()
  },

  /**
   * Get OHLCV data for charting, fetched live from the broker — works
   * immediately for any valid symbol/exchange, no pre-download step
   * (unlike getCatalog-gated Historify data). Used by pages/Charts.tsx.
   */
  getLiveChartData: async (
    symbol: string,
    exchange: string,
    interval: string
  ): Promise<LiveChartDataResponse> => {
    const params = new URLSearchParams({ symbol, exchange, interval })
    const response = await fetch(`/historify/api/live-data?${params}`, {
      credentials: 'include',
    })
    // A reverse proxy or infra failure in front of Flask can return a
    // non-JSON body (HTML error page, empty response) that response.json()
    // would throw on with an opaque "Unexpected end of JSON input" — catch
    // that here so the Charts page always gets a status/message shape it
    // can render, instead of an unhandled promise rejection.
    try {
      return await response.json()
    } catch {
      return {
        status: 'error',
        message: response.ok
          ? 'Server returned an unexpected (non-JSON) response'
          : `Server error (HTTP ${response.status})`,
      }
    }
  },

  /**
   * Compute indicator overlay series + crossover signals over the given
   * bars (POST, not GET — the bars array can be large). Pass the exact
   * same bars the chart is rendering (e.g. from getLiveChartData) so
   * overlays line up with the candles on screen.
   */
  getIndicatorSeries: async (
    bars: OHLCVBarDto[],
    indicators: IndicatorRequest[]
  ): Promise<IndicatorOverlayResponse> => {
    if (indicators.length === 0 || bars.length === 0) {
      return { status: 'success', data: {}, signals: {} }
    }
    const csrfToken = await fetchCSRFToken()
    const response = await fetch('/historify/api/indicators', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      body: JSON.stringify({ bars, indicators: serializeIndicators(indicators) }),
    })
    return response.json()
  },

  /**
   * Detect support/resistance levels from real swing highs/lows in the
   * given bars (POST — same "send the bars you're already rendering"
   * pattern as getIndicatorSeries). Not a fixed formula — clustered from
   * actual price reversals, ranked by touch count.
   */
  getSupportResistance: async (bars: OHLCVBarDto[]): Promise<SupportResistanceResponse> => {
    if (bars.length === 0) {
      return { status: 'success', data: { resistance: [], support: [] } }
    }
    const csrfToken = await fetchCSRFToken()
    const response = await fetch('/historify/api/support-resistance', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      body: JSON.stringify({ bars }),
    })
    return response.json()
  },

  /** Get all symbols in the user's Historify watchlist. */
  getWatchlist: async (): Promise<{ status: string; data?: WatchlistItem[] }> => {
    const response = await fetch('/historify/api/watchlist', { credentials: 'include' })
    return response.json()
  },

  /** Add a symbol to the watchlist. */
  addToWatchlist: async (
    symbol: string,
    exchange: string,
    displayName?: string
  ): Promise<{ status: string; message?: string }> => {
    const csrfToken = await fetchCSRFToken()
    const response = await fetch('/historify/api/watchlist', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      body: JSON.stringify({ symbol, exchange, display_name: displayName }),
    })
    return response.json()
  },

  /** Remove a symbol from the watchlist. */
  removeFromWatchlist: async (
    symbol: string,
    exchange: string
  ): Promise<{ status: string; message?: string }> => {
    const csrfToken = await fetchCSRFToken()
    const response = await fetch('/historify/api/watchlist', {
      method: 'DELETE',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
      body: JSON.stringify({ symbol, exchange }),
    })
    return response.json()
  },
}
