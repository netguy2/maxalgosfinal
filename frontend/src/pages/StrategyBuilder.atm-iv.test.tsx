import { renderHook } from '@testing-library/react'
import { useEffect, useMemo, useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

/**
 * Regression test for the /optiongreeks 429 flood.
 *
 * StrategyBuilder merges live WebSocket LTP ticks into `chainData`, calling
 * setChainData() on every tick. The ATM-IV effect used to list `chainData`
 * in its dependency array, so each tick produced a new object identity ->
 * effect refired -> one /optiongreeks request per tick. On a single-worker
 * gunicorn that starved the healthcheck endpoint, so Docker marked the
 * container unhealthy and nginx served 504s for every other route.
 *
 * The fix keys the effect on the ATM CE *symbol* (a string) instead. These
 * tests model both wirings against the same tick stream so the difference
 * is unambiguous, rather than asserting on the real component (which needs
 * a broker session, WS feed and auth store to mount).
 */

interface Strike {
  strike: number
  ce?: { symbol: string; ltp: number }
}
interface ChainData {
  atm_strike: number
  chain: Strike[]
}

function makeChain(atm: number, ltp: number): ChainData {
  return {
    atm_strike: atm,
    // A fresh array + fresh objects, exactly as the WS-merge .map() produces.
    chain: [{ strike: atm, ce: { symbol: `NIFTY${atm}CE`, ltp } }],
  }
}

/** The OLD wiring: effect depends on the whole chainData object. */
function useAtmIvBuggy(fetchIv: (symbol: string) => void) {
  const [chainData, setChainData] = useState<ChainData | null>(null)

  useEffect(() => {
    if (!chainData?.atm_strike) return
    const symbol = chainData.chain.find((s) => s.strike === chainData.atm_strike)?.ce?.symbol
    if (symbol) fetchIv(symbol)
  }, [chainData, fetchIv])

  return { setChainData }
}

/** The FIXED wiring: effect depends on the derived symbol string. */
function useAtmIvFixed(fetchIv: (symbol: string) => void) {
  const [chainData, setChainData] = useState<ChainData | null>(null)

  const atmCeSymbol = useMemo(() => {
    if (!chainData?.atm_strike) return null
    return chainData.chain.find((s) => s.strike === chainData.atm_strike)?.ce?.symbol ?? null
  }, [chainData?.atm_strike, chainData?.chain])

  useEffect(() => {
    if (!atmCeSymbol) return
    fetchIv(atmCeSymbol)
  }, [atmCeSymbol, fetchIv])

  return { setChainData }
}

/** Simulate N live LTP ticks: same ATM strike, same symbol, new price. */
function pushTicks(setChainData: (c: ChainData) => void, rerender: () => void, count: number) {
  for (let i = 0; i < count; i++) {
    setChainData(makeChain(25000, 100 + i))
    rerender()
  }
}

describe('StrategyBuilder ATM-IV effect', () => {
  it('fires one request per WS tick when keyed on chainData (the bug)', () => {
    const fetchIv = vi.fn()
    const { result, rerender } = renderHook(() => useAtmIvBuggy(fetchIv))

    pushTicks(result.current.setChainData, rerender, 20)

    // Every tick refires the effect -> a request each. This is what
    // exhausted the rate limiter and produced the 429 wall.
    expect(fetchIv.mock.calls.length).toBeGreaterThan(10)
  })

  it('fires exactly once across many ticks when keyed on the ATM symbol', () => {
    const fetchIv = vi.fn()
    const { result, rerender } = renderHook(() => useAtmIvFixed(fetchIv))

    pushTicks(result.current.setChainData, rerender, 20)

    // The symbol never changed, so the IV is fetched once no matter how
    // many price updates arrive.
    expect(fetchIv).toHaveBeenCalledTimes(1)
    expect(fetchIv).toHaveBeenCalledWith('NIFTY25000CE')
  })

  it('refetches when the ATM strike actually moves', () => {
    const fetchIv = vi.fn()
    const { result, rerender } = renderHook(() => useAtmIvFixed(fetchIv))

    pushTicks(result.current.setChainData, rerender, 5)
    expect(fetchIv).toHaveBeenCalledTimes(1)

    // Spot moves enough to shift ATM -> new symbol -> IV must refresh.
    result.current.setChainData(makeChain(25100, 120))
    rerender()

    expect(fetchIv).toHaveBeenCalledTimes(2)
    expect(fetchIv).toHaveBeenLastCalledWith('NIFTY25100CE')
  })

  it('does not fetch before the chain has loaded', () => {
    const fetchIv = vi.fn()
    renderHook(() => useAtmIvFixed(fetchIv))
    expect(fetchIv).not.toHaveBeenCalled()
  })
})
