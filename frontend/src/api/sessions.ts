/**
 * Sessions API — manage user's active login sessions.
 *
 * All routes live under /auth/* (Flask auth blueprint) and use the same
 * session cookie + X-CSRFToken pattern as the rest of the app.
 */

export interface ActiveSession {
  session_id: string
  device_info: string | null
  ip_address: string | null
  broker: string | null
  login_time: string | null
  last_seen: string | null
  is_current?: boolean // tagged client-side by comparing with current_session_id

  // Session Intelligence (see services/session_intelligence_service.py).
  // All nullable -- populated only for sessions created after this feature
  // shipped; older rows (pre-migration) fall back to device_info parsing.
  browser_family: string | null
  browser_version: string | null
  os_family: string | null
  os_version: string | null
  device_type: string | null
  device_brand: string | null
  windows_version: string | null
  screen_resolution: string | null
  timezone: string | null
  language: string | null
  platform: string | null
  hardware_concurrency: number | null
  device_memory_gb: number | null
  geo_country: string | null
  geo_region: string | null
  geo_city: string | null
  geo_isp: string | null
  is_trusted_device: boolean
}

export interface ActiveSessionsResponse {
  status: string
  sessions: ActiveSession[]
  current_session_id: string
}

export interface RevokeResponse {
  status: string
  sessions: ActiveSession[]
}

async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', { credentials: 'include' })
  const data = await response.json()
  return data.csrf_token as string
}

export const sessionsApi = {
  /** GET /auth/active-sessions — list all active sessions for the current user */
  list: async (): Promise<ActiveSessionsResponse> => {
    const response = await fetch('/auth/active-sessions', {
      credentials: 'include',
    })
    if (!response.ok) throw new Error('Failed to fetch sessions')
    return response.json()
  },

  /** DELETE /auth/active-sessions/:sessionId — revoke one specific session */
  revoke: async (sessionId: string): Promise<RevokeResponse> => {
    const csrf = await fetchCSRFToken()
    const response = await fetch(`/auth/active-sessions/${sessionId}`, {
      method: 'DELETE',
      credentials: 'include',
      headers: { 'X-CSRFToken': csrf },
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error((data as { message?: string }).message || 'Failed to revoke session')
    }
    return response.json()
  },

  /** POST /auth/active-sessions/logout-others — log out every session except this one */
  logoutOthers: async (): Promise<RevokeResponse> => {
    const csrf = await fetchCSRFToken()
    const response = await fetch('/auth/active-sessions/logout-others', {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/json' },
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error((data as { message?: string }).message || 'Failed to logout other sessions')
    }
    return response.json()
  },
}
