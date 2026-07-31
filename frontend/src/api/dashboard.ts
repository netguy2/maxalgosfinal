// api/dashboard.ts
// Wraps blueprints/dashboard.py's session-authenticated market-movers
// endpoint plus the margin/activity/pnl-history/master-contract/deployments
// feeds Dashboard.tsx's subcomponents need. Uses plain fetch (not
// webClient/apiClient) throughout -- apiClient auto-redirects to /login on
// any 401, which would break dashboard-data's need to distinguish
// BROKER_SESSION_EXPIRED (reconnect broker) from a real session expiry
// (redirect to login) from a generic fetch error (retry in place).

export interface MarketMover {
  symbol: string
  exchange: string
  ltp: number
  change_percent: number
}

interface MarketMoversResponse {
  status: 'success' | 'error'
  message?: string
  gainers?: MarketMover[]
  losers?: MarketMover[]
}

export interface MarginData {
  availablecash: string
  collateral: string
  m2munrealized: string
  m2mrealized: string
  utiliseddebits: string
}

export interface DashboardDataResult {
  /** 'success' | 'broker_session_expired' | 'unauthenticated' | 'error' */
  status: 'success' | 'broker_session_expired' | 'unauthenticated' | 'error'
  data?: MarginData
  message?: string
}

export interface ActivityEntry {
  category: 'system' | 'broker' | 'account' | 'order' | string
  title: string
  message: string
  timestamp: string | null
}

export interface PnlSnapshotEntry {
  m2munrealized: string
  m2mrealized: string
  timestamp: string | null
}

export interface MasterContractStatus {
  status: 'pending' | 'downloading' | 'success' | 'error'
  message?: string
  total_symbols?: number
}

export interface DeploymentInstance {
  id: number
  name: string
  status: string
  pnl: number
  trades_count: number
  health_score: number
  metrics: {
    cpu?: number
    memory?: number
    latency?: number
    heartbeat?: number
    last_tick?: string
  }
}

export const dashboardApi = {
  getMarketMovers: async (): Promise<{ gainers: MarketMover[]; losers: MarketMover[] }> => {
    try {
      const response = await fetch('/api/dashboard/market-movers', { credentials: 'include' })
      const data: MarketMoversResponse = await response.json()
      if (data.status !== 'success') return { gainers: [], losers: [] }
      return { gainers: data.gainers || [], losers: data.losers || [] }
    } catch {
      return { gainers: [], losers: [] }
    }
  },

  // Preserves the exact 401 / BROKER_SESSION_EXPIRED discrimination the
  // page's inline fetch used to do -- caller still owns the resulting
  // state transitions (setIsBrokerSessionExpired etc.), this just
  // centralizes the fetch + response parsing.
  getDashboardData: async (): Promise<DashboardDataResult> => {
    try {
      const response = await fetch('/auth/dashboard-data', { credentials: 'include' })

      if (response.status === 401) {
        try {
          const errData = await response.json()
          if (errData?.code === 'BROKER_SESSION_EXPIRED') {
            return {
              status: 'broker_session_expired',
              message: errData.message || 'Broker session expired - please reconnect your broker',
            }
          }
        } catch {
          // fall through to unauthenticated below
        }
        return { status: 'unauthenticated' }
      }

      const data = await response.json()
      if (data.status === 'success' && data.data) {
        return { status: 'success', data: data.data }
      }
      return { status: 'error', message: data.message || 'Failed to fetch margin data' }
    } catch {
      return { status: 'error', message: 'Failed to fetch margin data' }
    }
  },

  getActivity: async (limit = 8): Promise<ActivityEntry[]> => {
    try {
      const response = await fetch(`/auth/activity?limit=${limit}`, { credentials: 'include' })
      if (response.status === 401) return []
      const data = await response.json()
      return data.status === 'success' ? data.data || [] : []
    } catch {
      return []
    }
  },

  getPnlHistory: async (): Promise<PnlSnapshotEntry[]> => {
    try {
      const response = await fetch('/auth/pnl-history', { credentials: 'include' })
      if (response.status === 401) return []
      const data = await response.json()
      return data.status === 'success' ? data.data || [] : []
    } catch {
      return []
    }
  },

  getMasterContractStatus: async (): Promise<MasterContractStatus> => {
    try {
      const response = await fetch('/api/master-contract/status', {
        credentials: 'include',
        headers: { Accept: 'application/json' },
      })
      if (response.status === 401) return { status: 'pending' }
      return await response.json()
    } catch {
      return { status: 'error', message: 'Failed to check status' }
    }
  },

  // Backs ActiveStrategiesCard. Reuses the same endpoint pages/Deployments.tsx
  // already polls every 5s -- no new backend endpoint. Returns the raw array
  // as-is (no {status,data} envelope on this endpoint).
  getDeployments: async (): Promise<DeploymentInstance[]> => {
    try {
      const response = await fetch('/api/v1/deployments', { credentials: 'include' })
      if (!response.ok) return []
      return await response.json()
    } catch {
      return []
    }
  },
}
