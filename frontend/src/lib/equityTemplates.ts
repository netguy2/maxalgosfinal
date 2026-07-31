/**
 * Trade templates used by the Strategy Builder's Equity mode. Unlike options
 * templates (`strategyTemplates.ts`), these have no strikes/expiry to resolve
 * against a live chain — picking one simply pre-fills the equity order form's
 * Order Type and suggested Target/SL percentages.
 */

import {
  Activity,
  ArrowUpRight,
  Gauge,
  LineChart,
  type LucideIcon,
  Repeat,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react'

export type EquityTemplateSide = 'BUY' | 'SELL'

export interface EquityTemplate {
  id: string
  name: string
  side: EquityTemplateSide
  description: string
  defaultOrderType: 'MARKET' | 'LIMIT'
  /** Suggested stop-loss, as a percent below (BUY) / above (SELL) entry. */
  suggestedSlPct?: number
  /** Suggested target, as a percent above (BUY) / below (SELL) entry. */
  suggestedTargetPct?: number
  icon: LucideIcon
}

export const EQUITY_TEMPLATES: EquityTemplate[] = [
  {
    id: 'momentum_buy',
    name: 'Momentum Buy',
    side: 'BUY',
    description: 'Ride an already-strong up-move with a tight trailing stop.',
    defaultOrderType: 'MARKET',
    suggestedSlPct: 1,
    suggestedTargetPct: 3,
    icon: TrendingUp,
  },
  {
    id: 'breakout_entry',
    name: 'Breakout Entry',
    side: 'BUY',
    description: 'Enter on a confirmed break above resistance.',
    defaultOrderType: 'LIMIT',
    suggestedSlPct: 1.5,
    suggestedTargetPct: 4,
    icon: ArrowUpRight,
  },
  {
    id: 'pullback_buy',
    name: 'Pullback Buy',
    side: 'BUY',
    description: 'Buy a shallow retracement within an existing uptrend.',
    defaultOrderType: 'LIMIT',
    suggestedSlPct: 1.5,
    suggestedTargetPct: 3.5,
    icon: Repeat,
  },
  {
    id: 'swing_long',
    name: 'Swing Long',
    side: 'BUY',
    description: 'Multi-day positional long with a wider stop.',
    defaultOrderType: 'LIMIT',
    suggestedSlPct: 3,
    suggestedTargetPct: 8,
    icon: LineChart,
  },
  {
    id: 'intraday_scalping',
    name: 'Intraday Scalping',
    side: 'BUY',
    description: 'Quick in-and-out on small, fast moves.',
    defaultOrderType: 'MARKET',
    suggestedSlPct: 0.4,
    suggestedTargetPct: 0.8,
    icon: Zap,
  },
  {
    id: 'vwap_reversal',
    name: 'VWAP Reversal',
    side: 'BUY',
    description: 'Enter on a reversion back toward VWAP.',
    defaultOrderType: 'LIMIT',
    suggestedSlPct: 1,
    suggestedTargetPct: 2,
    icon: Activity,
  },
  {
    id: 'moving_average_cross',
    name: 'Moving Average Cross',
    side: 'BUY',
    description: 'Enter on a fast/slow moving-average crossover.',
    defaultOrderType: 'MARKET',
    suggestedSlPct: 2,
    suggestedTargetPct: 5,
    icon: Gauge,
  },
  {
    id: 'rsi_reversal',
    name: 'RSI Reversal',
    side: 'BUY',
    description: 'Enter when RSI reverses out of oversold territory.',
    defaultOrderType: 'LIMIT',
    suggestedSlPct: 1.5,
    suggestedTargetPct: 3,
    icon: Repeat,
  },
  {
    id: 'support_bounce',
    name: 'Support Bounce',
    side: 'BUY',
    description: 'Buy a bounce off a well-tested support level.',
    defaultOrderType: 'LIMIT',
    suggestedSlPct: 1.5,
    suggestedTargetPct: 3,
    icon: ArrowUpRight,
  },
  {
    id: 'resistance_breakout',
    name: 'Resistance Breakout',
    side: 'BUY',
    description: 'Buy a confirmed breakout above a resistance level.',
    defaultOrderType: 'LIMIT',
    suggestedSlPct: 1.5,
    suggestedTargetPct: 4,
    icon: ArrowUpRight,
  },
  {
    id: 'gap_up_strategy',
    name: 'Gap Up Strategy',
    side: 'BUY',
    description: 'Trade continuation after a bullish opening gap.',
    defaultOrderType: 'MARKET',
    suggestedSlPct: 1.5,
    suggestedTargetPct: 3,
    icon: TrendingUp,
  },
  {
    id: 'gap_down_short',
    name: 'Gap Down Short',
    side: 'SELL',
    description: 'Trade continuation after a bearish opening gap.',
    defaultOrderType: 'MARKET',
    suggestedSlPct: 1.5,
    suggestedTargetPct: 3,
    icon: TrendingDown,
  },
]
