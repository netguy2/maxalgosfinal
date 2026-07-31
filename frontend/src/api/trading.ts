import type {
  ApiResponse,
  GttOrder,
  Holding,
  MarginData,
  Order,
  OrderStats,
  PlaceOrderRequest,
  PortfolioStats,
  Position,
  Trade,
} from '@/types/trading'
import { apiClient, webClient } from './client'

export interface QuotesData {
  ask: number
  bid: number
  high: number
  low: number
  ltp: number
  oi: number
  open: number
  prev_close: number
  volume: number
}

export interface DepthLevel {
  price: number
  quantity: number
}

export interface DepthData {
  asks: DepthLevel[]
  bids: DepthLevel[]
  high: number
  low: number
  ltp: number
  ltq: number
  oi: number
  open: number
  prev_close: number
  totalbuyqty: number
  totalsellqty: number
  volume: number
}

export interface MultiQuotesSymbol {
  symbol: string
  exchange: string
}

export interface MultiQuotesResult {
  symbol: string
  exchange: string
  data: QuotesData
}

// MultiQuotes API has a different response structure (results at root, not in data)
export interface MultiQuotesApiResponse {
  status: 'success' | 'error'
  results?: MultiQuotesResult[]
  message?: string
}

export interface BasketOrderItem {
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  pricetype: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  product: 'CNC' | 'NRML' | 'MIS'
  price?: number
  trigger_price?: number
  disclosed_quantity?: number
}

export interface BasketOrderResult {
  symbol: string
  status: 'success' | 'error' | 'rejected'
  orderid?: string
  message?: string
  rejection_reason?: string
}

export interface BasketOrderResponse {
  status: 'success' | 'error'
  message?: string
  results?: BasketOrderResult[]
  mode?: 'live' | 'analyze'
}

export interface PlaceGttOrderPayload {
  apikey: string
  strategy: string
  trigger_type: 'SINGLE' | 'OCO'
  exchange: string
  symbol: string
  action: 'BUY' | 'SELL'
  /** GTT only accepts delivery/carry products — MIS is rejected server-side. */
  product: 'CNC' | 'NRML'
  quantity: number
  pricetype: 'LIMIT' | 'MARKET'
  price: number
  triggerprice_sl?: number
  triggerprice_tg?: number
  stoploss?: number | null
  target?: number | null
}

export interface PlaceGttOrderResponse {
  status: 'success' | 'error'
  trigger_id?: string
  message?: string
}

export interface OrderStatusData {
  orderid: string
  symbol: string
  /** Broker's real terminal/non-terminal state: "open" | "complete" | "rejected" (lowercase, broker-dependent casing normalized server-side). */
  order_status: string
  average_price?: number
  [key: string]: unknown
}

export interface OrderStatusResponse {
  status: 'success' | 'error'
  data?: OrderStatusData
  message?: string
}

export const tradingApi = {
  /**
   * Get real-time quotes for a symbol
   */
  getQuotes: async (
    apiKey: string,
    symbol: string,
    exchange: string
  ): Promise<ApiResponse<QuotesData>> => {
    const response = await apiClient.post<ApiResponse<QuotesData>>('/quotes', {
      apikey: apiKey,
      symbol,
      exchange,
    })
    return response.data
  },

  /**
   * Get real-time quotes for multiple symbols
   */
  getMultiQuotes: async (
    apiKey: string,
    symbols: MultiQuotesSymbol[]
  ): Promise<MultiQuotesApiResponse> => {
    const response = await apiClient.post<MultiQuotesApiResponse>('/multiquotes', {
      apikey: apiKey,
      symbols,
    })
    return response.data
  },

  /**
   * Get market depth for a symbol (5-level order book)
   */
  getDepth: async (
    apiKey: string,
    symbol: string,
    exchange: string
  ): Promise<ApiResponse<DepthData>> => {
    const response = await apiClient.post<ApiResponse<DepthData>>('/depth', {
      apikey: apiKey,
      symbol,
      exchange,
    })
    return response.data
  },

  /**
   * Get margin/funds data
   */
  getFunds: async (apiKey: string): Promise<ApiResponse<MarginData>> => {
    const response = await apiClient.post<ApiResponse<MarginData>>('/funds', {
      apikey: apiKey,
    })
    return response.data
  },

  /**
   * Get positions
   */
  getPositions: async (apiKey: string): Promise<ApiResponse<Position[]>> => {
    const response = await apiClient.post<ApiResponse<Position[]>>('/positionbook', {
      apikey: apiKey,
    })
    return response.data
  },

  /**
   * Get order book
   */
  getOrders: async (
    apiKey: string
  ): Promise<ApiResponse<{ orders: Order[]; statistics: OrderStats }>> => {
    const response = await apiClient.post<ApiResponse<{ orders: Order[]; statistics: OrderStats }>>(
      '/orderbook',
      {
        apikey: apiKey,
      }
    )
    return response.data
  },

  /**
   * Get order book merged across every CONNECTED broker (not just the
   * data broker), each order tagged with its own `broker` field. Falls
   * back to the single-broker /orderbook shape otherwise.
   */
  getOrdersMulti: async (
    apiKey: string
  ): Promise<ApiResponse<{ orders: Order[]; statistics: OrderStats }>> => {
    const response = await apiClient.post<ApiResponse<{ orders: Order[]; statistics: OrderStats }>>(
      '/orderbookmulti',
      {
        apikey: apiKey,
      }
    )
    return response.data
  },

  /**
   * Get trade book
   */
  getTrades: async (apiKey: string): Promise<ApiResponse<Trade[]>> => {
    const response = await apiClient.post<ApiResponse<Trade[]>>('/tradebook', {
      apikey: apiKey,
    })
    return response.data
  },

  /**
   * Get holdings
   */
  getHoldings: async (
    apiKey: string
  ): Promise<ApiResponse<{ holdings: Holding[]; statistics: PortfolioStats }>> => {
    const response = await apiClient.post<
      ApiResponse<{ holdings: Holding[]; statistics: PortfolioStats }>
    >('/holdings', {
      apikey: apiKey,
    })
    return response.data
  },

  /**
   * Place order
   */
  placeOrder: async (order: PlaceOrderRequest): Promise<ApiResponse<{ orderid: string }>> => {
    const response = await apiClient.post<ApiResponse<{ orderid: string }>>('/placeorder', order)
    return response.data
  },

  /**
   * Place the same order across multiple connected brokers, one broker at
   * a time (sequential fan-out — see services/multi_broker_order_service.py).
   */
  placeOrderMulti: async (
    order: PlaceOrderRequest,
    brokers: string[]
  ): Promise<{
    status: 'success' | 'error' | 'partial'
    message?: string
    results?: { broker: string; status: 'success' | 'error'; orderid?: string; message?: string }[]
  }> => {
    const response = await apiClient.post('/placeordermulti', { ...order, brokers })
    return response.data
  },

  /**
   * Place a basket of orders in one call. Each item is independent — the
   * backend returns a per-order `results[]` so partial success is possible.
   */
  placeBasketOrder: async (
    apiKey: string,
    strategy: string,
    orders: BasketOrderItem[]
  ): Promise<BasketOrderResponse> => {
    const response = await apiClient.post<BasketOrderResponse>('/basketorder', {
      apikey: apiKey,
      strategy,
      orders,
    })
    return response.data
  },

  /**
   * Place the same basket of orders across multiple connected brokers,
   * one broker at a time (sequential fan-out — see
   * services/multi_broker_order_service.py). Each broker's own
   * results[] is nested under the broker's name in the response.
   */
  placeBasketOrderMulti: async (
    apiKey: string,
    strategy: string,
    orders: BasketOrderItem[],
    brokers: string[]
  ): Promise<{
    status: 'success' | 'error' | 'partial'
    message?: string
    results?: (BasketOrderResult & { broker: string })[]
  }> => {
    const response = await apiClient.post('/basketordermulti', {
      apikey: apiKey,
      strategy,
      orders,
      brokers,
    })
    return response.data
  },

  /**
   * Modify order (uses session auth with CSRF)
   */
  modifyOrder: async (
    orderid: string,
    orderData: {
      symbol: string
      exchange: string
      action: string
      product: string
      pricetype: string
      quantity: number
      price?: number
      trigger_price?: number
      disclosed_quantity?: number
    }
  ): Promise<ApiResponse<{ orderid: string }>> => {
    const response = await webClient.post<ApiResponse<{ orderid: string }>>('/modify_order', {
      orderid,
      ...orderData,
    })
    return response.data
  },

  /**
   * Cancel order (uses session auth with CSRF)
   */
  cancelOrder: async (orderid: string): Promise<ApiResponse<{ orderid: string }>> => {
    const response = await webClient.post<ApiResponse<{ orderid: string }>>('/cancel_order', {
      orderid,
    })
    return response.data
  },

  /**
   * Close a specific position (uses session auth with CSRF)
   */
  closePosition: async (
    symbol: string,
    exchange: string,
    product: string
  ): Promise<ApiResponse<void>> => {
    // Uses the web route which handles session-based auth with CSRF
    const response = await webClient.post<ApiResponse<void>>('/close_position', {
      symbol,
      exchange,
      product,
    })
    return response.data
  },

  /**
   * Close all positions (uses session auth with CSRF)
   */
  closeAllPositions: async (): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>('/close_all_positions', {})
    return response.data
  },

  /**
   * Cancel all orders (uses session auth with CSRF)
   */
  cancelAllOrders: async (): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>('/cancel_all_orders', {})
    return response.data
  },

  /**
   * Get the GTT (Good Till Triggered) order book — active triggers + recent history.
   */
  getGttOrderbook: async (apiKey: string): Promise<ApiResponse<GttOrder[]>> => {
    const response = await apiClient.post<ApiResponse<GttOrder[]>>('/gttorderbook', {
      apikey: apiKey,
    })
    return response.data
  },

  /**
   * Cancel an active GTT trigger (uses session auth with CSRF).
   */
  cancelGttOrder: async (triggerId: string): Promise<ApiResponse<{ trigger_id: string }>> => {
    const response = await webClient.post<ApiResponse<{ trigger_id: string }>>(
      '/cancel_gtt_order',
      { trigger_id: triggerId }
    )
    return response.data
  },

  /**
   * Modify an active GTT trigger (uses session auth with CSRF).
   * Flat replacement body — same shape as PlaceGTTOrder plus trigger_id.
   * last_price is fetched server-side from the broker's quotes endpoint.
   */
  modifyGttOrder: async (
    triggerId: string,
    payload: {
      symbol: string
      exchange: string
      trigger_type: 'SINGLE' | 'OCO'
      action: 'BUY' | 'SELL' | string
      product: string
      quantity: number
      pricetype: string
      price: number
      triggerprice_sl: number
      triggerprice_tg: number
      stoploss?: number | null
      target?: number | null
      strategy?: string
    }
  ): Promise<ApiResponse<{ trigger_id: string }>> => {
    const response = await webClient.post<ApiResponse<{ trigger_id: string }>>(
      '/modify_gtt_order',
      { trigger_id: triggerId, ...payload }
    )
    return response.data
  },

  /**
   * Place a new GTT trigger (Target/SL bracket) — apikey-authenticated,
   * mirrors /placeorder and /basketorder (NOT session/CSRF auth like
   * modify/cancel above). Backend only accepts product CNC/NRML (MIS is
   * rejected) and only Zerodha/Dhan currently ship broker-side GTT support
   * — other brokers return a structured 501, and GTT placement is not
   * available at all in Sandbox mode (also a structured 501). validateStatus
   * lets callers read those bodies instead of the call throwing.
   */
  placeGttOrder: async (payload: PlaceGttOrderPayload): Promise<PlaceGttOrderResponse> => {
    const response = await apiClient.post<PlaceGttOrderResponse>('/placegttorder', payload, {
      validateStatus: () => true,
    })
    return response.data
  },

  /**
   * Poll the broker's real orderbook/tradebook for the true fill status of a
   * placed order. `/basketorder`'s "success" only means the broker ACCEPTED
   * the order for routing (order_id returned) — it does NOT mean the
   * exchange filled it. This is the only source of truth for whether an
   * entry actually executed, and must be checked before treating a position
   * as live or attaching a GTT bracket to it.
   */
  getOrderStatus: async (
    apiKey: string,
    strategy: string,
    orderid: string
  ): Promise<OrderStatusResponse> => {
    const response = await apiClient.post<OrderStatusResponse>('/orderstatus', {
      apikey: apiKey,
      strategy,
      orderid,
    })
    return response.data
  },
}
