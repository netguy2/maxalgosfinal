// components/dashboard/BrokerConnectCta.tsx
// Extracted from Dashboard.tsx: the "no broker connected" banner and the
// error/session-expired retry alert. Logic unchanged from the original
// inline JSX -- only moved into its own component.

import { AlertTriangle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

interface BrokerConnectCtaProps {
  isBrokerConnected: boolean
  error: string | null
  isBrokerSessionExpired: boolean
  brokerName: string | null
  onRetry: () => void
}

export function BrokerConnectCta({
  isBrokerConnected,
  error,
  isBrokerSessionExpired,
  brokerName,
  onRetry,
}: BrokerConnectCtaProps) {
  const navigate = useNavigate()

  return (
    <>
      {!isBrokerConnected && (
        <div className="p-6 rounded-2xl border border-dashed border-brand/40 bg-brand/5 flex flex-col sm:flex-row items-center justify-between gap-4 text-center sm:text-left">
          <div>
            <h3 className="text-lg font-bold text-foreground">No Trading Account Connected</h3>
            <p className="text-sm text-muted-foreground mt-1">
              You are currently browsing the dashboard, but you need to connect your broker
              credentials to start trading.
            </p>
          </div>
          <button
            type="button"
            onClick={() => navigate('/broker')}
            className="px-6 py-2.5 rounded-lg bg-brand hover:bg-brand/90 text-black font-bold text-sm shadow-md shadow-brand/10 transition-colors shrink-0"
          >
            Connect Broker
          </button>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-loss/10 border border-loss/20 flex flex-col sm:flex-row items-center gap-4 justify-between">
          <div className="flex items-center gap-3">
            <AlertTriangle className="h-5 w-5 text-loss shrink-0" />
            <p className="text-sm text-loss font-semibold">{error}</p>
          </div>
          <button
            type="button"
            onClick={
              isBrokerSessionExpired
                ? () => navigate(brokerName ? `/broker?broker=${brokerName}` : '/broker/manage')
                : onRetry
            }
            className="px-4 py-1.5 rounded-lg bg-card hover:bg-muted text-foreground text-xs font-bold border border-border transition-colors shrink-0"
          >
            {isBrokerSessionExpired ? 'Reconnect Broker' : 'Retry'}
          </button>
        </div>
      )}
    </>
  )
}
