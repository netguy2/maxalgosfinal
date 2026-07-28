// api/masterRisk.ts
// Wraps blueprints/master_risk.py's /api/v1/master-risk/* routes. Same
// webClient (automatic CSRF) convention as api/killswitch.ts.

import axios from 'axios'
import { webClient } from './client'

export interface MasterRiskSettings {
  enabled: boolean
  sl_value: number | null
  target_value: number | null
  triggered_at: string | null
  triggered_reason: 'sl' | 'target' | null
}

export interface MasterRiskAuditEntry {
  id: number
  event_at: string | null
  reason: 'sl' | 'target'
  combined_pnl_at_trigger: number
  threshold_value: number
  positions_closed: number
  notes: string | null
}

interface ApiEnvelope {
  status: 'success' | 'error'
  message?: string
}

function errorMessage(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as ApiEnvelope | undefined
    if (data?.message) return data.message
  }
  return err instanceof Error ? err.message : fallback
}

export const masterRiskApi = {
  getSettings: async (): Promise<MasterRiskSettings | null> => {
    try {
      const response = await webClient.get<ApiEnvelope & MasterRiskSettings>(
        '/api/v1/master-risk/settings'
      )
      if (response.data.status !== 'success') return null
      return response.data
    } catch {
      return null
    }
  },

  updateSettings: async (
    enabled: boolean,
    slValue: number | null,
    targetValue: number | null
  ): Promise<{ success: boolean; settings?: MasterRiskSettings; message?: string }> => {
    try {
      const response = await webClient.post<ApiEnvelope & MasterRiskSettings>(
        '/api/v1/master-risk/settings',
        { enabled, sl_value: slValue, target_value: targetValue }
      )
      return { success: response.data.status === 'success', settings: response.data }
    } catch (err) {
      return { success: false, message: errorMessage(err, 'Failed to update Master SL/Target') }
    }
  },

  getAudit: async (limit = 50): Promise<MasterRiskAuditEntry[]> => {
    try {
      const response = await webClient.get<ApiEnvelope & { audit: MasterRiskAuditEntry[] }>(
        `/api/v1/master-risk/audit?limit=${limit}`
      )
      if (response.data.status !== 'success') return []
      return response.data.audit || []
    } catch {
      return []
    }
  },
}
