// api/ai-insight.ts
// Wrapper around blueprints/ai_insight.py's session-authenticated,
// rate-limited endpoint that generates an advisory AI insight for the
// currently open symbol on the Charts page. Uses webClient (automatic
// CSRF), same pattern as api/ai-settings.ts.

import axios from 'axios'
import { webClient } from './client'

export type AiSentiment = 'bullish' | 'bearish' | 'neutral'

export interface AiTradeLevels {
  stop_loss: number
  target: number
  /** Suggested max % of available capital to risk on this position (1-25,
   * clamped server-side). The actual rupee/quantity conversion happens
   * client-side using the user's real balance -- the AI provider itself
   * never sees account balance, only this percentage. */
  position_size_pct: number
  rationale: string
}

export interface AiInsight {
  sentiment: AiSentiment
  confidence: number
  summary: string
  key_drivers: string[]
  watch_level: number | null
  trade_levels: AiTradeLevels | null
}

interface ApiEnvelope<T> {
  status: 'success' | 'error'
  message?: string
  data?: T
}

export const aiInsightApi = {
  analyze: async (
    symbol: string,
    exchange: string,
    interval: string,
    /** Keys from the Charts page's enabled overlay chips (EMA, SMA, VWAP,
     * RSI, MACD, ATR, BOLLINGER, STOCH) -- when given, the backend only
     * computes and sends these to the AI, matching what the user is
     * actually looking at. Omit/empty to use the backend's default set. */
    indicators?: string[],
    /** Current live tick price, more recent than the last closed candle. */
    livePrice?: number
  ): Promise<{ success: boolean; data?: AiInsight; message?: string }> => {
    try {
      const response = await webClient.post<ApiEnvelope<AiInsight>>('/ai-insight/api/analyze', {
        symbol,
        exchange,
        interval,
        indicators: indicators && indicators.length > 0 ? indicators : undefined,
        live_price: livePrice,
      })
      return {
        success: response.data.status === 'success',
        data: response.data.data,
        message: response.data.message,
      }
    } catch (err) {
      // webClient's response interceptor rejects on non-2xx (e.g. 429 rate
      // limit, 502 provider failure) — surface the backend's error message
      // if present rather than letting the promise reject uncaught.
      const message =
        (axios.isAxiosError(err) && (err.response?.data as ApiEnvelope<never>)?.message) ||
        (err instanceof Error ? err.message : 'Failed to get AI insight')
      return { success: false, message }
    }
  },
}
