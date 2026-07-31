// api/killswitch.ts
// Wraps blueprints/killswitch.py's /api/v1/killswitch/* routes. Uses
// webClient (automatic CSRF) since activate/deactivate/scope are all
// state-changing. The backend accepts either a session cookie OR an
// apikey in the body -- the frontend always uses the session-cookie path
// (webClient sends credentials automatically), so no apikey is ever sent
// from here.

import axios from 'axios'
import { webClient } from './client'

export interface KillSwitchState {
  kill_switch_active: boolean
  activated_at: string | null
  activated_by: string | null
  reason: string | null
  min_unlock_at: string | null
  already_active?: boolean
  cleanup_summary?: Record<string, number>
}

export interface KillSwitchScope {
  cancel_orders_enabled: boolean
  close_positions_enabled: boolean
}

export interface KillSwitchAuditEntry {
  id: number
  event_at: string | null
  event_type: 'activated' | 'deactivated'
  actor_type: string
  actor_id: string | null
  reason: string | null
  live_orders_cancelled: number
  live_orders_failed: number
  live_positions_closed: number
  sandbox_orders_cancelled: number
  sandbox_positions_closed: number
  strategies_stopped: number
  flows_aborted: number
  notes: string | null
}

interface ApiEnvelope {
  status: 'success' | 'error'
  message?: string
  code?: string
  retry_after_seconds?: number
}

function errorMessage(
  err: unknown,
  fallback: string
): { message: string; code?: string; retryAfter?: number } {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as (ApiEnvelope & Record<string, unknown>) | undefined
    if (data?.message) {
      return { message: data.message, code: data.code, retryAfter: data.retry_after_seconds }
    }
  }
  return { message: err instanceof Error ? err.message : fallback }
}

export const killSwitchApi = {
  getStatus: async (): Promise<KillSwitchState | null> => {
    try {
      const response = await webClient.get<ApiEnvelope & KillSwitchState>(
        '/api/v1/killswitch/status'
      )
      if (response.data.status !== 'success') return null
      return response.data
    } catch {
      return null
    }
  },

  getScope: async (): Promise<KillSwitchScope | null> => {
    try {
      const response = await webClient.get<ApiEnvelope & { scope: KillSwitchScope }>(
        '/api/v1/killswitch/scope'
      )
      if (response.data.status !== 'success') return null
      return response.data.scope
    } catch {
      return null
    }
  },

  setScope: async (scope: KillSwitchScope): Promise<{ success: boolean; message?: string }> => {
    try {
      const response = await webClient.post<ApiEnvelope & { scope: KillSwitchScope }>(
        '/api/v1/killswitch/scope',
        scope
      )
      return { success: response.data.status === 'success' }
    } catch (err) {
      return {
        success: false,
        message: errorMessage(err, 'Failed to update kill switch settings').message,
      }
    }
  },

  activate: async (
    reason?: string
  ): Promise<{ success: boolean; state?: KillSwitchState; message?: string }> => {
    try {
      const response = await webClient.post<ApiEnvelope & KillSwitchState>(
        '/api/v1/killswitch/activate',
        { reason }
      )
      return { success: response.data.status === 'success', state: response.data }
    } catch (err) {
      return {
        success: false,
        message: errorMessage(err, 'Failed to activate kill switch').message,
      }
    }
  },

  deactivate: async (
    confirmation: string
  ): Promise<{ success: boolean; message?: string; code?: string; retryAfterSeconds?: number }> => {
    try {
      const response = await webClient.post<ApiEnvelope & KillSwitchState>(
        '/api/v1/killswitch/deactivate',
        { confirmation }
      )
      return { success: response.data.status === 'success' }
    } catch (err) {
      const { message, code, retryAfter } = errorMessage(err, 'Failed to deactivate kill switch')
      return { success: false, message, code, retryAfterSeconds: retryAfter }
    }
  },

  getAudit: async (limit = 50): Promise<KillSwitchAuditEntry[]> => {
    try {
      const response = await webClient.get<ApiEnvelope & { audit: KillSwitchAuditEntry[] }>(
        `/api/v1/killswitch/audit?limit=${limit}`
      )
      if (response.data.status !== 'success') return []
      return response.data.audit || []
    } catch {
      return []
    }
  },
}
