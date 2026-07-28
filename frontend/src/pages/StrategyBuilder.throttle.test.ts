import { describe, expect, it } from 'vitest'

/**
 * Regression test for the request-rate floor on the Strategy Builder.
 *
 * Serializing calls (the original queuedFetch) bounds CONCURRENCY but not
 * RATE: a render->fetch loop simply queues calls back-to-back and still
 * saturates the single gunicorn worker. That is what turned an ATM-IV
 * dependency bug into thousands of 429s, a starved healthcheck, and
 * nginx 504s across the whole app.
 *
 * The dependency bug is fixed at its source, but the floor is the
 * defence-in-depth guarantee: any future loop degrades to a survivable
 * rate instead of taking the instance down. This test pins that guarantee
 * against a mirrored implementation of the real helper.
 */

const MIN_CALL_INTERVAL_MS = 120

function makeQueuedFetch() {
  let chain: Promise<unknown> = Promise.resolve()
  let lastCallStartedAt = 0

  return function queuedFetch<T>(fn: () => Promise<T>): Promise<T> {
    const throttled = async (): Promise<T> => {
      const sinceLast = Date.now() - lastCallStartedAt
      if (sinceLast < MIN_CALL_INTERVAL_MS) {
        await new Promise((resolve) => setTimeout(resolve, MIN_CALL_INTERVAL_MS - sinceLast))
      }
      lastCallStartedAt = Date.now()
      return fn()
    }
    const next = chain.then(throttled, throttled)
    chain = next.catch(() => undefined)
    return next
  }
}

describe('StrategyBuilder queuedFetch', () => {
  it('spaces out a burst instead of firing it back-to-back', async () => {
    const queuedFetch = makeQueuedFetch()
    const startedAt: number[] = []

    await Promise.all(
      Array.from({ length: 5 }, () =>
        queuedFetch(async () => {
          startedAt.push(Date.now())
        })
      )
    )

    expect(startedAt).toHaveLength(5)
    // Every consecutive pair must respect the floor. Without it, a runaway
    // loop issues requests as fast as the event loop can turn them over.
    for (let i = 1; i < startedAt.length; i++) {
      const gap = startedAt[i] - startedAt[i - 1]
      // Small tolerance for timer coarseness.
      expect(gap).toBeGreaterThanOrEqual(MIN_CALL_INTERVAL_MS - 20)
    }
  })

  it('still runs calls strictly in order', async () => {
    const queuedFetch = makeQueuedFetch()
    const order: number[] = []

    await Promise.all(
      Array.from({ length: 4 }, (_, i) =>
        queuedFetch(async () => {
          order.push(i)
        })
      )
    )

    expect(order).toEqual([0, 1, 2, 3])
  })

  it('one failure does not break the queue for later callers', async () => {
    const queuedFetch = makeQueuedFetch()

    const failing = queuedFetch(async () => {
      throw new Error('broker down')
    })
    await expect(failing).rejects.toThrow('broker down')

    // The chain must keep working after a rejection -- otherwise a single
    // transient broker error would silently wedge the whole page.
    await expect(queuedFetch(async () => 'ok')).resolves.toBe('ok')
  })

  it('does not delay an isolated call that follows a long idle gap', async () => {
    const queuedFetch = makeQueuedFetch()

    await queuedFetch(async () => 'first')
    await new Promise((resolve) => setTimeout(resolve, MIN_CALL_INTERVAL_MS + 30))

    const startedAt = Date.now()
    await queuedFetch(async () => 'second')

    // Correct, non-looping code should never actually pay the throttle.
    expect(Date.now() - startedAt).toBeLessThan(MIN_CALL_INTERVAL_MS)
  })
})
