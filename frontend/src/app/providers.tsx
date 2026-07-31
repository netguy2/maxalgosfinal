import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import type { ReactNode } from 'react'
import { Toaster } from '@/components/ui/sonner'
import { MarketDataProvider } from '@/contexts/MarketDataContext'
import { useAlertStore } from '@/stores/alertStore'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60, // 1 minute
      gcTime: 1000 * 60 * 10, // keep cached data 10 min so back-navigation is instant
      // Trading pages refresh via SocketIO events; refetching every query on
      // every window focus just burns requests and adds jank.
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})

interface ProvidersProps {
  children: ReactNode
}

export function Providers({ children }: ProvidersProps) {
  const { position, maxVisibleToasts, duration } = useAlertStore()

  return (
    <QueryClientProvider client={queryClient}>
      <MarketDataProvider>{children}</MarketDataProvider>
      <Toaster
        position={position}
        richColors
        visibleToasts={maxVisibleToasts}
        duration={duration}
        closeButton
      />
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  )
}
