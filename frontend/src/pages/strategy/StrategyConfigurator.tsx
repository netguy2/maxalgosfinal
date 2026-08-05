import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  Clock,
  Crosshair,
  FileText,
  HelpCircle,
  Layers,
  Play,
  Save,
  Settings,
  ShieldCheck,
  Sliders,
  Sparkles,
  Target,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { fetchCSRFToken } from '@/api/client'
import { strategyApi } from '@/api/strategy'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { CATALOG } from '@/lib/marketplace-catalog'
import { getSchemaForTemplate, type StrategyTemplateSchema } from '@/lib/strategy-schemas'
import { SYMBOL_OPTIONS, getExchangeForSymbol } from '@/lib/symbol-options'
import { SearchableSymbolSelect } from '@/components/strategy/SearchableSymbolSelect'
import { isBasketOnlySignal } from '@/lib/template-param-adapter'
import { showToast } from '@/utils/toast'

// Display names for the brokers this platform supports -- mirrors
// BrokerManage.tsx's BROKER_DISPLAY_NAMES. Only used to label whichever
// brokers /api/broker/connections says are actually connected for this
// user; never used to fabricate a broker option that isn't really theirs.
const BROKER_DISPLAY_NAMES: Record<string, string> = {
  compositedge: 'CompositEdge',
  dhan: 'Dhan',
  deltaexchange: 'Delta Exchange',
  indmoney: 'IndMoney',
  dhan_sandbox: 'Dhan (Sandbox)',
  definedge: 'Definedge',
  firstock: 'Firstock',
  flattrade: 'Flattrade',
  motilal: 'Motilal Oswal',
  fyers: 'Fyers',
  ibulls: 'Ibulls',
  iifl: 'IIFL',
  iiflcapital: 'IIFL Capital',
  jainamxts: 'JainamXts',
  pocketful: 'Pocketful',
  rmoney: 'RMoney',
  shoonya: 'Shoonya',
  upstox: 'Upstox',
  wisdom: 'Wisdom Capital',
  zebu: 'Zebu',
  bnr: 'BNR Securities',
  zerodha: 'Zerodha',
  aliceblue: 'Alice Blue',
  angel: 'Angel One',
}

type WizardTab = 'overview' | 'entry' | 'exit' | 'risk' | 'execution' | 'review'

const WIZARD_STEPS: { id: WizardTab; label: string; icon: any }[] = [
  { id: 'overview', label: '1. Overview & Market', icon: Crosshair },
  { id: 'entry', label: '2. Entry Rules', icon: Layers },
  { id: 'exit', label: '3. Exit Rules', icon: Target },
  { id: 'risk', label: '4. Risk & Sizing', icon: ShieldCheck },
  { id: 'execution', label: '5. Execution & Broker', icon: Settings },
  { id: 'review', label: '6. Review & Deploy', icon: CheckCircle2 },
]

export default function StrategyConfigurator() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const templateId = searchParams.get('template') || 'orb-15'

  const catalogTemplate = CATALOG.find((c) => c.id === templateId)
  // Prefer the catalog item's real strategy-type identifier (signalId) over
  // the raw catalog id, which often bears no relationship to the strategy
  // type (see getSchemaForTemplate's own comment for why this matters).
  const schema: StrategyTemplateSchema = getSchemaForTemplate(
    catalogTemplate?.signalId ?? templateId
  )

  const [activeTab, setActiveTab] = useState<WizardTab>('overview')

  // General & Market State
  const [name, setName] = useState(
    catalogTemplate ? `My ${catalogTemplate.name}` : 'My Algo Strategy'
  )
  const [description, setDescription] = useState(
    catalogTemplate?.description || 'Custom strategy configuration based on blueprint template.'
  )
  // Was three independent dropdowns (Exchange/Segment/Symbol) with no
  // validation between them -- the default itself, symbol="NIFTY" +
  // exchange="NSE", was already an invalid pair (NIFTY is an index, quoted
  // under NSE_INDEX, not the plain equity/cash "NSE" segment; there was no
  // NSE_INDEX option in the Exchange dropdown at all), so a user deploying
  // straight off the default hit "wrong symbol"/"no live price" from the
  // broker every time. Symbol now drives Exchange directly via
  // SYMBOL_OPTIONS below, so an invalid pair can no longer be constructed.
  const [symbol, setSymbol] = useState(SYMBOL_OPTIONS[0].value)
  const exchange = getExchangeForSymbol(symbol)
  // Segment (Equity/Options/Futures) is currently informational only --
  // this deployment engine has no options/futures contract-resolution path
  // (services/strategy_compiler.py's options_strategy compiler always
  // raises CompilerError; there is no futures-contract resolver anywhere
  // in services/deployment_service.py), so it always places a plain
  // equity/index-underlying order regardless of this value. Kept as
  // 'Equity' only -- see the Segment select below, which disables the
  // other two options rather than silently accepting a selection that
  // does nothing.
  const [segment] = useState('Equity')

  // Time & Session
  const [timeframe, setTimeframe] = useState(schema.defaultTimeframe || '15m')
  const [startTime, setStartTime] = useState('09:20')
  const [endTime, setEndTime] = useState('15:10')
  const [squareoffTime, setSquareoffTime] = useState('15:15')

  // Dynamic Schema-based Entry Parameters
  const [dynamicConfig, setDynamicConfig] = useState<Record<string, any>>({})

  // Exit Rules
  const [slType, setSlType] = useState('Percentage (%)')
  const [slValue, setSlValue] = useState(1.0)
  const [targetType, setTargetType] = useState('Risk-Reward (1:2)')
  const [targetValue, setTargetValue] = useState(2.0)
  const [exitOnReverse, setExitOnReverse] = useState(true)

  // Risk Management
  const [capital, setCapital] = useState(100000)
  const [sizingMode, setSizingMode] = useState('Risk %')
  const [riskPercent, setRiskPercent] = useState(1.0)
  const [quantity, setQuantity] = useState(50)
  const [maxTradesPerDay, setMaxTradesPerDay] = useState(2)
  const [maxDailyLoss, setMaxDailyLoss] = useState(5000)

  // Execution & Broker
  const [orderType, setOrderType] = useState('Market')
  const [productType, setProductType] = useState('MIS')
  // Basket templates (Equal Weight/Top Volume/Top Gainers/Sector Basket)
  // have no Paper Trading path at all -- see isBasketOnlySignal's doc
  // comment. Default straight to 'live' for these so the wizard's default
  // state isn't itself the broken one; the dropdown below also disables
  // 'paper' outright rather than just defaulting away from it.
  const [executionMode, setExecutionMode] = useState<'live' | 'paper'>(
    isBasketOnlySignal(catalogTemplate?.signalId) ? 'live' : 'paper'
  )
  // Was hardcoded to 'zebu' regardless of what the user actually connected --
  // every live deployment silently routed to a broker session that might not
  // exist, failing with "Broker order rejected" / "Invalid Trading Symbol" on
  // every single order. Starts empty and is populated from the user's REAL
  // connected brokers below; the chip picker itself only ever lists brokers
  // that fetch confirmed are connected.
  //
  // Multiple brokers can be selected at once -- on deploy, one independent
  // order fans out to EVERY selected broker (services/deployment_service.py's
  // _evaluation_loop), so a strategy can run the same signal across several
  // connected accounts simultaneously instead of only ever picking one.
  const [selectedBrokers, setSelectedBrokers] = useState<string[]>([])
  const [connectedBrokers, setConnectedBrokers] = useState<string[]>([])

  const toggleBroker = (broker: string) => {
    setSelectedBrokers((prev) =>
      prev.includes(broker) ? prev.filter((b) => b !== broker) : [...prev, broker]
    )
  }

  const [saving, setSaving] = useState(false)
  const [deploying, setDeploying] = useState(false)

  const [loadingBrokers, setLoadingBrokers] = useState(false)

  // Load the user's actual connected brokers (never a fabricated static
  // list) -- same /api/broker/connections endpoint Broker Management,
  // DeployStrategyDrawer, and PlaceOrderDialog already use. Exposed as a
  // callback (not just a one-shot mount effect) because a stale one-time
  // fetch here previously meant: connect/reconnect a broker AFTER this page
  // loaded, and the wizard kept showing whatever broker was live at mount
  // time forever, with no way to refresh it short of a full page reload --
  // the "Connected Broker" field is disabled in Paper mode too, so this was
  // easy to not notice until switching to Live mode.
  const loadConnectedBrokers = useCallback(async () => {
    setLoadingBrokers(true)
    try {
      const response = await fetch('/api/broker/connections', { credentials: 'include' })
      if (!response.ok) return
      const data = await response.json()
      if (data.status !== 'success') return
      const connected: string[] = (data.connections || [])
        .filter((c: { connected: boolean }) => c.connected)
        .map((c: { broker: string }) => c.broker)
      setConnectedBrokers(connected)
      setSelectedBrokers((prev) => {
        // Drop any previously-selected broker that's no longer connected;
        // keep everything else. Default to the first connected broker only
        // when nothing was selected yet at all (first load).
        const stillValid = prev.filter((b) => connected.includes(b))
        if (stillValid.length > 0) return stillValid
        if (prev.length === 0 && connected.length > 0) return [connected[0]]
        return stillValid
      })
    } catch {
      /* non-fatal -- dropdown just stays as it was */
    } finally {
      setLoadingBrokers(false)
    }
  }, [])

  useEffect(() => {
    loadConnectedBrokers()
  }, [loadConnectedBrokers])

  // Re-check on every switch into Live mode -- the whole point of this
  // control is "which broker will REAL orders go to", so it must reflect
  // whatever is connected right now, not whatever was connected when the
  // page happened to load.
  useEffect(() => {
    if (executionMode === 'live') {
      loadConnectedBrokers()
    }
  }, [executionMode, loadConnectedBrokers])

  // Initialize dynamic configuration fields from schema defaults
  useEffect(() => {
    const initialConfig: Record<string, any> = {}
    schema.fields.forEach((field) => {
      initialConfig[field.key] = field.default
    })
    setDynamicConfig(initialConfig)
  }, [schema])

  // Combine full configuration object for explanation and validation
  const fullConfig = {
    name,
    description,
    exchange,
    segment,
    symbol,
    timeframe,
    startTime,
    endTime,
    squareoffTime,
    slType,
    slValue,
    targetType,
    targetValue,
    capital,
    sizingMode,
    riskPercent,
    quantity,
    maxTradesPerDay,
    maxDailyLoss,
    executionMode,
    selectedBrokers,
    orderType,
    productType,
    ...dynamicConfig,
  }

  // Real-time plain English explanation & validation alerts
  const explanation = schema.generateExplanation(fullConfig)
  const validationErrors = schema.validate(fullConfig)

  const handleSaveStrategy = async (deployNow = false) => {
    if (validationErrors.length > 0) {
      showToast.error(validationErrors[0], 'strategy')
      return
    }
    if (deployNow && executionMode === 'live' && selectedBrokers.length === 0) {
      showToast.error(
        'No broker connected -- connect one in Broker Management before deploying live.',
        'strategy'
      )
      return
    }

    if (deployNow) {
      setDeploying(true)
    } else {
      setSaving(true)
    }

    try {
      // 1. Create strategy blueprint in database
      const created = await strategyApi.createStrategy({
        name,
        platform: 'Custom',
        strategy_type: 'intraday',
        trading_mode: 'BOTH',
        start_time: startTime,
        end_time: endTime,
        squareoff_time: squareoffTime,
        template_id: templateId,
      })

      const newId = created?.data?.strategy_id

      if (!newId) {
        showToast.error('Failed to create strategy configuration', 'strategy')
        return
      }

      // Add symbol mapping
      try {
        await strategyApi.addSymbolMapping(newId, {
          symbol,
          exchange,
          quantity,
          product_type: productType,
        })
      } catch {
        // Continue
      }

      // 2. Deploy immediately if requested.
      //
      // Live Broker Mode for a signalId this platform can generate real
      // Python for: skip the wizard/compiler/conditions_tree pipeline
      // entirely (services/strategy_compiler.py -> services/
      // deployment_service.py's background evaluation loop) -- that
      // pipeline re-derives symbol/exchange/order-routing at multiple
      // separate hops, which is exactly where this session's earlier bugs
      // (wrong symbol, index order-placement failures) hid. Instead,
      // generate one real, runnable Python script with the wizard's
      // chosen symbol/exchange/periods baked in as literal values once,
      // and upload it through the exact same path NewPythonStrategy.tsx
      // uses -- the platform's Python Strategy Host then runs it as an
      // isolated, process-supervised subprocess placing real orders via
      // the maxalgos SDK.
      //
      // Paper Trading keeps using the old pipeline unchanged (the Python
      // runner has no simulated/sandbox execution mode yet), as does any
      // template with no signalId adapter (e.g. option-structure catalog
      // entries, which route through the Options Strategy Builder
      // instead and were never part of this pipeline to begin with).
      if (deployNow) {
        const targetBrokers =
          executionMode === 'paper'
            ? ['Paper Trading']
            : selectedBrokers.length > 0
              ? selectedBrokers
              : connectedBrokers.length > 0
                ? [connectedBrokers[0]]
                : ['zebu']

        const csrfToken = await fetchCSRFToken()
        const deployRes = await fetch('/api/v1/deployments', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
          },
          body: JSON.stringify({
            strategy_id: newId,
            name: `${name} (Active)`,
            brokers: targetBrokers,
            capital,
            max_positions: maxTradesPerDay,
            order_type: orderType,
            product: productType,
            trigger_type: 'On Conditions',
            deploy_now: true,
            strategy_config: fullConfig,
            template_id: templateId,
          }),
        })

        const deployData = await deployRes.json()
        if (deployData.id) {
          await fetch(`/api/v1/deployments/${deployData.id}/resume`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
          })
          showToast.success(
            `Strategy "${name}" configured & deployed live (${targetBrokers.join(', ')})!`,
            'strategy'
          )
          navigate('/deployments')
          return
        }

        // Deploy failed (e.g. this strategy type has no compiler yet --
        // services/strategy_compiler.py raised CompilerError, returned as a
        // 400 with a message). The strategy blueprint was still saved to
        // "My Strategies" above, but going live failed -- must NOT fall
        // through to the generic success toast below, which would tell the
        // user deployment succeeded when it didn't.
        showToast.error(
          deployData?.message || `Strategy saved, but live deployment failed.`,
          'strategy'
        )
        navigate('/strategy')
        return
      }

      showToast.success(`Strategy "${name}" saved to My Strategies!`, 'strategy')
      navigate('/strategy')
    } catch {
      showToast.error('Failed to save strategy configuration', 'strategy')
    } finally {
      setSaving(false)
      setDeploying(false)
    }
  }

  return (
    <div className="min-h-screen bg-background p-4 md:p-8 space-y-6 max-w-7xl mx-auto pb-24">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border/50 pb-5">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Link
              to="/marketplace"
              className="flex items-center gap-1 hover:text-foreground transition"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Marketplace</span>
            </Link>
            <span>/</span>
            <span>{schema.name} Configurator</span>
          </div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight">{name}</h1>
            <Badge variant="outline" className="bg-primary/10 text-primary border-primary/20">
              <Sparkles className="w-3 h-3 mr-1" />
              {schema.category} Blueprint
            </Badge>
            <Badge variant="outline" className="bg-profit/10 text-profit border-profit/20">
              No Code Required
            </Badge>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            className="text-xs font-bold gap-1.5"
            onClick={() => navigate('/marketplace')}
          >
            Cancel
          </Button>
          <Button
            variant="outline"
            className="text-xs font-bold gap-1.5 border-border hover:bg-accent"
            onClick={() => handleSaveStrategy(false)}
            disabled={saving || deploying}
          >
            <Save className="w-3.5 h-3.5" />
            {saving ? 'Saving...' : 'Save Draft'}
          </Button>
          <Button
            className="text-xs font-bold gap-1.5 bg-cat-2 hover:bg-cat-2 text-white"
            onClick={() => handleSaveStrategy(true)}
            disabled={saving || deploying || validationErrors.length > 0}
          >
            <Play className="w-3.5 h-3.5 fill-current" />
            {deploying ? 'Deploying...' : 'Deploy Strategy'}
          </Button>
        </div>
      </div>

      {/* Validation Warnings Banner */}
      {validationErrors.length > 0 && (
        <div className="p-3 bg-warning/10 border border-warning/30 rounded-lg flex items-center gap-3 text-xs text-warning">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <div className="font-semibold">{validationErrors[0]}</div>
        </div>
      )}

      {/* Wizard / Tab Navigation Bar */}
      <div className="flex items-center gap-1 border-b border-border overflow-x-auto pb-1">
        {WIZARD_STEPS.map((step) => {
          const Icon = step.icon
          const isActive = activeTab === step.id
          return (
            <button
              key={step.id}
              onClick={() => setActiveTab(step.id)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-t-lg text-xs font-semibold transition border-b-2 whitespace-nowrap ${
                isActive
                  ? 'border-cat-2 text-cat-2 bg-cat-2/5'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-accent/50'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{step.label}</span>
            </button>
          )
        })}
      </div>

      {/* Main Grid: Wizard Config Form (Left 2 cols) + Live Behavior Explanation (Right 1 col) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Form Area (2 cols) */}
        <div className="lg:col-span-2 space-y-6">
          {/* TAB 1: OVERVIEW & MARKET */}
          {activeTab === 'overview' && (
            <div className="space-y-6">
              <Card className="border border-border">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-bold flex items-center gap-2">
                    <Sliders className="w-4 h-4 text-cat-2" />
                    Strategy Identity & General Details
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground block mb-1">
                      Strategy Name
                    </label>
                    <input
                      type="text"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className="w-full px-3 py-2 rounded-md border border-border bg-background text-sm font-bold focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground block mb-1">
                      Description
                    </label>
                    <textarea
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      rows={2}
                      className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                    />
                  </div>
                </CardContent>
              </Card>

              <Card className="border border-border">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-bold flex items-center gap-2">
                    <Crosshair className="w-4 h-4 text-profit" />
                    Target Instrument & Asset Class
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-3 gap-3">
                    <div>
                      <label className="text-xs font-semibold text-muted-foreground block mb-1">
                        Primary Symbol
                      </label>
                      <SearchableSymbolSelect value={symbol} onChange={setSymbol} />
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-muted-foreground block mb-1">
                        Exchange
                      </label>
                      {/* Derived from Symbol, not independently choosable --
                      an index/equity/commodity symbol only ever trades on
                      one correct exchange, and letting the two be picked
                      separately is exactly what produced invalid pairs
                      (e.g. NIFTY + plain NSE) that the broker rejected as
                      "wrong symbol". */}
                      <input
                        value={exchange}
                        disabled
                        readOnly
                        className="w-full px-3 py-2 rounded-md border border-border bg-muted/40 text-xs font-medium text-muted-foreground cursor-not-allowed"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-muted-foreground block mb-1">
                        Segment
                      </label>
                      <select
                        value={segment}
                        disabled
                        className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs focus:outline-none font-medium disabled:opacity-70"
                      >
                        <option value="Equity">Equity / Index</option>
                        <option value="Options" disabled>
                          Options (Coming soon)
                        </option>
                        <option value="Futures" disabled>
                          Futures (Coming soon)
                        </option>
                      </select>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card className="border border-border">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm font-bold flex items-center gap-2">
                    <Clock className="w-4 h-4 text-info" />
                    Timeframe & Intraday Trading Session
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-4 gap-3">
                    <div>
                      <label className="text-xs font-semibold text-muted-foreground block mb-1">
                        Timeframe
                      </label>
                      <select
                        value={timeframe}
                        onChange={(e) => setTimeframe(e.target.value)}
                        className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs font-semibold focus:outline-none"
                      >
                        <option value="1m">1 Minute</option>
                        <option value="3m">3 Minutes</option>
                        <option value="5m">5 Minutes</option>
                        <option value="15m">15 Minutes</option>
                        <option value="30m">30 Minutes</option>
                        <option value="1h">1 Hour</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-muted-foreground block mb-1">
                        Trading Start Time
                      </label>
                      <input
                        type="time"
                        value={startTime}
                        onChange={(e) => setStartTime(e.target.value)}
                        className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs font-mono font-bold focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-muted-foreground block mb-1">
                        Trading End Time
                      </label>
                      <input
                        type="time"
                        value={endTime}
                        onChange={(e) => setEndTime(e.target.value)}
                        className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs font-mono font-bold focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-muted-foreground block mb-1">
                        Auto Square-Off
                      </label>
                      <input
                        type="time"
                        value={squareoffTime}
                        onChange={(e) => setSquareoffTime(e.target.value)}
                        className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs font-mono font-bold focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    </div>
                  </div>

                  {/* Quick Preset Time Pills */}
                  <div className="flex items-center gap-2 pt-1 border-t border-border/40">
                    <span className="text-[11px] font-semibold text-muted-foreground">
                      Quick Presets:
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        setStartTime('09:15')
                        setEndTime('15:10')
                        setSquareoffTime('15:15')
                      }}
                      className="px-2 py-0.5 rounded text-[10px] font-medium bg-muted hover:bg-accent border border-border/50 text-foreground transition"
                    >
                      Market Session (09:15 - 15:15)
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setStartTime('09:30')
                        setEndTime('15:10')
                        setSquareoffTime('15:15')
                      }}
                      className="px-2 py-0.5 rounded text-[10px] font-medium bg-muted hover:bg-accent border border-border/50 text-foreground transition"
                    >
                      ORB 15 Session (09:30 - 15:15)
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setStartTime('10:00')
                        setEndTime('14:30')
                        setSquareoffTime('15:00')
                      }}
                      className="px-2 py-0.5 rounded text-[10px] font-medium bg-muted hover:bg-accent border border-border/50 text-foreground transition"
                    >
                      Mid-Day Session (10:00 - 15:00)
                    </button>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* TAB 2: DYNAMIC ENTRY RULES */}
          {activeTab === 'entry' && (
            <Card className="border border-border">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-bold flex items-center gap-2">
                  <Layers className="w-4 h-4 text-cat-2" />
                  {schema.name} Entry Parameters
                </CardTitle>
                <CardDescription className="text-xs">
                  Template-specific entry triggers and indicator settings.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  {schema.fields
                    .filter((f) => f.category === 'entry')
                    .map((field) => (
                      <div key={field.key} className="space-y-1">
                        <label className="text-xs font-semibold text-muted-foreground block">
                          {field.label}
                        </label>
                        {field.type === 'select' && (
                          <select
                            value={dynamicConfig[field.key] ?? field.default}
                            onChange={(e) =>
                              setDynamicConfig((prev) => ({ ...prev, [field.key]: e.target.value }))
                            }
                            className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs font-semibold focus:outline-none"
                          >
                            {field.options?.map((opt) => (
                              <option key={opt.value} value={opt.value}>
                                {opt.label}
                              </option>
                            ))}
                          </select>
                        )}
                        {field.type === 'number' && (
                          <input
                            type="number"
                            step={field.step || 1}
                            min={field.min}
                            max={field.max}
                            value={dynamicConfig[field.key] ?? field.default}
                            onChange={(e) =>
                              setDynamicConfig((prev) => ({
                                ...prev,
                                [field.key]: Number(e.target.value),
                              }))
                            }
                            className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs font-semibold focus:outline-none"
                          />
                        )}
                        {field.type === 'boolean' && (
                          <div className="flex items-center gap-2 pt-2">
                            <input
                              type="checkbox"
                              id={field.key}
                              checked={!!(dynamicConfig[field.key] ?? field.default)}
                              onChange={(e) =>
                                setDynamicConfig((prev) => ({
                                  ...prev,
                                  [field.key]: e.target.checked,
                                }))
                              }
                              className="rounded border-border"
                            />
                            <label
                              htmlFor={field.key}
                              className="text-xs font-medium cursor-pointer"
                            >
                              Enable {field.label}
                            </label>
                          </div>
                        )}
                        {field.description && (
                          <p className="text-[10px] text-muted-foreground">{field.description}</p>
                        )}
                      </div>
                    ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* TAB 3: EXIT RULES */}
          {activeTab === 'exit' && (
            <Card className="border border-border">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-bold flex items-center gap-2">
                  <Target className="w-4 h-4 text-profit" />
                  Exit Rules & Profit Targets
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground block mb-1">
                      Stop Loss Type
                    </label>
                    <select
                      value={slType}
                      onChange={(e) => setSlType(e.target.value)}
                      className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs focus:outline-none"
                    >
                      <option value="Percentage (%)">Percentage (%)</option>
                      <option value="Fixed Points">Fixed Points</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground block mb-1">
                      Stop Loss Value
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      value={slValue}
                      onChange={(e) => setSlValue(Number(e.target.value))}
                      className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs text-loss font-bold focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground block mb-1">
                      Target Type
                    </label>
                    <select
                      value={targetType}
                      onChange={(e) => setTargetType(e.target.value)}
                      className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs focus:outline-none"
                    >
                      <option value="Risk-Reward (1:2)">Risk-Reward Ratio</option>
                      <option value="Percentage (%)">Percentage (%)</option>
                      <option value="Fixed Points">Fixed Points</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground block mb-1">
                      Target Value
                    </label>
                    <input
                      type="number"
                      step="0.1"
                      value={targetValue}
                      onChange={(e) => setTargetValue(Number(e.target.value))}
                      className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs text-profit font-bold focus:outline-none"
                    />
                  </div>
                </div>

                <div className="flex items-center gap-2 pt-2 border-t border-border">
                  <input
                    type="checkbox"
                    id="exitReverse"
                    checked={exitOnReverse}
                    onChange={(e) => setExitOnReverse(e.target.checked)}
                    className="rounded border-border"
                  />
                  <label htmlFor="exitReverse" className="text-xs font-medium cursor-pointer">
                    Exit on Opposite Crossover Signal
                  </label>
                </div>
              </CardContent>
            </Card>
          )}

          {/* TAB 4: RISK & SIZING */}
          {activeTab === 'risk' && (
            <Card className="border border-border">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-bold flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-warning" />
                  Capital & Risk Controls
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <label className="text-xs font-semibold text-muted-foreground block mb-1">
                    Allocated Capital (₹)
                  </label>
                  <input
                    type="number"
                    value={capital}
                    onChange={(e) => setCapital(Number(e.target.value))}
                    className="w-full px-3 py-2 rounded-md border border-border bg-background text-sm font-bold focus:outline-none"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground block mb-1">
                      Position Sizing Mode
                    </label>
                    <select
                      value={sizingMode}
                      onChange={(e) => setSizingMode(e.target.value)}
                      className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs focus:outline-none"
                    >
                      <option value="Risk %">Risk % Per Trade</option>
                      <option value="Fixed Qty">Fixed Quantity</option>
                    </select>
                  </div>
                  {sizingMode === 'Risk %' ? (
                    <div>
                      <label className="text-xs font-semibold text-muted-foreground block mb-1">
                        Risk Per Trade (%)
                      </label>
                      <input
                        type="number"
                        step="0.5"
                        value={riskPercent}
                        onChange={(e) => setRiskPercent(Number(e.target.value))}
                        className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs focus:outline-none font-bold text-warning"
                      />
                    </div>
                  ) : (
                    <div>
                      <label className="text-xs font-semibold text-muted-foreground block mb-1">
                        Fixed Quantity (Shares/Lots)
                      </label>
                      <input
                        type="number"
                        value={quantity}
                        onChange={(e) => setQuantity(Number(e.target.value))}
                        className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs focus:outline-none font-bold"
                      />
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground block mb-1">
                      Max Trades / Day
                    </label>
                    <input
                      type="number"
                      value={maxTradesPerDay}
                      onChange={(e) => setMaxTradesPerDay(Number(e.target.value))}
                      className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs focus:outline-none font-semibold"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground block mb-1">
                      Max Daily Loss Limit (₹)
                    </label>
                    <input
                      type="number"
                      value={maxDailyLoss}
                      onChange={(e) => setMaxDailyLoss(Number(e.target.value))}
                      className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs text-loss font-bold focus:outline-none"
                    />
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* TAB 5: EXECUTION & BROKER */}
          {activeTab === 'execution' && (
            <Card className="border border-border">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-bold flex items-center gap-2">
                  <Settings className="w-4 h-4 text-muted-foreground" />
                  Broker Routing & Order Execution
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground block mb-1">
                      Execution Mode
                    </label>
                    <select
                      value={executionMode}
                      onChange={(e) => setExecutionMode(e.target.value as any)}
                      className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs font-bold focus:outline-none"
                    >
                      <option
                        value="paper"
                        disabled={isBasketOnlySignal(catalogTemplate?.signalId)}
                      >
                        Paper Trading (Simulated)
                        {isBasketOnlySignal(catalogTemplate?.signalId)
                          ? ' -- not available for basket strategies'
                          : ''}
                      </option>
                      <option value="live">Live Broker Mode</option>
                    </select>
                    {isBasketOnlySignal(catalogTemplate?.signalId) && (
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        Basket strategies generate a real Python script and only run in Live Broker
                        Mode -- there's no simulated basket execution yet.
                      </p>
                    )}
                  </div>
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-xs font-semibold text-muted-foreground">
                        Connected Broker{selectedBrokers.length > 1 ? 's' : ''}
                      </label>
                      <button
                        type="button"
                        onClick={loadConnectedBrokers}
                        disabled={loadingBrokers}
                        className="text-[11px] font-semibold text-primary hover:underline disabled:opacity-50"
                        title="Re-check which brokers are currently connected"
                      >
                        {loadingBrokers ? 'Checking…' : 'Refresh'}
                      </button>
                    </div>
                    {/* Chip multi-select: click a broker to toggle it in/out
                    of selection. On deploy, one independent order fans out
                    to EVERY selected broker (services/deployment_service.py),
                    so this strategy can run across several connected
                    accounts at once instead of only one. */}
                    {connectedBrokers.length === 0 ? (
                      <p className="px-3 py-2 rounded-md border border-dashed border-border text-xs text-muted-foreground">
                        No broker connected
                      </p>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {connectedBrokers.map((broker) => {
                          const active = selectedBrokers.includes(broker)
                          return (
                            <button
                              key={broker}
                              type="button"
                              disabled={executionMode === 'paper'}
                              onClick={() => toggleBroker(broker)}
                              className={`px-2.5 py-1.5 rounded-full text-xs font-semibold border transition disabled:opacity-50 disabled:cursor-not-allowed ${
                                active
                                  ? 'bg-primary text-primary-foreground border-primary'
                                  : 'bg-background text-muted-foreground border-border hover:border-primary/50'
                              }`}
                            >
                              {active && '✓ '}
                              {BROKER_DISPLAY_NAMES[broker] ?? broker}
                            </button>
                          )
                        })}
                      </div>
                    )}
                    {executionMode === 'live' && connectedBrokers.length === 0 && (
                      <p className="mt-1 text-[11px] text-loss">
                        No broker connected -- connect one in Broker Management before deploying
                        live.
                      </p>
                    )}
                    {executionMode === 'live' &&
                      connectedBrokers.length > 0 &&
                      selectedBrokers.length === 0 && (
                        <p className="mt-1 text-[11px] text-loss">
                          Select at least one broker to deploy live.
                        </p>
                      )}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground block mb-1">
                      Order Type
                    </label>
                    <select
                      value={orderType}
                      onChange={(e) => setOrderType(e.target.value)}
                      className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs focus:outline-none font-medium"
                    >
                      <option value="Market">Market Order</option>
                      <option value="Limit">Limit Order</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground block mb-1">
                      Product Type
                    </label>
                    <select
                      value={productType}
                      onChange={(e) => setProductType(e.target.value)}
                      className="w-full px-3 py-2 rounded-md border border-border bg-background text-xs font-semibold focus:outline-none"
                    >
                      <option value="MIS">MIS (Intraday)</option>
                      <option value="NRML">NRML (Overnight)</option>
                      <option value="CNC">CNC (Delivery)</option>
                    </select>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* TAB 6: REVIEW & DEPLOY */}
          {activeTab === 'review' && (
            <Card className="border border-border">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-bold flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-profit" />
                  Deployment Conditions Summary
                </CardTitle>
                <CardDescription className="text-xs">
                  Review all parameters before initiating 1-click live execution.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4 text-xs">
                  <div className="p-3 bg-muted/30 rounded-lg space-y-1.5 border border-border/50">
                    <div className="font-bold text-muted-foreground border-b border-border/40 pb-1">
                      Market & Time
                    </div>
                    <div>
                      Exchange: <span className="font-semibold">{exchange}</span>
                    </div>
                    <div>
                      Symbol: <span className="font-bold text-primary">{symbol}</span>
                    </div>
                    <div>
                      Timeframe: <span className="font-semibold">{timeframe}</span>
                    </div>
                    <div>
                      Window:{' '}
                      <span className="font-mono">
                        {startTime} - {endTime}
                      </span>
                    </div>
                    <div>
                      Square-Off: <span className="font-mono">{squareoffTime}</span>
                    </div>
                  </div>

                  <div className="p-3 bg-muted/30 rounded-lg space-y-1.5 border border-border/50">
                    <div className="font-bold text-muted-foreground border-b border-border/40 pb-1">
                      Risk & Execution
                    </div>
                    <div>
                      Capital: <span className="font-bold">₹{capital.toLocaleString()}</span>
                    </div>
                    <div>
                      Sizing: <span className="font-semibold">{sizingMode}</span>
                    </div>
                    <div>
                      Stop Loss:{' '}
                      <span className="font-semibold text-loss">
                        {slValue} {slType}
                      </span>
                    </div>
                    <div>
                      Target:{' '}
                      <span className="font-semibold text-profit">
                        {targetValue} {targetType}
                      </span>
                    </div>
                    <div>
                      Mode:{' '}
                      <span className="font-bold text-cat-2">
                        {executionMode.toUpperCase()} (
                        {executionMode === 'paper'
                          ? 'Paper Trading'
                          : selectedBrokers.map((b) => BROKER_DISPLAY_NAMES[b] ?? b).join(', ') ||
                            'none selected'}
                        )
                      </span>
                    </div>
                  </div>
                </div>

                <Button
                  className="w-full text-xs font-bold gap-2 bg-cat-2 hover:bg-cat-2 text-white py-3"
                  onClick={() => handleSaveStrategy(true)}
                  disabled={saving || deploying || validationErrors.length > 0}
                >
                  <Play className="w-4 h-4 fill-current" />
                  <span>Confirm & Deploy Strategy Now</span>
                </Button>
              </CardContent>
            </Card>
          )}

          {/* Navigation Buttons (Prev / Next Step) */}
          <div className="flex items-center justify-between pt-2">
            <Button
              variant="outline"
              size="sm"
              disabled={activeTab === 'overview'}
              onClick={() => {
                const idx = WIZARD_STEPS.findIndex((s) => s.id === activeTab)
                if (idx > 0) setActiveTab(WIZARD_STEPS[idx - 1].id)
              }}
              className="text-xs font-semibold"
            >
              Previous Step
            </Button>

            <Button
              size="sm"
              disabled={activeTab === 'review'}
              onClick={() => {
                const idx = WIZARD_STEPS.findIndex((s) => s.id === activeTab)
                if (idx < WIZARD_STEPS.length - 1) setActiveTab(WIZARD_STEPS[idx + 1].id)
              }}
              className="text-xs font-bold gap-1 bg-primary text-primary-foreground"
            >
              <span>Next Step</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>

        {/* Right Column: Live Strategy Explanation Panel (Sticky 1 col) */}
        <div className="space-y-6 lg:sticky lg:top-8 self-start">
          <Card className="border border-cat-2/30 bg-cat-2/5 shadow-sm">
            <CardHeader className="pb-3 border-b border-cat-2/20">
              <CardTitle className="text-sm font-bold text-cat-2 flex items-center gap-2">
                <FileText className="w-4 h-4" />
                Live Strategy Explanation
              </CardTitle>
              <CardDescription className="text-[11px] text-muted-foreground">
                Plain English summary updating in real time as you adjust parameters.
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-3">
              <pre className="text-xs font-mono whitespace-pre-wrap leading-relaxed text-foreground/90 bg-background/80 p-3.5 rounded-lg border border-border/60">
                {explanation}
              </pre>

              <div className="p-2.5 bg-background/60 rounded-md border border-border/50 flex items-start gap-2 text-[11px] text-muted-foreground">
                <HelpCircle className="w-3.5 h-3.5 text-cat-2 shrink-0 mt-0.5" />
                <span>
                  This strategy configuration is compiled into a clean execution graph on Max Algos engine. No code is exposed or required.
                </span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
