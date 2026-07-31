// api/indicator-presets.ts
// Wrappers around blueprints/indicator_presets.py's session-authenticated
// REST endpoints for saved indicator selections ("setups") on the Charts
// page, scoped per-user to either one symbol or globally. Uses webClient
// (frontend/src/api/client.ts) — its request interceptor attaches
// X-CSRFToken automatically on POST/DELETE, no manual CSRF handling
// needed (same pattern as api/chart-drawings.ts).

import { webClient } from './client'

export interface IndicatorPresetConfig {
  indicators: string[]
  customIndicatorIds: number[]
}

interface ApiEnvelope<T> {
  status: 'success' | 'error'
  message?: string
  data?: T
}

interface GetPresetResponse extends ApiEnvelope<IndicatorPresetConfig | null> {
  scope: 'symbol' | 'global' | null
}

export const indicatorPresetsApi = {
  get: async (
    symbol: string,
    exchange: string
  ): Promise<{ scope: 'symbol' | 'global' | null; config: IndicatorPresetConfig | null }> => {
    const response = await webClient.get<GetPresetResponse>('/indicator-presets/api/get', {
      params: { symbol, exchange },
    })
    if (response.data.status !== 'success' || !response.data.data) {
      return { scope: null, config: null }
    }
    return { scope: response.data.scope, config: response.data.data }
  },

  saveForSymbol: async (
    symbol: string,
    exchange: string,
    config: IndicatorPresetConfig
  ): Promise<boolean> => {
    const response = await webClient.post<ApiEnvelope<unknown>>('/indicator-presets/api/save', {
      scope: 'symbol',
      symbol,
      exchange,
      ...config,
    })
    return response.data.status === 'success'
  },

  saveGlobal: async (config: IndicatorPresetConfig): Promise<boolean> => {
    const response = await webClient.post<ApiEnvelope<unknown>>('/indicator-presets/api/save', {
      scope: 'global',
      ...config,
    })
    return response.data.status === 'success'
  },
}
