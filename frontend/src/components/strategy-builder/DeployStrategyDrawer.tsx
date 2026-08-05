import { Layers, Plus, Trash2, X, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { fetchCSRFToken } from '@/api/client'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const BROKER_DISPLAY_NAMES: Record<string, string> = {
  fivepaisa: '5 Paisa',
  fivepaisaxts: '5 Paisa (XTS)',
  aliceblue: 'Alice Blue',
  angel: 'Angel One',
  arrow: 'Arrow',
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
}

interface DeployStrategyDrawerProps {
  open: boolean
  onClose: () => void
  strategyName: string
  legs: any[]
  /** True while the caller is still fetching `legs` from the strategy's
   * real symbol mappings — used to distinguish "still loading" from
   * "strategy genuinely has no symbols configured" so we don't flash a
   * false validation error while the fetch is in flight. */
  legsLoading?: boolean
  /** Real strategy row this deployment attaches to — required to create the
   * Draft deployment the dry-run validates against. */
  strategyId: number | undefined
  /**
   * Called once the user confirms activation on the Review tab, AFTER a
   * real Draft deployment already exists and (optionally) passed dry-run.
   * Receives the created deployment's id — the caller's job is just to
   * activate it (e.g. POST its resume endpoint) and update its own UI,
   * not to create anything.
   */
  onActivate: (deploymentId: number) => Promise<void>
}

export function DeployStrategyDrawer({
  open,
  onClose,
  strategyName,
  legs,
  legsLoading = false,
  strategyId,
  onActivate,
}: DeployStrategyDrawerProps) {
  const [activeTab, setActiveTab] = useState<string>('General')
  const [name, setName] = useState(strategyName || 'My Deployed Strategy')
  const [executionMode, setExecutionMode] = useState<'live' | 'paper'>('paper')
  const [selectedBrokers, setSelectedBrokers] = useState<string[]>(['Paper Trading'])
  const [connectedBrokers, setConnectedBrokers] = useState<string[]>([])
  const [capital, setCapital] = useState(50000)
  const [maxPositions, setMaxPositions] = useState(2)
  const [orderType, setOrderType] = useState('Market')
  const [product, setProduct] = useState('MIS')
  const [triggerType] = useState('On Conditions')

  // Risk Params
  const [dailyLoss, setDailyLoss] = useState(10000)
  const [maxTrades, setMaxTrades] = useState(5)
  const [stopAfterProfit, setStopAfterProfit] = useState(20000)
  const [cooldown, setCooldown] = useState(15)

  // Conditions list (implicit AND group). Starts empty — these are not
  // derived from the actual strategy (no real signal exists here to infer
  // them from), so defaulting to fake values like "RSI < 30" would silently
  // attach trigger conditions the user never chose. The user adds their own
  // via handleAddCondition below.
  const [conditions, setConditions] = useState<
    Array<{ indicator: string; condition: string; value: number }>
  >([])

  // Real dry-run state. dryRunChecks holds the backend's actual per-check
  // booleans (services/deployment_service.py's validate_dry_run) — note
  // broker_connected is a genuine DB lookup; the other three keys are
  // currently hardcoded True server-side (no real margin/permissions/
  // capital check exists yet). Surfaced honestly rather than implying more
  // certainty than the backend actually provides.
  const [validationError, setValidationError] = useState<string | null>(null)
  const [draftDeploymentId, setDraftDeploymentId] = useState<number | null>(null)
  const [creatingDraft, setCreatingDraft] = useState(false)
  const [activating, setActivating] = useState(false)

  // Reset draft state on every fresh open — this is a new deploy session.
  useEffect(() => {
    if (!open) return
    setValidationError(null)
    setDraftDeploymentId(null)
    setActiveTab('General')
  }, [open])

  useEffect(() => {
    if (!open) return
    const fetchBrokers = async () => {
      try {
        const response = await fetch('/api/broker/connections')
        if (response.ok) {
          const data = await response.json()
          if (data.status === 'success') {
            const connected = (data.connections || [])
              .filter((c: any) => c.connected)
              .map((c: any) => BROKER_DISPLAY_NAMES[c.broker] || c.broker)
            setConnectedBrokers(connected)
            if (connected.length > 0) {
              setSelectedBrokers([connected[0]])
              setExecutionMode('live')
            } else {
              setSelectedBrokers(['Paper Trading'])
              setExecutionMode('paper')
            }
          }
        }
      } catch (e) {
        console.error('Failed to load connected brokers:', e)
      }
    }
    fetchBrokers()
  }, [open])

  const handleAddCondition = () => {
    setConditions([...conditions, { indicator: 'RSI', condition: '<', value: 50 }])
  }

  const handleRemoveCondition = (index: number) => {
    setConditions(conditions.filter((_, i) => i !== index))
  }

  const handleUpdateCondition = (index: number, key: string, val: any) => {
    setConditions(conditions.map((c, i) => (i === index ? { ...c, [key]: val } : c)))
  }

  const buildDeploymentParams = () => {
    // Compile flat conditions array into a nested logical AND tree node
    const conditionsTree = {
      operator: 'AND',
      children: conditions.map((c) => ({
        indicator: c.indicator,
        condition: c.condition,
        value: c.value,
      })),
    }

    const riskParams = {
      daily_loss_limit: dailyLoss,
      max_trades: maxTrades,
      profit_target: stopAfterProfit,
      cooldown: cooldown,
    }

    return {
      name,
      strategy_id: strategyId,
      broker: selectedBrokers.join(','),
      capital,
      max_positions: maxPositions,
      order_type: orderType,
      product,
      trigger_type: triggerType,
      conditions_tree: conditionsTree,
      risk_params: riskParams,
      // Always created as a Draft here — activation is a separate,
      // explicit step (see handleActivateClick) once dry-run has run.
      deploy_now: false,
      strategy_config: {
        // No fabricated symbol/exchange fallback here -- legs is the
        // strategy's real symbol mappings (fetched by the caller before
        // opening this drawer). An empty legs array reaching this point is
        // blocked by ensureDraftDeployment below, never silently sent as a
        // fake NIFTY/NFO pair the backend can't resolve.
        legs: legs.map((l) => ({
          symbol: l.symbol,
          exchange: l.exchange,
          side: l.side || 'BUY',
          segment: l.segment || 'OPTION',
        })),
      },
    }
  }

  /** Creates the real Draft deployment the dry-run and activation both
   * operate on. Idempotent per drawer session — only fires once, the first
   * time the Review tab is opened. */
  const ensureDraftDeployment = async (): Promise<number | null> => {
    if (draftDeploymentId !== null) return draftDeploymentId
    if (!strategyId) {
      setValidationError('No strategy selected — cannot create a deployment.')
      return null
    }
    if (legsLoading) {
      setValidationError("Still loading this strategy's symbols — try again in a moment.")
      return null
    }
    if (legs.length === 0 || legs.some((l) => !l.symbol || !l.exchange)) {
      setValidationError(
        'This strategy has no symbol mappings configured yet. Add at least one symbol ' +
          '(Configure Symbols on the strategy card) before deploying — otherwise there is ' +
          'nothing for the deployment to trade.'
      )
      return null
    }
    setCreatingDraft(true)
    setValidationError(null)
    try {
      const csrfToken = await fetchCSRFToken()
      const res = await fetch('/api/v1/deployments', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify(buildDeploymentParams()),
      })
      const data = await res.json()
      if (data.status === 'error' || !data.id) {
        setValidationError(data.message || 'Failed to create deployment draft')
        return null
      }
      setDraftDeploymentId(data.id)
      return data.id
    } catch {
      setValidationError('Network error creating deployment draft')
      return null
    } finally {
      setCreatingDraft(false)
    }
  }

  const handleActivateClick = async () => {
    const deploymentId = draftDeploymentId ?? (await ensureDraftDeployment())
    if (!deploymentId) return
    setActivating(true)
    try {
      await onActivate(deploymentId)
    } finally {
      setActivating(false)
    }
  }

  if (!open) return null

  const tabs = ['General', 'Conditions', 'Risk', 'Execution', 'Review']

  return (
    <div className="fixed inset-y-0 right-0 w-[420px] bg-card border-l border-border shadow-2xl z-50 flex flex-col select-none text-foreground">
      {/* Header */}
      <div className="p-4 border-b border-border flex items-center justify-between bg-muted/20">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-violet-500" />
          <h2 className="text-base font-bold">Deploy Strategy</h2>
        </div>
        <button type="button" onClick={onClose} className="p-1 hover:bg-accent rounded">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-border text-xs font-semibold px-2 bg-muted/5">
        {tabs.map((tab) => (
          <button
            type="button"
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'flex-1 py-2 text-center border-b-2 -mb-[2px] transition',
              activeTab === tab
                ? 'border-primary text-primary font-bold'
                : 'border-transparent text-muted-foreground hover:text-foreground'
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Form Content */}
      <div className="flex-1 p-4 overflow-y-auto space-y-4 text-sm">
        {activeTab === 'General' && (
          <div className="space-y-3.5">
            <div>
              <label className="text-xs font-bold text-muted-foreground uppercase block mb-1">
                Strategy Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-3 py-2 rounded-md border border-border bg-background focus:ring-1 focus:ring-primary focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-muted-foreground uppercase block mb-1">
                Execution Mode
              </label>
              <div className="grid grid-cols-2 gap-2 bg-muted/40 p-1 rounded-lg border border-border/60">
                <button
                  type="button"
                  onClick={() => {
                    setExecutionMode('paper')
                    setSelectedBrokers(['Paper Trading'])
                  }}
                  className={`text-xs font-bold h-8 rounded-md transition-all ${
                    executionMode === 'paper'
                      ? 'bg-primary text-primary-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  Paper Trading
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setExecutionMode('live')
                    const firstBroker = connectedBrokers.length > 0 ? [connectedBrokers[0]] : []
                    setSelectedBrokers(firstBroker)
                  }}
                  className={`text-xs font-bold h-8 rounded-md transition-all ${
                    executionMode === 'live'
                      ? 'bg-primary text-primary-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  Live Trading
                </button>
              </div>
            </div>

            {executionMode === 'live' && (
              <div>
                <label className="text-xs font-bold text-muted-foreground uppercase block mb-2">
                  Select Active Brokers
                </label>
                <div className="space-y-1.5 border border-border rounded-md p-3 bg-background max-h-[140px] overflow-y-auto">
                  {connectedBrokers.length === 0 ? (
                    <div className="text-xs text-muted-foreground">
                      No active broker sessions connected.
                    </div>
                  ) : (
                    connectedBrokers.map((b) => {
                      const isChecked = selectedBrokers.includes(b)
                      return (
                        <label
                          key={b}
                          className="flex items-center gap-2 text-xs font-semibold cursor-pointer"
                        >
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => {
                              if (isChecked) {
                                setSelectedBrokers(selectedBrokers.filter((x) => x !== b))
                              } else {
                                setSelectedBrokers([
                                  ...selectedBrokers.filter((x) => x !== 'Paper Trading'),
                                  b,
                                ])
                              }
                            }}
                            className="rounded border-border bg-background text-primary focus:ring-primary h-3.5 w-3.5"
                          />
                          {b}
                        </label>
                      )
                    })
                  )}
                </div>
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-bold text-muted-foreground uppercase block mb-1">
                  Capital Allocation (₹)
                </label>
                <input
                  type="number"
                  value={capital}
                  onChange={(e) => setCapital(Number(e.target.value))}
                  className="w-full px-3 py-2 rounded-md border border-border bg-background focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-bold text-muted-foreground uppercase block mb-1">
                  Max Positions
                </label>
                <input
                  type="number"
                  value={maxPositions}
                  onChange={(e) => setMaxPositions(Number(e.target.value))}
                  className="w-full px-3 py-2 rounded-md border border-border bg-background focus:outline-none"
                />
              </div>
            </div>
          </div>
        )}

        {activeTab === 'Conditions' && (
          <div className="space-y-4">
            <div>
              <label className="text-xs font-bold text-muted-foreground uppercase block mb-2">
                Conditions (All must be true)
              </label>

              <div className="space-y-2">
                {conditions.map((cond, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-1.5 border border-border/60 bg-muted/10 p-2 rounded-md"
                  >
                    <select
                      value={cond.indicator}
                      onChange={(e) => handleUpdateCondition(idx, 'indicator', e.target.value)}
                      className="flex-1 text-xs px-1.5 py-1 border border-border bg-background rounded focus:outline-none"
                    >
                      <optgroup label="Price & Underlying">
                        <option value="Spot">Spot Price</option>
                        <option value="LTP">LTP</option>
                        <option value="Future">Future Price</option>
                      </optgroup>
                      <optgroup label="Trend">
                        <option value="EMA">EMA (20)</option>
                        <option value="SMA">SMA (50)</option>
                        <option value="VWAP">VWAP</option>
                        <option value="Supertrend">Supertrend</option>
                      </optgroup>
                      <optgroup label="Momentum">
                        <option value="RSI">RSI (14)</option>
                        <option value="MACD">MACD</option>
                        <option value="Stochastic">Stochastic</option>
                      </optgroup>
                      <optgroup label="Options & Greeks">
                        <option value="IV">IV</option>
                        <option value="Delta">Delta</option>
                        <option value="PCR">PCR</option>
                        <option value="OI">OI</option>
                      </optgroup>
                    </select>

                    <select
                      value={cond.condition}
                      onChange={(e) => handleUpdateCondition(idx, 'condition', e.target.value)}
                      className="text-xs px-1 py-1 border border-border bg-background rounded w-12 focus:outline-none"
                    >
                      <option>&lt;</option>
                      <option>&gt;</option>
                      <option>==</option>
                    </select>

                    <input
                      type="number"
                      value={cond.value}
                      onChange={(e) => handleUpdateCondition(idx, 'value', Number(e.target.value))}
                      className="text-xs px-1.5 py-1 border border-border bg-background rounded w-16 focus:outline-none"
                    />

                    <button
                      type="button"
                      onClick={() => handleRemoveCondition(idx)}
                      className="p-1 hover:bg-accent rounded text-loss"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
                {conditions.length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    No trigger conditions yet — this strategy runs on entry alone until you add one.
                  </p>
                )}
              </div>

              <button
                type="button"
                onClick={handleAddCondition}
                className="mt-3 flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
              >
                <Plus className="w-3.5 h-3.5" />
                Add Condition
              </button>
            </div>
          </div>
        )}

        {activeTab === 'Risk' && (
          <div className="grid grid-cols-2 gap-3.5">
            <div>
              <label className="text-xs font-bold text-muted-foreground uppercase block mb-1">
                Daily Loss Limit (₹)
              </label>
              <input
                type="number"
                value={dailyLoss}
                onChange={(e) => setDailyLoss(Number(e.target.value))}
                className="w-full px-3 py-2 rounded-md border border-border bg-background focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-muted-foreground uppercase block mb-1">
                Stop After Profit (₹)
              </label>
              <input
                type="number"
                value={stopAfterProfit}
                onChange={(e) => setStopAfterProfit(Number(e.target.value))}
                className="w-full px-3 py-2 rounded-md border border-border bg-background focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-muted-foreground uppercase block mb-1">
                Max Trades / Day
              </label>
              <input
                type="number"
                value={maxTrades}
                onChange={(e) => setMaxTrades(Number(e.target.value))}
                className="w-full px-3 py-2 rounded-md border border-border bg-background focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-muted-foreground uppercase block mb-1">
                Cooldown (min)
              </label>
              <input
                type="number"
                value={cooldown}
                onChange={(e) => setCooldown(Number(e.target.value))}
                className="w-full px-3 py-2 rounded-md border border-border bg-background focus:outline-none"
              />
            </div>
          </div>
        )}

        {activeTab === 'Execution' && (
          <div className="space-y-4">
            <div>
              <label className="text-xs font-bold text-muted-foreground uppercase block mb-2">
                Execution Mappings
              </label>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground block mb-0.5">Order Type</label>
                  <select
                    value={orderType}
                    onChange={(e) => setOrderType(e.target.value)}
                    className="w-full px-3 py-2 rounded-md border border-border bg-background focus:outline-none"
                  >
                    <option>Market</option>
                    <option>Limit</option>
                  </select>
                </div>

                <div>
                  <label className="text-xs text-muted-foreground block mb-0.5">Product Type</label>
                  <select
                    value={product}
                    onChange={(e) => setProduct(e.target.value)}
                    className="w-full px-3 py-2 rounded-md border border-border bg-background focus:outline-none"
                  >
                    <option>MIS</option>
                    <option>NRML</option>
                    <option>CNC</option>
                  </select>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'Review' && (
          <div className="space-y-4 flex flex-col h-full justify-between pb-2">
            <div className="border border-border rounded-lg bg-card p-4 space-y-3">
              <h3 className="text-sm font-bold">Deployment Summary</h3>
              <p className="text-xs text-muted-foreground">
                Review your deployment configuration before activating.
              </p>

              {validationError && (
                <div className="flex items-start gap-1.5 text-xs text-loss">
                  <XCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  <span>{validationError}</span>
                </div>
              )}

              <div className="space-y-2 text-xs border-t border-border/50 pt-3">
                <div className="grid grid-cols-2 gap-y-2 text-xs">
                  <span className="text-muted-foreground">Deployment Name:</span>
                  <span className="font-bold text-right truncate">{name}</span>

                  <span className="text-muted-foreground">Mode:</span>
                  <span className="font-bold text-right capitalize">{executionMode}</span>

                  <span className="text-muted-foreground">Target Broker:</span>
                  <span className="font-bold text-right truncate">
                    {selectedBrokers.join(', ')}
                  </span>

                  <span className="text-muted-foreground">Allocated Capital:</span>
                  <span className="font-bold text-right">₹{capital.toLocaleString()}</span>

                  <span className="text-muted-foreground">Order & Product:</span>
                  <span className="font-bold text-right">
                    {orderType} / {product}
                  </span>

                  <span className="text-muted-foreground">Max Daily Loss:</span>
                  <span className="font-bold text-right text-loss">
                    ₹{dailyLoss.toLocaleString()}
                  </span>

                  <span className="text-muted-foreground">Symbols:</span>
                  <span className="font-bold text-right truncate">
                    {legsLoading
                      ? 'Loading…'
                      : legs.length > 0
                        ? legs.map((l) => l.symbol).join(', ')
                        : 'None configured'}
                  </span>
                </div>
              </div>
            </div>

            <div className="pt-8 flex gap-2">
              <Button variant="outline" className="flex-1 text-xs font-bold" onClick={onClose}>
                Cancel
              </Button>
              <Button
                className="flex-1 text-xs font-bold bg-violet-600 hover:bg-violet-700 text-white"
                onClick={handleActivateClick}
                disabled={activating || creatingDraft}
              >
                {activating ? 'Deploying...' : creatingDraft ? 'Creating...' : 'Deploy Strategy'}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
