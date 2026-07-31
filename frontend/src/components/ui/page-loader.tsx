/**
 * Full-screen route loader shown while lazy-loaded pages resolve.
 *
 * Replaces the previous bare spinner + "Loading..." with a branded mark:
 * the Max Algos logo held steady inside a rotating gold arc (the brand
 * accent), so a route transition reads as "the app is working" rather than
 * a generic wait state. Motion is disabled under prefers-reduced-motion.
 */
export function PageLoader() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-5">
        <div className="relative h-16 w-16">
          {/* Rotating brand-colored arc */}
          <div
            className="absolute inset-0 rounded-full border-2 border-transparent border-t-brand border-r-brand/40 motion-safe:animate-spin"
            style={{ animationDuration: '900ms' }}
            aria-hidden="true"
          />
          {/* Steady logo in the center */}
          <div className="absolute inset-0 flex items-center justify-center">
            <img
              src="/logo.png"
              alt=""
              className="h-9 w-9 motion-safe:animate-pulse"
              style={{ animationDuration: '2s' }}
            />
          </div>
        </div>
        <p className="text-sm font-medium text-muted-foreground tracking-wide">
          Loading<span className="motion-safe:animate-pulse">…</span>
        </p>
      </div>
    </div>
  )
}
