import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

interface PageHeaderProps {
  title: string
  description?: string
  /** Inline slot rendered right after the title (e.g. a Live/Paused status
   * badge). Sits on the same row as the title, before the description. */
  titleAdornment?: ReactNode
  /** Right-aligned slot for page-level actions (buttons, filters). */
  actions?: ReactNode
  className?: string
}

/**
 * Standard page header: title (+ optional inline adornment) and description
 * on the left, actions slot on the right. Every page adopts this for a
 * consistent top-of-page rhythm.
 */
export function PageHeader({
  title,
  description,
  titleAdornment,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <div
      className={cn(
        'mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between',
        className
      )}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold tracking-tight text-foreground">{title}</h1>
          {titleAdornment}
        </div>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2 flex-wrap">{actions}</div>}
    </div>
  )
}
