import { AlertTriangle, Bot, Check, KeyRound, Loader2, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { type AiProvider, type AiSettings, aiSettingsApi } from '@/api/ai-settings'
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
import { showToast } from '@/utils/toast'

const PROVIDER_LABELS: Record<AiProvider, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  gemini: 'Google Gemini',
  custom: 'Custom (OpenAI-compatible)',
}

const PROVIDER_MODEL_HINTS: Record<AiProvider, string> = {
  openai: 'gpt-4o-mini',
  anthropic: 'claude-3-5-haiku-latest',
  gemini: 'gemini-1.5-flash',
  custom: 'e.g. llama-3.3-70b-versatile (Groq)',
}

export default function AiSettingsPage() {
  const [settings, setSettings] = useState<AiSettings | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)

  const [provider, setProvider] = useState<AiProvider>('openai')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')

  const loadSettings = async () => {
    setIsLoading(true)
    try {
      const data = await aiSettingsApi.get()
      setSettings(data)
      if (data) {
        setProvider(data.provider)
        setModel(data.model || '')
        setBaseUrl(data.baseUrl || '')
      }
    } finally {
      setIsLoading(false)
    }
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: one-time load on mount
  useEffect(() => {
    loadSettings()
  }, [])

  const handleSave = async () => {
    if (!apiKey.trim()) {
      showToast.error('Enter an API key to save', 'strategy')
      return
    }
    if (provider === 'custom' && !baseUrl.trim()) {
      showToast.error('Base URL is required for a custom provider', 'strategy')
      return
    }
    if (provider === 'custom' && !model.trim()) {
      showToast.error(
        'Enter the model name your endpoint expects (e.g. llama-3.3-70b-versatile for Groq)',
        'strategy'
      )
      return
    }
    setIsSaving(true)
    try {
      const result = await aiSettingsApi.save(
        provider,
        apiKey.trim(),
        model.trim() || undefined,
        provider === 'custom' ? baseUrl.trim() : undefined
      )
      if (result.success) {
        showToast.success('AI provider configured', 'strategy')
        setApiKey('')
        await loadSettings()
      } else {
        showToast.error(result.message || 'Failed to save AI settings', 'strategy')
      }
    } finally {
      setIsSaving(false)
    }
  }

  const handleDelete = async () => {
    setIsDeleting(true)
    try {
      const success = await aiSettingsApi.remove()
      if (success) {
        showToast.success('AI provider configuration removed', 'strategy')
        setSettings(null)
        setApiKey('')
        setModel('')
        setBaseUrl('')
      } else {
        showToast.error('Failed to remove AI settings', 'strategy')
      }
    } finally {
      setIsDeleting(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  return (
    <div className="py-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bot className="h-5 w-5" />
              AI Insight Provider
            </CardTitle>
            <CardDescription>
              Bring your own API key from OpenAI, Anthropic, Google Gemini, or any OpenAI-compatible
              endpoint. Used only by the "Get AI Insight" button on the Charts page — advisory only,
              never places or influences an order.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {settings?.hasApiKey && (
              <div className="flex items-center gap-2 rounded-lg border border-profit/40 bg-profit/10 px-3 py-2 text-sm text-profit">
                <Check className="h-4 w-4 shrink-0" />
                {PROVIDER_LABELS[settings.provider]} configured. Re-enter a key below to replace it.
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="ai-provider">Provider</Label>
              <Select value={provider} onValueChange={(v) => setProvider(v as AiProvider)}>
                <SelectTrigger id="ai-provider">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(PROVIDER_LABELS) as AiProvider[]).map((p) => (
                    <SelectItem key={p} value={p}>
                      {PROVIDER_LABELS[p]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="ai-api-key">API Key</Label>
              <div className="flex items-center gap-2">
                <KeyRound className="h-4 w-4 shrink-0 text-muted-foreground" />
                <Input
                  id="ai-api-key"
                  type="password"
                  autoComplete="off"
                  placeholder={settings?.hasApiKey ? '••••••••••••••••••••' : 'sk-...'}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="ai-model">
                Model {provider === 'custom' ? '(required)' : '(optional)'}
              </Label>
              <Input
                id="ai-model"
                placeholder={PROVIDER_MODEL_HINTS[provider]}
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
            </div>

            {provider === 'custom' && (
              <div className="space-y-2">
                <Label htmlFor="ai-base-url">Base URL</Label>
                <Input
                  id="ai-base-url"
                  placeholder="https://your-endpoint.example.com/v1"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
              </div>
            )}

            <div className="flex flex-wrap gap-2 pt-2">
              <Button onClick={handleSave} disabled={isSaving}>
                {isSaving ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <KeyRound className="h-4 w-4 mr-2" />
                )}
                Save
              </Button>
              {settings?.hasApiKey && (
                <Button variant="outline" onClick={handleDelete} disabled={isDeleting}>
                  <Trash2 className={`h-4 w-4 mr-2 ${isDeleting ? 'animate-pulse' : ''}`} />
                  Remove
                </Button>
              )}
            </div>

            <Alert>
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                Your key is encrypted at rest and never shown again once saved. AI Insight calls are
                rate-limited server-side and cost real money against your own provider account — the
                platform never places trades from AI output automatically.
              </AlertDescription>
            </Alert>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>How AI Insight works</CardTitle>
            <CardDescription>What gets sent, and what doesn't.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm text-muted-foreground">
            <div>
              <h3 className="font-semibold text-foreground mb-1">Sent to your AI provider</h3>
              <ul className="space-y-1 list-disc list-inside">
                <li>Recent OHLCV bars for the symbol you have open (last ~20 bars)</li>
                <li>The values of indicators you already have enabled on that chart</li>
              </ul>
            </div>
            <div>
              <h3 className="font-semibold text-foreground mb-1">Never sent</h3>
              <ul className="space-y-1 list-disc list-inside">
                <li>Broker credentials, tokens, or account balance</li>
                <li>Positions, holdings, or order history</li>
                <li>Any data for symbols other than the one currently open</li>
              </ul>
            </div>
            <div>
              <h3 className="font-semibold text-foreground mb-1">Response</h3>
              <p>
                A structured sentiment (bullish/bearish/neutral), confidence, a short summary, key
                drivers cited from the data above, and an optional watch level — rendered as a
                read-only card. You always place orders manually via the order ticket.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
