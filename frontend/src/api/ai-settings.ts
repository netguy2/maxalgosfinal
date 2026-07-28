// api/ai-settings.ts
// Wrappers around blueprints/ai_settings.py's session-authenticated REST
// endpoints for the user's own AI provider configuration (AI Insight
// feature on the Charts page). Uses webClient (frontend/src/api/client.ts)
// — its request interceptor attaches X-CSRFToken automatically on
// POST/DELETE, no manual CSRF handling needed (same pattern as
// api/indicator-presets.ts). The decrypted API key is never returned by
// the backend — only whether one is configured (hasApiKey).

import axios from 'axios'
import { webClient } from './client'

export type AiProvider = 'openai' | 'anthropic' | 'gemini' | 'custom'

export interface AiSettings {
  provider: AiProvider
  model: string | null
  baseUrl: string | null
  hasApiKey: boolean
  newsProvider: string | null
  hasNewsApiKey: boolean
}

interface ApiEnvelope<T> {
  status: 'success' | 'error'
  message?: string
  data?: T
}

function errorMessage(err: unknown, fallback: string): string {
  // webClient's response interceptor rejects the promise on any non-2xx
  // status (e.g. 400 invalid provider) rather than resolving with the
  // error body — unwrap the backend's JSON message when present.
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as ApiEnvelope<never> | undefined
    if (data?.message) return data.message
  }
  return err instanceof Error ? err.message : fallback
}

export const aiSettingsApi = {
  get: async (): Promise<AiSettings | null> => {
    try {
      const response = await webClient.get<ApiEnvelope<AiSettings | null>>('/ai-settings/api/get')
      if (response.data.status !== 'success') return null
      return response.data.data ?? null
    } catch {
      return null
    }
  },

  save: async (
    provider: AiProvider,
    apiKey: string,
    model?: string,
    baseUrl?: string
  ): Promise<{ success: boolean; message?: string }> => {
    try {
      const response = await webClient.post<ApiEnvelope<AiSettings>>('/ai-settings/api/save', {
        provider,
        apiKey,
        model,
        baseUrl,
      })
      return { success: response.data.status === 'success', message: response.data.message }
    } catch (err) {
      return { success: false, message: errorMessage(err, 'Failed to save AI settings') }
    }
  },

  remove: async (): Promise<boolean> => {
    try {
      const response = await webClient.delete<ApiEnvelope<void>>('/ai-settings/api/delete')
      return response.data.status === 'success'
    } catch {
      return false
    }
  },

  saveNews: async (
    newsProvider: string,
    newsApiKey: string
  ): Promise<{ success: boolean; message?: string }> => {
    try {
      const response = await webClient.post<ApiEnvelope<AiSettings>>('/ai-settings/api/save-news', {
        newsProvider,
        newsApiKey,
      })
      return { success: response.data.status === 'success', message: response.data.message }
    } catch (err) {
      return { success: false, message: errorMessage(err, 'Failed to save news settings') }
    }
  },
}
