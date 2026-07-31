import { useEffect } from 'react'
import { profileMenuItems } from '@/config/navigation'
import { useAuthStore } from '@/stores/authStore'
import { useBrokerStore } from '@/stores/brokerStore'

/**
 * Profile dropdown items filtered by broker capabilities AND admin role.
 *
 * Single source of truth for menu gating, used by the shared Navbar AND the
 * standalone full-screen layouts (Playground, Historify, Historify Charts,
 * Automation Studio) so crypto-only items (Leverage) and equity-only items
 * (Holdings) never leak into the wrong broker's menus (GitHub issue #1480),
 * and admin-only items (the Admin panel) never show to regular users.
 */
export function useProfileMenuItems() {
  const { capabilities, isLoaded, fetchCapabilities } = useBrokerStore()
  const isAdmin = useAuthStore((s) => s.isAdmin)

  // Standalone layouts can mount without the main app shell having fetched
  // capabilities yet — fetch on demand so gating never runs on stale null.
  useEffect(() => {
    if (!isLoaded) {
      fetchCapabilities()
    }
  }, [isLoaded, fetchCapabilities])

  return profileMenuItems.filter((item) => {
    if (item.adminOnly && !isAdmin) return false
    if (item.href === '/leverage') return capabilities?.leverage_config === true
    if (item.href === '/holdings') return capabilities?.broker_type !== 'crypto'
    return true
  })
}
