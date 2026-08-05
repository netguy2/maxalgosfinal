import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * Width presets. `default` is the app-wide standard -- every page uses it
 * unless it has a concrete reason not to.
 *
 * Why a preset union rather than a free `className`: page width was
 * previously decided ad hoc at ~90 call sites (`max-w-7xl`, bare `container`,
 * `container mx-auto py-6 max-w-7xl px-4 sm:px-6`, nothing at all), so the
 * content column visibly jumped on every route change. Naming the small set
 * of legitimate widths makes the inconsistent ones impossible to express.
 */
type PageWidth = 'default' | 'wide' | 'narrow' | 'full'

const WIDTH_CLASS: Record<PageWidth, string> = {
  /** 1280px -- standard for dashboards, forms, lists. */
  default: 'max-w-7xl',
  /** 1536px -- dense trading tables that genuinely need the extra columns. */
  wide: 'max-w-screen-2xl',
  /** 672px -- single-column reading/settings surfaces (profile, API key). */
  narrow: 'max-w-2xl',
  /** Unbounded -- charts and editors that own the whole viewport. */
  full: 'max-w-none',
}

interface PageContainerProps {
  children: ReactNode
  /** Content width. Defaults to the 1280px app standard. */
  width?: PageWidth
  /**
   * Vertical rhythm between direct children. `default` (24px) suits stacked
   * cards/sections; `tight` (16px) suits toolbar-heavy or compact pages.
   * `none` opts out entirely for pages that manage their own layout (e.g. a
   * flex column that must fill the height, like the Flow editor).
   */
  spacing?: 'default' | 'tight' | 'none'
  className?: string
}

const SPACING_CLASS = {
  default: 'space-y-6',
  tight: 'space-y-4',
  none: '',
} as const

/**
 * The single owner of page width and vertical rhythm.
 *
 * Horizontal padding and the top/bottom page padding live in `Layout`'s
 * <main>, NOT here -- so this element only ever centers and caps. Pages must
 * not re-add `container`, `mx-auto`, `px-*` or `py-*` at their root; doing so
 * is what produced the doubled padding and shifting column widths this
 * component exists to remove.
 */
export function PageContainer({
  children,
  width = 'default',
  spacing = 'default',
  className,
}: PageContainerProps) {
  return (
    <div className={cn('mx-auto w-full', WIDTH_CLASS[width], SPACING_CLASS[spacing], className)}>
      {children}
    </div>
  )
}
