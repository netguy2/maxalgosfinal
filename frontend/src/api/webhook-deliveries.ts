import { webClient } from './client'

/** One stage decision recorded as a signal moved through processing. */
export interface DeliveryStage {
  stage: string
  outcome: string
  detail?: string
  ms?: number
}

/**
 * A single inbound webhook request and everything that happened to it.
 *
 * `outcome` is the current state, not necessarily terminal: a signal is
 * "accepted" when queued and only becomes "processed"/"failed" once the async
 * worker finishes, so a row can legitimately sit in "accepted" briefly.
 */
export interface WebhookDelivery {
  id: number
  webhook_id: string
  source_type: string
  strategy_id: number | null
  strategy_name: string | null
  signal: string | null
  payload: string | null
  remote_ip: string | null
  outcome: 'received' | 'accepted' | 'rejected' | 'processed' | 'failed' | 'duplicate'
  reason_code: string | null
  reason_detail: string | null
  stages: DeliveryStage[]
  order_ids: string[]
  received_at: string | null
  completed_at: string | null
  duration_ms: number | null
}

export interface DeliveryQuery {
  strategyId?: number
  webhookId?: string
  outcome?: string
  limit?: number
  offset?: number
}

export const webhookDeliveryApi = {
  /** Recent deliveries for the session user, newest first. */
  list: async (query: DeliveryQuery = {}): Promise<WebhookDelivery[]> => {
    const params: Record<string, string | number> = {}
    if (query.strategyId != null) params.strategy_id = query.strategyId
    if (query.webhookId) params.webhook_id = query.webhookId
    if (query.outcome) params.outcome = query.outcome
    if (query.limit != null) params.limit = query.limit
    if (query.offset != null) params.offset = query.offset

    const response = await webClient.get<{ deliveries: WebhookDelivery[] }>(
      '/strategy/api/webhook-deliveries',
      { params }
    )
    return response.data.deliveries || []
  },

  /** One delivery with its full stage timeline. */
  get: async (deliveryId: number): Promise<WebhookDelivery> => {
    const response = await webClient.get<{ delivery: WebhookDelivery }>(
      `/strategy/api/webhook-deliveries/${deliveryId}`
    )
    return response.data.delivery
  },
}
