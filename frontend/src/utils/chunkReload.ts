// Detect "the user has a stale frontend bundle open in their browser, and
// CI just rebuilt the dist with new chunk hashes" — the classic SPA failure
// after a deploy. The browser's cached index.html still references
// Historify-OLDHASH.js, but the server only has Historify-NEWHASH.js.
// Lazy import() rejects with a browser-specific error message; we recognise
// any of those and force-reload once to fetch the fresh index.html.
//
// See netguy2/maxalgosfinal#1393 for the bug report.

const CHUNK_ERROR_PATTERNS = [
  // Safari: "Importing a module script failed."
  /Importing a module script failed/i,
  // Chrome / Edge
  /Failed to fetch dynamically imported module/i,
  // Firefox
  /error loading dynamically imported module/i,
  // Webpack legacy / generic
  /ChunkLoadError/i,
  // Vite preload helper
  /Unable to preload CSS for/i,
  /Failed to load resource.*\.(?:js|mjs|css)/i,
]

// Timestamp of the last auto-reload attempt (ms epoch, as a string).
const RELOAD_TS_KEY = 'maxalgos:chunk-reload-ts'
// If another chunk error happens within this window of the last reload, we
// treat it as "the reload didn't fix it" and STOP reloading — surfacing the
// error UI instead of looping. Comfortably longer than a real reload +
// first paint (which is well under a second), short enough that a genuine
// *later* stale-chunk navigation in the same tab can still auto-recover.
const RELOAD_COOLDOWN_MS = 15000

/** True iff the error message looks like a stale-chunk import failure. */
export function isChunkLoadError(message: string | undefined | null): boolean {
  if (!message) return false
  return CHUNK_ERROR_PATTERNS.some((p) => p.test(message))
}

/**
 * Milliseconds until an auto-reload for a chunk error would be permitted
 * again (0 if it's allowed right now). Lets the error UI schedule a
 * self-healing retry once the cooldown elapses, instead of stranding the
 * user on the error card, without any risk of a tight loop.
 */
export function msUntilReloadAllowed(): number {
  try {
    const last = Number(sessionStorage.getItem(RELOAD_TS_KEY) || '0')
    if (!last) return 0
    const remaining = RELOAD_COOLDOWN_MS - (Date.now() - last)
    return remaining > 0 ? remaining : 0
  } catch {
    return 0
  }
}

/**
 * If the error looks like a stale-chunk failure, force-reload the page ONCE
 * to pick up the fresh index.html. Returns true if a reload was triggered
 * (caller should suppress further error UI, since the page is about to
 * navigate).
 *
 * Loop-proof by design: it records the timestamp of each reload and refuses
 * to reload again if the previous one was under RELOAD_COOLDOWN_MS ago. This
 * is deliberately time-based rather than a boolean "already tried" flag —
 * the flag approach broke when the flag got cleared before a lazy route
 * chunk finished loading, letting a repeat error look like a fresh first
 * attempt and reload forever (blank-page loop). A cooldown timestamp cannot
 * be defeated by timing: two chunk errors seconds apart can never both
 * trigger a reload, no matter what else runs in between.
 */
export function tryAutoReloadOnChunkError(message: string | undefined | null): boolean {
  if (!isChunkLoadError(message)) return false

  const now = Date.now()
  try {
    const last = Number(sessionStorage.getItem(RELOAD_TS_KEY) || '0')
    if (last && now - last < RELOAD_COOLDOWN_MS) {
      // We reloaded very recently and it still failed — stop looping and let
      // the error UI render so the user isn't trapped on a blank page.
      return false
    }
    sessionStorage.setItem(RELOAD_TS_KEY, String(now))
  } catch {
    // sessionStorage unavailable (private-browsing edge cases). Without the
    // cooldown record we cannot guarantee loop-safety, so do NOT reload —
    // fall through to the error UI, which offers a manual Reload button.
    return false
  }

  // Plain reload: fetches a fresh index.html from the origin. index.html is
  // served no-store (see blueprints/react_app.py), so the reload always gets
  // the current shell + current chunk hashes; a query-string cache-buster is
  // unnecessary and only risks confusing route matching, so we don't add one.
  window.location.reload()
  return true
}
