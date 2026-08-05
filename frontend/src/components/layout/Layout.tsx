import { useEffect, useRef, useState } from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { SocketProvider } from '@/components/socket/SocketProvider'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { useAuthStore } from '@/stores/authStore'
import { Footer } from './Footer'
import { MobileBottomNav } from './MobileBottomNav'
import { Navbar } from './Navbar'
import { AppSidebar } from './Sidebar'

// How long an unauthenticated read is tolerated before actually redirecting.
// Zustand's persist middleware hydrates from localStorage asynchronously; a
// freshly-mounted Layout can observe isAuthenticated as false for one tick
// even immediately after Login.tsx set it true, if this component mounts in
// the same frame persist is still catching up. A single false reading no
// longer bounces the user straight back to /login -- it must stay false
// across a short grace window first.
const AUTH_BOUNCE_GRACE_MS = 400

export function Layout() {
  const { isAuthenticated } = useAuthStore()
  const [shouldRedirect, setShouldRedirect] = useState(false)
  const graceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (isAuthenticated) {
      // Authenticated (or became authenticated) -- cancel any pending
      // redirect and reset so a later logout still redirects promptly.
      if (graceTimerRef.current) {
        clearTimeout(graceTimerRef.current)
        graceTimerRef.current = null
      }
      setShouldRedirect(false)
      return
    }

    // Not authenticated: wait out the grace window before actually
    // redirecting, in case this is a transient read during store hydration
    // right after login rather than a genuine logged-out state.
    graceTimerRef.current = setTimeout(() => {
      setShouldRedirect(true)
    }, AUTH_BOUNCE_GRACE_MS)

    return () => {
      if (graceTimerRef.current) {
        clearTimeout(graceTimerRef.current)
        graceTimerRef.current = null
      }
    }
  }, [isAuthenticated])

  if (!isAuthenticated && shouldRedirect) {
    return <Navigate to="/login" replace />
  }

  if (!isAuthenticated) {
    // Within the grace window -- render nothing rather than the protected
    // page shell (avoids a flash of sidebar/nav before we know for sure).
    return null
  }

  return (
    <SocketProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset className="h-svh overflow-hidden">
          <Navbar />
          {/* Owns the page's outer padding only. Width capping and vertical
              rhythm belong to <PageContainer>, which each page renders at its
              root -- the old `container mx-auto` wrapper here fought with the
              per-page containers and produced doubled padding. */}
          <main className="flex-1 overflow-y-auto px-4 md:px-6 py-6 pb-24 md:pb-6">
            <Outlet />
          </main>
          <Footer className="hidden md:block shrink-0" />
          <MobileBottomNav />
        </SidebarInset>
      </SidebarProvider>
    </SocketProvider>
  )
}

export function PublicLayout() {
  return (
    <div className="min-h-screen bg-background">
      <Outlet />
    </div>
  )
}
