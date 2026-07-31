import { ArrowLeft, Clock, FileCode, Info, Sparkles, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { pythonStrategyApi } from '@/api/python-strategy'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { CATALOG } from '@/lib/marketplace-catalog'
import { generatePythonStrategy } from '@/lib/python-strategy-generator'
import { CRYPTO_EXCHANGE_VALUE, SCHEDULE_DAYS, STRATEGY_EXCHANGES } from '@/types/python-strategy'
import { showToast } from '@/utils/toast'

const EXAMPLE_STRATEGY = `"""
Example Max Algos Strategy
This is a minimal example showing how to use the Max Algos Python SDK.

NOTE: The maxalgos SDK is bundled with Max Algos — no pip install required.
MAX_ALGOS_API_KEY, HOST_SERVER, and WEBSOCKET_URL are injected automatically
when this script is launched via the /python runner.
"""

import os
import time
from maxalgos import api

# Get credentials from environment (auto-injected by the /python runner)
API_KEY = os.getenv('MAX_ALGOS_API_KEY')
HOST    = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')

# Initialize the SDK client
client = api(
    api_key=API_KEY,
    host=HOST,
)

def main():
    """Main strategy logic"""
    print("Strategy started")

    # Example: Get Last Traded Price for a symbol
    ltp = client.ltp("NHPC", "NSE")
    print(f"NHPC LTP: {ltp}")

    # Your trading logic here
    while True:
        # Check market conditions
        # Place orders based on your strategy
        # Example: client.placeorder(strategy="MyStrategy", symbol="NHPC",
        #          action="BUY", exchange="NSE", quantity=1)
        time.sleep(60)  # Check every minute

if __name__ == "__main__":
    main()
`

export default function NewPythonStrategy() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Marketplace template clone: resolve the catalog item and generate a real,
  // working Python file for it (genuine indicator math — see
  // lib/python-strategy-generator.ts). The generated source is editable
  // before upload, same as any hand-written script.
  const templateId = searchParams.get('template')
  const template = templateId ? CATALOG.find((c) => c.id === templateId) : undefined
  const [generatedSource, setGeneratedSource] = useState<string | null>(null)

  const [name, setName] = useState(template ? template.name : '')
  const [file, setFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [showExample, setShowExample] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Exchange drives the holiday/session calendar
  const [exchange, setExchange] = useState<string>('NSE')

  // Generate the template's Python source once on mount and pre-attach it as
  // the upload file, so the strategy is genuinely functional immediately —
  // the user can still edit the generated code before submitting.
  // biome-ignore lint/correctness/useExhaustiveDependencies: must run exactly once on mount; template is derived from the URL and stable for the page's lifetime
  useEffect(() => {
    if (!template?.signalId) return
    const { fileName, source } = generatePythonStrategy(
      template.signalId,
      template.name,
      template.description
    )
    setGeneratedSource(source)
    setFile(new File([source], fileName, { type: 'text/x-python' }))
  }, [])

  // Schedule fields with defaults (Mon-Fri, 9:00 AM - 4:00 PM IST)
  const [startTime, setStartTime] = useState('09:00')
  const [stopTime, setStopTime] = useState('16:00')
  const [selectedDays, setSelectedDays] = useState<string[]>(['mon', 'tue', 'wed', 'thu', 'fri'])

  // Brokers this strategy is allowed to trade on -- informational only
  // (the script itself picks a broker per-order via placeorder(broker=...),
  // this list is exposed to it as MAX_ALGOS_BROKERS so it doesn't need to
  // hardcode broker names). Multiple can be selected since one script may
  // fan out orders across several connected brokers.
  const [connectedBrokers, setConnectedBrokers] = useState<string[]>([])
  const [selectedBrokers, setSelectedBrokers] = useState<string[]>([])

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
        /* leave selection empty -- strategy still works via the default broker */
      }
    }
    fetchBrokers()
  }, [])

  const toggleBroker = (broker: string) => {
    setSelectedBrokers((prev) =>
      prev.includes(broker) ? prev.filter((b) => b !== broker) : [...prev, broker]
    )
  }

  const isCrypto = exchange === CRYPTO_EXCHANGE_VALUE

  // When exchange changes, apply sensible defaults (idempotent for explicit edits)
  const handleExchangeChange = (value: string) => {
    setExchange(value)
    if (value === CRYPTO_EXCHANGE_VALUE) {
      // CRYPTO: 24/7, all days
      setStartTime('00:00')
      setStopTime('23:59')
      setSelectedDays(['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'])
    } else if (value === 'MCX') {
      // MCX: full session including evening
      setStartTime('09:00')
      setStopTime('23:55')
      setSelectedDays(['mon', 'tue', 'wed', 'thu', 'fri'])
    } else {
      // NSE/BSE/NFO/BFO equity defaults
      setStartTime('09:15')
      setStopTime('15:30')
      setSelectedDays(['mon', 'tue', 'wed', 'thu', 'fri'])
    }
  }

  const handleDayToggle = (day: string) => {
    setSelectedDays((prev) => (prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day]))
  }

  const validateForm = () => {
    const newErrors: Record<string, string> = {}

    if (!name.trim()) {
      newErrors.name = 'Strategy name is required'
    } else if (name.length < 3 || name.length > 50) {
      newErrors.name = 'Name must be between 3 and 50 characters'
    } else if (!/^[a-zA-Z0-9\s\-_]+$/.test(name)) {
      newErrors.name = 'Name can only contain letters, numbers, spaces, hyphens, and underscores'
    }

    if (!file) {
      newErrors.file = 'Please select a Python file'
    } else if (!file.name.endsWith('.py')) {
      newErrors.file = 'File must be a Python file (.py)'
    }

    // Schedule validation
    if (!startTime) {
      newErrors.startTime = 'Start time is required'
    }
    if (!stopTime) {
      newErrors.stopTime = 'Stop time is required'
    }
    if (selectedDays.length === 0) {
      newErrors.days = 'Select at least one day'
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      // Validate file extension
      if (!selectedFile.name.endsWith('.py')) {
        showToast.error('Please select a Python file (.py)', 'pythonStrategy')
        return
      }
      // Validate file size (max 1MB for Python scripts)
      const maxSizeBytes = 1024 * 1024 // 1MB
      if (selectedFile.size > maxSizeBytes) {
        showToast.error('File size must be less than 1MB', 'pythonStrategy')
        return
      }
      setFile(selectedFile)
      // Auto-fill name from file name if empty
      if (!name) {
        const baseName = selectedFile.name.replace('.py', '').replace(/_/g, ' ')
        setName(baseName.charAt(0).toUpperCase() + baseName.slice(1))
      }
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!validateForm()) {
      showToast.error('Please fix the form errors', 'pythonStrategy')
      return
    }

    try {
      setLoading(true)
      // Upload strategy with schedule (schedule is mandatory)
      const response = await pythonStrategyApi.uploadStrategy(name, file!, {
        start_time: startTime,
        stop_time: stopTime,
        days: selectedDays,
        exchange,
        brokers: selectedBrokers,
      })

      if (response.status === 'success') {
        showToast.success('Strategy uploaded with schedule', 'pythonStrategy')
        navigate('/python')
      } else {
        showToast.error(response.message || 'Failed to upload strategy', 'pythonStrategy')
      }
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to upload strategy'
      showToast.error(errorMessage, 'pythonStrategy')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="container mx-auto py-6 max-w-2xl space-y-6">
      {/* Back Button */}
      <Button variant="ghost" asChild>
        <Link to="/python">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Python Strategies
        </Link>
      </Button>

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Add Python Strategy</h1>
        <p className="text-muted-foreground">
          Upload a Python script to run as an automated trading strategy
        </p>
      </div>

      {template && generatedSource && (
        <Alert>
          <Sparkles className="h-4 w-4" />
          <AlertDescription>
            Generated a real, working strategy for <strong>{template.name}</strong> — genuine
            indicator math and order placement, ready to run. Review the code below, tune the
            parameters at the top, then upload.
          </AlertDescription>
        </Alert>
      )}

      {/* Requirements Info */}
      <Alert>
        <Info className="h-4 w-4" />
        <AlertDescription>
          Your Python script should use the <code className="bg-muted px-1 rounded">maxalgos</code>{' '}
          SDK. Install it with: <code className="bg-muted px-1 rounded">pip install maxalgos</code>
        </AlertDescription>
      </Alert>

      {/* Generated strategy preview/editor */}
      {generatedSource && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <FileCode className="h-5 w-5" />
              Generated Strategy Code
            </CardTitle>
            <CardDescription>
              Edit freely — your changes are uploaded as the strategy file.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <textarea
              value={generatedSource}
              onChange={(e) => {
                const source = e.target.value
                setGeneratedSource(source)
                const fileName = file?.name || 'strategy.py'
                setFile(new File([source], fileName, { type: 'text/x-python' }))
              }}
              spellCheck={false}
              className="w-full h-96 font-mono text-xs p-3 border border-border rounded-md bg-muted/30 focus:outline-none focus:ring-2 focus:ring-primary resize-y"
            />
          </CardContent>
        </Card>
      )}

      {/* Form */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Upload className="h-5 w-5" />
            Upload Strategy
          </CardTitle>
          <CardDescription>Select your Python script file and give it a name</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Strategy Name */}
            <div className="space-y-2">
              <Label htmlFor="name">Strategy Name</Label>
              <Input
                id="name"
                placeholder="My Trading Strategy"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={errors.name ? 'border-loss' : ''}
              />
              {errors.name && <p className="text-sm text-loss">{errors.name}</p>}
              <p className="text-xs text-muted-foreground">A descriptive name for your strategy</p>
            </div>

            {/* File Upload */}
            <div className="space-y-2">
              <Label htmlFor="file">Python Script</Label>
              <div
                className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer hover:border-primary transition-colors ${
                  errors.file ? 'border-loss' : ''
                }`}
                onClick={() => fileInputRef.current?.click()}
              >
                <input
                  ref={fileInputRef}
                  id="file"
                  type="file"
                  accept=".py"
                  className="hidden"
                  onChange={handleFileChange}
                />
                {file ? (
                  <div className="flex items-center justify-center gap-2">
                    <FileCode className="h-8 w-8 text-profit" />
                    <div className="text-left">
                      <p className="font-medium">{file.name}</p>
                      <p className="text-sm text-muted-foreground">
                        {(file.size / 1024).toFixed(2)} KB
                      </p>
                    </div>
                  </div>
                ) : (
                  <div>
                    <Upload className="h-8 w-8 mx-auto text-muted-foreground mb-2" />
                    <p className="text-sm text-muted-foreground">
                      Click to select a Python file (.py)
                    </p>
                    <p className="text-xs text-muted-foreground mt-1">Maximum file size: 1MB</p>
                  </div>
                )}
              </div>
              {errors.file && <p className="text-sm text-loss">{errors.file}</p>}
            </div>

            {/* Exchange Section */}
            <div className="space-y-2 border-t pt-6">
              <Label htmlFor="exchange">Exchange</Label>
              <select
                id="exchange"
                value={exchange}
                onChange={(e) => handleExchangeChange(e.target.value)}
                className="w-full px-3 py-2 text-sm border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-primary"
              >
                {STRATEGY_EXCHANGES.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">
                Drives the holiday calendar and effective trading window for this strategy. Each
                exchange has its own holiday list and per-date session timings (e.g. MCX may run a
                partial 17:00-23:55 session on a date when NSE/BSE are fully closed — the host
                follows whatever the calendar DB says, not a hardcoded "evening" rule). CRYPTO
                ignores holidays entirely.
              </p>
            </div>

            {/* Brokers Section */}
            <div className="space-y-2 border-t pt-6">
              <Label>Brokers</Label>
              {connectedBrokers.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No connected brokers found. Connect one from Broker Management, or the strategy
                  will use your account's default broker.
                </p>
              ) : (
                <div className="space-y-1.5 border border-border rounded-md p-3 bg-muted/30 max-h-[140px] overflow-y-auto">
                  {connectedBrokers.map((b) => (
                    <label
                      key={b}
                      className="flex items-center gap-2 text-xs font-semibold cursor-pointer text-foreground"
                    >
                      <input
                        type="checkbox"
                        checked={selectedBrokers.includes(b)}
                        onChange={() => toggleBroker(b)}
                        className="rounded border-border bg-background text-primary focus:ring-primary h-3.5 w-3.5"
                      />
                      {b}
                    </label>
                  ))}
                </div>
              )}
              <p className="text-xs text-muted-foreground">
                Select every broker this script may trade on. It's informational for the
                script — call{' '}
                <code className="bg-muted px-1 rounded">
                  client.placeorder(..., broker="brokername")
                </code>{' '}
                to route a specific order to one of them; omit it to use your account's default
                broker. Selecting multiple lets one script fan out across several brokers.
              </p>
            </div>

            {/* Schedule Section */}
            <div className="space-y-4 border-t pt-6">
              <div className="flex items-center gap-2">
                <Clock className="h-5 w-5 text-muted-foreground" />
                <h3 className="font-medium">Schedule</h3>
              </div>
              <p className="text-sm text-muted-foreground">
                {isCrypto
                  ? 'CRYPTO runs 24/7. The schedule below limits when this script is allowed to run.'
                  : 'Configure when this strategy should run. All times are in IST.'}
              </p>

              {/* Time Inputs */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="startTime">Start Time (IST)</Label>
                  <Input
                    id="startTime"
                    type="time"
                    value={startTime}
                    onChange={(e) => setStartTime(e.target.value)}
                    className={errors.startTime ? 'border-loss' : ''}
                  />
                  {errors.startTime && <p className="text-sm text-loss">{errors.startTime}</p>}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="stopTime">Stop Time (IST)</Label>
                  <Input
                    id="stopTime"
                    type="time"
                    value={stopTime}
                    onChange={(e) => setStopTime(e.target.value)}
                    className={errors.stopTime ? 'border-loss' : ''}
                  />
                  {errors.stopTime && <p className="text-sm text-loss">{errors.stopTime}</p>}
                </div>
              </div>

              {/* Day Selection */}
              <div className="space-y-2">
                <Label>Schedule Days</Label>
                <div className="flex flex-wrap gap-2">
                  {SCHEDULE_DAYS.map((day) => (
                    <button
                      type="button"
                      key={day.value}
                      className={`flex items-center gap-2 px-3 py-2 border rounded-lg cursor-pointer transition-colors ${
                        selectedDays.includes(day.value)
                          ? 'bg-primary text-primary-foreground border-primary'
                          : 'hover:bg-muted'
                      }`}
                      onClick={() => handleDayToggle(day.value)}
                    >
                      <div
                        className={`h-4 w-4 rounded border flex items-center justify-center ${
                          selectedDays.includes(day.value)
                            ? 'bg-primary-foreground border-primary-foreground'
                            : 'border-current'
                        }`}
                      >
                        {selectedDays.includes(day.value) && (
                          <svg
                            className="h-3 w-3 text-primary"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="3"
                          >
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        )}
                      </div>
                      <span className="text-sm">{day.label}</span>
                    </button>
                  ))}
                </div>
                {errors.days && <p className="text-sm text-loss">{errors.days}</p>}
                <p className="text-xs text-muted-foreground">
                  Select the days when this strategy should run. Weekends can be enabled for special
                  trading sessions.
                </p>
              </div>
            </div>

            {/* Submit */}
            <div className="flex gap-3 pt-4">
              <Button
                type="button"
                variant="outline"
                className="flex-1"
                onClick={() => navigate('/python')}
              >
                Cancel
              </Button>
              <Button type="submit" className="flex-1" disabled={loading}>
                {loading ? 'Uploading...' : 'Upload Strategy'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Example Strategy */}
      <Collapsible open={showExample} onOpenChange={setShowExample}>
        <Card>
          <CardHeader>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" className="w-full justify-between p-0">
                <CardTitle className="text-lg flex items-center gap-2">
                  <FileCode className="h-5 w-5" />
                  Example Strategy Template
                </CardTitle>
                <span className="text-muted-foreground">{showExample ? 'Hide' : 'Show'}</span>
              </Button>
            </CollapsibleTrigger>
          </CardHeader>
          <CollapsibleContent>
            <CardContent>
              <pre className="p-4 bg-muted rounded-lg overflow-x-auto text-xs font-mono">
                {EXAMPLE_STRATEGY}
              </pre>
              <Button
                variant="outline"
                size="sm"
                className="mt-4"
                onClick={() => {
                  navigator.clipboard.writeText(EXAMPLE_STRATEGY)
                  showToast.success('Copied to clipboard', 'clipboard')
                }}
              >
                Copy Template
              </Button>
            </CardContent>
          </CollapsibleContent>
        </Card>
      </Collapsible>
    </div>
  )
}
