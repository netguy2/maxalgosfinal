import { Component, type ErrorInfo, type ReactNode } from 'react'
import {
  isChunkLoadError,
  msUntilReloadAllowed,
  tryAutoReloadOnChunkError,
} from '@/utils/chunkReload'
import { reportClientError } from '@/utils/errorReporter'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  message: string
  reloading: boolean
  /** True once the reload has taken long enough that we no longer trust it
   * to complete on its own — shows a manual escape hatch. See #1393
   * follow-up: users reported getting permanently stuck on "Loading new
   * version…" with no way out when the auto-reload silently failed to
   * navigate (browser policy, a legacy service worker serving a stale
   * cached index.html, or the reloaded page hitting the same chunk error
   * again while still inside the cooldown window). */
  reloadStalled: boolean
}

/**
 * Top-level React ErrorBoundary. Catches render-time errors in the tree,
 * reports them to the backend, and shows a minimal fallback so the app
 * doesn't go fully blank. The reporter itself is best-effort.
 *
 * Stale-chunk handling: when CI commits a new frontend/dist build the old
 * hashed JS chunks vanish, so any browser tab that still has the previous
 * index.html cached gets a "Failed to fetch dynamically imported module"
 * (or similar, depending on browser) when the user navigates to a
 * lazy-loaded route. We recognise that class of error and auto-reload
 * once to pick up the fresh index.html — see #1393.
 */
// If the page hasn't actually navigated away this long after we started a
// reload, something is blocking it (a legacy service worker serving a
// stale cached index.html, browser reload policy, etc.) — stop trusting
// the automatic path and show a manual button instead of leaving the user
// on inert text forever.
const RELOAD_STALL_TIMEOUT_MS = 6000

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '', reloading: false, reloadStalled: false }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      message: error.message || 'Something went wrong',
      reloading: false,
      reloadStalled: false,
    }
  }

  private retryTimer: ReturnType<typeof setTimeout> | undefined
  private stallTimer: ReturnType<typeof setTimeout> | undefined

  private armStallTimer(): void {
    if (this.stallTimer) clearTimeout(this.stallTimer)
    this.stallTimer = setTimeout(() => {
      this.setState({ reloadStalled: true })
    }, RELOAD_STALL_TIMEOUT_MS)
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    reportClientError({
      message: error.message || 'Render error',
      stack: error.stack,
      component_stack: info.componentStack || undefined,
    })

    // Auto-recover from stale-bundle navigation failures by reloading once.
    // tryAutoReloadOnChunkError is a no-op if the error isn't chunk-related
    // or if we've reloaded within the cooldown window.
    if (tryAutoReloadOnChunkError(error.message)) {
      this.setState({ reloading: true })
      this.armStallTimer()
      return
    }

    // Chunk error, but an immediate reload was blocked by the cooldown (a
    // reload already happened moments ago). Rather than strand the user on
    // the error card, wait out the remaining cooldown and reload ONCE
    // automatically -- self-healing without a manual click, and still
    // loop-proof because the cooldown gates it.
    if (isChunkLoadError(error.message)) {
      const wait = msUntilReloadAllowed()
      this.setState({ reloading: true })
      this.armStallTimer()
      this.retryTimer = setTimeout(() => {
        window.location.reload()
      }, wait + 250)
    }
  }

  componentWillUnmount(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer)
    if (this.stallTimer) clearTimeout(this.stallTimer)
  }

  handleReload = (): void => {
    window.location.reload()
  }

  handleHardReload = (): void => {
    // A plain reload() may be exactly what's failing to escape a stale
    // cached shell (e.g. a legacy service worker serving cache-first
    // navigations) -- also try clearing this tab's session-scoped reload
    // bookkeeping so a subsequent attempt isn't blocked by the cooldown,
    // then force a cache-bypassing navigation.
    try {
      sessionStorage.removeItem('maxalgos:chunk-reload-ts')
    } catch {
      // sessionStorage unavailable -- fall through to reload anyway.
    }
    window.location.reload()
  }

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children
    if (this.props.fallback) return this.props.fallback

    // Auto-reload in flight (stale-chunk recovery). Show a neutral loading
    // hint instead of an error so the user doesn't see scary text for the
    // ~50ms before the page actually navigates -- but if RELOAD_STALL_TIMEOUT_MS
    // passes and we're still here, the automatic reload didn't work (blocked
    // by browser policy, a stale service worker, or a repeat chunk error
    // still inside the cooldown window) -- surface a manual escape hatch
    // instead of leaving the user on inert text forever (reported
    // repeatedly as "stuck on Loading new version").
    if (this.state.reloading) {
      return (
        <div className="min-h-screen flex items-center justify-center p-6 bg-background">
          <div className="max-w-md w-full text-center space-y-2">
            <h1 className="text-base font-medium">Loading new version…</h1>
            <p className="text-xs text-muted-foreground">A fresh build is available.</p>
            {this.state.reloadStalled && (
              <div className="pt-3 space-y-2">
                <p className="text-xs text-muted-foreground">
                  This is taking longer than expected.
                </p>
                <button
                  type="button"
                  onClick={this.handleHardReload}
                  className="inline-flex items-center justify-center rounded-md text-sm font-medium h-9 px-4 bg-primary text-primary-foreground hover:bg-primary/90"
                >
                  Reload now
                </button>
              </div>
            )}
          </div>
        </div>
      )
    }

    return (
      <div className="min-h-screen flex items-center justify-center p-6 bg-background">
        <div className="max-w-md w-full text-center space-y-4">
          <h1 className="text-xl font-semibold">Something went wrong</h1>
          <p className="text-sm text-muted-foreground break-words">{this.state.message}</p>
          <p className="text-xs text-muted-foreground">
            The error has been logged. You can reload the page or visit{' '}
            <a className="underline" href="/admin/diagnostics">
              Diagnostics
            </a>{' '}
            to view recent errors.
          </p>
          <button
            type="button"
            onClick={this.handleReload}
            className="inline-flex items-center justify-center rounded-md text-sm font-medium h-9 px-4 bg-primary text-primary-foreground hover:bg-primary/90"
          >
            Reload
          </button>
        </div>
      </div>
    )
  }
}
