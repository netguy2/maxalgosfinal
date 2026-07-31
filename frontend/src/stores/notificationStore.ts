import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface NotificationItem {
  id: string
  title: string
  message: string
  type: 'success' | 'error' | 'warning' | 'info'
  /** Epoch millis — sortable; format for display at render time. */
  createdAt: number
  /** Pre-formatted display time (kept for backwards compatibility). */
  timestamp: string
  read: boolean
}

interface NotificationState {
  notifications: NotificationItem[]
  addNotification: (
    notification: Omit<NotificationItem, 'id' | 'timestamp' | 'createdAt' | 'read'>
  ) => void
  markAsRead: (id: string) => void
  markAllAsRead: () => void
  clearAll: () => void
}

let seq = 0

export const useNotificationStore = create<NotificationState>()(
  persist(
    (set) => ({
      notifications: [],
      addNotification: (notif) => {
        const now = Date.now()
        const newNotif: NotificationItem = {
          ...notif,
          id: `${now}-${seq++}`,
          createdAt: now,
          timestamp: new Date(now).toLocaleTimeString(),
          read: false,
        }
        set((state) => ({
          notifications: [newNotif, ...state.notifications].slice(0, 50), // Keep last 50 alerts
        }))
      },
      markAsRead: (id) => {
        set((state) => ({
          notifications: state.notifications.map((n) => (n.id === id ? { ...n, read: true } : n)),
        }))
      },
      markAllAsRead: () => {
        set((state) => ({
          notifications: state.notifications.map((n) => ({ ...n, read: true })),
        }))
      },
      clearAll: () => {
        set({ notifications: [] })
      },
    }),
    {
      name: 'maxalgos-notifications',
      partialize: (state) => ({ notifications: state.notifications }),
    }
  )
)
