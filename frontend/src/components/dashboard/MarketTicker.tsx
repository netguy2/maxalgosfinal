// components/dashboard/MarketTicker.tsx
// Continuously auto-scrolling live index ticker, replacing the old static
// NIFTY/BANKNIFTY index cards. Subscribes via the shared useMarketData
// hook (backed by the MarketDataManager singleton), so this adds
// subscriptions to the one shared WebSocket rather than opening a new
// connection, regardless of how many other components on the page also
// call useMarketData.

import { useEffect, useState } from 'react'
import { Marquee } from '@/components/ui/marquee'
import { useMarketData } from '@/hooks/useMarketData'
import { cn } from '@/lib/utils'

interface TickerSymbol {
  label: string
  symbol: string
  exchange: string
}

const TICKER_SYMBOLS: TickerSymbol[] = [
  { label: 'NIFTY 50', symbol: 'NIFTY', exchange: 'NSE_INDEX' },
  { label: 'BANK NIFTY', symbol: 'BANKNIFTY', exchange: 'NSE_INDEX' },
  { label: 'FIN NIFTY', symbol: 'FINNIFTY', exchange: 'NSE_INDEX' },
  { label: 'SENSEX', symbol: 'SENSEX', exchange: 'BSE_INDEX' },
  { label: 'RELIANCE', symbol: 'RELIANCE', exchange: 'NSE' },
  { label: 'TCS', symbol: 'TCS', exchange: 'NSE' },
  { label: 'HDFC BANK', symbol: 'HDFCBANK', exchange: 'NSE' },
  { label: 'INFOSYS', symbol: 'INFY', exchange: 'NSE' },
  { label: 'ICICI BANK', symbol: 'ICICIBANK', exchange: 'NSE' },
  { label: 'SBIN', symbol: 'SBIN', exchange: 'NSE' },
  { label: 'TATAMOTORS', symbol: 'TATAMOTORS', exchange: 'NSE' },
  { label: 'ITC', symbol: 'ITC', exchange: 'NSE' },
]

interface MarketTickerProps {
  isBrokerConnected: boolean
}

export function MarketTicker({ isBrokerConnected }: MarketTickerProps) {
  const { data: wsMarketData } = useMarketData({
    symbols: TICKER_SYMBOLS.map((t) => ({ symbol: t.symbol, exchange: t.exchange })),
    enabled: isBrokerConnected,
  })

  const [restQuotes, setRestQuotes] = useState<
    Record<string, { ltp: number; change: number; change_percent: number }>
  >({})

  useEffect(() => {
    if (!isBrokerConnected) return
    const fetchRestQuotes = async () => {
      try {
        const res = await fetch('/api/dashboard/ticker-quotes', { credentials: 'include' })
        const data = await res.json()
        if (data.status === 'success' && data.quotes) {
          setRestQuotes(data.quotes)
        }
      } catch {
        // Non-fatal fallback
      }
    }
    fetchRestQuotes()
  }, [isBrokerConnected])

  const chips = TICKER_SYMBOLS.map((t) => {
    const key = `${t.exchange}:${t.symbol}`
    const tick = wsMarketData.get(key)
    const restQuote = restQuotes[key]

    const ltp = tick?.data?.ltp ?? restQuote?.ltp
    const change = tick?.data?.change ?? restQuote?.change
    const changePct = tick?.data?.change_percent ?? restQuote?.change_percent

    const changeLabel =
      change !== undefined
        ? `${change >= 0 ? '▲' : '▼'} ${Math.abs(change).toFixed(2)} (${changePct?.toFixed(2)}%)`
        : ltp !== undefined
          ? '—'
          : isBrokerConnected
            ? 'Loading price...'
            : 'Connect data broker'

    return {
      key,
      content: (
        <div className="flex items-center gap-2.5 rounded-full border border-border bg-card px-4 py-2 shadow-sm whitespace-nowrap">
          <span className="text-xs font-bold text-foreground">{t.label}</span>
          <span className="text-xs font-extrabold tabular-nums text-foreground">
            {ltp !== undefined ? ltp.toLocaleString('en-IN', { minimumFractionDigits: 2 }) : '--'}
          </span>
          <span
            className={cn(
              'text-[11px] font-semibold',
              change === undefined
                ? 'text-muted-foreground'
                : change >= 0
                  ? 'text-profit'
                  : 'text-loss'
            )}
          >
            {changeLabel}
          </span>
        </div>
      ),
    }
  })

  return <Marquee items={chips} speed={45} />
}
