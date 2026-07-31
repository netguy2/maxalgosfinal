import {
  AlertTriangle,
  Chrome,
  Clock,
  Globe,
  Laptop,
  LogOut,
  Monitor,
  RefreshCw,
  Shield,
  ShieldCheck,
  Smartphone,
  Tablet,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
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
import { type ActiveSession, sessionsApi } from '@/api/sessions'
import { useSessionStore } from '@/stores/sessionStore'
import { showToast } from '@/utils/toast'

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Parse a User-Agent string into a friendly device + browser label */
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

function DeviceIcon({
  ua,
  className,
}: {
  ua: string | null
  className?: string
}) {
  const s = ua || ''
  if (/iphone|android.*mobile|windows phone/i.test(s))
    return <Smartphone className={className} />
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
  const { device, browser, os } = parseDeviceLabel(session.device_info)

  return (
    <div
      className={`relative flex flex-col sm:flex-row sm:items-center gap-4 rounded-xl border p-4 transition-all duration-200 ${
        isCurrent
          ? 'border-emerald-500/40 bg-emerald-950/20'
          : 'border-zinc-800 bg-zinc-900/60 hover:border-zinc-700 hover:bg-zinc-900'
      }`}
    >
      {/* Device icon */}
      <div
        className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl ${
          isCurrent ? 'bg-emerald-900/50' : 'bg-zinc-800'
        }`}
      >
        <DeviceIcon
          ua={session.device_info}
          className={`h-6 w-6 ${isCurrent ? 'text-emerald-400' : 'text-zinc-400'}`}
        />
      </div>

      {/* Details */}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-zinc-100">
            {browser} on {os}
          </span>
          {isCurrent && (
            <Badge
              variant="outline"
              className="border-emerald-500/50 bg-emerald-950/50 text-emerald-400 text-xs"
            >
              <ShieldCheck className="mr-1 h-3 w-3" />
              This device
            </Badge>
          )}
        </div>

        <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm text-zinc-500">
          {session.ip_address && (
            <span className="flex items-center gap-1.5">
              <Globe className="h-3.5 w-3.5" />
              {session.ip_address}
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

        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-600">
          {session.login_time && (
            <span>Logged in {relativeTime(session.login_time)}</span>
          )}
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
          className="shrink-0 border-red-800/60 bg-red-950/20 text-red-400 hover:border-red-700 hover:bg-red-950/40 hover:text-red-300"
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
    <div className="flex items-center gap-4 rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
      <Skeleton className="h-12 w-12 shrink-0 rounded-xl bg-zinc-800" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-4 w-40 bg-zinc-800" />
        <Skeleton className="h-3 w-64 bg-zinc-800" />
        <Skeleton className="h-3 w-32 bg-zinc-800" />
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
      showToast.error(
        err instanceof Error ? err.message : 'Failed to revoke session',
        'system'
      )
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

  const otherSessionsCount = sessions.filter(
    (s) => s.session_id !== currentSessionId
  ).length

  return (
    <div className="mx-auto max-w-2xl space-y-6 px-4 py-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">Active Sessions</h1>
          <p className="mt-1 text-sm text-zinc-500">
            Manage devices that are currently logged into your account.
          </p>
        </div>
        <Button
          id="refresh-sessions-btn"
          variant="outline"
          size="sm"
          className="shrink-0 border-zinc-700 bg-zinc-900 text-zinc-400 hover:border-zinc-600 hover:text-zinc-300"
          onClick={() => loadSessions(true)}
          disabled={isRefreshing || isLoading}
        >
          <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Session list card */}
      <Card className="border-zinc-800 bg-zinc-950">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-4">
            <div>
              <CardTitle className="text-base font-medium text-zinc-200">
                {isLoading ? (
                  <Skeleton className="h-4 w-32 bg-zinc-800" />
                ) : (
                  <>
                    {sessions.length} active{' '}
                    {sessions.length === 1 ? 'session' : 'sessions'}
                  </>
                )}
              </CardTitle>
              <CardDescription className="mt-0.5 text-xs text-zinc-600">
                Sessions expire daily at 3:30 AM IST
              </CardDescription>
            </div>

            {otherSessionsCount > 0 && (
              <Button
                id="logout-others-btn"
                variant="outline"
                size="sm"
                className="shrink-0 border-orange-800/60 bg-orange-950/20 text-orange-400 hover:border-orange-700 hover:bg-orange-950/40 hover:text-orange-300"
                onClick={() => setShowLogoutOthersDialog(true)}
                disabled={isLogoutOthersLoading || isLoading}
              >
                <AlertTriangle className="mr-1.5 h-3.5 w-3.5" />
                Log out {otherSessionsCount} other{' '}
                {otherSessionsCount === 1 ? 'device' : 'devices'}
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
            <div className="py-8 text-center text-sm text-zinc-600">
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
      <Card className="border-zinc-800 bg-zinc-950">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-zinc-400">
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
            <p key={tip} className="text-xs text-zinc-600 leading-relaxed">
              • {tip}
            </p>
          ))}
        </CardContent>
      </Card>

      {/* Logout-others confirmation dialog */}
      <AlertDialog open={showLogoutOthersDialog} onOpenChange={setShowLogoutOthersDialog}>
        <AlertDialogContent className="border-zinc-800 bg-zinc-950 text-zinc-100">
          <AlertDialogHeader>
            <AlertDialogTitle>Log out all other devices?</AlertDialogTitle>
            <AlertDialogDescription className="text-zinc-500">
              This will immediately end{' '}
              <span className="font-medium text-zinc-300">
                {otherSessionsCount} other{' '}
                {otherSessionsCount === 1 ? 'session' : 'sessions'}
              </span>
              . Any active automation or strategies running from those devices may be
              interrupted. Your current session will not be affected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              id="cancel-logout-others-btn"
              className="border-zinc-700 bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-300"
            >
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              id="confirm-logout-others-btn"
              className="bg-orange-600 text-white hover:bg-orange-700"
              onClick={handleLogoutOthers}
            >
              <LogOut className="mr-1.5 h-4 w-4" />
              Log out {otherSessionsCount}{' '}
              {otherSessionsCount === 1 ? 'device' : 'devices'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
