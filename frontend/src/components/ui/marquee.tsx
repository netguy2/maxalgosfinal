// components/ui/marquee.tsx
// Generic continuously auto-scrolling row. Extracted from the page-local
// `Marquee` in pages/Home.tsx (which only rendered plain text chips) so it
// can also carry structured content (e.g. dashboard/MarketTicker.tsx's
// live price+change chips). The `@keyframes marquee` this relies on lives
// in index.css (moved there from Home.tsx's inline <style> tag) so both
// consumers share one definition.

import type { ReactNode } from 'react'

interface MarqueeProps {
  /** One item per chip. Rendered twice back-to-back (seamless loop trick)
   * — each item's `key` must be stable and unique within a single pass. */
  items: { key: string; content: ReactNode }[]
  /** Seconds for one full pass of the (single, non-doubled) item list. */
  speed?: number
  /** Pause the animation on hover — useful when chips are interactive. */
  pauseOnHover?: boolean
  className?: string
}

export function Marquee({ items, speed = 35, pauseOnHover = false, className }: MarqueeProps) {
  const doubled = [...items, ...items]
  return (
    <div className={`overflow-hidden w-full relative group ${className ?? ''}`}>
      <div
        className={
          pauseOnHover
            ? 'flex gap-3 w-max group-hover:[animation-play-state:paused]'
            : 'flex gap-3 w-max'
        }
        style={{ animation: `marquee ${speed}s linear infinite` }}
      >
        {doubled.map((item, i) => (
          <div key={`${item.key}-${i < items.length ? 'a' : 'b'}`}>{item.content}</div>
        ))}
      </div>

      {/* fade edges */}
      <div className="pointer-events-none absolute inset-y-0 left-0 w-16 bg-gradient-to-r from-background to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-16 bg-gradient-to-l from-background to-transparent" />
    </div>
  )
}
