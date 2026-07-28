import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  type ActivityEntry,
  dashboardApi,
  type MarginData,
  type MarketMover,
  type MasterContractStatus,
  type PnlSnapshotEntry,
} from '@/api/dashboard'
import { ActiveStrategiesCard } from '@/components/dashboard/ActiveStrategiesCard'
import { BrokerConnectCta } from '@/components/dashboard/BrokerConnectCta'
import { KpiRow } from '@/components/dashboard/KpiRow'
import { MarketTicker } from '@/components/dashboard/MarketTicker'
import { PortfolioPerformanceChart } from '@/components/dashboard/PortfolioPerformanceChart'
import { RecentActivityTimeline } from '@/components/dashboard/RecentActivityTimeline'
import { TopMoversLists } from '@/components/dashboard/TopMoversLists'
import { useOrderEventRefresh } from '@/hooks/useOrderEventRefresh'
import { useAuthStore } from '@/stores/authStore'
import { onModeChange } from '@/stores/themeStore'

export default function Dashboard() {
  const { user, brokerSessionValid } = useAuthStore()
  const [marginData, setMarginData] = useState<MarginData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Distinguishes "broker's own token expired, needs OAuth re-login" from
  // any other dashboard-data fetch failure. The two need different retry
  // actions -- re-fetching dashboard-data can never fix an expired broker
  // token (the broker will keep rejecting it), only re-running the OAuth
  // flow via /broker/manage can.
  const [isBrokerSessionExpired, setIsBrokerSessionExpired] = useState(false)
  const [masterContract, setMasterContract] = useState<MasterContractStatus>({
    status: 'pending',
  })
  const [isAuthenticated, setIsAuthenticated] = useState(true)

  const isBrokerConnected = !!user?.broker

  // Top gainers/losers -- on-demand fetch (no polling), NIFTY 50 basket
  // ranked server-side by % change. See services/market_movers_service.py.
  const [gainers, setGainers] = useState<MarketMover[]>([])
  const [losers, setLosers] = useState<MarketMover[]>([])
  const [isLoadingMovers, setIsLoadingMovers] = useState(true)

  const fetchMarketMovers = useCallback(async () => {
    if (!user?.broker) {
      setIsLoadingMovers(false)
      return
    }
    setIsLoadingMovers(true)
    try {
      const { gainers: g, losers: l } = await dashboardApi.getMarketMovers()
      setGainers(g)
      setLosers(l)
    } finally {
      setIsLoadingMovers(false)
    }
  }, [user?.broker])

  useEffect(() => {
    fetchMarketMovers()
  }, [fetchMarketMovers])

  // Fetch dashboard funds data
  const fetchFundsData = useCallback(async () => {
    setIsLoading(true)
    const result = await dashboardApi.getDashboardData()

    if (result.status === 'broker_session_expired') {
      setError(result.message || 'Broker session expired - please reconnect your broker')
      setIsBrokerSessionExpired(true)
      useAuthStore.getState().setBrokerSessionValid(false)
      setIsLoading(false)
      return
    }

    if (result.status === 'unauthenticated') {
      setIsAuthenticated(false)
      setIsLoading(false)
      return
    }

    if (result.status === 'success' && result.data) {
      setMarginData(result.data)
      setError(null)
      setIsBrokerSessionExpired(false)
      useAuthStore.getState().setBrokerSessionValid(true)
    } else {
      setError(result.message || 'Failed to fetch margin data')
    }
    setIsLoading(false)
  }, [])

  useEffect(() => {
    fetchFundsData()
  }, [fetchFundsData])

  useOrderEventRefresh(fetchFundsData, {
    events: ['order_event', 'analyzer_update', 'close_position_event'],
  })

  // appMode (live/analyzer) changes which backend code path funds data
  // comes from (live broker token vs. API-key path) -- must keep refetching
  // on this event, not just on order events.
  useEffect(() => {
    const unsubscribe = onModeChange(() => {
      fetchFundsData()
    })
    return () => unsubscribe()
  }, [fetchFundsData])

  // Recent activity feed
  const [activity, setActivity] = useState<ActivityEntry[]>([])
  const [activityLoading, setActivityLoading] = useState(true)

  const fetchActivity = useCallback(async () => {
    const data = await dashboardApi.getActivity(8)
    setActivity(data)
    setActivityLoading(false)
  }, [])

  useEffect(() => {
    fetchActivity()
  }, [fetchActivity])

  useOrderEventRefresh(fetchActivity, {
    events: ['order_event', 'analyzer_update', 'close_position_event', 'cache_loaded'],
  })

  // Today's P&L history (for the Portfolio Performance sparkline)
  const [pnlHistory, setPnlHistory] = useState<PnlSnapshotEntry[]>([])

  const fetchPnlHistory = useCallback(async () => {
    const data = await dashboardApi.getPnlHistory()
    setPnlHistory(data)
  }, [])

  useEffect(() => {
    fetchPnlHistory()
  }, [fetchPnlHistory])

  useOrderEventRefresh(fetchPnlHistory, {
    events: ['order_event', 'analyzer_update', 'close_position_event'],
  })

  // Master contract status -- poll every 5s until synced, then stop.
  const checkMasterContractStatus = useCallback(async () => {
    const data = await dashboardApi.getMasterContractStatus()
    setMasterContract(data)
  }, [])

  useEffect(() => {
    checkMasterContractStatus()
    const interval = setInterval(() => {
      setMasterContract((prev) => {
        if (prev.status === 'success') {
          return prev
        }
        checkMasterContractStatus()
        return prev
      })
    }, 5000)
    return () => clearInterval(interval)
  }, [checkMasterContractStatus])

  if (!isAuthenticated) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[50vh] space-y-4">
        <h1 className="text-2xl font-bold">Session Expired</h1>
        <p className="text-muted-foreground">Please log in to access the dashboard.</p>
        <Link to="/login" className="text-brand hover:underline">
          Go to Login
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-10">
      {/* Header */}
      <div>
        <span className="text-xs font-semibold text-brand uppercase tracking-wider block mb-1">
          Good morning, {user?.username || 'Trader'} 👋
        </span>
        <h1 className="text-xl font-bold text-foreground tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground mt-0.5">Track. Analyze. Automate.</p>
      </div>

      <MarketTicker isBrokerConnected={isBrokerConnected} />

      <KpiRow
        marginData={marginData}
        isLoading={isLoading}
        isBrokerConnected={isBrokerConnected}
        brokerName={user?.broker ?? null}
        brokerSessionValid={brokerSessionValid}
        masterContract={masterContract}
      />

      <BrokerConnectCta
        isBrokerConnected={isBrokerConnected}
        error={error}
        isBrokerSessionExpired={isBrokerSessionExpired}
        brokerName={user?.broker ?? null}
        onRetry={fetchFundsData}
      />

      <PortfolioPerformanceChart
        pnlHistory={pnlHistory}
        marginData={marginData}
        isBrokerConnected={isBrokerConnected}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <TopMoversLists gainers={gainers} losers={losers} isLoading={isLoadingMovers} />
        <ActiveStrategiesCard />
      </div>

      <RecentActivityTimeline activity={activity} isLoading={activityLoading} />
    </div>
  )
}
