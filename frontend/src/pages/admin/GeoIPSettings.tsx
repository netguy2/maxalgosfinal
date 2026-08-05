import {
  AlertTriangle,
  CheckCircle2,
  DatabaseZap,
  Globe,
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

interface GeoIPSettingsData {
  enabled: boolean
  account_id: string | null
  license_key_set: boolean
  databases_downloaded: boolean
}

export default function GeoIPSettings() {
  const [settings, setSettings] = useState<GeoIPSettingsData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [enabled, setEnabled] = useState(false)
  const [accountIdInput, setAccountIdInput] = useState('')
  const [licenseKeyInput, setLicenseKeyInput] = useState('')

  const fetchSettings = useCallback(async () => {
    try {
      setIsLoading(true)
      setError(null)
      const res = await fetch('/admin/api/geoip', { credentials: 'include' })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        const s: GeoIPSettingsData = data.data
        setSettings(s)
        setEnabled(s.enabled)
        setAccountIdInput(s.account_id || '')
      } else {
        setError(data.message || 'Failed to fetch GeoIP settings')
      }
    } catch {
      setError('Failed to connect to server')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSettings()
  }, [fetchSettings])

  const handleSave = async () => {
    setIsSaving(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const res = await fetch('/admin/api/geoip', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          enabled,
          account_id: accountIdInput,
          license_key: licenseKeyInput, // blank = keep existing
        }),
      })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        showToast.success('GeoIP settings updated')
        setLicenseKeyInput('')
        await fetchSettings()
      } else {
        showToast.error(data.message || 'Failed to update GeoIP settings')
      }
    } catch {
      showToast.error('Network error. Please try again.')
    } finally {
      setIsSaving(false)
    }
  }

  const handleRefresh = async () => {
    setIsRefreshing(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const res = await fetch('/admin/api/geoip/refresh', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
      })
      const data = await res.json()
      if (res.ok && data.status === 'success') {
        showToast.success('GeoLite2 databases downloaded')
        await fetchSettings()
      } else {
        showToast.error(data.message || 'Failed to download GeoLite2 databases')
      }
    } catch {
      showToast.error('Network error. Please try again.')
    } finally {
      setIsRefreshing(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16 gap-3 text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        <span className="text-sm font-medium">Loading GeoIP settings…</span>
      </div>
    )
  }

  return (
    <div className="space-y-8 max-w-3xl mx-auto pb-10">
      {/* Header */}
      <PageHeader
        eyebrow="Admin Panel"
        title="GeoIP Settings"
        description="Configure MaxMind GeoLite2 for city/country/ISP lookup on the Active Sessions dashboard"
        actions={
          <button
            type="button"
            onClick={fetchSettings}
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

      {settings && (
        <div className="p-6 rounded-2xl bg-card border border-border space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-foreground flex items-center gap-2">
              <KeyRound className="h-5 w-5 text-brand" />
              MaxMind Credentials
            </h2>
            {settings.account_id && settings.license_key_set && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded border bg-profit/10 border-profit/20 text-profit">
                <CheckCircle2 className="h-3 w-3" />
                Configured
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground -mt-4">
            From your MaxMind account &gt; My License Keys. Sign up for a free GeoLite2 account at{' '}
            <a
              href="https://www.maxmind.com/en/geolite2/signup"
              target="_blank"
              rel="noopener noreferrer"
              className="text-brand hover:underline"
            >
              maxmind.com/en/geolite2/signup
            </a>{' '}
            if you don't have one yet.
          </p>

          {/* Enabled toggle */}
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                GeoIP Enabled
              </Label>
              <p className="text-xs text-muted-foreground mt-1">
                When off, Active Sessions shows IP address only, no city/country/ISP.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setEnabled((v) => !v)}
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs font-bold transition-all shrink-0',
                enabled
                  ? 'bg-profit/10 border-profit/30 text-profit'
                  : 'bg-background border-border text-muted-foreground hover:border-muted-foreground/40'
              )}
            >
              {enabled ? <ToggleRight className="h-4 w-4" /> : <ToggleLeft className="h-4 w-4" />}
              {enabled ? 'Enabled' : 'Disabled'}
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                Account ID
              </Label>
              <Input
                placeholder="123456"
                value={accountIdInput}
                onChange={(e) => setAccountIdInput(e.target.value)}
                className="bg-background border-border focus:border-brand/40 text-foreground font-mono text-sm"
                autoComplete="off"
              />
            </div>

            <div className="space-y-1.5">
              <Label className="text-muted-foreground text-xs font-semibold uppercase tracking-wider">
                License Key
              </Label>
              <Input
                type="password"
                placeholder={
                  settings.license_key_set ? '••••••••  (leave blank to keep)' : 'License key'
                }
                value={licenseKeyInput}
                onChange={(e) => setLicenseKeyInput(e.target.value)}
                className="bg-background border-border focus:border-brand/40 text-foreground"
                autoComplete="new-password"
              />
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

      {/* Database status */}
      {settings && (
        <div className="p-6 rounded-2xl bg-card border border-border space-y-4">
          <h2 className="text-lg font-bold text-foreground flex items-center gap-2">
            <Globe className="h-5 w-5 text-brand" />
            GeoLite2 Databases
          </h2>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <DatabaseZap className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm text-foreground">
                {settings.databases_downloaded ? 'Downloaded and active' : 'Not downloaded yet'}
              </span>
              <span
                className={cn(
                  'inline-flex items-center px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded border',
                  settings.databases_downloaded
                    ? 'bg-profit/10 border-profit/20 text-profit'
                    : 'bg-warning/10 border-warning/20 text-warning'
                )}
              >
                {settings.databases_downloaded ? 'Ready' : 'Pending'}
              </span>
            </div>
            <Button
              onClick={handleRefresh}
              disabled={isRefreshing || !settings.account_id || !settings.license_key_set}
              variant="outline"
              size="sm"
            >
              {isRefreshing ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Downloading…
                </>
              ) : (
                <>
                  <RefreshCw className="h-4 w-4 mr-2" />
                  Download Now
                </>
              )}
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            Databases refresh automatically once a month. Use "Download Now" after saving
            credentials for the first time, or to force an immediate update.
          </p>
        </div>
      )}
    </div>
  )
}
