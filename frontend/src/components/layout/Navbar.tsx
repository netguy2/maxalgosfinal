import { BarChart3, Bell, BookOpen, CreditCard, LogOut, Menu, Moon, Sun, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { authApi } from '@/api/auth'
import { LogoutConfirmDialog } from '@/components/auth/LogoutConfirmDialog'
import { KillSwitchButton } from '@/components/layout/KillSwitchButton'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { isActiveRoute, mobileSheetItems } from '@/config/navigation'
import { useProfileMenuItems } from '@/hooks/useProfileMenuItems'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useNotificationStore } from '@/stores/notificationStore'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

export function Navbar() {
  const location = useLocation()
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [showLogoutDialog, setShowLogoutDialog] = useState(false)
  const { mode, appMode, toggleMode, toggleAppMode, isTogglingMode } = useThemeStore()
  const { user, logout, isAdmin } = useAuthStore()
  const { notifications, markAllAsRead, clearAll } = useNotificationStore()

  // Profile menu filtered by broker capabilities (shared hook, issue #1480)
  const filteredProfileMenuItems = useProfileMenuItems()

  // Persistent "Subscribed" indicator -- admins bypass the subscription
  // gate entirely (no PlatformSubscription row required, see
  // blueprints/auth.py login()'s `not user.is_admin` check) so this only
  // fetches/renders for non-admin accounts. Fetched once per mount rather
  // than on every navigation; the badge doesn't need to react instantly to
  // a renewal happening in another tab.
  const [hasActiveSubscription, setHasActiveSubscription] = useState(false)
  useEffect(() => {
    if (isAdmin) return
    fetch('/payments/subscription/status', { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.status === 'success') {
          setHasActiveSubscription(Boolean(data.data?.has_active_subscription))
        }
      })
      .catch(() => {
        // Silently skip -- absence of the badge is a cosmetic-only gap,
        // not something worth surfacing an error for.
      })
  }, [isAdmin])

  const [timeStr, setTimeStr] = useState<string>('')
  const [marketStatus, setMarketStatus] = useState<'Open' | 'Closed'>('Closed')

  // Real-time Clock
  useEffect(() => {
    const updateClock = () => {
      const now = new Date()
      setTimeStr(
        now.toLocaleTimeString('en-US', {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: true,
        })
      )
    }

    updateClock()
    const timer = setInterval(updateClock, 1000)
    return () => clearInterval(timer)
  }, [])

  // Market Status Check (IST: Mon-Fri, 9:15 AM - 3:30 PM)
  useEffect(() => {
    const checkMarket = () => {
      const now = new Date()
      const utc = now.getTime() + now.getTimezoneOffset() * 60000
      const istTime = new Date(utc + 3600000 * 5.5)

      const day = istTime.getDay() // 0 = Sun, 6 = Sat
      const hours = istTime.getHours()
      const minutes = istTime.getMinutes()
      const totalMinutes = hours * 60 + minutes

      const isWeekday = day >= 1 && day <= 5
      const isMarketHours = totalMinutes >= 9 * 60 + 15 && totalMinutes <= 15 * 60 + 30

      setMarketStatus(isWeekday && isMarketHours ? 'Open' : 'Closed')
    }

    checkMarket()
    const timer = setInterval(checkMarket, 60000) // check every minute
    return () => clearInterval(timer)
  }, [])

  const handleLogout = async () => {
    try {
      await authApi.logout()
      logout()
      navigate('/login')
      showToast.success('Logged out successfully')
    } catch {
      logout()
      navigate('/login')
    }
  }

  const handleModeToggle = async () => {
    const result = await toggleAppMode()
    if (result.success) {
      const newMode = useThemeStore.getState().appMode
      showToast.success(`Switched to ${newMode === 'live' ? 'Live' : 'Analyze'} mode`)

      // Show warning toast when enabling analyzer mode (like old UI)
      if (newMode === 'analyzer') {
        setTimeout(() => {
          showToast.warning('Analyzer (Sandbox) mode is for testing purposes only', undefined, {
            duration: 10000,
          })
        }, 2000)
      }
    } else {
      showToast.error(result.message || 'Failed to toggle mode')
    }
  }

  const isActive = (href: string) => isActiveRoute(location.pathname, href)

  return (
    <nav className="sticky top-0 z-50 w-full border-b border-border bg-card/60 backdrop-blur supports-[backdrop-filter]:bg-card/40">
      <div className="container mx-auto px-4 flex h-14 items-center">
        {/* Mobile Menu */}
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild className="md:hidden">
            <Button variant="ghost" size="icon" className="mr-2 min-h-[44px] min-w-[44px]">
              <Menu className="h-5 w-5" />
              <span className="sr-only">Toggle menu</span>
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72 overflow-y-auto">
            {/* Visually hidden but accessible for screen readers */}
            <SheetHeader className="sr-only">
              <SheetTitle>Navigation Menu</SheetTitle>
              <SheetDescription>Main navigation and quick access links</SheetDescription>
            </SheetHeader>
            <div className="flex flex-col gap-4 py-4">
              <Link
                to="/dashboard"
                className="flex items-center gap-2 px-2"
                onClick={() => setMobileOpen(false)}
              >
                <img src="/logo.png" alt="Max Algos" className="h-8 w-8" />
                <span className="font-semibold">Max Algos</span>
              </Link>

              {/* Secondary nav items (not in bottom nav) */}
              <nav className="flex flex-col gap-1">
                <div className="px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Navigation
                </div>
                {mobileSheetItems.map((item) => (
                  <Link
                    key={item.href}
                    to={item.href}
                    onClick={() => setMobileOpen(false)}
                    className={cn(
                      'flex items-center gap-3 rounded-lg px-3 py-3 text-sm transition-colors min-h-[44px] touch-manipulation',
                      isActive(item.href)
                        ? 'bg-primary text-primary-foreground'
                        : 'hover:bg-muted active:bg-muted'
                    )}
                  >
                    <item.icon className="h-4 w-4" />
                    {item.label}
                  </Link>
                ))}
              </nav>

              {/* Profile menu items for mobile access */}
              <nav className="flex flex-col gap-1 border-t pt-4">
                <div className="px-3 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Quick Access
                </div>
                {filteredProfileMenuItems.map((item) => (
                  <Link
                    key={item.href}
                    to={item.href}
                    onClick={() => setMobileOpen(false)}
                    className={cn(
                      'flex items-center gap-3 rounded-lg px-3 py-3 text-sm transition-colors min-h-[44px] touch-manipulation',
                      isActive(item.href)
                        ? 'bg-primary text-primary-foreground'
                        : 'hover:bg-muted active:bg-muted'
                    )}
                  >
                    <item.icon className="h-4 w-4" />
                    {item.label}
                  </Link>
                ))}
                <a
                  href="https://docs.maxalgos.in"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-3 rounded-lg px-3 py-3 text-sm transition-colors min-h-[44px] touch-manipulation hover:bg-muted active:bg-muted"
                  onClick={() => setMobileOpen(false)}
                >
                  <BookOpen className="h-4 w-4" />
                  Docs
                </a>
              </nav>
            </div>
          </SheetContent>
        </Sheet>

        <Link to="/dashboard" className="flex items-center gap-2 mr-6 md:hidden select-none">
          <div className="relative flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-tr from-brand to-brand/30 border border-brand/50">
            <div className="w-4 h-4 rounded-full bg-card border border-brand" />
          </div>
          <span className="font-extrabold text-foreground text-sm tracking-wider">MAX ALGOS</span>
        </Link>

        {/* Desktop sidebar collapse toggle (Ctrl/Cmd+B) */}
        <SidebarTrigger className="hidden md:flex" />

        {/* Right Side */}
        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          {/* Market Status — hidden below lg alongside the broker badge to
              keep the bar within narrow (portrait/small-laptop) widths */}
          <div className="hidden lg:flex items-center gap-1.5 text-xs font-medium text-muted-foreground mr-1">
            <span
              className={cn(
                'w-2 h-2 rounded-full',
                marketStatus === 'Open' ? 'bg-success' : 'bg-muted-foreground/30'
              )}
            />
            <span
              className={cn(
                'font-bold',
                marketStatus === 'Open' ? 'text-success' : 'text-muted-foreground'
              )}
            >
              {marketStatus}
            </span>
          </div>

          {/* Time */}
          <div className="hidden sm:flex items-center text-xs font-bold text-foreground tabular-nums select-none mr-1">
            {timeStr || '12:00:00 PM'}
          </div>

          {/* Broker Badge — hidden below lg to keep the bar within narrow
              (portrait/small-laptop) widths */}
          {user?.broker && (
            <Badge variant="outline" className="hidden lg:flex text-xs">
              {user.broker}
            </Badge>
          )}

          {/* Subscription Badge — non-admin accounts with an active
              platform subscription only; admins never see this since the
              subscription gate doesn't apply to them. */}
          {hasActiveSubscription && (
            <Badge variant="outline" className="hidden lg:flex text-xs gap-1">
              <CreditCard className="h-3 w-3" />
              Subscribed
            </Badge>
          )}

          {/* Mode Badge */}
          <Badge
            variant={appMode === 'live' ? 'default' : 'secondary'}
            className={cn(
              'text-xs',
              // Analyzer mode retints --primary purple, so default styling follows
              appMode === 'analyzer' && 'bg-primary text-primary-foreground'
            )}
          >
            <span className="hidden lg:inline">
              {appMode === 'live' ? 'Live Mode' : 'Analyze Mode'}
            </span>
            <span className="lg:hidden">{appMode === 'live' ? 'Live' : 'Analyze'}</span>
          </Badge>

          {/* Mode Toggle */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={handleModeToggle}
            disabled={isTogglingMode}
            title={`Switch to ${appMode === 'live' ? 'Analyze' : 'Live'} mode`}
            aria-label={`Switch to ${appMode === 'live' ? 'Analyze' : 'Live'} mode`}
          >
            {isTogglingMode ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            ) : appMode === 'live' ? (
              <Zap className="h-4 w-4" />
            ) : (
              <BarChart3 className="h-4 w-4" />
            )}
          </Button>

          {/* Kill Switch */}
          <KillSwitchButton />

          {/* Theme Toggle */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={toggleMode}
            title={mode === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
            aria-label={mode === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
          >
            {mode === 'light' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>

          {/* Notification Dropdown — closing it marks everything as read */}
          <DropdownMenu
            onOpenChange={(open) => {
              if (!open) markAllAsRead()
            }}
          >
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 relative"
                title="Notifications"
                aria-label="Notifications"
              >
                <Bell className="h-4 w-4" />
                {notifications.filter((n) => !n.read).length > 0 && (
                  <span className="absolute top-1.5 right-1.5 w-2.5 h-2.5 rounded-full bg-destructive border border-background animate-pulse" />
                )}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-80 max-h-[400px] overflow-y-auto p-2">
              <div className="flex items-center justify-between px-2 py-1 mb-1">
                <span className="text-xs font-bold text-foreground">Notifications</span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => markAllAsRead()}
                    className="text-[10px] text-muted-foreground hover:text-foreground font-semibold"
                  >
                    Mark all read
                  </button>
                  <button
                    type="button"
                    onClick={() => clearAll()}
                    className="text-[10px] text-destructive hover:text-destructive/80 font-semibold"
                  >
                    Clear all
                  </button>
                </div>
              </div>
              <DropdownMenuSeparator />
              {notifications.length === 0 ? (
                <div className="text-center py-6 text-xs text-muted-foreground">
                  No notifications
                </div>
              ) : (
                <div className="space-y-1.5 mt-1">
                  {notifications.map((notif) => (
                    <div
                      key={notif.id}
                      className={cn(
                        'p-2 rounded-md transition-colors text-xs space-y-0.5 border border-border/40',
                        notif.read ? 'bg-background' : 'bg-muted/50 border-l-2 border-l-primary'
                      )}
                    >
                      <div className="flex items-center justify-between font-bold text-foreground">
                        <span
                          className={cn(
                            notif.type === 'error' && 'text-destructive',
                            notif.type === 'success' && 'text-success',
                            notif.type === 'warning' && 'text-warning',
                            notif.type === 'info' && 'text-info'
                          )}
                        >
                          {notif.title}
                        </span>
                        <span className="text-[10px] text-muted-foreground font-normal">
                          {notif.timestamp}
                        </span>
                      </div>
                      <p className="text-[11px] text-muted-foreground leading-tight">
                        {notif.message}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Profile Dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 rounded-full bg-primary text-primary-foreground"
                aria-label="Open user menu"
              >
                <span className="text-sm font-medium">
                  {user?.username?.[0]?.toUpperCase() || 'O'}
                </span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              {filteredProfileMenuItems.map((item) => (
                <DropdownMenuItem
                  key={item.href}
                  onSelect={() => navigate(item.href)}
                  className="cursor-pointer"
                >
                  <item.icon className="h-4 w-4 mr-2" />
                  {item.label}
                </DropdownMenuItem>
              ))}
              <DropdownMenuItem asChild>
                <a
                  href="https://docs.maxalgos.in"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2"
                >
                  <BookOpen className="h-4 w-4" />
                  Docs
                </a>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => setShowLogoutDialog(true)}
                className="text-destructive focus:text-destructive"
              >
                <LogOut className="h-4 w-4 mr-2" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <LogoutConfirmDialog
        open={showLogoutDialog}
        onOpenChange={setShowLogoutDialog}
        onConfirm={handleLogout}
      />
    </nav>
  )
}
