// components/dashboard/RecentActivityTimeline.tsx
// Filtered timeline view of Recent Activity — drops the repeated "Logged
// in successfully" noise and renders as a time+event timeline instead of
// the old icon+title+message+time row list. Runs full-width, doing double
// duty as the "recent orders"/"notifications" surface since no distinct
// backend source exists for either of those.

import { Activity, FileText, TrendingUp, Zap } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { ActivityEntry } from '@/api/dashboard'
import { CardContent, CardHeader } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { cn } from '@/lib/utils'
import { PremiumCard } from './PremiumCard'

const ACTIVITY_ICONS: Record<string, { icon: typeof Activity; className: string }> = {
  system: { icon: Activity, className: 'bg-orange-500/10 border-orange-500/15 text-orange-400' },
  broker: { icon: Zap, className: 'bg-blue-500/10 border-blue-500/15 text-blue-400' },
  account: { icon: FileText, className: 'bg-purple-500/10 border-purple-500/15 text-purple-400' },
  order: { icon: TrendingUp, className: 'bg-profit/10 border-profit/15 text-profit' },
}

function formatActivityTime(ts: string | null): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true })
}

// Drop the specific repeated login-noise entry, not the whole "account"
// category -- other account-category messages (e.g. future settings
// changes) should still show.
function isLoginNoise(entry: ActivityEntry): boolean {
  return (
    entry.category === 'account' &&
    entry.title === 'Account' &&
    entry.message === 'Logged in successfully'
  )
}

interface RecentActivityTimelineProps {
  activity: ActivityEntry[]
  isLoading: boolean
}

export function RecentActivityTimeline({ activity, isLoading }: RecentActivityTimelineProps) {
  const rawCount = activity.length
  const filtered = activity.filter((e) => !isLoginNoise(e))

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-bold text-foreground tracking-wide">Recent Activity</h3>
        <Link
          to="/logs/live"
          className="text-xs font-bold text-brand hover:underline cursor-pointer select-none"
        >
          View all
        </Link>
      </div>

      <PremiumCard className="p-5 min-h-[220px]">
        <CardHeader className="sr-only">
          <span>Recent Activity</span>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <p className="text-xs text-muted-foreground font-medium">Loading activity…</p>
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={Activity}
              title={rawCount === 0 ? 'No recent activity yet' : 'No notable activity yet'}
              description={
                rawCount === 0
                  ? 'Activity will show up here once you start trading or connecting brokers.'
                  : 'Routine sign-ins are hidden — order fills, deployments, and alerts will appear here.'
              }
            />
          ) : (
            <div className="relative pl-5">
              <div className="absolute left-[7px] top-1 bottom-1 w-px bg-border" />
              <div className="space-y-5">
                {filtered.map((entry, idx) => {
                  const iconMeta = ACTIVITY_ICONS[entry.category] ?? ACTIVITY_ICONS.system
                  const Icon = iconMeta.icon
                  return (
                    <div
                      className="relative flex items-start gap-3"
                      key={`${entry.timestamp}-${idx}`}
                    >
                      <div
                        className={cn(
                          'absolute -left-5 top-0.5 h-3.5 w-3.5 rounded-full border-2 border-card',
                          iconMeta.className
                        )}
                      />
                      <span className="text-[10px] text-muted-foreground/80 font-semibold whitespace-nowrap w-12 shrink-0 pt-0.5">
                        {formatActivityTime(entry.timestamp)}
                      </span>
                      <div className="flex items-start gap-2 flex-1 min-w-0">
                        <div className={cn('p-1.5 rounded-lg border shrink-0', iconMeta.className)}>
                          <Icon className="h-3.5 w-3.5" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <h4 className="text-sm font-bold text-foreground leading-tight">
                            {entry.title}
                          </h4>
                          <p className="text-[11px] text-muted-foreground mt-0.5">
                            {entry.message}
                          </p>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </CardContent>
      </PremiumCard>
    </div>
  )
}
