import { beforeEach, describe, expect, it, vi } from 'vitest'

// MarketDataManager pulls in a real WebSocket + browser timers; the store
// only needs to know that connect()/disconnect() were called, not that they
// actually do anything.
const connect = vi.fn()
const disconnect = vi.fn()
vi.mock('@/lib/MarketDataManager', () => ({
  MarketDataManager: { getInstance: () => ({ connect, disconnect }) },
}))
vi.mock('./brokerStore', () => ({
  useBrokerStore: { getState: () => ({ capabilities: null }) },
}))

import { useAuthStore } from './authStore'

const LOGGED_IN_USER = {
  username: 'audit',
  broker: 'zerodha',
  isLoggedIn: true,
  loginTime: new Date().toISOString(),
}

describe('authStore setUser / market-data reconnect', () => {
  beforeEach(() => {
    connect.mockClear()
    disconnect.mockClear()
    useAuthStore.setState({
      user: null,
      apiKey: null,
      isAuthenticated: false,
      isAdmin: false,
      brokerSessionValid: false,
    })
  })

  // The bug: after a broker disconnect + re-login in the SAME tab (no page
  // reload), the live WebSocket feed stayed dead while REST calls kept
  // working fine (they re-auth per request). logout() correctly calls
  // MarketDataManager.disconnect(), but nothing then called connect() again
  // -- useMarketData's auto-connect effect only re-runs when the subscribed
  // symbol set changes, not on connectionState, so a page sitting on an
  // unchanged symbol set (e.g. the Dashboard) never reconnected the socket.
  it('reconnects the market-data feed when logging in from a logged-out state', () => {
    useAuthStore.getState().setUser(LOGGED_IN_USER)
    expect(connect).toHaveBeenCalledTimes(1)
  })

  it('does not reconnect on a redundant setUser call while already logged in', () => {
    useAuthStore.getState().setUser(LOGGED_IN_USER)
    connect.mockClear()

    // AuthSync re-syncs on every tab-focus / session-status poll -- most of
    // those calls see the same already-logged-in user and must not force a
    // fresh socket each time.
    useAuthStore.getState().setUser({ ...LOGGED_IN_USER, loginTime: new Date().toISOString() })
    expect(connect).not.toHaveBeenCalled()
  })

  it('reconnects after the full disconnect -> logout -> re-login cycle', () => {
    useAuthStore.getState().setUser(LOGGED_IN_USER)
    connect.mockClear()

    useAuthStore.getState().logout()
    expect(disconnect).toHaveBeenCalledTimes(1)

    useAuthStore.getState().setUser(LOGGED_IN_USER)
    expect(connect).toHaveBeenCalledTimes(1)
  })

  it('does not reconnect when setUser reports a brokerless session (isLoggedIn: false)', () => {
    useAuthStore.getState().setUser({ ...LOGGED_IN_USER, broker: null, isLoggedIn: false })
    expect(connect).not.toHaveBeenCalled()
  })
})
