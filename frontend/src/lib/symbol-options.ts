// SYMBOL_OPTIONS — Comprehensive list of preset symbols across Indian Indices,
// Equities, and MCX Commodities for the Strategy Builders (StrategyConfigurator & CustomStrategyBuilder).

export interface SymbolOption {
  value: string
  label: string
  exchange: string
}

export function getExchangeForSymbol(symbol: string, reportedExchange?: string): string {
  if (reportedExchange) {
    const upper = reportedExchange.toUpperCase()
    if (['NSE_INDEX', 'BSE_INDEX', 'NSE', 'BSE', 'MCX', 'CDS', 'NFO', 'BFO'].includes(upper)) {
      return upper
    }
  }
  const s = symbol.toUpperCase().trim()
  if (['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', 'NIFTY50', 'INDIAVIX'].includes(s)) {
    return 'NSE_INDEX'
  }
  if (['SENSEX', 'BANKEX'].includes(s)) {
    return 'BSE_INDEX'
  }
  const mcxSymbols = [
    'GOLD',
    'GOLDM',
    'SILVER',
    'SILVERM',
    'SILVERMIC',
    'CRUDEOIL',
    'CRUDEOILM',
    'NATURALGAS',
    'NATURALGASMINI',
    'COPPER',
    'ZINC',
    'ZINCMINI',
    'ALUMINIUM',
    'ALUMINI',
    'LEAD',
    'LEADMINI',
    'NICKEL',
    'COTTON',
    'MENTHAOIL',
  ]
  if (mcxSymbols.includes(s)) {
    return 'MCX'
  }
  return 'NSE'
}

export const SYMBOL_OPTIONS: SymbolOption[] = [
  // --- INDICES ---
  { value: 'NIFTY', label: 'NIFTY 50', exchange: 'NSE_INDEX' },
  { value: 'BANKNIFTY', label: 'BANKNIFTY', exchange: 'NSE_INDEX' },
  { value: 'FINNIFTY', label: 'FINNIFTY', exchange: 'NSE_INDEX' },
  { value: 'MIDCPNIFTY', label: 'MIDCPNIFTY', exchange: 'NSE_INDEX' },
  { value: 'NIFTYNXT50', label: 'NIFTY NEXT 50', exchange: 'NSE_INDEX' },
  { value: 'SENSEX', label: 'SENSEX', exchange: 'BSE_INDEX' },
  { value: 'BANKEX', label: 'BSE BANKEX', exchange: 'BSE_INDEX' },
  { value: 'INDIAVIX', label: 'INDIA VIX', exchange: 'NSE_INDEX' },

  // --- MCX COMMODITIES ---
  { value: 'GOLD', label: 'GOLD (MCX)', exchange: 'MCX' },
  { value: 'GOLDM', label: 'GOLD MINI (MCX)', exchange: 'MCX' },
  { value: 'SILVER', label: 'SILVER (MCX)', exchange: 'MCX' },
  { value: 'SILVERM', label: 'SILVER MINI (MCX)', exchange: 'MCX' },
  { value: 'SILVERMIC', label: 'SILVER MIC (MCX)', exchange: 'MCX' },
  { value: 'CRUDEOIL', label: 'CRUDEOIL (MCX)', exchange: 'MCX' },
  { value: 'CRUDEOILM', label: 'CRUDEOIL MINI (MCX)', exchange: 'MCX' },
  { value: 'NATURALGAS', label: 'NATURALGAS (MCX)', exchange: 'MCX' },
  { value: 'NATURALGASMINI', label: 'NATURALGAS MINI (MCX)', exchange: 'MCX' },
  { value: 'COPPER', label: 'COPPER (MCX)', exchange: 'MCX' },
  { value: 'ZINC', label: 'ZINC (MCX)', exchange: 'MCX' },
  { value: 'ZINCMINI', label: 'ZINC MINI (MCX)', exchange: 'MCX' },
  { value: 'ALUMINIUM', label: 'ALUMINIUM (MCX)', exchange: 'MCX' },
  { value: 'ALUMINI', label: 'ALUMINIUM MINI (MCX)', exchange: 'MCX' },
  { value: 'LEAD', label: 'LEAD (MCX)', exchange: 'MCX' },
  { value: 'LEADMINI', label: 'LEAD MINI (MCX)', exchange: 'MCX' },
  { value: 'NICKEL', label: 'NICKEL (MCX)', exchange: 'MCX' },
  { value: 'COTTON', label: 'COTTON (MCX)', exchange: 'MCX' },

  // --- TOP EQUITIES & FnO STOCKS ---
  { value: 'ADANIENT', label: 'ADANI ENTERPRISES', exchange: 'NSE' },
  { value: 'ADANIPORTS', label: 'ADANI PORTS', exchange: 'NSE' },
  { value: 'APOLLOHOSP', label: 'APOLLO HOSPITALS', exchange: 'NSE' },
  { value: 'ASIANPAINT', label: 'ASIAN PAINTS', exchange: 'NSE' },
  { value: 'AXISBANK', label: 'AXIS BANK', exchange: 'NSE' },
  { value: 'BAJAJ-AUTO', label: 'BAJAJ AUTO', exchange: 'NSE' },
  { value: 'BAJFINANCE', label: 'BAJAJ FINANCE', exchange: 'NSE' },
  { value: 'BAJAJFINSV', label: 'BAJAJ FINSERV', exchange: 'NSE' },
  { value: 'BEL', label: 'BHARAT ELECTRONICS', exchange: 'NSE' },
  { value: 'BPCL', label: 'BHARAT PETROLEUM', exchange: 'NSE' },
  { value: 'BHARTIARTL', label: 'BHARTI AIRTEL', exchange: 'NSE' },
  { value: 'BOSCHLTD', label: 'BOSCH', exchange: 'NSE' },
  { value: 'BRITANNIA', label: 'BRITANNIA INDUSTRIES', exchange: 'NSE' },
  { value: 'CANBK', label: 'CANARA BANK', exchange: 'NSE' },
  { value: 'CHOLAFIN', label: 'CHOLAMANDALAM INVESTMENT', exchange: 'NSE' },
  { value: 'CIPLA', label: 'CIPLA', exchange: 'NSE' },
  { value: 'COALINDIA', label: 'COAL INDIA', exchange: 'NSE' },
  { value: 'DIVISLAB', label: 'DIVIS LABORATORIES', exchange: 'NSE' },
  { value: 'DLF', label: 'DLF', exchange: 'NSE' },
  { value: 'DRREDDY', label: 'DR REDDYS LABORATORIES', exchange: 'NSE' },
  { value: 'EICHERMOT', label: 'EICHER MOTORS', exchange: 'NSE' },
  { value: 'GAIL', label: 'GAIL INDIA', exchange: 'NSE' },
  { value: 'GRASIM', label: 'GRASIM INDUSTRIES', exchange: 'NSE' },
  { value: 'HAL', label: 'HINDUSTAN AERONAUTICS', exchange: 'NSE' },
  { value: 'HCLTECH', label: 'HCL TECHNOLOGIES', exchange: 'NSE' },
  { value: 'HDFCBANK', label: 'HDFC BANK', exchange: 'NSE' },
  { value: 'HDFCLIFE', label: 'HDFC LIFE INSURANCE', exchange: 'NSE' },
  { value: 'HEROMOTOCO', label: 'HERO MOTOCORP', exchange: 'NSE' },
  { value: 'HINDALCO', label: 'HINDALCO INDUSTRIES', exchange: 'NSE' },
  { value: 'HINDUNILVR', label: 'HINDUSTAN UNILEVER', exchange: 'NSE' },
  { value: 'ICICIBANK', label: 'ICICI BANK', exchange: 'NSE' },
  { value: 'INDUSINDBK', label: 'INDUSIND BANK', exchange: 'NSE' },
  { value: 'INDUSTOWER', label: 'INDUS TOWERS', exchange: 'NSE' },
  { value: 'INFY', label: 'INFOSYS', exchange: 'NSE' },
  { value: 'IOC', label: 'INDIAN OIL CORP', exchange: 'NSE' },
  { value: 'IRCTC', label: 'IRCTC', exchange: 'NSE' },
  { value: 'ITC', label: 'ITC', exchange: 'NSE' },
  { value: 'JIOFIN', label: 'JIO FINANCIAL SERVICES', exchange: 'NSE' },
  { value: 'JSWSTEEL', label: 'JSW STEEL', exchange: 'NSE' },
  { value: 'KOTAKBANK', label: 'KOTAK MAHINDRA BANK', exchange: 'NSE' },
  { value: 'LT', label: 'LARSEN & TOUBRO', exchange: 'NSE' },
  { value: 'LTIM', label: 'LTIMINDTREE', exchange: 'NSE' },
  { value: 'M&M', label: 'MAHINDRA & MAHINDRA', exchange: 'NSE' },
  { value: 'MARUTI', label: 'MARUTI SUZUKI', exchange: 'NSE' },
  { value: 'NESTLEIND', label: 'NESTLE INDIA', exchange: 'NSE' },
  { value: 'NTPC', label: 'NTPC', exchange: 'NSE' },
  { value: 'ONGC', label: 'OIL & NATURAL GAS CORP', exchange: 'NSE' },
  { value: 'PERSISTENT', label: 'PERSISTENT SYSTEMS', exchange: 'NSE' },
  { value: 'PFC', label: 'POWER FINANCE CORP', exchange: 'NSE' },
  { value: 'POWERGRID', label: 'POWER GRID CORP', exchange: 'NSE' },
  { value: 'RECLTD', label: 'REC LIMITED', exchange: 'NSE' },
  { value: 'RELIANCE', label: 'RELIANCE INDUSTRIES', exchange: 'NSE' },
  { value: 'SBILIFE', label: 'SBI LIFE INSURANCE', exchange: 'NSE' },
  { value: 'SBIN', label: 'STATE BANK OF INDIA', exchange: 'NSE' },
  { value: 'SHRIRAMFIN', label: 'SHRIRAM FINANCE', exchange: 'NSE' },
  { value: 'SIEMENS', label: 'SIEMENS', exchange: 'NSE' },
  { value: 'SUNPHARMA', label: 'SUN PHARMACEUTICALS', exchange: 'NSE' },
  { value: 'TATACONSUM', label: 'TATA CONSUMER PRODUCTS', exchange: 'NSE' },
  { value: 'TATAMOTORS', label: 'TATA MOTORS', exchange: 'NSE' },
  { value: 'TATAPOWER', label: 'TATA POWER', exchange: 'NSE' },
  { value: 'TATASTEEL', label: 'TATA STEEL', exchange: 'NSE' },
  { value: 'TCS', label: 'TATA CONSULTANCY SERVICES', exchange: 'NSE' },
  { value: 'TECHM', label: 'TECH MAHINDRA', exchange: 'NSE' },
  { value: 'TITAN', label: 'TITAN COMPANY', exchange: 'NSE' },
  { value: 'TRENT', label: 'TRENT', exchange: 'NSE' },
  { value: 'TVSMOTOR', label: 'TVS MOTOR COMPANY', exchange: 'NSE' },
  { value: 'ULTRACEMCO', label: 'ULTRATECH CEMENT', exchange: 'NSE' },
  { value: 'UNITDSPR', label: 'UNITED SPIRITS', exchange: 'NSE' },
  { value: 'UPL', label: 'UPL LIMITED', exchange: 'NSE' },
  { value: 'VBL', label: 'VARUN BEVERAGES', exchange: 'NSE' },
  { value: 'VEDL', label: 'VEDANTA', exchange: 'NSE' },
  { value: 'WIPRO', label: 'WIPRO', exchange: 'NSE' },
  { value: 'ZOMATO', label: 'ZOMATO', exchange: 'NSE' },
]
