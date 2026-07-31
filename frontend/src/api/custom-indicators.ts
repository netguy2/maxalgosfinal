// api/custom-indicators.ts
// Wrappers around blueprints/custom_indicators.py's session-authenticated
// REST endpoints. Uses webClient (frontend/src/api/client.ts) rather than
// raw fetch — its request interceptor attaches X-CSRFToken automatically
// on POST/PUT/DELETE, so no manual CSRF handling is needed here (unlike
// api/historify.ts, which predates this and calls fetch() directly).

import { webClient } from './client'

export type CustomIndicatorOperand = {
  indicator: 'EMA' | 'SMA' | 'VWAP' | 'RSI' | 'ATR' | 'BOLLINGER'
  /** Omitted/ignored for VWAP, which has no period. */
  period?: number
}

export type CustomIndicatorFormula =
  | {
      kind: 'combine'
      op: '+' | '-' | '*' | '/'
      a: CustomIndicatorOperand
      b: CustomIndicatorOperand
    }
  | {
      kind: 'threshold'
      a: CustomIndicatorOperand
      threshold: number
      invert: boolean
    }

export interface CustomIndicator {
  id: number
  name: string
  formula: CustomIndicatorFormula
  color: string
  enabled: boolean
  created_at: string | null
}

export interface CustomIndicatorSeriesPoint {
  time: number
  value: number
}

export interface CustomIndicatorSignal {
  time: number
  side: 'BUY' | 'SELL'
}

export interface CustomIndicatorComputeResult {
  series?: CustomIndicatorSeriesPoint[]
  signals?: CustomIndicatorSignal[]
  error?: string
}

interface ApiEnvelope<T> {
  status: 'success' | 'error'
  message?: string
  data?: T
}

export const customIndicatorsApi = {
  list: async (): Promise<ApiEnvelope<CustomIndicator[]>> => {
    const response = await webClient.get<ApiEnvelope<CustomIndicator[]>>(
      '/custom-indicators/api/list'
    )
    return response.data
  },

  create: async (
    name: string,
    formula: CustomIndicatorFormula,
    color: string
  ): Promise<ApiEnvelope<CustomIndicator>> => {
    const response = await webClient.post<ApiEnvelope<CustomIndicator>>(
      '/custom-indicators/api/create',
      { name, formula, color }
    )
    return response.data
  },

  remove: async (id: number): Promise<ApiEnvelope<void>> => {
    const response = await webClient.delete<ApiEnvelope<void>>(`/custom-indicators/api/${id}`)
    return response.data
  },

  /**
   * Compute one or more custom indicators over the given bars — pass the
   * exact same bars the chart is rendering so the result lines up with
   * the candles on screen (same pattern as historifyApi.getIndicatorSeries).
   */
  compute: async (
    bars: Array<{
      timestamp: number
      open: number
      high: number
      low: number
      close: number
      volume: number
    }>,
    formulas: Array<{ id: number; formula: CustomIndicatorFormula }>
  ): Promise<ApiEnvelope<Record<string, CustomIndicatorComputeResult>>> => {
    if (formulas.length === 0 || bars.length === 0) {
      return { status: 'success', data: {} }
    }
    const response = await webClient.post<
      ApiEnvelope<Record<string, CustomIndicatorComputeResult>>
    >('/custom-indicators/api/compute', { bars, formulas })
    return response.data
  },
}
