// api/chart-watchlists.ts
// Wrappers around blueprints/chart_watchlists.py's session-authenticated
// REST endpoints for named, multiple Charts watchlists. Uses webClient
// (frontend/src/api/client.ts) — its request interceptor attaches
// X-CSRFToken automatically on POST/PUT/DELETE, no manual CSRF handling
// needed (same pattern as api/custom-indicators.ts).

import { webClient } from './client'

export interface ChartWatchlistSymbol {
  id: number
  symbol: string
  exchange: string
  added_at: string | null
}

export interface ChartWatchlist {
  id: number
  name: string
  created_at: string | null
  items: ChartWatchlistSymbol[]
}

interface ApiEnvelope<T> {
  status: 'success' | 'error'
  message?: string
  data?: T
}

export const chartWatchlistsApi = {
  list: async (): Promise<ApiEnvelope<ChartWatchlist[]>> => {
    const response = await webClient.get<ApiEnvelope<ChartWatchlist[]>>(
      '/chart-watchlists/api/list'
    )
    return response.data
  },

  create: async (name: string): Promise<ApiEnvelope<ChartWatchlist>> => {
    const response = await webClient.post<ApiEnvelope<ChartWatchlist>>(
      '/chart-watchlists/api/create',
      { name }
    )
    return response.data
  },

  remove: async (watchlistId: number): Promise<ApiEnvelope<void>> => {
    const response = await webClient.delete<ApiEnvelope<void>>(
      `/chart-watchlists/api/${watchlistId}`
    )
    return response.data
  },

  addSymbol: async (
    watchlistId: number,
    symbol: string,
    exchange: string
  ): Promise<ApiEnvelope<ChartWatchlistSymbol>> => {
    const response = await webClient.post<ApiEnvelope<ChartWatchlistSymbol>>(
      `/chart-watchlists/api/${watchlistId}/symbols`,
      { symbol, exchange }
    )
    return response.data
  },

  removeSymbol: async (
    watchlistId: number,
    symbol: string,
    exchange: string
  ): Promise<ApiEnvelope<void>> => {
    const response = await webClient.delete<ApiEnvelope<void>>(
      `/chart-watchlists/api/${watchlistId}/symbols`,
      { data: { symbol, exchange } }
    )
    return response.data
  },
}
