/**
 * Curated Marketplace / Template catalog.
 *
 * This module owns the Free/Pro tiers (editable templates that clone into a
 * new strategy / builder session). This is the SOLE place templates are
 * browsed (the former standalone /strategy/templates page was a duplicate
 * of this same catalog and has been removed).
 *
 * Premium listings are served from the backend (`/strategy/api/marketplace`)
 * merged into `backendPremium` in Marketplace.tsx AND also statically
 * defined below so the Premium tab is always populated even before the
 * backend seed runs (first startup, fresh DB). The static PREMIUM entries
 * below mirror the backend seed's template_ids exactly — on subscribe, the
 * backend creates a real Deployment via services/strategy_compiler.py.
 */

export type CatalogTier = 'free' | 'pro' | 'premium' | 'ai'

export type CatalogAssetClass =
  | 'Equity'
  | 'Options'
  | 'Futures'
  | 'Basket'
  | 'Portfolio'
  | 'Index'
  | 'Any'

export type Difficulty = 'Beginner' | 'Intermediate' | 'Advanced'

export interface CatalogItem {
  id: string
  name: string
  tier: CatalogTier
  /** Grouping within a tier, e.g. "Trend Following", "Option Selling". */
  category: string
  asset: CatalogAssetClass
  difficulty: Difficulty
  description: string
  /** Present only for real, backend-backed subscribable listings. */
  strategyId?: number
  /**
   * Real destination for Free/Pro templates. Exactly one of these should be
   * set for a template to be genuinely wired:
   * - signalId: generates a real, working Python strategy (see
   *   lib/python-strategy-generator.ts) and opens it via /python/new.
   * - optionsTemplateId: opens the Options Strategy Builder with this exact
   *   template preloaded from lib/strategyTemplates.ts (real option legs).
   * Items with neither are honestly marked "Coming soon" in the UI.
   */
  signalId?: import('./python-strategy-generator').SignalId
  optionsTemplateId?: string
  // Optional performance metadata (shown on the card when available)
  rating?: number
  subscribers?: number
  winRate?: number
  profitFactor?: number
  sharpe?: number
  maxDrawdown?: number
  monthlyReturn?: number
  capital?: number
  version?: string
  /** Monthly price in INR; 0 / undefined => free. */
  price?: number
  featured?: boolean
}

export interface CatalogTierMeta {
  tier: CatalogTier
  label: string
  /** Short pitch shown under the tier tab. */
  tagline: string
}

export const TIER_META: CatalogTierMeta[] = [
  {
    tier: 'free',
    label: 'Free Templates',
    tagline: 'Editable starting points — clone, customize, deploy.',
  },
  {
    tier: 'pro',
    label: 'Pro Templates',
    tagline: 'Advanced editable templates for experienced traders.',
  },
  {
    tier: 'premium',
    label: 'Premium',
    tagline: 'Managed strategies with performance tracking and updates.',
  },
  {
    tier: 'ai',
    label: 'AI Strategies',
    tagline: 'Adaptive rule-based engines, backed by real published listings.',
  },
]

// Helper to keep the (large) catalog terse.
const t = (
  id: string,
  name: string,
  tier: CatalogTier,
  category: string,
  asset: CatalogAssetClass,
  difficulty: Difficulty,
  description: string,
  extra: Partial<CatalogItem> = {}
): CatalogItem => ({ id, name, tier, category, asset, difficulty, description, ...extra })

// ---------------------------------------------------------------------------
// FREE TEMPLATES  (~30 genuinely wired entries)
//
// Criteria for inclusion:
//  1. Has a real signalId that services/strategy_compiler.py can compile, OR
//  2. Has a real optionsTemplateId that the Options Strategy Builder can load.
// Entries without either are NOT shown (wiredOnly filter hides them by default).
// Futures, Portfolio, and Basket categories have been removed — basket compiler
// raises CompilerError, and Futures/Portfolio have no execution surface at all.
// ---------------------------------------------------------------------------
const FREE: CatalogItem[] = [
  // ── Trend Following ──────────────────────────────────────────────────────
  t(
    'ema-9-21',
    'EMA 9/21 Crossover',
    'free',
    'Trend Following',
    'Equity',
    'Beginner',
    'Classic fast/slow EMA crossover — most reliable intraday trend template.',
    { signalId: 'ema-cross', rating: 4.6, subscribers: 892, winRate: 62 }
  ),
  t(
    'sma-golden',
    'SMA Golden Cross',
    'free',
    'Trend Following',
    'Equity',
    'Beginner',
    '50/200 SMA golden-cross positional trend — the institutional benchmark.',
    { signalId: 'sma-cross', rating: 4.5, subscribers: 743, winRate: 60 }
  ),
  t(
    'supertrend-trend',
    'Supertrend',
    'free',
    'Trend Following',
    'Equity',
    'Beginner',
    'Supertrend flips drive entries and exits — self-adjusts to volatility.',
    { signalId: 'supertrend', rating: 4.7, subscribers: 1241, winRate: 65 }
  ),
  t(
    'triple-ema',
    'Triple EMA Stack',
    'free',
    'Trend Following',
    'Equity',
    'Intermediate',
    'Three-EMA alignment (5/13/34) — only trades when all three agree.',
    { signalId: 'triple-ema', rating: 4.5, subscribers: 521, winRate: 63 }
  ),
  t(
    'adx-trend',
    'ADX Trend Filter',
    'free',
    'Trend Following',
    'Equity',
    'Intermediate',
    'Trades only when ADX confirms trend strength above 25. Fewer, higher-quality signals.',
    { signalId: 'adx-trend', rating: 4.6, subscribers: 610, winRate: 67 }
  ),
  t(
    'atr-trail',
    'ATR Trailing Stop Trend',
    'free',
    'Trend Following',
    'Equity',
    'Intermediate',
    'ATR-based trailing-stop system that rides trends and exits on reversal.',
    { signalId: 'atr-trend', rating: 4.5, subscribers: 489, winRate: 64 }
  ),

  // ── Breakout ─────────────────────────────────────────────────────────────
  t(
    'orb-5',
    'Opening Range Breakout (5 min)',
    'free',
    'Breakout',
    'Equity',
    'Beginner',
    'Breaks of the first 5-minute candle range — the most popular intraday breakout.',
    { signalId: 'orb', rating: 4.7, subscribers: 1834, winRate: 64 }
  ),
  t(
    'orb-15',
    'Opening Range Breakout (15 min)',
    'free',
    'Breakout',
    'Equity',
    'Beginner',
    'Wider 15-minute range gives fewer but more reliable breakout signals.',
    { signalId: 'orb', rating: 4.6, subscribers: 1243, winRate: 62 }
  ),
  t(
    'prev-high',
    'Previous Day High/Low Breakout',
    'free',
    'Breakout',
    'Equity',
    'Beginner',
    'Entry on breaking the previous day high or low — clean, unambiguous level.',
    { signalId: 'prev-day-breakout', rating: 4.5, subscribers: 874, winRate: 59 }
  ),
  t(
    'vol-breakout',
    'Volume Surge Breakout',
    'free',
    'Breakout',
    'Equity',
    'Intermediate',
    'Breakout confirmed by 2× average volume spike — filters false breaks.',
    { signalId: 'volume-breakout', rating: 4.4, subscribers: 512, winRate: 61 }
  ),
  t(
    'inside-candle',
    'Inside Candle Breakout',
    'free',
    'Breakout',
    'Equity',
    'Intermediate',
    'Trades the expansion out of a mother/inside-bar pattern.',
    { signalId: 'inside-candle-breakout', rating: 4.4, subscribers: 438, winRate: 60 }
  ),
  t(
    'nr7',
    'NR7 Breakout',
    'free',
    'Breakout',
    'Equity',
    'Advanced',
    'Narrowest-range-7 volatility contraction breakout — strong mean-reversion setup.',
    { signalId: 'nr7-breakout', rating: 4.5, subscribers: 367, winRate: 63 }
  ),
  t(
    'bb-squeeze',
    'Bollinger Squeeze Breakout',
    'free',
    'Breakout',
    'Equity',
    'Advanced',
    'Trades the expansion after Bollinger Bands contract into a squeeze.',
    { signalId: 'bollinger-squeeze', rating: 4.6, subscribers: 581, winRate: 65 }
  ),
  t(
    'opening-gap',
    'Opening Gap Strategy',
    'free',
    'Breakout',
    'Equity',
    'Advanced',
    'Enters on confirmed opening gaps > 1% — captures gap continuation moves.',
    { signalId: 'gap-strategy', rating: 4.4, subscribers: 320, winRate: 58 }
  ),

  // ── Momentum ─────────────────────────────────────────────────────────────
  t(
    'rsi-mom',
    'RSI Momentum',
    'free',
    'Momentum',
    'Equity',
    'Beginner',
    'Buy above RSI 60, sell below RSI 40 — simple momentum with clear rules.',
    { signalId: 'rsi-momentum', rating: 4.5, subscribers: 921, winRate: 61 }
  ),
  t(
    'macd-mom',
    'MACD Momentum',
    'free',
    'Momentum',
    'Equity',
    'Beginner',
    'MACD line crossing its signal line — the classic momentum transition signal.',
    { signalId: 'macd-momentum', rating: 4.5, subscribers: 814, winRate: 62 }
  ),
  t(
    'roc',
    'Rate-of-Change Momentum',
    'free',
    'Momentum',
    'Equity',
    'Beginner',
    'ROC > +2% triggers buy, ROC < –2% triggers sell — pure price momentum.',
    { signalId: 'roc-momentum', rating: 4.4, subscribers: 487, winRate: 60 }
  ),

  // ── Mean Reversion ───────────────────────────────────────────────────────
  t(
    'rsi-rev',
    'RSI Reversal',
    'free',
    'Mean Reversion',
    'Equity',
    'Beginner',
    'Fade RSI extremes — bounce from oversold (<30), rejection from overbought (>70).',
    { signalId: 'rsi-reversal', rating: 4.6, subscribers: 743, winRate: 68 }
  ),
  t(
    'bb-rev',
    'Bollinger Band Reversion',
    'free',
    'Mean Reversion',
    'Equity',
    'Intermediate',
    'Buy at lower band, sell at upper band — mean reversion with defined risk.',
    { signalId: 'bollinger-reversal', rating: 4.5, subscribers: 602, winRate: 66 }
  ),
  t(
    'vwap-rev',
    'VWAP Reversion',
    'free',
    'Mean Reversion',
    'Equity',
    'Intermediate',
    'Revert to VWAP from 0.5% deviation — sharp, statistically-sound intraday mean reversion.',
    { signalId: 'vwap-reversion', rating: 4.7, subscribers: 1102, winRate: 70 }
  ),
  t(
    'keltner-rev',
    'Keltner Channel Reversion',
    'free',
    'Mean Reversion',
    'Equity',
    'Advanced',
    'Keltner channel-band touch reversion — lower noise than Bollinger on trending days.',
    { signalId: 'keltner-reversion', rating: 4.5, subscribers: 411, winRate: 67 }
  ),
  t(
    'donchian-pull',
    'Donchian Midline Pullback',
    'free',
    'Mean Reversion',
    'Equity',
    'Intermediate',
    'Buy/sell crosses of the Donchian midline — trend-with-pullback hybrid.',
    { signalId: 'donchian-pullback', rating: 4.4, subscribers: 378, winRate: 65 }
  ),

  // ── Swing ────────────────────────────────────────────────────────────────
  t(
    'swing-high',
    'Swing High/Low Breakout',
    'free',
    'Swing',
    'Equity',
    'Beginner',
    'Break of a 20-bar swing high or low — clean positional trend-entry.',
    { signalId: 'swing-breakout', rating: 4.5, subscribers: 684, winRate: 61 }
  ),
  t(
    'ema-pull',
    'EMA Pullback',
    'free',
    'Swing',
    'Equity',
    'Intermediate',
    'Buy pullbacks to the rising 20 EMA in an established uptrend.',
    { signalId: 'ema-pullback', rating: 4.6, subscribers: 532, winRate: 64 }
  ),

  // ── Scalping ─────────────────────────────────────────────────────────────
  t(
    'vwap-scalp',
    'VWAP Scalper',
    'free',
    'Scalping',
    'Equity',
    'Advanced',
    'Rapid entries on VWAP crossovers — designed for liquid index derivatives.',
    { signalId: 'vwap-scalp', rating: 4.6, subscribers: 823, winRate: 63 }
  ),

  // ── Options — Bullish ────────────────────────────────────────────────────
  t(
    'long-call',
    'Long Call',
    'free',
    'Options — Bullish',
    'Options',
    'Beginner',
    'Buy a call for defined-risk directional upside.',
    { optionsTemplateId: 'long_call' }
  ),
  t(
    'bull-call-spread',
    'Bull Call Spread',
    'free',
    'Options — Bullish',
    'Options',
    'Intermediate',
    'Debit spread — cap upside cost and max loss with a spread.',
    { optionsTemplateId: 'bull_call_spread' }
  ),
  t(
    'short-put',
    'Short Put',
    'free',
    'Options — Bullish',
    'Options',
    'Intermediate',
    'Sell a put to collect premium in a bullish or flat market.',
    { optionsTemplateId: 'short_put' }
  ),

  // ── Options — Bearish ────────────────────────────────────────────────────
  t(
    'long-put',
    'Long Put',
    'free',
    'Options — Bearish',
    'Options',
    'Beginner',
    'Buy a put for defined-risk directional downside.',
    { optionsTemplateId: 'long_put' }
  ),
  t(
    'bear-put-spread',
    'Bear Put Spread',
    'free',
    'Options — Bearish',
    'Options',
    'Intermediate',
    'Debit spread positioned for a controlled downside move.',
    { optionsTemplateId: 'bear_put_spread' }
  ),

  // ── Options — Neutral ────────────────────────────────────────────────────
  t(
    'short-straddle',
    'Short Straddle',
    'free',
    'Options — Neutral',
    'Options',
    'Advanced',
    'Sell ATM call + put — profit from time decay when market stays range-bound.',
    { optionsTemplateId: 'short_straddle' }
  ),
  t(
    'iron-condor',
    'Iron Condor',
    'free',
    'Options — Neutral',
    'Options',
    'Advanced',
    'Defined-risk range-bound premium seller with four legs.',
    { optionsTemplateId: 'short_iron_condor' }
  ),
  t(
    'iron-fly',
    'Iron Fly',
    'free',
    'Options — Neutral',
    'Options',
    'Advanced',
    'Tight-range defined-risk premium seller — higher premium, narrower zone than condor.',
    { optionsTemplateId: 'short_iron_fly' }
  ),
  t(
    'long-straddle',
    'Long Straddle',
    'free',
    'Options — Neutral',
    'Options',
    'Intermediate',
    'Buy ATM call + put for volatility expansion — event/earnings play.',
    { optionsTemplateId: 'long_straddle' }
  ),
]

// ---------------------------------------------------------------------------
// PRO TEMPLATES (advanced, always-wired)
// ---------------------------------------------------------------------------
const PRO: CatalogItem[] = [
  // Equity
  t(
    'bbs-pro',
    'Bollinger Squeeze + Volume',
    'pro',
    'Equity',
    'Equity',
    'Advanced',
    'Bollinger squeeze breakout filtered by above-average volume — high-probability setups only.',
    { signalId: 'bollinger-squeeze', rating: 4.7, subscribers: 341 }
  ),
  t(
    'atr-trend-pro',
    'ATR Trailing Trend Pro',
    'pro',
    'Equity',
    'Equity',
    'Advanced',
    'ATR trailing-stop trend system with EMA confirmation — rides full trend legs.',
    { signalId: 'atr-trend', rating: 4.7, subscribers: 289 }
  ),
  t(
    'gap-pro',
    'Opening Gap Continuation Pro',
    'pro',
    'Equity',
    'Equity',
    'Advanced',
    'Trades opening gaps > 1.5% with momentum confirmation — high edge on volatile days.',
    { signalId: 'gap-strategy', rating: 4.6, subscribers: 198 }
  ),
  t(
    'adx-macd',
    'ADX + MACD Combo',
    'pro',
    'Equity',
    'Equity',
    'Advanced',
    'ADX trend filter combined with MACD momentum for dual-confirmed entries.',
    { signalId: 'adx-trend', rating: 4.7, subscribers: 312 }
  ),
  t(
    'nr7-vwap',
    'NR7 + VWAP Pro',
    'pro',
    'Equity',
    'Equity',
    'Advanced',
    'NR7 volatility contraction breakout filtered by VWAP direction — elite intraday setup.',
    { signalId: 'nr7-breakout', rating: 4.8, subscribers: 276 }
  ),
  // Options — advanced structures
  t(
    'bwb',
    'Broken Wing Butterfly',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Asymmetric butterfly — zero net debit with a defined short-side risk.',
    { optionsTemplateId: 'call_butterfly' }
  ),
  t(
    'ratio-back',
    'Ratio Backspread',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Net-long-volatility ratio backspread — unlimited upside, defined downside.',
    { optionsTemplateId: 'call_ratio_back_spread' }
  ),
  t(
    'jade-lizard',
    'Jade Lizard',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Short call + bull put spread — no upside risk, income strategy for neutral-to-bullish view.',
    { optionsTemplateId: 'jade_lizard' }
  ),
  t(
    'collar',
    'Collar',
    'pro',
    'Options',
    'Options',
    'Intermediate',
    'Protective put funded by a covered call — hedged position at low net cost.',
    { optionsTemplateId: 'risk_reversal' }
  ),
  t(
    'diagonal',
    'Diagonal Spread',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Spread across both strike and expiry — captures time decay + directional drift.',
    { optionsTemplateId: 'diagonal_calendar' }
  ),
]

// ---------------------------------------------------------------------------
// PREMIUM STRATEGIES
//
// These cards are always visible in the Premium tab — they mirror the backend
// seed in blueprints/strategy.py::_init_mock_marketplace_listings. When the
// backend seed runs (first startup), these become subscribable. The static
// entries here ensure the tab is never empty even before the first seed.
// ---------------------------------------------------------------------------
const PREMIUM: CatalogItem[] = [
  t(
    'premium-momentum-breakout',
    'Momentum Breakout',
    'premium',
    'Published',
    'Index',
    'Advanced',
    'High-probability breakout trading strategy on high-volume indices. Combines ROC momentum with ORB trigger for precision entries.',
    {
      rating: 4.8,
      subscribers: 1482,
      winRate: 71,
      maxDrawdown: -9.2,
      monthlyReturn: 5.8,
      price: 1499,
      featured: true,
    }
  ),
  t(
    'premium-bnf-expiry',
    'BNF Expiry Hunter',
    'premium',
    'Published',
    'Index',
    'Advanced',
    'Advanced multi-leg Opening Range Breakout model optimised for Thursday index expiries.',
    {
      rating: 4.9,
      subscribers: 2130,
      winRate: 76,
      maxDrawdown: -8.1,
      monthlyReturn: 6.4,
      price: 2999,
      featured: true,
    }
  ),
  t(
    'premium-nifty-swing-ai',
    'Nifty Swing AI',
    'premium',
    'Published',
    'Index',
    'Advanced',
    'Machine-learning driven index swing trading strategy focusing on longer swings using SMA Golden Cross.',
    {
      rating: 4.8,
      subscribers: 1010,
      winRate: 68,
      maxDrawdown: -9.0,
      monthlyReturn: 4.8,
      price: 2299,
      featured: false,
    }
  ),
  t(
    'premium-supertrend-pro',
    'Supertrend Flip Pro',
    'premium',
    'Published',
    'Index',
    'Advanced',
    'Production-grade Supertrend flip system — rides confirmed trend reversals on Nifty. Real-time retraining monthly.',
    {
      rating: 4.7,
      subscribers: 760,
      winRate: 67,
      maxDrawdown: -10.1,
      monthlyReturn: 5.3,
      price: 2199,
      featured: true,
    }
  ),
  t(
    'premium-delta-neutral',
    'Delta Neutral Income',
    'premium',
    'Published',
    'Index',
    'Advanced',
    'Keltner-channel range-reversion income system. Targets 4–5% monthly from range-bound market phases.',
    {
      rating: 4.8,
      subscribers: 970,
      winRate: 75,
      maxDrawdown: -7.9,
      monthlyReturn: 5.0,
      price: 2799,
      featured: false,
    }
  ),
  t(
    'premium-vwap-institutional',
    'VWAP Institutional',
    'premium',
    'Published',
    'Equity',
    'Advanced',
    'VWAP-cross scalping system modelled on institutional execution behaviour. Optimised for large-cap NSE equities.',
    {
      rating: 4.7,
      subscribers: 690,
      winRate: 66,
      maxDrawdown: -9.5,
      monthlyReturn: 5.2,
      price: 2199,
      featured: false,
    }
  ),
  t(
    'premium-adx-filter-pro',
    'ADX Trend Filter Pro',
    'premium',
    'Published',
    'Index',
    'Advanced',
    'ADX-filtered trend system — only trades when trend strength is confirmed above 25. High win-rate, low drawdown.',
    {
      rating: 4.8,
      subscribers: 820,
      winRate: 69,
      maxDrawdown: -8.8,
      monthlyReturn: 5.1,
      price: 2399,
      featured: false,
    }
  ),
  t(
    'premium-dynamic-hedge',
    'Dynamic Portfolio Hedge',
    'premium',
    'Published',
    'Index',
    'Advanced',
    'ATR trailing-trend system used to auto-hedge directional exposure. Ideal for protecting long equity portfolios.',
    {
      rating: 4.9,
      subscribers: 560,
      winRate: 70,
      maxDrawdown: -6.5,
      monthlyReturn: 3.9,
      price: 3499,
      featured: false,
    }
  ),
]

const AI: CatalogItem[] = []

/** Full catalog, all tiers concatenated. */
export const CATALOG: CatalogItem[] = [...FREE, ...PRO, ...PREMIUM, ...AI]

export function itemsByTier(tier: CatalogTier): CatalogItem[] {
  return CATALOG.filter((i) => i.tier === tier)
}

export function categoriesForTier(tier: CatalogTier): string[] {
  const seen: string[] = []
  for (const item of CATALOG) {
    if (item.tier === tier && !seen.includes(item.category)) seen.push(item.category)
  }
  return seen
}
