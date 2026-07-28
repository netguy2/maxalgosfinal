import { useEffect, useState } from 'react'
import { useAuthStore } from '@/stores/authStore'
import { cn } from '@/lib/utils'
import { MarketDataManager } from '@/lib/MarketDataManager'

interface FooterProps {
  className?: string
}

export function Footer({ className }: FooterProps) {
  const { user, brokerSessionValid } = useAuthStore()
  // user.broker records which broker was last connected; brokerSessionValid
  // tracks whether that session is still actually valid server-side (set by
  // Dashboard.tsx when a real API call surfaces BROKER_SESSION_EXPIRED).
  // Without the second check this showed "Connected" even after a broker's
  // token expired/was revoked, since user.broker doesn't clear on its own.
  const isBrokerConnected = !!user?.broker && brokerSessionValid

  const [dataFeedState, setDataFeedState] = useState({
    isConnected: false,
    isConnecting: false,
    isFallbackMode: false,
  })

  useEffect(() => {
    const manager = MarketDataManager.getInstance()
    const unsubscribe = manager.addStateListener((state) => {
      setDataFeedState({
        isConnected: state.isConnected,
        isConnecting:
          state.connectionState === 'connecting' || state.connectionState === 'authenticating',
        isFallbackMode: state.isFallbackMode,
      })
    })
    return unsubscribe
  }, [])

  return (
    <footer
      className={cn(
        'border-t border-border bg-card px-6 py-3 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs font-medium text-muted-foreground sticky bottom-0 z-40',
        className
      )}
    >
      {/* Left side Status indicators — Market Status and Time now live in
          the top Navbar so they're visible without scrolling to the
          footer. */}
      <div className="flex flex-wrap items-center gap-6">
        {/* Broker Status */}
        <div className="flex items-center gap-2">
          <span>Broker Status</span>
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                'w-2 h-2 rounded-full',
                isBrokerConnected ? 'bg-profit animate-pulse' : 'bg-loss'
              )}
            />
            <span className={cn('font-bold', isBrokerConnected ? 'text-profit' : 'text-loss')}>
              {isBrokerConnected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
        </div>

        <span className="hidden sm:inline text-border">|</span>

        {/* Data Feed */}
        <div className="flex items-center gap-2">
          <span>Data Feed</span>
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                'w-2 h-2 rounded-full',
                dataFeedState.isConnected && !dataFeedState.isFallbackMode
                  ? 'bg-profit animate-pulse'
                  : dataFeedState.isConnecting || dataFeedState.isFallbackMode
                    ? 'bg-warning animate-pulse'
                    : 'bg-loss'
              )}
            />
            <span
              className={cn(
                'font-bold',
                dataFeedState.isConnected && !dataFeedState.isFallbackMode
                  ? 'text-profit'
                  : dataFeedState.isConnecting || dataFeedState.isFallbackMode
                    ? 'text-warning'
                    : 'text-loss'
              )}
            >
              {dataFeedState.isConnected && !dataFeedState.isFallbackMode
                ? 'Live'
                : dataFeedState.isConnecting
                  ? 'Connecting'
                  : dataFeedState.isFallbackMode
                    ? 'Polling'
                    : 'Disconnected'}
            </span>
          </div>
        </div>
      </div>

      {/* Right side Copyright */}
      <div className="text-[10px] text-muted-foreground">
        &copy; {new Date().getFullYear()} MaxAlgos. All rights reserved.
      </div>
    </footer>
  )
}
