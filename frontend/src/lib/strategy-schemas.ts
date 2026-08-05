/**
 * Strategy Schema Architecture for No-Code Blueprint Configurator
 *
 * Provides template-aware dynamic configuration schemas, field specifications,
 * validation rules, and live plain-English explanation generators for all strategy categories.
 */

export type FieldType = 'select' | 'number' | 'text' | 'boolean' | 'time' | 'radio'

export interface SchemaField {
  key: string
  label: string
  type: FieldType
  default: any
  description?: string
  options?: { value: string; label: string }[]
  min?: number
  max?: number
  step?: number
  unit?: string
  category: 'entry' | 'exit' | 'risk' | 'execution' | 'market'
}

export interface StrategyTemplateSchema {
  id: string
  name: string
  category: string
  diagramType:
    | 'orb'
    | 'crossover'
    | 'supertrend'
    | 'rsi'
    | 'macd'
    | 'options'
    | 'breakout'
    | 'generic'
  defaultTimeframe: string
  fields: SchemaField[]
  generateExplanation: (config: Record<string, any>) => string
  validate: (config: Record<string, any>) => string[]
}

// === SCHEMA REGISTRY ===

export const STRATEGY_SCHEMAS: Record<string, StrategyTemplateSchema> = {
  // 1. OPENING RANGE BREAKOUT (ORB)
  orb: {
    id: 'orb',
    name: 'Opening Range Breakout (ORB)',
    category: 'Breakout',
    diagramType: 'orb',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'orbDuration',
        label: 'Opening Range Duration',
        type: 'select',
        default: '15',
        options: [
          { value: '5', label: '5 Minutes (09:15 - 09:20)' },
          { value: '15', label: '15 Minutes (09:15 - 09:30)' },
          { value: '30', label: '30 Minutes (09:15 - 09:45)' },
        ],
        category: 'entry',
      },
      {
        key: 'breakoutDirection',
        label: 'Breakout Direction',
        type: 'select',
        default: 'both',
        options: [
          { value: 'both', label: 'Both (High & Low Breakout)' },
          { value: 'high_only', label: 'High Only (Bullish Breakout)' },
          { value: 'low_only', label: 'Low Only (Bearish Breakdown)' },
        ],
        category: 'entry',
      },
      {
        key: 'confirmationMode',
        label: 'Breakout Confirmation',
        type: 'select',
        default: 'candle_close',
        options: [
          { value: 'candle_close', label: 'Candle Close Above/Below Range' },
          { value: 'instant', label: 'Instant Touch / Price Break' },
        ],
        category: 'entry',
      },
      {
        key: 'gapFilter',
        label: 'Gap Filter',
        type: 'boolean',
        default: true,
        description: 'Skip entries if open price gaps > 1.5% from yesterday close',
        category: 'entry',
      },
      {
        key: 'volumeFilter',
        label: 'Volume Spike Filter',
        type: 'boolean',
        default: false,
        description: 'Require breakout candle volume to exceed 1.5x 20-period SMA',
        category: 'entry',
      },
      {
        key: 'allowReentry',
        label: 'Allow Re-entry',
        type: 'boolean',
        default: false,
        description: 'Allow fresh entry if first trade hits Stop Loss',
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const duration = cfg.orbDuration || '15'
      const dir =
        cfg.breakoutDirection === 'high_only'
          ? 'BUY only'
          : cfg.breakoutDirection === 'low_only'
            ? 'SELL only'
            : 'BUY or SELL'
      const conf =
        cfg.confirmationMode === 'instant'
          ? 'immediately when price touches'
          : 'when candle closes outside'
      const gap = cfg.gapFilter
        ? '• Gap filter ACTIVE: skips trade if open price gaps > 1.5%\n'
        : ''
      const vol = cfg.volumeFilter
        ? '• Volume filter ACTIVE: requires breakout volume > 1.5x SMA\n'
        : ''

      return (
        `This strategy will:\n` +
        `• Monitor ${cfg.symbol || 'NIFTY'} on ${cfg.timeframe || duration + 'm'} timeframe\n` +
        `• Wait until 09:15 AM and calculate the first ${duration}-minute High and Low price range\n` +
        `• Trigger a ${dir} trade ${conf} the Opening Range\n` +
        `${gap}${vol}` +
        `• Apply a Stop Loss of ${cfg.slValue || '1'}${cfg.slType?.includes('%') ? '%' : ' pts'} and Target of ${cfg.targetValue || '2'}:1 Risk-Reward\n` +
        `• Auto square-off all open positions at ${cfg.squareoffTime || '15:15'} PM`
      )
    },
    validate: (cfg) => {
      const errs: string[] = []
      const duration = parseInt(cfg.orbDuration || '15', 10)
      const startTime = cfg.startTime || '09:20'
      const [h, m] = startTime.split(':').map(Number)
      const startMinutes = h * 60 + m
      const marketOpen = 9 * 60 + 15
      const minAllowed = marketOpen + duration

      if (startMinutes < minAllowed) {
        const reqH = Math.floor(minAllowed / 60)
        const reqM = minAllowed % 60
        const reqStr = `${String(reqH).padStart(2, '0')}:${String(reqM).padStart(2, '0')}`
        errs.push(
          `Trading start time (${startTime}) is too early for ${duration}-min ORB. Minimum start time is ${reqStr} AM.`
        )
      }
      return errs
    },
  },

  // 2. EMA CROSSOVER
  ema_cross: {
    id: 'ema_cross',
    name: 'EMA Crossover Trend',
    category: 'Trend Following',
    diagramType: 'crossover',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'fastEma',
        label: 'Fast EMA Period',
        type: 'number',
        default: 9,
        min: 2,
        max: 100,
        category: 'entry',
      },
      {
        key: 'slowEma',
        label: 'Slow EMA Period',
        type: 'number',
        default: 21,
        min: 5,
        max: 200,
        category: 'entry',
      },
      {
        key: 'priceSource',
        label: 'Price Source',
        type: 'select',
        default: 'close',
        options: [
          { value: 'close', label: 'Close Price' },
          { value: 'open', label: 'Open Price' },
          { value: 'hl2', label: 'Median Price (H+L)/2' },
        ],
        category: 'entry',
      },
      {
        key: 'trendFilter',
        label: 'Higher Timeframe Trend Filter',
        type: 'boolean',
        default: true,
        description: 'Only buy when price is above 200 EMA on 1-Hour chart',
        category: 'entry',
      },
      {
        key: 'exitOnReverse',
        label: 'Exit on Opposite Cross',
        type: 'boolean',
        default: true,
        description: 'Automatically close Long position if Fast EMA crosses below Slow EMA',
        category: 'exit',
      },
    ],
    generateExplanation: (cfg) => {
      const fast = cfg.fastEma || 9
      const slow = cfg.slowEma || 21
      const filter = cfg.trendFilter
        ? '• Requires price to be above 200 EMA for bullish entries\n'
        : ''
      const reverseExit = cfg.exitOnReverse
        ? '• Position will auto-close if reverse crossover occurs\n'
        : ''

      return (
        `This strategy will:\n` +
        `• Monitor ${cfg.symbol || 'NIFTY'} on ${cfg.timeframe || '15m'} timeframe\n` +
        `• Track Fast EMA (${fast}) crossing above/below Slow EMA (${slow})\n` +
        `• BUY when Fast EMA (${fast}) crosses ABOVE Slow EMA (${slow})\n` +
        `• SELL when Fast EMA (${fast}) crosses BELOW Slow EMA (${slow})\n` +
        `${filter}${reverseExit}` +
        `• Max trades per day capped at ${cfg.maxTradesPerDay || 2}`
      )
    },
    validate: (cfg) => {
      const errs: string[] = []
      const fast = parseInt(cfg.fastEma, 10)
      const slow = parseInt(cfg.slowEma, 10)
      if (fast >= slow) {
        errs.push(`Fast EMA period (${fast}) must be smaller than Slow EMA period (${slow}).`)
      }
      return errs
    },
  },

  // 3. SUPERTREND
  supertrend: {
    id: 'supertrend',
    name: 'Supertrend Trend Follower',
    category: 'Trend Following',
    diagramType: 'supertrend',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'atrPeriod',
        label: 'ATR Period',
        type: 'number',
        default: 10,
        min: 1,
        max: 50,
        category: 'entry',
      },
      {
        key: 'multiplier',
        label: 'Supertrend Multiplier',
        type: 'number',
        default: 3.0,
        step: 0.5,
        min: 1,
        max: 10,
        category: 'entry',
      },
      {
        key: 'confirmationCandles',
        label: 'Confirmation Candles',
        type: 'select',
        default: '1',
        options: [
          { value: '1', label: '1 Candle Close (Instant Signal)' },
          { value: '2', label: '2 Consecutive Candles' },
        ],
        category: 'entry',
      },
      {
        key: 'useEmaFilter',
        label: '50 EMA Filter',
        type: 'boolean',
        default: false,
        description: 'Only take BUY signals when price is above 50 EMA',
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const atr = cfg.atrPeriod || 10
      const mult = cfg.multiplier || 3.0
      const conf = cfg.confirmationCandles || '1'
      const ema = cfg.useEmaFilter
        ? '• 50 EMA filter enabled: skips trades counter to 50 EMA\n'
        : ''

      return (
        `This strategy will:\n` +
        `• Monitor Supertrend (${atr}, ${mult}) on ${cfg.symbol || 'NIFTY'} ${cfg.timeframe || '15m'}\n` +
        `• BUY when Supertrend turns GREEN (${conf} candle close)\n` +
        `• SELL when Supertrend turns RED (${conf} candle close)\n` +
        `${ema}` +
        `• Stop Loss tracks Supertrend trailing line dynamically`
      )
    },
    validate: () => [],
  },

  // 4. RSI MOMENTUM
  rsi_momentum: {
    id: 'rsi_momentum',
    name: 'RSI Momentum Oscillator',
    category: 'Momentum',
    diagramType: 'rsi',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'rsiLength',
        label: 'RSI Period',
        type: 'number',
        default: 14,
        min: 2,
        max: 50,
        category: 'entry',
      },
      {
        key: 'buyAbove',
        label: 'Bullish Threshold (RSI Buy Above)',
        type: 'number',
        default: 60,
        min: 50,
        max: 90,
        category: 'entry',
      },
      {
        key: 'sellBelow',
        label: 'Bearish Threshold (RSI Sell Below)',
        type: 'number',
        default: 40,
        min: 10,
        max: 50,
        category: 'entry',
      },
      {
        key: 'useVwapFilter',
        label: 'VWAP Filter',
        type: 'boolean',
        default: true,
        description: 'Require price to be above VWAP for BUY orders',
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const len = cfg.rsiLength || 14
      const buy = cfg.buyAbove || 60
      const sell = cfg.sellBelow || 40
      const vwap = cfg.useVwapFilter ? '• VWAP confirmation enabled\n' : ''

      return (
        `This strategy will:\n` +
        `• Calculate RSI (${len}) on ${cfg.symbol || 'NIFTY'} ${cfg.timeframe || '15m'}\n` +
        `• BUY when RSI rises ABOVE ${buy} (Bullish momentum)\n` +
        `• SELL when RSI falls BELOW ${sell} (Bearish momentum)\n` +
        `${vwap}` +
        `• Exit when RSI crosses back into neutral zone (40-60) or SL/Target hit`
      )
    },
    validate: (cfg) => {
      const errs: string[] = []
      if (parseInt(cfg.buyAbove, 10) <= parseInt(cfg.sellBelow, 10)) {
        errs.push('RSI Buy threshold must be higher than RSI Sell threshold.')
      }
      return errs
    },
  },

  // 6. SMA GOLDEN/DEATH CROSSOVER
  sma_cross: {
    id: 'sma_cross',
    name: 'SMA Golden Cross',
    category: 'Trend Following',
    diagramType: 'crossover',
    defaultTimeframe: '1d',
    fields: [
      {
        key: 'fastSma',
        label: 'Fast SMA Period',
        type: 'number',
        default: 50,
        min: 5,
        max: 100,
        category: 'entry',
      },
      {
        key: 'slowSma',
        label: 'Slow SMA Period',
        type: 'number',
        default: 200,
        min: 50,
        max: 400,
        category: 'entry',
      },
      {
        key: 'exitOnReverse',
        label: 'Exit on Opposite Cross',
        type: 'boolean',
        default: true,
        description:
          'Automatically close Long position if Fast SMA crosses below Slow SMA (Death Cross)',
        category: 'exit',
      },
    ],
    generateExplanation: (cfg) => {
      const fast = cfg.fastSma || 50
      const slow = cfg.slowSma || 200
      const reverseExit = cfg.exitOnReverse
        ? '• Position will auto-close on Death Cross (reverse crossover)\n'
        : ''

      return (
        `This strategy will:\n` +
        `• Monitor ${cfg.symbol || 'NIFTY'} on daily candles\n` +
        `• BUY when SMA (${fast}) crosses ABOVE SMA (${slow}) — the "Golden Cross"\n` +
        `• SELL when SMA (${fast}) crosses BELOW SMA (${slow}) — the "Death Cross"\n` +
        `${reverseExit}`
      )
    },
    validate: (cfg) => {
      const errs: string[] = []
      const fast = parseInt(cfg.fastSma, 10)
      const slow = parseInt(cfg.slowSma, 10)
      if (fast >= slow) {
        errs.push(`Fast SMA period (${fast}) must be smaller than Slow SMA period (${slow}).`)
      }
      return errs
    },
  },

  // 7. MACD MOMENTUM
  macd_momentum: {
    id: 'macd_momentum',
    name: 'MACD Signal Crossover',
    category: 'Momentum',
    diagramType: 'macd',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'fastPeriod',
        label: 'Fast EMA Period',
        type: 'number',
        default: 12,
        min: 2,
        max: 50,
        category: 'entry',
      },
      {
        key: 'slowPeriod',
        label: 'Slow EMA Period',
        type: 'number',
        default: 26,
        min: 5,
        max: 100,
        category: 'entry',
      },
      {
        key: 'signalPeriod',
        label: 'Signal Line Period',
        type: 'number',
        default: 9,
        min: 2,
        max: 50,
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const fast = cfg.fastPeriod || 12
      const slow = cfg.slowPeriod || 26
      const signal = cfg.signalPeriod || 9

      return (
        `This strategy will:\n` +
        `• Calculate MACD (${fast}, ${slow}, ${signal}) on ${cfg.symbol || 'NIFTY'} ${cfg.timeframe || '15m'}\n` +
        `• BUY when the MACD line crosses ABOVE its Signal line\n` +
        `• SELL when the MACD line crosses BELOW its Signal line`
      )
    },
    validate: (cfg) => {
      const errs: string[] = []
      const fast = parseInt(cfg.fastPeriod, 10)
      const slow = parseInt(cfg.slowPeriod, 10)
      if (fast >= slow) {
        errs.push(`Fast period (${fast}) must be smaller than Slow period (${slow}).`)
      }
      return errs
    },
  },

  // 8. RSI REVERSAL
  rsi_reversal: {
    id: 'rsi_reversal',
    name: 'RSI Reversal (Oversold/Overbought)',
    category: 'Mean Reversion',
    diagramType: 'rsi',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'rsiLength',
        label: 'RSI Period',
        type: 'number',
        default: 14,
        min: 2,
        max: 50,
        category: 'entry',
      },
      {
        key: 'oversoldLevel',
        label: 'Oversold Level',
        type: 'number',
        default: 30,
        min: 5,
        max: 40,
        category: 'entry',
      },
      {
        key: 'overboughtLevel',
        label: 'Overbought Level',
        type: 'number',
        default: 70,
        min: 60,
        max: 95,
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const len = cfg.rsiLength || 14
      const oversold = cfg.oversoldLevel || 30
      const overbought = cfg.overboughtLevel || 70

      return (
        `This strategy will:\n` +
        `• Calculate RSI (${len}) on ${cfg.symbol || 'NIFTY'} ${cfg.timeframe || '15m'}\n` +
        `• BUY when RSI crosses back UP through ${oversold} (oversold bounce)\n` +
        `• SELL when RSI crosses back DOWN through ${overbought} (overbought rejection)`
      )
    },
    validate: (cfg) => {
      const errs: string[] = []
      if (parseInt(cfg.oversoldLevel, 10) >= parseInt(cfg.overboughtLevel, 10)) {
        errs.push('Oversold level must be lower than Overbought level.')
      }
      return errs
    },
  },

  // 9. SWING BREAKOUT
  swing_breakout: {
    id: 'swing_breakout',
    name: 'Swing High/Low Breakout',
    category: 'Breakout',
    diagramType: 'breakout',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'lookbackPeriod',
        label: 'Swing Lookback Period',
        type: 'number',
        default: 20,
        min: 5,
        max: 100,
        description: 'Number of prior candles used to determine the swing high/low',
        category: 'entry',
      },
      {
        key: 'breakoutDirection',
        label: 'Breakout Direction',
        type: 'select',
        default: 'both',
        options: [
          { value: 'both', label: 'Both (High & Low Breakout)' },
          { value: 'high_only', label: 'High Only (Bullish Breakout)' },
          { value: 'low_only', label: 'Low Only (Bearish Breakdown)' },
        ],
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const period = cfg.lookbackPeriod || 20
      const dir =
        cfg.breakoutDirection === 'high_only'
          ? 'BUY only'
          : cfg.breakoutDirection === 'low_only'
            ? 'SELL only'
            : 'BUY or SELL'

      return (
        `This strategy will:\n` +
        `• Monitor ${cfg.symbol || 'NIFTY'} on ${cfg.timeframe || '15m'} timeframe\n` +
        `• Track the swing high/low over the last ${period} candles\n` +
        `• Trigger a ${dir} trade when price breaks beyond that swing level`
      )
    },
    validate: () => [],
  },

  // 10. RATE OF CHANGE (ROC) MOMENTUM
  roc_momentum: {
    id: 'roc_momentum',
    name: 'Rate of Change Momentum',
    category: 'Momentum',
    diagramType: 'generic',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'rocPeriod',
        label: 'ROC Period',
        type: 'number',
        default: 12,
        min: 2,
        max: 50,
        category: 'entry',
      },
      {
        key: 'buyAbove',
        label: 'Bullish Threshold (ROC % Buy Above)',
        type: 'number',
        default: 2,
        step: 0.5,
        min: 0,
        max: 20,
        category: 'entry',
      },
      {
        key: 'sellBelow',
        label: 'Bearish Threshold (ROC % Sell Below)',
        type: 'number',
        default: -2,
        step: 0.5,
        min: -20,
        max: 0,
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const period = cfg.rocPeriod || 12
      const buy = cfg.buyAbove ?? 2
      const sell = cfg.sellBelow ?? -2

      return (
        `This strategy will:\n` +
        `• Calculate Rate of Change (${period}) on ${cfg.symbol || 'NIFTY'} ${cfg.timeframe || '15m'}\n` +
        `• BUY when ROC rises ABOVE ${buy}% (bullish momentum)\n` +
        `• SELL when ROC falls BELOW ${sell}% (bearish momentum)`
      )
    },
    validate: (cfg) => {
      const errs: string[] = []
      if (parseFloat(cfg.buyAbove) <= parseFloat(cfg.sellBelow)) {
        errs.push('ROC Buy threshold must be higher than ROC Sell threshold.')
      }
      return errs
    },
  },

  // 11. PREVIOUS DAY HIGH/LOW BREAKOUT
  prev_day_breakout: {
    id: 'prev_day_breakout',
    name: 'Previous Day High/Low Breakout',
    category: 'Breakout',
    diagramType: 'breakout',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'breakoutDirection',
        label: 'Breakout Direction',
        type: 'select',
        default: 'both',
        options: [
          { value: 'both', label: 'Both (High & Low Breakout)' },
          { value: 'high_only', label: 'High Only (Bullish Breakout)' },
          { value: 'low_only', label: 'Low Only (Bearish Breakdown)' },
        ],
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const dir =
        cfg.breakoutDirection === 'high_only'
          ? 'BUY only'
          : cfg.breakoutDirection === 'low_only'
            ? 'SELL only'
            : 'BUY or SELL'

      return (
        `This strategy will:\n` +
        `• Monitor ${cfg.symbol || 'NIFTY'} on ${cfg.timeframe || '15m'} timeframe\n` +
        `• Track the previous trading day's High and Low\n` +
        `• Trigger a ${dir} trade when price breaks beyond yesterday's High/Low`
      )
    },
    validate: () => [],
  },

  // 5. OPTIONS STRATEGY (Iron Condor / Straddle / Spreads)
  options_strategy: {
    id: 'options_strategy',
    name: 'Multi-Leg Option Blueprint',
    category: 'Options',
    diagramType: 'options',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'strikeSelection',
        label: 'Strike Selection',
        type: 'select',
        default: 'ATM',
        options: [
          { value: 'ATM', label: 'ATM (At The Money)' },
          { value: 'OTM1', label: 'OTM 1 Strike Out' },
          { value: 'OTM2', label: 'OTM 2 Strikes Out' },
          { value: 'ITM1', label: 'ITM 1 Strike In' },
        ],
        category: 'entry',
      },
      {
        key: 'expiryType',
        label: 'Expiry',
        type: 'select',
        default: 'current_week',
        options: [
          { value: 'current_week', label: 'Weekly Expiry (Current)' },
          { value: 'next_week', label: 'Next Week Expiry' },
          { value: 'monthly', label: 'Monthly Expiry' },
        ],
        category: 'entry',
      },
      {
        key: 'lots',
        label: 'Lot Quantity',
        type: 'number',
        default: 2,
        min: 1,
        max: 100,
        category: 'risk',
      },
      {
        key: 'legSLPercent',
        label: 'Per-Leg Stop Loss %',
        type: 'number',
        default: 25,
        min: 5,
        max: 100,
        unit: '%',
        category: 'exit',
      },
    ],
    generateExplanation: (cfg) => {
      const strike = cfg.strikeSelection || 'ATM'
      const exp = cfg.expiryType?.replace('_', ' ') || 'current week'
      const lots = cfg.lots || 2
      const sl = cfg.legSLPercent || 25

      return (
        `This Options Blueprint will:\n` +
        `• Dynamically resolve ${strike} strikes for ${cfg.symbol || 'NIFTY'} (${exp})\n` +
        `• Execute multi-leg basket orders of ${lots} lot(s) in parallel\n` +
        `• Apply individual Leg SL of ${sl}% premium\n` +
        `• Auto square-off at ${cfg.squareoffTime || '15:15'} PM`
      )
    },
    validate: () => [],
  },

  // 12. TRIPLE EMA STACK
  triple_ema: {
    id: 'triple_ema',
    name: 'Triple EMA Trend Stack',
    category: 'Trend Following',
    diagramType: 'crossover',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'fastPeriod',
        label: 'Fast EMA Period',
        type: 'number',
        default: 5,
        min: 2,
        max: 50,
        category: 'entry',
      },
      {
        key: 'midPeriod',
        label: 'Mid EMA Period',
        type: 'number',
        default: 13,
        min: 3,
        max: 100,
        category: 'entry',
      },
      {
        key: 'slowPeriod',
        label: 'Slow EMA Period',
        type: 'number',
        default: 34,
        min: 5,
        max: 200,
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const fast = cfg.fastPeriod || 5
      const mid = cfg.midPeriod || 13
      const slow = cfg.slowPeriod || 34
      return (
        `This strategy will:\n` +
        `• Monitor ${cfg.symbol || 'NIFTY'} on ${cfg.timeframe || '15m'} timeframe\n` +
        `• BUY when EMA(${fast}) > EMA(${mid}) > EMA(${slow}) — a bullish stacked trend`
      )
    },
    validate: (cfg) => {
      const errs: string[] = []
      const fast = parseInt(cfg.fastPeriod, 10)
      const mid = parseInt(cfg.midPeriod, 10)
      const slow = parseInt(cfg.slowPeriod, 10)
      if (!(fast < mid && mid < slow)) {
        errs.push(`Periods must satisfy Fast (${fast}) < Mid (${mid}) < Slow (${slow}).`)
      }
      return errs
    },
  },

  // 13. ADX TREND FILTER
  adx_trend: {
    id: 'adx_trend',
    name: 'ADX Trend Filter',
    category: 'Trend Following',
    diagramType: 'generic',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'adxPeriod',
        label: 'ADX Period',
        type: 'number',
        default: 14,
        min: 5,
        max: 50,
        category: 'entry',
      },
      {
        key: 'adxThreshold',
        label: 'ADX Threshold',
        type: 'number',
        default: 25,
        min: 10,
        max: 50,
        description: 'Minimum ADX value to confirm a trending market',
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const period = cfg.adxPeriod || 14
      const threshold = cfg.adxThreshold || 25
      return (
        `This strategy will:\n` +
        `• Calculate ADX (${period}) on ${cfg.symbol || 'NIFTY'} ${cfg.timeframe || '15m'}\n` +
        `• Only trade when ADX rises above ${threshold} (confirms trend strength)\n` +
        `• BUY when +DI > -DI while ADX confirms trend`
      )
    },
    validate: () => [],
  },

  // 14. VOLUME BREAKOUT
  volume_breakout: {
    id: 'volume_breakout',
    name: 'Volume Breakout',
    category: 'Breakout',
    diagramType: 'breakout',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'volumeLookback',
        label: 'Volume Lookback Period',
        type: 'number',
        default: 20,
        min: 5,
        max: 100,
        category: 'entry',
      },
      {
        key: 'volumeMultiplier',
        label: 'Volume Surge Multiplier',
        type: 'number',
        default: 2.0,
        step: 0.5,
        min: 1.2,
        max: 10,
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const mult = cfg.volumeMultiplier || 2.0
      return (
        `This strategy will:\n` +
        `• Monitor ${cfg.symbol || 'NIFTY'} on ${cfg.timeframe || '15m'} timeframe\n` +
        `• Trigger when volume exceeds ${mult}x its rolling average, confirmed by rising price`
      )
    },
    validate: () => [],
  },

  // 15. INSIDE CANDLE BREAKOUT
  inside_candle_breakout: {
    id: 'inside_candle_breakout',
    name: 'Inside Candle Breakout',
    category: 'Breakout',
    diagramType: 'breakout',
    defaultTimeframe: '15m',
    fields: [],
    generateExplanation: (cfg) =>
      `This strategy will:\n` +
      `• Monitor ${cfg.symbol || 'NIFTY'} on ${cfg.timeframe || '15m'} timeframe\n` +
      `• Detect inside-bar (mother/inside candle) setups\n` +
      `• Trigger a BUY/SELL when price breaks beyond the mother candle's range`,
    validate: () => [],
  },

  // 16. NR7 BREAKOUT
  nr7_breakout: {
    id: 'nr7_breakout',
    name: 'NR7 Volatility Breakout',
    category: 'Breakout',
    diagramType: 'breakout',
    defaultTimeframe: '15m',
    fields: [],
    generateExplanation: (cfg) =>
      `This strategy will:\n` +
      `• Monitor ${cfg.symbol || 'NIFTY'} on ${cfg.timeframe || '15m'} timeframe\n` +
      `• Detect NR7 bars (narrowest range of the last 7 candles) — a volatility contraction\n` +
      `• Trigger a BUY/SELL when price breaks beyond that NR7 bar's range`,
    validate: () => [],
  },

  // 17. BOLLINGER BAND REVERSAL
  bollinger_reversal: {
    id: 'bollinger_reversal',
    name: 'Bollinger Band Reversal',
    category: 'Mean Reversion',
    diagramType: 'generic',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'bbPeriod',
        label: 'BB Period',
        type: 'number',
        default: 20,
        min: 5,
        max: 100,
        category: 'entry',
      },
      {
        key: 'bbStdDev',
        label: 'BB Std Dev',
        type: 'number',
        default: 2.0,
        step: 0.5,
        min: 1,
        max: 4,
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const period = cfg.bbPeriod || 20
      const std = cfg.bbStdDev || 2.0
      return (
        `This strategy will:\n` +
        `• Calculate Bollinger Bands (${period}, ${std}σ) on ${cfg.symbol || 'NIFTY'} ${cfg.timeframe || '15m'}\n` +
        `• BUY on a touch of the lower band (oversold reversion)\n` +
        `• SELL on a touch of the upper band (overbought reversion)`
      )
    },
    validate: () => [],
  },

  // 18. VWAP REVERSION
  vwap_reversion: {
    id: 'vwap_reversion',
    name: 'VWAP Reversion',
    category: 'Mean Reversion',
    diagramType: 'generic',
    defaultTimeframe: '5m',
    fields: [
      {
        key: 'deviationPercent',
        label: 'Deviation Threshold %',
        type: 'number',
        default: 0.5,
        step: 0.1,
        min: 0.1,
        max: 5,
        unit: '%',
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const dev = cfg.deviationPercent ?? 0.5
      return (
        `This strategy will:\n` +
        `• Track ${cfg.symbol || 'NIFTY'}'s session VWAP intraday\n` +
        `• BUY when price deviates more than ${dev}% below VWAP (reversion long)\n` +
        `• SELL when price deviates more than ${dev}% above VWAP (reversion short)`
      )
    },
    validate: () => [],
  },

  // 19. KELTNER CHANNEL REVERSION
  keltner_reversion: {
    id: 'keltner_reversion',
    name: 'Keltner Channel Reversion',
    category: 'Mean Reversion',
    diagramType: 'generic',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'emaPeriod',
        label: 'EMA Midline Period',
        type: 'number',
        default: 20,
        min: 5,
        max: 100,
        category: 'entry',
      },
      {
        key: 'atrPeriod',
        label: 'ATR Period',
        type: 'number',
        default: 10,
        min: 5,
        max: 50,
        category: 'entry',
      },
      {
        key: 'atrMultiplier',
        label: 'ATR Multiplier',
        type: 'number',
        default: 2.0,
        step: 0.5,
        min: 1,
        max: 5,
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const ema = cfg.emaPeriod || 20
      const atr = cfg.atrPeriod || 10
      const mult = cfg.atrMultiplier || 2.0
      return (
        `This strategy will:\n` +
        `• Calculate Keltner Channels (EMA ${ema}, ATR ${atr} x${mult}) on ${cfg.symbol || 'NIFTY'} ${cfg.timeframe || '15m'}\n` +
        `• BUY on a touch of the lower channel bound (reversion)\n` +
        `• SELL on a touch of the upper channel bound (reversion)`
      )
    },
    validate: () => [],
  },

  // 20. DONCHIAN PULLBACK
  donchian_pullback: {
    id: 'donchian_pullback',
    name: 'Donchian Channel Pullback',
    category: 'Mean Reversion',
    diagramType: 'generic',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'donchianPeriod',
        label: 'Donchian Period',
        type: 'number',
        default: 20,
        min: 5,
        max: 100,
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const period = cfg.donchianPeriod || 20
      return (
        `This strategy will:\n` +
        `• Calculate the ${period}-period Donchian Channel on ${cfg.symbol || 'NIFTY'} ${cfg.timeframe || '15m'}\n` +
        `• BUY when price pulls back to and bounces off the channel midline (uptrend)\n` +
        `• SELL when price pulls back to and rejects off the channel midline (downtrend)`
      )
    },
    validate: () => [],
  },

  // 21. EMA PULLBACK
  ema_pullback: {
    id: 'ema_pullback',
    name: 'EMA Pullback Bounce',
    category: 'Swing',
    diagramType: 'crossover',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'emaPeriod',
        label: 'Pullback EMA Period',
        type: 'number',
        default: 20,
        min: 5,
        max: 100,
        category: 'entry',
      },
      {
        key: 'trendEmaPeriod',
        label: 'Trend EMA Period',
        type: 'number',
        default: 50,
        min: 10,
        max: 200,
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const ema = cfg.emaPeriod || 20
      const trend = cfg.trendEmaPeriod || 50
      return (
        `This strategy will:\n` +
        `• Confirm an uptrend using EMA(${trend}) vs EMA(${ema}) on ${cfg.symbol || 'NIFTY'} ${cfg.timeframe || '15m'}\n` +
        `• BUY when price pulls back to touch EMA(${ema}) and bounces higher`
      )
    },
    validate: (cfg) => {
      const errs: string[] = []
      if (parseInt(cfg.emaPeriod, 10) >= parseInt(cfg.trendEmaPeriod, 10)) {
        errs.push('Pullback EMA period must be smaller than Trend EMA period.')
      }
      return errs
    },
  },

  // 22. VWAP SCALP
  vwap_scalp: {
    id: 'vwap_scalp',
    name: 'VWAP Scalper',
    category: 'Scalping',
    diagramType: 'crossover',
    defaultTimeframe: '5m',
    fields: [],
    generateExplanation: (cfg) =>
      `This strategy will:\n` +
      `• Track ${cfg.symbol || 'NIFTY'}'s session VWAP on a fast ${cfg.timeframe || '5m'} timeframe\n` +
      `• BUY when price crosses ABOVE VWAP, SELL when price crosses BELOW VWAP`,
    validate: () => [],
  },

  // 23. GAP STRATEGY
  gap_strategy: {
    id: 'gap_strategy',
    name: 'Opening Gap Strategy',
    category: 'Breakout',
    diagramType: 'breakout',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'gapThresholdPercent',
        label: 'Gap Threshold %',
        type: 'number',
        default: 1.0,
        step: 0.25,
        min: 0.25,
        max: 10,
        unit: '%',
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const threshold = cfg.gapThresholdPercent || 1.0
      return (
        `This strategy will:\n` +
        `• Compare ${cfg.symbol || 'NIFTY'}'s open vs yesterday's close each morning\n` +
        `• BUY on a gap-up beyond ${threshold}%, SELL on a gap-down beyond ${threshold}%`
      )
    },
    validate: () => [],
  },

  // 24. BOLLINGER SQUEEZE
  bollinger_squeeze: {
    id: 'bollinger_squeeze',
    name: 'Bollinger Squeeze Breakout',
    category: 'Breakout',
    diagramType: 'breakout',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'bbPeriod',
        label: 'BB Period',
        type: 'number',
        default: 20,
        min: 5,
        max: 100,
        category: 'entry',
      },
      {
        key: 'bbStdDev',
        label: 'BB Std Dev',
        type: 'number',
        default: 2.0,
        step: 0.5,
        min: 1,
        max: 4,
        category: 'entry',
      },
      {
        key: 'squeezeLookback',
        label: 'Squeeze Lookback',
        type: 'number',
        default: 50,
        min: 20,
        max: 200,
        description: 'Bars used to determine what counts as a "squeeze"',
        category: 'entry',
      },
      {
        key: 'squeezePercentile',
        label: 'Squeeze Percentile',
        type: 'number',
        default: 20,
        min: 5,
        max: 40,
        unit: '%',
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const period = cfg.bbPeriod || 20
      return (
        `This strategy will:\n` +
        `• Track Bollinger Bandwidth (${period}) on ${cfg.symbol || 'NIFTY'} ${cfg.timeframe || '15m'}\n` +
        `• Detect low-volatility squeezes, then BUY/SELL on the breakout release`
      )
    },
    validate: () => [],
  },

  // 25. ATR TREND
  atr_trend: {
    id: 'atr_trend',
    name: 'ATR Trailing Trend',
    category: 'Trend Following',
    diagramType: 'crossover',
    defaultTimeframe: '15m',
    fields: [
      {
        key: 'atrPeriod',
        label: 'ATR Period',
        type: 'number',
        default: 14,
        min: 5,
        max: 50,
        category: 'entry',
      },
      {
        key: 'emaPeriod',
        label: 'EMA Anchor Period',
        type: 'number',
        default: 20,
        min: 5,
        max: 100,
        category: 'entry',
      },
      {
        key: 'atrMultiplier',
        label: 'ATR Multiplier',
        type: 'number',
        default: 1.5,
        step: 0.25,
        min: 0.5,
        max: 5,
        category: 'entry',
      },
    ],
    generateExplanation: (cfg) => {
      const atr = cfg.atrPeriod || 14
      const ema = cfg.emaPeriod || 20
      const mult = cfg.atrMultiplier || 1.5
      return (
        `This strategy will:\n` +
        `• Calculate an ATR(${atr})-anchored trailing stop off EMA(${ema}) x${mult} on ${cfg.symbol || 'NIFTY'} ${cfg.timeframe || '15m'}\n` +
        `• BUY when price crosses above the trailing stop, EXIT when price crosses below it`
      )
    },
    validate: () => [],
  },

  // 26. BASKET STRATEGIES (NOT YET SUPPORTED for rule-based live deployment)
  basket_strategy: {
    id: 'basket_strategy',
    name: 'Multi-Symbol Basket Strategy',
    category: 'Basket',
    diagramType: 'generic',
    defaultTimeframe: '15m',
    fields: [],
    generateExplanation: () =>
      `Basket strategies (equal-weight / top-movers ranking across multiple symbols) are ` +
      `not yet supported for live deployment through this wizard — they require ` +
      `multi-symbol ranking and execution, which the current single-symbol rule engine ` +
      `doesn't support. Deploying will show a clear error rather than silently doing nothing.`,
    validate: () => [],
  },
}

// Exact signalId -> schema key mapping. Catalog `id` values (e.g. "sma-golden",
// "rsi-rev", "swing-high") bear no naming relationship to their strategy TYPE
// -- lib/marketplace-catalog.ts's `signalId` field is the real type identifier,
// and multiple catalog ids can share one signalId (e.g. "swing-high" and
// "swing-low" both use signalId: "swing-breakout"). Substring-matching on the
// catalog id (the old approach) both missed real matches and produced false
// collisions (e.g. "rsi-rev" contains "rsi" and would incorrectly resolve to
// rsi_momentum instead of rsi_reversal). This map must be kept in sync with
// services/strategy_compiler.py's STRATEGY_TYPE_REGISTRY -- same keys, same
// signalId values, so frontend/backend never disagree about which schema a
// given catalog item resolves to.
const SIGNAL_ID_TO_SCHEMA_KEY: Record<string, string> = {
  orb: 'orb',
  'ema-cross': 'ema_cross',
  supertrend: 'supertrend',
  'rsi-momentum': 'rsi_momentum',
  'sma-cross': 'sma_cross',
  'macd-momentum': 'macd_momentum',
  'rsi-reversal': 'rsi_reversal',
  'swing-breakout': 'swing_breakout',
  'roc-momentum': 'roc_momentum',
  'prev-day-breakout': 'prev_day_breakout',
  'triple-ema': 'triple_ema',
  'adx-trend': 'adx_trend',
  'volume-breakout': 'volume_breakout',
  'inside-candle-breakout': 'inside_candle_breakout',
  'nr7-breakout': 'nr7_breakout',
  'bollinger-reversal': 'bollinger_reversal',
  'vwap-reversion': 'vwap_reversion',
  'keltner-reversion': 'keltner_reversion',
  'donchian-pullback': 'donchian_pullback',
  'ema-pullback': 'ema_pullback',
  'vwap-scalp': 'vwap_scalp',
  'gap-strategy': 'gap_strategy',
  'bollinger-squeeze': 'bollinger_squeeze',
  'atr-trend': 'atr_trend',
  'basket-equal-weight': 'basket_strategy',
  'basket-top-movers': 'basket_strategy',
}

export function getSchemaForTemplate(templateIdOrSignalId: string): StrategyTemplateSchema {
  if (!templateIdOrSignalId) return STRATEGY_SCHEMAS.orb

  const key = SIGNAL_ID_TO_SCHEMA_KEY[templateIdOrSignalId.toLowerCase()]
  if (key && STRATEGY_SCHEMAS[key]) return STRATEGY_SCHEMAS[key]

  // Legacy fallback for direct/manual URL access with no matching catalog
  // entry (e.g. a hand-typed ?template=orb-15) -- substring matching, same
  // as before, for the ORIGINAL 5 blueprint ids only (these were never
  // affected by the collision problem since their ids happen to contain
  // their own type name).
  const id = templateIdOrSignalId.toLowerCase()
  if (id.includes('orb')) return STRATEGY_SCHEMAS.orb
  if (id.includes('ema') && id.includes('cross')) return STRATEGY_SCHEMAS.ema_cross
  if (id.includes('supertrend')) return STRATEGY_SCHEMAS.supertrend
  if (id.includes('rsi')) return STRATEGY_SCHEMAS.rsi_momentum
  if (
    id.includes('condor') ||
    id.includes('straddle') ||
    id.includes('option') ||
    id.includes('spread')
  ) {
    return STRATEGY_SCHEMAS.options_strategy
  }

  return STRATEGY_SCHEMAS.orb
}
