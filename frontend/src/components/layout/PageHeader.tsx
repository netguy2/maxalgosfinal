import { ArrowLeft } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { cn } from '@/lib/utils'

interface PageHeaderProps {
  title: string
  description?: ReactNode
  /**
   * Icon rendered before the title. Pass the element, not the component, and
   * leave it unsized -- the header sizes it so every page's icon matches
   * (they previously ranged from h-4 to h-6 across pages).
   */
  icon?: ReactNode
  /**
   * Renders a back-arrow link above the title. Several detail/admin pages
   * hand-rolled this row; centralising it keeps the arrow, spacing and hover
   * treatment identical everywhere.
   */
  backTo?: string
  /** Accessible label for the back link. Defaults to "Go back". */
  backLabel?: string
  /** Inline slot after the title (e.g. a Live/Paused status badge). */
  titleAdornment?: ReactNode
  /** Right-aligned slot for page-level actions (buttons, filters). */
  actions?: ReactNode
  className?: string
}

/**
 * The standard page header: optional back link, then title (+ icon and inline
 * adornment) with a description on the left and an actions slot on the right.
 *
 * Every page uses this. Before it was adopted, 78 pages hand-rolled the same
 * row and picked their own title size -- text-xl through text-6xl, with
 * `text-2xl` and `text-xl` both common -- so the heading visibly changed size
 * as you moved between pages. The size lives here now and pages cannot set it.
 */
export function PageHeader({
  title,
  description,
  icon,
  backTo,
  backLabel = 'Go back',
  titleAdornment,
  actions,
  className,
}: PageHeaderProps) {
  return (
    <div className={cn('mb-6 flex flex-col gap-3', className)}>
      {backTo && (
        <Link
          to={backTo}
          aria-label={backLabel}
          className="text-muted-foreground hover:text-foreground -ml-1 inline-flex w-fit items-center gap-1.5 text-sm transition-colors"
        >
          <ArrowLeft className="size-4" />
          Back
        </Link>
      )}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            {/* Fixed icon box so a heading with an icon aligns with one
                without, and every page's icon is the same size. */}
            {icon && (
              <span className="text-muted-foreground shrink-0 [&>svg]:size-5">{icon}</span>
            )}
            <h1 className="text-foreground truncate text-xl font-bold tracking-tight">{title}</h1>
            {titleAdornment}
          </div>
          {description && <p className="text-muted-foreground mt-1 text-sm">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  )
}
