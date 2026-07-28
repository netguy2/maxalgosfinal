import {
  AlertTriangle,
  AtSign,
  CheckCircle2,
  Loader2,
  Mail,
  RefreshCw,
  Save,
  Send,
  ToggleLeft,
  ToggleRight,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { fetchCSRFToken } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

interface SmtpSettingsData {
  smtp_server: string | null
  smtp_port: number | null
  smtp_username: string | null
  smtp_password_set: boolean
  smtp_use_tls: boolean
  smtp_from_email: string | null
  smtp_helo_hostname: string | null
}

// Platform Email Identities -- which "From" address each category of
// outbound email uses. All share the single SMTP transport configured
// above (one mailbox login), so a Microsoft 365/Gmail account can send as
// noreply@/security@/billing@ aliases without a separate SMTP login per
// alias. Any identity left blank falls back to Default Sender, which
// itself falls back to the legacy single From Email if that's all that
// was ever configured (see database/settings_db.py get_email_from_address).
interface EmailIdentitiesData {
  smtp_email_default: string | null
  smtp_email_verification: string | null
  smtp_email_security: string | null
  smtp_email_billing: string | null
  smtp_email_notifications: string | null
  smtp_email_reply_to: string | null
}

export default function EmailSettings() {
  const [settings, setSettings] = useState<SmtpSettingsData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [smtpServer, setSmtpServer] = useState('')
  const [smtpPort, setSmtpPort] = useState('587')
  const [smtpUsername, setSmtpUsername] = useState('')
  const [smtpPassword, setSmtpPassword] = useState('')
  const [smtpHeloHostname, setSmtpHeloHostname] = useState('')
  const [smtpUseTls, setSmtpUseTls] = useState(true)

  const [testEmail, setTestEmail] = useState('')
  const [isTesting, setIsTesting] = useState(false)

  const [isIdentitiesLoading, setIsIdentitiesLoading] = useState(true)
  const [isSavingIdentities, setIsSavingIdentities] = useState(false)
  const [defaultSender, setDefaultSender] = useState('')
  const [verificationSender, setVerificationSender] = useState('')
  const [securitySender, setSecuritySender] = useState('')
  const [billingSender, setBillingSender] = useState('')
  const [notificationsSender, setNotificationsSender] = useState('')
  const [replyTo, setReplyTo] = useState('')

  const fetchSettings = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)
      const res = await fetch('/admin/api/smtp', { credentials: 'include' })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        const s: SmtpSettingsData = data.data
        setSettings(s)
        setSmtpServer(s.smtp_server || '')
        setSmtpPort(s.smtp_port ? String(s.smtp_port) : '587')
        setSmtpUsername(s.smtp_username || '')
        setSmtpHeloHostname(s.smtp_helo_hostname || '')
        setSmtpUseTls(s.smtp_use_tls ?? true)
      } else {
        setError(data.message || 'Failed to fetch SMTP settings')
      }
    } catch {
      setError('Failed to connect to server')
    } finally {
      setIsLoading(false)
    }
  }, [])

  const fetchIdentities = useCallback(async () => {
    try {
      setIsIdentitiesLoading(true)
      const res = await fetch('/admin/api/smtp/identities', { credentials: 'include' })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        const s: EmailIdentitiesData = data.data
        setDefaultSender(s.smtp_email_default || '')
        setVerificationSender(s.smtp_email_verification || '')
        setSecuritySender(s.smtp_email_security || '')
        setBillingSender(s.smtp_email_billing || '')
        setNotificationsSender(s.smtp_email_notifications || '')
        setReplyTo(s.smtp_email_reply_to || '')
      }
    } catch {
      // Non-fatal -- identities section shows blank fields, transport
      // section above still works independently.
    } finally {
      setIsIdentitiesLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSettings()
    fetchIdentities()
  }, [fetchSettings, fetchIdentities])

  const handleSaveIdentities = async () => {
    setIsSavingIdentities(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const res = await fetch('/admin/api/smtp/identities', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          smtp_email_default: defaultSender,
          smtp_email_verification: verificationSender,
          smtp_email_security: securitySender,
          smtp_email_billing: billingSender,
          smtp_email_notifications: notificationsSender,
          smtp_email_reply_to: replyTo,
        }),
      })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        showToast.success('Platform email identities updated')
        await fetchIdentities()
      } else {
        showToast.error(data.message || 'Failed to update email identities')
      }
    } catch {
      showToast.error('Network error. Please try again.')
    } finally {
      setIsSavingIdentities(false)
    }
  }

  const handleSave = async () => {
    setIsSaving(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const res = await fetch('/admin/api/smtp', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          smtp_server: smtpServer,
          smtp_port: Number.parseInt(smtpPort, 10) || 587,
          smtp_username: smtpUsername,
          smtp_password: smtpPassword, // blank = keep existing, backend leaves it untouched
          smtp_use_tls: smtpUseTls,
          // smtp_from_email intentionally omitted -- "From" address
          // configuration moved to the Platform Email Identities section
          // below (see handleSaveIdentities). The backend keeps
          // smtp_from_email as a read-only legacy fallback for installs
          // that configured it before this split and haven't set a
          // Default Sender yet; this form no longer writes to it.
          smtp_helo_hostname: smtpHeloHostname,
        }),
      })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        showToast.success('SMTP settings updated')
        setSmtpPassword('')
        await fetchSettings()
      } else {
        showToast.error(data.message || 'Failed to update SMTP settings')
      }
    } catch {
      showToast.error('Network error. Please try again.')
    } finally {
      setIsSaving(false)
    }
  }

  const handleSendTest = async () => {
    if (!testEmail.trim()) {
      showToast.error('Enter an email address to send the test to')
      return
    }
    setIsTesting(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const res = await fetch('/admin/api/smtp/test', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({ test_email: testEmail.trim() }),
      })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        showToast.success(data.message || 'Test email sent')
      } else {
        showToast.error(data.message || 'Failed to send test email')
      }
    } catch {
      showToast.error('Network error. Please try again.')
    } finally {
      setIsTesting(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16 gap-3 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span className="text-sm font-medium">Loading email settings…</span>
      </div>
    )
  }

  const isConfigured = Boolean(settings?.smtp_server && settings?.smtp_password_set)

  return (
    <div className="space-y-8 max-w-3xl mx-auto pb-10">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <span className="text-xs font-semibold text-brand uppercase tracking-wider block mb-1">
            Admin Panel
          </span>
          <h1 className="text-xl font-bold text-foreground tracking-tight">
            Email Settings
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Configure the SMTP server used for signup verification, password reset, and other
            platform emails
          </p>
        </div>
        <button
          type="button"
          onClick={fetchSettings}
          className="p-2 rounded-lg bg-card border border-border hover:border-muted-foreground/40 text-muted-foreground hover:text-foreground transition-all"
          title="Refresh"
        >
          <RefreshCw className="h-4 w-4" />
        </button>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-loss/10 border border-loss/20 flex items-center gap-3">
          <AlertTriangle className="h-5 w-5 text-loss shrink-0" />
          <p className="text-sm text-loss">{error}</p>
        </div>
      )}

      <div
        className={cn(
          'p-4 rounded-xl border flex items-center gap-3',
          isConfigured
            ? 'bg-profit/10 border-profit/20'
            : 'bg-warning/10 border-warning/20'
        )}
      >
        {isConfigured ? (
          <CheckCircle2 className="h-5 w-5 text-profit shrink-0" />
        ) : (
          <AlertTriangle className="h-5 w-5 text-warning shrink-0" />
        )}
        <p className={cn('text-sm', isConfigured ? 'text-profit' : 'text-warning')}>
          {isConfigured
            ? 'SMTP is configured. Registration and password-reset emails will be sent.'
            : 'SMTP is not fully configured. Users who self-register will not receive a verification email until this is set up.'}
        </p>
      </div>

      <div className="p-6 rounded-2xl bg-card border border-border space-y-6">
        <h2 className="text-lg font-bold text-foreground flex items-center gap-2">
          <Mail className="h-5 w-5 text-brand" />
          SMTP Configuration
        </h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
              SMTP Server
            </Label>
            <Input
              placeholder="smtp.gmail.com"
              value={smtpServer}
              onChange={(e) => setSmtpServer(e.target.value)}
              className="bg-background border-border focus:border-brand/40 text-foreground"
            />
          </div>

          <div className="space-y-1.5">
            <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
              SMTP Port
            </Label>
            <Input
              type="number"
              placeholder="587"
              value={smtpPort}
              onChange={(e) => setSmtpPort(e.target.value)}
              className="bg-background border-border focus:border-brand/40 text-foreground"
            />
          </div>

          <div className="space-y-1.5">
            <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
              SMTP Username
            </Label>
            <Input
              placeholder="you@example.com"
              value={smtpUsername}
              onChange={(e) => setSmtpUsername(e.target.value)}
              className="bg-background border-border focus:border-brand/40 text-foreground"
              autoComplete="off"
            />
          </div>

          <div className="space-y-1.5">
            <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
              SMTP Password
            </Label>
            <Input
              type="password"
              placeholder={settings?.smtp_password_set ? '••••••••  (leave blank to keep)' : 'App password / API key'}
              value={smtpPassword}
              onChange={(e) => setSmtpPassword(e.target.value)}
              className="bg-background border-border focus:border-brand/40 text-foreground"
              autoComplete="new-password"
            />
          </div>

          <div className="space-y-1.5">
            <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
              HELO Hostname (optional)
            </Label>
            <Input
              placeholder="Defaults to SMTP server"
              value={smtpHeloHostname}
              onChange={(e) => setSmtpHeloHostname(e.target.value)}
              className="bg-background border-border focus:border-brand/40 text-foreground"
            />
          </div>
        </div>

        <div className="flex items-center justify-between">
          <div>
            <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
              Use TLS
            </Label>
            <p className="text-xs text-muted-foreground mt-1">
              Enable STARTTLS on port 587, or implicit SSL on port 465.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setSmtpUseTls((v) => !v)}
            className={cn(
              'flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-bold transition-all shrink-0',
              smtpUseTls
                ? 'bg-profit/10 border-profit/30 text-profit'
                : 'bg-background border-border text-muted-foreground hover:border-muted-foreground/40'
            )}
          >
            {smtpUseTls ? <ToggleRight className="h-4 w-4" /> : <ToggleLeft className="h-4 w-4" />}
            {smtpUseTls ? 'Enabled' : 'Disabled'}
          </button>
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

      {/* Platform Email Identities -- separate card so "who the email
          appears to come from" is configured independently from the SMTP
          transport above. All identities share the one SMTP login. */}
      <div className="p-6 rounded-2xl bg-card border border-border space-y-6">
        <div>
          <h2 className="text-lg font-bold text-foreground flex items-center gap-2">
            <AtSign className="h-5 w-5 text-brand" />
            Platform Email Identities
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Which "From" address each type of email is sent as. All use the single SMTP account
            above — set up matching aliases (e.g. noreply@, security@, billing@) on that mailbox.
            Any field left blank falls back to the Default Sender.
          </p>
        </div>

        {isIdentitiesLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading identities…
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                  Default Sender
                </Label>
                <Input
                  placeholder="noreply@maxalgos.com"
                  value={defaultSender}
                  onChange={(e) => setDefaultSender(e.target.value)}
                  className="bg-background border-border focus:border-brand/40 text-foreground"
                />
                <p className="text-[11px] text-muted-foreground">
                  Fallback for any identity below that's left blank.
                </p>
              </div>

              <div className="space-y-1.5">
                <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                  Verification Emails
                </Label>
                <Input
                  placeholder="noreply@maxalgos.com"
                  value={verificationSender}
                  onChange={(e) => setVerificationSender(e.target.value)}
                  className="bg-background border-border focus:border-brand/40 text-foreground"
                />
                <p className="text-[11px] text-muted-foreground">
                  Signup email verification.
                </p>
              </div>

              <div className="space-y-1.5">
                <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                  Security Emails
                </Label>
                <Input
                  placeholder="security@maxalgos.com"
                  value={securitySender}
                  onChange={(e) => setSecuritySender(e.target.value)}
                  className="bg-background border-border focus:border-brand/40 text-foreground"
                />
                <p className="text-[11px] text-muted-foreground">
                  Password reset and account-security notices.
                </p>
              </div>

              <div className="space-y-1.5">
                <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                  Billing Emails
                </Label>
                <Input
                  placeholder="billing@maxalgos.com"
                  value={billingSender}
                  onChange={(e) => setBillingSender(e.target.value)}
                  className="bg-background border-border focus:border-brand/40 text-foreground"
                />
                <p className="text-[11px] text-muted-foreground">
                  Payment and invoice emails.
                </p>
              </div>

              <div className="space-y-1.5">
                <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                  Notification Emails
                </Label>
                <Input
                  placeholder="notifications@maxalgos.com"
                  value={notificationsSender}
                  onChange={(e) => setNotificationsSender(e.target.value)}
                  className="bg-background border-border focus:border-brand/40 text-foreground"
                />
                <p className="text-[11px] text-muted-foreground">
                  Strategy and broker activity emails.
                </p>
              </div>

              <div className="space-y-1.5">
                <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                  Support Reply-To
                </Label>
                <Input
                  placeholder="support@maxalgos.com"
                  value={replyTo}
                  onChange={(e) => setReplyTo(e.target.value)}
                  className="bg-background border-border focus:border-brand/40 text-foreground"
                />
                <p className="text-[11px] text-muted-foreground">
                  Where user replies are routed (optional).
                </p>
              </div>
            </div>

            <div className="flex justify-end">
              <Button
                onClick={handleSaveIdentities}
                disabled={isSavingIdentities}
                className="bg-brand hover:bg-brand/90 text-brand-foreground font-bold px-6"
              >
                {isSavingIdentities ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Saving…
                  </>
                ) : (
                  <>
                    <Save className="h-4 w-4 mr-2" />
                    Save Identities
                  </>
                )}
              </Button>
            </div>
          </>
        )}
      </div>

      {/* Test email */}
      <div className="p-6 rounded-2xl bg-card border border-border space-y-4">
        <h2 className="text-lg font-bold text-foreground flex items-center gap-2">
          <Send className="h-5 w-5 text-brand" />
          Send Test Email
        </h2>
        <p className="text-xs text-muted-foreground">
          Uses the currently saved settings above (save first if you just changed them).
        </p>
        <div className="flex gap-3">
          <Input
            type="email"
            placeholder="test@example.com"
            value={testEmail}
            onChange={(e) => setTestEmail(e.target.value)}
            className="bg-background border-border focus:border-brand/40 text-foreground"
          />
          <Button
            onClick={handleSendTest}
            disabled={isTesting}
            variant="outline"
            className="shrink-0"
          >
            {isTesting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <>
                <Send className="h-4 w-4 mr-2" />
                Send Test
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  )
}
