import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { useBrokerStore } from '@/stores/brokerStore'
import { useSessionStore } from '@/stores/sessionStore'
import { useThemeStore } from '@/stores/themeStore'

// Routes an unsubscribed (but authenticated) user is still allowed to sit
// on -- everything else redirects to /subscribe when the platform-fee gate
// flags them. Auth/registration pages stay reachable so they can log out or
// switch accounts.
const SUBSCRIPTION_ALLOWED_PATHS = ['/subscribe', '/login', '/register', '/verify-email', '/reset-password']

interface AuthSyncProps {
  children: React.ReactNode
}

/**
 * AuthSync component that synchronizes Flask session with Zustand store.
 * This ensures the React app knows about authentication state from OAuth callbacks.
 * Also syncs app mode (live/analyzer) from the backend.
 */
export function AuthSync({ children }: AuthSyncProps) {
  const [isChecking, setIsChecking] = useState(true)
  const { setUser, setApiKey, setIsAdmin, logout } = useAuthStore()
  const { fetchCapabilities, clearCapabilities } = useBrokerStore()
  const { setActiveSessionCount } = useSessionStore()
  const { syncAppMode } = useThemeStore()
  const navigate = useNavigate()
  // Guards against syncSession running twice back-to-back for the same
  // trigger (e.g. StrictMode double-invoke in dev). It does NOT block
  // re-syncing forever -- see the tab-focus effect below, which re-runs
  // syncSession() whenever the tab regains focus. Without that, a single
  // early/racy /auth/session-status response (e.g. fired before a just-set
  // login cookie fully propagated, or before an admin flag was added to the
  // backend in a rolling deploy) would lock in a stale isAdmin/user value
  // for the rest of that tab's lifetime with no way to self-correct short
  // of a full manual reload.
  const isSyncingRef = useRef(false)
  const hasCompletedInitialSyncRef = useRef(false)

  useEffect(() => {
    const syncSession = async () => {
      if (isSyncingRef.current) {
        return
      }
      isSyncingRef.current = true
      try {
        const response = await fetch('/auth/session-status', {
          credentials: 'include',
        })

        if (response.ok) {
          const data = await response.json()

          if (data.status === 'success' && data.logged_in && data.broker) {
            // Flask session is authenticated with broker - sync to Zustand
            setUser({
              username: data.user,
              broker: data.broker,
              isLoggedIn: true,
              loginTime: new Date().toISOString(),
            })
            setIsAdmin(Boolean(data.is_admin))
            // Store the API key for trading API calls
            if (data.api_key) {
              setApiKey(data.api_key)
            }
            // Fetch broker capabilities (exchanges, type, features)
            await fetchCapabilities()
            // Also sync app mode from backend
            await syncAppMode()
            // Sync active session count
            if (data.active_sessions !== undefined) {
              setActiveSessionCount(data.active_sessions)
            }
          } else if (data.status === 'success' && data.authenticated && !data.broker) {
            // User has a valid app session but hasn't connected a broker
            // yet. Checking !data.broker (not !data.logged_in) matters: the
            // backend sets session["logged_in"] = True at password/TOTP
            // success regardless of whether a broker is connected (see
            // blueprints/auth.py login()/login_totp()), so logged_in alone
            // does not mean "has a broker". A fresh signup with no broker
            // ever connected has logged_in=True, broker=None -- the OLD
            // `!data.logged_in` check here made that combination match
            // NEITHER this branch nor the first one above (which requires
            // data.broker to be truthy), falling through to the final
            // else and calling logout() on every legitimately-logged-in
            // brokerless user, bouncing them straight back to /login.
            setUser({
              username: data.user,
              broker: null,
              isLoggedIn: false,
              loginTime: null,
            })
            setIsAdmin(Boolean(data.is_admin))
            clearCapabilities()
          } else {
            // Not authenticated or status is not success - clear Zustand store
            logout()
            clearCapabilities()
          }

          // Platform-fee gate: the server flags authenticated users without
          // an active subscription. Land them on /subscribe (server-side
          // enforcement already 403s every data endpoint regardless -- this
          // just gives them the right page instead of broken widgets).
          if (
            data.status === 'success' &&
            data.authenticated &&
            data.subscription_required &&
            !SUBSCRIPTION_ALLOWED_PATHS.some((p) => window.location.pathname.startsWith(p))
          ) {
            navigate('/subscribe', { replace: true })
          }
        } else {
          // Any non-OK response (401, 500, etc.) - clear Zustand store
          logout()
          clearCapabilities()
        }
      } catch (_error) {
        // On error, don't change auth state - let existing state persist
      } finally {
        // Only the very first sync should gate rendering behind the
        // full-screen spinner. Focus/visibility-triggered re-syncs must
        // update the store silently in the background -- flipping
        // isChecking back to true on every window focus would blank the
        // whole app out from under the user just to refresh isAdmin.
        if (!hasCompletedInitialSyncRef.current) {
          hasCompletedInitialSyncRef.current = true
          setIsChecking(false)
        }
        isSyncingRef.current = false
      }
    }

    syncSession()

    // Re-sync whenever the tab regains focus/visibility, so a session-status
    // value that went stale (role change, subscription change, or a rolling
    // deploy that landed mid-session) corrects itself without requiring the
    // user to know to hard-reload.
    const onFocus = () => {
      syncSession()
    }
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        syncSession()
      }
    }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [setUser, setApiKey, setIsAdmin, logout, fetchCapabilities, clearCapabilities, syncAppMode, setActiveSessionCount, navigate])

  // Show nothing while checking - prevents flash of wrong content
  if (isChecking) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  return <>{children}</>
}
