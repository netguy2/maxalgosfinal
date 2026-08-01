import { AlertCircle, ArrowLeft, CheckCircle2, PlayCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
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
  const [broker, setBroker] = useState('Paper Trading')

  const [validating, setValidating] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [wouldTrigger, setWouldTrigger] = useState<boolean | null>(null)
  const [saving, setSaving] = useState(false)

  const selectedSymbol = SYMBOL_OPTIONS.find((s) => s.value === symbolValue) ?? SYMBOL_OPTIONS[0]

  useEffect(() => {
    strategyApi
      .listIndicators()
      .then((res) => setIndicators(res.indicators ?? []))
      .catch(() => showToast.error('Failed to load indicator list', 'strategy'))
  }, [])

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

      // Deployment (broker/capital/risk_params) stays on the existing
      // generic deploy path -- same raw-fetch + CSRF pattern
      // StrategyConfigurator.tsx's final step already uses, since there is
      // no dedicated deploymentsApi wrapper for this endpoint yet.
      const csrfToken = await fetchCSRFToken()
      const deployRes = await fetch('/api/v1/deployments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({
          strategy_id: createRes.strategy_id,
          name: `${name} (Active)`,
          brokers: [broker],
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
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Capital</Label>
            <Input type="number" value={capital} onChange={(e) => setCapital(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label>Broker</Label>
            <Input
              value={broker}
              onChange={(e) => setBroker(e.target.value)}
              placeholder="Paper Trading"
            />
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
