import {
  AlertCircle,
  AlertTriangle,
  BookOpen,
  ExternalLink,
  Eye,
  EyeOff,
  Info,
  Key,
  Loader2,
  Plug,
  Radio,
  RefreshCw,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { fetchCSRFToken } from '@/api/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  isMultiPartBroker,
  joinBrokerParts,
  MULTI_PART_BROKER_CONFIG,
  splitBrokerParts,
} from '@/lib/brokerCredentials'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'

// All supported brokers with their display names and auth types
const allBrokers = [
  { id: 'fivepaisa', name: '5 Paisa', authType: 'totp' },
  { id: 'fivepaisaxts', name: '5 Paisa (XTS)', authType: 'totp' },
  { id: 'aliceblue', name: 'Alice Blue', authType: 'totp' },
  { id: 'angel', name: 'Angel One', authType: 'totp' },
  { id: 'arrow', name: 'Arrow', authType: 'oauth' },
  { id: 'compositedge', name: 'CompositEdge', authType: 'oauth' },
  { id: 'dhan', name: 'Dhan', authType: 'oauth' },
  { id: 'deltaexchange', name: 'Delta Exchange', authType: 'totp' },
  { id: 'indmoney', name: 'IndMoney', authType: 'totp' },
  { id: 'dhan_sandbox', name: 'Dhan (Sandbox)', authType: 'totp' },
  { id: 'definedge', name: 'Definedge', authType: 'totp' },
  { id: 'firstock', name: 'Firstock', authType: 'totp' },
  { id: 'flattrade', name: 'Flattrade', authType: 'oauth' },
  { id: 'motilal', name: 'Motilal Oswal', authType: 'totp' },
  { id: 'fyers', name: 'Fyers', authType: 'oauth' },
  { id: 'ibulls', name: 'Ibulls', authType: 'totp' },
  { id: 'iifl', name: 'IIFL', authType: 'totp' },
  { id: 'iiflcapital', name: 'IIFL Capital', authType: 'oauth' },
  { id: 'jainamxts', name: 'JainamXts', authType: 'totp' },
  { id: 'pocketful', name: 'Pocketful', authType: 'oauth' },
  { id: 'rmoney', name: 'RMoney', authType: 'oauth' },
  { id: 'sharekhan', name: 'Sharekhan', authType: 'oauth' },
  { id: 'shoonya', name: 'Shoonya', authType: 'totp' },
  { id: 'upstox', name: 'Upstox', authType: 'oauth' },
  { id: 'wisdom', name: 'Wisdom Capital', authType: 'totp' },
  { id: 'zebu', name: 'Zebu', authType: 'totp' },
  { id: 'bnr', name: 'BNR Securities', authType: 'totp' },
  { id: 'zerodha', name: 'Zerodha', authType: 'oauth' },
] as const

// Per-broker API-key format hints, keyed by broker id. Data-driven so the
// hint renders once from a lookup (the old JSX had these duplicated inline,
// literally twice each for fivepaisa/flattrade/dhan).
const BROKER_KEY_FORMAT_HINTS: Record<string, string> = {
  fivepaisa: 'User_Key:::User_ID:::client_id',
  flattrade: 'client_id:::api_key',
  dhan: 'client_id:::api_key',
}

// Brokers where auto session refresh is possible (direct password+TOTP
// login, no OAuth redirect) -- must match user_db.AUTO_REFRESH_SUPPORTED_
// BROKERS. Each maps to the extra login fields its authenticate_broker()
// needs (beyond the stored API key/secret and the TOTP seed).
const AUTO_REFRESH_FIELDS: Record<
  string,
  { label: string; fields: { name: string; label: string; placeholder: string }[] }
> = {
  angel: {
    label: 'Angel One',
    fields: [
      { name: 'clientcode', label: 'Client Code', placeholder: 'Your Angel client code' },
      { name: 'pin', label: 'PIN / Password', placeholder: 'Login PIN' },
    ],
  },
  fivepaisa: {
    label: '5paisa',
    fields: [
      { name: 'clientcode', label: 'Client Code / Email', placeholder: 'Registered email' },
      { name: 'pin', label: 'PIN', placeholder: 'Login PIN' },
    ],
  },
  motilal: {
    label: 'Motilal Oswal',
    fields: [
      { name: 'userid', label: 'User ID', placeholder: 'Your Motilal user ID' },
      { name: 'pin', label: 'Password', placeholder: 'Login password' },
      { name: 'dob', label: 'Date of Birth', placeholder: 'DD/MM/YYYY' },
    ],
  },
}

interface BrokerConfig {
  broker_name: string
  broker_api_key: string
  redirect_url: string
}

// Helper function to get Flattrade API key
function getFlattradeApiKey(fullKey: string): string {
  if (!fullKey) return ''
  const parts = fullKey.split(':::')
  return parts.length > 1 ? parts[1] : fullKey
}

// Generate random state for OAuth
function generateRandomState(): string {
  const length = 16
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  let result = ''
  for (let i = 0; i < length; i++) {
    result += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  return result
}

export default function BrokerSelect() {
  const { user } = useAuthStore()
  const [selectedBroker, setSelectedBroker] = useState<string>('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)
  const [brokerConfig, setBrokerConfig] = useState<BrokerConfig | null>(null)
  // The ACTUALLY connected broker (from the server's session/Auth-table
  // record), independent of whichever broker happens to be picked in the
  // <Select> below. This platform stores exactly one broker session at a
  // time (see database/auth_db.py - Auth.username is unique), so "which
  // broker's credentials are really active" is only ever this value, never
  // whatever the dropdown currently shows.
  const [connectedBroker, setConnectedBroker] = useState<{
    broker: string | null
    tokenValid: boolean | null
  }>({ broker: null, tokenValid: null })

  // In-page configuration credentials state
  const [brokerApiKey, setBrokerApiKey] = useState<string>('')
  // Per-part values for brokers whose API key is really N `:::`-joined
  // fields (Zebu, BNR, Flattrade, Dhan, 5paisa). Kept in sync with
  // brokerApiKey via joinBrokerParts so the rest of the form/save logic
  // never needs to know about the split.
  const [keyParts, setKeyParts] = useState<string[]>([])
  const [brokerApiSecret, setBrokerApiSecret] = useState<string>('')
  const [brokerApiKeyMarket, setBrokerApiKeyMarket] = useState<string>('')
  const [brokerApiSecretMarket, setBrokerApiSecretMarket] = useState<string>('')
  const [redirectUrl, setRedirectUrl] = useState<string>('')
  const [showConfigForm, setShowConfigForm] = useState<boolean>(false)
  const [showApiKey, setShowApiKey] = useState(false)
  const [showApiSecret, setShowApiSecret] = useState(false)

  // Auto session refresh (opt-in, angel/fivepaisa/motilal only)
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(false)
  const [autoRefreshLastStatus, setAutoRefreshLastStatus] = useState<string | null>(null)
  const [showAutoRefreshModal, setShowAutoRefreshModal] = useState(false)
  const [autoRefreshAck, setAutoRefreshAck] = useState(false)
  const [autoRefreshSeed, setAutoRefreshSeed] = useState('')
  const [autoRefreshParams, setAutoRefreshParams] = useState<Record<string, string>>({})
  const [autoRefreshSaving, setAutoRefreshSaving] = useState(false)

  // Surface a failed-login error forwarded by the backend (see
  // handle_auth_failure / broker_login in blueprints/auth.py) - e.g. a
  // broker OAuth callback that failed (wrong checksum, IP not whitelisted,
  // etc). Without this, a failed broker-switch attempt was silently
  // swallowed and the user just saw the dashboard with their previous
  // broker still connected, no indication anything went wrong.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const authError = params.get('auth_error')
    if (authError) {
      setError(authError)
      // Strip the param from the visible URL so refreshing/sharing the
      // link doesn't re-show a stale error.
      const url = new URL(window.location.href)
      url.searchParams.delete('auth_error')
      window.history.replaceState({}, '', url.toString())
    }
  }, [])

  // Fetch the real currently-connected broker + live token health, so the
  // status banner below can tell the truth instead of relying on whichever
  // broker happens to be selected in the dropdown.
  useEffect(() => {
    const fetchConnectedBrokerStatus = async () => {
      try {
        const response = await fetch('/auth/broker-status', { credentials: 'include' })
        const data = await response.json()
        if (data.status === 'success') {
          setConnectedBroker({
            broker: data.connected ? data.broker : null,
            tokenValid: data.connected ? data.token_valid : null,
          })
        }
      } catch {
        // Non-fatal - the rest of the page still functions without this.
      }
    }
    fetchConnectedBrokerStatus()
  }, [])

  // Fetch initial/default configuration. If the Broker Management page sent
  // us here with ?broker=<name> (e.g. "Connect" on a configured broker),
  // preselect and load THAT broker's config instead of the default one.
  useEffect(() => {
    const fetchInitialBrokerConfig = async () => {
      try {
        const requested = new URLSearchParams(window.location.search).get('broker')
        const url = requested
          ? `/auth/broker-config?broker=${encodeURIComponent(requested)}`
          : '/auth/broker-config'
        const response = await fetch(url, {
          credentials: 'include',
        })
        const data = await response.json()

        if (data.status === 'success') {
          const brokerName = requested || data.broker_name
          setBrokerConfig(data)
          setSelectedBroker(brokerName)
          setRedirectUrl(data.redirect_url || '')
          setBrokerApiKey(data.broker_api_key || '')
          setKeyParts(
            isMultiPartBroker(brokerName)
              ? splitBrokerParts(brokerName, data.broker_api_key || '')
              : []
          )
          // A configured broker arriving with no saved key means "set up";
          // open the form so the user can enter credentials immediately.
          if (!data.broker_api_key) setShowConfigForm(true)
        } else {
          setError(data.message || 'Failed to load broker configuration')
        }
      } catch {
        setError('Failed to load broker configuration')
      } finally {
        setIsLoading(false)
      }
    }

    fetchInitialBrokerConfig()
    // biome-ignore lint/correctness/useExhaustiveDependencies: intentional mount-only fetch
  }, [])

  // Fetch dynamic configuration whenever selected broker changes
  useEffect(() => {
    if (!selectedBroker || isLoading) return

    const fetchBrokerConfig = async () => {
      setError(null)
      setSuccessMsg(null)
      try {
        const response = await fetch(`/auth/broker-config?broker=${selectedBroker}`, {
          credentials: 'include',
        })
        const data = await response.json()

        if (data.status === 'success') {
          setBrokerConfig(data)
          setRedirectUrl(data.redirect_url || '')
          setBrokerApiKey(data.broker_api_key || '')
          setKeyParts(
            isMultiPartBroker(selectedBroker)
              ? splitBrokerParts(selectedBroker, data.broker_api_key || '')
              : []
          )
          setBrokerApiSecret('') // Secrets are never sent back for security
          setBrokerApiKeyMarket('')
          setBrokerApiSecretMarket('')

          // Auto-show input form if no API key is set for the selected broker
          if (!data.broker_api_key) {
            setShowConfigForm(true)
          } else {
            setShowConfigForm(false)
          }
        } else {
          setError(data.message || 'Failed to fetch broker configuration')
        }
      } catch {
        setError('Failed to fetch broker configuration')
      }
    }

    fetchBrokerConfig()
  }, [selectedBroker, isLoading])

  // keyParts is seeded directly inside both fetch callbacks above (right
  // where the freshly-fetched broker_api_key is available), not in a
  // separate effect - a [selectedBroker]-only effect would run before the
  // async fetch resolves and split the *previous* broker's stale key.

  const updateKeyPart = (index: number, value: string) => {
    setKeyParts((prev) => {
      const next = [...prev]
      next[index] = value
      setBrokerApiKey(joinBrokerParts(next))
      return next
    })
  }

  // Save credentials to database first, then connect
  const handleSaveAndConnect = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccessMsg(null)

    if (!brokerApiKey) {
      setError('Broker API Key / ID is required')
      return
    }

    setIsSaving(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/api/broker/credentials', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          broker_api_key: brokerApiKey,
          broker_api_secret: brokerApiSecret,
          broker_api_key_market: brokerApiKeyMarket,
          broker_api_secret_market: brokerApiSecretMarket,
          redirect_url: redirectUrl,
        }),
      })
      const data = await response.json()
      if (data.status === 'success') {
        setSuccessMsg('Broker credentials saved! Connecting...')

        // Initiate actual connection
        await initiateConnection()
      } else {
        setError(data.message || 'Failed to save credentials')
        setIsSaving(false)
      }
    } catch {
      setError('Failed to save credentials')
      setIsSaving(false)
    }
  }

  // Direct connection (for already configured credentials)
  const handleDirectConnect = (e: React.FormEvent) => {
    e.preventDefault()
    initiateConnection()
  }

  // Fetch auto-refresh status whenever the selected broker changes (only
  // relevant for the 3 supported brokers).
  useEffect(() => {
    if (!selectedBroker || !AUTO_REFRESH_FIELDS[selectedBroker]) {
      setAutoRefreshEnabled(false)
      setAutoRefreshLastStatus(null)
      return
    }
    fetch(`/api/broker/auto-refresh/status?broker=${selectedBroker}`, { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.status === 'success') {
          setAutoRefreshEnabled(Boolean(data.data?.enabled))
          setAutoRefreshLastStatus(data.data?.last_status ?? null)
        }
      })
      .catch(() => {})
  }, [selectedBroker])

  const handleEnableAutoRefresh = async () => {
    setAutoRefreshSaving(true)
    setError(null)
    try {
      const csrfToken = await fetchCSRFToken()
      const res = await fetch('/api/broker/auto-refresh/enable', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({
          broker: selectedBroker,
          acknowledged: autoRefreshAck,
          totp_seed: autoRefreshSeed.trim(),
          ...autoRefreshParams,
        }),
      })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        setAutoRefreshEnabled(true)
        setShowAutoRefreshModal(false)
        setAutoRefreshSeed('')
        setAutoRefreshParams({})
        setAutoRefreshAck(false)
        setSuccessMsg('Auto-login enabled for this broker.')
      } else {
        setError(data.message || 'Could not enable auto-login')
      }
    } catch {
      setError('Could not enable auto-login')
    } finally {
      setAutoRefreshSaving(false)
    }
  }

  const handleDisableAutoRefresh = async () => {
    try {
      const csrfToken = await fetchCSRFToken()
      const res = await fetch('/api/broker/auto-refresh/disable', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({ broker: selectedBroker }),
      })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        setAutoRefreshEnabled(false)
        setAutoRefreshLastStatus(null)
        setSuccessMsg('Auto-login disabled. Your stored 2FA seed was cleared.')
      }
    } catch {
      setError('Could not disable auto-login')
    }
  }

  const initiateConnection = async () => {
    setIsSubmitting(true)
    let loginUrl = ''

    // Use current state values
    const activeKey = brokerApiKey

    // Build login URL based on broker type (matching original broker.html logic)
    switch (selectedBroker) {
      case 'fivepaisa':
      case 'fivepaisaxts':
      case 'angel':
      case 'indmoney':
      case 'deltaexchange':
      case 'jainamxts':
      case 'dhan_sandbox':
      case 'definedge':
      case 'firstock':
      case 'motilal':
      case 'ibulls':
      case 'iifl':
      case 'rmoney':
      case 'wisdom':
      case 'zebu': {
        // go.mynt.in is Zebu's OAuth domain specifically. bnr, shoonya, and
        // aliceblue are Noren-family/OAuth brokers too but each has its OWN
        // distinct OAuth domain (prime.bnrsecurities.com, api.shoonya.com,
        // ant.aliceblueonline.com respectively -- see blueprints/brlogin.py)
        // -- they were previously grouped into this same go.mynt.in branch,
        // which sent their real client_id to the wrong OAuth provider
        // entirely ("Access Restricted for API Only Users" on go.mynt.in).
        // They now fall through to the /callback case below, which lets the
        // backend build the correct broker-specific URL instead of
        // hardcoding it here.
        const parts = activeKey ? activeKey.split(':::') : []
        const clientId =
          parts.length > 1 && parts[1]?.trim() ? parts[1].trim() : parts[0]?.trim() || ''
        if (clientId) {
          loginUrl = `https://go.mynt.in/OAuthlogin/authorize/oauth?client_id=${encodeURIComponent(clientId)}`
        } else {
          loginUrl = `/${selectedBroker}/callback`
        }
        break
      }

      case 'bnr':
      case 'shoonya':
      case 'aliceblue':
        // Let the backend build the correct broker-specific OAuth URL
        // (blueprints/brlogin.py resolves each broker's own domain/client_id
        // from its stored credentials) instead of hardcoding a URL here.
        loginUrl = `/${selectedBroker}/callback`
        break

      case 'iiflcapital':
        loginUrl = '/iiflcapital/callback'
        break

      case 'dhan':
        loginUrl = '/dhan/initiate-oauth'
        break

      case 'compositedge':
        loginUrl = `https://xts.compositedge.com/interactive/thirdparty?appKey=${activeKey}&returnURL=${redirectUrl}`
        break

      case 'flattrade': {
        const flattradeApiKey = getFlattradeApiKey(activeKey)
        loginUrl = `https://auth.flattrade.in/?app_key=${flattradeApiKey}`
        break
      }

      case 'fyers':
        loginUrl = `https://api-t1.fyers.in/api/v3/generate-authcode?client_id=${activeKey}&redirect_uri=${redirectUrl}&response_type=code&state=2e9b44629ebb28226224d09db3ffb47c`
        break

      case 'upstox':
        loginUrl = `https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id=${activeKey}&redirect_uri=${redirectUrl}`
        break

      case 'zerodha':
        loginUrl = `https://kite.trade/connect/login?api_key=${activeKey}`
        break

      case 'sharekhan': {
        // BROKER_API_KEY holds "api_key:::vendor_key" (vendor_key optional,
        // blank for non-vendor logins) - same joined-field convention as
        // Flattrade/Dhan/Zebu (see MULTI_PART_BROKER_CONFIG).
        const [sharekhanApiKey, sharekhanVendorKey] = activeKey.split(':::')
        loginUrl = `https://api.sharekhan.com/skapi/auth/login.html?api_key=${sharekhanApiKey}&state=12345`
        if (sharekhanVendorKey) {
          loginUrl += `&vendor_key=${sharekhanVendorKey}`
        }
        break
      }

      case 'arrow':
        loginUrl = `https://app.arrow.trade/app/login?appID=${activeKey}`
        break

      case 'pocketful': {
        const state = generateRandomState()
        localStorage.setItem('pocketful_oauth_state', state)
        const scope = 'orders holdings'
        loginUrl = `https://trade.pocketful.in/oauth2/auth?client_id=${activeKey}&redirect_uri=${redirectUrl}&response_type=code&scope=${encodeURIComponent(scope)}&state=${encodeURIComponent(state)}`
        break
      }

      default:
        setError('Please select a broker')
        setIsSubmitting(false)
        setIsSaving(false)
        return
    }

    setTimeout(() => {
      window.location.href = loginUrl
    }, 300)
  }

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-brand" />
      </div>
    )
  }

  const selectedBrokerName = allBrokers.find((b) => b.id === selectedBroker)?.name
  const isConfigured = !!brokerConfig?.broker_api_key
  // "Add broker" mode: arrived from Broker Management with ?broker=<name>
  // and the user already has a data broker connected. Skip the full
  // first-time marketing splash and show a tighter, purpose-specific card
  // instead, since this is an experienced user adding a second/third
  // broker, not a brand-new setup.
  const isAddingAdditionalBroker =
    !!connectedBroker.broker && connectedBroker.broker !== selectedBroker

  return (
    <div className="min-h-screen flex items-center justify-center py-10 px-4">
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="flex justify-center mb-4">
            <img src="/logo.png" alt="Max Algos" className="h-14 w-14" />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">
            {isAddingAdditionalBroker ? 'Add a Broker' : 'Connect Your Broker'}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {isAddingAdditionalBroker ? (
              <>
                <span className="font-medium text-foreground">
                  {allBrokers.find((b) => b.id === connectedBroker.broker)?.name}
                </span>{' '}
                stays your data broker — this one is added for placing orders.
              </>
            ) : (
              <>
                Welcome{user?.username ? `, ${user.username}` : ''}. Link a trading account to start
                trading.
              </>
            )}
          </p>
        </div>

        {/* Connected-broker status strip (first-time layout only) */}
        {!isAddingAdditionalBroker && (
          <div
            className={cn(
              'flex items-center gap-2.5 rounded-lg border px-3.5 py-2.5 mb-5 text-sm',
              connectedBroker.broker
                ? connectedBroker.tokenValid
                  ? 'bg-profit/10 border-profit/25 text-profit'
                  : 'bg-warning/10 border-warning/25 text-warning'
                : 'bg-muted/50 border-border text-muted-foreground'
            )}
          >
            <Radio className="h-4 w-4 shrink-0" />
            <span>
              {connectedBroker.broker ? (
                <>
                  Data broker:{' '}
                  <span className="font-semibold">
                    {allBrokers.find((b) => b.id === connectedBroker.broker)?.name ??
                      connectedBroker.broker}
                  </span>
                  {connectedBroker.tokenValid === false && ' — session expired, reconnect below'}
                </>
              ) : (
                'No broker connected yet'
              )}
            </span>
          </div>
        )}

        {/* Main card */}
        <div className="rounded-2xl border border-border bg-card p-6 space-y-5 shadow-sm">
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {successMsg && (
            <Alert className="bg-profit/10 border-profit/30 text-profit">
              <Info className="h-4 w-4" />
              <AlertDescription>{successMsg}</AlertDescription>
            </Alert>
          )}

          {/* Broker selector (hidden when adding a fixed broker from Manage) */}
          {!isAddingAdditionalBroker && (
            <div className="space-y-2">
              <Label
                htmlFor="broker-select"
                className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
              >
                Broker
              </Label>
              <Select
                value={selectedBroker}
                onValueChange={(val) => {
                  setSelectedBroker(val)
                  setShowApiKey(false)
                  setShowApiSecret(false)
                }}
                disabled={isSubmitting || isSaving}
              >
                <SelectTrigger id="broker-select" className="w-full">
                  <SelectValue placeholder="Select a broker" />
                </SelectTrigger>
                <SelectContent>
                  {allBrokers.map((broker) => (
                    <SelectItem key={broker.id} value={broker.id}>
                      {broker.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {isAddingAdditionalBroker && selectedBrokerName && (
            <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3.5 py-2.5">
              <Plug className="h-4 w-4 text-brand shrink-0" />
              <span className="text-sm font-semibold text-foreground">{selectedBrokerName}</span>
            </div>
          )}

          {selectedBroker && (
            <>
              {/* Configured / needs-setup status */}
              {isConfigured && !showConfigForm ? (
                <div className="flex items-center justify-between gap-3 rounded-lg bg-profit/10 border border-profit/25 px-3.5 py-2.5">
                  <span className="text-sm text-profit">
                    <span className="font-semibold">{selectedBrokerName}</span> credentials saved.
                  </span>
                  <button
                    type="button"
                    className="text-xs font-semibold text-brand hover:underline shrink-0"
                    onClick={() => setShowConfigForm(true)}
                  >
                    Edit
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-2.5 rounded-lg bg-info/10 border border-info/25 px-3.5 py-2.5 text-sm text-info">
                  <Info className="h-4 w-4 shrink-0" />
                  <span>
                    Enter your <span className="font-semibold">{selectedBrokerName}</span> API
                    credentials to connect.
                  </span>
                </div>
              )}

              {/* Key-format hint (single, data-driven) */}
              {BROKER_KEY_FORMAT_HINTS[selectedBroker] && (
                <p className="text-xs text-muted-foreground -mt-1">
                  API key format:{' '}
                  <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground">
                    {BROKER_KEY_FORMAT_HINTS[selectedBroker]}
                  </code>
                </p>
              )}

              {/* Credentials form */}
              {showConfigForm && (
                <form onSubmit={handleSaveAndConnect} className="space-y-4 pt-1">
                  {isMultiPartBroker(selectedBroker) ? (
                    // Multi-part API key (Zebu, BNR, Flattrade, Dhan, 5paisa):
                    // one labeled input per part instead of asking the user to
                    // type the ":::" separator. Parts join into brokerApiKey on
                    // every change, so save/connect logic is unaffected.
                    <div className="space-y-2">
                      <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        API Key
                      </Label>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {MULTI_PART_BROKER_CONFIG[selectedBroker].parts.map((part, idx) => (
                          <div key={part.label} className="space-y-1">
                            <Label className="text-xs text-muted-foreground font-normal">
                              {part.label}
                            </Label>
                            <Input
                              type="text"
                              value={keyParts[idx] ?? ''}
                              onChange={(e) => updateKeyPart(idx, e.target.value)}
                              placeholder={part.placeholder}
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        API Key / Client ID
                      </Label>
                      <div className="relative">
                        <Input
                          type={showApiKey ? 'text' : 'password'}
                          value={brokerApiKey}
                          onChange={(e) => setBrokerApiKey(e.target.value)}
                          placeholder={
                            isConfigured ? 'Kept existing (enter to update)' : 'Enter API key'
                          }
                          className="pr-10"
                        />
                        <button
                          type="button"
                          onClick={() => setShowApiKey(!showApiKey)}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                          aria-label={showApiKey ? 'Hide API key' : 'Show API key'}
                        >
                          {showApiKey ? (
                            <EyeOff className="h-4 w-4" />
                          ) : (
                            <Eye className="h-4 w-4" />
                          )}
                        </button>
                      </div>
                    </div>
                  )}

                  <div className="space-y-2">
                    <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      API Secret / Access Token
                    </Label>
                    <div className="relative">
                      <Input
                        type={showApiSecret ? 'text' : 'password'}
                        value={brokerApiSecret}
                        onChange={(e) => setBrokerApiSecret(e.target.value)}
                        placeholder="Enter API secret"
                        className="pr-10"
                      />
                      <button
                        type="button"
                        onClick={() => setShowApiSecret(!showApiSecret)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                        aria-label={showApiSecret ? 'Hide API secret' : 'Show API secret'}
                      >
                        {showApiSecret ? (
                          <EyeOff className="h-4 w-4" />
                        ) : (
                          <Eye className="h-4 w-4" />
                        )}
                      </button>
                    </div>
                  </div>

                  {/* Market keys for XTS brokers */}
                  {(selectedBroker.includes('xts') ||
                    selectedBroker === 'fivepaisaxts' ||
                    selectedBroker === 'jainamxts') && (
                    <div className="space-y-3 pt-3 border-t border-border">
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        Market Data Keys (XTS only)
                      </h4>
                      <div className="grid grid-cols-2 gap-3">
                        <div className="space-y-1.5">
                          <Label className="text-xs text-muted-foreground font-normal">
                            Market API Key
                          </Label>
                          <Input
                            type="password"
                            value={brokerApiKeyMarket}
                            onChange={(e) => setBrokerApiKeyMarket(e.target.value)}
                            placeholder="Market key"
                          />
                        </div>
                        <div className="space-y-1.5">
                          <Label className="text-xs text-muted-foreground font-normal">
                            Market API Secret
                          </Label>
                          <Input
                            type="password"
                            value={brokerApiSecretMarket}
                            onChange={(e) => setBrokerApiSecretMarket(e.target.value)}
                            placeholder="Market secret"
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="space-y-1.5">
                    <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Redirect URL
                    </Label>
                    <Input
                      type="text"
                      value={redirectUrl}
                      onChange={(e) => setRedirectUrl(e.target.value)}
                      placeholder="Redirect URL"
                    />
                    <p className="text-xs text-muted-foreground">
                      Must end with{' '}
                      <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">
                        /{selectedBroker}/callback
                      </code>
                    </p>
                  </div>

                  <div className="flex gap-3 pt-1">
                    {isConfigured && (
                      <Button
                        type="button"
                        variant="outline"
                        className="flex-1"
                        onClick={() => setShowConfigForm(false)}
                        disabled={isSaving || isSubmitting}
                      >
                        Cancel
                      </Button>
                    )}
                    <Button
                      type="submit"
                      className="flex-1"
                      disabled={isSaving || isSubmitting || !brokerApiKey}
                    >
                      {isSaving ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Saving…
                        </>
                      ) : (
                        <>
                          <Key className="mr-2 h-4 w-4" />
                          Save &amp; Connect
                        </>
                      )}
                    </Button>
                  </div>
                </form>
              )}

              {/* Direct connect (credentials already saved) */}
              {!showConfigForm && isConfigured && (
                <form onSubmit={handleDirectConnect}>
                  <Button type="submit" className="w-full" disabled={isSubmitting || isSaving}>
                    {isSubmitting ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Connecting…
                      </>
                    ) : (
                      <>
                        <ExternalLink className="mr-2 h-4 w-4" />
                        Connect Account
                      </>
                    )}
                  </Button>
                </form>
              )}

              {/* Auto session refresh -- only for the 3 supported
                  password+TOTP brokers, and only once credentials exist. */}
              {AUTO_REFRESH_FIELDS[selectedBroker] && isConfigured && !showConfigForm && (
                <div className="rounded-lg border border-border bg-muted/30 p-3.5 space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <RefreshCw className="h-4 w-4 text-brand shrink-0" />
                      <span className="text-sm font-semibold text-foreground">
                        Keep me logged in
                      </span>
                    </div>
                    {autoRefreshEnabled ? (
                      <button
                        type="button"
                        onClick={handleDisableAutoRefresh}
                        className="text-xs font-semibold text-loss hover:underline"
                      >
                        Turn off
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => {
                          setAutoRefreshAck(false)
                          setAutoRefreshSeed('')
                          setAutoRefreshParams({})
                          setShowAutoRefreshModal(true)
                        }}
                        className="text-xs font-semibold text-brand hover:underline"
                      >
                        Set up
                      </button>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {autoRefreshEnabled ? (
                      <>
                        Auto-login is on — this broker re-connects each morning without you.
                        {autoRefreshLastStatus === 'failed' && (
                          <span className="text-loss">
                            {' '}
                            Last auto-login failed — connect manually today.
                          </span>
                        )}
                      </>
                    ) : (
                      "Auto-login each morning so you don't have to reconnect daily. Stores your broker 2FA seed — read the warning before enabling."
                    )}
                  </p>
                </div>
              )}
            </>
          )}
        </div>

        {/* Auto-refresh setup modal (security warning + seed entry) */}
        <AlertDialog open={showAutoRefreshModal} onOpenChange={setShowAutoRefreshModal}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle className="flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-warning" />
                Enable auto-login for {AUTO_REFRESH_FIELDS[selectedBroker]?.label}
              </AlertDialogTitle>
              <AlertDialogDescription asChild>
                <div className="space-y-3 text-left">
                  <p>
                    To log in for you every morning, Max Algos will store your broker&rsquo;s{' '}
                    <strong>2FA authenticator seed</strong> and login details, encrypted.
                  </p>
                  <div className="rounded-md bg-warning/10 border border-warning/25 p-3 text-xs text-warning space-y-1.5">
                    <p className="font-semibold">Understand the risk before continuing:</p>
                    <ul className="list-disc list-inside space-y-1">
                      <li>Storing a 2FA seed is against most brokers&rsquo; terms of service.</li>
                      <li>
                        If this server is breached, an attacker could log into your real trading
                        account unattended — 2FA won&rsquo;t stop them.
                      </li>
                    </ul>
                  </div>
                </div>
              </AlertDialogDescription>
            </AlertDialogHeader>

            <div className="space-y-3 py-1">
              <div className="space-y-1.5">
                <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  TOTP Seed (base32)
                </Label>
                <Input
                  value={autoRefreshSeed}
                  onChange={(e) => setAutoRefreshSeed(e.target.value)}
                  placeholder="The secret shown when you set up your authenticator"
                  autoComplete="off"
                />
              </div>
              {AUTO_REFRESH_FIELDS[selectedBroker]?.fields.map((f) => (
                <div key={f.name} className="space-y-1.5">
                  <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {f.label}
                  </Label>
                  <Input
                    type={f.name === 'pin' ? 'password' : 'text'}
                    value={autoRefreshParams[f.name] ?? ''}
                    onChange={(e) =>
                      setAutoRefreshParams((prev) => ({ ...prev, [f.name]: e.target.value }))
                    }
                    placeholder={f.placeholder}
                    autoComplete="off"
                  />
                </div>
              ))}
              <label className="flex items-start gap-2 text-xs text-foreground cursor-pointer pt-1">
                <input
                  type="checkbox"
                  checked={autoRefreshAck}
                  onChange={(e) => setAutoRefreshAck(e.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  I understand my broker 2FA seed will be stored so the platform can log in for me,
                  and that a breach could expose my trading account.
                </span>
              </label>
            </div>

            <AlertDialogFooter>
              <AlertDialogCancel disabled={autoRefreshSaving}>Cancel</AlertDialogCancel>
              <Button
                onClick={handleEnableAutoRefresh}
                disabled={!autoRefreshAck || !autoRefreshSeed.trim() || autoRefreshSaving}
              >
                {autoRefreshSaving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Enabling…
                  </>
                ) : (
                  'Enable auto-login'
                )}
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        {/* Docs link footer (first-time layout only) */}
        {!isAddingAdditionalBroker && (
          <div className="flex items-center justify-center gap-1.5 mt-5 text-sm text-muted-foreground">
            <BookOpen className="h-4 w-4" />
            <span>Need help?</span>
            <a
              href="https://docs.maxalgos.in"
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-brand hover:underline inline-flex items-center gap-1"
            >
              Broker setup guides
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>
        )}
      </div>
    </div>
  )
}
