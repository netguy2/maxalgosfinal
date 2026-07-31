// Data for the AI Strategy Wizard: maps (volatility outlook × market direction) to
// suggested option structures. Pure data, no JSX dependency.

/**
 * WizardStrategy.name -> lib/marketplace-catalog.ts CatalogItem.id (NOT
 * optionsTemplateId — StrategyBuilder.tsx's ?template= handler looks up
 * CATALOG.find(c => c.id === ...) and resolves optionsTemplateId from
 * there itself), for names confirmed to be a genuine 1:1 structural match
 * (same legs, same strikes-relative-to-ATM shape) — hand-verified against
 * marketplace-catalog.ts, not fuzzy-matched. Letting StrategyWizard seed
 * the Visual Builder with the real template instead of opening it blank.
 * Names with no entry here (Futures/Semi-Futures, ratio-spread/condor/
 * butterfly variants whose wizard description doesn't cleanly match a
 * single catalog template, "Strap & Strip" combos) intentionally fall
 * back to the existing blank-open behavior rather than risk seeding the
 * wrong structure.
 */
export const WIZARD_TO_TEMPLATE_ID: Record<string, string> = {
  'Long Call': 'long-call',
  'Long Put': 'long-put',
  'Long Straddle': 'long-straddle',
  'Long Strangle': 'long-strangle',
  'Short Straddle': 'short-straddle',
  'Short Strangle': 'short-strangle',
  'Short Put': 'short-put',
  'Short Call': 'short-call',
  'Bull Call Spread': 'bull-call-spread',
  'Bull Put Spread': 'bull-put-spread',
  'Bear Call Spread': 'bear-call-spread',
  'Bear Put Spread': 'bear-put-spread',
  'Long Futures': 'long-synthetic',
  'Long Semi Futures': 'long-synthetic',
  'Short Futures': 'short-synthetic',
  'Short Semi Futures': 'short-synthetic',
  'Call Ratio Backspread': 'ratio-back',
  'Put Ratio Backspread': 'strip',
  'Call Ratio Spread': 'ladder',
  'Put Ratio Spread': 'ladder',
  'Put & Call Ratio Spread': 'ladder',
  'Long Condor': 'bull-condor',
  'Short Condor': 'iron-condor',
  'Long Butterfly': 'bull-butterfly',
  'Short Butterfly': 'bear-butterfly',
  'Long Strap': 'strap',
  'Long Strip': 'strip',
  'Short Strap & Strip': 'short-straddle',
}

export interface WizardStrategy {
  name: string
  description: string
  risk: 'Limited Risk' | 'Unlimited Risk'
  return: 'Limited Return' | 'Unlimited Return'
  type: 'CE' | 'PE' | 'FUT' | 'SPREAD'
}

export const WIZARD_MATRIX: Record<string, Record<string, WizardStrategy[]>> = {
  Rising: {
    Bullish: [
      {
        name: 'Long Call',
        description:
          'Buy 1 ATM or OTM Call option. Unlimited upside if market rises above strike + premium.',
        risk: 'Limited Risk',
        return: 'Unlimited Return',
        type: 'CE',
      },
      {
        name: 'Call Ratio Backspread',
        description:
          'Sell 1 lower-strike Call + Buy 2 higher-strike Calls. Profits from a sharp upward move.',
        risk: 'Limited Risk',
        return: 'Unlimited Return',
        type: 'SPREAD',
      },
    ],
    Neutral: [
      {
        name: 'Long Straddle',
        description:
          'Buy 1 ATM Call + Buy 1 ATM Put (same strike, same expiry). Profit from large move in either direction.',
        risk: 'Limited Risk',
        return: 'Unlimited Return',
        type: 'SPREAD',
      },
      {
        name: 'Long Strangle',
        description:
          'Buy 1 OTM Call + Buy 1 OTM Put (different strikes). Cheaper alternative to Straddle.',
        risk: 'Limited Risk',
        return: 'Unlimited Return',
        type: 'SPREAD',
      },
      {
        name: 'Long Strap',
        description: 'Buy 2 ATM Calls + Buy 1 ATM Put. Bullish volatility play.',
        risk: 'Limited Risk',
        return: 'Unlimited Return',
        type: 'SPREAD',
      },
      {
        name: 'Long Strip',
        description: 'Buy 1 ATM Call + Buy 2 ATM Puts. Bearish volatility play.',
        risk: 'Limited Risk',
        return: 'Unlimited Return',
        type: 'SPREAD',
      },
    ],
    Bearish: [
      {
        name: 'Long Put',
        description: 'Buy 1 ATM or OTM Put option. Unlimited downside profit if market drops.',
        risk: 'Limited Risk',
        return: 'Unlimited Return',
        type: 'PE',
      },
      {
        name: 'Put Ratio Backspread',
        description:
          'Sell 1 higher-strike Put + Buy 2 lower-strike Puts. Profits from a sharp fall.',
        risk: 'Limited Risk',
        return: 'Unlimited Return',
        type: 'SPREAD',
      },
    ],
  },
  Neutral: {
    Bullish: [
      {
        name: 'Long Futures',
        description: 'Buy 1 Nifty/BankNifty futures lot. Full delta exposure to underlying.',
        risk: 'Unlimited Risk',
        return: 'Unlimited Return',
        type: 'FUT',
      },
      {
        name: 'Long Semi Futures',
        description: 'Deep ITM Long Call. Behaves like a futures contract with limited risk.',
        risk: 'Unlimited Risk',
        return: 'Unlimited Return',
        type: 'CE',
      },
      {
        name: 'Bull Call Spread',
        description:
          'Buy 1 lower-strike Call + Sell 1 higher-strike Call. Net debit trade with capped risk/reward.',
        risk: 'Limited Risk',
        return: 'Limited Return',
        type: 'SPREAD',
      },
      {
        name: 'Bull Put Spread',
        description:
          'Sell 1 higher-strike Put + Buy 1 lower-strike Put. Net credit trade that decays positively.',
        risk: 'Limited Risk',
        return: 'Limited Return',
        type: 'SPREAD',
      },
    ],
    Neutral: [
      {
        name: 'Long Condor',
        description:
          'Buy lower Call + Sell low-mid Call + Sell high-mid Call + Buy higher Call. Wide flat profit zone.',
        risk: 'Limited Risk',
        return: 'Limited Return',
        type: 'SPREAD',
      },
      {
        name: 'Short Condor',
        description:
          'Sell lower Call + Buy low-mid Call + Buy high-mid Call + Sell higher Call. Net credit breakout trade.',
        risk: 'Limited Risk',
        return: 'Limited Return',
        type: 'SPREAD',
      },
      {
        name: 'Long Butterfly',
        description:
          'Buy 1 lower-strike Call + Sell 2 ATM Calls + Buy 1 higher-strike Call. Capped risk.',
        risk: 'Limited Risk',
        return: 'Limited Return',
        type: 'SPREAD',
      },
      {
        name: 'Short Butterfly',
        description:
          'Sell 1 lower-strike Call + Buy 2 ATM Calls + Sell 1 higher-strike Call. Capped risk reversal play.',
        risk: 'Limited Risk',
        return: 'Limited Return',
        type: 'SPREAD',
      },
    ],
    Bearish: [
      {
        name: 'Short Futures',
        description: 'Sell 1 futures lot short. Linear bearish profits.',
        risk: 'Unlimited Risk',
        return: 'Unlimited Return',
        type: 'FUT',
      },
      {
        name: 'Short Semi Futures',
        description: 'Deep ITM Long Put. Behaves short futures with limited risk.',
        risk: 'Unlimited Risk',
        return: 'Unlimited Return',
        type: 'PE',
      },
      {
        name: 'Bear Put Spread',
        description:
          'Buy 1 higher-strike Put + Sell 1 lower-strike Put. Capped risk bearish trade.',
        risk: 'Limited Risk',
        return: 'Limited Return',
        type: 'SPREAD',
      },
      {
        name: 'Bear Call Spread',
        description:
          'Sell 1 lower-strike Call + Buy 1 higher-strike Call. Net credit bearish spread.',
        risk: 'Limited Risk',
        return: 'Limited Return',
        type: 'SPREAD',
      },
    ],
  },
  Falling: {
    Bullish: [
      {
        name: 'Short Put',
        description: 'Sell 1 Put option. Income strategy in low-volatility bullish markets.',
        risk: 'Unlimited Risk',
        return: 'Limited Return',
        type: 'PE',
      },
    ],
    Neutral: [
      {
        name: 'Short Straddle',
        description:
          'Sell 1 ATM Call + Sell 1 ATM Put. Maximum premium decay income in calm markets.',
        risk: 'Unlimited Risk',
        return: 'Limited Return',
        type: 'SPREAD',
      },
      {
        name: 'Short Strangle',
        description: 'Sell 1 OTM Call + Sell 1 OTM Put. Wider profit safety zone.',
        risk: 'Unlimited Risk',
        return: 'Limited Return',
        type: 'SPREAD',
      },
      {
        name: 'Short Strap & Strip',
        description: 'Sell 2 ATM Calls + Sell 1 ATM Put (or vice versa). Heavy premium collection.',
        risk: 'Unlimited Risk',
        return: 'Limited Return',
        type: 'SPREAD',
      },
      {
        name: 'Put & Call Ratio Spread',
        description: 'Combined Call and Put ratio spreads to hedge neutral range decay.',
        risk: 'Unlimited Risk',
        return: 'Limited Return',
        type: 'SPREAD',
      },
      {
        name: 'Call Ratio Spread',
        description: 'Buy 1 ATM Call + Sell 2 OTM Calls. Net credit range play.',
        risk: 'Unlimited Risk',
        return: 'Limited Return',
        type: 'SPREAD',
      },
      {
        name: 'Put Ratio Spread',
        description: 'Buy 1 ATM Put + Sell 2 OTM Puts. Net credit downside range play.',
        risk: 'Unlimited Risk',
        return: 'Limited Return',
        type: 'SPREAD',
      },
    ],
    Bearish: [
      {
        name: 'Short Call',
        description: 'Sell 1 Call option. Income strategy in low-volatility bearish markets.',
        risk: 'Unlimited Risk',
        return: 'Limited Return',
        type: 'CE',
      },
    ],
  },
}
