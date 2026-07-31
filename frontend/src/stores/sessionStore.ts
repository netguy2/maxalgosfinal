import { create } from 'zustand'
import type { ActiveSession } from '@/api/sessions'

interface SessionStore {
  activeSessionCount: number
  activeSessions: ActiveSession[]
  currentSessionId: string | null
  setActiveSessionCount: (count: number) => void
  setActiveSessions: (sessions: ActiveSession[], currentSessionId?: string) => void
}

export const useSessionStore = create<SessionStore>((set) => ({
  activeSessionCount: 0,
  activeSessions: [],
  currentSessionId: null,
  setActiveSessionCount: (count) => set({ activeSessionCount: count }),
  setActiveSessions: (sessions, currentSessionId) =>
    set((state) => ({
      activeSessions: sessions,
      activeSessionCount: sessions.length,
      currentSessionId: currentSessionId ?? state.currentSessionId,
    })),
}))
