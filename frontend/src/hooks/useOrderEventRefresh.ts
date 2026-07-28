import { useEffect, useMemo, useRef, useState } from 'react'
import { io, type Socket } from 'socket.io-client'

/**
 * Supported Socket.IO event types for order-related updates
 */
export type OrderEventType =
  | 'order_event'
  | 'analyzer_update'
  | 'close_position_event'
  | 'cancel_order_event'
  | 'modify_order_event'
  | 'cache_loaded'
  | 'master_risk_triggered'

/**
 * Configuration options for useOrderEventRefresh hook
 */
export interface UseOrderEventRefreshOptions {
  /** Events to listen for (default: ['order_event', 'analyzer_update']) */
  events?: OrderEventType[]
  /** Delay in ms before calling refresh function (default: 500) */
  delay?: number
  /** Whether the hook is enabled (default: true) */
  enabled?: boolean
}

// ---------------------------------------------------------------------------
// Shared Socket.IO connection.
//
// Every consumer of this module shares ONE physical connection (reference
// counted). Previously each hook call opened its own long-polling connection —
// Dashboard alone opened four — and inline `events` array literals caused the
// effect to tear down and reconnect on every render.
// ---------------------------------------------------------------------------
let sharedSocket: Socket | null = null
let refCount = 0

function acquireSocket(): Socket {
  if (!sharedSocket) {
    const { protocol, hostname, port } = window.location
    sharedSocket = io(`${protocol}//${hostname}:${port}`, {
      // Polling only — production runs gunicorn/eventlet where this is the
      // supported transport for the SocketIO server.
      transports: ['polling'],
      upgrade: false,
    })
  }
  refCount++
  return sharedSocket
}

function releaseSocket(): void {
  refCount--
  if (refCount <= 0) {
    refCount = 0
    sharedSocket?.disconnect()
    sharedSocket = null
  }
}

/**
 * Centralized hook for Socket.IO order event listeners.
 *
 * Shares a single Socket.IO connection across all consumers and listens for
 * the specified events, calling the refresh function with an optional delay.
 *
 * @example
 * ```tsx
 * useOrderEventRefresh(fetchPositions);
 * useOrderEventRefresh(fetchPositions, {
 *   events: ['order_event', 'analyzer_update', 'close_position_event'],
 *   delay: 500,
 * });
 * ```
 *
 * @param refreshFn - Function to call when an event is received
 * @param options - Configuration options
 */
export function useOrderEventRefresh(
  refreshFn: () => void,
  options: UseOrderEventRefreshOptions = {}
): void {
  const { events = ['order_event', 'analyzer_update'], delay = 500, enabled = true } = options

  const refreshFnRef = useRef(refreshFn)

  // Keep refresh function reference up to date
  useEffect(() => {
    refreshFnRef.current = refreshFn
  }, [refreshFn])

  // Stable identity for the events list — callers pass inline array literals,
  // which must not cause listener re-registration on every render.
  const eventsKey = events.join(',')

  useEffect(() => {
    if (!enabled) return

    const socket = acquireSocket()
    const eventList = eventsKey.split(',') as OrderEventType[]
    let timer: ReturnType<typeof setTimeout> | undefined

    const handleEvent = () => {
      // Delay slightly to allow server to process the event
      timer = setTimeout(() => refreshFnRef.current(), delay)
    }

    eventList.forEach((event) => {
      socket.on(event, handleEvent)
    })

    return () => {
      if (timer) clearTimeout(timer)
      eventList.forEach((event) => {
        socket.off(event, handleEvent)
      })
      releaseSocket()
    }
  }, [eventsKey, delay, enabled])
}

/**
 * Hook to get direct access to the shared Socket.IO connection for custom
 * event handling.
 *
 * @example
 * ```tsx
 * const { socket, isConnected } = useSocketConnection();
 *
 * useEffect(() => {
 *   if (!socket) return;
 *   socket.on('custom_event', handleCustomEvent);
 *   return () => socket.off('custom_event', handleCustomEvent);
 * }, [socket]);
 * ```
 */
export function useSocketConnection(enabled = true): {
  socket: Socket | null
  isConnected: boolean
} {
  const [socket, setSocket] = useState<Socket | null>(null)
  const [isConnected, setIsConnected] = useState(false)

  useEffect(() => {
    if (!enabled) return

    const s = acquireSocket()
    setSocket(s)
    setIsConnected(s.connected)

    const onConnect = () => setIsConnected(true)
    const onDisconnect = () => setIsConnected(false)
    s.on('connect', onConnect)
    s.on('disconnect', onDisconnect)

    return () => {
      s.off('connect', onConnect)
      s.off('disconnect', onDisconnect)
      setSocket(null)
      releaseSocket()
    }
  }, [enabled])

  return useMemo(() => ({ socket, isConnected }), [socket, isConnected])
}
