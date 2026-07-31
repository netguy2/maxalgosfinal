import type {
  AddSymbolRequest,
  CreateCePeReversalRequest,
  CreateLegGroupRequest,
  CreateStrategyRequest,
  ExecutionModel,
  LegGroup,
  Strategy,
  StrategySymbolMapping,
  SymbolSearchResult,
} from '@/types/strategy'
import type { ApiResponse } from '@/types/trading'
import { webClient } from './client'

export const strategyApi = {
  /**
   * Get all strategies
   */
  getStrategies: async (): Promise<Strategy[]> => {
    const response = await webClient.get<{ strategies: Strategy[] }>('/strategy/api/strategies')
    return response.data.strategies || []
  },

  /**
   * Get a single strategy by ID
   */
  getStrategy: async (
    strategyId: number
  ): Promise<{ strategy: Strategy; mappings: StrategySymbolMapping[] }> => {
    const response = await webClient.get<{ strategy: Strategy; mappings: StrategySymbolMapping[] }>(
      `/strategy/api/strategy/${strategyId}`
    )
    return response.data
  },

  /**
   * Create a new strategy
   */
  createStrategy: async (
    data: CreateStrategyRequest
  ): Promise<ApiResponse<{ strategy_id: number }>> => {
    const response = await webClient.post<ApiResponse<{ strategy_id: number }>>(
      '/strategy/api/strategy',
      data
    )
    return response.data
  },

  /**
   * Toggle strategy active/inactive
   */
  toggleStrategy: async (strategyId: number): Promise<ApiResponse<{ is_active: boolean }>> => {
    const response = await webClient.post<ApiResponse<{ is_active: boolean }>>(
      `/strategy/api/strategy/${strategyId}/toggle`
    )
    return response.data
  },

  /**
   * Switch a strategy between 'legacy' (2-action BUY/SELL) and 'unified'
   * (4-action BUY/SELL/SHORT/EXIT with per-mapping order_side) webhook
   * signal processing. See services/signal_engine.py's dispatch.
   */
  updateExecutionModel: async (
    strategyId: number,
    executionModel: ExecutionModel
  ): Promise<ApiResponse<{ execution_model: ExecutionModel }>> => {
    const response = await webClient.post<ApiResponse<{ execution_model: ExecutionModel }>>(
      `/strategy/api/strategy/${strategyId}/execution-model`,
      { execution_model: executionModel }
    )
    return response.data
  },

  /**
   * List a strategy's leg groups (stateful rotation -- execution_model
   * 'stateful'), each with its legs and current rotation state.
   */
  getLegGroups: async (strategyId: number): Promise<ApiResponse<LegGroup[]>> => {
    const response = await webClient.get<ApiResponse<LegGroup[]>>(
      `/strategy/api/strategy/${strategyId}/leg-groups`
    )
    return response.data
  },

  /**
   * Create a leg group with its legs in one call (generic multi-leg
   * builder's "Save").
   */
  createLegGroup: async (
    strategyId: number,
    data: CreateLegGroupRequest
  ): Promise<ApiResponse<LegGroup>> => {
    const response = await webClient.post<ApiResponse<LegGroup>>(
      `/strategy/api/strategy/${strategyId}/leg-groups`,
      data
    )
    return response.data
  },

  /**
   * Rename a leg group and/or replace its legs entirely. Replacing legs
   * resets the group to flat (current_leg_id null).
   */
  updateLegGroup: async (
    strategyId: number,
    legGroupId: number,
    data: Partial<CreateLegGroupRequest>
  ): Promise<ApiResponse<LegGroup>> => {
    const response = await webClient.put<ApiResponse<LegGroup>>(
      `/strategy/api/strategy/${strategyId}/leg-groups/${legGroupId}`,
      data
    )
    return response.data
  },

  /**
   * Pause/resume a leg group. Does not close whichever leg is currently
   * open -- only stops it reacting to further signals.
   */
  toggleLegGroup: async (
    strategyId: number,
    legGroupId: number
  ): Promise<ApiResponse<{ is_active: boolean }>> => {
    const response = await webClient.post<ApiResponse<{ is_active: boolean }>>(
      `/strategy/api/strategy/${strategyId}/leg-groups/${legGroupId}/toggle`
    )
    return response.data
  },

  /**
   * Permanently delete a leg group and its legs.
   */
  deleteLegGroup: async (strategyId: number, legGroupId: number): Promise<ApiResponse<void>> => {
    const response = await webClient.delete<ApiResponse<void>>(
      `/strategy/api/strategy/${strategyId}/leg-groups/${legGroupId}`
    )
    return response.data
  },

  /**
   * One-click "CE/PE Reversal" quick-start: server-side builds the exact
   * 2-leg group a Call/Put flip strategy needs from a minimal
   * underlying/expiry/strike/quantity/product request.
   */
  createCePeReversal: async (
    strategyId: number,
    data: CreateCePeReversalRequest
  ): Promise<ApiResponse<LegGroup>> => {
    const response = await webClient.post<ApiResponse<LegGroup>>(
      `/strategy/api/strategy/${strategyId}/leg-groups/ce-pe-reversal`,
      data
    )
    return response.data
  },

  /**
   * Delete a strategy
   */
  deleteStrategy: async (strategyId: number): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(`/strategy/${strategyId}/delete`)
    return response.data
  },

  /**
   * Add a symbol mapping to a strategy
   */
  addSymbolMapping: async (
    strategyId: number,
    data: AddSymbolRequest
  ): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy/${strategyId}/configure`,
      data
    )
    return response.data
  },

  /**
   * Add bulk symbol mappings
   */
  addBulkSymbols: async (
    strategyId: number,
    csvData: string
  ): Promise<ApiResponse<{ added: number; failed: number }>> => {
    const response = await webClient.post<ApiResponse<{ added: number; failed: number }>>(
      `/strategy/${strategyId}/configure`,
      { symbols: csvData } // Backend expects 'symbols' field
    )
    return response.data
  },

  /**
   * Update an existing symbol mapping
   */
  updateSymbolMapping: async (
    strategyId: number,
    mappingId: number,
    data: Partial<AddSymbolRequest>
  ): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy/${strategyId}/symbol/${mappingId}/update`,
      data
    )
    return response.data
  },

  /**
   * Delete a symbol mapping
   */
  deleteSymbolMapping: async (
    strategyId: number,
    mappingId: number
  ): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy/${strategyId}/symbol/${mappingId}/delete`
    )
    return response.data
  },

  /**
   * Pause/resume a single symbol mapping. A paused symbol is skipped on
   * every incoming webhook signal until resumed -- the connection and
   * every other symbol in it keep working normally.
   */
  toggleSymbolMapping: async (
    strategyId: number,
    mappingId: number
  ): Promise<ApiResponse<{ is_active: boolean }>> => {
    const response = await webClient.post<ApiResponse<{ is_active: boolean }>>(
      `/strategy/${strategyId}/symbol/${mappingId}/toggle`
    )
    return response.data
  },

  /**
   * Search symbols
   */
  searchSymbols: async (query: string, exchange?: string): Promise<SymbolSearchResult[]> => {
    const params = new URLSearchParams({ q: query })
    if (exchange) {
      params.append('exchange', exchange)
    }
    const response = await webClient.get<{ results: SymbolSearchResult[] }>(
      `/strategy/search?${params.toString()}`
    )
    return response.data.results || []
  },

  /**
   * Search underlyings only (equity/index rows, no dated F&O contracts) --
   * used by the Futures/Options "Underlying" picker so searching "NIFTY"
   * shows the index itself instead of every NIFTY...CE/PE contract.
   */
  searchUnderlyingSymbols: async (query: string): Promise<SymbolSearchResult[]> => {
    const params = new URLSearchParams({ q: query })
    const response = await webClient.get<{ results: SymbolSearchResult[] }>(
      `/strategy/search/underlying?${params.toString()}`
    )
    return response.data.results || []
  },

  /**
   * Lot size for an underlying on a given F&O exchange -- lets the form
   * suggest Quantity as soon as underlying+exchange are picked for a
   * Futures/Options mapping, without waiting for a full contract
   * resolution (lot size is constant across expiries/strikes).
   */
  getUnderlyingLotsize: async (underlying: string, exchange: string): Promise<number | null> => {
    const params = new URLSearchParams({ underlying, exchange })
    const response = await webClient.get<{ lotsize: number | null }>(
      `/strategy/lotsize?${params.toString()}`
    )
    return response.data.lotsize
  },

  /**
   * Get webhook URL for a strategy
   */
  getWebhookUrl: (webhookId: string): string => {
    const baseUrl = window.location.origin
    return `${baseUrl}/strategy/webhook/${webhookId}`
  },

  /**
   * Get past backtests + trades for a strategy
   */
  getBacktests: async (strategyId: number): Promise<ApiResponse<unknown>> => {
    const response = await webClient.get<ApiResponse<unknown>>(
      `/strategy/api/strategy/${strategyId}/backtests`
    )
    return response.data
  },

  /**
   * Run a backtest for a strategy
   */
  runBacktest: async (
    strategyId: number,
    params: {
      symbol: string
      timeframe: string
      start_date: string
      end_date: string
      capital: string | number
    }
  ): Promise<ApiResponse<unknown>> => {
    const response = await webClient.post<ApiResponse<unknown>>(
      `/strategy/api/strategy/${strategyId}/backtest`,
      params
    )
    return response.data
  },
}
