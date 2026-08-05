import { HelpCircle, LogOut } from 'lucide-react'
import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { authApi } from '@/api/auth'
import { LogoutConfirmDialog } from '@/components/auth/LogoutConfirmDialog'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from '@/components/ui/sidebar'
import { externalLinks, isActiveRoute, navSections } from '@/config/navigation'
import { prefetchRoute } from '@/lib/route-prefetch'
import { useAuthStore } from '@/stores/authStore'
import { showToast } from '@/utils/toast'

/**
 * Desktop app sidebar built on the shadcn sidebar primitives.
 * Collapses to an icon rail (Ctrl/Cmd+B) and renders every section from the
 * single navigation registry in src/config/navigation.ts.
 */
export function AppSidebar() {
  const location = useLocation()
  const navigate = useNavigate()
  const { logout } = useAuthStore()
  const [showLogoutDialog, setShowLogoutDialog] = useState(false)

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

  return (
    <Sidebar collapsible="icon" className="hidden md:flex">
      <SidebarHeader className="border-b border-sidebar-border">
        <Link
          to="/dashboard"
          className="flex items-center gap-2.5 px-1.5 py-1 select-none group/brand"
        >
          <img
            src="/max-icon.png"
            alt="Max Algos"
            className="size-8 shrink-0 rounded-full object-cover ring-2 ring-brand/40 transition-shadow duration-300 group-hover/brand:ring-brand/70"
          />
          <div className="flex flex-col leading-none group-data-[collapsible=icon]:hidden">
            <span className="text-sidebar-foreground text-base font-extrabold tracking-wider">
              MAX
            </span>
            <span className="text-brand text-[9px] font-black tracking-[0.25em] mt-0.5">ALGOS</span>
          </div>
        </Link>
      </SidebarHeader>

      <SidebarContent className="scrollbar-thin">
        {navSections.map((section) => (
          <SidebarGroup key={section.label}>
            <SidebarGroupLabel>{section.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {section.items.map((item) => (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton
                      asChild
                      isActive={isActiveRoute(location.pathname, item.href)}
                      tooltip={item.label}
                    >
                      <Link
                        to={item.href}
                        onMouseEnter={() => prefetchRoute(item.href)}
                        onFocus={() => prefetchRoute(item.href)}
                      >
                        <item.icon />
                        <span>{item.label}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter className="border-t border-sidebar-border">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild tooltip="Documentation">
              <a href={externalLinks.docs.href} target="_blank" rel="noopener noreferrer">
                <HelpCircle />
                <span>Need help? Docs</span>
              </a>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              tooltip="Logout"
              onClick={() => setShowLogoutDialog(true)}
              className="hover:bg-destructive/10 hover:text-destructive"
            >
              <LogOut />
              <span>Logout</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <SidebarRail />

      <LogoutConfirmDialog
        open={showLogoutDialog}
        onOpenChange={setShowLogoutDialog}
        onConfirm={handleLogout}
      />
    </Sidebar>
  )
}
