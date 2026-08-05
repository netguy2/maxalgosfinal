// components/charts/AiInsightCard.tsx
// Read-only advisory panel docked in the Charts page's right sidebar.
// Fetches a structured sentiment/summary from the user's own configured AI
// provider (blueprints/ai_insight.py) on button click — never wired to
// order placement. Has a settings gear to pick which of the chart's
// enabled indicators feed the analysis, and can be collapsed to save
// vertical space (state persisted, same as before).

import {
  AlertTriangle,
  Bot,
  ChevronDown,
  Loader2,
  RefreshCw,
  Settings2,
  Sparkles,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { type AiInsight, aiInsightApi } from '@/api/ai-insight'
import { aiSettingsApi } from '@/api/ai-settings'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

export interface AiInsightIndicatorOption {
  key: string
  label: string
}

interface AiInsightCardProps {
  symbol: string
  exchange: string
  interval: string
  /** Current live tick price, sent to the backend so it isn't reasoning
   * off a stale closed candle. */
  livePrice?: number
  /** Indicator chips the user can currently toggle on the chart (same
   * keys as Charts.tsx's AVAILABLE_INDICATORS) — offered in the gear
   * menu so the AI's inputs can be scoped to what's actually enabled. */
  availableIndicators: AiInsightIndicatorOption[]
  /** Which of availableIndicators are currently drawn on the chart —
   * seeds the popup's own selection the first time it's opened. */
  chartEnabledIndicatorKeys: Set<string>
  /** Available trading capital, used ONLY client-side to turn the AI's
   * trade_levels.position_size_pct into a rupee amount / share quantity —
   * this value is never sent to the AI provider (see
   * services/ai_insight_service.py's module docstring: the backend only
   * ever computes and sends a percentage, real balance stays local). */
  availableBalance?: number
}

const SENTIMENT_STYLES: Record<AiInsight['sentiment'], string> = {
  bullish: 'border-profit/40 bg-profit/10 text-profit',
  bearish: 'border-loss/40 bg-loss/10 text-loss',
  neutral: 'border-border bg-muted text-muted-foreground',
}

const STORAGE_KEY_INDICATORS = 'maxalgos.charts.aiInsight.indicators'
const STORAGE_KEY_COLLAPSED = 'maxalgos.charts.aiInsight.collapsed'

function loadStoredIndicators(defaultKeys: string[]): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_INDICATORS)
    if (!raw) return new Set(defaultKeys)
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed) && parsed.length > 0) return new Set(parsed)
  } catch {
    // ignore malformed/unavailable storage
  }
  return new Set(defaultKeys)
}

export function AiInsightCard({
  symbol,
  exchange,
  interval,
  livePrice,
  availableIndicators,
  chartEnabledIndicatorKeys,
  availableBalance,
}: AiInsightCardProps) {
  const [hasApiKey, setHasApiKey] = useState<boolean | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [insight, setInsight] = useState<AiInsight | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(STORAGE_KEY_COLLAPSED) === 'true'
  )

  // Which indicators feed the analysis. Seeded once from whatever's
  // enabled on the chart right now (or a prior saved choice) — a ref
  // guards the seed so switching indicators on the chart afterward
  // doesn't silently change what the popup is configured to send.
  const seededRef = useRef(false)
  const [selectedIndicators, setSelectedIndicators] = useState<Set<string>>(() => new Set())
  useEffect(() => {
    if (seededRef.current || availableIndicators.length === 0) return
    seededRef.current = true
    const fallback =
      chartEnabledIndicatorKeys.size > 0
        ? Array.from(chartEnabledIndicatorKeys)
        : availableIndicators.map((i) => i.key)
    setSelectedIndicators(loadStoredIndicators(fallback))
  }, [availableIndicators, chartEnabledIndicatorKeys])

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_INDICATORS, JSON.stringify(Array.from(selectedIndicators)))
  }, [selectedIndicators])

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_COLLAPSED, String(collapsed))
  }, [collapsed])

  const toggleIndicator = (key: string) => {
    setSelectedIndicators((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  useEffect(() => {
    aiSettingsApi.get().then((settings) => setHasApiKey(settings?.hasApiKey ?? false))
  }, [])

  // Clear a stale insight when the symbol changes so the popup never
  // shows a previous symbol's analysis under a new one — it stays
  // mounted across symbol switches, so this must react to the identity
  // actually changing, not just run once on mount.
  // biome-ignore lint/correctness/useExhaustiveDependencies: symbol/exchange are the deliberate trigger for this reset, not values read inside it
  useEffect(() => {
    setInsight(null)
    setError(null)
  }, [symbol, exchange])

  const handleAnalyze = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const result = await aiInsightApi.analyze(
        symbol,
        exchange,
        interval,
        Array.from(selectedIndicators),
        livePrice
      )
      if (result.success && result.data) {
        setInsight(result.data)
      } else {
        setError(result.message || 'Failed to get AI insight')
      }
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Card className="border-border/80">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-sm">
          <span className="flex items-center gap-1.5">
            <Bot className="h-4 w-4" />
            AI Insight
          </span>
          <span className="flex items-center gap-0.5">
            {insight && !collapsed && (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={handleAnalyze}
                disabled={isLoading}
                aria-label="Refresh AI insight"
              >
                <RefreshCw className={cn('h-3.5 w-3.5', isLoading && 'animate-spin')} />
              </Button>
            )}
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  aria-label="Configure AI insight"
                >
                  <Settings2 className="h-3.5 w-3.5" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-64" align="end">
                <p className="text-xs font-semibold mb-2">Indicators to analyze</p>
                <div className="space-y-1.5 max-h-48 overflow-y-auto">
                  {availableIndicators.map((ind) => (
                    <label key={ind.key} className="flex items-center gap-2 text-xs cursor-pointer">
                      <Checkbox
                        checked={selectedIndicators.has(ind.key)}
                        onCheckedChange={() => toggleIndicator(ind.key)}
                      />
                      {ind.label}
                    </label>
                  ))}
                </div>
                <p className="text-[10px] text-muted-foreground mt-2">
                  Only the checked indicators' current values are sent to the AI.
                </p>
              </PopoverContent>
            </Popover>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => setCollapsed((c) => !c)}
              aria-label={collapsed ? 'Expand' : 'Collapse'}
            >
              <ChevronDown
                className={cn('h-3.5 w-3.5 transition-transform', collapsed && '-rotate-90')}
              />
            </Button>
          </span>
        </CardTitle>
      </CardHeader>
      {!collapsed && (
        <CardContent className="space-y-3">
          {hasApiKey === false && (
            <p className="text-xs text-muted-foreground">
              <Link to="/ai-settings" className="text-primary underline">
                Configure your AI provider
              </Link>{' '}
              to enable this.
            </p>
          )}

          {!insight && (
            <Button
              size="sm"
              className="w-full"
              onClick={handleAnalyze}
              disabled={isLoading || hasApiKey === false || hasApiKey === null}
            >
              {isLoading ? (
                <Loader2 className="h-3.5 w-3.5 mr-2 animate-spin" />
              ) : (
                <Sparkles className="h-3.5 w-3.5 mr-2" />
              )}
              Get AI Insight
            </Button>
          )}

          {isLoading && !insight && (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          )}

          {error && (
            <div className="flex items-start gap-1.5 rounded-md border border-loss/40 bg-loss/10 px-2 py-1.5 text-xs text-loss">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              {error}
            </div>
          )}

          {insight && (
            <div className="space-y-2.5">
              <div className="flex items-center gap-2">
                <Badge
                  variant="outline"
                  className={cn('capitalize text-[11px]', SENTIMENT_STYLES[insight.sentiment])}
                >
                  {insight.sentiment}
                </Badge>
                <span className="text-[11px] text-muted-foreground">
                  {insight.confidence}% confidence
                </span>
              </div>
              <p className="text-xs leading-relaxed">{insight.summary}</p>
              {insight.key_drivers.length > 0 && (
                <ul className="space-y-1 text-[11px] text-muted-foreground">
                  {insight.key_drivers.map((driver) => (
                    <li key={driver} className="flex items-start gap-1.5">
                      <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" />
                      {driver}
                    </li>
                  ))}
                </ul>
              )}
              {insight.watch_level !== null && (
                <p className="text-[11px] text-muted-foreground">
                  Watch level:{' '}
                  <span className="font-medium text-foreground">{insight.watch_level}</span>
                </p>
              )}
              {insight.trade_levels && (
                <div className="rounded-md border border-border bg-muted/40 p-2 space-y-1.5">
                  <div className="grid grid-cols-2 gap-1.5 text-[11px]">
                    <div>
                      <span className="text-muted-foreground">Stop Loss</span>
                      <p className="font-bold text-loss">
                        {insight.trade_levels.stop_loss.toLocaleString('en-IN')}
                      </p>
                    </div>
                    <div>
                      <span className="text-muted-foreground">Target</span>
                      <p className="font-bold text-profit">
                        {insight.trade_levels.target.toLocaleString('en-IN')}
                      </p>
                    </div>
                  </div>
                  <div className="text-[11px]">
                    <span className="text-muted-foreground">Suggested size</span>
                    <p className="font-bold text-foreground">
                      {insight.trade_levels.position_size_pct}% of capital
                      {availableBalance !== undefined && livePrice ? (
                        <span className="font-normal text-muted-foreground">
                          {' '}
                          (~
                          {Math.floor(
                            ((availableBalance * insight.trade_levels.position_size_pct) /
                              100 /
                              livePrice) *
                              10
                          ) / 10}{' '}
                          qty)
                        </span>
                      ) : null}
                    </p>
                  </div>
                  <p className="text-[10px] text-muted-foreground italic">
                    {insight.trade_levels.rationale}
                  </p>
                </div>
              )}
              <p className="text-[10px] text-muted-foreground/70 italic pt-1 border-t border-border">
                AI-generated, not financial advice. Levels and sizing are algorithmic suggestions
                from price/volatility data and broader market-risk readings (India VIX, GIFT NIFTY)
                where available — no news, fundamentals, or human review. Always verify and use your
                own risk judgment before trading.
              </p>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  )
}
