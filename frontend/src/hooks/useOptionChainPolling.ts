import { useCallback, useEffect, useRef, useState } from 'react'
import type { OptionChainResponse } from '@/types/option-chain'
import { usePageVisibility } from './usePageVisibility'

interface UseOptionChainPollingOptions {
  enabled: boolean
  refreshInterval?: number
  pauseWhenHidden?: boolean
  poll?: boolean
}

interface UseOptionChainPollingState {
  data: OptionChainResponse | null
  isLoading: boolean
  isConnected: boolean
  isPaused: boolean
  error: string | null
  lastUpdate: Date | null
}

/**
 * Hook for polling option chain data from REST API.
 * Supports page visibility to pause polling when tab is hidden.
 *
 * @param apiKey - Max Algos API key
 * @param underlying - Underlying symbol (NIFTY, BANKNIFTY, etc.)
 * @param exchange - Exchange code (NSE_INDEX, BSE_INDEX)
 * @param expiryDate - Expiry date in DDMMMYY format
 * @param strikeCount - Number of strikes to fetch
 * @param options - Polling options
 */
export function useOptionChainPolling(
  apiKey: string | null,
  underlying: string,
  exchange: string,
  expiryDate: string,
  strikeCount: number,
  options: UseOptionChainPollingOptions = {
    enabled: true,
    refreshInterval: 30000,
    pauseWhenHidden: true,
  }
) {
  const { enabled, refreshInterval = 30000, pauseWhenHidden = true, poll = true } = options
  const { isVisible } = usePageVisibility()

  const [state, setState] = useState<UseOptionChainPollingState>({
    data: null,
    isLoading: false,
    isConnected: false,
    isPaused: false,
    error: null,
    lastUpdate: null,
  })

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  // Drop the previous chain whenever the request identity changes. Without
  // this, useOptionChainLive briefly pairs the prior chain's option symbols
  // with the newly-switched optionExchange (e.g. NFO:SENSEX..., BFO:NIFTY...),
  // which the broker rejects as invalid subscriptions.
  // biome-ignore lint/correctness/useExhaustiveDependencies: these deps are intentional reset triggers — the body only resets state, but it MUST re-fire whenever the request identity (apiKey/underlying/exchange/expiryDate/strikeCount) changes to avoid pairing a stale chain with a newly-switched exchange
  useEffect(() => {
    setState((prev) => ({ ...prev, data: null, lastUpdate: null }))
  }, [apiKey, underlying, exchange, expiryDate, strikeCount])

  // Determine if polling should be active
  const shouldPoll = enabled && (!pauseWhenHidden || isVisible)

  const fetchData = useCallback(async () => {
    // A missing apiKey is a terminal condition (the user hasn't generated
    // one yet) -- unlike underlying/exchange/expiryDate, which are
    // legitimately empty for a moment while the page's own dropdowns are
    // still populating and will resolve on their own, no apiKey never
    // resolves without the user taking action elsewhere. Silently
    // returning here (the previous behavior) left isLoading stuck at its
    // initial `false` with no data and no error -- callers like
    // OptionChain.tsx render an infinite loading spinner in exactly that
    // state (`!data && !error && expiries.length > 0`), so a user without
    // an API key would see a spinner that never resolves, with no
    // indication of what's wrong or how to fix it.
    if (!apiKey) {
      setState((prev) => ({
        ...prev,
        isLoading: false,
        error: 'No API key found. Generate one from the API Key page to load live option chain data.',
      }))
      return
    }

    if (!underlying || !exchange || !expiryDate) {
      return
    }

    // Skip if already fetching
    if (abortControllerRef.current) {
      return
    }

    setState((prev) => ({ ...prev, isLoading: true }))

    try {
      const controller = new AbortController()
      abortControllerRef.current = controller

      const response = await fetch('/api/v1/optionchain', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          apikey: apiKey,
          underlying,
          exchange,
          expiry_date: expiryDate,
          strike_count: strikeCount,
        }),
        signal: controller.signal,
      })

      if (!response.ok) {
        let errMsg = `HTTP error! status: ${response.status}`
        try {
          const errData = await response.json()
          if (errData && errData.message) {
            errMsg = errData.message
          }
        } catch (_) {}
        throw new Error(errMsg)
      }


      const data: OptionChainResponse = await response.json()

      if (data.status === 'success') {
        setState((prev) => ({
          ...prev,
          data,
          isLoading: false,
          isConnected: true,
          error: null,
          lastUpdate: new Date(),
        }))
      } else {
        setState((prev) => ({
          ...prev,
          isLoading: false,
          error: data.message || 'Failed to fetch option chain',
        }))
      }
    } catch (error) {
      if (error instanceof Error) {
        if (error.name === 'AbortError') {
          if (abortControllerRef.current === null) {
            setState((prev) => ({ ...prev, isLoading: false }))
          }
        } else {
          setState((prev) => ({
            ...prev,
            isLoading: false,
            error: error.message || 'Connection error',
            isConnected: false,
          }))
        }
      }
    } finally {
      abortControllerRef.current = null
    }
  }, [apiKey, underlying, exchange, expiryDate, strikeCount])

  // Handle polling start/stop based on visibility
  useEffect(() => {
    if (!shouldPoll) {
      // Pause polling
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      setState((prev) => ({ ...prev, isPaused: !!enabled }))
      return
    }

    // Resume/start polling
    setState((prev) => ({ ...prev, isConnected: true, isPaused: false }))

    // Fetch immediately when becoming visible
    fetchData()

    // Set up interval only if polling is enabled
    if (poll && refreshInterval > 0) {
      intervalRef.current = setInterval(fetchData, refreshInterval)
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
        abortControllerRef.current = null
      }
    }
  }, [shouldPoll, fetchData, refreshInterval, enabled])

  const refetch = useCallback(() => {
    fetchData()
  }, [fetchData])

  return {
    ...state,
    refetch,
  }
}
