import { describe, expect, it, vi } from 'vitest'
import { withTimeout } from './Backtest'

describe('withTimeout', () => {
  it('resolves with the underlying value when it settles before the timeout', async () => {
    const result = await withTimeout(Promise.resolve('ok'), 1000, 'test')
    expect(result).toBe('ok')
  })

  it('rejects when the underlying promise never settles before the timeout', async () => {
    vi.useFakeTimers()
    try {
      const neverSettles = new Promise(() => {})
      const race = withTimeout(neverSettles, 5000, 'Loading strategies')
      // Attach a rejection handler before the timer fires so Node doesn't
      // flag this as an unhandled rejection while fake timers are paused.
      const assertion = expect(race).rejects.toThrow(/Loading strategies timed out after 5s/)
      await vi.advanceTimersByTimeAsync(5000)
      await assertion
    } finally {
      vi.useRealTimers()
    }
  })

  it('propagates the underlying rejection reason when the real request fails first', async () => {
    vi.useFakeTimers()
    try {
      const race = withTimeout(Promise.reject(new Error('network down')), 5000, 'test')
      await expect(race).rejects.toThrow('network down')
    } finally {
      vi.useRealTimers()
    }
  })
})
