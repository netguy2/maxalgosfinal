// api/chart-drawings.ts
// Wrappers around blueprints/chart_drawings.py's session-authenticated
// REST endpoints for manually-placed chart drawings (trendlines,
// horizontal rays, rectangles, fibonacci retracements). Uses webClient
// (frontend/src/api/client.ts) — its request interceptor attaches
// X-CSRFToken automatically on POST/PUT/DELETE, no manual CSRF handling
// needed (same pattern as api/custom-indicators.ts / api/chart-watchlists.ts).

import type { ChartDrawing } from '@/components/charts/chartDrawings'
import { webClient } from './client'

interface ApiEnvelope<T> {
  status: 'success' | 'error'
  message?: string
  data?: T
}

interface DrawingDto {
  id: number
  type: 'trendline' | 'horizontal_ray' | 'rectangle' | 'fibonacci'
  color: string
  pointA?: { time: number; price: number }
  pointB?: { time: number; price: number }
  point?: { time: number; price: number }
}

function dtoToDrawing(dto: DrawingDto): ChartDrawing | null {
  if (
    (dto.type === 'trendline' || dto.type === 'rectangle' || dto.type === 'fibonacci') &&
    dto.pointA &&
    dto.pointB
  ) {
    return {
      id: String(dto.id),
      type: dto.type,
      pointA: dto.pointA,
      pointB: dto.pointB,
      color: dto.color,
    }
  }
  if (dto.type === 'horizontal_ray' && dto.point) {
    return {
      id: String(dto.id),
      type: 'horizontal_ray',
      point: dto.point,
      color: dto.color,
    }
  }
  return null
}

export const chartDrawingsApi = {
  list: async (symbol: string, exchange: string, interval: string): Promise<ChartDrawing[]> => {
    const response = await webClient.get<ApiEnvelope<DrawingDto[]>>('/chart-drawings/api/list', {
      params: { symbol, exchange, interval },
    })
    if (response.data.status !== 'success') return []
    return (response.data.data || []).map(dtoToDrawing).filter((d): d is ChartDrawing => d !== null)
  },

  create: async (
    symbol: string,
    exchange: string,
    interval: string,
    drawing: ChartDrawing
  ): Promise<ChartDrawing | null> => {
    const body =
      drawing.type === 'horizontal_ray'
        ? {
            symbol,
            exchange,
            interval,
            type: 'horizontal_ray',
            color: drawing.color,
            point: drawing.point,
          }
        : {
            symbol,
            exchange,
            interval,
            type: drawing.type,
            color: drawing.color,
            pointA: drawing.pointA,
            pointB: drawing.pointB,
          }
    const response = await webClient.post<ApiEnvelope<DrawingDto>>(
      '/chart-drawings/api/create',
      body
    )
    if (response.data.status !== 'success' || !response.data.data) return null
    return dtoToDrawing(response.data.data)
  },

  remove: async (drawingId: string): Promise<boolean> => {
    const response = await webClient.delete<ApiEnvelope<void>>(`/chart-drawings/api/${drawingId}`)
    return response.data.status === 'success'
  },
}
