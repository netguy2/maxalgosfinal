import { lazy, type ReactNode, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Providers } from '@/app/providers'
import { AuthSync } from '@/components/auth/AuthSync'
import { FullWidthLayout } from '@/components/layout/FullWidthLayout'
import { Layout } from '@/components/layout/Layout'
import { ToolsSwitcher } from '@/components/options/ToolsSwitcher'
import { PageLoader } from '@/components/ui/page-loader'
import { usePageTitle } from '@/hooks/usePageTitle'
// Login is the first page nearly every visitor hits, and its chunk is tiny
// (~8KB vs. the ~350KB main bundle) — statically importing it means the
// very first route a user navigates to never depends on a second,
// separately-fetchable chunk request succeeding. Lazy-loading it bought
// negligible bundle savings but meant any transient failure to fetch
// Login-<hash>.js (slow connection, ad-blocker/extension interference, a
// request racing a fresh deploy) threw a real error on the single most
// common page load in the app, surfacing as the "Loading new version…"
// recovery screen for users who hadn't even reached a stale build.
import Login from '@/pages/Login'
import { useAuthStore } from '@/stores/authStore'
import { useBrokerStore } from '@/stores/brokerStore'

/** Wraps an options-tool page with the in-page tool switcher tab strip. */
function OptionsTool({ page }: { page: ReactNode }) {
  return (
    <div className="pt-4">
      <ToolsSwitcher />
      {page}
    </div>
  )
}

// Lazy load all pages for code splitting
// Public pages
const Home = lazy(() => import('@/pages/Home'))
const Faq = lazy(() => import('@/pages/Faq'))
const Setup = lazy(() => import('@/pages/Setup'))
const Register = lazy(() => import('@/pages/Register'))
const VerifyEmail = lazy(() => import('@/pages/VerifyEmail'))
const Subscribe = lazy(() => import('@/pages/Subscribe'))
const ResetPassword = lazy(() => import('@/pages/ResetPassword'))
const ServerError = lazy(() => import('@/pages/ServerError'))
const RateLimited = lazy(() => import('@/pages/RateLimited'))
const NotFound = lazy(() => import('@/pages/NotFound'))

// Broker auth
const BrokerSelect = lazy(() => import('@/pages/BrokerSelect'))
const BrokerManage = lazy(() => import('@/pages/BrokerManage'))
const BrokerTOTP = lazy(() => import('@/pages/BrokerTOTP'))

// Main pages
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const Positions = lazy(() => import('@/pages/Positions'))
const OrderBook = lazy(() => import('@/pages/OrderBook'))
const TradeBook = lazy(() => import('@/pages/TradeBook'))
const Holdings = lazy(() => import('@/pages/Holdings'))
const Token = lazy(() => import('@/pages/Token'))
const Search = lazy(() => import('@/pages/Search'))
const ApiKey = lazy(() => import('@/pages/ApiKey'))
const ActiveSessions = lazy(() => import('@/pages/ActiveSessions'))
const AiSettings = lazy(() => import('@/pages/AiSettings'))
const Profile = lazy(() => import('@/pages/Profile'))
const ActionCenter = lazy(() => import('@/pages/ActionCenter'))

// Platform pages
const TradingView = lazy(() => import('@/pages/TradingView'))
const GoCharting = lazy(() => import('@/pages/GoCharting'))
const PnLTracker = lazy(() => import('@/pages/PnLTracker'))

// Sandbox & Analyzer
const Sandbox = lazy(() => import('@/pages/Sandbox'))
const SandboxPnL = lazy(() => import('@/pages/SandboxPnL'))
const Analyzer = lazy(() => import('@/pages/Analyzer'))
const WebSocketTest = lazy(() => import('@/pages/WebSocketTest'))
const Playground = lazy(() => import('@/pages/Playground'))
const Historify = lazy(() => import('@/pages/Historify'))
const HistorifyCharts = lazy(() => import('@/pages/HistorifyCharts'))
const Charts = lazy(() => import('@/pages/Charts'))

// Tools & Option Chain
const OptionChain = lazy(() => import('@/pages/OptionChain'))
const IVChart = lazy(() => import('@/pages/IVChart'))
const OITracker = lazy(() => import('@/pages/OITracker'))
const MaxPain = lazy(() => import('@/pages/MaxPain'))
const StraddleChart = lazy(() => import('@/pages/StraddleChart'))
const CustomStraddle = lazy(() => import('@/pages/CustomStraddle'))
const VolSurface = lazy(() => import('@/pages/VolSurface'))
const GEXDashboard = lazy(() => import('@/pages/GEXDashboard'))
const IVSmile = lazy(() => import('@/pages/IVSmile'))
const OIProfile = lazy(() => import('@/pages/OIProfile'))
const StrategyBuilder = lazy(() => import('@/pages/StrategyBuilder'))
const StrategyPortfolio = lazy(() => import('@/pages/StrategyPortfolio'))
const Deployments = lazy(() => import('@/pages/Deployments'))
const Marketplace = lazy(() => import('@/pages/Marketplace'))
const Analytics = lazy(() => import('@/pages/Analytics'))
const Camarilla = lazy(() => import('@/pages/Camarilla'))

// Strategy pages
const StrategyIndex = lazy(() => import('@/pages/strategy/StrategyIndex'))
const NewStrategy = lazy(() => import('@/pages/strategy/NewStrategy'))
const ViewStrategy = lazy(() => import('@/pages/strategy/ViewStrategy'))
const ConfigureSymbols = lazy(() => import('@/pages/strategy/ConfigureSymbols'))
const StrategyWizard = lazy(() => import('@/pages/strategy/StrategyWizard'))
const StrategyConfigurator = lazy(() => import('@/pages/strategy/StrategyConfigurator'))
const CustomStrategyBuilder = lazy(() => import('@/pages/strategy/CustomStrategyBuilder'))
const BacktestLogs = lazy(() => import('@/pages/strategy/BacktestLogs'))
const Backtest = lazy(() => import('@/pages/strategy/Backtest'))
const WebhooksGuide = lazy(() => import('@/pages/tools/WebhooksGuide'))

// Python Strategy pages
const PythonStrategyIndex = lazy(() => import('@/pages/python-strategy/PythonStrategyIndex'))
const NewPythonStrategy = lazy(() => import('@/pages/python-strategy/NewPythonStrategy'))
const EditPythonStrategy = lazy(() => import('@/pages/python-strategy/EditPythonStrategy'))
const PythonStrategyLogs = lazy(() => import('@/pages/python-strategy/PythonStrategyLogs'))
const AllPythonStrategyLogs = lazy(() => import('@/pages/python-strategy/AllPythonStrategyLogs'))
const SchedulePythonStrategy = lazy(() => import('@/pages/python-strategy/SchedulePythonStrategy'))
const PythonStrategyGuide = lazy(() => import('@/pages/python-strategy/PythonStrategyGuide'))

// MaxHook pages — unified front door for external signal connections
// (TradingView/etc. via the generic Strategy webhook engine, and Chartink
// via its own separate backend). ConfigureChartinkSymbols is Chartink's
// existing symbol-mapping page, reused unchanged under the /maxhook route.
const MaxHookIndex = lazy(() => import('@/pages/maxhook/MaxHookIndex'))
const NewMaxHookConnection = lazy(() => import('@/pages/maxhook/NewMaxHookConnection'))
const ViewMaxHookConnection = lazy(() => import('@/pages/maxhook/ViewMaxHookConnection'))
const ConfigureChartinkSymbols = lazy(() => import('@/pages/chartink/ConfigureChartinkSymbols'))

// Flow pages
const FlowIndex = lazy(() => import('@/pages/flow/FlowIndex'))
const FlowEditor = lazy(() => import('@/pages/flow/FlowEditor'))
const FlowKeyboardShortcuts = lazy(() => import('@/pages/flow/FlowKeyboardShortcuts'))

// Leverage page (crypto brokers only)
const Leverage = lazy(() => import('@/pages/Leverage'))

/** Route guard: only renders children if leverage_config is true, else redirects to dashboard */
function LeverageRoute() {
  const capabilities = useBrokerStore((s) => s.capabilities)
  if (!capabilities?.leverage_config) {
    return <Navigate to="/dashboard" replace />
  }
  return <Leverage />
}

/** Route guard: hide Holdings for crypto brokers (no equity holdings concept) */
function HoldingsRoute() {
  const capabilities = useBrokerStore((s) => s.capabilities)
  if (capabilities?.broker_type === 'crypto') {
    return <Navigate to="/dashboard" replace />
  }
  return <Holdings />
}

/**
 * Route guard for /admin/* pages: renders children only for platform admins,
 * otherwise redirects to the dashboard. The backend independently enforces
 * admin access on every admin API with 403s -- this guard is the matching
 * client-side gate so a non-admin can neither see the admin panel shell nor
 * land on it by typing the URL. isAdmin comes from /auth/session-status via
 * AuthSync -> authStore.
 */
function RequireAdmin({ children }: { children: ReactNode }) {
  const isAdmin = useAuthStore((s) => s.isAdmin)
  if (!isAdmin) {
    return <Navigate to="/dashboard" replace />
  }
  return <>{children}</>
}

// Admin pages
const AdminIndex = lazy(() => import('@/pages/admin/AdminIndex'))
const FreezeQty = lazy(() => import('@/pages/admin/FreezeQty'))
const Holidays = lazy(() => import('@/pages/admin/Holidays'))
const MarketTimings = lazy(() => import('@/pages/admin/MarketTimings'))
const Diagnostics = lazy(() => import('@/pages/admin/Diagnostics'))
const RemoteMcp = lazy(() => import('@/pages/admin/RemoteMcp'))
const UserManagement = lazy(() => import('@/pages/admin/UserManagement'))
const PaymentSettings = lazy(() => import('@/pages/admin/PaymentSettings'))
const EmailSettings = lazy(() => import('@/pages/admin/EmailSettings'))
const GeoIPSettings = lazy(() => import('@/pages/admin/GeoIPSettings'))
const MasterContract = lazy(() => import('@/pages/admin/MasterContract'))

// Logs & Monitoring pages
const LogsIndex = lazy(() => import('@/pages/LogsIndex'))
const LiveLogs = lazy(() => import('@/pages/Logs'))
const SecurityDashboard = lazy(() => import('@/pages/monitoring/SecurityDashboard'))
const TrafficDashboard = lazy(() => import('@/pages/monitoring/TrafficDashboard'))
const LatencyDashboard = lazy(() => import('@/pages/monitoring/LatencyDashboard'))
const HealthMonitor = lazy(() => import('@/pages/HealthMonitor'))

function PageTitleUpdater() {
  usePageTitle()
  return null
}

function App() {
  return (
    <Providers>
      <BrowserRouter>
        <PageTitleUpdater />
        <AuthSync>
          <Suspense fallback={<PageLoader />}>
            <Routes>
              {/* Public routes */}
              <Route path="/" element={<Home />} />
              <Route path="/faq" element={<Faq />} />
              <Route path="/setup" element={<Setup />} />
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
              <Route path="/verify-email" element={<VerifyEmail />} />
              <Route path="/subscribe" element={<Subscribe />} />
              <Route path="/reset-password" element={<ResetPassword />} />
              <Route path="/error" element={<ServerError />} />
              <Route path="/rate-limited" element={<RateLimited />} />

              {/* Protected routes */}
              <Route element={<Layout />}>
                {/* Broker auth routes */}
                <Route path="/broker" element={<BrokerSelect />} />
                <Route path="/broker/manage" element={<BrokerManage />} />
                <Route path="/broker/:broker/totp" element={<BrokerTOTP />} />
                {/* Dynamic broker TOTP routes for all supported brokers */}
                <Route path="/:broker/auth" element={<BrokerTOTP />} />

                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/positions" element={<Positions />} />
                <Route path="/orderbook" element={<OrderBook />} />
                <Route path="/tradebook" element={<TradeBook />} />
                <Route path="/holdings" element={<HoldingsRoute />} />
                {/* Search routes - match Flask /search/* routes */}
                <Route path="/search/token" element={<Token />} />
                <Route path="/search" element={<Search />} />
                {/* API Key management & session management */}
                <Route path="/apikey" element={<ApiKey />} />
                <Route path="/active-sessions" element={<ActiveSessions />} />
                <Route path="/ai-settings" element={<AiSettings />} />
                {/* Phase 4: Charts & Webhook Configuration */}
                {/* Platform config now lives per-strategy at webhook creation;
                    the standalone Platforms page was removed. Redirect old
                    deep links to the strategy webhooks guide. */}
                <Route path="/platforms" element={<Navigate to="/tools/webhooks" replace />} />
                <Route path="/tradingview" element={<TradingView />} />
                <Route path="/gocharting" element={<GoCharting />} />
                <Route path="/pnl-tracker" element={<PnLTracker />} />
                {/* Phase 4: Sandbox & Analyzer */}
                <Route path="/sandbox" element={<Sandbox />} />
                <Route path="/sandbox/mypnl" element={<SandboxPnL />} />
                <Route path="/analyzer" element={<Analyzer />} />
                {/* Options tools suite — /tools lands on Option Chain; every
                    tool page renders the in-page ToolsSwitcher tab strip. */}
                <Route path="/tools" element={<Navigate to="/optionchain" replace />} />
                <Route path="/optionchain" element={<OptionsTool page={<OptionChain />} />} />
                <Route path="/ivchart" element={<OptionsTool page={<IVChart />} />} />
                <Route path="/oitracker" element={<OptionsTool page={<OITracker />} />} />
                <Route path="/maxpain" element={<OptionsTool page={<MaxPain />} />} />
                <Route path="/straddle" element={<OptionsTool page={<StraddleChart />} />} />
                <Route path="/straddlepnl" element={<OptionsTool page={<CustomStraddle />} />} />
                <Route path="/volsurface" element={<OptionsTool page={<VolSurface />} />} />
                <Route path="/gex" element={<OptionsTool page={<GEXDashboard />} />} />
                <Route path="/ivsmile" element={<OptionsTool page={<IVSmile />} />} />
                <Route path="/oiprofile" element={<OptionsTool page={<OIProfile />} />} />
                <Route path="/visual-builder" element={<StrategyBuilder />} />
                <Route path="/visual-builder/portfolio" element={<StrategyPortfolio />} />
                <Route path="/marketplace" element={<Marketplace />} />
                <Route path="/analytics" element={<Analytics />} />
                <Route path="/deployments" element={<Deployments />} />
                <Route path="/camarilla" element={<OptionsTool page={<Camarilla />} />} />
                {/* Legacy /tools/strategy paths — redirect to the new route. */}
                <Route path="/tools/strategy" element={<Navigate to="/visual-builder" replace />} />
                <Route
                  path="/tools/strategy/portfolio"
                  element={<Navigate to="/visual-builder/portfolio" replace />}
                />
                <Route
                  path="/strategybuilder"
                  element={<Navigate to="/visual-builder" replace />}
                />
                <Route
                  path="/strategybuilder/portfolio"
                  element={<Navigate to="/visual-builder/portfolio" replace />}
                />
                <Route path="/websocket/test" element={<WebSocketTest />} />
                <Route path="/websocket/test/20" element={<WebSocketTest depthLevel={20} />} />
                <Route path="/websocket/test/30" element={<WebSocketTest depthLevel={30} />} />
                <Route path="/websocket/test/50" element={<WebSocketTest depthLevel={50} />} />
                {/* Phase 6: Webhook Strategies */}
                <Route path="/strategy" element={<StrategyIndex />} />
                <Route path="/strategy/new" element={<NewStrategy />} />
                <Route path="/strategy/wizard" element={<StrategyWizard />} />
                <Route path="/strategy/configure" element={<StrategyConfigurator />} />
                <Route path="/strategy/builder/custom" element={<CustomStrategyBuilder />} />
                <Route path="/strategy/backtests" element={<BacktestLogs />} />
                <Route path="/backtest" element={<Backtest />} />
                <Route path="/strategy/:strategyId" element={<ViewStrategy />} />
                <Route path="/strategy/:strategyId/configure" element={<ConfigureSymbols />} />
                <Route path="/tools/webhooks" element={<WebhooksGuide />} />
                {/* Phase 6: Python Strategies */}
                <Route path="/python" element={<PythonStrategyIndex />} />
                <Route path="/python/new" element={<NewPythonStrategy />} />
                <Route path="/python/logs" element={<AllPythonStrategyLogs />} />
                <Route path="/python/:strategyId/edit" element={<EditPythonStrategy />} />
                <Route path="/python/:strategyId/logs" element={<PythonStrategyLogs />} />
                <Route path="/python/:strategyId/schedule" element={<SchedulePythonStrategy />} />
                <Route path="/python/guide" element={<PythonStrategyGuide />} />
                {/* MaxHook — unified signal-connection front door.
                    /maxhook/:connectionId/configure only ever links from a
                    Chartink-provider connection's detail page (see
                    ViewMaxHookConnection's configureHref), reusing
                    ConfigureChartinkSymbols.tsx unchanged — its :strategyId
                    param expects Chartink's raw numeric id, not the
                    composite "kind-id" ViewMaxHookConnection uses for
                    itself. */}
                <Route path="/maxhook" element={<MaxHookIndex />} />
                <Route path="/maxhook/new" element={<NewMaxHookConnection />} />
                <Route path="/maxhook/:connectionId" element={<ViewMaxHookConnection />} />
                <Route
                  path="/maxhook/:strategyId/configure"
                  element={<ConfigureChartinkSymbols />}
                />
                {/* Automation Studio */}
                <Route path="/flow" element={<FlowIndex />} />
                <Route path="/flow/shortcuts" element={<FlowKeyboardShortcuts />} />
                {/* Leverage Configuration (crypto brokers only) */}
                <Route path="/leverage" element={<LeverageRoute />} />
                {/* Phase 7: Admin — all gated to platform admins (RequireAdmin) */}
                <Route
                  path="/admin"
                  element={
                    <RequireAdmin>
                      <AdminIndex />
                    </RequireAdmin>
                  }
                />
                <Route
                  path="/admin/freeze"
                  element={
                    <RequireAdmin>
                      <FreezeQty />
                    </RequireAdmin>
                  }
                />
                <Route
                  path="/admin/holidays"
                  element={
                    <RequireAdmin>
                      <Holidays />
                    </RequireAdmin>
                  }
                />
                <Route
                  path="/admin/timings"
                  element={
                    <RequireAdmin>
                      <MarketTimings />
                    </RequireAdmin>
                  }
                />
                <Route
                  path="/admin/diagnostics"
                  element={
                    <RequireAdmin>
                      <Diagnostics />
                    </RequireAdmin>
                  }
                />
                <Route
                  path="/admin/remote-mcp"
                  element={
                    <RequireAdmin>
                      <RemoteMcp />
                    </RequireAdmin>
                  }
                />
                <Route
                  path="/admin/users"
                  element={
                    <RequireAdmin>
                      <UserManagement />
                    </RequireAdmin>
                  }
                />
                <Route
                  path="/admin/payments"
                  element={
                    <RequireAdmin>
                      <PaymentSettings />
                    </RequireAdmin>
                  }
                />
                <Route
                  path="/admin/email"
                  element={
                    <RequireAdmin>
                      <EmailSettings />
                    </RequireAdmin>
                  }
                />
                <Route
                  path="/admin/geoip"
                  element={
                    <RequireAdmin>
                      <GeoIPSettings />
                    </RequireAdmin>
                  }
                />
                <Route
                  path="/admin/master-contract"
                  element={
                    <RequireAdmin>
                      <MasterContract />
                    </RequireAdmin>
                  }
                />
                {/* Phase 7: Logs & Monitoring */}
                <Route path="/logs" element={<LogsIndex />} />
                <Route path="/logs/live" element={<LiveLogs />} />
                <Route path="/logs/sandbox" element={<Analyzer />} />
                <Route
                  path="/logs/security"
                  element={
                    <RequireAdmin>
                      <SecurityDashboard />
                    </RequireAdmin>
                  }
                />
                <Route
                  path="/logs/traffic"
                  element={
                    <RequireAdmin>
                      <TrafficDashboard />
                    </RequireAdmin>
                  }
                />
                <Route
                  path="/logs/latency"
                  element={
                    <RequireAdmin>
                      <LatencyDashboard />
                    </RequireAdmin>
                  }
                />
                <Route path="/health" element={<HealthMonitor />} />
                {/* Phase 7: Settings & Control Center */}
                <Route path="/profile" element={<Profile />} />
                <Route path="/action-center" element={<ActionCenter />} />
              </Route>

              {/* Full-width protected routes */}
              <Route element={<FullWidthLayout />}>
                <Route path="/playground" element={<Playground />} />
                <Route path="/historify" element={<Historify />} />
                <Route path="/historify/charts" element={<HistorifyCharts />} />
                <Route path="/historify/charts/:symbol" element={<HistorifyCharts />} />
                <Route path="/charts" element={<Charts />} />
                <Route path="/charts/:symbol" element={<Charts />} />
                {/* Automation Studio (full-width for canvas) */}
                <Route path="/flow/editor/:id" element={<FlowEditor />} />
              </Route>

              {/* 404 Not Found */}
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </AuthSync>
      </BrowserRouter>
    </Providers>
  )
}

export default App
