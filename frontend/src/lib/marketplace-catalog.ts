/**
 * Curated Marketplace / Template catalog.
 *
 * This module owns the Free/Pro tiers (editable templates that clone into a
 * new strategy / builder session). This is the SOLE place templates are
 * browsed (the former standalone /strategy/templates page was a duplicate
 * of this same catalog and has been removed).
 *
 * Premium and AI are NOT curated here -- both tiers are served entirely by
 * the backend `/strategy/api/marketplace` endpoint (real, subscribable
 * listings seeded in blueprints/strategy.py::_init_mock_marketplace_listings,
 * merged into `backendPremium` in Marketplace.tsx). Every one of those
 * listings carries a real `template_id` that compiles into a genuine,
 * working Deployment on subscribe, so unlike a static preview card,
 * subscribing actually produces a strategy that trades.
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
   * Items with neither are honestly marked "Coming soon" in the UI — there is
   * no strategy surface yet that can carry Futures/Portfolio/basket-arbitrage
   * logic, so we do not pretend cloning them produces a working strategy.
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
// FREE TEMPLATES
// ---------------------------------------------------------------------------
const FREE: CatalogItem[] = [
  // Trend Following
  t(
    'ema-9-21',
    'EMA 9/21 Crossover',
    'free',
    'Trend Following',
    'Equity',
    'Beginner',
    'Classic fast/slow EMA crossover entries and exits.',
    { signalId: 'ema-cross' }
  ),
  t(
    'ema-20-50',
    'EMA 20/50 Trend',
    'free',
    'Trend Following',
    'Equity',
    'Beginner',
    'Medium-term trend following on the 20/50 EMA pair.',
    { signalId: 'ema-cross' }
  ),
  t(
    'ema-vwap',
    'EMA + VWAP',
    'free',
    'Trend Following',
    'Equity',
    'Intermediate',
    'EMA trend confirmed by VWAP for intraday bias.',
    { signalId: 'vwap-reversion' }
  ),
  t(
    'sma-golden',
    'SMA Golden Cross',
    'free',
    'Trend Following',
    'Equity',
    'Beginner',
    '50/200 SMA golden-cross positional trend template.',
    { signalId: 'sma-cross' }
  ),
  t(
    'triple-ema',
    'Triple EMA Trend',
    'free',
    'Trend Following',
    'Equity',
    'Intermediate',
    'Three-EMA stack for stronger trend confirmation.',
    { signalId: 'triple-ema' }
  ),
  t(
    'supertrend-trend',
    'Supertrend Trend',
    'free',
    'Trend Following',
    'Equity',
    'Beginner',
    'Supertrend flips drive entries and exits.',
    { signalId: 'supertrend' }
  ),
  t(
    'adx-trend',
    'ADX Trend Filter',
    'free',
    'Trend Following',
    'Equity',
    'Intermediate',
    'Trades only when ADX confirms trend strength.',
    { signalId: 'adx-trend' }
  ),
  // Breakout
  t(
    'orb-5',
    'Opening Range Breakout (ORB 5)',
    'free',
    'Breakout',
    'Equity',
    'Beginner',
    'Breaks of the first 5-minute range.',
    { signalId: 'orb' }
  ),
  t(
    'orb-15',
    'ORB 15',
    'free',
    'Breakout',
    'Equity',
    'Beginner',
    'Breaks of the first 15-minute range.',
    { signalId: 'orb' }
  ),
  t(
    'cpr-breakout',
    'CPR Breakout',
    'free',
    'Breakout',
    'Equity',
    'Intermediate',
    'Central Pivot Range breakout template.',
    { signalId: 'prev-day-breakout' }
  ),
  t(
    'prev-high',
    'Previous High Breakout',
    'free',
    'Breakout',
    'Equity',
    'Beginner',
    'Entry on breaking the previous day high.',
    { signalId: 'prev-day-breakout' }
  ),
  t(
    'prev-low',
    'Previous Low Breakdown',
    'free',
    'Breakout',
    'Equity',
    'Beginner',
    'Short entry on breaking the previous day low.',
    { signalId: 'prev-day-breakout' }
  ),
  t(
    'vol-breakout',
    'Volume Breakout',
    'free',
    'Breakout',
    'Equity',
    'Intermediate',
    'Breakouts confirmed by a volume surge.',
    { signalId: 'volume-breakout' }
  ),
  t(
    'inside-candle',
    'Inside Candle Breakout',
    'free',
    'Breakout',
    'Equity',
    'Intermediate',
    'Trades the break of an inside-bar range.',
    { signalId: 'inside-candle-breakout' }
  ),
  t(
    'nr7',
    'NR7 Breakout',
    'free',
    'Breakout',
    'Equity',
    'Advanced',
    'Narrow-range-7 volatility contraction breakout.',
    { signalId: 'nr7-breakout' }
  ),
  // Momentum
  t(
    'rsi-mom',
    'RSI Momentum',
    'free',
    'Momentum',
    'Equity',
    'Beginner',
    'Momentum entries from RSI thresholds.',
    { signalId: 'rsi-momentum' }
  ),
  t(
    'macd-mom',
    'MACD Momentum',
    'free',
    'Momentum',
    'Equity',
    'Beginner',
    'MACD signal-line crossover momentum.',
    { signalId: 'macd-momentum' }
  ),
  t(
    'mom-vol',
    'Momentum + Volume',
    'free',
    'Momentum',
    'Equity',
    'Intermediate',
    'Momentum entries filtered by volume.',
    { signalId: 'volume-breakout' }
  ),
  t(
    'roc',
    'ROC Strategy',
    'free',
    'Momentum',
    'Equity',
    'Beginner',
    'Rate-of-change driven momentum template.',
    { signalId: 'roc-momentum' }
  ),
  t(
    'pa-mom',
    'Price Action Momentum',
    'free',
    'Momentum',
    'Equity',
    'Intermediate',
    'Momentum from raw price-action structure.',
    { signalId: 'swing-breakout' }
  ),
  // Mean Reversion
  t(
    'rsi-rev',
    'RSI Reversal',
    'free',
    'Mean Reversion',
    'Equity',
    'Beginner',
    'Fade oversold/overbought RSI extremes.',
    { signalId: 'rsi-reversal' }
  ),
  t(
    'bb-rev',
    'Bollinger Band Reversal',
    'free',
    'Mean Reversion',
    'Equity',
    'Intermediate',
    'Reversion from Bollinger band touches.',
    { signalId: 'bollinger-reversal' }
  ),
  t(
    'vwap-rev',
    'VWAP Reversion',
    'free',
    'Mean Reversion',
    'Equity',
    'Intermediate',
    'Reversion back to the VWAP mean.',
    { signalId: 'vwap-reversion' }
  ),
  t(
    'keltner-rev',
    'Keltner Channel Reversion',
    'free',
    'Mean Reversion',
    'Equity',
    'Advanced',
    'Reversion off Keltner channel bounds.',
    { signalId: 'keltner-reversion' }
  ),
  t(
    'donchian-pull',
    'Donchian Pullback',
    'free',
    'Mean Reversion',
    'Equity',
    'Intermediate',
    'Pullback entries within Donchian channels.',
    { signalId: 'donchian-pullback' }
  ),
  // Swing
  t(
    'swing-high',
    'Swing High Breakout',
    'free',
    'Swing',
    'Equity',
    'Beginner',
    'Positional break of a prior swing high.',
    { signalId: 'swing-breakout' }
  ),
  t(
    'swing-low',
    'Swing Low Breakdown',
    'free',
    'Swing',
    'Equity',
    'Beginner',
    'Positional break of a prior swing low.',
    { signalId: 'swing-breakout' }
  ),
  t(
    'ema-pull',
    'EMA Pullback',
    'free',
    'Swing',
    'Equity',
    'Intermediate',
    'Buy pullbacks to a rising EMA.',
    { signalId: 'ema-pullback' }
  ),
  t(
    'trendline-bounce',
    'Trendline Bounce',
    'free',
    'Swing',
    'Equity',
    'Advanced',
    'Entries off trendline retests.',
    { signalId: 'donchian-pullback' }
  ),
  t(
    'sr-bounce',
    'Support Resistance Bounce',
    'free',
    'Swing',
    'Equity',
    'Intermediate',
    'Bounce trades at S/R levels.',
    { signalId: 'donchian-pullback' }
  ),
  // Scalping
  t(
    'vwap-scalp',
    'VWAP Scalper',
    'free',
    'Scalping',
    'Equity',
    'Advanced',
    'Fast scalps around VWAP.',
    { signalId: 'vwap-scalp' }
  ),
  t(
    'ema-scalp',
    'EMA Scalper',
    'free',
    'Scalping',
    'Equity',
    'Advanced',
    'EMA micro-trend scalping.',
    { signalId: 'ema-cross' }
  ),
  t(
    'mom-scalp',
    'Momentum Scalper',
    'free',
    'Scalping',
    'Equity',
    'Advanced',
    'Scalps momentum bursts.',
    { signalId: 'roc-momentum' }
  ),
  t(
    'range-scalp',
    'Range Scalper',
    'free',
    'Scalping',
    'Equity',
    'Advanced',
    'Scalps inside a defined range.',
    { signalId: 'bollinger-reversal' }
  ),
  t(
    'st-scalp',
    'Supertrend Scalper',
    'free',
    'Scalping',
    'Equity',
    'Advanced',
    'Scalps Supertrend flips.',
    { signalId: 'supertrend' }
  ),
  // Options — Bullish
  t(
    'long-call',
    'Long Call',
    'free',
    'Options — Bullish',
    'Options',
    'Beginner',
    'Buy a call for directional upside.',
    { optionsTemplateId: 'long_call' }
  ),
  t(
    'short-put',
    'Short Put',
    'free',
    'Options — Bullish',
    'Options',
    'Intermediate',
    'Sell a put to collect premium in an uptrend.',
    { optionsTemplateId: 'short_put' }
  ),
  t(
    'bull-call-spread',
    'Bull Call Spread',
    'free',
    'Options — Bullish',
    'Options',
    'Intermediate',
    'Debit spread capping cost and reward.',
    { optionsTemplateId: 'bull_call_spread' }
  ),
  t(
    'bull-put-spread',
    'Bull Put Spread',
    'free',
    'Options — Bullish',
    'Options',
    'Intermediate',
    'Credit spread for a bullish bias.',
    { optionsTemplateId: 'bull_put_spread' }
  ),
  t(
    'long-synthetic',
    'Long Synthetic',
    'free',
    'Options — Bullish',
    'Options',
    'Advanced',
    'Synthetic long via call + short put.',
    { optionsTemplateId: 'long_synthetic' }
  ),
  t(
    'bull-butterfly',
    'Bull Butterfly',
    'free',
    'Options — Bullish',
    'Options',
    'Advanced',
    'Directional butterfly skewed bullish.',
    { optionsTemplateId: 'bullish_butterfly' }
  ),
  t(
    'bull-condor',
    'Bull Condor',
    'free',
    'Options — Bullish',
    'Options',
    'Advanced',
    'Condor positioned for upside drift.',
    { optionsTemplateId: 'bullish_condor' }
  ),
  // Options — Bearish
  t(
    'long-put',
    'Long Put',
    'free',
    'Options — Bearish',
    'Options',
    'Beginner',
    'Buy a put for directional downside.',
    { optionsTemplateId: 'long_put' }
  ),
  t(
    'short-call',
    'Short Call',
    'free',
    'Options — Bearish',
    'Options',
    'Advanced',
    'Sell a call to collect premium in a downtrend.',
    { optionsTemplateId: 'short_call' }
  ),
  t(
    'bear-call-spread',
    'Bear Call Spread',
    'free',
    'Options — Bearish',
    'Options',
    'Intermediate',
    'Credit spread for a bearish bias.',
    { optionsTemplateId: 'bear_call_spread' }
  ),
  t(
    'bear-put-spread',
    'Bear Put Spread',
    'free',
    'Options — Bearish',
    'Options',
    'Intermediate',
    'Debit spread capping cost and reward.',
    { optionsTemplateId: 'bear_put_spread' }
  ),
  t(
    'short-synthetic',
    'Short Synthetic',
    'free',
    'Options — Bearish',
    'Options',
    'Advanced',
    'Synthetic short via put + short call.',
    { optionsTemplateId: 'short_synthetic' }
  ),
  t(
    'bear-butterfly',
    'Bear Butterfly',
    'free',
    'Options — Bearish',
    'Options',
    'Advanced',
    'Directional butterfly skewed bearish.',
    { optionsTemplateId: 'bearish_butterfly' }
  ),
  t(
    'bear-condor',
    'Bear Condor',
    'free',
    'Options — Bearish',
    'Options',
    'Advanced',
    'Condor positioned for downside drift.',
    { optionsTemplateId: 'bearish_condor' }
  ),
  // Options — Neutral
  t(
    'long-straddle',
    'Long Straddle',
    'free',
    'Options — Neutral',
    'Options',
    'Intermediate',
    'Buy ATM call + put for a volatility expansion.',
    { optionsTemplateId: 'long_straddle' }
  ),
  t(
    'short-straddle',
    'Short Straddle',
    'free',
    'Options — Neutral',
    'Options',
    'Advanced',
    'Sell ATM call + put for premium decay.',
    { optionsTemplateId: 'short_straddle' }
  ),
  t(
    'long-strangle',
    'Long Strangle',
    'free',
    'Options — Neutral',
    'Options',
    'Intermediate',
    'Buy OTM call + put for cheaper vol exposure.',
    { optionsTemplateId: 'long_strangle' }
  ),
  t(
    'short-strangle',
    'Short Strangle',
    'free',
    'Options — Neutral',
    'Options',
    'Advanced',
    'Sell OTM call + put with a wider zone.',
    { optionsTemplateId: 'short_strangle' }
  ),
  t(
    'iron-condor',
    'Iron Condor',
    'free',
    'Options — Neutral',
    'Options',
    'Advanced',
    'Defined-risk range-bound premium seller.',
    { optionsTemplateId: 'short_iron_condor' }
  ),
  t(
    'iron-fly',
    'Iron Fly',
    'free',
    'Options — Neutral',
    'Options',
    'Advanced',
    'Tight-range defined-risk premium seller.',
    { optionsTemplateId: 'short_iron_fly' }
  ),
  t(
    'calendar',
    'Calendar',
    'free',
    'Options — Neutral',
    'Options',
    'Advanced',
    'Time spread across two expiries.',
    { optionsTemplateId: 'call_calendar' }
  ),
  t(
    'diagonal',
    'Diagonal',
    'free',
    'Options — Neutral',
    'Options',
    'Advanced',
    'Diagonal spread across strike and time.',
    { optionsTemplateId: 'diagonal_calendar' }
  ),
  t(
    'butterfly',
    'Butterfly',
    'free',
    'Options — Neutral',
    'Options',
    'Advanced',
    'Symmetric butterfly around ATM.',
    { optionsTemplateId: 'call_butterfly' }
  ),
  // Futures — no code slot exists yet for futures-specific logic (webhook
  // strategies have no indicator engine and Python strategies don't have a
  // futures-specific template surface). Honestly marked "Coming soon".
  t(
    'long-fut',
    'Long Futures',
    'free',
    'Futures',
    'Futures',
    'Beginner',
    'Directional long futures template.'
  ),
  t(
    'short-fut',
    'Short Futures',
    'free',
    'Futures',
    'Futures',
    'Beginner',
    'Directional short futures template.'
  ),
  t(
    'fut-breakout',
    'Futures Breakout',
    'free',
    'Futures',
    'Futures',
    'Intermediate',
    'Breakout entries on futures.'
  ),
  t(
    'fut-mom',
    'Futures Momentum',
    'free',
    'Futures',
    'Futures',
    'Intermediate',
    'Momentum entries on futures.'
  ),
  t(
    'cal-spread',
    'Calendar Spread',
    'free',
    'Futures',
    'Futures',
    'Advanced',
    'Near/far month futures calendar spread.'
  ),
  // Basket — real, generated multi-symbol Python strategies
  t(
    'eq-weight',
    'Equal Weight Basket',
    'free',
    'Basket',
    'Basket',
    'Beginner',
    'Trade a basket with equal weights.',
    { signalId: 'basket-equal-weight' }
  ),
  t(
    'top-vol',
    'Top Volume Basket',
    'free',
    'Basket',
    'Basket',
    'Intermediate',
    'Basket of top-volume names.',
    { signalId: 'basket-top-movers' }
  ),
  t(
    'top-gainers',
    'Top Gainers Basket',
    'free',
    'Basket',
    'Basket',
    'Intermediate',
    'Basket of top gaining names.',
    { signalId: 'basket-top-movers' }
  ),
  t(
    'sector-basket',
    'Sector Basket',
    'free',
    'Basket',
    'Basket',
    'Intermediate',
    'Sector-constrained basket.',
    { signalId: 'basket-equal-weight' }
  ),
]

// ---------------------------------------------------------------------------
// PRO TEMPLATES
// ---------------------------------------------------------------------------
const PRO: CatalogItem[] = [
  // Equity
  t(
    'mtf-ema',
    'Multi-Timeframe EMA',
    'pro',
    'Equity',
    'Equity',
    'Advanced',
    'EMA trend aligned across multiple timeframes.',
    { signalId: 'ema-cross' }
  ),
  t(
    'vwap-cpr',
    'VWAP + CPR Combo',
    'pro',
    'Equity',
    'Equity',
    'Advanced',
    'Combines VWAP bias with CPR levels.',
    { signalId: 'vwap-reversion' }
  ),
  t(
    'st-rsi',
    'Supertrend + RSI',
    'pro',
    'Equity',
    'Equity',
    'Intermediate',
    'Supertrend trend filtered by RSI.',
    { signalId: 'supertrend' }
  ),
  t(
    'ema-adx',
    'EMA + ADX',
    'pro',
    'Equity',
    'Equity',
    'Intermediate',
    'EMA trend gated by ADX strength.',
    { signalId: 'adx-trend' }
  ),
  t(
    'macd-vol',
    'MACD + Volume',
    'pro',
    'Equity',
    'Equity',
    'Intermediate',
    'MACD momentum confirmed by volume.',
    { signalId: 'macd-momentum' }
  ),
  t(
    'atr-trend',
    'ATR Trend',
    'pro',
    'Equity',
    'Equity',
    'Advanced',
    'ATR-based trailing trend system.',
    { signalId: 'atr-trend' }
  ),
  t(
    'bb-squeeze',
    'Bollinger Squeeze Breakout',
    'pro',
    'Equity',
    'Equity',
    'Advanced',
    'Trades volatility squeezes releasing into breakouts.',
    { signalId: 'bollinger-squeeze' }
  ),
  t(
    'vol-expansion',
    'Volatility Expansion',
    'pro',
    'Equity',
    'Equity',
    'Advanced',
    'Enters on expanding volatility regimes.',
    { signalId: 'bollinger-squeeze' }
  ),
  t(
    'opening-gap',
    'Opening Gap Strategy',
    'pro',
    'Equity',
    'Equity',
    'Advanced',
    'Trades opening gaps with fade/continuation logic.',
    { signalId: 'gap-strategy' }
  ),
  t(
    'breadth',
    'Market Breadth Strategy',
    'pro',
    'Equity',
    'Equity',
    'Advanced',
    'Uses advance/decline breadth for bias.'
  ),
  // Options
  t(
    'bwb',
    'Broken Wing Butterfly',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Asymmetric butterfly reducing one-side risk.',
    { optionsTemplateId: 'call_butterfly' }
  ),
  t(
    'bwc',
    'Broken Wing Condor',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Asymmetric condor with skewed wings.',
    { optionsTemplateId: 'short_iron_condor' }
  ),
  t(
    'ratio-back',
    'Ratio Backspread',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Net-long-vol ratio backspread.',
    { optionsTemplateId: 'call_ratio_back_spread' }
  ),
  t(
    'ladder',
    'Ladder Spread',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Laddered strikes for staged exposure.',
    { optionsTemplateId: 'call_ratio_spread' }
  ),
  t(
    'covered-call',
    'Covered Call',
    'pro',
    'Options',
    'Options',
    'Intermediate',
    'Long stock with a written call.',
    { optionsTemplateId: 'short_call' }
  ),
  t(
    'covered-put',
    'Covered Put',
    'pro',
    'Options',
    'Options',
    'Intermediate',
    'Short stock with a written put.',
    { optionsTemplateId: 'short_put' }
  ),
  t(
    'collar',
    'Collar',
    'pro',
    'Options',
    'Options',
    'Intermediate',
    'Protective put funded by a covered call.',
    { optionsTemplateId: 'risk_reversal' }
  ),
  t(
    'protective-put',
    'Protective Put',
    'pro',
    'Options',
    'Options',
    'Beginner',
    'Downside insurance on a long position.',
    { optionsTemplateId: 'long_put' }
  ),
  t(
    'strip',
    'Strip',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Volatility play weighted to the downside.',
    { optionsTemplateId: 'put_ratio_back_spread' }
  ),
  t(
    'strap',
    'Strap',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Volatility play weighted to the upside.',
    { optionsTemplateId: 'call_ratio_back_spread' }
  ),
  t('guts', 'Guts', 'pro', 'Options', 'Options', 'Advanced', 'ITM strangle variant.', {
    optionsTemplateId: 'short_strangle',
  }),
  t(
    'seagull',
    'Seagull',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Three-leg directional structure.',
    { optionsTemplateId: 'jade_lizard' }
  ),
  t('fence', 'Fence', 'pro', 'Options', 'Options', 'Advanced', 'Range-bounding collar variant.', {
    optionsTemplateId: 'risk_reversal',
  }),
  t(
    'xmas-tree',
    'Christmas Tree',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Staggered butterfly ladder.',
    { optionsTemplateId: 'double_fly' }
  ),
  t(
    'box-spread',
    'Box Spread',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Locked-range arbitrage structure.',
    { optionsTemplateId: 'long_iron_fly' }
  ),
  t(
    'conversion',
    'Conversion',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Long stock, long put, short call arbitrage.',
    { optionsTemplateId: 'short_synthetic' }
  ),
  t(
    'rev-conversion',
    'Reverse Conversion',
    'pro',
    'Options',
    'Options',
    'Advanced',
    'Short stock, short put, long call arbitrage.',
    { optionsTemplateId: 'long_synthetic' }
  ),
  // Futures — no real destination yet (see FREE tier note above)
  t(
    'basis-arb',
    'Basis Arbitrage',
    'pro',
    'Futures',
    'Futures',
    'Advanced',
    'Cash-futures basis arbitrage.'
  ),
  t(
    'cal-arb',
    'Calendar Arbitrage',
    'pro',
    'Futures',
    'Futures',
    'Advanced',
    'Near/far month calendar arbitrage.'
  ),
  t(
    'rollover',
    'Rollover Strategy',
    'pro',
    'Futures',
    'Futures',
    'Intermediate',
    'Systematic expiry rollovers.'
  ),
  t(
    'tf-fut',
    'Trend Following Futures',
    'pro',
    'Futures',
    'Futures',
    'Intermediate',
    'Trend following on futures.'
  ),
  t(
    'intraday-fut-scalp',
    'Intraday Futures Scalping',
    'pro',
    'Futures',
    'Futures',
    'Advanced',
    'High-frequency futures scalps.'
  ),
  // Portfolio — multi-symbol/beta logic has no real template surface yet
  t(
    'pair-trading',
    'Pair Trading',
    'pro',
    'Portfolio',
    'Portfolio',
    'Advanced',
    'Long/short mean-reverting pairs.'
  ),
  t(
    'beta-neutral',
    'Beta Neutral',
    'pro',
    'Portfolio',
    'Portfolio',
    'Advanced',
    'Neutralize portfolio beta.'
  ),
  t(
    'dollar-neutral',
    'Dollar Neutral',
    'pro',
    'Portfolio',
    'Portfolio',
    'Advanced',
    'Balance long/short notional.'
  ),
  t(
    'sector-rotation',
    'Sector Rotation',
    'pro',
    'Portfolio',
    'Portfolio',
    'Advanced',
    'Rotate into leading sectors.'
  ),
  t(
    'risk-parity',
    'Risk Parity',
    'pro',
    'Portfolio',
    'Portfolio',
    'Advanced',
    'Weight by risk contribution.'
  ),
  t(
    'portfolio-hedge',
    'Portfolio Hedging',
    'pro',
    'Portfolio',
    'Portfolio',
    'Advanced',
    'Dynamic portfolio hedging.'
  ),
]

// ---------------------------------------------------------------------------
// PREMIUM & AI STRATEGIES
//
// These tiers are now served entirely from the backend
// (`/strategy/api/marketplace`, merged into `backendPremium` in
// Marketplace.tsx) instead of a static curated list here. Every listing
// seeded there (blueprints/strategy.py::_init_mock_marketplace_listings)
// carries a real `template_id` that compiles into a genuine, working
// Deployment on subscribe (services/strategy_compiler.py) -- so unlike the
// previous static entries, subscribing actually produces a strategy that
// trades. Kept as empty arrays (rather than removed) so itemsByTier/
// categoriesForTier below don't need special-casing for these two tiers.
// ---------------------------------------------------------------------------
const PREMIUM: CatalogItem[] = []
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
