import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { useBrokerStore } from './brokerStore'

interface User {
  username: string
  broker: string | null
  isLoggedIn: boolean
  loginTime: string | null
}

interface AuthStore {
  user: User | null
  apiKey: string | null
  isAuthenticated: boolean
  // Whether the current user is a platform admin. Sourced from
  // /auth/session-status (see AuthSync). Used to hide admin-only navigation
  // and guard /admin/* routes on the client -- the backend still enforces
  // admin access with 403s, so this is UX, never the security boundary.
  isAdmin: boolean
  // True until a real API call surfaces BROKER_SESSION_EXPIRED (see
  // Dashboard.tsx's fetchFundsData). user.broker only records which broker
  // was last connected, not whether that session is still valid server-side
  // - components that show a "Broker Status: Connected" indicator (e.g.
  // Footer.tsx) need this instead, or they show green after the broker's
  // token has actually expired/been revoked.
  brokerSessionValid: boolean

  setUser: (user: User) => void
  setApiKey: (apiKey: string | null) => void
  setBrokerSessionValid: (valid: boolean) => void
  setIsAdmin: (isAdmin: boolean) => void
  login: (username: string, broker: string) => void
  logout: () => void
  checkSession: () => boolean
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set, get) => ({
      user: null,
      apiKey: null,
      isAuthenticated: false,
      isAdmin: false,
      brokerSessionValid: true,

      // isAuthenticated means "has a valid Max Algos app session" - it must
      // NOT be tied to whether a broker happens to be connected
      // (user.isLoggedIn). AuthSync.tsx calls setUser() with
      // isLoggedIn: false for the legitimate "logged into the app, no
      // broker connected yet" state (see /auth/session-status's
      // authenticated/logged_in distinction) - conflating the two here
      // made isAuthenticated false whenever no broker was connected,
      // which made Layout.tsx's route guard bounce the user to /login
      // the instant they disconnected a broker, including when navigating
      // TO Broker Management specifically to reconnect one (a deadlock:
      // the only page that can fix "no broker connected" became
      // unreachable in that exact state).
      setUser: (user) => set({ user, isAuthenticated: true, brokerSessionValid: true }),

      setApiKey: (apiKey) => set({ apiKey }),

      setBrokerSessionValid: (valid) => set({ brokerSessionValid: valid }),

      setIsAdmin: (isAdmin) => set({ isAdmin }),

      login: (username, broker) => {
        const user: User = {
          username,
          broker,
          isLoggedIn: true,
          loginTime: new Date().toISOString(),
        }
        set({ user, isAuthenticated: true, brokerSessionValid: true })
      },

      logout: () => {
        set({
          user: null,
          isAuthenticated: false,
          isAdmin: false,
          apiKey: null,
          brokerSessionValid: true,
        })
      },

      checkSession: () => {
        const { user } = get()
        if (!user || !user.loginTime) return false

        // Skip session expiry for crypto brokers (24/7 markets)
        const capabilities = useBrokerStore.getState().capabilities
        if (capabilities?.broker_type === 'crypto') {
          return true
        }

        // Session expiry check (3 AM IST daily)
        const now = new Date()
        const loginTime = new Date(user.loginTime)

        // Convert to IST properly: UTC + 5.5 hours
        // First get UTC time, then add IST offset
        const istOffsetMs = 5.5 * 60 * 60 * 1000
        const localOffsetMs = now.getTimezoneOffset() * 60 * 1000

        // Convert current time to IST
        const nowUTC = now.getTime() + localOffsetMs
        const nowIST = new Date(nowUTC + istOffsetMs)

        // Convert login time to IST
        const loginUTC = loginTime.getTime() + localOffsetMs
        const loginIST = new Date(loginUTC + istOffsetMs)

        // Create today's 3 AM IST expiry time
        const todayExpiry = new Date(nowIST)
        todayExpiry.setHours(3, 0, 0, 0)

        // If current time is after 3 AM IST today and login was before 3 AM IST today
        if (nowIST > todayExpiry && loginIST < todayExpiry) {
          get().logout()
          return false
        }

        return true
      },
    }),
    {
      name: 'maxalgos-auth',
    }
  )
)
