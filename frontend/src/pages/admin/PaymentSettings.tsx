import {
  AlertTriangle,
  CheckCircle2,
  CreditCard,
  IndianRupee,
  KeyRound,
  Loader2,
  RefreshCw,
  Save,
  ToggleLeft,
  ToggleRight,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { fetchCSRFToken } from '@/api/client'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

interface PaymentSettingsData {
  payments_enabled: boolean
  setup_fee_paise: number
  default_subscription_price_paise: number
  platform_subscription_plan_id: string | null
}

interface RazorpayCredentialsData {
  key_id: string | null
  key_secret_set: boolean
  webhook_secret_set: boolean
}

interface PaymentRecord {
  id: number
  user_id: string | null
  purpose: string
  razorpay_order_id: string
  razorpay_payment_id: string | null
  amount_paise: number
  currency: string
  status: string
  strategy_id: number | null
  created_at: string
  verified_at: string | null
}

function paiseToRupeeString(paise: number): string {
  return (paise / 100).toString()
}

function rupeeStringToPaise(value: string): number {
  const rupees = Number.parseFloat(value)
  return Number.isFinite(rupees) ? Math.round(rupees * 100) : 0
}

export default function PaymentSettings() {
  const [settings, setSettings] = useState<PaymentSettingsData | null>(null)
  const [setupFeeInput, setSetupFeeInput] = useState('')
  const [defaultPriceInput, setDefaultPriceInput] = useState('')
  const [planIdInput, setPlanIdInput] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [payments, setPayments] = useState<PaymentRecord[]>([])
  const [isLoadingPayments, setIsLoadingPayments] = useState(true)

  const [credentials, setCredentials] = useState<RazorpayCredentialsData | null>(null)
  const [isLoadingCredentials, setIsLoadingCredentials] = useState(true)
  const [isSavingCredentials, setIsSavingCredentials] = useState(false)
  const [keyIdInput, setKeyIdInput] = useState('')
  const [keySecretInput, setKeySecretInput] = useState('')
  const [webhookSecretInput, setWebhookSecretInput] = useState('')

  const fetchSettings = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)
      const res = await fetch('/payments/admin/settings', { credentials: 'include' })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        // Backend wraps the settings in {status, data} — unwrap it. Reading
        // fields off the envelope left every input blank (undefined paise ->
        // "NaN"/""), which is why the fee fields showed empty.
        const s: PaymentSettingsData = data.data
        setSettings(s)
        setSetupFeeInput(paiseToRupeeString(s.setup_fee_paise))
        setDefaultPriceInput(paiseToRupeeString(s.default_subscription_price_paise))
        setPlanIdInput(s.platform_subscription_plan_id || '')
      } else {
        setError(data.message || 'Failed to fetch payment settings')
      }
    } catch {
      setError('Failed to connect to server')
    } finally {
      setIsLoading(false)
    }
  }, [])

  const fetchPayments = useCallback(async () => {
    try {
      setIsLoadingPayments(true)
      const res = await fetch('/payments/admin/list', { credentials: 'include' })
      const data = await res.json()
      if (res.ok) {
        // Backend returns {status, data: [...]} — the old `data.payments`
        // read was always undefined, so the payment log rendered empty.
        setPayments(data.data || [])
      }
    } catch {
      // Non-fatal — settings form still works without the log.
    } finally {
      setIsLoadingPayments(false)
    }
  }, [])

  const fetchCredentials = useCallback(async () => {
    try {
      setIsLoadingCredentials(true)
      const res = await fetch('/payments/admin/credentials', { credentials: 'include' })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        setCredentials(data.data)
        setKeyIdInput(data.data.key_id || '')
      }
    } catch {
      // Non-fatal — credentials card just shows nothing to edit yet.
    } finally {
      setIsLoadingCredentials(false)
    }
  }, [])

  useEffect(() => {
    fetchSettings()
    fetchPayments()
    fetchCredentials()
  }, [fetchSettings, fetchPayments, fetchCredentials])

  const handleSaveCredentials = async () => {
    setIsSavingCredentials(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const res = await fetch('/payments/admin/credentials', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          key_id: keyIdInput,
          key_secret: keySecretInput, // blank = keep existing
          webhook_secret: webhookSecretInput, // blank = keep existing
        }),
      })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        showToast.success('Razorpay credentials updated')
        setKeySecretInput('')
        setWebhookSecretInput('')
        await fetchCredentials()
      } else {
        showToast.error(data.message || 'Failed to update Razorpay credentials')
      }
    } catch {
      showToast.error('Network error. Please try again.')
    } finally {
      setIsSavingCredentials(false)
    }
  }

  const handleToggle = () => {
    if (!settings) return
    setSettings({ ...settings, payments_enabled: !settings.payments_enabled })
  }

  const handleSave = async () => {
    if (!settings) return
    setIsSaving(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const res = await fetch('/payments/admin/settings', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          payments_enabled: settings.payments_enabled,
          setup_fee_paise: rupeeStringToPaise(setupFeeInput),
          default_subscription_price_paise: rupeeStringToPaise(defaultPriceInput),
          platform_subscription_plan_id: planIdInput.trim(),
        }),
      })
      const data = await res.json()
      if (res.ok) {
        showToast.success('Payment settings updated')
        await fetchSettings()
      } else {
        showToast.error(data.message || 'Failed to update payment settings')
      }
    } catch {
      showToast.error('Network error. Please try again.')
    } finally {
      setIsSaving(false)
    }
  }

  const statusColor = (status: string) => {
    if (status === 'captured') return 'text-profit bg-profit/10 border-profit/20'
    if (status === 'failed') return 'text-loss bg-loss/10 border-loss/20'
    return 'text-muted-foreground bg-muted border-border'
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16 gap-3 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span className="text-sm font-medium">Loading payment settings…</span>
      </div>
    )
  }

  return (
    <div className="space-y-8 max-w-5xl mx-auto pb-10">
      {/* Header */}
      <PageHeader
        eyebrow="Admin Panel"
        title="Payment Settings"
        description="Control the Razorpay setup fee, marketplace pricing, and view recent payments"
        actions={
          <button
            type="button"
            onClick={() => {
              fetchSettings()
              fetchPayments()
              fetchCredentials()
            }}
            className="p-2 rounded-lg bg-card border border-border hover:border-muted-foreground/40 text-muted-foreground hover:text-foreground transition-all"
            title="Refresh"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        }
      />

      {error && (
        <div className="p-4 rounded-xl bg-loss/10 border border-loss/20 flex items-center gap-3">
          <AlertTriangle className="h-5 w-5 text-loss shrink-0" />
          <p className="text-sm text-loss">{error}</p>
        </div>
      )}

      {/* Razorpay Credentials */}
      {!isLoadingCredentials && (
        <div className="p-6 rounded-2xl bg-card border border-border space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-foreground flex items-center gap-2">
              <KeyRound className="h-5 w-5 text-brand" />
              Razorpay API Credentials
            </h2>
            {credentials?.key_id && credentials.key_secret_set && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded border bg-profit/10 border-profit/20 text-profit">
                <CheckCircle2 className="h-3 w-3" />
                Configured
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground -mt-4">
            From your Razorpay Dashboard &gt; Settings &gt; API Keys. Use test-mode keys (
            <code className="text-[11px]">rzp_test_...</code>) while testing, live keys (
            <code className="text-[11px]">rzp_live_...</code>) in production.
          </p>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                Key ID
              </Label>
              <Input
                placeholder="rzp_test_..."
                value={keyIdInput}
                onChange={(e) => setKeyIdInput(e.target.value)}
                className="bg-background border-border focus:border-brand/40 text-foreground font-mono text-sm"
                autoComplete="off"
              />
            </div>

            <div className="space-y-1.5">
              <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                Key Secret
              </Label>
              <Input
                type="password"
                placeholder={
                  credentials?.key_secret_set ? '••••••••  (leave blank to keep)' : 'Key secret'
                }
                value={keySecretInput}
                onChange={(e) => setKeySecretInput(e.target.value)}
                className="bg-background border-border focus:border-brand/40 text-foreground"
                autoComplete="new-password"
              />
            </div>

            <div className="space-y-1.5 sm:col-span-2">
              <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                Webhook Secret (optional)
              </Label>
              <Input
                type="password"
                placeholder={
                  credentials?.webhook_secret_set
                    ? '••••••••  (leave blank to keep)'
                    : 'Set in Razorpay Dashboard > Webhooks, needed to verify server callbacks'
                }
                value={webhookSecretInput}
                onChange={(e) => setWebhookSecretInput(e.target.value)}
                className="bg-background border-border focus:border-brand/40 text-foreground"
                autoComplete="new-password"
              />
            </div>
          </div>

          <div className="flex justify-end">
            <Button
              onClick={handleSaveCredentials}
              disabled={isSavingCredentials}
              className="bg-brand hover:bg-brand/90 text-brand-foreground font-bold px-6"
            >
              {isSavingCredentials ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Saving…
                </>
              ) : (
                <>
                  <Save className="h-4 w-4 mr-2" />
                  Save Credentials
                </>
              )}
            </Button>
          </div>
        </div>
      )}

      {settings && (
        <div className="p-6 rounded-2xl bg-card border border-border space-y-6">
          <h2 className="text-lg font-bold text-foreground flex items-center gap-2">
            <CreditCard className="h-5 w-5 text-brand" />
            Razorpay Configuration
          </h2>

          {/* Enabled toggle */}
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                Payments Enabled
              </Label>
              <p className="text-xs text-muted-foreground mt-1">
                When off, setup skips the fee and free-listing subscribe stays instant — a
                killswitch for keys not yet configured.
              </p>
            </div>
            <button
              type="button"
              onClick={handleToggle}
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-bold transition-all shrink-0',
                settings.payments_enabled
                  ? 'bg-profit/10 border-profit/30 text-profit'
                  : 'bg-background border-border text-muted-foreground hover:border-muted-foreground/40'
              )}
            >
              {settings.payments_enabled ? (
                <ToggleRight className="h-4 w-4" />
              ) : (
                <ToggleLeft className="h-4 w-4" />
              )}
              {settings.payments_enabled ? 'Enabled' : 'Disabled'}
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label
                htmlFor="setup-fee"
                className="text-muted-foreground text-xs font-semibold uppercase tracking-wider"
              >
                Setup / Activation Fee (₹)
              </Label>
              <div className="relative">
                <IndianRupee className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  id="setup-fee"
                  type="number"
                  min="0"
                  step="1"
                  value={setupFeeInput}
                  onChange={(e) => setSetupFeeInput(e.target.value)}
                  className="pl-9 bg-background border-border focus:border-brand/40 text-foreground"
                />
              </div>
              <p className="text-[11px] text-muted-foreground">
                Charged once, before the admin account is created.
              </p>
            </div>

            <div className="space-y-1.5">
              <Label
                htmlFor="default-price"
                className="text-muted-foreground text-xs font-semibold uppercase tracking-wider"
              >
                Default Subscription Price (₹)
              </Label>
              <div className="relative">
                <IndianRupee className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  id="default-price"
                  type="number"
                  min="0"
                  step="1"
                  value={defaultPriceInput}
                  onChange={(e) => setDefaultPriceInput(e.target.value)}
                  className="pl-9 bg-background border-border focus:border-brand/40 text-foreground"
                />
              </div>
              <p className="text-[11px] text-muted-foreground">
                Default for new marketplace listings; each listing's own price still overrides this.
              </p>
            </div>

            <div className="space-y-1.5 sm:col-span-2">
              <Label
                htmlFor="platform-plan-id"
                className="text-muted-foreground text-xs font-semibold uppercase tracking-wider"
              >
                Platform Subscription Plan ID
              </Label>
              <Input
                id="platform-plan-id"
                placeholder="plan_..."
                value={planIdInput}
                onChange={(e) => setPlanIdInput(e.target.value)}
                className="bg-background border-border focus:border-brand/40 text-foreground font-mono text-sm"
                autoComplete="off"
              />
              <p className="text-[11px] text-muted-foreground">
                The recurring platform-fee plan users subscribe to before accessing the dashboard.
                Create the Plan in Razorpay Dashboard &gt; Subscriptions &gt; Plans (it defines the
                amount and billing cycle), then paste its plan_id here. Until this is set, users
                cannot complete the platform subscription.
              </p>
            </div>
          </div>

          <div className="flex justify-end">
            <Button
              onClick={handleSave}
              disabled={isSaving}
              className="bg-brand hover:bg-brand/90 text-brand-foreground font-bold px-6"
            >
              {isSaving ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Saving…
                </>
              ) : (
                <>
                  <Save className="h-4 w-4 mr-2" />
                  Save Settings
                </>
              )}
            </Button>
          </div>
        </div>
      )}

      {/* Payment log */}
      <div className="rounded-2xl bg-card border border-border overflow-hidden">
        <div className="p-5 border-b border-border flex items-center justify-between">
          <h2 className="text-base font-bold text-foreground flex items-center gap-2">
            <CreditCard className="h-4 w-4 text-brand" />
            Recent Payments
            <span className="ml-1 text-xs font-semibold text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
              {payments.length}
            </span>
          </h2>
        </div>

        {isLoadingPayments ? (
          <div className="flex items-center justify-center py-16 gap-3 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span className="text-sm font-medium">Loading payments…</span>
          </div>
        ) : payments.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
            <CreditCard className="h-8 w-8" />
            <p className="text-sm font-medium">No payments recorded yet</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground border-b border-border">
                  <th className="px-5 py-3 font-semibold">Purpose</th>
                  <th className="px-5 py-3 font-semibold">User</th>
                  <th className="px-5 py-3 font-semibold">Amount</th>
                  <th className="px-5 py-3 font-semibold">Status</th>
                  <th className="px-5 py-3 font-semibold">Order ID</th>
                  <th className="px-5 py-3 font-semibold">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {payments.map((p) => (
                  <tr key={p.id} className="hover:bg-muted/40 transition-colors">
                    <td className="px-5 py-3 font-medium text-foreground capitalize">
                      {p.purpose}
                    </td>
                    <td className="px-5 py-3 text-muted-foreground">{p.user_id || '—'}</td>
                    <td className="px-5 py-3 text-foreground font-semibold">
                      ₹{(p.amount_paise / 100).toLocaleString('en-IN')}
                    </td>
                    <td className="px-5 py-3">
                      <span
                        className={cn(
                          'inline-flex items-center px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded border',
                          statusColor(p.status)
                        )}
                      >
                        {p.status}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-muted-foreground font-mono text-xs truncate max-w-[160px]">
                      {p.razorpay_order_id}
                    </td>
                    <td className="px-5 py-3 text-muted-foreground text-xs">
                      {new Date(p.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
