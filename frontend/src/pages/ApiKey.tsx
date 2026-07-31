import { AlertCircle, Check, Copy, Eye, EyeOff, Info, Key, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuthStore } from '@/stores/authStore'
import { showToast } from '@/utils/toast'

async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', {
    credentials: 'include',
  })
  const data = await response.json()
  return data.csrf_token
}

export default function ApiKey() {
  const { user } = useAuthStore()
  const [apiKey, setApiKey] = useState<string | null>(null)
  const [hasApiKey, setHasApiKey] = useState(false)
  const [showApiKey, setShowApiKey] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isRegenerating, setIsRegenerating] = useState(false)
  const [showRegenerateDialog, setShowRegenerateDialog] = useState(false)

  // Order mode state
  const [orderMode, setOrderMode] = useState<'auto' | 'semi_auto'>('auto')
  const [isTogglingMode, setIsTogglingMode] = useState(false)

  // biome-ignore lint/correctness/useExhaustiveDependencies: one-time API key load on mount; fetchApiKeyData has no reactive inputs
  useEffect(() => {
    fetchApiKeyData()
  }, [])

  const fetchApiKeyData = async () => {
    setIsLoading(true)
    try {
      const response = await fetch('/apikey', {
        credentials: 'include',
        headers: {
          Accept: 'application/json',
        },
      })

      if (response.ok) {
        const contentType = response.headers.get('content-type')
        if (contentType?.includes('application/json')) {
          const data = await response.json()
          setApiKey(data.api_key || null)
          setHasApiKey(!!data.api_key)
          setOrderMode(data.order_mode || 'auto')
        } else {
          // Backend returned HTML - this shouldn't happen now
          showToast.error('Failed to load API key - please refresh', 'system')
        }
      }
    } catch (_error) {
      showToast.error('Failed to load API key', 'system')
    } finally {
      setIsLoading(false)
    }
  }

  const handleCopyApiKey = async () => {
    if (apiKey) {
      try {
        await navigator.clipboard.writeText(apiKey)
        showToast.success('API key copied to clipboard', 'clipboard')
      } catch {
        showToast.error('Failed to copy API key', 'clipboard')
      }
    }
  }

  const handleRegenerateApiKey = async () => {
    setIsRegenerating(true)
    setShowRegenerateDialog(false)

    try {
      const csrfToken = await fetchCSRFToken()

      const response = await fetch('/apikey', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          user_id: user?.username,
        }),
      })

      const data = await response.json()

      if (data.api_key) {
        setApiKey(data.api_key)
        setHasApiKey(true)
        setShowApiKey(true)
        showToast.success('API key generated successfully', 'system')
      } else {
        showToast.error(data.error || 'Failed to generate API key', 'system')
      }
    } catch (_error) {
      showToast.error('Failed to generate API key', 'system')
    } finally {
      setIsRegenerating(false)
    }
  }

  const handleToggleOrderMode = async () => {
    const newMode = orderMode === 'auto' ? 'semi_auto' : 'auto'
    setIsTogglingMode(true)

    try {
      const csrfToken = await fetchCSRFToken()

      const response = await fetch('/apikey/mode', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          user_id: user?.username,
          mode: newMode,
        }),
      })

      const data = await response.json()

      if (data.mode) {
        setOrderMode(data.mode)
        showToast.success(
          `Order mode updated to ${data.mode === 'semi_auto' ? 'Semi-Auto' : 'Auto'}`,
          'system'
        )
      } else {
        showToast.error(data.error || 'Failed to update order mode', 'system')
      }
    } catch (_error) {
      showToast.error('Failed to update order mode', 'system')
    } finally {
      setIsTogglingMode(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  return (
    <div className="py-6">
      <div className="max-w-2xl">
        {/* API Key Management Card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Key className="h-5 w-5" />
              API Key Management
            </CardTitle>
            <CardDescription>
              {hasApiKey
                ? 'Your API key was automatically generated during account creation. You can view it below or generate a new one if needed.'
                : 'Your API key could not be found. Please generate a new one.'}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* API Key Display */}
            <div className="flex items-center gap-2 p-3 bg-muted rounded-lg">
              <Key className="h-4 w-4 shrink-0 text-muted-foreground" />
              <code className="flex-1 font-mono text-sm truncate">
                {hasApiKey
                  ? showApiKey
                    ? apiKey
                    : `${apiKey?.slice(0, 8)}${'•'.repeat(32)}${apiKey?.slice(-8)}`
                  : 'No API key generated'}
              </code>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={() => setShowApiKey(!showApiKey)}
                disabled={!hasApiKey}
                title={showApiKey ? 'Hide API key' : 'Show API key'}
                aria-label={showApiKey ? 'Hide API key' : 'Show API key'}
              >
                {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </Button>
            </div>

            {/* Action Buttons */}
            <div className="flex flex-wrap gap-2">
              <Button onClick={handleCopyApiKey} disabled={!hasApiKey} size="sm">
                <Copy className="h-4 w-4 mr-2" />
                Copy
              </Button>

              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowRegenerateDialog(true)}
                disabled={isRegenerating}
              >
                <RefreshCw className={`h-4 w-4 mr-2 ${isRegenerating ? 'animate-spin' : ''}`} />
                {hasApiKey ? 'Regenerate' : 'Generate'}
              </Button>
            </div>

            {/* Divider */}
            <div className="border-t pt-6">
              {/* Order Mode Toggle */}
              <div className="space-y-4">
                <div>
                  <h3 className="font-semibold text-lg">Order Execution Mode</h3>
                  <p className="text-sm text-muted-foreground">
                    Choose between automatic execution or manual approval.
                  </p>
                </div>

                <div className="flex items-center gap-4 p-4 bg-muted rounded-lg">
                  <Button
                    variant={orderMode === 'auto' ? 'default' : 'outline'}
                    className={`flex-1 ${orderMode === 'auto' ? 'bg-profit hover:bg-profit' : ''}`}
                    onClick={() => orderMode !== 'auto' && handleToggleOrderMode()}
                    disabled={isTogglingMode}
                  >
                    <Check className="h-4 w-4 mr-2" />
                    Auto Mode
                  </Button>

                  <Button
                    variant={orderMode === 'semi_auto' ? 'default' : 'outline'}
                    className={`flex-1 ${orderMode === 'semi_auto' ? 'bg-warning hover:bg-warning' : ''}`}
                    onClick={() => orderMode !== 'semi_auto' && handleToggleOrderMode()}
                    disabled={isTogglingMode}
                  >
                    <AlertCircle className="h-4 w-4 mr-2" />
                    Semi-Auto
                  </Button>
                </div>
                <div className="flex justify-between text-xs text-muted-foreground px-4">
                  <span>Execute immediately</span>
                  <span>Queue for approval</span>
                </div>

                {/* Current Mode Status */}
                <Alert
                  variant={orderMode === 'semi_auto' ? 'default' : 'default'}
                  className={
                    orderMode === 'semi_auto'
                      ? 'border-warning bg-warning/10'
                      : 'border-profit bg-profit/10'
                  }
                >
                  <Info className="h-4 w-4" />
                  <AlertDescription>
                    Current mode:{' '}
                    <strong>{orderMode === 'semi_auto' ? 'Semi-Auto' : 'Auto'}</strong>
                    {orderMode === 'semi_auto' ? (
                      <span>
                        {' '}
                        - All orders will be queued in{' '}
                        <Link
                          to="/action-center"
                          className="font-bold underline hover:text-primary"
                        >
                          Control Center
                        </Link>{' '}
                        for approval
                      </span>
                    ) : (
                      <span> - All orders will execute immediately</span>
                    )}
                  </AlertDescription>
                </Alert>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Regenerate Confirmation Dialog */}
      <AlertDialog open={showRegenerateDialog} onOpenChange={setShowRegenerateDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {hasApiKey ? 'Regenerate API Key?' : 'Generate API Key?'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {hasApiKey
                ? 'Are you sure you want to regenerate your API key? The current key will be invalidated and any applications using it will need to be updated.'
                : 'Generate a new API key for authenticating your API requests?'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleRegenerateApiKey}>
              {hasApiKey ? 'Regenerate' : 'Generate'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
