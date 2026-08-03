import type {
  AllStrategiesLogFile,
  CombinedLogResponse,
  EnvironmentVariables,
  LogContent,
  LogFile,
  MasterContractStatus,
  PythonStrategy,
  PythonStrategyContent,
  ScheduleConfig,
} from '@/types/python-strategy'
import type { ApiResponse } from '@/types/trading'
import { webClient } from './client'

export const pythonStrategyApi = {
  /**
   * Get all Python strategies
   */
  getStrategies: async (): Promise<PythonStrategy[]> => {
    const response = await webClient.get<{ strategies: PythonStrategy[] }>('/python/api/strategies')
    return response.data.strategies || []
  },

  /**
   * Get a single strategy
   */
  getStrategy: async (strategyId: string): Promise<PythonStrategy> => {
    const response = await webClient.get<{ strategy: PythonStrategy }>(
      `/python/api/strategy/${strategyId}`
    )
    return response.data.strategy
  },

  /**
   * Get strategy content for editing
   */
  getStrategyContent: async (strategyId: string): Promise<PythonStrategyContent> => {
    const response = await webClient.get<PythonStrategyContent>(
      `/python/api/strategy/${strategyId}/content`
    )
    return response.data
  },

  /**
   * Upload a new strategy with mandatory schedule
   */
  uploadStrategy: async (
    name: string,
    file: File,
    schedule: {
      start_time: string
      stop_time: string
      days: string[]
      exchange?: string
      /** Which of the user's connected brokers this strategy may trade
       * on -- informational, exposed to the script as MAX_ALGOS_BROKERS.
       * The script still picks a specific broker per order via
       * placeorder(broker=...). */
      brokers?: string[]
      /** Marketplace catalog id / signalId this script was generated from,
       * for traceability only (shown as "from {template} template" in My
       * Strategies) -- purely additive, backend defaults both to null
       * when omitted so hand-written uploads are unaffected. */
      source_template_id?: string
      source_signal_id?: string
      /** If true, attempt to start the strategy running IMMEDIATELY
       * (subject to the same market-hours/schedule-day/holiday gate
       * /python/start/<id> already enforces) instead of only arming it
       * for its next scheduled cron fire. Used by StrategyConfigurator.tsx's
       * "Live Broker Mode" deploy -- without this, deploying a template
       * outside the exact schedule_start minute silently did nothing
       * until the next scheduled day despite the UI saying "deployed
       * live!" immediately. Omit/false for hand-written uploads
       * (NewPythonStrategy.tsx), which should only ever be scheduled, not
       * auto-started on upload. */
      start_now?: boolean
    }
  ): Promise<ApiResponse<{ strategy_id: string; started?: boolean }>> => {
    const formData = new FormData()
    formData.append('strategy_name', name)
    formData.append('strategy_file', file)
    formData.append('exchange', schedule.exchange || 'NSE')
    // Add schedule fields
    formData.append('schedule_start', schedule.start_time)
    formData.append('schedule_stop', schedule.stop_time)
    formData.append('schedule_days', JSON.stringify(schedule.days))
    formData.append('brokers', JSON.stringify(schedule.brokers || []))
    if (schedule.source_template_id) {
      formData.append('source_template_id', schedule.source_template_id)
    }
    if (schedule.source_signal_id) {
      formData.append('source_signal_id', schedule.source_signal_id)
    }
    if (schedule.start_now) {
      formData.append('start_now', 'true')
    }

    const response = await webClient.post<ApiResponse<{ strategy_id: string; started?: boolean }>>(
      '/python/new',
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    )
    return response.data
  },

  /**
   * Save strategy content
   */
  saveStrategy: async (strategyId: string, content: string): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(`/python/save/${strategyId}`, {
      content,
    })
    return response.data
  },

  /**
   * Export strategy file
   */
  exportStrategy: async (
    strategyId: string,
    version: 'saved' | 'current' = 'saved'
  ): Promise<Blob> => {
    const response = await webClient.get(`/python/export/${strategyId}?version=${version}`, {
      responseType: 'blob',
    })
    return response.data
  },

  /**
   * Delete a strategy
   */
  deleteStrategy: async (strategyId: string): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(`/python/delete/${strategyId}`)
    return response.data
  },

  /**
   * Start a strategy
   */
  startStrategy: async (strategyId: string): Promise<ApiResponse<{ process_id: number }>> => {
    const response = await webClient.post<ApiResponse<{ process_id: number }>>(
      `/python/start/${strategyId}`
    )
    return response.data
  },

  /**
   * Stop a strategy
   */
  stopStrategy: async (strategyId: string): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(`/python/stop/${strategyId}`)
    return response.data
  },

  /**
   * Clear error state
   */
  clearError: async (strategyId: string): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(`/python/clear-error/${strategyId}`)
    return response.data
  },

  /**
   * Schedule a strategy
   */
  scheduleStrategy: async (
    strategyId: string,
    config: ScheduleConfig
  ): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/python/schedule/${strategyId}`,
      config
    )
    return response.data
  },

  /**
   * Unschedule a strategy
   */
  unscheduleStrategy: async (strategyId: string): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(`/python/unschedule/${strategyId}`)
    return response.data
  },

  /**
   * Get log files for a strategy
   */
  getLogFiles: async (strategyId: string): Promise<LogFile[]> => {
    const response = await webClient.get<{ logs: LogFile[] }>(`/python/api/logs/${strategyId}`)
    return response.data.logs || []
  },

  /**
   * Get log file content
   */
  getLogContent: async (strategyId: string, logName: string): Promise<LogContent> => {
    const response = await webClient.get<LogContent>(`/python/api/logs/${strategyId}/${logName}`)
    return response.data
  },

  /**
   * Clear all logs for a strategy
   */
  clearLogs: async (strategyId: string): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(`/python/logs/${strategyId}/clear`)
    return response.data
  },

  /**
   * List every log file across all of the user's Python strategies
   * (newest first), each tagged with which strategy produced it.
   */
  getAllLogFiles: async (): Promise<AllStrategiesLogFile[]> => {
    const response = await webClient.get<{ logs: AllStrategiesLogFile[] }>('/python/api/logs/all')
    return response.data.logs || []
  },

  /**
   * Merged, cross-strategy tail: the most recent log file from every
   * strategy, combined into one feed with per-line strategy attribution.
   */
  getCombinedLogs: async (limit = 500): Promise<CombinedLogResponse> => {
    const response = await webClient.get<CombinedLogResponse>(
      `/python/api/logs/all/combined?limit=${limit}`
    )
    return response.data
  },

  /**
   * Get environment variables
   */
  getEnvVariables: async (strategyId: string): Promise<EnvironmentVariables> => {
    const response = await webClient.get<EnvironmentVariables>(`/python/env/${strategyId}`)
    return response.data
  },

  /**
   * Save environment variables
   */
  saveEnvVariables: async (
    strategyId: string,
    variables: EnvironmentVariables
  ): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(`/python/env/${strategyId}`, variables)
    return response.data
  },

  /**
   * Get master contract status
   */
  getMasterContractStatus: async (): Promise<MasterContractStatus> => {
    const response = await webClient.get<MasterContractStatus>('/python/status')
    return response.data
  },

  /**
   * Check and start pending strategies (after master contract download)
   */
  checkAndStartPending: async (): Promise<ApiResponse<{ started: number }>> => {
    const response =
      await webClient.post<ApiResponse<{ started: number }>>('/python/check-contracts')
    return response.data
  },

  /**
   * AI-generate a complete Python strategy script from a plain-English
   * description, using the user's own AI provider key configured at
   * /ai-settings. Returns the generated source for review/editing before
   * uploading via uploadStrategy -- this does not save or schedule
   * anything itself.
   */
  generateAiStrategy: async (
    strategyName: string,
    description: string
  ): Promise<
    ApiResponse<{
      source: string
      summary: string
      symbol: string
      exchange: string
      quantity: number
      product: string
      timeframe: string
    }>
  > => {
    const response = await webClient.post<
      ApiResponse<{
        source: string
        summary: string
        symbol: string
        exchange: string
        quantity: number
        product: string
        timeframe: string
      }>
    >('/python/api/generate-ai', { strategy_name: strategyName, description })
    return response.data
  },
}
