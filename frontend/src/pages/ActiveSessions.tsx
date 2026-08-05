import {
  AlertTriangle,
  Chrome,
  Clock,
  Globe,
  Laptop,
  LogOut,
  MapPin,
  Monitor,
  RefreshCw,
  Shield,
  ShieldCheck,
  ShieldQuestion,
  Smartphone,
  Tablet,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { type ActiveSession, sessionsApi } from '@/api/sessions'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useSessionStore } from '@/stores/sessionStore'
import { showToast } from '@/utils/toast'

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Build the "Chrome 139 on Windows 11" style label from server-parsed
 * Session Intelligence fields, falling back to client-side UA regex
 * parsing for sessions created before that feature shipped (server fields
 * all null on those rows). */
function buildDeviceLabel(session: ActiveSession): { device: string; browser: string; os: string } {
  if (session.browser_family || session.os_family) {
    const browser = session.browser_family
      ? `${session.browser_family}${session.browser_version ? ` ${session.browser_version.split('.')[0]}` : ''}`
      : 'Unknown browser'
    const os =
      session.os_family === 'Windows' && session.windows_version
        ? `Windows ${session.windows_version}`
        : session.os_family
          ? `${session.os_family}${session.os_version ? ` ${session.os_version}` : ''}`
          : 'Unknown OS'
    const device = session.device_type
      ? session.device_type.charAt(0).toUpperCase() + session.device_type.slice(1)
      : 'Desktop'
    return { device, browser, os }
  }
  return parseDeviceLabel(session.device_info)
}

/** Location string from GeoIP fields, e.g. "Chennai, Tamil Nadu, India".
 * Returns null when GeoIP wasn't configured/enabled at login time (all
 * geo_* fields null) or the IP was private (see utils/ip_helper.py). */
function buildLocationLabel(session: ActiveSession): string | null {
  const parts = [session.geo_city, session.geo_region, session.geo_country].filter(Boolean)
  return parts.length > 0 ? parts.join(', ') : null
}

/** Parse a User-Agent string into a friendly device + browser label.
 * Fallback path only — used when the server hasn't parsed this session
 * (rows created before Session Intelligence shipped). */
function parseDeviceLabel(ua: string | null): { device: string; browser: string; os: string } {
  const s = ua || ''

  // Device type
  let device = 'Desktop'
  if (/iphone|android.*mobile|windows phone/i.test(s)) device = 'Phone'
  else if (/ipad|tablet|kindle/i.test(s)) device = 'Tablet'

  // OS
  let os = 'Unknown OS'
  if (/windows nt 10/i.test(s)) os = 'Windows 10/11'
  else if (/windows nt/i.test(s)) os = 'Windows'
  else if (/mac os x/i.test(s)) os = 'macOS'
  else if (/android/i.test(s)) os = 'Android'
  else if (/iphone os|cpu os/i.test(s)) os = 'iOS'
  else if (/linux/i.test(s)) os = 'Linux'

  // Browser
  let browser = 'Unknown browser'
  if (/edg\//i.test(s)) browser = 'Edge'
  else if (/opr\//i.test(s)) browser = 'Opera'
  else if (/chrome\/[0-9]/i.test(s) && !/chromium/i.test(s)) browser = 'Chrome'
  else if (/firefox\//i.test(s)) browser = 'Firefox'
  else if (/safari\//i.test(s) && !/chrome/i.test(s)) browser = 'Safari'
  else if (/postmanruntime/i.test(s)) browser = 'Postman'
  else if (/python-requests|okhttp|curl|insomnia/i.test(s)) browser = 'API Client'

  return { device, browser, os }
}

function DeviceIcon({ ua, className }: { ua: string | null; className?: string }) {
  const s = ua || ''
  if (/iphone|android.*mobile|windows phone/i.test(s)) return <Smartphone className={className} />
  if (/ipad|tablet|kindle/i.test(s)) return <Tablet className={className} />
  if (/chrome/i.test(s)) return <Chrome className={className} />
  return <Monitor className={className} />
}

/** Format ISO string as relative time */
function relativeTime(iso: string | null): string {
  if (!iso) return 'Unknown'
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

// ─── Session Card ─────────────────────────────────────────────────────────────

function SessionCard({
  session,
  isCurrent,
  onRevoke,
  isRevoking,
}: {
  session: ActiveSession
  isCurrent: boolean
  onRevoke: (id: string) => void
  isRevoking: boolean
}) {
  const { device, browser, os } = buildDeviceLabel(session)
  const location = buildLocationLabel(session)

  return (
    <div
      className={`relative flex flex-col sm:flex-row sm:items-center gap-4 rounded-xl border p-4 transition-all duration-200 ${
        isCurrent
          ? 'border-profit/40 bg-profit/10'
          : 'border-border bg-muted/60 hover:border-muted-foreground/30 hover:bg-muted'
      }`}
    >
      {/* Device icon */}
      <div
        className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl ${
          isCurrent ? 'bg-profit/20' : 'bg-muted'
        }`}
      >
        <DeviceIcon
          ua={session.device_info}
          className={`h-6 w-6 ${isCurrent ? 'text-profit' : 'text-muted-foreground'}`}
        />
      </div>

      {/* Details */}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-foreground">
            {browser} on {os}
          </span>
          {isCurrent && (
            <Badge variant="outline" className="border-profit/50 bg-profit/10 text-profit text-xs">
              <ShieldCheck className="mr-1 h-3 w-3" />
              This device
            </Badge>
          )}
          {!isCurrent && session.is_trusted_device && (
            <Badge
              variant="outline"
              className="border-muted-foreground/30 bg-muted text-muted-foreground text-xs"
            >
              <ShieldCheck className="mr-1 h-3 w-3" />
              Trusted device
            </Badge>
          )}
          {!isCurrent && !session.is_trusted_device && (
            <Badge
              variant="outline"
              className="border-warning/40 bg-warning/10 text-warning text-xs"
            >
              <ShieldQuestion className="mr-1 h-3 w-3" />
              New device
            </Badge>
          )}
        </div>

        <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
          {session.ip_address && (
            <span className="flex items-center gap-1.5">
              <Globe className="h-3.5 w-3.5" />
              {session.ip_address}
            </span>
          )}
          {location && (
            <span className="flex items-center gap-1.5">
              <MapPin className="h-3.5 w-3.5" />
              {location}
              {session.geo_isp ? ` · ${session.geo_isp}` : ''}
            </span>
          )}
          <span className="flex items-center gap-1.5">
            <Laptop className="h-3.5 w-3.5" />
            {device}
          </span>
          {session.broker && (
            <span className="flex items-center gap-1.5">
              <Shield className="h-3.5 w-3.5" />
              {session.broker}
            </span>
          )}
        </div>

        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground/70">
          {session.login_time && <span>Logged in {relativeTime(session.login_time)}</span>}
          {session.last_seen && (
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              Active {relativeTime(session.last_seen)}
            </span>
          )}
        </div>
      </div>

      {/* Action */}
      {!isCurrent && (
        <Button
          id={`revoke-session-${session.session_id.slice(0, 8)}`}
          variant="outline"
          size="sm"
          className="shrink-0 border-loss/40 bg-loss/10 text-loss hover:border-loss/60 hover:bg-loss/20 hover:text-loss"
          onClick={() => onRevoke(session.session_id)}
          disabled={isRevoking}
        >
          <LogOut className="mr-1.5 h-3.5 w-3.5" />
          Log out
        </Button>
      )}
    </div>
  )
}

// ─── Skeleton loader ──────────────────────────────────────────────────────────

function SessionSkeleton() {
  return (
    <div className="flex items-center gap-4 rounded-xl border border-border bg-muted/60 p-4">
      <Skeleton className="h-12 w-12 shrink-0 rounded-xl" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-3 w-64" />
        <Skeleton className="h-3 w-32" />
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ActiveSessions() {
  const [sessions, setSessions] = useState<ActiveSession[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [revokingId, setRevokingId] = useState<string | null>(null)
  const [isLogoutOthersLoading, setIsLogoutOthersLoading] = useState(false)
  const [showLogoutOthersDialog, setShowLogoutOthersDialog] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)

  // Also read live sessions from store (pushed via socket active_sessions_update)
  const storeSessions = useSessionStore((s) => s.activeSessions)
  const storeSessionId = useSessionStore((s) => s.currentSessionId)

  const loadSessions = useCallback(async (showRefreshSpinner = false) => {
    if (showRefreshSpinner) setIsRefreshing(true)
    else setIsLoading(true)
    try {
      const data = await sessionsApi.list()
      setSessions(data.sessions || [])
      setCurrentSessionId(data.current_session_id)
    } catch {
      showToast.error('Failed to load active sessions', 'system')
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [])

  // Initial load
  // biome-ignore lint/correctness/useExhaustiveDependencies: one-time load on mount
  useEffect(() => {
    loadSessions()
  }, [])

  // Sync live updates from socket store (if the socket pushed a fresh list)
  useEffect(() => {
    if (storeSessions.length > 0) {
      setSessions(storeSessions)
    }
    if (storeSessionId) {
      setCurrentSessionId(storeSessionId)
    }
  }, [storeSessions, storeSessionId])

  const handleRevoke = async (sessionId: string) => {
    setRevokingId(sessionId)
    try {
      const data = await sessionsApi.revoke(sessionId)
      setSessions(data.sessions || [])
      showToast.success('Device logged out successfully', 'system')
    } catch (err) {
      showToast.error(err instanceof Error ? err.message : 'Failed to revoke session', 'system')
    } finally {
      setRevokingId(null)
    }
  }

  const handleLogoutOthers = async () => {
    setShowLogoutOthersDialog(false)
    setIsLogoutOthersLoading(true)
    try {
      const data = await sessionsApi.logoutOthers()
      setSessions(data.sessions || [])
      showToast.success('All other devices have been logged out', 'system')
    } catch (err) {
      showToast.error(
        err instanceof Error ? err.message : 'Failed to logout other devices',
        'system'
      )
    } finally {
      setIsLogoutOthersLoading(false)
    }
  }

  const otherSessionsCount = sessions.filter((s) => s.session_id !== currentSessionId).length

  return (
    <PageContainer width="narrow">
      {/* Header */}
      <PageHeader
        title="Active Sessions"
        description="Manage devices that are currently logged into your account."
        actions={
          <Button
            id="refresh-sessions-btn"
            variant="outline"
            size="sm"
            className="shrink-0"
            onClick={() => loadSessions(true)}
            disabled={isRefreshing || isLoading}
          >
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        }
      />

      {/* Session list card */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-4">
            <div>
              <CardTitle className="text-base font-medium text-foreground">
                {isLoading ? (
                  <Skeleton className="h-4 w-32" />
                ) : (
                  <>
                    {sessions.length} active {sessions.length === 1 ? 'session' : 'sessions'}
                  </>
                )}
              </CardTitle>
              <CardDescription className="mt-0.5 text-xs">
                Sessions expire daily at 3:30 AM IST
              </CardDescription>
            </div>

            {otherSessionsCount > 0 && (
              <Button
                id="logout-others-btn"
                variant="outline"
                size="sm"
                className="shrink-0 border-warning/40 bg-warning/10 text-warning hover:border-warning/60 hover:bg-warning/20 hover:text-warning"
                onClick={() => setShowLogoutOthersDialog(true)}
                disabled={isLogoutOthersLoading || isLoading}
              >
                <AlertTriangle className="mr-1.5 h-3.5 w-3.5" />
                Log out {otherSessionsCount} other {otherSessionsCount === 1 ? 'device' : 'devices'}
              </Button>
            )}
          </div>
        </CardHeader>

        <CardContent className="space-y-3 pb-4">
          {isLoading ? (
            <>
              <SessionSkeleton />
              <SessionSkeleton />
            </>
          ) : sessions.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              No active sessions found.
            </div>
          ) : (
            sessions.map((session) => (
              <SessionCard
                key={session.session_id}
                session={session}
                isCurrent={session.session_id === currentSessionId}
                onRevoke={handleRevoke}
                isRevoking={revokingId === session.session_id}
              />
            ))
          )}
        </CardContent>
      </Card>

      {/* Security tips card */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <Shield className="h-4 w-4" />
            Security tips
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 pb-4">
          {[
            "Log out devices you no longer use or don't recognise.",
            'A new-device email alert is sent whenever your account is accessed from an unfamiliar device.',
            "If you see a session you don't recognise, log it out and change your password immediately.",
          ].map((tip) => (
            <p key={tip} className="text-xs text-muted-foreground leading-relaxed">
              • {tip}
            </p>
          ))}
        </CardContent>
      </Card>

      {/* Logout-others confirmation dialog */}
      <AlertDialog open={showLogoutOthersDialog} onOpenChange={setShowLogoutOthersDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Log out all other devices?</AlertDialogTitle>
            <AlertDialogDescription>
              This will immediately end{' '}
              <span className="font-medium text-foreground">
                {otherSessionsCount} other {otherSessionsCount === 1 ? 'session' : 'sessions'}
              </span>
              . Any active automation or strategies running from those devices may be interrupted.
              Your current session will not be affected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel id="cancel-logout-others-btn">Cancel</AlertDialogCancel>
            <AlertDialogAction
              id="confirm-logout-others-btn"
              className="bg-warning text-warning-foreground hover:bg-warning/90"
              onClick={handleLogoutOthers}
            >
              <LogOut className="mr-1.5 h-4 w-4" />
              Log out {otherSessionsCount} {otherSessionsCount === 1 ? 'device' : 'devices'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageContainer>
  )
}
