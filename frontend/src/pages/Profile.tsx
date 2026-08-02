import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  Bell,
  Calendar,
  Check,
  CheckCircle2,
  Copy,
  CreditCard,
  Eye,
  EyeOff,
  FileWarning,
  FolderCheck,
  Key,
  Lock,
  Mail,
  Moon,
  Palette,
  Power,
  RefreshCw,
  RotateCcw,
  Shield,
  Sun,
  User,
  Volume2,
  VolumeX,
  Wrench,
  X,
  XCircle,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { webClient } from '@/api/client'
import { type KillSwitchAuditEntry, type KillSwitchScope, killSwitchApi } from '@/api/killswitch'
import TwoFactorEnforcement from '@/components/auth/TwoFactorEnforcement'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  isMultiPartBroker,
  joinBrokerParts,
  MULTI_PART_BROKER_CONFIG,
} from '@/lib/brokerCredentials'
import { type AlertCategories, type ToastPosition, useAlertStore } from '@/stores/alertStore'
import { useAuthStore } from '@/stores/authStore'
import { type ThemeColor, type ThemeMode, useThemeStore } from '@/stores/themeStore'
import { showToast, toast } from '@/utils/toast'

// Professional themes suitable for trading terminals
const THEME_MODES: { value: ThemeMode; label: string; icon: typeof Sun; description: string }[] = [
  {
    value: 'light',
    label: 'Light',
    icon: Sun,
    description: 'Clean, bright interface for daytime trading',
  },
  {
    value: 'dark',
    label: 'Dark',
    icon: Moon,
    description: 'Reduced eye strain for extended sessions',
  },
]

// Accent colors for customization — every ThemeColor the store supports.
// Swatches use fixed preview colors (oklch matches the CSS accent overrides).
const ACCENT_COLORS: { value: ThemeColor; label: string; color: string }[] = [
  { value: 'zinc', label: 'Zinc', color: 'bg-zinc-500' },
  { value: 'slate', label: 'Slate', color: 'bg-slate-500' },
  { value: 'stone', label: 'Stone', color: 'bg-stone-500' },
  { value: 'gray', label: 'Gray', color: 'bg-gray-500' },
  { value: 'neutral', label: 'Neutral', color: 'bg-neutral-500' },
  { value: 'red', label: 'Red', color: 'bg-[oklch(0.55_0.2_25)]' },
  { value: 'rose', label: 'Rose', color: 'bg-[oklch(0.58_0.2_10)]' },
  { value: 'orange', label: 'Orange', color: 'bg-orange-500' },
  { value: 'green', label: 'Green', color: 'bg-[oklch(0.55_0.2_145)]' },
  { value: 'blue', label: 'Blue', color: 'bg-blue-500' },
  { value: 'yellow', label: 'Yellow', color: 'bg-[oklch(0.72_0.15_95)]' },
  { value: 'violet', label: 'Violet', color: 'bg-violet-500' },
]

interface ProfileData {
  username: string
  smtp_settings: {
    smtp_server: string
    smtp_port: number
    smtp_username: string
    smtp_password: boolean
    smtp_use_tls: boolean
    smtp_from_email: string
    smtp_helo_hostname: string
  } | null
  qr_code: string | null
  totp_secret: string | null
  // Public identity fields (never includes the internal uuid -- see
  // database/user_db.py User.to_public_dict())
  user_code?: string | null
  email?: string
  status?: string
  created_at?: string | null
  last_login_at?: string | null
}

interface BillingStatus {
  has_active_subscription: boolean
  plan: string | null
  subscription_status: string | null
  current_period_end: string | null
}

interface PasswordRequirements {
  length: boolean
  uppercase: boolean
  lowercase: boolean
  number: boolean
  special: boolean
}

interface BrokerCredentials {
  broker_api_key: string
  broker_api_key_raw_length: number
  broker_api_secret: string
  broker_api_secret_raw_length: number
  broker_api_key_market: string
  broker_api_key_market_raw_length: number
  broker_api_secret_market: string
  broker_api_secret_market_raw_length: number
  redirect_url: string
  current_broker: string
  valid_brokers: string[]
  ngrok_allow: boolean
  host_server: string
  websocket_url: string
  server_status?: {
    flask: { host: string; port: string }
    websocket: { host: string; port: string }
    zmq: { host: string; port: string }
  }
}

interface PermissionCheck {
  path: string
  full_path: string
  description: string
  exists: boolean
  expected_mode: string
  expected_rwx: string
  actual_mode: string | null
  actual_rwx: string | null
  is_correct: boolean
  is_sensitive: boolean
  is_directory?: boolean
  issue: string | null
  warning: string | null
}

interface PermissionsData {
  platform: string
  base_path: string
  is_windows: boolean
  all_correct: boolean
  checks: PermissionCheck[]
}

// Toast position options
const TOAST_POSITIONS: { value: ToastPosition; label: string }[] = [
  { value: 'top-left', label: 'Top Left' },
  { value: 'top-center', label: 'Top Center' },
  { value: 'top-right', label: 'Top Right' },
  { value: 'bottom-left', label: 'Bottom Left' },
  { value: 'bottom-center', label: 'Bottom Center' },
  { value: 'bottom-right', label: 'Bottom Right' },
]

// Alert category descriptions - organized by groups
const ALERT_CATEGORIES_REALTIME: {
  key: keyof AlertCategories
  label: string
  description: string
}[] = [
  {
    key: 'orders',
    label: 'Order Notifications',
    description: 'Real-time BUY/SELL order placement, cancellation, and modification alerts',
  },
  {
    key: 'analyzer',
    label: 'Analyzer Mode',
    description: 'Real-time sandbox/analyzer mode operation notifications',
  },
  {
    key: 'system',
    label: 'System Alerts',
    description: 'Password changes, master contract downloads, and system events',
  },
  {
    key: 'actionCenter',
    label: 'Control Center',
    description: 'Pending order notifications in semi-auto mode',
  },
]

const ALERT_CATEGORIES_TRADING: {
  key: keyof AlertCategories
  label: string
  description: string
}[] = [
  {
    key: 'positions',
    label: 'Positions',
    description: 'Position close/update operations and P&L notifications',
  },
  {
    key: 'strategy',
    label: 'Strategy Management',
    description: 'Strategy creation, symbol configuration, and webhook operations',
  },
  {
    key: 'chartink',
    label: 'Chartink',
    description: 'Chartink strategy operations and scanner integrations',
  },
  {
    key: 'maxhook',
    label: 'MaxHook',
    description: 'Signal connection creation, updates, and webhook management',
  },
]

const ALERT_CATEGORIES_DATA: {
  key: keyof AlertCategories
  label: string
  description: string
}[] = [
  {
    key: 'historify',
    label: 'Historify',
    description: 'Historical data jobs, file uploads, downloads, and schedules',
  },
  {
    key: 'pythonStrategy',
    label: 'Python Strategy',
    description: 'Python strategy uploads, execution, logs, and scheduling',
  },
  {
    key: 'flow',
    label: 'Flow Workflows',
    description: 'Visual workflow creation, execution, and management',
  },
]

const ALERT_CATEGORIES_ADMIN: {
  key: keyof AlertCategories
  label: string
  description: string
}[] = [
  {
    key: 'admin',
    label: 'Admin Panel',
    description: 'Market timings, holidays, freeze quantities, and admin settings',
  },
  {
    key: 'monitoring',
    label: 'Monitoring',
    description: 'Health monitor, latency dashboard, and security alerts',
  },
  {
    key: 'clipboard',
    label: 'Clipboard',
    description: 'Copy to clipboard confirmation messages',
  },
]

export default function ProfilePage() {
  const user = useAuthStore((s) => s.user)
  const isAdmin = useAuthStore((s) => s.isAdmin)
  const { mode, color, appMode, setMode, setColor } = useThemeStore()
  const alertStore = useAlertStore()
  const [activeTab, setActiveTab] = useState('account')
  const [isLoading, setIsLoading] = useState(true)
  const [profileData, setProfileData] = useState<ProfileData | null>(null)
  const [billingStatus, setBillingStatus] = useState<BillingStatus | null>(null)
  const [isBillingLoading, setIsBillingLoading] = useState(true)

  // Kill switch scope settings + recent activity
  const [killSwitchScope, setKillSwitchScope] = useState<KillSwitchScope | null>(null)
  const [isSavingKillSwitchScope, setIsSavingKillSwitchScope] = useState(false)
  const [killSwitchAudit, setKillSwitchAudit] = useState<KillSwitchAuditEntry[]>([])
  const [isLoadingKillSwitchAudit, setIsLoadingKillSwitchAudit] = useState(false)

  const loadKillSwitchTab = useCallback(async () => {
    setIsLoadingKillSwitchAudit(true)
    try {
      const [scope, audit] = await Promise.all([
        killSwitchApi.getScope(),
        killSwitchApi.getAudit(20),
      ])
      setKillSwitchScope(scope)
      setKillSwitchAudit(audit)
    } finally {
      setIsLoadingKillSwitchAudit(false)
    }
  }, [])

  const handleKillSwitchScopeChange = async (next: KillSwitchScope) => {
    setKillSwitchScope(next)
    setIsSavingKillSwitchScope(true)
    try {
      const result = await killSwitchApi.setScope(next)
      if (result.success) {
        showToast.success('Kill switch settings updated', 'strategy')
      } else {
        showToast.error(result.message || 'Failed to update kill switch settings', 'strategy')
      }
    } finally {
      setIsSavingKillSwitchScope(false)
    }
  }

  // Password form state
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordRequirements, setPasswordRequirements] = useState<PasswordRequirements>({
    length: false,
    uppercase: false,
    lowercase: false,
    number: false,
    special: false,
  })
  const [isChangingPassword, setIsChangingPassword] = useState(false)

  // Broker credentials state
  const [brokerCredentials, setBrokerCredentials] = useState<BrokerCredentials | null>(null)
  const [brokerApiKey, setBrokerApiKey] = useState('')
  // Per-part values for brokers whose API key is really N `:::`-joined
  // fields (Zebu, BNR, Flattrade, Dhan, 5paisa). The backend never returns
  // the raw stored key here (only a masked preview), so these always start
  // blank - there is nothing to split on broker switch, only to join on edit.
  const [keyParts, setKeyParts] = useState<string[]>([])
  const [brokerApiSecret, setBrokerApiSecret] = useState('')
  const [brokerApiKeyMarket, setBrokerApiKeyMarket] = useState('')
  const [brokerApiSecretMarket, setBrokerApiSecretMarket] = useState('')
  const [selectedBroker, setSelectedBroker] = useState('')
  const [ngrokEnabled, setNgrokEnabled] = useState(false)
  const [hostServer, setHostServer] = useState('')
  const [websocketUrl, setWebsocketUrl] = useState('')
  const [isSavingBroker, setIsSavingBroker] = useState(false)
  const [isSavingNgrok, setIsSavingNgrok] = useState(false)
  const [showRestartDialog, setShowRestartDialog] = useState(false)
  const [showApiKey, setShowApiKey] = useState(false)
  const [showApiSecret, setShowApiSecret] = useState(false)

  // Permissions state
  const [permissionsData, setPermissionsData] = useState<PermissionsData | null>(null)
  const [isLoadingPermissions, setIsLoadingPermissions] = useState(false)
  const [isFixingPermissions, setIsFixingPermissions] = useState(false)

  // Check if in analyzer mode (theme changes blocked)
  const isAnalyzerMode = appMode === 'analyzer'

  // biome-ignore lint/correctness/useExhaustiveDependencies: one-time data load on mount; fetchProfileData/fetchBrokerCredentials/fetchBillingStatus are stable per-render fetchers and must not refire when their closures are recreated.
  useEffect(() => {
    fetchProfileData()
    fetchBrokerCredentials()
    fetchBillingStatus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchBillingStatus = async () => {
    setIsBillingLoading(true)
    try {
      const response = await webClient.get<{ status: string; data: BillingStatus }>(
        '/payments/subscription/status'
      )
      if (response.data.status === 'success') {
        setBillingStatus(response.data.data)
      }
    } catch (_error) {
      // Billing tab shows its own "couldn't load" state; no toast needed
      // since this isn't the tab the user necessarily has open.
    } finally {
      setIsBillingLoading(false)
    }
  }

  const fetchProfileData = async () => {
    try {
      const response = await webClient.get<{ status: string; data: ProfileData }>(
        '/auth/profile-data'
      )
      if (response.data.status === 'success') {
        setProfileData(response.data.data)
        // Note: smtp_settings is still fetched here (used only to decide
        // whether the SMTP tab trigger renders for admins) -- the actual
        // SMTP form fields it used to seed were removed when this tab was
        // retired in favor of /admin/email.
      }
    } catch (_error) {
      showToast.error('Failed to load profile data', 'admin')
    } finally {
      setIsLoading(false)
    }
  }

  const fetchBrokerCredentials = async () => {
    try {
      const response = await webClient.get<{ status: string; data: BrokerCredentials }>(
        '/api/broker/credentials'
      )
      if (response.data.status === 'success') {
        setBrokerCredentials(response.data.data)
        setSelectedBroker(response.data.data.current_broker)
        setNgrokEnabled(response.data.data.ngrok_allow)
        setHostServer(response.data.data.host_server)
        setWebsocketUrl(response.data.data.websocket_url || '')
      }
    } catch (_error) {}
  }

  const fetchPermissions = async () => {
    setIsLoadingPermissions(true)
    try {
      const response = await webClient.get<{ status: string; data: PermissionsData }>(
        '/api/system/permissions'
      )
      if (response.data.status === 'success') {
        setPermissionsData(response.data.data)
      }
    } catch (_error) {
      showToast.error('Failed to load permission status', 'admin')
    } finally {
      setIsLoadingPermissions(false)
    }
  }

  const handleFixPermissions = async () => {
    setIsFixingPermissions(true)
    try {
      const response = await webClient.post<{
        status: string
        data: {
          fixed: Array<{ path: string; action: string }>
          failed: Array<{ path: string; error: string }>
          message: string
        }
      }>('/api/system/permissions/fix')

      if (response.data.status === 'success') {
        const { fixed, failed, message } = response.data.data
        if (fixed.length > 0) {
          showToast.success(`Fixed ${fixed.length} permission issues`, 'admin')
        }
        if (failed.length > 0) {
          showToast.warning(`${failed.length} issues could not be fixed automatically`, 'admin')
        }
        if (fixed.length === 0 && failed.length === 0) {
          showToast.info(message, 'admin')
        }
        // Refresh permissions after fix
        await fetchPermissions()
      } else {
        showToast.error('Failed to fix permissions', 'admin')
      }
    } catch (_error) {
      showToast.error('Failed to fix permissions', 'admin')
    } finally {
      setIsFixingPermissions(false)
    }
  }

  const getRedirectUrl = (broker: string): string => {
    // Extract host from current redirect URL or use default
    const currentUrl = brokerCredentials?.redirect_url || 'http://127.0.0.1:5000'
    const match = currentUrl.match(/^(https?:\/\/[^/]+)/)
    const host = match ? match[1] : 'http://127.0.0.1:5000'
    return `${host}/${broker}/callback`
  }

  const handleBrokerSave = async () => {
    setIsSavingBroker(true)
    try {
      const formData = new FormData()
      if (brokerApiKey) formData.append('broker_api_key', brokerApiKey)
      if (brokerApiSecret) formData.append('broker_api_secret', brokerApiSecret)
      if (brokerApiKeyMarket) formData.append('broker_api_key_market', brokerApiKeyMarket)
      if (brokerApiSecretMarket) formData.append('broker_api_secret_market', brokerApiSecretMarket)
      if (selectedBroker && selectedBroker !== brokerCredentials?.current_broker) {
        formData.append('redirect_url', getRedirectUrl(selectedBroker))
      }

      const response = await webClient.post<{
        status: string
        message: string
        restart_required?: boolean
      }>('/api/broker/credentials', formData)

      if (response.data.status === 'success') {
        showToast.success(response.data.message, 'admin')
        // Update local state to reflect saved values (don't re-fetch since env vars won't update until restart)
        if (brokerCredentials) {
          setBrokerCredentials({
            ...brokerCredentials,
            current_broker: selectedBroker || brokerCredentials.current_broker,
            redirect_url:
              selectedBroker !== brokerCredentials.current_broker
                ? getRedirectUrl(selectedBroker)
                : brokerCredentials.redirect_url,
            // Update masked values to show something was changed.
            // Use a FIXED-length mask (prefix + 8 asterisks) so the rendered
            // value cannot leak the secret's true length and cannot overflow
            // the column layout. Mirrors blueprints/broker_credentials.py:mask_secret.
            broker_api_key: brokerApiKey
              ? `${brokerApiKey.slice(0, 6)}${'*'.repeat(8)}`
              : brokerCredentials.broker_api_key,
            broker_api_key_raw_length: brokerApiKey
              ? brokerApiKey.length
              : brokerCredentials.broker_api_key_raw_length,
            broker_api_secret: brokerApiSecret
              ? `${brokerApiSecret.slice(0, 4)}${'*'.repeat(8)}`
              : brokerCredentials.broker_api_secret,
            broker_api_secret_raw_length: brokerApiSecret
              ? brokerApiSecret.length
              : brokerCredentials.broker_api_secret_raw_length,
          })
        }
        // Clear form fields
        setBrokerApiKey('')
        setBrokerApiSecret('')
        setBrokerApiKeyMarket('')
        setBrokerApiSecretMarket('')
        // Show restart dialog
        setShowRestartDialog(true)
      } else {
        showToast.error(response.data.message || 'Failed to save credentials', 'admin')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to save broker credentials', 'admin')
    } finally {
      setIsSavingBroker(false)
    }
  }

  const hasCredentialChanges = Boolean(
    brokerApiKey ||
      brokerApiSecret ||
      brokerApiKeyMarket ||
      brokerApiSecretMarket ||
      (selectedBroker && selectedBroker !== brokerCredentials?.current_broker)
  )

  const hasNgrokChanges = Boolean(
    ngrokEnabled !== brokerCredentials?.ngrok_allow ||
      (hostServer && hostServer !== brokerCredentials?.host_server) ||
      (websocketUrl && websocketUrl !== brokerCredentials?.websocket_url)
  )

  const handleNgrokSave = async () => {
    setIsSavingNgrok(true)
    try {
      // Send as JSON for more reliable handling
      const payload: {
        ngrok_allow: string
        host_server?: string
        websocket_url?: string
      } = {
        ngrok_allow: ngrokEnabled ? 'TRUE' : 'FALSE',
      }
      if (hostServer) {
        payload.host_server = hostServer
      }
      if (websocketUrl) {
        payload.websocket_url = websocketUrl
      }

      const response = await webClient.post<{
        status: string
        message: string
        restart_required?: boolean
      }>('/api/broker/credentials', payload)

      if (response.data.status === 'success') {
        showToast.success(response.data.message, 'admin')
        // Update local brokerCredentials state to reflect saved values
        // Don't re-fetch from server since env vars won't update until restart
        if (brokerCredentials) {
          setBrokerCredentials({
            ...brokerCredentials,
            ngrok_allow: ngrokEnabled,
            host_server: hostServer || brokerCredentials.host_server,
            websocket_url: websocketUrl || brokerCredentials.websocket_url,
          })
        }
        // Show restart dialog
        setShowRestartDialog(true)
      } else {
        showToast.error(response.data.message || 'Failed to save settings', 'admin')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to save settings', 'admin')
    } finally {
      setIsSavingNgrok(false)
    }
  }

  // Password validation
  const checkPasswordRequirements = useCallback((password: string) => {
    const requirements: PasswordRequirements = {
      length: password.length >= 8,
      uppercase: /[A-Z]/.test(password),
      lowercase: /[a-z]/.test(password),
      number: /[0-9]/.test(password),
      // Any non-alphanumeric counts as a special character (matches backend)
      special: /[^A-Za-z0-9]/.test(password),
    }
    setPasswordRequirements(requirements)
    return Object.values(requirements).every(Boolean)
  }, [])

  useEffect(() => {
    checkPasswordRequirements(newPassword)
  }, [newPassword, checkPasswordRequirements])

  const getPasswordStrength = () => {
    const metCount = Object.values(passwordRequirements).filter(Boolean).length
    if (metCount === 0) return { percentage: 0, label: 'None', color: 'bg-gray-400' }
    if (metCount <= 2) return { percentage: 40, label: 'Weak', color: 'bg-loss' }
    if (metCount <= 3) return { percentage: 60, label: 'Fair', color: 'bg-warning' }
    if (metCount <= 4) return { percentage: 80, label: 'Good', color: 'bg-blue-500' }
    return { percentage: 100, label: 'Strong', color: 'bg-profit' }
  }

  const passwordsMatch = newPassword === confirmPassword && confirmPassword !== ''
  const meetsAllRequirements = Object.values(passwordRequirements).every(Boolean)
  const canSubmitPassword = passwordsMatch && meetsAllRequirements && oldPassword !== ''

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmitPassword) return

    setIsChangingPassword(true)
    try {
      const formData = new FormData()
      formData.append('old_password', oldPassword)
      formData.append('new_password', newPassword)
      formData.append('confirm_password', confirmPassword)

      const response = await webClient.post<{ status: string; message: string }>(
        '/auth/change-password',
        formData
      )

      if (response.data.status === 'success') {
        showToast.success(response.data.message || 'Password changed successfully', 'system')
        setOldPassword('')
        setNewPassword('')
        setConfirmPassword('')
      } else {
        showToast.error(response.data.message || 'Failed to change password', 'system')
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { message?: string } } }
      showToast.error(err.response?.data?.message || 'Failed to change password', 'system')
    } finally {
      setIsChangingPassword(false)
    }
  }

  const handleThemeModeChange = (newMode: ThemeMode) => {
    if (isAnalyzerMode) {
      showToast.error('Cannot change theme while in Analyzer Mode', 'system')
      return
    }
    setMode(newMode)
    showToast.success(`Theme changed to ${newMode}`, 'system')
  }

  const handleAccentColorChange = (newColor: ThemeColor) => {
    if (isAnalyzerMode) {
      showToast.error('Cannot change theme while in Analyzer Mode', 'system')
      return
    }
    setColor(newColor)
    showToast.success(`Accent color changed to ${newColor}`, 'system')
  }

  const handleResetTheme = () => {
    if (isAnalyzerMode) {
      showToast.error('Cannot change theme while in Analyzer Mode', 'system')
      return
    }
    setMode('light')
    setColor('zinc')
    showToast.success('Theme reset to default', 'system')
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard
      .writeText(text)
      .then(() => {
        showToast.success('Copied to clipboard', 'clipboard')
      })
      .catch(() => {
        showToast.error('Failed to copy', 'clipboard')
      })
  }

  // Zebu, BNR, Flattrade, Dhan, and 5paisa render split per-part inputs
  // instead (see isMultiPartBroker below), so this only needs a default.
  const getApiKeyPlaceholder = () => 'Enter new API key'

  const updateKeyPart = (index: number, value: string) => {
    setKeyParts((prev) => {
      const next = [...prev]
      next[index] = value
      setBrokerApiKey(joinBrokerParts(next))
      return next
    })
  }

  const strength = getPasswordStrength()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  return (
    <div className="py-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <Link to="/dashboard" className="text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <User className="h-5 w-5" />
            Settings
          </h1>
        </div>
        <p className="text-muted-foreground">
          Manage your account, broker credentials, alerts, appearance and security
        </p>
      </div>

      {/* Tabs */}
      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          setActiveTab(value)
          // Always re-fetch permissions when the tab is opened so the view
          // never shows a stale snapshot from a previous visit
          if (value === 'permissions') {
            fetchPermissions()
          }
          if (value === 'killswitch') {
            loadKillSwitchTab()
          }
        }}
      >
        <TabsList className="w-full h-auto flex flex-wrap justify-start gap-1">
          <TabsTrigger value="account" className="gap-1">
            <Lock className="h-4 w-4" />
            <span>Account</span>
          </TabsTrigger>
          <TabsTrigger value="billing" className="gap-1">
            <CreditCard className="h-4 w-4" />
            <span>Billing</span>
          </TabsTrigger>
          <TabsTrigger value="broker" className="gap-1">
            <Key className="h-4 w-4" />
            <span>Broker</span>
          </TabsTrigger>
          <TabsTrigger value="alerts" className="gap-1">
            <Bell className="h-4 w-4" />
            <span>Alerts</span>
          </TabsTrigger>
          <TabsTrigger value="permissions" className="gap-1">
            <FolderCheck className="h-4 w-4" />
            <span>System</span>
          </TabsTrigger>
          <TabsTrigger value="theme" className="gap-1">
            <Palette className="h-4 w-4" />
            <span>Theme</span>
          </TabsTrigger>
          {/* SMTP is a platform-wide admin setting (see /admin/email) --
              the backend only returns smtp_settings for admins, so this tab
              self-hides for everyone else rather than showing a form that
              would just 403 on save. */}
          {profileData?.smtp_settings && (
            <TabsTrigger value="smtp" className="gap-1">
              <Mail className="h-4 w-4" />
              <span>SMTP</span>
            </TabsTrigger>
          )}
          <TabsTrigger value="totp" className="gap-1">
            <Shield className="h-4 w-4" />
            <span>TOTP</span>
          </TabsTrigger>
          <TabsTrigger value="killswitch" className="gap-1">
            <Power className="h-4 w-4" />
            <span>Kill Switch</span>
          </TabsTrigger>
        </TabsList>

        {/* Account Tab */}
        <TabsContent value="account" className="space-y-6">
          {/* Account Info */}
          <Card>
            <CardHeader>
              <CardTitle>Account Information</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-4">
              {profileData?.user_code && (
                <div className="space-y-2">
                  <Label>User ID</Label>
                  <Input value={profileData.user_code} disabled className="font-mono" />
                </div>
              )}
              <div className="space-y-2">
                <Label>Username</Label>
                <Input value={user?.username || profileData?.username || ''} disabled />
              </div>
              {profileData?.email && (
                <div className="space-y-2">
                  <Label>Email</Label>
                  <Input value={profileData.email} disabled />
                </div>
              )}
              {profileData?.created_at && (
                <div className="space-y-2">
                  <Label>Joined</Label>
                  <Input
                    value={new Date(profileData.created_at).toLocaleDateString(undefined, {
                      year: 'numeric',
                      month: 'long',
                      day: 'numeric',
                    })}
                    disabled
                  />
                </div>
              )}
              <div className="space-y-2">
                <Label>Account Type</Label>
                <div className="pt-2">
                  {/* Was hardcoded to always show "Administrator" regardless
                      of the actual role -- now reflects the real is_admin
                      flag from the session (see authStore.isAdmin, sourced
                      from /auth/session-status). */}
                  <Badge variant={isAdmin ? 'default' : 'secondary'}>
                    {isAdmin ? 'Administrator' : 'User'}
                  </Badge>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Password Change */}
          <Card>
            <CardHeader>
              <CardTitle>Change Password</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleChangePassword} className="space-y-4">
                <div className="space-y-2">
                  <Label>Current Password</Label>
                  <Input
                    type="password"
                    placeholder="Enter your current password"
                    value={oldPassword}
                    onChange={(e) => setOldPassword(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label>New Password</Label>
                  <Input
                    type="password"
                    placeholder="Enter your new password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label>Confirm New Password</Label>
                  <Input
                    type="password"
                    placeholder="Confirm your new password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                  />
                  {confirmPassword && (
                    <p className={`text-sm ${passwordsMatch ? 'text-profit' : 'text-loss'}`}>
                      {passwordsMatch ? 'Passwords match' : 'Passwords do not match'}
                    </p>
                  )}
                </div>

                {/* Password Strength */}
                <div className="bg-muted rounded-lg p-4 space-y-3">
                  <div className="flex justify-between text-sm">
                    <span>Strength</span>
                    <span className="font-medium">{strength.label}</span>
                  </div>
                  <Progress value={strength.percentage} className={strength.color} />

                  <div className="grid grid-cols-2 gap-2 text-xs">
                    {Object.entries(passwordRequirements).map(([key, met]) => (
                      <div
                        key={key}
                        className={`flex items-center gap-1 px-2 py-1 rounded-full border ${
                          met
                            ? 'bg-profit/10 border-profit text-profit'
                            : 'bg-muted border-border text-muted-foreground'
                        }`}
                      >
                        {met ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
                        <span>
                          {key === 'length' && '8+ chars'}
                          {key === 'uppercase' && 'A-Z'}
                          {key === 'lowercase' && 'a-z'}
                          {key === 'number' && '0-9'}
                          {key === 'special' && 'Special (@#$%^&*)'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                <Button type="submit" disabled={!canSubmitPassword || isChangingPassword}>
                  {isChangingPassword ? (
                    <>
                      <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                      Changing...
                    </>
                  ) : (
                    <>
                      <Lock className="h-4 w-4 mr-2" />
                      Change Password
                    </>
                  )}
                </Button>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Billing Tab */}
        <TabsContent value="billing" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Subscription</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {isBillingLoading ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  Loading subscription details...
                </div>
              ) : !billingStatus ? (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle>Couldn't load billing details</AlertTitle>
                  <AlertDescription>
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-2"
                      onClick={fetchBillingStatus}
                    >
                      <RefreshCw className="h-4 w-4 mr-2" />
                      Retry
                    </Button>
                  </AlertDescription>
                </Alert>
              ) : billingStatus.has_active_subscription ? (
                <>
                  <div className="flex items-center justify-between">
                    <div className="space-y-1">
                      <Label>Status</Label>
                      <div>
                        <Badge
                          variant={
                            billingStatus.subscription_status === 'active' ? 'default' : 'secondary'
                          }
                          className="gap-1"
                        >
                          <CreditCard className="h-3 w-3" />
                          {billingStatus.subscription_status === 'past_due' ? 'Past due' : 'Active'}
                        </Badge>
                      </div>
                    </div>
                    {billingStatus.plan && (
                      <div className="space-y-1 text-right">
                        <Label>Plan</Label>
                        <p className="text-sm font-medium capitalize">{billingStatus.plan}</p>
                      </div>
                    )}
                  </div>

                  {billingStatus.subscription_status === 'past_due' && (
                    <Alert variant="destructive">
                      <AlertTriangle className="h-4 w-4" />
                      <AlertTitle>Payment past due</AlertTitle>
                      <AlertDescription>
                        Your last renewal charge failed. Access continues during this grace period,
                        but please update your payment method to avoid interruption.
                      </AlertDescription>
                    </Alert>
                  )}

                  {billingStatus.current_period_end && (
                    <div className="space-y-2">
                      <Label className="flex items-center gap-1.5">
                        <Calendar className="h-3.5 w-3.5" />
                        Next renewal
                      </Label>
                      <Input
                        disabled
                        value={new Date(billingStatus.current_period_end).toLocaleDateString(
                          undefined,
                          { year: 'numeric', month: 'long', day: 'numeric' }
                        )}
                      />
                      <p className="text-xs text-muted-foreground">
                        Your subscription renews automatically via Razorpay on this date.
                      </p>
                    </div>
                  )}
                </>
              ) : (
                <div className="space-y-4">
                  <Alert>
                    <AlertCircle className="h-4 w-4" />
                    <AlertTitle>No active subscription</AlertTitle>
                    <AlertDescription>
                      You don't currently have an active platform subscription.
                    </AlertDescription>
                  </Alert>
                  <Button asChild>
                    <Link to="/subscribe">
                      <CreditCard className="h-4 w-4 mr-2" />
                      Subscribe now
                    </Link>
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Broker Tab */}
        <TabsContent value="broker" className="space-y-6">
          <Alert>
            <Key className="h-4 w-4" />
            <AlertTitle>Broker API Credentials</AlertTitle>
            <AlertDescription>
              Update your broker API credentials. Changes require an application restart to take
              effect. You will be logged out after saving.
            </AlertDescription>
          </Alert>

          {/* Current Broker */}
          <Card>
            <CardHeader>
              <CardTitle>Current Configuration</CardTitle>
              <CardDescription>Your currently configured broker and credentials</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Current Broker</Label>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-base">
                      {brokerCredentials?.current_broker?.toUpperCase() || 'Not configured'}
                    </Badge>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>Redirect URL</Label>
                  <code className="text-xs text-muted-foreground break-all">
                    {brokerCredentials?.redirect_url || 'Not configured'}
                  </code>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4 pt-2">
                <div className="space-y-2 min-w-0">
                  <Label>API Key</Label>
                  {/* block truncate clamps long masked values to their column;
                      backend mask is fixed-length but defence-in-depth in case
                      a future change emits a longer string. */}
                  <code className="block truncate text-xs text-muted-foreground">
                    {brokerCredentials?.broker_api_key || '(not set)'}
                  </code>
                </div>
                <div className="space-y-2 min-w-0">
                  <Label>API Secret</Label>
                  <code className="block truncate text-xs text-muted-foreground">
                    {brokerCredentials?.broker_api_secret || '(not set)'}
                  </code>
                </div>
              </div>
              {(brokerCredentials?.broker_api_key_market_raw_length ?? 0) > 0 && (
                <div className="grid grid-cols-2 gap-4 pt-2">
                  <div className="space-y-2 min-w-0">
                    <Label>Market API Key</Label>
                    <code className="block truncate text-xs text-muted-foreground">
                      {brokerCredentials?.broker_api_key_market || '(not set)'}
                    </code>
                  </div>
                  <div className="space-y-2 min-w-0">
                    <Label>Market API Secret</Label>
                    <code className="block truncate text-xs text-muted-foreground">
                      {brokerCredentials?.broker_api_secret_market || '(not set)'}
                    </code>
                  </div>
                </div>
              )}
              <div className="grid grid-cols-2 gap-4 pt-2 border-t">
                <div className="space-y-2">
                  <Label>Ngrok Status</Label>
                  <Badge variant={brokerCredentials?.ngrok_allow ? 'default' : 'secondary'}>
                    {brokerCredentials?.ngrok_allow ? 'Enabled' : 'Disabled'}
                  </Badge>
                </div>
                <div className="space-y-2">
                  <Label>Host Server</Label>
                  <code className="text-xs text-muted-foreground break-all">
                    {brokerCredentials?.host_server || '(not set)'}
                  </code>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Update Credentials */}
          <Card>
            <CardHeader>
              <CardTitle>Update Credentials</CardTitle>
              <CardDescription>
                Enter new values to update. Leave fields empty to keep existing values.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Broker Selection */}
              <div className="space-y-2">
                <Label>Select Broker</Label>
                <Select
                  value={selectedBroker}
                  onValueChange={(value) => {
                    setSelectedBroker(value)
                    // Key format/part-count differs per broker, so a
                    // half-typed value for the previous broker can't carry over.
                    setBrokerApiKey('')
                    setKeyParts([])
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select a broker" />
                  </SelectTrigger>
                  <SelectContent>
                    {brokerCredentials?.valid_brokers.map((broker) => (
                      <SelectItem key={broker} value={broker}>
                        {broker.charAt(0).toUpperCase() + broker.slice(1)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selectedBroker && selectedBroker !== brokerCredentials?.current_broker && (
                  <p className="text-sm text-warning">
                    Changing broker to: {selectedBroker.toUpperCase()}
                  </p>
                )}
              </div>

              {/* API Credentials */}
              <div
                className={
                  isMultiPartBroker(selectedBroker) ? 'space-y-4' : 'grid grid-cols-2 gap-4'
                }
              >
                <div className="space-y-2">
                  <Label>Broker API Key</Label>
                  {isMultiPartBroker(selectedBroker) ? (
                    // Multi-part API key (Zebu, BNR, Flattrade, Dhan, 5paisa) - one
                    // labeled input per part instead of asking the user to type the
                    // ":::" separator themselves. Parts are joined into brokerApiKey
                    // on every change, so save logic below is unaffected.
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
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
                  ) : (
                    <div className="relative">
                      <Input
                        type={showApiKey ? 'text' : 'password'}
                        value={brokerApiKey}
                        onChange={(e) => setBrokerApiKey(e.target.value)}
                        placeholder={getApiKeyPlaceholder()}
                        className="pr-10"
                      />
                      <button
                        type="button"
                        onClick={() => setShowApiKey(!showApiKey)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      >
                        {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    </div>
                  )}
                  <p className="text-xs text-muted-foreground">
                    {(brokerCredentials?.broker_api_key_raw_length ?? 0) > 0
                      ? `Current: ${brokerCredentials?.broker_api_key_raw_length} chars`
                      : 'Not currently set'}
                  </p>
                </div>
                <div className="space-y-2">
                  <Label>Broker API Secret</Label>
                  <div className="relative">
                    <Input
                      type={showApiSecret ? 'text' : 'password'}
                      value={brokerApiSecret}
                      onChange={(e) => setBrokerApiSecret(e.target.value)}
                      placeholder="Enter new API secret"
                      className="pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowApiSecret(!showApiSecret)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      {showApiSecret ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {(brokerCredentials?.broker_api_secret_raw_length ?? 0) > 0
                      ? `Current: ${brokerCredentials?.broker_api_secret_raw_length} chars`
                      : 'Not currently set'}
                  </p>
                </div>
              </div>

              {/* Market API Credentials (optional) */}
              <div className="pt-4 border-t">
                <h4 className="font-medium mb-3">Market Data API (Optional)</h4>
                <p className="text-sm text-muted-foreground mb-4">
                  Required only for XTS API supported brokers (e.g., 5paisa XTS, Jainam XTS)
                </p>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Market API Key</Label>
                    <Input
                      type="password"
                      value={brokerApiKeyMarket}
                      onChange={(e) => setBrokerApiKeyMarket(e.target.value)}
                      placeholder="Enter market API key"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Market API Secret</Label>
                    <Input
                      type="password"
                      value={brokerApiSecretMarket}
                      onChange={(e) => setBrokerApiSecretMarket(e.target.value)}
                      placeholder="Enter market API secret"
                    />
                  </div>
                </div>
              </div>

              {/* 5paisa, Flattrade, and Dhan format hints removed - their
                  split per-part inputs above make the format self-evident. */}

              {/* Save Button */}
              <Button
                onClick={handleBrokerSave}
                disabled={!hasCredentialChanges || isSavingBroker}
                className="w-full"
              >
                {isSavingBroker ? (
                  <>
                    <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <Key className="h-4 w-4 mr-2" />
                    Save Broker Credentials
                  </>
                )}
              </Button>
            </CardContent>
          </Card>

          {/* Server Status Card */}
          {brokerCredentials?.server_status && (
            <Card>
              <CardHeader>
                <CardTitle>Server Status</CardTitle>
                <CardDescription>Running services and their configured ports</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-3 gap-4">
                  <div className="flex flex-col items-center p-3 bg-muted rounded-lg">
                    <Badge variant="default" className="mb-2 bg-profit">
                      Running
                    </Badge>
                    <span className="text-sm font-medium">Flask App</span>
                    <span className="text-xs text-muted-foreground">
                      {brokerCredentials.server_status.flask.host}:
                      {brokerCredentials.server_status.flask.port}
                    </span>
                  </div>
                  <div className="flex flex-col items-center p-3 bg-muted rounded-lg">
                    <Badge variant="default" className="mb-2 bg-profit">
                      Running
                    </Badge>
                    <span className="text-sm font-medium">WebSocket</span>
                    <span className="text-xs text-muted-foreground">
                      {brokerCredentials.server_status.websocket.host}:
                      {brokerCredentials.server_status.websocket.port}
                    </span>
                  </div>
                  <div className="flex flex-col items-center p-3 bg-muted rounded-lg">
                    <Badge variant="default" className="mb-2 bg-profit">
                      Running
                    </Badge>
                    <span className="text-sm font-medium">ZeroMQ</span>
                    <span className="text-xs text-muted-foreground">
                      {brokerCredentials.server_status.zmq.host}:
                      {brokerCredentials.server_status.zmq.port}
                    </span>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Ngrok Configuration - Separate Card */}
          <Card>
            <CardHeader>
              <CardTitle>Server Configuration</CardTitle>
              <CardDescription>
                Configure ngrok for receiving webhook alerts from external services like
                TradingView, Chartink, GoCharting, etc.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="ngrok_enabled"
                  checked={ngrokEnabled}
                  onCheckedChange={(checked) => setNgrokEnabled(checked === true)}
                />
                <Label htmlFor="ngrok_enabled">Enable Ngrok Tunnel</Label>
                {ngrokEnabled !== brokerCredentials?.ngrok_allow && (
                  <Badge variant="outline" className="text-warning">
                    Changed
                  </Badge>
                )}
              </div>

              <div className="space-y-2">
                <Label>Host Server URL</Label>
                <Input
                  value={hostServer}
                  onChange={(e) => setHostServer(e.target.value)}
                  placeholder="https://your-domain.ngrok-free.app"
                />
                <p className="text-xs text-muted-foreground">
                  Your ngrok domain or custom domain for receiving webhooks.
                </p>
                {hostServer !== brokerCredentials?.host_server && hostServer && (
                  <Badge variant="outline" className="text-warning">
                    Changed from: {brokerCredentials?.host_server}
                  </Badge>
                )}
              </div>

              <div className="space-y-2">
                <Label>WebSocket URL</Label>
                <Input
                  value={websocketUrl}
                  onChange={(e) => setWebsocketUrl(e.target.value)}
                  placeholder="ws://127.0.0.1:8765"
                />
                <p className="text-xs text-muted-foreground">
                  WebSocket server URL for real-time market data streaming.
                </p>
                {websocketUrl !== brokerCredentials?.websocket_url && websocketUrl && (
                  <Badge variant="outline" className="text-warning">
                    Changed from: {brokerCredentials?.websocket_url}
                  </Badge>
                )}
              </div>

              <Button
                onClick={handleNgrokSave}
                disabled={!hasNgrokChanges || isSavingNgrok}
                className="w-full"
              >
                {isSavingNgrok ? (
                  <>
                    <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <RefreshCw className="h-4 w-4 mr-2" />
                    Save Ngrok Settings
                  </>
                )}
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Alerts Tab */}
        <TabsContent value="alerts" className="space-y-6">
          <Alert>
            <Bell className="h-4 w-4" />
            <AlertTitle>Toast Notification Settings</AlertTitle>
            <AlertDescription>
              Configure how toast notifications appear. Useful for power users running multiple
              strategies who want to reduce notification spam.
            </AlertDescription>
          </Alert>

          {/* Master Controls */}
          <Card>
            <CardHeader>
              <CardTitle>Master Controls</CardTitle>
              <CardDescription>
                Enable or disable all toast notifications and sounds
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Toasts Enabled */}
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="toasts-enabled">Toast Notifications</Label>
                  <p className="text-sm text-muted-foreground">
                    Show popup notifications for events
                  </p>
                </div>
                <Switch
                  id="toasts-enabled"
                  checked={alertStore.toastsEnabled}
                  onCheckedChange={alertStore.setToastsEnabled}
                />
              </div>

              {/* Sound Enabled */}
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label htmlFor="sound-enabled" className="flex items-center gap-2">
                    {alertStore.soundEnabled ? (
                      <Volume2 className="h-4 w-4" />
                    ) : (
                      <VolumeX className="h-4 w-4" />
                    )}
                    Sound Alerts
                  </Label>
                  <p className="text-sm text-muted-foreground">
                    Play audio alert for important events
                  </p>
                </div>
                <Switch
                  id="sound-enabled"
                  checked={alertStore.soundEnabled}
                  onCheckedChange={alertStore.setSoundEnabled}
                />
              </div>
            </CardContent>
          </Card>

          {/* Display Settings */}
          <Card className={!alertStore.toastsEnabled ? 'opacity-60' : ''}>
            <CardHeader>
              <CardTitle>Display Settings</CardTitle>
              <CardDescription>Customize toast appearance and behavior</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Position */}
              <div className="space-y-2">
                <Label>Toast Position</Label>
                <Select
                  value={alertStore.position}
                  onValueChange={(value) => alertStore.setPosition(value as ToastPosition)}
                  disabled={!alertStore.toastsEnabled}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select position" />
                  </SelectTrigger>
                  <SelectContent>
                    {TOAST_POSITIONS.map((pos) => (
                      <SelectItem key={pos.value} value={pos.value}>
                        {pos.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Max Visible Toasts */}
              <div className="space-y-2">
                <Label>Maximum Visible Toasts</Label>
                <div className="flex items-center gap-4">
                  <Input
                    type="number"
                    min={1}
                    max={10}
                    value={alertStore.maxVisibleToasts}
                    onChange={(e) => alertStore.setMaxVisibleToasts(Number(e.target.value))}
                    disabled={!alertStore.toastsEnabled}
                    className="w-24"
                  />
                  <span className="text-sm text-muted-foreground">
                    (1-10) Additional toasts will be queued
                  </span>
                </div>
              </div>

              {/* Duration */}
              <div className="space-y-2">
                <Label>Auto-dismiss Duration</Label>
                <div className="flex items-center gap-4">
                  <Input
                    type="number"
                    min={1}
                    max={15}
                    value={alertStore.duration / 1000}
                    onChange={(e) => alertStore.setDuration(Number(e.target.value) * 1000)}
                    disabled={!alertStore.toastsEnabled}
                    className="w-24"
                  />
                  <span className="text-sm text-muted-foreground">seconds (1-15)</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Category Controls - Real-time (Socket.IO) */}
          <Card className={!alertStore.toastsEnabled ? 'opacity-60' : ''}>
            <CardHeader>
              <CardTitle>Real-time Notifications</CardTitle>
              <CardDescription>
                High-frequency alerts from Socket.IO events. Disable these to reduce notification
                spam during active trading.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {ALERT_CATEGORIES_REALTIME.map((category) => (
                <div
                  key={category.key}
                  className="flex items-center justify-between py-2 border-b last:border-0"
                >
                  <div className="space-y-0.5">
                    <Label htmlFor={`category-${category.key}`}>{category.label}</Label>
                    <p className="text-sm text-muted-foreground">{category.description}</p>
                  </div>
                  <Switch
                    id={`category-${category.key}`}
                    checked={alertStore.categories[category.key]}
                    onCheckedChange={(checked) =>
                      alertStore.setCategoryEnabled(category.key, checked)
                    }
                    disabled={!alertStore.toastsEnabled}
                  />
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Category Controls - Trading */}
          <Card className={!alertStore.toastsEnabled ? 'opacity-60' : ''}>
            <CardHeader>
              <CardTitle>Trading Operations</CardTitle>
              <CardDescription>
                Notifications from position management, strategies, and Chartink integrations
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {ALERT_CATEGORIES_TRADING.map((category) => (
                <div
                  key={category.key}
                  className="flex items-center justify-between py-2 border-b last:border-0"
                >
                  <div className="space-y-0.5">
                    <Label htmlFor={`category-${category.key}`}>{category.label}</Label>
                    <p className="text-sm text-muted-foreground">{category.description}</p>
                  </div>
                  <Switch
                    id={`category-${category.key}`}
                    checked={alertStore.categories[category.key]}
                    onCheckedChange={(checked) =>
                      alertStore.setCategoryEnabled(category.key, checked)
                    }
                    disabled={!alertStore.toastsEnabled}
                  />
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Category Controls - Data & Automation */}
          <Card className={!alertStore.toastsEnabled ? 'opacity-60' : ''}>
            <CardHeader>
              <CardTitle>Data & Automation</CardTitle>
              <CardDescription>
                Notifications from historical data, Python strategies, and workflow automation
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {ALERT_CATEGORIES_DATA.map((category) => (
                <div
                  key={category.key}
                  className="flex items-center justify-between py-2 border-b last:border-0"
                >
                  <div className="space-y-0.5">
                    <Label htmlFor={`category-${category.key}`}>{category.label}</Label>
                    <p className="text-sm text-muted-foreground">{category.description}</p>
                  </div>
                  <Switch
                    id={`category-${category.key}`}
                    checked={alertStore.categories[category.key]}
                    onCheckedChange={(checked) =>
                      alertStore.setCategoryEnabled(category.key, checked)
                    }
                    disabled={!alertStore.toastsEnabled}
                  />
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Category Controls - Admin & System */}
          <Card className={!alertStore.toastsEnabled ? 'opacity-60' : ''}>
            <CardHeader>
              <CardTitle>Admin & Utilities</CardTitle>
              <CardDescription>
                Notifications from admin panel, monitoring, and clipboard operations
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {ALERT_CATEGORIES_ADMIN.map((category) => (
                <div
                  key={category.key}
                  className="flex items-center justify-between py-2 border-b last:border-0"
                >
                  <div className="space-y-0.5">
                    <Label htmlFor={`category-${category.key}`}>{category.label}</Label>
                    <p className="text-sm text-muted-foreground">{category.description}</p>
                  </div>
                  <Switch
                    id={`category-${category.key}`}
                    checked={alertStore.categories[category.key]}
                    onCheckedChange={(checked) =>
                      alertStore.setCategoryEnabled(category.key, checked)
                    }
                    disabled={!alertStore.toastsEnabled}
                  />
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Actions */}
          <Card>
            <CardHeader>
              <CardTitle>Actions</CardTitle>
              <CardDescription>Test and manage notifications</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-3">
                <Button
                  variant="outline"
                  onClick={() => {
                    toast.success('This is a test success notification')
                  }}
                  disabled={!alertStore.toastsEnabled}
                >
                  Test Toast
                </Button>
                <Button
                  variant="outline"
                  onClick={() => {
                    toast.dismiss()
                    toast.success('All notifications cleared')
                  }}
                >
                  Clear All Toasts
                </Button>
                <Button
                  variant="outline"
                  onClick={() => {
                    alertStore.resetToDefaults()
                    toast.success('Settings reset to defaults')
                  }}
                >
                  <RotateCcw className="h-4 w-4 mr-2" />
                  Reset to Defaults
                </Button>
              </div>

              {/* Current Settings Summary */}
              <div className="mt-4 p-4 bg-muted rounded-lg">
                <h4 className="font-medium mb-2">Current Configuration</h4>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <span className="text-muted-foreground">Toasts:</span>
                  <span>{alertStore.toastsEnabled ? 'Enabled' : 'Disabled'}</span>
                  <span className="text-muted-foreground">Sound:</span>
                  <span>{alertStore.soundEnabled ? 'Enabled' : 'Disabled'}</span>
                  <span className="text-muted-foreground">Position:</span>
                  <span className="capitalize">{alertStore.position.replace('-', ' ')}</span>
                  <span className="text-muted-foreground">Max Visible:</span>
                  <span>{alertStore.maxVisibleToasts} toasts</span>
                  <span className="text-muted-foreground">Duration:</span>
                  <span>{alertStore.duration / 1000} seconds</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Help Card */}
          <Card>
            <CardHeader>
              <CardTitle>Understanding Notification Categories</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground space-y-4">
              <div>
                <p className="font-medium text-foreground mb-2">
                  Real-time Notifications (High Priority)
                </p>
                <ul className="list-disc list-inside space-y-1 ml-2">
                  <li>
                    <strong>Orders:</strong> BUY/SELL alerts from Socket.IO - highest frequency
                    during trading
                  </li>
                  <li>
                    <strong>Analyzer:</strong> Sandbox mode operations - can spam during sandbox
                    trading
                  </li>
                  <li>
                    <strong>System:</strong> Password changes, master contracts - infrequent but
                    important
                  </li>
                  <li>
                    <strong>Control Center:</strong> Semi-auto pending orders - high frequency in
                    managed accounts
                  </li>
                </ul>
              </div>
              <div>
                <p className="font-medium text-foreground mb-2">Trading Operations</p>
                <ul className="list-disc list-inside space-y-1 ml-2">
                  <li>
                    <strong>Positions:</strong> Position close/update notifications
                  </li>
                  <li>
                    <strong>Strategy:</strong> Strategy CRUD, symbol configuration, webhooks
                  </li>
                  <li>
                    <strong>Chartink:</strong> Chartink scanner and strategy integrations
                  </li>
                </ul>
              </div>
              <div>
                <p className="font-medium text-foreground mb-2">Data & Automation</p>
                <ul className="list-disc list-inside space-y-1 ml-2">
                  <li>
                    <strong>Historify:</strong> Historical data jobs, uploads, downloads (67 toasts
                    - highest volume)
                  </li>
                  <li>
                    <strong>Python Strategy:</strong> Strategy uploads, execution logs, scheduling
                  </li>
                  <li>
                    <strong>Flow:</strong> Visual workflow execution and management
                  </li>
                </ul>
              </div>
              <div>
                <p className="font-medium text-foreground mb-2">Admin & Utilities</p>
                <ul className="list-disc list-inside space-y-1 ml-2">
                  <li>
                    <strong>Admin:</strong> Market timings, holidays, freeze quantities
                  </li>
                  <li>
                    <strong>Monitoring:</strong> Health, latency, and security dashboards
                  </li>
                  <li>
                    <strong>Clipboard:</strong> Copy-to-clipboard confirmations
                  </li>
                </ul>
              </div>
              <div className="pt-3 border-t">
                <p className="font-medium text-foreground mb-2">Tips for Power Users</p>
                <ul className="list-disc list-inside space-y-1 ml-2">
                  <li>
                    Running 5+ strategies? Set max visible to <strong>2-3</strong> and duration to{' '}
                    <strong>2 seconds</strong>
                  </li>
                  <li>
                    Disable <strong>Analyzer</strong> when not sandbox trading to reduce spam
                  </li>
                  <li>
                    Disable <strong>Orders</strong> if you prefer checking the order book manually
                  </li>
                  <li>
                    Disable <strong>Historify</strong> during large data imports to avoid
                    notification flood
                  </li>
                  <li>
                    Keep <strong>System</strong> enabled for critical security alerts
                  </li>
                </ul>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Permissions Tab */}
        <TabsContent value="permissions" className="space-y-6">
          <Alert>
            <FolderCheck className="h-4 w-4" />
            <AlertTitle>File Permissions Monitor</AlertTitle>
            <AlertDescription>
              Check file and directory permissions for Max Algos components. Incorrect permissions
              may cause the application to malfunction.
            </AlertDescription>
          </Alert>

          {/* System Info */}
          {permissionsData && (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="flex items-center gap-2">
                      System Status
                      {permissionsData.all_correct ? (
                        <Badge className="bg-profit">All OK</Badge>
                      ) : (
                        <Badge variant="destructive">Issues Found</Badge>
                      )}
                    </CardTitle>
                    <CardDescription>
                      Platform: {permissionsData.platform}
                      {permissionsData.is_windows && ' (Windows uses access-based checks)'}
                    </CardDescription>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={fetchPermissions}
                      disabled={isLoadingPermissions}
                    >
                      {isLoadingPermissions ? (
                        <RefreshCw className="h-4 w-4 animate-spin" />
                      ) : (
                        <>
                          <RefreshCw className="h-4 w-4 mr-2" />
                          Refresh
                        </>
                      )}
                    </Button>
                    {!permissionsData.all_correct && !permissionsData.is_windows && (
                      <Button
                        size="sm"
                        onClick={handleFixPermissions}
                        disabled={isFixingPermissions}
                      >
                        {isFixingPermissions ? (
                          <RefreshCw className="h-4 w-4 animate-spin" />
                        ) : (
                          <>
                            <Wrench className="h-4 w-4 mr-2" />
                            Fix Issues
                          </>
                        )}
                      </Button>
                    )}
                  </div>
                </div>
              </CardHeader>
            </Card>
          )}

          {/* Loading State */}
          {isLoadingPermissions && !permissionsData && (
            <Card>
              <CardContent className="py-12 flex items-center justify-center">
                <div className="flex items-center gap-2">
                  <RefreshCw className="h-5 w-5 animate-spin" />
                  <span>Checking permissions...</span>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Permissions List */}
          {permissionsData && (
            <Card>
              <CardHeader>
                <CardTitle>Permission Details</CardTitle>
                <CardDescription>
                  Click on items with issues to see recommended fixes
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {permissionsData.checks.map((check) => (
                    <div
                      key={check.path}
                      className={`flex items-start gap-3 p-3 rounded-lg border ${
                        check.is_correct
                          ? 'bg-profit/10 border-profit/20'
                          : 'bg-loss/10 border-loss/20'
                      }`}
                    >
                      {/* Status Icon */}
                      <div className="mt-0.5">
                        {check.is_correct ? (
                          <CheckCircle2 className="h-5 w-5 text-profit" />
                        ) : check.exists ? (
                          <FileWarning className="h-5 w-5 text-loss" />
                        ) : (
                          <XCircle className="h-5 w-5 text-loss" />
                        )}
                      </div>

                      {/* Details */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium font-mono text-sm">{check.path}</span>
                          {check.is_sensitive && (
                            <Badge variant="outline" className="text-xs">
                              <Lock className="h-3 w-3 mr-1" />
                              Sensitive
                            </Badge>
                          )}
                          {check.is_directory && (
                            <Badge variant="outline" className="text-xs">
                              Directory
                            </Badge>
                          )}
                        </div>
                        <p className="text-sm text-muted-foreground mt-0.5">{check.description}</p>

                        {/* Permission Details */}
                        <div className="flex items-center gap-4 mt-2 text-xs">
                          <span className="text-muted-foreground">
                            Expected:{' '}
                            <code className="bg-muted px-1 rounded">{check.expected_mode}</code>
                            <span className="ml-1 text-muted-foreground/70">
                              ({check.expected_rwx})
                            </span>
                          </span>
                          {check.exists && check.actual_mode && (
                            <span className={check.is_correct ? 'text-profit' : 'text-loss'}>
                              Actual:{' '}
                              <code
                                className={`px-1 rounded ${check.is_correct ? 'bg-profit/10' : 'bg-loss/10'}`}
                              >
                                {check.actual_mode}
                              </code>
                              <span className="ml-1 opacity-70">({check.actual_rwx})</span>
                            </span>
                          )}
                        </div>

                        {/* Issue Message */}
                        {check.issue && (
                          <div className="mt-2 p-2 bg-loss/10 rounded text-sm">
                            <p className="text-loss font-medium">{check.issue}</p>
                            {!permissionsData.is_windows && !check.exists && (
                              <p className="text-loss text-xs mt-1">
                                Fix: Create the directory or file
                              </p>
                            )}
                            {!permissionsData.is_windows &&
                              check.exists &&
                              check.actual_mode !== check.expected_mode && (
                                <p className="text-loss text-xs mt-1">
                                  Fix:{' '}
                                  <code className="bg-loss/20 px-1 rounded">
                                    chmod {check.expected_mode} {check.path}
                                  </code>
                                </p>
                              )}
                          </div>
                        )}

                        {/* Warning Message (doesn't affect is_correct status) */}
                        {check.warning && !check.issue && (
                          <div className="mt-2 p-2 bg-warning/10 rounded text-sm">
                            <p className="text-warning font-medium">{check.warning}</p>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Help Card */}
          <Card>
            <CardHeader>
              <CardTitle>Understanding Permissions</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground space-y-3">
              <div>
                <p className="font-medium text-foreground">Permission Format (Unix/Linux/macOS)</p>
                <p>Permissions are shown as a 3-digit number (e.g., 755) where:</p>
                <ul className="list-disc list-inside mt-1 space-y-1 ml-2">
                  <li>
                    <code className="bg-muted px-1 rounded">7</code> = Read + Write + Execute (rwx)
                  </li>
                  <li>
                    <code className="bg-muted px-1 rounded">5</code> = Read + Execute (r-x)
                  </li>
                  <li>
                    <code className="bg-muted px-1 rounded">6</code> = Read + Write (rw-)
                  </li>
                  <li>
                    <code className="bg-muted px-1 rounded">4</code> = Read only (r--)
                  </li>
                  <li>
                    <code className="bg-muted px-1 rounded">0</code> = No permission (---)
                  </li>
                </ul>
              </div>
              <div>
                <p className="font-medium text-foreground">Sensitive Files</p>
                <p>
                  Files marked as sensitive (like{' '}
                  <code className="bg-muted px-1 rounded">.env</code> and{' '}
                  <code className="bg-muted px-1 rounded">keys/</code>) should have restricted
                  permissions (600 or 700) to prevent unauthorized access.
                </p>
              </div>
              <div>
                <p className="font-medium text-foreground">Windows</p>
                <p>
                  On Windows, the system checks if files/directories are readable and writable
                  instead of Unix-style permissions.
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Theme Tab */}
        <TabsContent value="theme" className="space-y-6">
          {/* Analyzer Mode Warning */}
          {isAnalyzerMode && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Theme Changes Disabled</AlertTitle>
              <AlertDescription>
                Theme customization is disabled while in Analyzer Mode. The purple theme is
                automatically applied for visual distinction. Switch back to Live Mode to change
                themes.
              </AlertDescription>
            </Alert>
          )}

          {/* Current Theme Status */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Current Theme</CardTitle>
                  <CardDescription>
                    {isAnalyzerMode
                      ? 'Analyzer Mode (Purple Theme)'
                      : `${mode.charAt(0).toUpperCase() + mode.slice(1)} Mode with ${color.charAt(0).toUpperCase() + color.slice(1)} accent`}
                  </CardDescription>
                </div>
                <div className="flex items-center gap-4">
                  <div className="flex gap-2">
                    <div className="w-6 h-6 rounded bg-primary" title="Primary" />
                    <div className="w-6 h-6 rounded bg-secondary" title="Secondary" />
                    <div className="w-6 h-6 rounded bg-accent" title="Accent" />
                    <div className="w-6 h-6 rounded bg-muted" title="Muted" />
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleResetTheme}
                    disabled={isAnalyzerMode || (mode === 'light' && color === 'zinc')}
                  >
                    <RefreshCw className="h-4 w-4 mr-2" />
                    Reset
                  </Button>
                </div>
              </div>
            </CardHeader>
          </Card>

          {/* Theme Mode Selection */}
          <Card className={isAnalyzerMode ? 'opacity-60' : ''}>
            <CardHeader>
              <CardTitle>Theme Mode</CardTitle>
              <CardDescription>Choose between light and dark interface</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {THEME_MODES.map((themeOption) => {
                  const Icon = themeOption.icon
                  const isSelected = mode === themeOption.value && !isAnalyzerMode
                  return (
                    <button
                      type="button"
                      key={themeOption.value}
                      onClick={() => handleThemeModeChange(themeOption.value)}
                      disabled={isAnalyzerMode}
                      className={`flex items-start gap-4 p-4 rounded-lg border-2 transition-all text-left ${
                        isSelected
                          ? 'border-primary bg-primary/5'
                          : 'border-border hover:border-primary/50'
                      } ${isAnalyzerMode ? 'cursor-not-allowed' : 'cursor-pointer'}`}
                    >
                      <div
                        className={`p-2 rounded-lg ${isSelected ? 'bg-primary text-primary-foreground' : 'bg-muted'}`}
                      >
                        <Icon className="h-5 w-5" />
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{themeOption.label}</span>
                          {isSelected && <Check className="h-4 w-4 text-primary" />}
                        </div>
                        <p className="text-sm text-muted-foreground mt-1">
                          {themeOption.description}
                        </p>
                      </div>
                    </button>
                  )
                })}
              </div>
            </CardContent>
          </Card>

          {/* Accent Color Selection */}
          <Card className={isAnalyzerMode ? 'opacity-60' : ''}>
            <CardHeader>
              <CardTitle>Accent Color</CardTitle>
              <CardDescription>Customize the primary accent color</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-4 sm:grid-cols-6 gap-3">
                {ACCENT_COLORS.map((accentColor) => {
                  const isSelected = color === accentColor.value && !isAnalyzerMode
                  return (
                    <button
                      type="button"
                      key={accentColor.value}
                      onClick={() => handleAccentColorChange(accentColor.value)}
                      disabled={isAnalyzerMode}
                      className={`flex flex-col items-center gap-2 p-3 rounded-lg border-2 transition-all ${
                        isSelected
                          ? 'border-primary bg-primary/5'
                          : 'border-border hover:border-primary/50'
                      } ${isAnalyzerMode ? 'cursor-not-allowed' : 'cursor-pointer'}`}
                      title={accentColor.label}
                    >
                      <div
                        className={`w-8 h-8 rounded-full ${accentColor.color} ring-2 ring-offset-2 ring-offset-background ${isSelected ? 'ring-primary' : 'ring-transparent'}`}
                      />
                      <span className="text-xs font-medium">{accentColor.label}</span>
                    </button>
                  )
                })}
              </div>
            </CardContent>
          </Card>

          {/* Theme Info */}
          <Card>
            <CardHeader>
              <CardTitle>About Themes</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground space-y-2">
              <p>
                <strong>Light Mode:</strong> Optimized for daytime use with high contrast and
                readability.
              </p>
              <p>
                <strong>Dark Mode:</strong> Reduces eye strain during extended trading sessions,
                especially in low-light environments.
              </p>
              <p>
                <strong>Analyzer Mode:</strong> When in sandbox/analyzer mode, a distinct purple
                theme is applied automatically to clearly indicate you are not trading with real
                funds.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        {/* SMTP Tab -- retired in favor of /admin/email, which now owns
            both the shared SMTP transport AND the Platform Email
            Identities (per-purpose From addresses). This duplicate form
            used to write the same single smtp_from_email column via a
            separate /auth/smtp-config route, which could silently
            override whatever "Default Sender" was set on the canonical
            admin page -- exactly the confusion the identities split was
            meant to eliminate. Kept as a redirect rather than deleted
            outright so an existing bookmark/habit still lands somewhere
            useful instead of a dead tab. */}
        <TabsContent value="smtp" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>SMTP Configuration</CardTitle>
              <CardDescription>Email settings have moved to the main Admin panel.</CardDescription>
            </CardHeader>
            <CardContent>
              <Alert>
                <Mail className="h-4 w-4" />
                <AlertTitle>Manage email settings in Admin</AlertTitle>
                <AlertDescription>
                  SMTP transport (server, credentials, TLS) and Platform Email Identities (which
                  "From" address each email type uses) are now configured together on the Email
                  Settings admin page.
                </AlertDescription>
              </Alert>
              <Button asChild className="mt-4">
                <Link to="/admin/email">
                  <Mail className="h-4 w-4 mr-2" />
                  Open Email Settings
                </Link>
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        {/* TOTP Tab */}
        <TabsContent value="totp" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>TOTP Authentication</CardTitle>
              <CardDescription>Manage your Two-Factor Authentication settings</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <Alert>
                <Shield className="h-4 w-4" />
                <AlertTitle>About TOTP Authentication</AlertTitle>
                <AlertDescription>
                  TOTP (Time-based One-Time Password) provides an additional layer of security.
                  You&apos;ll need an authenticator app like Google Authenticator or Authy to
                  generate codes for password recovery.
                </AlertDescription>
              </Alert>

              <TwoFactorEnforcement />

              {profileData?.qr_code && profileData?.totp_secret ? (
                <div className="bg-muted rounded-lg p-6 space-y-6">
                  <h3 className="font-semibold text-center">Your TOTP QR Code</h3>

                  {/* QR Code */}
                  <div className="flex justify-center">
                    <div className="p-4 bg-white rounded-lg shadow">
                      <img
                        src={`data:image/png;base64,${profileData.qr_code}`}
                        alt="TOTP QR Code"
                        className="w-48 h-48"
                      />
                    </div>
                  </div>

                  {/* Manual Entry */}
                  <div className="bg-background rounded-lg p-4 space-y-2">
                    <h4 className="font-semibold">Manual Entry</h4>
                    <p className="text-sm text-muted-foreground">Secret key for manual entry:</p>
                    <div className="flex items-center gap-2">
                      <code className="flex-1 bg-muted p-2 rounded text-sm break-all">
                        {profileData.totp_secret}
                      </code>
                      <Button
                        size="icon"
                        variant="outline"
                        onClick={() => copyToClipboard(profileData.totp_secret!)}
                        aria-label="Copy TOTP secret"
                      >
                        <Copy className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>

                  {/* Instructions */}
                  <div className="space-y-2">
                    <p className="font-medium">Setup Instructions:</p>
                    <ol className="list-decimal list-inside space-y-1 text-sm text-muted-foreground">
                      <li>Install an authenticator app (Google Authenticator, Authy, etc.)</li>
                      <li>Scan the QR code above or enter the secret key manually</li>
                      <li>Save your backup codes in a safe place</li>
                      <li>
                        You&apos;ll need the TOTP code to reset your password if you forget it
                      </li>
                    </ol>
                  </div>
                </div>
              ) : (
                <Alert variant="destructive">
                  <AlertTitle>TOTP Not Available</AlertTitle>
                  <AlertDescription>
                    Unable to load TOTP setup. Please contact your administrator.
                  </AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Kill Switch Tab */}
        <TabsContent value="killswitch" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Power className="h-5 w-5" />
                Kill Switch Settings
              </CardTitle>
              <CardDescription>
                Controls which actions run when the emergency stop button (top right) is
                activated. Stopping running strategies and automations always happens regardless
                of these settings.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="flex items-center justify-between rounded-lg border border-border p-4">
                <div>
                  <p className="font-medium text-sm">Cancel all orders</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Cancel every pending order, live and sandbox, across all connected brokers.
                  </p>
                </div>
                <Switch
                  checked={killSwitchScope?.cancel_orders_enabled ?? true}
                  disabled={isSavingKillSwitchScope || !killSwitchScope}
                  onCheckedChange={(checked) =>
                    killSwitchScope &&
                    handleKillSwitchScopeChange({
                      ...killSwitchScope,
                      cancel_orders_enabled: checked,
                    })
                  }
                />
              </div>
              <div className="flex items-center justify-between rounded-lg border border-border p-4">
                <div>
                  <p className="font-medium text-sm">Close all positions</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Square off every open position, live and sandbox, across all connected
                    brokers.
                  </p>
                </div>
                <Switch
                  checked={killSwitchScope?.close_positions_enabled ?? true}
                  disabled={isSavingKillSwitchScope || !killSwitchScope}
                  onCheckedChange={(checked) =>
                    killSwitchScope &&
                    handleKillSwitchScopeChange({
                      ...killSwitchScope,
                      close_positions_enabled: checked,
                    })
                  }
                />
              </div>
              <Alert>
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription>
                  Turning both off means the kill switch will only stop strategies and
                  automations — orders and positions stay untouched. Most users should leave both
                  on.
                </AlertDescription>
              </Alert>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recent Activity</CardTitle>
              <CardDescription>Last 20 kill switch activations and deactivations.</CardDescription>
            </CardHeader>
            <CardContent>
              {isLoadingKillSwitchAudit ? (
                <p className="text-sm text-muted-foreground">Loading…</p>
              ) : killSwitchAudit.length === 0 ? (
                <p className="text-sm text-muted-foreground">No kill switch activity yet.</p>
              ) : (
                <div className="space-y-2">
                  {killSwitchAudit.map((entry) => (
                    <div
                      key={entry.id}
                      className="flex items-start justify-between gap-4 rounded-lg border border-border p-3 text-sm"
                    >
                      <div>
                        <p className="font-medium capitalize">
                          {entry.event_type} — {entry.actor_type}
                          {entry.actor_id ? ` (${entry.actor_id})` : ''}
                        </p>
                        {entry.event_type === 'activated' && (
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {entry.live_orders_cancelled} orders cancelled,{' '}
                            {entry.live_positions_closed} positions closed,{' '}
                            {entry.strategies_stopped} strategies stopped
                          </p>
                        )}
                        {entry.reason && (
                          <p className="text-xs text-muted-foreground mt-0.5">
                            Reason: {entry.reason}
                          </p>
                        )}
                      </div>
                      <span className="text-xs text-muted-foreground whitespace-nowrap">
                        {entry.event_at ? new Date(entry.event_at).toLocaleString('en-IN') : ''}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Restart Required Dialog */}
      <AlertDialog open={showRestartDialog} onOpenChange={setShowRestartDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-warning" />
              Restart Required
            </AlertDialogTitle>
            <AlertDialogDescription className="space-y-3">
              <p>
                Your configuration has been saved to the{' '}
                <code className="bg-muted px-1 rounded">.env</code> file.
              </p>
              <p>
                To apply these changes, please restart the Max Algos application using your usual
                method (terminal, service manager, or container orchestrator).
              </p>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogAction onClick={() => setShowRestartDialog(false)}>
              Got it
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
