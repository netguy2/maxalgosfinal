import { ArrowLeft, Info, Webhook } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { chartinkApi } from '@/api/chartink'
import { strategyApi } from '@/api/strategy'
import { PageHeader } from '@/components/layout/PageHeader'
import { Alert, AlertDescription } from '@/components/ui/alert'
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
import { PLATFORMS, type Platform } from '@/types/strategy'
import { showToast } from '@/utils/toast'

// Sensible defaults so a connection can be created with just a name and a
// provider. Every field below is editable afterward from the connection's
// detail view — nothing here is a permanent choice.
const DEFAULTS = {
  strategy_type: 'intraday' as const,
  trading_mode: 'LONG' as const,
  start_time: '09:15',
  end_time: '15:00',
  squareoff_time: '15:15',
}

function ProviderInstructions({ provider }: { provider: Platform | '' }) {
  if (!provider) return null

  if (provider === 'chartink') {
    return (
      <Alert>
        <Info className="h-4 w-4" />
        <AlertDescription>
          <p className="font-medium mb-2">Chartink Setup</p>
          <ol className="list-decimal list-inside space-y-1 text-sm">
            <li>Copy the webhook URL after creating this connection.</li>
            <li>Paste it into your Chartink screener's alert settings.</li>
            <li>
              Include <code className="bg-muted px-1 rounded">BUY</code>,{' '}
              <code className="bg-muted px-1 rounded">SELL</code>,{' '}
              <code className="bg-muted px-1 rounded">SHORT</code>, or{' '}
              <code className="bg-muted px-1 rounded">COVER</code> in the alert name.
            </li>
            <li>
              Map screener symbols to broker symbols from the connection's Configure Symbols page.
            </li>
          </ol>
        </AlertDescription>
      </Alert>
    )
  }

  if (provider === 'tradingview') {
    return (
      <Alert>
        <Info className="h-4 w-4" />
        <AlertDescription>
          <p className="font-medium mb-2">TradingView Setup</p>
          <ol className="list-decimal list-inside space-y-1 text-sm">
            <li>Copy the webhook URL after creating this connection.</li>
            <li>Paste it into your TradingView alert's webhook field.</li>
            <li>
              Use this JSON as the alert message:
              <pre className="mt-1 p-2 bg-muted rounded text-xs font-mono overflow-x-auto">{`{
  "signal": "BUY"
}`}</pre>
            </li>
            <li>Map action → instrument from the connection's Configure Symbols page.</li>
          </ol>
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <Alert>
      <Info className="h-4 w-4" />
      <AlertDescription>
        <p className="font-medium mb-2">Webhook Setup</p>
        <ol className="list-decimal list-inside space-y-1 text-sm">
          <li>Copy the webhook URL after creating this connection.</li>
          <li>
            POST this JSON to it:
            <pre className="mt-1 p-2 bg-muted rounded text-xs font-mono overflow-x-auto">{`{
  "signal": "BUY"
}`}</pre>
          </li>
          <li>Map action → instrument from the connection's Configure Symbols page.</li>
        </ol>
      </AlertDescription>
    </Alert>
  )
}

export default function NewMaxHookConnection() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [name, setName] = useState('')
  const [provider, setProvider] = useState<Platform | ''>('')
  const [errors, setErrors] = useState<Record<string, string>>({})

  const [strategyType, setStrategyType] = useState<'intraday' | 'positional'>(
    DEFAULTS.strategy_type
  )
  const [startTime, setStartTime] = useState(DEFAULTS.start_time)
  const [endTime, setEndTime] = useState(DEFAULTS.end_time)
  const [squareoffTime, setSquareoffTime] = useState(DEFAULTS.squareoff_time)
  const [selectedBrokers, setSelectedBrokers] = useState<string[]>(['Paper Trading'])
  const [connectedBrokers, setConnectedBrokers] = useState<string[]>([])

  useEffect(() => {
    const fetchBrokers = async () => {
      try {
        const response = await fetch('/api/broker/connections')
        if (!response.ok) return
        const data = await response.json()
        if (data.status !== 'success') return
        const connected = (data.connections || [])
          .filter((c: { connected: boolean }) => c.connected)
          .map((c: { broker: string }) => c.broker)
        setConnectedBrokers(connected)
        if (connected.length > 0) setSelectedBrokers([connected[0]])
      } catch {
        /* keep Paper Trading default */
      }
    }
    fetchBrokers()
  }, [])

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) {
      newErrors.name = 'Connection name is required'
    } else if (name.length < 3 || name.length > 50) {
      newErrors.name = 'Name must be between 3 and 50 characters'
    } else if (!/^[a-zA-Z0-9\s\-_]+$/.test(name)) {
      newErrors.name = 'Name can only contain letters, numbers, spaces, hyphens, and underscores'
    }
    if (!provider) {
      newErrors.provider = 'Please select a signal provider'
    }
    if (strategyType === 'intraday') {
      if (startTime >= endTime) {
        newErrors.time = 'Start time must be before end time'
      } else if (endTime >= squareoffTime) {
        newErrors.time = 'End time must be before square off time'
      }
    }
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) {
      showToast.error('Please fix the form errors', 'maxhook')
      return
    }

    setLoading(true)
    try {
      if (provider === 'chartink') {
        const response = await chartinkApi.createStrategy({
          name,
          strategy_type: strategyType,
          ...(strategyType === 'intraday' && {
            start_time: startTime,
            end_time: endTime,
            squareoff_time: squareoffTime,
          }),
        })
        if (response.status === 'success' && response.data?.strategy_id) {
          showToast.success('Connection created', 'maxhook')
          navigate(`/maxhook/chartink-${response.data.strategy_id}`)
        } else {
          showToast.error(response.message || 'Failed to create connection', 'maxhook')
        }
        return
      }

      const response = await strategyApi.createStrategy({
        name,
        platform: provider,
        // Tags this row as MaxHook-created so My Strategies (StrategyIndex)
        // can exclude it -- without this it's an ordinary Strategy row
        // indistinguishable from one created via My Strategies directly.
        signal_source: 'MaxHook',
        strategy_type: strategyType,
        // Direction (LONG/SHORT/BOTH) is now configured per-symbol on the
        // Configure Symbols page via each mapping's React-to-Signal
        // trigger, not once for the whole connection -- BOTH here just
        // keeps the connection itself unrestricted so every symbol's own
        // trigger setting is what actually governs behavior.
        trading_mode: 'BOTH',
        brokers: selectedBrokers.join(','),
        ...(strategyType === 'intraday' && {
          start_time: startTime,
          end_time: endTime,
          squareoff_time: squareoffTime,
        }),
      })
      if (response.status === 'success' && response.data?.strategy_id) {
        showToast.success('Connection created', 'maxhook')
        navigate(`/maxhook/strategy-${response.data.strategy_id}`)
      } else {
        showToast.error(response.message || 'Failed to create connection', 'maxhook')
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Failed to create connection'
      showToast.error(message, 'maxhook')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="container mx-auto py-6 max-w-2xl space-y-6">
      <Button variant="ghost" asChild>
        <Link to="/maxhook">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to MaxHook
        </Link>
      </Button>

      <PageHeader
        title="New Connection"
        description="Receive trading signals from an external platform."
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Webhook className="h-5 w-5" />
            Connection Details
          </CardTitle>
          <CardDescription>Name it, pick a provider, and you're ready.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="name">Connection Name</Label>
              <Input
                id="name"
                placeholder="e.g. Nifty Breakout"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={errors.name ? 'border-loss' : ''}
              />
              {errors.name && <p className="text-sm text-loss">{errors.name}</p>}
            </div>

            <div className="space-y-2">
              <Label htmlFor="provider">Signal Provider</Label>
              <Select value={provider} onValueChange={(v) => setProvider(v as Platform)}>
                <SelectTrigger className={errors.provider ? 'border-loss' : ''}>
                  <SelectValue placeholder="Select a provider" />
                </SelectTrigger>
                <SelectContent>
                  {PLATFORMS.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {errors.provider && <p className="text-sm text-loss">{errors.provider}</p>}
            </div>

            <ProviderInstructions provider={provider} />

            {/* Flattened onto a single page (no collapsible) -- trading
                direction is no longer configured here at all: it's set
                per-symbol on the Configure Symbols page via each
                mapping's React-to-Signal trigger. */}
            <div className="space-y-6 pt-2">
              <div className="space-y-2">
                <Label>Strategy Type</Label>
                <Select
                  value={strategyType}
                  onValueChange={(v) => setStrategyType(v as 'intraday' | 'positional')}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="intraday">Intraday</SelectItem>
                    <SelectItem value="positional">Positional</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Intraday connections have trading hours and auto square-off.
                </p>
              </div>

              {provider !== 'chartink' && (
                <div className="space-y-2">
                  <Label>Brokers</Label>
                  <div className="space-y-1.5 border border-border rounded-md p-3 bg-muted/30 max-h-[140px] overflow-y-auto">
                    {connectedBrokers.map((b) => {
                      const isChecked = selectedBrokers.includes(b)
                      return (
                        <label
                          key={b}
                          className="flex items-center gap-2 text-xs font-semibold cursor-pointer text-foreground"
                        >
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() =>
                              setSelectedBrokers(
                                isChecked
                                  ? selectedBrokers.filter((x) => x !== b)
                                  : [...selectedBrokers, b]
                              )
                            }
                            className="rounded border-border bg-background text-primary focus:ring-primary h-3.5 w-3.5"
                          />
                          {b}
                        </label>
                      )
                    })}
                    <label className="flex items-center gap-2 text-xs font-semibold cursor-pointer text-foreground">
                      <input
                        type="checkbox"
                        checked={selectedBrokers.includes('Paper Trading')}
                        onChange={() =>
                          setSelectedBrokers(
                            selectedBrokers.includes('Paper Trading')
                              ? selectedBrokers.filter((x) => x !== 'Paper Trading')
                              : [...selectedBrokers, 'Paper Trading']
                          )
                        }
                        className="rounded border-border bg-background text-primary focus:ring-primary h-3.5 w-3.5"
                      />
                      Paper Trading
                    </label>
                  </div>
                </div>
              )}

              {strategyType === 'intraday' && (
                <div className="space-y-4 p-4 border rounded-lg bg-muted/50">
                  <h4 className="font-medium text-sm">Trading Hours</h4>
                  <div className="grid grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="start_time">Start</Label>
                      <Input
                        id="start_time"
                        type="time"
                        value={startTime}
                        onChange={(e) => setStartTime(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="end_time">End</Label>
                      <Input
                        id="end_time"
                        type="time"
                        value={endTime}
                        onChange={(e) => setEndTime(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="squareoff_time">Square Off</Label>
                      <Input
                        id="squareoff_time"
                        type="time"
                        value={squareoffTime}
                        onChange={(e) => setSquareoffTime(e.target.value)}
                      />
                    </div>
                  </div>
                  {errors.time && <p className="text-sm text-loss">{errors.time}</p>}
                </div>
              )}
            </div>

            <div className="flex gap-3 pt-2">
              <Button
                type="button"
                variant="outline"
                className="flex-1"
                onClick={() => navigate('/maxhook')}
              >
                Cancel
              </Button>
              <Button type="submit" className="flex-1" disabled={loading}>
                {loading ? 'Creating...' : 'Create Connection'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
