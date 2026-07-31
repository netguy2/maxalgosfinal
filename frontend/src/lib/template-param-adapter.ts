/**
 * Adapts a wizard's schema-driven `dynamicConfig` (StrategyConfigurator.tsx,
 * field names from strategy-schemas.ts's STRATEGY_SCHEMAS, e.g. `fastEma`,
 * `rsiLength`, `buyAbove`) into `SignalParams` (python-strategy-generator.ts's
 * generic, reused-across-signals field names, e.g. `fastPeriod`, `rsiPeriod`,
 * `rsiBuy`) so a live Deploy can generate a real Python script whose
 * indicator periods/thresholds actually match what the user configured in
 * the wizard, instead of silently falling back to the generator's
 * hardcoded defaults.
 *
 * Deliberately one small pure function per signalId rather than a single
 * generic remapper — several schema fields carry DIFFERENT meanings across
 * signals under the same generic SignalParams key (e.g. `gap-strategy`'s
 * gap threshold % rides in `rsiBuy`; `swing-breakout`/`roc-momentum`/
 * `donchian-pullback`/`atr-trend`/`ema-pullback` all overload `fastPeriod`/
 * `slowPeriod` for non-EMA concepts) — a table lets each mapping be
 * reviewed against its own schema instead of guessed from a shared rule.
 *
 * Schema fields with NO effect in the generator today (MACD `signalPeriod`,
 * ROC/ADX thresholds, volume lookback, VWAP deviation%, squeeze lookback/
 * percentile, ORB gap/volume filters & re-entry, EMA-cross trend filter)
 * are intentionally not mapped — the generator hardcodes a value for them
 * internally. Widening SignalParams/SIGNAL_BODIES to honor them is real
 * generator feature work, out of scope here.
 */

import type { SignalId, SignalParams } from './python-strategy-generator'

/** Schema's breakoutDirection ('both'|'high_only'|'low_only') to the
 * generator's direction enum ('LONG'|'SHORT'|'BOTH'). */
function mapBreakoutDirection(value: unknown): 'LONG' | 'SHORT' | 'BOTH' {
  if (value === 'high_only') return 'LONG'
  if (value === 'low_only') return 'SHORT'
  return 'BOTH'
}

function num(value: unknown, fallback: number): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

type Adapter = (cfg: Record<string, any>) => Partial<SignalParams>

const ADAPTERS: Partial<Record<SignalId, Adapter>> = {
  orb: (cfg) => ({
    orbMinutes: num(cfg.orbDuration, 15),
    direction: mapBreakoutDirection(cfg.breakoutDirection),
  }),
  'ema-cross': (cfg) => ({
    fastPeriod: num(cfg.fastEma, 9),
    slowPeriod: num(cfg.slowEma, 21),
  }),
  'sma-cross': (cfg) => ({
    fastPeriod: num(cfg.fastSma, 50),
    slowPeriod: num(cfg.slowSma, 200),
  }),
  'triple-ema': (cfg) => ({
    fastPeriod: num(cfg.fastPeriod, 5),
    midPeriod: num(cfg.midPeriod, 13),
    slowPeriod: num(cfg.slowPeriod, 34),
  }),
  supertrend: (cfg) => ({
    atrPeriod: num(cfg.atrPeriod, 10),
    atrMultiplier: num(cfg.multiplier, 3.0),
  }),
  'rsi-momentum': (cfg) => ({
    rsiPeriod: num(cfg.rsiLength, 14),
    rsiBuy: num(cfg.buyAbove, 55),
    rsiSell: num(cfg.sellBelow, 45),
  }),
  'macd-momentum': (cfg) => ({
    fastPeriod: num(cfg.fastPeriod, 12),
    slowPeriod: num(cfg.slowPeriod, 26),
  }),
  'rsi-reversal': (cfg) => ({
    rsiPeriod: num(cfg.rsiLength, 14),
    rsiBuy: num(cfg.oversoldLevel, 30), // generator reads this as OVERSOLD
    rsiSell: num(cfg.overboughtLevel, 70), // generator reads this as OVERBOUGHT
  }),
  'swing-breakout': (cfg) => ({
    fastPeriod: num(cfg.lookbackPeriod, 10), // generator reuses as SWING_LOOKBACK
    direction: mapBreakoutDirection(cfg.breakoutDirection),
  }),
  'roc-momentum': (cfg) => ({
    fastPeriod: num(cfg.rocPeriod, 10), // generator reuses as ROC_PERIOD
  }),
  'prev-day-breakout': (cfg) => ({
    direction: mapBreakoutDirection(cfg.breakoutDirection),
  }),
  'adx-trend': (cfg) => ({
    atrPeriod: num(cfg.adxPeriod, 14), // generator reuses as ADX_PERIOD
  }),
  'volume-breakout': (cfg) => ({
    volumeMultiplier: num(cfg.volumeMultiplier, 2.0),
  }),
  'bollinger-reversal': (cfg) => ({
    bbPeriod: num(cfg.bbPeriod, 20),
    bbStdDev: num(cfg.bbStdDev, 2.0),
  }),
  'keltner-reversion': (cfg) => ({
    midPeriod: num(cfg.emaPeriod, 20), // generator reuses as EMA_PERIOD
    atrPeriod: num(cfg.atrPeriod, 10),
    atrMultiplier: num(cfg.atrMultiplier, 2.0),
  }),
  'donchian-pullback': (cfg) => ({
    fastPeriod: num(cfg.donchianPeriod, 20), // generator reuses as DONCHIAN_PERIOD
  }),
  'ema-pullback': (cfg) => ({
    fastPeriod: num(cfg.emaPeriod, 20), // generator reuses as EMA_PERIOD
    slowPeriod: num(cfg.trendEmaPeriod, 50), // generator reuses as TREND_EMA_PERIOD
  }),
  'gap-strategy': (cfg) => ({
    rsiBuy: num(cfg.gapThresholdPercent, 1.0), // generator reads GAP_THRESHOLD_PCT from rsiBuy
  }),
  'bollinger-squeeze': (cfg) => ({
    bbPeriod: num(cfg.bbPeriod, 20),
    bbStdDev: num(cfg.bbStdDev, 2.0),
  }),
  'atr-trend': (cfg) => ({
    atrPeriod: num(cfg.atrPeriod, 14),
    fastPeriod: num(cfg.emaPeriod, 20), // generator reuses as EMA_PERIOD
    atrMultiplier: num(cfg.atrMultiplier, 1.5),
  }),
  // No configurable fields in these schemas -- generator defaults apply as-is.
  'inside-candle-breakout': () => ({}),
  'nr7-breakout': () => ({}),
  'vwap-reversion': () => ({}),
  'vwap-scalp': () => ({}),
  // basket_strategy schema exposes no fields; the generator's hardcoded
  // default basket symbols apply since the wizard has nothing to edit them
  // with (pre-existing limitation, not introduced by this adapter).
  'basket-equal-weight': () => ({}),
  'basket-top-movers': () => ({}),
}

/** True for every signalId this adapter (and therefore the live Python-
 * script deploy path) actually supports -- StrategyConfigurator.tsx uses
 * this to decide whether Deploy should generate+upload a script or fall
 * back to the legacy wizard/compiler pipeline. */
export function hasSignalAdapter(signalId: string | undefined): signalId is SignalId {
  return !!signalId && signalId in ADAPTERS
}

export function buildSignalParams(
  signalId: SignalId,
  dynamicConfig: Record<string, any>,
  common: {
    symbol: string
    exchange: string
    quantity: number
    product: string
    timeframe: string
  }
): SignalParams {
  const adapter = ADAPTERS[signalId]
  const mapped = adapter ? adapter(dynamicConfig) : {}
  return { ...common, ...mapped }
}
