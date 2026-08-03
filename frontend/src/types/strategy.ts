// Strategy Types for Webhook-based Strategies

export interface Strategy {
  id: number
  name: string
  webhook_id: string
  platform: string
  is_active: boolean
  is_intraday: boolean
  trading_mode: 'LONG' | 'SHORT' | 'BOTH'
  brokers?: string
  lifecycle_state?: string
  signal_source?: string
  /** 'legacy' (2-action BUY/SELL, default), 'unified' (4-action
   * BUY/SELL/SHORT/EXIT with per-mapping order_side), or 'stateful'
   * (LegGroup/Leg rotation -- tracks which leg is currently open so the
   * same signal can mean "close whichever leg is open, open the other
   * one", e.g. a Call/Put reversal) -- see services/signal_engine.py's
   * _process_signal_event dispatch. */
  execution_model?: ExecutionModel
  start_time: string | null
  end_time: string | null
  squareoff_time: string | null
  created_at: string
  updated_at: string
}

export type ExecutionModel = 'legacy' | 'unified' | 'stateful'

/** The signal this mapping reacts to. Only BUY/SELL are valid on
 * 'legacy' strategies; all four are valid on 'unified' strategies. */
export type MappingAction = 'BUY' | 'SELL' | 'SHORT' | 'EXIT'

export const UNIFIED_ACTIONS: { value: MappingAction; label: string }[] = [
  { value: 'BUY', label: 'BUY' },
  { value: 'SELL', label: 'SELL' },
  { value: 'SHORT', label: 'SHORT' },
  { value: 'EXIT', label: 'EXIT' },
]

/** What a mapping DOES when its trigger signal arrives -- distinct from
 * `action`, which is WHICH signal it listens for. Mirrors the verb set used
 * by mainstream webhook platforms (TradersPost: buy/sell/exit/reverse/add)
 * so alert bodies written for those services map over directly. */
export type SignalAction = 'ENTER' | 'EXIT' | 'REVERSE' | 'ADD' | 'REDUCE' | 'IGNORE'

export const SIGNAL_ACTIONS: {
  value: SignalAction
  label: string
  description: string
}[] = [
  { value: 'ENTER', label: 'Enter', description: 'Open a new position.' },
  { value: 'EXIT', label: 'Exit', description: 'Close the open position for this instrument.' },
  {
    value: 'REVERSE',
    label: 'Reverse',
    description: 'Close what is open, then enter the opposite side.',
  },
  { value: 'ADD', label: 'Add', description: 'Add to an existing position (pyramid).' },
  { value: 'REDUCE', label: 'Reduce', description: 'Partially close an existing position.' },
  {
    value: 'IGNORE',
    label: 'Ignore',
    description: 'Do nothing — mute this signal without deleting the row.',
  },
]

export type OrderType = 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'

export const ORDER_TYPES: { value: OrderType; label: string }[] = [
  { value: 'MARKET', label: 'Market' },
  { value: 'LIMIT', label: 'Limit' },
  { value: 'SL', label: 'Stop Limit (SL)' },
  { value: 'SL-M', label: 'Stop Market (SL-M)' },
]

/** SL/target/trailing are stored as a percent or a points offset, never an
 * absolute price -- one mapping is reused across many fills at different
 * prices, so an absolute level would be wrong on every fill but the first. */
export type RiskValueType = 'percent' | 'points'

export const RISK_VALUE_TYPES: { value: RiskValueType; label: string }[] = [
  { value: 'percent', label: '%' },
  { value: 'points', label: 'pts' },
]

export interface StrategySymbolMapping {
  id: number
  strategy_id: number
  symbol: string
  action?: MappingAction
  exchange: string
  quantity: number
  product_type: 'MIS' | 'CNC' | 'NRML'
  instrument?: string
  is_active: boolean
  instrument_type?: InstrumentType
  underlying?: string
  expiry_type?: ExpiryType
  option_type?: 'CE' | 'PE'
  strike_offset?: string
  strike_selection_mode?: StrikeSelectionMode
  strike_target_value?: number | null
  /** What to do when the signal fires. Server normalises null to 'ENTER'. */
  signal_action?: SignalAction
  order_type?: OrderType
  limit_price?: number | null
  trigger_price?: number | null
  stop_loss_type?: RiskValueType | null
  stop_loss_value?: number | null
  target_type?: RiskValueType | null
  target_value?: number | null
  trailing_type?: RiskValueType | null
  trailing_value?: number | null
  /** Size in lots for F&O; resolved against the contract's lot size at
   * signal time. When set it overrides `quantity`. */
  lots?: number | null
  /** Mappings sharing a basket fire together as one multi-leg order (e.g.
   * a straddle from a single alert). Null = standalone. */
  leg_basket?: string | null
  basket_leg_order?: number | null
  label?: string | null
  /** BUY/SELL order this mapping places when its `action` matches the
   * incoming signal -- only meaningful on 'unified' strategies. Unset
   * (null) means "derive from `action`" (BUY action -> BUY order,
   * everything else -> SELL order), same as every mapping created
   * before this field existed. Set it to the OPPOSITE of what you'd
   * expect for reversal/flip strategies, e.g. a SELL-triggered mapping
   * with order_side=BUY to enter a Put when a Call is exited. */
  order_side?: 'BUY' | 'SELL' | null
  created_at: string
}

/** Which raw webhook signal opens/closes a leg. BUY/SELL/SHORT are
 * ordinary tradable legs; EXIT is a pure "flatten" trigger with no
 * instrument of its own -- see Leg's `condition`/EXIT handling below. */
export type LegEntrySignal = 'BUY' | 'SELL' | 'SHORT' | 'EXIT'

export const LEG_ENTRY_SIGNALS: { value: LegEntrySignal; label: string }[] = [
  { value: 'BUY', label: 'BUY' },
  { value: 'SELL', label: 'SELL' },
  { value: 'SHORT', label: 'SHORT' },
  { value: 'EXIT', label: 'EXIT (flatten)' },
]

export type ConditionOperator = '>' | '<' | '>=' | '<=' | '==' | '!='

export const CONDITION_OPERATORS: { value: ConditionOperator; label: string }[] = [
  { value: '>', label: '> (greater than)' },
  { value: '<', label: '< (less than)' },
  { value: '>=', label: '>= (greater or equal)' },
  { value: '<=', label: '<= (less or equal)' },
  { value: '==', label: '== (equal to)' },
  { value: '!=', label: '!= (not equal to)' },
]

/** Common indicator names to suggest in the condition editor -- not
 * exhaustive (services/indicator_registry.py registers ~40), just the
 * frequently-used ones; the field still accepts any string. */
export const COMMON_CONDITION_INDICATORS = [
  'SPOT',
  'RSI',
  'EMA',
  'SMA',
  'VWAP',
  'MACD',
  'ATR',
  'ADX',
] as const

/** One evaluable condition leaf, discriminated by `type`. Matches the leaf
 * shape services/condition_engine.py's evaluate_conditions_tree consumes.
 * `indicator` is the original (and default when `type` is omitted) shape;
 * the other three are system conditions backed by real platform data --
 * see evaluate_conditions_tree's docstring for exactly what each checks. */
export type ConditionLeaf =
  | { type: 'indicator'; indicator: string; condition: ConditionOperator; value: number | string }
  | { type: 'market_open'; exchange?: string }
  | { type: 'broker_connected'; broker?: string }
  | { type: 'signal_fresh'; condition: ConditionOperator; value_seconds: number }

/** A condition attached to a Leg: either a single leaf, or a group of
 * leaves/nested groups joined by AND/OR. The leg-group UI only ever
 * builds one flat AND/OR row per leg (no UI for nesting groups within
 * groups), but the shape and backend validator both support arbitrary
 * nesting for future use. */
export type ConditionNode = ConditionLeaf | { operator: 'AND' | 'OR'; children: ConditionNode[] }

export const CONDITION_TYPES: {
  value: ConditionLeaf['type']
  label: string
  description: string
}[] = [
  {
    value: 'indicator',
    label: 'Indicator Comparison',
    description: 'Compare a live indicator (RSI, EMA, SPOT, ...) against a value.',
  },
  {
    value: 'market_open',
    label: 'Market Open',
    description: 'Only trigger while the exchange is in trading hours.',
  },
  {
    value: 'broker_connected',
    label: 'Broker Connected',
    description: 'Only trigger if a broker session is active.',
  },
  {
    value: 'signal_fresh',
    label: 'Signal Fresh',
    description: 'Only trigger if the webhook signal is recent enough.',
  },
]

/** One instrument within a LegGroup -- e.g. the "Call" or "Put" side of a
 * reversal. Only meaningful on 'stateful' strategies. `entry_signal` is
 * which raw webhook signal opens this leg; `order_side` is the entry
 * order it places when opened (almost always BUY for a long option leg).
 * Mirrors StrategySymbolMapping's FUT/OPT/EQ instrument fields. An EXIT
 * leg (entry_signal === 'EXIT') has no instrument -- every field below
 * `entry_signal` is null/absent for it. `condition`, when set, must ALSO
 * be true (in addition to entry_signal matching) for the leg to trigger --
 * only gates opening, never closing. */
export interface Leg {
  id: number
  leg_group_id: number
  label: string
  entry_signal: LegEntrySignal
  order_side: 'BUY' | 'SELL' | null
  instrument_type: InstrumentType | null
  exchange: string | null
  underlying?: string
  expiry_type?: ExpiryType
  option_type?: 'CE' | 'PE'
  strike_offset?: string
  strike_selection_mode?: StrikeSelectionMode
  strike_target_value?: number | null
  instrument?: string
  quantity: number | null
  product_type: string | null
  condition: ConditionNode | null
  sort_order: number
}

/** A rotating position: a named set of mutually-exclusive Legs (e.g.
 * "Call" and "Put"), where exactly one (or none) is open at a time.
 * `current_leg_id` is the live state -- null means flat (no leg open).
 * See services/signal_engine.py's _process_leg_group_webhook_signal for
 * the rotation logic this state drives. */
export interface LegGroup {
  id: number
  strategy_id: number
  name: string
  is_active: boolean
  current_leg_id: number | null
  events_timeline: { time: string; event: string }[]
  legs: Leg[]
  created_at: string
  updated_at: string | null
}

/** Payload shape for one leg in a create/update leg-group request --
 * matches Leg's fields minus the server-assigned id/leg_group_id. An EXIT
 * leg only needs `label`/`entry_signal` (all other fields omitted). */
export interface LegRequest {
  label: string
  entry_signal: LegEntrySignal
  order_side?: 'BUY' | 'SELL'
  instrument_type?: InstrumentType
  exchange?: string
  underlying?: string
  expiry_type?: ExpiryType
  option_type?: 'CE' | 'PE'
  strike_offset?: string
  strike_selection_mode?: StrikeSelectionMode
  strike_target_value?: number | null
  instrument?: string
  quantity?: number
  product_type?: string
  condition?: ConditionNode | null
}

export interface CreateLegGroupRequest {
  name: string
  legs: LegRequest[]
}

export interface CreateCePeReversalRequest {
  underlying: string
  exchange: string
  expiry_type: ExpiryType
  strike_offset: string
  quantity: number
  product_type: string
}

export interface CreateStrategyRequest {
  name: string
  platform: string
  strategy_type: 'intraday' | 'positional'
  trading_mode: 'LONG' | 'SHORT' | 'BOTH'
  brokers?: string
  start_time?: string
  end_time?: string
  squareoff_time?: string
  /** Wizard blueprint id (e.g. "orb-15", "ema-cross") from
   * frontend/src/lib/strategy-schemas.ts's STRATEGY_SCHEMAS keys. Lets the
   * backend compiler (services/strategy_compiler.py) know how to translate
   * this strategy's config into a real conditions_tree at deploy time. */
  template_id?: string
  /** Provenance tag, not a functional field -- lets a creation flow mark
   * "how was this strategy created" for later filtering (e.g. MaxHook
   * connections are excluded from the My Strategies list; see
   * StrategyIndex.tsx's unifiedRows). Omit for the default My Strategies
   * creation flow, which the backend labels "TradingView" as before. */
  signal_source?: string
}

export interface AddSymbolRequest {
  symbol: string
  action?: MappingAction
  exchange: string
  quantity: number
  product_type: string
  instrument?: string
  instrument_type?: InstrumentType
  underlying?: string
  expiry_type?: ExpiryType
  option_type?: 'CE' | 'PE'
  strike_offset?: string
  strike_selection_mode?: StrikeSelectionMode
  strike_target_value?: number | null
  order_side?: 'BUY' | 'SELL'
  signal_action?: SignalAction
  order_type?: OrderType
  limit_price?: number | null
  trigger_price?: number | null
  stop_loss_type?: RiskValueType
  stop_loss_value?: number | null
  target_type?: RiskValueType
  target_value?: number | null
  trailing_type?: RiskValueType
  trailing_value?: number | null
  lots?: number | null
  leg_basket?: string | null
  basket_leg_order?: number | null
  label?: string | null
}

export type InstrumentType = 'EQ' | 'FUT' | 'OPT'

export const INSTRUMENT_TYPES: { value: InstrumentType; label: string }[] = [
  { value: 'EQ', label: 'Equity / Index' },
  { value: 'FUT', label: 'Futures' },
  { value: 'OPT', label: 'Options' },
]

export type ExpiryType = 'current_week' | 'next_week' | 'current_month' | 'next_month'

export const EXPIRY_TYPES: { value: ExpiryType; label: string }[] = [
  { value: 'current_week', label: 'Weekly (Current)' },
  { value: 'next_week', label: 'Weekly (Next)' },
  { value: 'current_month', label: 'Monthly (Current)' },
  { value: 'next_month', label: 'Monthly (Next)' },
]

// Mirrors frontend/src/lib/strategy-schemas.ts's existing strikeSelection
// option list for the options_strategy wizard blueprint -- same
// labels/values reused here rather than inventing a new set.
export const STRIKE_OFFSETS = [
  'ITM5',
  'ITM4',
  'ITM3',
  'ITM2',
  'ITM1',
  'ATM',
  'OTM1',
  'OTM2',
  'OTM3',
  'OTM4',
  'OTM5',
] as const

/** How an option strike is chosen. "offset" (default) uses the fixed
 * ATM/ITM/OTM STRIKE_OFFSETS list above. "premium"/"delta" resolve live to
 * whichever strike's premium/delta is closest to a target value; "oi"
 * resolves to the highest-open-interest strike -- see
 * services/option_symbol_service.py's get_option_symbol_by_metric. */
export type StrikeSelectionMode = 'offset' | 'premium' | 'delta' | 'oi'

export const STRIKE_SELECTION_MODES: {
  value: StrikeSelectionMode
  label: string
  description: string
}[] = [
  {
    value: 'offset',
    label: 'Offset (ATM/ITM/OTM)',
    description: 'Fixed offset from the at-the-money strike.',
  },
  {
    value: 'premium',
    label: 'Premium',
    description: 'Strike whose live premium is closest to a target price.',
  },
  {
    value: 'delta',
    label: 'Delta',
    description: 'Strike whose live delta is closest to a target (0-1).',
  },
  { value: 'oi', label: 'Max OI', description: 'Strike with the highest open interest right now.' },
]

export interface BulkSymbolRequest {
  csv_data: string
}

export interface SymbolSearchResult {
  symbol: string
  brsymbol: string
  name: string
  exchange: string
  token: string
  lotsize: number
  tick_size?: number
}

// 'chartink' is a MaxHook-only pseudo-platform: choosing it in the
// connection creation form routes to the separate Chartink backend
// (blueprints/chartink.py) instead of the generic strategy webhook engine,
// since Chartink's screener-symbol-to-broker-symbol mapping model is not
// compatible with the generic engine's action-to-instrument model. It is
// never written to Strategy.platform in the database — see
// frontend/src/pages/maxhook/NewMaxHookConnection.tsx.
export type Platform =
  | 'tradingview'
  | 'chartink'
  | 'amibroker'
  | 'python'
  | 'rest_api'
  | 'webhook'
  | 'internal_scanner'
  | 'ai_strategy'
  | 'manual'
  | 'metatrader'
  | 'excel'
  | 'others'

export const PLATFORMS: { value: Platform; label: string }[] = [
  { value: 'tradingview', label: 'TradingView' },
  { value: 'chartink', label: 'Chartink' },
  { value: 'amibroker', label: 'Amibroker' },
  { value: 'python', label: 'Python' },
  { value: 'rest_api', label: 'REST API' },
  { value: 'webhook', label: 'Webhook' },
  { value: 'internal_scanner', label: 'Internal Scanner' },
  { value: 'ai_strategy', label: 'AI Strategy' },
  { value: 'manual', label: 'Manual' },
  { value: 'metatrader', label: 'Metatrader' },
  { value: 'excel', label: 'Excel' },
  { value: 'others', label: 'Others' },
]

/** Shared "which provider is this" label lookup — used by MaxHookIndex and
 * ViewMaxHookConnection so both generic Strategy and Chartink connections
 * render a consistent Source label. */
export function getSignalSourceLabel(platform: string): string {
  const found = PLATFORMS.find((p) => p.value === platform)
  return found?.label ?? platform
}

export const EXCHANGES = ['NSE', 'BSE', 'NFO', 'CDS', 'BFO', 'BCD', 'MCX', 'NCDEX', 'NCO'] as const
export type Exchange = (typeof EXCHANGES)[number]

export const EQUITY_EXCHANGES = ['NSE', 'BSE'] as const
export const DERIVATIVE_EXCHANGES = ['NFO', 'CDS', 'BFO', 'BCD', 'MCX', 'NCDEX', 'NCO'] as const

export function getProductTypes(exchange: string): string[] {
  if (EQUITY_EXCHANGES.includes(exchange as (typeof EQUITY_EXCHANGES)[number])) {
    return ['MIS', 'CNC']
  }
  return ['MIS', 'NRML']
}

export const TRADING_MODES = [
  {
    value: 'LONG',
    label: 'LONG Only',
    description: 'Only buy signals (BUY to open, SELL to close)',
  },
  {
    value: 'SHORT',
    label: 'SHORT Only',
    description: 'Only sell signals (SHORT to open, COVER to close)',
  },
  { value: 'BOTH', label: 'BOTH', description: 'Both long and short positions' },
] as const
