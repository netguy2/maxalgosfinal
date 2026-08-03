// Each symbol carries its own correct exchange -- indices are quoted under
// *_INDEX (NIFTY/BANKNIFTY/FINNIFTY -> NSE_INDEX), never plain NSE (the
// equity/cash segment) or NFO (F&O contracts only, no bare-underlying
// token). Picking a symbol here is now the ONLY way to set exchange, so an
// invalid pair can't be constructed regardless of what the user clicks.
//
// Shared between StrategyConfigurator.tsx (wizard) and
// CustomStrategyBuilder.tsx (no-code condition tree) so both builders'
// symbol pickers stay in sync -- extracted from StrategyConfigurator.tsx
// to avoid drift between the two.
export const SYMBOL_OPTIONS: { value: string; label: string; exchange: string }[] = [
  { value: 'NIFTY', label: 'NIFTY 50', exchange: 'NSE_INDEX' },
  { value: 'BANKNIFTY', label: 'BANKNIFTY', exchange: 'NSE_INDEX' },
  { value: 'FINNIFTY', label: 'FINNIFTY', exchange: 'NSE_INDEX' },
  { value: 'RELIANCE', label: 'RELIANCE', exchange: 'NSE' },
  { value: 'INFY', label: 'INFY', exchange: 'NSE' },
  { value: 'TATASTEEL', label: 'TATASTEEL', exchange: 'NSE' },
  { value: 'HDFCBANK', label: 'HDFCBANK', exchange: 'NSE' },
  // MCX commodities -- kept in sync with useSupportedExchanges.ts's
  // UNDERLYINGS['MCX'] and blueprints/flow.py's get_index_symbols_lot_sizes
  { value: 'GOLD', label: 'GOLD (MCX)', exchange: 'MCX' },
  { value: 'GOLDM', label: 'GOLDM (MCX)', exchange: 'MCX' },
  { value: 'SILVER', label: 'SILVER (MCX)', exchange: 'MCX' },
  { value: 'SILVERM', label: 'SILVERM (MCX)', exchange: 'MCX' },
  { value: 'CRUDEOIL', label: 'CRUDEOIL (MCX)', exchange: 'MCX' },
  { value: 'NATURALGAS', label: 'NATURALGAS (MCX)', exchange: 'MCX' },
  { value: 'COPPER', label: 'COPPER (MCX)', exchange: 'MCX' },
  { value: 'ZINC', label: 'ZINC (MCX)', exchange: 'MCX' },
  { value: 'ALUMINIUM', label: 'ALUMINIUM (MCX)', exchange: 'MCX' },
  { value: 'LEAD', label: 'LEAD (MCX)', exchange: 'MCX' },
  { value: 'NICKEL', label: 'NICKEL (MCX)', exchange: 'MCX' },
]
