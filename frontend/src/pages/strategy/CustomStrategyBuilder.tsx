import { AlertCircle, ArrowLeft, CheckCircle2, PlayCircle, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { fetchCSRFToken } from '@/api/client'
import { strategyApi } from '@/api/strategy'
import type { GroupNode, IndicatorOption } from '@/components/strategy/ConditionTreeEditor'
import { ConditionTreeEditor } from '@/components/strategy/ConditionTreeEditor'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { SYMBOL_OPTIONS } from '@/lib/symbol-options'
import { showToast } from '@/utils/toast'

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

const DEFAULT_TREE: GroupNode = {
  operator: 'AND',
  children: [{ indicator: 'RSI', condition: '>', value: 60, period: 14 }],
}

const DEFAULT_EXIT_TREE: GroupNode = {
  operator: 'OR',
  children: [{ indicator: 'RSI', condition: '<', value: 40, period: 14 }],
}

/** No-code custom strategy builder -- Tradetron-style condition tree.
 * Reuses services/condition_engine.py::evaluate_conditions_tree as its
 * interpreter (via services/condition_tree_validator.py server-side) and
 * the generic deploy path (blueprints/deployments.py::create_new_deployment),
 * exactly like the wizard (StrategyConfigurator.tsx) does -- the only
 * difference is entry/exit rules are a hand-authored AND/OR tree instead
 * of one of the 26 fixed wizard blueprints. */
export default function CustomStrategyBuilder() {
  const navigate = useNavigate()

  const [indicators, setIndicators] = useState<IndicatorOption[]>([])
  const [name, setName] = useState('My Custom Strategy')
  const [symbolValue, setSymbolValue] = useState(SYMBOL_OPTIONS[0].value)
  const [entryTree, setEntryTree] = useState<GroupNode>(DEFAULT_TREE)
  const [useExitTree, setUseExitTree] = useState(false)
  const [exitTree, setExitTree] = useState<GroupNode>(DEFAULT_EXIT_TREE)
  const [stopLossPct, setStopLossPct] = useState('2')
  const [targetPct, setTargetPct] = useState('4')
  const [quantity, setQuantity] = useState('1')
  const [capital, setCapital] = useState('100000')

  // Execution & Broker State
  const [executionMode, setExecutionMode] = useState<'live' | 'paper'>('paper')
  const [selectedBrokers, setSelectedBrokers] = useState<string[]>([])
  const [connectedBrokers, setConnectedBrokers] = useState<string[]>([])
  const [loadingBrokers, setLoadingBrokers] = useState(false)

  const [validating, setValidating] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [wouldTrigger, setWouldTrigger] = useState<boolean | null>(null)
  const [saving, setSaving] = useState(false)

  const selectedSymbol = SYMBOL_OPTIONS.find((s) => s.value === symbolValue) ?? SYMBOL_OPTIONS[0]

  const toggleBroker = (broker: string) => {
    setSelectedBrokers((prev) =>
      prev.includes(broker) ? prev.filter((b) => b !== broker) : [...prev, broker]
    )
  }

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
        const stillValid = prev.filter((b) => connected.includes(b))
        if (stillValid.length > 0) return stillValid
        if (prev.length === 0 && connected.length > 0) return [connected[0]]
        return stillValid
      })
    } catch {
      /* ignore */
    } finally {
      setLoadingBrokers(false)
    }
  }, [])

  useEffect(() => {
    strategyApi
      .listIndicators()
      .then((res) => setIndicators(res.indicators ?? []))
      .catch(() => showToast.error('Failed to load indicator list', 'strategy'))

    loadConnectedBrokers()
  }, [loadConnectedBrokers])

  useEffect(() => {
    if (executionMode === 'live') {
      loadConnectedBrokers()
    }
  }, [executionMode, loadConnectedBrokers])

  const handleTestConditions = async () => {
    setValidating(true)
    setValidationError(null)
    setWouldTrigger(null)
    try {
      const res = await strategyApi.validateCustomStrategy({
        conditions_tree: entryTree,
        symbol: selectedSymbol.value,
        exchange: selectedSymbol.exchange,
      })
      if (res.status === 'success') {
        setWouldTrigger(res.would_trigger ?? null)
      } else {
        setValidationError(res.message || 'Validation failed')
      }
    } catch (err) {
      const message =
        (err as { response?: { data?: { message?: string } } })?.response?.data?.message ||
        'Validation failed'
      setValidationError(message)
    } finally {
      setValidating(false)
    }
  }

  const handleSaveAndDeploy = async () => {
    if (executionMode === 'live' && selectedBrokers.length === 0) {
      showToast.error(
        'No broker connected -- connect one in Broker Management before deploying live.',
        'strategy'
      )
      return
    }

    setSaving(true)
    try {
      const createRes = await strategyApi.createCustomStrategy({
        name,
        symbol: selectedSymbol.value,
        exchange: selectedSymbol.exchange,
        conditions_tree: entryTree,
        exit_conditions_tree: useExitTree ? exitTree : undefined,
        stop_loss_pct: stopLossPct ? Number(stopLossPct) : undefined,
        target_pct: targetPct ? Number(targetPct) : undefined,
        quantity: quantity ? Number(quantity) : undefined,
      })

      if (createRes.status !== 'success' || !createRes.strategy_id) {
        showToast.error(createRes.message || 'Failed to save strategy', 'strategy')
        return
      }

      const csrfToken = await fetchCSRFToken()
      const deployRes = await fetch('/api/v1/deployments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({
          strategy_id: createRes.strategy_id,
          name: `${name} (Active)`,
          brokers: executionMode === 'paper' ? ['Paper Trading'] : selectedBrokers,
          capital: Number(capital),
          max_positions: 1,
          order_type: 'Market',
          product: 'MIS',
          trigger_type: 'On Conditions',
          deploy_now: true,
          template_id: 'custom_builder',
        }),
      })
      const deployData = await deployRes.json()
      if (deployData.id) {
        await fetch(`/api/v1/deployments/${deployData.id}/resume`, {
          method: 'POST',
          headers: { 'X-CSRFToken': csrfToken },
        })
        showToast.success(`Custom strategy "${name}" saved & deployed!`, 'strategy')
        navigate('/deployments')
        return
      }

      showToast.error(deployData?.message || 'Strategy saved, but deployment failed.', 'strategy')
      navigate('/strategy')
    } catch (err) {
      const message =
        (err as { response?: { data?: { message?: string } } })?.response?.data?.message ||
        'Failed to save strategy'
      showToast.error(message, 'strategy')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-background p-4 md:p-8 space-y-6 max-w-5xl mx-auto pb-24">
      <Button variant="ghost" asChild>
        <Link to="/strategy/new">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back
        </Link>
      </Button>

      <div>
        <h1 className="text-2xl font-bold tracking-tight">Build a Custom Strategy</h1>
        <p className="text-muted-foreground">
          Design entry/exit condition trees over live indicators -- no template required.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Strategy & Market</CardTitle>
          <CardDescription>Name this strategy and pick the symbol it trades.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Strategy Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>Symbol</Label>
            <Select value={symbolValue} onValueChange={setSymbolValue}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SYMBOL_OPTIONS.map((s) => (
                  <SelectItem key={s.value} value={s.value}>
                    {s.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Entry Conditions</CardTitle>
          <CardDescription>All groups/conditions here gate strategy entry.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <ConditionTreeEditor value={entryTree} onChange={setEntryTree} indicators={indicators} />
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="outline"
              onClick={handleTestConditions}
              disabled={validating}
            >
              <PlayCircle className="h-4 w-4 mr-2" />
              {validating ? 'Testing...' : 'Test Conditions Now'}
            </Button>
            {wouldTrigger !== null && (
              <Badge
                className={
                  wouldTrigger
                    ? 'bg-profit/10 text-profit border-none'
                    : 'bg-muted text-muted-foreground border-none'
                }
              >
                {wouldTrigger ? 'Would trigger right now' : 'Would not trigger right now'}
              </Badge>
            )}
            {validationError && (
              <span className="flex items-center gap-1 text-sm text-destructive">
                <AlertCircle className="h-4 w-4" /> {validationError}
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Exit Conditions (optional)</CardTitle>
              <CardDescription>Leave off to exit purely on stop-loss/target below.</CardDescription>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setUseExitTree((v) => !v)}
            >
              {useExitTree ? 'Remove exit tree' : 'Add exit tree'}
            </Button>
          </div>
        </CardHeader>
        {useExitTree && (
          <CardContent>
            <ConditionTreeEditor value={exitTree} onChange={setExitTree} indicators={indicators} />
          </CardContent>
        )}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Risk & Sizing</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label>Stop Loss %</Label>
            <Input
              type="number"
              value={stopLossPct}
              onChange={(e) => setStopLossPct(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Target %</Label>
            <Input type="number" value={targetPct} onChange={(e) => setTargetPct(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>Quantity</Label>
            <Input type="number" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Execution & Broker</CardTitle>
          <CardDescription>Select execution mode and connect to your live broker.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>Execution Mode</Label>
              <Select
                value={executionMode}
                onValueChange={(val) => setExecutionMode(val as 'live' | 'paper')}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="paper">Paper Trading (Simulated)</SelectItem>
                  <SelectItem value="live">Live Broker Mode</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label>Capital (₹)</Label>
              <Input type="number" value={capital} onChange={(e) => setCapital(e.target.value)} />
            </div>
          </div>

          <div className="space-y-2 pt-2 border-t border-border/50">
            <div className="flex items-center justify-between">
              <Label>Connected Broker{selectedBrokers.length > 1 ? 's' : ''}</Label>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={loadConnectedBrokers}
                disabled={loadingBrokers}
                className="h-6 text-xs text-primary hover:underline px-1"
              >
                <RefreshCw className={`h-3 w-3 mr-1 ${loadingBrokers ? 'animate-spin' : ''}`} />
                {loadingBrokers ? 'Checking...' : 'Refresh'}
              </Button>
            </div>

            {connectedBrokers.length === 0 ? (
              <div className="p-3 rounded-md border border-dashed border-border bg-muted/30 text-xs text-muted-foreground flex items-center justify-between">
                <span>No live broker connected</span>
                <Link to="/brokers" className="text-primary font-semibold hover:underline">
                  Connect Broker →
                </Link>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {connectedBrokers.map((b) => {
                  const active = selectedBrokers.includes(b)
                  return (
                    <Button
                      key={b}
                      type="button"
                      variant={active ? 'default' : 'outline'}
                      size="sm"
                      disabled={executionMode === 'paper'}
                      onClick={() => toggleBroker(b)}
                      className="h-8 text-xs font-semibold"
                    >
                      {active ? '✓ ' : ''}
                      {BROKER_DISPLAY_NAMES[b] ?? b}
                    </Button>
                  )
                })}
              </div>
            )}

            {executionMode === 'live' && connectedBrokers.length === 0 && (
              <p className="text-xs text-destructive font-medium flex items-center gap-1 mt-1">
                <AlertCircle className="h-3.5 w-3.5" />
                No broker connected -- please connect one in Broker Management before deploying
                live.
              </p>
            )}

            {executionMode === 'live' &&
              connectedBrokers.length > 0 &&
              selectedBrokers.length === 0 && (
                <p className="text-xs text-destructive font-medium flex items-center gap-1 mt-1">
                  <AlertCircle className="h-3.5 w-3.5" />
                  Select at least one broker to deploy live.
                </p>
              )}
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-end gap-3">
        <Button variant="outline" onClick={() => navigate('/strategy')}>
          Cancel
        </Button>
        <Button onClick={handleSaveAndDeploy} disabled={saving}>
          <CheckCircle2 className="h-4 w-4 mr-2" />
          {saving ? 'Saving...' : 'Save & Deploy'}
        </Button>
      </div>
    </div>
  )
}
